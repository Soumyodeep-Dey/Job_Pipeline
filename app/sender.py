"""Dedicated Docker worker. A lost acknowledgement is never retried."""
import logging
import json
import signal
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.applications import readiness
from app.database import SessionLocal, engine
from app.dispatch_policy import budget, reserve_slot
from app.form_questions import QuestionsNeeded, known_answers, questions_resolved, remember_questions
from app.dispatch import destination, now, packet
from app.discovery.location import india_opportunity
from app.discovery.matching import target_role_matches
from app.discovery.service import get_profile
from app.discovery.sources import Fetcher, board_from_url, normalize_job
from app.hosted_forms import ReviewNeeded, submit_hosted
from app.models import (ApplicantProfile, ApplicationPreparation, DispatchAttempt,
                        DispatchControl, Job, JobEvidence)
from app.phase9 import eligibility
from app.tailoring import approved_proposal, create_proposal, latest, ProposalInput, stale_reason

STOP = Event()
log = logging.getLogger(__name__)


class ScheduleClosed(ReviewNeeded):
    def __init__(self):
        super().__init__("Waiting for the next available daily slot after 9 AM India time.")

def enabled(db):
    settings = db.get(DispatchControl, 1)
    return bool(settings and settings.enabled)

def current_posting(job, evidence):
    board = board_from_url(evidence.board_url)
    identifier = destination(job, evidence).split("/")[-1]
    if board.provider == "ashby":
        host = "api.ashbyhq.com"
        path = f"/posting-api/job-board/{board.token}"
    elif board.provider.startswith("lever"):
        host = "api.eu.lever.co" if board.provider.endswith("-eu") else "api.lever.co"
        path = f"/v0/postings/{board.token}/{identifier}?mode=json"
    else:
        host = "boards-api.eu.greenhouse.io" if board.provider.endswith("-eu") else "boards-api.greenhouse.io"
        path = f"/v1/boards/{board.token}/jobs/{identifier}"
    fetch = Fetcher()
    try:
        _, body = fetch.get("https://" + host + path,{host},public_api=True)
        data = json.loads(body)
        rows = data["jobs"] if board.provider == "ashby" else [data]
        for raw in rows:
            if raw.get("isListed", True) is False:
                continue
            item = normalize_job(raw,board)
            if item["external_id"] != identifier:
                continue
            if (item["title"] == job.role and item["location"] == job.location
                    and item["description"] == evidence.description and item["url"] == job.source_url):
                return
            break
        raise ReviewNeeded("Live posting changed or closed. Review current employer requirements.")
    finally:
        fetch.close()

def consider(db, job):
    """Make proposals for relevant jobs. A human approves the exact resulting PDF."""
    if not enabled(db) or not budget(db, now())["can_send"] or not india_opportunity(job):
        return None
    roles = get_profile(db).target_roles
    if not roles or not target_role_matches(job.role,roles):
        return None
    prep = db.get(ApplicationPreparation,job.job_id)
    if prep and prep.submitted_on:
        return None
    ev = db.get(JobEvidence,job.job_id)
    if not ev:
        return None
    proposal = latest(db,job.job_id)
    if proposal is None or (proposal.status in ("pending","approved") and stale_reason(db,job,proposal)):
        from app.resumes import master_resume_id
        if master_resume_id(db):
            create_proposal(job.job_id,ProposalInput(),db)
        return None
    approved, _ = approved_proposal(db,job)
    if job.status != "Approved" or not approved:
        return None
    url = destination(job,ev)
    if not url:
        return None
    previous = db.get(DispatchAttempt, job.job_id)
    if previous:
        if previous.state in {"waiting_answers", "scheduled"} and previous.submission_started_at is None:
            if previous.state == "waiting_answers" and not questions_resolved(db, job.job_id):
                return None
            previous.state = "checking"
            previous.updated_at = now()
            db.commit()
            return job.job_id
        return None
    profile = db.get(ApplicantProfile,1)
    if not profile or not all(profile.data.get(k) for k in ("full_name","email")):
        return None
    if eligibility(db,job)["status"] != "eligible":
        return None
    if prep and not readiness(db,job,prep)["ready"]:
        return None
    attempt = DispatchAttempt(job_id=job.job_id,destination=url,state="checking",
        message="Checking the live employer posting.",snapshot={"role":job.role},updated_at=now())
    db.add(attempt)
    db.commit()
    return job.job_id

def process(db, job_id, adapter=submit_hosted, verify=current_posting):
    attempt = db.get(DispatchAttempt,job_id)
    if not attempt or attempt.state != "checking":
        return
    try:
        job = db.get(Job,job_id)
        ev = db.get(JobEvidence,job_id)
        if not enabled(db) or destination(job,ev) != attempt.destination:
            raise ReviewNeeded("Automation paused or posting changed.")
        verify(job,ev)
        approved, reason = approved_proposal(db,job)
        if not approved:
            raise ReviewNeeded(reason)
        prep = db.get(ApplicationPreparation,job_id)
        if prep is None:
            prep = ApplicationPreparation(job_id=job_id,resume_id=approved.master_id,
                checklist={"posting_open":True,"location_eligible":eligibility(db,job)["status"]=="eligible",
                           "documents_ready":bool(approved.pdf)}, verified_facts=[],notes="",draft="")
            db.add(prep)
            db.flush()
        blockers, selected = packet(db,job)
        if blockers:
            raise ReviewNeeded(" ".join(blockers))
        facts = dict(db.get(ApplicantProfile,1).data)
        answers = known_answers(db, job_id)
        facts["_form_answers"] = answers
        facts["_used_form_answers"] = []
        pdf = bytes(approved.pdf)
        attempt.snapshot = {**selected,"confirmed_answers_available":{k:v for k,v in facts.items() if not k.startswith("_")}}
        db.commit()

        def before_submit():
            db.expire_all()
            job = db.get(Job,job_id,with_for_update=True)
            blockers, current = packet(db,job)
            roles = get_profile(db).target_roles
            matches = roles and target_role_matches(job.role,roles) and india_opportunity(job)
            if blockers or current != selected or not matches or not enabled(db) or attempt.state != "checking":
                raise ReviewNeeded("Approval, profile, posting or automation settings changed.")
            if known_answers(db, job_id) != answers:
                raise ReviewNeeded("Saved answers changed. Recheck the form before sending.")
            # Serialize daily reservations across senders and commit before the click.
            if not reserve_slot(db, attempt, now()):
                raise ScheduleClosed()
            # Durable boundary before any submit click. A crash now requires reconciliation.
            attempt.snapshot = {**attempt.snapshot, "form_answers": facts["_used_form_answers"]}
            attempt.state = "sending"
            attempt.message = "Submission started. Check for a receipt before any further action."
            attempt.updated_at = now()
            db.commit()

        receipt = adapter(selected,facts,pdf,before_submit)
        if attempt.state != "sending" or not receipt:
            raise RuntimeError("Missing submission confirmation")
        attempt.state = "received"
        attempt.message = receipt
        attempt.updated_at = now()
        db.commit()
    except Exception as exc:
        db.rollback()
        attempt = db.get(DispatchAttempt,job_id)
        ambiguous = attempt.submission_started_at is not None
        attempt.state = "uncertain" if ambiguous else "needs_review"
        if not ambiguous and isinstance(exc, QuestionsNeeded):
            remember_questions(db, job_id, exc.questions)
            attempt.state = "waiting_answers"
        if not ambiguous and isinstance(exc, ScheduleClosed):
            attempt.state = "scheduled"
        attempt.message = ("Check the employer receipt. Automatic retries are disabled." if ambiguous else
            str(exc)[:450] if isinstance(exc,ReviewNeeded) else
            "Employer form or posting could not be verified. Inspect it before rechecking.")
        attempt.updated_at = now()
        db.commit()
        return
    reconcile(db,attempt)

def reconcile(db,attempt):
    """Recover a saved receipt independently of later profile or approval changes."""
    job = db.get(Job,attempt.job_id,with_for_update=True)
    prep = db.get(ApplicationPreparation,attempt.job_id)
    if not prep.submitted_on:
        prep.submitted_on = attempt.updated_at.astimezone(ZoneInfo('Asia/Kolkata')).date()
        prep.channel = "Automated employer form"
        prep.reference = attempt.message
        prep.submission_snapshot = {**attempt.snapshot,"receipt":attempt.message,
                                    "received_at":attempt.updated_at.isoformat()}
        prep.resume_id = attempt.snapshot["master_id"]
        job.status = "Applied"
        job.resume_version = "proposal:" + attempt.snapshot["proposal_id"]
    attempt.state = "confirmed"
    db.commit()

def recover(db):
    for item in db.scalars(select(DispatchAttempt).where(DispatchAttempt.state.in_(
            ["checking","sending","received"]))):
        if item.state == "received":
            reconcile(db,item)
        else:
            item.state = "uncertain" if item.state == "sending" else "needs_review"
            item.message = "Worker interrupted. Review the attempt history."
            item.updated_at = now()
    db.commit()

def tick():
    with SessionLocal() as db:
        if not enabled(db) or not budget(db, now())["can_send"]:
            return
        ids = list(db.scalars(select(Job.job_id).where(Job.status.in_(
            ["Approved","Shortlisted","New"])).order_by(Job.date_found.desc(),Job.job_id)))
    for identifier in ids:
        if STOP.is_set():
            break
        Path("/tmp/sender-heartbeat").touch()
        with SessionLocal() as db:
            try:
                job = db.get(Job,identifier,with_for_update=True)
                if consider(db,job):
                    process(db,identifier)
            except IntegrityError:
                db.rollback()  # Another attempt owns this job or its canonical destination.
            except Exception:
                db.rollback()
                log.exception("Submission preparation failed for %s",identifier)

def main():
    signal.signal(signal.SIGTERM,lambda *_: STOP.set())
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(741906)")):
            raise RuntimeError("Another submission worker is active")
        lock.commit()
        with SessionLocal() as db:
            recover(db)
        while not STOP.is_set():
            lock.execute(text("SELECT 1"))
            lock.commit()
            Path("/tmp/sender-heartbeat").touch()
            tick()
            STOP.wait(30)

if __name__ == "__main__":
    main()
