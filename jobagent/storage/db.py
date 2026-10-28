"""SQLite persistence. Plain SQL kept in one place so it is easy to read and inspect."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from jobagent.models import JobStatus

SCHEMA_VERSION = 1
log = logging.getLogger("jobagent.storage")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)  # autocommit; explicit tx below
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self._migrate()

    # ------------------------------------------------------------------ infrastructure
    def _migrate(self) -> None:
        schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        # Every statement uses IF NOT EXISTS, so re-running is idempotent and non-destructive.
        self.conn.executescript(schema)
        row = self.conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        elif row["version"] > SCHEMA_VERSION:
            raise RuntimeError(f"database schema v{row['version']} is newer than this app (v{SCHEMA_VERSION})")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    def q(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def q1(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    # ------------------------------------------------------------------ runs
    def start_run(self, command: str) -> int:
        cur = self.conn.execute("INSERT INTO runs(command, started_at) VALUES (?, ?)", (command, now_iso()))
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, stats: dict, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats_json=?, error=? WHERE id=?",
            (now_iso(), status, json.dumps(stats, default=str), error, run_id),
        )

    def runs(self, limit: int = 20) -> list[dict]:
        rows = self.q("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) | {"stats": json.loads(r["stats_json"])} for r in rows]

    # ------------------------------------------------------------------ jobs
    def insert_job(self, fields: dict[str, Any]) -> int:
        fields = dict(fields)
        fields.setdefault("first_seen_at", now_iso())
        fields.setdefault("last_checked_at", fields["first_seen_at"])
        cols = ", ".join(fields)
        marks = ", ".join(f":{k}" for k in fields)
        cur = self.conn.execute(f"INSERT INTO jobs({cols}) VALUES ({marks})", fields)
        job_id = int(cur.lastrowid)
        self.conn.execute(
            "INSERT INTO status_history(job_id, from_status, to_status, reason, changed_at) VALUES (?,?,?,?,?)",
            (job_id, None, fields.get("status", JobStatus.NEW.value), "discovered", fields["first_seen_at"]),
        )
        return job_id

    def update_job(self, job_id: int, fields: dict[str, Any]) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        self.conn.execute(f"UPDATE jobs SET {sets} WHERE id = :_id", {**fields, "_id": job_id})

    def job(self, job_id: int) -> dict | None:
        r = self.q1("SELECT * FROM jobs WHERE id=?", (job_id,))
        return dict(r) if r else None

    def find_by_source_id(self, source: str, source_job_id: str) -> dict | None:
        r = self.q1(
            """SELECT j.* FROM jobs j WHERE j.source=? AND j.source_job_id=?
               UNION SELECT j.* FROM jobs j JOIN job_sightings s ON s.job_id=j.id
                     WHERE s.source=? AND s.source_job_id=? LIMIT 1""",
            (source, source_job_id, source, source_job_id),
        )
        return dict(r) if r else None

    def find_by_url(self, url: str) -> dict | None:
        r = self.q1(
            """SELECT j.* FROM jobs j WHERE j.canonical_url=?
               UNION SELECT j.* FROM jobs j JOIN job_sightings s ON s.job_id=j.id WHERE s.url=? LIMIT 1""",
            (url, url),
        )
        return dict(r) if r else None

    def find_by_company_title(self, company_norm: str, title_norm: str) -> list[dict]:
        rows = self.q("SELECT * FROM jobs WHERE company_norm=? AND title_norm=?", (company_norm, title_norm))
        return [dict(r) for r in rows]

    def add_sighting(self, job_id: int, source: str, source_job_id: str | None, url: str | None,
                     run_id: int | None) -> None:
        self.conn.execute(
            "INSERT INTO job_sightings(job_id, source, source_job_id, url, run_id, seen_at) VALUES (?,?,?,?,?,?)",
            (job_id, source, source_job_id, url, run_id, now_iso()),
        )

    def add_description(self, job_id: int, text: str, sha: str) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO job_descriptions(job_id, sha256, text, captured_at) VALUES (?,?,?,?)",
            (job_id, sha, text, now_iso()),
        )
        return cur.rowcount > 0

    def description(self, job_id: int) -> tuple[str, str] | None:
        """Latest (text, sha) for a job."""
        r = self.q1("SELECT text, sha256 FROM job_descriptions WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,))
        return (r["text"], r["sha256"]) if r else None

    def set_status(self, job_id: int, new_status: JobStatus | str, reason: str) -> None:
        new = JobStatus(new_status).value
        row = self.q1("SELECT status FROM jobs WHERE id=?", (job_id,))
        if row is None:
            raise KeyError(f"job {job_id} not found")
        if row["status"] == new:
            return
        self.conn.execute("UPDATE jobs SET status=? WHERE id=?", (new, job_id))
        self.conn.execute(
            "INSERT INTO status_history(job_id, from_status, to_status, reason, changed_at) VALUES (?,?,?,?,?)",
            (job_id, row["status"], new, reason, now_iso()),
        )

    def status_history(self, job_id: int) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM status_history WHERE job_id=? ORDER BY id", (job_id,))]

    # ------------------------------------------------------------------ analyses
    def save_analysis(self, job_id: int, run_id: int | None, description_sha: str | None, profile_sha: str,
                      scoring_version: str, score: float, category: str, eligible: bool,
                      requirements: dict, result: dict) -> int:
        cur = self.conn.execute(
            """INSERT INTO job_analyses(job_id, run_id, description_sha, profile_sha, scoring_version, score,
                   category, eligible, requirements_json, result_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (job_id, run_id, description_sha, profile_sha, scoring_version, score, category, int(eligible),
             json.dumps(requirements), json.dumps(result), now_iso()),
        )
        return int(cur.lastrowid)

    def latest_analysis(self, job_id: int) -> dict | None:
        r = self.q1("SELECT * FROM job_analyses WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,))
        if not r:
            return None
        d = dict(r)
        d["requirements"] = json.loads(d.pop("requirements_json"))
        d["result"] = json.loads(d.pop("result_json"))
        return d

    def has_current_analysis(self, job_id: int, description_sha: str | None, profile_sha: str,
                             scoring_version: str) -> bool:
        r = self.q1(
            """SELECT 1 FROM job_analyses WHERE job_id=? AND IFNULL(description_sha,'')=IFNULL(?, '')
               AND profile_sha=? AND scoring_version=? LIMIT 1""",
            (job_id, description_sha, profile_sha, scoring_version),
        )
        return r is not None

    # ------------------------------------------------------------------ run tasks
    def mark_task(self, run_id: int, job_id: int, stage: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO run_tasks(run_id, job_id, stage, status, error, updated_at) VALUES (?,?,?,?,?,?)
               ON CONFLICT(run_id, job_id, stage) DO UPDATE SET status=excluded.status, error=excluded.error,
                   attempts=run_tasks.attempts+1, updated_at=excluded.updated_at""",
            (run_id, job_id, stage, status, error, now_iso()),
        )

    def failed_tasks(self, stage: str | None = None) -> list[dict]:
        """Latest failed task per (job, stage) that has not since succeeded."""
        sql = """SELECT t.* FROM run_tasks t
                 WHERE t.status='failed' AND NOT EXISTS (
                     SELECT 1 FROM run_tasks u WHERE u.job_id=t.job_id AND u.stage=t.stage
                     AND u.status='done' AND u.updated_at >= t.updated_at)"""
        params: tuple = ()
        if stage:
            sql += " AND t.stage=?"
            params = (stage,)
        rows = [dict(r) for r in self.q(sql + " ORDER BY t.updated_at DESC", params)]
        seen, out = set(), []
        for r in rows:
            if (r["job_id"], r["stage"]) not in seen:
                seen.add((r["job_id"], r["stage"]))
                out.append(r)
        return out

    # ------------------------------------------------------------------ resumes
    def find_resume(self, job_id: int, profile_sha: str, description_sha: str | None) -> dict | None:
        r = self.q1(
            "SELECT * FROM resumes WHERE job_id=? AND profile_sha=? AND IFNULL(description_sha,'')=IFNULL(?, '')",
            (job_id, profile_sha, description_sha),
        )
        return dict(r) if r else None

    def latest_resume(self, job_id: int) -> dict | None:
        r = self.q1("SELECT * FROM resumes WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,))
        return dict(r) if r else None

    def save_resume(self, job_id: int, profile_sha: str, description_sha: str | None, status: str,
                    docx_path: str | None, pdf_path: str | None, report_path: str | None,
                    validation: dict, changes: dict) -> int:
        cur = self.conn.execute(
            """INSERT INTO resumes(job_id, profile_sha, description_sha, status, docx_path, pdf_path, report_path,
                   validation_json, changes_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id, profile_sha, description_sha) DO UPDATE SET status=excluded.status,
                   docx_path=excluded.docx_path, pdf_path=excluded.pdf_path, report_path=excluded.report_path,
                   validation_json=excluded.validation_json, changes_json=excluded.changes_json,
                   created_at=excluded.created_at""",
            (job_id, profile_sha, description_sha, status, docx_path, pdf_path, report_path,
             json.dumps(validation), json.dumps(changes), now_iso()),
        )
        return int(cur.lastrowid)

    # ------------------------------------------------------------------ AI bookkeeping
    def log_ai_call(self, run_id: int | None, purpose: str, provider: str, model: str | None,
                    input_tokens: int | None, output_tokens: int | None, cost_usd: float | None,
                    cached: bool, success: bool, error: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO ai_calls(run_id, purpose, provider, model, input_tokens, output_tokens, cost_usd,
                   cached, success, error, called_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, purpose, provider, model, input_tokens, output_tokens, cost_usd, int(cached), int(success),
             error, now_iso()),
        )

    def cache_get(self, key: str) -> dict | None:
        r = self.q1("SELECT response_json FROM ai_cache WHERE key=?", (key,))
        return json.loads(r["response_json"]) if r else None

    def cache_put(self, key: str, purpose: str, response: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO ai_cache(key, purpose, response_json, created_at) VALUES (?,?,?,?)",
            (key, purpose, json.dumps(response), now_iso()),
        )

    def ai_usage(self) -> dict:
        r = self.q1(
            """SELECT COUNT(*) calls, SUM(cached) cached, SUM(1-success) errors,
                      SUM(input_tokens) input_tokens, SUM(output_tokens) output_tokens, SUM(cost_usd) cost_usd
               FROM ai_calls""")
        return dict(r) if r else {}

    # ------------------------------------------------------------------ reporting view
    def jobs_overview(self) -> list[dict]:
        """One row per job with its latest analysis and resume, for reports and the dashboard."""
        rows = self.q(
            """SELECT j.*,
                      a.score, a.category, a.eligible, a.result_json, a.requirements_json, a.created_at AS analyzed_at,
                      r.status AS resume_status, r.docx_path, r.pdf_path, r.report_path
               FROM jobs j
               LEFT JOIN job_analyses a ON a.id = (SELECT MAX(id) FROM job_analyses WHERE job_id=j.id)
               LEFT JOIN resumes r ON r.id = (SELECT MAX(id) FROM resumes WHERE job_id=j.id)
               ORDER BY a.score DESC NULLS LAST, j.id""")
        out = []
        for r in rows:
            d = dict(r)
            d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
            d["requirements"] = json.loads(d.pop("requirements_json")) if d.get("requirements_json") else None
            d["extra"] = json.loads(d.pop("extra_json") or "{}")
            out.append(d)
        return out

    # ------------------------------------------------------------------ deletion (explicit, user-confirmed)
    def purge_all_job_data(self) -> dict:
        counts = {}
        with self.tx():
            for table in ("run_tasks", "resumes", "job_analyses", "status_history", "job_descriptions",
                          "job_sightings", "jobs", "ai_cache", "ai_calls", "runs"):
                counts[table] = self.conn.execute(f"DELETE FROM {table}").rowcount
        return counts
