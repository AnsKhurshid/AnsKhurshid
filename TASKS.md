# Task checklist

Legend: [x] done and verified by tests or a documented manual check · [ ] remaining · [~] needs your input

## Phase 1: Inspect & plan
- [x] Inspect repository and runtime (Python 3.13, LibreOffice available; repo held only unrelated docs)
- [x] Architecture, technology choices, LinkedIn access constraints documented (README §2, §7)

## Phase 2: Core
- [x] Config file + startup validation (`config/settings.yaml`, `.env.example`, `jobagent status`)
- [x] Resume parsing (DOCX, text PDF) and evidence-level profile extraction
- [x] Profile review/approve cycle; reviewed profile never silently overwritten
- [x] SQLite storage: jobs, sightings, description versions, status history, analyses, resumes, run tasks, AI usage
- [x] Source interface + registry; LinkedIn compliant connector; manual CSV/JSON/text/HTML; robots.txt-respecting fetcher
- [x] Normalisation (title, company, location, arrangement, employment type, salary, URL) and dedupe (ID → URL → company/title/city/description)
- [x] Deterministic requirement extraction, hard constraints, configurable weighted scoring, career-direction adjustment
- [x] Optional structured AI analysis (Anthropic) with evidence verification, caching, cost tracking, fallback

## Phase 3: Resumes
- [x] Deterministic tailoring from verified content only
- [x] DOCX generation (single column, ATS friendly); PDF via LibreOffice
- [x] Independent validator (structured + rendered-document pass); `needs_review` on failure
- [x] Tailoring report: keywords, unsupported requirements, changes, validation
- [x] Optional AI bullet rewriting with fact-preservation checks

## Phase 4: Reporting & dashboard
- [x] CSV (all, shortlisted), Excel (all / shortlisted / skill gaps), Markdown summary with sample-size disclosure
- [x] Streamlit dashboard: KPIs, filters, charts, sortable table, job detail, resume download/generation, decision buttons, exports (manually verified with screenshots)

## Phase 5: Testing & usability
- [x] 68 automated tests (unit, integration, rerun, matching, factuality, errors, CLI end-to-end)
- [x] README (install, config, architecture, usage, troubleshooting, limitations)
- [~] **End-to-end validation with your real master resume** (waiting for the file)
- [~] Tune taxonomy, weights and thresholds after reviewing results on real jobs

## Future (not started)
- [ ] Scheduled runs (cron / Task Scheduler wrapper around `jobagent run`)
- [ ] Desktop / e-mail notifications for new strong matches
- [ ] Cover-letter drafts (same factual-validation approach)
- [ ] Interview prep notes per job; skill-gap learning plan
- [ ] Application tracking extras (follow-up dates, contacts you add manually)
- [ ] More connectors (company career pages with JobPosting data, public job APIs such as Greenhouse/Lever boards)
- [ ] LinkedIn job-alert e-mail (.eml) import
- [ ] OpenAI provider
