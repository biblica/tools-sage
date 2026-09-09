"""Provider-bound STC task boundary and canonical profile regressions."""

from __future__ import annotations

import json
import shutil
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from sage.act_tasks import create_act_task, submit_act_task
from sage.errors import ValidationError
from sage.external_access import READ_ONLY_SCRIPTURE
from sage.jobs import JobStore
from sage.plan_continuation import continue_analysis_plan
from sage.project_inventory import (
    register_project,
    registered_project_records,
    update_project_record,
)
from sage.registry import load_ecosystem
from sage.resource_mounts import set_resource_mount
from sage.stc import LEGACY_STC_PLANNER_VERSION, STC_PLANNER_VERSION
from sage.stc_reporting import _stc_report_markdown
from sage.storage import storage_layout


def _initialize(package_root: Path, root: Path, *, register_wip: bool = True) -> None:
    """Initialize one isolated SAGE fixture and optionally import its WIP Project."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system/src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-m", "sage.cli", "--settings", str(root / "ecosystem.yml"), "workspace", "initialize"], text=True, capture_output=True, env=env, check=False, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    if not register_wip:
        return
    registered = register_project(
        root,
        project_id="usWIP",
        project_path=storage_layout(root).projects_root / "usWIP",
        language_code="en",
        profile_variant="bol-target",
        base_vrs_file="eng.vrs",
        content_state="UNDER_REVIEW",
        imported_at=datetime(2026, 8, 29, 14, 35, tzinfo=timezone.utc),
    )
    scope = dict(registered["scope"])
    scope["roles"] = ["WIP"]
    update_project_record(root, "usWIP", {"enabled": True, "scope": scope})


def _install_fixture_ol_profile(root: Path, package_root: Path, family: str) -> None:
    """Bind the packaged authority profile to the fixture OL resource instance."""
    source = package_root / "system/resources/scripture/original-language" / family.lower() / "authority-profile.yml"
    target = root.parent / "localdata/work/projects" / family / "authority-profile.yml"
    shutil.copy2(source, target)


def test_stc_shortcut_uses_registered_project_import_date(
    package_root,
    make_workspace,
) -> None:
    """Catch the scriptable STC shortcut inventing a Job date from task creation time."""
    root = make_workspace(qualification_status="VALIDATED")
    _install_fixture_ol_profile(root, package_root, "GRK")
    _initialize(package_root, root)

    task = create_act_task(
        load_ecosystem(root / "ecosystem.yml"),
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:1",
    )

    assert task["job_id"] == "STC-usWIP_20260829"
    job = JobStore(root, root / "ecosystem.yml").load_job(task["job_id"], tool="stc")
    assert job.wip_snapshot is not None
    assert job.wip_snapshot["snapshot_date"] == "20260829"
    assert registered_project_records(root)["usWIP"]["imported_date"] == "20260829"


def test_stc_shortcut_blocks_project_without_sage_import_date(
    package_root,
    make_workspace,
) -> None:
    """Catch direct STC creation bypassing the Project-import provenance contract."""
    root = make_workspace(qualification_status="VALIDATED")
    _install_fixture_ol_profile(root, package_root, "GRK")
    _initialize(package_root, root, register_wip=False)

    with pytest.raises(ValidationError) as exc_info:
        create_act_task(
            load_ecosystem(root / "ecosystem.yml"),
            workflow="stc",
            operation="stc",
            output_project_id="usWIP",
            contemporary_source_id=None,
            scope_value="MAT 1:1",
        )

    assert exc_info.value.code == "PROJECT_IMPORT_DATE_MISSING"


def test_stc_degraded_secondary_rendering_keeps_secondary_summary_section() -> None:
    """Catch a selected secondary language appearing in the header but not findings."""
    document = {
        "report_language": "en",
        "language_authority": {
            "primary_language": "en",
            "secondary_language": "uk-UA",
        },
        "report_renderings": {
            "status": "DEGRADED",
            "findings": {},
        },
        "resource_bindings": {
            "WIP": "ukrNPUv1",
            "ORIGINAL_LANGUAGE_GREEK": "GRK",
        },
        "authority_family": "GRK",
        "primary_coverage": ["MAT 1:1"],
        "source_comparison_status": "COMPLETE",
        "scope": "MAT 1",
        "findings": [
            {
                "finding_id": "STC-MAT-001-0001",
                "target_reference": "MAT 1:1",
                "category": "CORRESPONDENCE",
                "summary": "The WIP wording requires review.",
                "wip_evidence": "WIP evidence",
                "ol_evidence": "OL evidence",
            }
        ],
    }

    report = _stc_report_markdown(document)

    assert "- Report languages: `en`; `uk-UA`" in report
    assert "**Summary — en**" in report
    assert "**Summary — uk-UA**" in report
    assert report.index("**Summary — en**") < report.index("**Summary — uk-UA**")
    assert report.index("**Summary — uk-UA**") < report.index("**ukrNPUv1 evidence**")


def test_stc_task_routes_only_wip_ol_sfm_and_complete_profiles(package_root, make_workspace) -> None:
    """STC must not expose or fingerprint Reference evidence in the sealed provider task."""
    root = make_workspace(qualification_status="VALIDATED")
    _install_fixture_ol_profile(root, package_root, "GRK")
    _initialize(package_root, root)
    update_project_record(
        root,
        "usWIP",
        {"display_name": "English Working Translation"},
    )
    reference_file = root.parent / "localdata/work/projects/usNIVv2/41MAT.SFM"
    reference_file.unlink()

    task = create_act_task(
        load_ecosystem(root / "ecosystem.yml"),
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:1",
    )

    manifest = json.loads(Path(task["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["skill_id"] == "stc"
    reads = {Path(item["path"]).name: item["evidence_class"] for item in manifest["allowed_reads"]}
    assert reads == {
        "wip.sfm": "SUBJECT_TEXT",
        "original-language.sfm": "AUTHORIZED_CONTENT_EVIDENCE",
        "wip-grammar-contract.json": "LINGUISTIC_COMPETENCE_RULES",
        "ol-authority-profile.yml": "AUTHORITY_INTERPRETATION_RULES",
    }
    assert manifest["resource_bindings"] == {
        "WIP": "usWIP",
        "ORIGINAL_LANGUAGE_GREEK": "GRK",
    }
    assert manifest["resource_display_names"] == {
        "WIP": "English Working Translation",
        "ORIGINAL_LANGUAGE_GREEK": "GRK",
    }
    assert manifest["contemporary_source"] is None
    assert set(manifest["resource_fingerprints"]) >= {"project.usWIP", "project.GRK"}
    assert "project.usNIVv2" not in manifest["resource_fingerprints"]
    assert manifest["context_budget"]["planning_basis"] == "ROUTED_SFM_ONLY"
    profile_rows = {item["stream_id"]: item for item in manifest["linguistic_profile_bindings"]}
    assert set(profile_rows) == {"WIP", "REPORT:PRIMARY", "GRK:PRIMARY"}
    assert {item["profile_class"] for item in profile_rows.values()} == {
        "LANGUAGE_PROFILE", "OL_AUTHORITY_PROFILE"
    }
    assert profile_rows["WIP"]["path"] == profile_rows["REPORT:PRIMARY"]["path"]
    assert profile_rows["WIP"]["sha256"] == profile_rows["REPORT:PRIMARY"]["sha256"]
    act = Path(task["act_path"]).read_text(encoding="utf-8")
    assert "Use only the supplied WIP + OL slice as evidence" in act
    assert "Authorized REFERENCE" not in act
    assert "Reference Project" not in act
    assert "- REFERENCE:" not in act


@pytest.mark.parametrize(
    ("planner_version", "expected_ol_reference", "unexpected_ol_reference"),
    (
        (STC_PLANNER_VERSION, "\\v 2 ", "\\v 3 "),
        (LEGACY_STC_PLANNER_VERSION, "\\v 3 ", "\\v 2 "),
    ),
)
def test_stc_task_routes_ol_by_its_persisted_planner_version(
    package_root,
    make_workspace,
    planner_version: str,
    expected_ol_reference: str,
    unexpected_ol_reference: str,
) -> None:
    """V2 uses canonical OL correspondence while resumed V1 remains exact-local."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _install_fixture_ol_profile(root, package_root, "GRK")
    projects_root = root.parent / "localdata/work/projects"
    (projects_root / "usWIP" / "custom.vrs").write_text(
        "MAT 1:3 = MAT 1:2\n",
        encoding="utf-8",
    )
    settings = root / "ecosystem.yml"
    settings_data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    settings_data["projects"]["usWIP"]["versification"]["custom_file"] = "custom.vrs"
    settings.write_text(yaml.safe_dump(settings_data, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)

    task = create_act_task(
        load_ecosystem(settings),
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:3",
        stc_planner_version=planner_version,
    )

    manifest_path = Path(task["manifest_path"])
    ol_sfm = (manifest_path.parent / "packet" / "original-language.sfm").read_text(
        encoding="utf-8"
    )
    assert expected_ol_reference in ol_sfm
    assert unexpected_ol_reference not in ol_sfm
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["stc_planner_version"] == planner_version
    if planner_version == STC_PLANNER_VERSION:
        assert manifest["stc_alignment"] == {
            "primary_local_atoms": ["MAT 1:3"],
            "canonical_atoms": ["MAT 1:2"],
            "authority_stream": "GRK:PRIMARY",
            "authority_local_spans": ["MAT 1:2"],
            "missing_canonical_atoms": [],
        }
    else:
        assert manifest["stc_alignment"] is None


def test_plannerless_stc_plan_resumes_without_mutation(
    package_root,
    make_workspace,
) -> None:
    """A frozen pre-V2 plan remains an exact-local, immutable continuation artifact."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _install_fixture_ol_profile(root, package_root, "GRK")
    projects_root = root.parent / "localdata/work/projects"
    (projects_root / "usWIP" / "custom.vrs").write_text(
        "MAT 1:3 = MAT 1:2\n",
        encoding="utf-8",
    )
    settings = root / "ecosystem.yml"
    settings_data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    settings_data["projects"]["usWIP"]["versification"]["custom_file"] = "custom.vrs"
    settings.write_text(yaml.safe_dump(settings_data, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)
    config = load_ecosystem(settings)
    task = create_act_task(
        config,
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:3",
        stc_planner_version=LEGACY_STC_PLANNER_VERSION,
    )
    store = JobStore(root, settings)
    job = store.load_job(task["job_id"], tool="stc")
    run = store.load_run(job, task["run_id"])
    plan = {
        "schema_version": "1.0",
        "status": "PARTITIONED",
        "plan_id": "STC-MAT-LEGACY",
        "workflow": "stc",
        "operation": "stc",
        "job_id": job.job_id,
        "run_id": run.run_id,
        "work_units": [{
            "unit_id": task["work_unit_id"],
            "task_id": task["task_id"],
            "scope": task["scope"],
            "manifest_path": task["manifest_path"],
        }],
    }
    plan_path = run.root / "plans" / "STC-MAT-LEGACY.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
    plan_bytes = plan_path.read_bytes()

    continuation = continue_analysis_plan(config, plan_path)

    ol_sfm = (
        Path(task["manifest_path"]).parent / "packet" / "original-language.sfm"
    ).read_text(encoding="utf-8")
    assert continuation["status"] == "NEXT_WORK_UNIT"
    assert "\\v 3 " in ol_sfm
    assert "\\v 2 " not in ol_sfm
    assert "stc_planner_version" not in plan
    assert plan_path.read_bytes() == plan_bytes


def test_stc_task_reports_empty_primary_ol_coordinate_without_aborting(
    package_root,
    make_workspace,
) -> None:
    """A one-verse WIP scope survives when the ready GRK source has no such verse."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=2)
    _install_fixture_ol_profile(root, package_root, "GRK")
    greek_file = root.parent / "localdata/work/projects/GRK/41MAT.SFM"
    greek_file.write_text(
        "\n".join(
            line for line in greek_file.read_text(encoding="utf-8").splitlines()
            if not line.startswith("\\v 2 ")
        ) + "\n",
        encoding="utf-8",
    )
    _initialize(package_root, root)

    task = create_act_task(
        load_ecosystem(root / "ecosystem.yml"),
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:2",
    )

    manifest_path = Path(task["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["expected_references"] == ["MAT 1:2"]
    assert manifest["packets"]["original_language"]["primary_references"] == []
    assert len(manifest["source_text_issues"]) == 1
    issue = manifest["source_text_issues"][0]
    assert issue["status"] == "REPORT_ONLY"
    assert issue["classification"] == "STRUCTURE_PROBLEM"
    assert issue["structure_status"] == "VERSIFICATION_MISMATCH"
    assert issue["text_relation"] == "ADDITION"
    assert issue["source_project_id"] == "GRK"
    assert issue["wip_project_id"] == "usWIP"
    assert issue["reference"] == "MAT 1:2"
    assert Path(manifest_path.parent / "packet/original-language.sfm").read_text(
        encoding="utf-8"
    ) == "\\id MAT\n\\c 1\n"
    assert "Do not invent wording for source coordinates reported as absent" in Path(
        task["act_path"]
    ).read_text(encoding="utf-8")

    output = manifest_path.parent / "output/findings.json"
    output.write_text(
        json.dumps({
            "review_summary": "The WIP coordinate was reviewed; no OL wording was available.",
            "report_language": manifest["narrative_language"]["tag"],
            "findings": [],
        }),
        encoding="utf-8",
    )
    result = submit_act_task(load_ecosystem(root / "ecosystem.yml"), manifest_path)
    normalized = json.loads(
        (manifest_path.parent / "validation/normalized-findings.json").read_text(encoding="utf-8")
    )
    assert normalized["source_comparison_status"] == "COMPLETE_WITH_STRUCTURE_PROBLEMS"
    assert normalized["source_text_issues"] == manifest["source_text_issues"]
    published_report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "## Structural issues" in published_report
    assert "MAT 1:2" in published_report


def test_stc_task_accepts_governed_authority_profile_from_external_ol_root(
    package_root,
    make_workspace,
) -> None:
    """External OL staging treats the authority profile as governed metadata, not Scripture."""
    root = make_workspace(qualification_status="VALIDATED")
    _install_fixture_ol_profile(root, package_root, "GRK")
    local_greek = root.parent / "localdata/work/projects/GRK"
    external_greek = root.parent / "external-GRK"
    shutil.copytree(local_greek, external_greek)
    set_resource_mount(
        root,
        project_id="GRK",
        external_path=external_greek,
        access_mode=READ_ONLY_SCRIPTURE,
    )
    _initialize(package_root, root)

    task = create_act_task(
        load_ecosystem(root / "ecosystem.yml"),
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:1",
    )

    manifest = json.loads(Path(task["manifest_path"]).read_text(encoding="utf-8"))
    profile = next(
        item for item in manifest["allowed_reads"]
        if Path(item["path"]).name == "ol-authority-profile.yml"
    )
    assert profile["evidence_class"] == "AUTHORITY_INTERPRETATION_RULES"


def test_stc_submission_uses_stc_grammar_and_writes_standalone_canonical_artifacts(package_root, make_workspace) -> None:
    """A sealed one-unit STC task must finalize from semantic STC output, including zero findings."""
    from sage.act_tasks import submit_act_task

    root = make_workspace(qualification_status="VALIDATED")
    _install_fixture_ol_profile(root, package_root, "GRK")
    _initialize(package_root, root)
    reference_file = root.parent / "localdata/work/projects/usNIVv2/41MAT.SFM"
    reference_file.unlink()
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:1",
    )
    manifest_path = Path(task["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output = manifest_path.parent / "output/findings.json"
    output.write_text(
        json.dumps({
            "review_summary": "The assigned primary coordinate was reviewed.",
            "report_language": manifest["narrative_language"]["tag"],
            "findings": [],
        }),
        encoding="utf-8",
    )

    result = submit_act_task(config, manifest_path)

    assert result["status"] == "FINALIZED"
    normalized = json.loads((manifest_path.parent / "validation/normalized-findings.json").read_text(encoding="utf-8"))
    assert normalized["operation"] == "stc"
    assert normalized["finding_count"] == 0
    assert normalized["analytical_completion"]["status"] == "COMPLETE"
    canonical = manifest_path.parent / "validation/stc"
    assert (canonical / "STC_RUN_RESULT.json").is_file()
    assert (canonical / "STC_FINDINGS.json").is_file()
    assert (canonical / "STC_REPORT.md").is_file()
    report_path = Path(result["report_path"])
    note_path = Path(result["operator_note_text_path"])
    assert report_path.name == f"{normalized['run_id']}_MAT-001_ACTION-REPORT.md"
    assert note_path.name == f"{normalized['run_id']}_MAT-001_OPERATOR-NOTE.txt"
    assert report_path.parent.name == "001"
    assert report_path.parent.parent.name == "MAT"
    assert "Source Text Correspondence (STC) Report" in report_path.read_text(encoding="utf-8")
    assert note_path.is_file()
