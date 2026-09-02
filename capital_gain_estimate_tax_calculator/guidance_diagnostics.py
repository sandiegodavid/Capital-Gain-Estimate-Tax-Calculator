"""Credential-safe terminal diagnostics for AI guidance requests."""

from __future__ import annotations

import json
import logging

LOGGER = logging.getLogger(__name__)
_SENSITIVE_HEADERS = frozenset({"authorization", "x-goog-api-key"})


def request_diagnostic(endpoint: str, request_body: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    """Return a reproducible request record with credentials removed."""
    safe_headers = {
        name: "[REDACTED]" if name.lower() in _SENSITIVE_HEADERS else value
        for name, value in headers.items()
    }
    return {"method": "POST", "url": endpoint, "headers": safe_headers, "body": request_body}


def print_request(provider_label: str, endpoint: str, request_body: dict[str, object], headers: dict[str, str]) -> None:
    """Print a credential-free request before it is sent."""
    print(f"{provider_label} tax-rate request sending:\n{json.dumps(request_diagnostic(endpoint, request_body, headers), indent=2)}")


def print_response(provider_label: str, response_body: dict[str, object]) -> None:
    """Print a formatted response after it is received."""
    print(f"{provider_label} tax-rate response received:\n{json.dumps(response_body, indent=2)}")


def log_http_failure(provider_label: str, reason: str, endpoint: str, request_body: dict[str, object], headers: dict[str, str]) -> None:
    """Log an HTTP failure without exposing credentials."""
    LOGGER.error(
        "%s tax-rate request failed: %s\nSanitized request:\n%s",
        provider_label,
        reason,
        json.dumps(request_diagnostic(endpoint, request_body, headers), indent=2),
    )


def log_sdk_failure(provider_label: str, error: Exception, request_body: dict[str, object]) -> None:
    """Log a credential-free SDK failure."""
    diagnostic = {"sdk": "google-genai", "request": request_body}
    LOGGER.error(
        "%s tax-rate SDK request failed: %s\nSanitized SDK request:\n%s",
        provider_label,
        error,
        json.dumps(diagnostic, indent=2),
    )
