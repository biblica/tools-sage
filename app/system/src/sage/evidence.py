"""Deterministic evidence serialization, measurement, and hard-limit enforcement."""

from __future__ import annotations

import json
import math
import re
import unicodedata
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
    """Release-governed RTC sizing contract for routed WIP+Reference SFM only."""

    provider: str
    estimator: str
    wip_target_min_tokens: int
    wip_target_max_tokens: int
    wip_hard_exclusive_tokens: int
    route_hard_max_tokens: int
    route_hard_serialized_bytes: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RTCSizingPolicy":
        """Load the SFM-only RTC policy and reject contradictory limits up front."""
        if not isinstance(value, Mapping):
            raise ConfigurationError("RTC sizing must be a mapping")
        text_fields = ("provider", "estimator")
        integer_fields = (
            "wip_target_min_tokens",
            "wip_target_max_tokens",
            "wip_hard_exclusive_tokens",
            "route_hard_max_tokens",
            "route_hard_serialized_bytes",
        )
        missing = [name for name in (*text_fields, *integer_fields) if name not in value]
        if missing:
            raise ConfigurationError(
                "RTC sizing is missing required parameters: " + ", ".join(missing)
            )
        text: dict[str, str] = {}
        for name in text_fields:
            raw = value.get(name)
            if not isinstance(raw, str) or not raw.strip():
                raise ConfigurationError(f"RTC sizing field {name} must be a nonempty string")
            text[name] = raw.strip().lower() if name == "provider" else raw.strip()
        integers: dict[str, int] = {}
        for name in integer_fields:
            raw = value.get(name)
            if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
                raise ConfigurationError(f"RTC sizing field {name} must be a positive integer")
            integers[name] = raw
        policy = cls(**text, **integers)
        failures: list[str] = []
        if policy.wip_target_min_tokens > policy.wip_target_max_tokens:
            failures.append("WIP target minimum exceeds target maximum")
        if policy.wip_target_max_tokens >= policy.wip_hard_exclusive_tokens:
            failures.append("WIP target maximum must be below the exclusive WIP hard maximum")
        if policy.wip_hard_exclusive_tokens > policy.route_hard_max_tokens:
            failures.append("WIP hard maximum exceeds the routed-SFM review-item maximum")
        if failures:
            raise ConfigurationError("Invalid RTC sizing: " + "; ".join(failures))
        return policy

    def to_dict(self) -> dict[str, Any]:
        """Return the complete routed-SFM RTC sizing contract."""
        return asdict(self)

    def validate_active_provider(self, provider: str) -> None:
        """Require planning to use the provider whose routed-SFM cap governs the policy."""
        active = provider.strip().lower()
        if active != self.provider:
            raise ConfigurationError(
                f"RTC sizing is governed for provider {self.provider}, but the active "
                f"workflow provider is {active or 'not configured'}"
            )

    def enforce_route(
        self,
        measurement: Mapping[str, Any],
        *,
        scope: str,
        workflow: str = "rtc",
    ) -> None:
        """Enforce RTC WIP and combined WIP+Reference limits from routed SFM only."""
        projection = measurement.get("evidence_projection")
        by_class = projection.get("by_evidence_class", {}) if isinstance(projection, Mapping) else {}
        subject = by_class.get("SUBJECT_TEXT", {}) if isinstance(by_class, Mapping) else {}
        wip_tokens = int(subject.get("routed_sfm_estimated_tokens", 0)) if isinstance(subject, Mapping) else 0
        route_tokens = int(measurement.get("total_estimated_tokens", 0))
        route_bytes = int(measurement.get("total_bytes", 0))
        failures: list[str] = []
        if wip_tokens <= 0:
            failures.append("WIP routed-SFM measurement is missing")
        elif wip_tokens >= self.wip_hard_exclusive_tokens:
            failures.append(f"WIP estimated tokens {wip_tokens} >= {self.wip_hard_exclusive_tokens}")
        if route_tokens > self.route_hard_max_tokens:
            failures.append(f"routed SFM estimated tokens {route_tokens} > {self.route_hard_max_tokens}")
        if route_bytes > self.route_hard_serialized_bytes:
            failures.append(f"routed SFM bytes {route_bytes} > {self.route_hard_serialized_bytes}")
        if failures:
            legacy = str(workflow).strip().lower() == "saw"
            identity = "Legacy RTC" if legacy else "RTC"
            raise EvidenceLimitError(
                f"{identity} routed-SFM review item exceeds governed sizing limits: " + "; ".join(failures),
                code="SAW_RTC_ROUTE_LIMIT_EXCEEDED" if legacy else "RTC_ROUTE_LIMIT_EXCEEDED",
                affected_scope=scope,
                next_action="Reslice the WIP at a legal discourse boundary and rebuild the RTC review item.",
                details={"routed_sfm": dict(measurement), "rtc_sizing": self.to_dict()},
            )


def serialize_evidence(value: Any) -> bytes:
    """Serialize as compact deterministic UTF-8 JSON for exact context measurement."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


TOKEN_ESTIMATOR = "SAGE_MULTILINGUAL_HEURISTIC_2"

# Tokens per character by Unicode script block, fitted on 2026-10-15 against the o200k_base tokenizer
# (the governed Codex provider) over SFM books in 30 Paratext Projects and the bundled GRK/HEB; see
# docs/advanced/models-and-ai/TOKEN-ESTIMATOR-CALIBRATION.md. Held-out books land within 0.80-1.28x of
# real tokens. Scripts without calibration data cost 1.0 per character, deliberately on the high side.
_SCRIPT_BLOCKS: tuple[tuple[int, int, str], ...] = (
    (0x0591, 0x05AF, "hebrew_cantillation"),
    (0x0590, 0x05FF, "hebrew"),
    (0x0370, 0x03FF, "greek"),
    (0x1F00, 0x1FFF, "greek"),
    (0x0400, 0x052F, "cyrillic"),
    (0x0600, 0x06FF, "arabic"),
    (0x0750, 0x077F, "arabic"),
    (0x08A0, 0x08FF, "arabic"),
    (0xFB50, 0xFDFF, "arabic"),
    (0xFE70, 0xFEFF, "arabic"),
    (0x0900, 0x097F, "devanagari"),
    (0x0980, 0x09FF, "bengali"),
    (0x0A00, 0x0A7F, "gurmukhi"),
    (0x0B00, 0x0B7F, "oriya"),
    (0x0D00, 0x0D7F, "malayalam"),
    (0x0D80, 0x0DFF, "sinhala"),
    (0x0E00, 0x0E7F, "thai"),
    (0x0E80, 0x0EFF, "lao"),
    (0x1200, 0x139F, "ethiopic"),
    (0x3000, 0x9FFF, "cjk"),
    (0xFF00, 0xFFEF, "cjk"),
)
_TOKENS_PER_CHARACTER: dict[str, float] = {
    "ascii_alnum": 0.1608,
    "ascii_punct": 2.1525,  # USFM markers (\v, \q1) and punctuation: almost every one is its own token
    "ascii_space": 0.4702,
    "latin_ext": 0.5,  # floor: too rare in the calibration texts to fit; protects e.g. Vietnamese
    "symbol": 0.5,  # floor for non-ASCII punctuation such as curly quotes and dashes
    "hebrew": 0.9708,
    "hebrew_cantillation": 2.1091,
    "greek": 0.7345,
    "cyrillic": 0.2927,
    "arabic": 0.3277,
    "arabic_mark": 1.0901,
    "devanagari": 0.3388,
    "bengali": 0.3095,
    "gurmukhi": 0.4756,
    "oriya": 1.1086,
    "malayalam": 0.3267,
    "sinhala": 0.4986,
    "thai": 0.2422,
    "lao": 1.6574,
    "ethiopic": 2.1597,
    "cjk": 1.0026,
}
_UNCALIBRATED_TOKENS_PER_CHARACTER = 1.0
_character_cost_cache: dict[str, float] = {}


def _character_cost(char: str) -> float:
    """Return the calibrated token cost of one character."""
    cost = _character_cost_cache.get(char)
    if cost is not None:
        return cost
    point = ord(char)
    if point < 128:
        kind = "ascii_alnum" if char.isalnum() else "ascii_space" if char.isspace() else "ascii_punct"
    else:
        kind = next((name for start, end, name in _SCRIPT_BLOCKS if start <= point <= end), "")
        category = unicodedata.category(char)
        if kind == "arabic" and category.startswith("M"):
            kind = "arabic_mark"
        elif not kind:
            if point <= 0x024F or 0x1E00 <= point <= 0x1EFF or 0x0300 <= point <= 0x036F:
                kind = "latin_ext"
            elif category[0] in "PSZ":
                kind = "symbol"
    cost = _TOKENS_PER_CHARACTER.get(kind, _UNCALIBRATED_TOKENS_PER_CHARACTER)
    _character_cost_cache[char] = cost
    return cost


def estimate_tokens(text: str) -> int:
    """Return a multilingual token estimate calibrated per script (`TOKEN_ESTIMATOR`).

    SAGE records this as an estimate, never as an exact model-token count. The
    actual serialized byte count remains an independent hard guard.
    """
    return max(1, math.ceil(sum(_character_cost(char) for char in text)))


def evidence_within_limits(
    measurement: EvidenceMeasurement,
    policy: EvidencePolicy,
    *,
    primary_verse_units: int,
) -> bool:
    """Return whether one routed-SFM measurement fits all governed hard limits."""
    return (
        measurement.serialized_bytes <= policy.hard_serialized_bytes
        and measurement.estimated_tokens <= policy.hard_estimated_tokens
        and primary_verse_units <= policy.maximum_primary_verse_units
    )
