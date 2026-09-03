"""Projects-root base VRS and project-local custom VRS tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.errors import ConfigurationError
from sage.registry import load_ecosystem
from sage.usj import compile_usfm_file, parse_usj_units
from sage.vrs import (
    VerseRef,
    compose_vrs,
    load_project_vrs,
    parse_vrs_file,
    resolve_project_vrs_paths,
)


def test_auto_custom_vrs_resolves_inside_project(make_workspace) -> None:
    """Verify that auto custom VRS resolves inside project."""
    root = make_workspace(verse_max=3)
    custom = storage_layout(root).projects_root / "usNIVv2" / "custom.vrs"
    custom.write_text("#! -MAT 1:2\n", encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    base, resolved_custom = resolve_project_vrs_paths(config, config.project("usNIVv2"))
    assert base == (root / "system" / "resources" / "scripture" / "eng.vrs").resolve()
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


def test_vrs_parser_accepts_plain_and_executable_exclusions(tmp_path: Path) -> None:
    """Both legacy and Paratext 7.3 executable-comment exclusions are semantic."""
    path = tmp_path / "exclusions.vrs"
    path.write_text(
        "MAT 1:5\n-MAT 1:2\n#! -MAT 1:3\n",
        encoding="utf-8",
    )

    schema = parse_vrs_file(path, schema_id="fixture", canonical_id="org")

    assert schema.exclusions == {
        VerseRef("MAT", 1, 2),
        VerseRef("MAT", 1, 3),
    }
    assert "-MAT" not in schema.chapter_max


def test_vrs_parser_preserves_plain_and_executable_verse_segments(tmp_path: Path) -> None:
    """Segment declarations retain the unmarked segment and ordered suffixes."""
    path = tmp_path / "segments.vrs"
    path.write_text(
        "MAT 1:5\n*MAT 1:2,-,a,b\n#! *MAT 1:3,-,a\n",
        encoding="utf-8",
    )

    schema = parse_vrs_file(path, schema_id="fixture", canonical_id="org")

    assert schema.verse_segments == {
        VerseRef("MAT", 1, 2): ("", "a", "b"),
        VerseRef("MAT", 1, 3): ("", "a"),
    }


def test_vrs_parser_rejects_ampersand_mapping_with_ranges_on_both_sides(
    tmp_path: Path,
) -> None:
    """Paratext ampersand mappings require exactly one side to be one verse."""
    path = tmp_path / "many-to-many.vrs"
    path.write_text(
        "ACT 1:4\n&ACT 1:1-2 = ACT 1:3-4\n",
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="exactly one side must contain one verse"):
        parse_vrs_file(path, schema_id="bad", canonical_id="org")


def test_custom_vrs_end_truncates_inherited_chapters(tmp_path: Path) -> None:
    """END removes later base chapters instead of leaving stale inherited maxima."""
    base_path = tmp_path / "base.vrs"
    base_path.write_text("MAT 1:2 2:2 3:2\n", encoding="utf-8")
    custom_path = tmp_path / "custom.vrs"
    custom_path.write_text("MAT 1:3 END\n", encoding="utf-8")
    base = parse_vrs_file(base_path, schema_id="base", canonical_id="org")
    custom = parse_vrs_file(custom_path, schema_id="custom", canonical_id="org")

    schema = compose_vrs(base, custom, schema_id="composed")

    assert schema.chapter_max["MAT"] == {1: 3}


def test_bundled_grk_custom_vrs_excludes_only_absent_candidate_coordinates(package_root) -> None:
    """The bundled Greek VRS must distinguish absent coordinates from present variant text."""
    grk_root = package_root / "system" / "resources" / "scripture" / "original-language" / "grk"
    schema = parse_vrs_file(
        grk_root / "custom.vrs",
        schema_id="GRK-custom",
        canonical_id="org.vrs",
    )
    absent = {
        VerseRef("MAT", 17, 21),
        VerseRef("MAT", 18, 11),
        VerseRef("MAT", 23, 14),
        VerseRef("MRK", 7, 16),
        VerseRef("MRK", 9, 44),
        VerseRef("MRK", 9, 46),
        VerseRef("MRK", 11, 26),
        VerseRef("MRK", 15, 28),
        VerseRef("LUK", 17, 36),
        VerseRef("LUK", 23, 17),
        VerseRef("JHN", 5, 4),
        VerseRef("ACT", 8, 37),
        VerseRef("ACT", 15, 34),
        VerseRef("ACT", 24, 7),
        VerseRef("ACT", 28, 29),
        VerseRef("ROM", 16, 24),
    }
    present = {
        VerseRef("JHN", 7, 53),
        *(VerseRef("JHN", 8, verse) for verse in range(1, 12)),
        *(VerseRef("MRK", 16, verse) for verse in range(9, 21)),
        VerseRef("1JN", 5, 7),
        VerseRef("1JN", 5, 8),
    }

    actual: set[VerseRef] = set()
    for path in sorted(grk_root.glob("*.SFM")):
        usj = compile_usfm_file(path)
        book = str(usj["sage"]["book_code"])
        for unit in parse_usj_units(usj):
            actual.update(
                VerseRef(book, int(unit["chapter"]), verse)
                for verse in range(int(unit["verse_start"]), int(unit["verse_end"]) + 1)
            )

    assert schema.exclusions == absent
    assert absent.isdisjoint(actual)
    assert present <= actual
    assert schema.exclusions.isdisjoint(present)


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
