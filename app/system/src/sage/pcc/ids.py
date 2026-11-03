"""Deterministic, namespaced PCC identifiers (handover doc 01 "Stable IDs and hashes").

An ID is ``<PREFIX>-<first 16 hex of SHA-256 over canonical JSON of its key fields>``. The key is
never a human label alone, and presentation order never changes an ID. Callers that mint many IDs
in one Run use :class:`IdRegistry` to fail closed on a truncated-hash collision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..errors import ValidationError

PREFIXES = {
    "expression": "EXPR",
    "sense": "SENSE",
    "occurrence": "OCC",
    "group": "SECG",
    "finding": "PCF",
    "cluster": "CL",
    "rule": "RULE",
    "exception": "EXC",
    "alignment": "ALN",
    "event": "EVT",
}
DIGEST_HEX = 16


def canonical_json(value: Any) -> str:
    """Serialize ``value`` the same way on every platform (sorted keys, no extra whitespace)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def full_digest(value: Any) -> str:
    """Return the full SHA-256 of ``value``'s canonical JSON."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def make_id(kind: str, key: Any) -> str:
    """Return the deterministic ID of one record from its identifying ``key`` fields."""
    try:
        prefix = PREFIXES[kind]
    except KeyError as exc:
        raise ValidationError(f"Unknown PCC identifier kind: {kind}", code="PCC_ID_KIND_UNKNOWN") from exc
    return f"{prefix}-{full_digest([kind, key])[:DIGEST_HEX]}"


def expression_id(source_corpus_sha256: str, normalized_form: str) -> str:
    """Expression identity: controlling SOURCE content and normalized wording."""
    return make_id("expression", {"source": source_corpus_sha256, "form": normalized_form})


def occurrence_id(source_corpus_sha256: str, reference: str, start: int, end: int, expression: str) -> str:
    """Occurrence identity: SOURCE content, reference, code-point span and expression."""
    return make_id(
        "occurrence",
        {"source": source_corpus_sha256, "ref": reference, "span": [start, end], "expression": expression},
    )


def group_id(scope_policy_sha256: str, expression: str, sense: str) -> str:
    """SECG identity: comparison-scope policy, expression and sense."""
    return make_id("group", {"policy": scope_policy_sha256, "expression": expression, "sense": sense})


def finding_id(run_input_sha256: str, code: str, subject_ids: list[str], candidate: str) -> str:
    """Finding identity: Run input fingerprint, code, sorted subjects and candidate fingerprint."""
    return make_id(
        "finding",
        {"input": run_input_sha256, "code": code, "subjects": sorted(subject_ids), "candidate": candidate},
    )


class IdRegistry:
    """Track minted IDs in one Run and fail closed when two different keys share an ID."""

    def __init__(self) -> None:
        """Start with no minted identifiers."""
        self._keys: dict[str, str] = {}

    def mint(self, kind: str, key: Any) -> str:
        """Return the ID for ``key`` and reject a truncated-hash collision with an earlier key."""
        value = make_id(kind, key)
        digest = full_digest([kind, key])
        previous = self._keys.setdefault(value, digest)
        if previous != digest:
            raise ValidationError(
                f"PCC identifier collision on {value}",
                code="PCC_ID_COLLISION",
                details={"id": value},
            )
        return value
