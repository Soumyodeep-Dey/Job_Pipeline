from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.importer import TRACKER_HEADERS, parse_companies, read_workbook
from app.models import Company

DATA = Path(__file__).resolve().parents[1] / "data"


def tracker_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(TRACKER_HEADERS)
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def upload(client, content, endpoint="jobs"):
    return client.post(f"/imports/{endpoint}", files={"file": ("source.xlsx", content)})


def test_tracker_import_reports_errors_and_duplicates(client):
    rows = [
        ["one", "Atlan", "Developer", "India", "Python", 90, None, "https://example.com/one", "2026-09-20", "New", None, "No"],
        ["two", "Atlan", "Developer", None, None, 80, None, "https://example.com/two", None, "Approved", None, "Yes"],
        ["three", "Atlan", "Developer", None, None, 80, None, None, None, "Approved", None, "No"],
        ["four", "Missing", "Developer"],
        ["five", "Atlan", "Developer", None, None, 101],
        [None, "Atlan", "Developer"],
        ["six", "Atlan", "Developer", None, None, None, None, None, None, "New", None, "perhaps"],
        [None, "Atlan", "Developer", None, None, None, None, "https://example.com/uuid"],
    ]
    content = tracker_bytes(rows)
    result = upload(client, content).json()
    assert result["created"] == 3
    assert [e["row"] for e in result["errors"]] == [4, 5, 6, 7, 8]
    result = upload(client, content).json()
    assert result["created"] == 0
    assert result["duplicates"] == 3
    assert len(client.get("/jobs").json()) == 3


def test_empty_tracker_and_invalid_file(client):
    assert upload(client, tracker_bytes([])).json()["created"] == 0
    assert upload(client, b"not an xlsx").status_code == 422
    assert upload(client, tracker_bytes([]), "companies").status_code == 422
    assert client.post("/imports/jobs", files={"file": ("bad.csv", b"a,b")}).status_code == 400


def test_tracker_hyperlink_and_formula(client):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(TRACKER_HEADERS)
    sheet.append([42, "Atlan", "Dev", None, None, 0, None, "Apply"])
    sheet["H2"].hyperlink = "https://example.com/42"
    sheet.append([43, "Atlan", "=1+1"])
    stream = BytesIO()
    workbook.save(stream)
    result = upload(client, stream.getvalue()).json()
    assert result["created"] == 1
    assert result["errors"][0]["row"] == 3
    job = client.get("/jobs").json()[0]
    assert job["job_id"] == "42"
    assert job["source_url"] == "https://example.com/42"
    assert job["match_score"] == 0


@pytest.fixture(scope="module")
def company_source():
    path = DATA / "Domain wise Company Data.xlsx"
    if not path.exists():
        pytest.skip("Place the supplied company workbook in data/ to run source integration tests")
    return path.read_bytes()


def test_actual_source_layout(company_source):
    workbook = read_workbook(company_source)
    companies, configs, entries = parse_companies(workbook)
    workbook.close()
    assert entries == 452
    assert len(companies) == 440
    assert "https://atlan.com/careers/" in companies["atlan"]["career_pages"]
    assert {c["sheet"]: len(c["keyword_bank"]) for c in configs} == {
        "Keywords for DATA": 5000, "Keywords for AI": 4022, "Keywords for Cyber": 4823,
    }
    assert len(companies["sarvam ai"]["keyword_profiles"]) >= 1
    assert len(companies["moody's"]["keyword_profiles"]) == 1
    assert len(companies["lowe's india"]["keyword_profiles"]) == 1
    assert any(-100 in rule["values"] for c in configs for rule in c["rules"])


def test_company_import_repeatable(client, company_source, session_factory):
    first = upload(client, company_source, "companies")
    assert first.status_code == 200, first.text
    assert first.json()["unique_companies"] == 440
    assert first.json()["created"] == 439  # Atlan was seeded in the fixture.
    second = upload(client, company_source, "companies").json()
    assert second["created"] == 0
    assert second["updated"] == 440
    with session_factory() as db:
        companies = db.scalars(select(Company)).all()
        assert len(companies) == 440
        assert sum(len(c.keyword_profiles) for c in companies) == 449
    configs = client.get("/discovery-config").json()
    assert len(configs) == 3
    assert sum(len(c["keyword_bank"]) for c in configs) == 13845


def test_supplied_empty_tracker(client):
    path = DATA / "Application Tracker.xlsx"
    if not path.exists():
        pytest.skip("Supplied tracker not available")
    result = client.post("/imports/jobs")
    assert result.status_code == 200
    assert result.json() == {"created": 0, "duplicates": 0, "errors": [], "duplicate_rows": []}
