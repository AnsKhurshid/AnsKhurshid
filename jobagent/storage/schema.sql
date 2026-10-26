-- Schema version 1. Migrations are additive only (no destructive changes).

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    command      TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'running',   -- running | completed | partial | failed
    stats_json   TEXT NOT NULL DEFAULT '{}',
    error        TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL,                 -- source of first sighting
    source_job_id     TEXT,
    canonical_url     TEXT,
    title             TEXT,
    title_norm        TEXT,
    role_category     TEXT,
    company           TEXT,
    company_norm      TEXT,
    location          TEXT,
    city              TEXT,
    country           TEXT,
    work_arrangement  TEXT,                          -- on-site | hybrid | remote | unknown
    employment_type   TEXT,
    salary_min        REAL,
    salary_max        REAL,
    salary_currency   TEXT,
    salary_period     TEXT,
    posted_at         TEXT,
    deadline          TEXT,
    hiring_org        TEXT,
    retrieval_status  TEXT NOT NULL,
    retrieval_notes   TEXT,
    status            TEXT NOT NULL DEFAULT 'new',
    availability      TEXT NOT NULL DEFAULT 'open',  -- open | closed | unknown
    description_sha   TEXT,
    first_seen_at     TEXT NOT NULL,
    last_checked_at   TEXT NOT NULL,
    extra_json        TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_source_id ON jobs(source, source_job_id) WHERE source_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_jobs_url ON jobs(canonical_url);
CREATE INDEX IF NOT EXISTS ix_jobs_company_title ON jobs(company_norm, title_norm);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);

-- Every place a job has been seen (one job can appear on several sources / URLs).
CREATE TABLE IF NOT EXISTS job_sightings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER NOT NULL REFERENCES jobs(id),
    source         TEXT NOT NULL,
    source_job_id  TEXT,
    url            TEXT,
    run_id         INTEGER REFERENCES runs(id),
    seen_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sightings_job ON job_sightings(job_id);

-- Original job descriptions, stored verbatim and versioned by content hash.
CREATE TABLE IF NOT EXISTS job_descriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    sha256       TEXT NOT NULL,
    text         TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    UNIQUE(job_id, sha256)
);

CREATE TABLE IF NOT EXISTS status_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    from_status  TEXT,
    to_status    TEXT NOT NULL,
    reason       TEXT,
    changed_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_analyses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           INTEGER NOT NULL REFERENCES jobs(id),
    run_id           INTEGER REFERENCES runs(id),
    description_sha  TEXT,
    profile_sha      TEXT NOT NULL,
    scoring_version  TEXT NOT NULL,
    score            REAL NOT NULL,
    category         TEXT NOT NULL,
    eligible         INTEGER NOT NULL,
    requirements_json TEXT NOT NULL,
    result_json      TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analyses_job ON job_analyses(job_id, created_at);

CREATE TABLE IF NOT EXISTS resumes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           INTEGER NOT NULL REFERENCES jobs(id),
    profile_sha      TEXT NOT NULL,
    description_sha  TEXT,
    status           TEXT NOT NULL,                   -- ready | needs_review
    docx_path        TEXT,
    pdf_path         TEXT,
    report_path      TEXT,
    validation_json  TEXT NOT NULL,
    changes_json     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(job_id, profile_sha, description_sha)
);

-- Per-run, per-job stage progress: lets a failed analysis be retried without redoing finished work.
CREATE TABLE IF NOT EXISTS run_tasks (
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    stage       TEXT NOT NULL,                        -- analyze | tailor
    status      TEXT NOT NULL,                        -- done | failed | skipped
    attempts    INTEGER NOT NULL DEFAULT 1,
    error       TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, job_id, stage)
);

CREATE TABLE IF NOT EXISTS ai_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER,
    purpose        TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cost_usd       REAL,
    cached         INTEGER NOT NULL DEFAULT 0,
    success        INTEGER NOT NULL,
    error          TEXT,
    called_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_cache (
    key           TEXT PRIMARY KEY,
    purpose       TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
