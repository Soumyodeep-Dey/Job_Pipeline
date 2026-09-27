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
