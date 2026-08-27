"""Deterministic evidence serialization, measurement, and hard-limit enforcement."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .errors import EvidenceLimitError, ValidationError

WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class EvidenceMeasurement:
    """Measured size of the exact serialized evidence payload."""

    serialized_bytes: int
    unicode_characters: int
    words: int
    estimated_tokens: int

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-serializable representation for reports and state files."""
        return asdict(self)


@dataclass(frozen=True)
class EvidencePolicy:
    """Shared planning and final-packet limits for one workflow operation."""

    target_estimated_tokens: int = 18000
    hard_estimated_tokens: int = 28000
    hard_serialized_bytes: int = 196000
    minimum_target_tokens: int = 6000
    maximum_primary_verse_units: int = 220
    context_before_verses: int = 1
    context_after_verses: int = 1
    allow_cross_chapter_units: bool = True
    maximum_primary_discourse_units: int = 0
    preferred_primary_discourse_units: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "EvidencePolicy":
        """Load and validate a policy mapping with conservative defaults."""
        data = dict(value or {})
        fields: dict[str, Any] = {}
        for name in (
            "target_estimated_tokens",
            "hard_estimated_tokens",
            "hard_serialized_bytes",
            "minimum_target_tokens",
            "maximum_primary_verse_units",
            "context_before_verses",
            "context_after_verses",
            "maximum_primary_discourse_units",
            "preferred_primary_discourse_units",
        ):
            if name in data:
                raw = data[name]
                if not isinstance(raw, int) or raw < 0:
                    raise ValidationError(f"Evidence policy {name} must be a nonnegative integer")
                fields[name] = raw
        if "allow_cross_chapter_units" in data:
            if not isinstance(data["allow_cross_chapter_units"], bool):
                raise ValidationError("Evidence policy allow_cross_chapter_units must be boolean")
            fields["allow_cross_chapter_units"] = data["allow_cross_chapter_units"]
        policy = cls(**fields)
        if policy.target_estimated_tokens <= 0:
            raise ValidationError("target_estimated_tokens must be positive")
        if policy.hard_estimated_tokens < policy.target_estimated_tokens:
            raise ValidationError("hard_estimated_tokens must not be below target_estimated_tokens")
        if policy.minimum_target_tokens > policy.target_estimated_tokens:
            raise ValidationError("minimum_target_tokens must not exceed target_estimated_tokens")
        if policy.hard_serialized_bytes <= 0:
            raise ValidationError("hard_serialized_bytes must be positive")
        if policy.maximum_primary_verse_units <= 0:
            raise ValidationError("maximum_primary_verse_units must be positive")
        if policy.maximum_primary_discourse_units < 0:
            raise ValidationError("maximum_primary_discourse_units must be nonnegative")
        if policy.preferred_primary_discourse_units < 0:
            raise ValidationError("preferred_primary_discourse_units must be nonnegative")
        return policy

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for reports and state files."""
        return asdict(self)


def serialize_evidence(value: Any) -> bytes:
    """Serialize as compact deterministic UTF-8 JSON for exact context measurement."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def estimate_tokens(text: str) -> int:
    """Return a conservative multilingual token estimate.

    SAGE records this as an estimate, never as an exact model-token count. The
    actual serialized byte count remains an independent hard guard.
    """
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    word_count = len(WORD_RE.findall(text))
    character_estimate = ascii_count / 4.0 + non_ascii_count / 2.0
    word_estimate = word_count * 1.35
    return max(1, math.ceil(max(character_estimate, word_estimate)))


def measure_evidence(value: Any) -> EvidenceMeasurement:
    """Measure the exact serialized packet and estimate its model tokens."""
    payload = serialize_evidence(value)
    text = payload.decode("utf-8")
    return EvidenceMeasurement(
        serialized_bytes=len(payload),
        unicode_characters=len(text),
        words=len(WORD_RE.findall(text)),
        estimated_tokens=estimate_tokens(text),
    )


def evidence_within_limits(
    measurement: EvidenceMeasurement,
    policy: EvidencePolicy,
    *,
    primary_verse_units: int,
) -> bool:
    """Return whether an evidence packet fits all governed hard limits."""
    return (
        measurement.serialized_bytes <= policy.hard_serialized_bytes
        and measurement.estimated_tokens <= policy.hard_estimated_tokens
        and primary_verse_units <= policy.maximum_primary_verse_units
    )


def enforce_evidence_limits(
    value: Any,
    policy: EvidencePolicy,
    *,
    primary_verse_units: int,
    operation: str,
) -> EvidenceMeasurement:
    """Measure a final packet and block before model execution when oversized."""
    measurement = measure_evidence(value)
    failures: list[str] = []
    if measurement.serialized_bytes > policy.hard_serialized_bytes:
        failures.append(
            f"serialized bytes {measurement.serialized_bytes} > {policy.hard_serialized_bytes}"
        )
    if measurement.estimated_tokens > policy.hard_estimated_tokens:
        failures.append(
            f"estimated tokens {measurement.estimated_tokens} > {policy.hard_estimated_tokens}"
        )
    if primary_verse_units > policy.maximum_primary_verse_units:
        failures.append(
            f"primary verse units {primary_verse_units} > {policy.maximum_primary_verse_units}"
        )
    if failures:
        raise EvidenceLimitError(
            f"{operation} evidence exceeds governed limits: " + "; ".join(failures)
        )
    return measurement
