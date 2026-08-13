"""Immutable BIC generated-TARGET publication tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sage_core.errors import GenerationError
from sage_core.generations import (
    project_validation_fingerprint,
    publish_generated_target,
    resolve_generation,
    verify_generation,
)
from sage_core.profiles import load_workflow_profile
from sage_core.registry import load_ecosystem
from sage_core.scripture import compile_project


def test_generated_target_publication_is_immutable_and_reusable(make_workspace) -> None:
    """Verify that generated target publication is immutable and reusable."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    profile = load_workflow_profile(config, config.workflow("bic"))
    project_result = compile_project(config, config.project("usBOLx1"))
    first = publish_generated_target(
        config,
        profile,
        "usBOLx1",
        project_result,
        source_fingerprints={"idKKHv0": "a" * 64, "usNIRVv2": "b" * 64},
        grammar_contracts={"CONTENT_SOURCE": "c" * 64, "GENERATED_TARGET": "d" * 64},
        now=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
    )
    assert first["immutable"] is True
    assert first["validation_provenance"]["usj_compiler"].startswith("SAGE-USJ-")
    assert len(
        first["validation_provenance"]["structure_policy"]["effective_sha256"]
    ) == 64
    generation = resolve_generation(profile.publication_root, "usBOLx1", "current")
    assert verify_generation(generation)["generation_id"] == first["generation_id"]
    second = publish_generated_target(
        config,
        profile,
        "usBOLx1",
        project_result,
        source_fingerprints={"idKKHv0": "a" * 64, "usNIRVv2": "b" * 64},
        grammar_contracts={"CONTENT_SOURCE": "c" * 64, "GENERATED_TARGET": "d" * 64},
    )
    assert second["reused"] is True
    published_file = next((generation / "project").glob("*.SFM"))
    published_file.write_text("tampered", encoding="utf-8")
    with pytest.raises(GenerationError, match="hash mismatch"):
        verify_generation(generation)


def test_note_only_generated_verse_cannot_be_published(make_workspace) -> None:
    """Verify that note only generated verse cannot be published."""
    root = make_workspace(verse_max=1)
    target = root / "projects" / "usBOLx1" / "41MAT.SFM"
    target.write_text(
        "\\id MAT Fixture\n\\c 1\n\\p\n"
        "\\v 1 \\f + \\fr 1:1 \\ft note only\\f*\n",
        encoding="utf-8",
    )
    config = load_ecosystem(root / "ecosystem.yml")
    profile = load_workflow_profile(config, config.workflow("bic"))
    project_result = compile_project(config, config.project("usBOLx1"))
    with pytest.raises(GenerationError, match="note-only"):
        publish_generated_target(
            config,
            profile,
            "usBOLx1",
            project_result,
            source_fingerprints={"idKKHv0": "a" * 64},
            grammar_contracts={"GENERATED_TARGET": "d" * 64},
        )


def test_scope_limited_validation_cannot_publish_generation(make_workspace) -> None:
    """Verify that scope limited validation cannot publish generation."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    profile = load_workflow_profile(config, config.workflow("bic"))
    project_result = compile_project(config, config.project("usBOLx1"), books={"MAT"})
    assert project_result["summary"]["scope_limited"] is True
    with pytest.raises(GenerationError, match="full-project validation"):
        publish_generated_target(
            config,
            profile,
            "usBOLx1",
            project_result,
            source_fingerprints={"idKKHv0": "a" * 64},
            grammar_contracts={"GENERATED_TARGET": "d" * 64},
        )


def test_project_validation_fingerprint_covers_vrs_and_structure_policy(make_workspace) -> None:
    """Verify that project validation fingerprint covers VRS and structure policy."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("idKKHv0")
    first = compile_project(config, project)
    first_digest = project_validation_fingerprint(first)

    custom_vrs = project.path / "custom.vrs"
    custom_vrs.write_text("#! -MAT 1:3\n", encoding="utf-8")
    second = compile_project(config, project)
    second_digest = project_validation_fingerprint(second)

    assert first["resource_sha256"] == second["resource_sha256"]
    assert first["effective_vrs"]["effective_sha256"] != second["effective_vrs"]["effective_sha256"]
    assert first_digest != second_digest



def test_publication_blocks_when_target_usfm_changes_after_validation(make_workspace) -> None:
    """Verify that publication blocks when target USFM changes after validation."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    profile = load_workflow_profile(config, config.workflow("bic"))
    project = config.project("usBOLx1")
    project_result = compile_project(config, project)
    target = project.path / "41MAT.SFM"
    target.write_text(
        target.read_text(encoding="utf-8") + "\\rem changed after validation\n",
        encoding="utf-8",
    )
    with pytest.raises(GenerationError, match="changed after validation"):
        publish_generated_target(
            config,
            profile,
            "usBOLx1",
            project_result,
            source_fingerprints={"idKKHv0": "a" * 64},
            grammar_contracts={"GENERATED_TARGET": "d" * 64},
        )


def test_publication_blocks_when_custom_vrs_changes_after_validation(make_workspace) -> None:
    """Verify that publication blocks when custom VRS changes after validation."""
    root = make_workspace()
    custom = root / "projects" / "usBOLx1" / "custom.vrs"
    custom.write_text("# initial project-local override\n", encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    profile = load_workflow_profile(config, config.workflow("bic"))
    project_result = compile_project(config, config.project("usBOLx1"))
    custom.write_text("# changed after validation\n", encoding="utf-8")
    with pytest.raises(GenerationError, match="custom VRS changed after validation"):
        publish_generated_target(
            config,
            profile,
            "usBOLx1",
            project_result,
            source_fingerprints={"idKKHv0": "a" * 64},
            grammar_contracts={"GENERATED_TARGET": "d" * 64},
        )


def test_published_generation_records_validated_custom_vrs(make_workspace) -> None:
    """Verify that published generation records validated custom VRS."""
    root = make_workspace()
    custom = root / "projects" / "usBOLx1" / "custom.vrs"
    custom.write_text("# governed project-local override\n", encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    profile = load_workflow_profile(config, config.workflow("bic"))
    result = publish_generated_target(
        config,
        profile,
        "usBOLx1",
        compile_project(config, config.project("usBOLx1")),
        source_fingerprints={"idKKHv0": "a" * 64},
        grammar_contracts={"GENERATED_TARGET": "d" * 64},
        publication_basis="DEVELOPMENT_OVERRIDE",
    )
    custom_record = result["published_custom_vrs"]
    assert custom_record["path"] == "custom.vrs"
    assert len(custom_record["sha256"]) == 64
    assert result["publication_basis"] == "DEVELOPMENT_OVERRIDE"
    assert verify_generation(Path(result["path"]))["published_custom_vrs"] == custom_record



