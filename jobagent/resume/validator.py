"""Independent factual validation of a tailored resume against the reviewed profile.

Runs twice: on the structured resume, and on the text read back from the generated DOCX.
Errors block the 'ready' status; warnings are reported but do not block.
"""
from __future__ import annotations

import math
import re

from pydantic import BaseModel, Field

from jobagent.models import CandidateProfile
from jobagent.resume.model import TailoredResume
from jobagent.taxonomy import Taxonomy

NUM_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
PLACEHOLDER_RE = re.compile(r"\{\{?|\}\}?|\bTODO\b|\bTBD\b|\bXXX\b|lorem ipsum|\[(?:insert|your|company|role)[^\]]*\]|UNKNOWN (?:EMPLOYER|TITLE)", re.I)
YEARS_CLAIM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", re.I)


class ValidationReport(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: dict[str, str] = Field(default_factory=dict)   # check -> pass/fail/warn


def _profile_text(p: CandidateProfile) -> str:
    parts = [p.summary or "", p.headline or "", p.name or ""]
    for e in p.experience:
        parts += [e.employer, e.title, e.start or "", e.end or "", e.location or ""] + e.bullets
    for pr in p.projects:
        parts += [pr.name, pr.description or ""] + pr.bullets
    for ed in p.education:
        parts += [ed.institution, ed.degree or "", ed.field or "", ed.start or "", ed.end or ""]
    parts += [c.name + " " + (c.issuer or "") + " " + (c.date or "") for c in p.certifications]
    parts += p.achievements
    c = p.contact
    parts += [c.email or "", c.phone or "", c.location or "", c.linkedin or "", c.github or "", c.website or ""]
    return "\n".join(parts)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUM_RE.findall(text)}


def validate_resume(resume: TailoredResume, profile: CandidateProfile, taxonomy: Taxonomy,
                    job_skills: list[str] | None = None, document_text: str | None = None) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, str] = {}

    def check(name: str, problems: list[str], severity: str = "error") -> None:
        (errors if severity == "error" else warnings).extend(problems)
        checks[name] = "pass" if not problems else ("fail" if severity == "error" else "warn")

    # 1. Employers, titles and dates are identical to the profile; no role removed or added.
    prob = []
    prof_roles = [(e.employer, e.title, e.start, e.end) for e in profile.experience]
    res_roles = [(r.employer, r.title, r.start, r.end) for r in resume.experience]
    for r in res_roles:
        if r not in prof_roles:
            prob.append(f"role not in profile (employer/title/dates changed?): {r}")
    for r in prof_roles:
        if r not in res_roles:
            prob.append(f"role from profile missing in resume: {r}")
    if res_roles != [r for r in prof_roles if r in res_roles]:
        prob.append("roles are not in the original chronological order")
    check("employers_titles_dates", prob)

    # 2. Every bullet traces to an original bullet of the same role/project.
    prob = []
    for r in resume.experience:
        orig = next((e for e in profile.experience if (e.employer, e.title) == (r.employer, r.title)), None)
        for b in r.bullets:
            if orig is None or b.source not in orig.bullets:
                prob.append(f"bullet has no source in role {r.employer}: {b.text[:80]}")
    for pr in resume.projects:
        orig = next((p for p in profile.projects if p.name == pr.name), None)
        for b in pr.bullets:
            if orig is None or b.source not in orig.bullets:
                prob.append(f"project bullet has no source ({pr.name}): {b.text[:80]}")
        if orig and pr.kind != orig.kind:
            prob.append(f"project kind changed for {pr.name}: {orig.kind} -> {pr.kind}")
    check("bullets_traceable", prob)

    # 3. Rewritten bullets introduce no new numbers or skills relative to their source.
    prob = []
    for b in [b for r in resume.experience for b in r.bullets] + [b for p in resume.projects for b in p.bullets]:
        if b.text == b.source:
            continue
        new_nums = _numbers(b.text) - _numbers(b.source)
        if new_nums:
            prob.append(f"rewritten bullet adds numbers {sorted(new_nums)}: {b.text[:80]}")
        new_sk = set(taxonomy.find(b.text)) - taxonomy.implied_closure(set(taxonomy.find(b.source)))
        if new_sk:
            prob.append(f"rewritten bullet adds skills {sorted(new_sk)}: {b.text[:80]}")
    check("rewrites_faithful", prob)

    # 4. Every skill mentioned anywhere is in the profile; summary only claims professional skills.
    levels = {s.name: s.level for s in profile.skills}
    held = taxonomy.implied_closure(set(levels))
    prof_closure = taxonomy.implied_closure({k for k, v in levels.items() if v == "professional"})
    prob = []
    body = resume.all_text().replace(", ".join(resume.exploring), "")
    for s in taxonomy.find(body):
        if s not in held:
            prob.append(f"skill without evidence in profile: {s}")
    for s in taxonomy.find(resume.summary):
        if s not in prof_closure:
            prob.append(f"summary presents '{s}' as experience but profile level is {levels.get(s, 'absent')}")
    for g in resume.skill_groups:
        for s in g.skills:
            if levels.get(s) == "studied":
                prob.append(f"studied-only skill listed as a skill: {s}")
    check("skills_supported", prob)

    # 5. No invented metrics: every number must already exist in the profile text.
    source_nums = _numbers(_profile_text(profile))
    yrs = profile.total_experience_years
    allowed_extra = {str(math.floor(yrs))} if yrs else set()
    prob = [f"number not found in your resume: {n}" for n in sorted(_numbers(resume.all_text()) - source_nums - allowed_extra)]
    check("no_invented_numbers", prob)

    # 6. Years-of-experience claims do not exceed the profile.
    prob = []
    for m in YEARS_CLAIM_RE.finditer(resume.summary):
        if yrs is None or float(m.group(1)) > yrs:
            prob.append(f"summary claims {m.group(0)} but profile has {yrs} years")
    check("experience_years", prob)

    # 7. Hygiene: placeholders, duplicates, empty sections.
    prob = []
    if PLACEHOLDER_RE.search(resume.all_text()):
        prob.append(f"placeholder text found: {PLACEHOLDER_RE.search(resume.all_text()).group(0)!r}")
    bullets = [b.text for r in resume.experience for b in r.bullets] + [b.text for p in resume.projects for b in p.bullets]
    dups = {b for b in bullets if bullets.count(b) > 1}
    if dups:
        prob.append(f"duplicate bullets: {list(dups)[:2]}")
    if not resume.name:
        prob.append("candidate name missing")
    if not resume.experience:
        prob.append("no experience section")
    check("hygiene", prob)

    # 8. ATS / readability warnings.
    prob = []
    words = len(resume.all_text().split())
    if words < 150:
        prob.append(f"resume is very short ({words} words)")
    if words > 1100:
        prob.append(f"resume is long ({words} words); consider trimming to 1-2 pages")
    if not (resume.contact.email or resume.contact.phone):
        prob.append("no contact details (email/phone) on resume")
    for b in bullets:
        if len(b) > 300:
            prob.append(f"very long bullet ({len(b)} chars): {b[:60]}...")
    check("ats_readability", prob, severity="warn")

    # 9. Keyword use: genuinely tailored, not stuffed.
    prob = []
    if job_skills:
        text = resume.summary
        counts = {s: len(taxonomy.find(text).get(s, [])) for s in job_skills}
        stuffed = [s for s, n in counts.items() if n > 2]
        if stuffed:
            prob.append(f"keywords repeated in summary: {stuffed}")
        if not any(s in taxonomy.find(resume.summary) for s in job_skills):
            prob.append("summary mentions none of the job's key skills; tailoring is weak")
    check("keywords_natural", prob, severity="warn")

    # 10. The rendered document matches (catches rendering bugs).
    if document_text is not None:
        prob = []
        doc_nums = _numbers(document_text) - source_nums - allowed_extra
        if doc_nums:
            prob.append(f"document contains numbers not in your resume: {sorted(doc_nums)[:5]}")
        for s in taxonomy.find(document_text):
            if s not in held:
                prob.append(f"document mentions skill without evidence: {s}")
        for r in resume.experience:
            if r.employer not in document_text or r.title not in document_text:
                prob.append(f"role missing from document: {r.title} @ {r.employer}")
        if PLACEHOLDER_RE.search(document_text):
            prob.append("placeholder text in document")
        check("document_matches", prob)

    return ValidationReport(passed=not errors, errors=errors, warnings=warnings, checks=checks)
