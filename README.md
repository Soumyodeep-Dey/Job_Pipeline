# Job Pipeline

A Python, FastAPI and PostgreSQL project for discovering jobs and tracking applications, built in cumulative phases. **Phase 1 remains the foundation; Phase 2 adds discovery on top of it.**

**Current implementation: Phase 7 protected operation and recovery tools.** Phase 1 imports, tracking APIs, filters and duplicate prevention remain available. Phase 3 automatically approves jobs at 80% or higher required-skill coverage against one imported résumé; lower or unknown coverage needs manual approval. Open the dashboard at http://localhost:8000/ and sign in using AUTH_USERNAME / AUTH_PASSWORD from your private .env file. Background discovery, opt-in schedules and in-app notifications are available. Select a résumé, save a readiness checklist, optionally draft from confirmed facts, record manual submissions and track follow-ups. Résumé generation and external application submission are not implemented.

## All phases and documentation

| Phase | Scope | Status | Guide |
| --- | --- | --- | --- |
| 1 — Data foundation | Excel inspection/imports, company and job tables, tracking APIs, approval rules, Docker and tests | Completed | [Phase 1](docs/PHASE1.md) |
| 2 — Discovery pilot | Official source resolution, Greenhouse/Lever/Ashby feeds, explainable matching, evidence, run history and migrations | Completed as a pilot | [Phase 2](docs/PHASE2.md) |
| 3 — Coverage and matching quality | Audit career URLs and missing profiles, improve role/experience/location interpretation, evaluate decisions, handle larger boards | Implemented with documented matching limits | [Phase 3](docs/PHASE3.md) |
| 4 — Review dashboard | Company selection, discovery controls, job filters, descriptions, explanations and approval controls | Implemented | [Phase 4](docs/PHASE4.md) |
| 5 — Background automation | Workers, schedules, controlled retries, notifications and monitoring; decide whether n8n is useful | Implemented; schedules opt-in | [Phase 5](docs/PHASE5.md) |
| 6 — Application preparation and tracking | Verified profile facts, résumé versions, checklists, optional draft assistance and follow-ups | Implemented | [Phase 6](docs/PHASE6.md) |
| 7 — Reliable deployment | Authentication, deployment, backups, restore testing, monitoring and end-to-end verification | Implemented locally; public deployment configuration prepared | [Phase 7](docs/PHASE7.md) |

An optional Phase 8 for assisted or automatic submission would require separate scope and explicit approval. It is not required to complete version 1. Future phase boundaries may be refined before implementation.

## Where to start

- **Imports and manual tracking:** [Phase 1 guide](docs/PHASE1.md), including workbook findings, the 12 tracker columns, endpoints and PowerShell examples.
- **Upgrading or discovering jobs:** [Phase 2 guide](docs/PHASE2.md), including backup/restore instructions, migrations, the data-flow diagram, matching rules and discovery commands.
- **Résumé import, automatic approval and coverage:** [Phase 3 guide](docs/PHASE3.md), including adding new résumés and the exact scoring formula.
- **Browser dashboard:** [Phase 4 guide](docs/PHASE4.md), including what each screen does, technology choices and approval controls.
- **Background discovery:** [Phase 5 guide](docs/PHASE5.md), including task recovery, retries, schedules, worker health and notifications.
- **Application preparation:** [Phase 6 guide](docs/PHASE6.md), including the data flow, checklist, selected-résumé approval, drafts, submission records and follow-ups.
- **Sign-in, backups and deployment:** [Phase 7 guide](docs/PHASE7.md), including authentication, restore drills, monitoring and HTTPS deployment.
- **Next milestone:** choose a server/domain if public deployment is needed; continue improving India discovery coverage. Optional Phase 8 submission assistance needs separate scope.

## Run the current application

Install Docker Desktop with Linux containers enabled. Keep both original workbooks in `data/`. Before upgrading an existing Phase 1 database, follow the [Phase 2 backup instructions](docs/PHASE2.md#start-or-upgrade-powershell).

Run from PowerShell:

```powershell
Set-Location 'D:\OFFICIAL WORK\PROJECTS\Somnath Da\Job_Pipeline'
.\.venv\Scripts\python.exe scripts/setup_local.py
docker desktop start
docker compose config --quiet
docker compose up --build -d --wait
docker compose ps
Invoke-RestMethod 'http://localhost:8000/health'
.\.venv\Scripts\python.exe scripts/smoke.py
Start-Process 'http://localhost:8000/'
```

If `docker desktop start` is unavailable, open Docker Desktop from the Start menu. The local `.env` uses PostgreSQL host port **55432** because Windows blocked 5432 during setup; `.env.example` retains 5432 for other machines. The API uses port **8000** unless changed in `.env`.

Docker startup applies Alembic migrations before launching the API. This is a single-owner authenticated service bound to localhost. The setup script generates private credentials in `.env`; it preserves existing database settings. See [Phase 7](docs/PHASE7.md) for first-time Python setup, sign-in, authenticated API commands and the separate HTTPS deployment configuration. Public hosting has not been activated.

Import companies before importing or creating jobs:

```powershell
$base = 'http://localhost:8000'
$credential = Get-Credential -UserName 'owner' -Message 'Credentials from .env'
$pair = $credential.UserName + ':' + $credential.GetNetworkCredential().Password
$headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)) }
Remove-Variable pair
Invoke-RestMethod -Method Post "$base/imports/companies" -Headers $headers
Invoke-RestMethod -Method Post "$base/imports/jobs" -Headers $headers
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
│   ├── applications.py      # Phase 6 preparation and follow-up API
│   ├── migrate.py           # Migration entry point
│   └── discovery/           # Phase 2 sources, matching, service and routes
├── migrations/              # Versioned database changes
├── tests/                   # Tracking, discovery and migration tests
├── docs/
│   ├── PHASE1.md            # Preserved foundation guide
│   ├── PHASE2.md            # Discovery pilot guide
│   ├── PHASE3.md            # Coverage, resumes and approval
│   ├── PHASE4.md            # Browser dashboard guide
│   ├── PHASE5.md            # Worker, schedules and notifications
│   ├── PHASE6.md            # Preparation, submissions and follow-ups
│   └── PHASE7.md            # Sign-in, deployment, backups and monitoring
├── resume/                  # Local PDFs; excluded from Git and image
├── backups/                 # Local backups; excluded from Git
├── scripts/                 # Setup, backup/restore verification and smoke checks
├── deploy/Caddyfile          # HTTPS reverse proxy configuration
├── docker-compose.production.yml
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

Phase 3 verification on 2026-09-27: **98 tests passed** across SQLite and PostgreSQL, Docker services healthy, and all four supplied PDF résumés imported with repeat-import deduplication verified. See [Phase 3](docs/PHASE3.md) for the matching limits and how to add new résumés.

Phase 4 verification: **102 tests passed**, Docker rebuilt successfully, and the dashboard was checked in the browser. [Open the dashboard](http://localhost:8000/).

## Documentation convention for future phases

Phase 7 verification (2026-09-30): **169 tests passed, 1 SQLite-only concurrency skip**; final security checks passed on both databases. Local services and authenticated smoke checks passed. A backup was restored into an isolated temporary container and verified (440 companies, 12 jobs, 4 résumé versions). Local and HTTPS Compose configurations validated; public deployment awaits a server/domain. See [Phase 7](docs/PHASE7.md).

Phase 5 verification (2026-09-28): **127 tests passed, 1 SQLite-only concurrency skip**; API, PostgreSQL and worker healthy. A live queued discovery task completed and produced a local notification. No recurring schedules were enabled. See [Phase 5](docs/PHASE5.md).

1. Keep this README as the project-wide overview; do not replace earlier phase documentation with the newest phase.
2. Create `docs/PHASE<N>.md` when starting each phase, following the existing uppercase naming convention.
3. Record its scope, implementation steps, technology choices, data/schema changes, commands, tests, results and limitations.
4. Link the new guide from this README and add navigation to the previous phase.
5. Preserve earlier guides and dated verification results. Clearly label compatibility notes when commands need updating for the current checkout.
6. Update the current-phase label and roadmap status to reflect actual progress. Keep unimplemented features marked as proposed.

India-focus correction (2026-09-28): dashboard defaults to India-location opportunities, retains excluded jobs in history, and rejects placeholder matching profiles. **106 tests passed.** Current pilot source limitations and discovery results are recorded in [Phase 4](docs/PHASE4.md#india-focus-correction--2026-09-28).

## India discovery and master résumé update — 2026-10-03

A full 440-company sweep fetched 2,161 postings from supported sources and populated eight India review candidates. 383 company sources remain unresolved or inaccessible; see the [coverage report and repeatable sweep commands](docs/INDIA_DISCOVERY.md). Matching now retains flagged technical candidates when exact role wording or a company keyword profile is missing. Your selected AI / Full Stack PDF is the single active master via `MASTER_RESUME_ID`; historical versions remain available with `/resumes?include_archived=true`.
