"""Status vocabulary shared by pipeline tool runs and integration tests."""
from __future__ import annotations

from enum import Enum


class ToolStatus(str, Enum):
    LIVE_SUCCESS = "LIVE_SUCCESS"            # a real response came back from the external service
    LOCAL_SUCCESS = "LOCAL_SUCCESS"          # a local algorithm ran on real input
    AUTH_REQUIRED = "AUTH_REQUIRED"          # no key configured, or the service rejected the key
    RATE_LIMITED = "RATE_LIMITED"            # HTTP 429 after retries
    BLOCKED = "BLOCKED"                      # network, proxy or policy prevented the call
    SERVICE_ERROR = "SERVICE_ERROR"          # 5xx, timeout, or a response not in the documented shape
    NOT_TESTED = "NOT_TESTED"                # deliberately not run (billing, consent, optional model)
    SKIPPED_CONSENT = "SKIPPED_CONSENT"      # user did not consent to third-party upload
    SKIPPED_NOT_APPLICABLE = "SKIPPED_NOT_APPLICABLE"
    INPUT_ERROR = "INPUT_ERROR"              # the submission itself was invalid


class ToolError(Exception):
    """Messages are redacted on creation, so a service that echoes a key cannot leak it into a report."""

    def __init__(self, status: ToolStatus, message: str, http_status: int | None = None) -> None:
        from satyapan.logging_setup import redact
        message = redact(message)
        super().__init__(f"{status.value}: {message}")
        self.status = status
        self.message = message
        self.http_status = http_status
