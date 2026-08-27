"""Deterministic evidence serialization, measurement, and hard-limit enforcement."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .errors import ConfigurationError, EvidenceLimitError, ValidationError

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
    preferred_max_estimated_tokens: int = 0
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
            "preferred_max_estimated_tokens",
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
        if policy.preferred_max_estimated_tokens and policy.preferred_max_estimated_tokens < policy.target_estimated_tokens:
            raise ValidationError("preferred_max_estimated_tokens must not be below target_estimated_tokens")
        if policy.preferred_max_estimated_tokens > policy.hard_estimated_tokens:
            raise ValidationError("preferred_max_estimated_tokens must not exceed hard_estimated_tokens")
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


@dataclass(frozen=True)
class RTCSizingPolicy:
    """Release-governed sizing contract for a complete SAW RTC handoff."""

    provider: str
    estimator: str
    wip_target_min_tokens: int
    wip_target_max_tokens: int
    wip_hard_exclusive_tokens: int
    governed_wip_ceiling_tokens: int
    package_hard_max_tokens: int
    provider_handoff_max_tokens: int
    package_hard_serialized_bytes: int
    minimum_reference_reserve_tokens: int
    minimum_overhead_reserve_tokens: int
    minimum_overhead_serialized_bytes: int

    # Keep all release-governed RTC parameters together: parsing, cross-field
    # validation and exact-handoff enforcement must evolve as one contract.

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RTCSizingPolicy":
        """Load the required RTC policy and reject contradictory limits up front."""
        if not isinstance(value, Mapping):
            raise ConfigurationError("SAW rtc_sizing must be a mapping")
        text_fields = ("provider", "estimator")
        integer_fields = (
            "wip_target_min_tokens",
            "wip_target_max_tokens",
            "wip_hard_exclusive_tokens",
            "governed_wip_ceiling_tokens",
            "package_hard_max_tokens",
            "provider_handoff_max_tokens",
            "package_hard_serialized_bytes",
            "minimum_reference_reserve_tokens",
            "minimum_overhead_reserve_tokens",
            "minimum_overhead_serialized_bytes",
        )
        missing = [name for name in (*text_fields, *integer_fields) if name not in value]
        if missing:
            raise ConfigurationError(
                "SAW rtc_sizing is missing required parameters: " + ", ".join(missing)
            )
        text: dict[str, str] = {}
        for name in text_fields:
            raw = value.get(name)
            if not isinstance(raw, str) or not raw.strip():
                raise ConfigurationError(f"SAW rtc_sizing.{name} must be a nonempty string")
            text[name] = raw.strip().lower() if name == "provider" else raw.strip()
        integers: dict[str, int] = {}
        for name in integer_fields:
            raw = value.get(name)
            if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
                raise ConfigurationError(f"SAW rtc_sizing.{name} must be a positive integer")
            integers[name] = raw
        policy = cls(**text, **integers)
        failures: list[str] = []
        if policy.wip_target_min_tokens > policy.wip_target_max_tokens:
            failures.append("WIP target minimum exceeds target maximum")
        if policy.wip_target_max_tokens >= policy.wip_hard_exclusive_tokens:
            failures.append("WIP target maximum must be below the exclusive WIP hard maximum")
        if policy.wip_hard_exclusive_tokens > policy.governed_wip_ceiling_tokens:
            failures.append("WIP hard maximum exceeds the governed slicer ceiling")
        if policy.package_hard_max_tokens > policy.provider_handoff_max_tokens:
            failures.append("RTC package maximum exceeds the provider handoff maximum")
        minimum_required = (
            policy.wip_hard_exclusive_tokens - 1
            + policy.minimum_reference_reserve_tokens
            + policy.minimum_overhead_reserve_tokens
        )
        if policy.package_hard_max_tokens < minimum_required:
            failures.append(
                "RTC package capacity cannot hold the maximum WIP slice plus required "
                "REFERENCE and overhead reserves"
            )
        if failures:
            raise ConfigurationError("Invalid SAW rtc_sizing: " + "; ".join(failures))
        return policy

    def to_dict(self) -> dict[str, Any]:
        """Return the complete release-governed sizing contract."""
        return asdict(self)

    def validate_active_provider(self, provider: str) -> None:
        """Require planning to use the provider whose handoff cap governs the policy."""
        active = provider.strip().lower()
        if active != self.provider:
            raise ConfigurationError(
                f"SAW rtc_sizing is governed for provider {self.provider}, but the active "
                f"workflow provider is {active or 'not configured'}"
            )

    def enforce_handoff(
        self,
        measurement: Mapping[str, Any],
        *,
        scope: str,
    ) -> None:
        """Enforce the complete package and WIP component on an exact provider handoff."""
        projection = measurement.get("evidence_projection")
        by_class = (
            projection.get("by_evidence_class", {})
            if isinstance(projection, Mapping)
            else {}
        )
        subject = by_class.get("SUBJECT_TEXT", {}) if isinstance(by_class, Mapping) else {}
        wip_tokens = int(subject.get("model_estimated_tokens", 0)) if isinstance(subject, Mapping) else 0
        total_tokens = int(measurement.get("total_estimated_tokens", 0))
        total_bytes = int(measurement.get("total_bytes", 0))
        failures: list[str] = []
        if wip_tokens <= 0:
            failures.append("WIP component measurement is missing")
        elif wip_tokens >= self.wip_hard_exclusive_tokens:
            failures.append(
                f"WIP estimated tokens {wip_tokens} >= {self.wip_hard_exclusive_tokens}"
            )
        if total_tokens > self.package_hard_max_tokens:
            failures.append(
                f"package estimated tokens {total_tokens} > {self.package_hard_max_tokens}"
            )
        if total_tokens > self.provider_handoff_max_tokens:
            failures.append(
                f"provider handoff estimated tokens {total_tokens} > "
                f"{self.provider_handoff_max_tokens}"
            )
        if total_bytes > self.package_hard_serialized_bytes:
            failures.append(
                f"package bytes {total_bytes} > {self.package_hard_serialized_bytes}"
            )
        if failures:
            raise EvidenceLimitError(
                "Exact SAW RTC package exceeds governed sizing limits: " + "; ".join(failures),
                code="SAW_RTC_PACKAGE_LIMIT_EXCEEDED",
                affected_scope=scope,
                next_action="Reslice the WIP at a smaller discourse boundary and rebuild the RTC package.",
                details={"handoff": dict(measurement), "rtc_sizing": self.to_dict()},
            )


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
