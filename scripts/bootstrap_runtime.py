#!/usr/bin/env python3
"""Bootstrap SAGE's local Python runtime before importing any application module."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MIN_PYTHON = (3, 10)
RUNTIME_STATE_SCHEMA = 1
RELEASE_STATE_SCHEMA = 1
AUTO_YES_ENV = "SAGE_BOOTSTRAP_AUTO_YES"
SUPPORTED_SYSTEMS = {"Windows", "Darwin", "Linux"}




def _version(root: Path) -> str | None:
    """Return the package release identity when this is a complete SAGE source tree."""
    path = root / "VERSION"
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _release_state_path(root: Path) -> Path:
    """Return the local release-boundary receipt used by RC clean-start policy."""
    return root / "state" / "release-state.json"


def _read_release_state(root: Path) -> dict[str, object]:
    """Load the local release receipt without letting corrupt prior state block cleanup."""
    path = _release_state_path(root)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _remove_local_path(path: Path, root: Path, removed: list[str]) -> None:
    """Remove one SAGE-local mutable path without following symlinks outside the package."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        label = path.relative_to(root).as_posix()
    except ValueError:
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
    removed.append(label)


def _rc_mutable_state_present(root: Path) -> bool:
    """Return whether an overlaid RC tree contains mutable state from an earlier run/build."""
    state = root / "state"
    if state.is_dir() and any(state.iterdir()):
        return True
    for tool in ("bic", "saw"):
        folder = root / "jobs" / tool
        if folder.is_dir() and any(item.name != "README.md" for item in folder.iterdir()):
            return True
    cache = root / "cache"
    if cache.is_dir() and any(cache.iterdir()):
        return True
    workspace = root / "workspace-data"
    if workspace.is_dir():
        for item in workspace.iterdir():
            if item.name != "scripture-projects":
                return True
        scripture = workspace / "scripture-projects"
        if scripture.is_dir() and any(item.name != "README.md" for item in scripture.iterdir()):
            return True
    return False


def _reset_rc_mutable_state(root: Path) -> list[str]:
    """Remove prior-RC operator/project/workflow state while preserving source and .venv."""
    removed: list[str] = []
    _remove_local_path(root / "state", root, removed)
    _remove_local_path(root / "cache", root, removed)
    for tool in ("bic", "saw"):
        folder = root / "jobs" / tool
        if folder.is_dir():
            for item in list(folder.iterdir()):
                if item.name != "README.md":
                    _remove_local_path(item, root, removed)
    workspace = root / "workspace-data"
    if workspace.is_dir():
        for item in list(workspace.iterdir()):
            if item.name != "scripture-projects":
                _remove_local_path(item, root, removed)
        scripture = workspace / "scripture-projects"
        if scripture.is_dir():
            for item in list(scripture.iterdir()):
                if item.name != "README.md":
                    _remove_local_path(item, root, removed)
    return sorted(set(removed))


def _apply_rc_release_boundary(root: Path) -> dict[str, object]:
    """Enforce clean operator state on every new RC version; beta migration is deliberately separate."""
    version = _version(root)
    if version is None or "-rc" not in version.casefold():
        return {"status": "NOT_APPLICABLE", "version": version}
    previous = _read_release_state(root)
    previous_version = str(previous.get("version") or "").strip() or None
    changed = previous_version != version
    stale = _rc_mutable_state_present(root)
    removed: list[str] = []
    if changed and stale:
        removed = _reset_rc_mutable_state(root)
    path = _release_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": RELEASE_STATE_SCHEMA,
        "version": version,
        "policy": "RC_CLEAN_START_ON_VERSION_CHANGE",
        "previous_version": previous_version,
        "reset_performed": bool(removed),
        "removed": removed,
        "validated_utc": datetime.now(timezone.utc).isoformat(),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return payload


def _write(message: str = "") -> None:
    """Write one bootstrap message immediately."""
    print(message, flush=True)


def _confirm(prompt: str) -> bool:
    """Ask permission for a machine-changing bootstrap action; default to yes."""
    if os.environ.get(AUTO_YES_ENV, "").strip().lower() in {"1", "true", "yes", "y"}:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(f"{prompt} [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        _write()
        return False
    return answer in {"", "y", "yes"}


def _run(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one bootstrap subprocess without shell interpolation."""
    return subprocess.run(
        args,
        text=True,
        capture_output=capture,
        check=False,
    )




def _platform_status() -> tuple[bool, str]:
    """Return whether the host operating system is one of SAGE's supported desktop platforms."""
    system = platform.system() or "UNKNOWN"
    return system in SUPPORTED_SYSTEMS, system


def _venv_module_available() -> bool:
    """Return whether the bootstrap interpreter can create standard-library virtual environments."""
    result = _run([sys.executable, "-c", "import venv"])
    return result.returncode == 0

def _python_version(python: Path | str) -> str:
    """Return one interpreter version string without allowing a summary probe to break startup."""
    try:
        result = _run([str(python), "-c", "import platform; print(platform.python_version())"])
    except OSError:
        return "UNKNOWN"
    return (result.stdout or "").strip() if result.returncode == 0 else "UNKNOWN"


def _python_is_supported(python: Path | str) -> bool:
    """Return whether an interpreter is runnable and meets SAGE's minimum version."""
    result = _run(
        [
            str(python),
            "-c",
            "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)",
        ]
    )
    return result.returncode == 0


def _venv_python(root: Path) -> Path:
    """Return the platform-native Python path inside SAGE's local virtual environment."""
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _requirements_sha256(requirements: Path) -> str:
    """Hash the declared runtime requirements for resumable environment state."""
    return hashlib.sha256(requirements.read_bytes()).hexdigest()


def _requirements_status(python: Path, requirements: Path) -> tuple[bool, list[str]]:
    """Validate installed distributions and declared version constraints using pip's bundled packaging parser."""
    validator = r'''
import importlib.metadata as md
import json
import sys
from pathlib import Path
from pip._vendor.packaging.requirements import Requirement

missing = []
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith(("-r", "--requirement", "-c", "--constraint", "--", "git+", "http://", "https://")):
        missing.append(f"unsupported requirement entry: {line}")
        continue
    try:
        req = Requirement(line)
    except Exception as exc:
        missing.append(f"invalid requirement {line!r}: {exc}")
        continue
    if req.marker is not None and not req.marker.evaluate():
        continue
    try:
        version = md.version(req.name)
    except md.PackageNotFoundError:
        missing.append(f"{req.name} (missing)")
        continue
    if req.specifier and not req.specifier.contains(version, prereleases=True):
        missing.append(f"{req.name} {version} does not satisfy {req.specifier}")
print(json.dumps(missing))
raise SystemExit(1 if missing else 0)
'''
    result = _run([str(python), "-c", validator, str(requirements)])
    try:
        details = json.loads((result.stdout or "[]").strip() or "[]")
    except json.JSONDecodeError:
        details = [(result.stderr or result.stdout or "requirements validation failed").strip()]
    return result.returncode == 0, [str(item) for item in details]


def _pip_check(python: Path) -> tuple[bool, str]:
    """Run pip's installed-package consistency check inside the SAGE virtual environment."""
    result = _run([str(python), "-m", "pip", "check"])
    detail = (result.stdout + result.stderr).strip()
    return result.returncode == 0, detail


def _pip_is_available(python: Path) -> bool:
    """Return whether pip is usable inside the local virtual environment."""
    return _run([str(python), "-m", "pip", "--version"]).returncode == 0


def _ensure_pip(python: Path) -> bool:
    """Repair pip after the operator has approved environment creation or repair."""
    if _pip_is_available(python):
        return True
    _write("Repairing pip inside the SAGE environment...")
    result = _run([str(python), "-m", "ensurepip", "--upgrade"], capture=False)
    return result.returncode == 0


def _create_venv(root: Path) -> bool:
    """Create a fresh local virtual environment using the bootstrap interpreter."""
    venv_dir = root / ".venv"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    _write("Creating SAGE Python environment (.venv)...")
    result = _run([sys.executable, "-m", "venv", str(venv_dir)], capture=False)
    return result.returncode == 0


def _install_requirements(python: Path, requirements: Path) -> bool:
    """Synchronize the local environment to requirements.txt after operator approval."""
    if not _ensure_pip(python):
        return False
    _write("Installing / repairing SAGE Python dependencies...")
    result = _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
        ],
        capture=False,
    )
    return result.returncode == 0


def _write_runtime_state(root: Path, python: Path, requirements: Path) -> None:
    """Persist the last positively validated local-runtime fingerprint."""
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    version = _run([str(python), "-c", "import platform; print(platform.python_version())"])
    implementation = _run([str(python), "-c", "import platform; print(platform.python_implementation())"])
    system_ready, system = _platform_status()
    payload = {
        "schema_version": RUNTIME_STATE_SCHEMA,
        "status": "READY",
        "python_environment": ".venv",
        "python_environment_path": str(root / ".venv"),
        "python_executable": str(python),
        "python_version": (version.stdout or "").strip(),
        "python_minimum": ".".join(str(item) for item in MIN_PYTHON),
        "python_implementation": (implementation.stdout or "").strip(),
        "platform_system": system,
        "platform_supported": system_ready,
        "dependency_validation": "requirements-specifiers+pip-check",
        "requirements_sha256": _requirements_sha256(requirements),
        "validated_utc": datetime.now(timezone.utc).isoformat(),
    }
    target = state_dir / "runtime-state.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def _blocked(*lines: str) -> int:
    """Render one fail-closed bootstrap error and return the blocking exit code."""
    _write("SAGE PRE-CHECK")
    _write()
    _write("Python environment: BLOCKED")
    for line in lines:
        _write(line)
    return 2


def ensure_runtime(root: Path) -> int:
    """Create, repair, and validate the local SAGE virtual environment."""
    root = root.resolve()
    requirements = root / "requirements.txt"
    venv_python = _venv_python(root)

    platform_ready, system = _platform_status()
    if not platform_ready:
        return _blocked(f"Unsupported operating system: {system}. SAGE supports Windows, macOS, and Linux.")
    if sys.version_info < MIN_PYTHON:
        return _blocked("Python 3.10 or later is required to create the SAGE environment.")
    if not _venv_module_available():
        return _blocked(
            "The Python standard-library venv module is unavailable.",
            "Install the platform package that provides Python virtual environments (for example python3-venv on Debian/Ubuntu), then relaunch SAGE.",
        )
    if not requirements.is_file():
        return _blocked("requirements.txt is missing from the SAGE package.")

    created_now = False
    if not venv_python.is_file() or not _python_is_supported(venv_python):
        _write("SAGE PRE-CHECK")
        _write()
        _write("Python environment: NOT READY")
        if venv_python.exists():
            _write("The local .venv is incomplete or uses an unsupported Python version.")
            action = "Rebuild the local SAGE .venv and install its declared dependencies now?"
        else:
            _write("The local SAGE .venv has not been created yet.")
            action = "Create the local SAGE .venv and install its declared dependencies now?"
        if not _confirm(action):
            return _blocked(
                "No changes were made.",
                "Run ./sage (Unix/macOS) or sage.cmd (Windows) again when ready.",
            )
        if not _create_venv(root):
            return _blocked("Could not create .venv with the available Python interpreter.")
        created_now = True
        venv_python = _venv_python(root)
        if not venv_python.is_file() or not _python_is_supported(venv_python):
            return _blocked("The newly created .venv Python could not be validated.")

    if not _pip_is_available(venv_python):
        if not created_now:
            _write("SAGE PRE-CHECK")
            _write()
            _write("Python environment: INCOMPLETE")
            _write("pip is unavailable inside the local .venv.")
            if not _confirm("Repair the SAGE Python environment now?"):
                return _blocked("No changes were made.", "pip is required inside .venv.")
        if not _ensure_pip(venv_python):
            return _blocked("pip is unavailable inside .venv and repair failed.")

    requirements_ok, missing = _requirements_status(venv_python, requirements)
    pip_ok, pip_detail = _pip_check(venv_python)
    if not requirements_ok or not pip_ok:
        _write("SAGE PRE-CHECK")
        _write()
        _write("Python environment: INCOMPLETE")
        if missing:
            _write("Missing or incompatible runtime dependencies:")
            for item in missing:
                _write(f"  - {item}")
        if not pip_ok and pip_detail:
            _write("Dependency consistency check:")
            for line in pip_detail.splitlines():
                _write(f"  - {line}")
        if not created_now and not _confirm("Repair the SAGE Python environment now?"):
            return _blocked(
                "No changes were made.",
                f"Manual repair: {venv_python} -m pip install -r {requirements}",
            )
        if not _install_requirements(venv_python, requirements):
            return _blocked("Dependency installation failed. See the platform ERRORS.md cheat sheet.")
        requirements_ok, missing = _requirements_status(venv_python, requirements)
        pip_ok, pip_detail = _pip_check(venv_python)
        if not requirements_ok or not pip_ok:
            details = missing or ([pip_detail] if pip_detail else [])
            return _blocked("The repaired environment still failed validation.", *details)

    release_receipt = _apply_rc_release_boundary(root)
    _write_runtime_state(root, venv_python, requirements)
    python_version = _python_version(venv_python)
    _write("SAGE PRE-CHECK")
    _write()
    _write("Python environment: READY")
    _write(f"SAGE root: {root}")
    _write(f"Managed environment: {root / '.venv'}")
    _write(f"Python: {python_version}")
    if release_receipt.get("status") != "NOT_APPLICABLE":
        _write(f"RC state policy: {release_receipt.get('policy')}")
        if release_receipt.get("reset_performed"):
            _write("Prior RC operator/project state: RESET")
        else:
            _write("Prior RC operator/project state: CLEAN / CURRENT")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the dependency bootstrap and return a fail-closed process status."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(__file__).resolve().parents[1]
    return ensure_runtime(root)


if __name__ == "__main__":
    raise SystemExit(main())
