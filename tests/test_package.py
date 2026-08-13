"""Source-package hygiene and normative metadata tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_core.standard import load_standard
from sage_core.validation import validate_package

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


def test_standard_version_matches_version_file(package_root: Path) -> None:
    """Verify that standard version matches version file."""
    standard = load_standard(package_root)
    assert standard.version == (package_root / "VERSION").read_text(encoding="utf-8").strip()
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
    bytecode = copy / "core" / "sage_core" / "__pycache__" / "validation.pyc"
    bytecode.parent.mkdir(parents=True, exist_ok=True)
    bytecode.write_bytes(b"cache")
    result = validate_package(copy)
    assert result["status"] == "READY", result
    assert result["artifacts"] == []


def test_package_validation_rejects_previous_rc_named_artifacts(package_root: Path, tmp_path: Path) -> None:
    """Verify that prior release-candidate scripts or reports cannot re-enter the source package."""
    import shutil

    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    stale_name = "rc" + "6.04-stale-helper.py"
    stale = copy / "scripts" / stale_name
    stale.write_text("print('stale')\n", encoding="utf-8")
    result = validate_package(copy)
    assert result["status"] == "BLOCKED"
    assert result["stale_rc_artifacts"] == [f"scripts/{stale_name}"]


def test_source_release_contains_no_preconfigured_project_state_or_workflow_fixtures(package_root: Path) -> None:
    """Verify RC source distribution starts with no operator Project data or resource-test workflow bindings."""
    import yaml

    raw = yaml.safe_load((package_root / "ecosystem.yml").read_text(encoding="utf-8"))
    assert raw.get("projects") == {}
    assert not (package_root / "state").exists()
    assert not list((package_root / "workflows").rglob("*resource-test*"))
    assert not list((package_root / "jobs" / "bic").glob("*/job.yml"))
    assert not list((package_root / "jobs" / "saw").glob("*/job.yml"))


def test_current_menu_does_not_contain_legacy_resource_mapping_surface(package_root: Path) -> None:
    """Verify the old RC resource chooser cannot reappear through a duplicate current entry point."""
    text = (package_root / "core" / "sage_core" / "menu.py").read_text(encoding="utf-8")
    assert "Map Paratext/PTLite project folder" not in text
    assert "Select Scripture resource" not in text
    assert "Add Projects to SAGE" in text
    assert "Original-language resources" in text
    assert "Scan / Rescan Paratext Projects" in text
