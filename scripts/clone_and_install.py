#!/usr/bin/env python3
"""Clone SAGE repository and perform a clean installation with full setup."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MIN_PYTHON = (3, 10)


def _check_python_version() -> bool:
    """Verify Python version meets minimum requirement."""
    version_info = sys.version_info
    if version_info >= MIN_PYTHON:
        return True
    print(
        f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
        f"but {version_info.major}.{version_info.minor} found.",
        file=sys.stderr,
    )
    return False


def _check_git() -> bool:
    """Verify git is available."""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    print("ERROR: git is not installed or not in PATH.", file=sys.stderr)
    return False


def _clone_repository(repo_url: str, target_dir: Path) -> bool:
    """Clone the SAGE repository."""
    if target_dir.exists():
        print(
            f"ERROR: Target directory already exists: {target_dir}",
            file=sys.stderr,
        )
        return False

    print(f"Cloning SAGE repository to: {target_dir}")
    try:
        result = subprocess.run(
            ["git", "clone", repo_url, str(target_dir)],
            check=False,
        )
        if result.returncode != 0:
            print("ERROR: Repository clone failed.", file=sys.stderr)
            return False
    except Exception as e:
        print(f"ERROR: Clone operation failed: {e}", file=sys.stderr)
        return False

    print(f"✓ Repository cloned successfully to {target_dir}")
    return True


def _create_venv(root: Path) -> bool:
    """Create Python virtual environment."""
    venv_path = root / ".venv"

    if venv_path.exists():
        print(f"Virtual environment already exists at {venv_path}")
        return True

    print(f"Creating virtual environment at {venv_path}")
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to create virtual environment: {e}", file=sys.stderr)
        return False

    print("✓ Virtual environment created successfully")
    return True


def _get_venv_python(root: Path) -> Path | None:
    """Get the Python executable path from the virtual environment."""
    if platform.system() == "Windows":
        python_exe = root / ".venv" / "Scripts" / "python.exe"
    else:
        python_exe = root / ".venv" / "bin" / "python"

    if python_exe.exists():
        return python_exe

    return None


def _install_dependencies(root: Path) -> bool:
    """Install Python dependencies in the virtual environment."""
    python_exe = _get_venv_python(root)
    if not python_exe:
        print(
            "ERROR: Virtual environment Python executable not found.",
            file=sys.stderr,
        )
        return False

    requirements_file = root / "requirements.txt"
    if not requirements_file.exists():
        print(
            f"ERROR: requirements.txt not found at {requirements_file}",
            file=sys.stderr,
        )
        return False

    print(f"Installing dependencies from {requirements_file}")
    try:
        subprocess.run(
            [str(python_exe), "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
        )
        subprocess.run(
            [str(python_exe), "-m", "pip", "install", "-r", str(requirements_file)],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Dependency installation failed: {e}", file=sys.stderr)
        return False

    print("✓ Dependencies installed successfully")
    return True


def _install_dev_dependencies(root: Path) -> bool:
    """Install development dependencies."""
    python_exe = _get_venv_python(root)
    if not python_exe:
        return False

    requirements_dev_file = root / "requirements-dev.txt"
    if not requirements_dev_file.exists():
        print(f"INFO: No development requirements file found at {requirements_dev_file}")
        return True

    print(f"Installing development dependencies from {requirements_dev_file}")
    try:
        subprocess.run(
            [str(python_exe), "-m", "pip", "install", "-r", str(requirements_dev_file)],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"WARNING: Development dependency installation failed: {e}", file=sys.stderr)
        return False

    print("✓ Development dependencies installed successfully")
    return True


def _validate_installation(root: Path) -> bool:
    """Validate the SAGE installation."""
    python_exe = _get_venv_python(root)
    if not python_exe:
        print("ERROR: Virtual environment validation failed.", file=sys.stderr)
        return False

    print("Validating SAGE installation...")
    try:
        result = subprocess.run(
            [str(python_exe), "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"],
            check=False,
        )
        if result.returncode != 0:
            print(
                "ERROR: Python 3.10+ validation failed in virtual environment.",
                file=sys.stderr,
            )
            return False
    except Exception as e:
        print(f"ERROR: Installation validation failed: {e}", file=sys.stderr)
        return False

    # Verify core module exists
    core_module = root / "core" / "sage_core"
    if not core_module.is_dir():
        print(f"ERROR: Core module not found at {core_module}", file=sys.stderr)
        return False

    print("✓ Installation validation passed")
    return True


def _write_install_log(root: Path, success: bool) -> None:
    """Write installation log to state directory."""
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    log_file = state_dir / "installation.json"
    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": success,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.system(),
        "root_directory": str(root),
    }

    try:
        log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"WARNING: Failed to write installation log: {e}", file=sys.stderr)


def _print_completion_message(root: Path, success: bool) -> None:
    """Print completion message with next steps."""
    if not success:
        print("\n" + "=" * 70, file=sys.stderr)
        print("INSTALLATION FAILED", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("\nPlease check the errors above and try again.", file=sys.stderr)
        return

    print("\n" + "=" * 70)
    print("SAGE INSTALLATION COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print(f"\nInstallation directory: {root}")
    print("\nNext steps:")
    print("1. Navigate to the installation directory:")
    print(f"   cd {root}")
    print("\n2. Test the installation:")
    if platform.system() == "Windows":
        print("   sage.cmd status")
    else:
        print("   ./sage status")
    print("\n3. To use SAGE workflows:")
    if platform.system() == "Windows":
        print("   bic.cmd help       (for Bible Interchange Control)")
        print("   saw.cmd help       (for Scripture Alignment Workflow)")
    else:
        print("   ./bic help         (for Bible Interchange Control)")
        print("   ./saw help         (for Scripture Alignment Workflow)")
    print("\nFor more information, see the README.md in the installation directory.")
    print("=" * 70 + "\n")


def main() -> int:
    """Main installation entry point."""
    # Parse arguments
    if len(sys.argv) < 2:
        print(
            "Usage: clone_and_install.py <repo_url> [target_directory]",
            file=sys.stderr,
        )
        print(
            "\nExample:",
            file=sys.stderr,
        )
        print(
            "  python clone_and_install.py https://github.com/biblica/tools-sage.git ./sage",
            file=sys.stderr,
        )
        return 2

    repo_url = sys.argv[1]
    target_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd() / "sage"

    # Pre-flight checks
    print("SAGE Clean Installation")
    print("=" * 70)
    print("\nPerforming pre-flight checks...")

    if not _check_python_version():
        return 1

    if not _check_git():
        return 1

    print("✓ Python version check passed")
    print("✓ Git availability check passed")

    # Clone repository
    print("\n" + "-" * 70)
    if not _clone_repository(repo_url, target_dir):
        return 1

    # Setup virtual environment
    print("\n" + "-" * 70)
    if not _create_venv(target_dir):
        return 1

    # Install dependencies
    print("\n" + "-" * 70)
    if not _install_dependencies(target_dir):
        return 1

    # Install dev dependencies (optional)
    print("\n" + "-" * 70)
    _install_dev_dependencies(target_dir)

    # Validate installation
    print("\n" + "-" * 70)
    success = _validate_installation(target_dir)

    # Write log
    _write_install_log(target_dir, success)

    # Print completion message
    _print_completion_message(target_dir, success)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
