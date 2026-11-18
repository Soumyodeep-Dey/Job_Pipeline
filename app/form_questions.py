"""Persist employer questions as data. Only the owner can confirm answers."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApplicantProfile, DispatchAttempt, FormQuestion, SavedFormAnswer, Job

router = APIRouter(tags=["Application questions"])
DB = Annotated[Session, Depends(get_db)]


class ReviewNeeded(Exception):
    pass


class QuestionsNeeded(ReviewNeeded):
    def __init__(self, questions):
        self.questions = questions
        super().__init__("Answer the employer questions in Background tasks → Answers needed.")


def fingerprint(spec):
    # Preserve wording, help text, input type and choices. No semantic guessing.
    return sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def profile_version(db):
    profile = db.get(ApplicantProfile, 1)
    return profile.version if profile else 0


def known_answers(db, job_id):
    version = profile_version(db)
    answers = {r.fingerprint: r.answer for r in db.scalars(select(SavedFormAnswer).where(
        SavedFormAnswer.profile_version == version))}
    for row in db.scalars(select(FormQuestion).where(FormQuestion.job_id == job_id)):
        if row.answer is not None and row.profile_version == version:
            answers[row.fingerprint] = row.answer
    return answers


def remember_questions(db, job_id, specs):
    for spec in specs:
        key = fingerprint(spec)
        identifier = sha256((job_id + ":" + key).encode()).hexdigest()
        row = db.get(FormQuestion, identifier)
        if row is None:
            db.add(FormQuestion(id=identifier, job_id=job_id, fingerprint=key, spec=spec,
                updated_at=datetime.now(timezone.utc)))


def questions_resolved(db, job_id):
    rows = db.scalars(select(FormQuestion).where(FormQuestion.job_id == job_id)).all()
    answers = known_answers(db, job_id)
    return bool(rows) and all(r.fingerprint in answers for r in rows)


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    answer: str = Field(max_length=6000)
    reuse: StrictBool = False
    confirmed: Literal[True]
    expected_profile_version: int = Field(ge=0)


@router.get("/dispatch/questions")
def inbox(db: DB):
    version = profile_version(db)
    pending = []
    for row, job, attempt in db.execute(select(FormQuestion, Job, DispatchAttempt)
            .join(Job, Job.job_id == FormQuestion.job_id)
            .join(DispatchAttempt, DispatchAttempt.job_id == Job.job_id)
            .where(DispatchAttempt.state == "waiting_answers").order_by(FormQuestion.updated_at)):
        if row.fingerprint not in known_answers(db, job.job_id):
            pending.append({"id": row.id, "job_id": job.job_id, "role": job.role,
                "location": job.location, "url": attempt.destination, "spec": row.spec})
    saved = db.scalars(select(SavedFormAnswer).order_by(SavedFormAnswer.updated_at.desc())).all()
    return {"profile_version": version, "pending": pending, "saved_answers": [
        {"fingerprint": r.fingerprint, "spec": r.spec, "answer": r.answer,
         "current": r.profile_version == version} for r in saved]}


@router.put("/dispatch/questions/{question_id}")
def answer_question(question_id: str, payload: AnswerInput, db: DB):
    row = db.get(FormQuestion, question_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "Question not found")
    attempt = db.get(DispatchAttempt, row.job_id, with_for_update=True)
    if not attempt or attempt.submission_started_at is not None:
        raise HTTPException(409, "This application has already reached submission. Its answers are frozen.")
    version = profile_version(db)
    if payload.expected_profile_version != version:
        raise HTTPException(409, "Your applicant profile changed. Refresh and confirm the answer again.")
    spec = row.spec
    if not payload.answer and spec["required"]:
        raise HTTPException(422, "This question requires an answer.")
    if payload.answer and spec["kind"] in {"radio", "select-one", "checkbox"} and payload.answer not in spec["options"]:
        raise HTTPException(422, "Choose one of the employer's exact options.")
    if payload.reuse and spec["kind"] == "checkbox":
        raise HTTPException(422, "Checkbox declarations can only be answered for this job.")
    row.answer = payload.answer
    row.profile_version = version
    row.updated_at = datetime.now(timezone.utc)
    if payload.reuse:
        saved = db.get(SavedFormAnswer, row.fingerprint, with_for_update=True)
        if saved is None:
            saved = SavedFormAnswer(fingerprint=row.fingerprint, spec=spec)
            db.add(saved)
        saved.answer = payload.answer
        saved.profile_version = version
        saved.updated_at = row.updated_at
    db.commit()
    return {"message": "Answer saved. The sender will recheck this job within its daily allowance."}


@router.delete("/dispatch/answers/{key}")
def forget_answer(key: str, db: DB):
    row = db.get(SavedFormAnswer, key, with_for_update=True)
    if row is None:
        raise HTTPException(404, "Saved answer not found")
    db.delete(row)
    db.commit()
    return {"message": "Answer will no longer be reused on other jobs."}
