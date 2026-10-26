"""Ingestion: normalise RawJobs, deduplicate against the database, and upsert idempotently."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from jobagent.ingestion.normalize import (canonicalize_url, detect_work_arrangement, normalize_company,
                                          normalize_employment_type, normalize_title, parse_location,
                                          parse_salary, role_category)
from jobagent.models import RawJob, RetrievalStatus, SourceResult
from jobagent.storage.db import Database, now_iso
from jobagent.utils.text import clean_text, sha256

log = logging.getLogger("jobagent.ingestion")

STATUS_RANK = {RetrievalStatus.FAILED.value: 0, RetrievalStatus.NEEDS_MANUAL_REVIEW.value: 1,
               RetrievalStatus.PARTIAL.value: 2, RetrievalStatus.COMPLETE.value: 3}


@dataclass
class IngestStats:
    received: int = 0
    inserted: int = 0
    duplicates: int = 0
    updated: int = 0
    skipped: int = 0
    by_retrieval: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    job_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__ | {"job_ids": len(self.job_ids)}


def _shingles(text: str, k: int = 5) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def description_similarity(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return None
    return len(sa & sb) / len(sa | sb)


def normalized_fields(raw: RawJob) -> dict:
    desc = clean_text(raw.description) if raw.description else None
    city, country = parse_location(raw.location)
    url = canonicalize_url(raw.url)
    smin, smax, cur, period = raw.salary_min, raw.salary_max, raw.salary_currency, raw.salary_period
    if smin is None and smax is None:
        smin, smax, cur, period = parse_salary(raw.extra.get("salary_text") or desc)
    return {
        "source": raw.source,
        "source_job_id": raw.source_job_id,
        "canonical_url": url,
        "title": clean_text(raw.title) or None,
        "title_norm": normalize_title(raw.title) or None,
        "role_category": role_category(raw.title) if raw.title else None,
        "company": clean_text(raw.company) or None,
        "company_norm": normalize_company(raw.company) or None,
        "location": clean_text(raw.location) or None,
        "city": city,
        "country": country,
        "work_arrangement": detect_work_arrangement(raw.work_arrangement, raw.title, raw.location, desc),
        "employment_type": normalize_employment_type(raw.employment_type, desc),
        "salary_min": smin, "salary_max": smax, "salary_currency": cur, "salary_period": period,
        "posted_at": raw.posted_at.isoformat() if raw.posted_at else None,
        "deadline": raw.deadline.isoformat() if raw.deadline else None,
        "hiring_org": raw.hiring_organization or raw.company,
        "retrieval_status": raw.retrieval_status.value,
        "retrieval_notes": raw.retrieval_notes,
        "description_sha": sha256(desc)[:16] if desc else None,
        "extra_json": json.dumps(raw.extra, default=str),
        "_description": desc,
    }


def find_duplicate(db: Database, f: dict) -> tuple[dict | None, str | None]:
    """Return (existing_job, reason). Order: platform ID > canonical URL > company+title(+city, description)."""
    if f["source_job_id"]:
        if hit := db.find_by_source_id(f["source"], f["source_job_id"]):
            return hit, "same platform job id"
    if f["canonical_url"]:
        if hit := db.find_by_url(f["canonical_url"]):
            return hit, "same canonical url"
    if f["company_norm"] and f["title_norm"]:
        for cand in db.find_by_company_title(f["company_norm"], f["title_norm"]):
            if f["city"] and cand["city"] and f["city"] != cand["city"]:
                continue  # same title in another office is a different opening
            # Two different IDs on the same platform are distinct unless descriptions are near-identical (repost).
            same_platform_diff_id = (cand["source"] == f["source"] and cand["source_job_id"] and f["source_job_id"]
                                     and cand["source_job_id"] != f["source_job_id"])
            existing = db.description(cand["id"])
            sim = description_similarity(existing[0] if existing else None, f["_description"])
            if sim is None and not same_platform_diff_id:
                return cand, "same company, title and location"
            if sim is not None and sim >= 0.8:
                return cand, f"same company and title, description {sim:.0%} similar"
    return None, None


MERGEABLE = ("canonical_url", "title", "title_norm", "role_category", "company", "company_norm", "location", "city",
             "country", "employment_type", "salary_min", "salary_max", "salary_currency", "salary_period",
             "posted_at", "deadline", "hiring_org")


def upsert_job(db: Database, raw: RawJob, run_id: int | None) -> tuple[int, str]:
    """Insert or merge one job inside a single transaction. Returns (job_id, 'inserted'|'duplicate'|'updated')."""
    f = normalized_fields(raw)
    desc = f.pop("_description")
    with db.tx():
        f["_description"] = desc
        existing, reason = find_duplicate(db, f)
        f.pop("_description")
        if existing is None:
            job_id = db.insert_job(f)
            outcome = "inserted"
        else:
            job_id = existing["id"]
            changes = {k: f[k] for k in MERGEABLE if f.get(k) and not existing.get(k)}
            if existing.get("work_arrangement") in (None, "unknown") and f["work_arrangement"] != "unknown":
                changes["work_arrangement"] = f["work_arrangement"]
            if STATUS_RANK[f["retrieval_status"]] > STATUS_RANK.get(existing["retrieval_status"], 0):
                changes["retrieval_status"] = f["retrieval_status"]
                changes["retrieval_notes"] = f["retrieval_notes"]
            if desc and f["description_sha"] != existing.get("description_sha"):
                changes["description_sha"] = f["description_sha"]
            if existing.get("availability") == "closed":
                changes["availability"] = "open"
            changes["last_checked_at"] = now_iso()
            db.update_job(job_id, changes)
            outcome = "updated" if len(changes) > 1 else "duplicate"
            log.info("job %s matched existing (%s)", job_id, reason)
        if desc:
            db.add_description(job_id, desc, f["description_sha"])
        db.add_sighting(job_id, raw.source, raw.source_job_id, f["canonical_url"], run_id)
    return job_id, outcome


def ingest(db: Database, results: list[SourceResult], run_id: int | None, max_jobs: int | None = None) -> IngestStats:
    stats = IngestStats()
    for res in results:
        stats.errors.extend(f"[{res.source}] {e}" for e in res.errors)
        stats.notes.extend(f"[{res.source}] {n}" for n in res.notes)
        for raw in res.jobs:
            if max_jobs and stats.received >= max_jobs:
                stats.skipped += 1
                continue
            stats.received += 1
            stats.by_retrieval[raw.retrieval_status.value] = stats.by_retrieval.get(raw.retrieval_status.value, 0) + 1
            if not (raw.title or raw.url or raw.description):
                stats.errors.append(f"[{res.source}] skipped empty record")
                continue
            try:
                job_id, outcome = upsert_job(db, raw, run_id)
            except Exception as exc:  # one bad record must not abort the batch
                log.exception("failed to ingest record from %s", res.source)
                stats.errors.append(f"[{res.source}] {raw.title or raw.url}: {exc}")
                continue
            stats.job_ids.append(job_id)
            if outcome == "inserted":
                stats.inserted += 1
            elif outcome == "updated":
                stats.updated += 1
                stats.duplicates += 1
            else:
                stats.duplicates += 1
    if stats.skipped:
        stats.notes.append(f"{stats.skipped} records not processed: max_jobs_per_run reached")
    return stats
