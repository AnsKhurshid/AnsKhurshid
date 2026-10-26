from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from jobagent.config import PROJECT_ROOT, load_settings
from jobagent.ingestion.pipeline import ingest
from jobagent.profile.store import approve, extract_to_file
from jobagent.sources.base import CollectRequest
from jobagent.sources.linkedin import LinkedInSource
from jobagent.sources.manual import ManualSource
from jobagent.storage.db import Database
from jobagent.taxonomy import load_taxonomy
from tests.fixtures.sample_resume import build_sample_resume

FIX = Path(__file__).parent / "fixtures"
JOBS = FIX / "jobs"


@pytest.fixture
def taxonomy():
    return load_taxonomy()


@pytest.fixture
def settings(tmp_path):
    cfg = yaml.safe_load((PROJECT_ROOT / "config" / "settings.yaml").read_text())
    cfg["profile"] = {"master_resume_path": str(tmp_path / "resume" / "master.docx"),
                      "candidate_profile_path": str(tmp_path / "profile" / "profile.yaml")}
    cfg["sources"]["linkedin"]["inbox_dir"] = str(tmp_path / "inbox" / "linkedin")
    cfg["sources"]["manual"]["inbox_dir"] = str(tmp_path / "inbox" / "manual")
    cfg["resume"]["output_dir"] = str(tmp_path / "resumes")
    cfg["resume"]["generate_pdf"] = False   # PDF conversion is tested separately (slow)
    cfg["reporting"]["output_dir"] = str(tmp_path / "reports")
    cfg["storage"]["db_path"] = str(tmp_path / "db.sqlite")
    cfg["logging"]["dir"] = str(tmp_path / "logs")
    cfg["ai"]["provider"] = "none"
    cfg["search"]["candidate_experience_years"] = 2.5   # pin: the fixture resume says "Present"
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return load_settings(path)


@pytest.fixture
def config_path(settings, tmp_path):
    return tmp_path / "settings.yaml"


@pytest.fixture
def db(settings):
    d = Database(settings.path(settings.storage.db_path))
    yield d
    d.close()


@pytest.fixture
def master_resume(settings):
    return build_sample_resume(settings.path(settings.profile.master_resume_path))


def reviewed_profile_file(settings, taxonomy, master_resume):
    """Extract, apply the same corrections a user would make, approve."""
    ppath = settings.path(settings.profile.candidate_profile_path)
    extract_to_file(master_resume, ppath, taxonomy)
    data = yaml.safe_load(ppath.read_text())
    for s in data["skills"]:
        if s["name"] == "Git":
            s["level"] = "professional"
        if s["name"] == "Tableau":
            s["level"] = "studied"
    data["total_experience_years"] = 2.5
    ppath.write_text(yaml.safe_dump(data, sort_keys=False))
    return approve(ppath)


@pytest.fixture
def profile(settings, taxonomy, master_resume):
    return reviewed_profile_file(settings, taxonomy, master_resume)


@pytest.fixture
def loaded_db(settings, db):
    li = LinkedInSource(settings).collect(CollectRequest(
        files=[JOBS / "linkedin_saved_jsonld.html", JOBS / "linkedin_saved_layout.html", JOBS / "linkedin_urls.txt",
               JOBS / "pasted_job.txt"], use_inbox=False))
    ma = ManualSource(settings).collect(CollectRequest(files=[JOBS / "jobs.json"], use_inbox=False))
    ingest(db, [li, ma], None)
    return db


def job_id_by_source_id(db, sid: str) -> int:
    return db.q1("SELECT job_id FROM job_sightings WHERE source_job_id=?", (sid,))["job_id"]


@pytest.fixture
def jobs_json():
    return json.loads((JOBS / "jobs.json").read_text())
