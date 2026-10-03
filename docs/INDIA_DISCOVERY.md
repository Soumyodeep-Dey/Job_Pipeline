# India discovery correction — 2026-10-03

The empty India view did not establish that the listed companies had no openings. Earlier discovery had checked a small pilot, and exact role-phrase gating discarded technical titles that differed from the workbook wording. Atlan, Hevo Data and Acceldata are listed in Company Data but have no company keyword profiles in the supplied workbook.

## Changes

- Discovery still starts exclusively from imported workbook companies and their official career pages.
- An India technical title with at least two demonstrated-skill mentions can be retained for manual review even without an exact workbook role phrase. Its missing title match remains visible in evidence; no title-match points are awarded.
- A listed company without a keyword profile can produce India technical review candidates with score zero and an explicit missing-profile warning. Its rules are not invented or written into the workbook. A conservative seniority-title check still excludes senior/staff/lead/manager roles, and experience checks still apply.
- These fallback candidates have no automatically extracted required-skills list and are not automatically approved. Inspect the live description and enter verified requirements before reassessment, or use the manual review controls.
- Excluded discovery postings cannot acquire automatic approval merely because their descriptions mention matching skills. This preserves location/experience/exclusion gates.
- Existing jobs are deduplicated and existing decisions are preserved.

The 80% résumé rule still applies when explicitly assessing verified requirements. Keyword mentions alone are not mandatory job requirements or evidence that the candidate has a skill.

## Run a workbook-wide sweep

The one-time sweep uses the local Python environment and PostgreSQL connection in `.env`. Docker database must be running. It has up to four concurrent companies, the normal per-company request/response/time limits, and a ceiling of 1,200 postings per company. Large-board results retain `next_offset` for additional discovery. This is an explicit command, not a new recurring schedule.

```powershell
Set-Location 'D:\OFFICIAL WORK\PROJECTS\Somnath Da\Job_Pipeline'
docker compose up -d --wait
.\.venv\Scripts\python.exe scripts/discover_workbook.py --workers 4
# Or repeat only selected companies:
.\.venv\Scripts\python.exe scripts/discover_workbook.py --company-ids 3,4,20 --workers 2
```

Every company attempt appears in API discovery history. A timestamped aggregate JSON report is saved in ignored `backups/discovery-sweep-*.json`. The command runs in the foreground: keep its terminal open. Background scheduling remains available through Phase 5 for supported sources.

Unsupported providers, blocked robots access, obsolete URLs, redirects outside the permitted hosts, and network failures are reported as failures. None means “this company has no vacancies.” No guessed ATS tokens, access-control bypass, or automatic application submission is used.

## Résumé next step

Use one confirmed master résumé as the factual source for later tailoring to shortlisted jobs. Keep original files as historical copies; do not combine claims across versions without verification. Résumé editing and external submissions are separate from this discovery sweep.

The user selected `Soumyodeep_Dey_AI_Full Stack.pdf`. `MASTER_RESUME_ID` in `.env` now selects that content hash; pass it to both API and worker through Compose. `/resumes` shows the active master, while `/resumes?include_archived=true` retains access to historical versions. New automatic assessments and preparations use the master; original PDFs and historical application snapshots are preserved. Changing the master does not silently reassess old jobs.

An editable, fact-preserving résumé draft for Hevo's Associate SDE role is in ignored `resume/master/Soumyodeep_Dey_Resume.md`, with gaps and source notes alongside it. It is not yet a replacement PDF or a submitted application.

## Completed sweep

Verification: 101 local tests passed with 1 SQLite-only concurrency skip; Docker tests passed 178 with the same skip. API/database/worker health and authenticated smoke checks passed. Live checks confirmed one active master, four preserved résumé versions, and eight India candidates. PostgreSQL connection attempts now have a 10-second timeout instead of potentially waiting indefinitely.

All 440 imported companies were attempted on 2026-10-03. There were 2,161 fetched postings and 203 newly tracked jobs, including excluded history. Eight non-rejected India-location candidates are visible in the dashboard; two additional review candidates have unconfirmed remote locations. 383 companies failed source resolution/access. The other 57 companies produced 58 page outcomes (56 completed, 2 partial), including pagination. Source failure is not evidence of no vacancies.

Promising starting points are Hevo Data's Associate Software Development Engineer and CloudSEK's SDE Intern – Frontend. Other retained roles include higher-level or uncertain-fit titles and need description review. No résumé coverage claim or application submission is implied by appearing in the India view.

## Saved India shortlist

These were returned by the providers during this sweep; verify the live vacancy and eligibility before applying. New means pending review, not approved.

| Company | Role | Location | Posting |
| --- | --- | --- | --- |
| Anyscale | Software Engineer, Ray Core | Bengaluru, Karnataka | [Official posting](https://jobs.ashbyhq.com/anyscale/8b29c5e5-d56f-4c52-8887-a6a1827cf042) |
| Hevo Data | Associate Software Development Engineer (SDE) | Bangalore, India | [Official posting](https://jobs.lever.co/hevodata/993a3ed3-3014-432f-b0f4-28d300d58d9a) |
| CloudSEK | SDE Intern - Frontend | Bengaluru, Karnataka, India | [Official posting](https://job-boards.greenhouse.io/cloudsek/jobs/6200261004) |
| Hevo Data | SDE II | Bangalore, India | [Official posting](https://jobs.lever.co/hevodata/53987105-3d28-42b1-9132-3672abcef2aa) |
| Observe.AI | AI Agent Engineer | Hyderabad, Telangana, India | [Official posting](https://www.observe.ai/position?gh_jid=5432596008) |
| Hevo Data | SDE I | Bangalore, India | [Official posting](https://jobs.lever.co/hevodata/6cbbe304-e065-4711-bf3e-756795d2bc2a) |
| Sophos | Data Quality Analyst (Salesforce Data Steward) | Philippines; India | [Official posting](https://jobs.lever.co/sophos/566fcac4-599c-480d-b904-83d01f58cbbf) |
| CloudSEK | SDE - 3 - Frontend | Bengaluru, Karnataka, India | [Official posting](https://job-boards.greenhouse.io/cloudsek/jobs/6139513004) |
