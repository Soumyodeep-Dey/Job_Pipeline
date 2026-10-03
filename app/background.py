"""Queue operations. Each function owns one short database transaction."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.discovery.schemas import DiscoveryRequest
from app.discovery.service import run_discovery
from app.models import BackgroundTask, DiscoverySchedule, DiscoveryRun, Notification

MAX_ATTEMPTS = 3


def now():
    return datetime.now(timezone.utc)


def enqueue(db, payload, schedule_id=None, at=None):
    at = at or now()
    task = BackgroundTask(id=str(uuid4()), schedule_id=schedule_id, payload=payload,
                          status="queued", attempts=0, run_ids=[], created_at=at, available_at=at)
    db.add(task)
    return task


def notify(db, task):
    db.add(Notification(id=str(uuid4()), task_id=task.id, created_at=now(), read=False,
                        message=f"Discovery task {task.id[:8]}: {task.status}. "
                                + (task.error or "Open its run history for created jobs and source results.")))


def schedule_due(db, at=None):
    at = at or now()
    schedules = db.scalars(select(DiscoverySchedule).where(DiscoverySchedule.enabled.is_(True),
        DiscoverySchedule.next_run_at <= at).with_for_update(skip_locked=True)).all()
    for schedule in schedules:
        pending = db.scalar(select(BackgroundTask.id).where(BackgroundTask.schedule_id == schedule.id,
                                BackgroundTask.status.in_(["queued", "running"])))
        if pending is None:
            enqueue(db, schedule.payload, schedule.id, at)
        # Coalesce missed occurrences into one; never replay an offline backlog.
        schedule.next_run_at = at + timedelta(minutes=schedule.interval_minutes)
    db.commit()


def claim(db, at=None):
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.status == "queued",
                    BackgroundTask.available_at <= (at or now())).order_by(BackgroundTask.created_at)
                    .with_for_update(skip_locked=True).limit(1))
    if task:
        task.status = "running"
        task.attempts += 1
        task.error = None
        task.run_ids = [*task.run_ids, str(uuid4())]
    db.commit()
    return task.id if task else None


def fail_or_retry(db, task, reason, retryable=True):
    task.error = reason[:500]
    if retryable and task.attempts < MAX_ATTEMPTS:
        task.status = "queued"
        task.available_at = now() + timedelta(seconds=30 * 2 ** (task.attempts - 1))
    else:
        task.status = "failed"
        task.finished_at = now()
        notify(db, task)


def interrupt_attempt(db, task):
    if task.run_ids:
        run = db.get(DiscoveryRun, task.run_ids[-1])
        if run and run.status == "running":
            run.status = "interrupted"
            run.finished_at = now()


def recover(db):
    # Called only after the worker holds the exclusive PostgreSQL worker lock.
    for task in db.scalars(select(BackgroundTask).where(BackgroundTask.status == "running")):
        run = db.get(DiscoveryRun, task.run_ids[-1]) if task.run_ids else None
        if run and run.status in ("completed", "partial", "failed"):
            task.status = run.status
            task.finished_at = run.finished_at or now()
            task.error = None if run.status == "completed" else "Inspect recovered run results for source failures or truncation."
            notify(db, task)
            continue
        interrupt_attempt(db, task)
        fail_or_retry(db, task, "Worker stopped during the previous attempt; committed jobs are retained.")
    db.commit()


def execute(factory, task_id):
    try:
        with factory() as db:
            task = db.get(BackgroundTask, task_id)
            run = run_discovery(db, DiscoveryRequest(**task.payload), run_id=task.run_ids[-1])
            task.status = run.status  # Source failures are terminal, not an endless retry loop.
            task.finished_at = now()
            task.error = None if run.status == "completed" else "Some sources failed or were truncated; inspect the run results."
            notify(db, task)
            db.commit()
    except Exception as exc:
        with factory() as db:
            task = db.get(BackgroundTask, task_id)
            interrupt_attempt(db, task)
            # Avoid persisting SQL exception strings, which can contain private parameters.
            reason = str(exc)[:300] if isinstance(exc, ValueError) else f"{type(exc).__name__}: worker execution failed"
            fail_or_retry(db, task, reason, retryable=not isinstance(exc, ValueError))
            db.commit()
