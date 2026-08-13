"""Atomic state, locking, and CLI initialisation tests."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage_core.atomic import atomic_write_json, atomic_write_text
from sage_core.errors import LockError
from sage_core.locking import WorkspaceLock
from sage_core.profiles import load_workflow_profile
from sage_core.registry import load_ecosystem
from sage_core.scripture import compile_project


def test_atomic_write_text_and_json(tmp_path: Path) -> None:
    """Verify that atomic write text and JSON."""
    text_path = tmp_path / "state" / "value.txt"
    json_path = tmp_path / "state" / "value.json"
    atomic_write_text(text_path, "complete\n")
    atomic_write_json(json_path, {"state": "COMPLETE"})
    assert text_path.read_text(encoding="utf-8") == "complete\n"
    assert json.loads(json_path.read_text(encoding="utf-8"))["state"] == "COMPLETE"
    assert not list(text_path.parent.glob("*.tmp"))


def test_lock_contention_is_blocked(tmp_path: Path) -> None:
    """Verify that lock contention is blocked."""
    lock_path = tmp_path / "workspace.lock"
    first = WorkspaceLock(lock_path, "FIRST").acquire()
    try:
        with pytest.raises(LockError, match="locked"):
            WorkspaceLock(lock_path, "SECOND").acquire()
    finally:
        first.release()


def test_same_host_stale_lock_can_be_recovered(tmp_path: Path) -> None:
    """Verify that same host stale lock can be recovered."""
    lock_path = tmp_path / "workspace.lock"
    lock_path.mkdir()
    (lock_path / "owner.json").write_text(
        json.dumps(
            {
                "pid": 99999999,
                "host": socket.gethostname(),
                "operation": "STALE",
            }
        ),
        encoding="utf-8",
    )
    lock = WorkspaceLock(lock_path, "RECOVER", break_stale=True).acquire()
    assert lock.acquired
    lock.release()


def run_cli(package_root: Path, workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the SAGE CLI in an isolated subprocess for this test."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root / "core")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage_core.cli",
            "--settings",
            str(workspace / "ecosystem.yml"),
            *arguments,
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=30,
    )


def test_initialize_requests_input_for_unconfigured_workspace(package_root: Path, make_workspace) -> None:
    """Verify that `initialize` requests input for an unconfigured workspace."""
    root = make_workspace(configured=False)
    result = run_cli(package_root, root, "--json", "workspace", "initialize")
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "INPUT_REQUIRED"
    assert payload["reason_code"] == "INIT_INPUT_REQUIRED"
    assert not (root / "workspace-data" / "sage" / "state" / "ecosystem.json").exists()


def test_initialize_ready_with_release_candidate_restrictions(package_root: Path, make_workspace) -> None:
    """Verify that initialisation reports release-candidate restrictions while remaining ready."""
    root = make_workspace(configured=True, qualification_status="IN_PROGRESS")
    result = run_cli(package_root, root, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "State: READY" in result.stdout
    assert "Capability: RESTRICTED" in result.stdout
    report = root / "workspace-data" / "sage" / "output" / "initialization-report.md"
    assert report.exists()
    assert "BIC" in report.read_text(encoding="utf-8")


def test_initialize_validated_when_workflows_validated(package_root: Path, make_workspace) -> None:
    """Verify that initialisation validates after all workflows validate."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    result = run_cli(package_root, root, "--json", "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["state"] == "READY"
    assert payload["capability"] == "VALIDATED"


def test_cli_status_before_initialize_is_not_run(package_root: Path, make_workspace) -> None:
    """Verify that CLI status is NOT_RUN before initialisation."""
    root = make_workspace()
    result = run_cli(package_root, root, "workspace", "status")
    assert result.returncode == 0
    assert "State: NOT_RUN" in result.stdout


def test_empty_generated_target_does_not_affect_independent_saw(package_root: Path, make_workspace) -> None:
    """Verify that an empty BIC TARGET does not affect the independent SAW WIP."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    target_file = root / "projects" / "usBOLx1" / "41MAT.SFM"
    target_file.unlink()
    result = run_cli(package_root, root, "--json", "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["state"] == "READY"
    assert payload["capability"] == "VALIDATED"
    assert payload["projects"]["usBOLx1"]["status"] == "NOT_GENERATED"
    assert payload["workflows"]["bic"]["resource_state"] == "READY"
    assert payload["workflows"]["bic"]["execution_available"] is True
    assert payload["workflows"]["saw"]["resource_state"] == "READY"
    assert payload["workflows"]["saw"]["execution_available"] is True



def test_initialize_uses_configured_workspace_data_root(
    package_root: Path,
    make_workspace,
) -> None:
    """Ecosystem state, lock, and reports must follow paths.workspace_data_root."""
    root = make_workspace(configured=True)
    settings_path = root / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["paths"]["workspace_data_root"] = "runtime-data"
    for workflow_id in ("bic", "saw"):
        workflow = settings["workflows"][workflow_id]
        workflow["state_root"] = f"runtime-data/{workflow_id}/state"
        workflow["lock_root"] = f"runtime-data/{workflow_id}/locks"
        workflow["transaction_root"] = f"runtime-data/{workflow_id}/transactions"
        workflow["output_root"] = f"runtime-data/{workflow_id}/output"
        if workflow_id == "bic":
            workflow["publication_root"] = (
                "runtime-data/bic/output/published-targets"
            )
    settings_path.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    result = run_cli(package_root, root, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    assert (root / "runtime-data" / "sage" / "state" / "ecosystem.json").exists()
    assert (root / "runtime-data" / "sage" / "output" / "initialization-report.md").exists()
    assert not (root / "workspace-data" / "sage" / "state" / "ecosystem.json").exists()
