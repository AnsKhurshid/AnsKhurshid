"""Local Streamlit dashboard:  python -m jobagent dashboard   (or: streamlit run jobagent/dashboard/app.py)

Read-mostly: it can record your own decisions (reviewed / applied / closed) and generate resumes locally.
It never applies to jobs or contacts anyone.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jobagent.config import load_settings  # noqa: E402
from jobagent.models import JobStatus  # noqa: E402
from jobagent.reporting.exports import generate_reports, jobs_frame, skill_gap_frame  # noqa: E402
from jobagent.storage.db import Database  # noqa: E402

SERIES = "#2a78d6"          # single-series hue (validated reference palette, slot 1)
CATEGORY_ORDER = ["Strong match", "Potential match", "Stretch opportunity", "Low priority"]

st.set_page_config(page_title="Job Search Agent", layout="wide")
settings = load_settings()
db = Database(settings.path(settings.storage.db_path))


def existing(value) -> Path | None:
    """pandas stores missing paths as NaN; return a Path only for a real, existing file."""
    return Path(value) if isinstance(value, str) and value and Path(value).exists() else None


def txt(value, default: str = "?") -> str:
    return default if value is None or (isinstance(value, float) and pd.isna(value)) or value == "" else str(value)


def bar(counts: pd.Series, title: str, horizontal: bool = True, order: list[str] | None = None):
    """Single-series count bar chart: one hue, direct value labels, count axis, hover shows count and %."""
    df = counts.rename_axis("label").reset_index(name="count")
    if order:
        df["label"] = pd.Categorical(df["label"], categories=[o for o in order if o in set(df["label"])], ordered=True)
        df = df.sort_values("label")
    total = df["count"].sum()
    df["pct"] = (100 * df["count"] / total).round(1) if total else 0
    kw = dict(x="count", y="label", orientation="h") if horizontal else dict(x="label", y="count")
    fig = px.bar(df, text="count", custom_data=["pct"], **kw)
    fig.update_traces(marker_color=SERIES, marker_line_width=0, textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}: %{x} jobs (%{customdata[0]}% of shown)<extra></extra>" if horizontal
                      else "%{x}: %{y} jobs (%{customdata[0]}% of shown)<extra></extra>")
    fig.update_layout(title=dict(text=title, font=dict(size=14)), height=max(260, 28 * len(df) + 90) if horizontal else 300,
                      margin=dict(l=10, r=30, t=40, b=10), bargap=0.35, showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    axis_count = dict(title="Number of jobs", showgrid=True, gridcolor="rgba(128,128,128,0.15)", zeroline=False)
    axis_label = dict(title=None, showgrid=False)
    if horizontal:
        fig.update_xaxes(**axis_count)
        fig.update_yaxes(**axis_label, autorange="reversed")
    else:
        fig.update_yaxes(**axis_count)
        fig.update_xaxes(**axis_label)
    return fig


df = jobs_frame(db)
st.title("Job Search Dashboard")
if df.empty:
    st.info("No jobs yet. Import jobs with `python -m jobagent run` (see README).")
    st.stop()

seen = pd.to_datetime(df["first_seen"], errors="coerce", utc=True)
st.caption(f"Reporting period (jobs first seen): **{seen.min():%Y-%m-%d} – {seen.max():%Y-%m-%d}** · "
           f"Only jobs you imported are included (LinkedIn is not searched automatically), so this is not an exhaustive "
           f"view of the market. All figures are counts unless marked %.")

# ------------------------------------------------------------------ filters (one row, above everything)
f1, f2, f3, f4, f5, f6 = st.columns([1.3, 1, 1, 1, 1, 1])
analysed_scores = df["score"].dropna()
smin = f1.slider("Match score", 0, 100, (0, 100))
cities = f2.multiselect("Location", sorted(df["city"].dropna().unique()))
roles = f3.multiselect("Role", sorted(df["role_category"].dropna().unique()))
arrs = f4.multiselect("Arrangement", sorted(df["work_arrangement"].dropna().unique()))
companies = f5.multiselect("Company", sorted(df["company"].dropna().unique()))
statuses = f6.multiselect("Status", [s.value for s in JobStatus])

view = df.copy()
if smin != (0, 100):
    view = view[view["score"].between(*smin)]
for col, sel in (("city", cities), ("role_category", roles), ("work_arrangement", arrs), ("company", companies),
                 ("status", statuses)):
    if sel:
        view = view[view[col].isin(sel)]
analysed = view[view["score"].notna()]

# ------------------------------------------------------------------ KPI tiles
cat = analysed["category"].value_counts()
k = st.columns(9)
k[0].metric("Sightings (all imports)", int(db.q1("SELECT COUNT(*) n FROM job_sightings")["n"]))
k[1].metric("Unique jobs", len(view))
k[2].metric("Analysed", len(analysed))
k[3].metric("Strong", int(cat.get("Strong match", 0)))
k[4].metric("Potential", int(cat.get("Potential match", 0)))
k[5].metric("Stretch", int(cat.get("Stretch opportunity", 0)))
k[6].metric("Low priority", int(cat.get("Low priority", 0)))
k[7].metric("Resumes generated", int(view["resume_status"].notna().sum()))
k[8].metric("Awaiting review", int(view["status"].isin(["shortlisted", "resume_generated"]).sum()))
needs = int(view["data_quality"].isin(["needs_manual_review", "failed"]).sum())
if needs:
    st.warning(f"{needs} job(s) have only a URL. Add their descriptions with `python -m jobagent add-details <id> <file>`.")

# ------------------------------------------------------------------ charts
tab_charts, tab_table, tab_detail, tab_export = st.tabs(["Charts", "Jobs table", "Job detail", "Exports"])
with tab_charts:
    if analysed.empty:
        st.info("No analysed jobs match the filters.")
    else:
        c1, c2 = st.columns(2)
        c1.plotly_chart(bar(analysed["category"].value_counts(), "Jobs by match category", order=CATEGORY_ORDER),
                        use_container_width=True)
        c2.plotly_chart(bar(view["work_arrangement"].fillna("unknown").value_counts(), "Jobs by work arrangement"),
                        use_container_width=True)
        c1.plotly_chart(bar(view["city"].fillna("unknown").value_counts().head(12), "Jobs by location (top 12)"),
                        use_container_width=True)
        c2.plotly_chart(bar(view["role_category"].fillna("unknown").value_counts(), "Jobs by role category"),
                        use_container_width=True)
        c1.plotly_chart(bar(view["company"].fillna("unknown").value_counts().head(12), "Jobs by company (top 12)"),
                        use_container_width=True)
        skills = Counter()
        for r in analysed["_req"]:
            skills.update((r or {}).get("required_skills", []) + (r or {}).get("preferred_skills", []))
        if skills:
            c2.plotly_chart(bar(pd.Series(dict(skills.most_common(15))),
                                f"Most requested skills (top 15, across {len(analysed)} analysed jobs)"),
                            use_container_width=True)
        posted = pd.to_datetime(view["posted_at"], errors="coerce").dropna()
        if len(posted) >= 3:
            weekly = posted.dt.to_period("W").dt.start_time.value_counts().sort_index()
            weekly.index = weekly.index.strftime("%Y-%m-%d")
            st.plotly_chart(bar(weekly, f"Jobs by posting week ({len(posted)} of {len(view)} jobs have a posting date)",
                                horizontal=False), use_container_width=True)
        else:
            st.caption("Posting-date chart hidden: fewer than 3 jobs have a reliable posting date.")
        n = len(analysed)
        if n < settings.reporting.min_sample_for_trends:
            st.caption(f"⚠ Small sample ({n} analysed jobs): skill counts are anecdotal, not market trends.")

# ------------------------------------------------------------------ table
with tab_table:
    cols = ["job_id", "score", "title", "company", "location", "work_arrangement", "posted_at", "matching_skills",
            "missing_required", "eligibility_warnings", "recommendation", "status", "resume_status", "url"]
    st.dataframe(
        view.sort_values("score", ascending=False, na_position="last")[cols], hide_index=True, use_container_width=True,
        column_config={
            "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
            "url": st.column_config.LinkColumn("Posting", display_text="open"),
            "job_id": st.column_config.NumberColumn("ID", width="small"),
        })
    st.caption("Click a column header to sort. Use the filters above to narrow the list.")

# ------------------------------------------------------------------ detail
with tab_detail:
    options = view.sort_values("score", ascending=False, na_position="last")
    labels = {int(r.job_id): f"#{r.job_id} · {r.score:.0f} · {r.title} @ {r.company}" if pd.notna(r.score)
              else f"#{r.job_id} · (not analysed) · {r.title or r.url}" for r in options.itertuples()}
    jid = st.selectbox("Job", list(labels), format_func=labels.get)
    row = view[view["job_id"] == jid].iloc[0]
    res = row["_result"] or {}
    st.subheader(f"{row['title'] or '(no title)'} @ {row['company'] or '?'}")
    st.write(f"{txt(row['location'])} · {txt(row['work_arrangement'])} · {txt(row['employment_type'], 'type n/a')} · "
             f"posted {txt(row['posted_at'])} · status **{row['status']}** · data {row['data_quality']}")
    if row["url"]:
        st.markdown(f"[Open job posting]({row['url']})")
    if res:
        st.markdown(f"### {res['score']:.0f}/100 · {row['category']} · confidence {res['confidence']} → **{res['recommendation']}**")
        st.write(res["explanation"])
        for adj in res.get("adjustments", []):
            st.caption(f"Adjustment: {adj}")
        comp = pd.DataFrame(res["components"])
        comp["label"] = comp["name"].str.replace("_", " ") + " (" + comp["weight"].map("{:g}".format) + ")"
        fig = px.bar(comp, x="points", y="label", orientation="h", text="points", range_x=[0, max(comp["weight"].max(), 1) * 1.15])
        fig.update_traces(marker_color=SERIES, textposition="outside", cliponaxis=False,
                          hovertemplate="%{y}: %{x} points<extra></extra>")
        fig.update_layout(title="Points earned per component (max = weight in brackets)", height=280,
                          margin=dict(l=10, r=30, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        fig.update_yaxes(title=None, autorange="reversed")
        fig.update_xaxes(title="Points", gridcolor="rgba(128,128,128,0.15)")
        st.plotly_chart(fig, use_container_width=True)
        a, b = st.columns(2)
        with a:
            st.markdown("**Hard constraints**")
            for h in res.get("hard_constraints", []):
                icon = {"pass": "✅", "fail": "⛔", "unknown": "⚠️"}[h["status"]]
                st.write(f"{icon} {h['status']}: {h['name']}: {h['detail']}")
            for key, label in (("strengths", "Strengths"), ("reasons_to_apply", "Reasons to apply")):
                if res.get(key):
                    st.markdown(f"**{label}**")
                    st.write("\n".join(f"- {x}" for x in res[key]))
        with b:
            for key, label in (("missing_required", "Missing required"), ("missing_preferred", "Missing preferred"),
                               ("transferable", "Transferable"), ("reasons_not_to_apply", "Reasons not to apply")):
                if res.get(key):
                    st.markdown(f"**{label}**")
                    st.write("\n".join(f"- {x}" for x in res[key]))
        with st.expander("Scoring evidence"):
            for c in res["components"]:
                st.markdown(f"**{c['name']}**: {c['score']:.2f} × {c['weight']:g} = {c['points']}")
                st.text("\n".join(c["evidence"]))
    else:
        st.info("Not analysed yet" + (": this job needs a description (add-details)." if row["data_quality"] in
                                      ("needs_manual_review", "failed") else "."))

    st.markdown("### Resume")
    docx, pdf = existing(row["resume_docx"]), existing(row["resume_pdf"])
    if docx:
        st.write(f"Status: **{row['resume_status']}**" + ("" if row["resume_status"] == "ready" else
                                                          " (validation failed; see the tailoring report)"))
        d1, d2, d3 = st.columns(3)
        d1.download_button("Download DOCX", docx.read_bytes(), file_name=docx.name)
        if pdf:
            d2.download_button("Download PDF", pdf.read_bytes(), file_name=pdf.name)
        rep = db.latest_resume(int(jid))
        if rep and rep["report_path"] and Path(rep["report_path"]).exists():
            with st.expander("Tailoring & validation report"):
                st.markdown(Path(rep["report_path"]).read_text(encoding="utf-8"))
    elif res:
        if st.button("Generate tailored resume"):
            from jobagent.profile.store import ProfileNotReady, require_reviewed
            from jobagent.resume.service import ResumeService
            from jobagent.taxonomy import load_taxonomy
            try:
                profile = require_reviewed(settings.path(settings.profile.candidate_profile_path))
                out = ResumeService(settings, db, load_taxonomy(), profile).generate(int(jid))
                st.success(f"Resume {out.status}: {out.docx_path}")
                st.rerun()
            except (ProfileNotReady, ValueError) as exc:
                st.error(str(exc))

    st.markdown("### Record your decision")
    st.caption("This only updates your local tracking. Nothing is sent or submitted.")
    s1, s2, s3, s4 = st.columns(4)
    for col, status, label in ((s1, JobStatus.REVIEWED, "Mark reviewed"), (s2, JobStatus.APPLIED, "I applied (manually)"),
                               (s3, JobStatus.REJECTED, "Not interested"), (s4, JobStatus.CLOSED, "Posting closed")):
        if col.button(label, key=f"{status.value}-{jid}"):
            with db.tx():
                db.set_status(int(jid), status, "set from dashboard")
                if status == JobStatus.CLOSED:
                    db.update_job(int(jid), {"availability": "closed"})
            st.rerun()

# ------------------------------------------------------------------ exports
with tab_export:
    st.write("Exports include all jobs in the database (filters above are not applied).")
    if st.button("Generate CSV / Excel / summary reports"):
        paths = generate_reports(settings, db)
        st.session_state["paths"] = {k: str(v) for k, v in paths.items()}
    for k, v in st.session_state.get("paths", {}).items():
        st.download_button(f"Download {k}", Path(v).read_bytes(), file_name=Path(v).name, key=k)
    gaps = skill_gap_frame(df)
    st.markdown(f"**Skill-gap analysis** ({int(df['score'].notna().sum())} analysed jobs)")
    st.dataframe(gaps, hide_index=True, use_container_width=True)
