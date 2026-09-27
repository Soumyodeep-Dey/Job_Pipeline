# Job Pipeline

A Python, FastAPI and PostgreSQL project for discovering jobs and tracking applications, built in cumulative phases. **Phase 1 remains the foundation; Phase 2 adds discovery on top of it.**

**Current implementation: Phase 2 discovery pilot.** Phase 1 imports, tracking APIs, filters, duplicate prevention and human approval remain available. There is no dedicated dashboard, scheduled discovery, résumé generation or application submission yet.

## All phases and documentation

| Phase | Scope | Status | Guide |
| --- | --- | --- | --- |
| 1 — Data foundation | Excel inspection/imports, company and job tables, tracking APIs, approval rules, Docker and tests | Completed | [Phase 1](docs/PHASE1.md) |
| 2 — Discovery pilot | Official source resolution, Greenhouse/Lever/Ashby feeds, explainable matching, evidence, run history and migrations | Completed as a pilot | [Phase 2](docs/PHASE2.md) |
| 3 — Coverage and matching quality | Audit career URLs and missing profiles, improve role/experience/location interpretation, evaluate decisions, handle larger boards | Proposed; not implemented | Create `docs/PHASE3.md` when work starts |
| 4 — Review dashboard | Company selection, discovery controls, job filters, descriptions, explanations and approval controls | Proposed; not implemented | Create `docs/PHASE4.md` when work starts |
| 5 — Background automation | Workers, schedules, controlled retries, notifications and monitoring; decide whether n8n is useful | Proposed; not implemented | Create `docs/PHASE5.md` when work starts |
| 6 — Application preparation and tracking | Verified profile facts, résumé versions, checklists, optional draft assistance and follow-ups | Proposed; not implemented | Create `docs/PHASE6.md` when work starts |
| 7 — Reliable deployment | Authentication, deployment, backups, restore testing, monitoring and end-to-end verification | Proposed final phase of version 1 | Create `docs/PHASE7.md` when work starts |

An optional Phase 8 for assisted or automatic submission would require separate scope and explicit approval. It is not required to complete version 1. Future phase boundaries may be refined before implementation.

## Where to start

- **Imports and manual tracking:** [Phase 1 guide](docs/PHASE1.md), including workbook findings, the 12 tracker columns, endpoints and PowerShell examples.
- **Upgrading or discovering jobs:** [Phase 2 guide](docs/PHASE2.md), including backup/restore instructions, migrations, the data-flow diagram, matching rules and discovery commands.
- **Next development milestone:** Phase 3. Evaluate discovery coverage and matching quality before scheduling daily runs.

## Run the current application

Install Docker Desktop with Linux containers enabled. Keep both original workbooks in `data/`. Before upgrading an existing Phase 1 database, follow the [Phase 2 backup instructions](docs/PHASE2.md#start-or-upgrade-powershell).

Run from PowerShell:

```powershell
Set-Location 'D:\OFFICIAL WORK\PROJECTS\Somnath Da\Job_Pipeline'
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker desktop start
docker compose config --quiet
docker compose up --build -d --wait
docker compose ps
Invoke-RestMethod 'http://localhost:8000/health'
Start-Process 'http://localhost:8000/docs'
```

If `docker desktop start` is unavailable, open Docker Desktop from the Start menu. The local `.env` uses PostgreSQL host port **55432** because Windows blocked 5432 during setup; `.env.example` retains 5432 for other machines. The API uses port **8000** unless changed in `.env`.

Docker startup applies Alembic migrations before launching the API. This is currently a single-user local service without authentication. It binds to localhost; human approval records the caller's decision, not a verified reviewer identity.

Import companies before importing or creating jobs:

```powershell
$base = 'http://localhost:8000'
Invoke-RestMethod -Method Post "$base/imports/companies"
Invoke-RestMethod -Method Post "$base/imports/jobs"
```

The supplied tracker originally contained headers only, so its import creates zero jobs unless you add rows. Excel imports are one-way: database updates do not write back to Excel.

## Project structure

```text
Job_Pipeline/
├── data/                    # Original Excel inputs
├── app/
│   ├── database.py          # Database connections and sessions
│   ├── models.py            # Tables and constraints
│   ├── schemas.py           # Tracker validation
│   ├── importer.py          # Excel importers
│   ├── main.py              # Tracking API and startup
│   ├── migrate.py           # Migration entry point
│   └── discovery/           # Phase 2 sources, matching, service and routes
├── migrations/              # Versioned database changes
├── tests/                   # Tracking, discovery and migration tests
├── docs/
│   ├── PHASE1.md            # Preserved foundation guide
│   └── PHASE2.md            # Discovery pilot guide
├── backups/                 # Local backups; excluded from Git
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
├── .env.example
└── README.md                # Overview and index for every phase
```

The main stack is Python, FastAPI, PostgreSQL, SQLAlchemy and Docker Compose. Supporting tools include openpyxl for Excel, HTTPX for source requests, Alembic for migrations, and pytest for tests. Dependency versions are in [requirements.txt](requirements.txt).

## Tests, logs and shutdown

Run the test suite with SQLite and isolated PostgreSQL test schemas:

```powershell
docker compose run --rm -e TEST_POSTGRES=1 api python -m pytest -q -p no:cacheprovider
docker compose logs --tail 100 api db
docker compose down
```

Normal shutdown retains the database volume. Do not add `--volumes` unless you intend to delete its data. Credentials, database backups and source workbooks are excluded from Git.

Recorded verification at phase completion: **45 tests passed for Phase 1**, and **73 for Phase 2**. These are historical results, not fresh test runs. Full results and live-pilot limitations are retained in each phase guide.

## Documentation convention for future phases

1. Keep this README as the project-wide overview; do not replace earlier phase documentation with the newest phase.
2. Create `docs/PHASE<N>.md` when starting each phase, following the existing uppercase naming convention.
3. Record its scope, implementation steps, technology choices, data/schema changes, commands, tests, results and limitations.
4. Link the new guide from this README and add navigation to the previous phase.
5. Preserve earlier guides and dated verification results. Clearly label compatibility notes when commands need updating for the current checkout.
6. Update the current-phase label and roadmap status to reflect actual progress. Keep unimplemented features marked as proposed.
