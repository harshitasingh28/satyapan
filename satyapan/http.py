"""The only way Satyapan code talks to the internet.

SSRF stance: the backend NEVER fetches a URL that a user submitted. It only calls
a fixed allowlist of API hosts (plus RDAP servers taken from the IANA bootstrap,
the Hugging Face router and the operator-configured hosted LLM host). Suspect links are investigated through
those APIs, and opened only inside urlscan's sandbox.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from satyapan.config import Settings, get_settings
from satyapan.errors import ToolError, ToolStatus
from satyapan.logging_setup import redact

STATIC_ALLOWED_HOSTS = {
    "factchecktools.googleapis.com",
    "safebrowsing.googleapis.com",
    "vision.googleapis.com",
    "urlscan.io",
    "api.sightengine.com",
    "query.wikidata.org",
    "www.pib.gov.in",
    "pib.gov.in",
    "data.iana.org",
    "www.virustotal.com",
}
RETRYABLE = {429, 500, 502, 503, 504}


@dataclass
class CallRecord:
    tool: str
    method: str
    url: str
    http_status: int | None
    ms: float
    error: str | None
    reached_service: bool
    response_fields: list[str] = field(default_factory=list)


class ApiClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings or get_settings()
        self.allowed = set(STATIC_ALLOWED_HOSTS)
        if self.settings.llm_base_url:
            llm_host = urlsplit(self.settings.llm_base_url).hostname
            if llm_host:
                self.allowed.add(llm_host)
        for extra in (self.settings.llm_fallback_base_url, self.settings.embedding_base_url):
            host = urlsplit(extra).hostname if extra else None
            if host:                              # operator-configured hosted AI endpoints
                self.allowed.add(host)
        if self.settings.hf_token:               # Hugging Face router: chat and feature extraction
            hf_host = urlsplit(self.settings.hf_router_url).hostname
            if hf_host:
                self.allowed.add(hf_host)
        ua = f"Satyapan/0.2 (student hackathon research, contact {self.settings.contact})"
        self._http = httpx.Client(timeout=self.settings.http_timeout_s, headers={"User-Agent": ua},
                                  follow_redirects=False, transport=transport)
        self.calls: list[CallRecord] = []

    def allow_host(self, host: str) -> None:
        """Used for RDAP servers listed in the IANA bootstrap file."""
        self.allowed.add(host.lower())

    def close(self) -> None:
        self._http.close()

    def _check(self, url: str) -> None:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https":           # hosted services only, no local model servers
            raise ToolError(ToolStatus.BLOCKED, f"refusing non-https URL {redact(url)}")
        if host not in self.allowed:
            raise ToolError(ToolStatus.BLOCKED, f"host {host} is not on the API allowlist")

    def request(self, tool: str, method: str, url: str, *, retries: int | None = None,
                **kwargs) -> tuple[httpx.Response, float]:
        self._check(url)
        retries = self.settings.http_retries if retries is None else retries
        shown = str(httpx.Request(method, url, params=kwargs.get("params")).url)   # what was sent, key redacted later
        last: ToolError | None = None
        for attempt in range(retries + 1):
            start = time.perf_counter()
            try:
                resp = self._http.request(method, url, **kwargs)
            except httpx.TimeoutException as exc:
                last = ToolError(ToolStatus.SERVICE_ERROR, f"timeout: {exc}")
                self._record(tool, method, shown, None, start, str(last), False)
            except (httpx.ProxyError, httpx.ConnectError, httpx.NetworkError) as exc:
                last = ToolError(ToolStatus.BLOCKED, f"network: {exc}")
                self._record(tool, method, shown, None, start, str(last), False)
            else:
                ms = self._record(tool, method, shown, resp.status_code, start, None, True)
                if resp.status_code in (401, 403):
                    raise ToolError(ToolStatus.AUTH_REQUIRED, resp.text[:200], resp.status_code)
                if resp.status_code not in RETRYABLE:
                    return resp, ms
                status = ToolStatus.RATE_LIMITED if resp.status_code == 429 else ToolStatus.SERVICE_ERROR
                last = ToolError(status, resp.text[:200], resp.status_code)
            if attempt < retries:
                time.sleep(min(2.0 * (2 ** attempt), 8.0))
        assert last is not None
        raise last

    def _record(self, tool, method, url, status, start, error, reached) -> float:
        ms = round((time.perf_counter() - start) * 1000, 1)
        self.calls.append(CallRecord(tool, method, redact(url), status, ms, error and redact(error), reached))
        return ms


def json_or_error(resp: httpx.Response, tool: str) -> dict:
    try:
        return resp.json()
    except ValueError as exc:
        raise ToolError(ToolStatus.SERVICE_ERROR, f"{tool}: non-JSON response (HTTP {resp.status_code})") from exc
