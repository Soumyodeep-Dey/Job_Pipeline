import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.discovery import service
from app.discovery.matching import contains, evaluate, experience_fit
from app.discovery.schemas import CandidateProfile
from app.discovery.sources import Board, Fetcher, SourceError, board_from_url, canonical_url, fetch_jobs, public_url, resolve_board
from app.models import Company, DiscoveryConfig, Job, JobEvidence

WEIGHTS = {"title": 35, "skills": 30, "experience": 20, "location": 15, "exclusion": -100}
PROFILE = {"sheet": "Keywords for AI", "keywords": ["backend engineer", "Python", "SQL", "Kafka"],
           "exclusions": ["senior", "lead", "5+ years", "US citizenship required"]}


def posting(**changes):
    return {"external_id": "123", "title": "Junior Backend Engineer", "location": "Bengaluru, India",
            "description": "0-2 years of experience. Python, SQL and Kafka.",
            "url": "https://jobs.lever.co/example/123", **changes}


def evaluate_job(**changes):
    company = SimpleNamespace(keyword_profiles=[PROFILE])
    return evaluate(posting(**changes), company, CandidateProfile(), {}, WEIGHTS)


def test_explainable_matching():
    result = evaluate_job()
    assert result["score"] == 84  # 35 title + 12 demonstrated + 2 adjacent + 20 experience + 15 location.
    assert result["demonstrated_skill_matches"] == ["Python", "SQL"]
    assert result["adjacent_skill_matches"] == ["Kafka"]
    assert result["skills_to_review"] == ["Kafka"]
    assert result["disposition"] == "review_required"


@pytest.mark.parametrize("changes,disposition", [
    ({"title": "Senior Backend Engineer"}, "excluded"),
    ({"description": "Minimum 5+ years of experience with Python"}, "excluded"),
    ({"location": "London, UK"}, "excluded"),
    ({"title": "Account Executive"}, "irrelevant"),
    ({"location": "Remote"}, "review_required"),
    ({"description": "", "title": "Backend Engineer"}, "review_required"),
])
def test_matching_gates(changes, disposition):
    result = evaluate_job(**changes)
    assert result["disposition"] == disposition
    if disposition in ("excluded", "irrelevant"):
        assert result["score"] == 0


def test_boundary_alias_and_experience_matching():
    assert not contains("leadership", "lead")
    assert not contains("JavaScript", "Java")
    assert contains("NodeJS and RESTful APIs", "Node.js")
    assert contains("NodeJS and RESTful APIs", "REST APIs")
    assert experience_fit("Developer", "12 years of experience", 2)[0] == "mismatch"
    assert experience_fit("Developer", "3 to 5 years of experience", 2)[0] == "mismatch"
    assert experience_fit("Developer", "Python and SQL", 2)[0] == "unknown"
    assert experience_fit("Developer", "We have served customers for 20 years.", 2)[0] == "unknown"
    assert evaluate_job(description="Work alongside senior developers and lead discussions.")["exclusion_matches"] == []


class FakeFetcher:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = []

    def get(self, url, allowed_hosts, public_api=False):
        self.calls.append(url)
        value = self.pages.get(url)
        if value is None:
            raise SourceError("Fixture source unavailable")
        return url, value.encode() if isinstance(value, str) else json.dumps(value).encode()

    def close(self):
        pass


def test_resolve_linked_boards_and_embed():
    page = 'https://company.example/careers'
    fetcher = FakeFetcher({page: '<script src="https://boards.greenhouse.io/embed/job_board/js?for=example"></script>'})
    board = resolve_board(page, fetcher)
    assert board.token == "example" and board.provider == "greenhouse"
    assert board_from_url("https://jobs.lever.co/example/123").token == "example"
    assert board_from_url("https://jobs.ashbyhq.com/example").provider == "ashby"
    assert board_from_url("https://jobs.lever.co.evil.example/example") is None
    assert board_from_url("https://jobs.lever.co/%2e%2e") is None
    with pytest.raises(SourceError, match="Unsupported"):
        resolve_board(page, FakeFetcher({page: '<a href="/jobs">Jobs</a>'}))


@pytest.mark.parametrize("provider,endpoint,data", [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true",
     {"jobs": [{"id": 1, "title": "Developer", "absolute_url": "https://boards.greenhouse.io/example/jobs/1?utm_source=x",
                "location": {"name": "India"}, "content": "&lt;p&gt;Python&lt;/p&gt;"}]}),
    ("lever", "https://api.lever.co/v0/postings/example?mode=json&limit=100&skip=0",
     [{"id": "1", "text": "Developer", "hostedUrl": "https://jobs.lever.co/example/1",
       "categories": {"allLocations": ["India", "Remote"]}, "descriptionPlain": "Python",
       "lists": [{"text": "Skills", "content": "<li>SQL</li>"}]}]),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/example",
     {"jobs": [{"title": "Developer", "jobUrl": "https://jobs.ashbyhq.com/example/1", "location": "India",
                "descriptionPlain": "Python", "isListed": True},
               {"title": "Private", "isListed": False}]}),
])
def test_provider_parsing(provider, endpoint, data):
    jobs, errors, truncated = fetch_jobs(Board(provider, "example", "unused"), FakeFetcher({endpoint: data}), 100)
    assert len(jobs) == 1 and not errors and not truncated
    assert jobs[0]["title"] == "Developer"
    assert "Python" in jobs[0]["description"]
    assert "?" not in jobs[0]["url"]


def test_lever_pagination_and_truncation():
    raw = {"id": "1", "text": "Developer", "hostedUrl": "https://jobs.lever.co/example/1", "categories": {}}
    base = "https://api.lever.co/v0/postings/example?mode=json&limit=100&skip="
    fetcher = FakeFetcher({base + "0": [raw] * 100, base + "100": [raw]})
    jobs, _, truncated = fetch_jobs(Board("lever", "example", "unused"), fetcher, 200)
    assert len(jobs) == 101 and len(fetcher.calls) == 2 and not truncated
    jobs, _, truncated = fetch_jobs(Board("lever", "example", "unused"), fetcher, 50)
    assert len(jobs) == 50 and truncated


def test_invalid_posting_reported():
    board = Board("ashby", "example", "unused")
    url = "https://api.ashbyhq.com/posting-api/job-board/example"
    jobs, errors, _ = fetch_jobs(board, FakeFetcher({url: {"jobs": [{"title": "Missing URL"}]}}), 100)
    assert not jobs and len(errors) == 1
    with pytest.raises(SourceError):
        fetch_jobs(board, FakeFetcher({url: {"wrong": []}}), 100)


def test_canonical_url_preserves_job_identity_in_query():
    first = canonical_url("https://example.com/careers?gh_jid=1&utm_source=board#apply")
    second = canonical_url("https://example.com/careers?gh_jid=2&utm_source=board")
    assert first == "https://example.com/careers?gh_jid=1"
    assert first != second


def test_blocks_private_sources_and_credentials():
    for url in ("https://127.0.0.1/x", "https://[::1]/", "http://example.com", "https://user:pass@example.com"):
        with pytest.raises(SourceError):
            public_url(url)


def test_fetcher_robots_redirect_and_retry(monkeypatch):
    monkeypatch.setattr("app.discovery.sources.public_url", lambda url: None)
    monkeypatch.setattr("app.discovery.sources.time.sleep", lambda seconds: None)
    attempts = []

    def handle(request):
        attempts.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        if request.url.path == "/private":
            pytest.fail("Robots-disallowed source must never be requested")
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "https://127.0.0.1/"})
        if attempts.count("/retry") == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, text="ok")

    fetcher = Fetcher()
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(SourceError, match="disallows"):
        fetcher.get("https://example.com/private", {"example.com"})
    with pytest.raises(SourceError, match="Redirect"):
        fetcher.get("https://example.com/redirect", {"example.com"})
    assert fetcher.get("https://example.com/retry", {"example.com"})[1] == b"ok"
    assert attempts.count("/retry") == 2
    fetcher.close()


def test_robots_www_redirect(monkeypatch):
    monkeypatch.setattr("app.discovery.sources.public_url", lambda url: None)

    def handle(request):
        if request.url.path == "/robots.txt" and request.url.host == "example.com":
            return httpx.Response(301, headers={"Location": "https://www.example.com/robots.txt"})
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text="ok")

    fetcher = Fetcher()
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(handle))
    assert fetcher.get("https://example.com/careers", {"example.com"})[1] == b"ok"
    fetcher.close()


def test_public_api_does_not_depend_on_unrelated_robots_route(monkeypatch):
    monkeypatch.setattr("app.discovery.sources.public_url", lambda url: None)
    requested = []

    def handle(request):
        requested.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(401)
        return httpx.Response(200, json={"jobs": []})

    fetcher = Fetcher()
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(handle))
    jobs, errors, truncated = fetch_jobs(Board("ashby", "example", "unused"), fetcher, 100)
    assert jobs == [] and not errors and not truncated
    assert requested == ["/posting-api/job-board/example"]
    with pytest.raises(SourceError, match="Not a supported"):
        fetcher.get("https://example.com/secret", {"example.com"}, public_api=True)
    fetcher.close()


@pytest.fixture
def discovery_seed(session_factory):
    with session_factory() as db:
        company = db.scalar(select(Company).where(Company.name_key == "atlan"))
        company.keyword_profiles = [PROFILE]
        company.career_pages = ["https://jobs.lever.co/example"]
        db.add(DiscoveryConfig(sheet="Keywords for DATA", keyword_bank=[], notes=[], rules=[
            {"values": [label, "test", value]} for label, value in [
                ("Title match", 35), ("Strong skill match", 30), ("Experience fit", 20),
                ("Location fit", 15), ("Exclusion hit", -100)]]))
        db.commit()
        return company.id


def test_discovery_api_duplicate_and_approval_preservation(client, session_factory, discovery_seed, monkeypatch):
    monkeypatch.setattr(service, "Fetcher", FakeFetcher)
    monkeypatch.setattr(service, "fetch_jobs", lambda *args: ([posting()], [], False))
    response = client.post("/discovery/runs", json={"company_ids": [discovery_seed]})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "completed" and run["results"][0]["created"] == 1
    job = client.get("/jobs").json()[0]
    assert len(job) == 12 and job["status"] == "New" and job["human_approval"] is False
    evidence = client.get(f"/jobs/{job['job_id']}/discovery").json()
    assert evidence["explanation"]["score"] == job["match_score"]
    assert client.patch(f"/jobs/{job['job_id']}", json={"status": "Approved"}).status_code == 422
    assert client.patch(f"/jobs/{job['job_id']}", json={"status": "Approved", "human_approval": True}).status_code == 200
    second = client.post("/discovery/runs", json={"company_ids": [discovery_seed]}).json()
    assert second["results"][0]["duplicates"] == 1
    assert client.get("/jobs").json()[0]["status"] == "Approved"
    with session_factory() as db:
        assert len(db.scalars(select(JobEvidence)).all()) == 1
    assert client.get(f"/discovery/runs/{run['id']}").status_code == 200
    assert len(client.get("/discovery/runs").json()) == 2


def test_discovery_exclusions_and_unknown_location(client, discovery_seed, monkeypatch):
    monkeypatch.setattr(service, "Fetcher", FakeFetcher)
    monkeypatch.setattr(service, "fetch_jobs", lambda *args: ([
        posting(title="Senior Backend Engineer"),
        posting(external_id="456", url="https://jobs.lever.co/example/456", location="Remote"),
        posting(title="Sales Representative"),
    ], [], False))
    run = client.post("/discovery/runs", json={"company_ids": [discovery_seed]}).json()
    result = run["results"][0]
    assert result["excluded"] == 1 and result["review_required"] == 1 and result["irrelevant"] == 1
    jobs = client.get("/jobs").json()
    assert sorted(job["status"] for job in jobs) == ["New", "Rejected"]
    assert not any(job["human_approval"] for job in jobs)


def test_discovery_failure_recorded(client, discovery_seed, monkeypatch):
    class FailingFetcher(FakeFetcher):
        def get(self, *args, **kwargs):
            raise SourceError("Network unavailable")
    monkeypatch.setattr(service, "Fetcher", FailingFetcher)
    run = client.post("/discovery/runs", json={"company_ids": [discovery_seed]}).json()
    assert run["status"] == "failed" and run["finished_at"]
    assert run["results"][0]["errors"] == ["Network unavailable"]


def test_profile_and_input_validation(client):
    assert "Python" in client.get("/matching-profile").json()["demonstrated_skills"]
    assert client.put("/matching-profile", json={"demonstrated_skills": ["Rust"], "locations": ["India"]}).status_code == 200
    assert client.get("/matching-profile").json()["demonstrated_skills"] == ["Rust"]
    for body in ({"locations": []}, {"demonstrated_skills": [""]}, {"max_experience_years": -1}):
        assert client.put("/matching-profile", json=body).status_code == 422
    for body in ({"company_ids": []}, {"company_ids": [1, 1]}, {"company_ids": [999]},
                 {"company_ids": [1], "max_jobs_per_company": 301}):
        assert client.post("/discovery/runs", json=body).status_code == 422
    assert client.get("/discovery/runs/missing").status_code == 404
    assert client.get("/jobs/missing/discovery").status_code == 404
