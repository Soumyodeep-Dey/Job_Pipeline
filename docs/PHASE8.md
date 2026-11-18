# Phase 8 — Target roles and approved job-specific resumes

Phase 8 adds changeable target designations and a persistent resume review workflow. The earlier phases remain in place. Job-match approval and resume wording approval are separate: 80% required-skill coverage never approves wording changes.

## What this phase does and why

1. Save AI Engineer, Data Engineer or custom targets in Background tasks. These preferences narrow workbook discovery without changing proven resume skills. India remains the location preference.
2. Daily discovery reuses the existing worker and schedules. Imported companies are split into groups of five, staggered by two minutes, repeating daily. The existing 440-company workspace has 88 groups. Source errors and the 300-posting per-company bound remain visible.
3. Open a job and create a resume proposal from the configured master. The initial proposal adds a short focus line containing only supported explicit required skills and retains the original text. Unknown requirements retain the original text for review. This is conservative, deterministic tailoring, not an AI rewrite.
4. Inspect the original, proposed text, before-and-after diff, requirement evidence and missing skills. Optionally propose a wording revision with the exact passage to replace, replacement text, a verbatim master source quote and a reason. Quotes are checked for provenance; they do not prove the replacement is semantically true. The reviewer must check every claim.
5. Explicitly approve or reject the exact content version. The approval request includes its SHA-256 content hash and a truthful-claims confirmation. Approved versions cannot be edited in place. Creating a new proposal supersedes previous pending/approved versions and requires a fresh review.
6. Approval creates final PDF and DOCX files, stored with file hashes in PostgreSQL. Drafts and rejected versions cannot be exported as approved resumes. Exports use a simple text layout; they do not preserve the master PDF's original visual design or embedded hyperlinks.
7. Preparation requires the current approved proposal from the selected master, the normal job approval and the eligibility/document checklist. A changed master, job description or required-skill list invalidates approval for future use. Coverage for readiness is calculated from the approved content.
8. Record a completed external application through the existing workflow. The frozen snapshot includes the exact proposal, content/file hashes, reviewer and approval time. Submitted jobs cannot receive new proposals; their original approved files remain downloadable even if later job facts change.

## Dashboard steps

Open Job review, select a job, and find **Review job-specific resume** below the job assessment controls. Select the master, create a proposal, expand the original/proposed/diff panels, and inspect the evidence. Use the revision form if needed. Check the truthful-claims confirmation and click **Approve this resume and create exports** only when you approve that exact wording. Download PDF or DOCX, save the application preparation checklist, then apply on the employer site. Record the application only after confirmation.

A job marked Approved may still show a resume-review blocker. This is intentional. Rejected proposals require a new version. Creating a fresh proposal from the master discards earlier edits from the new version while preserving their history.

## Data and implementation

Migration 0006 adds `resume_proposals`. Each record belongs to one job and one imported master and stores an immutable proposed text, master snapshot, job fingerprint, evidence, status, review identity/time and approved export bytes with hashes. The original 12 job business fields stay unchanged. Existing applications, including Observe.AI, are preserved.

FastAPI validates requests; SQLAlchemy and PostgreSQL store records transactionally. Mutating proposal and submission actions lock the job row to serialize changes on PostgreSQL. Python difflib produces reviewable differences. ReportLab creates PDFs and python-docx creates DOCX files after approval. No cloud model or API key is needed. A future LLM may propose better wording, but it must keep the evidence and explicit review gate.

Status progression: pending → approved or rejected. A new proposal supersedes earlier pending/approved versions. Staleness is checked separately against current master and job facts. The dashboard lists the latest 50 versions; records remain stored in the database.

## Endpoints

- `GET /jobs/{job_id}/resume-proposals`: latest 50 proposals and evidence.
- `POST /jobs/{job_id}/resume-proposals`: create a pending version; optional supported edits.
- `POST /jobs/{job_id}/resume-proposals/{proposal_id}/review`: approve or reject the displayed content hash.
- `GET /jobs/{job_id}/resume-proposals/{proposal_id}/export/pdf`: approved PDF.
- `GET /jobs/{job_id}/resume-proposals/{proposal_id}/export/docx`: approved DOCX.
- Existing preparation and application-recording endpoints now enforce current resume approval for the normal workflow.

The historical `application-receipt` endpoint remains an explicit record of an already completed external action. It never submits an application and does not assert that the pipeline approved it. Its purpose is accurate history, not a path for sending unapproved resumes. Direct historical job status updates likewise do not create a submission or an approved artifact.

## Upgrade and checks in PowerShell

```powershell
Set-Location 'D:\OFFICIAL WORK\PROJECTS\Somnath Da\Job_Pipeline'
.\.venv\Scripts\python.exe scripts/backup.py create
docker compose config --quiet
docker compose build api worker
docker compose run --rm -e TEST_POSTGRES=1 api python -m pytest -q -p no:cacheprovider
docker compose up -d --wait
.\.venv\Scripts\python.exe scripts/smoke.py
Start-Process 'http://localhost:8000/'
```

The API startup command runs Alembic before Uvicorn. Keep the pre-upgrade backup. Restore older backups with the corresponding application release; the verification script expects the current revision. Never run `docker compose down -v` as an upgrade step. Local non-Docker tests need the new requirements installed in the virtual environment.

## Limits and next phases

No automatic employer submission, broader job-board account connections or Docker Gmail OAuth are added here. Codex Gmail monitoring remains separate. Source access, India eligibility, closed postings and missing form answers still need verification. Export files are final only after the user's approval; they do not establish eligibility or truth beyond the evidence reviewed.

Next, improve the confirmed applicant profile and requirement extraction, then implement and test one submission adapter with receipts and duplicate protection before expanding to more platforms. Phase 8 delivers the approval and artifact boundary that those adapters must use.
