"""Polite fetching of individual public job pages.

Rules enforced here (not configurable away):
  * robots.txt is honoured; disallowed URLs are not fetched.
  * Hosts on DENY_HOSTS are never fetched automatically (their terms prohibit automated access).
  * No cookies or credentials are sent; a fixed, honest User-Agent identifies the tool.
  * Per-host rate limit, timeouts and bounded retries for transient failures only.
"""
from __future__ import annotations

import logging
import urllib.robotparser
from urllib.parse import urlparse

import requests

from jobagent.config import UrlFetchSettings
from jobagent.utils.retry import PermanentError, RateLimiter, TransientError, retry_call

log = logging.getLogger("jobagent.sources.fetch")

DENY_HOSTS = ("linkedin.com", "indeed.com", "glassdoor.com")


class FetchRefused(PermanentError):
    """We chose not to fetch (robots.txt / platform terms)."""


class Fetcher:
    def __init__(self, cfg: UrlFetchSettings, session: requests.Session | None = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": cfg.user_agent, "Accept-Language": "en"})
        self.limiter = RateLimiter(cfg.min_interval_seconds)
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    @staticmethod
    def denied_host(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in DENY_HOSTS)

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", timeout=self.cfg.timeout_seconds)
                if r.status_code >= 400:
                    rp = None if r.status_code in (401, 403) else rp
                    if rp is not None:
                        rp.parse([])  # no robots.txt => allowed
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException as exc:
                log.info("robots.txt unavailable for %s: %s", base, exc)
                rp = None  # be conservative: unknown => do not fetch
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> tuple[bool, str]:
        if not self.cfg.enabled:
            return False, "url fetching disabled in settings"
        if urlparse(url).scheme not in ("http", "https"):
            return False, "only http(s) URLs are supported"
        if self.denied_host(url):
            return False, ("automated access to this platform is not permitted by its terms; "
                           "save the page from your browser or paste the description instead")
        rp = self._robots_for(url)
        if rp is None:
            return False, "robots.txt could not be retrieved or forbids access"
        if not rp.can_fetch(self.cfg.user_agent, url):
            return False, "disallowed by robots.txt"
        return True, "ok"

    def get(self, url: str) -> str:
        ok, why = self.allowed(url)
        if not ok:
            raise FetchRefused(why)
        host = urlparse(url).netloc

        def once() -> str:
            self.limiter.wait(host)
            try:
                r = self.session.get(url, timeout=self.cfg.timeout_seconds, allow_redirects=True)
            except (requests.Timeout, requests.ConnectionError) as exc:
                raise TransientError(str(exc)) from exc
            if r.status_code == 429 or r.status_code >= 500:
                raise TransientError(f"HTTP {r.status_code}")
            if r.status_code >= 400:
                raise PermanentError(f"HTTP {r.status_code}")
            return r.text

        return retry_call(once, max_attempts=self.cfg.max_retries)
