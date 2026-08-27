"""Source-package hygiene and normative metadata tests."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from sage.standard import load_standard
from sage.validation import validate_package

pytestmark = pytest.mark.source_release


def test_package_validation_passes(package_root: Path) -> None:
    """Verify that package validation passes."""
    result = validate_package(package_root)
    assert result["status"] == "READY", result
    assert result["scripture_payloads"] == []
    assert result["nested_archives"] == []



def test_package_validation_rejects_legacy_provider_runtime_paths(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Verify deprecated provider-specific runtime roots cannot re-enter a source release."""
    import shutil

    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    legacy = copy / ".cline"
    legacy.mkdir()
    (legacy / "marker.txt").write_text("legacy", encoding="utf-8")
    result = validate_package(copy)
    assert result["status"] == "BLOCKED"
    assert result["legacy_provider_paths"] == [".cline"]




def test_vanilla_install_manifest_matches_source_tree(package_root: Path) -> None:
    """Verify the documented vanilla inventory exactly matches shipped source paths."""
    manifest = (package_root / "docs" / "advanced" / "release" / "VANILLA-INSTALL-MANIFEST.md").read_text(encoding="utf-8")
    documented = {
        match.group(1).rstrip("/")
        for match in re.finditer(r"^- `([^`]+)`$", manifest, re.MULTILINE)
    }
    ephemeral = {".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    actual = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if not any(part in ephemeral for part in path.relative_to(package_root).parts)
    }
    assert documented == actual, {
        "missing_from_manifest": sorted(actual - documented),
        "missing_from_source": sorted(documented - actual),
    }

def test_standard_version_matches_version_file(package_root: Path) -> None:
    """Verify that standard version matches version file."""
    standard = load_standard(package_root)
    assert standard.version == (package_root / "VERSION").read_text(encoding="utf-8").strip()
    assert standard.release_status == "BETA"
    assert standard.feature_classifications["tui"] == "EXPERIMENTAL_UNSTABLE"
    assert "EXPERIMENTAL_UNSTABLE" in standard.feature_maturity_states
    assert standard.public_release_ready is False
    assert "READY" in standard.operation_states
    assert "RESTRICTED" in standard.capability_states


def test_custom_vrs_files_are_not_centralized(package_root: Path) -> None:
    """Verify that custom VRS files are not centralized."""
    assert not (package_root / "versification" / "custom").exists()
    assert not list((package_root / "projects").glob("custom.vrs"))


def test_package_validation_rejects_internal_symbolic_links(package_root: Path, tmp_path: Path) -> None:
    """Verify that package validation rejects internal symbolic links."""
    import shutil
    import pytest

    root = tmp_path / "SAGE"
    shutil.copytree(package_root, root)
    link = root / "docs" / "linked-readme.md"
    try:
        link.symlink_to(root / "README.md")
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are unavailable on this host")
    result = validate_package(root)
    assert result["status"] == "BLOCKED"
    assert any("symbolic link" in item.lower() for item in result["errors"])


def test_package_validation_rejects_external_symbolic_links(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """The allowlisted builder must not follow links to external content."""
    import shutil

    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    secret = tmp_path / "secret.txt"
    secret.write_text("not package content", encoding="utf-8")
    (copy / "docs" / "external.md").symlink_to(secret)
    result = validate_package(copy)
    assert result["status"] == "BLOCKED"
    assert result["symlinks"] == ["docs/external.md"]


def test_package_validation_rejects_coverage_artifacts(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Coverage products must never be distributed in a SAGE release."""
    import shutil

    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    (copy / ".coverage").write_text("runtime data", encoding="utf-8")
    result = validate_package(copy)
    assert result["status"] == "BLOCKED"
    assert ".coverage" in result["artifacts"]


def test_package_validation_ignores_ephemeral_test_caches(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Repeated or reordered test runs must not change package readiness."""
    import shutil

    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    (copy / ".pytest_cache").mkdir()
    (copy / ".pytest_cache" / "README.md").write_text("cache", encoding="utf-8")
    bytecode = copy / "system" / "src" / "sage" / "__pycache__" / "validation.pyc"
    bytecode.parent.mkdir(parents=True, exist_ok=True)
    bytecode.write_bytes(b"cache")
    result = validate_package(copy)
    assert result["status"] == "READY", result
    assert result["artifacts"] == []


def test_package_validation_rejects_previous_pre_release_named_artifacts(package_root: Path, tmp_path: Path) -> None:
    """Verify that earlier pre-release scripts or reports cannot re-enter the source package."""
    import shutil

    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    stale_name = "rc" + "6.04-stale-helper.py"
    stale = copy / "system" / "tools" / stale_name
    stale.write_text("print('stale')\n", encoding="utf-8")
    result = validate_package(copy)
    assert result["status"] == "BLOCKED"
    assert result["stale_pre_release_artifacts"] == [f"system/tools/{stale_name}"]


def test_source_release_contains_no_preconfigured_project_state_or_workflow_fixtures(package_root: Path) -> None:
    """Verify the alpha source tree starts without bundled operator data or workflow bindings."""
    import yaml

    raw = yaml.safe_load((package_root / "ecosystem.yml").read_text(encoding="utf-8"))
    assert raw.get("projects") == {}
    for local_root in (".venv", "workspace_data", "jobs", "reports", "localdata"):
        assert not (package_root / local_root).exists()
    assert not list((package_root / "system" / "config" / "workflows").rglob("*resource-test*"))


def test_source_audit_rejects_job_runtime_payloads(package_root: Path, tmp_path: Path) -> None:
    """A clean source audit must reject complete or partial Job directories."""
    import shutil
    import subprocess
    import sys

    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    stale_job = copy / "jobs" / "saw" / "SAW_stale-source-stale-reference"
    stale_job.mkdir(parents=True)
    (stale_job / "job.yml").write_text("schema_version: '1.0'\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(copy / "system" / "tools" / "deep_audit.py"),
            str(copy),
            "--mode",
            "source",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Clean source contains local/runtime roots: jobs" in result.stdout


def test_current_menu_does_not_contain_legacy_resource_mapping_surface(package_root: Path) -> None:
    """Verify the old resource chooser cannot reappear through a duplicate current entry point."""
    text = (package_root / "system" / "src" / "sage" / "menu.py").read_text(encoding="utf-8")
    assert "Map Paratext/PTLite project folder" not in text
    assert "Select Scripture resource" not in text
    assert "Add Projects to SAGE" in text
    assert '("3","Remove Project from SAGE")' in text
    assert '("6","Paratext Projects root")' in text
    assert "Original-language resources" in text
    assert '("7","Scan Paratext Projects")' in text


def test_textual_dependency_is_supplemental_to_classic_runtime(package_root: Path) -> None:
    """Verify a TUI dependency failure cannot invalidate the classic base dependency set."""
    base = (package_root / "system" / "requirements.txt").read_text(encoding="utf-8").casefold()
    tui = (package_root / "system" / "requirements-tui.txt").read_text(encoding="utf-8").casefold()
    pyproject = (package_root / "system" / "pyproject.toml").read_text(encoding="utf-8").casefold()

    assert "textual" not in base
    assert "textual==8.2.8" in tui
    assert "[project.optional-dependencies]" in pyproject
    assert 'tui = ["textual==8.2.8"]' in pyproject
