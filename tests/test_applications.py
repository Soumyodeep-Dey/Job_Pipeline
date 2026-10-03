from datetime import timedelta

import pytest

from app.applications import today
from app.models import Resume


@pytest.fixture
def prepared(client, session_factory):
    with session_factory() as db:
        db.add_all([Resume(id="strong", filename="strong.pdf", text="Python SQL Docker Linux"),
                    Resume(id="weak", filename="weak.pdf", text="Python")])
        db.commit()
    assert client.post('/jobs', json={"job_id": "apply", "company": "Atlan", "role": "Developer",
                                      "location": "India", "required_skills": "Python, SQL, Docker, Linux, React"}).status_code == 201
    return {"resume_id": "strong", "checklist": {"posting_open": True, "location_eligible": True,
                                                 "documents_ready": True},
            "verified_facts": [{"text": "Built a Python API", "evidence": "Portfolio README", "confirmed": True}]}


def submission():
    return {"confirmed_submitted": True, "submitted_on": str(today()), "channel": "Employer site",
            "follow_up_on": str(today())}


def test_auto_approval_submission_freezes_exact_version(client, prepared):
    result = client.put('/jobs/apply/preparation', json=prepared)
    assert result.status_code == 200, result.text
    assert result.json()['ready'] is True
    assert result.json()['selected_resume_match_percent'] == 80
    assert client.get('/jobs/apply/approval').json()['human_approval'] is False
    assert client.post('/jobs/apply/application', json=submission()).status_code == 201
    assert client.post('/jobs/apply/application', json=submission()).status_code == 409
    assert client.put('/jobs/apply/preparation', json=prepared | {'resume_id': 'weak'}).status_code == 409
    snapshot = client.get('/jobs/apply/preparation').json()['preparation']['submission_snapshot']
    assert snapshot['resume_id'] == 'strong'
    assert snapshot['selected_resume_match_percent'] == 80
    assert snapshot['human_approval'] is False
    assert client.get('/dashboard/jobs/apply').json()['status'] == 'Applied'
    assert client.get('/applications?due_only=true').json()[0]['due'] is True
    assert client.patch('/jobs/apply/follow-up', json={'follow_up_on': str(today()), 'done': True}).status_code == 200
    assert client.get('/applications?due_only=true').json() == []
    assert len(client.get('/applications').json()) == 1


def test_selected_weak_resume_requires_manual_approval(client, prepared):
    result = client.put('/jobs/apply/preparation', json=prepared | {'resume_id': 'weak'}).json()
    assert result['ready'] is False
    assert result['selected_resume_match_percent'] == 20
    assert client.post('/jobs/apply/application', json=submission()).status_code == 409
    assert client.patch('/jobs/apply', json={'status': 'Approved', 'human_approval': True}).status_code == 200
    assert client.get('/jobs/apply/preparation').json()['ready'] is True
    assert client.post('/jobs/apply/application', json=submission()).status_code == 201


def test_recheck_current_requirements_and_decision(client, prepared):
    client.put('/jobs/apply/preparation', json=prepared)
    client.post('/jobs/apply/resume-assessment', json={'required_skills': 'Java, Kubernetes'})
    assert client.get('/jobs/apply/preparation').json()['ready'] is False
    assert client.post('/jobs/apply/application', json=submission()).status_code == 409
    client.patch('/jobs/apply', json={'status': 'Rejected'})
    client.put('/jobs/apply/preparation', json=prepared)
    assert client.get('/dashboard/jobs/apply').json()['status'] == 'Rejected'


def test_checklist_unknown_resume_and_confirmation(client, prepared):
    assert client.put('/jobs/apply/preparation', json=prepared | {'resume_id': 'missing'}).status_code == 422
    assert client.get('/jobs/apply/preparation').json()['preparation'] is None
    result = client.put('/jobs/apply/preparation', json=prepared | {'checklist': {}}).json()
    assert len(result['blockers']) == 3
    assert client.post('/jobs/apply/application', json=submission()).status_code == 409
    client.put('/jobs/apply/preparation', json=prepared)
    assert client.post('/jobs/apply/application', json=submission() | {'confirmed_submitted': False}).status_code == 422
    assert client.post('/jobs/apply/application', json=submission() | {'submitted_on': str(today()+timedelta(days=1))}).status_code == 422
    assert client.post('/jobs/apply/application', json=submission() | {'follow_up_on': str(today()-timedelta(days=1))}).status_code == 422


def test_only_confirmed_facts_in_template(client, prepared):
    assert client.post('/jobs/apply/preparation/draft').status_code == 422
    invalid = prepared | {'verified_facts': [{'text': 'Unverified', 'evidence': '', 'confirmed': False}]}
    assert client.put('/jobs/apply/preparation', json=invalid).status_code == 422
    client.put('/jobs/apply/preparation', json=prepared)
    draft = client.post('/jobs/apply/preparation/draft').json()['draft']
    assert 'Built a Python API' in draft
    assert 'Atlan' in draft
    assert 'Docker' not in draft  # No inferred facts from resume keywords.
    assert client.get('/jobs/apply/preparation').json()['preparation']['draft'] == ''


def test_unknown_coverage_manual_and_followup_lifecycle(client, prepared):
    client.post('/jobs/apply/resume-assessment', json={'required_skills': ''})
    result = client.put('/jobs/apply/preparation', json=prepared).json()
    assert result['selected_resume_match_percent'] is None
    assert result['ready'] is False
    assert client.patch('/jobs/apply/follow-up', json={'follow_up_on': None}).status_code == 409
    client.patch('/jobs/apply', json={'status': 'Approved', 'human_approval': True})
    client.post('/jobs/apply/application', json=submission())
    assert client.patch('/jobs/apply/follow-up', json={'follow_up_on': str(today()-timedelta(days=1))}).status_code == 422
    client.patch('/jobs/apply', json={'status': 'Rejected'})
    assert client.get('/applications?due_only=true').json() == []
    client.patch('/jobs/apply/follow-up', json={'follow_up_on': None})
    assert client.get('/applications').json()[0]['follow_up_on'] is None
    assert client.get('/jobs/missing/preparation').status_code == 404


def test_tracker_contract_and_pagination(client, prepared):
    client.put('/jobs/apply/preparation', json=prepared)
    client.post('/jobs/apply/application', json=submission())
    assert len(client.get('/dashboard/jobs/apply').json()) == 12
    assert client.get('/applications?offset=1').json() == []
    assert client.get('/applications?limit=201').status_code == 422


def test_single_master_controls_matching_and_preparation(client, prepared, monkeypatch):
    client.put('/jobs/apply/preparation', json=prepared)
    monkeypatch.setenv('MASTER_RESUME_ID', 'weak')
    assert [r['id'] for r in client.get('/resumes').json()] == ['weak']
    assert len(client.get('/resumes?include_archived=true').json()) == 2
    assert client.get('/jobs/apply/preparation').json()['ready'] is False
    assert client.post('/jobs/apply/application', json=submission()).status_code == 409
    assert client.put('/jobs/apply/preparation', json=prepared).status_code == 422
    assert client.post('/jobs/apply/resume-assessment', json={'resume_id': 'strong'}).status_code == 422
    result = client.post('/jobs/apply/resume-assessment', json={}).json()
    assert result['resume_id'] == 'weak' and result['resume_match_percent'] == 20
    assert result['status'] == 'New'
    monkeypatch.setenv('MASTER_RESUME_ID', 'missing')
    assert client.get('/resumes').json() == []
    result = client.post('/jobs/apply/resume-assessment', json={}).json()
    assert result['resume_match_percent'] is None
    assert result['eligible_for_automatic_approval'] is False
