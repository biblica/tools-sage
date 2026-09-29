"""Build bounded NCA extraction requests and validate exact model evidence.

Simplified per the 2026-09-28 rewrite: a work unit's response is just its
ordered numeric values (canonical rational strings, in reading order) plus
honest completeness -- no spans, kinds, qualifiers, roles, or representations.
Comparison against the indexed expected values happens later, locally, in
numbers/compare.py -- extraction never sees the expected values.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Any, Mapping

from sage.errors import ValidationError

from .batching import ExtractionBatch
from .transport import _digest
from .models import (
    freeze,
    EXTRACTION_STATUSES,
    Extraction,
)


_RATIONAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")
_PARSING_FIELDS: dict[str, frozenset[str]] = {
    "digits": frozenset({"preferred", "allowed"}),
    "grouping": frozenset({"style", "separator"}),
    "decimal": frozenset({"separator"}),
    "fractions": frozenset({"notation", "forms"}),
    "ranges": frozenset({"separator"}),
    "qualifiers": frozenset({"forms", "markers"}),
    "units": frozenset({"forms", "abbreviations"}),
}


def _error(message: str, *, code: str) -> ValidationError:
    """Build one stable NCA extraction validation error."""
    return ValidationError(message, code=code)


def _require_object(value: object, label: str, *, code: str) -> Mapping[str, Any]:
    """Require one string-keyed response mapping."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _error(f"{label} must be an object", code=code)
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
    code: str,
) -> None:
    """Reject missing and invented structured-response fields."""
    keys = set(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise _error(f"{label} has " + "; ".join(details), code=code)


def _require_list(value: object, label: str, *, code: str) -> list[Any]:
    """Require one JSON array without accepting tuple aliases."""
    if not isinstance(value, list):
        raise _error(f"{label} must be an array", code=code)
    return value


def _require_text(value: object, label: str, *, allow_empty: bool = False) -> str:
    """Require one response string and optionally reject blank evidence."""
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _error(f"{label} must be a non-empty string", code="NCA_EXTRACTION_SCHEMA_INVALID")
    return value


def _fraction(value: object, label: str) -> Fraction:
    """Parse one canonical reduced rational string without float conversion."""
    if not isinstance(value, str) or not _RATIONAL.fullmatch(value):
        raise _error(
            f"{label} must be a canonical rational string",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        )
    try:
        parsed = Fraction(value)
        canonical = str(parsed)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise _error(
            f"{label} cannot be represented as an exact rational",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        ) from exc
    if canonical != value:
        raise _error(
            f"{label} must be reduced and normalized",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        )
    return parsed


def _safe_convention_value(value: object) -> object:
    """Copy only inert JSON-like convention data from an already validated profile."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_convention_value(item) for item in value]
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {str(key): _safe_convention_value(item) for key, item in value.items()}
    raise _error(
        "Style parsing conventions contain an unsupported value",
        code="NCA_EXTRACTION_PAYLOAD_INVALID",
    )


def _parsing_conventions(style_profile: Mapping[str, object]) -> dict[str, object]:
    """Select only fields that help interpret numeric surface notation."""
    rules = style_profile.get("rules", {})
    if not isinstance(rules, Mapping):
        return {}
    result: dict[str, object] = {}
    for area, allowed in _PARSING_FIELDS.items():
        raw = rules.get(area)
        if not isinstance(raw, Mapping):
            continue
        selected = {
            field: _safe_convention_value(raw[field])
            for field in sorted(allowed)
            if field in raw
        }
        if selected:
            result[area] = selected
    return result


def _validated_extraction_item(raw: Mapping[str, Any]) -> Extraction:
    """Validate status and the ordered numeric values found in one work unit."""
    status = _require_text(raw["status"], "status")
    if status not in EXTRACTION_STATUSES:
        raise _error("Extraction status is unsupported", code="NCA_EXTRACTION_SCHEMA_INVALID")
    limitations = tuple(
        _require_text(value, f"limitations[{index}]")
        for index, value in enumerate(
            _require_list(raw["limitations"], "limitations", code="NCA_EXTRACTION_SCHEMA_INVALID")
        )
    )
    if status != "COMPLETE" and not limitations:
        raise _error("Incomplete extraction must state a limitation", code="NCA_EXTRACTION_SCHEMA_INVALID")
    values = tuple(
        _fraction(value, f"values[{index}]")
        for index, value in enumerate(
            _require_list(raw["values"], "values", code="NCA_EXTRACTION_SCHEMA_INVALID")
        )
    )
    return Extraction(values=values, status=status, limitations=limitations)


@dataclass(frozen=True)
class BatchValidation:
    """Independently admitted members with controller-owned response item hashes."""

    accepted: Mapping[str, Extraction]
    pending: Mapping[str, str]
    batch_id: str
    item_sha256: Mapping[str, str]

    def __post_init__(self) -> None:
        """Own immutable results and require disjoint, fully hashed accepted membership."""
        if (not isinstance(self.batch_id, str) or not self.batch_id
                or not isinstance(self.accepted, Mapping) or not isinstance(self.pending, Mapping)
                or not isinstance(self.item_sha256, Mapping)
                or set(self.accepted).intersection(self.pending)
                or set(self.item_sha256) != set(self.accepted)
                or any(not isinstance(key, str) or not key for key in (*self.accepted, *self.pending))
                or any(not isinstance(value, Extraction) for value in self.accepted.values())
                or any(not isinstance(value, str) or not value for value in self.pending.values())
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in self.item_sha256.values())):
            raise _error("Invalid batch validation binding", code="NCA_BATCH_COVERAGE_INVALID")
        for field in ("accepted", "pending", "item_sha256"):
            object.__setattr__(self, field, freeze(getattr(self, field)))


def build_batch_extraction_payload(
    batch: ExtractionBatch, *, parsing_conventions: Mapping[str, object],
) -> Mapping[str, object]:
    """Send only bound target streams, routed SFM, and allowlisted parsing conventions."""
    if not isinstance(batch, ExtractionBatch) or not isinstance(parsing_conventions, Mapping):
        raise _error("Invalid batch extraction input", code="NCA_EXTRACTION_PAYLOAD_INVALID")
    conventions = _parsing_conventions({"rules": parsing_conventions})
    if (any(value.conventions_sha256 != _digest(conventions) for value in batch.inputs)
            or len({(value.language, value.purpose) for value in batch.inputs}) != 1):
        raise _error("Batch extraction conventions differ", code="NCA_EXTRACTION_PAYLOAD_INVALID")
    return {
        "schema_version": "1.0", "phase": "EXTRACTION", "batch_id": batch.batch_id,
        "language": batch.inputs[0].language,
        "routed_sfm": batch.routed_sfm,
        "work_units": [{"input_id": value.input_id, "stream_id": value.stream_id,
                        "text": value.text} for value in batch.inputs],
        "parsing_conventions": conventions,
        "output_schema_id": "sage-nca-extraction-1.0#extraction",
    }


def validate_batch_extraction_response(
    batch: ExtractionBatch, response: Mapping[str, object],
) -> BatchValidation:
    """Reconcile envelope identities first, then validate known members independently."""
    code = "NCA_EXTRACTION_SCHEMA_INVALID"
    coverage = "NCA_BATCH_COVERAGE_INVALID"
    if not isinstance(batch, ExtractionBatch):
        raise _error("Invalid extraction batch", code=coverage)
    root = _require_object(response, "response", code=code)
    _require_exact_keys(root, required=frozenset({"schema_version", "phase", "batch_id", "work_units"}),
                        label="response", code=code)
    if root["schema_version"] != "1.0" or root["phase"] != "EXTRACTION":
        raise _error("Extraction response identity is invalid", code=code)
    if root["batch_id"] != batch.batch_id:
        raise _error("Invalid batch identities", code=coverage)
    rows = _require_list(root["work_units"], "work_units", code=code)
    received = []
    for row in rows:
        item = _require_object(row, "work unit", code=coverage)
        if not isinstance(item.get("input_id"), str) or not item["input_id"]:
            raise _error("Invalid batch identities", code=coverage)
        received.append(item["input_id"])
    expected = {item.input_id for item in batch.inputs}
    if len(received) != len(set(received)) or set(received) - expected:
        raise _error("Invalid batch identities", code=coverage)
    by_id = dict(zip(received, rows))
    accepted, pending, hashes = {}, {}, {}
    for value in batch.inputs:
        raw = by_id.get(value.input_id)
        if raw is None:
            pending[value.input_id] = "NCA_BATCH_INPUT_MISSING"
            continue
        try:
            _require_exact_keys(raw, required=frozenset({"input_id", "status", "limitations", "values"}),
                                label="work unit", code=code)
            accepted[value.input_id] = _validated_extraction_item(raw)
        except ValidationError as exc:
            pending[value.input_id] = str(exc.code)
            continue
        hashes[value.input_id] = _digest({"batch_id": batch.batch_id, "input_id": value.input_id,
                                         "projection_sha256": value.projection_sha256, "item": raw})
    return BatchValidation(accepted, pending, batch.batch_id, hashes)
