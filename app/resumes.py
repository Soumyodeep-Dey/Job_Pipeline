"""Local résumé versions and transparent required-skill coverage (not hiring probability)."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.discovery.matching import ALIASES, contains
from app.models import Job, Resume, ResumeAssessment

router = APIRouter()
RESUME_DIR = Path(__file__).resolve().parent.parent / "resume"


def explicit_requirements(description):
    # Only a clearly labeled list is machine-readable. General JD mentions are
    # not silently converted into mandatory requirements.
    match = re.search(r"(?:required skills|mandatory skills)\s*:\s*([^\n]+)", description, re.I)
    if not match:
        return None
    value = re.split(r"\.(?:\s|$)|\b(?:preferred|responsibilities|benefits|qualifications)\s*:", match[1], maxsplit=1, flags=re.I)[0]
    terms = skills_list(value)
    if not terms or any(len(term.split()) > 5 or len(term) > 80 for term in terms):
        return None
    return ", ".join(terms)


def skills_list(value):
    """One requirement per comma/semicolon/newline; aliases count only once."""
    aliases = {alias: ("react" if key == "react.js" else key) for key, variants in ALIASES.items() for alias in variants}
    aliases.update({"react.js": "react", "react": "react"})
    return sorted({aliases.get(s.strip().casefold(), s.strip().casefold())
                   for s in re.split(r"[,;\n]", value or "") if s.strip()})


def resume_contains(text, skill):
    if skill in ("c", "c++", "c#"):
        return re.search(r"(?<![\w+#])" + re.escape(skill) + r"(?![\w+#])", text, re.I) is not None
    return contains(text, skill)


def assess(db, job, resume_id=None):
    requirements = skills_list(job.required_skills)
    resumes = list(db.scalars(select(Resume).order_by(Resume.id)))
    if resume_id:
        resumes = [r for r in resumes if r.id == resume_id]
        if not resumes:
            raise ValueError("Unknown resume ID")
    candidates = []
    for resume in resumes:
        matched = [skill for skill in requirements if resume_contains(resume.text, skill)]
        score = 100 * len(matched) / len(requirements) if requirements else None
        candidates.append((score or 0, resume, matched, score))
    best = max(candidates, key=lambda c: c[0]) if candidates else None
    score = best[3] if best else None
    automatic = score is not None and score >= 80
    result = {"policy": "required-skills-v1", "threshold": 80,
              "resume_id": best[1].id if best else None,
              "resume_filename": best[1].filename if best else None,
              "resume_match_percent": score, "required_skills": requirements,
              "matched_skills": best[2] if best else [],
              "missing_skills": [s for s in requirements if not best or s not in best[2]],
              "eligible_for_automatic_approval": automatic,
              "reason": "Required-skill coverage" if score is not None else "Résumé or explicit required skills unavailable",
              "limitations": "Text evidence only; does not establish proficiency, experience, location eligibility or hiring probability."}
    # Explicit reevaluation updates pending/approved records, never application outcomes.
    if job.status in ("New", "Shortlisted", "Approved", "Rejected"):
        job.auto_approved = automatic and not job.human_approval
        job.resume_match_percent = score
        if automatic and not job.human_approval:
            job.status = "Approved"
            job.resume_version = best[1].filename + "#" + best[1].id[:12]
        elif job.status == "Approved" and not job.human_approval:
            job.status = "New"
    return result


def store_resume(db, filename, content):
    from pypdf import PdfReader
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("PDF exceeds 10 MB")
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Upload a PDF résumé")
    identifier = sha256(content).hexdigest()
    if db.get(Resume, identifier):
        return {"filename": filename, "status": "duplicate", "id": identifier}
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted or len(reader.pages) > 20:
        raise ValueError("Use an unencrypted résumé of at most 20 pages")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(text.strip()) < 100:
        raise ValueError("Insufficient extractable text; OCR is not implemented")
    db.add(Resume(id=identifier, filename=filename, text=text))
    db.flush()
    return {"filename": filename, "status": "imported", "id": identifier}


@router.post("/imports/resumes")
def import_resumes(db: Session = Depends(get_db), file: UploadFile | None = File(default=None)):
    if file is not None:
        try:
            with db.begin_nested():
                result = store_resume(db, Path(file.filename or "resume.pdf").name,
                                      file.file.read(10 * 1024 * 1024 + 1))
            db.commit()
            return {"results": [result]}
        except Exception as exc:
            db.rollback()
            raise HTTPException(422, "Cannot import résumé: " + str(exc)[:200]) from exc
    results = []
    for path in sorted(RESUME_DIR.glob("*.pdf")):
        try:
            if path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("PDF exceeds 10 MB")
            with db.begin_nested():
                result = store_resume(db, path.name, path.read_bytes())
            results.append(result)
        except Exception as exc:
            results.append({"filename": path.name, "status": "error", "message": str(exc)[:200]})
    db.commit()
    return {"results": results, "note": "Existing jobs are unchanged; explicitly reassess them if needed."}


@router.get("/resumes")
def list_resumes(db: Session = Depends(get_db)):
    return [{"id": r.id, "filename": r.filename} for r in db.scalars(select(Resume).order_by(Resume.filename))]


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_id: str | None = None
    required_skills: str | None = Field(None, max_length=10000)


@router.post("/jobs/{job_id}/resume-assessment")
def reassess(job_id: str, payload: AssessmentRequest, db: Session = Depends(get_db)):
    job = db.scalar(select(Job).where(Job.job_id == job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "Job not found")
    if payload.required_skills is not None:
        job.required_skills = payload.required_skills
    try:
        result = assess(db, job, payload.resume_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    db.add(ResumeAssessment(job_id=job_id, result=result))
    db.commit()
    return result | {"status": job.status, "human_approval": job.human_approval}


@router.get("/jobs/{job_id}/resume-assessments")
def assessments(job_id: str, db: Session = Depends(get_db)):
    if db.get(Job, job_id) is None:
        raise HTTPException(404, "Job not found")
    return [{"id": r.id, "created_at": r.created_at, **r.result}
            for r in db.scalars(select(ResumeAssessment).where(ResumeAssessment.job_id == job_id)
                                .order_by(ResumeAssessment.id))]


@router.get("/jobs/{job_id}/approval")
def approval(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {"status": job.status, "human_approval": job.human_approval,
            "automatic_approval": job.auto_approved, "resume_match_percent": job.resume_match_percent,
            "resume_version": job.resume_version,
            "method": "manual" if job.human_approval else "automatic" if job.auto_approved else "pending"}
