"""Build bounded NCA extraction requests and validate exact model evidence."""

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
    NUMERIC_KINDS,
    NUMERIC_QUALIFIERS,
    Extraction,
    NumericExpression,
    TargetUnit,
)


EXTRACTION_SCHEMA_ID = "sage-nca-extraction-1.0#extraction"
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


def _span(value: object, text: str, surface: object, label: str) -> tuple[int, int]:
    """Validate one exact half-open span and its quoted source surface."""
    raw = _require_object(value, f"{label} span", code="NCA_EXTRACTION_EVIDENCE_INVALID")
    _require_exact_keys(
        raw,
        required=frozenset({"start", "end"}),
        label=f"{label} span",
        code="NCA_EXTRACTION_EVIDENCE_INVALID",
    )
    start, end = raw["start"], raw["end"]
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 0
        or end <= start
        or end > len(text)
        or not isinstance(surface, str)
        or text[start:end] != surface
    ):
        raise _error(
            f"{label} does not quote its exact source span",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        )
    return start, end


def _fraction(value: object, label: str) -> Fraction:
    """Parse one canonical reduced rational string without float conversion."""
    if not isinstance(value, str) or not _RATIONAL.fullmatch(value):
        raise _error(
            f"{label} must be a canonical rational string",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        )
    parsed = Fraction(value)
    if str(parsed) != value:
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


def build_extraction_payload(
    unit: TargetUnit,
    *,
    language: str,
    style_profile: Mapping[str, object],
) -> Mapping[str, object]:
    """Return target-only extraction input with allowlisted parsing conventions."""
    if not isinstance(unit, TargetUnit):
        raise _error("Extraction unit must be a TargetUnit", code="NCA_EXTRACTION_PAYLOAD_INVALID")
    if not isinstance(language, str) or not language.strip():
        raise _error("Extraction language must be explicit", code="NCA_EXTRACTION_PAYLOAD_INVALID")
    if not isinstance(style_profile, Mapping):
        raise _error("Extraction style profile must be a mapping", code="NCA_EXTRACTION_PAYLOAD_INVALID")
    return {
        "schema_version": "1.0",
        "phase": "EXTRACTION",
        "language": language,
        "work_units": [
            {
                "unit_id": unit.unit_id,
                "streams": [{"stream_id": "main", "text": unit.main_text}],
            }
        ],
        "parsing_conventions": _parsing_conventions(style_profile),
        "output_schema_id": EXTRACTION_SCHEMA_ID,
    }


def _validated_representations(
    raw_values: object,
    *,
    text: str,
    expression_values: tuple[Fraction, ...],
    expression_span: tuple[int, int],
) -> tuple[Mapping[str, object], ...]:
    """Validate dual-form evidence and require all representations to agree."""
    rows = _require_list(raw_values, "representations", code="NCA_EXTRACTION_SCHEMA_INVALID")
    result: list[Mapping[str, object]] = []
    seen: set[tuple[int, int]] = set()
    for index, value in enumerate(rows):
        raw = _require_object(
            value,
            f"representations[{index}]",
            code="NCA_EXTRACTION_SCHEMA_INVALID",
        )
        _require_exact_keys(
            raw,
            required=frozenset({"surface", "span", "value"}),
            label=f"representations[{index}]",
            code="NCA_EXTRACTION_SCHEMA_INVALID",
        )
        surface = _require_text(raw["surface"], f"representations[{index}].surface")
        span = _span(raw["span"], text, surface, f"representations[{index}]")
        value_fraction = _fraction(raw["value"], f"representations[{index}].value")
        if (
            span in seen
            or span[0] < expression_span[0]
            or span[1] > expression_span[1]
            or len(expression_values) != 1
            or value_fraction != expression_values[0]
        ):
            raise _error(
                "Representations must be distinct, contained, and numerically equal",
                code="NCA_EXTRACTION_EVIDENCE_INVALID",
            )
        seen.add(span)
        result.append({"surface": surface, "span": span, "value": str(value_fraction)})
    return tuple(result)


def _validated_role_spans(raw_values: object, *, text: str) -> tuple[tuple[int, int], ...]:
    """Validate exact target referent spans while retaining their offsets."""
    rows = _require_list(raw_values, "role_spans", code="NCA_EXTRACTION_SCHEMA_INVALID")
    result: list[tuple[int, int]] = []
    for index, value in enumerate(rows):
        raw = _require_object(value, f"role_spans[{index}]", code="NCA_EXTRACTION_SCHEMA_INVALID")
        _require_exact_keys(
            raw,
            required=frozenset({"start", "end", "surface"}),
            label=f"role_spans[{index}]",
            code="NCA_EXTRACTION_SCHEMA_INVALID",
        )
        span = _span(
            {"start": raw["start"], "end": raw["end"]},
            text,
            raw["surface"],
            f"role_spans[{index}]",
        )
        if span in result:
            raise _error("Duplicate role evidence span", code="NCA_EXTRACTION_EVIDENCE_INVALID")
        result.append(span)
    return tuple(result)


def _validated_expression(
    raw_value: object,
    *,
    text: str,
    expected_stream_id: str = "main",
) -> NumericExpression:
    """Convert one structurally valid exact response expression to its typed model."""
    raw = _require_object(raw_value, "expression", code="NCA_EXTRACTION_SCHEMA_INVALID")
    required = frozenset(
        {
            "expression_id",
            "stream_id",
            "surface",
            "span",
            "values",
            "kind",
            "unit",
            "qualifier",
            "role",
            "role_spans",
            "representations",
        }
    )
    _require_exact_keys(
        raw,
        required=required,
        label="expression",
        code="NCA_EXTRACTION_SCHEMA_INVALID",
    )
    expression_id = _require_text(raw["expression_id"], "expression.expression_id")
    stream_id = _require_text(raw["stream_id"], "expression.stream_id")
    if stream_id != expected_stream_id:
        raise _error("Expression uses an unknown evidence stream", code="NCA_EXTRACTION_EVIDENCE_INVALID")
    surface = _require_text(raw["surface"], "expression.surface")
    span = _span(raw["span"], text, surface, "expression")
    values = tuple(
        _fraction(value, f"expression.values[{index}]")
        for index, value in enumerate(
            _require_list(raw["values"], "expression.values", code="NCA_EXTRACTION_SCHEMA_INVALID")
        )
    )
    if not values:
        raise _error("Expression values cannot be empty", code="NCA_EXTRACTION_SCHEMA_INVALID")
    kind = _require_text(raw["kind"], "expression.kind")
    qualifier = _require_text(raw["qualifier"], "expression.qualifier")
    if kind not in NUMERIC_KINDS or qualifier not in NUMERIC_QUALIFIERS:
        raise _error("Expression kind or qualifier is unsupported", code="NCA_EXTRACTION_SCHEMA_INVALID")
    expected_arity = 2 if kind in {"RANGE", "RATIO"} else 1
    if len(values) != expected_arity:
        raise _error(
            "Expression kind and value arity disagree",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        )
    unit = raw["unit"]
    role = raw["role"]
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise _error("Expression unit must be null or non-empty text", code="NCA_EXTRACTION_SCHEMA_INVALID")
    if role is not None and (not isinstance(role, str) or not role.strip()):
        raise _error("Expression role must be null or non-empty text", code="NCA_EXTRACTION_SCHEMA_INVALID")
    representations = _validated_representations(
        raw["representations"],
        text=text,
        expression_values=values,
        expression_span=span,
    )
    parenthesis = surface.find("(")
    if (
        parenthesis > 0
        and any(character.isdecimal() for character in surface)
        and len(representations) < 2
    ):
        raise _error(
            "A words-plus-digits expression must retain both representation spans",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        )
    role_spans = _validated_role_spans(raw["role_spans"], text=text)
    return NumericExpression(
        values=values,
        kind=kind,
        surface=surface,
        span=span,
        unit=unit,
        qualifier=qualifier,
        role=role,
        expression_id=expression_id,
        stream_id=stream_id,
        representations=representations,
        role_spans=role_spans,
    )


def validate_extraction_response(
    unit: TargetUnit,
    response: Mapping[str, object],
) -> Extraction:
    """Validate complete unit coverage and exact target-bound numeric evidence."""
    root = _require_object(response, "response", code="NCA_EXTRACTION_SCHEMA_INVALID")
    _require_exact_keys(
        root,
        required=frozenset({"schema_version", "phase", "work_units"}),
        label="response",
        code="NCA_EXTRACTION_SCHEMA_INVALID",
    )
    if root["schema_version"] != "1.0" or root["phase"] != "EXTRACTION":
        raise _error("Extraction response identity is invalid", code="NCA_EXTRACTION_SCHEMA_INVALID")
    work_units = _require_list(root["work_units"], "work_units", code="NCA_EXTRACTION_SCHEMA_INVALID")
    if len(work_units) != 1:
        raise _error("Extraction response must cover exactly one work unit", code="NCA_EXTRACTION_COVERAGE_INVALID")
    raw = _require_object(work_units[0], "work_units[0]", code="NCA_EXTRACTION_SCHEMA_INVALID")
    _require_exact_keys(
        raw,
        required=frozenset({"unit_id", "status", "limitations", "expressions"}),
        optional=frozenset({"confidence"}),
        label="work_units[0]",
        code="NCA_EXTRACTION_SCHEMA_INVALID",
    )
    if raw["unit_id"] != unit.unit_id:
        raise _error("Extraction response covers the wrong work unit", code="NCA_EXTRACTION_COVERAGE_INVALID")
    return _validated_extraction_item(raw, text=unit.main_text, stream_id="main")


def _validated_extraction_item(
    raw: Mapping[str, Any], *, text: str, stream_id: str,
) -> Extraction:
    """Validate status and exact expressions in one admitted offset domain."""
    status = _require_text(raw["status"], "work_units[0].status")
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
    expressions = tuple(
        _validated_expression(value, text=text, expected_stream_id=stream_id)
        for value in _require_list(raw["expressions"], "expressions", code="NCA_EXTRACTION_SCHEMA_INVALID")
    )
    ids = [item.expression_id for item in expressions]
    spans = [item.span for item in expressions]
    if len(ids) != len(set(ids)) or len(spans) != len(set(spans)):
        raise _error("Extraction contains duplicate expression evidence", code="NCA_EXTRACTION_EVIDENCE_INVALID")
    ordered_spans = sorted(spans)
    if any(start < previous_end for (_previous_start, previous_end), (start, _end) in zip(ordered_spans, ordered_spans[1:])):
        raise _error("Extraction contains overlapping expression evidence", code="NCA_EXTRACTION_EVIDENCE_INVALID")
    return Extraction(expressions=expressions, status=status, limitations=limitations)


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
        "schema_version": "2.0", "phase": "EXTRACTION", "batch_id": batch.batch_id,
        "language": batch.inputs[0].language,
        "routed_sfm": batch.routed_sfm,
        "work_units": [{"input_id": value.input_id, "stream_id": value.stream_id,
                        "text": value.text} for value in batch.inputs],
        "parsing_conventions": conventions,
        "output_schema_id": "sage-nca-extraction-2.0#extraction",
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
    if root["schema_version"] != "2.0" or root["phase"] != "EXTRACTION":
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
            _require_exact_keys(raw, required=frozenset({"input_id", "status", "limitations", "expressions"}),
                                label="work unit", code=code)
            accepted[value.input_id] = _validated_extraction_item(raw, text=value.text, stream_id=value.stream_id)
        except ValidationError as exc:
            pending[value.input_id] = str(exc.code)
            continue
        hashes[value.input_id] = _digest({"batch_id": batch.batch_id, "input_id": value.input_id,
                                         "projection_sha256": value.projection_sha256, "item": raw})
    return BatchValidation(accepted, pending, batch.batch_id, hashes)
