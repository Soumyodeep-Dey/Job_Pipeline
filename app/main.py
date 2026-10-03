from contextlib import asynccontextmanager
import os
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.security import SecurityMiddleware, validate_security
from app.operations import router as operations_router
from pathlib import Path
from typing import Annotated
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.discovery.routes import router as discovery_router
from app.discovery.coverage import router as coverage_router
from app.resumes import router as resume_router
from app.applications import router as application_router
from app.automation_routes import router as automation_router
from app.importer import build_job, duplicate_job, import_companies, import_jobs, read_workbook
from app.models import Company, DiscoveryConfig, Job
from app.schemas import CompanyRead, JobCreate, JobRead, JobUpdate, Status

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@asynccontextmanager
async def lifespan(app):
    validate_security()
    # Fail early if the explicit migration step has not completed.
    with engine.begin() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if revision != "0005":
            raise RuntimeError("Run python -m app.migrate before starting Phase 7")
        # Worker-owned tasks can outlive API restarts. Recovery belongs to the worker.
    yield


app = FastAPI(title="Job Pipeline — Phase 7", lifespan=lifespan)
app.add_middleware(SecurityMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(","))
app.include_router(operations_router)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")

app.include_router(discovery_router)
app.include_router(resume_router)
app.include_router(coverage_router)
app.include_router(automation_router)
app.include_router(application_router)
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


@app.get("/dashboard/jobs/{job_id}", response_model=JobRead)
def dashboard_job(job_id: str, db: DB):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job_response(job, db.get(Company, job.company_id).name)


@app.post("/jobs", response_model=JobRead, status_code=201)
def create_job(payload: JobCreate, db: DB):
    if duplicate_job(db, payload):
        raise HTTPException(409, "A job with this Job ID or Source URL already exists")
    try:
        job = build_job(db, payload)
        db.add(job)
        db.commit()
    except ValueError as exc:
        db.rollback()
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
    scope: Literal["all", "india", "history"] = "all",
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
    query = query.order_by(Job.date_found.desc(), Job.job_id)
    if scope == "all":
        rows = db.execute(query.offset(offset).limit(limit))
    else:
        from app.discovery.location import india_opportunity
        # Apply the same word-boundary policy before pagination on both databases.
        rows = [row for row in db.execute(query)
                if india_opportunity(row[0]) == (scope == "india")][offset:offset + limit]
    return [job_response(job, name) for job, name in rows]


@app.patch("/jobs/{job_id}", response_model=JobRead)
def update_job(job_id: str, changes: JobUpdate, db: DB):
    job = db.scalar(select(Job).where(Job.job_id == job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "Job not found")
    values = changes.model_dump(exclude_unset=True)
    status = values.get("status", job.status)
    approval = values.get("human_approval", job.human_approval)
    if status == "Approved" and not (approval or job.auto_approved):
        raise HTTPException(422, "Approved status requires human_approval=true; change status when revoking approval")
    if status != "Approved" or approval:
        job.auto_approved = False
    for key, value in values.items():
        setattr(job, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Update violates a database constraint") from exc
    return job_response(job, db.get(Company, job.company_id).name)
