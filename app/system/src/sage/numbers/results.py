"""Serialize and strictly validate canonical NCA machine result documents."""

from __future__ import annotations

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
_HASH = re.compile(r"^[0-9a-f]{64}$")
_RATIONAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")
_PHASES = ("EXTRACTION", "CORRESPONDENCE", "FOOTNOTE")


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
            "precision": result.projected.precision,
            "status": result.projected.status,
            "source_sha256": target.source_sha256,
            "source_locator": _plain(target.source_locator),
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


def _validate_receipts(value: object, *, receipts_required: bool) -> None:
    """Validate exact phase-keyed provider/model receipts without creating defaults."""
    raw = _require_mapping(value, "model receipts", "NCA_RESULT_RECEIPT_INVALID")
    if set(raw) != set(_PHASES):
        raise _error("Model receipts must be keyed by every NCA phase.", "NCA_RESULT_RECEIPT_INVALID")
    count = 0
    for phase in _PHASES:
        rows = raw[phase]
        if not isinstance(rows, list):
            raise _error("Model phase receipts must be arrays.", "NCA_RESULT_RECEIPT_INVALID")
        for row in rows:
            receipt = _require_mapping(row, "model receipt", "NCA_RESULT_RECEIPT_INVALID")
            if receipt.get("phase") != phase or any(
                not isinstance(receipt.get(field), str) or not receipt[field]
                for field in ("provider", "model")
            ):
                raise _error("Model receipt identity is incomplete.", "NCA_RESULT_RECEIPT_INVALID")
            for field in ("prompt_sha256", "input_sha256", "response_sha256"):
                if not isinstance(receipt.get(field), str) or not _HASH.fullmatch(receipt[field]):
                    raise _error("Model receipt content identity is invalid.", "NCA_RESULT_RECEIPT_INVALID")
            count += 1
    if receipts_required and count == 0:
        raise _error("Assessed NCA units require actual model receipts.", "NCA_RESULT_RECEIPT_INVALID")


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


def _validate_unit(value: object, allowed_evidence: set[str]) -> str:
    """Validate one unit's closed outcomes, references, spans, and evidence IDs."""
    raw = _require_mapping(value, "unit result", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(raw, {"unit_id", "projection", "extraction", "reading", "footnote", "final_outcome", "style_findings", "limitations"}, "unit result")
    unit_id = raw["unit_id"]
    if not isinstance(unit_id, str) or not unit_id:
        raise _error("Unit result ID is missing.", "NCA_RESULT_COVERAGE_INVALID")
    projection = _require_mapping(raw["projection"], "projection", "NCA_RESULT_SCHEMA_INVALID")
    if projection.get("status") not in PROJECTION_STATUSES:
        raise _error("Projection status is unknown.", "NCA_RESULT_ENUM_INVALID")
    _validate_hash(projection.get("source_sha256"), "Target source hash")
    extraction = _require_mapping(raw["extraction"], "extraction", "NCA_RESULT_SCHEMA_INVALID")
    if extraction.get("status") not in EXTRACTION_STATUSES:
        raise _error("Extraction status is unknown.", "NCA_RESULT_ENUM_INVALID")
    expressions = extraction.get("expressions")
    if not isinstance(expressions, list):
        raise _error("Extraction expressions must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    for expression in expressions:
        item = _require_mapping(expression, "numeric expression", "NCA_RESULT_SCHEMA_INVALID")
        values = item.get("values")
        if not isinstance(values, list) or not values:
            raise _error("Numeric expression values are missing.", "NCA_RESULT_FRACTION_INVALID")
        for number in values:
            _validate_fraction(number)
    reading = _require_mapping(raw["reading"], "reading", "NCA_RESULT_SCHEMA_INVALID")
    semantic = _require_mapping(reading.get("semantic"), "semantic decision", "NCA_RESULT_SCHEMA_INVALID")
    if reading.get("selected") not in READING_SELECTIONS or semantic.get("outcome") not in SEMANTIC_OUTCOMES or raw.get("final_outcome") not in SEMANTIC_OUTCOMES:
        raise _error("Unit result contains an unknown semantic outcome.", "NCA_RESULT_ENUM_INVALID")
    if reading.get("footnote_action") not in FOOTNOTE_ACTIONS:
        raise _error("Reading footnote action is unknown.", "NCA_RESULT_ENUM_INVALID")
    evidence_ids = semantic.get("evidence_ids")
    if not isinstance(evidence_ids, list) or any(item not in allowed_evidence for item in evidence_ids):
        raise _error("Semantic evidence is outside the allowed result set.", "NCA_RESULT_EVIDENCE_INVALID")
    source_ids = reading.get("source_ids")
    if not isinstance(source_ids, list) or any(item not in allowed_evidence for item in source_ids):
        raise _error("Reading sources are outside the allowed result set.", "NCA_RESULT_EVIDENCE_INVALID")
    footnote = _require_mapping(raw["footnote"], "footnote", "NCA_RESULT_SCHEMA_INVALID")
    if footnote.get("action") not in FOOTNOTE_ACTIONS or footnote.get("status") not in FOOTNOTE_STATUSES or footnote.get("outcome") not in FOOTNOTE_OUTCOMES:
        raise _error("Footnote result contains an unknown outcome.", "NCA_RESULT_ENUM_INVALID")
    if not isinstance(raw["style_findings"], list) or not isinstance(raw["limitations"], list):
        raise _error("Unit result collections are malformed.", "NCA_RESULT_SCHEMA_INVALID")
    return unit_id


def _validate_findings(value: object, allowed_evidence: set[str]) -> list[Mapping[str, Any]]:
    """Require NUMBERS-only findings with global identities and bounded evidence."""
    if not isinstance(value, list):
        raise _error("NCA findings must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    rows: list[Mapping[str, Any]] = []
    for value_row in value:
        row = _require_mapping(value_row, "finding", "NCA_RESULT_SCHEMA_INVALID")
        if row.get("category") not in {"ACCURACY", "FOOTNOTE", "STYLE", "EVIDENCE"} or not str(row.get("code", "")).startswith("NCA_"):
            raise _error("Non-NUMBERS finding entered an NCA result.", "NCA_RESULT_FINDING_INVALID")
        for field in ("source_ids", "evidence_ids"):
            identifiers = row.get(field, [])
            if not isinstance(identifiers, list) or any(item not in allowed_evidence for item in identifiers):
                raise _error("Finding evidence is outside the allowed result set.", "NCA_RESULT_EVIDENCE_INVALID")
        rows.append(row)
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
    _validate_policy(raw["check_policy"])
    limitations = _require_mapping(raw["limitations"], "limitations", "NCA_RESULT_LIMITATION_REQUIRED")
    if limitations.get("capability") != NCA_CAPABILITY_LIMITATION or limitations.get("sqs_confidence_checks_applied") is not False:
        raise _error("NCA capability and SQS limitation is required.", "NCA_RESULT_LIMITATION_REQUIRED")
    units = raw["units"]
    if not isinstance(units, list):
        raise _error("NCA units must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    allowed = set(allowed_evidence_ids)
    if len(allowed) != len(allowed_evidence_ids):
        raise _error("Allowed evidence IDs must be unique.", "NCA_RESULT_EVIDENCE_INVALID")
    actual_ids = [_validate_unit(unit, allowed) for unit in units]
    findings = _validate_findings(raw["findings"], allowed)
    _validate_coverage(
        raw["coverage"], expected_unit_ids, actual_ids, findings_count=len(findings)
    )
    receipts_required = any(
        unit["extraction"].get("status") != "UNSUPPORTED" for unit in units
    )
    _validate_receipts(raw["model_receipts"], receipts_required=receipts_required)
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
