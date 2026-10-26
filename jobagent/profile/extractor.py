"""Deterministic resume -> CandidateProfile extraction.

Best effort by design: anything ambiguous goes into `unverified` so the user can confirm it during
review. Nothing is inferred that is not present in the resume text.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from jobagent.models import (CandidateProfile, Certification, Contact, Education, Experience, Project,
                             SkillEntry)
from jobagent.profile.parser import Line
from jobagent.taxonomy import Taxonomy

SECTION_ALIASES = {
    "summary": ["summary", "professional summary", "profile", "professional profile", "about me", "objective",
                "career objective", "career summary", "overview"],
    "experience": ["experience", "work experience", "professional experience", "employment history",
                   "employment", "work history", "career history", "relevant experience"],
    "projects": ["projects", "personal projects", "academic projects", "key projects", "selected projects",
                 "portfolio", "project experience", "side projects"],
    "education": ["education", "academic background", "academics", "qualifications", "education and training"],
    "skills": ["skills", "technical skills", "core skills", "key skills", "core competencies", "competencies",
               "technologies", "tech stack", "tools and technologies", "tools & technologies", "expertise",
               "areas of expertise", "skills and tools", "skills & tools"],
    "certifications": ["certifications", "certificates", "licenses and certifications",
                       "licenses & certifications", "courses", "training", "certifications and courses",
                       "certifications & courses", "professional development", "online courses"],
    "achievements": ["achievements", "awards", "honors", "honours", "accomplishments", "awards and achievements"],
    "other": ["languages", "interests", "hobbies", "references", "volunteer", "volunteering",
              "publications", "extracurricular activities"],
}
_HEADING_LOOKUP = {a: k for k, v in SECTION_ALIASES.items() for a in v}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE = rf"(?:{_MON}\.?\s*,?\s*\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE})\s*(?:-|–|—|to|until)\s*(?P<end>{_DATE}|present|current|now|ongoing|till date|to date)",
    re.IGNORECASE)

TITLE_WORDS = re.compile(
    r"\b(engineer|developer|analyst|intern|internship|manager|consultant|associate|lead|scientist|specialist|"
    r"architect|administrator|programmer|officer|executive|trainee|assistant|director|head|designer|tester|"
    r"coordinator|technician|researcher|fellow)\b", re.IGNORECASE)
DEGREE_WORDS = re.compile(
    r"\b(bachelor|master|b\.?s\.?c?|m\.?s\.?c?|bs|ms|be|me|b\.?e|m\.?e|phd|ph\.d|mba|bba|bscs|bsse|mscs|"
    r"intermediate|matric|f\.?sc|a[- ]levels?|o[- ]levels?|diploma|associate degree)\b", re.IGNORECASE)
METRIC_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|percent|x\b|\+|k\b|m\b|million|thousand|hours?|hrs|minutes?|mins|days?|weeks?|"
    r"records|rows|tables|pipelines|jobs|sources|users|clients|feeds|gb|tb|mb))", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s\-()]{8,}\d)")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-%]+/?", re.IGNORECASE)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+/?", re.IGNORECASE)
SPLIT_RE = re.compile(r"\s+(?:\||—|–|-|@|at)\s+|\s*\|\s*|,\s+(?=[A-Z])")


def _section_of(line: Line) -> str | None:
    key = re.sub(r"[^a-z& ]", "", line.text.lower()).strip()
    key = re.sub(r"\s+", " ", key)
    if key in _HEADING_LOOKUP and len(line.text) <= 45:
        return _HEADING_LOOKUP[key]
    return None


def split_sections(lines: list[Line]) -> dict[str, list[Line]]:
    sections: dict[str, list[Line]] = {"header": []}
    current = "header"
    for ln in lines:
        sec = _section_of(ln)
        if sec and not ln.bullet:
            current = sec
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(ln)
    return sections


def _parse_date(text: str, is_end: bool) -> date | None:
    t = text.strip().lower().rstrip(".")
    if t in ("present", "current", "now", "ongoing", "till date", "to date"):
        return date.today()
    if m := re.match(r"(\d{1,2})/(\d{4})", t):
        return date(int(m.group(2)), max(1, min(12, int(m.group(1)))), 1)
    if m := re.match(rf"({_MON})\.?\s*,?\s*(\d{{4}})", t):
        return date(int(m.group(2)), MONTHS[m.group(1)[:3]], 1)
    if m := re.match(r"(\d{4})", t):
        return date(int(m.group(1)), 12 if is_end else 1, 1)
    return None


def months_between(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    s, e = _parse_date(start, False), _parse_date(end, True)
    if not s or not e or e < s:
        return None
    return (e.year - s.year) * 12 + (e.month - s.month) + 1


def total_experience_years(experience: list[Experience], exclude_internships: bool = True) -> float | None:
    """Merge overlapping date ranges and return total years (1 decimal)."""
    ranges = []
    for x in experience:
        if exclude_internships and re.search(r"\bintern(ship)?\b|\btrainee\b", x.title, re.IGNORECASE):
            continue
        s, e = _parse_date(x.start or "", False), _parse_date(x.end or "", True)
        if s and e and e >= s:
            ranges.append((s.year * 12 + s.month, e.year * 12 + e.month))
    if not ranges:
        return None
    ranges.sort()
    total, (cs, ce) = 0, ranges[0]
    for s, e in ranges[1:]:
        if s <= ce + 1:
            ce = max(ce, e)
        else:
            total += ce - cs + 1
            cs, ce = s, e
    total += ce - cs + 1
    return round(total / 12, 1)


def _parse_header_block(header: list[str]) -> tuple[str | None, str | None, str | None, str | None, str | None, bool]:
    """From the non-bullet lines heading an experience entry, return (title, employer, start, end, location, ambiguous)."""
    start = end = None
    rest: list[str] = []
    for h in header:
        m = DATE_RANGE_RE.search(h)
        if m and not start:
            start, end = m.group("start").strip(), m.group("end").strip()
            h = (h[:m.start()] + h[m.end():]).strip(" |,–—-()")
        if h:
            rest.append(h)
    parts: list[str] = []
    for r in rest:
        parts.extend(p.strip(" |,–—-()") for p in SPLIT_RE.split(r) if p and p.strip(" |,–—-()"))
    title = next((p for p in parts if TITLE_WORDS.search(p)), None)
    others = [p for p in parts if p != title]
    location = next((p for p in others if re.search(
        r"\b(pakistan|lahore|karachi|islamabad|rawalpindi|remote|hybrid|usa|uk|uae|canada|on-?site)\b", p, re.I)), None)
    others = [p for p in others if p != location]
    employer = others[0] if others else None
    ambiguous = title is None or employer is None or start is None
    return title, employer, start, end, location, ambiguous


def _entries(lines: list[Line]) -> list[tuple[list[str], list[str]]]:
    """Group a section into (header_lines, bullet_lines) entries."""
    entries: list[tuple[list[str], list[str]]] = []
    header: list[str] = []
    bullets: list[str] = []
    for ln in lines:
        if ln.bullet:
            bullets.append(ln.text)
            continue
        # A non-bullet line after bullets starts a new entry; long prose lines without bullets are
        # treated as bullets (some resumes write paragraphs).
        if bullets:
            entries.append((header, bullets))
            header, bullets = [], []
        if len(ln.text) > 140 and header:
            bullets.append(ln.text)
        else:
            header.append(ln.text)
    if header or bullets:
        entries.append((header, bullets))
    return entries


def _split_experience_headers(entries):
    """Some resumes stack several roles' headers without bullets; split on repeated date ranges."""
    out = []
    for header, bullets in entries:
        idx = [i for i, h in enumerate(header) if DATE_RANGE_RE.search(h)]
        if len(idx) <= 1:
            out.append((header, bullets))
            continue
        # keep it simple: only the last header group owns the bullets
        groups, prev = [], 0
        for i in idx[1:]:
            cut = i - 1 if i - 1 > prev else i
            groups.append(header[prev:cut])
            prev = cut
        groups.append(header[prev:])
        for g in groups[:-1]:
            out.append((g, []))
        out.append((groups[-1], bullets))
    return out


def extract_profile(lines: list[Line], taxonomy: Taxonomy, resume_sha: str | None = None) -> CandidateProfile:
    sections = split_sections(lines)
    unverified: list[str] = []
    header_text = "\n".join(l.text for l in sections.get("header", []))
    all_text = "\n".join(l.text for l in lines)

    # ---- identity / contact (kept local)
    contact = Contact(
        email=(m.group(0) if (m := EMAIL_RE.search(all_text)) else None),
        phone=(m.group(0).strip() if (m := PHONE_RE.search(header_text)) else None),
        linkedin=(m.group(0) if (m := LINKEDIN_RE.search(all_text)) else None),
        github=(m.group(0) if (m := GITHUB_RE.search(all_text)) else None),
    )
    header_lines = [l.text for l in sections.get("header", [])]
    cand_name = next((h for h in header_lines if not EMAIL_RE.search(h) and not PHONE_RE.search(h)
                 and len(h.split()) <= 5 and not any(c.isdigit() for c in h)), None)
    headline = next((h for h in header_lines[1:4] if h != cand_name and TITLE_WORDS.search(h) and len(h) < 90), None)
    loc_line = next((h for h in header_lines if re.search(r"\b(pakistan|lahore|karachi|islamabad|rawalpindi)\b", h, re.I)), None)
    if loc_line:
        m = re.search(r"([A-Z][a-z]+(?:,\s*)?(?:Punjab|Sindh)?,?\s*Pakistan|Lahore|Karachi|Islamabad|Rawalpindi)", loc_line)
        contact.location = m.group(0) if m else None

    summary_lines = [l.text for l in sections.get("summary", [])]
    summary = " ".join(summary_lines) or None

    # ---- experience
    experience: list[Experience] = []
    for header, bullets in _split_experience_headers(_entries(sections.get("experience", []))):
        if not header and experience:
            experience[-1].bullets.extend(bullets)
            continue
        title, employer, start, end, location, ambiguous = _parse_header_block(header)
        exp = Experience(employer=employer or "UNKNOWN EMPLOYER", title=title or "UNKNOWN TITLE",
                         start=start, end=end, location=location, bullets=bullets)
        if ambiguous:
            unverified.append(f"Experience entry parsed from {header!r}: please confirm employer/title/dates.")
        experience.append(exp)

    # ---- projects
    projects: list[Project] = []
    for header, bullets in _entries(sections.get("projects", [])):
        if not header and projects:
            projects[-1].bullets.extend(bullets)
            continue
        name_line = header[0] if header else (bullets[0][:60] if bullets else "Project")
        desc = " ".join(header[1:]) or None
        kind = "learning" if re.search(r"\b(course|tutorial|bootcamp|learning|udemy|coursera)\b",
                                       " ".join(header + bullets), re.I) else "portfolio"
        projects.append(Project(name=re.split(r"\s+[|–—-]\s+", name_line)[0].strip(), kind=kind,
                                description=desc, bullets=bullets))
        unverified.append(f"Project '{projects[-1].name}' classified as {kind}; change kind to 'professional' "
                          "if it was done for an employer.")

    # ---- education
    education: list[Education] = []
    for header, bullets in _entries(sections.get("education", [])):
        block = header + bullets
        if not block:
            continue
        rng = next((m for b in block if (m := DATE_RANGE_RE.search(b))), None)
        parts = [p.strip(" |,–—-()") for b in block for p in re.split(r"\s*[|–—]\s*|\s+-\s+", DATE_RANGE_RE.sub("", b))]
        parts = [p for p in parts if p and not re.fullmatch(r"(19|20)\d{2}", p)]
        degree = next((p for p in parts if DEGREE_WORDS.search(p)), None)
        inst = next((p for p in parts if p != degree and re.search(
            r"\b(university|college|institute|school|academy|uet|nust|fast|lums|comsats|pucit)\b", p, re.I)), None)
        inst = inst or next((p for p in parts if p != degree), degree or block[0])
        years = re.findall(r"\b((?:19|20)\d{2})\b", " ".join(block))
        education.append(Education(institution=inst, degree=degree,
                                   start=rng.group("start") if rng else None,
                                   end=rng.group("end") if rng else (years[-1] if years else None)))
        if not degree:
            unverified.append(f"Education entry {block!r}: degree not recognised; please confirm.")

    # ---- certifications
    certifications = []
    for ln in sections.get("certifications", []):
        t = ln.text.strip()
        if len(t) < 3:
            continue
        issuer = None
        if m := re.search(r"\b(AWS|Amazon|Microsoft|Google|Coursera|Udemy|DataCamp|IBM|Databricks|Snowflake|Oracle|LinkedIn Learning)\b", t):
            issuer = m.group(1)
        yr = re.search(r"\b((?:19|20)\d{2})\b", t)
        certifications.append(Certification(name=t, issuer=issuer, date=yr.group(1) if yr else None))

    # ---- skills with evidence levels
    def scan(lines_: list[str]) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for txt in lines_:
            for skill in taxonomy.find(txt):
                found.setdefault(skill, []).append(txt)
        return found

    exp_lines = [b for e in experience for b in e.bullets] + [l.text for l in sections.get("experience", []) if not l.bullet]
    proj_prof = [b for p in projects if p.kind == "professional" for b in p.bullets + [p.description or ""]]
    proj_other = [b for p in projects if p.kind == "portfolio" for b in p.bullets + [p.name, p.description or ""]]
    learn = [b for p in projects if p.kind == "learning" for b in p.bullets + [p.name, p.description or ""]]
    learn += [c.name for c in certifications] + [l.text for l in sections.get("education", [])]
    listed_lines = [l.text for l in sections.get("skills", [])] + summary_lines

    prof = scan(exp_lines + proj_prof)
    proj = scan(proj_other)
    stud = scan(learn)
    listed = scan(listed_lines)

    for e in experience:
        e.skills = sorted(scan(e.bullets + [e.title]).keys())
    for p in projects:
        p.skills = sorted(scan(p.bullets + [p.name, p.description or ""]).keys())

    skills: list[SkillEntry] = []
    for name, ev in prof.items():
        skills.append(SkillEntry(name=name, level="professional", evidence=ev[:3]))
    for name, ev in proj.items():
        if name not in prof:
            skills.append(SkillEntry(name=name, level="project", evidence=ev[:3]))
    for name, ev in listed.items():
        if name not in prof and name not in proj:
            skills.append(SkillEntry(name=name, level="listed", evidence=ev[:2]))
            unverified.append(f"Skill '{name}' appears only in a skills list/summary; set level to professional, "
                              "project or studied.")
    for name, ev in stud.items():
        if all(s.name != name for s in skills):
            skills.append(SkillEntry(name=name, level="studied", evidence=ev[:2]))

    achievements = [b for b in exp_lines + proj_prof + proj_other if METRIC_RE.search(b)]

    profile = CandidateProfile(
        name=cand_name, headline=headline, contact=contact, summary=summary,
        experience=experience, projects=projects, education=education, certifications=certifications,
        skills=sorted(skills, key=lambda s: (["professional", "project", "listed", "studied"].index(s.level), s.name)),
        achievements=achievements, unverified=unverified,
        source_resume_sha256=resume_sha, extracted_at=datetime.now(timezone.utc),
    )
    profile.total_experience_years = total_experience_years(experience)
    if profile.total_experience_years is None:
        unverified.append("Could not compute total experience from dates; set total_experience_years.")
    else:
        unverified.append(f"Total professional experience computed as {profile.total_experience_years} years "
                          "(internships excluded, overlaps merged); correct if wrong.")
    if not experience:
        unverified.append("No work-experience section detected; check section headings.")
    return profile
