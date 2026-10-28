"""Command-line interface:  python -m jobagent <command> ...

Nothing in this tool applies to jobs, contacts anyone, or uploads your resume.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from jobagent.config import Settings, load_settings, startup_report
from jobagent.logging_setup import setup_logging
from jobagent.models import JobStatus

log = logging.getLogger("jobagent.cli")


# ------------------------------------------------------------------ helpers
def _db(settings: Settings):
    from jobagent.storage.db import Database
    return Database(settings.path(settings.storage.db_path))


def _taxonomy():
    from jobagent.taxonomy import load_taxonomy
    return load_taxonomy()


def _print_table(rows: list[dict], cols: list[tuple[str, str, int]]) -> None:
    print("  ".join(h.ljust(w) for _, h, w in cols))
    print("  ".join("-" * w for _, _, w in cols))
    for r in rows:
        cells = []
        for key, _, w in cols:
            v = r.get(key)
            s = "" if v is None else (f"{v:.0f}" if isinstance(v, float) else str(v))
            cells.append(s[:w].ljust(w))
        print("  ".join(cells))


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"{prompt} Type 'yes' to confirm: ").strip().lower() == "yes"
    except EOFError:
        return False


# ------------------------------------------------------------------ commands
def cmd_init(settings: Settings, args) -> int:
    for p in (settings.path(settings.profile.master_resume_path).parent,
              settings.path(settings.profile.candidate_profile_path).parent,
              settings.path(settings.sources.linkedin.inbox_dir), settings.path(settings.sources.manual.inbox_dir),
              settings.path(settings.resume.output_dir), settings.path(settings.reporting.output_dir),
              settings.path(settings.logging.dir)):
        p.mkdir(parents=True, exist_ok=True)
    env = settings.root / ".env"
    if not env.exists() and (settings.root / ".env.example").exists():
        shutil.copy(settings.root / ".env.example", env)
        print(f"created {env} (fill in only if you enable AI)")
    _db(settings).close()
    print("Initialised data directories and database.\n")
    return cmd_status(settings, args)


def cmd_status(settings: Settings, args) -> int:
    for level, check, msg in startup_report(settings):
        print(f"[{level.upper():4}] {check}: {msg}")
    db_path = settings.path(settings.storage.db_path)
    if db_path.exists():
        db = _db(settings)
        counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
        manual = db.q1("SELECT COUNT(*) n FROM jobs WHERE retrieval_status IN ('needs_manual_review','failed')")["n"]
        print(f"\nJobs by status: {counts or 'none yet'}")
        if manual:
            print(f"Jobs awaiting details from you (URL only / failed): {manual}  -> `jobagent jobs --needs-details`")
        failed = db.failed_tasks()
        if failed:
            print(f"Failed tasks awaiting retry: {len(failed)}  -> `jobagent retry`")
        usage = db.ai_usage()
        if usage.get("calls"):
            print(f"AI usage: {usage['calls']} calls ({usage['cached'] or 0} cached, {usage['errors'] or 0} errors), "
                  f"{usage['input_tokens'] or 0} in / {usage['output_tokens'] or 0} out tokens, "
                  f"est. ${usage['cost_usd'] or 0:.4f}")
    return 0


def cmd_profile(settings: Settings, args) -> int:
    from jobagent.profile.parser import ResumeParseError
    from jobagent.profile.store import (ProfileNotReady, approve, extract_to_file, load_profile,
                                        review_problems)
    ppath = settings.path(settings.profile.candidate_profile_path)
    if args.action == "extract":
        resume = settings.path(Path(args.resume) if args.resume else settings.profile.master_resume_path)
        if not resume.exists():
            print(f"Master resume not found at {resume}.\nPlease copy your resume (.docx or .pdf) there, or set "
                  "profile.master_resume_path in config/settings.yaml, then rerun this command.")
            return 2
        try:
            profile, target = extract_to_file(resume, ppath, _taxonomy(), force=args.force)
        except ResumeParseError as exc:
            print(f"Could not parse resume: {exc}")
            return 2
        print(f"Extracted profile written to {target}")
        if target != ppath:
            print("Your existing reviewed profile was kept; compare the new file and merge changes manually "
                  "(or rerun with --force to replace it).")
        print(f"  {len(profile.experience)} roles, {len(profile.projects)} projects, {len(profile.skills)} skills, "
              f"{profile.total_experience_years} years computed")
        print(f"  {len(profile.unverified)} items flagged for your review.\n"
              f"Next: edit {target.name}, then run `python -m jobagent profile approve`.")
        return 0
    try:
        profile = load_profile(ppath)
    except ProfileNotReady as exc:
        print(exc)
        return 2
    if args.action == "show":
        print(f"Name: {profile.name}   Reviewed: {profile.reviewed}   Experience: {profile.total_experience_years} yrs")
        for e in profile.experience:
            print(f"  - {e.title} @ {e.employer} ({e.start} – {e.end}): {', '.join(e.skills)}")
        for lvl in ("professional", "project", "listed", "studied"):
            names = [s.name for s in profile.skills if s.level == lvl]
            if names:
                print(f"  {lvl:12} {', '.join(names)}")
        if profile.unverified:
            print("Unverified items:")
            for u in profile.unverified:
                print(f"  ? {u}")
        problems = review_problems(profile)
        if problems:
            print("Blocking issues before approval:")
            for p in problems:
                print(f"  ! {p}")
        return 0
    if args.action == "approve":
        try:
            approve(ppath)
        except ProfileNotReady as exc:
            print(exc)
            return 2
        print("Profile approved. Matching and resume tailoring will use it.")
        return 0
    return 1


def cmd_links(settings: Settings, args) -> int:
    from jobagent.reporting.links import write_links_page
    from jobagent.sources.linkedin import build_search_urls
    links = build_search_urls(settings, per_city=args.per_city)
    out = write_links_page(settings, links)
    for l in links:
        print(f"{l['title']:28} {l['location']:24} {l['work_arrangement']:20} {l['url']}")
    print(f"\n{len(links)} links. Clickable page: {out}")
    print("Open them in your browser, then save interesting jobs (Ctrl+S on the job page, or paste the text) into "
          f"{settings.path(settings.sources.linkedin.inbox_dir)} and run `python -m jobagent import`.")
    return 0


def _is_linkedin_file(p: Path) -> bool:
    if "linkedin" in p.name.lower():
        return True
    if p.suffix.lower() in (".html", ".htm", ".txt", ".md"):
        return "linkedin.com/" in p.read_text(encoding="utf-8", errors="ignore")[:200_000]
    return False


def _import(settings: Settings, db, run_id: int, files: list[str], urls: list[str], use_inbox: bool):
    from jobagent.ingestion.pipeline import ingest
    from jobagent.sources.base import CollectRequest
    from jobagent.sources.registry import enabled_sources
    sources = {s.name: s for s in enabled_sources(settings)}
    routed: dict[str, list[Path]] = {name: [] for name in sources}
    for f in map(Path, files):
        target = "linkedin" if "linkedin" in sources and _is_linkedin_file(f) else "manual"
        if target not in sources:
            raise ValueError(f"no enabled source can import {f} (enable 'manual' in sources.enabled)")
        routed[target].append(f)
    results = []
    for name, src in sources.items():
        own_urls = [u for u in urls if src.handles_url(u)]
        results.append(src.collect(CollectRequest(files=routed[name], urls=own_urls, use_inbox=use_inbox)))
    return ingest(db, results, run_id, max_jobs=settings.search.max_jobs_per_run)


def cmd_import(settings: Settings, args) -> int:
    db = _db(settings)
    run_id = db.start_run("import")
    try:
        stats = _import(settings, db, run_id, args.files, args.url or [], not args.no_inbox)
    except Exception as exc:
        db.finish_run(run_id, "failed", {}, str(exc))
        raise
    db.finish_run(run_id, "partial" if stats.errors else "completed", {"ingest": stats.as_dict()})
    _print_ingest(stats)
    return 0


def _print_ingest(stats) -> None:
    print(f"Received {stats.received} records: {stats.inserted} new, {stats.duplicates} duplicates "
          f"({stats.updated} merged with new details).")
    print(f"Retrieval: {stats.by_retrieval}")
    for n in stats.notes:
        print(f"note: {n}")
    for e in stats.errors:
        print(f"error: {e}")


def _analyzer(settings: Settings, db, run_id: int | None):
    from jobagent.ai.client import AIClient
    from jobagent.matching.analyzer import Analyzer
    from jobagent.profile.store import require_reviewed
    profile = require_reviewed(settings.path(settings.profile.candidate_profile_path))
    ai = AIClient(settings, db, run_id=run_id) if settings.matching.use_ai else None
    if ai and ai.available:
        print(f"AI analysis enabled ({settings.ai.provider}/{settings.ai.model}): job descriptions and a "
              "contact-free copy of your profile will be sent to the provider.")
    return Analyzer(settings, db, _taxonomy(), profile, ai=ai, run_id=run_id)


def _print_analyze(stats) -> None:
    print(f"Analysed {stats.analyzed} jobs ({stats.skipped_current} already current, "
          f"{stats.skipped_no_description} awaiting descriptions, {stats.failed} failed). "
          f"Categories: {stats.by_category}")
    if stats.ai_unavailable_reason:
        print(f"note: deterministic scoring only ({stats.ai_unavailable_reason})")
    for e in stats.errors:
        print(f"error: {e}")


def cmd_analyze(settings: Settings, args) -> int:
    from jobagent.profile.store import ProfileNotReady
    db = _db(settings)
    run_id = db.start_run("analyze")
    try:
        an = _analyzer(settings, db, run_id)
        stats = an.analyze(job_ids=args.job or None, force=args.force, limit=args.limit)
    except ProfileNotReady as exc:
        db.finish_run(run_id, "failed", {}, str(exc))
        print(exc)
        return 2
    db.finish_run(run_id, "partial" if stats.failed else "completed", {"analyze": stats.__dict__})
    _print_analyze(stats)
    return 0


def _tailor(settings: Settings, db, run_id: int, job_ids: list[int], force: bool) -> list[str]:
    from jobagent.profile.store import require_reviewed
    from jobagent.resume.service import ResumeService
    profile = require_reviewed(settings.path(settings.profile.candidate_profile_path))
    svc = ResumeService(settings, db, _taxonomy(), profile, run_id=run_id)
    lines = []
    for jid in job_ids:
        try:
            out = svc.generate(jid, force=force)
            db.mark_task(run_id, jid, "tailor", "done")
            lines.append(f"job {jid}: {out.status} -> {out.docx_path}" + (f" (+PDF)" if out.pdf_path else "")
                         + (f"\n    issues: {'; '.join(out.issues[:4])}" if out.issues else ""))
        except Exception as exc:
            log.exception("tailoring failed for job %s", jid)
            db.mark_task(run_id, jid, "tailor", "failed", str(exc)[:500])
            lines.append(f"job {jid}: FAILED: {exc}")
    return lines


def cmd_tailor(settings: Settings, args) -> int:
    from jobagent.profile.store import ProfileNotReady
    db = _db(settings)
    ids = list(args.job or [])
    if args.shortlisted:
        ids += [r["id"] for r in db.q("SELECT id FROM jobs WHERE status='shortlisted' ORDER BY id")]
    if not ids:
        print("No jobs selected. Use `tailor <job_id>` or `tailor --shortlisted`.")
        return 1
    run_id = db.start_run("tailor")
    try:
        lines = _tailor(settings, db, run_id, ids, args.force)
    except ProfileNotReady as exc:
        db.finish_run(run_id, "failed", {}, str(exc))
        print(exc)
        return 2
    db.finish_run(run_id, "completed", {"tailored": len(lines)})
    print("\n".join(lines))
    return 0


def cmd_report(settings: Settings, args) -> int:
    from jobagent.reporting.exports import generate_reports
    db = _db(settings)
    paths = generate_reports(settings, db, run_id=None)
    for k, v in paths.items():
        print(f"{k:16} {v}")
    return 0


def cmd_run(settings: Settings, args) -> int:
    """Full pipeline: import -> analyze -> (tailor shortlisted) -> report."""
    from jobagent.profile.store import ProfileNotReady
    from jobagent.reporting.exports import generate_reports
    db = _db(settings)
    run_id = db.start_run("run")
    stats: dict = {}
    status = "completed"
    try:
        ing = _import(settings, db, run_id, args.files, args.url or [], not args.no_inbox)
        stats["ingest"] = ing.as_dict()
        _print_ingest(ing)
        try:
            an = _analyzer(settings, db, run_id)
            ast = an.analyze()
            stats["analyze"] = ast.__dict__
            _print_analyze(ast)
            if ast.failed:
                status = "partial"
            if args.tailor:
                ids = [r["id"] for r in db.q("SELECT j.id FROM jobs j WHERE j.status='shortlisted'")]
                lines = _tailor(settings, db, run_id, ids, False)
                stats["tailored"] = len(lines)
                print("\n".join(lines))
        except ProfileNotReady as exc:
            status = "partial"
            print(f"Skipping analysis: {exc}")
        paths = generate_reports(settings, db, run_id=run_id)
        stats["reports"] = {k: str(v) for k, v in paths.items()}
        print("\nReports:")
        for k, v in paths.items():
            print(f"  {k:16} {v}")
    except Exception as exc:
        db.finish_run(run_id, "failed", stats, str(exc))
        raise
    db.finish_run(run_id, status, stats)
    return 0


def cmd_jobs(settings: Settings, args) -> int:
    db = _db(settings)
    rows = db.jobs_overview()
    if args.status:
        rows = [r for r in rows if r["status"] == args.status]
    if args.min_score is not None:
        rows = [r for r in rows if (r["score"] or 0) >= args.min_score]
    if args.needs_details:
        rows = [r for r in rows if r["retrieval_status"] in ("needs_manual_review", "failed")]
    for r in rows:
        r["rec"] = (r["result"] or {}).get("recommendation")
    _print_table(rows, [("id", "ID", 4), ("score", "Score", 5), ("category", "Category", 9), ("rec", "Recommend", 18),
                        ("status", "Status", 16), ("title", "Title", 32), ("company", "Company", 24),
                        ("city", "City", 11), ("work_arrangement", "Arrangement", 11), ("retrieval_status", "Data", 19)])
    if args.needs_details:
        print("\nSupply a description with: python -m jobagent add-details <ID> <file.txt|file.html>")
    return 0


def cmd_show(settings: Settings, args) -> int:
    db = _db(settings)
    job = db.job(args.job_id)
    if not job:
        print("job not found")
        return 1
    a = db.latest_analysis(args.job_id)
    print(f"#{job['id']} {job['title']} @ {job['company']} | {job['location']} | {job['work_arrangement']} | "
          f"{job['employment_type']}\nURL: {job['canonical_url']}\nStatus: {job['status']}  Data: {job['retrieval_status']}"
          f"  First seen: {job['first_seen_at']}  Posted: {job['posted_at']}")
    if not a:
        print("\nNot analysed yet." + (" Needs a description (add-details)." if job["retrieval_status"] in ("needs_manual_review", "failed") else ""))
        return 0
    r = a["result"]
    print(f"\nScore {r['score']} ({r['category']}, confidence {r['confidence']}) → {r['recommendation']}")
    print(r["explanation"])
    for adj in r.get("adjustments", []):
        print(f"  adjustment: {adj}")
    for c in r["components"]:
        print(f"\n  {c['name']}: {c['score']:.2f} × {c['weight']:g} = {c['points']}")
        for e in c["evidence"][:12]:
            print(f"     {e}")
    print("\nHard constraints:")
    for h in r["hard_constraints"] or [{"name": "-", "status": "none", "detail": ""}]:
        print(f"  [{h['status']}] {h['name']}: {h['detail']}")
    for label, key in (("Strengths", "strengths"), ("Missing required", "missing_required"),
                       ("Missing preferred", "missing_preferred"), ("Transferable", "transferable"),
                       ("Reasons to apply", "reasons_to_apply"), ("Reasons not to apply", "reasons_not_to_apply")):
        if r.get(key):
            print(f"\n{label}:\n  - " + "\n  - ".join(r[key]))
    print("\nStatus history:")
    for h in db.status_history(args.job_id):
        print(f"  {h['changed_at']}  {h['from_status'] or '-'} → {h['to_status']}  ({h['reason']})")
    return 0


def cmd_set_status(settings: Settings, args) -> int:
    db = _db(settings)
    with db.tx():
        db.set_status(args.job_id, JobStatus(args.status), args.reason or "set by user")
        if args.status == JobStatus.CLOSED.value:
            db.update_job(args.job_id, {"availability": "closed"})
    print(f"job {args.job_id} → {args.status}")
    return 0


def cmd_add_details(settings: Settings, args) -> int:
    """Attach a description (pasted text or saved page) to an existing job, e.g. a URL-only LinkedIn record."""
    from jobagent.ingestion.pipeline import upsert_job
    from jobagent.models import RawJob, RetrievalStatus
    from jobagent.sources.html_parser import grade, parse_job_html
    from jobagent.sources.linkedin import SELECTORS
    from jobagent.sources.textjob import looks_like_text_job, parse_text_jobs
    db = _db(settings)
    job = db.job(args.job_id)
    if not job:
        print("job not found")
        return 1
    path = Path(args.file)
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        raw = parse_job_html(text, job["source"], selectors=SELECTORS)
        if raw is None:
            print("no job posting found in that page")
            return 1
    elif looks_like_text_job(text):
        raw = parse_text_jobs(text, job["source"])[0]
    else:
        raw = RawJob(source=job["source"], description=text)
    raw.source, raw.source_job_id, raw.url = job["source"], job["source_job_id"], job["canonical_url"]
    raw.title = raw.title or job["title"]
    raw.company = raw.company or job["company"]
    raw.retrieval_status = grade(raw) if raw.title else RetrievalStatus.PARTIAL
    raw.retrieval_notes = f"details supplied by user from {path.name}"
    job_id, outcome = upsert_job(db, raw, None)
    j = db.job(job_id)
    if not j["title"] or not j["company"]:
        print("Description saved. Title/company still missing: put 'Title:' and 'Company:' lines at the top of the file "
              "and rerun, or the job will be analysed with partial data.")
    print(f"job {job_id}: {outcome}; data now '{j['retrieval_status']}'. Run `python -m jobagent analyze --job {job_id}`.")
    return 0


def cmd_retry(settings: Settings, args) -> int:
    db = _db(settings)
    failed = db.failed_tasks()
    if not failed:
        print("No failed tasks.")
        return 0
    run_id = db.start_run("retry")
    an_ids = [t["job_id"] for t in failed if t["stage"] == "analyze"]
    tl_ids = [t["job_id"] for t in failed if t["stage"] == "tailor"]
    if an_ids:
        st = _analyzer(settings, db, run_id).analyze(job_ids=an_ids, force=True)
        _print_analyze(st)
    if tl_ids:
        print("\n".join(_tailor(settings, db, run_id, tl_ids, True)))
    db.finish_run(run_id, "completed", {"retried": len(failed)})
    return 0


def cmd_dashboard(settings: Settings, args) -> int:
    import subprocess
    app = Path(__file__).parent / "dashboard" / "app.py"
    if not shutil.which("streamlit"):
        print("Streamlit is not installed: pip install 'jobagent[dashboard]'  (or pip install streamlit plotly)")
        return 2
    import os
    env = dict(os.environ)
    if args.config:
        env["JOBAGENT_CONFIG"] = str(Path(args.config).resolve())
    # Bound to localhost only: the dashboard shows private data.
    return subprocess.call(["streamlit", "run", str(app), "--server.headless", "true", "--server.address", "localhost",
                            "--browser.gatherUsageStats", "false"], env=env)


def cmd_purge(settings: Settings, args) -> int:
    if not (args.jobs or args.resumes or args.reports):
        print("Choose what to delete: --jobs (database job data), --resumes (generated resumes), --reports")
        return 1
    what = [n for n, f in (("all job data in the database", args.jobs), ("all generated resumes", args.resumes),
                           ("all generated reports", args.reports)) if f]
    if not _confirm(f"This will permanently delete {', '.join(what)}. Your master resume and profile are NOT touched.",
                    args.yes):
        print("Cancelled.")
        return 1
    if args.jobs:
        counts = _db(settings).purge_all_job_data()
        print(f"deleted rows: {counts}")
    for flag, key in ((args.resumes, settings.resume.output_dir), (args.reports, settings.reporting.output_dir)):
        if flag:
            d = settings.path(key)
            master = settings.path(settings.profile.master_resume_path).resolve()
            if d.exists() and master not in [p.resolve() for p in d.rglob("*")]:
                shutil.rmtree(d)
                d.mkdir(parents=True)
                print(f"emptied {d}")
            elif d.exists():
                print(f"refusing to delete {d}: it contains the master resume")
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobagent", description=__doc__)
    p.add_argument("--config", help="path to settings.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create data folders and database, show setup status")
    sub.add_parser("status", help="show setup status, job counts and AI usage")

    pr = sub.add_parser("profile", help="extract / show / approve the candidate profile")
    pr.add_argument("action", choices=["extract", "show", "approve"])
    pr.add_argument("--resume", help="resume path (defaults to profile.master_resume_path)")
    pr.add_argument("--force", action="store_true", help="overwrite an already-reviewed profile")

    li = sub.add_parser("links", help="generate LinkedIn search links to open in your browser")
    li.add_argument("--per-city", action="store_true")

    for name, helptext in (("import", "import jobs from inboxes, files and URLs"),
                           ("run", "import + analyse + report (optionally tailor shortlisted)")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("files", nargs="*", help="job files (.html, .txt, .csv, .json)")
        sp.add_argument("--url", action="append", help="job URL (repeatable)")
        sp.add_argument("--no-inbox", action="store_true", help="do not scan inbox folders")
        if name == "run":
            sp.add_argument("--tailor", action="store_true", help="generate resumes for shortlisted jobs")

    an = sub.add_parser("analyze", help="score and analyse jobs")
    an.add_argument("--job", type=int, action="append")
    an.add_argument("--force", action="store_true", help="re-analyse even if a current analysis exists")
    an.add_argument("--limit", type=int)

    tl = sub.add_parser("tailor", help="generate tailored resumes")
    tl.add_argument("job", type=int, nargs="*")
    tl.add_argument("--shortlisted", action="store_true")
    tl.add_argument("--force", action="store_true")

    sub.add_parser("report", help="write CSV / Excel / summary reports")

    jb = sub.add_parser("jobs", help="list jobs")
    jb.add_argument("--status", choices=[s.value for s in JobStatus])
    jb.add_argument("--min-score", type=float)
    jb.add_argument("--needs-details", action="store_true")

    sh = sub.add_parser("show", help="explain one job's score")
    sh.add_argument("job_id", type=int)

    ss = sub.add_parser("set-status", help="record your decision (reviewed, applied, closed, rejected ...)")
    ss.add_argument("job_id", type=int)
    ss.add_argument("status", choices=[s.value for s in JobStatus])
    ss.add_argument("--reason")

    ad = sub.add_parser("add-details", help="attach a pasted/saved description to an existing job")
    ad.add_argument("job_id", type=int)
    ad.add_argument("file")

    sub.add_parser("retry", help="retry failed analysis/tailoring tasks")
    sub.add_parser("dashboard", help="launch the Streamlit dashboard")

    pg = sub.add_parser("purge", help="delete local job data / generated files (asks for confirmation)")
    pg.add_argument("--jobs", action="store_true")
    pg.add_argument("--resumes", action="store_true")
    pg.add_argument("--reports", action="store_true")
    pg.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    return p


COMMANDS = {
    "init": cmd_init, "status": cmd_status, "profile": cmd_profile, "links": cmd_links, "import": cmd_import,
    "analyze": cmd_analyze, "tailor": cmd_tailor, "report": cmd_report, "run": cmd_run, "jobs": cmd_jobs,
    "show": cmd_show, "set-status": cmd_set_status, "add-details": cmd_add_details, "retry": cmd_retry,
    "dashboard": cmd_dashboard, "purge": cmd_purge,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
    except Exception as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 2
    setup_logging(settings.path(settings.logging.dir), settings.logging.level)
    try:
        return COMMANDS[args.cmd](settings, args)
    except BrokenPipeError:  # output piped into e.g. `head`
        return 0
    except KeyboardInterrupt:
        print("interrupted; completed work has been saved")
        return 130
