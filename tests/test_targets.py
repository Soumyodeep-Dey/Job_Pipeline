from types import SimpleNamespace

from sqlalchemy import select

from app.applications import readiness
from app.background import enqueue
from app.discovery.matching import evaluate, target_role_matches
from app.discovery.schemas import CandidateProfile
from app.models import BackgroundTask, DiscoverySchedule, MatchingProfile


def test_roles_preserve_skills_and_validate(client):
    before = client.get('/matching-profile').json()
    response = client.put('/target-settings', json={'target_roles': ['AI Engineer', 'Data Engineer'],
        'india_work_preference': 'relocation_office_hybrid'})
    assert response.status_code == 200
    after = client.get('/matching-profile').json()
    assert after['demonstrated_skills'] == before['demonstrated_skills']
    assert after['locations'] == before['locations']
    assert client.put('/target-settings', json={'target_roles': [' '], 'india_work_preference': 'unconfirmed'}).status_code == 422
    assert client.put('/target-settings', json={'target_roles': [], 'india_work_preference': 'unconfirmed'}).status_code == 422


def test_target_gate_beats_technical_fallback():
    profile = CandidateProfile(target_roles=['AI Engineer', 'Data Engineer'])
    company = SimpleNamespace(keyword_profiles=[])
    weights = dict(title=35, skills=30, experience=20, location=15, exclusion=-100)
    posting = dict(title='Frontend Engineer', description='Python SQL', location='India')
    assert evaluate(posting, company, profile, {}, weights)['disposition'] == 'irrelevant'
    posting['title'] = 'Junior AI Agent Engineer'
    result = evaluate(posting, company, profile, {}, weights)
    assert result['target_role_matches'] == ['AI Engineer']
    assert result['disposition'] == 'review_required'
    assert not target_role_matches('Data Scientist', profile.target_roles)
    assert not target_role_matches('Retail Engineer', profile.target_roles)
    assert target_role_matches('ETL Developer', profile.target_roles) == ['Data Engineer']


def test_existing_jobs_follow_changed_roles_before_pagination(client):
    for index, role in enumerate(['Frontend Engineer', 'AI Engineer', 'Data Engineer']):
        assert client.post('/jobs', json={'job_id': str(index), 'company': 'Atlan', 'role': role,
            'location': 'India', 'source_url': f'https://example.com/{index}'}).status_code == 201
    for role in ['AI Engineer', 'Data Engineer']:
        client.put('/target-settings', json={'target_roles': [role], 'india_work_preference': 'unconfirmed'})
        rows = client.get('/jobs?scope=india&target_only=true&limit=1').json()
        assert len(rows) == 1 and rows[0]['role'] == role
        assert len(client.get('/jobs?target_only=false').json()) == 3


def test_managed_schedules_idempotent_and_pause_cancels_queue(client, session_factory):
    client.put('/target-settings', json={'target_roles': ['Data Engineer'], 'india_work_preference': 'unconfirmed'})
    for _ in range(2):
        result = client.put('/target-settings/automation', json={'enabled': True})
        assert result.status_code == 200
        assert result.json()['total_batches'] == 1
    with session_factory() as db:
        schedule = db.scalar(select(DiscoverySchedule))
        task = enqueue(db, schedule.payload, schedule.id)
        db.commit()
        task_id = task.id
    result = client.put('/target-settings/automation', json={'enabled': False})
    assert result.json()['enabled_batches'] == 0
    with session_factory() as db:
        assert db.get(BackgroundTask, task_id).status == 'cancelled'


def test_changed_roles_block_preparation_without_changing_status(session_factory):
    with session_factory() as db:
        db.add(MatchingProfile(id=1, settings=CandidateProfile(target_roles=['Data Engineer']).model_dump()))
        db.commit()
        job = SimpleNamespace(role='Frontend Engineer', status='Approved', human_approval=True)
        state = readiness(db, job, None)
        assert 'Job is outside the current target designations' in state['blockers']
        assert job.status == 'Approved'
