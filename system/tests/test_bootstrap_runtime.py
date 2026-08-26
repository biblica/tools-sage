"""Deterministic external-runtime bootstrap and dependency pre-check contracts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


BOOTSTRAP_PATH = Path(__file__).resolve().parents[2] / "system" / "tools" / "bootstrap_runtime.py"
SPEC = importlib.util.spec_from_file_location("sage_bootstrap_runtime", BOOTSTRAP_PATH)
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def _root(tmp_path: Path, requirements: str = "") -> Path:
    """Create the minimum immutable Core tree needed by bootstrap tests."""
    root = tmp_path / "SAGE"
    (root / "system" / "tools").mkdir(parents=True)
    (root / "system" / "requirements.txt").write_text(requirements, encoding="utf-8")
    (root / "VERSION").write_text("0.01beta\n", encoding="utf-8")
    return root


def test_launchers_delegate_to_bootstrap_before_application_import(package_root: Path) -> None:
    """Launchers must delegate environment creation and application launch to bootstrap."""
    unix = (package_root / "system" / "bin" / "sage").read_text(encoding="utf-8")
    windows = (package_root / "system/bin/sage.cmd").read_text(encoding="utf-8")

    assert "bootstrap_runtime.py" in unix
    assert 'exec "$BOOTSTRAP_PYTHON" "$BOOTSTRAP_SCRIPT"' in unix
    assert "--launch" in unix
    assert "-m sage.cli" not in unix
    assert "bootstrap_runtime.py" in windows
    assert '"%BOOTSTRAP_SCRIPT%"' in windows
    assert "--launch" in windows
    assert "-m sage.cli" not in windows


def test_bootstrap_module_has_no_sage_package_import() -> None:
    """Bootstrap may load the storage file directly but must not import the SAGE package."""
    source = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    assert "import sage" not in source
    assert "from sage" not in source
    assert "spec_from_file_location" in source


def test_runtime_manifests_require_exact_pins(tmp_path: Path) -> None:
    """Ranges and remote requirements are rejected before machine changes occur."""
    manifest = tmp_path / "requirements.txt"
    manifest.write_text("PyYAML>=6\nopenpyxl==3.1.5\n", encoding="utf-8")
    errors = bootstrap._locked_requirements_errors(manifest)
    assert len(errors) == 1
    assert "not exactly pinned" in errors[0]


def test_requirements_validator_detects_missing_declared_distribution(tmp_path: Path) -> None:
    """Missing runtime requirements are detected before application startup."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("definitely-not-installed-sage-bootstrap-package==1.0\n", encoding="utf-8")
    ready, details = bootstrap._requirements_status(Path(sys.executable), requirements)
    assert ready is False
    assert any("definitely-not-installed-sage-bootstrap-package" in item for item in details)


def test_first_launch_creates_external_managed_venv_and_receipt(tmp_path: Path) -> None:
    """A clean first launch automatically creates the sibling SAGEdata runtime."""
    root = _root(tmp_path)

    result = bootstrap.ensure_runtime(root)

    assert result == 0
    layout = bootstrap.storage_layout(root)
    venv_python = bootstrap._venv_python(root)
    assert layout.data_root == tmp_path / "SAGEdata"
    assert venv_python.is_file()
    assert not (root / ".venv").exists()
    state = json.loads((layout.state_root / "runtime-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY"
    assert state["python_environment"] == "SAGEdata/.system/runtime/venv"
    assert state["dependency_validation"] == "exact-pins+only-binary+no-deps+pip-check"
    assert state["requirements_sha256"] == bootstrap._requirements_sha256(root / "system" / "requirements.txt")


def test_incomplete_existing_venv_runs_automatic_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An incomplete managed environment is repaired without an interactive decision."""
    root = _root(tmp_path, "openpyxl==3.1.5\n")
    venv_python = bootstrap._venv_python(root)
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "_python_is_supported", lambda python: True)
    monkeypatch.setattr(bootstrap, "_pip_is_available", lambda python: True)
    statuses = iter([(False, ["openpyxl (missing)"]), (True, [])])
    monkeypatch.setattr(bootstrap, "_requirements_status", lambda python, req: next(statuses))
    monkeypatch.setattr(bootstrap, "_pip_check", lambda python: (True, ""))
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
    monkeypatch.setattr(bootstrap, "_write_host_capability", lambda root, capability=None: bootstrap.storage_layout(root).state_root / "host-capability.json")
    monkeypatch.setattr(bootstrap, "_python_version", lambda python: "3.13.0")

    assert bootstrap.ensure_runtime(root) == 0
    assert repaired == [(venv_python, root / "system" / "requirements.txt")]
    assert states == [(root.resolve(), venv_python, root / "system" / "requirements.txt")]


def test_bootstrap_rejects_unpinned_manifest_before_environment_creation(tmp_path: Path) -> None:
    """A mutable dependency range cannot create or modify the managed runtime."""
    root = _root(tmp_path, "PyYAML>=6\n")
    assert bootstrap.ensure_runtime(root) == 2
    assert not bootstrap.storage_layout(root).venv_root.exists()


def test_bootstrap_rejects_unsupported_platform_before_environment_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed before dependency setup on an unsupported operating system."""
    root = _root(tmp_path)
    monkeypatch.setattr(bootstrap, "_platform_status", lambda: (False, "Plan9"))
    assert bootstrap.ensure_runtime(root) == 2
    assert not bootstrap.storage_layout(root).venv_root.exists()


def test_bootstrap_requires_standard_library_venv_before_environment_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed when Python cannot create a standard virtual environment."""
    root = _root(tmp_path)
    monkeypatch.setattr(bootstrap, "_platform_status", lambda: (True, "Linux"))
    monkeypatch.setattr(bootstrap, "_venv_module_available", lambda: False)
    assert bootstrap.ensure_runtime(root) == 2
    assert not bootstrap.storage_layout(root).venv_root.exists()


def test_runtime_state_records_python_platform_and_dependency_contract(tmp_path: Path) -> None:
    """Persist enough detail to prove the deterministic preflight that allowed startup."""
    root = _root(tmp_path)
    assert bootstrap.ensure_runtime(root) == 0
    state = json.loads((bootstrap.storage_layout(root).state_root / "runtime-state.json").read_text(encoding="utf-8"))
    assert state["python_minimum"] == "3.10"
    assert state["python_implementation"]
    assert state["platform_system"] in {"Windows", "Darwin", "Linux"}
    assert state["platform_supported"] is True
    assert state["dependency_validation"] == "exact-pins+only-binary+no-deps+pip-check"


def test_platform_launchers_enforce_python_minimum_and_delegate_wrappers(package_root: Path) -> None:
    """Cover Windows plus macOS/Linux launcher contracts without executing a foreign OS shell."""
    unix = (package_root / "system" / "bin" / "sage").read_text(encoding="utf-8")
    windows = (package_root / "system/bin/sage.cmd").read_text(encoding="utf-8")
    assert "sys.version_info >= (3, 10)" in unix
    assert "sys.version_info >= (3,10)" in windows
    for name in ("bic", "saw"):
        text = (package_root / "system" / "bin" / name).read_text(encoding="utf-8")
        assert 'exec "$BIN_DIR/sage"' in text
    for name in ("system/bin/bic.cmd", "system/bin/saw.cmd"):
        text = (package_root / name).read_text(encoding="utf-8")
        assert 'call "%BIN_DIR%sage.cmd"' in text
        assert 'launcher-shortcut --workflow ' in text
        assert '-- %*' in text
        assert 'SHIFT' not in text.upper()


def test_prerelease_version_change_preserves_all_persistent_sagedata(tmp_path: Path) -> None:
    """Changing Beta versions records provenance but never deletes operator/runtime state."""
    root = _root(tmp_path)
    first = bootstrap._apply_pre_release_boundary(root)
    assert first["reset_performed"] is False
    layout = bootstrap.storage_layout(root, create=True)
    project = layout.projects_root / "usTARGET" / "41MAT.SFM"
    project.parent.mkdir(parents=True)
    project.write_text("\\id MAT\n", encoding="utf-8")
    job = layout.jobs_root / "saw" / "SAW_example" / "job.yml"
    job.parent.mkdir(parents=True)
    job.write_text("id: SAW_example\n", encoding="utf-8")
    report = layout.reports_root / "report.md"
    report.write_text("report\n", encoding="utf-8")
    runtime = layout.venv_root / "keep.txt"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("runtime\n", encoding="utf-8")
    local_state = layout.state_root / "project-inventory.json"
    local_state.write_text('{"projects": {}}\n', encoding="utf-8")
    (root / "VERSION").write_text("0.01beta2\n", encoding="utf-8")

    receipt = bootstrap._apply_pre_release_boundary(root)

    assert receipt["version_changed"] is True
    assert receipt["reset_performed"] is False
    assert receipt["policy"] == "PRERELEASE_STATE_PRESERVED_ON_VERSION_CHANGE"
    assert project.is_file() and job.is_file() and report.is_file() and runtime.is_file() and local_state.is_file()


def test_same_beta_version_preserves_new_operator_state(tmp_path: Path) -> None:
    """Every launch preserves current-version operator state."""
    root = _root(tmp_path)
    first = bootstrap._apply_pre_release_boundary(root)
    assert first["reset_performed"] is False
    project_state = bootstrap.storage_layout(root, create=True).state_root / "project-inventory.json"
    project_state.write_text('{"schema_version": "1.0", "projects": {}}\n', encoding="utf-8")

    second = bootstrap._apply_pre_release_boundary(root)

    assert second["reset_performed"] is False
    assert project_state.is_file()


def test_bootstrap_main_accepts_tui_dependency_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Launcher-selected TUI profile reaches runtime validation without changing base defaults."""
    root = _root(tmp_path)
    calls: list[tuple[Path, str]] = []

    def fake_ensure(value: Path, *, profile: str = "base") -> int:
        """Record one deterministic bootstrap request without creating a real runtime."""
        calls.append((value.resolve(), profile))
        return 0

    monkeypatch.setattr(bootstrap, "ensure_runtime", fake_ensure)

    assert bootstrap.main([str(root), "tui"]) == 0
    assert calls == [(root.resolve(), "tui")]


def test_windows_launcher_passes_root_without_trailing_backslash_and_no_core_venv(package_root: Path) -> None:
    """Prevent Windows argv corruption and any return to an in-Core virtual environment."""
    windows = (package_root / "system" / "bin" / "sage.cmd").read_text(encoding="utf-8")
    assert 'do set "ROOT_DIR=%%~fI"' in windows
    assert 'do set "ROOT_DIR=%%~fI\\"' not in windows
    assert 'set "BOOTSTRAP_SCRIPT=%ROOT_DIR%\\system\\tools\\bootstrap_runtime.py"' in windows
    assert "VENV_PYTHON" not in windows
    assert "%ROOT_DIR%\\.venv" not in windows


def test_bootstrap_recovers_valid_cwd_from_malformed_launcher_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Recover from the legacy Windows quoted-root defect only when cwd proves a valid Core root."""
    root = _root(tmp_path)
    (root / "system" / "tools" / "bootstrap_runtime.py").write_text("# anchor\n", encoding="utf-8")
    malformed = tmp_path / 'SAGE" base'
    monkeypatch.chdir(root)

    assert bootstrap._resolve_cli_root(malformed) == root.resolve()


def test_host_capability_selects_basic_when_available_ram_is_below_4_gib(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select BASIC when available RAM is below the governed four-GiB threshold."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 3 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 16)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "BASIC"
    assert row["detection_status"] == "READY"
    assert row["default_hardening_workers"] == 2
    assert "AVAILABLE_RAM_BELOW_4_GIB" in row["reasons"]


def test_host_capability_selects_basic_when_logical_threads_are_below_8(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select BASIC when logical CPU capacity is below the governed eight-thread threshold."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 8 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 4)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "BASIC"
    assert row["default_hardening_workers"] == 2
    assert "LOGICAL_CPU_THREADS_BELOW_8" in row["reasons"]


def test_host_capability_selects_standard_at_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select STANDARD when RAM and CPU meet the governed thresholds."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 4 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 8)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "STANDARD"
    assert row["detection_status"] == "READY"
    assert row["default_hardening_workers"] == 4
    assert row["reasons"] == []


def test_host_capability_detection_failure_falls_safely_to_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail safely to BASIC when a required host-capability measurement is unavailable."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: None)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 32)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "BASIC"
    assert row["detection_status"] == "FAILED_SAFE"
    assert row["default_hardening_workers"] == 2
    assert row["reasons"] == ["HARDWARE_DETECTION_FAILED"]


def test_hardening_worker_override_remains_bounded() -> None:
    """Keep explicit hardening-worker overrides within the supported one-to-eight range."""
    basic = {"default_hardening_workers": 2}
    standard = {"default_hardening_workers": 4}
    assert bootstrap.hardening_worker_cap(basic, {}) == (2, "HOST_PROFILE_DEFAULT")
    assert bootstrap.hardening_worker_cap(standard, {}) == (4, "HOST_PROFILE_DEFAULT")
    assert bootstrap.hardening_worker_cap(basic, {"SAGE_HARDENING_WORKERS": "99"}) == (8, "ENV_OVERRIDE")
    assert bootstrap.hardening_worker_cap(standard, {"SAGE_HARDENING_WORKERS": "0"}) == (1, "ENV_OVERRIDE")
    assert bootstrap.hardening_worker_cap(standard, {"SAGE_HARDENING_WORKERS": "bad"}) == (4, "INVALID_OVERRIDE_FALLBACK")


def test_host_capability_receipt_is_machine_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup capability state is written only beneath hidden SAGEdata machine state."""
    root = _root(tmp_path)
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 8 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 8)
    target = bootstrap._write_host_capability(root)
    assert target == tmp_path / "SAGEdata" / ".system" / "state" / "host-capability.json"
    row = json.loads(target.read_text(encoding="utf-8"))
    assert row["profile"] == "STANDARD"
    assert row["default_hardening_workers"] == 4
    assert row["detected_utc"]
