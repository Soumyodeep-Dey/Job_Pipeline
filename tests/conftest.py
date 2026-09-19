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
def client(session_factory):
    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    # Tables are created above; do not run the production PostgreSQL startup hook.
    client = TestClient(app)
    yield client
    client.close()
    app.dependency_overrides.clear()
