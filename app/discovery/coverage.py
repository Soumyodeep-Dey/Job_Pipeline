"""Report source gaps without inventing workbook rules or career URLs."""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company
from app.discovery.schemas import DiscoveryRequest
from app.discovery.sources import Fetcher, SourceError, board_from_url, resolve_board

router = APIRouter(tags=["Phase 3 coverage"])


@router.get("/discovery/coverage")
def coverage(db: Session = Depends(get_db), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    companies = db.scalars(select(Company).order_by(Company.id).offset(offset).limit(limit))
    return [{"company_id": c.id, "company": c.name, "career_pages": c.career_pages,
             "missing_career_page": not c.career_pages, "missing_keyword_profile": not c.keyword_profiles,
             "direct_supported_board": any(board_from_url(url) is not None for url in c.career_pages),
             "action": "Correct missing information in the company workbook and reimport; use source-audits to check links."}
            for c in companies]


@router.post("/discovery/source-audits")
def audit(payload: DiscoveryRequest, db: Session = Depends(get_db)):
    companies = [db.get(Company, identifier) for identifier in payload.company_ids]
    if any(c is None for c in companies):
        raise HTTPException(422, "Unknown company ID")
    results = []
    for company in companies:
        fetcher = Fetcher()
        attempts = []
        try:
            for url in company.career_pages[:3]:
                try:
                    board = resolve_board(url, fetcher)
                    attempts.append({"url": url, "status": "supported", "board_url": board.url, "provider": board.provider})
                except SourceError as exc:
                    attempts.append({"url": url, "status": "unresolved", "message": str(exc)})
        finally:
            fetcher.close()
        results.append({"company_id": company.id, "missing_keyword_profile": not company.keyword_profiles,
                        "attempts": attempts, "unexamined_urls": max(0, len(company.career_pages) - 3)})
    return {"results": results, "note": "Point-in-time source checks; no jobs created or workbook data changed."}


@router.get("/discovery/diagnostics")
def diagnostics(db: Session = Depends(get_db)):
    """Latest company result and exact visibility funnel; no network or writes."""
    from collections import Counter
    from app.models import DiscoveryRun, Job, JobEvidence
    from app.discovery.location import india_opportunity
    from app.discovery.matching import target_role_matches, contains
    from app.discovery.location import INDIA_LOCATIONS
    from app.discovery.service import get_profile
    latest = {}
    for run in db.scalars(select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc(), DiscoveryRun.id.desc())):
        for result in run.results:
            identifier = result.get('company_id')
            if identifier not in latest:
                latest[identifier] = {**result, 'run_id': run.id, 'checked_at': run.started_at.isoformat()}
    rows = []
    for company in db.scalars(select(Company).order_by(Company.name)):
        result = latest.get(company.id)
        messages = [] if not result else [*result.get('errors', []), *[a.get('message','') for a in result.get('source_attempts',[])]]
        message = ' '.join(messages).lower()
        if not company.career_pages: category, action = 'missing_url', 'Correct the company workbook career URL and reimport.'
        elif result is None: category, action = 'not_checked', 'Select this company and run a source audit or discovery.'
        elif result.get('status') == 'completed': category, action = 'completed', 'Inspect fetched, excluded and duplicate counts; success does not guarantee suitable openings.'
        elif 'robots' in message: category, action = 'access_restricted', 'Use an officially linked supported feed when available; do not bypass source restrictions.'
        elif 'unsupported' in message or 'no supported board' in message: category, action = 'unsupported', 'Verify the official career link; this source may need another connector.'
        elif result.get('truncated'): category, action = 'more_pages', 'Continue from the reported next_offset.'
        else: category, action = 'source_error', 'Inspect the source error and retry only after resolving it.'
        rows.append({'company_id': company.id, 'company': company.name, 'career_pages': company.career_pages,
                     'category': category, 'action': action, 'latest': result, 'errors': messages})
    jobs = db.scalars(select(Job)).all()
    evidence = {e.job_id:e for e in db.scalars(select(JobEvidence))}
    roles = get_profile(db).target_roles
    india = [j for j in jobs if india_opportunity(j)]
    excluded = [j for j in jobs if j.status == 'Rejected' and j.job_id in evidence and evidence[j.job_id].explanation.get('disposition') == 'excluded']
    return {'companies': rows, 'source_summary': dict(Counter(r['category'] for r in rows)),
            'funnel': {'stored_jobs':len(jobs), 'explicit_india_location':sum(any(contains(j.location or '',v) for v in INDIA_LOCATIONS) for j in jobs),
                       'india_visible':len(india), 'india_target_visible':sum(bool(not roles or target_role_matches(j.role,roles)) for j in india),
                       'legacy_rejected_with_discovery_exclusion':len(excluded)},
            'target_roles': roles, 'note':'Counts precede company/status/score filters. Rejected with discovery exclusion evidence is not proof of employer rejection. Latest source results are historical, not live availability checks.'}
