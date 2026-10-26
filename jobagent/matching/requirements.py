"""Deterministic extraction of structured requirements from a job description."""
from __future__ import annotations

import re

from jobagent.ingestion.normalize import role_category, seniority_of
from jobagent.models import JobRequirements
from jobagent.taxonomy import Taxonomy

SECTION_PATTERNS = [
    ("preferred", r"nice[- ]to[- ]have|preferred|bonus|good[- ]to[- ]have|desirable|plus(es)?\b|added advantage|"
                  r"would be (a )?(plus|great)|optional|extra credit"),
    ("required", r"requirements?|qualifications?|must[- ]haves?|what you (bring|need|have)|what we('re| are) looking for|"
                 r"who you are|you (have|bring|are)|skills( required| needed)?|required skills|minimum|essential|"
                 r"technical skills|experience required|about you|your profile|ideal candidate|competencies"),
    ("responsibilities", r"responsibilit|what you('ll| will) do|duties|the role|your role|role overview|day[- ]to[- ]day|"
                         r"your impact|key tasks|what you'll be doing|job description|you will|accountabilities"),
    ("other", r"about (us|the company|the team)|benefits|perks|why join|what we offer|compensation|salary|"
              r"how to apply|equal opportunity|our culture|location"),
]
INLINE_PREFERRED = re.compile(
    r"\b(nice to have|is a plus|are a plus|a plus\b|preferred|bonus|good to have|desirable|advantage|"
    r"familiarity with|exposure to|would be (great|nice|a plus)|ideally|optional)\b", re.I)
INLINE_REQUIRED = re.compile(r"\b(must|required|mandatory|essential|minimum|at least|strong|proven|solid)\b", re.I)

YEARS_RE = re.compile(
    r"(?P<min>\d{1,2})(?:\.\d)?\s*\+?\s*(?:(?:-|–|to)\s*(?P<max>\d{1,2})\s*\+?\s*)?(?:years?|yrs?)\b"
    r"(?P<ctx>[^.\n]{0,80})", re.I)
CERT_LINE = re.compile(r"\bcertif", re.I)
DEGREE_MASTER = re.compile(r"\b(master'?s?|m\.?s\.?c?|msc|m\.?sc|ph\.?d|mphil)\b", re.I)
DEGREE_BACHELOR = re.compile(r"\b(bachelor'?s?|b\.?s\.?c?|bsc|b\.?e\b|bs\b|undergraduate)\b", re.I)

COUNTRY_WORDS = (r"(?:the\s+)?(united states|u\.s\.?a?|us|usa|united kingdom|uk|canada|europe|european union|eu|"
                 r"germany|india|uae|united arab emirates|saudi arabia|ksa|australia|latin america|latam|emea|apac|"
                 r"north america|americas|netherlands|poland|spain|ireland)")
RESTRICTION_PATTERNS = [
    re.compile(rf"\b(?:located|based|residing|reside|live|living)\s+(?:in|within)\s+{COUNTRY_WORDS}\b", re.I),
    re.compile(rf"\b{COUNTRY_WORDS}[\s-]+(?:only|based candidates only|residents only)\b", re.I),
    re.compile(rf"\bopen (?:only )?to (?:candidates|applicants|residents) (?:in|from|located in) {COUNTRY_WORDS}\b", re.I),
    re.compile(rf"\bmust be (?:located|based) in {COUNTRY_WORDS}\b", re.I),
]
AUTH_PATTERNS = [
    re.compile(r"\b(?:must be|should be)?\s*(?:legally\s+)?authori[sz]ed to work in\s+(?:the\s+)?([A-Za-z .]{2,30}?)(?:[.,;]|\s+(?:without|and|we)\b|$)", re.I),
    re.compile(r"\b(?:no|unable to|cannot|not able to|do not|will not)\s+(?:provide\s+)?(?:offer\s+)?(?:visa\s+)?sponsor", re.I),
    re.compile(r"\b(?:us|u\.s\.) citizens?(?:hip)?\b|\bgreen card\b|\bsecurity clearance\b", re.I),
]
PAKISTAN_OK = re.compile(
    r"\b(?:candidates|applicants|engineers|professionals|people)?\s*(?:based|located|residing)\s+in\s+pakistan\b|"
    r"\bpakistan[- ]based\b|\bopen to (?:candidates in )?pakistan\b|\bfrom pakistan\b|\bremote\s*(?:\(|-|–)?\s*pakistan\b|"
    r"\b(?:work from )?anywhere in the world\b|\bworldwide\b|\bglobally remote\b|\bwork from anywhere\b", re.I)

DOMAINS = {
    "real estate": r"real[- ]estate|proptech|property listings?|mls\b|realty|mortgage",
    "fintech": r"fintech|banking|bank\b|payments?|financial services|lending|insurance|insurtech",
    "healthcare": r"health ?care|healthtech|medical|clinical|hospital|pharma",
    "e-commerce": r"e-?commerce|retail|marketplace|online store",
    "telecom": r"telecom|telecommunication|mobile operator",
    "logistics": r"logistics|supply chain|shipping|freight|delivery",
    "edtech": r"edtech|education|e-?learning",
    "adtech/marketing": r"adtech|advertising|marketing analytics|martech",
    "gaming": r"gaming|game studio",
    "saas": r"\bsaas\b|software as a service",
}


def _heading_kind(line: str) -> str | None:
    raw = line.strip()
    t = raw.strip("•-*#: \t").lower()
    if not t or len(t) > 60:
        return None
    is_heading_shape = raw.endswith(":") or len(t.split()) <= 6
    if not is_heading_shape:
        return None
    for kind, pat in SECTION_PATTERNS:
        if re.search(rf"^(?:key |main |core |job |technical |preferred |required |minimum |basic )?(?:{pat})", t):
            # A short line like "Python is a plus" is content, not a heading.
            if len(t.split()) > 4 and not raw.endswith(":"):
                return None
            return kind
    return None


def split_description(text: str) -> dict[str, list[str]]:
    """Return lines grouped by section kind: required / preferred / responsibilities / other / intro."""
    out: dict[str, list[str]] = {"intro": []}
    current = "intro"
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        kind = _heading_kind(line)
        if kind:
            current = kind
            out.setdefault(current, [])
            # "Requirements: Python, SQL" — keep content after the colon
            if ":" in line and line.split(":", 1)[1].strip():
                out[current].append(line.split(":", 1)[1].strip())
            continue
        out.setdefault(current, []).append(line.lstrip("•-*· ").strip())
    return out


def extract_years(lines: list[str]) -> tuple[float | None, float | None]:
    mins, maxs = [], []
    for ln in lines:
        for m in YEARS_RE.finditer(ln):
            ctx = (m.group("ctx") or "") + " " + ln
            if not re.search(r"experience|exp\b|working|professional|industry|hands[- ]on|background|in (data|software|etl)|as an? ", ctx, re.I):
                continue
            if re.search(r"\b(old|age|warranty|company has|founded|history)\b", ctx, re.I):
                continue
            lo = float(m.group("min"))
            if lo > 20:
                continue
            mins.append(lo)
            if m.group("max"):
                maxs.append(float(m.group("max")))
    return (max(mins) if mins else None), (max(maxs) if maxs else None)


def extract_requirements(description: str, title: str | None, taxonomy: Taxonomy,
                         extra: dict | None = None) -> JobRequirements:
    sections = split_description(description)
    has_sections = any(k in sections for k in ("required", "preferred", "responsibilities"))
    req_lines = sections.get("required", [])
    pref_lines = sections.get("preferred", [])
    resp_lines = sections.get("responsibilities", [])
    other_lines = sections.get("intro", []) + sections.get("other", [])

    required: dict[str, None] = {}
    preferred: dict[str, None] = {}
    unclassified: dict[str, None] = {}
    for ln in req_lines:
        found = taxonomy.find(ln)
        target = preferred if INLINE_PREFERRED.search(ln) and not re.search(r"\bmust\b|\brequired\b", ln, re.I) else required
        for s in found:
            target.setdefault(s)
    for ln in pref_lines:
        for s in taxonomy.find(ln):
            preferred.setdefault(s)
    for ln in resp_lines + other_lines:
        found = taxonomy.find(ln)
        for s in found:
            if INLINE_PREFERRED.search(ln):
                preferred.setdefault(s)
            elif INLINE_REQUIRED.search(ln) and not has_sections:
                required.setdefault(s)
            else:
                unclassified.setdefault(s)
    for s in list(preferred):
        if s in required:
            del preferred[s]
    for s in list(unclassified):
        if s in required or s in preferred:
            del unclassified[s]

    min_y, max_y = extract_years(req_lines or (resp_lines + other_lines + pref_lines))
    if min_y is None and extra and extra.get("experience_requirements"):
        min_y, max_y = extract_years([str(extra["experience_requirements"])])

    certs = []
    for ln in req_lines + resp_lines + other_lines:
        if CERT_LINE.search(ln) and not INLINE_PREFERRED.search(ln) and re.search(r"required|must|mandatory|essential", ln, re.I):
            certs.append(ln.strip())

    full = description or ""
    restrictions, auth = [], []
    for pat in RESTRICTION_PATTERNS:
        for m in pat.finditer(full):
            restrictions.append(m.group(0).strip())
    for pat in AUTH_PATTERNS:
        for m in pat.finditer(full):
            auth.append(m.group(0).strip())
    loc_req = (extra or {}).get("applicant_location_requirements") or []
    restrictions += [f"applicant location: {r}" for r in loc_req if r and "pakistan" not in str(r).lower()]

    if PAKISTAN_OK.search(full) or any("pakistan" in str(r).lower() for r in loc_req):
        remote = "pakistan_ok"
    elif restrictions or auth:
        remote = "region_restricted"
    else:
        remote = "unspecified"

    degree_req = [ln for ln in req_lines if DEGREE_MASTER.search(ln) and not DEGREE_BACHELOR.search(ln)
                  and re.search(r"degree|master|ms\b|m\.s|phd|ph\.d|msc", ln, re.I)]

    domains = [d for d, pat in DOMAINS.items() if re.search(pat, full, re.I)]
    seniority = seniority_of(title)
    if seniority is None and min_y is not None:
        seniority = "junior" if min_y < 2 else "mid" if min_y < 5 else "senior"

    req = JobRequirements(
        required_skills=list(required), preferred_skills=list(preferred), unclassified_skills=list(unclassified),
        min_years=min_y, max_years=max_y, seniority=seniority,
        responsibilities=[l for l in resp_lines if len(l) > 15][:15],
        mandatory_certifications=certs, location_restrictions=sorted(set(restrictions)),
        work_authorization=sorted(set(auth)), remote_eligibility=remote,
        role_category=role_category(title) if title else None, domains=domains,
    )
    if degree_req:
        req.mandatory_certifications += [f"DEGREE: {d}" for d in degree_req]
    return req
