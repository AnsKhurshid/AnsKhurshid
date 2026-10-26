"""LinkedIn connector (compliant mode).

LinkedIn offers no public job-search API for individuals and its User Agreement prohibits scraping or
automated access, so this connector never fetches linkedin.com itself. Instead it:

  1. builds search URLs from your settings for you to open in your own browser;
  2. imports what you bring back: job URLs (.txt), saved job pages (.html, "Save Page As"),
     or pasted job descriptions (.txt with 'Title:'/'Company:' headers).

A URL without details becomes a 'needs_manual_review' record so it is tracked and deduplicated, and
you are told to supply the description.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from jobagent.config import Settings
from jobagent.models import RawJob, RetrievalStatus, SourceResult
from jobagent.sources.base import CollectRequest, JobSource
from jobagent.sources.html_parser import parse_job_html
from jobagent.sources.textjob import looks_like_text_job, parse_text_jobs

log = logging.getLogger("jobagent.sources.linkedin")

JOB_ID_PATTERNS = [
    re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*?-)?(\d{6,})"),
    re.compile(r"linkedin\.com/comm/jobs/view/(\d{6,})"),
]
URL_RE = re.compile(r"https?://[^\s<>\"']+")

# Layout hints for saved pages (guest and logged-in layouts). These change over time; missing fields
# downgrade the record to 'partial' rather than failing.
SELECTORS = {
    "title": [".top-card-layout__title", ".topcard__title", ".job-details-jobs-unified-top-card__job-title",
              ".jobs-unified-top-card__job-title", "h1.t-24"],
    "company": [".topcard__org-name-link", ".topcard__flavor a", ".job-details-jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__company-name"],
    "location": [".topcard__flavor--bullet", ".job-details-jobs-unified-top-card__primary-description-container",
                 ".jobs-unified-top-card__bullet", ".job-details-jobs-unified-top-card__tertiary-description-container"],
    "description": [".show-more-less-html__markup", ".description__text", "#job-details",
                    ".jobs-description__content", ".jobs-box__html-content"],
    "posted": [".posted-time-ago__text", ".topcard__flavor--metadata"],
}
WORKPLACE_FILTER = {"on-site": "1", "remote": "2", "hybrid": "3"}


def linkedin_job_id(url: str) -> str | None:
    if not url or "linkedin.com" not in url:
        return None
    for pat in JOB_ID_PATTERNS:
        if m := pat.search(url):
            return m.group(1)
    qs = parse_qs(urlparse(url).query)
    for key in ("currentJobId", "jobId"):
        if qs.get(key) and qs[key][0].isdigit():
            return qs[key][0]
    return None


def canonical_linkedin_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def build_search_urls(settings: Settings, per_city: bool = False) -> list[dict]:
    """Search links for the user to open manually, Pakistan first.

    The Pakistan geo filter already covers every city, so by default each title gets one link for all
    configured arrangements plus one remote-only link. `per_city` adds on-site/hybrid links per city.
    """
    s = settings.search
    seconds = max(1, s.posted_within_days) * 86400
    geo = settings.sources.linkedin.geo_id_pakistan
    base = "https://www.linkedin.com/jobs/search/?"

    def link(title: str, location: str, arrangements: list[str], geo_id: str | None) -> dict:
        params = [f"keywords={quote_plus(title)}", f"location={quote_plus(location)}", f"f_TPR=r{seconds}",
                  "f_WT=" + quote_plus(",".join(WORKPLACE_FILTER[a] for a in arrangements))]
        if geo_id:
            params.append(f"geoId={geo_id}")
        return {"title": title, "location": location, "work_arrangement": "/".join(arrangements),
                "url": base + "&".join(params)}

    out = []
    for title in s.preferred_titles:
        out.append(link(title, s.primary_country, list(s.work_arrangements), geo))
        if "remote" in s.work_arrangements:
            out.append(link(title, s.primary_country, ["remote"], geo))
        if per_city:
            local = [a for a in s.work_arrangements if a != "remote"]
            for city in s.preferred_locations:
                if local:
                    out.append(link(title, f"{city}, {s.primary_country}", local, None))
    if s.include_international_remote:
        for title in s.preferred_titles:
            out.append(link(title, "Worldwide", ["remote"], None))
    return out


class LinkedInSource(JobSource):
    name = "linkedin"

    def handles_url(self, url: str) -> bool:
        return "linkedin.com" in (urlparse(url).hostname or "")

    def _inbox_files(self) -> list[Path]:
        inbox = self.settings.path(self.settings.sources.linkedin.inbox_dir)
        if not inbox.exists():
            return []
        return sorted(p for p in inbox.iterdir() if p.suffix.lower() in (".html", ".htm", ".txt", ".md"))

    def _from_url(self, url: str, note: str) -> RawJob | None:
        job_id = linkedin_job_id(url)
        if not job_id:
            return None
        return RawJob(source=self.name, source_job_id=job_id, url=canonical_linkedin_url(job_id),
                      retrieval_status=RetrievalStatus.NEEDS_MANUAL_REVIEW, retrieval_notes=note)

    def parse_file(self, path: Path) -> tuple[list[RawJob], list[str]]:
        errors: list[str] = []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return [], [f"{path.name}: cannot read ({exc})"]
        jobs: list[RawJob] = []
        if path.suffix.lower() in (".html", ".htm"):
            job = parse_job_html(text, self.name, selectors=SELECTORS)
            if job is None:
                errors.append(f"{path.name}: no job posting found in saved page")
            else:
                job.source_job_id = linkedin_job_id(job.url or "") or linkedin_job_id(text)
                if job.source_job_id:
                    job.url = canonical_linkedin_url(job.source_job_id)
                job.extra["imported_file"] = path.name
                jobs.append(job)
        elif looks_like_text_job(text):
            for job in parse_text_jobs(text, self.name):
                if job.url and (jid := linkedin_job_id(job.url)):
                    job.source_job_id, job.url = jid, canonical_linkedin_url(jid)
                job.extra["imported_file"] = path.name
                jobs.append(job)
        else:
            urls = URL_RE.findall(text)
            for u in urls:
                if job := self._from_url(u, f"URL only (from {path.name}); paste or save the description"):
                    jobs.append(job)
            if urls and not jobs:
                errors.append(f"{path.name}: no LinkedIn job URLs recognised")
        return jobs, errors

    def collect(self, request: CollectRequest) -> SourceResult:
        result = SourceResult(source=self.name, exhaustive=False)
        result.notes.append("LinkedIn is not searched automatically (no permitted API); only jobs you imported "
                            "are included, so results are not exhaustive.")
        files = list(request.files)
        if request.use_inbox:
            files += self._inbox_files()
        for path in files:
            jobs, errors = self.parse_file(path)
            result.jobs.extend(jobs)
            result.errors.extend(errors)
        for url in request.urls:
            if not self.handles_url(url):
                continue
            job = self._from_url(url, "URL supplied on command line; paste or save the description")
            if job:
                result.jobs.append(job)
            else:
                result.errors.append(f"not a LinkedIn job URL: {url}")
        if request.limit:
            result.jobs = result.jobs[:request.limit]
        return result
