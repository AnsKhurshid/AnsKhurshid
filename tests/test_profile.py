import shutil
import subprocess

import pytest
import yaml

from jobagent.profile.extractor import total_experience_years
from jobagent.profile.parser import ResumeParseError, read_resume
from jobagent.profile.store import (ProfileNotReady, approve, extract_to_file, load_profile, profile_sha,
                                    require_reviewed)
from jobagent.models import Experience
from jobagent.utils.text import sha256


def test_extraction_separates_evidence_levels(settings, taxonomy, master_resume):
    ppath = settings.path(settings.profile.candidate_profile_path)
    prof, _ = extract_to_file(master_resume, ppath, taxonomy)
    levels = {s.name: s.level for s in prof.skills}
    assert levels["AWS Step Functions"] == "professional"
    assert levels["Apache Airflow"] == "project"         # portfolio only, never promoted
    assert levels["Tableau"] == "listed"                 # skills list only -> needs confirmation
    assert levels["Databricks"] == "studied"             # certification only
    assert [e.employer for e in prof.experience] == ["Example PropTech Ltd", "Sample Analytics Co", "Demo Software House"]
    assert prof.experience[0].start == "Jan 2023" and prof.experience[0].end == "Present"
    assert prof.education[0].degree == "BS Computer Science"
    assert any("40%" in a for a in prof.achievements)
    assert prof.unverified, "ambiguous items must be flagged for review"


def test_master_resume_is_never_modified(settings, taxonomy, master_resume):
    before = sha256(master_resume.read_bytes())
    extract_to_file(master_resume, settings.path(settings.profile.candidate_profile_path), taxonomy)
    assert sha256(master_resume.read_bytes()) == before


def test_approval_requires_resolving_listed_skills(settings, taxonomy, master_resume):
    ppath = settings.path(settings.profile.candidate_profile_path)
    extract_to_file(master_resume, ppath, taxonomy)
    with pytest.raises(ProfileNotReady, match="listed"):
        approve(ppath)
    with pytest.raises(ProfileNotReady, match="not been reviewed"):
        require_reviewed(ppath)


def test_reviewed_profile_is_not_overwritten(settings, taxonomy, master_resume, profile):
    ppath = settings.path(settings.profile.candidate_profile_path)
    _, target = extract_to_file(master_resume, ppath, taxonomy)
    assert target.name.endswith(".new.yaml")
    assert load_profile(ppath).reviewed


def test_profile_hash_ignores_review_timestamps(profile):
    other = profile.model_copy(update={"reviewed_at": None})
    assert profile_sha(other) == profile_sha(profile)
    changed = profile.model_copy(update={"total_experience_years": 9})
    assert profile_sha(changed) != profile_sha(profile)


def test_experience_years_merge_overlaps_and_skip_internships():
    exp = [Experience(employer="A", title="Data Engineer", start="Jan 2023", end="Dec 2023"),
           Experience(employer="B", title="ETL Developer", start="Jun 2023", end="Jun 2024"),
           Experience(employer="C", title="Data Intern", start="Jan 2022", end="Dec 2022")]
    assert total_experience_years(exp) == 1.5


def test_missing_and_unsupported_files(tmp_path):
    with pytest.raises(ResumeParseError):
        read_resume(tmp_path / "nope.docx")
    (tmp_path / "x.rtf").write_text("hello")
    with pytest.raises(ResumeParseError, match="unsupported"):
        read_resume(tmp_path / "x.rtf")


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_pdf_resume_parses_like_docx(tmp_path, taxonomy, master_resume):
    subprocess.run(["soffice", f"-env:UserInstallation=file://{tmp_path}/lo", "--headless", "--convert-to", "pdf",
                    "--outdir", str(tmp_path), str(master_resume)], check=True, capture_output=True, timeout=120)
    from jobagent.profile.extractor import extract_profile
    prof = extract_profile(read_resume(tmp_path / "master.pdf"), taxonomy)
    assert len(prof.experience) == 3
    assert {s.name for s in prof.skills if s.level == "professional"} >= {"Python", "SQL", "AWS Lambda"}
