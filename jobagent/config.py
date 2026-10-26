"""Application settings: YAML file + environment variables, validated with Pydantic."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yaml"

WorkArrangement = Literal["on-site", "hybrid", "remote"]


class ProfileSettings(BaseModel):
    master_resume_path: Path = Path("data/resume/master_resume.docx")
    candidate_profile_path: Path = Path("data/profile/candidate_profile.yaml")


class SearchSettings(BaseModel):
    preferred_titles: list[str] = Field(default_factory=lambda: ["Data Engineer"])
    primary_country: str = "Pakistan"
    preferred_locations: list[str] = Field(default_factory=list)
    work_arrangements: list[WorkArrangement] = Field(default_factory=lambda: ["on-site", "hybrid", "remote"])
    include_international_remote: bool = False
    posted_within_days: int = 14
    min_experience_years: float = 0
    max_experience_years: float = 5
    candidate_experience_years: float | None = None
    preferred_industries: list[str] = Field(default_factory=list)
    excluded_industries: list[str] = Field(default_factory=list)
    excluded_title_keywords: list[str] = Field(default_factory=list)
    frequency: str = "weekly"
    max_jobs_per_run: int = Field(200, ge=1)


class LinkedInSettings(BaseModel):
    geo_id_pakistan: str = "101022442"
    inbox_dir: Path = Path("data/inbox/linkedin")


class ManualSettings(BaseModel):
    inbox_dir: Path = Path("data/inbox/manual")


class UrlFetchSettings(BaseModel):
    enabled: bool = True
    user_agent: str = "jobagent-personal/0.1"
    min_interval_seconds: float = 5
    timeout_seconds: float = 20
    max_retries: int = 3


class SourcesSettings(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: ["linkedin", "manual"])
    linkedin: LinkedInSettings = Field(default_factory=LinkedInSettings)
    manual: ManualSettings = Field(default_factory=ManualSettings)
    url_fetch: UrlFetchSettings = Field(default_factory=UrlFetchSettings)


class Weights(BaseModel):
    skills: float = 30
    responsibilities: float = 25
    seniority: float = 15
    role_alignment: float = 15
    location: float = 10
    domain: float = 5

    @model_validator(mode="after")
    def _sum_to_100(self) -> "Weights":
        total = sum(self.model_dump().values())
        if abs(total - 100) > 0.01:
            raise ValueError(f"matching.weights must sum to 100 (got {total})")
        return self


class Categories(BaseModel):
    strong: float = 80
    potential: float = 65
    stretch: float = 50

    @model_validator(mode="after")
    def _ordered(self) -> "Categories":
        if not (self.strong > self.potential > self.stretch):
            raise ValueError("matching.categories must satisfy strong > potential > stretch")
        return self


class MatchingSettings(BaseModel):
    min_match_score: float = 65
    weights: Weights = Field(default_factory=Weights)
    categories: Categories = Field(default_factory=Categories)
    use_ai: bool = True
    candidate_domains: list[str] = Field(default_factory=list)


class ResumeSettings(BaseModel):
    output_dir: Path = Path("data/resumes")
    generate_pdf: bool = True
    ai_rewrite_bullets: bool = False
    max_bullets_per_role: int = 6


class ReportingSettings(BaseModel):
    output_dir: Path = Path("data/reports")
    min_sample_for_trends: int = 10


class AISettings(BaseModel):
    provider: Literal["none", "anthropic", "openai"] = "none"
    model: str = ""
    max_tokens: int = 2000
    timeout_seconds: float = 60
    max_retries: int = 3
    input_cost_per_mtok: float = 0
    output_cost_per_mtok: float = 0

    @field_validator("model")
    @classmethod
    def _strip(cls, v: str) -> str:
        return (v or "").strip()


class StorageSettings(BaseModel):
    db_path: Path = Path("data/jobagent.db")


class LoggingSettings(BaseModel):
    dir: Path = Path("data/logs")
    level: str = "INFO"


class Settings(BaseModel):
    profile: ProfileSettings = Field(default_factory=ProfileSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    sources: SourcesSettings = Field(default_factory=SourcesSettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    resume: ResumeSettings = Field(default_factory=ResumeSettings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)
    ai: AISettings = Field(default_factory=AISettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    root: Path = Field(default=PROJECT_ROOT, exclude=True)

    def path(self, p: Path) -> Path:
        """Resolve a configured path against the project root."""
        p = Path(os.path.expanduser(str(p)))
        return p if p.is_absolute() else (self.root / p)

    def api_key(self) -> str | None:
        """Return the key for the configured provider from the environment (never from YAML)."""
        var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(self.ai.provider)
        return (os.environ.get(var) or None) if var else None


def load_settings(path: str | Path | None = None, root: Path | None = None) -> Settings:
    root = root or PROJECT_ROOT
    load_dotenv(root / ".env", override=False)
    cfg_path = Path(path or os.environ.get("JOBAGENT_CONFIG") or DEFAULT_CONFIG)
    if not cfg_path.is_absolute():
        cfg_path = root / cfg_path
    data: dict = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    settings = Settings.model_validate(data)
    settings.root = root
    if lvl := os.environ.get("JOBAGENT_LOG_LEVEL"):
        settings.logging.level = lvl
    return settings


def startup_report(settings: Settings) -> list[tuple[str, str, str]]:
    """Return (level, check, message) tuples describing readiness. Never raises."""
    import shutil

    out: list[tuple[str, str, str]] = []
    resume = settings.path(settings.profile.master_resume_path)
    if resume.exists():
        out.append(("ok", "master resume", str(resume)))
    else:
        out.append(("warn", "master resume",
                    f"not found at {resume}. Place your resume there (or change profile.master_resume_path) "
                    "before running profile extraction or resume tailoring."))
    prof = settings.path(settings.profile.candidate_profile_path)
    if prof.exists():
        out.append(("ok", "candidate profile", str(prof)))
    else:
        out.append(("warn", "candidate profile", "not extracted yet: run `python -m jobagent profile extract`"))
    if settings.ai.provider == "none":
        out.append(("info", "AI provider", "disabled: deterministic matching and tailoring only"))
    elif not settings.api_key():
        out.append(("warn", "AI provider", f"{settings.ai.provider} selected but its API key is not set in .env"))
    elif not settings.ai.model:
        out.append(("warn", "AI provider", "ai.model is empty in settings.yaml"))
    else:
        out.append(("ok", "AI provider", f"{settings.ai.provider} / {settings.ai.model}"))
    if settings.resume.generate_pdf:
        if shutil.which("soffice") or shutil.which("libreoffice"):
            out.append(("ok", "PDF conversion", "LibreOffice found"))
        else:
            out.append(("warn", "PDF conversion", "LibreOffice not found: only DOCX resumes will be produced"))
    return out
