"""Deterministic evidence serialization, measurement, and hard-limit enforcement."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from .errors import ConfigurationError, EvidenceLimitError, ValidationError

WORD_RE = re.compile(r"\w+", re.UNICODE)
# S/M/L work-unit size (an AI setting): the multiplier applied to every token and byte budget.
WORK_UNIT_SIZES = {"S": 0.5, "M": 1.0, "L": 2.0}


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

    def scaled(self, size_multiplier: float, target_scale: float) -> "EvidencePolicy":
        """Return this policy for one work-unit size and learned correction.

        Hard limits and the verse cap follow the size only; soft targets also shrink by the
        correction (`target_scale` = size / correction), so units are planned smaller without ever
        tightening the limits a previously planned unit is checked against.
        """
        if size_multiplier == 1.0 and target_scale == 1.0:
            return self
        hard = max(1, round(self.hard_estimated_tokens * size_multiplier))
        target = min(hard, max(1, round(self.target_estimated_tokens * target_scale)))
        preferred = (
            min(hard, max(target, round(self.preferred_max_estimated_tokens * target_scale)))
            if self.preferred_max_estimated_tokens
            else 0
        )
        return replace(
            self,
            target_estimated_tokens=target,
            hard_estimated_tokens=hard,
            hard_serialized_bytes=max(1, round(self.hard_serialized_bytes * size_multiplier)),
            minimum_target_tokens=min(target, round(self.minimum_target_tokens * target_scale)),
            preferred_max_estimated_tokens=preferred,
            maximum_primary_verse_units=max(1, round(self.maximum_primary_verse_units * size_multiplier)),
        )


@dataclass(frozen=True)
class RTCSizingPolicy:
    """Release-governed RTC sizing contract for routed WIP+Reference SFM only.

    The token fields are the profile's base (work-unit size M) values, counted in the tokens of
    `token_table` (the selected provider's tokenizer). `work_unit_size` scales every limit;
    `token_correction` (learned from real usage, >= 1.0) additionally shrinks only the WIP planning
    targets. Hard limits never depend on the correction.
    """

    estimator: str
    wip_target_min_tokens: int
    wip_target_max_tokens: int
    wip_hard_exclusive_tokens: int
    route_hard_max_tokens: int
    route_hard_serialized_bytes: int
    work_unit_size: str = "M"
    token_correction: float = 1.0
    token_table: str = "o200k-2026-10-15"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RTCSizingPolicy":
        """Load the SFM-only RTC policy and reject contradictory limits up front."""
        if not isinstance(value, Mapping):
            raise ConfigurationError("RTC sizing must be a mapping")
        integer_fields = (
            "wip_target_min_tokens",
            "wip_target_max_tokens",
            "wip_hard_exclusive_tokens",
            "route_hard_max_tokens",
            "route_hard_serialized_bytes",
        )
        missing = [name for name in ("estimator", *integer_fields) if name not in value]
        if missing:
            raise ConfigurationError(
                "RTC sizing is missing required parameters: " + ", ".join(missing)
            )
        estimator = value.get("estimator")
        if not isinstance(estimator, str) or not estimator.strip():
            raise ConfigurationError("RTC sizing field estimator must be a nonempty string")
        integers: dict[str, int] = {}
        for name in integer_fields:
            raw = value.get(name)
            if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
                raise ConfigurationError(f"RTC sizing field {name} must be a positive integer")
            integers[name] = raw
        size = str(value.get("work_unit_size", "M"))
        if size not in WORK_UNIT_SIZES:
            raise ConfigurationError(f"RTC sizing work_unit_size must be one of {', '.join(WORK_UNIT_SIZES)}")
        correction = value.get("token_correction", 1.0)
        if not isinstance(correction, (int, float)) or isinstance(correction, bool) or correction < 1.0:
            raise ConfigurationError("RTC sizing token_correction must be a number >= 1.0")
        # A provider binding is no longer part of the contract: one unified estimator sizes every
        # governed provider. A legacy `provider` key is accepted and ignored.
        policy = cls(
            estimator=estimator.strip(),
            **integers,
            work_unit_size=size,
            token_correction=float(correction),
        )
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

    def adjusted(self, work_unit_size: str, token_correction: float, token_table: str) -> "RTCSizingPolicy":
        """Return this contract for one work-unit size, learned correction, and provider token table."""
        return replace(
            self, work_unit_size=work_unit_size, token_correction=float(token_correction), token_table=token_table
        )

    @property
    def size_multiplier(self) -> float:
        """Return the S/M/L multiplier of this contract."""
        return WORK_UNIT_SIZES[self.work_unit_size]

    def _hard(self, base: int) -> int:
        """Scale one hard limit by the work-unit size only."""
        return max(1, round(base * self.size_multiplier))

    def _target(self, base: int) -> int:
        """Scale one planning target by the size and shrink it by the learned correction."""
        return max(1, round(base * self.size_multiplier / self.token_correction))

    @property
    def effective_wip_target_min_tokens(self) -> int:
        """Return the effective lower WIP planning target."""
        return self._target(self.wip_target_min_tokens)

    @property
    def effective_wip_target_max_tokens(self) -> int:
        """Return the effective upper WIP planning target, kept below the WIP hard maximum."""
        return min(self._target(self.wip_target_max_tokens), self.effective_wip_hard_exclusive_tokens - 1)

    @property
    def effective_wip_hard_exclusive_tokens(self) -> int:
        """Return the effective exclusive WIP hard maximum."""
        return self._hard(self.wip_hard_exclusive_tokens)

    @property
    def effective_route_hard_max_tokens(self) -> int:
        """Return the effective routed-SFM review-item token maximum."""
        return self._hard(self.route_hard_max_tokens)

    @property
    def effective_route_hard_serialized_bytes(self) -> int:
        """Return the effective routed-SFM review-item byte maximum."""
        return self._hard(self.route_hard_serialized_bytes)

    def same_contract(self, recorded: Mapping[str, Any]) -> bool:
        """Return whether a recorded contract matches this one, ignoring its frozen correction.

        A plan approved before work-unit sizes and token tables existed recorded a `provider` and
        neither field; it was sized at M with the o200k table, so it stays valid exactly then.
        """
        legacy_defaults = {"work_unit_size": "M", "token_table": "o200k-2026-10-15"}
        normalized = {**legacy_defaults, **{key: value for key, value in dict(recorded).items() if key != "provider"}}
        current = {key: value for key, value in self.to_dict().items() if key != "token_correction"}
        return current == {key: value for key, value in normalized.items() if key != "token_correction"}

    def validate_active_provider(self, provider: str) -> None:
        """Require a governed provider; the unified estimator sizes routed SFM for every one."""
        from .build_policy import GOVERNED_CLI_PROVIDER_IDS

        active = provider.strip().lower()
        if active not in GOVERNED_CLI_PROVIDER_IDS:
            raise ConfigurationError(
                f"RTC sizing needs a governed workflow provider, but the active provider is {active or 'not configured'}"
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
        wip_hard = self.effective_wip_hard_exclusive_tokens
        route_hard = self.effective_route_hard_max_tokens
        bytes_hard = self.effective_route_hard_serialized_bytes
        failures: list[str] = []
        if wip_tokens <= 0:
            failures.append("WIP routed-SFM measurement is missing")
        elif wip_tokens >= wip_hard:
            failures.append(f"WIP estimated tokens {wip_tokens} >= {wip_hard}")
        if route_tokens > route_hard:
            failures.append(f"routed SFM estimated tokens {route_tokens} > {route_hard}")
        if route_bytes > bytes_hard:
            failures.append(f"routed SFM bytes {route_bytes} > {bytes_hard}")
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

# Tokens per character by Unicode script block, one table per governed tokenizer, selected from the
# provider and routed model (`token_table_for`). Calibrated with system/tools/calibrate_token_estimator.py;
# see docs/advanced/models-and-ai/TOKEN-ESTIMATOR-CALIBRATION.md. Scripts without calibration data cost
# 1.0 per character, deliberately on the high side.
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
O200K_TABLE = "o200k-2026-10-15"
CLAUDE_TABLE = "claude-2026-10-22"
TOKEN_TABLES: dict[str, dict[str, float]] = {
    # Codex (o200k_base), fitted 2026-10-15 on John and Psalms of 30 translations plus GRK/HEB; held-out
    # books land within 0.80-1.28x of real tokens (re-checked 2026-10-22 on fresh samples: 0.94-1.28x).
    O200K_TABLE: {
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
    },
    # Claude Opus 5.5 and Sonnet 5.5 (identical counts), fitted 2026-10-22 on one chapter per script
    # from 24 translations plus GRK/HEB; held-out chapters land within 0.88-1.37x of real tokens. The
    # same Scripture costs a median 1.6x the o200k tokens (Punjabi 3.9x, Lao and Tigrinya under 1x).
    CLAUDE_TABLE: {
        "ascii_alnum": 0.3315,
        "ascii_punct": 3.8635,
        "ascii_space": 0.4702,
        "latin_ext": 0.5,
        "symbol": 0.5,
        "hebrew": 1.1166,
        "hebrew_cantillation": 3.2882,
        "greek": 1.0802,
        "cyrillic": 0.2008,
        "arabic": 0.6725,
        "arabic_mark": 1.3225,
        "devanagari": 0.6127,
        "bengali": 0.8395,
        "gurmukhi": 2.3878,
        "oriya": 1.715,
        "malayalam": 1.0413,
        "sinhala": 0.9499,
        "thai": 0.3686,
        "lao": 1.0952,
        "ethiopic": 1.663,
        "cjk": 0.918,
    },
}
_TOKENS_PER_CHARACTER = TOKEN_TABLES[O200K_TABLE]
_UNCALIBRATED_TOKENS_PER_CHARACTER = 1.0
_character_cost_cache: dict[tuple[str, str], float] = {}
_active_token_table = O200K_TABLE


def token_table_for(provider: str, model: str | None = None) -> str:
    """Return the weight table for one provider's tokenizer (Claude models share one tokenizer)."""
    del model  # Opus 5.5 and Sonnet 5.5 measured identical; Haiku is learned by the token correction.
    return CLAUDE_TABLE if provider.strip().lower() == "claude" else O200K_TABLE


def set_token_table(table: str) -> None:
    """Select the weight table `estimate_tokens` uses for the selected provider."""
    global _active_token_table
    if table not in TOKEN_TABLES:
        raise ConfigurationError(f"Unknown token table: {table}")
    _active_token_table = table


def active_token_table() -> str:
    """Return the weight table currently used by `estimate_tokens`."""
    return _active_token_table


def character_class(char: str) -> str:
    """Return the estimator class of one character ("" for an uncalibrated script)."""
    point = ord(char)
    if point < 128:
        return "ascii_alnum" if char.isalnum() else "ascii_space" if char.isspace() else "ascii_punct"
    kind = next((name for start, end, name in _SCRIPT_BLOCKS if start <= point <= end), "")
    category = unicodedata.category(char)
    if kind == "arabic" and category.startswith("M"):
        return "arabic_mark"
    if not kind:
        if point <= 0x024F or 0x1E00 <= point <= 0x1EFF or 0x0300 <= point <= 0x036F:
            return "latin_ext"
        if category[0] in "PSZ":
            return "symbol"
    return kind


def _character_cost(char: str, table: str) -> float:
    """Return the calibrated token cost of one character in one weight table."""
    key = (table, char)
    cost = _character_cost_cache.get(key)
    if cost is not None:
        return cost
    cost = TOKEN_TABLES[table].get(character_class(char), _UNCALIBRATED_TOKENS_PER_CHARACTER)
    _character_cost_cache[key] = cost
    return cost


def estimate_tokens(text: str, table: str | None = None) -> int:
    """Return a multilingual token estimate calibrated per script (`TOKEN_ESTIMATOR`).

    `table` defaults to the selected provider's table (`set_token_table`). SAGE records this as an
    estimate, never as an exact model-token count. The actual serialized byte count remains an
    independent hard guard.
    """
    name = table or _active_token_table
    return max(1, math.ceil(sum(_character_cost(char, name) for char in text)))


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
