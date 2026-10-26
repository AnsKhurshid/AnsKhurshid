"""Small text helpers shared by parsers and matchers."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_WS = re.compile(r"[ \t\r\f\v]+")


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace(" ", " ").replace("•", "•")
    lines = [_WS.sub(" ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def sha256(obj: Any) -> str:
    if not isinstance(obj, (str, bytes)):
        obj = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    if isinstance(obj, str):
        obj = obj.encode("utf-8")
    return hashlib.sha256(obj).hexdigest()


def norm_key(text: str | None) -> str:
    """Lower-case alphanumeric key used for fuzzy equality (company/title dedupe)."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
