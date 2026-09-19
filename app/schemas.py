from datetime import date
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Status = Literal["New", "Shortlisted", "Approved", "Applied", "Interview", "Rejected", "Offer", "Withdrawn"]


def name_key(value: str) -> str:
    # The source uses both curly and straight apostrophes for Moody's / Lowe's.
    return " ".join(value.replace("\u2019", "'").replace("\u2018", "'").split()).casefold()


class JobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    job_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=200)
    company: str = Field(min_length=1)
    role: str = Field(min_length=1)
    location: str | None = None
    required_skills: str | None = None
    match_score: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    missing_skills: str | None = None
    source_url: str | None = None
    date_found: date = Field(default_factory=date.today)
    status: Status = "New"
    resume_version: str | None = None
    human_approval: bool = False

    @field_validator("source_url")
    @classmethod
    def validate_url(cls, value):
        if not value:
            return None
        from urllib.parse import urlsplit
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc or any(c.isspace() for c in value):
            raise ValueError("Source URL must be an absolute HTTP or HTTPS URL")
        return value

    @model_validator(mode="after")
    def approval_gate(self):
        if self.status == "Approved" and not self.human_approval:
            raise ValueError("Approved status requires human_approval=true")
        return self


class JobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status | None = None
    human_approval: bool | None = None

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Supply status and/or human_approval with a non-null value")
        return self


class JobRead(JobCreate):
    pass


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    domains: list[str]
    career_pages: list[str]
    keyword_profiles: list[dict]
