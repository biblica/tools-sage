"""Deterministic external-runtime bootstrap and dependency pre-check contracts."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


BOOTSTRAP_PATH = Path(__file__).resolve().parents[2] / "system" / "tools" / "bootstrap_runtime.py"
POSIX_RUNTIME_BOOTSTRAP = BOOTSTRAP_PATH.with_name("bootstrap_python.sh")
WINDOWS_RUNTIME_BOOTSTRAP = BOOTSTRAP_PATH.with_name("bootstrap_python.ps1")
RUNTIME_MANIFEST = BOOTSTRAP_PATH.parents[1] / "config" / "python-runtime.json"
SPEC = importlib.util.spec_from_file_location("sage_bootstrap_runtime", BOOTSTRAP_PATH)
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def _root(tmp_path: Path, requirements: str = "") -> Path:
    """Create the minimum immutable Core tree needed by bootstrap tests."""
    root = tmp_path / "SAGE" / "app"
    (root / "system" / "tools").mkdir(parents=True)
    (root / "system" / "requirements.txt").write_text(requirements, encoding="utf-8")
    (root / "VERSION").write_text("0.01beta\n", encoding="utf-8")
    return root


def test_launchers_delegate_to_bootstrap_before_application_import(package_root: Path) -> None:
    """Launchers must delegate environment creation and application launch to bootstrap."""
    unix = (package_root / "system" / "bin" / "sage").read_text(encoding="utf-8")
    windows = (package_root / "system/bin/sage.cmd").read_text(encoding="utf-8")

    assert "bootstrap_python.sh" in unix
    assert 'exec /bin/sh "$RUNTIME_BOOTSTRAP"' in unix
    assert " launch " in unix
    assert "-m sage.cli" not in unix
    assert "bootstrap_python.ps1" in windows
    assert "powershell.exe" in windows
    assert '"launch"' in windows
    assert "-m sage.cli" not in windows
    combined = unix + windows
    for forbidden in ("find_python", "where py", "where python", "Install Python 3.10"):
        assert forbidden not in combined
    powershell = WINDOWS_RUNTIME_BOOTSTRAP.read_text(encoding="utf-8")
    assert "PROCESSOR_ARCHITEW6432" in powershell
    assert "PROCESSOR_ARCHITECTURE" in powershell
    assert "No approved SAGE Python runtime is pinned for Windows/" in powershell


def test_governed_python_runtime_manifest_pins_every_supported_target() -> None:
    """Pin one exact CPython patch archive and SHA-256 for every supported deployment target."""
    manifest = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["provider"] == "astral-sh/python-build-standalone"
    assert manifest["provider_release"] == "20260825"
    assert manifest["python_version"] == "3.12.14"
    assert manifest["host_python_minimum_version"] == "3.12.4"
    assert manifest["archive_flavor"] == "install_only_stripped"
    assert set(manifest["artifacts"]) == {
        "macos-arm64",
        "macos-x86_64",
        "linux-arm64",
        "linux-x86_64",
        "windows-x86_64",
    }
    for platform_key, artifact in manifest["artifacts"].items():
        assert artifact["archive_name"].startswith("cpython-3.12.14+20260825-")
        assert artifact["archive_name"].endswith("-install_only_stripped.tar.gz")
        assert artifact["url"].startswith(
            "https://github.com/astral-sh/python-build-standalone/releases/download/20260825/"
        )
        assert len(artifact["sha256"]) == 64
        assert all(character in "0123456789abcdef" for character in artifact["sha256"])
        expected_python = "python/python.exe" if platform_key.startswith("windows-") else "python/bin/python3"
        assert artifact["python_path"] == expected_python


def test_bootstraps_offer_governed_runtime_recovery_or_exit() -> None:
    """A failed runtime install offers governed package-manager recovery without changing the host silently."""
    posix = POSIX_RUNTIME_BOOTSTRAP.read_text(encoding="utf-8")
    windows = WINDOWS_RUNTIME_BOOTSTRAP.read_text(encoding="utf-8")
    for text in (posix, windows):
        assert "SAGE RUNTIME INSTALLATION REPORT" in text
        assert "Result: BLOCKED" in text
        assert "Install the SAGE Python runtime again" in text
        assert "Exit SAGE" in text
    assert 'brew" install "python@$PYTHON_MINOR"' in posix
    assert "Install approved Python $PYTHON_MINOR with Homebrew" in posix
    assert 'winget install --id "Python.Python.$PythonMinor"' in windows
    assert "Install approved Python $PythonMinor with WinGet" in windows
    assert "Get-AuthenticodeSignature" in windows


def test_posix_bootstrap_emits_block_report_before_noninteractive_exit(
    tmp_path: Path,
) -> None:
    """A real bootstrap boundary failure must report the reason and governed actions."""
    if os.name == "nt":
        pytest.skip("POSIX bootstrap contract")
    app = tmp_path / "SAGE" / "app"
    config = app / "system" / "config"
    config.mkdir(parents=True)
    (config / "python-runtime.json").write_bytes(RUNTIME_MANIFEST.read_bytes())
    result = subprocess.run(
        [
            "/bin/sh",
            str(POSIX_RUNTIME_BOOTSTRAP),
            str(app),
            "base",
            "launch",
        ],
        env={**os.environ, "SAGE_DATA_HOME": str(app / "localdata")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "SAGE RUNTIME INSTALLATION REPORT" in result.stderr
    assert "Result: BLOCKED" in result.stderr
    assert "Refusing to install mutable runtime data inside the immutable app directory" in result.stderr
    assert "1. Install the SAGE Python runtime again" in result.stderr
    assert "Exit SAGE" in result.stderr
    assert "Non-interactive launch: exiting SAGE." in result.stderr


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
    """A clean first launch automatically creates the sibling localdata runtime."""
    root = _root(tmp_path)

    result = bootstrap.ensure_runtime(root)

    assert result == 0
    layout = bootstrap.storage_layout(root)
    venv_python = bootstrap._venv_python(root)
    assert layout.data_root == tmp_path / "SAGE" / "localdata"
    assert venv_python.is_file()
    assert not (root / ".venv").exists()
    state = json.loads((layout.state_root / "runtime-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY"
    assert state["python_environment"] == "localdata/.system/runtime/venv"
    assert state["dependency_validation"] == "exact-pins+only-binary+no-deps+pip-check+import-smoke"
    assert state["requirements_sha256"] == bootstrap._requirements_sha256(root / "system" / "requirements.txt")


def test_incomplete_existing_venv_runs_automatic_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An incomplete managed environment is repaired without an interactive decision."""
    root = _root(tmp_path, "openpyxl==3.1.5\n")
    venv_python = bootstrap._venv_python(root)
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(bootstrap, "_python_matches_bootstrap", lambda python: True)
    monkeypatch.setattr(bootstrap, "_pip_is_available", lambda python: True)
    statuses = iter([(False, ["openpyxl (missing)"]), (True, [])])
    monkeypatch.setattr(bootstrap, "_requirements_status", lambda python, req: next(statuses))
    monkeypatch.setattr(bootstrap, "_pip_check", lambda python: (True, ""))
    monkeypatch.setattr(bootstrap, "_dependency_import_status", lambda python, reqs: (True, []))
    repaired: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        bootstrap,
        "_install_requirements",
        lambda python, req, force_reinstall=False: repaired.append((python, req)) is None or True,
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


def test_bootstrap_blocks_macos_quarantine_before_environment_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A downloaded bundle must not install or import native wheels under quarantine."""
    root = _root(tmp_path)
    monkeypatch.setattr(bootstrap, "_macos_quarantine_path", lambda *paths: root.parent)

    assert bootstrap.ensure_runtime(root) == 2
    assert not bootstrap.storage_layout(root).venv_root.exists()


def test_runtime_import_probe_loads_declared_modules(tmp_path: Path) -> None:
    """READY requires real imports rather than distribution metadata alone."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("PyYAML==6.0.3\nopenpyxl==3.1.5\ncertifi==2026.7.22\n", encoding="utf-8")

    ready, details = bootstrap._dependency_import_status(Path(sys.executable), [requirements])

    assert ready is True
    assert details == []


def test_runtime_import_failure_forces_one_pinned_reinstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken import is repaired even when pip metadata reports the exact versions."""
    root = _root(tmp_path, "PyYAML==6.0.3\n")
    venv_python = bootstrap._venv_python(root)
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_python_matches_bootstrap", lambda python: True)
    monkeypatch.setattr(bootstrap, "_pip_is_available", lambda python: True)
    monkeypatch.setattr(bootstrap, "_requirements_status", lambda python, req: (True, []))
    monkeypatch.setattr(bootstrap, "_pip_check", lambda python: (True, ""))
    import_statuses = iter([(False, ["PyYAML import failed"]), (True, [])])
    monkeypatch.setattr(
        bootstrap,
        "_dependency_import_status",
        lambda python, reqs: next(import_statuses),
    )
    repairs: list[tuple[Path, Path, bool]] = []
    monkeypatch.setattr(
        bootstrap,
        "_install_requirements",
        lambda python, req, force_reinstall=False: repairs.append(
            (python, req, force_reinstall)
        ) is None or True,
    )
    monkeypatch.setattr(bootstrap, "_write_runtime_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(bootstrap, "_write_host_capability", lambda *args, **kwargs: Path("receipt"))
    monkeypatch.setattr(bootstrap, "_python_version", lambda python: "3.12.14")

    assert bootstrap.ensure_runtime(root) == 0
    assert repairs == [(venv_python, root / "system" / "requirements.txt", True)]


def test_runtime_state_records_python_platform_and_dependency_contract(tmp_path: Path) -> None:
    """Persist enough detail to prove the deterministic preflight that allowed startup."""
    root = _root(tmp_path)
    assert bootstrap.ensure_runtime(root) == 0
    state = json.loads((bootstrap.storage_layout(root).state_root / "runtime-state.json").read_text(encoding="utf-8"))
    assert state["python_minimum"] == "3.10"
    assert state["python_implementation"]
    assert state["schema_version"] == 3
    assert state["python_runtime"] == "localdata/.system/runtime/python"
    assert state["python_runtime_provider"] == "sage-managed"
    assert state["python_runtime_version"]
    assert state["platform_system"] in {"Windows", "Darwin", "Linux"}
    assert state["platform_supported"] is True
    assert state["dependency_validation"] == "exact-pins+only-binary+no-deps+pip-check+import-smoke"


def test_runtime_state_records_an_approved_host_python_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distinguish an approved host interpreter from SAGE's downloadable standalone runtime."""
    root = _root(tmp_path)
    monkeypatch.setenv("SAGE_PYTHON_RUNTIME_PROVIDER", "python.org")
    monkeypatch.setenv("SAGE_PYTHON_RUNTIME_PATH", str(Path(sys.executable).resolve()))

    assert bootstrap.ensure_runtime(root) == 0

    state = json.loads((bootstrap.storage_layout(root).state_root / "runtime-state.json").read_text(encoding="utf-8"))
    assert state["python_runtime"] == "approved-host-python"
    assert state["python_runtime_provider"] == "python.org"
    assert state["python_runtime_path"] == str(Path(sys.executable).resolve())


def test_platform_launchers_use_pinned_runtime_and_delegate_wrappers(package_root: Path) -> None:
    """Cover Windows plus macOS/Linux pinned-runtime contracts without executing a foreign OS shell."""
    unix = (package_root / "system" / "bin" / "sage").read_text(encoding="utf-8")
    windows = (package_root / "system/bin/sage.cmd").read_text(encoding="utf-8")
    assert "bootstrap_python.sh" in unix
    assert "bootstrap_python.ps1" in windows
    runtime_bootstrap = POSIX_RUNTIME_BOOTSTRAP.read_text(encoding="utf-8")
    assert "macos_launch_quarantine_path" in runtime_bootstrap
    assert runtime_bootstrap.index("macos_launch_quarantine_path") < runtime_bootstrap.index(
        '"$BOOTSTRAP_PYTHON" "$BOOTSTRAP_SCRIPT"'
    )
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
    assert 'set "RUNTIME_BOOTSTRAP=%ROOT_DIR%\\system\\tools\\bootstrap_python.ps1"' in windows
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
    assert row["hardening_worker_limit"] == 2
    assert "AVAILABLE_RAM_BELOW_4_GIB" in row["reasons"]


def test_host_capability_selects_basic_when_logical_threads_are_below_8(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select BASIC when logical CPU capacity is below the governed eight-thread threshold."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 8 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 4)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "BASIC"
    assert row["default_hardening_workers"] == 2
    assert row["hardening_worker_limit"] == 2
    assert "LOGICAL_CPU_THREADS_BELOW_8" in row["reasons"]


def test_host_capability_selects_standard_at_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select STANDARD when RAM and CPU meet the governed thresholds."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 4 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 8)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "STANDARD"
    assert row["detection_status"] == "READY"
    assert row["default_hardening_workers"] == 4
    assert row["hardening_worker_limit"] == 4
    assert row["reasons"] == []


def test_host_capability_selects_standard_below_advanced_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep capable hosts STANDARD unless both ADVANCED thresholds are met."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 15)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "STANDARD"
    assert row["default_hardening_workers"] == 4
    assert row["hardening_worker_limit"] == 4


def test_host_capability_selects_advanced_at_16_gib_and_16_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select ADVANCED only when both governed high-capability thresholds are met."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 16)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "ADVANCED"
    assert row["detection_status"] == "READY"
    assert row["advanced_ram_threshold_bytes"] == 16 * 1024**3
    assert row["advanced_thread_threshold"] == 16
    assert row["default_hardening_workers"] == 6
    assert row["hardening_worker_limit"] == 6
    assert row["reasons"] == []


def test_host_capability_detection_failure_falls_safely_to_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail safely to BASIC when a required host-capability measurement is unavailable."""
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: None)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 32)
    row = bootstrap.detect_host_capability()
    assert row["profile"] == "BASIC"
    assert row["detection_status"] == "FAILED_SAFE"
    assert row["default_hardening_workers"] == 2
    assert row["hardening_worker_limit"] == 2
    assert row["reasons"] == ["HARDWARE_DETECTION_FAILED"]


def test_hardening_worker_override_cannot_exceed_host_profile_limit() -> None:
    """Keep overrides at or below the BASIC/STANDARD/ADVANCED setup-selected worker ceiling."""
    basic = {"profile": "BASIC", "default_hardening_workers": 2, "hardening_worker_limit": 2}
    standard = {"profile": "STANDARD", "default_hardening_workers": 4, "hardening_worker_limit": 4}
    advanced = {"profile": "ADVANCED", "default_hardening_workers": 6, "hardening_worker_limit": 6}
    assert bootstrap.hardening_worker_cap(basic, {}) == (2, "HOST_PROFILE_DEFAULT")
    assert bootstrap.hardening_worker_cap(standard, {}) == (4, "HOST_PROFILE_DEFAULT")
    assert bootstrap.hardening_worker_cap(advanced, {}) == (6, "HOST_PROFILE_DEFAULT")
    assert bootstrap.hardening_worker_cap(basic, {"SAGE_HARDENING_WORKERS": "99"}) == (2, "ENV_OVERRIDE_CAPPED_BY_HOST_PROFILE")
    assert bootstrap.hardening_worker_cap(standard, {"SAGE_HARDENING_WORKERS": "99"}) == (4, "ENV_OVERRIDE_CAPPED_BY_HOST_PROFILE")
    assert bootstrap.hardening_worker_cap(advanced, {"SAGE_HARDENING_WORKERS": "99"}) == (6, "ENV_OVERRIDE_CAPPED_BY_HOST_PROFILE")
    assert bootstrap.hardening_worker_cap(advanced, {"SAGE_HARDENING_WORKERS": "5"}) == (5, "ENV_OVERRIDE")
    assert bootstrap.hardening_worker_cap(basic, {"SAGE_HARDENING_WORKERS": "1"}) == (1, "ENV_OVERRIDE")
    assert bootstrap.hardening_worker_cap(standard, {"SAGE_HARDENING_WORKERS": "3"}) == (3, "ENV_OVERRIDE")
    assert bootstrap.hardening_worker_cap(standard, {"SAGE_HARDENING_WORKERS": "0"}) == (1, "ENV_OVERRIDE")
    assert bootstrap.hardening_worker_cap(standard, {"SAGE_HARDENING_WORKERS": "bad"}) == (4, "INVALID_OVERRIDE_FALLBACK")


def test_host_capability_receipt_is_machine_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup capability state is written only beneath hidden localdata machine state."""
    root = _root(tmp_path)
    monkeypatch.setattr(bootstrap, "_available_ram_bytes", lambda: 8 * 1024**3)
    monkeypatch.setattr(bootstrap, "_logical_cpu_threads", lambda: 8)
    target = bootstrap._write_host_capability(root)
    assert target == tmp_path / "SAGE" / "localdata" / ".system" / "state" / "host-capability.json"
    row = json.loads(target.read_text(encoding="utf-8"))
    assert row["profile"] == "STANDARD"
    assert row["default_hardening_workers"] == 4
    assert row["detected_utc"]


def test_setup_selected_host_capability_is_loaded_for_later_hardening(tmp_path: Path) -> None:
    """Formal hardening must reuse the setup-selected host-tier ceiling, not redetect upward."""
    root = _root(tmp_path)
    basic = {
        "schema_version": bootstrap.HOST_CAPABILITY_SCHEMA,
        "profile": "BASIC",
        "detection_status": "READY",
        "available_ram_bytes": 8 * 1024**3,
        "logical_cpu_threads": 8,
        "basic_ram_threshold_bytes": bootstrap.BASIC_RAM_THRESHOLD_BYTES,
        "basic_thread_threshold": bootstrap.BASIC_THREAD_THRESHOLD,
        "default_hardening_workers": 2,
        "hardening_worker_limit": 2,
        "reasons": [],
    }
    bootstrap._write_host_capability(root, basic)

    loaded, source = bootstrap.load_host_capability(root)

    assert loaded["profile"] == "BASIC"
    assert loaded["hardening_worker_limit"] == 2
    assert source == "SETUP_HOST_CAPABILITY_RECEIPT"


def test_setup_selected_advanced_capability_is_loaded_for_later_hardening(tmp_path: Path) -> None:
    """Formal hardening must retain a setup-selected ADVANCED ceiling of six workers."""
    root = _root(tmp_path)
    advanced = {
        "schema_version": bootstrap.HOST_CAPABILITY_SCHEMA,
        "profile": "ADVANCED",
        "detection_status": "READY",
        "available_ram_bytes": 16 * 1024**3,
        "logical_cpu_threads": 16,
        "basic_ram_threshold_bytes": bootstrap.BASIC_RAM_THRESHOLD_BYTES,
        "basic_thread_threshold": bootstrap.BASIC_THREAD_THRESHOLD,
        "advanced_ram_threshold_bytes": bootstrap.ADVANCED_RAM_THRESHOLD_BYTES,
        "advanced_thread_threshold": bootstrap.ADVANCED_THREAD_THRESHOLD,
        "default_hardening_workers": 6,
        "hardening_worker_limit": 6,
        "reasons": [],
    }
    bootstrap._write_host_capability(root, advanced)

    loaded, source = bootstrap.load_host_capability(root)

    assert loaded["profile"] == "ADVANCED"
    assert loaded["hardening_worker_limit"] == 6
    assert bootstrap.hardening_worker_cap(loaded, {"SAGE_HARDENING_WORKERS": "99"}) == (
        6,
        "ENV_OVERRIDE_CAPPED_BY_HOST_PROFILE",
    )
    assert source == "SETUP_HOST_CAPABILITY_RECEIPT"


def test_missing_or_invalid_setup_host_capability_fails_safe_to_basic(tmp_path: Path) -> None:
    """Absent/corrupt setup capability may never permit more than the BASIC worker ceiling."""
    root = _root(tmp_path)
    loaded, source = bootstrap.load_host_capability(root)
    assert loaded["profile"] == "BASIC"
    assert loaded["hardening_worker_limit"] == 2
    assert source == "MISSING_SETUP_RECEIPT_FAIL_SAFE_BASIC"

    target = bootstrap.storage_layout(root, create=True).state_root / "host-capability.json"
    target.write_text('{"profile":"STANDARD","hardening_worker_limit":99}\n', encoding="utf-8")
    loaded, source = bootstrap.load_host_capability(root)
    assert loaded["profile"] == "BASIC"
    assert loaded["hardening_worker_limit"] == 2
    assert source == "INVALID_SETUP_RECEIPT_FAIL_SAFE_BASIC"
