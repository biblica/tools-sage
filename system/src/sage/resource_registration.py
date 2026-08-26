"""Add role-neutral Paratext/PTLite Scripture Projects to the SAGE inventory."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .config import load_yaml
from .errors import ValidationError
from .language_codes import canonical_language_tag
from .project_inventory import project_code_policy, register_project
from .registry import load_ecosystem
from .resource_mounts import load_resource_mount_state

_ROLE_PROFILE_EQUIVALENTS = {
    "GENERATED_TARGET": {"GENERATED_TARGET", "TARGET"},
    "WIP": {"WIP", "TARGET"},
    "CONTENT_SOURCE": {"CONTENT_SOURCE"},
    "REFERENCE": {"REFERENCE"},
    "LEXICAL_DONOR": {"LEXICAL_DONOR"},
}


def compatible_language_options(settings_path: Path, role: str) -> tuple[tuple[str, str | None], ...]:
    """Return language/profile options usable for the requested Job binding.

    The current release uses this only while assigning a Project to a Job role. Language-profile variants
    are Job-scoped; adding a Project to SAGE never assigns a workflow role.
    """
    config = load_ecosystem(settings_path)
    if role in {"ORIGINAL_LANGUAGE_GREEK", "ORIGINAL_LANGUAGE_HEBREW"}:
        # Governed OL aliases are configured separately as @GRK/@HEB, never added as
        # ordinary translation Projects.
        return ()
    wanted = _ROLE_PROFILE_EQUIVALENTS.get(role, {role})
    values: list[tuple[str, str | None]] = []
    required_variant = role in {"CONTENT_SOURCE", "GENERATED_TARGET", "WIP"}
    for code, namespace in sorted(config.language_profiles.items()):
        variants = [item.variant_id for item in namespace.variants.values() if item.role in wanted]
        if variants:
            values.extend((code, variant) for variant in variants)
        elif not required_variant:
            values.append((code, None))
    return tuple(values)


def register_external_scripture_resource(
    settings_path: Path,
    *,
    project_id: str,
    project_folder: str | None = None,
    language_code: str,
    profile_variant: str | None,
    role: str | None,
    base_vrs_file: str,
    external_path: Path | None = None,
    display_name: str | None = None,
    declared_books: tuple[str, ...] | None = None,
    paratext_metadata: Mapping[str, Any] | None = None,
    versification_metadata: Mapping[str, Any] | None = None,
) -> None:
    """Add one external Scripture Project to the role-neutral SAGE Project Inventory.

    ``role`` and ``profile_variant`` are accepted only for source compatibility with earlier builds
    callers. The current release deliberately ignores them: SOURCE/DONOR/TARGET/WIP/REFERENCE and grammar
    variants belong to Job bindings, not Project inventory records.
    """
    settings = settings_path.expanduser().resolve()
    sage_root = settings.parent
    if external_path is None:
        state = load_resource_mount_state(sage_root)
        projects_root = state.get("projects_root")
        if not projects_root:
            raise ValidationError("Paratext/PTLite Projects root is not configured", code="PROJECT_ROOT_NOT_FOUND")
        folder = str(project_folder or "").strip()
        if not folder or Path(folder).name != folder:
            raise ValidationError("Project folder must be one direct subfolder name", code="RESOURCE_MOUNT_PATH_INVALID")
        external_path = Path(projects_root) / folder
    raw = load_yaml(settings)
    types = project_code_policy(raw)
    role_hint = str(role or "").strip().upper()
    if role_hint in {"ORIGINAL_LANGUAGE_GREEK", "ORIGINAL_LANGUAGE_HEBREW"}:
        raise ValidationError(
            "Original-language resources are configured through governed @GRK/@HEB aliases, not by adding them as ordinary SAGE Projects",
            code="OL_RESOURCE_REGISTRATION_FORBIDDEN",
        )
    register_project(
        sage_root,
        project_id=project_id,
        project_path=external_path,
        language_code=language_code,
        language_profile=language_code,
        profile_variant=None,
        base_vrs_file=base_vrs_file,
        display_name=display_name,
        kind="SCRIPTURE",
        content_state="LOCKED",
        allow_empty=False,
        coverage_policy="CONFIGURED_BOOKS_COMPLETE",
        type_codes=types,
        declared_books=declared_books,
        paratext_metadata=paratext_metadata,
        versification_metadata=versification_metadata,
    )


def register_catalogued_scripture_project(
    settings_path: Path,
    *,
    catalogue_row: Mapping[str, Any],
    role: str | None = None,
    profile_variant: str | None = None,
    writable_target_capability: bool = False,
) -> str:
    """Add one preparsed Paratext catalog row to SAGE with no Job role assignment."""
    from .external_access import READ_ONLY_SCRIPTURE
    from .resource_mounts import set_resource_mount

    settings = settings_path.expanduser().resolve()
    root = settings.parent
    project_id = str(catalogue_row.get("project_code") or "").strip()
    project_path = Path(str(catalogue_row.get("path") or "")).expanduser().resolve()
    raw_language_code = str(catalogue_row.get("language_profile_tag") or catalogue_row.get("language_iso") or "").strip()
    language_code = canonical_language_tag(raw_language_code, "SAGE Project language profile", require_preferred=False) if raw_language_code else ""
    if not project_id or not project_path.is_dir():
        raise ValidationError("Catalog row does not resolve to a valid Project folder", code="PARATEXT_CATALOG_ENTRY_INVALID")
    if not language_code:
        raise ValidationError(
            f"Project {project_id} has no usable LanguageIsoCode in settings.xml",
            code="PARATEXT_LANGUAGE_ISO_REQUIRED",
        )
    config = load_ecosystem(settings)
    if language_code not in config.language_profiles:
        raise ValidationError(
            f"Project {project_id} requires a configured regional Language Profile before registration: {language_code}",
            code="LANGUAGE_PROFILE_NOT_CONFIGURED",
            next_action="Confirm language identity and create/select the regional Language Profile, then retry Project registration.",
        )

    vrs_meta = dict(catalogue_row.get("versification") or {})
    reported_base = str(vrs_meta.get("base_file") or "").strip()
    declared_base = reported_base if reported_base.casefold() in config.base_vrs_files else ""
    base_file = declared_base or config.default_versification
    base_selection = "PROJECT_DECLARED" if declared_base else "DEFAULT"
    paratext_meta = {
        "full_name": catalogue_row.get("full_name"),
        "language_name": catalogue_row.get("language_name"),
        "language_iso": catalogue_row.get("language_iso"),
        "language_iso_raw": catalogue_row.get("language_iso_raw"),
        "paratext_language_code": catalogue_row.get("paratext_language_code"),
        "canonical_iso_639_3": catalogue_row.get("canonical_iso_639_3"),
        "preferred_language_subtag": catalogue_row.get("preferred_language_subtag"),
        "primary_audience_country": catalogue_row.get("primary_audience_country"),
        "language_profile_tag": language_code,
        "ldml_evidence": catalogue_row.get("ldml_evidence", []),
        "catalog_status": catalogue_row.get("status"),
    }
    register_project(
        root,
        project_id=project_id,
        project_path=project_path,
        language_code=language_code,
        language_profile=language_code,
        profile_variant=None,
        base_vrs_file=base_file,
        display_name=str(catalogue_row.get("full_name") or project_id),
        kind="SCRIPTURE",
        content_state="LOCKED",
        allow_empty=False,
        coverage_policy="CONFIGURED_BOOKS_COMPLETE",
        type_codes=project_code_policy(load_yaml(settings)),
        declared_books=tuple(str(book) for book in catalogue_row.get("books", [])),
        paratext_metadata=paratext_meta,
        versification_metadata={
            "custom_file": str(vrs_meta.get("file") or "auto"),
            "name": vrs_meta.get("name"),
            "reported_base_file": reported_base or None,
            "base_selection": base_selection,
            "base_description": vrs_meta.get("base_description"),
            "metadata_status": vrs_meta.get("metadata_status"),
        },
    )
    set_resource_mount(
        root,
        project_id=project_id,
        external_path=project_path,
        access_mode=READ_ONLY_SCRIPTURE,
    )
    return project_id
