# Job Pipeline — Phase 1

A local FastAPI service backed by PostgreSQL. It imports your Excel sources, stores companies and jobs, and supports manual application tracking. It does not scrape jobs, compute match scores, run n8n, generate résumés, or submit applications.

## What was inspected

`data/Domain wise Company Data.xlsx` has four sheets:

- **Company Data:** three blocks at A:C, E:G and I:K. There are 452 company entries and 440 unique names. The `Carrer Page (Link)` cells display “Careers”; the importer reads the actual hyperlinks.
- **Keywords for DATA:** company headers on row 3, plus 5,000 search phrases and matching rules, including scoring weights.
- **Keywords for AI:** company headers on row 4, plus 4,022 search phrases and matching rules.
- **Keywords for Cyber:** company headers on row 3, keyword-bank headers on row 5, plus 4,823 search phrases and matching rules.

`data/Application Tracker.xlsx` has one sheet, `Sheet1`, with the following 12 columns and no job rows. Therefore, importing the supplied tracker initially creates zero jobs.

| Excel column | API field | Storage / meaning |
| --- | --- | --- |
| Job ID | `job_id` | Unique text primary key; generated UUID if omitted |
| Company | `company` | Company name in API; `company_id` foreign key in database |
| Role | `role` | Required text |
| Location | `location` | Optional text |
| Required Skills | `required_skills` | Optional text, e.g. comma-separated skills |
| Match Score | `match_score` | Optional number from 0 to 100; not automatically calculated |
| Missing Skills | `missing_skills` | Optional text |
| Source URL | `source_url` | Optional unique HTTP(S) URL |
| Date Found | `date_found` | Date; defaults to the API server's current date |
| Status | `status` | Defaults to `New` |
| Resume Version | `resume_version` | Optional text |
| Human Approval | `human_approval` | Boolean; defaults to false |

## Project structure

```text
Job_Pipeline/
├── data/                     # Both original workbooks; mounted read-only
├── app/
│   ├── database.py           # Engine and request sessions
│   ├── models.py             # SQLAlchemy tables and database constraints
│   ├── schemas.py            # Validation and the twelve job fields
│   ├── importer.py           # Workbook layouts, hyperlinks and import reports
│   └── main.py               # FastAPI routes and startup
├── tests/                    # API, constraints and actual-workbook tests
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

Development order: inspect the sources, define tables and validation, implement imports, add routes, configure containers, then test. `companies` stores all domains and career pages for each normalized company name. Sheet-specific keyword profiles retain keywords, exclusions, packs, guardrails and source rows. `discovery_config` stores each sheet's full keyword bank, matching rules, weights, notes and reference rows without duplicating the banks for every company. `jobs` holds the tracker fields, using a foreign key for Company.

The matching rules are preserved as configuration for a later phase; Phase 1 does not execute discovery or scoring. No score is invented when the tracker has a blank Match Score.

## Start with Docker Desktop (PowerShell)

Install Docker Desktop with Linux containers enabled. Run these commands from PowerShell. The commands below use the current project location exactly; change the first line if you move this folder.

```powershell
Set-Location 'D:\OFFICIAL WORK\PROJECTS\Somnath Da\Job_Pipeline'
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker desktop start
docker compose --env-file .env config --quiet
docker compose up --build -d --wait
docker compose ps
Invoke-RestMethod -Uri 'http://localhost:8000/health'
Start-Process 'http://localhost:8000/docs'
```

If your Docker Desktop version does not support `docker desktop start`, open Docker Desktop from the Start menu and wait until the engine is running. `/docs` is the interactive API interface.

Compose starts PostgreSQL first and waits for its health check before starting the API. PostgreSQL data lives in a named volume and survives `docker compose down`. Both published ports bind to `127.0.0.1`. This is a single-user local service without authentication; Human Approval records the caller's explicit decision, not a verified reviewer identity.

`.env.example` contains local development credentials. If you change credentials, update `DATABASE_URL` for local Python as well. Use URL-safe characters in Compose credentials; URL-reserved characters need URL encoding in connection URLs. PostgreSQL initialization settings apply only when the data volume is first created. Changing `.env` does not change an existing database user's password. Change `API_PORT` or `POSTGRES_PORT` if a host port is occupied; adjust the example URLs or local `DATABASE_URL` accordingly.

## Import the two workbooks

The no-body endpoints read the fixed filenames from `data/`. Import companies first.

```powershell
$base = 'http://localhost:8000'
Invoke-RestMethod -Method Post -Uri "$base/imports/companies"
Invoke-RestMethod -Method Post -Uri "$base/imports/jobs"
Invoke-RestMethod -Uri "$base/companies?limit=500"
```

Alternatively upload a workbook using `/docs`, or use `curl.exe` (works in Windows PowerShell 5.1 and PowerShell 7):

```powershell
curl.exe --fail-with-body -X POST 'http://localhost:8000/imports/companies' -F 'file=@data/Domain wise Company Data.xlsx'
curl.exe --fail-with-body -X POST 'http://localhost:8000/imports/jobs' -F 'file=@data/Application Tracker.xlsx'
```

Company imports refresh metadata for names present in the workbook. Matching is case-insensitive, collapses repeated whitespace, and treats curly/straight apostrophes alike (the source varies these in Moody's and Lowe's India). Reimporting does not create duplicate companies or duplicate keyword profiles. Multiple domains and career URLs are preserved. Companies removed from the workbook remain in the database so existing job links remain valid. A malformed company workbook is rejected before any company changes are committed.

Tracker import rules:

- Keep exactly the original 12 headers in their original order. One sheet must match them.
- Company and Role are required. Company must already exist in the company source.
- Each Excel job row needs a Job ID or Source URL, so reimporting can identify it. A URL-only row receives a generated Job ID. Manual API creation can omit both and receives a UUID.
- Job IDs are global, case-sensitive text identifiers. If employer IDs overlap, prefix them with the company name. URLs are compared exactly after trimming whitespace; differing query strings or trailing slashes are different URLs.
- Blank optional cells stay empty. Missing Status becomes `New`; Date Found defaults to today. Enter dates as real Excel dates or `YYYY-MM-DD` text. Enter Match Score as points, e.g. `80`, not Excel `80%` (which stores `0.8`).
- Human Approval accepts `Yes/No`, `True/False`, `1/0`, or blank (false). Unrecognized values are errors. The API accepts boolean `true`/`false`.
- Formula cells in tracker rows are rejected. Source URL hyperlinks are supported.
- Duplicate Job ID **or** Source URL skips the row and never overwrites an existing job or its approval.
- Valid rows are committed even if other rows fail. The response includes `created`, `duplicates`, `duplicate_rows`, and `errors` with Excel row numbers. Inspect the response: HTTP 200 does not mean every row was valid.
- Uploads are limited to 20 MB compressed and 100 MB uncompressed.

## Create, filter and approve a job

```powershell
$base = 'http://localhost:8000'
$newJob = @{
    job_id = 'demo-atlan-001'
    company = 'Atlan'
    role = 'Junior Python Developer'
    location = 'Remote India'
    required_skills = 'Python, SQL, FastAPI'
    match_score = 80
    missing_skills = 'Kafka'
    source_url = 'https://example.com/jobs/demo-atlan-001'
    date_found = (Get-Date -Format 'yyyy-MM-dd')
    status = 'New'
    resume_version = 'resume-v1'
    human_approval = $false
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/jobs" -ContentType 'application/json' -Body $newJob

Invoke-RestMethod -Uri "$base/jobs?company=Atlan&status=New&location=India&min_match_score=75"

# Set these only after personally reviewing the job.
$approval = @{ status = 'Approved'; human_approval = $true } | ConvertTo-Json
Invoke-RestMethod -Method Patch -Uri "$base/jobs/demo-atlan-001" -ContentType 'application/json' -Body $approval

# Revoking approval requires moving out of Approved in the same request.
$revoke = @{ status = 'Shortlisted'; human_approval = $false } | ConvertTo-Json
Invoke-RestMethod -Method Patch -Uri "$base/jobs/demo-atlan-001" -ContentType 'application/json' -Body $revoke
```

This is a demonstration record, not a discovered live opening. Repeating the create command returns HTTP 409 because the ID and URL already exist.

Valid statuses: `New`, `Shortlisted`, `Approved`, `Applied`, `Interview`, `Rejected`, `Offer`, `Withdrawn`. They are case-sensitive. Statuses are manual tracker labels; setting Applied does not submit anything. Both API validation and a database check require human approval for Approved status, including direct SQL writes. Approval can be granted separately or in the same request as Approved status.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Checks database connectivity; 503 if unavailable |
| POST | `/imports/companies` | Import mounted or uploaded company workbook |
| POST | `/imports/jobs` | Import mounted or uploaded tracker |
| GET | `/companies` | List companies, domains, URLs and keyword profiles |
| GET | `/discovery-config` | Read all stored keyword banks and original rules |
| POST | `/jobs` | Create a job; 409 for duplicate ID or URL |
| GET | `/jobs` | Filter by company, status, location and minimum score |
| PATCH | `/jobs/{job_id}` | Update status and/or human approval |

Company and location filters are case-insensitive literal substring matches. Combined filters use AND. A minimum score excludes jobs with no score. Company/job lists accept `offset` (default 0) and `limit` (default 50, maximum 500). No arbitrary file paths are accepted by import endpoints.

## Run tests

With Docker running (no local Python required):

```powershell
docker compose run --rm --no-deps api python -m pytest -q -p no:cacheprovider
```

Tests use isolated in-memory SQLite databases, with foreign keys enabled. They do not modify the running PostgreSQL database. They cover actual workbook layouts and counts, import idempotency, row errors, hyperlinks, duplicates, filters, approval checks and database constraints. Source-workbook integration tests skip when the original files are absent.

To also run the same database/API tests against PostgreSQL:

```powershell
docker compose run --rm -e TEST_POSTGRES=1 api python -m pytest -q -p no:cacheprovider
```

This creates and removes randomly named `test_...` schemas in the configured PostgreSQL database. The application's public tables are untouched. The database user needs permission to create schemas (the Compose development user has it).

For local Python development, install Python 3.12 and use:

```powershell
Set-Location 'D:\OFFICIAL WORK\PROJECTS\Somnath Da\Job_Pipeline'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d db --wait
# Stop the container API if it already occupies port 8000.
docker compose stop api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

No activation command or PowerShell execution-policy change is needed. On the original development machine, Python was available through Codex's bundled runtime rather than on PATH; the project `.venv` was created with it. Use the installed Python launcher on another machine.

## Logs and shutdown

```powershell
docker compose logs --tail 100 api db
docker compose down
```

Keep the PostgreSQL named volume to retain jobs. `docker compose down --volumes` would delete that database, so it is not part of normal shutdown. Source Excel files are never rewritten and are excluded from Git because they may contain personal application information; copy them into `data/` on a new checkout.

Tables are created automatically on startup with SQLAlchemy `create_all`. This bootstraps Phase 1 but does not migrate an existing schema. Add a migration workflow before future schema changes.

## Verification on this machine

- Local Python test run: **23 passed**.
- Container test run with SQLite and PostgreSQL: **45 passed**. One dependency deprecation warning from Starlette/AnyIO; no test failures.
- `docker compose config --quiet` passed; the API image built successfully and both containers became healthy.
- Live `/health` returned `{"status":"ok","database":"ok"}`.
- Live imports created **440 companies**, stored **13,845 keyword-bank entries**, and created **0 jobs** from the supplied header-only tracker.
- Windows blocked host port 5432. The local, Git-ignored `.env` therefore sets `POSTGRES_PORT=55432` and uses `localhost:55432` in `DATABASE_URL`. `.env.example` retains the conventional default for other machines.
- The containers were left running. Open `http://localhost:8000/docs` to use the API, or run `docker compose down` to stop them while retaining data.
