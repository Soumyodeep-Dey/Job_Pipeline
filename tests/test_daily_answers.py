from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
from sqlalchemy import select

from app.dispatch_policy import budget
from app.form_questions import QuestionsNeeded, fingerprint, known_answers, remember_questions
from app.models import (ApplicantProfile, DispatchAttempt, FormQuestion, Job, ApplicationPreparation,
                        DiscoverySchedule, BackgroundTask)
from app.sender import consider, process, recover
from app.background import schedule_due
from test_dispatch import ready, URL
from test_applications import prepared

AT = datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)  # 9:30 AM IST
SPEC = {"prompt": "Notice period in days", "context": "", "kind": "number", "required": True, "options": []}


def history(db, count, at):
    for i in range(count):
        job_id = "history-" + str(i)
        db.add(Job(job_id=job_id, company_id=1, role="Data Engineer", location="India",
                   status="New", human_approval=False, date_found=at.date()))
        db.flush()
        db.add(DispatchAttempt(job_id=job_id, destination="https://example.org/" + str(i),
            state="uncertain", message="No receipt yet", snapshot={}, updated_at=at,
            submission_started_at=at))
    db.commit()


def answer(client, question, **changes):
    payload = {"answer":"30", "reuse":True, "confirmed":True,
               "expected_profile_version":client.get("/dispatch/questions").json()["profile_version"]}
    payload.update(changes)
    return client.put("/dispatch/questions/" + question["id"], json=payload)


def test_daily_boundary_cap_and_next_day(ready, monkeypatch):
    monkeypatch.setattr("app.sender.now", lambda: AT.replace(hour=3, minute=29))
    with ready() as db:
        assert consider(db, db.get(Job, "apply")) is None  # 8:59 IST
        assert not budget(db, AT.replace(hour=3, minute=29))["can_send"]
        assert budget(db, AT.replace(hour=3, minute=30))["can_send"]
        history(db, 5, AT)
        assert budget(db, AT)["remaining"] == 0
        assert not budget(db, AT)["can_send"]
        assert budget(db, AT + timedelta(days=1))["remaining"] == 5
        assert not budget(db, AT.replace(hour=3, minute=29) + timedelta(days=1))["can_send"]
        assert budget(db, AT.replace(hour=3, minute=30) + timedelta(days=1))["can_send"]


def test_quota_rechecked_at_submit_boundary(ready):
    with ready() as db:
        assert consider(db, db.get(Job, "apply"))
        def adapter(snapshot, facts, pdf, before):
            history(db, 5, AT)
            before()
            pytest.fail("A sixth submission must not be sent")
        process(db, "apply", adapter, lambda *_: None)
        attempt = db.get(DispatchAttempt, "apply")
        assert attempt.state == "scheduled"
        assert attempt.submission_started_at is None
        assert budget(db, AT)["used"] == 5


def test_wait_answer_reuse_resume_and_freeze_receipt(client, ready):
    with ready() as db:
        assert consider(db, db.get(Job, "apply"))
        def missing(*_):
            raise QuestionsNeeded([SPEC])
        process(db, "apply", missing, lambda *_: None)
        assert db.get(DispatchAttempt, "apply").state == "waiting_answers"
        assert budget(db, AT)["used"] == 0
        assert consider(db, db.get(Job, "apply")) is None
    question = client.get("/dispatch/questions").json()["pending"][0]
    assert answer(client, question).status_code == 200
    assert not client.get("/dispatch/questions").json()["pending"]
    with ready() as db:
        assert known_answers(db, "apply")[fingerprint(SPEC)] == "30"
        assert consider(db, db.get(Job, "apply"))
        def filled(snapshot, facts, pdf, before):
            assert facts["_form_answers"][fingerprint(SPEC)] == "30"
            facts["_used_form_answers"] = [{"question":SPEC, "answer":"30"}]
            before()
            return "Application submitted!"
        process(db, "apply", filled, lambda *_: None)
        row = db.get(DispatchAttempt, "apply")
        assert row.state == "confirmed"
        assert budget(db, AT)["used"] == 1
        assert db.get(ApplicationPreparation, "apply").submission_snapshot["form_answers"][0]["answer"] == "30"
    assert answer(client, question, answer="60").status_code == 409


def test_reuse_requires_exact_question_and_current_profile(client, ready):
    with ready() as db:
        remember_questions(db, "apply", [SPEC])
        db.add(DispatchAttempt(job_id="apply",destination=URL,state="waiting_answers",
                              message="Questions",snapshot={},updated_at=AT))
        db.commit()
    question = client.get("/dispatch/questions").json()["pending"][0]
    assert answer(client, question, expected_profile_version=999).status_code == 409
    assert answer(client, question).status_code == 200
    with ready() as db:
        assert fingerprint(SPEC) in known_answers(db, "future-job")
        assert fingerprint({**SPEC, "prompt":"Notice period in months"}) not in known_answers(db, "future-job")
        p = db.get(ApplicantProfile, 1)
        p.version += 1
        db.commit()
        assert fingerprint(SPEC) not in known_answers(db, "future-job")
        assert fingerprint(SPEC) not in known_answers(db, "apply")
    assert client.get("/dispatch/questions").json()["pending"]


def test_job_only_answers_choices_forget_and_auth(client, ready):
    spec = {**SPEC, "kind":"select-one", "options":["Immediate", "30 days"]}
    with ready() as db:
        remember_questions(db, "apply", [spec])
        db.add(DispatchAttempt(job_id="apply", destination=URL, state="waiting_answers",
                              message="Questions", snapshot={}, updated_at=AT))
        db.commit()
    question = client.get("/dispatch/questions").json()["pending"][0]
    assert answer(client, question, answer="unknown").status_code == 422
    assert answer(client, question, answer="30 days", reuse=False).status_code == 200
    with ready() as db:
        assert fingerprint(spec) in known_answers(db, "apply")
        assert fingerprint(spec) not in known_answers(db, "future-job")
    assert answer(client, question, answer="30 days", reuse=True).status_code == 200
    assert client.delete("/dispatch/answers/" + fingerprint(spec)).status_code == 200
    with ready() as db:
        assert fingerprint(spec) not in known_answers(db, "future-job")
    client.auth = None
    assert client.get("/dispatch/questions").status_code == 401
    assert client.put("/dispatch/questions/" + question["id"], json={}).status_code == 401


def test_restart_does_not_move_consumed_slot_to_new_day(ready):
    with ready() as db:
        history(db, 1, AT - timedelta(days=1))
        row = db.get(DispatchAttempt, "history-0")
        row.state = "sending"
        db.commit()
        recover(db)
        assert row.state == "uncertain"
        assert budget(db, AT - timedelta(days=1))["used"] == 1
        assert budget(db, AT)["used"] == 0


def test_managed_discovery_before_nine_and_no_backlog(session_factory):
    with session_factory() as db:
        db.add(DiscoverySchedule(id="daily",name="Target roles: batch 1",payload={"company_ids":[1]},
            interval_minutes=1440,enabled=True,next_run_at=AT-timedelta(days=3)))
        db.commit()
        schedule_due(db, AT.replace(hour=3,minute=29))
        assert db.scalar(select(BackgroundTask)) is None
        schedule_due(db, AT.replace(hour=3,minute=30))
        assert len(db.scalars(select(BackgroundTask)).all()) == 1
        schedule = db.get(DiscoverySchedule, "daily")
        next_at = schedule.next_run_at.replace(tzinfo=timezone.utc) if schedule.next_run_at.tzinfo is None else schedule.next_run_at
        assert next_at.astimezone(timezone.utc) == AT.replace(hour=3, minute=30) + timedelta(days=1)


def test_browser_questions_are_captured_then_answered():
    playwright = pytest.importorskip("playwright.sync_api")
    from app.hosted_forms import fill_and_send
    html = """<h1>Data Engineer</h1><form>
    <label>Name<input required></label><label>Email<input type="email" required></label>
    <label>Resume<input type="file" required></label>
    <label>Notice period<input type="number" required></label>
    <label>Work arrangement<select required><option value="">Choose</option><option>Hybrid</option><option>On-site</option></select></label>
    <fieldset><legend>Willing to travel?</legend><label>Yes<input type="radio" name="travel" required></label><label>No<input type="radio" name="travel"></label></fieldset>
    <label>I confirm accuracy<input type="checkbox" required></label>
    <button type="button" onclick="this.form.outerHTML='<p>Application submitted!</p>'">Submit Application</button></form>"""
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path="/usr/bin/chromium")
        page = browser.new_page()
        page.route("**/*",lambda route:route.fulfill(body=html,content_type="text/html"))
        pdf = b"fixture"
        snapshot = {"role":"Data Engineer","url":URL,"pdf_sha256":sha256(pdf).hexdigest()}
        facts = {"full_name":"Fixture", "email":"test@example.org"}
        calls = []
        with pytest.raises(QuestionsNeeded) as caught:
            fill_and_send(page, snapshot, facts, pdf, lambda:calls.append(1))
        assert len(caught.value.questions) == 4 and not calls
        choices = {"number":"30", "select-one":"Hybrid", "radio":"No", "checkbox":"Yes"}
        facts["_form_answers"] = {fingerprint(q): choices[q["kind"]] for q in caught.value.questions}
        assert fill_and_send(page, snapshot, facts, pdf, lambda:calls.append(1)) == "Application submitted!"
        assert calls == [1] and len(facts["_used_form_answers"]) == 4
        browser.close()


def test_concurrent_senders_share_five_slots(ready):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.dispatch_policy import reserve_slot
    with ready() as db:
        if db.bind.dialect.name != "postgresql":
            pytest.skip("Row locks require PostgreSQL")
        history(db, 4, AT)
        for identifier in ["candidate-one", "candidate-two"]:
            db.add(Job(job_id=identifier, company_id=1, role="Data Engineer", status="New",
                       human_approval=False, date_found=AT.date()))
            db.flush()
            db.add(DispatchAttempt(job_id=identifier, destination="https://example.org/"+identifier,
                state="checking", message="", snapshot={}, updated_at=AT))
        db.commit()
    barrier = Barrier(2)
    def compete(identifier):
        with ready() as db:
            row = db.get(DispatchAttempt, identifier)
            barrier.wait(timeout=10)
            allowed = reserve_slot(db, row, AT)
            if allowed:
                row.state = "sending"
            db.commit()
            return allowed
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, ["candidate-one", "candidate-two"]))
    assert sorted(results) == [False, True]
    with ready() as db:
        assert budget(db, AT)["used"] == 5


def test_saved_answers_changed_before_click_are_held(client, ready):
    from app.models import SavedFormAnswer
    with ready() as db:
        db.add(SavedFormAnswer(fingerprint=fingerprint(SPEC), spec=SPEC, answer="30",
            profile_version=db.get(ApplicantProfile, 1).version, updated_at=AT))
        db.commit()
        assert consider(db, db.get(Job, "apply"))
        def adapter(snapshot, facts, pdf, before):
            client.delete("/dispatch/answers/" + fingerprint(SPEC)).raise_for_status()
            before()
            pytest.fail("Changed answers must be rechecked")
        process(db, "apply", adapter, lambda *_: None)
        assert db.get(DispatchAttempt, "apply").state == "needs_review"
        assert budget(db, AT)["used"] == 0


def test_declarations_cannot_be_reused(client, ready):
    spec = {**SPEC, "prompt":"I agree to this employer's declaration", "kind":"checkbox", "options":["Yes","No"]}
    with ready() as db:
        remember_questions(db, "apply", [spec])
        db.add(DispatchAttempt(job_id="apply", destination=URL, state="waiting_answers",
                              message="Questions", snapshot={}, updated_at=AT))
        db.commit()
    question = client.get("/dispatch/questions").json()["pending"][0]
    assert answer(client, question, answer="Yes", reuse=True).status_code == 422
    assert answer(client, question, answer="Yes", reuse=False).status_code == 200


def test_dashboard_question_form_preserves_typing_and_saves(client, ready):
    playwright = pytest.importorskip("playwright.sync_api")
    with ready() as db:
        remember_questions(db, "apply", [SPEC])
        db.add(DispatchAttempt(job_id="apply", destination=URL, state="waiting_answers",
                              message="Questions", snapshot={"role":"Developer"}, updated_at=AT))
        db.commit()
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path="/usr/bin/chromium")
        page = browser.new_page()
        def handle(route):
            from urllib.parse import urlsplit
            request = route.request
            url = urlsplit(request.url)
            result = client.request(request.method, url.path + ("?" + url.query if url.query else ""),
                content=request.post_data_buffer, headers={"content-type":request.headers.get("content-type","")})
            route.fulfill(status=result.status_code, body=result.content,
                content_type=result.headers.get("content-type","application/octet-stream"))
        page.route("**/*", handle)
        page.goto("http://localhost/")
        page.locator("#question-alert").click()
        panel = page.locator("#application-questions")
        panel.get_by_label("Your answer (required)").fill("30")
        page.evaluate("loadDispatch()")
        assert panel.get_by_label("Your answer (required)").input_value() == "30"
        panel.get_by_label("Reuse this answer", exact=False).check()
        panel.get_by_role("button", name="Confirm answer and resume automatically").click()
        page.get_by_text("No unanswered application questions.", exact=True).wait_for()
        state = client.get("/dispatch/questions").json()
        assert state["saved_answers"][0]["answer"] == "30"
        assert client.get("/dispatch").json()["schedule"]["used"] == 0
        browser.close()
