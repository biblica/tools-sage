"""BIC SOURCE-to-TARGET versification alignment and write-safety regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.act_tasks import (
    create_act_task,
    submit_act_task,
    validate_act_request_readiness,
)
from sage.bounded_target import preflight_bounded_target_commit
from sage.errors import ValidationError
from sage.hashing import sha256_bytes, sha256_file
from sage.llm_tasks import _prompt
from sage.registry import load_ecosystem
from sage.storage import storage_layout


def _initialize(package_root: Path, root: Path) -> None:
    """Initialize one real disposable SAGE workspace without a provider call."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root / "system/src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(root / "ecosystem.yml"),
            "workspace",
            "initialize",
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def _configure_shifted_bic_projects(root: Path) -> None:
    """Give SOURCE 2CO 13:14 and TARGET its canonical local coordinate 13:13."""
    projects_root = storage_layout(root).projects_root
    sources = {
        "idKKHv0": "SOURCE FOURTEEN",
        "usNIVv2": "DONOR FOURTEEN",
        "usBOLx1": "EXISTING TARGET THIRTEEN",
    }
    verses = {"idKKHv0": 14, "usNIVv2": 14, "usBOLx1": 13}
    for project_id, text in sources.items():
        project_root = projects_root / project_id
        (project_root / "41MAT.SFM").unlink()
        verse = verses[project_id]
        scripture = (
            "\\id 2CO Fixture\n\\c 13\n\\p\n"
            "\\v 12 KEEP TARGET TWELVE\n"
            f"\\v {verse} {text}\n"
            if project_id == "usBOLx1"
            else f"\\id 2CO Fixture\n\\c 13\n\\p\n\\v {verse} {text}\n"
        )
        (project_root / "482CO.SFM").write_text(
            scripture,
            encoding="utf-8",
        )

    scripture_root = root / "system/resources/scripture"
    (scripture_root / "eng.vrs").write_text(
        "MAT 1:3\n2CO 13:14\n",
        encoding="utf-8",
    )
    (scripture_root / "org.vrs").write_text(
        "MAT 1:3\n2CO 13:13\n",
        encoding="utf-8",
    )
    (projects_root / "idKKHv0/custom.vrs").write_text(
        "2CO 13:14 = 2CO 13:13\n",
        encoding="utf-8",
    )

    settings_path = root / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    for project_id in sources:
        settings["projects"][project_id]["scope"]["expected_books"] = ["2CO"]
    settings["projects"]["idKKHv0"]["versification"]["custom_file"] = "custom.vrs"
    settings_path.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _configure_cross_book_bic_projects(package_root: Path, root: Path) -> None:
    """Use the shipped LXX EZR 11:1 to canonical TARGET-local NEH 1:1 mapping."""
    projects_root = storage_layout(root).projects_root
    for project_id in ("idKKHv0", "usNIVv2"):
        project_root = projects_root / project_id
        (project_root / "41MAT.SFM").unlink()
        (project_root / "15EZR.SFM").write_text(
            "\\id EZR Fixture\n\\c 11\n\\p\n\\v 1 SOURCE BOOK COORDINATE\n",
            encoding="utf-8",
        )
    target_root = projects_root / "usBOLx1"
    (target_root / "41MAT.SFM").unlink()
    (target_root / "16NEH.SFM").write_text(
        "\\id NEH Fixture\n\\c 1\n\\p\n\\v 1 TARGET BOOK COORDINATE\n",
        encoding="utf-8",
    )
    scripture_root = root / "system/resources/scripture"
    (scripture_root / "lxx.vrs").write_bytes(
        (package_root / "system/resources/scripture/lxx.vrs").read_bytes()
    )
    (scripture_root / "eng.vrs").write_text(
        "EZR 11:1\nNEH 1:1\n",
        encoding="utf-8",
    )
    (scripture_root / "org.vrs").write_text(
        "NEH 1:1\n",
        encoding="utf-8",
    )

    settings_path = root / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["versification"]["base_files"].append("lxx.vrs")
    settings["projects"]["idKKHv0"]["scope"]["expected_books"] = ["EZR"]
    settings["projects"]["idKKHv0"]["versification"]["base_file"] = "lxx.vrs"
    settings["projects"]["usNIVv2"]["scope"]["expected_books"] = ["EZR"]
    settings["projects"]["usBOLx1"]["scope"]["expected_books"] = ["NEH"]
    settings["projects"]["usBOLx1"]["versification"]["base_file"] = "org.vrs"
    settings_path.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _configure_chapter_boundary_bic_projects(root: Path) -> None:
    """Map two SOURCE chapter runs into one TARGET chapter run."""
    projects_root = storage_layout(root).projects_root
    source_text = (
        "\\id GEN Fixture\n\\c 31\n\\p\n\\v 55 SOURCE FIFTY-FIVE\n"
        "\\c 32\n\\p\n\\v 1 SOURCE ONE\n"
    )
    target_text = (
        "\\id GEN Fixture\n\\c 32\n\\p\n"
        "\\v 1 TARGET ONE\n\\v 2 TARGET TWO\n"
    )
    for project_id in ("idKKHv0", "usNIVv2"):
        project_root = projects_root / project_id
        (project_root / "41MAT.SFM").unlink()
        (project_root / "01GEN.SFM").write_text(source_text, encoding="utf-8")
    for project_id in ("usBOLx1", "usWIP", "usNIRVv2", "GRK", "HEB"):
        project_root = projects_root / project_id
        (project_root / "41MAT.SFM").unlink()
        (project_root / "01GEN.SFM").write_text(target_text, encoding="utf-8")

    scripture_root = root / "system/resources/scripture"
    (scripture_root / "eng.vrs").write_text(
        "GEN 31:55 32:1\n",
        encoding="utf-8",
    )
    (scripture_root / "org.vrs").write_text(
        "GEN 32:2\n",
        encoding="utf-8",
    )
    (projects_root / "idKKHv0/custom.vrs").write_text(
        "GEN 31:55 = GEN 32:1\nGEN 32:1 = GEN 32:2\n",
        encoding="utf-8",
    )

    settings_path = root / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    for project in settings["projects"].values():
        project["scope"]["expected_books"] = ["GEN"]
    settings["projects"]["idKKHv0"]["versification"]["custom_file"] = "custom.vrs"
    settings["projects"]["usBOLx1"]["versification"]["base_file"] = "org.vrs"
    settings_path.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def test_bic_task_projects_source_coverage_to_target_local_coordinates(
    package_root: Path,
    make_workspace,
) -> None:
    """Reusing SOURCE labels for TARGET output would write the wrong local verse."""
    root = make_workspace(qualification_status="VALIDATED")
    _configure_shifted_bic_projects(root)
    _initialize(package_root, root)

    task = create_act_task(
        load_ecosystem(root / "ecosystem.yml"),
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="2CO 13:14",
    )

    assert task["scope"] == "2CO 13:14"
    assert task["expected_references"] == ["2CO 13:14"]
    assert task["source_primary_references"] == ["2CO 13:14"]
    assert task["expected_output_references"] == ["2CO 13:13"]
    assert task["target_scope"] == "2CO 13:13"
    alignment = task["bic_alignment"]
    assert alignment["primary_stream"] == "SOURCE"
    assert alignment["target_stream"] == "TARGET"
    assert alignment["source_primary_references"] == ["2CO 13:14"]
    assert alignment["canonical_references"] == ["2CO 13:13"]
    assert alignment["target_local_references"] == ["2CO 13:13"]
    assert alignment["target_existing_references"] == ["2CO 13:13"]
    assert alignment["target_shapes"] == [[13, 13, 13]]
    assert alignment["precision"] == "COORDINATE"
    assert alignment["is_deterministic"] is True
    assert alignment["is_writable"] is True
    assert len(alignment["source_effective_vrs_sha256"]) == 64
    assert len(alignment["target_effective_vrs_sha256"]) == 64
    assert alignment["advisory"] is None
    assert "output_project" not in task["packets"]
    assert all(
        "usBOLx1/482CO.SFM" not in str(item["path"])
        for item in task["allowed_reads"]
    )
    prompt = _prompt(
        manifest=task,
        act_text=Path(task["act_path"]).read_text(encoding="utf-8"),
        reads=[],
    )
    assignment = json.loads(
        prompt.split("Controller-supplied assignment (only the response-envelope task_id is copied; ", 1)[
            1
        ].splitlines()[1]
    )
    assert assignment["source_primary_references"] == ["2CO 13:14"]
    assert assignment["expected_output_references"] == ["2CO 13:13"]
    assert assignment["target_scope"] == "2CO 13:13"


def test_bic_target_readiness_uses_the_projected_target_scope(
    package_root: Path,
    make_workspace,
) -> None:
    """A TARGET defect at the projected coordinate must not be treated as out-of-scope."""
    root = make_workspace(qualification_status="VALIDATED")
    _configure_shifted_bic_projects(root)
    target_file = storage_layout(root).projects_root / "usBOLx1/482CO.SFM"
    target_file.write_text(
        "\\id 2CO Fixture\n\\c 13\n\\p\n"
        "\\v 13 FIRST TARGET RECORD\n\\v 13 DUPLICATE TARGET RECORD\n"
        "\\v 14 SOURCE-SCOPE DECOY\n",
        encoding="utf-8",
    )
    _initialize(package_root, root)

    with pytest.raises(ValidationError) as caught:
        create_act_task(
            load_ecosystem(root / "ecosystem.yml"),
            workflow="bic",
            operation="inspect",
            output_project_id="usBOLx1",
            contemporary_source_id="idKKHv0",
            scope_value="2CO 13:14",
        )

    assert caught.value.code == "REQUESTED_SCOPE_BLOCKED"
    assert caught.value.affected_scope == "2CO 13:13"


def test_bic_cross_book_projection_validates_and_indexes_the_target_book(
    package_root: Path,
    make_workspace,
) -> None:
    """TARGET readiness follows the projected book rather than the SOURCE book."""
    root = make_workspace(qualification_status="VALIDATED")
    _configure_cross_book_bic_projects(package_root, root)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    readiness = validate_act_request_readiness(
        config,
        workflow="bic",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="EZR 11:1",
    )
    assert readiness["target_scope"] == "NEH 1:1"
    assert readiness["project_statuses"]["usBOLx1"] == "READY"

    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="EZR 11:1",
    )

    assert task["source_primary_references"] == ["EZR 11:1"]
    assert task["expected_output_references"] == ["NEH 1:1"]
    assert task["target_scope"] == "NEH 1:1"
    assert task["bic_alignment"]["target_existing_references"] == ["NEH 1:1"]
    assert task["bic_alignment"]["target_validation_scope"] == "NEH 1:1"
    vrs_evidence = json.loads(
        (Path(task["manifest_path"]).parent / "packet/vrs-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert vrs_evidence["scope"] == "EZR 11:1"
    assert vrs_evidence["resources"]["contemporary_source"]["scope"] == "EZR 11:1"
    assert vrs_evidence["resources"]["output_project"]["scope"] == "NEH 1:1"

    _submit_inspect(config, task)
    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="EZR 11:1",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output/rewrite.usfm"
    rewrite_output.write_text(
        "\\id NEH Fixture\n\\c 1\n\\p\n\\v 1 CROSS-BOOK REWRITE\n",
        encoding="utf-8",
    )
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)
    self_check = create_act_task(
        config,
        workflow="bic",
        operation="self_check",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="EZR 11:1",
        predecessor_task=str(rewrite_manifest),
    )
    self_manifest = Path(self_check["manifest_path"])
    self_output = self_manifest.parent / "output/self-check.usfm"
    self_output.write_text(rewrite_output.read_text(encoding="utf-8"), encoding="utf-8")
    _write_bic_assessment(self_check, self_output)
    result = submit_act_task(config, self_manifest)

    target_text = (
        storage_layout(root).projects_root / "usBOLx1/16NEH.SFM"
    ).read_text(encoding="utf-8")
    assert "CROSS-BOOK REWRITE" in target_text
    assert result["commit"]["bounded_scope"] == "NEH 1:1"
    assert result["commit"]["source_scope"] == "EZR 11:1"


def test_bic_empty_cross_book_target_uses_the_target_book_number(
    package_root: Path,
    make_workspace,
) -> None:
    """A new TARGET file must never inherit the SOURCE book's numeric prefix."""
    root = make_workspace(qualification_status="VALIDATED")
    _configure_cross_book_bic_projects(package_root, root)
    projects_root = storage_layout(root).projects_root
    (projects_root / "usBOLx1/16NEH.SFM").unlink()
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="EZR 11:1",
    )
    _submit_inspect(config, inspect)
    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="EZR 11:1",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output/rewrite.usfm"
    rewrite_output.write_text(
        "\\id NEH Fixture\n\\c 1\n\\p\n\\v 1 NEW CROSS-BOOK TARGET\n",
        encoding="utf-8",
    )
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)
    self_check = create_act_task(
        config,
        workflow="bic",
        operation="self_check",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="EZR 11:1",
        predecessor_task=str(rewrite_manifest),
    )
    self_manifest = Path(self_check["manifest_path"])
    self_output = self_manifest.parent / "output/self-check.usfm"
    self_output.write_text(rewrite_output.read_text(encoding="utf-8"), encoding="utf-8")
    _write_bic_assessment(self_check, self_output)

    result = submit_act_task(config, self_manifest)

    target_path = Path(result["commit"]["target_file"])
    assert target_path.name == "16NEHusBOLx1.SFM"
    assert target_path.is_file()
    assert not (projects_root / "usBOLx1/15NEHusBOLx1.SFM").exists()


def test_bic_changed_chapter_topology_is_inspect_only(
    package_root: Path,
    make_workspace,
) -> None:
    """A projection incompatible with the sealed marker contract must fail before REWRITE."""
    root = make_workspace(qualification_status="VALIDATED")
    _configure_chapter_boundary_bic_projects(root)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="GEN 31:55-32:1",
    )

    alignment = inspect["bic_alignment"]
    assert alignment["precision"] == "COORDINATE"
    assert alignment["target_scope"] == "GEN 32:1-2"
    assert alignment["chapter_topology"]["source_break_before_record_indexes"] == [0, 1]
    assert alignment["chapter_topology"]["target_break_before_record_indexes"] == [0]
    assert alignment["chapter_topology"]["is_compatible"] is False
    assert alignment["is_writable"] is False
    assert alignment["advisory"]["code"] == "BIC_TARGET_VRS_ALIGNMENT_REQUIRED"

    _submit_inspect(config, inspect)
    inspect_manifest = Path(inspect["manifest_path"])
    target_file = storage_layout(root).projects_root / "usBOLx1/01GEN.SFM"
    target_before = target_file.read_bytes()
    task_container = inspect_manifest.parent.parent
    task_directories_before = sorted(path.name for path in task_container.iterdir())

    with pytest.raises(ValidationError) as caught:
        create_act_task(
            config,
            workflow="bic",
            operation="rewrite",
            output_project_id="usBOLx1",
            contemporary_source_id="idKKHv0",
            scope_value="GEN 31:55-32:1",
        )

    assert caught.value.code == "BIC_TARGET_VRS_ALIGNMENT_REQUIRED"
    assert target_file.read_bytes() == target_before
    assert sorted(path.name for path in task_container.iterdir()) == task_directories_before


def _file_snapshot(root: Path) -> dict[str, bytes]:
    """Return exact file bytes below one governed transaction boundary."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _submit_inspect(config, task: dict) -> None:
    """Submit one valid SOURCE-local INSPECT proposal."""
    manifest = Path(task["manifest_path"])
    (manifest.parent / "output/inspect-submission.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation_id": task["task_id"],
                "scope": task["scope"],
                "resource_fingerprints": task["resource_fingerprints"],
                "proposals": [
                    {
                        "submitted_id": "P1",
                        "record_type": "LANGUAGE_RENDERING",
                        "payload": {"source": "fixture", "target": "fixture"},
                        "evidence_refs": task["source_primary_references"],
                    }
                ],
                "challenges": [],
            }
        ),
        encoding="utf-8",
    )
    submit_act_task(config, manifest)


def _write_bic_assessment(task: dict, output_path: Path) -> None:
    """Write complete grammar and challenge output for a BIC candidate."""
    grammar = task["project_grammar"]
    (output_path.parent / "grammar-assessment.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": task["task_id"],
                "scope": task["scope"],
                "profile_id": grammar["profile_id"],
                "profile_sha256": grammar["profile_sha256"],
                "output_sha256": sha256_file(output_path),
                "rules": [
                    {
                        "rule_id": rule_id,
                        "status": "PASS",
                        "evidence": "Checked against the bounded TARGET-local candidate.",
                    }
                    for rule_id in grammar["rule_ids"]
                ],
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    if task["operation"] == "rewrite":
        (output_path.parent / "translation-challenges.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.2",
                    "task_id": task["task_id"],
                    "operation": "rewrite",
                    "scope": task["scope"],
                    "output_sha256": sha256_file(output_path),
                    "challenges": [],
                }
            ),
            encoding="utf-8",
        )


def _reseal_as_legacy_bic_task(task: dict) -> Path:
    """Model a genuine pre-Stage-4 schema-2.4 task and its trusted control."""
    manifest_path = Path(task["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field_name in (
        "bic_alignment",
        "source_primary_references",
        "expected_output_references",
        "target_scope",
    ):
        manifest.pop(field_name, None)
    fingerprints = dict(manifest["resource_fingerprints"])
    fingerprints.pop("vrs.SOURCE", None)
    fingerprints.pop("vrs.TARGET", None)
    manifest["resource_fingerprints"] = fingerprints
    identity = {
        key: value
        for key, value in manifest.items()
        if key
        not in {
            "task_id",
            "task_root",
            "submit_commands",
            "task_fingerprint",
            "created_utc",
        }
    }
    fingerprint = sha256_bytes(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    manifest["task_fingerprint"] = fingerprint
    os.chmod(manifest_path, 0o644)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(manifest_path, 0o444)

    control_path = Path(task["control_path"])
    control = json.loads(control_path.read_text(encoding="utf-8"))
    control["manifest_sha256"] = sha256_file(manifest_path)
    control["task_fingerprint"] = fingerprint
    os.chmod(control_path, 0o644)
    control_path.write_text(
        json.dumps(control, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(control_path, 0o444)
    return manifest_path


def test_bic_commit_validates_and_merges_only_the_target_local_scope(
    package_root: Path,
    make_workspace,
) -> None:
    """A precise shifted projection must commit TARGET 13:13, never SOURCE 13:14."""
    root = make_workspace(qualification_status="VALIDATED")
    _configure_shifted_bic_projects(root)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="2CO 13:14",
    )
    _submit_inspect(config, inspect)
    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="2CO 13:14",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output/rewrite.usfm"
    rewrite_output.write_text(
        "\\id 2CO Candidate\n\\c 13\n\\p\n\\v 13 REWRITTEN TARGET THIRTEEN\n",
        encoding="utf-8",
    )
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)

    self_check = create_act_task(
        config,
        workflow="bic",
        operation="self_check",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="2CO 13:14",
        predecessor_task=str(rewrite_manifest),
    )
    staged_target = (
        Path(self_check["manifest_path"]).parent / "packet/staged-target.usj.json"
    ).read_text(encoding="utf-8")
    assert "REWRITTEN TARGET THIRTEEN" in staged_target
    assert '"verse_start": 13' in staged_target
    assert '"verse_start": 14' not in staged_target

    self_manifest = Path(self_check["manifest_path"])
    self_output = self_manifest.parent / "output/self-check.usfm"
    self_output.write_text(rewrite_output.read_text(encoding="utf-8"), encoding="utf-8")
    _write_bic_assessment(self_check, self_output)
    result = submit_act_task(config, self_manifest)

    target_text = (storage_layout(root).projects_root / "usBOLx1/482CO.SFM").read_text(
        encoding="utf-8"
    )
    assert "\\v 12 KEEP TARGET TWELVE" in target_text
    assert "\\v 13 REWRITTEN TARGET THIRTEEN" in target_text
    assert "\\v 14" not in target_text
    assert result["commit"]["bounded_scope"] == "2CO 13:13"
    assert result["commit"]["source_scope"] == "2CO 13:14"


def test_legacy_schema_2_4_bic_task_falls_back_to_original_coordinates(
    package_root: Path,
    make_workspace,
) -> None:
    """A sealed pre-Stage-4 task remains submittable when both VRS labels agree."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    _submit_inspect(config, inspect)
    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output/rewrite.usfm"
    source_text = (
        storage_layout(root).projects_root / "idKKHv0/41MAT.SFM"
    ).read_text(encoding="utf-8")
    rewrite_output.write_text(source_text, encoding="utf-8")
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)

    self_check = create_act_task(
        config,
        workflow="bic",
        operation="self_check",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
        predecessor_task=str(rewrite_manifest),
    )
    self_output = Path(self_check["manifest_path"]).parent / "output/self-check.usfm"
    self_output.write_text(source_text.replace("Verse 2.", "LEGACY VERSE TWO"), encoding="utf-8")
    _write_bic_assessment(self_check, self_output)
    legacy_manifest = _reseal_as_legacy_bic_task(self_check)

    result = submit_act_task(config, legacy_manifest)

    target_text = (
        storage_layout(root).projects_root / "usBOLx1/41MAT.SFM"
    ).read_text(encoding="utf-8")
    assert "LEGACY VERSE TWO" in target_text
    assert result["commit"]["bounded_scope"] == "MAT 1"
    assert result["commit"]["source_scope"] == "MAT 1"


def test_bic_preflight_uses_projected_target_shapes() -> None:
    """SOURCE-local verse labels must not drive TARGET-local shape preflight."""
    result = preflight_bounded_target_commit(
        "\\id 2CO Target\n\\c 13\n\\v 13 existing target\n",
        "\\id 2CO Source\n\\c 13\n\\v 14 source content\n",
        "2CO 13:13",
        expected_shapes=[[13, 13, 13]],
    )

    assert result["status"] == "READY"
    assert result["source_shapes"] == [(13, 13, 13)]


def test_bic_ambiguous_projection_is_advisory_for_inspect_and_blocks_rewrite(
    package_root: Path,
    make_workspace,
) -> None:
    """An equivalence-group mapping must never reach a writable BIC task or TARGET."""
    root = make_workspace(qualification_status="VALIDATED")
    _configure_shifted_bic_projects(root)
    projects_root = storage_layout(root).projects_root
    (projects_root / "idKKHv0/custom.vrs").write_text(
        "#! &2CO 13:13-14 = 2CO 13:13\n",
        encoding="utf-8",
    )
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="2CO 13:14",
    )
    advisory = inspect["bic_alignment"]["advisory"]
    assert advisory["code"] == "BIC_TARGET_VRS_ALIGNMENT_REQUIRED"
    assert advisory["classification"] == "STRUCTURE_ADVISORY"
    assert advisory["next_stage_allowed"] is False

    inspect_manifest = Path(inspect["manifest_path"])
    (inspect_manifest.parent / "output/inspect-submission.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation_id": inspect["task_id"],
                "scope": inspect["scope"],
                "resource_fingerprints": inspect["resource_fingerprints"],
                "proposals": [],
                "challenges": [
                    {
                        "submitted_id": "C1",
                        "scripture_reference": "2CO 13:14",
                        "challenge_type": "VERSIFICATION",
                        "summary": "SOURCE and TARGET use an equivalence-group mapping.",
                        "recommended_action": "Resolve TARGET coordinate ownership before REWRITE.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    submit_act_task(config, inspect_manifest)

    target_file = projects_root / "usBOLx1/482CO.SFM"
    target_before = target_file.read_bytes()
    task_container = inspect_manifest.parent.parent
    task_directories_before = sorted(path.name for path in task_container.iterdir())
    transaction_root = config.workflow("bic").transaction_root
    transactions_before = _file_snapshot(transaction_root)

    for operation in ("rewrite", "self_check"):
        with pytest.raises(ValidationError) as caught:
            create_act_task(
                config,
                workflow="bic",
                operation=operation,
                output_project_id="usBOLx1",
                contemporary_source_id="idKKHv0",
                scope_value="2CO 13:14",
            )
        assert caught.value.code == "BIC_TARGET_VRS_ALIGNMENT_REQUIRED"
    assert target_file.read_bytes() == target_before
    assert sorted(path.name for path in task_container.iterdir()) == task_directories_before
    assert _file_snapshot(transaction_root) == transactions_before


def test_bic_non_contiguous_target_projection_remains_inspect_only(
    package_root: Path,
    make_workspace,
) -> None:
    """Precise TARGET coordinates with a gap cannot define one bounded write scope."""
    root = make_workspace(qualification_status="VALIDATED")
    _configure_shifted_bic_projects(root)
    projects_root = storage_layout(root).projects_root
    (projects_root / "idKKHv0/482CO.SFM").write_text(
        "\\id 2CO Fixture\n\\c 13\n\\p\n"
        "\\v 13 SOURCE THIRTEEN\n\\v 14 SOURCE FOURTEEN\n",
        encoding="utf-8",
    )
    (projects_root / "usNIVv2/482CO.SFM").write_text(
        "\\id 2CO Fixture\n\\c 13\n\\p\n"
        "\\v 13 DONOR THIRTEEN\n\\v 14 DONOR FOURTEEN\n",
        encoding="utf-8",
    )
    (projects_root / "usBOLx1/482CO.SFM").write_text(
        "\\id 2CO Fixture\n\\c 13\n\\p\n"
        "\\v 12 KEEP TARGET TWELVE\n"
        "\\v 13 EXISTING TARGET THIRTEEN\n"
        "\\v 15 EXISTING TARGET FIFTEEN\n",
        encoding="utf-8",
    )
    scripture_root = root / "system/resources/scripture"
    (scripture_root / "eng.vrs").write_text(
        "MAT 1:3\n2CO 13:15\n",
        encoding="utf-8",
    )
    (projects_root / "idKKHv0/custom.vrs").write_text(
        "2CO 13:14 = 2CO 13:15\n",
        encoding="utf-8",
    )
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="2CO 13:13-14",
    )

    alignment = inspect["bic_alignment"]
    assert alignment["precision"] == "COORDINATE"
    assert alignment["target_local_references"] == ["2CO 13:13", "2CO 13:15"]
    assert alignment["target_scope"] is None
    assert alignment["advisory"]["code"] == "BIC_TARGET_VRS_ALIGNMENT_REQUIRED"
    assert alignment["advisory"]["next_stage_allowed"] is False

    inspect_manifest = Path(inspect["manifest_path"])
    (inspect_manifest.parent / "output/inspect-submission.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation_id": inspect["task_id"],
                "scope": inspect["scope"],
                "resource_fingerprints": inspect["resource_fingerprints"],
                "proposals": [],
                "challenges": [
                    {
                        "submitted_id": "C1",
                        "scripture_reference": "2CO 13:13-14",
                        "challenge_type": "VERSIFICATION",
                        "summary": "The projected TARGET-local coordinates are not contiguous.",
                        "recommended_action": "Resolve the TARGET write boundary before REWRITE.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    submit_act_task(config, inspect_manifest)
    target_file = projects_root / "usBOLx1/482CO.SFM"
    target_before = target_file.read_bytes()

    with pytest.raises(ValidationError) as caught:
        create_act_task(
            config,
            workflow="bic",
            operation="rewrite",
            output_project_id="usBOLx1",
            contemporary_source_id="idKKHv0",
            scope_value="2CO 13:13-14",
        )

    assert caught.value.code == "BIC_TARGET_VRS_ALIGNMENT_REQUIRED"
    assert target_file.read_bytes() == target_before
