"""Skill taxonomy: canonical names, synonyms, implications and transfer relationships."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from jobagent.config import PROJECT_ROOT

DEFAULT_TAXONOMY = PROJECT_ROOT / "config" / "skills_taxonomy.yaml"


@dataclass
class Skill:
    name: str
    category: str
    aliases: list[str] = field(default_factory=list)
    case_sensitive_aliases: list[str] = field(default_factory=list)
    implies: list[str] = field(default_factory=list)
    equivalent: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    context_only: bool = False


def _alias_pattern(alias: str) -> str:
    # Escape, allow flexible whitespace/hyphen between words, and require non-word boundaries that
    # also treat '+', '#', '/' and '.' as part of a token where relevant.
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", alias.strip()) if p]
    body = r"[\s\-]*".join(parts)
    return rf"(?<![A-Za-z0-9_+#/.&]){body}(?![A-Za-z0-9_+#&]|\.[A-Za-z0-9])"


class Taxonomy:
    def __init__(self, data: dict):
        credit = data.get("credit", {})
        self.equivalent_credit = float(credit.get("equivalent", 0.7))
        self.related_credit = float(credit.get("related", 0.35))
        self.skills: dict[str, Skill] = {}
        for name, spec in (data.get("skills") or {}).items():
            spec = spec or {}
            self.skills[name] = Skill(
                name=name,
                category=spec.get("category", "other"),
                aliases=list(spec.get("aliases") or []),
                case_sensitive_aliases=list(spec.get("case_sensitive_aliases") or []),
                implies=list(spec.get("implies") or []),
                equivalent=list(spec.get("equivalent") or []),
                related=list(spec.get("related") or []),
                context_only=bool(spec.get("context_only", False)),
            )
        self._lookup = {}
        for s in self.skills.values():
            for a in [s.name, *s.aliases]:
                self._lookup[a.lower()] = s.name
        self._patterns: list[tuple[re.Pattern, str]] = []
        for s in self.skills.values():
            ci = [s.name, *s.aliases] if not s.context_only else [s.name, *s.aliases]
            if s.case_sensitive_aliases:
                if s.context_only:
                    ci = [a for a in ci if a not in s.case_sensitive_aliases and len(a) > 1]
                self._patterns.append(
                    (re.compile("|".join(_alias_pattern(a) for a in s.case_sensitive_aliases)), s.name))
            ci = [a for a in ci if len(a) > 1]
            if s.context_only and s.name in ("Go",):
                ci = [a for a in ci if a.lower() != "go"]  # "go" is too common; only "golang"
            if ci:
                # Longest aliases first so "sql server" wins over "sql".
                ci = sorted(set(ci), key=len, reverse=True)
                self._patterns.append(
                    (re.compile("|".join(_alias_pattern(a) for a in ci), re.IGNORECASE), s.name))

    # ------------------------------------------------------------------ lookup
    def canonical(self, name: str) -> str | None:
        """Map any alias (or canonical name) to the canonical skill name."""
        if not name:
            return None
        hit = self._lookup.get(name.strip().lower())
        if hit:
            return hit
        found = self.find(name)
        return next(iter(found)) if len(found) == 1 else None

    def find(self, text: str) -> dict[str, list[str]]:
        """Return {canonical_skill: [matched snippets]} for all skills in text.

        Overlapping matches are resolved in favour of the longest alias, so "SQL Server" yields
        Microsoft SQL Server and not also bare SQL from the same characters.
        """
        if not text:
            return {}
        spans: list[tuple[int, int, str]] = []
        for pat, name in self._patterns:
            for m in pat.finditer(text):
                spans.append((m.start(), m.end(), name))
        spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
        taken: list[tuple[int, int]] = []
        out: dict[str, list[str]] = {}
        for start, end, name in spans:
            if any(start < e and end > s for s, e in taken):
                continue
            taken.append((start, end))
            out.setdefault(name, []).append(text[start:end])
        return out

    def implied_closure(self, names: set[str]) -> set[str]:
        """Skills plus everything they (transitively) imply."""
        out, stack = set(), list(names)
        while stack:
            n = stack.pop()
            if n in out:
                continue
            out.add(n)
            if s := self.skills.get(n):
                stack.extend(s.implies)
        return out

    def transfer_credit(self, required: str, candidate: set[str]) -> tuple[float, str | None]:
        """Best partial credit for a required skill the candidate lacks, and the skill providing it."""
        best, via = 0.0, None
        req = self.skills.get(required)
        for c in candidate:
            cs = self.skills.get(c)
            if not cs:
                continue
            if required in cs.equivalent or (req and c in req.equivalent):
                if self.equivalent_credit > best:
                    best, via = self.equivalent_credit, c
            elif required in cs.related or (req and c in req.related):
                if self.related_credit > best:
                    best, via = self.related_credit, c
        return best, via

    def category(self, name: str) -> str:
        s = self.skills.get(name)
        return s.category if s else "other"


@lru_cache(maxsize=4)
def _load(path: str) -> Taxonomy:
    return Taxonomy(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


def load_taxonomy(path: Path | None = None) -> Taxonomy:
    return _load(str(path or DEFAULT_TAXONOMY))
