"""HTTP transport to the SQS control plane: ordered endpoint failover, the
loopback/HTTPS exception, and proxy bypass for loopback traffic.

Locked decisions this implements: ordered endpoint failover is supported, but
invalid/security/4xx responses are not silently bypassed by trying another
endpoint; loopback HTTP is a local test exception only, non-loopback
endpoints require HTTPS; loopback requests explicitly bypass HTTP_PROXY/
HTTPS_PROXY, remote HTTPS retains normal proxy behavior.

This module only fetches/posts raw JSON. It does not validate bundle
content (see sqs_cache.py) and does not decide SAGE routing -- purely a
transport concern, kept independent per the integration plan's Task 4
requirement.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .errors import SageError

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_FAILOVER_URLLIB_ERRORS = (urllib.error.URLError, TimeoutError, socket.timeout)


class SqsTransportError(SageError):
    """Raised when every configured SQS endpoint fails, or a non-failover error occurs."""

    default_code = "SQS_TRANSPORT_ERROR"


def resolve_endpoints(*, urls_env: str | None = None, url_env: str | None = None) -> list[str]:
    """Resolve the ordered SQS endpoint list from SAGE_SQS_URLS, or the single SAGE_SQS_URL override.

    `urls_env`/`url_env` accept explicit values for testing; production callers
    read `os.environ` directly via the default None.
    """
    urls_value = urls_env if urls_env is not None else os.environ.get("SAGE_SQS_URLS")
    if urls_value and urls_value.strip():
        endpoints = [part.strip() for part in urls_value.split(",") if part.strip()]
        if endpoints:
            return [validate_sqs_endpoint(endpoint) for endpoint in endpoints]
    url_value = url_env if url_env is not None else os.environ.get("SAGE_SQS_URL")
    if url_value and url_value.strip():
        return [validate_sqs_endpoint(url_value.strip())]
    return []


def validate_sqs_endpoint(value: str) -> str:
    """Require loopback HTTP (local test only) or HTTPS for any other host."""
    endpoint = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(endpoint)
    is_loopback = parsed.hostname in _LOOPBACK_HOSTS
    if parsed.scheme == "http" and not is_loopback:
        raise SqsTransportError(
            f"Non-loopback SQS endpoint must use HTTPS: {value}",
            code="SQS_ENDPOINT_INSECURE",
        )
    if parsed.scheme not in {"http", "https"}:
        raise SqsTransportError(f"SQS endpoint must be http or https: {value}", code="SQS_ENDPOINT_INVALID")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SqsTransportError(
            f"SQS endpoint must not contain credentials, query, or fragment: {value}",
            code="SQS_ENDPOINT_INVALID",
        )
    return endpoint


def _is_loopback(endpoint: str) -> bool:
    """Return whether the endpoint's host is a loopback address."""
    return urllib.parse.urlparse(endpoint).hostname in _LOOPBACK_HOSTS


def _opener_for(endpoint: str) -> urllib.request.OpenerDirector:
    """Build a urllib opener that bypasses proxy env vars for loopback, honors them otherwise."""
    if _is_loopback(endpoint):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(urllib.request.ProxyHandler())


def _is_failover_eligible(exc: urllib.error.URLError) -> bool:
    """Return whether exc represents a connection/5xx failure (failover) vs. a hard stop."""
    if isinstance(exc, urllib.error.HTTPError):
        return 500 <= exc.code < 600
    return True  # any other URLError (connection refused, DNS, timeout) is failover-eligible


def _request_json(endpoint: str, path: str, *, method: str, payload: dict[str, Any] | None, timeout: int) -> Any:
    """Issue one JSON HTTP request against one endpoint; raises on any failure, does not fail over."""
    url = endpoint + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    opener = _opener_for(endpoint)
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def request_with_failover(endpoints: list[str], path: str, *, method: str = "GET",
                          payload: dict[str, Any] | None = None, timeout: int = 10) -> Any:
    """Try each endpoint in order; fail over only on connection failure or 5xx.

    A 4xx or any other non-failover error stops immediately and is raised as-is
    (via SqsTransportError wrapping urllib's HTTPError) -- it must never cause a
    silent retry against a different endpoint.
    """
    if not endpoints:
        raise SqsTransportError("No SQS endpoint is configured", code="SQS_NO_ENDPOINT_CONFIGURED")
    last_error: Exception | None = None
    for endpoint in endpoints:
        try:
            return _request_json(endpoint, path, method=method, payload=payload, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if _is_failover_eligible(exc):
                last_error = exc
                continue
            raise SqsTransportError(
                f"SQS request to {endpoint}{path} failed with {exc.code} (not eligible for failover)",
                code="SQS_REQUEST_REJECTED",
            ) from exc
        except _FAILOVER_URLLIB_ERRORS as exc:
            last_error = exc
            continue
        except json.JSONDecodeError as exc:
            raise SqsTransportError(f"SQS response from {endpoint}{path} was not valid JSON", code="SQS_RESPONSE_INVALID") from exc
    raise SqsTransportError(
        f"All {len(endpoints)} configured SQS endpoint(s) failed: {last_error}",
        code="SQS_ALL_ENDPOINTS_FAILED",
    ) from last_error


def fetch_health(endpoints: list[str], *, timeout: int = 5) -> dict[str, Any]:
    """GET /health with ordered endpoint failover."""
    return request_with_failover(endpoints, "/health", timeout=timeout)


def fetch_bundle(endpoints: list[str], *, timeout: int = 10) -> dict[str, Any]:
    """GET /bundle with ordered endpoint failover. Caller must still validate via sqs_cache."""
    return request_with_failover(endpoints, "/bundle", timeout=timeout)


def post_discovery(endpoints: list[str], payload: dict[str, Any], *, timeout: int = 10) -> Any:
    """POST /discoveries with ordered endpoint failover."""
    return request_with_failover(endpoints, "/discoveries", method="POST", payload=payload, timeout=timeout)


def fetch_planned_evaluations(endpoints: list[str], *, timeout: int = 10) -> list[dict[str, Any]]:
    """GET /planned-evaluations with ordered endpoint failover.

    A plain, non-exclusive list of pending qualification work -- unlike the
    server's own claim_next_evaluation(), fetching this list never marks
    anything RUNNING.
    """
    return request_with_failover(endpoints, "/planned-evaluations", timeout=timeout)
