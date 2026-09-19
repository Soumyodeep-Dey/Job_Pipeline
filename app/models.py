from datetime import date

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, Float, ForeignKey, String, Text
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
        CheckConstraint("status != 'Approved' OR human_approval = true", name="approval_required"),
        CheckConstraint("match_score IS NULL OR (match_score >= 0 AND match_score <= 100)", name="score_range"),
        CheckConstraint("length(trim(job_id)) > 0", name="nonempty_job_id"),
        CheckConstraint("source_url IS NULL OR length(trim(source_url)) > 0", name="nonempty_source_url"),
        CheckConstraint("status IN ('New', 'Shortlisted', 'Approved', 'Applied', 'Interview', 'Rejected', 'Offer', 'Withdrawn')", name="valid_status"),
    )

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
