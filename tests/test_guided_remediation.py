"""Guided operator-input remediation regressions."""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage_core.cli import _init_input_requirements, _resolve_grammar_override_input
from sage_core.errors import ConfigurationError
from sage_core.init_remediation import run_targeted_init_remediation
from sage_core.operator_overrides import operator_override_path
from sage_core.references import parse_scope
from sage_core.registry import load_ecosystem
from sage_core.reset_state import reset_project_state
from sage_core.vrs import VerseRef


def run_cli(
    package_root: Path,
    workspace: Path,
    *arguments: str,
    input_text: str | None = None,
    force_interactive: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the SAGE CLI in an isolated subprocess for this test."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root / "core")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if force_interactive:
        environment["SAGE_FORCE_INTERACTIVE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage_core.cli",
            "--settings",
            str(workspace / "ecosystem.yml"),
            *arguments,
        ],
        input=input_text,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=40,
    )


def test_chapter_range_scope_is_supported() -> None:
    """Verify that chapter range scope is supported."""
    scope = parse_scope("JHN 10-11")
    assert scope.label() == "JHN 10-11"
    assert scope.contains(VerseRef("JHN", 10, 1))
    assert scope.contains(VerseRef("JHN", 11, 57))
    assert not scope.contains(VerseRef("JHN", 12, 1))


def test_unknown_book_returns_ranked_jhn_suggestion(package_root: Path, make_workspace) -> None:
    """Verify that unknown book returns ranked JHN suggestion."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "saw",
        "--operation",
        "qa",
        "--scope",
        "JUN 10-11",
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "INPUT_REQUIRED"
    assert payload["reason_code"] == "UNKNOWN_BOOK_CODE"
    assert payload["received"] == "JUN"
    assert payload["suggestions"][0]["value"] == "JHN"
    assert payload["suggestions"][0]["confidence"] == "HIGH"



def test_saw_shortcut_route_returns_ranked_jhn_suggestion(package_root: Path, make_workspace) -> None:
    """Verify the SAW wrapper's canonical shortcut route returns the ranked JHN suggestion."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root,
        root,
        "--json",
        "shortcut",
        "--workflow",
        "saw",
        "qa",
        "--",
        "--output-project",
        "usBOLx1",
        "--contemporary-source",
        "usNIVv2",
        "--scope",
        "JUN 10-11",
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "INPUT_REQUIRED"
    assert payload["reason_code"] == "UNKNOWN_BOOK_CODE"
    assert payload["suggestions"][0]["value"] == "JHN"


def test_operator_cancellation_returns_abandoned(package_root: Path, make_workspace) -> None:
    """Verify that operator cancellation returns abandoned."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root,
        root,
        "workflow",
        "plan",
        "--workflow",
        "saw",
        "--operation",
        "qa",
        "--scope",
        "JUN 10-11",
        input_text="5\n",
        force_interactive=True,
    )
    assert result.returncode == 2
    assert "Result: ABANDONED" in result.stderr
    assert "Reason code: OPERATOR_CANCELLED" in result.stderr

def test_unknown_option_returns_canonical_alternative(package_root: Path, make_workspace) -> None:
    """Verify that unknown option returns canonical alternative."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "status",
        "--workflw",
        "bic",
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "INPUT_REQUIRED"
    assert payload["reason_code"] == "UNKNOWN_COMMAND_OPTION"
    assert payload["suggestions"][0]["value"] == "--workflow"


def test_unknown_project_returns_ranked_registered_alternative(package_root: Path, make_workspace) -> None:
    """Verify that unknown project returns ranked registered alternative."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root,
        root,
        "--json",
        "task",
        "create",
        "--workflow",
        "saw",
        "--operation",
        "qa",
        "--output-project",
        "usBOLL",
        "--contemporary-source",
        "usNIVv2",
        "--scope",
        "MAT 1:1",
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "INPUT_REQUIRED"
    assert payload["reason_code"] == "UNKNOWN_PROJECT_ID"
    assert payload["suggestions"][0]["value"] == "usBOLx1"


def test_noninteractive_initialize_requests_input_instead_of_blocking(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that non-interactive `initialize` requests input instead of blocking."""
    root = make_workspace(configured=False)
    result = run_cli(package_root, root, "--json", "workspace", "initialize")
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "INPUT_REQUIRED"
    assert payload["reason_code"] == "INIT_INPUT_REQUIRED"
    assert payload["received"]["configured"] is False
    assert not (root / "workspace-data" / "sage" / "state" / "ecosystem.json").exists()


def test_interactive_initialize_persists_governed_sidecar_and_revalidates(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that interactive initialisation persists its sidecar and revalidates."""
    root = make_workspace(configured=False)
    source = root / "ecosystem.yml"
    before = source.read_bytes()
    result = run_cli(
        package_root,
        root,
        "workspace",
        "initialize",
        input_text="\n",
        force_interactive=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert source.read_bytes() == before
    sidecar = operator_override_path(source)
    assert sidecar.is_file()
    effective = load_ecosystem(source)
    assert effective.configured is True
    assert "State: READY" in result.stdout


def test_targeted_init_can_enable_selected_project_without_rewriting_source(
    make_workspace,
) -> None:
    """Verify that targeted INIT can enable selected project without rewriting source."""
    root = make_workspace(configured=False)
    source = root / "ecosystem.yml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    data["projects"]["idKKHv0"]["enabled"] = False
    source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    before = source.read_bytes()
    config = load_ecosystem(source)
    result = run_targeted_init_remediation(
        config,
        project_ids=["idKKHv0"],
        input_stream=io.StringIO("\n\n"),
        output_stream=io.StringIO(),
    )
    assert result["changed"] is True
    assert source.read_bytes() == before
    effective = load_ecosystem(source)
    assert effective.configured is True
    assert effective.project("idKKHv0").enabled is True
    assert effective.operator_overrides_path is not None
    assert any(
        row["setting"] == "projects.idKKHv0.enabled"
        for row in effective.operator_resolutions
    )



def test_init_requirements_are_limited_to_requested_projects(make_workspace, monkeypatch) -> None:
    """Verify that INIT requirements are limited to requested projects."""
    root = make_workspace(configured=True)
    monkeypatch.setattr(
        "sage_core.cli.resolve_auto_settings",
        lambda config: [
            {
                "project_id": "idKKHv0",
                "setting": "projects.idKKHv0.versification.custom_file",
                "resolution_status": "OPERATOR_REVIEW_REQUIRED",
                "resolved_summary": "custom.vrs",
            },
            {
                "project_id": "usNIVv2",
                "setting": "projects.usNIVv2.versification.custom_file",
                "resolution_status": "OPERATOR_REVIEW_REQUIRED",
                "resolved_summary": "custom.vrs",
            },
        ],
    )
    requirements = _init_input_requirements(
        load_ecosystem(root / "ecosystem.yml"),
        project_ids=["usNIVv2"],
    )
    assert requirements["project_ids"] == ["usNIVv2"]
    assert {row["project_id"] for row in requirements["unresolved_auto_settings"]} == {"usNIVv2"}

def test_reset_preserves_internal_scripture_seed_but_removes_generated_payload(make_workspace) -> None:
    """Runtime reset keeps the shipped empty-directory seed while deleting generated Scripture data."""
    root = make_workspace(configured=False)
    seed = root / "workspace-data" / "scripture-projects" / "README.md"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("# Internal Scripture workspace\n", encoding="utf-8")
    generated = seed.parent / "generated" / "41MAT.SFM"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("\\id MAT\n", encoding="utf-8")

    reset_project_state(load_ecosystem(root / "ecosystem.yml"))

    assert seed.read_text(encoding="utf-8") == "# Internal Scripture workspace\n"
    assert not generated.exists()


def test_reset_preserves_governed_operator_overrides(make_workspace) -> None:
    """Verify that reset preserves governed operator overrides."""
    root = make_workspace(configured=False)
    source = root / "ecosystem.yml"
    config = load_ecosystem(source)
    run_targeted_init_remediation(
        config,
        project_ids=[],
        input_stream=io.StringIO("\n"),
        output_stream=io.StringIO(),
    )
    effective = load_ecosystem(source)
    sidecar = effective.operator_overrides_path
    assert sidecar is not None and sidecar.is_file()
    reset_project_state(effective)
    assert sidecar.is_file()


def test_stale_override_requires_guided_regeneration(make_workspace) -> None:
    """Verify that stale override requires guided regeneration."""
    root = make_workspace(configured=False)
    source = root / "ecosystem.yml"
    run_targeted_init_remediation(
        load_ecosystem(source),
        project_ids=[],
        input_stream=io.StringIO("\n"),
        output_stream=io.StringIO(),
    )
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        load_ecosystem(source)
    assert caught.value.code == "OPERATOR_OVERRIDE_STALE"


def test_provisional_grammar_does_not_prompt_or_gate_task_creation(make_workspace, monkeypatch) -> None:
    """Verify provisional grammar continues without a mandatory decision ID."""
    root = make_workspace(configured=True)
    profile_path = root / "profiles" / "languages" / "en" / "bol-target.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["profile"]["status"] = "PROJECT_REVIEW_REQUIRED"
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    args = argparse.Namespace(
        command="task",
        task_command="create",
        workflow_id="saw",
        operation="qa",
        output_project="usBOLx1",
        contemporary_source="usNIVv2",
        grammar_override_id=None,
        _guided_interactive=True,
        _input_corrections=[],
        _canonical_argv=["task", "create"],
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    _resolve_grammar_override_input(args, config)
    assert args.grammar_override_id is None
    assert args._input_corrections == []
    assert stderr.getvalue() == ""
