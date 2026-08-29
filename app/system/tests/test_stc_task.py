"""Provider-bound STC task boundary and canonical profile regressions."""

from __future__ import annotations

import json
import shutil
import os
import subprocess
import sys
from pathlib import Path

from sage.act_tasks import create_act_task
from sage.external_access import READ_ONLY_SCRIPTURE
from sage.registry import load_ecosystem
from sage.resource_mounts import set_resource_mount


def _initialize(package_root: Path, root: Path) -> None:
    """Initialize one isolated SAGE fixture through the real CLI."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system/src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, "-m", "sage.cli", "--settings", str(root / "ecosystem.yml"), "workspace", "initialize"], text=True, capture_output=True, env=env, check=False, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


def _install_fixture_ol_profile(root: Path, package_root: Path, family: str) -> None:
    """Bind the packaged authority profile to the fixture OL resource instance."""
    source = package_root / "system/resources/scripture/original-language" / family.lower() / "authority-profile.yml"
    target = root.parent / "localdata/work/projects" / family / "authority-profile.yml"
    shutil.copy2(source, target)


def test_stc_task_routes_only_wip_ol_sfm_and_complete_profiles(package_root, make_workspace) -> None:
    """STC must not expose or fingerprint Reference evidence in the sealed provider task."""
    root = make_workspace(qualification_status="VALIDATED")
    _install_fixture_ol_profile(root, package_root, "GRK")
    _initialize(package_root, root)
    reference_file = root.parent / "localdata/work/projects/usNIVv2/41MAT.SFM"
    reference_file.unlink()

    task = create_act_task(
        load_ecosystem(root / "ecosystem.yml"),
        workflow="saw",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )

    manifest = json.loads(Path(task["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["skill_id"] == "saw-stc"
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
        workflow="saw",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
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
        workflow="saw",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
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
    assert report_path.name == "MAT_001_STC_ACTION-REPORT.md"
    assert note_path.name == "MAT_001_STC_OPERATOR-NOTE.txt"
    assert report_path.parent.name == "MAT"
    assert "Source Text Correspondence (STC) Report" in report_path.read_text(encoding="utf-8")
    assert note_path.is_file()
