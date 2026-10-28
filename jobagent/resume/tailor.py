"""Deterministic resume tailoring: select, order and summarise verified content for one job.

Nothing is invented: bullets are the user's own (reordered / selected), skills come from the reviewed
profile, and the summary is filled only with verified facts.
"""
from __future__ import annotations

import math
import re

from jobagent.matching.scoring import CONCEPTS, LEVEL_RANK
from jobagent.models import CandidateProfile, JobRequirements, MatchResult
from jobagent.resume.model import (Bullet, ResumeProject, ResumeRole, SkillGroup, TailoredResume,
                                   TailoringRecord)
from jobagent.taxonomy import Taxonomy

GROUPS = [
    ("Languages", {"language"}),
    ("Databases & Warehousing", {"database", "warehouse"}),
    ("Cloud & Orchestration", {"cloud", "orchestration"}),
    ("Data Engineering", {"processing", "streaming", "integration", "concept"}),
    ("BI & Analytics", {"bi"}),
    ("Tools & Practices", {"devops", "practice", "ml", "other"}),
]
METRIC_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|x\b|percent|hours?|minutes?|records|rows|k\b|m\b|million)", re.I)


class Tailor:
    def __init__(self, profile: CandidateProfile, taxonomy: Taxonomy, max_bullets: int = 6):
        self.p = profile
        self.t = taxonomy
        self.max_bullets = max_bullets

    # ------------------------------------------------------------------ relevance
    def _weights(self, req: JobRequirements) -> dict[str, float]:
        w: dict[str, float] = {}
        for skills, val in ((req.preferred_skills, 0.5), (req.unclassified_skills, 0.7), (req.required_skills, 1.0)):
            for s in skills:
                w[s] = max(w.get(s, 0), val)
                for implied in self.t.implied_closure({s}) - {s}:
                    w.setdefault(implied, val * 0.3)
        return w

    def _job_concepts(self, req: JobRequirements, description: str) -> set[str]:
        text = "\n".join(req.responsibilities) or description
        return {c for c, pat in CONCEPTS.items() if re.search(pat, text, re.I)}

    def _bullet_score(self, text: str, weights: dict[str, float], concepts: set[str]) -> float:
        found = self.t.implied_closure(set(self.t.find(text)))
        s = sum(weights.get(k, 0) for k in found)
        s += 0.6 * sum(1 for c in concepts if re.search(CONCEPTS[c], text, re.I))
        if METRIC_RE.search(text):
            s += 0.3  # concrete outcomes help recruiters
        return s

    # ------------------------------------------------------------------ summary
    def _summary(self, req: JobRequirements, weights: dict[str, float], concepts: set[str]) -> tuple[str, str]:
        prof = {s.name for s in self.p.skills if s.level == "professional"}
        relevant = sorted((s for s in prof if weights.get(s, 0) >= 0.5 and self.t.category(s) != "concept"),
                          key=lambda s: (-weights.get(s, 0), s))[:6]
        # Drop broad skills already implied by a more specific one ("AWS" when "AWS Lambda" is listed).
        relevant = [s for s in relevant if not any(s in self.t.implied_closure({o}) - {o} for o in relevant if o != s)]
        if len(relevant) < 3:
            relevant += [s for s in sorted(prof) if s not in relevant and self.t.category(s) != "concept"][:6 - len(relevant)]
        evidence_concepts = []
        prof_text = "\n".join(b for e in self.p.experience for b in e.bullets)
        for c in ["building pipelines", "API/data ingestion", "transformation", "data synchronisation", "data quality",
                  "troubleshooting", "optimisation", "orchestration", "data modelling", "warehousing/lakes", "BI/reporting"]:
            if c in concepts and re.search(CONCEPTS[c], prof_text, re.I):
                evidence_concepts.append(c)
        phrases = {
            "building pipelines": "building and maintaining production ETL pipelines",
            "API/data ingestion": "ingesting data from external APIs",
            "transformation": "transforming data through staging layers",
            "data synchronisation": "incremental loading and reliable data synchronisation",
            "data quality": "resolving data-quality issues",
            "troubleshooting": "troubleshooting production pipeline failures",
            "optimisation": "optimising queries and pipeline performance",
            "orchestration": "orchestrating data workflows",
            "data modelling": "data modelling",
            "warehousing/lakes": "loading analytical data stores",
            "BI/reporting": "delivering reporting and dashboards",
        }
        # A phrase must not imply any skill the profile does not hold professionally.
        prof_closure = self.t.implied_closure(prof)
        evidence_concepts = [c for c in evidence_concepts if set(self.t.find(phrases[c])) <= prof_closure]
        headline = self.p.headline or (self.p.experience[0].title if self.p.experience else "Data professional")
        years = self.p.total_experience_years
        yrs = f" with {math.floor(years)}+ years of professional experience" if years and years >= 1 else ""
        ph = [phrases[c] for c in evidence_concepts[:3]]
        themes = (" " + (", ".join(ph[:-1]) + " and " + ph[-1] if len(ph) > 1 else ph[0])) if ph else ""
        sentences = [f"{headline}{yrs}{themes}."]
        if relevant:
            sentences.append("Hands-on with " + (", ".join(relevant[:-1]) + " and " + relevant[-1]
                                                 if len(relevant) > 1 else relevant[0]) + ".")
        extra = [phrases[c] for c in evidence_concepts[3:5]]
        if extra:
            sentences.append("Experienced in " + " and ".join(extra) + ".")
        summary = " ".join(sentences)
        strategy = (f"template summary from verified facts: headline '{headline}', years={years}, "
                    f"professional skills={relevant}, evidenced themes={evidence_concepts}")
        return summary, strategy

    # ------------------------------------------------------------------ main
    def build(self, job: dict, description: str, req: JobRequirements, match: MatchResult | None) -> tuple[TailoredResume, TailoringRecord]:
        weights = self._weights(req)
        concepts = self._job_concepts(req, description)
        rec = TailoringRecord(target_job=f"{job.get('title')} @ {job.get('company')} (job {job.get('id')})",
                              summary_strategy="")

        summary, rec.summary_strategy = self._summary(req, weights, concepts)

        # Skills: every professional (or still-unconfirmed 'listed') skill stays, ordered by job importance
        # inside standard groups. Project-only skills get their own clearly labelled line.
        held = [s for s in self.p.skills if s.level in ("professional", "listed")]
        groups = []
        known = {c for _, cats in GROUPS for c in cats}
        for label, cats in GROUPS:
            # The last group also catches any category not listed above.
            items = [s for s in held if self.t.category(s.name) in cats
                     or (label == GROUPS[-1][0] and self.t.category(s.name) not in known)]
            if label == "Data Engineering":
                # Concept skills (e.g. "ETL", "Data Quality") only when the job cares about them, to avoid clutter.
                items = [s for s in items if self.t.category(s.name) != "concept" or weights.get(s.name, 0) > 0]
            items.sort(key=lambda s: (-weights.get(s.name, 0), -LEVEL_RANK[s.level], s.name))
            if items:
                groups.append(SkillGroup(label=label, skills=[s.name for s in items]))
        project_only = sorted((s for s in self.p.skills if s.level == "project"),
                              key=lambda s: (-weights.get(s.name, 0), s.name))
        project_only = [s for s in project_only if self.t.category(s.name) != "concept" or weights.get(s.name, 0) > 0]
        if project_only:
            groups.append(SkillGroup(label="Project experience", skills=[s.name for s in project_only]))
        exploring = [s.name for s in self.p.skills if s.level == "studied" and weights.get(s.name, 0) > 0]

        roles = []
        for e in self.p.experience:  # chronological order is preserved; roles are never dropped
            scored = sorted(enumerate(e.bullets), key=lambda ib: (-self._bullet_score(ib[1], weights, concepts), ib[0]))
            keep = scored[:self.max_bullets]
            if [i for i, _ in keep] != list(range(len(keep))):
                rec.reordered_roles.append(f"{e.title} @ {e.employer}")
            for _, b in scored[self.max_bullets:]:
                rec.omitted_bullets.append(f"{e.employer}: {b}")
            roles.append(ResumeRole(employer=e.employer, title=e.title, start=e.start, end=e.end, location=e.location,
                                    bullets=[Bullet(text=b, source=b) for _, b in keep]))

        projects = []
        ranked = sorted(self.p.projects, key=lambda p: -sum(self._bullet_score(b, weights, concepts) for b in p.bullets + [p.name]))
        for i, pr in enumerate(ranked):
            relevance = sum(self._bullet_score(b, weights, concepts) for b in pr.bullets + [pr.name])
            if i >= 3 or (relevance == 0 and len(ranked) > 1):
                rec.omitted_projects.append(f"{pr.name} (relevance {relevance:.1f})")
                continue
            bl = sorted(pr.bullets, key=lambda b: -self._bullet_score(b, weights, concepts))[:4]
            projects.append(ResumeProject(name=pr.name, kind=pr.kind, description=pr.description,
                                          bullets=[Bullet(text=b, source=b) for b in bl]))

        resume = TailoredResume(
            name=self.p.name or "", contact=self.p.contact, headline=self.p.headline, summary=summary,
            skill_groups=groups, experience=roles, projects=projects, education=self.p.education,
            certifications=self.p.certifications, exploring=exploring,
        )

        # Keyword accounting
        job_skills = list(dict.fromkeys(req.required_skills + req.unclassified_skills + req.preferred_skills))
        shown = self.t.implied_closure(set(self.t.find(resume.all_text())))
        levels = {s.name: s.level for s in self.p.skills}
        held_closure = self.t.implied_closure({s.name for s in self.p.skills if s.level != "studied"})
        for s in job_skills:
            if s in shown:
                rec.keywords_included.append(s)
            elif s in held_closure:
                rec.keywords_missing_supported.append(s)
            else:
                note = " (studied only)" if levels.get(s) == "studied" else ""
                rec.requirements_unsupported.append(s + note)
        for c in (match.hard_constraints if match else []):
            if c.status != "pass" and c.name in ("certification", "degree"):
                rec.needs_user_input.append(f"{c.name}: {c.detail}. If you hold this, add it to your profile.")
        if any(s.level == "listed" for s in self.p.skills):
            rec.needs_user_input.append("Profile still has 'listed' skills; confirm their level for stronger tailoring.")
        return resume, rec
