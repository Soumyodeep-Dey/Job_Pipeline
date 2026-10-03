from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    name_key: Mapped[str] = mapped_column(Text, unique=True)
    domains: Mapped[list] = mapped_column(JSON, default=list)
    career_pages: Mapped[list] = mapped_column(JSON, default=list)
    # Keep separate sheet-specific profiles so cross-domain companies lose no rules.
    keyword_profiles: Mapped[list] = mapped_column(JSON, default=list)


class DiscoveryConfig(Base):
    __tablename__ = "discovery_config"

    sheet: Mapped[str] = mapped_column(Text, primary_key=True)
    keyword_bank: Mapped[list] = mapped_column(JSON)
    rules: Mapped[list] = mapped_column(JSON)
    notes: Mapped[list] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status != 'Approved' OR human_approval = true OR (auto_approved = true AND resume_match_percent IS NOT NULL AND resume_match_percent >= 80)", name="approval_required"),
        CheckConstraint("match_score IS NULL OR (match_score >= 0 AND match_score <= 100)", name="score_range"),
        CheckConstraint("length(trim(job_id)) > 0", name="nonempty_job_id"),
        CheckConstraint("source_url IS NULL OR length(trim(source_url)) > 0", name="nonempty_source_url"),
        CheckConstraint("status IN ('New', 'Shortlisted', 'Approved', 'Applied', 'Interview', 'Rejected', 'Offer', 'Withdrawn')", name="valid_status"),
    )

    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    resume_match_percent: Mapped[float | None] = mapped_column(Float)

    # The twelve business fields mirror the tracker; Company is a foreign key.
    job_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    role: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    required_skills: Mapped[str | None] = mapped_column(Text)
    match_score: Mapped[float | None] = mapped_column(Float)
    missing_skills: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text, unique=True)
    date_found: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="New", index=True)
    resume_version: Mapped[str | None] = mapped_column(Text)
    human_approval: Mapped[bool] = mapped_column(Boolean, default=False)


class MatchingProfile(Base):
    __tablename__ = "matching_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    settings: Mapped[dict] = mapped_column(JSON)


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30))
    profile_snapshot: Mapped[dict] = mapped_column(JSON)
    results: Mapped[list] = mapped_column(JSON, default=list)


class JobEvidence(Base):
    __tablename__ = "job_evidence"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    board_url: Mapped[str] = mapped_column(Text)
    career_page: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    explanation: Mapped[dict] = mapped_column(JSON)


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)


class ResumeAssessment(Base):
    __tablename__ = "resume_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    result: Mapped[dict] = mapped_column(JSON)


class DiscoverySchedule(Base):
    __tablename__ = "discovery_schedules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    interval_minutes: Mapped[int] = mapped_column()
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BackgroundTask(Base):
    __tablename__ = "background_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("discovery_schedules.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    run_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("background_tasks.id"), unique=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkerState(Base):
    __tablename__ = "worker_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationPreparation(Base):
    __tablename__ = "application_preparations"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id"), primary_key=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"))
    verified_facts: Mapped[list] = mapped_column(JSON, default=list)
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    draft: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    submitted_on: Mapped[date | None] = mapped_column(Date)
    channel: Mapped[str | None] = mapped_column(String(100))
    reference: Mapped[str | None] = mapped_column(Text)
    submission_snapshot: Mapped[dict | None] = mapped_column(JSON)
    follow_up_on: Mapped[date | None] = mapped_column(Date, index=True)
    follow_up_done: Mapped[bool] = mapped_column(Boolean, default=False)
