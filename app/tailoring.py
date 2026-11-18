"""Human reviewed, job-specific resumes. Job approval never approves wording."""
from datetime import datetime, timezone
from difflib import unified_diff
from hashlib import sha256
import json
import os
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApplicationPreparation, Company, Job, JobEvidence, Resume, ResumeProposal
from app.resumes import master_resume_id, resume_contains, skills_list
from app.resume_exports import export_resume

router = APIRouter(tags=['Resume review and export'])
DB = Annotated[Session, Depends(get_db)]

def digest(value):
    return sha256(value.encode('utf-8')).hexdigest()

def normalized(value):
    return value.replace('\ufffd', '-').replace('\r\n', '\n').strip()

def fingerprint(db, job):
    evidence = db.get(JobEvidence, job.job_id)
    from app.models import JobRequirementReview
    review = db.get(JobRequirementReview, job.job_id)
    review_marker = {'requirements_review_version': review.version} if review else {}
    return digest(json.dumps({**review_marker, 'role': job.role, 'company': job.company_id, 'location': job.location,
        'source_url': job.source_url, 'required_skills': job.required_skills,
        'description': evidence.description if evidence else ''}, sort_keys=True))

def latest(db, job_id):
    return db.scalar(select(ResumeProposal).where(ResumeProposal.job_id == job_id)
        .order_by(ResumeProposal.created_at.desc(), ResumeProposal.id.desc()).limit(1))

def stale_reason(db, job, proposal):
    master = db.get(Resume, proposal.master_id)
    if master is None or normalized(master.text) != proposal.master_text:
        return 'Master resume content changed; create a new proposal'
    if master_resume_id(db) != proposal.master_id:
        return 'Configured master resume changed; create a new proposal'
    if fingerprint(db, job) != proposal.job_fingerprint:
        return 'Job requirements or description changed; create a new proposal'
    return None

def approved_proposal(db, job):
    proposal = latest(db, job.job_id)
    if proposal is None or proposal.status != 'approved':
        return None, 'Review and approve the current job-specific resume version'
    reason = stale_reason(db, job, proposal)
    if reason:
        return None, reason
    if not proposal.pdf or not proposal.docx:
        return None, 'Approved resume exports are missing'
    return proposal, None

def get_job(db, job_id, lock=False):
    stmt = select(Job).where(Job.job_id == job_id)
    job = db.scalar(stmt.with_for_update() if lock else stmt)
    if job is None:
        raise HTTPException(404, 'Job not found')
    return job

def editable(db, job):
    prep = db.get(ApplicationPreparation, job.job_id)
    if (prep and prep.submitted_on) or job.status in ('Applied', 'Interview', 'Offer', 'Withdrawn'):
        raise HTTPException(409, 'Submitted jobs are frozen; their resume history is preserved')

def response(db, job, proposal):
    if proposal is None:
        return None
    return {'id': proposal.id, 'job_id': proposal.job_id, 'master_id': proposal.master_id,
        'created_at': proposal.created_at, 'reviewed_at': proposal.reviewed_at,
        'reviewed_by': proposal.reviewed_by, 'status': proposal.status,
        'original': proposal.master_text, 'proposed': proposal.content,
        'content_sha256': proposal.content_sha256, 'evidence': proposal.evidence,
        'diff': '\n'.join(unified_diff(proposal.master_text.splitlines(), proposal.content.splitlines(),
                         fromfile='Master resume', tofile='Proposed resume', lineterm='')),
        'stale_reason': stale_reason(db, job, proposal),
        'pdf_sha256': proposal.pdf_sha256, 'docx_sha256': proposal.docx_sha256}

class Edit(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    before: str = Field(min_length=1, max_length=4000)
    after: str = Field(min_length=1, max_length=4000)
    source_quote: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=1000)

class ProposalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    resume_id: str | None = None
    edits: list[Edit] = Field(default_factory=list, max_length=20)

class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['approve', 'reject']
    content_sha256: str = Field(min_length=64, max_length=64)
    confirmed_truthful: bool = False

@router.get('/jobs/{job_id}/resume-proposals')
def proposals(job_id: str, db: DB):
    job = get_job(db, job_id)
    return [response(db, job, p) for p in db.scalars(select(ResumeProposal)
        .where(ResumeProposal.job_id == job_id).order_by(ResumeProposal.created_at.desc(), ResumeProposal.id.desc()).limit(50))]

@router.post('/jobs/{job_id}/resume-proposals', status_code=201)
def create_proposal(job_id: str, payload: ProposalInput, db: DB):
    job = get_job(db, job_id, True)
    editable(db, job)
    selected = master_resume_id(db)
    if master_resume_id(db) and payload.resume_id and payload.resume_id != master_resume_id(db):
        raise HTTPException(422, 'Use the configured master resume')
    master = db.get(Resume, selected) if selected else None
    if master is None:
        raise HTTPException(422, 'Select an imported master resume first')
    original = normalized(master.text)
    comparison = []
    for skill in skills_list(job.required_skills):
        supported = resume_contains(original, skill)
        quotes = [line.strip() for line in original.splitlines() if resume_contains(line, skill)]
        comparison.append({'requirement': skill, 'supported': supported, 'source_quote': quotes[0] if quotes else ''})
    matched = [r['requirement'] for r in comparison if r['supported']]
    # Conservative tailoring: spotlight only supported requirements; retain every original fact.
    focus = 'Skills relevant to this role: ' + ', '.join(matched) if matched else ''
    lines = original.splitlines()
    content = '\n'.join([lines[0], focus, *lines[1:]]) if focus else original
    for edit in payload.edits:
        if edit.source_quote not in original:
            raise HTTPException(422, 'Each source quote must occur verbatim in the master resume')
        if content.count(edit.before) != 1:
            raise HTTPException(422, 'Each before passage must occur exactly once in the proposed resume')
        content = content.replace(edit.before, edit.after, 1)
    if len(content) > 60000:
        raise HTTPException(422, 'Proposal exceeds 60000 characters')
    for old in db.scalars(select(ResumeProposal).where(ResumeProposal.job_id == job_id,
                           ResumeProposal.status.in_(['pending', 'approved']))):
        old.status = 'superseded'
    proposal = ResumeProposal(id=str(uuid4()), job_id=job_id, master_id=master.id,
        created_at=datetime.now(timezone.utc), status='pending', master_text=original,
        job_fingerprint=fingerprint(db, job), content=content, content_sha256=digest(content),
        evidence={'requirements': comparison, 'edits': [e.model_dump() for e in payload.edits],
            'automatic_change': focus or 'No explicit supported requirements; original text retained for review',
            'review_note': 'Source quotes establish provenance, not semantic proof of an edit. Review all wording, dates and claims. Keyword matches do not establish proficiency.'})
    db.add(proposal)
    db.commit()
    return response(db, job, proposal)

@router.post('/jobs/{job_id}/resume-proposals/{proposal_id}/review')
def review(job_id: str, proposal_id: str, payload: ReviewInput, db: DB):
    job = get_job(db, job_id, True)
    editable(db, job)
    proposal = db.get(ResumeProposal, proposal_id)
    if proposal is None or proposal.job_id != job_id:
        raise HTTPException(404, 'Proposal not found for this job')
    if proposal.status != 'pending' or latest(db, job_id).id != proposal.id:
        raise HTTPException(409, 'Only the current pending proposal can be reviewed')
    if payload.content_sha256 != proposal.content_sha256:
        raise HTTPException(409, 'The displayed version does not match; reload and review it')
    reason = stale_reason(db, job, proposal)
    if reason:
        raise HTTPException(409, reason)
    if payload.decision == 'approve':
        if not payload.confirmed_truthful:
            raise HTTPException(422, 'Confirm that you reviewed the exact version and its claims are truthful')
        pdf, word = export_resume(proposal.content)
        proposal.pdf, proposal.docx = pdf, word
        proposal.pdf_sha256, proposal.docx_sha256 = sha256(pdf).hexdigest(), sha256(word).hexdigest()
        proposal.status = 'approved'
    else:
        proposal.status = 'rejected'
    proposal.reviewed_at = datetime.now(timezone.utc)
    proposal.reviewed_by = os.getenv('AUTH_USERNAME', 'workspace-owner')
    db.commit()
    return response(db, job, proposal)

@router.get('/jobs/{job_id}/resume-proposals/{proposal_id}/export/{format}')
def download(job_id: str, proposal_id: str, format: Literal['pdf', 'docx'], db: DB):
    job = get_job(db, job_id)
    proposal = db.get(ResumeProposal, proposal_id)
    if proposal is None or proposal.job_id != job_id:
        raise HTTPException(404, 'Proposal not found for this job')
    prep = db.get(ApplicationPreparation, job_id)
    historical = bool(prep and prep.submitted_on and (prep.submission_snapshot or {}).get('resume_proposal_id') == proposal.id)
    if not historical:
        current, reason = approved_proposal(db, job)
        if reason or current.id != proposal.id:
            raise HTTPException(409, reason or 'Export only the current approved version')
    data = getattr(proposal, format)
    if not data:
        raise HTTPException(409, 'Export unavailable')
    return Response(data, media_type='application/pdf' if format == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="resume-{proposal.id}.{format}"',
                 'X-Content-SHA256': getattr(proposal, format + '_sha256')})
