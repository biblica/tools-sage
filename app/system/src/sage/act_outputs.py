"""Operation-specific ACT output validation and deterministic rendering."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bic_memory import validate_inspect_submission
from .errors import ValidationError
from .hashing import sha256_file
from .human_output import catalogue_text, render_report_language_authority
from .iso_languages import iso_language
from .language_identification import resolve_country
from .ol_referrals import (
    OL_REFERRAL_CONTRACT_V1,
    normalize_referral_admission,
    referral_conflict_key,
)
from .references import (
    BOOK_ORDER,
    ScriptureScope,
    atomic_reference_labels,
    normalize_scope_set,
    parse_scope,
    parse_scope_set,
)
from .usj import compile_usfm_file, parse_usj_units
from .vrs import VerseRef

_MARKER_RE = re.compile(r"\\(\+?[A-Za-z0-9][A-Za-z0-9-]*)(\*)?")
_FINDING_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{2,63}$")
_FINDING_ID_SAFE_RE = re.compile(r"[^A-Z0-9._-]+")
_ALLOWED_CATEGORIES = {
    "STRUCTURE",
    "MEANING",
    "GRAMMAR",
    "TERMINOLOGY",
    "PARTICIPANT_REFERENCE",
    "QUOTATION",
    "VERSIFICATION",
    "ORTHOGRAPHY",
    "OTHER",
}
_ALLOWED_ACTION_LEVELS = {"INFORMATION", "REVIEW", "CHANGE", "BLOCK"}
_ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
_ALLOWED_STRUCTURAL_OUTCOMES = {"NO_FINDING", "FINDING", "INSUFFICIENT_DATA"}
_ALLOWED_GRAMMAR_STATUSES = {"PASS", "NOT_APPLICABLE", "ISSUE"}


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    """Require a JSON object at one output field and raise a bounded validation error otherwise."""
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return dict(value)


def _require_string(value: Any, label: str, *, maximum: int = 12000) -> str:
    """Require a non-empty string at one output field and preserve its exact submitted value."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a nonempty string")
    text = value.strip()
    if len(text) > maximum:
        raise ValidationError(f"{label} exceeds {maximum} characters")
    return text


def _string_list(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    """Validate a field as a list of strings, optionally requiring at least one item."""
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"{label} must be a list of nonempty strings")
    result = [item.strip() for item in value]
    if not allow_empty and not result:
        raise ValidationError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise ValidationError(f"{label} contains duplicate values")
    return result


def _canonical_saw_local_finding_id(value: Any, label: str) -> str:
    """Return one stable SAGE-safe local finding ID without trusting provider syntax.

    Provider-local IDs are cross-reference handles, not governed run-global identity. SAGE
    assigns run-global IDs later. Valid submitted IDs are preserved (case-normalized);
    syntactically invalid but non-empty IDs are deterministically encoded so provider
    punctuation cannot abort an otherwise valid completed work unit.
    """
    raw = _require_string(value, label, maximum=256)
    upper = raw.upper()
    if _FINDING_ID_RE.fullmatch(upper):
        return upper
    base = _FINDING_ID_SAFE_RE.sub("-", upper).strip("._-")
    if not base:
        base = "F"
    digest = hashlib.sha256(upper.encode("utf-8")).hexdigest()[:8].upper()
    base = base[:55].rstrip("._-") or "F"
    candidate = f"{base}-{digest}"
    if not _FINDING_ID_RE.fullmatch(candidate):
        candidate = f"F-{digest}"
    if not _FINDING_ID_RE.fullmatch(candidate):
        raise ValidationError(f"{label} cannot be normalized to a safe local finding ID")
    return candidate


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    """Load a UTF-8 JSON file and require its top-level value to be an object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid {label} JSON {path}: {exc}") from exc
    return _require_mapping(value, label)


def execution_route_from_receipt(
    task_root: Path,
    *,
    task_id: str,
    output_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Verify and project the sibling execution receipt without recomputing routing."""
    receipt_path = task_root.resolve() / "validation" / "llm-execution-receipt.json"
    if not receipt_path.is_file():
        raise ValidationError(
            "Task execution receipt is missing",
            code="EXECUTION_RECEIPT_MISSING",
        )
    receipt = load_json_object(receipt_path, "LLM execution receipt")
    if str(receipt.get("task_id") or "") != task_id:
        raise ValidationError(
            "Execution receipt belongs to another task",
            code="EXECUTION_RECEIPT_IDENTITY_MISMATCH",
        )
    recorded_outputs = receipt.get("output_sha256")
    expected_outputs = {str(key): str(value) for key, value in output_hashes.items()}
    if not isinstance(recorded_outputs, Mapping) or {
        str(key): str(value) for key, value in recorded_outputs.items()
    } != expected_outputs:
        raise ValidationError(
            "Execution receipt output hashes differ from the submitted task outputs",
            code="EXECUTION_RECEIPT_OUTPUT_MISMATCH",
        )
    if str(receipt.get("schema_version") or "") != "2.0":
        return {
            "status": "LEGACY_UNQUALIFIED",
            "task_id": task_id,
            "skill_id": receipt.get("skill_id"),
            "route_id": None,
            "provider": receipt.get("provider"),
            "model": receipt.get("model"),
            "reasoning_effort": receipt.get("reasoning_effort"),
            "routing_mode": None,
            "qualification_status": "UNVERIFIED",
            "phase_reasoning_efforts": list(receipt.get("phase_reasoning_efforts") or []),
            "receipt_path": str(receipt_path),
            "receipt_sha256": sha256_file(receipt_path),
        }
    required = (
        "skill_id",
        "route_id",
        "routing_mode",
        "qualification_status",
        "routing_policy_version",
        "model_identity_strength",
        "capability_fingerprint",
        "provider",
        "model",
        "reasoning_effort",
        "selection_mode",
    )
    missing = [field for field in required if receipt.get(field) in (None, "")]
    if missing:
        raise ValidationError(
            "Execution receipt route projection is incomplete: " + ", ".join(missing),
            code="EXECUTION_RECEIPT_IDENTITY_MISMATCH",
        )
    qualification = str(receipt["qualification_status"])
    if qualification == "PROVISIONAL_UNQUALIFIED":
        if receipt.get("qualification_evidence_sha256") not in (None, ""):
            raise ValidationError(
                "Provisional execution receipt must not claim qualification evidence",
                code="EXECUTION_RECEIPT_IDENTITY_MISMATCH",
            )
        if receipt.get("routing_basis_sha256") in (None, ""):
            raise ValidationError(
                "Provisional execution receipt is missing its policy routing basis",
                code="EXECUTION_RECEIPT_IDENTITY_MISMATCH",
            )
        if receipt.get("selection_mode") not in {
            "PROVISIONAL_PROVIDER_DEFAULT",
            "PROVISIONAL_OPERATOR_PREFERENCE",
        }:
            raise ValidationError(
                "Provisional execution receipt selection mode is invalid",
                code="EXECUTION_RECEIPT_IDENTITY_MISMATCH",
            )
    elif qualification in {"RECOMMENDED", "QUALIFIED"}:
        if receipt.get("qualification_evidence_sha256") in (None, ""):
            raise ValidationError(
                "Qualified execution receipt is missing qualification evidence",
                code="EXECUTION_RECEIPT_IDENTITY_MISMATCH",
            )
    else:
        raise ValidationError(
            f"Execution receipt qualification status is not operational: {qualification}",
            code="EXECUTION_RECEIPT_IDENTITY_MISMATCH",
        )
    return {
        "status": "PROVED",
        "task_id": task_id,
        "skill_id": receipt["skill_id"],
        "route_id": receipt["route_id"],
        "provider": receipt["provider"],
        "model": receipt["model"],
        "reasoning_effort": receipt["reasoning_effort"],
        "routing_mode": receipt["routing_mode"],
        "qualification_status": receipt["qualification_status"],
        "qualification_evidence_sha256": receipt["qualification_evidence_sha256"],
        "routing_basis_sha256": receipt.get("routing_basis_sha256"),
        "routing_policy_version": receipt["routing_policy_version"],
        "provider_runtime_version": receipt.get("provider_runtime_version"),
        "model_identity_strength": receipt["model_identity_strength"],
        "capability_fingerprint": receipt["capability_fingerprint"],
        "selection_mode": receipt.get("selection_mode"),
        "operator_policy_override": bool(receipt.get("operator_policy_override", False)),
        "phase_reasoning_efforts": list(receipt.get("phase_reasoning_efforts") or []),
        "started_utc": receipt.get("started_utc"),
        "completed_utc": receipt.get("completed_utc"),
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
    }


def aggregate_execution_routes(
    results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Group immutable execution projections by exact route while retaining task identity."""
    grouped: dict[str, dict[str, Any]] = {}
    task_ids: dict[str, set[str]] = {}
    for result in results:
        raw_routes = result.get("execution_routes")
        candidates = (
            [item for item in raw_routes if isinstance(item, Mapping)]
            if isinstance(raw_routes, list)
            else [result.get("execution_route")]
        )
        for raw in candidates:
            if not isinstance(raw, Mapping):
                continue
            route = dict(raw)
            route_id = str(route.get("route_id") or "")
            key = route_id or "legacy:" + json.dumps(
                {
                    "status": route.get("status"),
                    "provider": route.get("provider"),
                    "model": route.get("model"),
                    "reasoning_effort": route.get("reasoning_effort"),
                },
                sort_keys=True,
            )
            grouped.setdefault(key, route)
            inherited_tasks = route.get("task_ids")
            if isinstance(inherited_tasks, list):
                task_ids.setdefault(key, set()).update(
                    str(value) for value in inherited_tasks if str(value).strip()
                )
            task_id = str(route.get("task_id") or result.get("task_id") or "").strip()
            if task_id:
                task_ids.setdefault(key, set()).add(task_id)
    rows: list[dict[str, Any]] = []
    for key in sorted(grouped):
        tasks = sorted(task_ids.get(key, set()))
        rows.append({**grouped[key], "task_count": len(tasks), "task_ids": tasks})
    return rows


def render_execution_section(routes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Render actual receipt-backed execution routes for deterministic reports."""
    if not routes:
        return []
    if len(routes) == 1:
        route = routes[0]
        return [
            "## Execution route",
            "",
            f"- Skill: `{route.get('skill_id') or 'UNRECORDED'}`",
            f"- Provider: `{route.get('provider') or 'UNRECORDED'}`",
            f"- Model: `{route.get('model') or 'UNRECORDED'}`",
            f"- Reasoning: `{route.get('reasoning_effort') or 'UNRECORDED'}`",
            f"- Routing: `{route.get('routing_mode') or route.get('status') or 'UNRECORDED'}`",
            f"- Qualification: `{route.get('qualification_status') or 'UNVERIFIED'}`",
            "",
        ]
    lines = [
        "## Execution routes",
        "",
        "SKILL | PROVIDER | MODEL | REASONING | MODE | TASKS",
        "--- | --- | --- | --- | --- | ---:",
    ]
    for route in routes:
        lines.append(
            " | ".join(
                [
                    str(route.get("skill_id") or "UNRECORDED"),
                    str(route.get("provider") or "UNRECORDED"),
                    str(route.get("model") or "UNRECORDED"),
                    str(route.get("reasoning_effort") or "UNRECORDED"),
                    str(route.get("routing_mode") or route.get("status") or "UNRECORDED"),
                    str(route.get("task_count") or 0),
                ]
            )
        )
    return [*lines, ""]


def marker_sequence(text: str) -> tuple[str, ...]:
    """Return the exact normalized USFM marker sequence, including closers."""
    return tuple(
        f"{match.group(1).casefold()}{'*' if match.group(2) else ''}"
        for match in _MARKER_RE.finditer(text)
    )



_LAYOUT_MARKER_RE = re.compile(
    r"^(?:p|m|po|pr|cls|pmo|pm|pmc|pmr|pi\d*|mi\d*|nb|pc|ph\d*|"
    r"q\d*|qr|qc|rtc|qm\d*|qd|lh|li\d*|lf|lim\d*|tr|tc\d*|th\d*|tcr\d*|"
    r"thr\d*|b)$"
)


def protected_marker_sequence(text: str) -> tuple[str, ...]:
    """Return identity-critical markers while allowing approved layout normalization."""
    protected: list[str] = []
    for match in _MARKER_RE.finditer(text):
        marker = match.group(1).lstrip("+").casefold()
        if _LAYOUT_MARKER_RE.fullmatch(marker):
            continue
        protected.append(f"{marker}{'*' if match.group(2) else ''}")
    return tuple(protected)

def _unit_refs(unit: Mapping[str, Any], book: str) -> set[VerseRef]:
    """Return canonical references represented by one submitted unit or coverage item."""
    chapter = int(unit["chapter"])
    start = int(unit["verse_start"])
    end = int(unit["verse_end"])
    return {VerseRef(book, chapter, verse) for verse in range(start, end + 1)}


def usfm_scope_refs(path: Path, *, expected_book: str) -> tuple[set[VerseRef], dict[str, Any]]:
    """Compile a USFM output and return its represented atomic coordinates."""
    try:
        usj = compile_usfm_file(path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValidationError(f"USFM output cannot be compiled: {exc}") from exc
    errors = list(usj.get("sage", {}).get("errors", []))
    if errors:
        raise ValidationError("USFM output has parser errors: " + ", ".join(errors[:8]))
    actual_book = str(usj.get("sage", {}).get("book_code", "")).upper()
    if actual_book != expected_book:
        raise ValidationError(
            f"USFM output book is {actual_book or 'UNKNOWN'}; expected {expected_book}"
        )
    units = parse_usj_units(usj)
    if not units:
        raise ValidationError("USFM output contains no verse units")
    refs: set[VerseRef] = set()
    for unit in units:
        text = str(unit.get("body_text_exact", "")).strip()
        if not text:
            raise ValidationError(
                f"USFM output has empty visible verse content at "
                f"{expected_book} {unit['chapter']}:{unit['verse_start']}"
            )
        refs.update(_unit_refs(unit, expected_book))
    return refs, usj


def validate_bic_usfm_output(
    path: Path,
    *,
    expected_book: str,
    expected_references: set[VerseRef],
    source_marker_sequence: tuple[str, ...],
    marker_policy: str = "SEMANTIC_STRUCTURE_V1",
) -> dict[str, Any]:
    """Require valid bounded USFM with exact coordinate and marker coverage."""
    refs, _ = usfm_scope_refs(path, expected_book=expected_book)
    if refs != expected_references:
        missing = sorted(expected_references - refs)
        outside = sorted(refs - expected_references)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(ref.label() for ref in missing[:10]))
        if outside:
            details.append("outside=" + ",".join(ref.label() for ref in outside[:10]))
        raise ValidationError("USFM output does not match bounded scope: " + "; ".join(details))
    text = path.read_text(encoding="utf-8-sig")
    actual_markers = marker_sequence(text)
    source_protected = tuple(
        marker for marker in source_marker_sequence
        if not _LAYOUT_MARKER_RE.fullmatch(marker.rstrip("*"))
    )
    actual_protected = protected_marker_sequence(text)
    if actual_protected != source_protected:
        raise ValidationError(
            "USFM protected marker sequence differs from the bounded SOURCE packet",
            code="USFM_PROTECTED_MARKER_MISMATCH",
        )
    return {
        "format": "USFM",
        "book": expected_book,
        "atomic_coordinates": len(refs),
        "marker_count": len(actual_markers),
        "protected_marker_count": len(actual_protected),
        "marker_policy": marker_policy,
        "sha256": sha256_file(path),
    }


def validate_grammar_assessment(
    path: Path,
    *,
    task_id: str,
    scope_value: str,
    profile_id: str,
    profile_sha256: str,
    output_path: Path,
    required_rule_ids: Sequence[str],
) -> dict[str, Any]:
    """Require complete rule-by-rule grammar review for a BIC candidate."""
    document = load_json_object(path, "BIC grammar assessment")
    if document.get("schema_version") != "1.0":
        raise ValidationError("BIC grammar assessment schema_version must be '1.0'")
    expected = {
        "task_id": task_id,
        "scope": scope_value,
        "profile_id": profile_id,
        "profile_sha256": profile_sha256,
        "output_sha256": sha256_file(output_path),
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise ValidationError(f"BIC grammar assessment {key} does not match the task")
    raw_rules = document.get("rules")
    if not isinstance(raw_rules, list):
        raise ValidationError("BIC grammar assessment rules must be a list")
    expected_ids = list(required_rule_ids)
    seen: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_rules, start=1):
        row = _require_mapping(raw, f"rules[{index}]")
        rule_id = _require_string(row.get("rule_id"), f"rules[{index}].rule_id", maximum=100)
        if rule_id in seen:
            raise ValidationError(f"BIC grammar assessment repeats rule_id {rule_id}")
        status = str(row.get("status", "")).strip().upper()
        if status not in _ALLOWED_GRAMMAR_STATUSES:
            raise ValidationError(f"rules[{index}].status is unsupported: {status}")
        evidence = str(row.get("evidence", "")).strip()
        if status == "ISSUE" and not evidence:
            raise ValidationError(f"rules[{index}].evidence is required when status is ISSUE")
        seen[rule_id] = {"rule_id": rule_id, "status": status, "evidence": evidence}
    if set(seen) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(seen))
        outside = sorted(set(seen) - set(expected_ids))
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if outside:
            details.append("unknown=" + ",".join(outside))
        raise ValidationError("BIC grammar assessment does not cover the exact profile rules: " + "; ".join(details))
    unresolved = _string_list(document.get("unresolved", []), "BIC grammar assessment unresolved")
    return {
        **expected,
        "schema_version": "1.0",
        "rules": [seen[rule_id] for rule_id in expected_ids],
        "unresolved": unresolved,
        "issue_count": sum(1 for row in seen.values() if row["status"] == "ISSUE"),
    }


def _scope_contains_reference(parent: ScriptureScope, value: str) -> bool:
    """Return whether every submitted citation portion is authorized by the immutable task scope."""
    for child in parse_scope_set(value):
        if child.book != parent.book:
            return False
        if child.start_chapter is None:
            if parent.start_chapter is not None:
                return False
            continue
        points: list[tuple[int, int]] = []
        if child.start_verse is None:
            points.extend([(child.start_chapter, 1), (child.end_chapter or child.start_chapter, 9999)])
        else:
            points.extend(
                [
                    (child.start_chapter, child.start_verse),
                    (child.end_chapter or child.start_chapter, child.end_verse or child.start_verse),
                ]
            )
        if not all(parent.contains(VerseRef(parent.book, chapter, verse)) for chapter, verse in points):
            return False
    return True




def _atomic_reference_labels(value: str) -> set[str]:
    """Expand one or more submitted verse/range portions into atomic labels."""
    return set(atomic_reference_labels(value))

def _normalised_stage(operation: str, rtc_stage: str | None = None) -> str:
    """Return the exact stage required by one SAW operation or composite RTC subtask."""
    if operation == "rtc":
        return rtc_stage or "REFERENCE_TEXT_COMPARISON"
    return {"focused": "FOCUSED_CHECK", "ol": "FOCUSED_OL"}[operation]


def validate_saw_findings(
    path: Path,
    *,
    task_id: str,
    operation: str,
    scope_value: str,
    focus: str | None,
    check_type: str | None,
    expected_references: Sequence[str],
    structural_candidate_ids: Sequence[str],
    grammar_rule_ids: Sequence[str],
    allowed_evidence_ids: Sequence[str],
    task_fingerprint: str = "",
    required_review_checks: Sequence[str] = (),
    expected_work_unit_ids: Sequence[str] = (),
    rtc_stage: str | None = None,
    expected_ol_request_ids: Sequence[str] = (),
    expected_ol_requests: Sequence[Mapping[str, Any]] = (),
    narrative_language: str | None = None,
    ol_referral_contract: str | None = None,
) -> dict[str, Any]:
    """Validate staged SAW findings, complete coverage, and bounded focus answers."""
    # Validation order is deliberate: scope and schema checks precede evidence and coverage acceptance.
    document = load_json_object(path, "SAW findings")
    if document.get("schema_version") != "2.0":
        raise ValidationError("SAW findings schema_version must be '2.0'")
    if narrative_language is not None:
        contract = document.get("narrative_language")
        if not isinstance(contract, Mapping):
            raise ValidationError("SAW findings narrative_language contract is missing")
        if contract != {
            "tag": narrative_language,
            "authority": "CANONICAL_REPORT_NARRATIVE",
        }:
            raise ValidationError(
                "SAW findings narrative_language does not match the ACT task"
            )
    expected_identity = {
        "task_id": task_id,
        "operation": operation,
        "scope": scope_value,
        "stage": _normalised_stage(operation, rtc_stage),
    }
    for key, value in expected_identity.items():
        actual = str(document.get(key, "")).lower() if key == "operation" else document.get(key)
        expected_value = value.lower() if key == "operation" else value
        if actual != expected_value:
            raise ValidationError(f"SAW findings {key} does not match the ACT task")
    if operation in {"focused", "ol"}:
        if not focus:
            raise ValidationError(f"SAW {operation} task requires one bounded focus question")
        if document.get("focus") != focus:
            raise ValidationError("SAW findings focus does not match the ACT task")
        _require_string(document.get("answer"), "SAW bounded answer")
    elif document.get("focus") not in (None, ""):
        raise ValidationError("SAW Reference Text Comparison (RTC) findings must not introduce a focus question")
    if document.get("check_type") != check_type:
        raise ValidationError("SAW findings check_type does not match the ACT task")

    coverage = _require_mapping(document.get("coverage"), "SAW findings coverage")
    if str(coverage.get("status", "")).upper() != "COMPLETE":
        raise ValidationError("SAW findings coverage.status must be COMPLETE")
    reviewed = _string_list(
        coverage.get("reviewed_references"),
        "SAW findings coverage.reviewed_references",
        allow_empty=False,
    )
    if set(reviewed) != set(expected_references) or len(reviewed) != len(expected_references):
        raise ValidationError("SAW findings coverage does not reconcile the exact bounded coordinates")

    raw_receipts = document.get("review_receipts")
    if not isinstance(raw_receipts, list) or not raw_receipts:
        raise ValidationError(
            "SAW review receipts are required; coordinate coverage alone is not review evidence",
            code="RTC_REVIEW_EVIDENCE_MISSING",
            affected_scope=scope_value,
        )
    receipt_refs: list[str] = []
    receipts: list[dict[str, Any]] = []
    seen_receipt_ids: set[str] = set()
    seen_unit_ids: set[str] = set()
    required_checks = {str(value).strip().upper() for value in required_review_checks if str(value).strip()}
    for index, raw_receipt in enumerate(raw_receipts, start=1):
        receipt = _require_mapping(raw_receipt, f"review_receipts[{index}]")
        receipt_id = _require_string(receipt.get("receipt_id"), f"review_receipts[{index}].receipt_id", maximum=100)
        if receipt_id in seen_receipt_ids:
            raise ValidationError(f"Duplicate SAW review receipt_id: {receipt_id}")
        seen_receipt_ids.add(receipt_id)
        unit_id = _require_string(receipt.get("work_unit_id"), f"review_receipts[{index}].work_unit_id", maximum=160)
        if unit_id in seen_unit_ids:
            raise ValidationError(f"Duplicate SAW work_unit_id receipt: {unit_id}")
        seen_unit_ids.add(unit_id)
        refs = _string_list(receipt.get("reviewed_references"), f"review_receipts[{index}].reviewed_references", allow_empty=False)
        checks = {value.upper() for value in _string_list(receipt.get("checks_performed"), f"review_receipts[{index}].checks_performed", allow_empty=False)}
        if required_checks - checks:
            raise ValidationError(
                f"review_receipts[{index}] omits required checks: " + ", ".join(sorted(required_checks - checks)),
                code="RTC_REVIEW_EVIDENCE_INCOMPLETE",
                affected_scope=scope_value,
            )
        if task_fingerprint and receipt.get("task_fingerprint") != task_fingerprint:
            raise ValidationError(f"review_receipts[{index}].task_fingerprint does not match the ACT task")
        evidence_summary = _require_string(receipt.get("evidence_summary"), f"review_receipts[{index}].evidence_summary", maximum=4000)
        receipt_refs.extend(refs)
        receipts.append({
            "receipt_id": receipt_id,
            "work_unit_id": unit_id,
            "task_fingerprint": task_fingerprint,
            "reviewed_references": refs,
            "checks_performed": sorted(checks),
            "evidence_summary": evidence_summary,
        })
    if len(receipt_refs) != len(set(receipt_refs)) or set(receipt_refs) != set(expected_references):
        raise ValidationError(
            "SAW review receipts do not provide exact, non-overlapping evidence coverage",
            code="RTC_REVIEW_EVIDENCE_INCOMPLETE",
            affected_scope=scope_value,
        )
    if expected_work_unit_ids and seen_unit_ids != set(expected_work_unit_ids):
        raise ValidationError(
            "SAW review receipts do not reconcile the exact work-unit inventory",
            code="RTC_REVIEW_EVIDENCE_INCOMPLETE",
            affected_scope=scope_value,
        )

    raw_adjudications = document.get("structural_adjudications", [])
    if not isinstance(raw_adjudications, list):
        raise ValidationError("SAW structural_adjudications must be a list")
    adjudications: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_adjudications, start=1):
        row = _require_mapping(raw, f"structural_adjudications[{index}]")
        candidate_id = _require_string(
            row.get("candidate_id"),
            f"structural_adjudications[{index}].candidate_id",
            maximum=100,
        )
        if candidate_id in adjudications:
            raise ValidationError(f"Structural candidate {candidate_id} is adjudicated more than once")
        outcome = str(row.get("outcome", "")).strip().upper()
        if outcome not in _ALLOWED_STRUCTURAL_OUTCOMES:
            raise ValidationError(
                f"structural_adjudications[{index}].outcome is unsupported: {outcome}"
            )
        raw_finding_id = row.get("finding_id")
        finding_id = (
            _canonical_saw_local_finding_id(
                raw_finding_id, f"structural_adjudications[{index}].finding_id"
            )
            if raw_finding_id not in (None, "")
            else None
        )
        if outcome == "FINDING" and not finding_id:
            raise ValidationError(
                f"structural_adjudications[{index}].finding_id is required for FINDING"
            )
        adjudications[candidate_id] = {
            "candidate_id": candidate_id,
            "outcome": outcome,
            "finding_id": finding_id,
            "rationale": _require_string(
                row.get("rationale"),
                f"structural_adjudications[{index}].rationale",
            ),
        }
    if set(adjudications) != set(structural_candidate_ids):
        raise ValidationError("SAW structural adjudications do not reconcile the exact candidate inventory")

    ol_review_requests: list[dict[str, Any]] = []
    raw_requests = document.get("ol_review_requests", [])
    if not isinstance(raw_requests, list) or any(not isinstance(item, dict) for item in raw_requests):
        raise ValidationError("SAW ol_review_requests must be a list of objects")
    if operation == "rtc" and _normalised_stage(operation, rtc_stage) == "REFERENCE_TEXT_COMPARISON":
        seen_request_ids: set[str] = set()
        seen_deferred_ids: set[str] = set()
        seen_conflict_keys: set[str] = set()
        strict_referrals = ol_referral_contract == OL_REFERRAL_CONTRACT_V1
        for index, request in enumerate(raw_requests, start=1):
            admission = (
                normalize_referral_admission(request, index=index)
                if strict_referrals
                else {}
            )
            request_id = _require_string(request.get("request_id"), f"ol_review_requests[{index}].request_id", maximum=80).upper()
            if request_id in seen_request_ids:
                raise ValidationError(f"Duplicate OL review request_id: {request_id}")
            seen_request_ids.add(request_id)
            reference = normalize_scope_set(_require_string(request.get("target_reference"), f"ol_review_requests[{index}].target_reference", maximum=160))
            if not _scope_contains_reference(parse_scope(scope_value), reference):
                raise ValidationError(
                    f"ol_review_requests[{index}].target_reference is outside the task scope",
                    code=(
                        "SAW_OL_REFERRAL_SCOPE_INVALID"
                        if strict_referrals
                        else "VALIDATION_ERROR"
                    ),
                )
            evidence_ids = _string_list(request.get("evidence_ids"), f"ol_review_requests[{index}].evidence_ids", allow_empty=False)
            if set(evidence_ids) - set(allowed_evidence_ids):
                raise ValidationError(
                    f"ol_review_requests[{index}] cites evidence not routed to the task",
                    code=(
                        "SAW_OL_REFERRAL_EVIDENCE_INVALID"
                        if strict_referrals
                        else "VALIDATION_ERROR"
                    ),
                )
            deferred_finding_id = _canonical_saw_local_finding_id(
                request.get("deferred_finding_id"),
                f"ol_review_requests[{index}].deferred_finding_id",
            )
            if deferred_finding_id in seen_deferred_ids:
                raise ValidationError(f"Duplicate deferred_finding_id: {deferred_finding_id}")
            seen_deferred_ids.add(deferred_finding_id)
            conflict_key = ""
            if strict_referrals:
                conflict_key = referral_conflict_key(
                    target_reference=reference,
                    conflict_class=admission["conflict_class"],
                    wip_proposition=admission["wip_proposition"],
                    reference_proposition=admission["reference_proposition"],
                )
                if conflict_key in seen_conflict_keys:
                    raise ValidationError(
                        f"ol_review_requests[{index}] duplicates an admitted semantic conflict",
                        code="SAW_OL_REFERRAL_DUPLICATE",
                    )
                seen_conflict_keys.add(conflict_key)
            normalized_request = {
                "request_id": request_id,
                "deferred_finding_id": deferred_finding_id,
                "target_reference": reference,
                "question": _require_string(request.get("question"), f"ol_review_requests[{index}].question", maximum=1200),
                "reason": _require_string(request.get("reason"), f"ol_review_requests[{index}].reason", maximum=1600),
                "evidence_ids": evidence_ids,
            }
            if strict_referrals:
                normalized_request.update(admission)
                normalized_request["conflict_key"] = conflict_key
            ol_review_requests.append(normalized_request)
    elif raw_requests:
        raise ValidationError("OL review requests may be emitted only by the SAW Reference Text Comparison (RTC) meaning stage")

    expected_request_map = {
        str(item.get("request_id", "")).upper(): dict(item) for item in expected_ol_requests
    }
    expected_request_set = {str(value).upper() for value in expected_ol_request_ids}
    if expected_request_map and set(expected_request_map) != expected_request_set:
        raise ValidationError("Selective OL request metadata does not match the expected request-ID inventory")
    raw_resolutions = document.get("ol_resolutions", [])
    if not isinstance(raw_resolutions, list) or any(not isinstance(item, dict) for item in raw_resolutions):
        raise ValidationError("SAW ol_resolutions must be a list of objects")
    ol_resolutions: list[dict[str, Any]] = []
    seen_resolution_ids: set[str] = set()
    for index, raw_resolution in enumerate(raw_resolutions, start=1):
        resolution = _require_mapping(raw_resolution, f"ol_resolutions[{index}]")
        request_id = _require_string(resolution.get("request_id"), f"ol_resolutions[{index}].request_id", maximum=80).upper()
        if request_id in seen_resolution_ids:
            raise ValidationError(f"Duplicate OL resolution request_id: {request_id}")
        seen_resolution_ids.add(request_id)
        if request_id not in expected_request_set:
            raise ValidationError(f"ol_resolutions[{index}] resolves an unexpected OL request: {request_id}")
        expected_request = expected_request_map.get(request_id, {})
        target_reference = normalize_scope_set(_require_string(resolution.get("target_reference"), f"ol_resolutions[{index}].target_reference", maximum=160))
        if expected_request and target_reference != expected_request.get("target_reference"):
            raise ValidationError(f"ol_resolutions[{index}].target_reference does not match its inherited OL request")
        outcome = str(resolution.get("outcome", "")).strip().upper()
        if outcome not in {"FINDING", "NO_FINDING", "INSUFFICIENT_EVIDENCE"}:
            raise ValidationError(f"ol_resolutions[{index}].outcome is unsupported: {outcome}")
        decision = str(resolution.get("decision") or "INCONCLUSIVE").strip().upper()
        if decision not in {
            "WIP_CLOSER_TO_SOURCE",
            "REFERENCE_CLOSER_TO_SOURCE",
            "BOTH_DEFENSIBLE",
            "INCONCLUSIVE",
        }:
            raise ValidationError(f"ol_resolutions[{index}].decision is unsupported: {decision}")
        deferred_id = str(expected_request.get("deferred_finding_id", "")).upper()
        raw_finding_id = resolution.get("finding_id")
        finding_id = (
            _canonical_saw_local_finding_id(
                raw_finding_id, f"ol_resolutions[{index}].finding_id"
            )
            if raw_finding_id not in (None, "")
            else None
        )
        if outcome == "FINDING":
            if not deferred_id or finding_id != deferred_id:
                raise ValidationError(
                    f"ol_resolutions[{index}] FINDING must use the inherited deferred_finding_id"
                )
        elif finding_id:
            raise ValidationError(f"ol_resolutions[{index}].finding_id is valid only for FINDING outcome")
        ol_evidence = _require_string(
            resolution.get("original_language_evidence"),
            f"ol_resolutions[{index}].original_language_evidence",
            maximum=4000,
        )
        ol_resolutions.append({
            "request_id": request_id,
            "deferred_finding_id": deferred_id,
            "target_reference": target_reference,
            "outcome": outcome,
            "decision": decision,
            "finding_id": finding_id,
            "original_language_evidence": ol_evidence,
            "rationale": _require_string(resolution.get("rationale"), f"ol_resolutions[{index}].rationale", maximum=4000),
            "issue": str(resolution.get("issue") or "").strip(),
            "required_action": str(resolution.get("required_action") or "").strip(),
            "action_level": str(resolution.get("action_level") or "INFORMATION").strip().upper(),
            "confidence": str(resolution.get("confidence") or "UNKNOWN").strip().upper(),
        })
    if expected_request_set:
        if seen_resolution_ids != expected_request_set:
            raise ValidationError("SAW Reference Text Comparison (RTC) OL stage does not reconcile the exact requested OL issue inventory")
    elif ol_resolutions:
        raise ValidationError("ol_resolutions are valid only for a requested SAW Reference Text Comparison (RTC) OL stage")
    resolved_ol_request_ids = [row["request_id"] for row in ol_resolutions]
    declared_resolved = [value.upper() for value in _string_list(document.get("resolved_ol_request_ids", []), "resolved_ol_request_ids", allow_empty=True)]
    if declared_resolved and declared_resolved != resolved_ol_request_ids:
        raise ValidationError("resolved_ol_request_ids must match the structured ol_resolutions ledger")


    findings = document.get("findings")
    if not isinstance(findings, list):
        raise ValidationError("SAW findings must contain a findings list")
    parent_scope = parse_scope(scope_value)
    allowed_grammar_rules = set(grammar_rule_ids)
    allowed_evidence = set(allowed_evidence_ids)
    normalised: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(findings, start=1):
        row = _require_mapping(raw, f"findings[{index}]")
        finding_id = _canonical_saw_local_finding_id(
            row.get("finding_id"), f"findings[{index}].finding_id"
        )
        if finding_id in seen_ids:
            raise ValidationError(f"Duplicate SAW finding_id: {finding_id}")
        seen_ids.add(finding_id)
        reference = normalize_scope_set(_require_string(
            row.get("target_reference"),
            f"findings[{index}].target_reference",
            maximum=160,
        ))
        if not _scope_contains_reference(parent_scope, reference):
            raise ValidationError(
                f"findings[{index}].target_reference is outside the bounded task scope"
            )
        stage_name = _normalised_stage(operation, rtc_stage)
        if operation == "rtc" and stage_name in {"STRUCTURAL_ADJUDICATION", "SELECTIVE_OL_ADJUDICATION"}:
            if not _atomic_reference_labels(reference).issubset(set(expected_references)):
                raise ValidationError(
                    f"findings[{index}].target_reference is outside the exact composite-RTC stage references"
                )
        category = str(row.get("category", "")).strip().upper()
        if category not in _ALLOWED_CATEGORIES:
            raise ValidationError(f"findings[{index}].category is unsupported: {category}")
        action_level = str(row.get("action_level", "")).strip().upper()
        if action_level not in _ALLOWED_ACTION_LEVELS:
            raise ValidationError(
                f"findings[{index}].action_level is unsupported: {action_level}"
            )
        confidence = str(row.get("confidence", "")).strip().upper()
        if confidence not in _ALLOWED_CONFIDENCE:
            raise ValidationError(f"findings[{index}].confidence is unsupported: {confidence}")
        if action_level in {"CHANGE", "BLOCK"} and confidence in {"LOW", "UNKNOWN"}:
            raise ValidationError(
                f"findings[{index}] cannot use {confidence} confidence with {action_level}"
            )
        required_action = str(row.get("required_action", "")).strip()
        if action_level in {"REVIEW", "CHANGE", "BLOCK"} and not required_action:
            raise ValidationError(
                f"findings[{index}].required_action is required for {action_level}"
            )
        evidence_ids = _string_list(
            row.get("evidence_ids"),
            f"findings[{index}].evidence_ids",
            allow_empty=False,
        )
        if set(evidence_ids) - allowed_evidence:
            raise ValidationError(f"findings[{index}] cites unknown evidence IDs")
        cited_grammar_rules = _string_list(
            row.get("grammar_rule_ids", []),
            f"findings[{index}].grammar_rule_ids",
        )
        if set(cited_grammar_rules) - allowed_grammar_rules:
            raise ValidationError(f"findings[{index}] cites unknown grammar rule IDs")
        if category == "GRAMMAR" and not cited_grammar_rules:
            raise ValidationError(f"findings[{index}] grammar finding must cite grammar_rule_ids")
        ol_evidence = str(row.get("original_language_evidence", "")).strip()
        stage_name = _normalised_stage(operation, rtc_stage)
        ol_stage = operation == "ol" or (operation == "rtc" and stage_name == "SELECTIVE_OL_ADJUDICATION")
        if ol_stage and not ol_evidence:
            raise ValidationError(
                f"findings[{index}].original_language_evidence is required for OL review"
            )
        if not ol_stage and ol_evidence:
            raise ValidationError(
                f"findings[{index}].original_language_evidence must be empty outside an OL review stage"
            )
        normalised.append(
            {
                "finding_id": finding_id,
                "target_reference": reference,
                "category": category,
                "issue": _require_string(row.get("issue"), f"findings[{index}].issue"),
                "required_action": required_action,
                "action_level": action_level,
                "confidence": confidence,
                "evidence_ids": evidence_ids,
                "grammar_rule_ids": cited_grammar_rules,
                "original_language_evidence": ol_evidence,
            }
        )
    stage_name = _normalised_stage(operation, rtc_stage)
    if operation == "rtc" and stage_name == "REFERENCE_TEXT_COMPARISON":
        deferred_ids = {row["deferred_finding_id"] for row in ol_review_requests}
        overlap = deferred_ids & seen_ids
        if overlap:
            raise ValidationError(
                "Meaning-stage findings cannot simultaneously be final findings and deferred OL issues: "
                + ", ".join(sorted(overlap)),
                code=(
                    "SAW_OL_REFERRAL_FINDING_OVERLAP"
                    if ol_referral_contract == OL_REFERRAL_CONTRACT_V1
                    else "VALIDATION_ERROR"
                ),
            )
    if operation == "rtc" and stage_name == "SELECTIVE_OL_ADJUDICATION":
        expected_finding_ids = {
            str(row["finding_id"]) for row in ol_resolutions if row["outcome"] == "FINDING"
        }
        if seen_ids != expected_finding_ids:
            raise ValidationError(
                "Selective OL findings must exactly match FINDING outcomes in ol_resolutions"
            )
        resolution_by_finding = {str(row["finding_id"]): row for row in ol_resolutions if row["outcome"] == "FINDING"}
        for finding in normalised:
            resolution = resolution_by_finding[finding["finding_id"]]
            if finding["target_reference"] != resolution["target_reference"]:
                raise ValidationError("Selective OL finding reference must match its OL resolution")
    if operation == "rtc" and stage_name == "STRUCTURAL_ADJUDICATION":
        structural_finding_ids = {
            str(row["finding_id"]) for row in adjudications.values() if row["outcome"] == "FINDING"
        }
        if seen_ids != structural_finding_ids:
            raise ValidationError("Structural adjudication may emit findings only for routed structural candidates")

    for candidate_id, row in adjudications.items():
        if row["outcome"] == "FINDING" and row["finding_id"] not in seen_ids:
            raise ValidationError(
                f"Structural candidate {candidate_id} refers to missing finding_id {row['finding_id']}"
            )
    return {
        "schema_version": "2.0",
        "task_id": task_id,
        "operation": operation,
        "stage": _normalised_stage(operation, rtc_stage),
        "scope": scope_value,
        "focus": focus,
        "check_type": check_type,
        "answer": str(document.get("answer", "")).strip(),
        "coverage": {"status": "COMPLETE", "reviewed_references": reviewed},
        "review_receipts": receipts,
        "structural_adjudications": [adjudications[item] for item in structural_candidate_ids],
        "ol_review_requests": ol_review_requests,
        "resolved_ol_request_ids": resolved_ol_request_ids,
        "ol_resolutions": ol_resolutions,
        "findings": normalised,
        "finding_count": len(normalised),
    }


def validate_bic_inspect_output(
    path: Path,
    *,
    task_id: str,
    scope_value: str,
    resource_fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    """Validate BIC INSPECT output against the task identity and resources."""
    document = load_json_object(path, "BIC INSPECT submission")
    if document.get("operation_id") != task_id:
        raise ValidationError("BIC INSPECT operation_id must equal the ACT task_id")
    if document.get("scope") != scope_value:
        raise ValidationError("BIC INSPECT scope does not match the ACT task")
    if document.get("resource_fingerprints") != dict(resource_fingerprints):
        raise ValidationError("BIC INSPECT resource_fingerprints do not match the ACT task")
    return validate_inspect_submission(document, expected_scope=scope_value)


def _report_languages(document: Mapping[str, Any]) -> tuple[str, str | None]:
    """Return primary and optional secondary human-report language tags."""
    narrative = document.get("narrative_language")
    authority = document.get("language_authority")
    if isinstance(narrative, Mapping):
        primary = str(narrative.get("tag") or "").strip()
        if primary:
            secondary = (
                str(authority.get("secondary_language") or "").strip() or None
                if isinstance(authority, Mapping)
                else None
            )
            return primary, secondary if secondary != primary else None
    if not isinstance(authority, Mapping):
        return "en", None
    primary = str(authority.get("primary_language") or "en").strip() or "en"
    secondary = str(authority.get("secondary_language") or "").strip() or None
    return primary, secondary if secondary != primary else None


def _report_label(document: Mapping[str, Any], key: str) -> str:
    """Render one report label in primary/secondary order without changing canonical values."""
    primary, secondary = _report_languages(document)
    values = [catalogue_text(primary, key)]
    if secondary:
        secondary_value = catalogue_text(secondary, key)
        if secondary_value not in values:
            values.append(secondary_value)
    return " / ".join(values)


def _operator_project_ids(document: Mapping[str, Any]) -> tuple[str, str]:
    """Return actual SAW Project IDs for the subject and Reference Project."""
    bindings = document.get("resource_bindings")
    if isinstance(bindings, Mapping):
        wip = str(bindings.get("WIP") or "").strip()
        reference = str(bindings.get("REFERENCE") or "").strip()
    else:
        wip = reference = ""
    return (
        wip or str(document.get("output_project") or "WIP"),
        reference or str(document.get("contemporary_source") or "REFERENCE"),
    )


def _operator_project_names(document: Mapping[str, Any]) -> tuple[str, str]:
    """Return configured Project display names for Operator-facing WIP/reference labels."""
    wip_id, reference_id = _operator_project_ids(document)
    names = document.get("resource_display_names")
    if not isinstance(names, Mapping):
        names = {}
    return (
        str(names.get("WIP") or wip_id).strip() or wip_id,
        str(names.get("REFERENCE") or reference_id).strip() or reference_id,
    )


def _operator_project_text(value: Any, document: Mapping[str, Any]) -> str:
    """Replace internal SAW role labels with configured Project names in general report prose."""
    text = str(value or "")
    wip, reference = _operator_project_names(document)
    text = re.sub(r"\bWIP\b", wip, text)
    text = re.sub(r"\bREFERENCE\b", reference, text)
    return text


def _operator_ol_label(document: Mapping[str, Any], evidence_ids: Sequence[str]) -> str | None:
    """Return the exact routed GRK/HEB resource as one compact OL report label."""
    evidence = {str(value).strip().upper() for value in evidence_ids}
    bindings = document.get("resource_bindings")
    resources = bindings if isinstance(bindings, Mapping) else {}
    for role, fallback in (
        ("ORIGINAL_LANGUAGE_GREEK", "GRK"),
        ("ORIGINAL_LANGUAGE_HEBREW", "HEB"),
    ):
        if role in evidence:
            resource = str(resources.get(role) or fallback).strip() or fallback
            return f"{resource} OL"
    return None


def operator_finding_text(
    value: Any,
    document: Mapping[str, Any],
    finding: Mapping[str, Any],
) -> str:
    """Resolve bare SAW authority terms to compact Project or GRK/HEB OL identities."""
    text = str(value or "")
    wip_id, reference_id = _operator_project_ids(document)
    evidence_ids = [str(item) for item in finding.get("evidence_ids", [])]
    ol_label = _operator_ol_label(document, evidence_ids)
    source_label = ol_label or reference_id
    text = re.sub(r"\bWIP\b", lambda _: wip_id, text, flags=re.IGNORECASE)
    text = re.sub(r"\bREFERENCE\b", lambda _: reference_id, text, flags=re.IGNORECASE)
    if ol_label or "REFERENCE" in {item.upper() for item in evidence_ids}:
        text = re.sub(r"\bSOURCE\b", lambda _: source_label, text, flags=re.IGNORECASE)
    return text


def _operator_evidence_labels(row: Mapping[str, Any], document: Mapping[str, Any]) -> list[str]:
    """Resolve SAW evidence roles to compact Project IDs or routed OL labels."""
    wip_id, reference_id = _operator_project_ids(document)
    evidence_ids = [str(value) for value in row.get("evidence_ids", [])]
    ol_label = _operator_ol_label(document, evidence_ids)
    labels: list[str] = []
    for evidence_id in evidence_ids:
        normalized = evidence_id.strip().upper()
        if normalized == "WIP":
            labels.append(wip_id)
        elif normalized == "REFERENCE":
            labels.append(reference_id)
        elif normalized in {"ORIGINAL_LANGUAGE_GREEK", "ORIGINAL_LANGUAGE_HEBREW"}:
            labels.append(ol_label or normalized)
        else:
            labels.append(evidence_id)
    return labels


def _language_display_name(tag: str) -> str:
    """Return one human-readable report-language name; codes remain metadata only."""
    value = str(tag or "").strip()
    if not value:
        return "Unknown language"
    parts = value.replace("_", "-").split("-")
    row = iso_language(parts[0]) or {}
    name = str(row.get("name") or parts[0])
    region = next((part.upper() for part in parts[1:] if len(part) == 2 and part.isalpha()), None)
    if region:
        country = resolve_country(region)
        if country:
            return f"{name} ({country['name']})"
    return name


def _finding_sort_key(row: Mapping[str, Any]) -> tuple[int, int, int, int, str]:
    """Sort findings in canonical Scripture order, then preserve stable finding identity."""
    try:
        scope = parse_scope(str(row.get("target_reference") or ""))
        return (
            BOOK_ORDER.get(scope.book, 999),
            scope.start_chapter or 0,
            scope.start_verse or 0,
            scope.end_verse or scope.start_verse or 0,
            str(row.get("finding_id") or ""),
        )
    except Exception:
        return (999, 999, 999, 999, str(row.get("finding_id") or ""))


def render_plain_text_from_markdown(markdown: str) -> str:
    """Render finalized Markdown deterministically as plain text without an AI call."""
    lines: list[str] = []
    for raw in str(markdown).splitlines():
        line = raw.rstrip()
        if re.fullmatch(r"\s*---+\s*", line):
            lines.append("-" * 72)
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^>\s?", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"\1", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
        lines.append(line)
    # Collapse excessive blank lines while preserving finding separation.
    result: list[str] = []
    blank = False
    for line in lines:
        if line.strip():
            result.append(line)
            blank = False
        elif not blank:
            result.append("")
            blank = True
    return "\n".join(result).rstrip() + "\n"


def render_action_report(document: Mapping[str, Any]) -> str:
    """Render deterministic Operator-facing SAW Markdown with per-language issue/action grouping."""
    # Receipt-backed route metadata and assistive translations are projections;
    # neither may alter the canonical finding inventory rendered below.
    primary, secondary = _report_languages(document)
    primary_name = _language_display_name(primary)
    secondary_name = _language_display_name(secondary) if secondary else None
    renderings = document.get("report_renderings")
    rendering_rows: Mapping[str, Any] = {}
    rendering_event_rows: Mapping[str, Any] = {}
    rendering_status = None
    if isinstance(renderings, Mapping):
        rendering_status = str(renderings.get("status") or "").upper()
        raw_rows = renderings.get("findings")
        if isinstance(raw_rows, Mapping):
            rendering_rows = raw_rows
        raw_events = renderings.get("events")
        if isinstance(raw_events, Mapping):
            rendering_event_rows = raw_events
    wip, reference = _operator_project_names(document)
    report_title = _report_label(document, "report.saw_action_report")
    if str(document.get("operation") or "").strip().lower() == "rtc":
        report_title = f"Reference Text Comparison (RTC) — {report_title}"
    lines = [
        "# " + report_title,
        "",
        f"- Projects: `{wip}` checked against `{reference}`",
        f"- {_report_label(document, 'label.scope')}: `{document['scope']}`",
        f"- {_report_label(document, 'label.coverage')}: `{document['coverage']['status']}` ({len(document['coverage']['reviewed_references'])} coordinates)",
        f"- Report languages: `{primary}`" + (f"; `{secondary}`" if secondary else ""),
    ]
    raw_routes = document.get("execution_routes")
    routes = (
        [dict(row) for row in raw_routes if isinstance(row, Mapping)]
        if isinstance(raw_routes, list)
        else aggregate_execution_routes([document])
    )
    lines.extend(["", *render_execution_section(routes)])
    authority_notice = render_report_language_authority(document.get("language_authority"), markdown=True)
    if authority_notice:
        lines.extend(["", authority_notice])
    if secondary and rendering_status == "DEGRADED":
        lines.extend(["", f"> **{catalogue_text(primary, 'message.secondary_rendering_unavailable')}**"])
        secondary_notice = catalogue_text(secondary, "message.secondary_rendering_unavailable")
        if secondary_notice and secondary_notice != catalogue_text(primary, "message.secondary_rendering_unavailable"):
            lines.append(f"> **{secondary_notice}**")
    consolidation = document.get("consolidation")
    if isinstance(consolidation, Mapping) and consolidation.get("status") == "HUMAN_REVIEW_REQUIRED":
        lines.extend(["", "> **Consolidation requires human review because material conclusions conflict.**"])
    execution_events = [dict(row) for row in document.get("execution_events", []) if isinstance(row, Mapping)]
    if execution_events:
        lines.extend(["", "## Execution advisories", ""])
        for row in execution_events:
            event_id = str(row.get("event_id") or "")
            secondary_event = rendering_event_rows.get(event_id) if secondary else None
            scope = row.get("work_unit_scope") or row.get("requested_scope") or ""
            lines.extend([
                f"### {row.get('disposition', 'ERROR')} — {scope}",
                "",
                f"- Reason: `{row.get('reason_code', 'SAGE_ERROR')}`; Retryability: `{row.get('retryability', 'UNKNOWN')}`",
                "",
                f"**Message — {primary_name}**",
                "",
                _operator_project_text(row.get("message", ""), document),
                "",
            ])
            if secondary and isinstance(secondary_event, Mapping):
                lines.extend([f"**Message — {secondary_name}**", "", _operator_project_text(secondary_event.get("message", ""), document), ""])
            if row.get("next_action"):
                lines.extend([f"**Proposed action — {primary_name}**", "", _operator_project_text(row.get("next_action", ""), document), ""])
                if secondary and isinstance(secondary_event, Mapping) and secondary_event.get("next_action"):
                    lines.extend([f"**Proposed action — {secondary_name}**", "", _operator_project_text(secondary_event.get("next_action", ""), document), ""])
            lines.extend(["---", ""])
    vrs_advisories = [dict(row) for row in document.get("versification_advisories", []) if isinstance(row, Mapping)]
    if vrs_advisories:
        lines.extend(["", "## Versification advisories", "", "These coordinate differences did not block SAW execution.", ""])
        for row in vrs_advisories:
            coordinate = row.get("reference") or row.get("scope") or ""
            lines.append(
                f"- `{coordinate}` | `{row.get('project_id', '')}` | `{row.get('code', 'VRS_ADVISORY')}` — {row.get('message', '')}"
            )
    lines.extend(["", "## " + _report_label(document, "report.actionable_findings"), ""])
    findings = sorted(
        [dict(row) for row in document.get("findings", []) if isinstance(row, Mapping)],
        key=_finding_sort_key,
    )
    if not findings:
        lines.append(_report_label(document, "message.no_actionable_findings"))
    for position, row in enumerate(findings):
        finding_id = str(row["finding_id"])
        secondary_row = rendering_rows.get(finding_id) if secondary else None
        evidence = ", ".join(_operator_evidence_labels(row, document)) or "NONE"
        metadata = f"- Evidence: `{evidence}`"
        grammar = ", ".join(str(value) for value in row.get("grammar_rule_ids", []))
        if grammar:
            metadata += f"; Grammar rules: `{grammar}`"
        ol = str(row.get("original_language_evidence") or "").strip()
        if ol:
            metadata += f"; Original-language: `{operator_finding_text(ol, document, row)}`"
        lines.extend([
            f"### {finding_id} — {row['target_reference']}",
            "",
            f"- Category: `{row['category']}`",
            f"- Action level: `{row['action_level']}`",
            f"- Confidence: `{row['confidence']}`",
            metadata,
            "",
            f"**Issue — {primary_name}**",
            "",
            operator_finding_text(row["issue"], document, row),
            "",
            f"**Proposed action — {primary_name}**",
            "",
            operator_finding_text(row.get("required_action") or catalogue_text(primary, "message.no_action_required"), document, row),
            "",
        ])
        if secondary and isinstance(secondary_row, Mapping):
            secondary_issue = str(secondary_row.get("issue") or "").strip()
            secondary_action = str(secondary_row.get("required_action") or "").strip() or catalogue_text(secondary, "message.no_action_required")
            if secondary_issue:
                lines.extend([f"**Issue — {secondary_name}**", "", operator_finding_text(secondary_issue, document, row), ""])
            lines.extend([f"**Proposed action — {secondary_name}**", "", operator_finding_text(secondary_action, document, row), ""])
        if position != len(findings) - 1:
            lines.extend(["---", ""])
    return "\n".join(lines).rstrip() + "\n"

def render_operator_note_text(document: Mapping[str, Any]) -> str:
    """Render plain text deterministically from the finalized Markdown projection."""
    return render_plain_text_from_markdown(render_action_report(document))
