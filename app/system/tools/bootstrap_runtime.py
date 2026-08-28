#!/usr/bin/env python3
"""Bootstrap SAGE's local Python runtime before importing any application module."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
STORAGE_MODULE_PATH = SOURCE_ROOT / "sage" / "storage.py"
_STORAGE_SPEC = importlib.util.spec_from_file_location("_sage_bootstrap_storage", STORAGE_MODULE_PATH)
if _STORAGE_SPEC is None or _STORAGE_SPEC.loader is None:
    raise RuntimeError(f"Cannot load SAGE storage contract: {STORAGE_MODULE_PATH}")
_STORAGE_MODULE = importlib.util.module_from_spec(_STORAGE_SPEC)
sys.modules[_STORAGE_SPEC.name] = _STORAGE_MODULE
_STORAGE_SPEC.loader.exec_module(_STORAGE_MODULE)
DATA_HOME_ENV = _STORAGE_MODULE.DATA_HOME_ENV
StorageError = _STORAGE_MODULE.StorageError
clear_persisted_data_home = _STORAGE_MODULE.clear_persisted_data_home
storage_layout = _STORAGE_MODULE.storage_layout

MIN_PYTHON = (3, 10)
RUNTIME_STATE_SCHEMA = 3
RELEASE_STATE_SCHEMA = 1
SUPPORTED_SYSTEMS = {"Windows", "Darwin", "Linux"}

RUNTIME_IMPORT_MODULES = {
    "certifi": "certifi",
    "et-xmlfile": "et_xmlfile",
    "linkify-it-py": "linkify_it",
    "markdown-it-py": "markdown_it",
    "mdit-py-plugins": "mdit_py_plugins",
    "mdurl": "mdurl",
    "openpyxl": "openpyxl",
    "platformdirs": "platformdirs",
    "pygments": "pygments",
    "pyyaml": "yaml",
    "rich": "rich",
    "textual": "textual",
    "typing-extensions": "typing_extensions",
    "uc-micro-py": "uc_micro",
}

HOST_CAPABILITY_SCHEMA = 2
BASIC_RAM_THRESHOLD_BYTES = 4 * 1024**3
BASIC_THREAD_THRESHOLD = 8
BASIC_HARDENING_WORKERS = 2
STANDARD_HARDENING_WORKERS = 4
ADVANCED_RAM_THRESHOLD_BYTES = 16 * 1024**3
ADVANCED_THREAD_THRESHOLD = 16
ADVANCED_HARDENING_WORKERS = 6


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    """Replace one JSON receipt through a unique same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _logical_cpu_threads() -> int | None:
    """Return installed logical CPU thread count, or None when detection fails."""
    try:
        value = os.cpu_count()
    except Exception:
        return None
    return int(value) if isinstance(value, int) and value > 0 else None


def _available_ram_bytes() -> int | None:
    """Return currently available physical RAM using only platform-native interfaces."""
    system = platform.system()
    try:
        if system == "Linux":
            meminfo = Path("/proc/meminfo").read_text(encoding="utf-8", errors="strict")
            for line in meminfo.splitlines():
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
            return None
        if system == "Darwin":
            page_size_result = subprocess.run(
                ["sysctl", "-n", "hw.pagesize"],
                text=True, capture_output=True, timeout=5, check=False,
            )
            vm_result = subprocess.run(
                ["vm_stat"],
                text=True, capture_output=True, timeout=5, check=False,
            )
            if page_size_result.returncode != 0 or vm_result.returncode != 0:
                return None
            page_size = int(page_size_result.stdout.strip())
            pages = 0
            for key in ("Pages free", "Pages inactive", "Pages speculative"):
                for line in vm_result.stdout.splitlines():
                    if line.startswith(key + ":"):
                        pages += int(line.split(":", 1)[1].strip().rstrip("."))
                        break
            return pages * page_size if pages > 0 else None
        if system == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                """Represent the Windows GlobalMemoryStatusEx payload."""

                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return int(status.ullAvailPhys) if status.ullAvailPhys > 0 else None
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None
    return None


def detect_host_capability() -> dict[str, object]:
    """Classify this machine into the fail-safe BASIC/STANDARD/ADVANCED execution tier."""
    threads = _logical_cpu_threads()
    available_ram = _available_ram_bytes()
    reasons: list[str] = []
    detection_failed = threads is None or available_ram is None
    if detection_failed:
        profile = "BASIC"
        reasons.append("HARDWARE_DETECTION_FAILED")
    else:
        if available_ram < BASIC_RAM_THRESHOLD_BYTES:
            reasons.append("AVAILABLE_RAM_BELOW_4_GIB")
        if threads < BASIC_THREAD_THRESHOLD:
            reasons.append("LOGICAL_CPU_THREADS_BELOW_8")
        if reasons:
            profile = "BASIC"
        elif available_ram >= ADVANCED_RAM_THRESHOLD_BYTES and threads >= ADVANCED_THREAD_THRESHOLD:
            profile = "ADVANCED"
        else:
            profile = "STANDARD"
    default_workers = {
        "BASIC": BASIC_HARDENING_WORKERS,
        "STANDARD": STANDARD_HARDENING_WORKERS,
        "ADVANCED": ADVANCED_HARDENING_WORKERS,
    }[profile]
    return {
        "schema_version": HOST_CAPABILITY_SCHEMA,
        "profile": profile,
        "detection_status": "FAILED_SAFE" if detection_failed else "READY",
        "available_ram_bytes": available_ram,
        "logical_cpu_threads": threads,
        "basic_ram_threshold_bytes": BASIC_RAM_THRESHOLD_BYTES,
        "basic_thread_threshold": BASIC_THREAD_THRESHOLD,
        "advanced_ram_threshold_bytes": ADVANCED_RAM_THRESHOLD_BYTES,
        "advanced_thread_threshold": ADVANCED_THREAD_THRESHOLD,
        "default_hardening_workers": default_workers,
        "hardening_worker_limit": default_workers,
        "reasons": reasons,
    }


def hardening_worker_cap(
    capability: dict[str, object] | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Return a hardening worker count capped by the setup-selected host profile."""
    row = capability or detect_host_capability()
    env = os.environ if environ is None else environ
    profile = str(row.get("profile") or "").strip().upper()
    if profile == "ADVANCED":
        profile_limit = ADVANCED_HARDENING_WORKERS
    elif profile == "STANDARD":
        profile_limit = STANDARD_HARDENING_WORKERS
    elif profile == "BASIC":
        profile_limit = BASIC_HARDENING_WORKERS
    else:
        profile_limit = int(row.get("hardening_worker_limit") or row.get("default_hardening_workers") or BASIC_HARDENING_WORKERS)
    profile_limit = max(1, min(ADVANCED_HARDENING_WORKERS, profile_limit))
    default = max(1, min(profile_limit, int(row.get("default_hardening_workers") or profile_limit)))
    raw = str(env.get("SAGE_HARDENING_WORKERS", "")).strip()
    if not raw:
        return default, "HOST_PROFILE_DEFAULT"
    try:
        requested = int(raw)
    except ValueError:
        return default, "INVALID_OVERRIDE_FALLBACK"
    requested = max(1, requested)
    if requested > profile_limit:
        return profile_limit, "ENV_OVERRIDE_CAPPED_BY_HOST_PROFILE"
    return requested, "ENV_OVERRIDE"


def _write_host_capability(root: Path, capability: dict[str, object] | None = None) -> Path:
    """Persist machine-local capability state; this path is excluded from vanilla releases."""
    state_dir = storage_layout(root, create=True).state_root
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(capability or detect_host_capability())
    payload["detected_utc"] = datetime.now(timezone.utc).isoformat()
    target = state_dir / "host-capability.json"
    _atomic_write_json(target, payload)
    return target


def _basic_fail_safe_capability(reason: str) -> dict[str, object]:
    """Return the conservative BASIC ceiling when setup capability cannot be trusted."""
    return {
        "schema_version": HOST_CAPABILITY_SCHEMA,
        "profile": "BASIC",
        "detection_status": "FAILED_SAFE",
        "available_ram_bytes": None,
        "logical_cpu_threads": None,
        "basic_ram_threshold_bytes": BASIC_RAM_THRESHOLD_BYTES,
        "basic_thread_threshold": BASIC_THREAD_THRESHOLD,
        "advanced_ram_threshold_bytes": ADVANCED_RAM_THRESHOLD_BYTES,
        "advanced_thread_threshold": ADVANCED_THREAD_THRESHOLD,
        "default_hardening_workers": BASIC_HARDENING_WORKERS,
        "hardening_worker_limit": BASIC_HARDENING_WORKERS,
        "reasons": [reason],
    }


def load_host_capability(root: Path) -> tuple[dict[str, object], str]:
    """Load the setup-selected host ceiling; missing or invalid state fails safely to BASIC."""
    target = storage_layout(root, create=True).state_root / "host-capability.json"
    if not target.is_file():
        return _basic_fail_safe_capability("SETUP_HOST_CAPABILITY_MISSING"), "MISSING_SETUP_RECEIPT_FAIL_SAFE_BASIC"
    try:
        row = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _basic_fail_safe_capability("SETUP_HOST_CAPABILITY_INVALID"), "INVALID_SETUP_RECEIPT_FAIL_SAFE_BASIC"
    if not isinstance(row, dict):
        return _basic_fail_safe_capability("SETUP_HOST_CAPABILITY_INVALID"), "INVALID_SETUP_RECEIPT_FAIL_SAFE_BASIC"
    profile = str(row.get("profile") or "").upper()
    expected_limit = {
        "BASIC": BASIC_HARDENING_WORKERS,
        "STANDARD": STANDARD_HARDENING_WORKERS,
        "ADVANCED": ADVANCED_HARDENING_WORKERS,
    }.get(profile)
    try:
        schema_ok = int(row.get("schema_version", -1)) == HOST_CAPABILITY_SCHEMA
        default_workers = int(row.get("default_hardening_workers", -1))
        worker_limit = int(row.get("hardening_worker_limit", -1))
    except (TypeError, ValueError):
        schema_ok = False
        default_workers = worker_limit = -1
    if not schema_ok or expected_limit is None or default_workers > expected_limit or worker_limit > expected_limit or default_workers < 1 or worker_limit < 1:
        return _basic_fail_safe_capability("SETUP_HOST_CAPABILITY_INVALID"), "INVALID_SETUP_RECEIPT_FAIL_SAFE_BASIC"
    return dict(row), "SETUP_HOST_CAPABILITY_RECEIPT"


def _version(root: Path) -> str | None:
    """Return the package release identity when this is a complete SAGE source tree."""
    path = root / "VERSION"
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _release_state_path(root: Path) -> Path:
    """Return the local receipt used by the pre-release state-boundary policy."""
    return storage_layout(root, create=True).state_root / "release-state.json"


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


def _apply_pre_release_boundary(root: Path) -> dict[str, object]:
    """Record pre-release source changes without deleting any persistent operator data."""
    version = _version(root)
    if version is None or re.fullmatch(
        r"(?:\d+\.\d+(?:alpha|beta)(?:\d+)?|\d+\.\d+-(?:alpha|beta|dev|rc\d+)(?:\.\d+)?|\d+\.\d+(?:a|b|rc)\d+)",
        version.casefold(),
    ) is None:
        return {"status": "NOT_APPLICABLE", "version": version}
    previous = _read_release_state(root)
    previous_version = str(previous.get("version") or "").strip() or None
    path = _release_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": RELEASE_STATE_SCHEMA,
        "version": version,
        "policy": "PRERELEASE_STATE_PRESERVED_ON_VERSION_CHANGE",
        "previous_version": previous_version,
        "version_changed": previous_version != version,
        "reset_performed": False,
        "removed": [],
        "validated_utc": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(path, payload)
    return payload


def _write(message: str = "") -> None:
    """Write one bootstrap message immediately."""
    print(message, flush=True)


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


def _macos_quarantine_path(*candidates: Path) -> Path | None:
    """Return the first quarantined launch/runtime boundary without bypassing Gatekeeper."""
    if platform.system() != "Darwin":
        return None
    xattr = Path("/usr/bin/xattr")
    if not xattr.is_file():
        return None
    seen: set[Path] = set()
    for candidate in candidates:
        normalized = candidate.resolve()
        if normalized in seen or (not normalized.exists() and not normalized.is_symlink()):
            continue
        seen.add(normalized)
        result = _run([str(xattr), "-p", "com.apple.quarantine", str(normalized)])
        if result.returncode == 0:
            return normalized
    return None


def _macos_quarantine_tree_path(*candidates: Path) -> Path | None:
    """Return the first runtime tree containing quarantined descendants."""
    if platform.system() != "Darwin":
        return None
    xattr = Path("/usr/bin/xattr")
    if not xattr.is_file():
        return None
    for candidate in candidates:
        normalized = candidate.resolve()
        if not normalized.exists():
            continue
        result = _run(
            [str(xattr), "-r", "-p", "com.apple.quarantine", str(normalized)]
        )
        if result.returncode == 0:
            return normalized
    return None


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


def _python_matches_bootstrap(python: Path | str) -> bool:
    """Return whether an interpreter matches the exact bootstrap CPython patch release."""
    expected = ".".join(str(item) for item in sys.version_info[:3])
    result = _run(
        [
            str(python),
            "-c",
            (
                "import platform; "
                f"raise SystemExit(0 if platform.python_implementation() == 'CPython' "
                f"and platform.python_version() == {expected!r} else 1)"
            ),
        ]
    )
    return result.returncode == 0


def _venv_python(root: Path) -> Path:
    """Return the platform-native Python path in localdata's managed runtime."""
    venv_root = storage_layout(root, create=True).venv_root
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def _requirements_sha256(requirements: Path) -> str:
    """Hash the declared runtime requirements for resumable environment state."""
    return hashlib.sha256(requirements.read_bytes()).hexdigest()


def _locked_requirements_errors(requirements: Path) -> list[str]:
    """Return reproducibility errors for a runtime dependency manifest.

    SAGE runtime manifests must enumerate every installable distribution at an exact
    version so bootstrap can install with --no-deps. Environment markers are allowed
    for Python-version-specific pins, but ranges, editable sources and remote/VCS
    requirements are not.
    """
    errors: list[str] = []
    for line_number, raw in enumerate(requirements.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        requirement_text = line.split(";", 1)[0].strip()
        if requirement_text.startswith(("-", "git+", "http://", "https://")):
            errors.append(f"line {line_number}: unsupported runtime requirement: {line}")
            continue
        if "==" not in requirement_text or any(token in requirement_text for token in (">=", "<=", "~=", "!=", ">", "<")):
            errors.append(f"line {line_number}: runtime dependency is not exactly pinned: {line}")
    return errors


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


def _declared_import_probes(requirements: list[Path]) -> list[dict[str, str]]:
    """Map declared distributions to their runtime import names."""
    probes: list[dict[str, str]] = []
    for manifest in requirements:
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            requirement_text, separator, marker = line.partition(";")
            requirement_text = requirement_text.strip()
            distribution = requirement_text.split("==", 1)[0].split("[", 1)[0].strip()
            normalized = re.sub(r"[-_.]+", "-", distribution).casefold()
            module = RUNTIME_IMPORT_MODULES.get(normalized)
            if module is not None:
                probes.append(
                    {
                        "distribution": distribution,
                        "module": module,
                        "marker": marker.strip() if separator else "",
                    }
                )
    return probes


def _dependency_import_status(
    python: Path,
    requirements: list[Path],
) -> tuple[bool, list[str]]:
    """Import every declared runtime module so metadata-only checks cannot report READY."""
    probes = _declared_import_probes(requirements)
    if not probes:
        return True, []
    validator = r'''
import importlib
import json
import sys
from pip._vendor.packaging.markers import Marker

failures = []
imported = set()
for probe in json.loads(sys.argv[1]):
    distribution = probe["distribution"]
    module = probe["module"]
    marker = probe["marker"]
    if marker and not Marker(marker).evaluate():
        continue
    if module in imported:
        continue
    try:
        importlib.import_module(module)
    except Exception as exc:
        failures.append(f"{distribution} import failed: {type(exc).__name__}: {exc}")
    else:
        imported.add(module)
print(json.dumps(failures))
raise SystemExit(1 if failures else 0)
'''
    result = _run([str(python), "-c", validator, json.dumps(probes, sort_keys=True)])
    try:
        details = json.loads((result.stdout or "[]").strip() or "[]")
    except json.JSONDecodeError:
        detail = (result.stderr or result.stdout or "runtime import validation failed").strip()
        details = [detail]
    if result.returncode != 0 and not details:
        details = [(result.stderr or f"runtime import process exited {result.returncode}").strip()]
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
    """Create a fresh managed virtual environment outside the Git-controlled application tree."""
    venv_dir = storage_layout(root, create=True).venv_root
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    _write("Creating SAGE Python environment (localdata/.system/runtime/venv)...")
    result = _run([sys.executable, "-m", "venv", str(venv_dir)], capture=False)
    return result.returncode == 0


def _install_requirements(
    python: Path,
    requirements: Path,
    *,
    force_reinstall: bool = False,
) -> bool:
    """Synchronize one exact-pinned manifest without dependency re-resolution."""
    if not _ensure_pip(python):
        return False
    lock_errors = _locked_requirements_errors(requirements)
    if lock_errors:
        for error in lock_errors:
            _write(f"  - {error}")
        return False
    _write(f"Installing / repairing pinned SAGE dependencies from {requirements.name}...")
    args = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--no-deps",
    ]
    if force_reinstall:
        args.append("--force-reinstall")
    args.extend(["-r", str(requirements)])
    result = _run(args, capture=False)
    return result.returncode == 0


def _write_runtime_state(
    root: Path,
    python: Path,
    requirements: Path,
    *,
    profile: str = "base",
    supplemental_requirements: Path | None = None,
) -> None:
    """Persist the last positively validated local-runtime fingerprint."""
    layout = storage_layout(root, create=True)
    state_dir = layout.state_root
    state_dir.mkdir(parents=True, exist_ok=True)
    version = _run([str(python), "-c", "import platform; print(platform.python_version())"])
    implementation = _run([str(python), "-c", "import platform; print(platform.python_implementation())"])
    system_ready, system = _platform_status()
    runtime_provider = os.environ.get("SAGE_PYTHON_RUNTIME_PROVIDER") or "sage-managed"
    runtime_path = os.environ.get("SAGE_PYTHON_RUNTIME_PATH")
    payload = {
        "schema_version": RUNTIME_STATE_SCHEMA,
        "status": "READY",
        "python_environment": "localdata/.system/runtime/venv",
        "python_environment_path": str(layout.venv_root),
        "python_executable": str(python),
        "python_version": (version.stdout or "").strip(),
        "python_minimum": ".".join(str(item) for item in MIN_PYTHON),
        "python_implementation": (implementation.stdout or "").strip(),
        "python_runtime": (
            "localdata/.system/runtime/python"
            if runtime_provider == "sage-managed"
            else "approved-host-python"
        ),
        "python_runtime_provider": runtime_provider,
        "python_runtime_path": runtime_path,
        "python_runtime_platform": os.environ.get("SAGE_MANAGED_PYTHON_PLATFORM"),
        "python_runtime_archive_sha256": os.environ.get("SAGE_MANAGED_PYTHON_SHA256"),
        "python_runtime_version": os.environ.get("SAGE_MANAGED_PYTHON_VERSION") or _python_version(sys.executable),
        "platform_system": system,
        "platform_supported": system_ready,
        "dependency_validation": "exact-pins+only-binary+no-deps+pip-check+import-smoke",
        "dependency_profile": profile,
        "requirements_sha256": _requirements_sha256(requirements),
        "supplemental_requirements_sha256": (
            _requirements_sha256(supplemental_requirements)
            if supplemental_requirements is not None
            else None
        ),
        "validated_utc": datetime.now(timezone.utc).isoformat(),
    }
    target = state_dir / "runtime-state.json"
    _atomic_write_json(target, payload)


def _blocked(*lines: str) -> int:
    """Render one fail-closed bootstrap error and return the blocking exit code."""
    _write("SAGE PRE-CHECK")
    _write()
    _write("Python environment: BLOCKED")
    for line in lines:
        _write(line)
    return 2


def ensure_runtime(root: Path, *, profile: str = "base") -> int:
    """Create, repair, and validate the local SAGE virtual environment."""
    root = root.resolve()
    try:
        layout = storage_layout(root, create=True)
    except StorageError as exc:
        return _blocked(str(exc))
    normalized_profile = profile.strip().lower() or "base"
    if normalized_profile not in {"base", "tui"}:
        return _blocked(f"Unknown dependency profile: {profile}")

    quarantined = _macos_quarantine_path(
        root.parent,
        root,
        root / "system" / "bin" / "sage",
        root / "system" / "tools" / "bootstrap_python.sh",
        root / "system" / "tools" / "bootstrap_runtime.py",
        layout.data_root,
        layout.venv_root,
    )
    if quarantined is not None:
        return _blocked(
            f"macOS quarantine is attached to the SAGE launch/runtime boundary: {quarantined}",
            "SAGE stopped before installing or importing native Python dependencies and did not bypass Gatekeeper.",
            "Verify the release checksum, then follow app/docs/macos-linux/RECOVERY.md to authorize this exact SAGE copy.",
        )
    requirements = root / "system" / "requirements.txt"
    supplemental_requirements = (
        root / "system" / "requirements-tui.txt"
        if normalized_profile == "tui"
        else None
    )
    venv_python = _venv_python(root)

    platform_ready, system = _platform_status()
    if not platform_ready:
        return _blocked(f"Unsupported operating system: {system}. SAGE supports Windows, macOS, and Linux.")
    if sys.version_info < MIN_PYTHON:
        return _blocked("The SAGE-managed Python runtime is older than the supported minimum.")
    if not _venv_module_available():
        return _blocked(
            "The SAGE-managed Python runtime is incomplete: its standard-library venv module is unavailable.",
            "Choose Install again from the runtime installation report.",
        )
    if not requirements.is_file():
        return _blocked("system/requirements.txt is missing from the SAGE package.")
    if supplemental_requirements is not None and not supplemental_requirements.is_file():
        return _blocked("system/requirements-tui.txt is missing from the SAGE package.")
    for manifest in [requirements, *([supplemental_requirements] if supplemental_requirements is not None else [])]:
        lock_errors = _locked_requirements_errors(manifest)
        if lock_errors:
            return _blocked(
                f"Runtime dependency manifest is not deterministic: {manifest}",
                *lock_errors,
            )

    force_reinstall = os.environ.get("SAGE_FORCE_RUNTIME_REINSTALL") == "1"
    if force_reinstall or not venv_python.is_file() or not _python_matches_bootstrap(venv_python):
        _write("SAGE PRE-CHECK")
        _write()
        _write("Python environment: NOT READY")
        if force_reinstall:
            _write("The Operator requested runtime installation again; rebuilding the managed environment.")
        elif venv_python.exists():
            _write("The managed localdata Python environment is incomplete or does not match the approved Python patch release; rebuilding it deterministically.")
        else:
            _write("The managed SAGE Python environment has not been created; creating it deterministically.")
        if not _create_venv(root):
            return _blocked("Could not create the managed localdata Python environment with the available Python interpreter.")
        venv_python = _venv_python(root)
        if not venv_python.is_file() or not _python_matches_bootstrap(venv_python):
            return _blocked("The newly created managed Python environment could not be validated.")

    if not _pip_is_available(venv_python):
        _write("SAGE PRE-CHECK")
        _write()
        _write("Python environment: INCOMPLETE")
        _write("pip is unavailable inside the managed SAGE Python environment; repairing it deterministically.")
        if not _ensure_pip(venv_python):
            return _blocked("pip is unavailable inside the managed localdata Python environment and repair failed.")

    # Validate base dependencies independently from optional interface profiles so fallback remains runnable.
    requirement_files = [requirements]
    if supplemental_requirements is not None:
        requirement_files.append(supplemental_requirements)

    validation_rows = [(path, *_requirements_status(venv_python, path)) for path in requirement_files]
    requirements_ok = all(row[1] for row in validation_rows)
    missing = [item for path, _ready, details in validation_rows for item in details]
    pip_ok, pip_detail = _pip_check(venv_python)
    imports_ok, import_details = True, []
    if requirements_ok and pip_ok:
        quarantined_runtime = _macos_quarantine_tree_path(layout.venv_root)
        if quarantined_runtime is not None:
            return _blocked(
                f"macOS quarantine is attached inside the managed Python environment: {quarantined_runtime}",
                "SAGE stopped before importing native Python dependencies and did not bypass Gatekeeper.",
                "Verify the release checksum, then follow app/docs/macos-linux/RECOVERY.md to authorize this exact SAGE copy.",
            )
        imports_ok, import_details = _dependency_import_status(venv_python, requirement_files)
    if not requirements_ok or not pip_ok or not imports_ok:
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
        if not imports_ok:
            _write("Runtime import validation:")
            for line in import_details:
                _write(f"  - {line}")
        _write("Synchronizing the managed environment to the pinned dependency manifests.")
        force_dependency_reinstall = not pip_ok or not imports_ok
        for path, ready, _details in validation_rows:
            if (not ready or force_dependency_reinstall) and not _install_requirements(
                venv_python,
                path,
                force_reinstall=force_dependency_reinstall,
            ):
                return _blocked("Dependency installation failed. See the platform ERRORS.md cheat sheet.")
        validation_rows = [(path, *_requirements_status(venv_python, path)) for path in requirement_files]
        requirements_ok = all(row[1] for row in validation_rows)
        missing = [item for path, _ready, details in validation_rows for item in details]
        pip_ok, pip_detail = _pip_check(venv_python)
        imports_ok, import_details = True, []
        if requirements_ok and pip_ok:
            quarantined_runtime = _macos_quarantine_tree_path(layout.venv_root)
            if quarantined_runtime is not None:
                return _blocked(
                    f"macOS quarantine is attached inside the repaired Python environment: {quarantined_runtime}",
                    "SAGE stopped before importing native Python dependencies and did not bypass Gatekeeper.",
                    "Verify the release checksum, then follow app/docs/macos-linux/RECOVERY.md to authorize this exact SAGE copy.",
                )
            imports_ok, import_details = _dependency_import_status(venv_python, requirement_files)
        if not requirements_ok or not pip_ok or not imports_ok:
            details = missing or import_details or ([pip_detail] if pip_detail else [])
            return _blocked("The repaired environment still failed validation.", *details)

    release_receipt = _apply_pre_release_boundary(root)
    if supplemental_requirements is None:
        _write_runtime_state(root, venv_python, requirements)
    else:
        _write_runtime_state(
            root,
            venv_python,
            requirements,
            profile=normalized_profile,
            supplemental_requirements=supplemental_requirements,
        )
    host_capability = detect_host_capability()
    _write_host_capability(root, host_capability)
    python_version = _python_version(venv_python)
    _write("SAGE PRE-CHECK")
    _write()
    _write("Python environment: READY")
    _write(f"SAGE app root: {root}")
    _write(f"SAGE localdata root: {layout.data_root}")
    _write(f"Managed environment: {layout.venv_root}")
    _write(f"Python: {python_version}")
    _write(f"Python runtime provider: {os.environ.get('SAGE_PYTHON_RUNTIME_PROVIDER') or 'sage-managed'}")
    _write(f"Dependency profile: {normalized_profile.upper()}")
    _write(f"Host capability: {host_capability['profile']}")
    if release_receipt.get("status") != "NOT_APPLICABLE":
        _write(f"Pre-release state policy: {release_receipt.get('policy')}")
        if release_receipt.get("version_changed"):
            _write("Pre-release version changed: persistent localdata PRESERVED")
        else:
            _write("Pre-release operator/project state: PRESERVED / CURRENT")
    return 0


def _looks_like_sage_root(path: Path) -> bool:
    """Return True when path contains the immutable package anchors needed by bootstrap."""
    return (
        (path / "VERSION").is_file()
        and (path / "system" / "requirements.txt").is_file()
        and (path / "system" / "tools" / "bootstrap_runtime.py").is_file()
    )


def _resolve_cli_root(requested: Path | None) -> Path:
    """Resolve the package root, recovering safely from legacy Windows quoting defects."""
    if requested is None:
        return Path(__file__).resolve().parents[2]
    requested_resolved = requested.resolve()
    if _looks_like_sage_root(requested_resolved):
        return requested_resolved
    cwd = Path.cwd().resolve()
    # Legacy Windows cmd.exe quoting could merge the closing quote/profile into argv
    # when the quoted root ended in a backslash. Recover only for that recognizable
    # malformed-argument shape; otherwise preserve fail-closed root validation.
    if '"' in str(requested) and cwd != requested_resolved and _looks_like_sage_root(cwd):
        _write("SAGE PRE-CHECK")
        _write()
        _write("Launcher root argument was invalid; recovered the SAGE root from the current working directory.")
        _write(f"Recovered SAGE root: {cwd}")
        return cwd
    return requested_resolved


def _explicit_data_home_from_args(args: list[str]) -> str | None:
    """Read a global --data-home option early enough for bootstrap/runtime resolution."""
    for index, value in enumerate(args):
        if value.startswith("--data-home="):
            return value.split("=", 1)[1].strip() or None
        if value == "--data-home" and index + 1 < len(args):
            return args[index + 1].strip() or None
    return None


def main(argv: list[str] | None = None) -> int:
    """Run bootstrap and optionally launch the SAGE CLI inside the managed environment."""
    args = list(sys.argv[1:] if argv is None else argv)
    requested = Path(args[0]) if args else None
    root = _resolve_cli_root(requested)
    profile = args[1] if len(args) > 1 else "base"
    launch = "--launch" in args[2:]
    python_shell = "--python-shell" in args[2:]
    app_args: list[str] = []
    if launch:
        marker = args.index("--launch", 2)
        app_args = args[marker + 1 :]
        explicit_data = _explicit_data_home_from_args(app_args)
        if explicit_data:
            os.environ[DATA_HOME_ENV] = explicit_data
        elif "data-home" in app_args and "reset" in app_args:
            # Recovery must work even when a persisted custom volume is currently unavailable.
            clear_persisted_data_home(root)
    if python_shell:
        status = ensure_runtime(root, profile=profile)
        if status != 0:
            return status
        layout = storage_layout(root, create=True)
        os.environ[DATA_HOME_ENV] = str(layout.data_root)
        python = _venv_python(root)
        marker = args.index("--python-shell", 2)
        shell_args = args[marker + 1 :]
        result = subprocess.run([str(python), *shell_args], cwd=str(root), check=False)
        return int(result.returncode)
    status = ensure_runtime(root, profile=profile)
    if status != 0 or not launch:
        return status
    layout = storage_layout(root, create=True)
    os.environ[DATA_HOME_ENV] = str(layout.data_root)
    python = _venv_python(root)
    result = subprocess.run([str(python), "-m", "sage.cli", *app_args], cwd=str(root), check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
