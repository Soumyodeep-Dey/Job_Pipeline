import json
from types import SimpleNamespace

import pytest
from app.models import Resume
from app.resumes import explicit_requirements, skills_list, resume_contains
from app.discovery.sources import Board, fetch_jobs
from app.discovery.matching import experience_fit, contains, evaluate
from app.discovery.schemas import CandidateProfile


def seed(session_factory, text="Python SQL Docker Linux", identifier="a"):
    with session_factory() as db:
        db.add(Resume(id=identifier, filename=identifier + ".pdf", text=text))
        db.commit()


@pytest.mark.parametrize("requirements,status,score", [
    ("Python,SQL,Docker,Linux,Java", "Approved", 80),
    ("Python,SQL,Docker,Linux", "Approved", 100),
    ("Python,SQL,Docker,Linux,Java,Rust", "New", 100 * 4 / 6),
    (None, "New", None), ("Java", "New", 0),
])
def test_threshold(client, session_factory, requirements, status, score):
    seed(session_factory)
    response = client.post("/jobs", json={"job_id": "j", "company": "Atlan", "role": "Developer",
                                         "required_skills": requirements, "match_score": 100})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == status
    assert response.json()["human_approval"] is False
    evidence = client.get("/jobs/j/resume-assessments").json()[0]
    assert evidence["resume_match_percent"] == score
    if status == "New":
        assert client.patch("/jobs/j", json={"status": "Approved"}).status_code == 422
        assert client.patch("/jobs/j", json={"status": "Approved", "human_approval": True}).status_code == 200


def test_independent_versions_and_reassessment(client, session_factory):
    seed(session_factory, "Python SQL", "a")
    seed(session_factory, "Docker Linux", "b")
    client.post("/jobs", json={"job_id": "j", "company": "Atlan", "role": "Dev", "required_skills": "Python,SQL,Docker,Linux"})
    assert client.get("/jobs").json()[0]["status"] == "New"  # Never union résumés.
    seed(session_factory, "Python SQL Docker Linux", "c")
    assert client.get("/jobs").json()[0]["status"] == "New"  # No silent retroactive approval.
    assert client.post("/jobs/j/resume-assessment", json={}).json()["status"] == "Approved"
    assert client.post("/jobs/j/resume-assessment", json={"resume_id": "a"}).json()["status"] == "New"
    assert len(client.get("/jobs/j/resume-assessments").json()) == 3
    assert client.post("/jobs/j/resume-assessment", json={"resume_id": "missing"}).status_code == 422


def test_manual_rejection_and_terminal_status_preserved(client, session_factory):
    seed(session_factory)
    client.post("/jobs", json={"job_id": "j", "company": "Atlan", "role": "Dev", "required_skills": "Python"})
    client.patch("/jobs/j", json={"status": "Rejected"})
    assert client.patch("/jobs/j", json={"status": "Approved"}).status_code == 422
    client.patch("/jobs/j", json={"status": "Applied"})
    assert client.post("/jobs/j/resume-assessment", json={}).json()["status"] == "Applied"


def test_aliases_and_explicit_requirements():
    assert skills_list("React,react.js,ReactJS") == ["react"]
    assert explicit_requirements("Required skills: Python, SQL, Docker. Benefits: insurance") == "docker, python, sql"
    assert explicit_requirements("We use Python. SQL is preferred.") is None
    assert not contains("JavaScript", "Java")
    assert contains("SDE", "software engineer")
    assert experience_fit("Developer", "We have existed for 20 years", 2)[0] == "unknown"
    assert experience_fit("Developer", "3+ yrs of experience", 2)[0] == "mismatch"
    assert not resume_contains("C++ programmer", "c")
    assert resume_contains("C++ programmer", "c++")


def test_coverage(client):
    report = client.get("/discovery/coverage").json()[0]
    assert report["missing_keyword_profile"] and report["missing_career_page"]
    assert client.post("/discovery/source-audits", json={"company_ids": [999]}).status_code == 422


def test_board_continuation():
    rows = [{"id": i, "title": "Dev", "absolute_url": f"https://example.com/{i}"} for i in range(6)]
    fetcher = SimpleNamespace(get=lambda *a, **kw: ("", json.dumps({"jobs": rows})))
    jobs, errors, more = fetch_jobs(Board("greenhouse", "example", "https://boards.greenhouse.io/example"), fetcher, 2, 2)
    assert [j["external_id"] for j in jobs] == ["2", "3"]
    assert not errors and more


def test_resume_upload_and_rescan(client, monkeypatch, tmp_path):
    from app import resumes
    import pypdf
    monkeypatch.setattr(pypdf, "PdfReader", lambda _: SimpleNamespace(is_encrypted=False,
        pages=[SimpleNamespace(extract_text=lambda: "Python SQL developer experience " * 10)]))
    monkeypatch.setattr(resumes, "RESUME_DIR", tmp_path)
    (tmp_path / "first.pdf").write_bytes(b"first")
    assert client.post("/imports/resumes").json()["results"][0]["status"] == "imported"
    (tmp_path / "new.pdf").write_bytes(b"new version")
    results = client.post("/imports/resumes").json()["results"]
    assert [r["status"] for r in results] == ["duplicate", "imported"]
    response = client.post("/imports/resumes", files={"file": ("uploaded.pdf", b"third", "application/pdf")})
    assert response.json()["results"][0]["status"] == "imported"
    assert len(client.get("/resumes").json()) == 3
    assert client.post("/imports/resumes", files={"file": ("bad.txt", b"bad")}).status_code == 422


def test_remote_country_is_not_india():
    company = SimpleNamespace(keyword_profiles=[{"sheet": "Keywords for DATA", "keywords": ["software engineer"], "exclusions": []}])
    result = evaluate({"title": "SDE", "description": "0-2 years of experience", "location": "Remote - US"},
                      company, CandidateProfile(), {}, {"title":35,"skills":30,"experience":20,"location":15,"exclusion":-100})
    assert result["location_fit"] == "mismatch"
    assert result["disposition"] == "excluded"


def test_discovery_auto_approval(client, session_factory, monkeypatch):
    from app.discovery import service
    from app.models import Company
    seed(session_factory)
    with session_factory() as db:
        company = db.get(Company, 1)
        company.keyword_profiles = [{"sheet": "Keywords for DATA", "keywords": ["software engineer"], "exclusions": []}]
        company.career_pages = ["https://example.com/careers"]
        db.commit()
    monkeypatch.setattr(service, "workbook_weights", lambda _: {"title":35,"skills":30,"experience":20,"location":15,"exclusion":-100})
    monkeypatch.setattr(service, "resolve_board", lambda *a: Board("lever", "example", "https://jobs.lever.co/example"))
    monkeypatch.setattr(service, "fetch_jobs", lambda *a: ([{"external_id": "1", "title": "Software Engineer",
        "location": "India", "url": "https://jobs.lever.co/example/1",
        "description": "Required skills: Python, SQL, Docker, Linux, Java."}], [], False))
    result = client.post("/discovery/runs", json={"company_ids": [1]}).json()
    assert result["results"][0]["auto_approved"] == 1
    assert result["results"][0]["review_required"] == 0
    job = client.get("/jobs").json()[0]
    assert job["status"] == "Approved" and job["human_approval"] is False
    assert client.get(f"/jobs/{job['job_id']}/approval").json()["resume_match_percent"] == 80


def test_database_rejects_false_auto_approval(session_factory):
    from datetime import date
    from sqlalchemy.exc import IntegrityError
    from app.models import Job
    with session_factory() as db:
        db.add(Job(job_id="invalid", company_id=1, role="Dev", date_found=date.today(),
                   status="Approved", human_approval=False, auto_approved=True, resume_match_percent=79.99))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
