"""Allowlisted deterministic release-builder tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.source_release


def test_release_builder_excludes_runtime_and_operator_scripture_but_bundles_ol(
    package_root: Path, tmp_path: Path
) -> None:
    """Verify that release builder includes only governed OL Scripture resources."""
    output = tmp_path / f"SAGE-v{(package_root / 'VERSION').read_text(encoding='utf-8').strip()}.zip"
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["SAGE_TEST_SKIP_BUILD_HARDENING"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(package_root / "system" / "tools" / "build_release.py"),
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
        prefix = f"SAGE-v{(package_root / 'VERSION').read_text(encoding='utf-8').strip()}-Full-Distribution"
        assert f"{prefix}/.gitattributes" in names
        assert f"{prefix}/README.md" in names
        assert f"{prefix}/sage" in names
        assert f"{prefix}/sage.cmd" in names
        assert f"{prefix}/app/docs/macos-linux/CHEAT-SHEET.md" in names
        assert f"{prefix}/app/docs/windows/CHEAT-SHEET.md" in names
        assert f"{prefix}/START-HERE.md" not in names
        assert not any(name.startswith(f"{prefix}/jobs/") for name in names)
        assert not any(name.startswith(f"{prefix}/reports/") for name in names)
        assert not any(name.startswith(f"{prefix}/workspace_data/") for name in names)
        assert [name for name in names if name.startswith(f"{prefix}/localdata/")] == [
            f"{prefix}/localdata/README.md"
        ]
        assert not any(name.startswith(f"{prefix}/projects/") for name in names)
        expected_executable = {
            "sage",
            "app/sage-python",
            "app/system/bin/sage",
            "app/system/bin/bic",
            "app/system/bin/saw",
            "app/system/tools/clone_and_install.sh",
        }
        actual_executable = set()
        for member in archive.infolist():
            if member.is_dir():
                continue
            relative = member.filename.removeprefix(f"{prefix}/")
            permissions = (member.external_attr >> 16) & 0o777
            assert member.create_system == 3
            assert permissions in {0o644, 0o755}
            if permissions == 0o755:
                actual_executable.add(relative)
        assert actual_executable == expected_executable
    scripture = [name for name in names if name.lower().endswith((".sfm", ".usfm"))]
    assert scripture
    assert all(
        f"{prefix}/app/system/resources/scripture/original-language/grk/" in name
        or f"{prefix}/app/system/resources/scripture/original-language/heb/" in name
        for name in scripture
    )
    assert sum("/grk/" in name for name in scripture) == 27
    assert sum("/heb/" in name for name in scripture) == 39
    assert not any("__pycache__" in name or ".pytest_cache" in name for name in names)
    assert not any("/.venv/" in name or name.endswith("/.venv") for name in names)
    assert not any(name.lower().endswith(".zip") for name in names)


def test_windows_launchers_use_crlf(package_root: Path) -> None:
    """Verify that windows launchers use crlf."""
    bundle_root = package_root.parent
    paths = (
        bundle_root / "sage.cmd",
        package_root / "sage-python.cmd",
        package_root / "system/bin/sage.cmd",
        package_root / "system/bin/bic.cmd",
        package_root / "system/bin/saw.cmd",
    )
    for path in paths:
        payload = path.read_bytes()
        assert b"\r\n" in payload
        assert b"\n" not in payload.replace(b"\r\n", b"")


def test_posix_launchers_are_executable(package_root: Path) -> None:
    """Verify that POSIX launchers are executable."""
    paths = (
        package_root.parent / "sage",
        package_root / "sage-python",
        package_root / "system/bin/sage",
        package_root / "system/bin/bic",
        package_root / "system/bin/saw",
    )
    for path in paths:
        assert os.access(path, os.X_OK)


def test_workflow_launchers_have_current_help(package_root: Path) -> None:
    """Verify that workflow launchers have current help."""
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for name, label in (("bic", "BIC"), ("saw", "SAW")):
        result = subprocess.run(
            [str(package_root / "system" / "bin" / name), "--help"],
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
                str(package_root / "system" / "tools" / "build_release.py"),
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


def _load_release_builder(package_root: Path):
    """Load the release builder directly so receipt validation can be tested without a package build."""
    path = package_root / "system" / "tools" / "build_release.py"
    spec = importlib.util.spec_from_file_location("sage_test_build_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_formal_hardening_receipt_validation_requires_exact_hash_and_complete_gate(
    package_root: Path, tmp_path: Path
) -> None:
    """Accept only a zero-warning formal combine receipt that covers the exact staged source tree."""
    builder = _load_release_builder(package_root)
    source_hash = builder._source_tree_sha256(package_root)
    receipt = {
        "status": "PASS",
        "formal_combine": "PASS",
        "source_tree_sha256": source_hash,
        "governed_source_unchanged": True,
        "test_modules_scheduled_exactly_once": True,
        "schema_validation": "PASS",
        "package_validation": "PASS",
        "deep_audit": "PASS",
        "test_files_discovered": 60,
        "test_files_scheduled": 60,
        "test_cases_discovered": 627,
        "tests_passed": 625,
        "tests_skipped": 2,
        "tests_failed": 0,
        "errors": [],
        "warnings": [],
    }
    path = tmp_path / "combine.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    ok, loaded = builder._validate_hardening_receipt(path, expected_hash=source_hash)
    assert ok is True
    assert isinstance(loaded, dict) and loaded["source_tree_sha256"] == source_hash

    receipt["source_tree_sha256"] = "0" * 64
    path.write_text(json.dumps(receipt), encoding="utf-8")
    ok, detail = builder._validate_hardening_receipt(path, expected_hash=source_hash)
    assert ok is False
    assert isinstance(detail, dict) and detail["reason"] == "HARDENING_RECEIPT_INVALID"


def test_release_builder_exposes_formal_receipt_reuse_option(package_root: Path) -> None:
    """Keep post-qualification packaging able to reuse an exact formal-combine receipt."""
    text = (package_root / "system" / "tools" / "build_release.py").read_text(encoding="utf-8")
    assert '"--hardening-receipt"' in text
    assert "_validate_hardening_receipt" in text
