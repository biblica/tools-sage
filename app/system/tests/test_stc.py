"""STC planning, validation, and exact-finalization regressions."""

from __future__ import annotations

import json

import pytest
import yaml

from sage.errors import EvidenceLimitError, ValidationError
from sage.evidence import EvidencePolicy
from sage.stc import (
    STC_FINDING_CATEGORIES,
    finalize_stc_run,
    plan_stc_work_units,
    stc_authority_family,
    stc_package_measurements,
    validate_stc_submission,
)
from sage.work_units import EvidenceRecord


def _record(book: str, verse: int, text: str, *, role: str) -> EvidenceRecord:
    """Build one routed SFM Scripture record."""
    return EvidenceRecord(
        book=book,
        chapter=1,
        verse_start=verse,
        verse_end=verse,
        payload={"body_text": text, "resource_role": role},
        sfm=f"\\v {verse} {text}",
        section_id=f"{book}-S1",
        paragraph_id=f"{book}-P{verse}",
        discourse_unit_id=f"{book}-D{verse}",
        discourse_unit_kind="PARAGRAPH",
        discourse_unit_marker="p",
    )


def _policy(*, target: int = 100, hard: int = 140) -> EvidencePolicy:
    """Return a small deterministic SFM-only slicing policy."""
    return EvidencePolicy(
        target_estimated_tokens=target,
        hard_estimated_tokens=hard,
        hard_serialized_bytes=2000,
        minimum_target_tokens=1,
        maximum_primary_verse_units=220,
        context_before_verses=0,
        context_after_verses=0,
    )


def test_stc_routes_testament_to_primary_ol_family() -> None:
    """STC must choose GRK for NT and HEB for OT, never a translation reference."""
    assert stc_authority_family("JHN") == "GRK"
    assert stc_authority_family("GEN") == "HEB"
    with pytest.raises(ValidationError) as caught:
        stc_authority_family("BAR")
    assert caught.value.code == "STC_CANONICAL_BOOK_REQUIRED"


def test_stc_planning_sizes_wip_and_ol_sfm_together() -> None:
    """A route that fits WIP alone must still split when WIP+OL exceeds the hard guard."""
    wip = tuple(_record("JHN", verse, "w" * 90, role="WIP") for verse in range(1, 5))
    ol = tuple(_record("JHN", verse, "α" * 90, role="GRK") for verse in range(1, 5))

    units = plan_stc_work_units(wip, ol, _policy(target=90, hard=120), unit_prefix="STC-JHN")

    assert len(units) > 1
    assert {ref.label() for unit in units for ref in unit.primary_refs} == {
        "JHN 1:1", "JHN 1:2", "JHN 1:3", "JHN 1:4"
    }
    assert all(unit.measurement.estimated_tokens <= 120 for unit in units)


def test_stc_short_scope_is_not_split_by_a_discourse_count_cap(package_root) -> None:
    """STC keeps a sub-target short book together unless a routed-SFM hard limit requires a split."""
    raw = yaml.safe_load(
        (package_root / "system" / "config" / "workflows" / "saw" / "profile.yml").read_text(
            encoding="utf-8"
        )
    )
    policy = EvidencePolicy.from_mapping(raw["evidence_policies"]["stc"])
    wip = tuple(_record("JHN", verse, "word", role="WIP") for verse in range(1, 26))
    ol = tuple(_record("JHN", verse, "λόγος", role="GRK") for verse in range(1, 26))

    units = plan_stc_work_units(wip, ol, policy, unit_prefix="STC-JHN")

    assert policy.maximum_primary_discourse_units == 0
    assert len(units) == 1
    assert units[0].measurement.estimated_tokens < 1000


def test_stc_package_exposes_wip_source_and_combined_route_measurements() -> None:
    """STC operator display data names both routed streams and their combined size."""
    wip = tuple(_record("JHN", verse, "word", role="WIP") for verse in range(1, 3))
    ol = tuple(_record("JHN", verse, "λόγος", role="GRK") for verse in range(1, 3))
    units = plan_stc_work_units(wip, ol, _policy(), unit_prefix="STC-JHN")

    package = stc_package_measurements(units, ol)[0]

    assert package["route"]["estimated_tokens"] == (
        package["wip"]["estimated_tokens"] + package["ol"]["estimated_tokens"]
    )
    assert package["analysis_route"] == "STC_CORRESPONDENCE"


def test_stc_planning_fails_closed_when_ol_coverage_is_missing() -> None:
    """Every planned WIP primary coordinate must have routed primary-OL coverage."""
    wip = tuple(_record("JHN", verse, "w", role="WIP") for verse in range(1, 3))
    ol = (_record("JHN", 1, "α", role="GRK"),)

    with pytest.raises(ValidationError) as caught:
        plan_stc_work_units(wip, ol, _policy(), unit_prefix="STC-JHN")
    assert caught.value.code == "SFM_ROUTE_PRIMARY_COVERAGE_MISMATCH"


def test_stc_categories_are_frozen() -> None:
    """STC exposes only the four governed finding categories."""
    assert STC_FINDING_CATEGORIES == {"OMISSION", "ADDITION", "VARIATION", "CONSISTENCY"}


def test_stc_submission_normalizes_stable_finding_identity(tmp_path) -> None:
    """Provider IDs cannot define canonical STC finding identity."""
    payload = {
        "review_summary": "One governed variation.",
        "report_language": "eng",
        "findings": [{
            "finding_id": "provider-id",
            "category": "variation",
            "target_reference": "JHN 1:1",
            "summary": "Material departure.",
            "wip_evidence": "WIP words",
            "ol_evidence": "OL words",
        }],
    }
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    first = validate_stc_submission(
        path,
        task_id="TASK-1",
        work_unit_id="WU-1",
        scope_value="JHN 1:1",
        expected_references=("JHN 1:1",),
        authority_family="GRK",
        task_fingerprint="abc",
        narrative_language="eng",
    )
    second = validate_stc_submission(
        path,
        task_id="TASK-1",
        work_unit_id="WU-1",
        scope_value="JHN 1:1",
        expected_references=("JHN 1:1",),
        authority_family="GRK",
        task_fingerprint="abc",
        narrative_language="eng",
    )

    finding = first["findings"][0]
    assert finding["finding_id"].startswith("STC-F-")
    assert finding["finding_id"] == second["findings"][0]["finding_id"]
    assert finding["authority_family"] == "GRK"
    assert finding["authority_role"] == "PRIMARY"


def test_stc_zero_finding_submission_still_proves_analysis(tmp_path) -> None:
    """A zero-finding terminal result carries an analytical-completion receipt."""
    path = tmp_path / "findings.json"
    path.write_text(json.dumps({
        "review_summary": "No governed findings.",
        "report_language": "eng",
        "findings": [],
    }), encoding="utf-8")

    result = validate_stc_submission(
        path,
        task_id="TASK-1",
        work_unit_id="WU-1",
        scope_value="GEN 1:1",
        expected_references=("GEN 1:1",),
        authority_family="HEB",
        task_fingerprint="abc",
        narrative_language="eng",
    )

    assert result["finding_count"] == 0
    assert result["primary_coverage"] == ["GEN 1:1"]
    assert result["analytical_completion"]["status"] == "COMPLETE"


def test_stc_finalizer_writes_canonical_zero_finding_artifacts(tmp_path) -> None:
    """Exact terminal coverage finalizes even when no findings exist."""
    paths = finalize_stc_run(
        run_id="RUN-1",
        planned_units=[{"work_unit_id": "WU-1", "primary_coverage": ["JHN 1:1"]}],
        accepted_results=[{
            "work_unit_id": "WU-1",
            "primary_coverage": ["JHN 1:1"],
            "analytical_completion": {"status": "COMPLETE"},
            "findings": [],
        }],
        output_root=tmp_path,
    )

    assert paths["run_result"].name == "STC_RUN_RESULT.json"
    assert paths["findings"].name == "STC_FINDINGS.json"
    assert paths["report"].name == "STC_REPORT.md"
    run = json.loads(paths["run_result"].read_text(encoding="utf-8"))
    assert run["status"] == "COMPLETE"
    assert run["finding_count"] == 0


def test_stc_finalizer_rejects_missing_result_and_coverage_drift(tmp_path) -> None:
    """Exact planned work-unit ownership is fail-closed."""
    plan = [{"work_unit_id": "WU-1", "primary_coverage": ["JHN 1:1"]}]
    with pytest.raises(ValidationError) as missing:
        finalize_stc_run(run_id="RUN", planned_units=plan, accepted_results=[], output_root=tmp_path)
    assert missing.value.code == "MISSING_WORK_UNIT_RESULT"

    with pytest.raises(ValidationError) as drift:
        finalize_stc_run(
            run_id="RUN",
            planned_units=plan,
            accepted_results=[{
                "work_unit_id": "WU-1",
                "primary_coverage": ["JHN 1:2"],
                "analytical_completion": {"status": "COMPLETE"},
                "findings": [],
            }],
            output_root=tmp_path,
        )
    assert drift.value.code == "RESULT_COVERAGE_DRIFT"


def test_controller_aggregate_routes_partitioned_stc_to_canonical_finalizer(make_workspace) -> None:
    """The SAW plan controller must aggregate STC without applying WIP+Reference lineage rules."""
    import json
    from pathlib import Path

    from sage.act_tasks import aggregate_act_plan
    from sage.registry import load_ecosystem

    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    plans_root = config.workflow("saw").output_root / "plans"
    active_root = config.workflow("saw").output_root / "active"
    plan_id = "SAW-STC-MAT-CONTROLLER"
    run_id = "SAW-RUN-STC"
    job_id = "SAW_usWIP-usNIVv2"
    unit_id = f"{plan_id}-U001"
    task_root = active_root / unit_id
    validation = task_root / "validation"
    validation.mkdir(parents=True, exist_ok=True)
    manifest_path = task_root / "task-manifest.json"
    lineage = {"project.usWIP": "WIP-SHA", "project.GRK": "GRK-SHA"}
    manifest_path.write_text(json.dumps({
        "task_id": unit_id,
        "task_fingerprint": "TASK-SHA",
        "expected_references": ["MAT 1:1"],
        "resource_fingerprints": lineage,
    }) + "\n", encoding="utf-8")
    (validation / "submission.json").write_text(json.dumps({
        "status": "FINALIZED", "task_id": unit_id, "scope": "MAT 1:1"
    }) + "\n", encoding="utf-8")
    (validation / "normalized-findings.json").write_text(json.dumps({
        "schema_version": "1.0", "operation": "stc", "task_id": unit_id,
        "work_unit_id": unit_id, "task_fingerprint": "TASK-SHA", "scope": "MAT 1:1",
        "job_id": job_id, "run_id": run_id, "output_project": "usWIP",
        "contemporary_source": None, "primary_ol_authority": "GRK",
        "resource_fingerprints": lineage,
        "resource_bindings": {"WIP": "usWIP", "ORIGINAL_LANGUAGE_GREEK": "GRK"},
        "primary_coverage": ["MAT 1:1"],
        "analytical_completion": {"status": "COMPLETE", "review_item": "STC_CORRESPONDENCE", "reviewed_primary_coordinates": ["MAT 1:1"]},
        "finding_count": 0, "findings": [],
    }) + "\n", encoding="utf-8")
    plan_path = plans_root / f"{plan_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps({
        "schema_version": "1.0", "status": "PARTITIONED", "plan_id": plan_id,
        "workflow": "saw", "operation": "stc", "job_id": job_id, "run_id": run_id,
        "requested_scope": "MAT 1:1", "output_project": "usWIP", "contemporary_source": None,
        "primary_ol_authority": "GRK", "authority_family": "GRK", "authority_role": "PRIMARY",
        "expected_references": ["MAT 1:1"],
        "work_units": [{"unit_id": unit_id, "task_id": unit_id, "manifest_path": str(manifest_path.resolve()), "task_fingerprint": "TASK-SHA", "primary_coverage_atoms": ["MAT 1:1"]}],
    }) + "\n", encoding="utf-8")

    result = aggregate_act_plan(config, plan_path)

    assert result["status"] == "FINALIZED"
    assert result["finding_count"] == 0
    assert Path(result["canonical_artifacts"]["run_result"]).name == "STC_RUN_RESULT.json"
    assert Path(result["canonical_artifacts"]["findings"]).name == "STC_FINDINGS.json"
    assert Path(result["canonical_artifacts"]["report"]).name == "STC_REPORT.md"
    assert Path(result["report_path"]).name == "MAT_001_STC_ACTION-REPORT.md"
    assert Path(result["operator_note_text_path"]).name == "MAT_001_STC_OPERATOR-NOTE.txt"
