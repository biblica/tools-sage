"""Atomic state, locking, and CLI initialization tests."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.atomic import atomic_write_json, atomic_write_text
from sage.errors import LockError
from sage.locking import WorkspaceLock
from sage.profiles import load_workflow_profile
from sage.registry import load_ecosystem
from sage.scripture import compile_project


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
    environment["PYTHONPATH"] = str(package_root / "system" / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
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
    assert not (storage_layout(root).state_root / "ecosystem.json").exists()


def test_initialize_ready_with_alpha_restrictions(package_root: Path, make_workspace) -> None:
    """Verify that initialization reports alpha restrictions while remaining ready."""
    root = make_workspace(configured=True, qualification_status="IN_PROGRESS")
    result = run_cli(package_root, root, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "State: READY" in result.stdout
    assert "Capability: RESTRICTED" in result.stdout
    report = storage_layout(root).reports_root / "initialization" / "initialization-report.md"
    assert report.exists()
    assert "BIC" in report.read_text(encoding="utf-8")


def test_initialize_validated_when_workflows_validated(package_root: Path, make_workspace) -> None:
    """Verify that initialization validates after all workflows validate."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    result = run_cli(package_root, root, "--json", "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["state"] == "READY"
    assert payload["capability"] == "VALIDATED"


def test_cli_status_before_initialize_is_not_run(package_root: Path, make_workspace) -> None:
    """Verify that CLI status is NOT_RUN before initialization."""
    root = make_workspace()
    result = run_cli(package_root, root, "workspace", "status")
    assert result.returncode == 0
    assert "State: NOT_RUN" in result.stdout


def test_empty_generated_target_does_not_affect_independent_saw(package_root: Path, make_workspace) -> None:
    """Verify that an empty BIC TARGET does not affect the independent SAW WIP."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    target_file = storage_layout(root).projects_root / "usBOLx1" / "41MAT.SFM"
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





def test_optional_original_language_failure_does_not_block_normal_workflows(package_root: Path, make_workspace) -> None:
    """A broken optional GRK resource limits OL stages without disabling normal SAW/BIC execution."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    (storage_layout(root).projects_root / "GRK" / "41MAT.SFM").write_text("\\id MAT\n\\v 1 verse before chapter\n", encoding="utf-8")
    result = run_cli(package_root, root, "--json", "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["projects"]["GRK"]["status"] == "BLOCKED"
    assert payload["workflows"]["bic"]["resource_state"] == "READY_WITH_LIMITATIONS"
    assert payload["workflows"]["saw"]["resource_state"] == "READY_WITH_LIMITATIONS"
    assert payload["workflows"]["bic"]["execution_available"] is True
    assert payload["workflows"]["saw"]["execution_available"] is True
    assert any("Normal non-OL work remains executable" in item for item in payload["restrictions"])


def test_initialize_uses_configured_runtime_state_root(
    package_root: Path,
    make_workspace,
) -> None:
    """Job/runtime state may be scoped within .system without writing mutable data into Core."""
    root = make_workspace(configured=True)
    settings_path = root / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["paths"]["runtime_state_root"] = "@system/runtime-data"
    for workflow_id in ("bic", "saw"):
        workflow = settings["workflows"][workflow_id]
        workflow["state_root"] = f"@system/runtime-data/{workflow_id}/state"
        workflow["lock_root"] = f"@system/runtime-data/{workflow_id}/locks"
        workflow["transaction_root"] = f"@system/runtime-data/{workflow_id}/transactions"
        workflow["output_root"] = f"@system/runtime-data/{workflow_id}/output"
        if workflow_id == "bic":
            workflow["publication_root"] = (
                "@system/runtime-data/bic/output/published-targets"
            )
    settings_path.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    result = run_cli(package_root, root, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    assert (storage_layout(root).system_root / "runtime-data" / "state" / "ecosystem.json").exists()
    assert (storage_layout(root).reports_root / "initialization" / "initialization-report.md").exists()
    assert not (storage_layout(root).state_root / "ecosystem.json").exists()
