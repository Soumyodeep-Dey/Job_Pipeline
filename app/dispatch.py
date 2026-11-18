"""Automatic applications use one durable attempt per job and hosted posting."""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications import readiness
from app.database import get_db
from app.dispatch_policy import budget
from app.models import (ApplicantProfile, ApplicationPreparation, DispatchControl, DispatchAttempt,
                        JobEvidence)
from app.tailoring import approved_proposal

router = APIRouter(tags=["Automatic applications"])
DB = Annotated[Session, Depends(get_db)]

def now():
    return datetime.now(timezone.utc)

def destination(job, evidence):
    """Match the provider and tenant in discovery evidence before sharing a PDF."""
    if not evidence or not job.source_url:
        return None
    url = urlsplit(job.source_url)
    board = urlsplit(evidence.board_url)
    hosts = {
        "ashby": ("jobs.ashbyhq.com",),
        "lever": ("jobs.lever.co",),
        "lever-eu": ("jobs.eu.lever.co",),
        "greenhouse": ("job-boards.greenhouse.io", "boards.greenhouse.io"),
        "greenhouse-eu": ("job-boards.eu.greenhouse.io", "boards.eu.greenhouse.io"),
    }
    allowed = hosts.get(evidence.provider, ())
    if url.scheme != "https" or url.netloc not in allowed or board.netloc not in allowed:
        return None
    tenant = board.path.strip("/")
    if not re.fullmatch(r"[\w-]+", tenant):
        return None
    greenhouse = evidence.provider.startswith("greenhouse")
    pattern = r"/jobs/[0-9]+" if greenhouse else r"/[0-9a-fA-F-]{36}"
    if not re.fullmatch("/" + re.escape(tenant) + pattern, url.path.rstrip("/")):
        return None
    return f"https://{url.netloc}{url.path.rstrip('/')}"

def packet(db, job):
    prep = db.get(ApplicationPreparation, job.job_id)
    state = readiness(db, job, prep)
    url = destination(job, db.get(JobEvidence, job.job_id))
    reasons = list(state["blockers"])
    if not url:
        reasons.append("This source requires an assisted application.")
    profile = db.get(ApplicantProfile, 1)
    facts = profile.data if profile else {}
    if not facts.get("full_name") or not facts.get("email"):
        reasons.append("Confirm your name and email in Applicant profile.")
    proposal, _ = approved_proposal(db, job)
    snapshot = None
    if not reasons:
        snapshot = {"proposal_id":proposal.id, "master_id":proposal.master_id,
                    "pdf_sha256":proposal.pdf_sha256, "profile_version":profile.version,
                    "url":url, "role":job.role, "company_id":job.company_id,
                    "location":job.location, "eligibility":state, "requirements":job.required_skills}
    return reasons, snapshot

class Switch(BaseModel):
    enabled: StrictBool

@router.get("/dispatch")
def status(db: DB):
    settings = db.get(DispatchControl, 1)
    rows = db.scalars(select(DispatchAttempt).order_by(DispatchAttempt.updated_at.desc()).limit(100))
    return {"enabled":bool(settings and settings.enabled), "schedule":budget(db, now()), "attempts":[
        {"job_id":r.job_id, "role":r.snapshot.get("role"), "state":r.state, "message":r.message,
         "updated_at":r.updated_at, "url":r.destination} for r in rows]}

@router.put("/dispatch")
def switch(payload: Switch, db: DB):
    row = db.get(DispatchControl, 1, with_for_update=True)
    if not row:
        row = DispatchControl(id=1)
        db.add(row)
    row.enabled = payload.enabled
    db.commit()
    return status(db)

@router.get("/jobs/{job_id}/dispatch")
def preview(job_id: str, db: DB):
    from app.applications import get_job
    job = get_job(db, job_id)
    blockers, selected = packet(db, job)
    attempt = db.get(DispatchAttempt, job_id)
    return {"blockers":blockers, "packet":selected, "attempt":attempt.state if attempt else None,
            "message":attempt.message if attempt else None}

@router.post("/jobs/{job_id}/dispatch/recheck")
def recheck(job_id: str, db: DB):
    row = db.get(DispatchAttempt, job_id, with_for_update=True)
    if not row or row.state != "needs_review" or row.submission_started_at is not None:
        raise HTTPException(409, "Only a verified pre-submit stop can be rechecked.")
    db.delete(row)
    db.commit()
    return {"message":"The worker will check current requirements again."}
