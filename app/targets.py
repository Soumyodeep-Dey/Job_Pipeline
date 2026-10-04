"""Change job preferences without changing evidence about the applicant."""
from datetime import timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.background import now
from app.database import get_db
from app.discovery.schemas import CandidateProfile
from app.discovery.service import get_profile
from app.models import BackgroundTask, Company, DiscoverySchedule, MatchingProfile

router = APIRouter(tags=["Target role automation"])
DB = Annotated[Session, Depends(get_db)]
PREFIX = "Target roles: batch "


class Targets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_roles: list[str] = Field(min_length=1, max_length=20)
    india_work_preference: Literal["unconfirmed", "remote_only", "relocation_office_hybrid"]


@router.get("/target-settings")
def read_targets(db: DB):
    profile = get_profile(db)
    schedules = db.scalars(select(DiscoverySchedule).where(DiscoverySchedule.name.startswith(PREFIX))).all()
    return {"target_roles": profile.target_roles, "india_work_preference": profile.india_work_preference,
            "enabled_batches": sum(s.enabled for s in schedules), "total_batches": len(schedules),
            "submission_mode": "manual", "presets": ["AI Engineer", "Data Engineer"]}


@router.put("/target-settings")
def save_targets(payload: Targets, db: DB):
    # Serialize settings updates with managed schedule changes. Preserve all skills.
    stored = db.scalar(select(MatchingProfile).where(MatchingProfile.id == 1).with_for_update())
    values = get_profile(db).model_dump()
    values.update(payload.model_dump())
    try:
        profile = CandidateProfile(**values)
    except ValueError as exc:
        raise HTTPException(422, "Use nonblank target designations of at most 100 characters") from exc
    if stored:
        stored.settings = profile.model_dump()
    else:
        db.add(MatchingProfile(id=1, settings=profile.model_dump()))
    db.commit()
    return read_targets(db)


class AutomationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.put("/target-settings/automation")
def configure_automation(payload: AutomationInput, db: DB):
    stored = db.scalar(select(MatchingProfile).where(MatchingProfile.id == 1).with_for_update())
    if not stored or not get_profile(db).target_roles:
        raise HTTPException(422, "Save target designations first")
    schedules = db.scalars(select(DiscoverySchedule).where(DiscoverySchedule.name.startswith(PREFIX))
                           .with_for_update()).all()
    by_name = {s.name: s for s in schedules}
    at = now()
    if payload.enabled:
        ids = list(db.scalars(select(Company.id).order_by(Company.id)))
        if not ids:
            raise HTTPException(422, "Import the company workbook first")
        for index, start in enumerate(range(0, len(ids), 5)):
            name = PREFIX + str(index + 1)
            schedule = by_name.get(name)
            if schedule is None:
                schedule = DiscoverySchedule(id=str(uuid4()), name=name, enabled=False)
                db.add(schedule)
                schedules.append(schedule)
            schedule.payload = {"company_ids": ids[start:start + 5], "job_offset": 0, "max_jobs_per_company": 300}
            schedule.interval_minutes = 1440
            if not schedule.enabled:
                schedule.next_run_at = at + timedelta(minutes=index * 2)
            schedule.enabled = True
    else:
        for schedule in schedules:
            schedule.enabled = False
        if schedules:
            tasks = db.scalars(select(BackgroundTask).where(BackgroundTask.schedule_id.in_([s.id for s in schedules]),
                                    BackgroundTask.status == "queued").with_for_update()).all()
            for task in tasks:
                task.status = "cancelled"
                task.finished_at = at
                task.error = "Target-role automation paused by user"
    db.commit()
    return read_targets(db)
