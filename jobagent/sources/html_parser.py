"""Extract job postings from HTML: schema.org JobPosting JSON-LD first, page heuristics second."""
from __future__ import annotations

import html as htmllib
import json
import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from jobagent.models import RawJob, RetrievalStatus
from jobagent.utils.text import clean_text


ISO_COUNTRIES = {"PK": "Pakistan", "US": "United States", "GB": "United Kingdom", "UK": "United Kingdom",
                 "AE": "United Arab Emirates", "SA": "Saudi Arabia", "QA": "Qatar", "DE": "Germany",
                 "NL": "Netherlands", "CA": "Canada", "AU": "Australia", "IN": "India", "IE": "Ireland"}


def html_to_text(fragment: str) -> str:
    if not fragment:
        return ""
    soup = BeautifulSoup(fragment, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "ul", "ol", "tr"]):
        tag.insert_after("\n")
    return clean_text(htmllib.unescape(soup.get_text()))


def parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    for fmt in ("%d/%m/%Y", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return relative_date(s)


def relative_date(text: str, today: date | None = None) -> date | None:
    """'3 days ago', 'Reposted 2 weeks ago', '1 month ago' -> approximate date."""
    today = today or date.today()
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)s?\s+ago", text or "", re.I)
    if not m:
        return today if re.search(r"\b(just now|today)\b", text or "", re.I) else None
    n, unit = int(m.group(1)), m.group(2).lower()
    days = {"minute": 0, "hour": 0, "day": n, "week": 7 * n, "month": 30 * n}[unit]
    return today - timedelta(days=days)


def _iter_jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    stack.extend(item["@graph"] if isinstance(item["@graph"], list) else [item["@graph"]])
                t = item.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    yield item


def _jsonld_location(jp: dict) -> tuple[str | None, bool]:
    remote = str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE"
    locs = jp.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    names = []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, str):
            names.append(addr)
            continue
        parts = [addr.get("addressLocality"), addr.get("addressRegion")]
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        country = ISO_COUNTRIES.get(str(country).upper(), country) if country else None
        parts.append(country)
        name = ", ".join(p for p in parts if p)
        if name:
            names.append(name)
    return ("; ".join(names) or None), remote


def _salary(jp: dict) -> tuple[float | None, float | None, str | None, str | None]:
    bs = jp.get("baseSalary")
    if not isinstance(bs, dict):
        return None, None, None, None
    cur = bs.get("currency")
    val = bs.get("value") or {}
    if isinstance(val, (int, float, str)):
        try:
            v = float(val)
            return v, v, cur, None
        except ValueError:
            return None, None, cur, None
    def f(x):
        try:
            return float(x) if x is not None else None
        except (TypeError, ValueError):
            return None
    return f(val.get("minValue") or val.get("value")), f(val.get("maxValue") or val.get("value")), cur, (val.get("unitText") or None)


def jobposting_to_raw(jp: dict, source: str, url: str | None) -> RawJob:
    org = jp.get("hiringOrganization") or {}
    company = org.get("name") if isinstance(org, dict) else (org if isinstance(org, str) else None)
    location, remote = _jsonld_location(jp)
    smin, smax, cur, period = _salary(jp)
    emp = jp.get("employmentType")
    if isinstance(emp, list):
        emp = ", ".join(emp)
    desc = html_to_text(jp.get("description") or "")
    req = jp.get("applicantLocationRequirements")
    extra = {}
    if req:
        reqs = req if isinstance(req, list) else [req]
        extra["applicant_location_requirements"] = [
            (r.get("name") if isinstance(r, dict) else str(r)) for r in reqs]
    if jp.get("experienceRequirements"):
        extra["experience_requirements"] = jp.get("experienceRequirements")
    return RawJob(
        source=source, url=url or jp.get("url"), title=clean_text(jp.get("title")) or None, company=company,
        location=location, description=desc or None, employment_type=emp,
        work_arrangement="remote" if remote else None,
        salary_min=smin, salary_max=smax, salary_currency=cur, salary_period=period,
        posted_at=parse_date(jp.get("datePosted")), deadline=parse_date(jp.get("validThrough")),
        hiring_organization=company, extra=extra,
    )


def grade(job: RawJob) -> RetrievalStatus:
    if job.title and job.company and job.description and len(job.description) >= 300:
        return RetrievalStatus.COMPLETE
    if job.title or job.description:
        return RetrievalStatus.PARTIAL
    return RetrievalStatus.NEEDS_MANUAL_REVIEW


def parse_job_html(html: str, source: str, url: str | None = None,
                   selectors: dict[str, list[str]] | None = None) -> RawJob | None:
    """Parse one job page. Returns None when nothing job-like is found."""
    soup = BeautifulSoup(html, "lxml")
    if not url:
        link = soup.find("link", rel="canonical") or soup.find("meta", property="og:url")
        url = (link.get("href") or link.get("content")) if link else None
    for jp in _iter_jsonld(soup):
        job = jobposting_to_raw(jp, source, url)
        job.retrieval_status = grade(job)
        job.retrieval_notes = "parsed from schema.org JobPosting data"
        return job

    selectors = selectors or {}

    def first(keys: list[str]) -> str | None:
        for sel in keys:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el
        return None

    title_el = first(selectors.get("title", []) + ["h1"])
    company_el = first(selectors.get("company", []))
    location_el = first(selectors.get("location", []))
    desc_el = first(selectors.get("description", []) + ["[class*=description]", "main", "article"])
    posted_el = first(selectors.get("posted", []))
    title = clean_text(title_el.get_text(" ")) if title_el else None
    if not title:
        og = soup.find("meta", property="og:title")
        title = og.get("content") if og else (soup.title.get_text(strip=True) if soup.title else None)
    description = html_to_text(str(desc_el)) if desc_el else None
    if not title and not description:
        return None
    job = RawJob(
        source=source, url=url, title=title,
        company=clean_text(company_el.get_text(" ")) if company_el else None,
        location=clean_text(location_el.get_text(" ")) if location_el else None,
        description=description,
        posted_at=relative_date(posted_el.get_text(" ")) if posted_el else None,
    )
    job.retrieval_status = grade(job)
    job.retrieval_notes = "parsed from page layout (no structured data); verify fields"
    return job
