"""One-time bounded sweep of imported workbook companies. No applications sent."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.database import DATABASE_URL
from app.discovery.schemas import DiscoveryRequest
from app.discovery.service import run_discovery
from app.models import Company

SessionLocal = sessionmaker(bind=create_engine(DATABASE_URL, pool_pre_ping=True,
                           connect_args={"connect_timeout": 10}), expire_on_commit=False)


def discover(identifier):
    with SessionLocal() as db:
        run = run_discovery(db, DiscoveryRequest(company_ids=[identifier], max_jobs_per_company=300))
        results = list(run.results)
        # Continue large boards, bounded to 1,200 postings per company per sweep.
        while results[-1].get('next_offset') is not None and results[-1]['next_offset'] < 1200:
            run = run_discovery(db, DiscoveryRequest(company_ids=[identifier], max_jobs_per_company=300,
                                                     job_offset=results[-1]['next_offset']))
            results.extend(run.results)
        return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company-ids', help='Comma-separated IDs; default: all imported companies')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    args = parser.parse_args()
    with SessionLocal() as db:
        ids = [int(x) for x in args.company_ids.split(',')] if args.company_ids else list(db.scalars(select(Company.id)))
    print('Starting sweep:', len(ids), 'companies', flush=True)
    directory = Path(__file__).resolve().parents[1] / 'backups'
    directory.mkdir(exist_ok=True)
    path = directory / ('discovery-sweep-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(discover, identifier): identifier for identifier in ids}
        for future in as_completed(futures):
            try:
                rows = future.result()
            except Exception as exc:
                rows = [{'company_id': futures[future], 'status': 'failed', 'errors': [type(exc).__name__]}]
            results.extend(rows)
            path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            for row in rows:
                print(row.get('company', row['company_id']), row['status'], 'created', row.get('created', 0),
                      'review', row.get('review_required', 0), flush=True)
    print('Report:', path, flush=True)
