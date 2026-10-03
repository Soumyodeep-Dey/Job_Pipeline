"""Read-only checks of the running local stack; never prints credentials or job data."""
from pathlib import Path
import os

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
base = os.getenv("PUBLIC_ORIGIN") or "http://localhost:" + os.getenv("API_PORT", "8000")
with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
    assert client.get("/health").status_code == 200, "Database health failed"
    assert client.get("/ready").status_code == 200, "Migration readiness failed"
    assert client.get("/jobs").status_code == 401, "Jobs must require sign-in"
    assert client.get("/docs").status_code == 401, "Documentation must require sign-in"
    client.auth = (os.environ["AUTH_USERNAME"], os.environ["AUTH_PASSWORD"])
    for path in ("/", "/jobs?limit=1", "/companies?limit=1", "/resumes", "/applications", "/operations/health"):
        response = client.get(path)
        assert response.status_code == 200, f"Authenticated check failed: {path} ({response.status_code})"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
print("PASS: public health, protected API/docs, authenticated dashboard/data, and worker health.")
