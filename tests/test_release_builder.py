"""Allowlisted deterministic release-builder tests."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.source_release


def test_release_builder_excludes_runtime_and_scripture(package_root: Path, tmp_path: Path) -> None:
    """Verify that release builder excludes runtime and scripture."""
    output = tmp_path / f"SAGE-v{(package_root / 'VERSION').read_text(encoding='utf-8').strip()}.zip"
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["SAGE_TEST_SKIP_BUILD_HARDENING"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(package_root / "scripts" / "build_release.py"),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert output.exists()
    assert output.with_suffix(".zip.sha256").exists()
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert archive.testzip() is None
        prefix = f"SAGE-v{(package_root / 'VERSION').read_text(encoding='utf-8').strip()}-Standalone-CLI-Source"
        assert f"{prefix}/README.md" in names
        assert f"{prefix}/docs/macos-linux/CHEAT-SHEET.md" in names
        assert f"{prefix}/docs/windows/CHEAT-SHEET.md" in names
        assert f"{prefix}/START-HERE.md" not in names
        assert f"{prefix}/jobs/README.md" in names
        assert f"{prefix}/jobs/bic/README.md" in names
        assert f"{prefix}/jobs/saw/README.md" in names
        assert f"{prefix}/workspace-data/scripture-projects/README.md" in names
        assert not any(name.startswith(f"{prefix}/projects/") for name in names)
        for name in ("sage", "bic", "saw"):
            permissions = (archive.getinfo(f"{prefix}/{name}").external_attr >> 16) & 0o777
            assert permissions == 0o755
    assert not any(name.lower().endswith((".sfm", ".usfm")) for name in names)
    assert not any("__pycache__" in name or ".pytest_cache" in name for name in names)
    assert not any("/.venv/" in name or name.endswith("/.venv") for name in names)
    assert not any(name.lower().endswith(".zip") for name in names)


def test_windows_launchers_use_crlf(package_root: Path) -> None:
    """Verify that windows launchers use crlf."""
    for name in ("sage.cmd", "bic.cmd", "saw.cmd"):
        payload = (package_root / name).read_bytes()
        assert b"\r\n" in payload
        assert b"\n" not in payload.replace(b"\r\n", b"")


def test_posix_launchers_are_executable(package_root: Path) -> None:
    """Verify that POSIX launchers are executable."""
    for name in ("sage", "bic", "saw"):
        assert os.access(package_root / name, os.X_OK)


def test_workflow_launchers_have_current_help(package_root: Path) -> None:
    """Verify that workflow launchers have current help."""
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for name, label in (("bic", "BIC"), ("saw", "SAW")):
        result = subprocess.run(
            [str(package_root / name), "--help"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert result.stdout.startswith(f"usage: {name} ")
        assert "status" in result.stdout
        assert "submit" in result.stdout


def test_release_builder_is_byte_deterministic(package_root: Path, tmp_path: Path) -> None:
    """Two clean builds from the same tree must produce identical ZIP bytes."""
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["SAGE_TEST_SKIP_BUILD_AUDIT"] = "1"
    environment["SAGE_TEST_SKIP_BUILD_HARDENING"] = "1"
    outputs = [tmp_path / "first.zip", tmp_path / "second.zip"]
    for output in outputs:
        result = subprocess.run(
            [
                sys.executable,
                str(package_root / "scripts" / "build_release.py"),
                "--output",
                str(output),
            ],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        assert result.returncode == 0, result.stderr + result.stdout
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    assert not list(tmp_path.glob(".*.tmp"))
