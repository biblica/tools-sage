"""Projects-root base VRS and project-local custom VRS tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sage_core.errors import ConfigurationError
from sage_core.registry import load_ecosystem
from sage_core.vrs import VerseRef, load_project_vrs, parse_vrs_file, resolve_project_vrs_paths


def test_auto_custom_vrs_resolves_inside_project(make_workspace) -> None:
    """Verify that auto custom VRS resolves inside project."""
    root = make_workspace(verse_max=3)
    custom = root / "projects" / "usNIVv2" / "custom.vrs"
    custom.write_text("#! -MAT 1:2\n", encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    base, resolved_custom = resolve_project_vrs_paths(config, config.project("usNIVv2"))
    assert base == (root / "projects" / "eng.vrs").resolve()
    assert resolved_custom == custom.resolve()
    schema = load_project_vrs(config, config.project("usNIVv2"))
    assert VerseRef("MAT", 1, 2) in schema.exclusions


def test_custom_vrs_absolute_path_is_rejected(make_workspace) -> None:
    """Verify that custom VRS absolute path is rejected."""
    root = make_workspace()
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["projects"]["usNIVv2"]["versification"]["custom_file"] = str(root / "outside.vrs")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="custom_file"):
        load_ecosystem(path)


def test_vrs_parser_supports_exclusions_and_mappings(tmp_path: Path) -> None:
    """Verify that VRS parser supports exclusions and mappings."""
    path = tmp_path / "custom.vrs"
    path.write_text(
        "MAT 1:20\n#! -MAT 1:10\n#! &ACT 19:40-41 = ACT 19:40\nREV 13:1 = REV 12:18\nREV 13:1 = REV 13:1\n",
        encoding="utf-8",
    )
    schema = parse_vrs_file(path, schema_id="fixture", canonical_id="org")
    assert VerseRef("MAT", 1, 10) in schema.exclusions
    assert len(schema.mappings) == 3
    assert schema.mappings[0].continuation is True


def test_vrs_invalid_utf8_is_rejected(tmp_path: Path) -> None:
    """Verify that VRS invalid utf8 is rejected."""
    path = tmp_path / "bad.vrs"
    path.write_bytes(b"MAT 1:2\xff")
    with pytest.raises(Exception, match="valid UTF-8"):
        parse_vrs_file(path, schema_id="bad", canonical_id="org")


def test_base_vrs_must_be_filename_in_projects_root(make_workspace) -> None:
    """Verify that base VRS must be filename in projects root."""
    root = make_workspace()
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["versification"]["base_files"][0] = "base/eng.vrs"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="must be one .vrs filename"):
        load_ecosystem(path)


def test_effective_vrs_hash_is_portable_across_workspace_paths(make_workspace, tmp_path) -> None:
    """Verify that effective VRS hash is portable across workspace paths."""
    from shutil import copytree

    first_root = make_workspace()
    first_config = load_ecosystem(first_root / "ecosystem.yml")
    first_schema = load_project_vrs(first_config, first_config.project("idKKHv0"))

    second_root = tmp_path / "relocated" / "SAGE"
    copytree(first_root, second_root)
    second_config = load_ecosystem(second_root / "ecosystem.yml")
    second_schema = load_project_vrs(second_config, second_config.project("idKKHv0"))

    first = first_schema.to_dict()
    second = second_schema.to_dict()
    assert first["effective_sha256"] == second["effective_sha256"]
    assert all(not Path(item["path"]).is_absolute() for item in first["source_files"])
