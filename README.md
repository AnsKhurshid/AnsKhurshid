# Job Search Agent

A local, private tool that **discovers → analyses → shortlists → tailors resumes → reports** on data-engineering
jobs, starting with LinkedIn and prioritising Pakistan (on-site, hybrid and remote).

What it will **never** do: apply to jobs, message recruiters, upload your resume anywhere, or claim experience you
don't have. You review and send every application yourself.

> **New here? Read the [User Guide](USER_GUIDE.md)** for step-by-step setup and the weekly routine.
>
> The `docs/` folder holds unrelated database documentation and is not part of the application.

---

## 1. Quick start

```bash
# Python 3.11+ (tested on 3.13)
pip install -e ".[dashboard,dev]"          # add ",anthropic" for optional AI analysis
python -m jobagent init                    # creates data/ folders, database, .env

# 1) your resume (kept local, never modified)
cp ~/Downloads/MyResume.docx data/resume/master_resume.docx     # .pdf also works
python -m jobagent profile extract
#    -> edit data/profile/candidate_profile.yaml (fix anything wrong, reclassify 'listed' skills)
python -m jobagent profile show
python -m jobagent profile approve

# 2) find jobs (see "LinkedIn workflow" below)
python -m jobagent links                   # search links to open in your browser
#    save job pages / paste descriptions into data/inbox/linkedin/

# 3) analyse, shortlist, report (add --tailor to generate resumes for every shortlisted job)
python -m jobagent run
python -m jobagent jobs --status shortlisted
python -m jobagent show 12                 # why did job 12 get its score?
python -m jobagent tailor 12               # DOCX + PDF + tailoring report
python -m jobagent dashboard               # http://localhost:8501
```

PDF resumes need LibreOffice (`soffice`) on your PATH; without it you get DOCX only.

## 2. LinkedIn workflow (and why it works this way)

LinkedIn has **no public job-search API** for individuals, and its User Agreement prohibits scraping and automated
access (including using your logged-in session). Doing it anyway risks your account. So the LinkedIn connector
never contacts linkedin.com. Instead:

1. `python -m jobagent links` writes `data/reports/linkedin_search_links.html`, with searches for each preferred
   title, Pakistan-wide (geo filter) for all arrangements plus a remote-only search, limited to recent posts.
   `--per-city` adds Lahore/Karachi/Islamabad/... links.
2. Open them in your browser and bring back the jobs you care about, in any of these forms, dropped into
   `data/inbox/linkedin/`:
   * **Saved job page**: on the job's page press Ctrl+S, then "Webpage, HTML only". Title, company, location,
     description and date are extracted.
   * **Pasted text**: a `.txt` file with a few header lines, a blank line, then the description
     (see [`tests/fixtures/jobs/pasted_job.txt`](tests/fixtures/jobs/pasted_job.txt)):
     ```
     Title: Data Engineer
     Company: Example Corp
     Location: Lahore, Pakistan
     Work arrangement: Hybrid
     URL: https://www.linkedin.com/jobs/view/1234567890/

     <full description>
     ```
     Separate several jobs in one file with a line containing `---`.
   * **Just URLs**: a `.txt` file of job links. These are tracked and deduplicated, but marked
     `needs_manual_review` until you add the description with
     `python -m jobagent add-details <id> <file.txt|file.html>`.
3. `python -m jobagent run` imports everything. Rerunning is safe: no duplicate jobs or resumes are created.

Other sources: `data/inbox/manual/` accepts **CSV/JSON** (flexible column names: title, company, location,
description, url, ...), pasted-text files and saved pages from any job board. `--url <link>` fetches a public job
page (e.g. a company careers page) **only if its robots.txt allows it**. LinkedIn, Indeed and Glassdoor are never
fetched automatically.

Every import reports how many records were complete, partial, needed manual review or failed. Reports always
state that coverage is limited to what you imported.

## 3. How matching works

Matching is **deterministic first**: the same inputs always give the same score, and every point is explained
(`jobagent show <id>`, or the dashboard's Job detail tab).

| Component (default weight) | How it's computed |
|---|---|
| Technical skills (30) | Required, preferred and other mentioned skills from the description, credited by your evidence level: professional 1.0, project 0.6, studied 0.25. Equivalent technologies get partial *transferable* credit (e.g. Redshift ← PostgreSQL 0.7, Airflow ← Step Functions 0.35). Synonyms map to one skill, so repetition never counts twice. |
| Responsibilities (25) | Each responsibility line is matched against work themes (pipelines, API ingestion, data quality, troubleshooting, optimisation, …) evidenced in your experience bullets. |
| Seniority (15) | Required years (or the level implied by the title) vs your experience. |
| Role alignment (15) | Data Engineer / AWS DE / ETL / Python & SQL DE / Analytics / Integration roles score high; analyst, scientist and generic SWE roles score low. |
| Location (10) | Preferred Pakistani city, other Pakistani city, Pakistan-eligible remote, remote with unstated eligibility, or abroad. |
| Domain (5) | Matches `matching.candidate_domains` / preferred industries; excluded industries score 0. |

* **Career-direction adjustment**: when role alignment is below 60%, the total is scaled down (shown in the
  breakdown), so a Data Analyst job can't ride high on shared SQL/Python keywords.
* **Hard constraints are separate** and never hidden by a high score: location restrictions ("US only"), work
  authorisation, mandatory certifications and required postgraduate degrees. A failed constraint means
  `skip`, or `review_eligibility` when it's a certification you might hold. A remote job is only treated as open
  to you when it says so; otherwise you get a "verify eligibility" warning.
* **Categories** (configurable): 80+ strong · 65–79 potential · 50–64 stretch · <50 low priority.
  Shortlisted = eligible and score ≥ `matching.min_match_score`.
* **Optional AI review** (`ai.provider: anthropic`): blends 50/50 into the responsibilities component only. Any
  resume evidence the AI quotes is verified against your profile, and unsupported claims are dropped. It can add
  required skills only if they literally appear in the description. It can flag eligibility concerns but never fail
  a job by itself. Results are cached and costs are logged.

Your own decisions (`set-status ... applied|reviewed|closed`) are never overwritten by re-analysis.

## 4. Resume tailoring and accuracy

For a selected job, the tailoring engine:

* keeps **every role, title, employer and date exactly as in your profile**, in chronological order;
* reorders your own bullets by relevance to the job and keeps the top `resume.max_bullets_per_role` (omitted
  bullets are listed in the report);
* writes the summary from a template filled only with verified facts (your years, *professional-level* skills,
  themes evidenced in your bullets);
* orders skills by the job's priorities; portfolio-only skills go on a separate **"Project experience"** line,
  studied-only skills under **"Currently learning"** (only when relevant);
* never adds a skill, metric, employer, title or responsibility you don't have.

An **independent validator** then checks employers/titles/dates, bullet traceability, unsupported skills, new
numbers, years-of-experience claims, placeholders, duplicates and keyword stuffing. It runs again **on the text
read back from the generated DOCX**. If any check fails, the resume is saved as `needs_review` (never `ready`),
with the reasons in the report.

Output per job, in `data/resumes/<Company>_<Title>_J<id>/`: `…_Resume.docx`, `…_Resume.pdf`,
`…_tailoring_report.md` (keywords included, **requirements not supported by your profile**, what changed,
validation results) and `…_changes.json`.

Optional `resume.ai_rewrite_bullets: true` lets the AI reword bullets. Any rewrite that adds or drops a number or
adds a skill is rejected and the original wording is kept.

## 5. Configuration

`config/settings.yaml` (annotated) controls the resume path, preferred titles (priority order), country and cities,
arrangements, experience range, industries, excluded title keywords, scoring weights and thresholds, max jobs per
run, output folders, AI provider/model/effort/cost rates, and enabled sources.
`config/skills_taxonomy.yaml` defines skills, synonyms and transfer relationships, and is safe to extend.

Secrets go only in `.env` (see `.env.example`); nothing secret is read from YAML. Use another settings file with
`--config path` or `JOBAGENT_CONFIG`.

## 6. Privacy

* Everything (resume, profile, database, generated files, logs) stays in `data/`, which is git-ignored.
* With `ai.provider: none` (the default), nothing leaves your machine.
* With AI enabled, the job description and a **contact-free** copy of your profile (no name, email, phone or links)
  are sent to the provider; the CLI says so when it runs.
* Logs are JSON lines in `data/logs/` with API keys, tokens, cookies, e-mails and phone numbers redacted.
* The dashboard binds to localhost only.
* Delete data: `python -m jobagent purge --jobs --resumes --reports` (asks for confirmation; never touches the
  master resume or profile).

## 7. Architecture

```
jobagent/
  config.py           settings (Pydantic) + startup checks
  models.py           shared data models (RawJob, CandidateProfile, JobRequirements, MatchResult …)
  taxonomy.py         skill synonyms / implications / transferable equivalents
  sources/            connectors: base interface, linkedin (compliant import), manual (CSV/JSON/text/URL),
                      html_parser (schema.org JobPosting + layout fallback), url_fetch (robots.txt, rate limit)
  ingestion/          normalisation (titles, companies, locations, URLs, salary) + idempotent dedupe/upsert
  profile/            resume parsing (DOCX/PDF) → evidence-based profile → review/approve
  matching/           requirement extraction, scoring + hard constraints, analyser (optional AI)
  ai/                 provider-neutral structured-output client, cache, usage & cost tracking
  resume/             tailoring, DOCX rendering, PDF conversion, validator, service
  reporting/          CSV / Excel / Markdown summary, search-links page
  dashboard/app.py    Streamlit UI
  storage/            SQLite schema + repository
  cli.py              commands
```

**Adding a job source**: subclass `sources.base.JobSource`, return `RawJob`s with an honest `retrieval_status`
from `collect()`, and register it in `sources/registry.py`. Normalisation, deduplication, matching, resumes and
reports need no changes.

Key choices: **SQLite** (no server, inspectable with any SQL client; additive schema; every job's history, sightings,
description versions and status changes are kept), plain SQL rather than an ORM, **argparse** CLI,
**python-docx + LibreOffice** for documents, **Streamlit + Plotly** for the dashboard. Each job is ingested and analysed
in its own transaction, so a crash never loses completed work; `jobagent retry` re-runs only failed tasks.

Dependencies: pydantic, PyYAML, python-dotenv, requests, beautifulsoup4 + lxml (HTML), pdfplumber (PDF resumes),
python-docx, pandas + openpyxl (reports); optional streamlit + plotly (dashboard), anthropic (AI), pytest.

## 8. Commands

| Command | Purpose |
|---|---|
| `init` / `status` | set up folders; show readiness, job counts, pending tasks, AI usage and cost |
| `profile extract \| show \| approve` | build, inspect and approve the candidate profile |
| `links [--per-city]` | LinkedIn search links page |
| `import [files] [--url U] [--no-inbox]` | import jobs only |
| `run [files] [--tailor]` | import → analyse → (tailor shortlisted) → reports |
| `analyze [--job ID] [--force]` | (re)score jobs; unchanged jobs are skipped |
| `jobs [--status S] [--min-score N] [--needs-details]` | list jobs |
| `show ID` | full score explanation and status history |
| `tailor ID… \| --shortlisted [--force]` | generate tailored resumes |
| `add-details ID FILE` | attach a description to a URL-only job |
| `set-status ID reviewed\|applied\|rejected\|closed …` | record your own decisions |
| `report` | CSV (all + shortlist), Excel (all / shortlisted / skill gaps), summary |
| `retry` | retry failed analysis/tailoring tasks |
| `dashboard` | local Streamlit dashboard |
| `purge --jobs/--resumes/--reports` | delete local data (with confirmation) |

## 9. Testing

```bash
python -m pytest -q
```

69 tests run on synthetic fixtures only (a fictional resume and fictional jobs; no network). They cover taxonomy,
parsing, deduplication and reruns, URL canonicalisation, the robots/LinkedIn fetch refusal, scoring and hard
constraints, AI evidence verification and caching (with a fake provider), retry tracking, resume factuality
(including adversarial tampering and AI rewrites that add facts), reports, and a full CLI end-to-end run.

## 10. Troubleshooting

* **"profile has not been reviewed"**: edit `data/profile/candidate_profile.yaml`, then `profile approve`.
  `profile show` lists blocking issues.
* **Wrong roles or dates extracted**: unusual resume layouts (multi-column PDFs, text boxes) parse poorly. Fix the
  YAML by hand, or provide a DOCX. Scanned PDFs are not supported (no OCR).
* **A saved LinkedIn page imports as `partial`**: LinkedIn changes its page layout. Paste the description as a
  text job instead, or use `add-details`.
* **No PDF**: install LibreOffice so that `soffice` is on PATH.
* **AI not used**: `jobagent status` shows why (provider `none`, missing `ANTHROPIC_API_KEY`, …).

## 11. Known limitations

* No automatic LinkedIn search (by design, see §2). Coverage depends on what you import.
* Requirement extraction is heuristic: job descriptions without clear "Requirements / Nice to have" headings get
  lower confidence, and some skills land in an "unclassified" bucket (weighted between required and preferred).
* Experience-years and seniority parsing handle common phrasings ("3+ years", "2-4 years") but not every one.
* The skill taxonomy covers data-engineering tools; unknown tools in a description are ignored until added to
  `config/skills_taxonomy.yaml`.
* Only one resume version per job is kept (regenerating overwrites it; the database keeps the history row).
* The OpenAI provider is not implemented; the AI layer has a provider interface for adding one.
* Scheduling, notifications, cover letters and interview prep are future work (see `TASKS.md`).
