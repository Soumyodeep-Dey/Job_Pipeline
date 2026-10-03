"""Readiness and an authenticated operational overview."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Column, MetaData, String, Table, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.automation_routes import worker_health
from app.database import get_db

router = APIRouter(tags=["Operations"])
EXPECTED_REVISION = "0005"
VERSION_TABLE = Table("alembic_version", MetaData(), Column("version_num", String(32)))


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        revision = db.scalar(select(VERSION_TABLE.c.version_num))
        if revision == EXPECTED_REVISION:
            return {"status": "ready"}
    except SQLAlchemyError:
        db.rollback()
    return JSONResponse({"status": "not_ready"}, status_code=503)


@router.get("/operations/health")
def operations(db: Session = Depends(get_db)):
    try:
        readiness = ready(db)
        if isinstance(readiness, JSONResponse):
            return JSONResponse({"status": "unhealthy", "database": "not_ready"}, status_code=503)
        worker = worker_health(db)
        result = {"status": "healthy" if worker["status"] == "healthy" else "degraded",
                  "database": "ready", "worker": worker}
        if worker["status"] != "healthy":
            from fastapi.encoders import jsonable_encoder
            return JSONResponse(jsonable_encoder(result), status_code=503)
        return result
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse({"status": "unhealthy", "database": "unavailable"}, status_code=503)
