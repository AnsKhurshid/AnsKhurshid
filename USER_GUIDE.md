# User Guide

A practical, task-by-task guide to using the job search agent. For architecture and design details, see
[README.md](README.md).

**The tool never applies to jobs, contacts anyone, or uploads your resume.** It finds, scores and prepares.
You decide and send.

---

## 1. One-time setup (about 10 minutes)

### 1.1 Install

```bash
cd AnsKhurshid
pip install -e ".[dashboard,dev]"        # add ",anthropic" only if you want optional AI analysis
python -m jobagent init                  # creates data/ folders, the database and .env
```

For PDF resumes, install LibreOffice so the `soffice` command works. Without it you get DOCX only.

### 1.2 Add your master resume

Put it at `data/resume/master_resume.pdf` (or `.docx`; then change `profile.master_resume_path` in
`config/settings.yaml`). The file is **never modified**, and `data/` is never committed to git.

### 1.3 Build and approve your profile

```bash
python -m jobagent profile extract       # reads the resume -> data/profile/candidate_profile.yaml
python -m jobagent profile show          # summary + anything that needs your decision
```

Open `data/profile/candidate_profile.yaml` and check:

| Check | What to look for |
|---|---|
| Roles | employer, title, start/end dates exactly as on your resume |
| `total_experience_years` | professional years (internships are excluded by default) |
| Skill `level` | `professional` = used at work · `project` = portfolio only · `studied` = coursework/learning only. No skill may remain `listed`. |
| `unverified` | items the extractor was unsure about; delete each line once resolved |

Then:

```bash
python -m jobagent profile approve       # refuses if anything blocking is left
```

> Your profile is the single source of truth. Tailored resumes never claim more than it says, so keep it accurate.
> If you update your resume later, run `profile extract` again. Your approved profile is kept, and the new
> extraction is written to `candidate_profile.new.yaml` for you to compare and merge.

### 1.4 Review your preferences (optional)

`config/settings.yaml` is annotated. The settings most worth checking:

| Setting | Default | Meaning |
|---|---|---|
| `search.preferred_titles` | Data Engineer, AWS DE, ETL … | earlier entries count as stronger alignment |
| `search.preferred_locations` | Lahore, Karachi, Islamabad … | full location score for these cities |
| `search.work_arrangements` | on-site, hybrid, remote | arrangements you accept |
| `search.max_experience_years` | 5 | roles above this are flagged as a stretch |
| `matching.min_match_score` | 65 | shortlist threshold |
| `matching.weights` | 30/25/15/15/10/5 | must sum to 100 |
| `resume.max_bullets_per_role` | 6 | extra bullets are omitted (and listed in the report) |
| `ai.provider` | none | `anthropic` enables optional AI review (needs `ANTHROPIC_API_KEY` in `.env`) |

Run `python -m jobagent status` at any time to see whether everything is ready.

---

## 2. Weekly routine (about 30–45 minutes)

### Step 1: Generate search links
```bash
python -m jobagent links
```
Open `data/reports/linkedin_search_links.html`. It contains one Pakistan-wide search per target title, plus a
remote-only search, limited to recent posts. (`--per-city` adds city-level searches.)

### Step 2: Collect jobs from your browser
For each job worth considering, do **one** of the following, into `data/inbox/linkedin/`:

* **Save the page**: on the job page press **Ctrl+S**, then choose "Webpage, HTML only". Best option.
* **Paste the text** into a `.txt` file:
  ```
  Title: Data Engineer
  Company: Example Corp
  Location: Lahore, Pakistan
  Work arrangement: Hybrid
  URL: https://www.linkedin.com/jobs/view/1234567890/

  <paste the full job description here>
  ```
  Several jobs can go in one file, separated by a line containing only `---`.
* **Just the link**: list job URLs in a `.txt` file. The job is tracked, but it can't be scored until you add its
  description (see Step 4).

Jobs from other sites work the same way. Put CSV/JSON exports and pasted text in `data/inbox/manual/`, or pass a
company careers URL with `--url` (it is fetched only if that site's robots.txt allows it).

### Step 3: Run the pipeline
```bash
python -m jobagent run
```
This imports everything, skips duplicates, scores new or changed jobs, and writes reports. Running it again is
always safe. Files can stay in the inbox: nothing is duplicated, and unchanged jobs are not re-scored.

### Step 4: Complete URL-only jobs
```bash
python -m jobagent jobs --needs-details
python -m jobagent add-details 17 job17.txt      # pasted text or a saved .html page
python -m jobagent analyze --job 17
```

### Step 5: Review the shortlist
```bash
python -m jobagent dashboard          # opens http://localhost:8501
# or in the terminal:
python -m jobagent jobs --status shortlisted
python -m jobagent show 12            # full explanation of one job's score
```
See §3 for how to read a score.

### Step 6: Generate tailored resumes for the jobs you want
```bash
python -m jobagent tailor 12 15       # specific jobs
python -m jobagent tailor --shortlisted
```
Output goes to `data/resumes/<Company>_<Title>_J<id>/`:

| File | Use |
|---|---|
| `…_Resume.docx` / `…_Resume.pdf` | the resume to review and send |
| `…_tailoring_report.md` | what changed, keywords included, **requirements you don't meet**, validation results |
| `…_changes.json` | the same, machine-readable |

**Always read the report and the resume before sending.** See §4.

### Step 7: Apply yourself, then record what you did
```bash
python -m jobagent set-status 12 applied --reason "applied on company site"
python -m jobagent set-status 15 rejected --reason "not interested: night shift"
python -m jobagent set-status 9 closed
```
(Or use the buttons in the dashboard's Job detail tab.) Re-scoring never overwrites these decisions.

---

## 3. Reading a match score

Every score is explained. Run `show <id>`, or open the dashboard's **Job detail** tab.

| Part | Weight | It asks |
|---|---|---|
| Skills | 30 | Do you have the required/preferred tools, at what evidence level? |
| Responsibilities | 25 | Have you done this kind of work (pipelines, ingestion, troubleshooting …)? |
| Seniority | 15 | Do your years meet the requirement? |
| Role alignment | 15 | Is it a data-engineering-type role? |
| Location | 10 | Preferred city / Pakistan / remote open to Pakistan? |
| Domain | 5 | Real estate / your preferred industries? |

**Categories:** 80+ strong · 65–79 potential · 50–64 stretch · below 50 low priority.

**Recommendations:**

| Recommendation | Meaning | What to do |
|---|---|---|
| `apply` | strong match, eligible | prioritise; tailor a resume |
| `consider` | potential match | read the gaps; tailor if they look manageable |
| `stretch` | partial match | apply selectively, if the role is a growth target |
| `review_eligibility` | a mandatory certification/degree you don't have on file | if you hold it, add it to your profile; otherwise skip |
| `skip` | low score, or a hard block (e.g. "US residents only") | ignore |
| `needs_details` | too little information to judge | add the full description |

Things to know:

* **Hard constraints** (location restrictions, work authorisation, required certification/degree) are shown
  separately as ✅ / ⚠️ / ⛔. A high score never hides a ⛔.
* A **remote** job counts as open to you only if it says Pakistan-based candidates are eligible. Otherwise you'll
  see ⚠️ "verify eligibility".
* **Transferable** means you get partial credit for an equivalent tool (e.g. Redshift ← PostgreSQL). That is a
  talking point for an interview, not something claimed on your resume.
* **Confidence** reflects how much information the description gave, not how good the job is.
* Off-target roles (analyst, scientist, generic software engineering) are deliberately scaled down. The
  adjustment is shown in the breakdown.

---

## 4. Reviewing a tailored resume (checklist)

Before sending, open the `…_tailoring_report.md` and confirm:

1. **Validation: PASSED.** If it says FAILED, the resume is marked `needs_review`. Read the errors, fix your
   profile if needed, and regenerate with `tailor <id> --force`.
2. **"Requirements NOT supported by your profile"**: these were deliberately left out. Be ready to discuss them
   honestly, or skip the job.
3. **Summary**: it is built only from verified facts. Edit the DOCX by hand if you want a different tone.
4. **Omitted bullets**: lower-relevance bullets may be left out (they remain in your master resume). Re-add any you
   want in the DOCX.
5. **"Needs your input"**: e.g. a certification the job requires that isn't in your profile.

What the tool guarantees: same employers, titles and dates; every bullet comes from your resume; no new skills,
numbers or achievements; project-only skills appear on a separate "Project experience" line; studied-only skills
appear only under "Currently learning". The checks run again on the final DOCX text.

---

## 5. Dashboard tour

`python -m jobagent dashboard` opens it locally at http://localhost:8501. It is not reachable from other machines.

* **Filters (top row):** score range, location, role, arrangement, company, status. They apply to the tiles,
  charts and table.
* **Tiles:** sightings (all imports), unique jobs, analysed, strong / potential / stretch / low, resumes generated,
  awaiting your review.
* **Charts:** jobs by category, location, arrangement, role, company, most-requested skills, and posting week.
  These are all counts. Small samples are labelled as such.
* **Jobs table:** sortable, with a link to each posting.
* **Job detail:** score breakdown, constraints, strengths and gaps, resume download or generation, and decision
  buttons.
* **Exports:** CSV (all jobs, shortlist), an Excel workbook (all / shortlisted / skill gaps), and a summary report.
  The same exports are available via `python -m jobagent report`.

---

## 6. Optional: AI analysis

Off by default. Everything works without it. To enable:

1. Put `ANTHROPIC_API_KEY=...` in `.env`.
2. Set `ai.provider: anthropic` in `config/settings.yaml` (optionally adjust `ai.model` and `ai.effort`;
   lower effort costs less).
3. Run `python -m jobagent analyze --force` to re-score jobs with AI.

What gets sent: the job description and a copy of your profile **without** name, email, phone or links.
What the AI can and can't do: it refines only the responsibilities score (50/50 with the rule-based score); any
resume evidence it cites is checked against your profile; it can flag concerns but never mark a job ineligible on
its own. Results are cached, so the same job isn't paid for twice. `python -m jobagent status` shows calls,
tokens and estimated cost.

`resume.ai_rewrite_bullets: true` additionally lets AI reword bullets. Any rewrite that adds or removes a
number, or adds a skill, is rejected automatically.

---

## 7. Maintenance

| Task | Command / action |
|---|---|
| Check setup, counts, AI cost | `python -m jobagent status` |
| Retry failed analyses or resumes | `python -m jobagent retry` |
| Re-score everything after changing weights or profile | `python -m jobagent analyze --force` |
| Teach it a new tool name | add it to `config/skills_taxonomy.yaml` (aliases, implies, equivalent) |
| Update your profile | edit the YAML, then `profile approve` (jobs are re-scored automatically on the next run) |
| Delete local job data or generated files | `python -m jobagent purge --jobs --resumes --reports` (asks to confirm; never touches your master resume or profile) |
| Logs | `data/logs/jobagent.jsonl` (secrets and contact details are redacted) |

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "profile has not been reviewed" | edit `data/profile/candidate_profile.yaml`, then `profile approve`; `profile show` lists blockers |
| A saved LinkedIn page imports as `partial` | LinkedIn changed its layout. Paste the text as a `.txt` job instead, or use `add-details` |
| A job shows `needs_manual_review` | it's URL-only; use `add-details <id> <file>` |
| A skill you have shows as missing | add an alias in `config/skills_taxonomy.yaml`, or update the skill's level in your profile |
| A wrong role or date after re-extracting | fix the YAML by hand; multi-column or scanned PDFs parse poorly (a DOCX helps) |
| No PDF resume | install LibreOffice |
| Dashboard won't start | `pip install streamlit plotly` |
| AI not used | `status` explains why (provider `none`, missing key, …) |

---

## 9. Quick reference

```bash
python -m jobagent status                      # readiness and counts
python -m jobagent links                       # LinkedIn search links
python -m jobagent run [--tailor]              # import -> score -> (resumes) -> reports
python -m jobagent jobs [--status shortlisted] [--needs-details] [--min-score 70]
python -m jobagent show <id>                   # why this score
python -m jobagent add-details <id> <file>     # complete a URL-only job
python -m jobagent tailor <id> | --shortlisted [--force]
python -m jobagent set-status <id> applied|reviewed|rejected|closed [--reason "..."]
python -m jobagent report                      # CSV / Excel / summary
python -m jobagent dashboard
python -m jobagent retry
python -m jobagent purge --jobs --resumes --reports
```
