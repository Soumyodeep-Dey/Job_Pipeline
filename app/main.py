from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.discovery.routes import router as discovery_router
from app.importer import build_job, duplicate_job, import_companies, import_jobs, read_workbook
from app.models import Company, DiscoveryConfig, DiscoveryRun, Job
from app.schemas import CompanyRead, JobCreate, JobRead, JobUpdate, Status

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@asynccontextmanager
async def lifespan(app):
    # Fail early if the explicit migration step has not completed.
    with engine.begin() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if revision != "0002":
            raise RuntimeError("Run python -m app.migrate before starting Phase 2")
        # This pilot runs one API process. Runs interrupted by a previous shutdown
        # retain their committed company outcomes and are never reported complete.
        connection.execute(update(DiscoveryRun).where(DiscoveryRun.status == "running")
                           .values(status="interrupted", finished_at=datetime.now(timezone.utc)))
    yield


app = FastAPI(title="Job Pipeline — Phase 2", lifespan=lifespan)
app.include_router(discovery_router)
DB = Annotated[Session, Depends(get_db)]


@app.get("/health")
def health(db: DB):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "database": "unavailable"})


def run_import(db, file, filename, importer):
    limit = 20 * 1024 * 1024
    if file is not None:
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(400, "Upload an .xlsx file")
        content = file.file.read(limit + 1)
    else:
        path = DATA_DIR / filename
        if not path.is_file():
            raise HTTPException(404, f"Place {filename} in data/ or upload it")
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, "Workbook exceeds 20 MB")
    workbook = None
    try:
        workbook = read_workbook(content)
        return importer(db, workbook)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Import conflict; retry after any concurrent import completes") from exc
    finally:
        if workbook:
            workbook.close()


@app.post("/imports/companies")
def companies_import(db: DB, file: UploadFile | None = File(default=None)):
    return run_import(db, file, "Domain wise Company Data.xlsx", import_companies)


@app.post("/imports/jobs")
def jobs_import(db: DB, file: UploadFile | None = File(default=None)):
    return run_import(db, file, "Application Tracker.xlsx", import_jobs)


@app.get("/companies", response_model=list[CompanyRead])
def list_companies(db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    return db.scalars(select(Company).order_by(Company.name_key).offset(offset).limit(limit)).all()


@app.get("/discovery-config")
def discovery_config(db: DB):
    return [{"sheet": c.sheet, "keyword_bank": c.keyword_bank, "rules": c.rules, "notes": c.notes}
            for c in db.scalars(select(DiscoveryConfig).order_by(DiscoveryConfig.sheet))]


def job_response(job, company):
    return {field: getattr(job, field) for field in JobRead.model_fields if field != "company"} | {"company": company}


@app.post("/jobs", response_model=JobRead, status_code=201)
def create_job(payload: JobCreate, db: DB):
    if duplicate_job(db, payload):
        raise HTTPException(409, "A job with this Job ID or Source URL already exists")
    try:
        job = build_job(db, payload)
        db.add(job)
        db.commit()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Job conflicts with an existing ID, URL or database constraint") from exc
    return job_response(job, db.get(Company, job.company_id).name)


@app.get("/jobs", response_model=list[JobRead])
def list_jobs(
    db: DB, company: str | None = None, status: Status | None = None,
    location: str | None = None, min_match_score: float | None = Query(None, ge=0, le=100),
    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
):
    query = select(Job, Company.name).join(Company)
    if company:
        query = query.where(Company.name.icontains(company.strip(), autoescape=True))
    if status:
        query = query.where(Job.status == status)
    if location:
        query = query.where(Job.location.icontains(location.strip(), autoescape=True))
    if min_match_score is not None:
        query = query.where(Job.match_score >= min_match_score)
    rows = db.execute(query.order_by(Job.date_found.desc(), Job.job_id).offset(offset).limit(limit))
    return [job_response(job, name) for job, name in rows]


@app.patch("/jobs/{job_id}", response_model=JobRead)
def update_job(job_id: str, changes: JobUpdate, db: DB):
    job = db.scalar(select(Job).where(Job.job_id == job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "Job not found")
    values = changes.model_dump(exclude_unset=True)
    status = values.get("status", job.status)
    approval = values.get("human_approval", job.human_approval)
    if status == "Approved" and not approval:
        raise HTTPException(422, "Approved status requires human_approval=true; change status when revoking approval")
    for key, value in values.items():
        setattr(job, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Update violates a database constraint") from exc
    return job_response(job, db.get(Company, job.company_id).name)
