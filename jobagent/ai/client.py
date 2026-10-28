"""Provider-neutral structured-output client with caching, usage tracking and cost estimates.

Callers ask for a Pydantic model back; providers are swappable. Every call (including cache hits and
failures) is recorded in the ai_calls table. Nothing here is required for the app to run: when no
provider is configured, `available` is False and callers fall back to deterministic logic.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from jobagent.config import AISettings, Settings
from jobagent.storage.db import Database
from jobagent.utils.text import sha256

log = logging.getLogger("jobagent.ai")
M = TypeVar("M", bound=BaseModel)


class AIError(Exception):
    """Any AI failure. `permanent` errors (auth, bad request, refusal) should not be retried."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None


class AIProvider(ABC):
    name = "base"

    @abstractmethod
    def structured(self, system: str, user: str, schema: type[M]) -> tuple[M, Usage]:
        ...


class AnthropicProvider(AIProvider):
    name = "anthropic"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, cfg: AISettings, api_key: str):
        import anthropic  # optional dependency, imported only when used

        self._anthropic = anthropic
        self.cfg = cfg
        self.client = anthropic.Anthropic(api_key=api_key, timeout=cfg.timeout_seconds, max_retries=cfg.max_retries)

    def structured(self, system: str, user: str, schema: type[M]) -> tuple[M, Usage]:
        a = self._anthropic
        kwargs = dict(model=self.cfg.model, max_tokens=self.cfg.max_tokens, system=system,
                      messages=[{"role": "user", "content": user}], output_format=schema,
                      output_config={"effort": self.cfg.effort})
        try:
            if self.cfg.refusal_fallback:
                resp = self.client.beta.messages.parse(betas=[self.FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.parse(**kwargs)
        except (a.AuthenticationError, a.PermissionDeniedError, a.NotFoundError, a.BadRequestError) as exc:
            raise AIError(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}", permanent=True) from exc
        except (a.RateLimitError, a.APIStatusError, a.APIConnectionError) as exc:
            raise AIError(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}") from exc
        usage = Usage(getattr(resp.usage, "input_tokens", None), getattr(resp.usage, "output_tokens", None),
                      getattr(resp, "model", self.cfg.model))
        if resp.stop_reason == "refusal":
            raise AIError("request declined by the model (refusal)", permanent=True)
        if resp.stop_reason == "max_tokens":
            raise AIError("response truncated at max_tokens; raise ai.max_tokens", permanent=True)
        parsed = resp.parsed_output
        if parsed is None:
            raise AIError("no structured output returned", permanent=True)
        return parsed, usage


class AIClient:
    def __init__(self, settings: Settings, db: Database, provider: AIProvider | None = None,
                 run_id: int | None = None):
        self.settings = settings
        self.db = db
        self.run_id = run_id
        self.provider = provider
        self.reason_unavailable = None
        if provider is None:
            cfg = settings.ai
            if cfg.provider == "none":
                self.reason_unavailable = "AI provider disabled (ai.provider: none)"
            elif not settings.api_key():
                self.reason_unavailable = f"{cfg.provider} selected but its API key is not set in .env"
            elif not cfg.model:
                self.reason_unavailable = "ai.model is empty"
            else:
                try:
                    self.provider = AnthropicProvider(cfg, settings.api_key())
                except ImportError:
                    self.reason_unavailable = "the 'anthropic' package is not installed (pip install anthropic)"

    @property
    def available(self) -> bool:
        return self.provider is not None

    def _cost(self, u: Usage) -> float | None:
        cfg = self.settings.ai
        if u.input_tokens is None or not (cfg.input_cost_per_mtok or cfg.output_cost_per_mtok):
            return None
        return round((u.input_tokens * cfg.input_cost_per_mtok + (u.output_tokens or 0) * cfg.output_cost_per_mtok) / 1e6, 6)

    def structured(self, purpose: str, system: str, user: str, schema: type[M], version: str) -> M:
        if not self.provider:
            raise AIError(self.reason_unavailable or "AI unavailable", permanent=True)
        model = self.settings.ai.model
        key = sha256([purpose, version, self.provider.name, model, system, user, schema.model_json_schema()])
        if (cached := self.db.cache_get(key)) is not None:
            try:
                result = schema.model_validate(cached)
                self.db.log_ai_call(self.run_id, purpose, self.provider.name, model, 0, 0, 0.0, cached=True, success=True)
                return result
            except ValidationError:
                log.info("stale AI cache entry for %s ignored", purpose)
        try:
            result, usage = self.provider.structured(system, user, schema)
        except AIError as exc:
            self.db.log_ai_call(self.run_id, purpose, self.provider.name, model, None, None, None,
                                cached=False, success=False, error=str(exc)[:500])
            raise
        except ValidationError as exc:
            self.db.log_ai_call(self.run_id, purpose, self.provider.name, model, None, None, None,
                                cached=False, success=False, error="schema validation failed")
            raise AIError(f"AI response failed schema validation: {exc.error_count()} errors", permanent=True) from exc
        self.db.log_ai_call(self.run_id, purpose, self.provider.name, usage.model or model, usage.input_tokens,
                            usage.output_tokens, self._cost(usage), cached=False, success=True)
        self.db.cache_put(key, purpose, result.model_dump(mode="json"))
        return result
