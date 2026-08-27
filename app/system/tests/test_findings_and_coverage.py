"""Finding identity, VRS-aware references, and truthful coverage tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage.coverage import CoverageAssessment, assess_coverage
from sage.errors import ValidationError
from sage.findings import (
    assign_global_finding_ids,
    resolve_finding,
    validate_finding_references,
)
from sage.vrs import VerseRef, parse_vrs_file


def test_global_finding_ids_remain_unique_across_work_units() -> None:
    """Verify that global finding IDs remain unique across work units."""
    normalized = assign_global_finding_ids(
        {
            "PHP-U001": [{"finding_id": "T-001", "target_reference": "PHP 1:1"}],
            "PHP-U002": [{"finding_id": "T-001", "target_reference": "PHP 2:1"}],
        },
        run_id="RUN-001",
    )
    assert len({item["finding_id"] for item in normalized}) == 2
    assert {item["submitted_id"] for item in normalized} == {"T-001"}
    with pytest.raises(ValidationError, match="AMBIGUOUS_FINDING_ID"):
        resolve_finding(normalized, "T-001")
    assert resolve_finding(normalized, normalized[0]["finding_id"]) == normalized[0]



def test_saw_global_item_id_uses_hierarchy_separators_without_duplicate_prefixes() -> None:
    """Keep SAW ITEM codes compact, hierarchical, and free of repeated SAW prefixes."""
    normalized = assign_global_finding_ids(
        {
            "SAW-RTC-PH-99846F75": [
                {"finding_id": "F001", "target_reference": "PHM 1:1"}
            ]
        },
        run_id="SAW_PAPCV-A3A03DAC",
        prefix="SAW",
    )
    assert normalized[0]["finding_id"] == (
        "SAW_PAPCV-A3A03DAC_RTC-PH-99846F75_0001"
    )
    assert normalized[0]["submitted_id"] == "F001"

def test_vrs_mapped_original_language_reference_is_authorized(tmp_path: Path) -> None:
    """Verify that VRS mapping authorizes an original-language reference."""
    target_file = tmp_path / "eng.vrs"
    target_file.write_text(
        "2CO 13:14\n2CO 13:14 = 2CO 13:13\n",
        encoding="utf-8",
    )
    org_file = tmp_path / "org.vrs"
    org_file.write_text("2CO 13:13\n", encoding="utf-8")
    target = parse_vrs_file(target_file, schema_id="eng", canonical_id="org")
    greek = parse_vrs_file(org_file, schema_id="org", canonical_id="org")
    validate_finding_references(
        {
            "target_reference": "2CO 13:14",
            "greek_reference": "2CO 13:13",
        },
        target_schema=target,
        resource_schemas={"ORIGINAL_LANGUAGE_GREEK": greek},
        primary_target_refs=frozenset({VerseRef("2CO", 13, 14)}),
    )


def test_equivalence_group_allows_each_canonical_component(tmp_path: Path) -> None:
    """Verify that equivalence group allows each canonical component."""
    target_file = tmp_path / "eng.vrs"
    target_file.write_text(
        "REV 12:17 13:22\n"
        "REV 13:1 = REV 12:18\n"
        "REV 13:1 = REV 13:1\n",
        encoding="utf-8",
    )
    org_file = tmp_path / "org.vrs"
    org_file.write_text("REV 12:18 13:22\n", encoding="utf-8")
    target = parse_vrs_file(target_file, schema_id="eng", canonical_id="org")
    greek = parse_vrs_file(org_file, schema_id="org", canonical_id="org")
    assert target.mapping_precision({VerseRef("REV", 13, 1)}) == "EQUIVALENCE_GROUP"
    validate_finding_references(
        {
            "target_reference": "REV 13:1",
            "greek_reference": "REV 12:18",
        },
        target_schema=target,
        resource_schemas={"ORIGINAL_LANGUAGE_GREEK": greek},
        primary_target_refs=frozenset({VerseRef("REV", 13, 1)}),
    )


def test_context_only_coordinate_cannot_be_ordinary_finding_target(tmp_path: Path) -> None:
    """Verify that context only coordinate cannot be ordinary finding target."""
    schema_file = tmp_path / "eng.vrs"
    schema_file.write_text("MAT 1:3\n", encoding="utf-8")
    schema = parse_vrs_file(schema_file, schema_id="eng", canonical_id="org")
    with pytest.raises(ValidationError, match="CONTEXT_ONLY"):
        validate_finding_references(
            {"target_reference": "MAT 1:1"},
            target_schema=schema,
            resource_schemas={},
            primary_target_refs=frozenset({VerseRef("MAT", 1, 2)}),
            context_target_refs=frozenset({VerseRef("MAT", 1, 1)}),
        )


def test_coverage_never_claims_complete_when_restricted() -> None:
    """Verify that coverage never claims complete when restricted."""
    assessment = assess_coverage(
        findings_present=False,
        required_evidence_complete=True,
        restrictions=["Greek evidence unavailable"],
    )
    assert assessment.result == "NO_FINDINGS"
    assert assessment.coverage == "COMPLETE_WITH_RESTRICTIONS"
    assert assessment.confidence_basis == "LIMITED"
    with pytest.raises(ValidationError, match="may not be COMPLETE"):
        CoverageAssessment(
            result="NO_FINDINGS",
            coverage="COMPLETE",
            confidence_basis="FULL",
            restrictions=("restriction",),
        )


def test_long_run_and_unit_names_do_not_collide_after_compaction() -> None:
    """Verify that long run and unit names do not collide after compaction."""
    normalized = assign_global_finding_ids(
        {
            "PSA-LONG-SHARED-PREFIX-UNIT-ALPHA": [
                {"finding_id": "T-001", "target_reference": "PSA 1:1"}
            ],
            "PSA-LONG-SHARED-PREFIX-UNIT-BRAVO": [
                {"finding_id": "T-001", "target_reference": "PSA 2:1"}
            ],
        },
        run_id="RUN-WITH-A-LONG-SHARED-PREFIX-AND-STABLE-IDENTITY",
    )
    assert len({item["finding_id"] for item in normalized}) == 2
    for item in normalized:
        parts = item["finding_id"].split("_")
        assert len(parts) == 4
        assert len(parts[1]) <= 18
        assert len(parts[2]) <= 18


def test_mixed_authorized_and_unrelated_ol_range_is_rejected(tmp_path: Path) -> None:
    """Verify that a mixed authorized and unrelated OL range is rejected."""
    target_file = tmp_path / "eng.vrs"
    target_file.write_text(
        "REV 12:17 13:22\n"
        "REV 13:1 = REV 12:18\n"
        "REV 13:1 = REV 13:1\n",
        encoding="utf-8",
    )
    org_file = tmp_path / "org.vrs"
    org_file.write_text("REV 12:18 13:22\n", encoding="utf-8")
    target = parse_vrs_file(target_file, schema_id="eng", canonical_id="org")
    greek = parse_vrs_file(org_file, schema_id="org", canonical_id="org")
    with pytest.raises(ValidationError, match="not authorized"):
        validate_finding_references(
            {
                "target_reference": "REV 13:1",
                "greek_reference": "REV 12:18-13:2",
            },
            target_schema=target,
            resource_schemas={"ORIGINAL_LANGUAGE_GREEK": greek},
            primary_target_refs=frozenset({VerseRef("REV", 13, 1)}),
        )



def test_non_target_citation_is_limited_to_the_findings_target_span(tmp_path: Path) -> None:
    """Verify that non target citation is limited to the findings target span."""
    schema_file = tmp_path / "eng.vrs"
    schema_file.write_text("MAT 1:2\n", encoding="utf-8")
    schema = parse_vrs_file(schema_file, schema_id="eng", canonical_id="org")
    with pytest.raises(ValidationError, match="not authorized"):
        validate_finding_references(
            {
                "target_reference": "MAT 1:1",
                "reference_reference": "MAT 1:2",
            },
            target_schema=schema,
            resource_schemas={"REFERENCE": schema},
            primary_target_refs=frozenset(
                {VerseRef("MAT", 1, 1), VerseRef("MAT", 1, 2)}
            ),
        )


def test_unexecuted_analysis_is_reported_as_not_assessed() -> None:
    """Verify that unexecuted analysis is reported as not assessed."""
    assessment = assess_coverage(
        findings_present=False,
        required_evidence_complete=True,
        assessed=False,
        skipped_checks=["SAW analytical controller is not enabled."],
    )
    assert assessment.result == "NOT_ASSESSED"
    assert assessment.coverage == "NOT_ASSESSED"
    assert assessment.confidence_basis == "LIMITED"


def test_partition_aggregation_globalizes_duplicate_provider_finding_ids(make_workspace) -> None:
    """Provider-local F001 may repeat across work units; aggregation assigns run-global IDs."""
    import json

    from sage.act_tasks import aggregate_act_plan
    from sage.registry import load_ecosystem

    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    plans_root = config.workflow("saw").output_root / "plans"
    active_root = config.workflow("saw").output_root / "active"
    plan_id = "SAW-RTC-RUT-DUPLICATE-ID"
    run_id = "SAW-RUN-001"
    job_id = "SAW_usWIP-usNIVv2"
    units = []
    expected = []
    lineage = {"project.usWIP": "WIP-SHA", "project.usNIVv2": "REF-SHA"}
    for index, reference in enumerate(("MAT 1:1", "MAT 1:2"), start=1):
        unit_id = f"{plan_id}-U{index:03d}"
        task_root = active_root / unit_id
        manifest = task_root / "task-manifest.json"
        validation = task_root / "validation"
        validation.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"task_id": unit_id}) + "\n", encoding="utf-8")
        (validation / "submission.json").write_text(
            json.dumps({"status": "FINALIZED", "task_id": unit_id, "scope": reference}) + "\n",
            encoding="utf-8",
        )
        (validation / "normalized-findings.json").write_text(
            json.dumps({
                "job_id": job_id,
                "run_id": run_id,
                "output_project": "usWIP",
                "contemporary_source": "usNIVv2",
                "resource_fingerprints": lineage,
                "resource_bindings": {"wip": "usWIP", "reference": "usNIVv2"},
                "coverage": {"status": "COMPLETE", "reviewed_references": [reference]},
                "review_receipts": [],
                "structural_adjudications": [],
                "ol_review_requests": [],
                "ol_resolutions": [],
                "resolved_ol_request_ids": [],
                "findings": [{
                    "finding_id": "F001",
                    "target_reference": reference,
                    "category": "MEANING",
                    "issue": f"Issue in {reference}",
                }],
                "finding_count": 1,
            }) + "\n",
            encoding="utf-8",
        )
        units.append({"unit_id": unit_id, "manifest_path": str(manifest.resolve())})
        expected.append(reference)
    plan_path = plans_root / f"{plan_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps({
            "workflow": "saw",
            "status": "PARTITIONED",
            "plan_id": plan_id,
            "job_id": job_id,
            "run_id": run_id,
            "requested_scope": "MAT 1:1-2",
            "output_project": "usWIP",
            "contemporary_source": "usNIVv2",
            "expected_references": expected,
            "work_units": units,
        }) + "\n",
        encoding="utf-8",
    )

    result = aggregate_act_plan(config, plan_path)
    assert result["finding_count"] == 2
    assert {row["submitted_id"] for row in result["findings"]} == {"F001"}
    assert len({row["finding_id"] for row in result["findings"]}) == 2
    assert all(row["finding_id"].startswith("SAW_") for row in result["findings"])


def test_partition_aggregation_expands_legacy_raw_bridge_plan_coverage(make_workspace) -> None:
    """Legacy stage plans with raw bridge labels finalize against atomic child coverage."""
    import json

    from sage.act_tasks import aggregate_act_plan
    from sage.registry import load_ecosystem

    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    plans_root = config.workflow("saw").output_root / "plans"
    active_root = config.workflow("saw").output_root / "active"
    plan_id = "SAW-RTC-MAT-LEGACY-BRIDGE"
    run_id = "SAW-RUN-BRIDGE"
    job_id = "SAW_usWIP-usNIVv2"
    lineage = {"project.usWIP": "WIP-SHA", "project.usNIVv2": "REF-SHA"}
    unit_refs = (("MAT 1:1", "MAT 1:2"), ("MAT 1:3",))
    units = []
    for index, references in enumerate(unit_refs, start=1):
        unit_id = f"{plan_id}-U{index:03d}"
        task_root = active_root / unit_id
        manifest = task_root / "task-manifest.json"
        validation = task_root / "validation"
        validation.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({
                "task_id": unit_id,
                "expected_references": list(references),
            }) + "\n",
            encoding="utf-8",
        )
        (validation / "submission.json").write_text(
            json.dumps({
                "status": "FINALIZED",
                "task_id": unit_id,
                "scope": "MAT 1:1-2" if index == 1 else "MAT 1:3",
            }) + "\n",
            encoding="utf-8",
        )
        (validation / "normalized-findings.json").write_text(
            json.dumps({
                "task_id": unit_id,
                "job_id": job_id,
                "run_id": run_id,
                "output_project": "usWIP",
                "contemporary_source": "usNIVv2",
                "resource_fingerprints": lineage,
                "resource_bindings": {"wip": "usWIP", "reference": "usNIVv2"},
                "coverage": {
                    "status": "COMPLETE",
                    "reviewed_references": list(references),
                },
                "review_receipts": [],
                "structural_adjudications": [],
                "ol_review_requests": [],
                "ol_resolutions": [],
                "resolved_ol_request_ids": [],
                "findings": [],
                "finding_count": 0,
            }) + "\n",
            encoding="utf-8",
        )
        units.append({
            "unit_id": unit_id,
            "task_id": unit_id,
            "manifest_path": str(manifest.resolve()),
        })
    plan_path = plans_root / f"{plan_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps({
            "workflow": "saw",
            "status": "PARTITIONED",
            "plan_id": plan_id,
            "job_id": job_id,
            "run_id": run_id,
            "requested_scope": "MAT 1:1-3",
            "output_project": "usWIP",
            "contemporary_source": "usNIVv2",
            "expected_references": ["MAT 1:1-2", "MAT 1:3"],
            "work_units": units,
        }) + "\n",
        encoding="utf-8",
    )

    result = aggregate_act_plan(config, plan_path)

    assert result["coverage"]["reviewed_references"] == [
        "MAT 1:1", "MAT 1:2", "MAT 1:3"
    ]
    assert result["coverage"]["legacy_raw_spans_expanded"] == ["MAT 1:1-2"]
