from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.discovery.schemas import CandidateProfile, DiscoveryRequest
from app.discovery.service import get_profile, run_discovery
from app.models import DiscoveryRun, JobEvidence, MatchingProfile

router = APIRouter(tags=["Phase 2 discovery"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/matching-profile", response_model=CandidateProfile)
def read_profile(db: DB):
    return get_profile(db)


@router.put("/matching-profile", response_model=CandidateProfile)
def replace_profile(payload: CandidateProfile, db: DB):
    profile = db.get(MatchingProfile, 1)
    if profile is None:
        db.add(MatchingProfile(id=1, settings=payload.model_dump()))
    else:
        profile.settings = payload.model_dump()
    db.commit()
    return payload


def run_response(run):
    return {"id": run.id, "status": run.status, "started_at": run.started_at,
            "finished_at": run.finished_at, "profile_snapshot": run.profile_snapshot, "results": run.results}


@router.post("/discovery/runs", status_code=201)
def discover(payload: DiscoveryRequest, db: DB):
    """Synchronous, bounded pilot: explicitly select 1–5 imported companies."""
    try:
        return run_response(run_discovery(db, payload))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/discovery/runs")
def list_runs(db: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return [run_response(run) for run in db.scalars(select(DiscoveryRun)
            .order_by(DiscoveryRun.started_at.desc()).offset(offset).limit(limit))]


@router.get("/discovery/runs/{run_id}")
def read_run(run_id: str, db: DB):
    run = db.get(DiscoveryRun, run_id)
    if run is None:
        raise HTTPException(404, "Discovery run not found")
    return run_response(run)


@router.get("/jobs/{job_id}/discovery")
def read_evidence(job_id: str, db: DB):
    evidence = db.get(JobEvidence, job_id)
    if evidence is None:
        raise HTTPException(404, "No discovery evidence; job is absent or was entered manually/imported")
    return {"job_id": evidence.job_id, "run_id": evidence.run_id, "provider": evidence.provider,
            "career_page": evidence.career_page, "board_url": evidence.board_url,
            "description": evidence.description, "explanation": evidence.explanation}
