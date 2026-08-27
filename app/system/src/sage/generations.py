"""Immutable BIC TARGET publication and verification."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .atomic import atomic_write_json
from .canon import resolve_expected_books
from .errors import GenerationError
from .hashing import sha256_bytes, sha256_file, sha256_paths
from .profiles import WorkflowProfile
from .registry import EcosystemConfig
from .scripture import discover_usfm_files
from .usj import USJ_COMPILER
from .vrs import resolve_project_vrs_paths

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _utc_id(now: datetime | None = None) -> str:
    """Build a sortable UTC generation identifier with collision-resistant precision."""
    value = now or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_manifest(path: Path) -> dict[str, Any]:
    """Read and validate one immutable generation manifest."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationError(f"Invalid generation manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GenerationError(f"Generation manifest root must be a mapping: {path}")
    return value


def _validated_hashes(values: Mapping[str, str], label: str) -> dict[str, str]:
    """Return the validated file hashes that define a publishable generation."""
    result: dict[str, str] = {}
    if not values:
        raise GenerationError(f"{label} must not be empty")
    for key, value in values.items():
        normalized_key = str(key).strip()
        digest = str(value).strip().lower()
        if not normalized_key or not SHA256_RE.fullmatch(digest):
            raise GenerationError(f"{label}.{key} must be a lowercase SHA-256 digest")
        result[normalized_key] = digest
    return dict(sorted(result.items()))


def _generation_fingerprint(
    *,
    project_id: str,
    resource_sha256: str,
    source_fingerprints: Mapping[str, str],
    grammar_contracts: Mapping[str, str],
    effective_vrs_sha256: str,
    project_scope: Mapping[str, Any],
    structure_policy_sha256: str,
    usj_compiler: str,
    sage_version: str,
    publication_basis: str,
) -> str:
    """Hash the validated project state used to identify equivalent generations."""
    payload = {
        "project_id": project_id,
        "resource_sha256": resource_sha256,
        "source_fingerprints": dict(sorted(source_fingerprints.items())),
        "grammar_contracts": dict(sorted(grammar_contracts.items())),
        "effective_vrs_sha256": effective_vrs_sha256,
        "project_scope": dict(project_scope),
        "structure_policy_sha256": structure_policy_sha256,
        "usj_compiler": usj_compiler,
        "sage_version": sage_version,
        "publication_basis": publication_basis,
    }
    return sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _validated_validation_provenance(value: Any) -> dict[str, Any]:
    """Validate the compiler and structure-policy fields in one generation."""
    if not isinstance(value, dict):
        raise GenerationError("Generation validation_provenance must be a mapping")
    compiler = str(value.get("usj_compiler", "")).strip()
    structure = value.get("structure_policy", {})
    if not compiler:
        raise GenerationError("Generation validation_provenance.usj_compiler is missing")
    if not isinstance(structure, dict):
        raise GenerationError(
            "Generation validation_provenance.structure_policy must be a mapping"
        )
    structure_hash = str(structure.get("effective_sha256", "")).strip().lower()
    if not SHA256_RE.fullmatch(structure_hash):
        raise GenerationError("Generation structure-policy hash is missing or invalid")
    normalized_structure = dict(structure)
    # Do not embed machine-specific absolute paths in portable generation manifests.
    normalized_structure["source"] = "system/config/structure-planning.yml"
    return {
        "usj_compiler": compiler,
        "structure_policy": normalized_structure,
        "structure_policy_sha256": structure_hash,
    }


def project_validation_fingerprint(project_result: Mapping[str, Any]) -> str:
    """Hash the governed validation inputs for one SAGE Scripture Project.

    The digest changes when the USFM payload, effective VRS, structure policy,
    or USJ compiler changes. BIC records these digests for every source binding
    used to produce a published TARGET generation.
    """
    effective_vrs = project_result.get("effective_vrs", {})
    structure_policy = project_result.get("structure_policy", {})
    if not isinstance(effective_vrs, dict) or not isinstance(structure_policy, dict):
        raise GenerationError("Project validation provenance is incomplete")
    payload = {
        "project_id": str(project_result.get("project_id", "")),
        "language_code": str(project_result.get("language_code", "")),
        "language_profile": str(project_result.get("language_profile", "")),
        "profile_variant": project_result.get("profile_variant"),
        "resource_sha256": str(project_result.get("resource_sha256", "")),
        "compiled_files_sha256": str(project_result.get("compiled_files_sha256", "")),
        "effective_vrs_sha256": str(effective_vrs.get("effective_sha256", "")),
        "project_scope": dict(project_result.get("declared_scope", {})),
        "structure_policy_sha256": str(structure_policy.get("effective_sha256", "")),
        "usj_compiler": USJ_COMPILER,
    }
    for field in (
        "resource_sha256",
        "compiled_files_sha256",
        "effective_vrs_sha256",
        "structure_policy_sha256",
    ):
        if not SHA256_RE.fullmatch(payload[field].lower()):
            raise GenerationError(f"Project validation provenance field is invalid: {field}")
        payload[field] = payload[field].lower()
    if not payload["project_id"]:
        raise GenerationError("Project validation provenance is missing project_id")
    if not payload["language_code"] or not payload["language_profile"]:
        raise GenerationError("Project validation provenance is missing language profile identity")
    if not payload["project_scope"]:
        raise GenerationError("Project validation provenance is missing declared scope")
    return sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _existing_by_fingerprint(project_root: Path, fingerprint: str) -> Path | None:
    """Find an existing immutable generation with the same validation fingerprint."""
    if not project_root.exists():
        return None
    for generation in sorted(item for item in project_root.iterdir() if item.is_dir()):
        if generation.name.startswith("."):
            continue
        manifest_path = generation / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = _read_manifest(manifest_path)
        if manifest.get("generation_fingerprint") == fingerprint:
            return generation
    return None


def publish_generated_target(
    config: EcosystemConfig,
    profile: WorkflowProfile,
    project_id: str,
    project_result: Mapping[str, Any],
    *,
    source_fingerprints: Mapping[str, str],
    grammar_contracts: Mapping[str, str],
    publication_basis: str = "VALIDATED_WORKFLOW",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Publish one validated BIC TARGET as an immutable generation snapshot."""
    # Freeze and hash generation inputs before changing the current-generation pointer.
    basis = publication_basis.strip().upper()
    if basis not in {"VALIDATED_WORKFLOW", "DEVELOPMENT_OVERRIDE"}:
        raise GenerationError(f"Unsupported publication basis: {publication_basis!r}")
    if profile.workflow_id != "bic":
        raise GenerationError("Only the BIC workflow may publish generated TARGETs")
    if project_id not in profile.may_write_projects:
        raise GenerationError(f"BIC does not have write permission for {project_id}")
    project = config.project(project_id)
    if project.kind != "GENERATED_SCRIPTURE" or project.producer != "bic":
        raise GenerationError(f"Project {project_id} is not a BIC-generated Scripture project")
    if project_result.get("status") not in {"READY", "READY_WITH_WARNINGS"}:
        raise GenerationError(
            f"Generated TARGET {project_id} is not publishable: {project_result.get('status')}"
        )
    summary = project_result.get("summary", {})
    if isinstance(summary, Mapping) and summary.get("scope_limited") is True:
        raise GenerationError(
            "Generated TARGET publication requires full-project validation, not a scope-limited result"
        )
    blocking_warning_codes = {"PRESENT_NOTE_ONLY", "EMPTY_VISIBLE_BODY"}
    bad_warnings = [
        item
        for item in project_result.get("warnings", [])
        if item.get("code") in blocking_warning_codes
    ]
    if bad_warnings:
        refs = ", ".join(str(item.get("reference", "")) for item in bad_warnings[:10])
        raise GenerationError(
            "Generated TARGET contains empty or note-only verse bodies and cannot be published: "
            + refs
        )
    publication_root = profile.publication_root
    if publication_root is None:
        raise GenerationError("BIC publication_root is not configured")
    resource_hash = str(project_result.get("resource_sha256", "")).lower()
    if not SHA256_RE.fullmatch(resource_hash):
        raise GenerationError("Generated TARGET resource hash is missing or invalid")
    normalized_sources = _validated_hashes(source_fingerprints, "source_fingerprints")
    normalized_grammar = _validated_hashes(grammar_contracts, "grammar_contracts")
    effective_vrs = project_result.get("effective_vrs", {})
    if not isinstance(effective_vrs, dict):
        raise GenerationError("Generated TARGET effective VRS is missing")
    effective_vrs_hash = str(effective_vrs.get("effective_sha256", "")).lower()
    if not SHA256_RE.fullmatch(effective_vrs_hash):
        raise GenerationError("Generated TARGET effective VRS hash is missing or invalid")
    validation_provenance = _validated_validation_provenance(
        {
            "usj_compiler": USJ_COMPILER,
            "structure_policy": project_result.get("structure_policy", {}),
        }
    )
    structure_policy = validation_provenance["structure_policy"]
    structure_policy_hash = validation_provenance["structure_policy_sha256"]
    project_scope = {
        "testament": project.scope.testament,
        "canon": project.scope.canon,
        "expected_books": (
            project.scope.expected_books
            if isinstance(project.scope.expected_books, str)
            else list(project.scope.expected_books)
        ),
        "resolved_expected_books": list(resolve_expected_books(project.scope)),
        "roles": list(project.scope.roles),
        "content_state": project.content_state,
    }
    if dict(project_result.get("declared_scope", {})) != project_scope:
        raise GenerationError(
            "Generated TARGET scope changed after validation; revalidate before publication"
        )
    sage_version = (config.root / "VERSION").read_text(encoding="utf-8").strip()
    fingerprint = _generation_fingerprint(
        project_id=project_id,
        resource_sha256=resource_hash,
        source_fingerprints=normalized_sources,
        grammar_contracts=normalized_grammar,
        effective_vrs_sha256=effective_vrs_hash,
        project_scope=project_scope,
        structure_policy_sha256=structure_policy_hash,
        usj_compiler=USJ_COMPILER,
        sage_version=sage_version,
        publication_basis=basis,
    )
    project_publications = publication_root / project_id
    existing = _existing_by_fingerprint(project_publications, fingerprint)
    if existing is not None:
        manifest = verify_generation(existing)
        atomic_write_json(
            project_publications / "current.json",
            {
                "generation_id": manifest["generation_id"],
                "generation_fingerprint": fingerprint,
                "resource_sha256": resource_hash,
                "manifest": str((existing / "manifest.json").resolve()),
            },
        )
        return {**manifest, "path": str(existing), "reused": True}

    generation_id = f"{_utc_id(now)}-{fingerprint[:12]}"
    final_root = project_publications / generation_id
    staging_root = project_publications / f".{generation_id}.staging"
    if final_root.exists() or staging_root.exists():
        raise GenerationError(f"Generation path already exists: {final_root}")
    project_copy = staging_root / "project"
    source_files = discover_usfm_files(project.path)
    if not source_files:
        raise GenerationError(f"Generated TARGET project has no USFM files: {project.path}")
    if any(source.is_symlink() for source in source_files):
        raise GenerationError("Generated TARGET publication does not accept symbolic-link USFM files")

    _, custom_vrs = resolve_project_vrs_paths(config, project)
    vrs_sources = effective_vrs.get("source_files", [])
    if not isinstance(vrs_sources, list):
        raise GenerationError("Generated TARGET effective VRS source inventory is invalid")
    expected_custom_sources = [
        item
        for item in vrs_sources
        if isinstance(item, dict)
        and str(item.get("path", "")).startswith(f"project:{project_id}/")
    ]
    if len(expected_custom_sources) > 1:
        raise GenerationError("Generated TARGET effective VRS has multiple project-local sources")
    if bool(custom_vrs) != bool(expected_custom_sources):
        raise GenerationError(
            "Generated TARGET custom VRS changed after validation; revalidate before publication"
        )

    copied: list[Path] = []
    copied_usfm: list[Path] = []
    published_custom_vrs: dict[str, str] | None = None
    try:
        project_copy.mkdir(parents=True)
        for source in source_files:
            target = project_copy / source.name
            shutil.copy2(source, target)
            copied.append(target)
            copied_usfm.append(target)
        published_usfm_hash = sha256_paths(copied_usfm, relative_to=project_copy)
        if published_usfm_hash != resource_hash:
            raise GenerationError(
                "Generated TARGET USFM changed after validation; revalidate before publication"
            )
        if custom_vrs is not None:
            if not custom_vrs.exists():
                raise GenerationError(
                    "Generated TARGET custom VRS disappeared after validation"
                )
            if custom_vrs.is_symlink():
                raise GenerationError("Generated TARGET custom VRS may not be a symbolic link")
            expected_custom_hash = str(expected_custom_sources[0].get("sha256", "")).lower()
            actual_custom_hash = sha256_file(custom_vrs)
            if actual_custom_hash != expected_custom_hash:
                raise GenerationError(
                    "Generated TARGET custom VRS changed after validation; revalidate before publication"
                )
            target = project_copy / custom_vrs.name
            shutil.copy2(custom_vrs, target)
            copied.append(target)
            if sha256_file(target) != expected_custom_hash:
                raise GenerationError("Published custom VRS copy does not match validated content")
            published_custom_vrs = {
                "path": target.relative_to(project_copy).as_posix(),
                "sha256": expected_custom_hash,
            }
        file_hashes = {
            path.relative_to(project_copy).as_posix(): sha256_file(path)
            for path in sorted(copied)
        }
        published_hash = sha256_paths(copied, relative_to=project_copy)
        manifest = {
            "schema_version": "1.0",
            "generation_id": generation_id,
            "generation_fingerprint": fingerprint,
            "status": "COMMITTED",
            "producer": "bic",
            "publication_basis": basis,
            "sage_version": sage_version,
            "project_id": project_id,
            "created_utc": (now or datetime.now(timezone.utc))
            .astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "resource_sha256": resource_hash,
            "published_usfm_sha256": published_usfm_hash,
            "published_files_sha256": published_hash,
            "published_custom_vrs": published_custom_vrs,
            "file_hashes": file_hashes,
            "effective_vrs": effective_vrs,
            "project_scope": project_scope,
            "validation_provenance": {
                "usj_compiler": validation_provenance["usj_compiler"],
                "structure_policy": structure_policy,
            },
            "source_fingerprints": normalized_sources,
            "grammar_contracts": normalized_grammar,
            "project_subdirectory": "project",
            "immutable": True,
        }
        atomic_write_json(staging_root / "manifest.json", manifest)
        project_publications.mkdir(parents=True, exist_ok=True)
        os.replace(staging_root, final_root)
    except Exception:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise
    atomic_write_json(
        project_publications / "current.json",
        {
            "generation_id": generation_id,
            "generation_fingerprint": fingerprint,
            "resource_sha256": resource_hash,
            "manifest": str((final_root / "manifest.json").resolve()),
        },
    )
    verified = verify_generation(final_root)
    return {**verified, "path": str(final_root), "reused": False}


def verify_generation(generation_root: Path) -> dict[str, Any]:
    """Verify one immutable generation manifest and its exact file inventory."""
    generation_root = generation_root.resolve()
    manifest = _read_manifest(generation_root / "manifest.json")
    if manifest.get("status") != "COMMITTED" or manifest.get("immutable") is not True:
        raise GenerationError(f"Generation is not committed and immutable: {generation_root}")
    publication_basis = str(manifest.get("publication_basis", "")).upper()
    if publication_basis not in {"VALIDATED_WORKFLOW", "DEVELOPMENT_OVERRIDE"}:
        raise GenerationError(f"Generation publication basis is invalid: {publication_basis!r}")
    project_root = generation_root / str(manifest.get("project_subdirectory", "project"))
    file_hashes = manifest.get("file_hashes")
    if not isinstance(file_hashes, dict) or not file_hashes:
        raise GenerationError(f"Generation file hash inventory is missing: {generation_root}")
    actual_files = {
        path.relative_to(project_root).as_posix()
        for path in project_root.rglob("*")
        if path.is_file()
    }
    expected_files = set(file_hashes)
    if actual_files != expected_files:
        raise GenerationError(
            "Published generation file inventory mismatch: "
            f"missing={sorted(expected_files - actual_files)}, "
            f"extra={sorted(actual_files - expected_files)}"
        )
    for relative, expected in sorted(file_hashes.items()):
        path = (project_root / relative).resolve()
        try:
            path.relative_to(project_root.resolve())
        except ValueError as exc:
            raise GenerationError(f"Generation file escapes project root: {relative}") from exc
        if path.is_symlink():
            raise GenerationError(f"Published generation file may not be a symbolic link: {relative}")
        actual = sha256_file(path)
        if actual != expected:
            raise GenerationError(
                f"Published generation file hash mismatch: {relative}: {actual} != {expected}"
            )
    usfm_files = sorted(
        project_root / relative
        for relative in expected_files
        if Path(relative).suffix.lower() in {".sfm", ".usfm"}
    )
    if not usfm_files:
        raise GenerationError("Published generation contains no USFM files")
    actual_usfm_hash = sha256_paths(usfm_files, relative_to=project_root)
    if actual_usfm_hash != manifest.get("published_usfm_sha256"):
        raise GenerationError("Published generation USFM aggregate hash is invalid")
    if actual_usfm_hash != manifest.get("resource_sha256"):
        raise GenerationError("Published generation USFM does not match validated resource hash")

    custom_info = manifest.get("published_custom_vrs")
    non_usfm_files = sorted(
        relative
        for relative in expected_files
        if Path(relative).suffix.lower() not in {".sfm", ".usfm"}
    )
    if custom_info is None:
        if non_usfm_files:
            raise GenerationError(
                "Published generation contains undeclared non-USFM files: "
                + ", ".join(non_usfm_files)
            )
    elif isinstance(custom_info, dict):
        custom_relative = str(custom_info.get("path", ""))
        custom_hash = str(custom_info.get("sha256", "")).lower()
        if non_usfm_files != [custom_relative] or not SHA256_RE.fullmatch(custom_hash):
            raise GenerationError("Published custom VRS inventory is invalid")
        if file_hashes.get(custom_relative) != custom_hash:
            raise GenerationError("Published custom VRS hash does not match file inventory")
        effective_sources = dict(manifest.get("effective_vrs", {})).get("source_files", [])
        expected_hashes = {
            str(item.get("sha256", "")).lower()
            for item in effective_sources
            if isinstance(item, dict)
            and str(item.get("path", "")).startswith(
                f"project:{manifest.get('project_id', '')}/"
            )
        }
        if expected_hashes != {custom_hash}:
            raise GenerationError("Published custom VRS does not match effective VRS provenance")
    else:
        raise GenerationError("Published custom VRS metadata must be a mapping or null")

    actual_inventory_hash = sha256_paths(
        [project_root / relative for relative in sorted(expected_files)],
        relative_to=project_root,
    )
    if actual_inventory_hash != manifest.get("published_files_sha256"):
        raise GenerationError(
            "Published generation aggregate hash does not match its manifest"
        )
    validation_provenance = _validated_validation_provenance(
        manifest.get("validation_provenance")
    )
    fingerprint = _generation_fingerprint(
        project_id=str(manifest.get("project_id", "")),
        resource_sha256=str(manifest.get("resource_sha256", "")),
        source_fingerprints=dict(manifest.get("source_fingerprints", {})),
        grammar_contracts=dict(manifest.get("grammar_contracts", {})),
        effective_vrs_sha256=str(
            dict(manifest.get("effective_vrs", {})).get("effective_sha256", "")
        ),
        project_scope=dict(manifest.get("project_scope", {})),
        structure_policy_sha256=validation_provenance["structure_policy_sha256"],
        usj_compiler=validation_provenance["usj_compiler"],
        sage_version=str(manifest.get("sage_version", "")),
        publication_basis=publication_basis,
    )
    if fingerprint != manifest.get("generation_fingerprint"):
        raise GenerationError("Generation fingerprint does not match its provenance fields")
    return manifest


def resolve_generation(publication_root: Path, project_id: str, selector: str) -> Path:
    """Resolve ``current`` or an explicit immutable generation ID."""
    project_root = publication_root / project_id
    if selector == "current":
        pointer_path = project_root / "current.json"
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GenerationError(f"Invalid generation pointer {pointer_path}: {exc}") from exc
        selector = str(pointer.get("generation_id", ""))
    if not selector or any(part in {"..", ""} for part in Path(selector).parts):
        raise GenerationError(f"Invalid generation selector: {selector!r}")
    path = (project_root / selector).resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError as exc:
        raise GenerationError(f"Generation selector escapes publication root: {selector}") from exc
    verify_generation(path)
    return path
