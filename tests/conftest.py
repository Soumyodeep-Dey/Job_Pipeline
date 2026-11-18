import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DATABASE_URL, get_db
from app.main import app
from app.models import Company


@pytest.fixture(autouse=True)
def isolate_master_selection(monkeypatch):
    monkeypatch.delenv("MASTER_RESUME_ID", raising=False)


@pytest.fixture(params=["sqlite", "postgres"] if os.getenv("TEST_POSTGRES") == "1" else ["sqlite"])
def session_factory(request):
    schema = None
    if request.param == "postgres":
        # Each test owns a fresh schema; public application tables are untouched.
        base_engine = create_engine(DATABASE_URL)
        schema = "test_" + uuid4().hex
        with base_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = base_engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(Company(name="Atlan", name_key="atlan", domains=["Data"], career_pages=[], keyword_profiles=[]))
        db.commit()
    try:
        yield factory
    finally:
        if schema:
            with base_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


@pytest.fixture
def client(session_factory, monkeypatch):
    monkeypatch.setenv("AUTH_USERNAME", "test-owner")
    monkeypatch.setenv("AUTH_PASSWORD", "test-password-long-enough-for-tests")
    monkeypatch.delenv("PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("DEPLOYMENT_MODE", "local")
    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    # Tables are created above; do not run the production PostgreSQL startup hook.
    app.middleware_stack = None
    client = TestClient(app, base_url="http://localhost")
    client.auth = ("test-owner", "test-password-long-enough-for-tests")
    yield client
    client.close()
    app.dependency_overrides.clear()


def confirm_phase9(client, job_id):
    """Explicit synthetic confirmations for legacy preparation scenarios."""
    profile=client.get('/applicant-profile').json()
    if not profile['version']:
        response=client.put('/applicant-profile',json={'expected_version':0,'confirmed':True,'data':{
            'full_name':'Test Applicant','india_work_authorized':True,'requires_sponsorship':False,
            'work_modes':['remote','hybrid','on_site'],'willing_relocate_india':True,
            'current_city':'Bengaluru','experience_years':2,'notice_days':0}})
        assert response.status_code==200,response.text
    req=client.get('/jobs/'+job_id+'/requirements').json()
    if not req['review_current']:
        data=req['suggested']['data'] | {'india_eligible':True,'work_mode':'remote','unresolved_requirements':[]}
        response=client.put('/jobs/'+job_id+'/requirements',json={'expected_version':req['version'],
            'source_hash':req['source_hash'],'confirmed':True,'review_note':'Confirmed synthetic test requirements','data':data})
        assert response.status_code==200,response.text
