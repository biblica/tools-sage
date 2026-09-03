"""Immutable Project identity resolution contracts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sage.errors import ValidationError
from sage.project_context import (
    identity_bindings,
    identity_display_names,
    resolve_project_identities,
    resolve_project_identity,
)
from sage.project_inventory import register_project
from sage.registry import load_ecosystem
from sage.scripture import compile_project


def test_project_identity_resolves_inventory_name_and_import_date(make_workspace) -> None:
    """An imported Project seals its human name, import date, and compiled provenance."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")
    register_project(
        root,
        project_id=project.project_id,
        project_path=project.path,
        language_code=project.language_code,
        base_vrs_file=project.versification.base,
        display_name="Persian Contemporary Bible",
        declared_books=("MAT",),
        imported_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    identity = resolve_project_identity(
        root,
        "WIP",
        project,
        compile_project(config, project),
    )

    assert identity.role == "WIP"
    assert identity.project_id == "usWIP"
    assert identity.display_name == "Persian Contemporary Bible"
    assert identity.imported_date == "20260901"
    assert len(identity.content_fingerprint) == 64
    assert len(identity.effective_vrs_sha256) == 64
    assert identity.vrs_schema_id == "usWIP:eng.vrs"


def test_missing_inventory_name_falls_back_to_project_id(make_workspace) -> None:
    """An unregistered legacy Project remains identifiable by its stable Project ID."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")

    identity = resolve_project_identity(
        root,
        "WIP",
        project,
        compile_project(config, project),
    )

    assert identity.display_name == identity.project_id == "usWIP"
    assert identity.imported_date is None


def test_identity_projections_return_fresh_role_maps(make_workspace) -> None:
    """Mutating one serialized role map cannot alter the sealed Project identities."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")
    identities = resolve_project_identities(
        root,
        {"WIP": project.project_id},
        config.projects,
        {project.project_id: compile_project(config, project)},
    )

    bindings = identity_bindings(identities)
    names = identity_display_names(identities)
    bindings["WIP"] = "changed"
    names["WIP"] = "changed"

    assert identity_bindings(identities) == {"WIP": "usWIP"}
    assert identity_display_names(identities) == {"WIP": "usWIP"}


def test_project_identity_rejects_blank_role_and_invalid_vrs_hash(make_workspace) -> None:
    """Malformed task identity cannot be sealed from incomplete role or VRS provenance."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")
    compiled = compile_project(config, project)

    with pytest.raises(ValidationError, match="role"):
        resolve_project_identity(root, " ", project, compiled)

    invalid = dict(compiled)
    invalid["effective_vrs"] = {**dict(compiled["effective_vrs"]), "effective_sha256": "bad"}
    with pytest.raises(ValidationError, match="VRS hash"):
        resolve_project_identity(root, "WIP", project, invalid)


def test_uncompiled_job_binding_retains_identity_without_claiming_provenance(
    make_workspace,
) -> None:
    """A dormant bound Project seals its name but does not invent compilation hashes."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    wip = config.project("usWIP")

    identities = resolve_project_identities(
        root,
        {"WIP": wip.project_id, "ORIGINAL_LANGUAGE_GREEK": "GRK"},
        config.projects,
        {wip.project_id: compile_project(config, wip)},
    )

    dormant = identities["ORIGINAL_LANGUAGE_GREEK"]
    assert dormant.project_id == "GRK"
    assert dormant.display_name == "GRK"
    assert dormant.content_fingerprint is None
    assert dormant.vrs_schema_id is None
    assert dormant.effective_vrs_sha256 is None


def test_not_generated_target_retains_identity_without_vrs_provenance(
    make_workspace,
) -> None:
    """An allowed-empty destination remains bound without claiming nonexistent VRS evidence."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    target = config.project("usBOLx1")

    identities = resolve_project_identities(
        root,
        {"TARGET": target.project_id},
        config.projects,
        {
            target.project_id: {
                "project_id": target.project_id,
                "status": "NOT_GENERATED",
            }
        },
    )

    identity = identities["TARGET"]
    assert identity.project_id == "usBOLx1"
    assert identity.content_fingerprint is None
    assert identity.vrs_schema_id is None
    assert identity.effective_vrs_sha256 is None
