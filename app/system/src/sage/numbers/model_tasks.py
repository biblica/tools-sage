"""Execute explicit NCA interpretation phases through one pinned SAGE model route."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from copy import deepcopy
from time import perf_counter_ns
from uuid import uuid4
from types import MappingProxyType
from typing import Any, Callable, Generic, Mapping, TypeVar

from sage.errors import ValidationError
from sage.executors import Executor, ProviderRequest
from sage.llm_settings import load_llm_settings
from sage.llm_tasks import _resolve_task_route, _validate_provider_response_route
from sage.model_policy import cache_provider_catalog
from sage.registry import EcosystemConfig
from sage.routing_override import resolve_routing_mode

from .batching import ExtractionBatch, _batch, split_batch
from .telemetry import CallMeasurement
from .extraction import (
    BatchValidation,
    build_batch_extraction_payload,
    validate_batch_extraction_response,
    _span,
    _validated_expression,
    _validated_role_spans,
    build_extraction_payload,
    validate_extraction_response,
)
from .models import (
    EXTRACTION_STATUSES,
    FOOTNOTE_ACTIONS,
    FOOTNOTE_OUTCOMES,
    FOOTNOTE_STATUSES,
    NUMERIC_KINDS,
    NUMERIC_QUALIFIERS,
    Extraction,
    FootnoteDecision,
    NumericExpression,
    ReferenceRow,
    TargetNote,
    TargetUnit,
    freeze,
)


SKILL_ID = "nca-numbers"
_TASK_VERSIONS = {
    "EXTRACTION": "nca-extraction-1.0",
    "CORRESPONDENCE": "nca-correspondence-1.0",
    "FOOTNOTE": "nca-footnote-1.0",
}
_PHASE_INSTRUCTIONS = {
    "GROUP_CORRESPONDENCE": (
        "Adjudicate this one protected target bridge against separately keyed source rows. "
        "Assign each atomic target expression to at most one Western row, or mark it unmatched or unresolved. "
        "Return exact per-row OL source and target referent spans, preserving source order, multiplicity, "
        "ranges, ratios and dual forms. Registered candidates belong only to their named row. "
        "Never infer an empty source for an unindexed row; ambiguous allocation remains PARTIAL."
    ),
    "EXTRACTION": (
        "Interpret every numeric expression in the supplied target main stream. Return exact "
        "half-open spans, quoted surfaces, reduced rational strings, kinds, qualifiers, units, "
        "and referent evidence. Preserve PARTIAL or UNSUPPORTED when interpretation is incomplete."
    ),
    "CORRESPONDENCE": (
        "Bind the supplied immutable OL numeric sequence to exact OL text expressions and bind "
        "each validated target expression to its exact referent evidence. Do not select authority "
        "or change any supplied numeric value."
    ),
    "FOOTNOTE": (
        "Assess only whether the supplied target note contains the disclosure required by the "
        "registered guidance. Quote exact note spans and preserve insufficient evidence."
    ),
}


def _response_span_schema() -> dict[str, object]:
    """Return the closed half-open span shape used by provider responses."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["start", "end"],
        "properties": {"start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1}},
    }


def _response_expression_schema(stream_id: str) -> dict[str, object]:
    """Return one closed exact numeric-expression provider schema."""
    rational = {"type": "string", "pattern": r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$"}
    role_span = {
        "type": "object",
        "additionalProperties": False,
        "required": ["start", "end", "surface"],
        "properties": {
            "start": {"type": "integer", "minimum": 0},
            "end": {"type": "integer", "minimum": 1},
            "surface": {"type": "string", "minLength": 1},
        },
    }
    representation = {
        "type": "object",
        "additionalProperties": False,
        "required": ["surface", "span", "value"],
        "properties": {
            "surface": {"type": "string", "minLength": 1},
            "span": _response_span_schema(),
            "value": rational,
        },
    }
    required = [
        "expression_id", "stream_id", "surface", "span", "values", "kind",
        "unit", "qualifier", "role", "role_spans", "representations",
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": {
            "expression_id": {"type": "string", "minLength": 1},
            "stream_id": {"type": "string", "const": stream_id},
            "surface": {"type": "string", "minLength": 1},
            "span": _response_span_schema(),
            "values": {"type": "array", "minItems": 1, "items": rational},
            "kind": {"enum": sorted(NUMERIC_KINDS)},
            "unit": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},
            "qualifier": {"enum": sorted(NUMERIC_QUALIFIERS)},
            "role": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},
            "role_spans": {"type": "array", "items": role_span},
            "representations": {"type": "array", "items": representation},
        },
    }


def _target_role_schema() -> dict[str, object]:
    """Return the closed target referent-assignment response schema."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["expression_id", "role", "role_spans"],
        "properties": {
            "expression_id": {"type": "string", "minLength": 1},
            "role": {"type": "string", "minLength": 1},
            "role_spans": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["start", "end", "surface"],
                    "properties": {
                        "start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 1},
                        "surface": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
    }


def _note_evidence_schema() -> dict[str, object]:
    """Return the closed exact target-note evidence response schema."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["note_id", "surface", "span"],
        "properties": {
            "note_id": {"type": "string", "minLength": 1},
            "surface": {"type": "string", "minLength": 1},
            "span": _response_span_schema(),
        },
    }


_SCHEMAS: dict[str, dict[str, object]] = {
    "EXTRACTION": {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "phase", "work_units"],
        "properties": {
            "schema_version": {"const": "1.0"},
            "phase": {"const": "EXTRACTION"},
            "work_units": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["unit_id", "status", "limitations", "expressions"],
                    "properties": {
                        "unit_id": {"type": "string", "minLength": 1},
                        "status": {"enum": sorted(EXTRACTION_STATUSES)},
                        "limitations": {"type": "array", "items": {"type": "string", "minLength": 1}},
                        "expressions": {"type": "array", "items": _response_expression_schema("main")},
                    },
                },
            },
        },
    },
    "CORRESPONDENCE": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "phase",
            "unit_id",
            "status",
            "limitations",
            "source_expressions",
            "target_roles",
        ],
        "properties": {
            "schema_version": {"const": "1.0"},
            "phase": {"const": "CORRESPONDENCE"},
            "unit_id": {"type": "string"},
            "status": {"enum": sorted(EXTRACTION_STATUSES)},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "source_expressions": {"type": "array", "items": _response_expression_schema("ol")},
            "target_roles": {"type": "array", "items": _target_role_schema()},
            "registered_status": {"enum": sorted(EXTRACTION_STATUSES)},
            "registered_limitations": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "registered_expressions": {"type": "array", "items": _response_expression_schema("registered")},
        },
    },
    "FOOTNOTE": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "phase",
            "unit_id",
            "note_id",
            "action",
            "status",
            "outcome",
            "limitations",
            "evidence",
        ],
        "properties": {
            "schema_version": {"const": "1.0"},
            "phase": {"const": "FOOTNOTE"},
            "unit_id": {"type": "string"},
            "note_id": {"type": "string"},
            "action": {"enum": sorted(FOOTNOTE_ACTIONS)},
            "status": {"enum": sorted(FOOTNOTE_STATUSES)},
            "outcome": {"enum": sorted(FOOTNOTE_OUTCOMES)},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": _note_evidence_schema()},
        },
    },
}
_READING_CONTEXT_FIELDS = frozenset(
    {
        "registry_id",
        "reading_id",
        "source_ids",
        "values",
        "text",
        "kind",
        "unit",
        "qualifier",
        "role",
        "policy_outcome",
    }
)
_GUIDANCE_FIELDS = frozenset(
    {
        "guidance_id",
        "registry_id",
        "action",
        "reading",
        "required_content",
        "source_ids",
        "reason_codes",
    }
)
T = TypeVar("T")


def _sha256(value: bytes) -> str:
    """Return one lowercase SHA-256 digest."""
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Mapping[str, object]) -> str:
    """Serialize one payload deterministically without altering Unicode text."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _model_error(message: str, code: str) -> ValidationError:
    """Build one stable routed NCA validation error."""
    return ValidationError(message, code=code)


def _text(value: object, label: str, code: str) -> str:
    """Require one non-empty string in a model phase response."""
    if not isinstance(value, str) or not value.strip():
        raise _model_error(f"{label} must be non-empty text", code)
    return value


def _list(value: object, label: str, code: str) -> list[Any]:
    """Require one JSON array in a model phase response."""
    if not isinstance(value, list):
        raise _model_error(f"{label} must be an array", code)
    return value


def _object(value: object, label: str, code: str) -> Mapping[str, Any]:
    """Require one string-keyed JSON object in a model phase response."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _model_error(f"{label} must be an object", code)
    return value


def _keys(
    value: Mapping[str, object],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
    code: str,
) -> None:
    """Reject missing and unregistered model response fields."""
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing or unknown:
        raise _model_error(
            f"{label} fields are invalid; missing={missing}, unknown={unknown}", code
        )


def _json_value(value: object, label: str) -> object:
    """Copy bounded JSON data while normalizing exact Fractions to strings."""
    from fractions import Fraction

    if isinstance(value, Fraction):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item, label) for item in value]
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {str(key): _json_value(item, label) for key, item in value.items()}
    raise _model_error(f"{label} contains unsupported data", "NCA_MODEL_PAYLOAD_INVALID")


def _bounded_mapping(
    value: Mapping[str, object] | None,
    allowed: frozenset[str],
    label: str,
) -> dict[str, object]:
    """Project an evidence mapping through an explicit inert-data allowlist."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _model_error(f"{label} must be a mapping", "NCA_MODEL_PAYLOAD_INVALID")
    return {
        key: _json_value(value[key], f"{label}.{key}")
        for key in sorted(allowed)
        if key in value
    }


def _expression_payload(expression: NumericExpression, text: str) -> dict[str, object]:
    """Serialize validated expression evidence with exact original surfaces."""
    representations = []
    for representation in expression.representations:
        span = tuple(representation["span"])
        representations.append(
            {
                "surface": representation["surface"],
                "span": {"start": span[0], "end": span[1]},
                "value": representation["value"],
            }
        )
    return {
        "expression_id": expression.expression_id,
        "stream_id": expression.stream_id,
        "surface": expression.surface,
        "span": {"start": expression.span[0], "end": expression.span[1]},
        "values": [str(value) for value in expression.values],
        "kind": expression.kind,
        "unit": expression.unit,
        "qualifier": expression.qualifier,
        "role": expression.role,
        "role_spans": [
            {"start": start, "end": end, "surface": text[start:end]}
            for start, end in expression.role_spans
        ],
        "representations": representations,
    }


@dataclass(frozen=True)
class CorrespondenceEvidence:
    """Validated typed OL expressions and target referent correspondence."""

    source_expressions: tuple[NumericExpression, ...]
    target_extraction: Extraction
    status: str
    limitations: tuple[str, ...] = ()
    registered_expressions: tuple[NumericExpression, ...] = ()
    registered_status: str = "NOT_APPLICABLE"
    registered_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Require typed immutable correspondence evidence and closed status values."""
        if (
            not isinstance(self.source_expressions, tuple)
            or any(not isinstance(item, NumericExpression) for item in self.source_expressions)
            or not isinstance(self.target_extraction, Extraction)
            or self.status not in EXTRACTION_STATUSES
            or not isinstance(self.limitations, tuple)
            or any(not isinstance(item, str) for item in self.limitations)
            or not isinstance(self.registered_expressions, tuple)
            or any(not isinstance(item, NumericExpression) for item in self.registered_expressions)
            or self.registered_status not in EXTRACTION_STATUSES | {"NOT_APPLICABLE"}
            or not isinstance(self.registered_limitations, tuple)
            or any(not isinstance(item, str) for item in self.registered_limitations)
        ):
            raise _model_error(
                "Correspondence evidence is malformed", "NCA_CORRESPONDENCE_EVIDENCE_INVALID"
            )


@dataclass(frozen=True)
class ModelPhaseReceipt:
    """Immutable route and content identity for one NCA model request."""

    phase: str
    task_version: str
    provider: str
    model: str
    reasoning_effort: str
    route_id: str
    routing_mode: str
    qualification_status: str
    prompt_sha256: str
    input_sha256: str
    response_sha256: str
    provider_metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        """Freeze provider metadata so transport receipts cannot mutate later."""
        admitted = {(phase, version) for phase, version in _TASK_VERSIONS.items()}
        admitted.update((phase, "nca-" + phase.lower().replace("_", "-") + "-2.0")
            for phase in ("EXTRACTION", "CORRESPONDENCE", "FOOTNOTE", "GROUP_CORRESPONDENCE"))
        if (self.phase, self.task_version) not in admitted:
            raise _model_error("Unknown NCA phase receipt", "NCA_MODEL_RECEIPT_INVALID")
        fields = (
            self.task_version,
            self.provider,
            self.model,
            self.reasoning_effort,
            self.route_id,
            self.routing_mode,
            self.qualification_status,
            self.prompt_sha256,
            self.input_sha256,
            self.response_sha256,
        )
        if any(not isinstance(value, str) or not value for value in fields):
            raise _model_error("Incomplete NCA phase receipt", "NCA_MODEL_RECEIPT_INVALID")
        object.__setattr__(
            self,
            "provider_metadata",
            MappingProxyType(
                {str(key): freeze(value) for key, value in self.provider_metadata.items()}
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Render a JSON-serializable receipt for immutable Run task evidence."""
        return {
            "phase": self.phase,
            "task_version": self.task_version,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "route_id": self.route_id,
            "routing_mode": self.routing_mode,
            "qualification_status": self.qualification_status,
            "prompt_sha256": self.prompt_sha256,
            "input_sha256": self.input_sha256,
            "response_sha256": self.response_sha256,
            "provider_metadata": _json_value(self.provider_metadata, "provider metadata"),
        }


@dataclass(frozen=True)
class ModelPhaseResult(Generic[T]):
    """Pair one validated typed phase value with its immutable execution receipt."""

    value: T
    receipt: ModelPhaseReceipt
    raw_response: str | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        """Require a real phase receipt for every returned interpretation."""
        if not isinstance(self.receipt, ModelPhaseReceipt):
            raise _model_error("NCA phase result lacks a receipt", "NCA_MODEL_RECEIPT_INVALID")
        if self.receipt.task_version == "nca-extraction-2.0" and (
            self.raw_response is None or not isinstance(self.request_id, str) or not self.request_id
        ):
            raise _model_error("NCA v2 result lacks physical request evidence", "NCA_MODEL_RECEIPT_INVALID")
        if self.raw_response is not None and (
            not isinstance(self.raw_response, str)
            or _sha256(self.raw_response.encode("utf-8")) != self.receipt.response_sha256
        ):
            raise _model_error("NCA raw response differs from its receipt", "NCA_MODEL_RECEIPT_INVALID")


def _is_subsequence(values: tuple[object, ...], expected: tuple[object, ...]) -> bool:
    """Return whether partial values preserve authoritative order and multiplicity."""
    iterator = iter(expected)
    return all(any(candidate == value for candidate in iterator) for value in values)


def _require_disjoint_primary_spans(expressions: tuple[NumericExpression, ...]) -> None:
    """Reject overlapping independently counted expressions within one source stream."""
    spans = sorted(expression.span for expression in expressions)
    if any(current[0] < previous[1] for previous, current in zip(spans, spans[1:])):
        raise _model_error(
            "Source correspondence overlaps primary expression evidence",
            "NCA_CORRESPONDENCE_EVIDENCE_INVALID",
        )


def validate_correspondence_response(
    unit: TargetUnit,
    target: Extraction,
    reference: ReferenceRow,
    response: Mapping[str, object],
    *,
    reading_context: Mapping[str, object] | None = None,
    schema_version: str = "1.0",
) -> CorrespondenceEvidence:
    """Validate exact OL expressions and target-role spans against immutable inputs."""
    code = "NCA_CORRESPONDENCE_EVIDENCE_INVALID"
    raw = _object(response, "correspondence response", code)
    required = frozenset(
        {
            "schema_version",
            "phase",
            "unit_id",
            "status",
            "limitations",
            "source_expressions",
            "target_roles",
        }
    )
    registered_fields = frozenset(
        {"registered_status", "registered_limitations", "registered_expressions"}
    )
    has_registered_context = reading_context is not None
    _keys(
        raw,
        required=required | (registered_fields if has_registered_context else frozenset()),
        optional=frozenset({"confidence"}),
        label="correspondence response",
        code=code,
    )
    if raw["schema_version"] != schema_version or raw["phase"] != "CORRESPONDENCE":
        raise _model_error("Correspondence response identity is invalid", code)
    if raw["unit_id"] != unit.unit_id:
        raise _model_error(
            "Correspondence covers the wrong work unit", "NCA_CORRESPONDENCE_COVERAGE_INVALID"
        )
    status = _text(raw["status"], "correspondence status", code)
    if status not in EXTRACTION_STATUSES:
        raise _model_error("Correspondence status is unsupported", code)
    limitations = tuple(
        _text(value, f"limitations[{index}]", code)
        for index, value in enumerate(_list(raw["limitations"], "limitations", code))
    )
    if status != "COMPLETE" and not limitations:
        raise _model_error("Incomplete correspondence must state a limitation", code)
    try:
        source = tuple(
            _validated_expression(value, text=reference.ol_text, expected_stream_id="ol")
            for value in _list(raw["source_expressions"], "source_expressions", code)
        )
    except ValidationError as exc:
        raise _model_error(str(exc), code) from exc
    source_ids = [item.expression_id for item in source]
    source_spans = [item.span for item in source]
    if len(source_ids) != len(set(source_ids)) or len(source_spans) != len(set(source_spans)):
        raise _model_error("Source correspondence duplicates expression evidence", code)
    _require_disjoint_primary_spans(source)
    flat_values = tuple(value for expression in source for value in expression.values)
    if (
        status == "COMPLETE"
        and flat_values != reference.ol_values
        or status != "COMPLETE"
        and not _is_subsequence(flat_values, reference.ol_values)
    ):
        raise _model_error("Source expressions change the immutable OL value sequence", code)

    by_id = {expression.expression_id: expression for expression in target.expressions}
    if None in by_id or len(by_id) != len(target.expressions):
        raise _model_error("Target extraction lacks unique persisted expression IDs", code)
    target_roles: dict[str, tuple[str, tuple[tuple[int, int], ...]]] = {}
    for index, item in enumerate(_list(raw["target_roles"], "target_roles", code)):
        role_raw = _object(item, f"target_roles[{index}]", code)
        _keys(
            role_raw,
            required=frozenset({"expression_id", "role", "role_spans"}),
            label=f"target_roles[{index}]",
            code=code,
        )
        expression_id = _text(role_raw["expression_id"], "target role expression ID", code)
        role = _text(role_raw["role"], "target role", code)
        if expression_id not in by_id or expression_id in target_roles:
            raise _model_error(
                "Target role uses unknown or duplicate expression evidence",
                "NCA_CORRESPONDENCE_COVERAGE_INVALID",
            )
        try:
            role_spans = _validated_role_spans(role_raw["role_spans"], text=unit.main_text)
        except ValidationError as exc:
            raise _model_error(str(exc), code) from exc
        target_roles[expression_id] = (role, role_spans)
    if status == "COMPLETE" and set(target_roles) != set(by_id):
        raise _model_error(
            "Complete correspondence omits target expression roles",
            "NCA_CORRESPONDENCE_COVERAGE_INVALID",
        )
    if status == "COMPLETE" and any(
        not item.role or not item.role.strip() or not item.role_spans for item in source
    ):
        raise _model_error(
            "Complete source correspondence requires exact referent evidence", code
        )
    if status == "COMPLETE" and any(not value[1] for value in target_roles.values()):
        raise _model_error(
            "Complete target correspondence requires exact referent evidence", code
        )
    enriched = tuple(
        replace(
            expression,
            role=target_roles[expression.expression_id][0],
            role_spans=target_roles[expression.expression_id][1],
        )
        for expression in target.expressions
        if expression.expression_id in target_roles
    )
    target_status = status if status != "COMPLETE" else target.status
    enriched_target = Extraction(enriched, target_status, limitations if status != "COMPLETE" else target.limitations)
    registered_expressions: tuple[NumericExpression, ...] = ()
    registered_status = "NOT_APPLICABLE"
    registered_limitations: tuple[str, ...] = ()
    # Registered candidates remain a parallel evidence stream; they never replace OL validation.
    if has_registered_context:
        context = _bounded_mapping(
            reading_context, _READING_CONTEXT_FIELDS, "reading context"
        )
        if any(
            not isinstance(context.get(field), str) or not str(context[field]).strip()
            for field in ("registry_id", "reading_id")
        ):
            raise _model_error("Reading context lacks registered identity", code)
        source_ids = context.get("source_ids")
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or any(not isinstance(value, str) or not value for value in source_ids)
        ):
            raise _model_error("Reading context lacks registered sources", code)
        candidate_text = _text(context.get("text"), "reading context text", code)
        candidate_values = context.get("values")
        if (
            not isinstance(candidate_values, list)
            or not candidate_values
            or any(not isinstance(value, str) for value in candidate_values)
        ):
            raise _model_error("Reading context values must be rational strings", code)
        from fractions import Fraction

        try:
            expected_values = tuple(Fraction(value) for value in candidate_values)
        except (ValueError, ZeroDivisionError) as exc:
            raise _model_error("Reading context values are invalid", code) from exc
        if [str(value) for value in expected_values] != candidate_values:
            raise _model_error("Reading context values must be reduced and normalized", code)
        registered_status = _text(raw["registered_status"], "registered status", code)
        if registered_status not in EXTRACTION_STATUSES:
            raise _model_error("Registered correspondence status is unsupported", code)
        registered_limitations = tuple(
            _text(value, f"registered_limitations[{index}]", code)
            for index, value in enumerate(
                _list(raw["registered_limitations"], "registered_limitations", code)
            )
        )
        if registered_status != "COMPLETE" and not registered_limitations:
            raise _model_error("Incomplete registered correspondence needs a limitation", code)
        try:
            registered_expressions = tuple(
                _validated_expression(
                    value,
                    text=candidate_text,
                    expected_stream_id="registered",
                )
                for value in _list(
                    raw["registered_expressions"], "registered_expressions", code
                )
            )
        except ValidationError as exc:
            raise _model_error(str(exc), code) from exc
        registered_ids = [expression.expression_id for expression in registered_expressions]
        registered_spans = [expression.span for expression in registered_expressions]
        if (
            len(registered_ids) != len(set(registered_ids))
            or len(registered_spans) != len(set(registered_spans))
        ):
            raise _model_error("Registered correspondence duplicates evidence", code)
        _require_disjoint_primary_spans(registered_expressions)
        registered_values = tuple(
            value for expression in registered_expressions for value in expression.values
        )
        if (
            registered_status == "COMPLETE"
            and registered_values != expected_values
            or registered_status != "COMPLETE"
            and not _is_subsequence(registered_values, expected_values)
        ):
            raise _model_error("Registered expressions change authorized values", code)
        expected_fields = {
            field: context[field]
            for field in ("kind", "unit", "qualifier", "role")
            if field in context
        }
        if any(
            any(getattr(expression, field) != expected for field, expected in expected_fields.items())
            for expression in registered_expressions
        ):
            raise _model_error("Registered expressions change authorized meaning", code)
        if registered_status == "COMPLETE" and any(
            not expression.role or not expression.role_spans
            for expression in registered_expressions
        ):
            raise _model_error("Registered correspondence requires exact referent evidence", code)
    return CorrespondenceEvidence(
        source,
        enriched_target,
        status,
        limitations,
        registered_expressions,
        registered_status,
        registered_limitations,
    )


def _validate_footnote_response(
    unit: TargetUnit,
    note: TargetNote,
    required_action: str,
    response: Mapping[str, object],
    *, schema_version: str = "1.0",
) -> FootnoteDecision:
    """Validate one note assessment against its exact selected note stream."""
    code = "NCA_FOOTNOTE_EVIDENCE_INVALID"
    raw = _object(response, "footnote response", code)
    required = frozenset(
        {
            "schema_version",
            "phase",
            "unit_id",
            "note_id",
            "action",
            "status",
            "outcome",
            "limitations",
            "evidence",
        }
    )
    _keys(raw, required=required, optional=frozenset({"confidence"}), label="footnote response", code=code)
    if (
        raw["schema_version"] != schema_version
        or raw["phase"] != "FOOTNOTE"
        or raw["unit_id"] != unit.unit_id
        or raw["note_id"] != note.note_id
    ):
        raise _model_error("Footnote response identity is invalid", code)
    action = _text(raw["action"], "footnote action", code)
    status = _text(raw["status"], "footnote status", code)
    outcome = _text(raw["outcome"], "footnote outcome", code)
    if (
        required_action not in FOOTNOTE_ACTIONS
        or action != required_action
        or status not in FOOTNOTE_STATUSES
        or outcome not in FOOTNOTE_OUTCOMES
    ):
        raise _model_error("Footnote policy fields are invalid", code)
    valid_outcomes = {
        ("NONE", "NOT_REQUIRED", "NONE"),
        ("RECOMMEND", "ADEQUATE", "NONE"),
        ("REQUIRE", "ADEQUATE", "NONE"),
        ("RECOMMEND", "MISSING", "ADVISORY"),
        ("REQUIRE", "MISSING", "REVIEW_MISSING_FOOTNOTE"),
        ("RECOMMEND", "INADEQUATE", "ADVISORY"),
        ("REQUIRE", "INADEQUATE", "REVIEW_MISSING_FOOTNOTE"),
        ("NONE", "NOT_ASSESSED", "INSUFFICIENT_EVIDENCE"),
        ("RECOMMEND", "NOT_ASSESSED", "INSUFFICIENT_EVIDENCE"),
        ("REQUIRE", "NOT_ASSESSED", "INSUFFICIENT_EVIDENCE"),
    }
    if (action, status, outcome) not in valid_outcomes:
        raise _model_error("Footnote status contradicts its policy outcome", code)
    limitations = tuple(
        _text(value, f"limitations[{index}]", code)
        for index, value in enumerate(_list(raw["limitations"], "limitations", code))
    )
    evidence_spans: list[tuple[int, int]] = []
    for index, item in enumerate(_list(raw["evidence"], "evidence", code)):
        evidence = _object(item, f"evidence[{index}]", code)
        _keys(
            evidence,
            required=frozenset({"note_id", "surface", "span"}),
            label=f"evidence[{index}]",
            code=code,
        )
        if evidence["note_id"] != note.note_id:
            raise _model_error("Footnote evidence uses another note", code)
        try:
            span = _span(evidence["span"], note.text, evidence["surface"], f"evidence[{index}]")
        except ValidationError as exc:
            raise _model_error(str(exc), code) from exc
        if span in evidence_spans:
            raise _model_error("Footnote evidence duplicates a note span", code)
        evidence_spans.append(span)
    if status == "ADEQUATE" and not evidence_spans:
        raise _model_error("Adequate footnote assessment requires exact evidence", code)
    if status in {"INADEQUATE", "NOT_ASSESSED"} and not limitations:
        raise _model_error("Unresolved footnote assessment requires a limitation", code)
    return FootnoteDecision(
        action,
        status,
        outcome,
        tuple(evidence_spans),
        tuple(note.note_id for _span_value in evidence_spans),
    )


class NcaModelTasks:
    """Run all NCA semantic phases through one route resolved and pinned at construction."""

    # Keep phase methods on one instance so every request reuses the readiness snapshot and route.

    def __init__(
        self,
        config: EcosystemConfig,
        *,
        settings: Mapping[str, object] | None = None,
        transport: Executor | None = None,
        expected_route_id: str | None = None,
        timeout_seconds: int = 600,
    ) -> None:
        """Resolve one normal configured Skill route and optionally verify persisted identity."""
        self._config = config
        self._settings = dict(settings) if settings is not None else load_llm_settings(config.root)
        self._timeout_seconds = timeout_seconds
        if transport is None:
            executor, status, route = _resolve_task_route(config, self._settings, SKILL_ID)
        else:
            provider = str(self._settings.get("selected_provider") or "").strip().lower()
            provider_settings = self._settings.get("providers")
            selected = provider_settings.get(provider) if isinstance(provider_settings, Mapping) else None
            if not isinstance(selected, Mapping) or not bool(selected.get("enabled", False)):
                raise _model_error("Configured NCA provider is not enabled", "LLM_PROVIDER_NOT_READY")
            executor = transport
            status = executor.status()
            if status.provider != provider:
                raise _model_error(
                    "NCA transport status differs from configured provider",
                    "PROVIDER_ROUTE_UNAVAILABLE",
                )
            if provider == "codex":
                cache_provider_catalog(config.root, status)
            route = resolve_routing_mode(config.root, SKILL_ID, [status])
            if route.identity.provider != provider:
                raise _model_error(
                    "NCA route differs from configured provider", "PROVIDER_ROUTE_UNAVAILABLE"
                )
        if expected_route_id is not None and route.identity.route_id != expected_route_id:
            raise _model_error(
                "Persisted NCA route identity differs from the currently resolved route",
                "NCA_MODEL_ROUTE_CHANGED",
            )
        self._executor = executor
        self._provider_status = status
        self._route = route
        self._attempts: list[ModelAttempt] = []

    @property
    def route_identity(self) -> Mapping[str, object]:
        """Return the pinned route identity for Run persistence and resume checks."""
        return MappingProxyType(self._route.to_dict())

    @property
    def route_snapshot(self) -> Mapping[str, object]:
        """Return normalized pinned route fields for Job/Run persistence without probing."""
        identity = self._route.identity
        return MappingProxyType(
            {
                "route_id": identity.route_id,
                "provider": identity.provider,
                "model": identity.model_id,
                "reasoning_effort": identity.reasoning_id,
                "capability_fingerprint": identity.capability_fingerprint,
                "qualification_status": self._route.qualification,
                "qualification_evidence_sha256": self._route.evidence_sha256,
                "routing_policy_version": identity.policy_version,
            }
        )

    @property
    def attempts(self) -> tuple[ModelAttempt, ...]:
        """Expose all actual calls, including failed unadmitted raw provider evidence."""
        return tuple(self._attempts)

    def _prompt(self, phase: str, payload: Mapping[str, object], *, task_version: str | None = None) -> str:
        """Assemble a version-aware capsule without authority policy in batch extraction."""
        version = task_version or _TASK_VERSIONS[phase]
        batch_extraction = phase == "EXTRACTION" and version == "nca-extraction-2.0"
        relative = ("system/skills/nca-numbers/references/TARGET-EXTRACTION-CONTRACT.md"
                    if batch_extraction else "system/skills/nca-numbers/SKILL.md")
        try:
            skill_contract = (self._config.root / relative).read_text(encoding="utf-8")
        except OSError as exc:
            raise _model_error("Registered NCA Skill contract is unavailable", "NCA_MODEL_SKILL_INVALID") from exc
        return _canonical_json({
            "task_version": version, "skill_id": SKILL_ID, "phase": phase,
            "instructions": ("Interpret only the supplied independent target streams. Return one version-2.0 "
                             "batch envelope with exact input identities and local evidence offsets."
                             if batch_extraction else _PHASE_INSTRUCTIONS[phase]),
            "skill_contract": skill_contract, "input": payload,
        })

    def configure_phase_execution(self, executor: object) -> None:
        """Bind one controller-owned checkpoint hook without changing public phase methods."""
        self._phase_executor = executor

    def _execute(
        self, phase: str, payload: Mapping[str, object],
        validator: Callable[[Mapping[str, object]], T], *,
        task_version: str | None = None, schema: Mapping[str, object] | None = None,
    ) -> ModelPhaseResult[T]:
        """Use the optional attempt-local hook around the exact physical phase boundary."""
        hook = getattr(self, '_phase_executor', None)
        if hook is not None:
            return hook(phase, payload, validator, task_version=task_version or _TASK_VERSIONS[phase],
                schema=schema or _SCHEMAS[phase], physical=self._execute_physical)
        return self._execute_physical(phase, payload, validator, task_version=task_version, schema=schema)

    def _execute_physical(
        self, phase: str, payload: Mapping[str, object],
        validator: Callable[[Mapping[str, object]], T], *,
        task_version: str | None = None, schema: Mapping[str, object] | None = None,
    ) -> ModelPhaseResult[T]:
        """Measure each physical call and admit a receipt only after exact validation."""
        version = task_version or _TASK_VERSIONS[phase]
        prompt = self._prompt(phase, payload, task_version=version)
        identity = self._route.identity
        reasoning = None if identity.reasoning_id == "provider-default" else identity.reasoning_id
        request = ProviderRequest(prompt=prompt, schema=dict(schema or _SCHEMAS[phase]),
            model=identity.model_id, reasoning_effort=reasoning, timeout_seconds=self._timeout_seconds)
        wire = {"prompt": request.prompt, "schema": request.schema, "model": request.model,
                "reasoning_effort": request.reasoning_effort, "timeout_seconds": request.timeout_seconds}
        wire_text = _canonical_json(wire)
        unit_ids = (tuple(str(item.get("input_id", item.get("unit_id"))) for item in payload["work_units"])
                    if phase == "EXTRACTION" else (str(payload["unit_id"]),))
        request_id = uuid4().hex
        response = None
        status = "NCA_MODEL_PROVIDER_FAILED"
        execute_prevalidated = getattr(self._executor, "execute_prevalidated", None)
        started_ns = perf_counter_ns()
        try:
            try:
                response = (execute_prevalidated(request, self._provider_status)
                            if callable(execute_prevalidated) else self._executor.execute(request))
            except Exception as exc:
                if isinstance(exc, ValidationError) and exc.code in {
                    "LLM_RESPONSE_ROUTE_MISMATCH", "NCA_MODEL_ROUTE_CHANGED", "PROVIDER_ROUTE_UNAVAILABLE"
                }:
                    raise
                if str(exc).startswith("invalid_json_schema"):
                    raise _model_error(
                        f"NCA {phase.lower()} request schema was rejected by the provider: {exc}",
                        "NCA_MODEL_SCHEMA_INVALID",
                    ) from exc
                raise _model_error(f"NCA {phase.lower()} provider request failed: {exc}",
                                   "NCA_MODEL_PROVIDER_FAILED") from exc
            finally:
                finished_ns = perf_counter_ns()
            _validate_provider_response_route(response, self._route)
            try:
                raw = json.loads(response.content)
            except (TypeError, json.JSONDecodeError) as exc:
                raise _model_error(f"NCA {phase.lower()} response is not one JSON object",
                                   "NCA_MODEL_RESPONSE_INVALID") from exc
            if not isinstance(raw, Mapping):
                raise _model_error(f"NCA {phase.lower()} response is not one JSON object", "NCA_MODEL_RESPONSE_INVALID")
            value = validator(raw)
            receipt = ModelPhaseReceipt(
                phase=phase, task_version=version, provider=response.provider, model=identity.model_id,
                reasoning_effort=identity.reasoning_id, route_id=identity.route_id,
                routing_mode=self._route.routing_mode, qualification_status=self._route.qualification,
                prompt_sha256=_sha256(prompt.encode("utf-8")),
                input_sha256=_sha256(_canonical_json(payload).encode("utf-8")),
                response_sha256=_sha256(response.content.encode("utf-8")), provider_metadata=response.metadata)
            result = ModelPhaseResult(value, receipt, response.content, request_id)
            status = "VALIDATED"
            return result
        except ValidationError as exc:
            status = str(exc.code)
            raise
        finally:
            content = response.content if response is not None else None
            metadata = response.metadata if response is not None else {}
            usage = metadata.get("usage", {})
            measurement = CallMeasurement(request_id=request_id, phase=phase, unit_ids=unit_ids,
                elapsed_ms=(finished_ns - started_ns) // 1_000_000,
                request_bytes=len(wire_text.encode("utf-8")),
                response_bytes=len(content.encode("utf-8")) if isinstance(content, str) else 0,
                input_tokens=_usage_counter(usage, "input_tokens"),
                output_tokens=_usage_counter(usage, "output_tokens"), status=status, reused=False)
            response_identity = ({"provider": response.provider, "model": response.model,
                                  "reasoning_effort": response.reasoning_effort, "metadata": metadata}
                                 if response is not None else {})
            self._attempts.append(ModelAttempt(measurement, wire, content, response_identity))

    def extract_batch(
        self, batch: ExtractionBatch, *, parsing_conventions: Mapping[str, object],
    ) -> ModelPhaseResult[BatchValidation]:
        """Send precisely one target-only batch request and retain its one parent receipt."""
        payload = build_batch_extraction_payload(batch, parsing_conventions=parsing_conventions)
        return self._execute("EXTRACTION", payload,
            lambda response: validate_batch_extraction_response(batch, response),
            task_version="nca-extraction-2.0", schema=_batch_response_schema())

    def extract(
        self,
        unit: TargetUnit,
        *,
        language: str,
        style_profile: Mapping[str, object],
    ) -> ModelPhaseResult[Extraction]:
        """Run target-only numeric extraction without OL or NIV reference values."""
        payload = build_extraction_payload(unit, language=language, style_profile=style_profile)
        return self._execute(
            "EXTRACTION", payload, lambda response: validate_extraction_response(unit, response)
        )

    def correspond(
        self,
        unit: TargetUnit,
        target: Extraction,
        reference: ReferenceRow,
        *,
        reading_context: Mapping[str, object] | None = None,
    ) -> ModelPhaseResult[CorrespondenceEvidence]:
        """Run exact OL/target correspondence with an optional registered reading hook."""
        if not isinstance(target, Extraction) or not isinstance(reference, ReferenceRow):
            raise _model_error("Correspondence inputs are not typed evidence", "NCA_MODEL_PAYLOAD_INVALID")
        version = "2.0" if getattr(self, "_phase_executor", None) is not None else "1.0"
        schema = deepcopy(_SCHEMAS["CORRESPONDENCE"])
        schema["properties"]["schema_version"]["const"] = version
        registered_fields = ("registered_status", "registered_limitations", "registered_expressions")
        if reading_context is None:
            for field in registered_fields:
                schema["properties"].pop(field, None)
        else:
            schema["required"] = [*schema["required"], *registered_fields]
        payload: Mapping[str, object] = {
            "schema_version": version,
            "phase": "CORRESPONDENCE",
            "unit_id": unit.unit_id,
            "target": {
                "stream_id": "main",
                "text": unit.main_text,
                "status": target.status,
                "limitations": list(target.limitations),
                "expressions": [
                    _expression_payload(expression, unit.main_text)
                    for expression in target.expressions
                ],
            },
            "authority": {
                "western_reference": str(reference.western_reference),
                "ol_reference": reference.ol_reference,
                "language": reference.language,
                "ol_text": reference.ol_text,
                "ol_values": [str(value) for value in reference.ol_values],
            },
            "reading_context": _bounded_mapping(
                reading_context, _READING_CONTEXT_FIELDS, "reading context"
            ),
            "output_schema_id": f"sage-nca-extraction-{version}#correspondence",
        }
        return self._execute(
            "CORRESPONDENCE",
            payload,
            lambda response: validate_correspondence_response(
                unit,
                target,
                reference,
                response,
                reading_context=reading_context, schema_version=version,
            ), task_version=f"nca-correspondence-{version}", schema=schema,
        )

    def correspond_group(self, unit, extraction: Extraction, reference_group):
        """Execute one row-keyed group phase through the same physical checkpoint boundary."""
        from .groups import build_group_payload, group_response_schema, validate_group_correspondence
        if unit != reference_group.unit:
            raise _model_error("Group protected unit differs", "NCA_MODEL_PAYLOAD_INVALID")
        return self._execute("GROUP_CORRESPONDENCE", build_group_payload(reference_group, extraction),
            lambda response: validate_group_correspondence(reference_group, extraction, response),
            task_version="nca-group-correspondence-2.0", schema=group_response_schema(reference_group))

    def assess_footnote(
        self,
        unit: TargetUnit,
        note: TargetNote,
        guidance: Mapping[str, object],
        *,
        required_action: str,
    ) -> ModelPhaseResult[FootnoteDecision]:
        """Assess one exact target note against bounded registered guidance."""
        if note not in unit.notes:
            raise _model_error("Footnote is not part of the target unit", "NCA_MODEL_PAYLOAD_INVALID")
        if required_action not in FOOTNOTE_ACTIONS:
            raise _model_error("Required footnote action is invalid", "NCA_MODEL_PAYLOAD_INVALID")
        version = "2.0" if getattr(self, "_phase_executor", None) is not None else "1.0"
        schema = deepcopy(_SCHEMAS["FOOTNOTE"])
        schema["properties"]["schema_version"]["const"] = version
        payload: Mapping[str, object] = {
            "schema_version": version,
            "phase": "FOOTNOTE",
            "unit_id": unit.unit_id,
            "note": {"note_id": note.note_id, "text": note.text},
            "guidance": _bounded_mapping(guidance, _GUIDANCE_FIELDS, "footnote guidance"),
            "required_action": required_action,
            "output_schema_id": f"sage-nca-extraction-{version}#footnote",
        }
        return self._execute(
            "FOOTNOTE",
            payload,
            lambda response: _validate_footnote_response(
                unit, note, required_action, response, schema_version=version
            ), task_version=f"nca-footnote-{version}", schema=schema,
        )


def _batch_response_schema() -> dict[str, object]:
    """Keep v1 provider contracts intact while closing the version-2.0 batch envelope."""
    schema = deepcopy(_SCHEMAS["EXTRACTION"])
    schema["required"].append("batch_id")
    properties = schema["properties"]
    properties["schema_version"] = {"const": "2.0"}
    properties["batch_id"] = {"type": "string", "minLength": 1}
    rows = properties["work_units"]
    rows.pop("maxItems")
    rows["minItems"] = 0
    item = rows["items"]
    item["required"][0] = "input_id"
    item["properties"]["input_id"] = item["properties"].pop("unit_id")
    item["properties"]["expressions"]["items"]["properties"]["stream_id"] = {"type": "string", "minLength": 1}
    return schema


def _usage_counter(usage: object, field: str) -> int | None:
    """Retain reported exact nonnegative token counts without estimates or coercion."""
    value = usage.get(field) if isinstance(usage, Mapping) else None
    return value if type(value) is int and value >= 0 else None


@dataclass(frozen=True)
class ModelAttempt:
    """One physical request and its exact raw evidence, independent of receipt admission."""

    measurement: CallMeasurement
    request: Mapping[str, object]
    raw_response: str | None
    response_identity: Mapping[str, object]

    def __post_init__(self) -> None:
        """Own request and provider identity data so later transports cannot mutate evidence."""
        object.__setattr__(self, "request", freeze(self.request))
        object.__setattr__(self, "response_identity", freeze(self.response_identity))


@dataclass(frozen=True)
class BatchExtractionResult:
    """Bounded terminal dispositions and unique parent receipts for checkpoint consumers."""

    accepted: Mapping[str, Extraction]
    pending: Mapping[str, str]
    parents: tuple[ModelPhaseResult[BatchValidation], ...]

    def __post_init__(self) -> None:
        """Own aggregate dispositions without copying parent usage into members."""
        object.__setattr__(self, "accepted", freeze(self.accepted))
        object.__setattr__(self, "pending", freeze(self.pending))


def extract_batch_with_retries(
    tasks: NcaModelTasks, batch: ExtractionBatch, *, parsing_conventions: Mapping[str, object],
    transient_retries: int = 1,
    on_accept: Callable[[ModelPhaseResult[BatchValidation]], None] | None = None,
) -> BatchExtractionResult:
    """Retry at most once per node, checkpoint successes immediately, and bisect unresolved inputs."""
    if type(transient_retries) is not int or transient_retries not in {0, 1}:
        raise _model_error("Batch retry count must be zero or one", "NCA_BATCH_POLICY_INVALID")
    # Validate once before building a failure tree; no preflight failure is a provider call.
    build_batch_extraction_payload(batch, parsing_conventions=parsing_conventions)
    accepted, pending, parents = {}, {}, []
    retryable = {"NCA_MODEL_PROVIDER_FAILED", "NCA_MODEL_RESPONSE_INVALID", "NCA_BATCH_COVERAGE_INVALID",
                 "NCA_EXTRACTION_SCHEMA_INVALID", "NCA_EXTRACTION_EVIDENCE_INVALID"}

    def visit(current: ExtractionBatch) -> None:
        """Spend one bounded node budget, then recurse only into strictly smaller membership."""
        reasons = {}
        for _attempt in range(1 + transient_retries):
            try:
                result = tasks.extract_batch(current, parsing_conventions=parsing_conventions)
            except ValidationError as exc:
                if exc.code not in retryable:
                    raise
                reasons = {value.input_id: str(exc.code) for value in current.inputs}
                continue
            reasons = dict(result.value.pending)
            if result.value.accepted:
                # This callback deliberately sits outside the provider retry exception boundary.
                if on_accept is not None:
                    on_accept(result)
                parents.append(result)
                accepted.update(result.value.accepted)
                remaining = tuple(value for value in current.inputs if value.input_id in reasons)
                if remaining:
                    visit(_batch(remaining, ''.join(value.routed_sfm for value in remaining), current.contract_version))
                return
        children = split_batch(current)
        if children:
            for child in children:
                visit(child)
        else:
            key = current.inputs[0].input_id
            pending[key] = "NCA_BATCH_SINGLETON_FAILED: " + reasons[key]

    visit(batch)
    return BatchExtractionResult(accepted, pending, tuple(parents))
