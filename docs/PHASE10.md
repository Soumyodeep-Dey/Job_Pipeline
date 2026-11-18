# Phase 10 — Automatic applications

Current schedule and saved-answer behaviour are described in [Phase 10.1](PHASE10_1.md). The sender now runs from 9 AM India time with a maximum of five submission starts per day.

Keep Docker Desktop running. The discovery worker searches the companies and roles selected in Background tasks. A separate sender checks candidate jobs every 30 seconds. **Background tasks → Automatic applications** controls external sending. Its setting persists across restarts. New installations start paused. Pause prevents new clicks once the worker observes the change. A request already in flight can finish.

1. Set your target roles and enable discovery. In Applicant profile, confirm the answers employers may receive. Unknown facts stay blank.
2. When the sender is enabled, it prepares a résumé proposal for discovered India jobs matching your target roles. In Job review, verify the posting requirements, resolve eligibility questions and approve the exact résumé wording. Changes to the source or master require a fresh version. The 80% coverage rule controls job approval. It does not approve résumé wording.
3. For eligible approved jobs, the sender checks the employer feed for the exact posting, title, location, description and URL. When no preparation exists, these checks and the approved PDF supply the readiness checklist. A previously saved incomplete checklist stays open for you to finish.
4. The worker opens supported public employer forms using a fresh Chromium session. It uses confirmed profile answers, verifies the destination and uploads the approved PDF. Foreign redirects, unrecognized mandatory questions, authentication and visible verification challenges need review. A changed posting requires a fresh review.
5. Before clicking Submit, the worker checks current approval and saves a durable attempt. A positive employer confirmation freezes the résumé fingerprint, profile version, submitted answers and receipt, then marks the job Applied. An ambiguous send is held for reconciliation. It is never automatically repeated. Use the existing receipt flow for a separately verified external submission.

**Current form coverage.** The automatic adapter recognizes single-page Ashby, Lever and Greenhouse forms on the provider's hosted domain and tenant recorded during discovery. Employer customizations can still require an assisted submission. SmartRecruiters is available for discovery. Custom sites, LinkedIn, Naukri, Foundit, Cutshort, YC and Wellfound require assisted submission. Platform account sessions and passwords are not supplied to the sender. Gmail monitoring remains the existing separate monitor.

**Diagnostics.** Each job shows its readiness blockers. Background tasks shows the latest 100 attempts. An attempt stopped before submission can be rechecked after correcting its cause. An uncertain result requires checking the employer portal or a receipt before taking any further action. Already submitted jobs are excluded on restart.

**PowerShell**

```powershell
Set-Location 'D:\OFFICIAL WORK\PROJECTS\Somnath Da\Job_Pipeline'
.\.venv\Scripts\python.exe scripts/backup.py create
docker compose config --quiet
docker compose up --build -d --wait
docker compose ps
.\.venv\Scripts\python.exe scripts/smoke.py
Start-Process 'http://localhost:8000/'
```

**Tests**

```powershell
docker compose run --build --rm -e TEST_POSTGRES=1 api python -m pytest -q -p no:cacheprovider
docker compose run --build --no-deps --rm sender python -m pytest tests/test_dispatch.py -q -p no:cacheprovider
```

Browser tests intercept network requests and use synthetic data. The automated adapters have not been verified by sending real applications across every supported provider.

**API.** GET /dispatch returns the switch and recent attempts. PUT /dispatch accepts an enabled boolean. GET /jobs/{job_id}/dispatch explains current blockers. POST /jobs/{job_id}/dispatch/recheck releases a pre-submit hold. All use existing owner authentication. Migration 0009 adds the control and attempts tables.
