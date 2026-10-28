"""CSV / Excel exports and a Markdown run summary."""
from __future__ import annotations

import io
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

from jobagent.config import Settings
from jobagent.storage.db import Database
from jobagent.utils.files import atomic_write_bytes, atomic_write_text

CATEGORY_LABEL = {"strong": "Strong match", "potential": "Potential match", "stretch": "Stretch opportunity",
                  "low": "Low priority"}


def jobs_frame(db: Database) -> pd.DataFrame:
    rows = []
    for j in db.jobs_overview():
        r = j.get("result") or {}
        req = j.get("requirements") or {}
        warnings = [f"{c['name']}: {c['detail']}" for c in r.get("hard_constraints", []) if c["status"] != "pass"]
        rows.append({
            "job_id": j["id"], "score": j.get("score"), "category": CATEGORY_LABEL.get(j.get("category") or "", None),
            "category_key": j.get("category"), "recommendation": r.get("recommendation"), "confidence": r.get("confidence"),
            "eligible": bool(j["eligible"]) if j.get("eligible") is not None else None,
            "title": j.get("title"), "role_category": j.get("role_category"), "company": j.get("company"),
            "location": j.get("location"), "city": j.get("city"), "country": j.get("country"),
            "work_arrangement": j.get("work_arrangement"), "employment_type": j.get("employment_type"),
            "posted_at": j.get("posted_at"), "deadline": j.get("deadline"),
            "salary": (f"{j['salary_currency'] or ''} {j['salary_min']:,.0f}-{j['salary_max']:,.0f} {j['salary_period'] or ''}".strip()
                       if j.get("salary_min") and j.get("salary_max") else None),
            "matching_skills": ", ".join(r.get("strengths", [])[:6]),
            "missing_required": ", ".join(r.get("missing_required", [])),
            "missing_preferred": ", ".join(r.get("missing_preferred", [])),
            "eligibility_warnings": "; ".join(warnings),
            "required_skills": ", ".join(req.get("required_skills", [])),
            "preferred_skills": ", ".join(req.get("preferred_skills", [])),
            "min_years": req.get("min_years"),
            "explanation": r.get("explanation"),
            "status": j.get("status"), "data_quality": j.get("retrieval_status"),
            "resume_status": j.get("resume_status"), "resume_docx": j.get("docx_path"), "resume_pdf": j.get("pdf_path"),
            "url": j.get("canonical_url"), "source": j.get("source"),
            "first_seen": j.get("first_seen_at"), "last_checked": j.get("last_checked_at"),
            "_req": req, "_result": r,
        })
    return pd.DataFrame(rows)


def skill_gap_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per skill: how many analysed jobs ask for it (required / preferred) and how many you are missing it in."""
    analysed = df[df["score"].notna()]
    req, pref, miss = Counter(), Counter(), Counter()
    for _, row in analysed.iterrows():
        q = row["_req"] or {}
        req.update(q.get("required_skills", []))
        pref.update(q.get("preferred_skills", []))
        miss.update((row["_result"] or {}).get("missing_required", []))
        miss.update((row["_result"] or {}).get("missing_preferred", []))
    skills = set(req) | set(pref)
    n = max(len(analysed), 1)
    out = [{"skill": s, "required_in": req[s], "preferred_in": pref[s], "jobs_mentioning": req[s] + pref[s],
            "pct_of_analysed_jobs": round(100 * (req[s] + pref[s]) / n, 1), "you_are_missing_in": miss[s]}
           for s in skills]
    return pd.DataFrame(out).sort_values(["jobs_mentioning", "required_in"], ascending=False) if out else pd.DataFrame(
        columns=["skill", "required_in", "preferred_in", "jobs_mentioning", "pct_of_analysed_jobs", "you_are_missing_in"])


def _public(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in df.columns if c.startswith("_") or c == "category_key"], errors="ignore")


def summary_markdown(settings: Settings, df: pd.DataFrame, gaps: pd.DataFrame, db: Database, run_id: int | None) -> str:
    now = datetime.now()
    analysed = df[df["score"].notna()]
    seen = pd.to_datetime(df["first_seen"], errors="coerce", utc=True) if len(df) else pd.Series(dtype="datetime64[ns, UTC]")
    period = f"{seen.min():%Y-%m-%d} to {seen.max():%Y-%m-%d}" if len(seen.dropna()) else "n/a"
    n = len(analysed)
    small = n < settings.reporting.min_sample_for_trends
    cats = analysed["category_key"].value_counts().to_dict() if n else {}
    L = [f"# Job search summary ({now:%Y-%m-%d %H:%M})", "",
         f"Reporting period (jobs first seen): **{period}**", ""]
    if run_id:
        run = next((r for r in db.runs(50) if r["id"] == run_id), None)
        if run:
            ing = run["stats"].get("ingest", {})
            L += [f"This run: {ing.get('received', 0)} records received, {ing.get('inserted', 0)} new, "
                  f"{ing.get('duplicates', 0)} duplicates.", ""]
    L += ["## Totals (counts)",
          f"- Jobs in database (unique after deduplication): {len(df)}",
          f"- Sightings recorded (all imports, incl. duplicates): {db.q1('SELECT COUNT(*) n FROM job_sightings')['n']}",
          f"- Analysed: {n}",
          f"- Strong matches: {cats.get('strong', 0)} · Potential: {cats.get('potential', 0)} · "
          f"Stretch: {cats.get('stretch', 0)} · Low priority: {cats.get('low', 0)}",
          f"- Not eligible as stated (hard constraint failed): {int((analysed['eligible'] == False).sum()) if n else 0}",
          f"- Awaiting details from you (URL only / failed fetch): {int(df['data_quality'].isin(['needs_manual_review', 'failed']).sum()) if len(df) else 0}",
          f"- Resumes generated: {int(df['resume_status'].notna().sum()) if len(df) else 0} "
          f"(ready: {int((df['resume_status'] == 'ready').sum()) if len(df) else 0})",
          f"- Awaiting your review (shortlisted or resume generated): {int(df['status'].isin(['shortlisted', 'resume_generated']).sum()) if len(df) else 0}",
          "", "_Coverage note: LinkedIn is not searched automatically; these results include only jobs you imported "
          "and are not an exhaustive view of the market._", ""]
    top = analysed[(analysed["eligible"] == True)].sort_values("score", ascending=False).head(10)
    L += ["## Top opportunities"]
    if len(top):
        for _, r in top.iterrows():
            L.append(f"- **{r['score']:.0f}** {r['title']} @ {r['company']} ({r['city'] or r['location'] or '?'}, "
                     f"{r['work_arrangement']}) → {r['recommendation']}" + (f"  [{r['url']}]" if r["url"] else ""))
    else:
        L.append("- none yet")
    L += ["", f"## Market skill trends (based on {n} analysed jobs, {period})"]
    if small:
        L.append(f"_Small sample (< {settings.reporting.min_sample_for_trends} jobs): treat these as anecdotal, not trends._")
    for _, g in gaps.head(10).iterrows():
        L.append(f"- {g['skill']}: in {g['jobs_mentioning']} of {n} jobs ({g['pct_of_analysed_jobs']}%); "
                 f"required in {g['required_in']}")
    common_gaps = gaps[gaps["you_are_missing_in"] > 0].sort_values("you_are_missing_in", ascending=False).head(8)
    L += ["", f"## Most common qualification gaps (of {n} analysed jobs)"]
    L += [f"- {g['skill']}: missing in {g['you_are_missing_in']} job(s)" for _, g in common_gaps.iterrows()] or ["- none"]
    L += ["", "## Recommended next steps"]
    steps = []
    if cats.get("strong") or cats.get("potential"):
        steps.append("Review the shortlisted jobs (`python -m jobagent jobs --status shortlisted`) and generate "
                     "resumes for the ones you want (`python -m jobagent tailor <id>`).")
    needs = int(df["data_quality"].isin(["needs_manual_review", "failed"]).sum()) if len(df) else 0
    if needs:
        steps.append(f"Add descriptions for {needs} URL-only job(s) (`python -m jobagent jobs --needs-details`).")
    if len(common_gaps) and not small:
        steps.append(f"Consider building credible evidence (a portfolio project or course) for: "
                     f"{', '.join(common_gaps['skill'].head(3))}.")
    if small:
        steps.append("Import more jobs before drawing conclusions about skill trends.")
    L += [f"{i}. {s}" for i, s in enumerate(steps, 1)] or ["1. Import jobs to get started."]
    usage = db.ai_usage()
    if usage.get("calls"):
        L += ["", f"_AI usage to date: {usage['calls']} calls, est. ${usage['cost_usd'] or 0:.4f}_"]
    return "\n".join(L) + "\n"


def generate_reports(settings: Settings, db: Database, run_id: int | None = None) -> dict[str, Path]:
    out_dir = settings.path(settings.reporting.output_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = jobs_frame(db)
    gaps = skill_gap_frame(df) if len(df) else skill_gap_frame(pd.DataFrame(columns=["score"]))
    pub = _public(df)
    short = pub[pub["status"].isin(["shortlisted", "resume_generated", "reviewed", "applied"])] if len(pub) else pub

    paths = {}
    for name, frame in (("all_jobs_csv", pub), ("shortlist_csv", short)):
        p = out_dir / f"{name.replace('_csv', '')}_{stamp}.csv"
        atomic_write_bytes(p, frame.to_csv(index=False).encode("utf-8-sig"))
        paths[name] = p
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pub.to_excel(xw, sheet_name="All jobs", index=False)
        short.to_excel(xw, sheet_name="Shortlisted", index=False)
        gaps.to_excel(xw, sheet_name="Skill gaps", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = min(60, max(10, max((len(str(c.value)) for c in col if c.value is not None), default=10)))
                ws.column_dimensions[col[0].column_letter].width = width
    paths["excel"] = out_dir / f"job_report_{stamp}.xlsx"
    atomic_write_bytes(paths["excel"], buf.getvalue())
    paths["summary_md"] = out_dir / f"summary_{stamp}.md"
    atomic_write_text(paths["summary_md"], summary_markdown(settings, df, gaps, db, run_id))
    return paths
