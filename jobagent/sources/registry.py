"""Registry of source connectors. Add a new platform by writing a JobSource and registering it here."""
from __future__ import annotations

from jobagent.config import Settings
from jobagent.sources.base import JobSource
from jobagent.sources.linkedin import LinkedInSource
from jobagent.sources.manual import ManualSource

SOURCES: dict[str, type[JobSource]] = {
    LinkedInSource.name: LinkedInSource,
    ManualSource.name: ManualSource,
}


def enabled_sources(settings: Settings) -> list[JobSource]:
    unknown = [n for n in settings.sources.enabled if n not in SOURCES]
    if unknown:
        raise ValueError(f"unknown sources in settings.sources.enabled: {unknown}; available: {list(SOURCES)}")
    return [SOURCES[n](settings) for n in settings.sources.enabled]
