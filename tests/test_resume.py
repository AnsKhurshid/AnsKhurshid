import shutil
from pathlib import Path

import pytest

from jobagent.ai.client import AIClient, AIProvider, Usage
from jobagent.matching.analyzer import Analyzer
from jobagent.resume.docx_writer import docx_text
from jobagent.resume.service import BulletRewrite, BulletRewrites, ResumeService
from jobagent.resume.validator import validate_resume
from jobagent.utils.text import sha256
from tests.conftest import job_id_by_source_id


@pytest.fixture
def analysed(settings, taxonomy, profile, loaded_db):
    Analyzer(settings, loaded_db, taxonomy, profile).analyze()
    return loaded_db


def _generate(settings, db, taxonomy, profile, sid, **kw):
    svc = ResumeService(settings, db, taxonomy, profile, **kw)
    jid = job_id_by_source_id(db, sid)
    return svc, jid, svc.generate(jid)


def test_tailored_resume_is_ready_and_factual(settings, taxonomy, profile, analysed, master_resume):
    before = sha256(master_resume.read_bytes())
    svc, jid, out = _generate(settings, analysed, taxonomy, profile, "J-1001")
    assert out.status == "ready", out.issues
    text = docx_text(Path(out.docx_path).read_bytes())
    for e in profile.experience:                       # every role kept with exact titles/dates
        assert e.employer in text and e.title in text and e.start in text
    assert "Snowflake" not in text and "dbt" not in text  # job wants them, profile lacks them
    assert "Project experience: " in text and "Apache Airflow" in text.split("Project experience: ")[1].split("\n")[0]
    assert sha256(master_resume.read_bytes()) == before
    assert analysed.job(jid)["status"] == "resume_generated"
    report = Path(out.report_path).read_text()
    assert "NOT supported" in report and "dbt" in report
    assert Path(out.docx_path).name == "Indus_Data_Systems_Pvt_Ltd_Data_Engineer_J{}_Resume.docx".format(jid)


def test_generation_is_idempotent(settings, taxonomy, profile, analysed):
    svc, jid, first = _generate(settings, analysed, taxonomy, profile, "J-1006")
    again = svc.generate(jid)
    assert again.reused and again.docx_path == first.docx_path
    assert analysed.q1("SELECT COUNT(*) n FROM resumes WHERE job_id=?", (jid,))["n"] == 1
    files = list(Path(first.docx_path).parent.iterdir())
    svc.generate(jid, force=True)
    assert sorted(Path(first.docx_path).parent.iterdir()) == sorted(files)


def test_tailoring_differs_by_job(settings, taxonomy, profile, analysed):
    _, _, de = _generate(settings, analysed, taxonomy, profile, "J-1001")
    _, _, etl = _generate(settings, analysed, taxonomy, profile, "J-1006")
    a, b = (docx_text(Path(o.docx_path).read_bytes()) for o in (de, etl))
    assert a != b
    assert "SSIS" in b.split("PROFESSIONAL SUMMARY")[1].split("TECHNICAL SKILLS")[0] or \
           b.index("SSIS") < a.index("SSIS")


def _resume(settings, taxonomy, profile, analysed):
    from jobagent.models import JobRequirements, MatchResult
    from jobagent.resume.tailor import Tailor
    jid = job_id_by_source_id(analysed, "J-1001")
    a = analysed.latest_analysis(jid)
    return Tailor(profile, taxonomy).build(analysed.job(jid), analysed.description(jid)[0],
                                           JobRequirements.model_validate(a["requirements"]),
                                           MatchResult.model_validate(a["result"]))[0]


@pytest.mark.parametrize("tamper,expected", [
    (lambda r: setattr(r.experience[0].bullets[0], "text", r.experience[0].bullets[0].text + " Cut costs by 75%."),
     "number not found"),
    (lambda r: setattr(r.experience[0], "employer", "Google"), "role not in profile"),
    (lambda r: setattr(r.experience[0], "end", "Dec 2025"), "role not in profile"),
    (lambda r: r.experience.pop(), "missing in resume"),
    (lambda r: setattr(r, "summary", r.summary + " Expert in Snowflake."), "skill without evidence"),
    (lambda r: setattr(r, "summary", r.summary + " Production experience with Apache Airflow."), "summary presents"),
    (lambda r: setattr(r, "summary", r.summary.replace("4+", "9+").replace("2+", "9+")), "claims"),
    (lambda r: setattr(r, "summary", r.summary + " [Insert company name]"), "placeholder"),
    (lambda r: r.experience[0].bullets.append(r.experience[0].bullets[0]), "duplicate"),
])
def test_validator_catches_fabrication(settings, taxonomy, profile, analysed, tamper, expected):
    r = _resume(settings, taxonomy, profile, analysed)
    assert validate_resume(r, profile, taxonomy).passed
    tamper(r)
    rep = validate_resume(r, profile, taxonomy)
    assert not rep.passed and any(expected in e for e in rep.errors), rep.errors


class RewriteProvider(AIProvider):
    name = "fake"

    def structured(self, system, user, schema):
        bullets = [ln[2:] for ln in user.split("BULLETS:\n")[1].splitlines() if ln.startswith("- ")]
        out = []
        for b in bullets:
            if "40%" in b:
                out.append(BulletRewrite(original=b, rewritten="Tuned PostgreSQL queries, cutting runtime by 60% and saving $1M."))
            elif "RETS" in b:
                out.append(BulletRewrite(original=b, rewritten=b.replace("Maintain", "Build and maintain") + " using Snowflake"))
            else:
                out.append(BulletRewrite(original=b, rewritten="Delivered: " + b))
        return BulletRewrites(bullets=out), Usage(10, 10, "fake")


def test_ai_rewrites_that_add_facts_are_reverted(settings, taxonomy, profile, analysed):
    settings.resume.ai_rewrite_bullets = True
    ai = AIClient(settings, analysed, provider=RewriteProvider())
    svc, jid, out = _generate(settings, analysed, taxonomy, profile, "J-1005", ai=ai)
    assert out.status == "ready", out.issues
    text = docx_text(Path(out.docx_path).read_bytes())
    assert "60%" not in text and "$1M" not in text and "Snowflake" not in text
    assert "40%" in text and "Delivered: " in text
    rec = analysed.latest_resume(jid)
    import json
    changes = json.loads(rec["changes_json"])
    assert len(changes["reverted_rewrites"]) == 2 and changes["rewritten_bullets"]


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_pdf_generated_when_available(settings, taxonomy, profile, analysed):
    settings.resume.generate_pdf = True
    _, _, out = _generate(settings, analysed, taxonomy, profile, "J-1001")
    assert out.pdf_path and Path(out.pdf_path).stat().st_size > 1000


def test_unanalysed_job_cannot_be_tailored(settings, taxonomy, profile, loaded_db):
    svc = ResumeService(settings, loaded_db, taxonomy, profile)
    with pytest.raises(ValueError, match="not been analysed"):
        svc.generate(job_id_by_source_id(loaded_db, "3888888888"))
