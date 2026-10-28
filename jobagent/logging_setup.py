"""Structured (JSON-lines) file logging plus concise console output, with secret redaction."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

_REDACT_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|cookie|token|li_at|jsessionid)(\"?\s*[:=]\s*\"?)[^\s\",;]+"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),          # e-mail addresses
    re.compile(r"(?<!\d)(?:\+?92|0)3\d{2}[\s-]?\d{7}(?!\d)"),  # Pakistani mobile numbers
]


def redact(text: str) -> str:
    for pat in _REDACT_PATTERNS:
        if pat.groups >= 2:
            text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        else:
            text = pat.sub("[REDACTED]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("run_id", "job_id", "source", "event"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    root = logging.getLogger("jobagent")
    if getattr(root, "_configured", False):
        return
    root.setLevel(level.upper())
    root.propagate = False
    flt = RedactingFilter()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    console.setLevel(logging.WARNING)
    console.addFilter(flt)
    root.addHandler(console)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / "jobagent.jsonl", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        fh.addFilter(flt)
        root.addHandler(fh)
    except OSError as exc:  # logging must never stop the app
        root.warning("file logging disabled: %s", exc)
    root._configured = True  # type: ignore[attr-defined]
