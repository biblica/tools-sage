"""Local-venv bootstrap and dependency pre-check contracts."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


BOOTSTRAP_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_runtime.py"
SPEC = importlib.util.spec_from_file_location("sage_bootstrap_runtime", BOOTSTRAP_PATH)
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def test_launchers_bootstrap_before_importing_sage_core(package_root: Path) -> None:
    """Verify both launchers validate .venv before any SAGE application import occurs."""
    unix = (package_root / "sage").read_text(encoding="utf-8")
    windows = (package_root / "sage.cmd").read_text(encoding="utf-8")

    assert "bootstrap_runtime.py" in unix
    assert unix.index("bootstrap_runtime.py") < unix.index("-m sage_core.cli")
    assert 'exec "$VENV_PYTHON" -m sage_core.cli' in unix
    assert "bootstrap_runtime.py" in windows
    assert windows.index("bootstrap_runtime.py") < windows.index("-m sage_core.cli")
    assert '"%VENV_PYTHON%" -m sage_core.cli' in windows


def test_bootstrap_module_has_no_sage_core_dependency() -> None:
    """Verify the bootstrap remains standard-library-only and cannot fail on application imports."""
    source = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    assert "import sage_core" not in source
    assert "from sage_core" not in source


def test_requirements_validator_detects_missing_declared_distribution(tmp_path: Path) -> None:
    """Verify missing runtime requirements are detected before application startup."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("definitely-not-installed-sage-bootstrap-package>=1\n", encoding="utf-8")
    ready, details = bootstrap._requirements_status(Path(sys.executable), requirements)
    assert ready is False
    assert any("definitely-not-installed-sage-bootstrap-package" in item for item in details)


def test_first_launch_creates_and_records_local_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a clean first launch creates .venv and records a positively validated runtime state."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pip>=0\n", encoding="utf-8")
    monkeypatch.setenv(bootstrap.AUTO_YES_ENV, "1")

    result = bootstrap.ensure_runtime(tmp_path)

    assert result == 0
    venv_python = bootstrap._venv_python(tmp_path)
    assert venv_python.is_file()
    state = json.loads((tmp_path / "state" / "runtime-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY"
    assert state["python_environment"] == ".venv"
    assert state["requirements_sha256"] == bootstrap._requirements_sha256(requirements)


def test_incomplete_existing_venv_runs_repair_before_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an existing .venv with a missing dependency is repaired instead of launching SAGE."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("openpyxl>=3.1\n", encoding="utf-8")
    venv_python = bootstrap._venv_python(tmp_path)
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "_python_is_supported", lambda python: True)
    monkeypatch.setattr(bootstrap, "_pip_is_available", lambda python: True)
    monkeypatch.setattr(bootstrap, "_ensure_pip", lambda python: True)
    statuses = iter([(False, ["openpyxl (missing)"]), (True, [])])
    monkeypatch.setattr(bootstrap, "_requirements_status", lambda python, req: next(statuses))
    monkeypatch.setattr(bootstrap, "_pip_check", lambda python: (True, ""))
    monkeypatch.setattr(bootstrap, "_confirm", lambda prompt: True)
    repaired: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        bootstrap,
        "_install_requirements",
        lambda python, req: repaired.append((python, req)) is None or True,
    )
    states: list[tuple[Path, Path, Path]] = []
    monkeypatch.setattr(
        bootstrap,
        "_write_runtime_state",
        lambda root, python, req: states.append((root, python, req)),
    )

    assert bootstrap.ensure_runtime(tmp_path) == 0
    assert repaired == [(venv_python, requirements)]
    assert states == [(tmp_path.resolve(), venv_python, requirements)]


def test_operator_can_decline_environment_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify bootstrap never creates .venv without operator permission."""
    (tmp_path / "requirements.txt").write_text("pip>=0\n", encoding="utf-8")
    monkeypatch.delenv(bootstrap.AUTO_YES_ENV, raising=False)
    monkeypatch.setattr(bootstrap, "_confirm", lambda prompt: False)

    assert bootstrap.ensure_runtime(tmp_path) == 2
    assert not (tmp_path / ".venv").exists()


def test_bootstrap_rejects_unsupported_platform_before_environment_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed before dependency setup on an unsupported operating system."""
    (tmp_path / "requirements.txt").write_text("pip>=0\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_platform_status", lambda: (False, "Plan9"))
    assert bootstrap.ensure_runtime(tmp_path) == 2
    assert not (tmp_path / ".venv").exists()


def test_bootstrap_requires_standard_library_venv_before_environment_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed before setup when Python cannot create a standard virtual environment."""
    (tmp_path / "requirements.txt").write_text("pip>=0\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_platform_status", lambda: (True, "Linux"))
    monkeypatch.setattr(bootstrap, "_venv_module_available", lambda: False)
    assert bootstrap.ensure_runtime(tmp_path) == 2
    assert not (tmp_path / ".venv").exists()


def test_runtime_state_records_python_platform_and_dependency_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist enough environment detail to prove the preflight that allowed SAGE to start."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pip>=0\n", encoding="utf-8")
    monkeypatch.setenv(bootstrap.AUTO_YES_ENV, "1")
    assert bootstrap.ensure_runtime(tmp_path) == 0
    state = json.loads((tmp_path / "state" / "runtime-state.json").read_text(encoding="utf-8"))
    assert state["python_minimum"] == "3.10"
    assert state["python_implementation"]
    assert state["platform_system"] in {"Windows", "Darwin", "Linux"}
    assert state["platform_supported"] is True
    assert state["dependency_validation"] == "requirements-specifiers+pip-check"


def test_platform_launchers_enforce_python_minimum_and_delegate_wrappers(package_root: Path) -> None:
    """Cover Windows plus macOS/Linux launcher contracts without executing a foreign OS shell."""
    unix = (package_root / "sage").read_text(encoding="utf-8")
    windows = (package_root / "sage.cmd").read_text(encoding="utf-8")
    assert "sys.version_info >= (3, 10)" in unix
    assert "sys.version_info >= (3,10)" in windows
    for name in ("bic", "saw"):
        text = (package_root / name).read_text(encoding="utf-8")
        assert 'exec "$ROOT_DIR/sage"' in text
    for name in ("bic.cmd", "saw.cmd"):
        text = (package_root / name).read_text(encoding="utf-8")
        assert 'call "%ROOT_DIR%sage.cmd"' in text
        assert '--settings "%SETTINGS_PATH%"' in text


def test_new_rc_version_resets_overlaid_operator_project_state_but_preserves_venv(tmp_path: Path) -> None:
    """Verify a new RC build starts clean even when extracted over an earlier mutable tree."""
    (tmp_path / "VERSION").write_text("0.01-rc7.03\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "keep.txt").write_text("runtime", encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "project-registry.json").write_text('{"old": true}\n', encoding="utf-8")
    (tmp_path / "state" / "resource-mounts.json").write_text('{"old": true}\n', encoding="utf-8")
    for tool in ("bic", "saw"):
        folder = tmp_path / "jobs" / tool
        folder.mkdir(parents=True)
        (folder / "README.md").write_text("seed\n", encoding="utf-8")
    stale_job = tmp_path / "jobs" / "bic" / "BIC_old"
    stale_job.mkdir()
    (stale_job / "job.yml").write_text("old: true\n", encoding="utf-8")
    scripture = tmp_path / "workspace-data" / "scripture-projects"
    scripture.mkdir(parents=True)
    (scripture / "README.md").write_text("seed\n", encoding="utf-8")
    (scripture / "old.sfm").write_text("\\id MAT\n", encoding="utf-8")
    generated = tmp_path / "workspace-data" / "bic"
    generated.mkdir()
    (generated / "old.txt").write_text("old\n", encoding="utf-8")

    receipt = bootstrap._apply_rc_release_boundary(tmp_path)

    assert receipt["version"] == "0.01-rc7.03"
    assert receipt["reset_performed"] is True
    assert (tmp_path / ".venv" / "keep.txt").is_file()
    assert not (tmp_path / "state" / "project-registry.json").exists()
    assert not stale_job.exists()
    assert (tmp_path / "jobs" / "bic" / "README.md").is_file()
    assert (scripture / "README.md").is_file()
    assert not (scripture / "old.sfm").exists()
    assert not generated.exists()
    marker = json.loads((tmp_path / "state" / "release-state.json").read_text(encoding="utf-8"))
    assert marker["policy"] == "RC_CLEAN_START_ON_VERSION_CHANGE"


def test_same_rc_version_preserves_new_operator_state(tmp_path: Path) -> None:
    """Verify clean-start policy runs once per RC version, not on every launch."""
    (tmp_path / "VERSION").write_text("0.01-rc7.03\n", encoding="utf-8")
    first = bootstrap._apply_rc_release_boundary(tmp_path)
    assert first["reset_performed"] is False
    project_state = tmp_path / "state" / "project-inventory.json"
    project_state.write_text('{"schema_version": "1.0", "projects": {}}\n', encoding="utf-8")

    second = bootstrap._apply_rc_release_boundary(tmp_path)

    assert second["reset_performed"] is False
    assert project_state.is_file()
