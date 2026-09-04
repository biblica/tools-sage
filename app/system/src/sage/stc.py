"""Source Text Correspondence (STC) planning, validation, and exact finalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .atomic import atomic_write_json, atomic_write_text
from .canon import NT_27, OT_39
from .errors import ValidationError
from .evidence import EvidenceMeasurement, EvidencePolicy
from .hashing import sha256_bytes
from .references import expand_reference_atoms, parse_scope
from .sfm_slicer import SfmAnalysisRoute, SfmStream, measure_sfm_slice, plan_sfm_work_units
from .source_coverage import source_text_issues
from .source_coverage import source_comparison_status, unique_source_text_issues
from .structural_issues import normalize_structure_problem
from .verse_alignment import ProjectVerseIndex
from .work_units import EvidenceRecord, WorkUnit
from .vrs import VerseRef

STC_FINDING_CATEGORIES = {"OMISSION", "ADDITION", "VARIATION", "CONSISTENCY"}
STC_ANALYSIS_ROUTE = "STC_CORRESPONDENCE"
STC_RESULT_VERSION = "1.0"
STC_ESTIMATOR = "SAGE_MULTILINGUAL_HEURISTIC_1"
STC_PLANNER_VERSION = "SAGE_STC_SFM_ROUTE_PLANNER_V2"
LEGACY_STC_PLANNER_VERSION = "SAGE_STC_SFM_ROUTE_PLANNER_V1"


def stc_authority_family(book: str) -> str:
    """Return the testament-governed primary OL authority family for one canonical book."""
    code = str(book).strip().upper()
    if code in NT_27:
        return "GRK"
    if code in OT_39:
        return "HEB"
    raise ValidationError(
        f"STC does not support original-language routing for book {book!r}",
        code="STC_CANONICAL_BOOK_REQUIRED",
    )


def plan_stc_work_units(
    wip_records: Iterable[EvidenceRecord],
    ol_records: Iterable[EvidenceRecord],
    policy: EvidencePolicy,
    *,
    unit_prefix: str,
    wip_index: ProjectVerseIndex | None = None,
    ol_index: ProjectVerseIndex | None = None,
    context_pool: Iterable[EvidenceRecord] | None = None,
    planner_version: str | None = None,
) -> tuple[WorkUnit, ...]:
    """Plan bounded WIP+primary-OL work units with exact canonical coverage."""
    selected = tuple(wip_records)
    if not selected:
        raise ValidationError("STC planning requires WIP Scripture records", code="STC_WIP_MISSING")
    ol = tuple(ol_records)
    family = stc_authority_family(selected[0].book)
    version = _stc_planner_version(planner_version, wip_index, ol_index)
    indexed = version == STC_PLANNER_VERSION
    route = SfmAnalysisRoute(
        route_id=STC_ANALYSIS_ROUTE,
        streams=(
            SfmStream(
                "WIP",
                tuple(context_pool) if context_pool is not None else selected,
                verse_index=wip_index if indexed else None,
            ),
            SfmStream(
                f"{family}:PRIMARY",
                ol,
                require_primary_coverage=False,
                verse_index=ol_index if indexed else None,
            ),
        ),
        primary_stream_id="WIP" if indexed else None,
        primary_index=wip_index if indexed else None,
    )
    return plan_sfm_work_units(
        selected,
        policy,
        unit_prefix=unit_prefix,
        route=route,
        context_pool=tuple(context_pool) if context_pool is not None else selected,
    )


def _records_for_refs(
    records: Iterable[EvidenceRecord], refs: frozenset[VerseRef]
) -> tuple[EvidenceRecord, ...]:
    """Select source records intersecting the requested canonical coordinates."""
    return tuple(record for record in records if refs.intersection(record.refs))


def _stc_planner_version(
    requested: str | None,
    wip_index: ProjectVerseIndex | None,
    ol_index: ProjectVerseIndex | None,
) -> str:
    """Resolve indexed V2 planning or the exact sealed V1 compatibility path."""
    version = str(requested or "").strip()
    if not version:
        version = (
            STC_PLANNER_VERSION
            if wip_index is not None and ol_index is not None
            else LEGACY_STC_PLANNER_VERSION
        )
    if version not in {STC_PLANNER_VERSION, LEGACY_STC_PLANNER_VERSION}:
        raise ValidationError(
            f"Unsupported STC planner version: {version}",
            code="STC_PLANNER_VERSION_UNSUPPORTED",
        )
    if version == STC_PLANNER_VERSION and (wip_index is None or ol_index is None):
        raise ValidationError(
            "STC V2 planning requires WIP and primary-OL Project verse indexes",
            code="STC_VRS_INDEX_REQUIRED",
        )
    return version


def _indexed_records_for_canonical(
    records: tuple[EvidenceRecord, ...],
    index: ProjectVerseIndex,
    refs: frozenset[VerseRef],
) -> tuple[EvidenceRecord, ...]:
    """Select canonical matches without expanding beyond routed OL evidence."""
    return tuple(record for record in index.records_for_canonical(refs) if record in records)


def _canonical_source_text_issues(
    unit: WorkUnit,
    wip_index: ProjectVerseIndex,
    missing_canonical: frozenset[VerseRef],
    *,
    authority_stream: str,
) -> list[dict[str, Any]]:
    """Attach missing canonical OL coverage to corresponding WIP-local coordinates."""
    missing_local: set[VerseRef] = set()
    canonical_by_local: dict[VerseRef, set[VerseRef]] = {}
    for record in unit.primary:
        record_missing = wip_index.canonical_refs_for_records((record,)).intersection(
            missing_canonical
        )
        if not record_missing:
            continue
        for local_ref in record.refs:
            missing_local.add(local_ref)
            canonical_by_local.setdefault(local_ref, set()).update(record_missing)
    issues = list(source_text_issues(
        missing_local,
        (),
        workflow="STC",
        source_stream=authority_stream,
        scope=str(unit.to_dict()["primary_scope"]),
    ))
    for issue in issues:
        local_ref = next(
            ref for ref in missing_local if ref.label() == issue["reference"]
        )
        issue["canonical_references"] = [
            ref.label() for ref in sorted(canonical_by_local[local_ref])
        ]
    return issues


def _component(measurement: EvidenceMeasurement) -> dict[str, Any]:
    """Render one routed-SFM measurement component for STC audit and display."""
    return {
        "estimator": STC_ESTIMATOR,
        "estimated_tokens": measurement.estimated_tokens,
        "serialized_bytes": measurement.serialized_bytes,
        "basis": "ROUTED_SFM_ONLY",
    }


def stc_package_measurements(
    units: Iterable[WorkUnit],
    ol_records: Iterable[EvidenceRecord],
    *,
    wip_index: ProjectVerseIndex | None = None,
    ol_index: ProjectVerseIndex | None = None,
    planner_version: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Measure WIP, primary OL, and combined STC routed-SFM review items."""
    original_language = tuple(ol_records)
    version = _stc_planner_version(planner_version, wip_index, ol_index)
    packages: list[dict[str, Any]] = []
    for unit in units:
        wip_slice = tuple(sorted(
            (*unit.context_before, *unit.primary, *unit.context_after),
            key=lambda item: (item.chapter, item.verse_start, item.verse_end),
        ))
        family = stc_authority_family(unit.primary[0].book)
        authority_stream = f"{family}:PRIMARY"
        if version == STC_PLANNER_VERSION:
            assert wip_index is not None and ol_index is not None
            primary_canonical = wip_index.canonical_refs_for_records(unit.primary)
            routed_canonical = wip_index.canonical_refs_for_records(wip_slice)
            ol_primary = _indexed_records_for_canonical(
                original_language,
                ol_index,
                primary_canonical,
            )
            ol_slice = _indexed_records_for_canonical(
                original_language,
                ol_index,
                routed_canonical,
            )
            covered = ol_index.canonical_refs_for_records(ol_primary)
            missing_canonical = primary_canonical.difference(covered)
            issues = _canonical_source_text_issues(
                unit,
                wip_index,
                missing_canonical,
                authority_stream=authority_stream,
            )
        else:
            ol_primary = _records_for_refs(original_language, unit.primary_refs)
            ol_slice = ol_primary
            covered = frozenset(ref for record in ol_primary for ref in record.refs)
            primary_canonical = frozenset(unit.primary_refs)
            missing_canonical = primary_canonical.difference(covered)
            issues = list(source_text_issues(
                unit.primary_refs,
                covered,
                workflow="STC",
                source_stream=authority_stream,
                scope=str(unit.to_dict()["primary_scope"]),
            ))
        primary_scope = str(unit.to_dict()["primary_scope"])
        package = {
            "sizing_basis": "ROUTED_SFM_ONLY",
            "analysis_route": STC_ANALYSIS_ROUTE,
            "primary_coverage_atoms": [ref.label() for ref in sorted(unit.primary_refs)],
            "structural_issues": issues,
            "source_text_issues": issues,
            "wip": _component(measure_sfm_slice(wip_slice)),
            "ol": _component(measure_sfm_slice(ol_slice)),
            "route": _component(unit.measurement),
        }
        if version == STC_PLANNER_VERSION:
            package.update({
                "projection": version,
                "source_spans": {
                    "WIP": [record.reference for record in unit.primary],
                    authority_stream: [record.reference for record in ol_primary],
                },
                "alignment": {
                    "primary_local_atoms": [
                        ref.label() for ref in sorted(unit.primary_refs)
                    ],
                    "canonical_atoms": [
                        ref.label() for ref in sorted(primary_canonical)
                    ],
                    "authority_stream": authority_stream,
                    "authority_local_spans": [
                        record.reference for record in ol_primary
                    ],
                    "missing_canonical_atoms": [
                        ref.label() for ref in sorted(missing_canonical)
                    ],
                },
            })
        packages.append(package)
    return tuple(packages)


def stc_package_summary(packages: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return STC routed-SFM maxima for operator plan display."""
    values = tuple(packages)
    return {
        "largest_wip_estimated_tokens": max(
            (int(item["wip"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_ol_estimated_tokens": max(
            (int(item["ol"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_route_estimated_tokens": max(
            (int(item["route"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_route_serialized_bytes": max(
            (int(item["route"]["serialized_bytes"]) for item in values), default=0
        ),
        "sizing_basis": "ROUTED_SFM_ONLY",
    }


def _stable_finding_id(work_unit_id: str, finding: Mapping[str, Any]) -> str:
    """Derive a deterministic STC finding identity from governed evidence coordinates."""
    seed = {
        "work_unit_id": work_unit_id,
        "category": str(finding.get("category") or "").upper(),
        "target_reference": str(finding.get("target_reference") or ""),
        "wip_evidence": str(finding.get("wip_evidence") or ""),
        "ol_evidence": str(finding.get("ol_evidence") or ""),
        "summary": str(finding.get("summary") or ""),
    }
    digest = sha256_bytes(json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))[:16].upper()
    return f"STC-F-{digest}"


def validate_stc_submission(
    path: Path,
    *,
    task_id: str,
    work_unit_id: str,
    scope_value: str,
    expected_references: Iterable[str],
    authority_family: str,
    task_fingerprint: str,
    narrative_language: str,
) -> dict[str, Any]:
    """Validate provider STC semantics and materialize deterministic identity/coverage."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid STC findings output: {exc}", code="STC_OUTPUT_INVALID") from exc
    if not isinstance(raw, dict):
        raise ValidationError("STC findings output must be a JSON object", code="STC_OUTPUT_INVALID")
    summary = str(raw.get("review_summary") or "").strip()
    if not summary:
        raise ValidationError("STC output requires review_summary", code="STC_OUTPUT_INVALID")
    report_language = str(raw.get("report_language") or "").strip()
    if report_language != narrative_language:
        raise ValidationError("STC report_language differs from the governed narrative language", code="STC_REPORT_LANGUAGE_MISMATCH")
    expected = tuple(str(value) for value in expected_references)
    expected_set = set(expected)
    scope = parse_scope(scope_value)
    findings_raw = raw.get("findings", [])
    if not isinstance(findings_raw, list):
        raise ValidationError("STC findings must be a list", code="STC_OUTPUT_INVALID")
    findings: list[dict[str, Any]] = []
    for value in findings_raw:
        if not isinstance(value, dict):
            raise ValidationError("Each STC finding must be an object", code="STC_OUTPUT_INVALID")
        category = str(value.get("category") or "").strip().upper()
        if category not in STC_FINDING_CATEGORIES:
            raise ValidationError(f"Unsupported STC finding category: {category}", code="STC_FINDING_CATEGORY_INVALID")
        reference = str(value.get("target_reference") or "").strip()
        reference_atoms = expand_reference_atoms(reference) if reference else ()
        if not reference_atoms or not all(scope.contains(ref) for ref in reference_atoms):
            raise ValidationError("STC finding lies outside the governed scope", code="STC_FINDING_SCOPE_INVALID")
        if reference not in expected_set and not any(reference.startswith(label) or label.startswith(reference) for label in expected_set):
            raise ValidationError("STC finding reference is outside planned primary coverage", code="STC_FINDING_SCOPE_INVALID")
        wip_evidence = str(value.get("wip_evidence") or "").strip()
        ol_evidence = str(value.get("ol_evidence") or "").strip()
        finding_summary = str(value.get("summary") or "").strip()
        if not wip_evidence or not ol_evidence or not finding_summary:
            raise ValidationError("STC findings require WIP evidence, OL evidence, and summary", code="STC_FINDING_EVIDENCE_MISSING")
        normalized = {
            "category": category,
            "target_reference": reference,
            "summary": finding_summary,
            "wip_evidence": wip_evidence,
            "ol_evidence": ol_evidence,
            "authority_family": authority_family,
            "authority_role": "PRIMARY",
        }
        normalized["finding_id"] = _stable_finding_id(work_unit_id, normalized)
        findings.append(normalized)
    ids = [row["finding_id"] for row in findings]
    if len(ids) != len(set(ids)):
        raise ValidationError("STC output contains duplicate normalized findings", code="STC_DUPLICATE_FINDING")
    return {
        "schema_version": STC_RESULT_VERSION,
        "operation": "stc",
        "task_id": task_id,
        "work_unit_id": work_unit_id,
        "task_fingerprint": task_fingerprint,
        "scope": scope_value,
        "analysis_route": STC_ANALYSIS_ROUTE,
        "authority_family": authority_family,
        "authority_role": "PRIMARY",
        "report_language": narrative_language,
        "review_summary": summary,
        "primary_coverage": list(expected),
        "analytical_completion": {
            "status": "COMPLETE",
            "review_item": STC_ANALYSIS_ROUTE,
            "reviewed_primary_coordinates": list(expected),
        },
        "finding_count": len(findings),
        "findings": findings,
    }


def finalize_stc_run(
    *,
    run_id: str,
    planned_units: Iterable[Mapping[str, Any]],
    accepted_results: Iterable[Mapping[str, Any]],
    output_root: Path,
) -> dict[str, Path]:
    """Fail closed on exact STC work-unit/coverage reconciliation and write canonical artifacts."""
    plans = [dict(row) for row in planned_units]
    results = [dict(row) for row in accepted_results]
    plan_by_id = {str(row.get("work_unit_id") or row.get("unit_id") or ""): row for row in plans}
    if not plan_by_id or len(plan_by_id) != len(plans) or "" in plan_by_id:
        raise ValidationError("STC immutable work-unit plan is invalid", code="STC_WORK_UNIT_PLAN_INVALID")
    result_by_id: dict[str, dict[str, Any]] = {}
    for result in results:
        unit_id = str(result.get("work_unit_id") or "")
        if unit_id in result_by_id:
            raise ValidationError("Duplicate STC terminal work-unit result", code="DUPLICATE_WORK_UNIT_RESULT")
        result_by_id[unit_id] = result
    missing = sorted(set(plan_by_id) - set(result_by_id))
    extra = sorted(set(result_by_id) - set(plan_by_id))
    if missing:
        raise ValidationError("Missing STC terminal work-unit result", code="MISSING_WORK_UNIT_RESULT", details={"work_unit_ids": missing})
    if extra:
        raise ValidationError("Unexpected STC terminal work-unit result", code="RESULT_COVERAGE_DRIFT", details={"work_unit_ids": extra})
    planned_atoms: list[str] = []
    observed_atoms: list[str] = []
    findings: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    source_issue_rows: list[dict[str, Any]] = []
    for unit_id, plan in plan_by_id.items():
        planned = list(plan.get("primary_coverage") or plan.get("primary_coverage_atoms") or [])
        observed = list(result_by_id[unit_id].get("primary_coverage") or [])
        if planned != observed:
            raise ValidationError("STC result primary coverage differs from immutable plan", code="RESULT_COVERAGE_DRIFT", details={"work_unit_id": unit_id})
        planned_atoms.extend(planned)
        observed_atoms.extend(observed)
        findings.extend(dict(row) for row in result_by_id[unit_id].get("findings", []) if isinstance(row, Mapping))
        receipts.append(dict(result_by_id[unit_id].get("analytical_completion") or {}))
        raw_structure = result_by_id[unit_id].get("structural_issues")
        if raw_structure is None:
            raw_structure = result_by_id[unit_id].get("source_text_issues", [])
        source_issue_rows.extend(
            normalize_structure_problem(dict(row))
            for row in raw_structure
            if isinstance(row, Mapping)
        )
    if len(planned_atoms) != len(set(planned_atoms)):
        raise ValidationError("STC plan has duplicate primary ownership", code="AGGREGATE_COVERAGE_MISMATCH")
    if observed_atoms != planned_atoms:
        raise ValidationError("STC aggregate coverage differs from planned coverage", code="AGGREGATE_COVERAGE_MISMATCH")
    finding_ids = [str(row.get("finding_id") or "") for row in findings]
    if len(finding_ids) != len(set(finding_ids)):
        raise ValidationError("STC aggregate contains duplicate finding identity", code="DUPLICATE_STC_FINDING")
    source_issue_rows = unique_source_text_issues(source_issue_rows)
    comparison_status = source_comparison_status(source_issue_rows)
    output_root.mkdir(parents=True, exist_ok=True)
    run_path = output_root / "STC_RUN_RESULT.json"
    findings_path = output_root / "STC_FINDINGS.json"
    report_path = output_root / "STC_REPORT.md"
    run_document = {
        "schema_version": STC_RESULT_VERSION,
        "run_id": run_id,
        "operation": "stc",
        "status": comparison_status,
        "structure_status": (
            "VERSIFICATION_MISMATCH" if source_issue_rows else "READY"
        ),
        "source_comparison_status": comparison_status,
        "structural_issues": source_issue_rows,
        "source_text_issues": source_issue_rows,
        "planned_work_units": plans,
        "accepted_work_unit_count": len(results),
        "planned_primary_coverage": planned_atoms,
        "analytical_completion_receipts": receipts,
        "finding_count": len(findings),
    }
    findings_document = {
        "schema_version": STC_RESULT_VERSION,
        "run_id": run_id,
        "operation": "stc",
        "finding_count": len(findings),
        "source_comparison_status": comparison_status,
        "structural_issues": source_issue_rows,
        "source_text_issues": source_issue_rows,
        "findings": findings,
    }
    atomic_write_json(run_path, run_document)
    atomic_write_json(findings_path, findings_document)
    lines = ["# STC Report", "", f"Run: `{run_id}`", f"Findings: {len(findings)}", ""]
    if source_issue_rows:
        lines.extend([
            "## Structural issues",
            "",
            "These coordinate or versification differences did not block STC execution.",
            "",
            *[
                f"- `{row.get('reference', '')}` | `{row.get('source_project_id', '')}` | "
                f"`{row.get('code', 'SOURCE_TEXT_ISSUE')}` — {row.get('message', '')}"
                for row in source_issue_rows
            ],
            "",
        ])
    if not findings:
        lines.append("No governed STC findings were reported. All planned STC review items completed.")
    else:
        for finding in findings:
            lines.extend([
                f"## {finding.get('finding_id', 'STC finding')} — {finding.get('category', '')}",
                "",
                f"- Reference: {finding.get('target_reference', '')}",
                f"- Summary: {finding.get('summary', '')}",
                f"- WIP: {finding.get('wip_evidence', '')}",
                f"- OL: {finding.get('ol_evidence', '')}",
                "",
            ])
    atomic_write_text(report_path, "\n".join(lines).rstrip() + "\n")
    return {"run_result": run_path, "findings": findings_path, "report": report_path}
