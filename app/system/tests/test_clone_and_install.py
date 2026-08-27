"""Cross-platform clone, localdata, and host-binding contracts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


CLONE_PATH = Path(__file__).resolve().parents[2] / "system" / "tools" / "clone_and_install.py"
SPEC = importlib.util.spec_from_file_location("sage_clone_and_install", CLONE_PATH)
assert SPEC is not None and SPEC.loader is not None
clone = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clone)


def test_clone_menu_has_exactly_two_canonical_modes() -> None:
    """Keep numeric Operator choices and automation names on one stable contract."""
    assert clone._normalise_mode("1") == clone.VANILLA_MODE
    assert clone._normalise_mode("clean") == clone.VANILLA_MODE
    assert clone._normalise_mode("vanilla") == clone.VANILLA_MODE
    assert clone._normalise_mode("2") == clone.NEW_HOST_MODE
    assert clone._normalise_mode("new-host") == clone.NEW_HOST_MODE
    assert clone._normalise_mode("3") is None


def test_new_host_projects_root_requires_an_existing_absolute_folder(tmp_path: Path) -> None:
    """Reject ambiguous host paths before cloning or changing SAGE state."""
    projects = tmp_path / "Paratext Projects"
    projects.mkdir()
    assert clone._absolute_existing_directory(f'"{projects}"', "Paratext Projects folder") == projects.resolve()
    with pytest.raises(ValueError, match="absolute"):
        clone._absolute_existing_directory("relative/projects", "Paratext Projects folder")
    with pytest.raises(ValueError, match="not found"):
        clone._absolute_existing_directory(str(tmp_path / "missing"), "Paratext Projects folder")


def test_data_home_defaults_to_bundle_and_rejects_app_overlap(tmp_path: Path) -> None:
    """Use bundle localdata by default and reject data roots inside the app."""
    root = tmp_path / "SAGE"
    root.mkdir()
    assert clone._data_home(root, None) == (root / "localdata").resolve()
    custom = tmp_path / "Operator Data" / "localdata"
    assert clone._data_home(root, str(custom)) == custom.resolve()
    with pytest.raises(ValueError, match="outside"):
        clone._data_home(root, str(root / "app" / "localdata"))
    with pytest.raises(ValueError, match="absolute"):
        clone._data_home(root, "relative/localdata")


def test_clone_bootstrap_uses_selected_data_home_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delegate runtime setup to bootstrap and pass localdata without deleting local content."""
    root = tmp_path / "SAGE"
    root.mkdir()
    data_home = tmp_path / "Persistent Data" / "localdata"
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Capture one bootstrap subprocess call without changing the host."""
        calls.append((args, kwargs["cwd"], kwargs["env"]))  # type: ignore[arg-type]
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(clone.subprocess, "run", run)
    assert clone._run_bootstrap(root, data_home) is True
    args, cwd, environment = calls[0]
    assert args == [
        str(root / "app" / ("sage-python.cmd" if sys.platform == "win32" else "sage-python")),
        "-c",
        "pass",
    ]
    assert cwd == root / "app"
    assert "SAGE_BOOTSTRAP_AUTO_YES" not in environment
    assert environment[clone.DATA_HOME_ENV] == str(data_home)
    assert "PRESERVE_JOBS_ENV" not in clone.__dict__
    assert "_clean_cloned_workspace" not in clone.__dict__


def test_clone_install_receipt_records_external_data_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Record the selected mode and non-destructive external-data policy in localdata."""
    root = tmp_path / "SAGE"
    (root / "app").mkdir(parents=True)
    (root / "app" / "VERSION").write_text("0.01beta\n", encoding="utf-8")
    data_home = tmp_path / "localdata"
    projects = tmp_path / "Paratext Projects"
    projects.mkdir()
    monkeypatch.setattr(clone, "_venv_python", lambda _data: tmp_path / "missing-python")
    receipt = clone._write_install_receipt(
        root,
        data_home,
        success=True,
        mode=clone.NEW_HOST_MODE,
        projects_root=projects,
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["status"] == "READY"
    assert payload["mode"] == "new-host"
    assert payload["data_home"] == str(data_home)
    assert payload["paratext_projects_root"] == str(projects)
    assert payload["operator_data_policy"] == "PRESERVE_EXISTING_RECOGNIZED_LOCALDATA"
    assert receipt == data_home / ".system" / "state" / "installation.json"


def test_clone_wrappers_are_portable_and_windows_uses_crlf(package_root: Path) -> None:
    """Route clone helpers through SAGE-managed Python on Unix and Windows."""
    unix = (package_root / "system" / "tools" / "clone_and_install.sh").read_text(encoding="utf-8")
    windows_path = package_root / "system" / "tools" / "clone_and_install.cmd"
    windows = windows_path.read_text(encoding="utf-8")
    payload = windows_path.read_bytes()
    assert 'exec "$APP_ROOT/sage-python" "$TOOLS_DIR/clone_and_install.py" "$@"' in unix
    assert "python3" not in unix and "System Python" not in unix
    assert 'call "%APP_ROOT%\\sage-python.cmd" "%TOOLS_DIR%clone_and_install.py" %*' in windows
    assert "py -3" not in windows and "System Python" not in windows
    assert b"\r\n" in payload
    assert b"\n" not in payload.replace(b"\r\n", b"")


def test_clone_tool_does_not_duplicate_dependency_install_policy() -> None:
    """Prevent the deployment helper from drifting into a second package manager."""
    source = CLONE_PATH.read_text(encoding="utf-8")
    assert "pip install --upgrade" not in source
    assert "requirements-dev.txt" not in source
