from pydantic import BaseModel, ConfigDict, Field, field_validator


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    demonstrated_skills: list[str] = Field(default_factory=lambda: [
        "Python", "JavaScript", "TypeScript", "React", "Next.js", "Node.js", "Express.js",
        "FastAPI", "SQL", "PostgreSQL", "MongoDB", "Docker", "Linux", "REST APIs", "RAG", "agents", "MCP",
    ], max_length=100)
    adjacent_skills: list[str] = Field(default_factory=lambda: ["Redis", "Kafka"], max_length=100)
    locations: list[str] = Field(default_factory=lambda: [
        "India", "Bengaluru", "Bangalore", "Kolkata", "Hyderabad", "Pune", "Gurugram",
        "Gurgaon", "Noida", "Chennai", "Mumbai", "Delhi",
    ], min_length=1, max_length=100)
    max_experience_years: int = Field(default=2, ge=0, le=20)

    @field_validator("demonstrated_skills", "adjacent_skills", "locations")
    @classmethod
    def clean_list(cls, values):
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("Entries must be nonblank strings of at most 100 characters")
        return list(dict.fromkeys(value.strip() for value in values))


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_ids: list[int] = Field(min_length=1, max_length=5)
    job_offset: int = Field(default=0, ge=0, le=100000)
    max_jobs_per_company: int = Field(default=100, ge=1, le=300)

    @field_validator("company_ids")
    @classmethod
    def valid_ids(cls, values):
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            raise ValueError("Use distinct positive company IDs")
        return values
