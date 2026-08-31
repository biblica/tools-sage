"""Deterministic, provenance-preserving consolidation of governed result documents."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from .act_outputs import aggregate_execution_routes
from .errors import ValidationError
from .hashing import sha256_file
from .source_coverage import source_comparison_status, unique_source_text_issues


_FINDING_EQUIVALENCE_FIELDS = (
    "target_reference",
    "category",
    "issue",
    "required_action",
    "action_level",
    "confidence",
    "grammar_rule_ids",
    "original_language_evidence",
)


def _canonical(value: Any) -> str:
    """Serialize a value for stable equality comparison."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _finding_signature(finding: Mapping[str, Any]) -> str:
    """Return the material-equivalence signature for one finding."""
    return _canonical({field: finding.get(field) for field in _FINDING_EQUIVALENCE_FIELDS})


def _explicit_conflict_key(finding: Mapping[str, Any]) -> str | None:
    """Return an explicit controller/validator conflict lineage, never a prose guess."""
    value = str(finding.get("conflict_group_id") or "").strip().upper()
    return value or None


def _unique_rows(documents: Sequence[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    """Combine one list field without changing first-seen order."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in documents:
        raw = document.get(field, [])
        if not isinstance(raw, list):
            raise ValidationError(f"Consolidation input {field} must be a list")
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValidationError(f"Consolidation input {field} contains a non-object")
            marker = _canonical(item)
            if marker not in seen:
                seen.add(marker)
                rows.append(dict(item))
    return rows


def consolidate_result_documents(
    documents: Sequence[Mapping[str, Any]],
    *,
    source_paths: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Return one chapter report record without mutating any source document."""
    if not documents:
        raise ValidationError("Consolidation requires at least one finalized result document")
    # Validate identity before reading individual records so mixed Jobs/scopes fail closed.
    normalised = [deepcopy(dict(document)) for document in documents]
    scopes = {str(document.get("scope", "")).strip().upper() for document in normalised}
    scopes.discard("")
    if len(scopes) != 1:
        raise ValidationError("Consolidation inputs must use one identical Book/chapter scope")
    operations = {str(document.get("operation", "")).strip().lower() for document in normalised}
    operations.discard("")
    if len(operations) != 1:
        raise ValidationError("Consolidation inputs must use one compatible operation")
    job_ids = {str(document.get("job_id", "")).strip() for document in normalised}
    job_ids.discard("")
    if len(job_ids) > 1:
        raise ValidationError("Consolidation inputs must belong to one Job")

    sources = list(source_paths or [])
    if sources and len(sources) != len(normalised):
        raise ValidationError("Consolidation source-path inventory does not match its documents")
    provenance: list[dict[str, Any]] = []
    for index, document in enumerate(normalised):
        source = sources[index].expanduser().resolve() if sources else None
        if source is not None and not source.is_file():
            raise ValidationError(f"Consolidation source result is missing: {source}")
        provenance.append(
            {
                "task_id": str(document.get("task_id", "")),
                "run_id": str(document.get("run_id", "")) or None,
                "source_path": str(source) if source else None,
                "sha256": sha256_file(source) if source else None,
            }
        )

    retained: list[dict[str, Any]] = []
    signature_index: dict[str, int] = {}
    duplicate_groups: list[dict[str, Any]] = []
    contributors: dict[int, list[dict[str, str]]] = {}
    conflict_signatures: dict[str, set[str]] = {}
    # Retain first-seen records; attach later equivalents as provenance-only contributors.
    for document_index, document in enumerate(normalised):
        findings = document.get("findings", [])
        if not isinstance(findings, list) or any(not isinstance(item, Mapping) for item in findings):
            raise ValidationError("Consolidation input findings must be a list of objects")
        for finding in findings:
            row = dict(finding)
            if not isinstance(row.get("execution_route"), Mapping) and isinstance(
                document.get("execution_route"), Mapping
            ):
                row["execution_route"] = dict(document["execution_route"])
            signature = _finding_signature(row)
            contribution = {
                "task_id": str(document.get("task_id", "")),
                "finding_id": str(row.get("finding_id", "")),
            }
            if signature in signature_index:
                retained_index = signature_index[signature]
                contributors.setdefault(retained_index, []).append(contribution)
                continue
            retained_index = len(retained)
            signature_index[signature] = retained_index
            retained.append(row)
            contributors[retained_index] = [contribution]
            conflict_key = _explicit_conflict_key(row)
            if conflict_key is not None:
                conflict_signatures.setdefault(conflict_key, set()).add(signature)

    for retained_index, rows in sorted(contributors.items()):
        if len(rows) > 1:
            duplicate_groups.append(
                {
                    "retained_finding_id": str(retained[retained_index].get("finding_id", "")),
                    "contributors": rows,
                }
            )
    conflicts: list[dict[str, Any]] = []
    for key, signatures in sorted(conflict_signatures.items()):
        if len(signatures) < 2:
            continue
        member_rows = [
            row
            for row in retained
            if _explicit_conflict_key(row) == key and _finding_signature(row) in signatures
        ]
        members = [str(row.get("finding_id", "")) for row in member_rows]
        conflicts.append(
            {
                "conflict_group_id": key,
                "target_reference": str(member_rows[0].get("target_reference", "")),
                "category": str(member_rows[0].get("category", "")),
                "finding_ids": members,
                "status": "HUMAN_REVIEW_REQUIRED",
            }
        )

    reviewed_references: list[str] = []
    for document in normalised:
        coverage = document.get("coverage", {})
        if isinstance(coverage, Mapping):
            for reference in coverage.get("reviewed_references", []):
                value = str(reference)
                if value not in reviewed_references:
                    reviewed_references.append(value)

    # Project the combined record through the normal report renderer without touching inputs.
    result = deepcopy(normalised[-1])
    scope = next(iter(scopes))
    source_issue_rows = unique_source_text_issues(
        row
        for document in normalised
        for row in _unique_rows([document], "source_text_issues")
    )
    result.update(
        {
            "schema_version": "2.0",
            "task_id": f"CONSOLIDATED-{scope.replace(' ', '-')}",
            "stage": "CONSOLIDATED",
            "scope": scope,
            "coverage": {"status": "COMPLETE", "reviewed_references": reviewed_references},
            "review_receipts": _unique_rows(normalised, "review_receipts"),
            "structural_adjudications": _unique_rows(normalised, "structural_adjudications"),
            "ol_review_requests": _unique_rows(normalised, "ol_review_requests"),
            "ol_resolutions": _unique_rows(normalised, "ol_resolutions"),
            "versification_advisories": _unique_rows(normalised, "versification_advisories"),
            "source_comparison_status": source_comparison_status(source_issue_rows),
            "source_text_issues": source_issue_rows,
            "findings": retained,
            "finding_count": len(retained),
            "execution_routes": aggregate_execution_routes(normalised),
            "consolidation": {
                "status": "HUMAN_REVIEW_REQUIRED" if conflicts else "COMPLETE",
                "input_count": len(normalised),
                "provenance": provenance,
                "duplicate_groups": duplicate_groups,
                "conflicts": conflicts,
                "conflict_policy": "EXPLICIT_LINEAGE_ONLY",
            },
        }
    )
    return result
