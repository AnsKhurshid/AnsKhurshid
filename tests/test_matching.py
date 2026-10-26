import pytest

from jobagent.ai.client import AIClient, AIError, AIProvider, Usage
from jobagent.matching.analyzer import AIJobAnalysis, Analyzer, EvidencePair
from jobagent.matching.requirements import extract_requirements
from jobagent.matching.scoring import score_job
from tests.conftest import job_id_by_source_id


def _score(settings, taxonomy, profile, title, description, **job):
    req = extract_requirements(description, title, taxonomy)
    j = {"title": title, "work_arrangement": "hybrid", "city": "Lahore", "country": "Pakistan",
         "location": "Lahore, Pakistan"} | job
    return score_job(j, description, req, profile, taxonomy, settings), req


def test_requirements_split_required_and_preferred(taxonomy, jobs_json):
    j = next(x for x in jobs_json if x["id"] == "J-1001")
    req = extract_requirements(j["description"], j["title"], taxonomy)
    assert {"Python", "SQL", "PostgreSQL", "AWS Step Functions"} <= set(req.required_skills)
    assert {"Apache Airflow", "dbt", "Amazon Redshift"} <= set(req.preferred_skills)
    assert req.min_years == 2


def test_location_restrictions_detected(taxonomy, jobs_json):
    us = next(x for x in jobs_json if x["id"] == "J-1004")
    pk = next(x for x in jobs_json if x["id"] == "J-1005")
    assert extract_requirements(us["description"], us["title"], taxonomy).remote_eligibility == "region_restricted"
    assert extract_requirements(pk["description"], pk["title"], taxonomy).remote_eligibility == "pakistan_ok"


def test_ranking_matches_career_direction(settings, taxonomy, profile, loaded_db):
    an = Analyzer(settings, loaded_db, taxonomy, profile)
    an.analyze()
    score = lambda sid: loaded_db.latest_analysis(job_id_by_source_id(loaded_db, sid))["result"]
    de, analyst, scientist = score("J-1001"), score("J-1003"), score("J-1007")
    assert de["category"] == "strong" and de["recommendation"] == "apply"
    assert analyst["score"] < 50 and analyst["adjustments"], "analyst roles must not ride on shared SQL keywords"
    assert scientist["score"] < analyst["score"] + 5
    us_remote = score("J-1004")
    assert us_remote["eligible"] is False and us_remote["recommendation"] == "skip"
    pk_remote = score("J-1005")
    assert pk_remote["eligible"] is True and pk_remote["category"] in ("strong", "potential")


def test_hard_constraints_are_not_hidden_by_high_score(settings, taxonomy, profile, loaded_db):
    Analyzer(settings, loaded_db, taxonomy, profile).analyze()
    jid = job_id_by_source_id(loaded_db, "J-1008")       # requires an AWS certification
    a = loaded_db.latest_analysis(jid)
    assert a["result"]["eligible"] is False and a["result"]["recommendation"] == "review_eligibility"
    assert loaded_db.job(jid)["status"] != "shortlisted"


def test_missing_preferred_skill_is_not_a_rejection(settings, taxonomy, profile):
    base = ("Responsibilities:\n- Build ETL pipelines in Python and SQL on AWS Lambda\n"
            "Requirements:\n- 2+ years of data engineering experience\n- Python, SQL, PostgreSQL\n")
    with_pref, _ = _score(settings, taxonomy, profile, "Data Engineer", base + "Nice to have:\n- Apache Kafka\n")
    assert with_pref.eligible and "Apache Kafka" in with_pref.missing_preferred
    assert with_pref.category in ("strong", "potential")


def test_keyword_repetition_does_not_inflate_score(settings, taxonomy, profile):
    desc = "Requirements:\n- Python and SQL\n- Experience with Apache Spark\n- 2+ years of experience"
    once, _ = _score(settings, taxonomy, profile, "Data Engineer", desc)
    spam, _ = _score(settings, taxonomy, profile, "Data Engineer", desc + "\n- Python Python Python SQL SQL Python")
    assert spam.score == pytest.approx(once.score, abs=0.5)


def test_seniority_gap_is_penalised(settings, taxonomy, profile):
    desc = "Requirements:\n- 7+ years of experience in data engineering\n- Python, SQL"
    r, _ = _score(settings, taxonomy, profile, "Senior Data Engineer", desc)
    seniority = next(c for c in r.components if c.name == "seniority")
    assert seniority.score <= 0.3 and any("Experience gap" in x for x in r.reasons_not_to_apply)


def test_score_breakdown_is_traceable(settings, taxonomy, profile):
    desc = "Requirements:\n- Python, SQL, AWS Lambda\n- 2+ years of experience"
    r, _ = _score(settings, taxonomy, profile, "Data Engineer", desc)
    assert sum(c.points for c in r.components) == pytest.approx(r.raw_score, abs=0.2)
    assert any("Python: professional" in e for e in r.components[0].evidence)


# ---------------------------------------------------------------- AI layer with a fake provider
class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, result=None, error=None):
        self.calls = 0
        self.result, self.error = result, error

    def structured(self, system, user, schema):
        self.calls += 1
        assert "sample.candidate@example.com" not in user, "contact details must not be sent to AI"
        if self.error:
            raise self.error
        return self.result, Usage(1000, 200, "fake-model")


def _ai_result(evidence_line):
    return AIJobAnalysis(
        responsibilities_alignment=0.9,
        evidence=[EvidencePair(job_requirement="Build pipelines", resume_evidence=evidence_line),
                  EvidencePair(job_requirement="Kafka streaming", resume_evidence="Built Kafka streaming at Google scale")],
        additional_required_skills=["Docker"],
        eligibility_concerns=["Role may require working UK hours"],
        reasons_to_apply=["Good AWS fit"], reasons_not_to_apply=[], summary="Solid fit.")


def test_ai_evidence_is_verified_and_cached(settings, taxonomy, profile, loaded_db):
    settings.ai.input_cost_per_mtok, settings.ai.output_cost_per_mtok = 4.0, 20.0
    line = profile.experience[0].bullets[0]
    fake = FakeProvider(result=_ai_result(line))
    ai = AIClient(settings, loaded_db, provider=fake)
    an = Analyzer(settings, loaded_db, taxonomy, profile, ai=ai)
    jid = job_id_by_source_id(loaded_db, "J-1005")
    r = an.analyze_job(jid)
    assert r.ai_used
    resp = next(c for c in r.components if c.name == "responsibilities")
    assert any("1 AI evidence claim(s) dropped" in e for e in resp.evidence)       # the invented Kafka claim
    assert "Docker" in extract_requirements(loaded_db.description(jid)[0], "x", taxonomy).preferred_skills
    assert r.eligible, "an AI concern alone can never fail eligibility"
    assert any(c.name == "AI flag" and c.status == "unknown" for c in r.hard_constraints)
    an.analyze_job(jid, force=True)
    assert fake.calls == 1, "second analysis must come from the cache"
    usage = loaded_db.ai_usage()
    assert usage["calls"] == 2 and usage["cached"] == 1 and usage["cost_usd"] == pytest.approx(0.008)


def test_ai_failure_falls_back_to_deterministic(settings, taxonomy, profile, loaded_db):
    ai = AIClient(settings, loaded_db, provider=FakeProvider(error=AIError("overloaded")))
    r = Analyzer(settings, loaded_db, taxonomy, profile, ai=ai).analyze_job(job_id_by_source_id(loaded_db, "J-1001"))
    assert not r.ai_used and "AI analysis unavailable" in r.explanation
    assert loaded_db.ai_usage()["errors"] == 1


def test_ai_unavailable_without_key(settings, db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings.ai.provider = "anthropic"
    ai = AIClient(settings, db)
    assert not ai.available and "API key" in ai.reason_unavailable


def test_failed_analysis_is_tracked_and_retryable(settings, taxonomy, profile, loaded_db, monkeypatch):
    run_id = loaded_db.start_run("analyze")
    an = Analyzer(settings, loaded_db, taxonomy, profile, run_id=run_id)
    target = job_id_by_source_id(loaded_db, "J-1006")
    real = an.analyze_job

    def flaky(job_id, force=False):
        if job_id == target:
            raise RuntimeError("transient parse error")
        return real(job_id, force)

    monkeypatch.setattr(an, "analyze_job", flaky)
    stats = an.analyze()
    assert stats.failed == 1 and stats.analyzed >= 9
    assert [t["job_id"] for t in loaded_db.failed_tasks("analyze")] == [target]
    run2 = loaded_db.start_run("retry")
    an2 = Analyzer(settings, loaded_db, taxonomy, profile, run_id=run2)
    assert an2.analyze(job_ids=[target], force=True).analyzed == 1
    assert loaded_db.failed_tasks("analyze") == []


def test_reanalysis_skips_unchanged_jobs(settings, taxonomy, profile, loaded_db):
    an = Analyzer(settings, loaded_db, taxonomy, profile)
    first = an.analyze()
    second = an.analyze()
    assert first.analyzed > 0 and second.analyzed == 0 and second.skipped_current == first.analyzed


def test_user_decisions_survive_reanalysis(settings, taxonomy, profile, loaded_db):
    an = Analyzer(settings, loaded_db, taxonomy, profile)
    an.analyze()
    jid = job_id_by_source_id(loaded_db, "J-1001")
    with loaded_db.tx():
        loaded_db.set_status(jid, "applied", "applied manually")
    an.analyze(force=True)
    assert loaded_db.job(jid)["status"] == "applied"
