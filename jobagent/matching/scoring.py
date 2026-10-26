"""Deterministic, explainable match scoring with separately evaluated hard constraints.

Every component returns a 0..1 score plus human-readable evidence. Weights come from settings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from jobagent.config import Settings
from jobagent.ingestion.normalize import normalize_title
from jobagent.models import (CandidateProfile, ComponentScore, HardConstraint, JobRequirements, MatchResult)
from jobagent.taxonomy import Taxonomy

SCORING_VERSION = "det-1"

LEVEL_CREDIT = {"professional": 1.0, "project": 0.6, "listed": 0.5, "studied": 0.25}
LEVEL_RANK = {"studied": 0, "listed": 1, "project": 2, "professional": 3}
IMPORTANCE = {"required": 1.0, "unclassified": 0.6, "preferred": 0.4}

ROLE_ALIGNMENT = {
    "data_engineer": 1.0, "aws_data_engineer": 1.0, "python_data_engineer": 1.0, "sql_data_engineer": 0.95,
    "etl_developer": 0.9, "data_integration_engineer": 0.9, "analytics_engineer": 0.85,
    "database_developer": 0.65, "data_architect": 0.5, "bi_engineer": 0.5, "database_administrator": 0.35,
    "data_analyst": 0.3, "ml_engineer": 0.3, "software_engineer": 0.3, "data_scientist": 0.2, "other": 0.2,
}
SENIORITY_DEFAULT_YEARS = {"intern": 0, "junior": 0, "mid": 2, "senior": 5, "lead": 7, "manager": 7, "principal": 10}

CONCEPTS = {
    "building pipelines": r"\b(build|develop|design|implement|create)\w*\b.{0,40}\b(pipeline|etl|elt|ingestion|workflow)s?\b|\betl\b|\belt\b",
    "API/data ingestion": r"\bapis?\b|\bingest|\bfeeds?\b|\brets\b|third[- ]party data",
    "data quality": r"data quality|validat|cleans|integrity|reconcil|data issues",
    "troubleshooting": r"troubleshoot|investigat|debug|failures?|incident|root cause|production support|on-call",
    "optimisation": r"optimi[sz]|performance|tuning|speed up|reduc\w+ (runtime|cost|latency)",
    "orchestration": r"orchestrat|workflow|schedul|step functions|airflow",
    "data modelling": r"data model|modell?ing|schema design|dimensional|star schema",
    "warehousing/lakes": r"warehouse|lakehouse|data lake|redshift|snowflake|bigquery",
    "streaming": r"stream|real[- ]time|kafka|kinesis",
    "BI/reporting": r"dashboard|reporting|visuali[sz]|power bi|tableau",
    "machine learning": r"machine learning|ml models?|model training|predictive|statistical model",
    "leadership": r"\blead(ing)?\b|mentor|manage (a )?team|own(ing)? the|architect(ing)? (the|our)",
    "data synchronisation": r"synchron|\bsync\b|incremental|\bcdc\b|upsert|change data capture",
    "migration": r"migrat",
    "cloud infrastructure": r"\baws\b|azure|\bgcp\b|cloud|serverless|lambda",
    "stakeholder work": r"stakeholder|business (users|teams)|requirements gathering|cross[- ]functional",
    "transformation": r"transform|staging|raw layer|clean(s|ing)? data|data prep",
    "monitoring": r"monitor|alert|observab|logging",
}


@dataclass
class CandidateView:
    """Precomputed candidate facts used by the scorer."""
    levels: dict[str, str]            # skill -> best level (including implied skills)
    years: float | None
    concepts: dict[str, float]        # concept -> credit (1.0 professional, 0.5 project)
    concept_evidence: dict[str, str]
    certifications: list[str]
    degrees: list[str]


def candidate_view(profile: CandidateProfile, taxonomy: Taxonomy, settings: Settings) -> CandidateView:
    levels: dict[str, str] = {}
    for s in profile.skills:
        for name in taxonomy.implied_closure({s.name}):
            if name not in levels or LEVEL_RANK[s.level] > LEVEL_RANK[levels[name]]:
                levels[name] = s.level
    concepts: dict[str, float] = {}
    evidence: dict[str, str] = {}
    prof_lines = [b for e in profile.experience for b in e.bullets]
    prof_lines += [b for p in profile.projects if p.kind == "professional" for b in p.bullets]
    proj_lines = [b for p in profile.projects if p.kind == "portfolio" for b in p.bullets]
    for credit, lines in ((1.0, prof_lines), (0.5, proj_lines)):
        for ln in lines:
            for c, pat in CONCEPTS.items():
                if re.search(pat, ln, re.I) and concepts.get(c, 0) < credit:
                    concepts[c] = credit
                    evidence[c] = ln
    years = settings.search.candidate_experience_years
    if years is None:
        years = profile.total_experience_years
    return CandidateView(levels=levels, years=years, concepts=concepts, concept_evidence=evidence,
                         certifications=[c.name for c in profile.certifications],
                         degrees=[e.degree or "" for e in profile.education])


# ------------------------------------------------------------------ components

def score_skills(req: JobRequirements, cand: CandidateView, taxonomy: Taxonomy):
    total_w = got = 0.0
    matched, missing_req, missing_pref, transferable, evidence = [], [], [], [], []
    for importance, skills in (("required", req.required_skills), ("unclassified", req.unclassified_skills),
                               ("preferred", req.preferred_skills)):
        w = IMPORTANCE[importance]
        for skill in skills:
            total_w += w
            level = cand.levels.get(skill)
            credit = LEVEL_CREDIT[level] if level else 0.0
            note = f"{skill}: {level}" if level else None
            if credit < 0.7:
                # Transfer from a related skill, scaled by how well that skill is evidenced.
                held = {k for k, v in cand.levels.items() if v in ("professional", "project")}
                t_credit, via = taxonomy.transfer_credit(skill, held)
                if via:
                    t_credit *= LEVEL_CREDIT[cand.levels[via]]
                    if t_credit > credit:
                        credit = t_credit
                        transferable.append(f"{skill} ← {via} ({cand.levels[via]})")
                        note = f"{skill}: transferable from {via}"
            got += w * credit
            if credit >= 0.6:
                matched.append(skill)
            elif importance == "required":
                missing_req.append(skill)
            elif importance == "preferred":
                missing_pref.append(skill)
            if note:
                evidence.append(f"[{importance}] {note}")
            else:
                evidence.append(f"[{importance}] {skill}: not in profile")
    if total_w == 0:
        return 0.5, ["no recognisable skills in the description; neutral score"], matched, missing_req, missing_pref, transferable
    return got / total_w, evidence, matched, missing_req, missing_pref, transferable


def score_responsibilities(req: JobRequirements, description: str, cand: CandidateView, taxonomy: Taxonomy):
    from jobagent.matching.requirements import split_description
    if req.responsibilities:
        lines = req.responsibilities
    else:
        # Requirement/preferred lines are already scored under skills; don't count them twice.
        sec = split_description(description)
        lines = [l for k in ("intro", "responsibilities", "other") for l in sec.get(k, []) if len(l) > 30][:20]
    scored, evidence, seen = [], [], set()
    for ln in lines:
        concepts = [c for c, pat in CONCEPTS.items() if re.search(pat, ln, re.I)]
        skills = list(taxonomy.find(ln))
        items = len(concepts) + len(skills)
        signature = frozenset(concepts + skills)
        if not items or signature in seen:   # repeated keywords count once
            continue
        seen.add(signature)
        credit = sum(cand.concepts.get(c, 0.0) for c in concepts)
        credit += sum(LEVEL_CREDIT.get(cand.levels.get(s, ""), 0.0) if cand.levels.get(s) else 0.0 for s in skills)
        frac = credit / items
        scored.append(frac)
        mark = "✓" if frac >= 0.75 else "~" if frac >= 0.4 else "✗"
        backing = next((cand.concept_evidence[c] for c in concepts if c in cand.concept_evidence), None)
        evidence.append(f"{mark} {ln[:110]}" + (f"  ⇐ resume: \"{backing[:90]}\"" if backing and frac >= 0.4 else ""))
    if not scored:
        return 0.5, ["responsibilities not recognisable; neutral score"]
    return sum(scored) / len(scored), evidence


def score_seniority(req: JobRequirements, title: str | None, cand: CandidateView, settings: Settings):
    y = cand.years
    need = req.min_years
    src = "stated"
    if need is None and req.seniority in SENIORITY_DEFAULT_YEARS:
        need, src = SENIORITY_DEFAULT_YEARS[req.seniority], f"implied by '{req.seniority}' title"
    if y is None:
        return 0.6, ["candidate experience unknown (set total_experience_years in profile)"], "unknown"
    if need is None:
        return 0.8, [f"no experience requirement found; candidate has {y} years"], f"unspecified (you: {y} yrs)"
    ev = [f"requires {need:g}+ years ({src}); candidate has {y:g}"]
    if req.max_years:
        ev[0] = f"requires {need:g}-{req.max_years:g} years ({src}); candidate has {y:g}"
    gap = need - y
    if gap <= 0:
        s = 1.0
        if req.max_years and y > req.max_years + 2:
            s = 0.75
            ev.append("candidate may be over-qualified for the stated range")
        compat = "meets requirement"
    else:
        s = 0.9 if gap <= 0.5 else 0.75 if gap <= 1 else 0.5 if gap <= 2 else 0.3 if gap <= 3 else 0.1
        compat = f"{gap:g} year(s) below requirement"
    if req.seniority in ("senior", "lead", "principal", "manager") and y < 4:
        s = min(s, 0.5)
        ev.append(f"'{req.seniority}' level role vs {y:g} years of experience")
        compat += f"; {req.seniority}-level title"
    if req.seniority == "intern":
        s = min(s, 0.4)
        ev.append("internship is below current career level")
        compat = "below current level (internship)"
    if need > settings.search.max_experience_years:
        ev.append(f"requirement exceeds configured max_experience_years ({settings.search.max_experience_years:g})")
    return s, ev, compat


def score_role(title: str | None, req: JobRequirements, settings: Settings):
    cat = req.role_category or "other"
    s = ROLE_ALIGNMENT.get(cat, 0.2)
    ev = [f"role category '{cat}' → {s:.2f}"]
    tnorm = normalize_title(title)
    for i, pref in enumerate(settings.search.preferred_titles):
        if normalize_title(pref) and normalize_title(pref) in tnorm:
            ps = max(0.8, 1.0 - 0.025 * i)
            if ps > s:
                s = ps
            ev.append(f"title matches preferred title #{i + 1} '{pref}'")
            break
    excluded = [k.strip() for k in settings.search.excluded_title_keywords
                if k.strip() and re.search(rf"\b{re.escape(k.strip())}\b", (title or "").lower())]
    if excluded:
        s *= 0.5
        ev.append(f"title contains excluded keyword(s): {', '.join(excluded)}")
    return min(1.0, s), ev


def score_location(job: dict, req: JobRequirements, settings: Settings):
    arr = job.get("work_arrangement") or "unknown"
    country = job.get("country")
    city = job.get("city")
    home = settings.search.primary_country
    preferred = {c.lower() for c in settings.search.preferred_locations}
    constraints: list[HardConstraint] = []
    ev = [f"arrangement: {arr}; location: {job.get('location') or 'unknown'}"]
    eligibility = ""

    if arr != "unknown" and arr not in settings.search.work_arrangements:
        ev.append(f"'{arr}' is not one of your configured arrangements")
        base_penalty = 0.3
    else:
        base_penalty = 1.0

    if arr == "remote":
        if req.remote_eligibility == "pakistan_ok" or (country == home and req.remote_eligibility != "region_restricted"):
            s, eligibility = 1.0, f"remote; open to candidates in {home}"
            constraints.append(HardConstraint(name="location", status="pass", detail=eligibility))
        elif req.remote_eligibility == "region_restricted":
            s, eligibility = 0.0, "remote but restricted: " + "; ".join((req.location_restrictions + req.work_authorization)[:3])
            constraints.append(HardConstraint(name="location", status="fail", detail=eligibility))
        else:
            s = 0.55 if settings.search.include_international_remote or country in (None, "Worldwide") else 0.35
            eligibility = (f"remote; eligibility for {home}-based applicants not stated: verify before applying")
            constraints.append(HardConstraint(name="location", status="unknown", detail=eligibility))
    elif country == home or (country is None and city and city.lower() in preferred):
        if city and city.lower() in preferred:
            s, eligibility = 1.0, f"{arr} in {city} (preferred location)"
        else:
            s, eligibility = 0.6, f"{arr} in {city or home}; outside preferred cities (may need relocation)"
        constraints.append(HardConstraint(name="location", status="pass", detail=eligibility))
    elif country is None:
        s, eligibility = 0.5, "location not stated: verify"
        constraints.append(HardConstraint(name="location", status="unknown", detail=eligibility))
    else:
        s, eligibility = 0.0, f"{arr} role in {country}: not in {home}"
        constraints.append(HardConstraint(name="location", status="fail", detail=eligibility))

    if req.work_authorization and not (arr == "remote" and req.remote_eligibility == "pakistan_ok"):
        constraints.append(HardConstraint(name="work authorization", status="fail" if country != home else "unknown",
                                          detail="; ".join(req.work_authorization[:3])))
    return s * base_penalty, ev + [eligibility], constraints, eligibility


def score_domain(req: JobRequirements, settings: Settings):
    cand = {d.lower() for d in settings.matching.candidate_domains}
    pref = {d.lower() for d in settings.search.preferred_industries}
    excl = {d.lower() for d in settings.search.excluded_industries}
    doms = {d.lower() for d in req.domains}
    if doms & excl:
        return 0.0, [f"excluded industry: {', '.join(sorted(doms & excl))}"]
    if doms & (cand | pref):
        return 1.0, [f"domain match: {', '.join(sorted(doms & (cand | pref)))}"]
    if not doms:
        return 0.7, ["no specific industry detected (neutral)"]
    return 0.5, [f"different domain: {', '.join(sorted(doms))}"]


def check_certifications(req: JobRequirements, cand: CandidateView) -> list[HardConstraint]:
    out = []
    for c in req.mandatory_certifications:
        if c.startswith("DEGREE: "):
            text = c[len("DEGREE: "):]
            has_master = any(re.search(r"\b(master|ms|msc|m\.s|mphil|phd)\b", d, re.I) for d in cand.degrees)
            out.append(HardConstraint(name="degree", status="pass" if has_master else "fail",
                                      detail=f"requires: {text}" + ("" if has_master else " (profile shows no postgraduate degree)")))
            continue
        tokens = {t for t in re.findall(r"[a-z]+", c.lower()) if t not in
                  {"certification", "certified", "certificate", "is", "required", "must", "have", "a", "an", "the",
                   "mandatory", "valid", "and", "or", "of", "in", "with"}}
        held = any(len(tokens & set(re.findall(r"[a-z]+", h.lower()))) >= max(2, len(tokens) // 2) for h in cand.certifications)
        out.append(HardConstraint(name="certification", status="pass" if held else "fail",
                                  detail=f"requires: {c}" + ("" if held else " (not in your profile)")))
    return out


# ------------------------------------------------------------------ main entry

def category_for(score: float, settings: Settings) -> str:
    c = settings.matching.categories
    return "strong" if score >= c.strong else "potential" if score >= c.potential else "stretch" if score >= c.stretch else "low"


def score_job(job: dict, description: str, req: JobRequirements, profile: CandidateProfile,
              taxonomy: Taxonomy, settings: Settings, cand: CandidateView | None = None,
              ai_responsibilities: tuple[float, list[str]] | None = None) -> MatchResult:
    cand = cand or candidate_view(profile, taxonomy, settings)
    w = settings.matching.weights
    sk, sk_ev, matched, miss_req, miss_pref, transferable = score_skills(req, cand, taxonomy)
    rs, rs_ev = score_responsibilities(req, description, cand, taxonomy)
    if ai_responsibilities is not None:
        ai_s, ai_ev = ai_responsibilities
        rs_ev = [f"deterministic {rs:.0%}, AI {ai_s:.0%} → blended 50/50"] + rs_ev + [f"AI: {e}" for e in ai_ev]
        rs = 0.5 * rs + 0.5 * max(0.0, min(1.0, ai_s))
    sn, sn_ev, compat = score_seniority(req, job.get("title"), cand, settings)
    rl, rl_ev = score_role(job.get("title"), req, settings)
    lc, lc_ev, loc_constraints, eligibility = score_location(job, req, settings)
    dm, dm_ev = score_domain(req, settings)

    comps = [
        ComponentScore(name="skills", weight=w.skills, score=round(sk, 3), points=round(sk * w.skills, 1), evidence=sk_ev),
        ComponentScore(name="responsibilities", weight=w.responsibilities, score=round(rs, 3),
                       points=round(rs * w.responsibilities, 1), evidence=rs_ev),
        ComponentScore(name="seniority", weight=w.seniority, score=round(sn, 3), points=round(sn * w.seniority, 1), evidence=sn_ev),
        ComponentScore(name="role_alignment", weight=w.role_alignment, score=round(rl, 3),
                       points=round(rl * w.role_alignment, 1), evidence=rl_ev),
        ComponentScore(name="location", weight=w.location, score=round(lc, 3), points=round(lc * w.location, 1), evidence=lc_ev),
        ComponentScore(name="domain", weight=w.domain, score=round(dm, 3), points=round(dm * w.domain, 1), evidence=dm_ev),
    ]
    raw_score = round(sum(c.points for c in comps), 1)
    score, adjustments = raw_score, []
    thr = settings.matching.off_target_role_threshold
    if thr > 0 and rl < thr:
        factor = 0.5 + 0.5 * (rl / thr)
        score = round(raw_score * factor, 1)
        adjustments.append(f"career-direction adjustment ×{factor:.2f} (role fit {rl:.0%} < {thr:.0%}): "
                           f"{raw_score:.1f} → {score:.1f}")
    constraints = loc_constraints + check_certifications(req, cand)
    eligible = not any(c.status == "fail" for c in constraints)
    category = category_for(score, settings)

    # Confidence: how much we can trust the inputs, not how good the match is.
    n_skills = len(req.required_skills) + len(req.preferred_skills) + len(req.unclassified_skills)
    if len(description) >= 600 and n_skills >= 5 and (req.required_skills or req.preferred_skills):
        confidence = "high"
    elif len(description) >= 250 and n_skills >= 2:
        confidence = "medium"
    else:
        confidence = "low"
    if any(c.status == "unknown" for c in constraints) and confidence == "high":
        confidence = "medium"

    strengths = []
    for s in matched[:8]:
        lvl = cand.levels.get(s)
        if lvl == "professional":
            strengths.append(f"{s} (professional experience)")
        elif lvl:
            strengths.append(f"{s} ({lvl})")
    strengths += [f"Experience with {c}" for c, v in cand.concepts.items()
                  if v >= 1.0 and any(re.search(CONCEPTS[c], r, re.I) for r in req.responsibilities)][:4]

    reasons_to, reasons_not = [], []
    if rl >= 0.85:
        reasons_to.append("Role is directly aligned with your Data Engineering direction")
    if sk >= 0.7:
        reasons_to.append(f"Strong technical overlap ({len(matched)} matching skills)")
    if lc >= 0.9:
        reasons_to.append(eligibility)
    growth = [s for s in miss_pref + miss_req if taxonomy.category(s) in ("cloud", "warehouse", "orchestration", "processing", "streaming")]
    if growth and sk >= 0.5:
        reasons_to.append("Growth opportunity in: " + ", ".join(growth[:4]))
    if miss_req:
        reasons_not.append("Missing required: " + ", ".join(miss_req[:6]))
    if sn < 0.6:
        reasons_not.append(f"Experience gap: {compat}")
    if rl < 0.6:
        reasons_not.append(f"Role type ({req.role_category}) is outside your target direction")
    for c in constraints:
        if c.status == "fail":
            reasons_not.append(f"Hard constraint failed: {c.name}: {c.detail}")
        elif c.status == "unknown":
            reasons_not.append(f"Check {c.name}: {c.detail}")

    if not eligible:
        cert_only = all(c.name in ("certification", "degree") for c in constraints if c.status == "fail")
        recommendation = "review_eligibility" if cert_only and category != "low" else "skip"
    else:
        recommendation = {"strong": "apply", "potential": "consider", "stretch": "stretch", "low": "skip"}[category]
    if confidence == "low" and recommendation in ("apply", "consider"):
        recommendation = "needs_details"

    explanation = (f"Scored {score:.0f}/100 ({category}){' after career-direction adjustment' if adjustments else ''}. Skills {sk:.0%}, responsibilities {rs:.0%}, "
                   f"seniority {sn:.0%} ({compat}), role fit {rl:.0%}, location {lc:.0%}. "
                   + ("Eligible." if eligible else "Not eligible as stated: " +
                      "; ".join(c.detail for c in constraints if c.status == "fail") + "."))

    return MatchResult(
        score=score, category=category, confidence=confidence, components=comps, hard_constraints=constraints,
        raw_score=raw_score, adjustments=adjustments, eligible=eligible, strengths=strengths, missing_required=miss_req, missing_preferred=miss_pref,
        transferable=transferable, experience_compatibility=compat, location_eligibility=eligibility,
        reasons_to_apply=reasons_to, reasons_not_to_apply=reasons_not, recommendation=recommendation,
        explanation=explanation, ai_used=False, scoring_version=SCORING_VERSION,
    )
