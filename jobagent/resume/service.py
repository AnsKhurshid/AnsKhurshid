"""Generate, validate and store a tailored resume for one job (idempotent)."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from jobagent.ai.client import AIClient, AIError
from jobagent.config import Settings
from jobagent.models import CandidateProfile, JobRequirements, JobStatus, MatchResult
from jobagent.profile.store import profile_sha
from jobagent.resume.docx_writer import docx_text, render_docx
from jobagent.resume.model import TailoredResume, TailoringRecord
from jobagent.resume.pdf import convert_to_pdf
from jobagent.resume.tailor import Tailor
from jobagent.resume.validator import ValidationReport, _numbers, validate_resume
from jobagent.storage.db import Database
from jobagent.taxonomy import Taxonomy
from jobagent.utils.files import atomic_write_bytes, atomic_write_text, sanitize_filename_part

log = logging.getLogger("jobagent.resume")
REWRITE_PROMPT_VERSION = "rewrite-1"


class BulletRewrite(BaseModel):
    original: str
    rewritten: str


class BulletRewrites(BaseModel):
    bullets: list[BulletRewrite] = Field(description="One entry per input bullet, in the same order")


REWRITE_SYSTEM = """You improve resume bullets for clarity and relevance to a target job.
Hard rules:
- Keep every fact exactly as stated. Do not add tools, technologies, numbers, metrics, outcomes, scope or ownership.
- Do not remove numbers that are present.
- Use the job's terminology only where the original bullet already describes that same thing.
- Start with a strong past- or present-tense action verb; one sentence; at most 35 words.
- If a bullet cannot be improved without adding facts, return it unchanged."""


@dataclass
class ResumeOutput:
    status: str
    docx_path: str | None
    pdf_path: str | None
    report_path: str | None
    issues: list[str] = field(default_factory=list)
    reused: bool = False


class ResumeService:
    def __init__(self, settings: Settings, db: Database, taxonomy: Taxonomy, profile: CandidateProfile,
                 ai: AIClient | None = None, run_id: int | None = None):
        self.settings, self.db, self.taxonomy, self.profile = settings, db, taxonomy, profile
        self.run_id = run_id
        self.psha = profile_sha(profile)
        self.ai = ai if ai is not None else (AIClient(settings, db, run_id=run_id) if settings.resume.ai_rewrite_bullets else None)

    def _paths(self, job: dict) -> tuple[Path, str]:
        company = sanitize_filename_part(job.get("company") or "Company", 30)
        title = sanitize_filename_part(job.get("title") or "Role", 40)
        stem = f"{company}_{title}_J{job['id']}"
        return self.settings.path(self.settings.resume.output_dir) / stem, stem

    def _rewrite(self, resume: TailoredResume, record: TailoringRecord, job: dict, req: JobRequirements) -> None:
        bullets = [b for r in resume.experience for b in r.bullets]
        if not bullets:
            return
        user = (f"TARGET JOB: {job.get('title')} at {job.get('company')}\nKEY SKILLS: "
                f"{', '.join(req.required_skills + req.preferred_skills)}\nRESPONSIBILITIES:\n- "
                + "\n- ".join(req.responsibilities[:10]) + "\n\nBULLETS:\n" + "\n".join(f"- {b.text}" for b in bullets))
        out = self.ai.structured("bullet_rewrite", REWRITE_SYSTEM, user, BulletRewrites, REWRITE_PROMPT_VERSION)
        by_orig = {r.original.strip(): r.rewritten.strip() for r in out.bullets}
        for b in bullets:
            new = by_orig.get(b.source.strip())
            if not new or new == b.source:
                continue
            new_nums = _numbers(new) - _numbers(b.source)
            lost_nums = _numbers(b.source) - _numbers(new)
            new_sk = set(self.taxonomy.find(new)) - self.taxonomy.implied_closure(set(self.taxonomy.find(b.source)))
            if new_nums or lost_nums or new_sk or len(new) > 320:
                record.reverted_rewrites.append({"original": b.source, "proposed": new, "why": (
                    f"added numbers {sorted(new_nums)} " if new_nums else "") + (f"dropped numbers {sorted(lost_nums)} " if lost_nums else "")
                    + (f"added skills {sorted(new_sk)}" if new_sk else "") + ("too long" if len(new) > 320 else "")})
                continue
            b.text, b.rewritten = new, True
            record.rewritten_bullets.append({"original": b.source, "rewritten": new})

    def generate(self, job_id: int, force: bool = False) -> ResumeOutput:
        job = self.db.job(job_id)
        if job is None:
            raise KeyError(f"job {job_id} not found")
        analysis = self.db.latest_analysis(job_id)
        desc = self.db.description(job_id)
        if not analysis or not desc:
            raise ValueError(f"job {job_id} has not been analysed yet (needs a description and `analyze`)")
        text, dsha = desc
        existing = self.db.find_resume(job_id, self.psha, dsha)
        if existing and not force and existing["docx_path"] and Path(existing["docx_path"]).exists():
            v = json.loads(existing["validation_json"])
            return ResumeOutput(existing["status"], existing["docx_path"], existing["pdf_path"], existing["report_path"],
                                issues=v.get("errors", []), reused=True)

        req = JobRequirements.model_validate(analysis["requirements"])
        match = MatchResult.model_validate(analysis["result"])
        tailor = Tailor(self.profile, self.taxonomy, self.settings.resume.max_bullets_per_role)
        resume, record = tailor.build(job, text, req, match)

        if self.ai and self.ai.available:
            try:
                self._rewrite(resume, record, job, req)
            except AIError as exc:
                record.needs_user_input.append(f"AI bullet rewrite skipped: {exc}")
        elif self.settings.resume.ai_rewrite_bullets and self.ai:
            record.needs_user_input.append(f"AI bullet rewrite unavailable: {self.ai.reason_unavailable}")

        job_skills = list(dict.fromkeys(req.required_skills + req.unclassified_skills + req.preferred_skills))
        report = validate_resume(resume, self.profile, self.taxonomy, job_skills)
        folder, stem = self._paths(job)
        docx_bytes = render_docx(resume, f"{job.get('title')} – {job.get('company')}")
        doc_report = validate_resume(resume, self.profile, self.taxonomy, job_skills, document_text=docx_text(docx_bytes))
        report = ValidationReport(passed=report.passed and doc_report.passed,
                                  errors=list(dict.fromkeys(report.errors + doc_report.errors)),
                                  warnings=list(dict.fromkeys(report.warnings + doc_report.warnings)),
                                  checks={**report.checks, **doc_report.checks})
        status = "ready" if report.passed else "needs_review"

        docx_path = folder / f"{stem}_Resume.docx"
        atomic_write_bytes(docx_path, docx_bytes)
        pdf_path = None
        pdf_note = None
        if self.settings.resume.generate_pdf:
            pdf_path, pdf_note = convert_to_pdf(docx_path, folder / f"{stem}_Resume.pdf")
        report_path = folder / f"{stem}_tailoring_report.md"
        atomic_write_text(report_path, self._report_md(job, resume, record, report, pdf_note))
        atomic_write_text(folder / f"{stem}_changes.json", json.dumps(
            {"record": record.model_dump(), "validation": report.model_dump(), "profile_sha": self.psha,
             "description_sha": dsha}, indent=2))

        with self.db.tx():
            self.db.save_resume(job_id, self.psha, dsha, status, str(docx_path), str(pdf_path) if pdf_path else None,
                                str(report_path), report.model_dump(), record.model_dump())
            if status == "ready" and job["status"] not in (JobStatus.REVIEWED.value, JobStatus.APPLIED.value, JobStatus.CLOSED.value):
                self.db.set_status(job_id, JobStatus.RESUME_GENERATED, f"tailored resume ready: {docx_path.name}")
        if status != "ready":
            log.warning("resume for job %s failed validation: %s", job_id, report.errors[:3])
        return ResumeOutput(status, str(docx_path), str(pdf_path) if pdf_path else None, str(report_path),
                            issues=report.errors + ([pdf_note] if pdf_note else []))

    def _report_md(self, job: dict, resume: TailoredResume, rec: TailoringRecord, rep: ValidationReport,
                   pdf_note: str | None) -> str:
        L = [f"# Tailoring report: {job.get('title')} @ {job.get('company')}", "",
             f"Job ID {job['id']} · {job.get('canonical_url') or 'no URL'}",
             f"**Validation: {'PASSED: ready for your review' if rep.passed else 'FAILED: not marked ready, see errors'}**",
             "", "> Review this resume yourself before sending it. Nothing has been submitted anywhere.", ""]
        if rep.errors:
            L += ["## Validation errors", *[f"- {e}" for e in rep.errors], ""]
        if rep.warnings:
            L += ["## Warnings", *[f"- {w}" for w in rep.warnings], ""]
        L += ["## Checks", *[f"- {k}: {v}" for k, v in rep.checks.items()], ""]
        L += ["## Summary used", resume.summary, "", f"_Strategy: {rec.summary_strategy}_", ""]
        L += ["## Job keywords included", ", ".join(rec.keywords_included) or "none", ""]
        if rec.keywords_missing_supported:
            L += ["## Supported by your profile but not shown", ", ".join(rec.keywords_missing_supported), ""]
        L += ["## Requirements NOT supported by your profile (deliberately not claimed)",
              ", ".join(rec.requirements_unsupported) or "none", ""]
        if rec.reordered_roles:
            L += ["## Bullets reordered for relevance", *[f"- {r}" for r in rec.reordered_roles], ""]
        if rec.omitted_bullets:
            L += ["## Bullets omitted (lower relevance; still in your master resume)", *[f"- {b}" for b in rec.omitted_bullets], ""]
        if rec.omitted_projects:
            L += ["## Projects omitted", *[f"- {p}" for p in rec.omitted_projects], ""]
        if rec.rewritten_bullets:
            L += ["## Bullets reworded (AI, validated)"]
            for r in rec.rewritten_bullets:
                L += [f"- before: {r['original']}", f"  after: {r['rewritten']}"]
            L.append("")
        if rec.reverted_rewrites:
            L += ["## AI rewrites rejected by validation"]
            for r in rec.reverted_rewrites:
                L += [f"- {r['proposed']}  ({r['why'].strip()})"]
            L.append("")
        if rec.needs_user_input:
            L += ["## Needs your input", *[f"- {n}" for n in rec.needs_user_input], ""]
        if pdf_note:
            L += [f"_PDF not generated: {pdf_note}_", ""]
        return "\n".join(L)
