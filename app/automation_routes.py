"""Background discovery APIs; no external email or messaging integration."""
from datetime import timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.background import enqueue, now
from app.database import get_db
from app.discovery.schemas import DiscoveryRequest
from app.models import BackgroundTask, Company, DiscoverySchedule, Notification, WorkerState
from uuid import uuid4

router = APIRouter(tags=["Phase 5 background discovery"])
DB = Annotated[Session, Depends(get_db)]


def validate_companies(db, request):
    if any(db.get(Company, identifier) is None for identifier in request.company_ids):
        raise HTTPException(422, "Select existing company IDs")


def task_response(task):
    return {key: getattr(task, key) for key in ("id", "schedule_id", "payload", "status", "attempts",
            "run_ids", "created_at", "available_at", "finished_at", "error")}


@router.post("/discovery/tasks", status_code=202)
def queue_discovery(payload: DiscoveryRequest, db: DB):
    validate_companies(db, payload)
    task = enqueue(db, payload.model_dump())
    db.commit()
    return task_response(task)


@router.get("/discovery/tasks")
def tasks(db: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return [task_response(t) for t in db.scalars(select(BackgroundTask)
            .order_by(BackgroundTask.created_at.desc()).offset(offset).limit(limit))]


@router.get("/discovery/tasks/{task_id}")
def task_detail(task_id: str, db: DB):
    task = db.get(BackgroundTask, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task_response(task)


@router.post("/discovery/tasks/{task_id}/cancel")
def cancel(task_id: str, db: DB):
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(404, "Task not found")
    if task.status != "queued":
        raise HTTPException(409, "Only queued tasks can be cancelled; running discovery finishes its bounded attempt")
    task.status = "cancelled"
    task.finished_at = now()
    db.commit()
    return task_response(task)


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    discovery: DiscoveryRequest
    interval_minutes: int = Field(default=1440, ge=15, le=10080)
    enabled: bool = False


class ScheduleState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def schedule_response(schedule):
    return {key: getattr(schedule, key) for key in ("id", "name", "payload", "interval_minutes", "enabled", "next_run_at")}


@router.post("/discovery/schedules", status_code=201)
def create_schedule(payload: ScheduleCreate, db: DB):
    validate_companies(db, payload.discovery)
    schedule = DiscoverySchedule(id=str(uuid4()), name=payload.name, payload=payload.discovery.model_dump(),
        interval_minutes=payload.interval_minutes, enabled=payload.enabled,
        next_run_at=now() + timedelta(minutes=payload.interval_minutes))
    db.add(schedule)
    db.commit()
    return schedule_response(schedule)


@router.get("/discovery/schedules")
def schedules(db: DB, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return [schedule_response(s) for s in db.scalars(select(DiscoverySchedule)
            .order_by(DiscoverySchedule.name, DiscoverySchedule.id).offset(offset).limit(limit))]


@router.patch("/discovery/schedules/{schedule_id}")
def set_schedule(schedule_id: str, payload: ScheduleState, db: DB):
    schedule = db.scalar(select(DiscoverySchedule).where(DiscoverySchedule.id == schedule_id).with_for_update())
    if schedule is None:
        raise HTTPException(404, "Schedule not found")
    if payload.enabled and not schedule.enabled:
        schedule.next_run_at = now() + timedelta(minutes=schedule.interval_minutes)
    schedule.enabled = payload.enabled
    # Pausing stops future enqueueing; existing tasks remain explicit and cancellable.
    db.commit()
    return schedule_response(schedule)


@router.get("/notifications")
def notifications(db: DB, unread_only: bool = True, limit: int = Query(50, ge=1, le=200)):
    query = select(Notification)
    if unread_only:
        query = query.where(Notification.read.is_(False))
    return [{key: getattr(n, key) for key in ("id", "task_id", "message", "created_at", "read")}
            for n in db.scalars(query.order_by(Notification.created_at.desc()).limit(limit))]


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: str, db: DB):
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(404, "Notification not found")
    notification.read = True
    db.commit()
    return {"read": True}


@router.get("/worker/health")
def worker_health(db: DB):
    state = db.get(WorkerState, 1)
    seen = state.last_seen.replace(tzinfo=timezone.utc) if state and state.last_seen.tzinfo is None else state.last_seen if state else None
    counts = dict(db.execute(select(BackgroundTask.status, func.count()).group_by(BackgroundTask.status)).all())
    return {"status": "healthy" if seen and now() - seen < timedelta(seconds=45) else "offline",
            "last_seen": seen, "tasks": counts}
