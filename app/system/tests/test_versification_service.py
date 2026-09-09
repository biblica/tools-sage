"""Internal versification service contract tests."""

from __future__ import annotations

from pathlib import Path

from sage.registry import load_ecosystem
from sage.vrs import VerseRef
from sage.versification_service import VersificationService


def test_catalog_exposes_registered_roles_and_pinned_provenance(
    package_root: Path,
) -> None:
    """Catalog consumers receive governed roles and provenance for each base schema."""
    service = VersificationService(load_ecosystem(package_root / "ecosystem.yml"))

    entries = {entry.filename: entry for entry in service.catalog()}

    assert set(entries) == {
        "eng.vrs",
        "org.vrs",
        "lxx.vrs",
        "vul.vrs",
        "rsc.vrs",
        "rso.vrs",
    }
    assert entries["org.vrs"].canonical is True
    assert entries["org.vrs"].default is False
    assert entries["eng.vrs"].canonical is False
    assert entries["eng.vrs"].default is True
    assert entries["lxx.vrs"].source_commit == (
        "bb9d36de70ed7fd6c3e62f0c86c1001f0009eb50"
    )
    assert entries["lxx.vrs"].source_license == "MIT"
    assert entries["lxx.vrs"].upstream_sha256 == (
        "f7c7bd6e0e5a536b6ec924bfb5f19596bc21af5bee268f97dd51d0845328cc1f"
    )
    assert service.base_schema("lxx.vrs").chapter_limit("PSA", 151) == 7


def test_project_schema_returns_an_independent_value(make_workspace) -> None:
    """Mutating one returned schema cannot corrupt a later service result."""
    root = make_workspace(verse_max=3)
    config = load_ecosystem(root / "ecosystem.yml")
    service = VersificationService(config)

    first = service.project_schema("usNIVv2")
    first.chapter_max["MAT"][1] = 99
    first.exclusions.add(VerseRef("MAT", 1, 1))

    second = service.project_schema("usNIVv2")

    assert second.chapter_limit("MAT", 1) == 3
    assert second.exclusions == set()


def test_project_schema_invalidates_when_custom_vrs_bytes_change(
    make_workspace,
) -> None:
    """A same-process custom VRS edit replaces stale cached schema data."""
    root = make_workspace(verse_max=3)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usNIVv2")
    custom = project.path / "custom.vrs"
    custom.write_text("#! -MAT 1:2\n", encoding="utf-8")
    service = VersificationService(config)

    first_fingerprint = service.effective_fingerprint(project)
    assert service.project_schema(project).exclusions == {VerseRef("MAT", 1, 2)}

    custom.write_text("#! -MAT 1:1\n", encoding="utf-8")
    second = service.project_schema(project)

    assert second.exclusions == {VerseRef("MAT", 1, 1)}
    assert service.effective_fingerprint(project) != first_fingerprint


def test_service_projects_many_to_one_references_deterministically(
    make_workspace,
) -> None:
    """Both projection directions retain ordered equivalence-group coordinates."""
    root = make_workspace(verse_max=3)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usNIVv2")
    (project.path / "custom.vrs").write_text(
        "#! &MAT 1:2-3 = MAT 1:2\n",
        encoding="utf-8",
    )
    service = VersificationService(config)

    canonical = service.to_canonical(
        project,
        (VerseRef("MAT", 1, 3), VerseRef("MAT", 1, 2)),
    )
    local = service.from_canonical(project, (VerseRef("MAT", 1, 2),))

    assert canonical.direction == "LOCAL_TO_CANONICAL"
    assert canonical.input_refs == (
        VerseRef("MAT", 1, 2),
        VerseRef("MAT", 1, 3),
    )
    assert canonical.projected_refs == (VerseRef("MAT", 1, 2),)
    assert canonical.precision == "EQUIVALENCE_GROUP"
    assert local.direction == "CANONICAL_TO_LOCAL"
    assert local.projected_refs == (
        VerseRef("MAT", 1, 2),
        VerseRef("MAT", 1, 3),
    )
    assert local.precision == "EQUIVALENCE_GROUP"


def test_to_canonical_rejects_independently_colliding_coordinates(
    make_workspace,
) -> None:
    """A one-way singleton mapping is not coordinate-precise when it cannot reverse."""
    root = make_workspace(verse_max=3)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usNIVv2")
    (project.path / "custom.vrs").write_text(
        "MAT 1:2 = MAT 1:1\nMAT 1:3 = MAT 1:1\n",
        encoding="utf-8",
    )
    service = VersificationService(config)

    projection = service.to_canonical(project, (VerseRef("MAT", 1, 2),))

    assert projection.projected_refs == (VerseRef("MAT", 1, 1),)
    assert projection.precision == "EQUIVALENCE_GROUP"
