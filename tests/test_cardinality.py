"""Cardinality, optional-OL, and human-facing binding grammar invariants."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage_core.act_tasks import create_act_task
from sage_core.errors import ValidationError
from sage_core.profiles import load_workflow_profile
from sage_core.registry import load_ecosystem
from sage_core.jobs import JobStore


def _write_yaml(path: Path, value: dict) -> None:
    """Write one stable YAML fixture."""
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _initialize(package_root: Path, root: Path) -> None:
    """Initialise a disposable workspace through the public CLI."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "core")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "sage_core.cli", "--settings", str(root / "ecosystem.yml"), "workspace", "initialize"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_machine_cardinality_vocabulary_is_explicit(package_root: Path) -> None:
    """Keep project cardinality machine-readable and separate from prose binding language."""
    tool = yaml.safe_load((package_root / "meta/schemas/job.schema.yml").read_text(encoding="utf-8"))
    controls = tool["controls"]
    assert controls["bic_cardinality"] == {
        "SOURCE": "exactly_one",
        "DONOR": "exactly_one",
        "TARGET": "exactly_one",
    }
    assert controls["bic_target_storage"]["cardinality"] == "exactly_one_of"
    assert controls["original_language_bindings"]["GRK"] == "zero_or_one"
    assert controls["original_language_bindings"]["HEB"] == "zero_or_one"
    assert controls["grammar_profile_selection"]["BIC_SOURCE_GRAMMAR"] == "exactly_one_active"
    assert controls["grammar_profile_selection"]["BIC_TARGET_GRAMMAR"] == "exactly_one_active"
    assert controls["grammar_profile_selection"]["SAW_WIP_GRAMMAR"] == "exactly_one_active"
    assert controls["effective_vrs"]["cardinality"] == "exactly_one"
    assert tool["cardinality_vocabulary"] == [
        "exactly_one", "zero_or_one", "one_or_more", "zero_or_more", "exactly_one_of"
    ]


def test_workflow_profiles_allow_optional_ol_bindings(make_workspace) -> None:
    """Greek and Hebrew are independently optional Job/workflow bindings."""
    root = make_workspace(qualification_status="VALIDATED")
    for workflow in ("bic", "saw"):
        path = root / f"workflows/{workflow}/profile.yml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw["bindings"].pop("ORIGINAL_LANGUAGE_GREEK", None)
        raw["bindings"].pop("ORIGINAL_LANGUAGE_HEBREW", None)
        _write_yaml(path, raw)
    config = load_ecosystem(root / "ecosystem.yml")
    bic = load_workflow_profile(config, config.workflow("bic"))
    saw = load_workflow_profile(config, config.workflow("saw"))
    assert "ORIGINAL_LANGUAGE_GREEK" not in bic.bindings
    assert "ORIGINAL_LANGUAGE_HEBREW" not in bic.bindings
    assert "ORIGINAL_LANGUAGE_GREEK" not in saw.bindings
    assert "ORIGINAL_LANGUAGE_HEBREW" not in saw.bindings


def test_jobs_accept_zero_ol_bindings_and_render_human_summary(make_workspace) -> None:
    """A Job can omit both OL bindings without weakening SOURCE/DONOR/TARGET cardinality."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    store = JobStore(config.root, config.settings_path)
    project = store.create_job(
        tool="bic",
        job_id="BIC_idKKHv0-usNIVv2-usBOLx1",
        display_name="BIC without preconfigured OL",
        bindings={
            "content_source": "idKKHv0",
            "lexical_donor": "usNIVv2",
            "generated_target": "usBOLx1",
        },
    )
    assert set(project.bindings) == {"content_source", "lexical_donor", "generated_target"}
    summary = (project.root / "README.md").read_text(encoding="utf-8")
    assert "SOURCE — one bound resource" in summary
    assert "DONOR — one bound resource" in summary
    assert "TARGET — one bound resource" in summary
    assert "Configured Greek resource: `NOT_CONFIGURED`" in summary
    assert "Configured Hebrew resource: `NOT_CONFIGURED`" in summary
    assert "Selected SOURCE grammar profile" in summary
    assert "Selected TARGET grammar profile" in summary
    assert "exactly_one" not in summary


def test_ol_free_saw_operation_does_not_require_ol_binding(package_root: Path, make_workspace) -> None:
    """Focused Check remains valid without configured Greek/Hebrew resources."""
    root = make_workspace(qualification_status="VALIDATED")
    profile_path = root / "workflows/saw/profile.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["bindings"].pop("ORIGINAL_LANGUAGE_GREEK", None)
    profile["bindings"].pop("ORIGINAL_LANGUAGE_HEBREW", None)
    _write_yaml(profile_path, profile)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="focused",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
        focus="Check the participant reference.",
        check_type="PARTICIPANT_REFERENCE",
    )
    assert task["operation"] == "focused"


def test_ol_operation_requires_applicable_configured_binding(package_root: Path, make_workspace) -> None:
    """An OL task fails closed when the testament-appropriate configured binding is absent."""
    root = make_workspace(qualification_status="VALIDATED")
    profile_path = root / "workflows/saw/profile.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["bindings"].pop("ORIGINAL_LANGUAGE_GREEK", None)
    _write_yaml(profile_path, profile)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(ValidationError, match="no configured ORIGINAL_LANGUAGE_GREEK binding"):
        create_act_task(
            config,
            workflow="saw",
            operation="ol",
            output_project_id="usWIP",
            contemporary_source_id="usNIVv2",
            scope_value="MAT 1:1",
            focus="Check the original-language relationship.",
        )


def test_current_operator_surfaces_use_binding_not_schema_jargon(package_root: Path) -> None:
    """Keep machine cardinality syntax out of normal operator-facing guides and templates."""
    current = [
        "README.md", "HELP.md",
        "docs/macos-linux/CHEAT-SHEET.md", "docs/macos-linux/RECOVERY.md", "docs/macos-linux/ERRORS.md",
        "docs/windows/CHEAT-SHEET.md", "docs/windows/RECOVERY.md", "docs/windows/ERRORS.md",
        "docs/BIC-CHEAT-SHEET.md", "docs/SAW-CHEAT-SHEET.md",
        "docs/ARCHITECTURE.md", "docs/BIC-SAW-AUTHORITY-BOUNDARIES.md",
        "workflows/bic/README.md", "workflows/saw/README.md",
    ]
    combined = "\n".join((package_root / rel).read_text(encoding="utf-8") for rel in current)
    assert "exactly one SOURCE" not in combined
    assert "exactly one DONOR" not in combined
    assert "exactly one TARGET" not in combined
    assert "exact GRK/HEB" not in combined
    assert "exact project-bound OL" not in combined
    assert "exact grammar profile" not in combined
    assert "one bound SOURCE resource" in combined
    assert "configured Greek resource" in combined
    assert "selected TARGET grammar profile" in (package_root / "docs/PROJECT-DOCUMENT-GRAMMAR.md").read_text(encoding="utf-8")
    assert "resolved effective VRS" in (package_root / "docs/PROJECT-DOCUMENT-GRAMMAR.md").read_text(encoding="utf-8")
