"""One background worker/scheduler process. Run with python -m app.worker."""
import logging
import signal
import threading
from pathlib import Path
from time import time

from sqlalchemy import text

from app.background import claim, execute, now, recover, schedule_due
from app.database import engine, SessionLocal
from app.models import WorkerState

log = logging.getLogger(__name__)
STOP = threading.Event()
HEARTBEAT = Path("/tmp/job-pipeline-worker-heartbeat")


def heartbeat():
    while not STOP.is_set():
        try:
            with SessionLocal() as db:
                state = db.get(WorkerState, 1)
                if state:
                    state.last_seen = now()
                else:
                    db.add(WorkerState(id=1, last_seen=now()))
                db.commit()
            HEARTBEAT.write_text(str(time()))
        except Exception:
            log.warning("Worker heartbeat could not reach the database")
        STOP.wait(10)


def main():
    logging.basicConfig(level=logging.INFO)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    # Dedicated connection keeps this session-level lock across service commits.
    with engine.connect() as lock:
        if not lock.execute(text("SELECT pg_try_advisory_lock(741905)")).scalar():
            raise RuntimeError("Another discovery worker is already running")
        if lock.execute(text("SELECT version_num FROM alembic_version")).scalar() != "0005":
            raise RuntimeError("Run migrations before starting the worker")
        lock.commit()
        with SessionLocal() as db:
            recover(db)
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            while not STOP.is_set():
                # Fail closed if the lock-holding connection is lost; restart recovers tasks.
                lock.execute(text("SELECT 1"))
                lock.commit()
                with SessionLocal() as db:
                    schedule_due(db)
                    task_id = claim(db)
                if task_id:
                    log.info("Executing task %s", task_id)
                    execute(SessionLocal, task_id)
                else:
                    STOP.wait(5)
        finally:
            STOP.set()
            thread.join(timeout=12)
            HEARTBEAT.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
