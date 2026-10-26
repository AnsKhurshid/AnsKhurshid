"""Generic import: CSV / JSON / pasted-text job files, and individual public URLs (robots.txt-respecting)."""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from jobagent.models import RawJob, RetrievalStatus, SourceResult
from jobagent.sources.base import CollectRequest, JobSource
from jobagent.sources.html_parser import grade, parse_date, parse_job_html
from jobagent.sources.textjob import looks_like_text_job, parse_text_jobs
from jobagent.sources.url_fetch import Fetcher, FetchRefused
from jobagent.utils.retry import PermanentError, TransientError

log = logging.getLogger("jobagent.sources.manual")

COLUMN_ALIASES = {
    "title": ["title", "job title", "job_title", "position", "role"],
    "company": ["company", "company name", "company_name", "employer", "organization"],
    "location": ["location", "city", "job location"],
    "description": ["description", "job description", "job_description", "details", "jd"],
    "url": ["url", "link", "job url", "job_url", "job link", "apply url"],
    "work_arrangement": ["work arrangement", "work_arrangement", "workplace", "workplace type", "remote", "arrangement"],
    "employment_type": ["employment type", "employment_type", "job type", "type"],
    "posted_at": ["posted", "posted_at", "date posted", "posting date", "date"],
    "deadline": ["deadline", "closing date", "apply by"],
    "source_job_id": ["id", "job id", "job_id"],
    "salary_text": ["salary", "pay", "compensation"],
    "source": ["source", "platform"],
}


def _pick(row: dict, key: str):
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in COLUMN_ALIASES[key]:
        v = lowered.get(alias)
        if v not in (None, ""):
            return str(v).strip()
    return None


def row_to_raw(row: dict, default_source: str) -> RawJob:
    src = (_pick(row, "source") or default_source).lower()
    job = RawJob(
        source=src, source_job_id=_pick(row, "source_job_id"), url=_pick(row, "url"),
        title=_pick(row, "title"), company=_pick(row, "company"), location=_pick(row, "location"),
        description=_pick(row, "description"), work_arrangement=_pick(row, "work_arrangement"),
        employment_type=_pick(row, "employment_type"), posted_at=parse_date(_pick(row, "posted_at")),
        deadline=parse_date(_pick(row, "deadline")),
    )
    if s := _pick(row, "salary_text"):
        job.extra["salary_text"] = s
    job.retrieval_status = grade(job)
    job.retrieval_notes = "imported from file"
    return job


class ManualSource(JobSource):
    name = "manual"

    def __init__(self, settings, fetcher: Fetcher | None = None):
        super().__init__(settings)
        self._fetcher = fetcher

    @property
    def fetcher(self) -> Fetcher:
        if self._fetcher is None:
            self._fetcher = Fetcher(self.settings.sources.url_fetch)
        return self._fetcher

    def handles_url(self, url: str) -> bool:
        return not Fetcher.denied_host(url)

    def parse_file(self, path: Path) -> tuple[list[RawJob], list[str]]:
        suffix = path.suffix.lower()
        try:
            if suffix == ".csv":
                with path.open(newline="", encoding="utf-8-sig") as fh:
                    rows = list(csv.DictReader(fh))
                return [row_to_raw(r, self.name) for r in rows], []
            if suffix == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                rows = data if isinstance(data, list) else data.get("jobs", [data])
                return [row_to_raw(r, self.name) for r in rows if isinstance(r, dict)], []
            if suffix in (".html", ".htm"):
                job = parse_job_html(path.read_text(encoding="utf-8", errors="replace"), self.name)
                return ([job], []) if job else ([], [f"{path.name}: no job posting found"])
            if suffix in (".txt", ".md"):
                text = path.read_text(encoding="utf-8", errors="replace")
                if looks_like_text_job(text):
                    return parse_text_jobs(text, self.name), []
                return [], [f"{path.name}: not a recognised job text file (needs Title:/Company: headers)"]
        except (OSError, json.JSONDecodeError, csv.Error, UnicodeDecodeError) as exc:
            return [], [f"{path.name}: {exc}"]
        return [], [f"{path.name}: unsupported file type"]

    def fetch_url(self, url: str) -> tuple[RawJob | None, str | None]:
        try:
            html = self.fetcher.get(url)
        except FetchRefused as exc:
            stub = RawJob(source=self.name, url=url, retrieval_status=RetrievalStatus.NEEDS_MANUAL_REVIEW,
                          retrieval_notes=f"not fetched: {exc}")
            return stub, None
        except (PermanentError, TransientError) as exc:
            stub = RawJob(source=self.name, url=url, retrieval_status=RetrievalStatus.FAILED,
                          retrieval_notes=f"fetch failed: {exc}")
            return stub, f"{url}: {exc}"
        job = parse_job_html(html, self.name, url=url)
        if job is None:
            return RawJob(source=self.name, url=url, retrieval_status=RetrievalStatus.NEEDS_MANUAL_REVIEW,
                          retrieval_notes="page fetched but no job posting recognised"), None
        return job, None

    def collect(self, request: CollectRequest) -> SourceResult:
        result = SourceResult(source=self.name, exhaustive=False)
        files = list(request.files)
        if request.use_inbox:
            inbox = self.settings.path(self.settings.sources.manual.inbox_dir)
            if inbox.exists():
                files += sorted(p for p in inbox.iterdir()
                                if p.suffix.lower() in (".csv", ".json", ".txt", ".md", ".html", ".htm"))
        for path in files:
            jobs, errors = self.parse_file(path)
            for j in jobs:
                j.extra.setdefault("imported_file", path.name)
            result.jobs.extend(jobs)
            result.errors.extend(errors)
        for url in request.urls:
            job, err = self.fetch_url(url)
            if job:
                result.jobs.append(job)
            if err:
                result.errors.append(err)
        if request.limit:
            result.jobs = result.jobs[:request.limit]
        return result
