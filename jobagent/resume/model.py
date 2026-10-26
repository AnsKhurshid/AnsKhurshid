"""Structure of a tailored resume, independent of the output format."""
from __future__ import annotations

from pydantic import BaseModel, Field

from jobagent.models import Certification, Contact, Education


class Bullet(BaseModel):
    text: str
    source: str            # the original resume bullet this came from (verbatim)
    rewritten: bool = False


class ResumeRole(BaseModel):
    employer: str
    title: str
    start: str | None = None
    end: str | None = None
    location: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)


class ResumeProject(BaseModel):
    name: str
    kind: str
    description: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)


class SkillGroup(BaseModel):
    label: str
    skills: list[str]


class TailoredResume(BaseModel):
    name: str
    contact: Contact
    headline: str | None = None
    summary: str
    skill_groups: list[SkillGroup]
    experience: list[ResumeRole]
    projects: list[ResumeProject] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    exploring: list[str] = Field(default_factory=list)   # studied-only skills, clearly labelled

    def all_text(self) -> str:
        parts = [self.headline or "", self.summary]
        parts += [", ".join(g.skills) for g in self.skill_groups]
        for r in self.experience:
            parts += [r.title, r.employer] + [b.text for b in r.bullets]
        for p in self.projects:
            parts += [p.name, p.description or ""] + [b.text for b in p.bullets]
        parts += [", ".join(self.exploring)]
        return "\n".join(parts)


class TailoringRecord(BaseModel):
    """What changed and why: saved next to the resume and in the database."""
    target_job: str
    summary_strategy: str
    reordered_roles: list[str] = Field(default_factory=list)
    omitted_bullets: list[str] = Field(default_factory=list)
    omitted_projects: list[str] = Field(default_factory=list)
    rewritten_bullets: list[dict] = Field(default_factory=list)
    reverted_rewrites: list[dict] = Field(default_factory=list)
    keywords_included: list[str] = Field(default_factory=list)
    keywords_missing_supported: list[str] = Field(default_factory=list)   # in profile but not shown
    requirements_unsupported: list[str] = Field(default_factory=list)     # job asks, profile lacks
    needs_user_input: list[str] = Field(default_factory=list)
