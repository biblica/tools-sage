"""Serialize and strictly validate canonical NCA machine result documents."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
import re
from typing import Any, Mapping

from sage.coverage import CoverageAssessment
from sage.errors import ValidationError
from sage.findings import validate_global_finding_ids

from .models import (
    EXTRACTION_STATUSES,
    FOOTNOTE_ACTIONS,
    FOOTNOTE_OUTCOMES,
    FOOTNOTE_STATUSES,
    NUMERIC_KINDS,
    NUMERIC_QUALIFIERS,
    PROJECTION_STATUSES,
    READING_SELECTIONS,
    SEMANTIC_OUTCOMES,
    RunResult,
)


NCA_CAPABILITY_LIMITATION = (
    "Findings are limited by the selected LLM's language understanding and "
    "numeric-interpretation capabilities. SQS confidence checks have not been applied."
)
_CHECKS = frozenset({"number_accuracy", "presentation_consistency", "footnote_review"})
_STYLE_AREAS = frozenset(
    {
        "digits", "bands", "grouping", "decimal", "ordinals", "fractions",
        "ranges", "qualifiers", "contexts", "units",
    }
)
_HASH = re.compile(r"^[0-9a-f]{64}$")
_RATIONAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")
_PHASES = ("EXTRACTION", "CORRESPONDENCE", "FOOTNOTE")
_TASK_VERSIONS = {
    "EXTRACTION": "nca-extraction-1.0",
    "CORRESPONDENCE": "nca-correspondence-1.0",
    "FOOTNOTE": "nca-footnote-1.0",
}
_RECEIPT_FIELDS = {
    "phase", "task_version", "provider", "model", "reasoning_effort", "route_id",
    "routing_mode", "qualification_status", "prompt_sha256", "input_sha256",
    "response_sha256", "provider_metadata",
}


def _error(message: str, code: str) -> ValidationError:
    """Build one stable machine-result validation error."""
    return ValidationError(message, code=code)


def _plain(value: Any) -> Any:
    """Convert immutable NCA values to JSON-compatible data without float coercion."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Fraction):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise _error(f"NCA result contains an unsupported value: {type(value).__name__}", "NCA_RESULT_SCHEMA_INVALID")


def _expression_document(expression: object) -> dict[str, object]:
    """Serialize one typed numeric expression with reduced rational strings."""
    return {
        "expression_id": expression.expression_id,
        "stream_id": expression.stream_id,
        "surface": expression.surface,
        "span": list(expression.span),
        "values": [str(value) for value in expression.values],
        "kind": expression.kind,
        "unit": expression.unit,
        "qualifier": expression.qualifier,
        "role": expression.role,
        "role_spans": [list(span) for span in expression.role_spans],
        "representations": _plain(expression.representations),
    }


def _unit_document(result: object) -> dict[str, object]:
    """Serialize one typed unit result while retaining all three reference identities."""
    target = result.projected.target
    return {
        "unit_id": target.unit_id,
        "projection": {
            "target_references": [ref.label() for ref in target.target_references],
            "western_references": [ref.label() for ref in result.projected.western_references],
            "canonical_references": [ref.label() for ref in result.projected.canonical_references],
            "ol_references": list(result.ol_references),
            "precision": result.projected.precision,
            "status": result.projected.status,
            "source_sha256": target.source_sha256,
            "source_locator": _plain(target.source_locator),
            "target_text": target.main_text,
            "target_note_streams": [
                {"note_id": note.note_id, "text": note.text} for note in target.notes
            ],
        },
        "extraction": {
            "status": result.extraction.status,
            "limitations": list(result.extraction.limitations),
            "expressions": [_expression_document(item) for item in result.extraction.expressions],
        },
        "reading": {
            "selected": result.reading.selected,
            "footnote_action": result.reading.footnote_action,
            "registry_id": result.reading.registry_id,
            "source_ids": list(result.reading.source_ids),
            "source_validation_outcome": result.reading.source_validation_outcome,
            "semantic": {
                "outcome": result.reading.semantic.outcome,
                "evidence_ids": list(result.reading.semantic.evidence_ids),
                "reason_codes": list(result.reading.semantic.reason_codes),
            },
        },
        "footnote": {
            "action": result.footnote.action,
            "status": result.footnote.status,
            "outcome": result.footnote.outcome,
            "evidence_spans": [list(span) for span in result.footnote.evidence_spans],
            "evidence_note_ids": list(result.footnote.evidence_note_ids),
        },
        "final_outcome": result.final_outcome,
        "style_findings": _plain(result.style_findings),
        "limitations": list(result.limitations),
    }


def _validate_policy(policy: object) -> dict[str, object]:
    """Require the exact three boolean assessment toggles inside a policy snapshot."""
    if not isinstance(policy, Mapping) or not isinstance(policy.get("checks"), Mapping):
        raise _error("NCA result lacks its check policy.", "NCA_RESULT_POLICY_INVALID")
    checks = policy["checks"]
    if set(checks) != _CHECKS or any(type(checks[name]) is not bool for name in _CHECKS):
        raise _error("NCA result check policy is malformed.", "NCA_RESULT_POLICY_INVALID")
    if not any(checks.values()):
        raise _error("NCA result must enable at least one check.", "NCA_RESULT_POLICY_INVALID")
    return _plain(policy)


def numbers_result_document(
    run_result: RunResult,
    *,
    provenance: Mapping[str, object],
    check_policy: Mapping[str, object],
    model_receipts: Mapping[str, object],
) -> dict[str, object]:
    """Build a canonical result document from typed results and exact run evidence."""
    if not isinstance(run_result, RunResult):
        raise _error("NCA result builder requires a RunResult.", "NCA_RESULT_SCHEMA_INVALID")
    document = {
        "schema_version": "1.0",
        "workflow": "nca",
        "check_id": "NUMBERS",
        "provenance": _plain(provenance),
        "check_policy": _validate_policy(check_policy),
        "model_receipts": _plain(model_receipts),
        "limitations": {
            "capability": NCA_CAPABILITY_LIMITATION,
            "sqs_confidence_checks_applied": False,
        },
        "units": [_unit_document(unit) for unit in run_result.units],
        "findings": _plain(run_result.findings),
        "coverage": _plain(run_result.coverage),
        "summary": _plain(run_result.summary),
    }
    return document


def _require_mapping(value: object, label: str, code: str) -> Mapping[str, Any]:
    """Require one string-keyed result mapping."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _error(f"{label} must be an object.", code)
    return value


def _require_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    """Reject missing or invented fields in a canonical result object."""
    if set(value) != expected:
        raise _error(f"{label} fields are malformed.", "NCA_RESULT_SCHEMA_INVALID")


def _validate_hash(value: object, label: str) -> None:
    """Require one lowercase SHA-256 identity."""
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise _error(f"{label} is not a SHA-256 value.", "NCA_RESULT_PROVENANCE_INVALID")


def _validate_provenance(value: object) -> None:
    """Require immutable Job, Run, reference, style, and WIP identities."""
    raw = _require_mapping(value, "provenance", "NCA_RESULT_PROVENANCE_INVALID")
    required = {"run_id", "job_id", "style_profile", "reference_package", "wip"}
    if not required <= set(raw) or any(not isinstance(raw[name], str) or not raw[name] for name in ("run_id", "job_id")):
        raise _error("NCA provenance is incomplete.", "NCA_RESULT_PROVENANCE_INVALID")
    style = _require_mapping(raw["style_profile"], "style profile provenance", "NCA_RESULT_PROVENANCE_INVALID")
    reference = _require_mapping(raw["reference_package"], "reference provenance", "NCA_RESULT_PROVENANCE_INVALID")
    wip = _require_mapping(raw["wip"], "WIP provenance", "NCA_RESULT_PROVENANCE_INVALID")
    if not isinstance(style.get("selector"), str) or not style["selector"]:
        raise _error("Style profile selector is missing.", "NCA_RESULT_PROVENANCE_INVALID")
    if not isinstance(reference.get("package_id"), str) or not reference["package_id"]:
        raise _error("Reference package ID is missing.", "NCA_RESULT_PROVENANCE_INVALID")
    if not isinstance(wip.get("identity"), str) or not wip["identity"]:
        raise _error("WIP identity is missing.", "NCA_RESULT_PROVENANCE_INVALID")
    _validate_hash(style.get("sha256"), "Style profile hash")
    _validate_hash(reference.get("sha256"), "Reference package hash")
    _validate_hash(wip.get("sha256"), "WIP hash")


def _validate_receipts(value: object, *, required_phases: set[str]) -> None:
    """Validate exact phase-keyed provider/model receipts without creating defaults."""
    raw = _require_mapping(value, "model receipts", "NCA_RESULT_RECEIPT_INVALID")
    if set(raw) != set(_PHASES):
        raise _error("Model receipts must be keyed by every NCA phase.", "NCA_RESULT_RECEIPT_INVALID")
    present: set[str] = set()
    for phase in _PHASES:
        rows = raw[phase]
        if not isinstance(rows, list):
            raise _error("Model phase receipts must be arrays.", "NCA_RESULT_RECEIPT_INVALID")
        for row in rows:
            receipt = _require_mapping(row, "model receipt", "NCA_RESULT_RECEIPT_INVALID")
            if set(receipt) != _RECEIPT_FIELDS or receipt.get("phase") != phase or receipt.get("task_version") != _TASK_VERSIONS[phase] or any(
                not isinstance(receipt.get(field), str) or not receipt[field]
                for field in ("provider", "model", "reasoning_effort", "route_id")
            ):
                raise _error("Model receipt identity is incomplete.", "NCA_RESULT_RECEIPT_INVALID")
            if receipt.get("routing_mode") not in {"AUTOMATIC", "GLOBAL_OVERRIDE"} or receipt.get("qualification_status") not in {"RECOMMENDED", "QUALIFIED", "PROVISIONAL_UNQUALIFIED"}:
                raise _error("Model receipt route state is invalid.", "NCA_RESULT_RECEIPT_INVALID")
            if not isinstance(receipt.get("provider_metadata"), Mapping):
                raise _error("Model receipt metadata is malformed.", "NCA_RESULT_RECEIPT_INVALID")
            for field in ("prompt_sha256", "input_sha256", "response_sha256"):
                if not isinstance(receipt.get(field), str) or not _HASH.fullmatch(receipt[field]):
                    raise _error("Model receipt content identity is invalid.", "NCA_RESULT_RECEIPT_INVALID")
            present.add(phase)
    if not required_phases <= present:
        raise _error("Assessed NCA phases require their actual model receipts.", "NCA_RESULT_RECEIPT_INVALID")


def _validate_fraction(value: object) -> None:
    """Require one canonical reduced rational string."""
    if not isinstance(value, str) or not _RATIONAL.fullmatch(value):
        raise _error("Serialized numeric values must be rational strings.", "NCA_RESULT_FRACTION_INVALID")
    try:
        parsed = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise _error("Serialized numeric value is invalid.", "NCA_RESULT_FRACTION_INVALID") from exc
    if str(parsed) != value:
        raise _error("Serialized numeric values must be reduced.", "NCA_RESULT_FRACTION_INVALID")


def _validated_span(value: object, *, label: str) -> tuple[int, int]:
    """Require one nonempty half-open serialized evidence span."""
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(item) is not int for item in value)
        or value[0] < 0
        or value[1] <= value[0]
    ):
        raise _error(f"{label} is invalid.", "NCA_RESULT_EXPRESSION_INVALID")
    return value[0], value[1]


def _validate_expression(
    value: object,
    *,
    role_required: bool,
    target_text: str,
) -> tuple[str, tuple[int, int]]:
    """Validate one complete nested expression against its serialized target stream."""
    raw = _require_mapping(value, "numeric expression", "NCA_RESULT_EXPRESSION_INVALID")
    expected = {
        "expression_id", "stream_id", "surface", "span", "values", "kind", "unit",
        "qualifier", "role", "role_spans", "representations",
    }
    if set(raw) != expected:
        raise _error("Numeric expression fields are malformed.", "NCA_RESULT_EXPRESSION_INVALID")
    expression_id = raw["expression_id"]
    if not isinstance(expression_id, str) or not expression_id or raw["stream_id"] != "main":
        raise _error("Numeric expression identity is missing.", "NCA_RESULT_EXPRESSION_INVALID")
    surface = raw["surface"]
    span = _validated_span(raw["span"], label="Numeric expression span")
    if (
        not isinstance(surface, str)
        or not surface
        or span[1] > len(target_text)
        or target_text[span[0]:span[1]] != surface
    ):
        raise _error("Numeric expression surface and span disagree.", "NCA_RESULT_EXPRESSION_INVALID")
    values = raw["values"]
    if not isinstance(values, list) or not values:
        raise _error("Numeric expression values are missing.", "NCA_RESULT_FRACTION_INVALID")
    for number in values:
        _validate_fraction(number)
    kind = raw["kind"]
    expected_arity = 2 if kind in {"RANGE", "RATIO"} else 1
    if kind not in NUMERIC_KINDS or len(values) != expected_arity:
        raise _error("Numeric expression kind or arity is invalid.", "NCA_RESULT_EXPRESSION_INVALID")
    unit = raw["unit"]
    role = raw["role"]
    if unit is not None and (not isinstance(unit, str) or not unit):
        raise _error("Numeric expression unit is invalid.", "NCA_RESULT_EXPRESSION_INVALID")
    if raw["qualifier"] not in NUMERIC_QUALIFIERS or role is not None and (not isinstance(role, str) or not role):
        raise _error("Numeric expression meaning fields are invalid.", "NCA_RESULT_EXPRESSION_INVALID")
    role_spans = raw["role_spans"]
    if not isinstance(role_spans, list):
        raise _error("Numeric expression role spans are malformed.", "NCA_RESULT_EXPRESSION_INVALID")
    for role_span in role_spans:
        role_start, role_end = _validated_span(
            role_span, label="Numeric expression role span"
        )
        if role_end > len(target_text):
            raise _error(
                "Numeric expression role span is outside its target stream.",
                "NCA_RESULT_EXPRESSION_INVALID",
            )
    if role_required and (not isinstance(role, str) or not role or not role_spans):
        raise _error("Resolved correspondence requires role evidence.", "NCA_RESULT_EXPRESSION_INVALID")
    representations = raw["representations"]
    if not isinstance(representations, list):
        raise _error("Numeric expression representations are malformed.", "NCA_RESULT_EXPRESSION_INVALID")
    for representation_value in representations:
        representation = _require_mapping(representation_value, "numeric representation", "NCA_RESULT_EXPRESSION_INVALID")
        if set(representation) != {"surface", "span", "value"}:
            raise _error("Numeric representation fields are malformed.", "NCA_RESULT_EXPRESSION_INVALID")
        child_surface = representation["surface"]
        child_span = _validated_span(representation["span"], label="Numeric representation span")
        _validate_fraction(representation["value"])
        if (
            not isinstance(child_surface, str)
            or not child_surface
            or child_span[1] > len(target_text)
            or target_text[child_span[0]:child_span[1]] != child_surface
            or not (span[0] <= child_span[0] < child_span[1] <= span[1])
        ):
            raise _error("Numeric representation is outside its expression.", "NCA_RESULT_EXPRESSION_INVALID")
    return expression_id, span


def _validate_style_finding(
    value: object,
    *,
    target_text: str,
    note_streams: Mapping[str, str],
) -> None:
    """Validate one style decision against the exact body, heading, or note stream."""
    raw = _require_mapping(value, "style finding", "NCA_RESULT_SCHEMA_INVALID")
    required = {"rule_id", "area", "code", "status", "location"}
    optional = {"span", "surface", "expected", "stream_id", "note_id"}
    if not required <= set(raw) or set(raw) - required - optional:
        raise _error("Style finding fields are malformed.", "NCA_RESULT_SCHEMA_INVALID")
    if any(not isinstance(raw[field], str) or not raw[field] for field in required):
        raise _error("Style finding identity is incomplete.", "NCA_RESULT_DECISION_INVALID")
    if (
        not raw["code"].startswith("NCA_STYLE_")
        or raw["status"] not in {"REVIEW", "NOT_ASSESSED"}
        or raw["location"] not in {"body", "heading", "footnote"}
        or raw["area"] not in _STYLE_AREAS
    ):
        raise _error("Style finding state is invalid.", "NCA_RESULT_DECISION_INVALID")
    if ("span" in raw) != ("surface" in raw):
        raise _error("Style finding span and surface must remain paired.", "NCA_RESULT_EXPRESSION_INVALID")
    if "span" in raw:
        span = _validated_span(raw["span"], label="Style finding span")
        stream_text = target_text
        if raw["location"] == "footnote":
            note_id = raw.get("note_id")
            if (
                not isinstance(note_id, str)
                or raw.get("stream_id") != f"note:{note_id}"
                or note_id not in note_streams
            ):
                raise _error("Style finding note stream is invalid.", "NCA_RESULT_EXPRESSION_INVALID")
            stream_text = note_streams[note_id]
        if (
            not isinstance(raw["surface"], str)
            or span[1] > len(stream_text)
            or stream_text[span[0]:span[1]] != raw["surface"]
        ):
            raise _error("Style finding is outside its target stream.", "NCA_RESULT_EXPRESSION_INVALID")


def _expected_final_outcome(raw: Mapping[str, Any], checks: Mapping[str, bool]) -> str:
    """Derive the unit final state from enabled checks and validated phase decisions."""
    reading = raw["reading"]
    semantic = reading["semantic"]["outcome"]
    footnote = raw["footnote"]
    if checks["number_accuracy"]:
        if (
            checks["footnote_review"]
            and reading["selected"] == "ALT"
            and semantic == "REGISTERED_ALTERNATE"
            and footnote["status"] == "ADEQUATE"
            and reading["source_validation_outcome"] is not None
        ):
            return reading["source_validation_outcome"]
        if footnote["outcome"] == "REVIEW_MISSING_FOOTNOTE":
            return "REVIEW_MISSING_FOOTNOTE"
        return semantic
    if checks["footnote_review"] and footnote["outcome"] == "REVIEW_MISSING_FOOTNOTE":
        return "REVIEW_MISSING_FOOTNOTE"
    return "NOT_ASSESSED"


def _validate_unit(
    value: object,
    allowed_evidence: set[str],
    checks: Mapping[str, bool],
) -> Mapping[str, Any]:
    """Validate one unit's closed outcomes, references, spans, and evidence IDs."""
    raw = _require_mapping(value, "unit result", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(raw, {"unit_id", "projection", "extraction", "reading", "footnote", "final_outcome", "style_findings", "limitations"}, "unit result")
    unit_id = raw["unit_id"]
    if not isinstance(unit_id, str) or not unit_id:
        raise _error("Unit result ID is missing.", "NCA_RESULT_COVERAGE_INVALID")
    projection = _require_mapping(raw["projection"], "projection", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(
        projection,
        {
            "target_references", "western_references", "canonical_references",
            "ol_references", "precision", "status", "source_sha256", "source_locator",
            "target_text", "target_note_streams",
        },
        "projection",
    )
    if projection.get("status") not in PROJECTION_STATUSES:
        raise _error("Projection status is unknown.", "NCA_RESULT_ENUM_INVALID")
    western = projection.get("western_references")
    ol_references = projection.get("ol_references")
    for field in ("target_references", "western_references", "canonical_references"):
        references = projection.get(field)
        if not isinstance(references, list) or any(
            not isinstance(item, str) or not item for item in references
        ):
            raise _error("Projection references are malformed.", "NCA_RESULT_REFERENCE_INVALID")
    if (
        not isinstance(ol_references, list)
        or len(ol_references) not in {0, len(western)}
        or any(value is not None and (not isinstance(value, str) or not value) for value in ol_references)
        or any(value is None for value in ol_references)
        and projection.get("status") != "REGISTERED_ABSENCE"
    ):
        raise _error("OL references do not match resolved Western rows.", "NCA_RESULT_REFERENCE_INVALID")
    _validate_hash(projection.get("source_sha256"), "Target source hash")
    if not isinstance(projection.get("precision"), str) or not projection["precision"]:
        raise _error("Projection precision is missing.", "NCA_RESULT_SCHEMA_INVALID")
    locator = projection.get("source_locator")
    if not isinstance(locator, Mapping) or any(
        not isinstance(key, str) or not key or type(item) is not int
        for key, item in locator.items()
    ):
        raise _error("Projection source locator is malformed.", "NCA_RESULT_SCHEMA_INVALID")
    target_text = projection.get("target_text")
    if not isinstance(target_text, str):
        raise _error("Serialized target text is missing.", "NCA_RESULT_EXPRESSION_INVALID")
    note_rows = projection.get("target_note_streams")
    if not isinstance(note_rows, list):
        raise _error("Serialized target note streams are malformed.", "NCA_RESULT_EXPRESSION_INVALID")
    note_streams: dict[str, str] = {}
    # Preserve each validation boundary here in serialization order so later checks
    # can derive decisions and findings only from already validated canonical fields.
    for value_row in note_rows:
        note_row = _require_mapping(value_row, "target note stream", "NCA_RESULT_EXPRESSION_INVALID")
        if set(note_row) != {"note_id", "text"} or any(
            not isinstance(note_row[field], str) for field in ("note_id", "text")
        ) or not note_row["note_id"] or note_row["note_id"] in note_streams:
            raise _error("Serialized target note stream is invalid.", "NCA_RESULT_EXPRESSION_INVALID")
        note_streams[note_row["note_id"]] = note_row["text"]
    extraction = _require_mapping(raw["extraction"], "extraction", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(extraction, {"status", "limitations", "expressions"}, "extraction")
    if extraction.get("status") not in EXTRACTION_STATUSES:
        raise _error("Extraction status is unknown.", "NCA_RESULT_ENUM_INVALID")
    extraction_limitations = extraction.get("limitations")
    if (
        not isinstance(extraction_limitations, list)
        or any(not isinstance(item, str) or not item for item in extraction_limitations)
        or extraction["status"] != "COMPLETE" and not extraction_limitations
    ):
        raise _error("Extraction limitations are inconsistent.", "NCA_RESULT_EXPRESSION_INVALID")
    expressions = extraction.get("expressions")
    if not isinstance(expressions, list):
        raise _error("Extraction expressions must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    reading = _require_mapping(raw["reading"], "reading", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(
        reading,
        {"selected", "footnote_action", "registry_id", "source_ids", "source_validation_outcome", "semantic"},
        "reading",
    )
    semantic = _require_mapping(reading["semantic"], "semantic decision", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(semantic, {"outcome", "evidence_ids", "reason_codes"}, "semantic decision")
    if reading["selected"] not in READING_SELECTIONS or semantic["outcome"] not in SEMANTIC_OUTCOMES or raw.get("final_outcome") not in SEMANTIC_OUTCOMES:
        raise _error("Unit result contains an unknown semantic outcome.", "NCA_RESULT_ENUM_INVALID")
    role_required = semantic["outcome"] in {
        "PASS_AUTHORITY1", "PASS_EQUIVALENT_NUMERIC_EXPRESSION", "PASS_UNIT_CONVERSION",
        "REGISTERED_ALTERNATE", "NO_CONFIGURED_OL_READING", "REVIEW_VALUE_DIFFERENCE",
        "REVIEW_NUMBER_MISSING", "REVIEW_NUMBER_ADDED",
    }
    identities: list[str] = []
    spans: list[tuple[int, int]] = []
    for expression in expressions:
        expression_id, span = _validate_expression(
            expression, role_required=role_required, target_text=target_text
        )
        identities.append(expression_id)
        spans.append(span)
    if len(identities) != len(set(identities)) or any(
        left[0] < right[1] and right[0] < left[1]
        for index, left in enumerate(spans)
        for right in spans[index + 1:]
    ):
        raise _error("Numeric expression evidence overlaps or repeats.", "NCA_RESULT_EXPRESSION_INVALID")
    if reading["footnote_action"] not in FOOTNOTE_ACTIONS:
        raise _error("Reading footnote action is unknown.", "NCA_RESULT_ENUM_INVALID")
    evidence_ids = semantic["evidence_ids"]
    if not isinstance(evidence_ids, list) or any(item not in allowed_evidence for item in evidence_ids):
        raise _error("Semantic evidence is outside the allowed result set.", "NCA_RESULT_EVIDENCE_INVALID")
    reason_codes = semantic["reason_codes"]
    if not isinstance(reason_codes, list) or any(
        not isinstance(item, str) or not item for item in reason_codes
    ):
        raise _error("Semantic reason codes are malformed.", "NCA_RESULT_DECISION_INVALID")
    source_ids = reading["source_ids"]
    if not isinstance(source_ids, list) or any(item not in allowed_evidence for item in source_ids):
        raise _error("Reading sources are outside the allowed result set.", "NCA_RESULT_EVIDENCE_INVALID")
    if reading["registry_id"] is not None and (
        not isinstance(reading["registry_id"], str) or not reading["registry_id"]
    ):
        raise _error("Reading registry identity is malformed.", "NCA_RESULT_DECISION_INVALID")
    source_outcome = reading["source_validation_outcome"]
    if source_outcome is not None and source_outcome not in {
        "PASS_AUTHORITY1", "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
        "CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE",
        "NO_CONFIGURED_OL_READING",
    }:
        raise _error("Reading source policy is invalid.", "NCA_RESULT_DECISION_INVALID")
    if reading["selected"] in {"UNSUPPORTED", "UNASSESSED"} and (
        reading["footnote_action"] != "NONE"
        or reading["registry_id"] is not None
        or source_ids
        or source_outcome is not None
    ):
        raise _error("Unsupported reading retains invented policy state.", "NCA_RESULT_DECISION_INVALID")
    if reading["selected"] == "UNASSESSED" and semantic["outcome"] != "NOT_ASSESSED":
        raise _error("Unassessed reading has a semantic claim.", "NCA_RESULT_DECISION_INVALID")
    if reading["selected"] == "ALT" and (
        not isinstance(reading["registry_id"], str)
        or not source_ids
        or source_outcome not in {
            "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
            "CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE",
        }
        or semantic["outcome"] not in {
            "REGISTERED_ALTERNATE", "REVIEW_VALUE_DIFFERENCE", "REVIEW_NUMBER_MISSING",
            "REVIEW_NUMBER_ADDED", "INSUFFICIENT_EVIDENCE",
        }
    ):
        raise _error("Alternate reading authority is inconsistent.", "NCA_RESULT_DECISION_INVALID")
    if reading["selected"] == "OL" and (
        semantic["outcome"] == "REGISTERED_ALTERNATE"
        or source_outcome in {
            "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
            "CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE",
        }
    ):
        raise _error("OL reading authority is inconsistent.", "NCA_RESULT_DECISION_INVALID")
    footnote = _require_mapping(raw["footnote"], "footnote", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(
        footnote,
        {"action", "status", "outcome", "evidence_spans", "evidence_note_ids"},
        "footnote",
    )
    if footnote["action"] not in FOOTNOTE_ACTIONS or footnote["status"] not in FOOTNOTE_STATUSES or footnote["outcome"] not in FOOTNOTE_OUTCOMES:
        raise _error("Footnote result contains an unknown outcome.", "NCA_RESULT_ENUM_INVALID")
    if checks["footnote_review"]:
        if footnote["action"] != reading["footnote_action"]:
            raise _error("Footnote action disagrees with its reading.", "NCA_RESULT_DECISION_INVALID")
    elif footnote != {
        "action": "NONE", "status": "NOT_ASSESSED", "outcome": "NONE",
        "evidence_spans": [], "evidence_note_ids": [],
    }:
        raise _error("Disabled footnote review retains an assessment.", "NCA_RESULT_DECISION_INVALID")
    valid_footnote = {
        "NONE": {("NOT_REQUIRED", "NONE"), ("NOT_ASSESSED", "NONE"), ("NOT_ASSESSED", "INSUFFICIENT_EVIDENCE")},
        "RECOMMEND": {("ADEQUATE", "NONE"), ("MISSING", "ADVISORY"), ("INADEQUATE", "ADVISORY"), ("NOT_ASSESSED", "INSUFFICIENT_EVIDENCE")},
        "REQUIRE": {("ADEQUATE", "NONE"), ("MISSING", "REVIEW_MISSING_FOOTNOTE"), ("INADEQUATE", "REVIEW_MISSING_FOOTNOTE"), ("NOT_ASSESSED", "INSUFFICIENT_EVIDENCE")},
    }
    if (footnote["status"], footnote["outcome"]) not in valid_footnote[footnote["action"]]:
        raise _error("Footnote status contradicts its outcome.", "NCA_RESULT_DECISION_INVALID")
    evidence_spans = footnote["evidence_spans"]
    note_ids = footnote["evidence_note_ids"]
    if not isinstance(evidence_spans, list) or not isinstance(note_ids, list) or len(evidence_spans) != len(note_ids):
        raise _error("Footnote evidence is malformed.", "NCA_RESULT_EXPRESSION_INVALID")
    for note_id, evidence_span in zip(note_ids, evidence_spans):
        span = _validated_span(evidence_span, label="Footnote evidence span")
        if not isinstance(note_id, str) or note_id not in note_streams or span[1] > len(note_streams[note_id]):
            raise _error("Footnote evidence is outside its note stream.", "NCA_RESULT_EXPRESSION_INVALID")
    if footnote["status"] == "ADEQUATE" and not evidence_spans or footnote["status"] != "ADEQUATE" and evidence_spans:
        raise _error("Footnote evidence disagrees with its status.", "NCA_RESULT_DECISION_INVALID")
    if not isinstance(raw["style_findings"], list) or not isinstance(raw["limitations"], list) or any(
        not isinstance(item, str) or not item for item in raw["limitations"]
    ):
        raise _error("Unit result collections are malformed.", "NCA_RESULT_SCHEMA_INVALID")
    for style_finding in raw["style_findings"]:
        _validate_style_finding(
            style_finding, target_text=target_text, note_streams=note_streams
        )
    if not checks["presentation_consistency"] and raw["style_findings"]:
        raise _error("Disabled presentation review retains an assessment.", "NCA_RESULT_DECISION_INVALID")
    if raw["final_outcome"] != _expected_final_outcome(raw, checks):
        raise _error("Unit final outcome contradicts its phase decisions.", "NCA_RESULT_DECISION_INVALID")
    return raw


def _expected_finding_signatures(
    units: list[Mapping[str, Any]], checks: Mapping[str, bool]
) -> Counter[tuple[object, ...]]:
    """Derive the finding categories and codes that enabled unit decisions require."""
    expected: Counter[tuple[object, ...]] = Counter()
    passes = {
        "PASS_AUTHORITY1", "PASS_EQUIVALENT_NUMERIC_EXPRESSION", "PASS_UNIT_CONVERSION",
        "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
        "CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE",
        "NO_CONFIGURED_OL_READING", "REGISTERED_ALTERNATE",
    }
    for unit in units:
        unit_id = unit["unit_id"]
        semantic = unit["reading"]["semantic"]
        screened = "NO_NUMERIC_CONTENT_REFERENCE_NOT_REQUIRED" in semantic["reason_codes"]
        if checks["number_accuracy"] and not screened and semantic["outcome"] not in passes:
            category = "EVIDENCE" if semantic["outcome"] in {
                "INSUFFICIENT_EVIDENCE", "REFERENCE_NOT_INDEXED"
            } else "ACCURACY"
            expected[(unit_id, category, f"NCA_{semantic['outcome']}", None, None)] += 1
        footnote = unit["footnote"]
        if checks["footnote_review"] and footnote["outcome"] in {
            "ADVISORY", "REVIEW_MISSING_FOOTNOTE", "INSUFFICIENT_EVIDENCE"
        }:
            expected[(unit_id, "FOOTNOTE", f"NCA_FOOTNOTE_{footnote['outcome']}", None, None)] += 1
        if checks["presentation_consistency"]:
            for style in unit["style_findings"]:
                if style["status"] == "REVIEW":
                    span = tuple(style["span"]) if "span" in style else None
                    expected[(unit_id, "STYLE", style["code"], style["rule_id"], span)] += 1
    return expected


def _validate_findings(
    value: object,
    allowed_evidence: set[str],
    *,
    units: list[Mapping[str, Any]],
    checks: Mapping[str, bool],
) -> list[Mapping[str, Any]]:
    """Require exact findings bound to their owning unit decisions and references."""
    if not isinstance(value, list):
        raise _error("NCA findings must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    unit_by_id = {unit["unit_id"]: unit for unit in units}
    actual: Counter[tuple[object, ...]] = Counter()
    rows: list[Mapping[str, Any]] = []
    for value_row in value:
        row = _require_mapping(value_row, "finding", "NCA_RESULT_SCHEMA_INVALID")
        category = row.get("category")
        common = {
            "finding_id", "work_unit_id", "category", "code", "severity", "target_reference",
            "target_references", "western_references", "ol_reference", "ol_references",
            "selected_reading", "source_ids", "evidence_ids", "message",
        }
        extras = {
            "FOOTNOTE": {"footnote_action", "footnote_status", "suggested_note"},
            "STYLE": {"rule_id", "span"},
            "ACCURACY": set(),
            "EVIDENCE": set(),
        }
        if category not in extras or set(row) != common | extras[category] or not str(row.get("code", "")).startswith("NCA_"):
            raise _error("Non-NUMBERS finding entered an NCA result.", "NCA_RESULT_FINDING_INVALID")
        unit = unit_by_id.get(row.get("work_unit_id"))
        if unit is None:
            raise _error("NCA finding has no owning unit.", "NCA_RESULT_FINDING_INVALID")
        projection = unit["projection"]
        target_refs = projection["target_references"]
        ol_refs = projection["ol_references"]
        expected_context = {
            "target_reference": target_refs[0] if target_refs else None,
            "target_references": target_refs,
            "western_references": projection["western_references"],
            "ol_reference": ol_refs[0] if len(ol_refs) == 1 else None,
            "ol_references": ol_refs,
            "selected_reading": unit["reading"]["selected"],
            "source_ids": unit["reading"]["source_ids"],
            "evidence_ids": unit["reading"]["semantic"]["evidence_ids"],
        }
        if any(row.get(field) != expected for field, expected in expected_context.items()):
            raise _error("NCA finding context disagrees with its unit.", "NCA_RESULT_FINDING_INVALID")
        for field in ("source_ids", "evidence_ids"):
            identifiers = row[field]
            if not isinstance(identifiers, list) or any(item not in allowed_evidence for item in identifiers):
                raise _error("Finding evidence is outside the allowed result set.", "NCA_RESULT_EVIDENCE_INVALID")
        if not isinstance(row.get("message"), str) or not row["message"]:
            raise _error("NCA finding message is missing.", "NCA_RESULT_FINDING_INVALID")
        rule_id = row.get("rule_id") if category == "STYLE" else None
        span_value = row.get("span") if category == "STYLE" else None
        span = tuple(span_value) if isinstance(span_value, list) else None
        if category == "STYLE" and (
            not isinstance(rule_id, str)
            or not rule_id
            or span_value is not None and not isinstance(span_value, list)
        ):
            raise _error("NCA style finding is malformed.", "NCA_RESULT_FINDING_INVALID")
        if category == "FOOTNOTE" and (
            row["footnote_action"] != unit["footnote"]["action"]
            or row["footnote_status"] != unit["footnote"]["status"]
            or row["suggested_note"] is not None and not isinstance(row["suggested_note"], str)
        ):
            raise _error("NCA footnote finding disagrees with its unit.", "NCA_RESULT_FINDING_INVALID")
        actual[(unit["unit_id"], category, row["code"], rule_id, span)] += 1
        rows.append(row)
    if actual != _expected_finding_signatures(units, checks):
        raise _error("NCA findings do not derive from enabled unit decisions.", "NCA_RESULT_FINDING_INVALID")
    try:
        validate_global_finding_ids([dict(row) for row in rows])
    except ValidationError as exc:
        raise _error(str(exc), "NCA_RESULT_FINDING_INVALID") from exc
    return rows


def _validate_coverage(
    value: object,
    expected_unit_ids: tuple[str, ...],
    actual_ids: list[str],
    *,
    findings_count: int,
    required_evidence_complete: bool,
) -> None:
    """Reconcile expected and assessed unit identities and controlled coverage state."""
    if len(expected_unit_ids) != len(set(expected_unit_ids)) or set(expected_unit_ids) != set(actual_ids) or len(actual_ids) != len(set(actual_ids)):
        raise _error("Expected NCA units do not reconcile exactly once.", "NCA_RESULT_COVERAGE_INVALID")
    raw = _require_mapping(value, "coverage", "NCA_RESULT_COVERAGE_INVALID")
    expected = raw.get("expected_unit_ids")
    assessed = raw.get("assessed_unit_ids")
    if expected != list(expected_unit_ids) or assessed != list(actual_ids):
        raise _error("Coverage unit ledger does not match the validated units.", "NCA_RESULT_COVERAGE_INVALID")
    try:
        assessment = CoverageAssessment(
            result=raw["result"],
            coverage=raw["coverage"],
            confidence_basis=raw["confidence_basis"],
            restrictions=tuple(raw.get("restrictions", [])),
            skipped_checks=tuple(raw.get("skipped_checks", [])),
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise _error("Coverage state is inconsistent.", "NCA_RESULT_COVERAGE_INVALID") from exc
    if assessment.coverage == "PARTIAL" and assessment.result != "INSUFFICIENT_DATA":
        raise _error("Partial evidence cannot claim an NCA all-clear.", "NCA_RESULT_COVERAGE_INVALID")
    if not required_evidence_complete and (
        assessment.coverage != "PARTIAL" or assessment.result != "INSUFFICIENT_DATA"
    ):
        raise _error("Incomplete NCA evidence requires partial insufficient-data coverage.", "NCA_RESULT_COVERAGE_INVALID")
    if required_evidence_complete and assessment.coverage == "PARTIAL":
        raise _error("Complete NCA evidence cannot claim unexplained partial coverage.", "NCA_RESULT_COVERAGE_INVALID")
    if assessment.coverage in {"COMPLETE", "COMPLETE_WITH_RESTRICTIONS"}:
        expected_result = "FINDINGS" if findings_count else "NO_FINDINGS"
        if assessment.result != expected_result:
            raise _error("Coverage result does not match actual findings.", "NCA_RESULT_COVERAGE_INVALID")
    if assessment.coverage == "NOT_ASSESSED" and findings_count:
        raise _error("An unassessed result cannot contain findings.", "NCA_RESULT_COVERAGE_INVALID")


def validate_numbers_result(
    document: Mapping[str, object],
    *,
    expected_unit_ids: tuple[str, ...],
    allowed_evidence_ids: tuple[str, ...],
) -> dict[str, object]:
    """Validate one complete canonical NCA result against external coverage bounds."""
    raw = _require_mapping(document, "NCA result", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(raw, {"schema_version", "workflow", "check_id", "provenance", "check_policy", "model_receipts", "limitations", "units", "findings", "coverage", "summary"}, "NCA result")
    if raw["schema_version"] != "1.0" or raw["workflow"] != "nca" or raw["check_id"] != "NUMBERS":
        raise _error("NCA result identity is invalid.", "NCA_RESULT_SCHEMA_INVALID")
    _validate_provenance(raw["provenance"])
    policy = _validate_policy(raw["check_policy"])
    limitations = _require_mapping(raw["limitations"], "limitations", "NCA_RESULT_LIMITATION_REQUIRED")
    if limitations.get("capability") != NCA_CAPABILITY_LIMITATION or limitations.get("sqs_confidence_checks_applied") is not False:
        raise _error("NCA capability and SQS limitation is required.", "NCA_RESULT_LIMITATION_REQUIRED")
    units = raw["units"]
    if not isinstance(units, list):
        raise _error("NCA units must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    allowed = set(allowed_evidence_ids)
    if len(allowed) != len(allowed_evidence_ids):
        raise _error("Allowed evidence IDs must be unique.", "NCA_RESULT_EVIDENCE_INVALID")
    checks = policy["checks"]
    validated_units = [_validate_unit(unit, allowed, checks) for unit in units]
    actual_ids = [unit["unit_id"] for unit in validated_units]
    findings = _validate_findings(
        raw["findings"], allowed, units=validated_units, checks=checks
    )
    required_evidence_complete = all(
        (
            unit["extraction"]["status"] == "COMPLETE"
            or "PRESENTATION_CHECK_DISABLED" in unit["limitations"]
        )
        and (
            unit["projection"]["precision"] == "STYLE_STREAM"
            or not (checks["number_accuracy"] or checks["footnote_review"])
            or unit["reading"]["semantic"]["outcome"]
            not in {"INSUFFICIENT_EVIDENCE", "REFERENCE_NOT_INDEXED"}
        )
        and (
            not checks["footnote_review"]
            or unit["projection"]["precision"] == "STYLE_STREAM"
            or unit["footnote"]["outcome"] != "INSUFFICIENT_EVIDENCE"
        )
        for unit in validated_units
    )
    _validate_coverage(
        raw["coverage"], expected_unit_ids, actual_ids,
        findings_count=len(findings),
        required_evidence_complete=required_evidence_complete,
    )
    required_phases: set[str] = set()
    if any(unit["extraction"]["status"] in {"COMPLETE", "PARTIAL"} for unit in validated_units):
        required_phases.add("EXTRACTION")
    if (checks["number_accuracy"] or checks["footnote_review"]) and any(
        unit["projection"]["precision"] != "STYLE_STREAM"
        and (
            unit["reading"]["selected"] in {"OL", "ALT"}
            or unit["reading"]["semantic"]["outcome"]
            in {"REVIEW_NUMBER_MISSING", "REVIEW_NUMBER_ADDED", "REVIEW_VALUE_DIFFERENCE"}
        )
        for unit in validated_units
    ):
        required_phases.add("CORRESPONDENCE")
    if checks["footnote_review"] and any(
        unit["footnote"]["status"] in {"ADEQUATE", "INADEQUATE"}
        for unit in validated_units
    ):
        required_phases.add("FOOTNOTE")
    _validate_receipts(raw["model_receipts"], required_phases=required_phases)
    summary = _require_mapping(raw["summary"], "summary", "NCA_RESULT_SCHEMA_INVALID")
    expected_summary = {
        "units": len(units),
        "findings": len(findings),
        "expressions": sum(len(unit["extraction"]["expressions"]) for unit in units),
        "insufficient_evidence": sum(
            "PRESENTATION_CHECK_DISABLED" not in unit["limitations"]
            and (
                unit["extraction"]["status"] != "COMPLETE"
                or unit["reading"]["semantic"]["outcome"] == "INSUFFICIENT_EVIDENCE"
                or unit["footnote"]["outcome"] == "INSUFFICIENT_EVIDENCE"
            )
            for unit in units
        ),
        "reference_not_indexed": sum(
            unit["final_outcome"] == "REFERENCE_NOT_INDEXED" for unit in units
        ),
        "not_assessed": sum(
            unit["final_outcome"] == "NOT_ASSESSED" for unit in units
        ),
        "extraction_complete": sum(
            unit["extraction"]["status"] == "COMPLETE" for unit in units
        ),
        "extraction_partial": sum(
            unit["extraction"]["status"] == "PARTIAL" for unit in units
        ),
        "extraction_unsupported": sum(
            unit["extraction"]["status"] == "UNSUPPORTED" for unit in units
        ),
    }
    if any(summary.get(key) != value for key, value in expected_summary.items()):
        raise _error("NCA summary does not derive from the result payload.", "NCA_RESULT_SUMMARY_INVALID")
    return _plain(raw)
