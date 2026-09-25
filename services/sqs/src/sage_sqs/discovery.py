"""Strict metadata-only discovery validation."""
from __future__ import annotations

from typing import Any

_PROHIBITED = {"scripture", "content", "text", "prompt", "project_id", "job_id", "user_id", "api_key", "token", "secret", "authorization"}


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text.lower())


def validate_discovery(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"kind", "sage_version", "observed"}:
        raise ValueError("INVALID_DISCOVERY")
    if any(str(key).lower() in _PROHIBITED for key in payload):
        raise ValueError("INVALID_DISCOVERY")
    kind = payload.get("kind")
    observed = payload.get("observed")
    if not isinstance(observed, dict):
        raise ValueError("INVALID_DISCOVERY")
    if any(str(key).lower() in _PROHIBITED for key in observed):
        raise ValueError("INVALID_DISCOVERY")
    if kind == "LANGUAGE_PROFILE":
        if set(observed) != {"profile_id", "language_code", "script", "region"}:
            raise ValueError("INVALID_DISCOVERY")
    elif kind == "LANGUAGE_VALIDATION_REQUEST":
        if set(observed) != {"profile_id", "language_code", "script", "region", "capability"}:
            raise ValueError("INVALID_DISCOVERY")
        if observed.get("capability") not in {"GRAMMAR_ANALYSIS", "SEMANTIC_REWRITE"}:
            raise ValueError("INVALID_DISCOVERY")
    elif kind == "MODEL":
        if set(observed) != {"provider_family", "model_id", "reasoning_levels", "capability_fingerprint"}:
            raise ValueError("INVALID_DISCOVERY")
        if observed.get("provider_family") != "openai" or not isinstance(observed.get("reasoning_levels"), list):
            raise ValueError("INVALID_DISCOVERY")
        if not _is_sha256(observed.get("capability_fingerprint")):
            raise ValueError("INVALID_DISCOVERY")
    else:
        raise ValueError("INVALID_DISCOVERY")
    return dict(payload)
