"""Prepare locally, then record an application the user submitted externally."""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApplicationPreparation, Company, Job, Resume, ResumeAssessment
from app.resumes import assess, resume_contains, skills_list, master_resume_id

router = APIRouter(tags=["Application preparation"])
DB = Annotated[Session, Depends(get_db)]


def today():
    # Pilot dates are calendar dates in India, independent of the container timezone.
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VerifiedFact(StrictModel):
    text: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=500)
    confirmed: Literal[True]


class Checklist(StrictModel):
    posting_open: bool = False
    location_eligible: bool = False
    documents_ready: bool = False


class PreparationInput(StrictModel):
    resume_id: str = Field(min_length=1, max_length=64)
    verified_facts: list[VerifiedFact] = Field(default_factory=list, max_length=20)
    checklist: Checklist = Field(default_factory=Checklist)
    draft: str = Field(default="", max_length=20000)
    notes: str = Field(default="", max_length=10000)


class SubmissionInput(StrictModel):
    confirmed_submitted: Literal[True]
    submitted_on: date
    channel: str = Field(min_length=1, max_length=100)
    reference: str = Field(default="", max_length=1000)
    follow_up_on: date | None = None

    @model_validator(mode="after")
    def valid_dates(self):
        if self.submitted_on > today():
            raise ValueError("Submission date cannot be in the future")
        if self.follow_up_on and self.follow_up_on < self.submitted_on:
            raise ValueError("Follow-up cannot precede submission")
        return self


class FollowUpInput(StrictModel):
    follow_up_on: date | None
    done: bool = False


class ReceiptInput(SubmissionInput):
    """Record an already completed external action without inventing readiness checks."""
    resume_id: str = Field(min_length=1, max_length=64)
    reference: str = Field(min_length=1, max_length=1000)
    notes: str = Field(default="", max_length=10000)


def get_job(db, job_id, lock=False):
    statement = select(Job).where(Job.job_id == job_id)
    job = db.scalar(statement.with_for_update() if lock else statement)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def readiness(db, job, preparation):
    blockers = []
    from app.discovery.service import get_profile
    from app.discovery.matching import target_role_matches
    roles = get_profile(db).target_roles
    if roles and not target_role_matches(job.role, roles) and not (preparation and preparation.submitted_on):
        blockers.append("Job is outside the current target designations")
    if not (preparation and preparation.submitted_on):
        from app.phase9 import eligibility
        result = eligibility(db, job)
        if result['status'] != 'eligible':
            blockers.append('Eligibility ' + result['status'].replace('_', ' ') + ': ' + '; '.join(
                c['message'] for c in result['checks'] if c['state'] != 'pass'))
    score = None
    from app.tailoring import approved_proposal
    approved, approval_blocker = approved_proposal(db, job)
    if not (preparation and preparation.submitted_on):
        if approval_blocker:
            blockers.append(approval_blocker)
        elif preparation and approved.master_id != preparation.resume_id:
            blockers.append("Preparation must use the approved proposal's master resume")
    if preparation:
        if master_resume_id() and preparation.resume_id != master_resume_id() and not preparation.submitted_on:
            blockers.append("Update preparation to the configured master résumé")
        resume = db.get(Resume, preparation.resume_id)
        requirements = skills_list(job.required_skills)
        if resume and requirements:
            score = 100 * sum(resume_contains(approved.content if approved else resume.text, s) for s in requirements) / len(requirements)
        for key, label in (("posting_open", "Confirm the posting is still open"),
                           ("location_eligible", "Confirm location/work eligibility"),
                           ("documents_ready", "Have the selected résumé and required documents ready")):
            if not preparation.checklist.get(key):
                blockers.append(label)
        if preparation.submitted_on:
            blockers.append("Application already recorded")
    else:
        blockers.append("Save a preparation with an imported résumé")
    if job.status != "Approved":
        blockers.append("Job must have Approved status")
    if not job.human_approval and (score is None or score < 80):
        blockers.append("Selected résumé coverage is below 80% or unknown: manual approval required")
    return {"ready": not blockers, "blockers": blockers, "selected_resume_match_percent": score,
            "approval_method": "manual" if job.human_approval else "automatic" if score is not None and score >= 80 else "pending"}


def response(db, job, preparation):
    fields = None if preparation is None else {column.name: getattr(preparation, column.name)
                                               for column in ApplicationPreparation.__table__.columns}
    return {"job_id": job.job_id, "preparation": fields, **readiness(db, job, preparation)}


@router.get("/jobs/{job_id}/preparation")
def get_preparation(job_id: str, db: DB):
    return response(db, get_job(db, job_id), db.get(ApplicationPreparation, job_id))


@router.put("/jobs/{job_id}/preparation")
def save_preparation(job_id: str, payload: PreparationInput, db: DB):
    if master_resume_id() and payload.resume_id != master_resume_id():
        raise HTTPException(422, "Choose the configured master résumé for new preparations")
    job = get_job(db, job_id, lock=True)
    preparation = db.get(ApplicationPreparation, job_id)
    if preparation and preparation.submitted_on:
        raise HTTPException(409, "Submitted preparation is frozen; update follow-up or job status instead")
    resume = db.get(Resume, payload.resume_id)
    if resume is None:
        raise HTTPException(422, "Import this résumé first")
    if preparation is None:
        preparation = ApplicationPreparation(job_id=job_id)
        db.add(preparation)
    for key, value in payload.model_dump().items():
        setattr(preparation, key, value)
    # Re-evaluate the exact chosen version; never reuse another résumé's high score.
    if job.status in ("New", "Shortlisted", "Approved"):
        result = assess(db, job, resume.id)
        db.add(ResumeAssessment(job_id=job_id, result=result))
        job.resume_version = resume.filename + "#" + resume.id[:12]
    db.commit()
    return response(db, job, preparation)


@router.post("/jobs/{job_id}/preparation/draft")
def draft(job_id: str, db: DB):
    job = get_job(db, job_id)
    preparation = db.get(ApplicationPreparation, job_id)
    if preparation is None or not preparation.verified_facts:
        raise HTTPException(422, "Save at least one confirmed fact with its evidence first")
    company = db.get(Company, job.company_id)
    facts = "\n".join("- " + fact["text"] for fact in preparation.verified_facts)
    return {"draft": f"Dear Hiring Team,\n\nI am interested in the {job.role} position at {company.name}.\n\nRelevant facts about my background:\n{facts}\n\nThank you for considering my application.",
            "note": "Local template using your confirmed facts. Edit and save before using externally. Nothing was sent."}


@router.post("/jobs/{job_id}/application", status_code=201)
def record_submission(job_id: str, payload: SubmissionInput, db: DB):
    job = get_job(db, job_id, lock=True)
    preparation = db.get(ApplicationPreparation, job_id)
    state = readiness(db, job, preparation)
    if not state["ready"]:
        raise HTTPException(409, state["blockers"])
    from app.tailoring import approved_proposal
    approved, _ = approved_proposal(db, job)
    # Freeze what was selected and approved at submission, even after later job edits.
    from app.phase9 import eligibility, answers
    preparation.submission_snapshot = {
        "eligibility": eligibility(db, job),
        "confirmed_application_answers": answers(db),
        "resume_proposal_id": approved.id,
        "approved_content_sha256": approved.content_sha256,
        "pdf_sha256": approved.pdf_sha256, "docx_sha256": approved.docx_sha256,
        "resume_reviewed_at": approved.reviewed_at.isoformat(),
        "resume_reviewed_by": approved.reviewed_by,
        "resume_id": preparation.resume_id, "resume_filename": db.get(Resume, preparation.resume_id).filename,
        "required_skills": job.required_skills, "source_url": job.source_url,
        "human_approval": job.human_approval, **state,
        "verified_facts": preparation.verified_facts, "checklist": preparation.checklist,
        "draft": preparation.draft, "notes": preparation.notes,
    }
    preparation.submitted_on = payload.submitted_on
    preparation.channel = payload.channel
    preparation.reference = payload.reference
    preparation.follow_up_on = payload.follow_up_on
    preparation.follow_up_done = False
    job.status = "Applied"
    job.resume_version = "proposal:" + approved.id + ":" + approved.content_sha256[:12]
    db.commit()
    return response(db, job, preparation)


@router.get("/applications")
def applications(db: DB, due_only: bool = False, limit: int = Query(50, ge=1, le=200),
                 offset: int = Query(0, ge=0)):
    statement = (select(ApplicationPreparation, Job, Company).select_from(ApplicationPreparation)
                 .join(Job, ApplicationPreparation.job_id == Job.job_id)
                 .join(Company, Job.company_id == Company.id))
    statement = statement.where(ApplicationPreparation.submitted_on.is_not(None))
    if due_only:
        statement = statement.where(ApplicationPreparation.follow_up_on <= today(),
                                    ApplicationPreparation.follow_up_done.is_(False),
                                    Job.status.in_(["Applied", "Interview"]))
    rows = db.execute(statement.order_by(ApplicationPreparation.submitted_on.desc(), Job.job_id).limit(limit).offset(offset))
    return [{"job_id": job.job_id, "company": company.name, "role": job.role, "status": job.status,
             "submitted_on": prep.submitted_on, "channel": prep.channel,
             "follow_up_on": prep.follow_up_on, "follow_up_done": prep.follow_up_done,
             "due": bool(prep.follow_up_on and prep.follow_up_on <= today() and not prep.follow_up_done
                         and job.status in ("Applied", "Interview"))} for prep, job, company in rows]


@router.post("/jobs/{job_id}/application-receipt", status_code=201)
def record_external_receipt(job_id: str, payload: ReceiptInput, db: DB):
    """Historical recording only; this endpoint never sends an application."""
    job = get_job(db, job_id, lock=True)
    prep = db.get(ApplicationPreparation, job_id)
    if prep and prep.submitted_on:
        raise HTTPException(409, "Application already recorded")
    resume = db.get(Resume, payload.resume_id)
    if resume is None:
        raise HTTPException(422, "Import the submitted résumé first")
    if prep is None:
        prep = ApplicationPreparation(job_id=job_id, verified_facts=[], checklist={}, draft="")
        db.add(prep)
    prep.resume_id = resume.id
    prep.submission_snapshot = {
        "recording_method": "external_receipt", "confirmed_submitted": True,
        "reference": payload.reference, "source_url": job.source_url,
        "resume_id": resume.id, "resume_filename": resume.filename,
        "previous_status": job.status, "human_approval": job.human_approval,
        "note": "Receipt records an external submission; it does not assert eligibility or automatic approval.",
    }
    prep.submitted_on = payload.submitted_on
    prep.channel = payload.channel
    prep.reference = payload.reference
    prep.notes = payload.notes
    prep.follow_up_on = payload.follow_up_on
    prep.follow_up_done = False
    job.status = "Applied"
    job.resume_version = resume.filename + "#" + resume.id[:12]
    db.commit()
    return response(db, job, prep)


@router.patch("/jobs/{job_id}/follow-up")
def follow_up(job_id: str, payload: FollowUpInput, db: DB):
    job = get_job(db, job_id, lock=True)
    preparation = db.get(ApplicationPreparation, job_id)
    if preparation is None or preparation.submitted_on is None:
        raise HTTPException(409, "Record an application first")
    if payload.follow_up_on and payload.follow_up_on < preparation.submitted_on:
        raise HTTPException(422, "Follow-up cannot precede submission")
    preparation.follow_up_on = payload.follow_up_on
    preparation.follow_up_done = payload.done
    db.commit()
    return response(db, job, preparation)
