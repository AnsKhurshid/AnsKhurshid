"""Plain-text job files: a few 'Key: value' header lines, a blank line, then the pasted description.

Example (save as anything.txt in an inbox folder):

    Title: Data Engineer
    Company: Example Corp
    Location: Lahore, Pakistan
    Work arrangement: Hybrid
    URL: https://www.linkedin.com/jobs/view/1234567890/
    Posted: 2026-10-20

    <paste the full job description here>

Several jobs can share one file when separated by a line containing only '---'.
"""
from __future__ import annotations

import re

from jobagent.models import RawJob
from jobagent.sources.html_parser import grade, parse_date
from jobagent.utils.text import clean_text

FIELD_MAP = {
    "title": "title", "job title": "title", "position": "title", "role": "title",
    "company": "company", "employer": "company", "organization": "company", "organisation": "company",
    "location": "location", "city": "location",
    "work arrangement": "work_arrangement", "workplace": "work_arrangement", "workplace type": "work_arrangement",
    "arrangement": "work_arrangement", "remote": "work_arrangement",
    "url": "url", "link": "url", "job url": "url",
    "employment type": "employment_type", "job type": "employment_type", "type": "employment_type",
    "posted": "posted_at", "date posted": "posted_at", "posting date": "posted_at",
    "deadline": "deadline", "apply by": "deadline", "closing date": "deadline",
    "salary": "salary_text", "id": "source_job_id", "job id": "source_job_id",
}
HEADER_RE = re.compile(r"^\s*([A-Za-z][A-Za-z ]{1,25}):\s*(.+?)\s*$")


def looks_like_text_job(text: str) -> bool:
    head = text.strip().splitlines()[:8]
    return sum(1 for ln in head if (m := HEADER_RE.match(ln)) and m.group(1).strip().lower() in FIELD_MAP) >= 2


def parse_text_jobs(text: str, source: str) -> list[RawJob]:
    jobs = []
    for chunk in re.split(r"(?m)^\s*-{3,}\s*$", text):
        if not chunk.strip():
            continue
        lines = chunk.strip().splitlines()
        fields: dict[str, str] = {}
        i = 0
        while i < len(lines):
            m = HEADER_RE.match(lines[i])
            if not m or m.group(1).strip().lower() not in FIELD_MAP:
                break
            fields[FIELD_MAP[m.group(1).strip().lower()]] = m.group(2)
            i += 1
        description = clean_text("\n".join(lines[i:])) or None
        job = RawJob(
            source=source,
            source_job_id=fields.get("source_job_id"),
            url=fields.get("url"), title=fields.get("title"), company=fields.get("company"),
            location=fields.get("location"), work_arrangement=fields.get("work_arrangement"),
            employment_type=fields.get("employment_type"), description=description,
            posted_at=parse_date(fields.get("posted_at")), deadline=parse_date(fields.get("deadline")),
            extra={"salary_text": fields["salary_text"]} if "salary_text" in fields else {},
        )
        job.retrieval_status = grade(job)
        job.retrieval_notes = "user-supplied text"
        jobs.append(job)
    return jobs
