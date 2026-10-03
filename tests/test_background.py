from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import background
from app.models import BackgroundTask, DiscoveryRun, DiscoverySchedule, Notification, WorkerState


def queue(client):
    response = client.post('/discovery/tasks', json={'company_ids': [1]})
    assert response.status_code == 202
    return response.json()['id']


def test_queue_cancel_and_validation(client, session_factory):
    assert client.post('/discovery/tasks', json={'company_ids': [999]}).status_code == 422
    assert client.post('/discovery/tasks', json={'company_ids': [1] * 6}).status_code == 422
    identifier = queue(client)
    assert client.get('/discovery/tasks/' + identifier).json()['attempts'] == 0
    assert client.post(f'/discovery/tasks/{identifier}/cancel').json()['status'] == 'cancelled'
    with session_factory() as db:
        assert background.claim(db) is None
    assert client.post(f'/discovery/tasks/{identifier}/cancel').status_code == 409
    assert client.get('/discovery/tasks/missing').status_code == 404


def test_claim_completion_notification(client, session_factory, monkeypatch):
    identifier = queue(client)
    with session_factory() as db:
        assert background.claim(db) == identifier
        assert background.claim(db) is None
    assert client.post(f'/discovery/tasks/{identifier}/cancel').status_code == 409
    monkeypatch.setattr(background, 'run_discovery', lambda *a, **kw: SimpleNamespace(status='completed'))
    background.execute(session_factory, identifier)
    result = client.get('/discovery/tasks/' + identifier).json()
    assert result['status'] == 'completed' and result['attempts'] == 1 and len(result['run_ids']) == 1
    notification = client.get('/notifications').json()[0]
    assert notification['task_id'] == identifier
    assert client.post(f"/notifications/{notification['id']}/read").status_code == 200
    assert client.get('/notifications').json() == []


def test_retries_are_bounded_and_backed_off(client, session_factory, monkeypatch):
    identifier = queue(client)
    def fail(*a, **kw):
        raise RuntimeError('private data must not be saved')
    monkeypatch.setattr(background, 'run_discovery', fail)
    for attempt in range(1, 4):
        with session_factory() as db:
            task = db.get(BackgroundTask, identifier)
            task.available_at = background.now() - timedelta(seconds=1)
            db.commit()
            assert background.claim(db) == identifier
        background.execute(session_factory, identifier)
        with session_factory() as db:
            task = db.get(BackgroundTask, identifier)
            assert task.attempts == attempt
            assert 'private data' not in task.error
            if attempt < 3:
                assert task.status == 'queued'
                assert background.claim(db) is None
            else:
                assert task.status == 'failed'
    assert len(client.get('/notifications').json()) == 1


@pytest.mark.parametrize('status', ['partial', 'failed'])
def test_source_outcomes_do_not_retry(client, session_factory, monkeypatch, status):
    identifier = queue(client)
    with session_factory() as db:
        background.claim(db)
    monkeypatch.setattr(background, 'run_discovery', lambda *a, **kw: SimpleNamespace(status=status))
    background.execute(session_factory, identifier)
    assert client.get('/discovery/tasks/' + identifier).json()['status'] == status


def test_invalid_config_does_not_retry(client, session_factory, monkeypatch):
    identifier = queue(client)
    with session_factory() as db:
        background.claim(db)
    def fail(*a, **kw):
        raise ValueError('Import the workbook first')
    monkeypatch.setattr(background, 'run_discovery', fail)
    background.execute(session_factory, identifier)
    assert client.get('/discovery/tasks/' + identifier).json()['status'] == 'failed'


def test_crash_recovery_keeps_run_history(client, session_factory):
    identifier = queue(client)
    with session_factory() as db:
        background.claim(db)
        task = db.get(BackgroundTask, identifier)
        db.add(DiscoveryRun(id=task.run_ids[-1], status='running', profile_snapshot={}, results=[{'created': 2}]))
        db.commit()
        background.recover(db)
        assert task.status == 'queued'
        run = db.get(DiscoveryRun, task.run_ids[-1])
        assert run.status == 'interrupted' and run.results == [{'created': 2}]
        assert task.attempts == 1


def test_schedules_opt_in_coalesce_and_pause(client, session_factory):
    body = {'name': 'India pilot', 'discovery': {'company_ids': [1]}, 'interval_minutes': 15}
    schedule = client.post('/discovery/schedules', json=body).json()
    assert schedule['enabled'] is False
    with session_factory() as db:
        stored = db.get(DiscoverySchedule, schedule['id'])
        stored.next_run_at = background.now() - timedelta(days=10)
        db.commit()
        background.schedule_due(db)
        assert list(db.scalars(select(BackgroundTask))) == []
    assert client.patch('/discovery/schedules/' + schedule['id'], json={'enabled': True}).status_code == 200
    with session_factory() as db:
        stored = db.get(DiscoverySchedule, schedule['id'])
        stored.next_run_at = background.now() - timedelta(days=10)
        db.commit()
        background.schedule_due(db)
        assert len(list(db.scalars(select(BackgroundTask)))) == 1
        stored.next_run_at = background.now() - timedelta(minutes=1)
        db.commit()
        background.schedule_due(db)
        assert len(list(db.scalars(select(BackgroundTask)))) == 1
    assert client.patch('/discovery/schedules/' + schedule['id'], json={'enabled': False}).json()['enabled'] is False
    assert client.post('/discovery/schedules', json=body | {'interval_minutes': 1}).status_code == 422


def test_worker_health(client, session_factory):
    assert client.get('/worker/health').json()['status'] == 'offline'
    with session_factory() as db:
        db.add(WorkerState(id=1, last_seen=background.now()))
        db.commit()
    assert client.get('/worker/health').json()['status'] == 'healthy'


def test_completed_run_recovered_without_replaying(client, session_factory):
    identifier = queue(client)
    with session_factory() as db:
        background.claim(db)
        task = db.get(BackgroundTask, identifier)
        db.add(DiscoveryRun(id=task.run_ids[-1], status='completed', profile_snapshot={}, results=[]))
        db.commit()
        background.recover(db)
        assert task.status == 'completed' and task.attempts == 1
        assert background.claim(db) is None
    assert len(client.get('/notifications').json()) == 1


def test_postgres_claim_skips_row_locked_by_other_session(client, session_factory):
    first, second = queue(client), queue(client)
    with session_factory() as lock_db, session_factory() as claim_db:
        if lock_db.bind.dialect.name != 'postgresql':
            pytest.skip('Row-level concurrency is checked on PostgreSQL')
        lock_db.scalar(select(BackgroundTask).where(BackgroundTask.id == first).with_for_update())
        assert background.claim(claim_db) == second
        lock_db.rollback()
        assert background.claim(claim_db) == first
