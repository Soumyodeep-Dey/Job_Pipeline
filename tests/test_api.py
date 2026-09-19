from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.database import get_db
from app.main import app
from app.models import Job


def payload(**changes):
    return {"job_id": "test-1", "company": "Atlan", "role": "Python Developer",
            "location": "Remote India", "match_score": 80,
            "source_url": "https://example.com/jobs/1", **changes}


def test_health_and_company_list(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}
    assert client.get("/companies").json()[0]["name"] == "Atlan"


def test_create_and_combined_filters(client):
    response = client.post("/jobs", json=payload())
    assert response.status_code == 201
    assert len(response.json()) == 12
    assert response.json()["human_approval"] is False
    assert len(client.get("/jobs?company=ATLAN&status=New&location=india&min_match_score=80").json()) == 1
    for query in ("company=missing", "status=Applied", "location=Paris", "min_match_score=81", "company=%"):
        assert client.get("/jobs?" + query).json() == []
    assert client.get("/jobs?limit=0").status_code == 422


@pytest.mark.parametrize("changes", [{"source_url": "https://example.com/jobs/2"}, {"job_id": "other"}])
def test_duplicate_id_or_url(client, changes):
    assert client.post("/jobs", json=payload()).status_code == 201
    assert client.post("/jobs", json=payload(**changes)).status_code == 409


def test_approval_transitions(client):
    assert client.post("/jobs", json=payload(status="Approved")).status_code == 422
    assert client.post("/jobs", json=payload()).status_code == 201
    assert client.patch("/jobs/test-1", json={"status": "Approved"}).status_code == 422
    assert client.patch("/jobs/test-1", json={"human_approval": True, "status": "Approved"}).status_code == 200
    assert client.patch("/jobs/test-1", json={"human_approval": False}).status_code == 422
    assert client.get("/jobs").json()[0]["human_approval"] is True
    assert client.patch("/jobs/test-1", json={"human_approval": False, "status": "Rejected"}).status_code == 200
    assert client.patch("/jobs/absent", json={"status": "New"}).status_code == 404
    for body in ({}, {"status": None}, {"human_approval": None}, {"role": "Other"}):
        assert client.patch("/jobs/test-1", json=body).status_code == 422


@pytest.mark.parametrize("changes", [
    {"company": "Unknown"}, {"role": "  "}, {"job_id": " "},
    {"match_score": -1}, {"match_score": 101}, {"status": "approved"},
    {"source_url": "not-a-url"}, {"human_approval": "perhaps"},
])
def test_invalid_job(client, changes):
    assert client.post("/jobs", json=payload(**changes)).status_code == 422


def test_missing_optional_identifiers(client):
    for _ in range(2):
        assert client.post("/jobs", json={"company": "atlan", "role": "Developer"}).status_code == 201
    jobs = client.get("/jobs").json()
    assert jobs[0]["job_id"] != jobs[1]["job_id"]
    assert all(j["match_score"] is None for j in jobs)
    assert client.get("/jobs?min_match_score=0").json() == []


def test_database_rejects_unapproved_job(session_factory):
    with session_factory() as db:
        db.add(Job(job_id="invalid", company_id=1, role="Dev", date_found=date.today(),
                   status="Approved", human_approval=False))
        with pytest.raises(IntegrityError):
            db.commit()


def test_database_unique_url(session_factory):
    with session_factory() as db:
        for job_id in ("a", "b"):
            db.add(Job(job_id=job_id, company_id=1, role="Dev", date_found=date.today(),
                       source_url="https://example.com/same", status="New", human_approval=False))
        with pytest.raises(IntegrityError):
            db.commit()


def test_health_database_failure(client):
    class BrokenSession:
        def execute(self, _):
            raise OperationalError("SELECT 1", {}, Exception("offline"))

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    assert client.get("/health").status_code == 503
