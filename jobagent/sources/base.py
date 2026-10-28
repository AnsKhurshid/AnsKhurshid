"""Source-connector interface. The core pipeline depends only on this module."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from jobagent.config import Settings
from jobagent.models import SourceResult


@dataclass
class CollectRequest:
    """Inputs for one collection pass. Connectors use what applies to them and ignore the rest."""
    files: list[Path] = field(default_factory=list)   # explicit files to import
    urls: list[str] = field(default_factory=list)     # explicit URLs supplied by the user
    use_inbox: bool = True                             # also scan the connector's inbox directory
    limit: int | None = None


class JobSource(ABC):
    """A job platform connector. Must never apply, message, or upload anything."""

    name: str = "base"

    def __init__(self, settings: Settings):
        self.settings = settings

    @abstractmethod
    def collect(self, request: CollectRequest) -> SourceResult:
        ...

    def handles_url(self, url: str) -> bool:
        return False
