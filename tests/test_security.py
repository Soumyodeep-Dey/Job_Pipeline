from datetime import timedelta

import pytest

from app.background import now
from app.models import WorkerState
from app.operations import VERSION_TABLE
from app.security import validate_security


@pytest.mark.parametrize('path', ['/', '/jobs', '/resumes', '/companies', '/docs', '/openapi.json',
                                  '/static/app.js', '/applications', '/operations/health'])
def test_every_private_surface_requires_login(client, path):
    response = client.get(path, auth=None)
    assert response.status_code == 401
    assert response.headers['www-authenticate'].startswith('Basic ')
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/health', auth=None).status_code == 200


def test_wrong_credentials_and_fail_closed(client, monkeypatch):
    for value in ['Basic invalid', 'Bearer token', 'Basic /w==']:
        assert client.get('/jobs', auth=None, headers={'Authorization': value}).status_code == 401
    assert client.get('/jobs', auth=('wrong', 'wrong')).status_code == 401
    assert client.get('/jobs').status_code == 200
    monkeypatch.setenv('AUTH_PASSWORD', '')
    assert client.get('/jobs').status_code == 503
    with pytest.raises(RuntimeError):
        validate_security()


def test_cross_site_write_blocked_same_origin_and_cli_work(client):
    payload = {'job_id': 'secure', 'company': 'Atlan', 'role': 'Developer'}
    assert client.post('/jobs', json=payload, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/jobs', json=payload, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.post('/jobs', json=payload, headers={'Origin': 'http://localhost'}).status_code == 201
    assert client.patch('/jobs/secure', json={'status': 'Shortlisted'}).status_code == 200
    assert client.get('/jobs', headers={'Host': 'evil.example'}).status_code == 400


def test_security_headers_and_rate_limit(client):
    response = client.get('/jobs')
    assert response.headers['x-frame-options'] == 'DENY'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert len(response.headers['x-request-id']) == 32
    for _ in range(10):
        assert client.get('/jobs', auth=('bad', 'bad')).status_code == 401
    response = client.get('/jobs', auth=('bad', 'bad'))
    assert response.status_code == 429
    assert response.headers['retry-after'] == '60'
    assert client.get('/health', auth=None).status_code == 200


def test_production_configuration(client, monkeypatch):
    monkeypatch.setenv('DEPLOYMENT_MODE', 'production')
    monkeypatch.setenv('PUBLIC_ORIGIN', 'http://jobs.example.com')
    with pytest.raises(RuntimeError):
        validate_security()
    monkeypatch.setenv('PUBLIC_ORIGIN', 'https://jobs.example.com')
    monkeypatch.setenv('ALLOWED_HOSTS', 'localhost,jobs.example.com')
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://owner:short@db/pipeline')
    with pytest.raises(RuntimeError):
        validate_security()
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://owner:long-random-password-for-test-only@db/pipeline')
    validate_security()
    monkeypatch.setenv('ALLOWED_HOSTS', '*')
    with pytest.raises(RuntimeError):
        validate_security()


def test_readiness_and_worker_monitor(client, session_factory):
    assert client.get('/ready', auth=None).status_code == 503
    with session_factory() as db:
        VERSION_TABLE.create(db.connection())
        db.execute(VERSION_TABLE.insert().values(version_num='0005'))
        db.commit()
    assert client.get('/ready', auth=None).json() == {'status': 'ready'}
    assert client.get('/operations/health').status_code == 503
    with session_factory() as db:
        db.add(WorkerState(id=1, last_seen=now()))
        db.commit()
    assert client.get('/operations/health').json()['status'] == 'healthy'
    with session_factory() as db:
        db.get(WorkerState, 1).last_seen = now() - timedelta(minutes=2)
        db.commit()
    assert client.get('/operations/health').status_code == 503
