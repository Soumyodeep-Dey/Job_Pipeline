# Phase 9.1 — Discovery coverage and visibility

Phase 9.1 explains why imported companies do not necessarily yield visible India jobs. Phase 10 remains reserved for application automation; it is not implemented by this update.

## Flow and purpose

Company workbook -> official career page -> supported board -> public postings -> workbook matching -> stored evidence -> India view -> target designation and other filters.

The Companies & discovery screen now shows each company's latest recorded result, source errors, check time, continuation offset and suggested action. Filter by source category to find unsupported, restricted, missing or untested sources. Refresh workspace after a background task finishes. These are historical results, not a promise that a source works now.

The job screen shows counts before additional status/company/score filters. Generic Remote remains unconfirmed for India; only explicit India locations count. Target-role matching remains separate. No filters have been loosened merely to inflate results.

Legacy Rejected records with discovery-exclusion evidence are counted separately and labelled in job details. This is evidence of a matching-rule exclusion, not proof of employer rejection. Existing statuses and verified submissions are preserved; this release does not silently repair history.

## SmartRecruiters connector

Official career pages can now resolve links to careers.smartrecruiters.com or jobs.smartrecruiters.com. Public posting lists and full descriptions are fetched through the [official Posting API](https://developers.smartrecruiters.com/docs/endpoints). Tokens must come from imported or officially linked URLs; no company slug guessing. Only public postings are requested.

Each batch processes at most ten postings because each needs a detail request within the existing request/time budget. Use next_offset from the run to continue. A failed detail is recorded as an error; retry its batch when resolved. Source restrictions, bounded requests, URL validation and duplicate prevention remain in force. Other custom careers platforms still require their own connectors. Adding this connector does not guarantee new matching India vacancies.

## API and implementation

GET /discovery/diagnostics requires existing owner authentication. It returns the latest company results, category counts, target roles and the visibility funnel without fetching websites or changing jobs. Python/SQLAlchemy aggregate persisted evidence; plain JavaScript renders the diagnostics. No schema migration or new dependency is needed.

## PowerShell verification

```powershell
Set-Location 'D:\OFFICIAL WORK\PROJECTS\Somnath Da\Job_Pipeline'
docker compose config --quiet
docker compose run --build --rm -e TEST_POSTGRES=1 api python -m pytest -q -p no:cacheprovider
docker compose up --build -d --wait
.\.venv\Scripts\python.exe scripts/smoke.py
```

## Next: Phase 10

Application automation needs tested platform adapters, confirmed answers, explicit resume-version approval, duplicate protection and receipt verification. Unsupported questions, captchas and login challenges must pause for user action. Phase 9.1 does not submit applications or send messages.

## Live validation on 3 November 2026

The imported Freshworks official careers page resolved to its SmartRecruiters board; a bounded public posting/detail read succeeded. The imported Visa careers page still did not resolve to a supported board. No career URLs were guessed or workbook records overwritten. Successful fetching does not imply a suitable opening.
