from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_migrate_fresh_and_adopt_phase1(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
        connection.execute(text("INSERT INTO companies (id, name, name_key, domains, career_pages, keyword_profiles) VALUES (1, 'Existing', 'existing', '[]', '[]', '[]')"))
        connection.execute(text("INSERT INTO jobs (job_id, company_id, role, date_found, status, human_approval) VALUES ('preserved', 1, 'Developer', '2026-09-27', 'Approved', true)"))
        # Simulate an unversioned Phase 1 database and run adoption + upgrade.
        connection.execute(text("DELETE FROM alembic_version"))
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert connection.execute(text("SELECT name FROM companies WHERE id=1")).scalar() == "Existing"
        assert connection.execute(text("SELECT status FROM jobs WHERE job_id='preserved'")).scalar() == "Approved"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
        assert {"discovery_runs", "job_evidence", "matching_profiles"}.issubset(inspect(connection).get_table_names())
        assert len(inspect(connection).get_columns("jobs")) == 14
    engine.dispose()
