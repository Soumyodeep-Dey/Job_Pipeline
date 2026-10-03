from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.discovery.matching import evaluate, workbook_weights
from app.discovery.schemas import CandidateProfile
from app.discovery.sources import Fetcher, SourceError, fetch_jobs, resolve_board
from app.importer import duplicate_job, build_job
from app.models import Company, DiscoveryConfig, DiscoveryRun, JobEvidence, MatchingProfile
from app.schemas import JobCreate
from app.resumes import explicit_requirements


def get_profile(db):
    stored = db.get(MatchingProfile, 1)
    return CandidateProfile(**stored.settings) if stored else CandidateProfile()


def run_discovery(db, request, run_id=None):
    companies = [db.get(Company, identifier) for identifier in request.company_ids]
    if any(company is None for company in companies):
        raise ValueError("Unknown company ID; list /companies and select existing IDs")
    configs = {config.sheet: config for config in db.scalars(select(DiscoveryConfig))}
    weights = workbook_weights(configs)
    candidate = get_profile(db)
    run = DiscoveryRun(id=run_id or str(uuid4()), status="running", profile_snapshot=candidate.model_dump(), results=[])
    db.add(run)
    db.commit()
    results = []
    for company in companies:
        result = {"company_id": company.id, "company": company.name, "status": "completed",
                  "fetched": 0, "created": 0, "duplicates": 0, "irrelevant": 0, "excluded": 0,
                  "review_required": 0, "auto_approved": 0, "errors": [], "truncated": False}
        fetcher = Fetcher()
        try:
            board = None
            attempts = []
            # Cross-domain companies may have several official URLs. Try at most three.
            for career_page in company.career_pages[:3]:
                try:
                    board = resolve_board(career_page, fetcher)
                    break
                except SourceError as exc:
                    attempts.append({"career_page": career_page, "message": str(exc)})
            if board is None:
                result["source_attempts"] = attempts
                raise SourceError("No supported board resolved from the company's official career pages")
            result.update(provider=board.provider, board_url=board.url, career_page=career_page)
            jobs, errors, truncated = fetch_jobs(board, fetcher, request.max_jobs_per_company, request.job_offset)
            result.update(fetched=len(jobs), errors=errors, truncated=truncated)
            result["next_offset"] = request.job_offset + request.max_jobs_per_company if truncated else None
            for posting in jobs:
                explanation = evaluate(posting, company, candidate, configs, weights)
                if explanation["disposition"] == "irrelevant":
                    result["irrelevant"] += 1
                    continue
                # Stable across reruns and namespaced across companies and providers.
                key = f"{company.id}:{board.provider}:{board.token}:{posting['external_id']}"
                job_id = "discovered-" + sha256(key.encode()).hexdigest()[:40]
                payload = JobCreate(job_id=job_id, company=company.name, role=posting["title"],
                    location=posting["location"] or None, match_score=explanation["score"],
                    source_url=posting["url"], date_found=date.today(),
                    required_skills=explicit_requirements(posting["description"]) if explanation["title_matches"] and explanation["disposition"] == "review_required" else None,
                    # Skill keyword mentions are exposed in evidence, not asserted as requirements.
                    status="Rejected" if explanation["disposition"] == "excluded" else "New",
                    human_approval=False)
                if duplicate_job(db, payload):
                    result["duplicates"] += 1
                    continue
                try:
                    with db.begin_nested():
                        job = build_job(db, payload)
                        db.add(job)
                        db.flush()
                        db.add(JobEvidence(job_id=job_id, run_id=run.id, provider=board.provider,
                            board_url=board.url, career_page=career_page, description=posting["description"],
                            explanation=explanation))
                        db.flush()
                    result["created"] += 1
                    if job.auto_approved:
                        result["auto_approved"] += 1
                    else:
                        result[explanation["disposition"]] += 1
                except IntegrityError:
                    if duplicate_job(db, payload):
                        result["duplicates"] += 1
                    else:
                        result["errors"].append(f"Posting {posting['external_id']}: database constraint rejected row")
            if result["errors"] or result["truncated"]:
                result["status"] = "partial"
        except (SourceError, ValueError) as exc:
            result["status"] = "failed"
            result["errors"].append(str(exc)[:500])
        finally:
            fetcher.close()
        results.append(result)
        run.results = list(results)
        db.commit()
    run.finished_at = datetime.now(timezone.utc)
    statuses = [r["status"] for r in results]
    run.status = "completed" if all(s == "completed" for s in statuses) else "failed" if all(s == "failed" for s in statuses) else "partial"
    db.commit()
    return run
