from unittest.mock import MagicMock

import pytest

from jobagent.ingestion.normalize import (canonicalize_url, detect_work_arrangement, normalize_company,
                                          parse_location, parse_salary, role_category)
from jobagent.ingestion.pipeline import ingest, upsert_job
from jobagent.models import RawJob, RetrievalStatus, SourceResult
from jobagent.sources.base import CollectRequest
from jobagent.sources.linkedin import LinkedInSource, build_search_urls, linkedin_job_id
from jobagent.sources.manual import ManualSource
from jobagent.sources.url_fetch import Fetcher, FetchRefused
from tests.conftest import JOBS


@pytest.mark.parametrize("url,expected", [
    ("https://www.linkedin.com/jobs/view/3999999999/?trackingId=x&refId=y", "3999999999"),
    ("https://www.linkedin.com/jobs/view/sql-data-engineer-at-acme-3777777777", "3777777777"),
    ("https://www.linkedin.com/jobs/search/?currentJobId=3888888888&keywords=x", "3888888888"),
    ("https://example.com/jobs/123", None),
])
def test_linkedin_job_ids(url, expected):
    assert linkedin_job_id(url) == expected


def test_url_canonicalisation_strips_tracking_but_keeps_ids():
    assert canonicalize_url("https://Jobs.Example.com/p/1?utm_source=li&gh_jid=42&fbclid=z#apply") == \
        "https://jobs.example.com/p/1?gh_jid=42"
    assert canonicalize_url("https://boards.example.com/job?id=7&trk=abc") == "https://boards.example.com/job?id=7"


def test_normalisers():
    assert normalize_company("Indus Data Systems (Pvt) Ltd") == normalize_company("Indus Data Systems Pvt. Ltd.")
    assert parse_location("Karachi, Sindh, Pakistan") == ("Karachi", "Pakistan")
    assert parse_location("Isb") == ("Islamabad", "Pakistan")
    assert detect_work_arrangement(None, "Data Engineer (Remote)", None, None) == "remote"
    assert detect_work_arrangement(None, "Data Engineer", "Rawalpindi (Hybrid)", None) == "hybrid"
    assert parse_salary("Salary: PKR 250,000 - 350,000 per month") == (250000, 350000, "PKR", "month")
    assert role_category("Sr. ETL Developer (SSIS)") == "etl_developer"
    assert role_category("Business Data Analyst") == "data_analyst"


def test_linkedin_connector_parses_saved_pages_text_and_urls(settings):
    res = LinkedInSource(settings).collect(CollectRequest(
        files=[JOBS / "linkedin_saved_jsonld.html", JOBS / "linkedin_saved_layout.html", JOBS / "linkedin_urls.txt",
               JOBS / "pasted_job.txt"], use_inbox=False))
    by_id = {j.source_job_id: j for j in res.jobs}
    jl = by_id["4012345678"]
    assert (jl.title, jl.company, jl.retrieval_status) == ("Analytics Engineer", "Example Retail Group", RetrievalStatus.COMPLETE)
    assert "Karachi" in jl.location and str(jl.posted_at) == "2026-10-21"
    lay = by_id["4098765432"]
    assert lay.company == "Example Logistics" and "Kafka" in lay.description
    assert by_id["3888888888"].retrieval_status == RetrievalStatus.NEEDS_MANUAL_REVIEW
    assert by_id["3666666666"].title == "Python Data Engineer"
    assert res.exhaustive is False and res.notes


def test_search_links_are_pakistan_first(settings):
    links = build_search_urls(settings)
    assert len(links) == 2 * len(settings.search.preferred_titles)
    assert all("geoId=101022442" in l["url"] for l in links)


def test_manual_csv_import(settings, tmp_path):
    p = tmp_path / "jobs.csv"
    p.write_text("Job Title,Company Name,Location,Description,Link\nETL Engineer,Acme,Lahore,"
                 "\"Build ETL pipelines with SSIS. Requirements: 2+ years\",https://acme.example/j/1?utm_source=x\n")
    res = ManualSource(settings).collect(CollectRequest(files=[p], use_inbox=False))
    assert res.jobs[0].title == "ETL Engineer" and res.jobs[0].url.startswith("https://acme.example")


def test_fetcher_never_fetches_linkedin_and_honours_robots(settings):
    session = MagicMock()
    f = Fetcher(settings.sources.url_fetch, session=session)
    with pytest.raises(FetchRefused):
        f.get("https://www.linkedin.com/jobs/view/123/")
    session.get.assert_not_called()
    session.get.return_value = MagicMock(status_code=200, text="User-agent: *\nDisallow: /jobs/")
    ok, why = f.allowed("https://careers.example.com/jobs/1")
    assert not ok and "robots" in why


def test_manual_url_refusal_becomes_manual_review_stub(settings):
    src = ManualSource(settings, fetcher=Fetcher(settings.sources.url_fetch, session=MagicMock()))
    job, err = src.fetch_url("https://www.indeed.com/viewjob?jk=1")
    assert job.retrieval_status == RetrievalStatus.NEEDS_MANUAL_REVIEW and err is None


def test_ingestion_is_idempotent(loaded_db, settings):
    n_jobs = loaded_db.q1("SELECT COUNT(*) n FROM jobs")["n"]
    n_desc = loaded_db.q1("SELECT COUNT(*) n FROM job_descriptions")["n"]
    li = LinkedInSource(settings).collect(CollectRequest(files=[JOBS / "linkedin_urls.txt"], use_inbox=False))
    ma = ManualSource(settings).collect(CollectRequest(files=[JOBS / "jobs.json"], use_inbox=False))
    stats = ingest(loaded_db, [li, ma], None)
    assert stats.inserted == 0
    assert loaded_db.q1("SELECT COUNT(*) n FROM jobs")["n"] == n_jobs == 14
    assert loaded_db.q1("SELECT COUNT(*) n FROM job_descriptions")["n"] == n_desc


def _raw(**kw):
    base = dict(source="manual", title="Data Engineer", company="Acme", location="Lahore, Pakistan",
                description="Build pipelines with Python and SQL. " * 30, retrieval_status=RetrievalStatus.COMPLETE)
    base.update(kw)
    return RawJob(**base)


def test_repost_without_url_dedupes_by_company_title_and_description(db):
    a, _ = upsert_job(db, _raw(source_job_id="1"), None)
    b, outcome = upsert_job(db, _raw(source_job_id="2", company="Acme Pvt Ltd"), None)
    assert a == b and outcome in ("duplicate", "updated")


def test_same_title_other_city_is_a_different_job(db):
    a, _ = upsert_job(db, _raw(), None)
    b, _ = upsert_job(db, _raw(location="Karachi, Pakistan"), None)
    assert a != b


def test_merge_fills_missing_fields_and_upgrades_retrieval(db):
    stub = RawJob(source="linkedin", source_job_id="555", url="https://www.linkedin.com/jobs/view/555/",
                  retrieval_status=RetrievalStatus.NEEDS_MANUAL_REVIEW)
    a, _ = upsert_job(db, stub, None)
    b, outcome = upsert_job(db, _raw(source="linkedin", source_job_id="555"), None)
    job = db.job(a)
    assert a == b and outcome == "updated"
    assert job["title"] == "Data Engineer" and job["retrieval_status"] == "complete"
    assert len(db.status_history(a)) == 1   # history preserved, no duplicate record


def test_bad_record_does_not_abort_batch(db, monkeypatch):
    import jobagent.ingestion.pipeline as pl
    real = pl.upsert_job

    def boom(db_, raw, run_id):
        if raw.title == "BAD":
            raise RuntimeError("corrupt")
        return real(db_, raw, run_id)

    monkeypatch.setattr(pl, "upsert_job", boom)
    stats = ingest(db, [SourceResult(source="manual", jobs=[_raw(title="BAD"), _raw()])], None)
    assert stats.inserted == 1 and len(stats.errors) == 1
