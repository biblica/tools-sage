"""Serialize and strictly validate canonical NCA machine result documents.

Simplified per the 2026-09-28 rewrite: a group's result is its numeric
comparison outcome (PASS/FAIL/NEEDS_REVIEW/NOT_ASSESSED) plus any noteworthy
text-critical notes -- no exact spans, kinds, roles, or per-row correspondence.
`presentation_consistency` remains an accepted check-policy toggle for
compatibility with existing Job configuration, but has no effect: this
pipeline is number-accuracy (and its noteworthy-info advisory) only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Any, Mapping

from sage.coverage import CoverageAssessment
from sage.errors import ValidationError
from sage.findings import validate_global_finding_ids

from .models import COMPARISON_MODES, COMPARISON_OUTCOMES, EXTRACTION_STATUSES, PROJECTION_STATUSES


NCA_CAPABILITY_LIMITATION = (
    "Findings are limited by the selected LLM's language understanding and "
    "numeric-interpretation capabilities. SQS confidence checks have not been applied."
)
_CHECKS = frozenset({"number_accuracy", "presentation_consistency", "footnote_review"})
_HASH = re.compile(r"^[0-9a-f]{64}$")
_RATIONAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")
_TASK_VERSIONS = {"EXTRACTION": "nca-extraction-1.0"}
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


@dataclass(frozen=True, slots=True)
class GroupResult:
    """One indexed group's extraction, local comparison, limitations, and notes."""

    projected: Any
    extraction: Any
    comparison: Any
    limitations: tuple
    notes: tuple


@dataclass(frozen=True, slots=True)
class NumbersResult:
    """An NCA run's aggregate groups, findings, coverage, summary, and call metrics."""

    groups: tuple
    findings: tuple
    coverage: Mapping[str, object]
    summary: Mapping[str, object]
    metrics: Mapping[str, object]


def _group_document(group: GroupResult) -> dict[str, object]:
    """Serialize one group result with its WIP/expected values and comparison outcome."""
    unit = group.projected
    return {
        "unit_id": unit.target.unit_id,
        "projection_status": unit.status,
        "western_references": [ref.label() for ref in unit.western_references],
        "target_references": [ref.label() for ref in unit.target.target_references],
        "extraction": {
            "status": group.extraction.status,
            "limitations": list(group.extraction.limitations),
            "values": [str(value) for value in group.extraction.values],
        },
        "comparison": {
            "outcome": group.comparison.outcome,
            "mode": group.comparison.mode,
            "authority": group.comparison.authority,
            "wip_values": [str(value) for value in group.comparison.wip_values],
            "expected_values": [str(value) for value in group.comparison.expected_values],
            "review_context": _plain(group.comparison.review_context),
        },
        "limitations": list(group.limitations),
        "notes": [_plain(note) for note in group.notes],
    }


def group_findings(group: GroupResult) -> list[dict[str, object]]:
    """Create NUMBERS findings for a FAIL or NEEDS_REVIEW comparison outcome.

    PASS and NOT_ASSESSED produce no findings -- NOT_ASSESSED coverage gaps are
    reported through the run's restrictions, not as a per-group finding.
    """
    if group.comparison.outcome not in {"FAIL", "NEEDS_REVIEW"}:
        return []
    unit = group.projected
    base = {
        "target_references": [ref.label() for ref in unit.target.target_references],
        "western_references": [ref.label() for ref in unit.western_references],
    }
    severity = "REVIEW" if group.comparison.outcome == "NEEDS_REVIEW" else "BLOCKING"
    return [{
        **base,
        "category": "ACCURACY",
        "code": f"NCA_NUMBER_{group.comparison.outcome}",
        "severity": severity,
        "mode": group.comparison.mode,
        "wip_values": [str(value) for value in group.comparison.wip_values],
        "expected_values": [str(value) for value in group.comparison.expected_values],
        "message": (
            "Numeric values differ from the indexed reference."
            if group.comparison.outcome == "FAIL"
            else "Same numeric values in a different order -- confirm this is a faithful "
                 "reordering, not a swapped referent."
        ),
    }]


def group_summary(groups: tuple[GroupResult, ...], *, checks: Mapping[str, bool], findings_count: int) -> dict[str, int]:
    """Derive handover counters directly from the validated group results."""
    outcomes = tuple(group.comparison.outcome for group in groups) if checks["number_accuracy"] else ()
    return {
        "groups": len(groups),
        "passes": outcomes.count("PASS"),
        "failures": outcomes.count("FAIL"),
        "needs_review": outcomes.count("NEEDS_REVIEW"),
        "not_assessed": outcomes.count("NOT_ASSESSED"),
        "noteworthy_notes": sum(len(group.notes) for group in groups) if checks["footnote_review"] else 0,
        "extraction_complete": sum(group.extraction.status == "COMPLETE" for group in groups),
        "extraction_partial": sum(group.extraction.status == "PARTIAL" for group in groups),
        "extraction_unsupported": sum(group.extraction.status == "UNSUPPORTED" for group in groups),
        "findings": findings_count,
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
    run_result: NumbersResult,
    *,
    provenance: Mapping[str, object],
    check_policy: Mapping[str, object],
    model_receipts: Mapping[str, object],
) -> dict[str, object]:
    """Build a canonical result document from typed results and exact run evidence."""
    if not isinstance(run_result, NumbersResult):
        raise _error("NCA result builder requires a NumbersResult.", "NCA_RESULT_SCHEMA_INVALID")
    return {
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
        "groups": [_group_document(group) for group in run_result.groups],
        "findings": _plain(run_result.findings),
        "coverage": _plain(run_result.coverage),
        "summary": _plain(run_result.summary),
        "metrics": _plain(run_result.metrics),
    }


def _require_mapping(value: object, label: str, code: str) -> Mapping[str, Any]:
    """Require one string-keyed result mapping."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _error(f"{label} must be an object.", code)
    return value


def _require_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    """Reject missing or invented fields in one result mapping."""
    if set(value) != expected:
        raise _error(f"{label} fields are invalid.", "NCA_RESULT_SCHEMA_INVALID")


def _validate_fraction(value: object) -> None:
    """Require one canonical reduced rational string."""
    if not isinstance(value, str) or not _RATIONAL.fullmatch(value):
        raise _error("NCA result contains a malformed numeric value.", "NCA_RESULT_SCHEMA_INVALID")


def _validate_extraction(value: object) -> Mapping[str, object]:
    """Require the simplified extraction document shape."""
    raw = _require_mapping(value, "extraction", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(raw, {"status", "limitations", "values"}, "extraction")
    if raw["status"] not in EXTRACTION_STATUSES:
        raise _error("Extraction status is unsupported.", "NCA_RESULT_SCHEMA_INVALID")
    if not isinstance(raw["limitations"], list) or any(not isinstance(v, str) for v in raw["limitations"]):
        raise _error("Extraction limitations must be an array of strings.", "NCA_RESULT_SCHEMA_INVALID")
    if not isinstance(raw["values"], list):
        raise _error("Extraction values must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    for value in raw["values"]:
        _validate_fraction(value)
    return raw


def _validate_comparison(value: object) -> Mapping[str, object]:
    """Require the comparison document shape and its closed vocabularies."""
    raw = _require_mapping(value, "comparison", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(raw, {"outcome", "mode", "authority", "wip_values", "expected_values", "review_context"}, "comparison")
    if raw["outcome"] not in COMPARISON_OUTCOMES:
        raise _error("Comparison outcome is unsupported.", "NCA_RESULT_SCHEMA_INVALID")
    if raw["mode"] not in COMPARISON_MODES:
        raise _error("Comparison mode is unsupported.", "NCA_RESULT_SCHEMA_INVALID")
    if raw["authority"] not in {"OL", "NIV", "NONE"}:
        raise _error("Comparison authority is unsupported.", "NCA_RESULT_SCHEMA_INVALID")
    for field in ("wip_values", "expected_values"):
        if not isinstance(raw[field], list):
            raise _error(f"Comparison {field} must be an array.", "NCA_RESULT_SCHEMA_INVALID")
        for value in raw[field]:
            _validate_fraction(value)
    if not isinstance(raw["review_context"], Mapping):
        raise _error("Comparison review_context must be an object.", "NCA_RESULT_SCHEMA_INVALID")
    if raw["outcome"] == "NEEDS_REVIEW" and not raw["review_context"]:
        raise _error("NEEDS_REVIEW requires review_context evidence.", "NCA_RESULT_SCHEMA_INVALID")
    return raw


def _validate_group(value: object, allowed_evidence_ids: set[str]) -> Mapping[str, object]:
    """Validate one group document against its closed shape and evidence allowlist."""
    raw = _require_mapping(value, "group", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(
        raw,
        {"unit_id", "projection_status", "western_references", "target_references", "extraction", "comparison", "limitations", "notes"},
        "group",
    )
    if not isinstance(raw["unit_id"], str) or not raw["unit_id"]:
        raise _error("Group unit_id is invalid.", "NCA_RESULT_SCHEMA_INVALID")
    if raw["projection_status"] not in PROJECTION_STATUSES:
        raise _error("Group projection_status is unsupported.", "NCA_RESULT_SCHEMA_INVALID")
    for field in ("western_references", "target_references"):
        if not isinstance(raw[field], list) or any(not isinstance(v, str) or not v for v in raw[field]):
            raise _error(f"Group {field} must be an array of non-empty strings.", "NCA_RESULT_SCHEMA_INVALID")
    _validate_extraction(raw["extraction"])
    _validate_comparison(raw["comparison"])
    if not isinstance(raw["limitations"], list) or any(not isinstance(v, str) for v in raw["limitations"]):
        raise _error("Group limitations must be an array of strings.", "NCA_RESULT_SCHEMA_INVALID")
    if not isinstance(raw["notes"], list) or any(not isinstance(v, Mapping) for v in raw["notes"]):
        raise _error("Group notes must be an array of objects.", "NCA_RESULT_SCHEMA_INVALID")
    return raw


def _validate_provenance(value: object) -> None:
    """Require a non-empty provenance mapping; contents are workflow-owned, not re-derived."""
    _require_mapping(value, "provenance", "NCA_RESULT_SCHEMA_INVALID")


def _validate_receipts(value: object, *, required_phases: set[str]) -> None:
    """Require exactly one admitted receipt per phase actually exercised."""
    raw = _require_mapping(value, "model_receipts", "NCA_RESULT_RECEIPT_INVALID")
    if set(raw) != {"EXTRACTION"}:
        raise _error("NCA model receipts must cover exactly the EXTRACTION phase.", "NCA_RESULT_RECEIPT_INVALID")
    receipts = raw["EXTRACTION"]
    if not isinstance(receipts, list):
        raise _error("NCA phase receipts must be an array.", "NCA_RESULT_RECEIPT_INVALID")
    if "EXTRACTION" in required_phases and not receipts:
        raise _error("NCA requires at least one admitted EXTRACTION receipt.", "NCA_RESULT_RECEIPT_INVALID")
    for receipt in receipts:
        raw_receipt = _require_mapping(receipt, "receipt", "NCA_RESULT_RECEIPT_INVALID")
        if set(raw_receipt) != _RECEIPT_FIELDS:
            raise _error("NCA phase receipt fields are invalid.", "NCA_RESULT_RECEIPT_INVALID")
        if raw_receipt["phase"] != "EXTRACTION" or raw_receipt["task_version"] != _TASK_VERSIONS["EXTRACTION"]:
            raise _error("NCA phase receipt identity is invalid.", "NCA_RESULT_RECEIPT_INVALID")


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


def _validate_findings(value: object, allowed: set[str], *, groups: list[Mapping[str, object]]) -> list[dict[str, object]]:
    """Validate findings reference only known groups and admitted evidence."""
    raw = value
    if not isinstance(raw, list):
        raise _error("NCA findings must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    validate_global_finding_ids(raw)
    group_ids = {group["unit_id"] for group in groups}
    for finding in raw:
        item = _require_mapping(finding, "finding", "NCA_RESULT_SCHEMA_INVALID")
        if item.get("work_unit_id") not in group_ids:
            raise _error("Finding references an unknown group.", "NCA_RESULT_SCHEMA_INVALID")
    return [_plain(finding) for finding in raw]


def validate_numbers_result(
    document: Mapping[str, object],
    *,
    expected_unit_ids: tuple[str, ...],
    allowed_evidence_ids: tuple[str, ...],
) -> dict[str, object]:
    """Validate one complete canonical NCA result against external coverage bounds."""
    raw = _require_mapping(document, "NCA result", "NCA_RESULT_SCHEMA_INVALID")
    _require_keys(raw, {"schema_version", "workflow", "check_id", "provenance", "check_policy", "model_receipts", "limitations", "groups", "findings", "coverage", "summary", "metrics"}, "NCA result")
    if raw["schema_version"] != "1.0" or raw["workflow"] != "nca" or raw["check_id"] != "NUMBERS":
        raise _error("NCA result identity is invalid.", "NCA_RESULT_SCHEMA_INVALID")
    _require_mapping(raw["metrics"], "metrics", "NCA_RESULT_SCHEMA_INVALID")
    _validate_provenance(raw["provenance"])
    policy = _validate_policy(raw["check_policy"])
    limitations = _require_mapping(raw["limitations"], "limitations", "NCA_RESULT_LIMITATION_REQUIRED")
    if limitations.get("capability") != NCA_CAPABILITY_LIMITATION or limitations.get("sqs_confidence_checks_applied") is not False:
        raise _error("NCA capability and SQS limitation is required.", "NCA_RESULT_LIMITATION_REQUIRED")
    groups = raw["groups"]
    if not isinstance(groups, list):
        raise _error("NCA groups must be an array.", "NCA_RESULT_SCHEMA_INVALID")
    allowed = set(allowed_evidence_ids)
    if len(allowed) != len(allowed_evidence_ids):
        raise _error("Allowed evidence IDs must be unique.", "NCA_RESULT_EVIDENCE_INVALID")
    checks = policy["checks"]
    validated_groups = [_validate_group(group, allowed) for group in groups]
    actual_ids = [group["unit_id"] for group in validated_groups]
    findings = _validate_findings(raw["findings"], allowed, groups=validated_groups)
    required_evidence_complete = all(
        group["extraction"]["status"] == "COMPLETE"
        and (
            not checks["number_accuracy"]
            or group["comparison"]["outcome"] in {"PASS", "FAIL"}
        )
        for group in validated_groups
    )
    _validate_coverage(
        raw["coverage"], expected_unit_ids, actual_ids,
        findings_count=len(findings),
        required_evidence_complete=required_evidence_complete,
    )
    required_phases: set[str] = set()
    if any(group["extraction"]["status"] in {"COMPLETE", "PARTIAL"} for group in validated_groups):
        required_phases.add("EXTRACTION")
    _validate_receipts(raw["model_receipts"], required_phases=required_phases)
    summary = _require_mapping(raw["summary"], "summary", "NCA_RESULT_SCHEMA_INVALID")
    expected_summary = group_summary_document(validated_groups, checks, len(findings))
    if set(summary) != set(expected_summary) or any(
        summary.get(key) != value for key, value in expected_summary.items()
    ):
        raise _error("NCA summary does not derive from the result payload.", "NCA_RESULT_SUMMARY_INVALID")
    return _plain(raw)


def group_summary_document(groups: list[Mapping[str, object]], checks: Mapping[str, bool], findings_count: int) -> dict[str, int]:
    """Recompute the summary directly from validated JSON group documents.

    Mirrors group_summary() above but over plain dicts (post-validation), so
    validate_numbers_result can independently re-derive and compare -- never
    trusting a caller-supplied summary.
    """
    outcomes = [group["comparison"]["outcome"] for group in groups] if checks["number_accuracy"] else []
    return {
        "groups": len(groups),
        "passes": outcomes.count("PASS"),
        "failures": outcomes.count("FAIL"),
        "needs_review": outcomes.count("NEEDS_REVIEW"),
        "not_assessed": outcomes.count("NOT_ASSESSED"),
        "noteworthy_notes": sum(len(group["notes"]) for group in groups) if checks["footnote_review"] else 0,
        "extraction_complete": sum(group["extraction"]["status"] == "COMPLETE" for group in groups),
        "extraction_partial": sum(group["extraction"]["status"] == "PARTIAL" for group in groups),
        "extraction_unsupported": sum(group["extraction"]["status"] == "UNSUPPORTED" for group in groups),
        "findings": findings_count,
    }
