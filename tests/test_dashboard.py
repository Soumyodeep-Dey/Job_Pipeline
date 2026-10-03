def test_dashboard_and_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    for path in ("/static/app.js", "/static/style.css"):
        assert client.get(path).status_code == 200
    assert client.get("/static/../database.py").status_code == 404


def test_dashboard_job_read_preserves_approval_gate(client):
    payload = {"job_id": "review-1", "company": "Atlan", "role": "Developer", "match_score": 100}
    assert client.post("/jobs", json=payload).status_code == 201
    assert client.get("/dashboard/jobs/review-1").json()["status"] == "New"
    assert client.patch("/jobs/review-1", json={"status": "Approved", "human_approval": False}).status_code == 422
    assert client.patch("/jobs/review-1", json={"status": "Approved", "human_approval": True}).status_code == 200
    assert client.get("/dashboard/jobs/review-1").json()["human_approval"] is True
    assert client.get("/dashboard/jobs/absent").status_code == 404
