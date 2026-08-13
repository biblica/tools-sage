"""Small localhost-only HTTP helpers for SAGE local-model providers."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..errors import ValidationError


_ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_local_endpoint(value: str, *, provider: str) -> str:
    """Require an explicit loopback HTTP endpoint; SAGE local providers never use remote hosts."""
    endpoint = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _ALLOWED_LOCAL_HOSTS:
        raise ValidationError(
            f"{provider} endpoint must use localhost/loopback only: {value}",
            code="LLM_REMOTE_ENDPOINT_FORBIDDEN",
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError(
            f"{provider} endpoint must not contain credentials, query, or fragment",
            code="LLM_ENDPOINT_INVALID",
        )
    return endpoint


def get_json(url: str, *, timeout: int = 4) -> Any:
    """Read JSON from an already validated local provider endpoint."""
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"Local provider request failed: {url}: {exc}",
            code="LLM_PROVIDER_UNREACHABLE",
        ) from exc


def post_json(url: str, payload: dict[str, Any], *, timeout: int) -> Any:
    """Post JSON to an already validated local provider endpoint."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"Local provider request failed: {url}: {exc}",
            code="LLM_PROVIDER_EXECUTION_FAILED",
        ) from exc
