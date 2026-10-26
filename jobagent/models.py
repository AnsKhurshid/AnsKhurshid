"""Core data models shared by sources, matching, resume and reporting."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RetrievalStatus(str, Enum):
    COMPLETE = "complete"            # title, company and a usable description were captured
    PARTIAL = "partial"              # some fields missing (e.g. no description)
    NEEDS_MANUAL_REVIEW = "needs_manual_review"  # only a URL/ID; user must supply details
    FAILED = "failed"                # source access failed


class JobStatus(str, Enum):
    NEW = "new"
    ANALYZED = "analyzed"
    SHORTLISTED = "shortlisted"
    REJECTED = "rejected"
    RESUME_GENERATED = "resume_generated"
    REVIEWED = "reviewed"
    APPLIED = "applied"
    CLOSED = "closed"


class RawJob(BaseModel):
    """A job as delivered by a source connector, before normalisation."""
    source: str
    source_job_id: str | None = None
    url: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    employment_type: str | None = None
    work_arrangement: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    posted_at: date | None = None
    deadline: date | None = None
    hiring_organization: str | None = None
    retrieval_status: RetrievalStatus = RetrievalStatus.PARTIAL
    retrieval_notes: str | None = None
    extra: dict = Field(default_factory=dict)


class SourceResult(BaseModel):
    """What a connector returns: jobs plus an honest account of what it could not do."""
    source: str
    jobs: list[RawJob] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    exhaustive: bool = False


# --------------------------------------------------------------------------- candidate profile

# professional: evidenced in work-experience content
# project:      evidenced only in project content
# listed:       appears in a skills list without supporting context (needs your confirmation)
# studied:      coursework / certification / exploration only; never presented as experience
SkillLevel = Literal["professional", "project", "listed", "studied"]


class Experience(BaseModel):
    employer: str
    title: str
    start: str | None = None          # kept as text exactly as on the resume (e.g. "Jan 2023")
    end: str | None = None            # "Present" allowed
    location: str | None = None
    bullets: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    kind: Literal["professional", "portfolio", "learning"] = "portfolio"
    description: str | None = None
    bullets: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None


class Certification(BaseModel):
    name: str
    issuer: str | None = None
    date: str | None = None


class SkillEntry(BaseModel):
    name: str                          # canonical name (taxonomy)
    level: SkillLevel
    evidence: list[str] = Field(default_factory=list)   # resume lines that support it


class Contact(BaseModel):
    """Kept locally; stripped before anything is sent to an AI provider."""
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class CandidateProfile(BaseModel):
    name: str | None = None
    headline: str | None = None
    contact: Contact = Field(default_factory=Contact)
    summary: str | None = None
    total_experience_years: float | None = None
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    skills: list[SkillEntry] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)      # quantified lines found on the resume
    unverified: list[str] = Field(default_factory=list)        # ambiguous items needing confirmation
    target_roles: list[str] = Field(default_factory=list)
    reviewed: bool = False
    reviewed_at: datetime | None = None
    source_resume_sha256: str | None = None
    extracted_at: datetime | None = None

    def skill_names(self, levels: tuple[str, ...] = ("professional", "project", "listed", "studied")) -> set[str]:
        return {s.name for s in self.skills if s.level in levels}

    def skill(self, name: str) -> SkillEntry | None:
        return next((s for s in self.skills if s.name == name), None)

    def for_ai(self) -> dict:
        """Minimal, contact-free view sent to AI providers."""
        return self.model_dump(
            mode="json",
            exclude={"contact", "name", "reviewed", "reviewed_at", "source_resume_sha256", "extracted_at"},
        )


# --------------------------------------------------------------------------- matching

class JobRequirements(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    unclassified_skills: list[str] = Field(default_factory=list)  # mentioned outside a req/pref section
    min_years: float | None = None
    max_years: float | None = None
    seniority: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    mandatory_certifications: list[str] = Field(default_factory=list)
    location_restrictions: list[str] = Field(default_factory=list)
    work_authorization: list[str] = Field(default_factory=list)
    remote_eligibility: Literal["pakistan_ok", "region_restricted", "unspecified", "not_remote"] = "unspecified"
    role_category: str | None = None
    domains: list[str] = Field(default_factory=list)


class ComponentScore(BaseModel):
    name: str
    weight: float
    score: float                       # 0..1
    points: float                      # weight * score
    evidence: list[str] = Field(default_factory=list)


class HardConstraint(BaseModel):
    name: str
    status: Literal["pass", "fail", "unknown"]
    detail: str


class MatchResult(BaseModel):
    score: float
    category: Literal["strong", "potential", "stretch", "low"]
    confidence: Literal["high", "medium", "low"]
    components: list[ComponentScore]
    hard_constraints: list[HardConstraint] = Field(default_factory=list)
    eligible: bool = True
    strengths: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    missing_preferred: list[str] = Field(default_factory=list)
    transferable: list[str] = Field(default_factory=list)
    experience_compatibility: str = ""
    location_eligibility: str = ""
    reasons_to_apply: list[str] = Field(default_factory=list)
    reasons_not_to_apply: list[str] = Field(default_factory=list)
    recommendation: Literal["apply", "consider", "stretch", "skip", "review_eligibility", "needs_details"]
    explanation: str = ""
    ai_used: bool = False
    scoring_version: str = ""
