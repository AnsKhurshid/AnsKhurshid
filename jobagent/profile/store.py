"""Persist the candidate profile as human-editable YAML and manage the review/approval cycle."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from jobagent.models import CandidateProfile
from jobagent.profile.extractor import extract_profile
from jobagent.profile.parser import read_resume
from jobagent.taxonomy import Taxonomy
from jobagent.utils.files import atomic_write_text
from jobagent.utils.text import sha256

HEADER = """\
# Candidate profile extracted from your master resume.
# REVIEW THIS FILE, correct anything wrong, then run:  python -m jobagent profile approve
#
# Skill levels:
#   professional = used in paid work (evidence from your experience section)
#   project      = demonstrated in a portfolio project only
#   listed       = appears in a skills list with no supporting context  -> please reclassify
#   studied      = coursework / certification / exploration only (never presented as experience)
# Project kinds: professional | portfolio | learning
# `unverified` lists items the extractor was unsure about; delete each line once resolved.
# Matching treats only this file as truth; tailored resumes never claim more than it states.
"""


class ProfileNotReady(Exception):
    pass


def profile_sha(profile: CandidateProfile) -> str:
    """Content hash that changes when anything relevant to matching/tailoring changes."""
    return sha256(profile.model_dump(mode="json", exclude={"reviewed", "reviewed_at", "extracted_at"}))[:16]


def save_profile(profile: CandidateProfile, path: Path) -> None:
    body = yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=110)
    atomic_write_text(path, HEADER + "\n" + body)


def load_profile(path: Path) -> CandidateProfile:
    if not path.exists():
        raise ProfileNotReady(f"no candidate profile at {path}; run `python -m jobagent profile extract`")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return CandidateProfile.model_validate(data)


def extract_to_file(resume_path: Path, profile_path: Path, taxonomy: Taxonomy, force: bool = False) -> tuple[CandidateProfile, Path]:
    """Extract a profile. Never overwrites a reviewed profile unless forced; writes *.new.yaml instead."""
    lines = read_resume(resume_path)
    resume_sha = sha256(resume_path.read_bytes())
    profile = extract_profile(lines, taxonomy, resume_sha=resume_sha)
    target = profile_path
    if profile_path.exists() and not force:
        try:
            existing = load_profile(profile_path)
        except Exception:
            existing = None
        if existing and existing.reviewed:
            target = profile_path.with_suffix(".new.yaml")
    save_profile(profile, target)
    return profile, target


def approve(profile_path: Path) -> CandidateProfile:
    profile = load_profile(profile_path)  # validates schema
    problems = review_problems(profile)
    if problems:
        raise ProfileNotReady("profile still has issues:\n  - " + "\n  - ".join(problems))
    profile.reviewed = True
    profile.reviewed_at = datetime.now(timezone.utc)
    save_profile(profile, profile_path)
    return profile


def review_problems(profile: CandidateProfile) -> list[str]:
    """Blocking issues that must be fixed before the profile can be approved."""
    problems = []
    for e in profile.experience:
        if "UNKNOWN" in e.employer or "UNKNOWN" in e.title:
            problems.append(f"experience entry with unknown employer/title: {e.employer} / {e.title}")
        if not e.start:
            problems.append(f"experience at {e.employer} has no start date")
    if not profile.experience:
        problems.append("no work experience entries")
    if profile.total_experience_years is None:
        problems.append("total_experience_years is not set")
    listed = [s.name for s in profile.skills if s.level == "listed"]
    if listed:
        problems.append("skills still at level 'listed' (reclassify as professional/project/studied): "
                        + ", ".join(listed))
    return problems


def require_reviewed(path: Path) -> CandidateProfile:
    profile = load_profile(path)
    if not profile.reviewed:
        raise ProfileNotReady(
            "the candidate profile has not been reviewed yet. Edit it, then run `python -m jobagent profile approve`.")
    return profile
