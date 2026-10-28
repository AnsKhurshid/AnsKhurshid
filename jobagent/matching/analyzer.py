"""Analyse stored jobs against the reviewed profile: requirements -> score -> (optional AI) -> persist."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from jobagent.ai.client import AIClient, AIError
from jobagent.config import Settings
from jobagent.matching.requirements import extract_requirements
from jobagent.matching.scoring import SCORING_VERSION, CandidateView, candidate_view, score_job
from jobagent.models import CandidateProfile, HardConstraint, JobStatus, MatchResult, RetrievalStatus
from jobagent.profile.store import profile_sha
from jobagent.storage.db import Database
from jobagent.taxonomy import Taxonomy

log = logging.getLogger("jobagent.matching")

AI_PROMPT_VERSION = "analysis-1"
# Statuses set by the user (or later stages) that re-analysis must not overwrite.
STICKY = {JobStatus.RESUME_GENERATED.value, JobStatus.REVIEWED.value, JobStatus.APPLIED.value, JobStatus.CLOSED.value}


class EvidencePair(BaseModel):
    job_requirement: str = Field(description="A responsibility or requirement quoted from the job description")
    resume_evidence: str = Field(description="The exact resume line (verbatim) that supports it, or empty if none")


class AIJobAnalysis(BaseModel):
    responsibilities_alignment: float = Field(description="0.0-1.0: how well the candidate's demonstrated work matches the role's responsibilities")
    evidence: list[EvidencePair]
    additional_required_skills: list[str] = Field(description="Mandatory skills/tools stated in the description that are missing from the deterministic list")
    eligibility_concerns: list[str] = Field(description="Location, work authorisation, certification, degree or other hard requirements the candidate may not meet")
    reasons_to_apply: list[str]
    reasons_not_to_apply: list[str]
    summary: str = Field(description="Two or three evidence-based sentences")


SYSTEM_PROMPT = """You evaluate how well a candidate fits a job, as a careful technical recruiter for data engineering roles.
Rules:
- Use ONLY the candidate profile and job description provided. Never assume experience that is not stated.
- Distinguish professional experience, portfolio projects, listed skills and studied-only skills; only professional experience counts as production experience.
- resume_evidence must be copied verbatim from the profile's experience or project bullets, or left empty.
- Do not reward keyword repetition; judge the substance of responsibilities.
- A remote job is not automatically open to candidates in Pakistan; flag any location or work-authorisation limits.
- Be concise."""


@dataclass
class AnalyzeStats:
    considered: int = 0
    analyzed: int = 0
    skipped_current: int = 0
    skipped_no_description: int = 0
    failed: int = 0
    ai_used: int = 0
    ai_unavailable_reason: str | None = None
    by_category: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _profile_lines(profile: CandidateProfile) -> list[str]:
    return [b for e in profile.experience for b in e.bullets] + [b for p in profile.projects for b in p.bullets]


def _supported(evidence: str, lines: list[str]) -> bool:
    words = set(re.findall(r"[a-z0-9]+", evidence.lower()))
    if len(words) < 3:
        return False
    return any(len(words & set(re.findall(r"[a-z0-9]+", ln.lower()))) / len(words) >= 0.7 for ln in lines)


class Analyzer:
    def __init__(self, settings: Settings, db: Database, taxonomy: Taxonomy, profile: CandidateProfile,
                 ai: AIClient | None = None, run_id: int | None = None):
        self.settings, self.db, self.taxonomy, self.profile = settings, db, taxonomy, profile
        self.ai = ai
        self.run_id = run_id
        self.psha = profile_sha(profile)
        self.cand: CandidateView = candidate_view(profile, taxonomy, settings)
        self.use_ai = bool(settings.matching.use_ai and ai and ai.available)
        self.version = SCORING_VERSION + ("+" + AI_PROMPT_VERSION if self.use_ai else "")

    def _ai_refine(self, job: dict, description: str, req, det: MatchResult):
        user = (
            f"JOB TITLE: {job.get('title')}\nCOMPANY: {job.get('company')}\nLOCATION: {job.get('location')} "
            f"({job.get('work_arrangement')})\n\nJOB DESCRIPTION:\n{description}\n\n"
            f"CANDIDATE PROFILE (JSON):\n{self.profile.for_ai()}\n\n"
            f"DETERMINISTIC FINDINGS: required={req.required_skills}, preferred={req.preferred_skills}, "
            f"missing_required={det.missing_required}, experience={det.experience_compatibility}, "
            f"location={det.location_eligibility}"
        )
        return self.ai.structured("job_analysis", SYSTEM_PROMPT, user, AIJobAnalysis, AI_PROMPT_VERSION)

    def analyze_job(self, job_id: int, force: bool = False) -> MatchResult | None:
        job = self.db.job(job_id)
        if job is None:
            raise KeyError(job_id)
        desc = self.db.description(job_id)
        if not desc or job["retrieval_status"] in (RetrievalStatus.NEEDS_MANUAL_REVIEW.value, RetrievalStatus.FAILED.value):
            return None
        text, dsha = desc
        if not force and self.db.has_current_analysis(job_id, dsha, self.psha, self.version):
            return "current"  # type: ignore[return-value]

        import json
        extra = json.loads(job.get("extra_json") or "{}")
        req = extract_requirements(text, job.get("title"), self.taxonomy, extra)
        result = score_job(job, text, req, self.profile, self.taxonomy, self.settings, self.cand)

        if self.use_ai:
            try:
                ai = self._ai_refine(job, text, req, result)
                lines = _profile_lines(self.profile)
                verified = [f"{e.job_requirement[:80]} ⇐ \"{e.resume_evidence[:80]}\"" for e in ai.evidence
                            if e.resume_evidence and _supported(e.resume_evidence, lines)]
                dropped = sum(1 for e in ai.evidence if e.resume_evidence and not _supported(e.resume_evidence, lines))
                added = []
                for s in ai.additional_required_skills:
                    canon = self.taxonomy.canonical(s)
                    if canon and canon not in req.required_skills and re.search(re.escape(s), text, re.I):
                        req.required_skills.append(canon)
                        req.preferred_skills = [p for p in req.preferred_skills if p != canon]
                        req.unclassified_skills = [p for p in req.unclassified_skills if p != canon]
                        added.append(canon)
                notes = verified + ([f"{dropped} AI evidence claim(s) dropped: not found in profile"] if dropped else [])
                result = score_job(job, text, req, self.profile, self.taxonomy, self.settings, self.cand,
                                   ai_responsibilities=(ai.responsibilities_alignment, notes))
                for c in ai.eligibility_concerns:
                    result.hard_constraints.append(HardConstraint(name="AI flag", status="unknown", detail=c))
                    result.reasons_not_to_apply.append(f"Check: {c}")
                result.reasons_to_apply += [r for r in ai.reasons_to_apply if r not in result.reasons_to_apply][:3]
                result.reasons_not_to_apply += [r for r in ai.reasons_not_to_apply if r not in result.reasons_not_to_apply][:3]
                result.explanation += " AI review: " + ai.summary + (f" (added required: {', '.join(added)})" if added else "")
                result.ai_used = True
                result.scoring_version = self.version
            except AIError as exc:
                log.warning("AI analysis failed for job %s, using deterministic result: %s", job_id, exc)
                result.explanation += f" (AI analysis unavailable: {exc})"
                result.scoring_version = SCORING_VERSION

        with self.db.tx():
            self.db.save_analysis(job_id, self.run_id, dsha, self.psha, result.scoring_version, result.score,
                                  result.category, result.eligible, req.model_dump(mode="json"),
                                  result.model_dump(mode="json"))
            if job["status"] not in STICKY:
                if result.eligible and result.score >= self.settings.matching.min_match_score:
                    self.db.set_status(job_id, JobStatus.SHORTLISTED, f"score {result.score:.0f} ≥ {self.settings.matching.min_match_score:g}")
                elif not result.eligible and result.recommendation == "skip":
                    self.db.set_status(job_id, JobStatus.REJECTED, "hard constraint: " + "; ".join(
                        c.detail for c in result.hard_constraints if c.status == "fail")[:300])
                elif result.category == "low":
                    self.db.set_status(job_id, JobStatus.REJECTED, f"low priority (score {result.score:.0f})")
                else:
                    self.db.set_status(job_id, JobStatus.ANALYZED, f"{result.category} (score {result.score:.0f}); {result.recommendation}")
        return result

    def analyze(self, job_ids: list[int] | None = None, force: bool = False, limit: int | None = None) -> AnalyzeStats:
        stats = AnalyzeStats()
        if self.ai and not self.ai.available:
            stats.ai_unavailable_reason = self.ai.reason_unavailable
        if job_ids is None:
            job_ids = [r["id"] for r in self.db.q("SELECT id FROM jobs WHERE availability != 'closed' ORDER BY id")]
        limit = limit or self.settings.search.max_jobs_per_run
        for job_id in job_ids:
            if stats.analyzed >= limit:
                break
            stats.considered += 1
            try:
                res = self.analyze_job(job_id, force=force)
            except Exception as exc:
                log.exception("analysis failed for job %s", job_id)
                stats.failed += 1
                stats.errors.append(f"job {job_id}: {exc}")
                if self.run_id:
                    self.db.mark_task(self.run_id, job_id, "analyze", "failed", str(exc)[:500])
                continue
            if res is None:
                stats.skipped_no_description += 1
                if self.run_id:
                    self.db.mark_task(self.run_id, job_id, "analyze", "skipped", "no description")
                continue
            if res == "current":
                stats.skipped_current += 1
                continue
            stats.analyzed += 1
            stats.ai_used += int(res.ai_used)
            stats.by_category[res.category] = stats.by_category.get(res.category, 0) + 1
            if self.run_id:
                self.db.mark_task(self.run_id, job_id, "analyze", "done")
        return stats
