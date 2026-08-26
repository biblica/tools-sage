#!/usr/bin/env python3
"""Clone SAGE, bootstrap its external SAGEdata runtime, and optionally bind Paratext Projects."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MIN_PYTHON = (3, 10)
VANILLA_MODE = "vanilla"
NEW_HOST_MODE = "new-host"
MODE_ALIASES = {
    "1": VANILLA_MODE,
    "clean": VANILLA_MODE,
    "clean-workspace": VANILLA_MODE,
    VANILLA_MODE: VANILLA_MODE,
    "2": NEW_HOST_MODE,
    NEW_HOST_MODE: NEW_HOST_MODE,
    "new_host": NEW_HOST_MODE,
}
DATA_HOME_ENV = "SAGE_DATA_HOME"


def _check_python_version() -> bool:
    """Return whether the invoking system Python meets SAGE minimum requirements."""
    if sys.version_info >= MIN_PYTHON:
        return True
    print(
        f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
        f"but {sys.version_info.major}.{sys.version_info.minor} found.",
        file=sys.stderr,
    )
    return False


def _check_git() -> bool:
    """Return whether Git is callable from the current host PATH."""
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        result = None
    if result is not None and result.returncode == 0:
        return True
    print("ERROR: Git is not installed or not in PATH.", file=sys.stderr)
    return False


def _normalise_mode(value: str) -> str | None:
    """Map one operator mode token to its canonical install mode."""
    return MODE_ALIASES.get(value.strip().casefold())


def _choose_mode(requested: str | None) -> str | None:
    """Resolve the requested install mode, prompting only on an interactive terminal."""
    if requested:
        mode = _normalise_mode(requested)
        if mode is None:
            print("ERROR: --mode must be vanilla or new-host.", file=sys.stderr)
        return mode
    if not sys.stdin.isatty():
        return VANILLA_MODE
    print("SAGE CLONE")
    print("1  Standard installation")
    print("2  New host / bind an existing Paratext Projects folder")
    try:
        return _normalise_mode(input("Select 1 or 2: "))
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return None


def _normalise_operator_path(value: str) -> str:
    """Normalize common shell quoting and escaped-space forms in an operator path."""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    if os.name != "nt":
        text = text.replace(r"\ ", " ")
    return text


def _absolute_existing_directory(value: str, label: str) -> Path:
    """Validate one operator path as an existing absolute directory."""
    candidate = Path(_normalise_operator_path(value)).expanduser()
    if not candidate.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise ValueError(f"{label} was not found: {resolved}")
    return resolved


def _choose_projects_root(requested: str | None) -> Path | None:
    """Resolve the external Paratext Projects root for new-host binding."""
    value = requested
    if not value and sys.stdin.isatty():
        try:
            value = input("Paratext Projects folder on this host: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return None
    if not value:
        print("ERROR: --paratext-projects-root is required for --mode new-host.", file=sys.stderr)
        return None
    try:
        return _absolute_existing_directory(value, "Paratext Projects folder")
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return None


def _clone_repository(repo_url: str, target_dir: Path) -> bool:
    """Clone the requested repository into a new target and clean incomplete failures."""
    if target_dir.exists():
        print(f"ERROR: Target directory already exists: {target_dir}", file=sys.stderr)
        return False
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Cloning SAGE repository to: {target_dir}")
    try:
        result = subprocess.run(["git", "clone", "--", repo_url, str(target_dir)], check=False)
    except OSError as exc:
        print(f"ERROR: Clone operation failed: {exc}", file=sys.stderr)
        result = None
    if result is not None and result.returncode == 0:
        return True
    if target_dir.exists():
        shutil.rmtree(target_dir)
    print("ERROR: Repository clone failed; incomplete target removed.", file=sys.stderr)
    return False


def _data_home(root: Path, requested: str | None) -> Path:
    """Resolve an explicit absolute data home or the default sibling SAGEdata directory."""
    if requested:
        value = Path(_normalise_operator_path(requested)).expanduser()
        if not value.is_absolute():
            raise ValueError("--data-home must be an absolute path")
        data = value.resolve()
    else:
        data = root.parent / "SAGEdata"
    try:
        data.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("SAGEdata must be outside the Git-controlled SAGE directory")
    return data


def _environment(data_home: Path) -> dict[str, str]:
    """Build the deterministic bootstrap environment for the selected SAGEdata root."""
    env = dict(os.environ)
    env[DATA_HOME_ENV] = str(data_home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _venv_python(data_home: Path) -> Path:
    """Return the platform-native interpreter inside SAGEdata managed runtime."""
    if platform.system() == "Windows":
        return data_home / ".system" / "runtime" / "venv" / "Scripts" / "python.exe"
    return data_home / ".system" / "runtime" / "venv" / "bin" / "python"


def _run_bootstrap(root: Path, data_home: Path) -> bool:
    """Run the standard SAGE bootstrap against the selected external data home."""
    result = subprocess.run(
        [sys.executable, str(root / "system" / "tools" / "bootstrap_runtime.py"), str(root)],
        cwd=root,
        env=_environment(data_home),
        check=False,
    )
    return result.returncode == 0


def _persist_custom_data_home(root: Path, data_home: Path) -> bool:
    """Persist a non-default data-home pointer without moving operator data."""
    if data_home == root.parent / "SAGEdata":
        return True
    python = _venv_python(data_home)
    result = subprocess.run(
        [str(python), "-m", "sage.cli", "--data-home", str(data_home), "data-home", "set", str(data_home)],
        cwd=root,
        env=_environment(data_home),
        check=False,
    )
    return result.returncode == 0


def _configure_projects_root(root: Path, data_home: Path, projects_root: Path) -> bool:
    """Bind existing Paratext Projects through the governed new-host portability flow."""
    python = _venv_python(data_home)
    program = "\n".join(
        (
            "import sys",
            "from pathlib import Path",
            "sage_root = Path(sys.argv[1]).resolve()",
            "sys.path.insert(0, str(sage_root / 'system' / 'src'))",
            "from sage.errors import SageError",
            "from sage.portability import rebind_new_host_projects",
            "try:",
            "    result = rebind_new_host_projects(sage_root, Path(sys.argv[2]))",
            "except SageError as exc:",
            "    print(f'ERROR [{exc.code}]: {exc}', file=sys.stderr)",
            "    raise SystemExit(1)",
            "print(f\"Rebound Job Projects: {result['rebound_projects']}\")",
        )
    )
    result = subprocess.run(
        [str(python), "-c", program, str(root), str(projects_root)],
        cwd=root,
        env=_environment(data_home),
        check=False,
    )
    return result.returncode == 0


def _validate_installation(root: Path, data_home: Path) -> bool:
    """Validate the managed interpreter, declared dependencies, version, and data boundary."""
    python = _venv_python(data_home)
    if not python.is_file():
        print("ERROR: Managed Python executable was not created.", file=sys.stderr)
        return False
    program = "\n".join(
        (
            "import sys",
            "from pathlib import Path",
            "sage_root = Path(sys.argv[1]).resolve()",
            "sys.path.insert(0, str(sage_root / 'system' / 'src'))",
            "import certifi, openpyxl, yaml, sage",
            "from sage.standard import load_standard",
            "from sage.storage import storage_layout",
            "standard = load_standard(sage_root)",
            "assert sage.__version__ == standard.version",
            "layout = storage_layout(sage_root, create=True)",
            "assert layout.data_root == Path(sys.argv[2]).resolve()",
        )
    )
    env = _environment(data_home)
    imports = subprocess.run([str(python), "-c", program, str(root), str(data_home)], cwd=root, env=env, check=False)
    consistency = subprocess.run([str(python), "-m", "pip", "check"], cwd=root, env=env, check=False)
    return imports.returncode == 0 and consistency.returncode == 0


def _managed_python_version(data_home: Path) -> str:
    """Return the managed runtime Python version for the installation receipt."""
    result = subprocess.run(
        [str(_venv_python(data_home)), "-c", "import platform; print(platform.python_version())"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"


def _write_install_receipt(root: Path, data_home: Path, *, success: bool, mode: str, projects_root: Path | None) -> Path:
    """Write a machine-local installation receipt without modifying Core."""
    state_dir = data_home / ".system" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    version_file = root / "VERSION"
    payload = {
        "schema_version": 2,
        "status": "READY" if success else "BLOCKED",
        "mode": mode,
        "sage_version": version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else None,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": _managed_python_version(data_home) if _venv_python(data_home).is_file() else None,
        "platform": platform.system(),
        "sage_root": str(root),
        "data_home": str(data_home),
        "paratext_projects_root": str(projects_root) if projects_root else None,
        "operator_data_policy": "PRESERVE_EXISTING_RECOGNIZED_SAGEDATA",
    }
    destination = state_dir / "installation.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def _print_completion(root: Path, data_home: Path, mode: str, projects_root: Path | None, receipt: Path) -> None:
    """Print platform-appropriate next-launch instructions after a successful clone."""
    print()
    print("SAGE CLONE COMPLETE")
    print(f"Mode: {mode}")
    print(f"SAGE root: {root}")
    print(f"SAGEdata: {data_home}")
    if projects_root:
        print(f"Paratext Projects folder: {projects_root}")
    print(f"Receipt: {receipt}")
    if platform.system() == "Windows":
        print(f'Next: cd /d "{root}"')
        print(r"Then: .\sage.cmd")
    else:
        print(f"Next: cd {shlex.quote(str(root))}")
        print("Then: ./sage")


def _parser() -> argparse.ArgumentParser:
    """Build the clone/install command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_url", help="Git repository URL or local repository path")
    parser.add_argument("target_directory", nargs="?", default="SAGE", help="New SAGE directory")
    parser.add_argument("--mode", help="Install mode: vanilla or new-host")
    parser.add_argument("--data-home", help="Absolute SAGEdata location; default is sibling SAGEdata")
    parser.add_argument("--paratext-projects-root", help="Existing absolute Paratext Projects folder for new-host mode")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Clone, bootstrap, bind optional host resources, validate, and record installation."""
    args = _parser().parse_args(argv)
    if not _check_python_version() or not _check_git():
        return 1
    mode = _choose_mode(args.mode)
    if mode is None:
        return 2
    projects_root = None
    if mode == NEW_HOST_MODE:
        projects_root = _choose_projects_root(args.paratext_projects_root)
        if projects_root is None:
            return 2
    elif args.paratext_projects_root:
        print("ERROR: --paratext-projects-root is valid only with --mode new-host.", file=sys.stderr)
        return 2
    target = Path(_normalise_operator_path(args.target_directory)).expanduser().resolve()
    if not _clone_repository(args.repo_url, target):
        return 1
    try:
        data_home = _data_home(target, args.data_home)
        if not _run_bootstrap(target, data_home):
            print(f"Retry by running the launcher inside: {target}", file=sys.stderr)
            return 1
        if not _persist_custom_data_home(target, data_home):
            print("ERROR: Could not persist the custom SAGEdata location.", file=sys.stderr)
            return 1
        if projects_root is not None and not _configure_projects_root(target, data_home, projects_root):
            return 1
        success = _validate_installation(target, data_home)
        receipt = _write_install_receipt(target, data_home, success=success, mode=mode, projects_root=projects_root)
    except (OSError, ValueError) as exc:
        print(f"ERROR: Installation failed: {exc}", file=sys.stderr)
        return 1
    if not success:
        return 1
    _print_completion(target, data_home, mode, projects_root, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
