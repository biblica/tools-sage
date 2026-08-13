"""Semantic-index input fingerprints and freshness gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from ..hashing import sha256_bytes, sha256_file
from ..registry import EcosystemConfig
from .store import (
    authority_root,
    index_root,
    import_root,
    load_authority_selection,
    load_import_selection,
    review_state_path,
)

INDEX_MANIFEST_SCHEMA = "2.0"


def _canonical_hash(payload: Any) -> str:
    """Hash one JSON-serialisable semantic descriptor in canonical form."""
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(data.encode("utf-8"))


def semantic_input_descriptor(config: EcosystemConfig, language: str) -> dict[str, Any]:
    """Describe every local input that can change generated semantic indexes."""
    imports: list[dict[str, Any]] = []
    for source_id in load_import_selection(config, language):
        records = import_root(config, language, source_id) / "records.json"
        manifest = import_root(config, language, source_id) / "manifest.json"
        if not records.is_file() or not manifest.is_file():
            raise ValidationError(f"Active semantic import is incomplete: {source_id}")
        imports.append(
            {
                "source_id": source_id,
                "records_sha256": sha256_file(records),
                "manifest_sha256": sha256_file(manifest),
            }
        )

    selection = load_authority_selection(config)
    authorities: dict[str, dict[str, str]] = {}
    semdom_source = selection.get("sil_semdom")
    if semdom_source:
        path = authority_root(config) / "sil-semdom" / semdom_source / "domains.json"
        if not path.is_file():
            raise ValidationError(f"Selected SIL Semantic Domains source is missing: {semdom_source}")
        authorities["sil_semdom"] = {
            "source_id": semdom_source,
            "content_sha256": sha256_file(path),
        }
    folder_source = selection.get("rapidwords_folders")
    if folder_source:
        path = authority_root(config) / "rapidwords-folders" / folder_source / "folders.json"
        if not path.is_file():
            raise ValidationError(f"Selected RapidWords folder source is missing: {folder_source}")
        authorities["rapidwords_folders"] = {
            "source_id": folder_source,
            "content_sha256": sha256_file(path),
        }

    review_path = review_state_path(config, language)
    review_sha = sha256_file(review_path) if review_path.is_file() else None
    return {
        "schema_version": "1.0",
        "language": language,
        "active_imports": imports,
        "active_authorities": authorities,
        "review_state_sha256": review_sha,
    }


def current_input_fingerprint(config: EcosystemConfig, language: str) -> tuple[str, dict[str, Any]]:
    """Hash the complete active semantic input descriptor deterministically."""
    descriptor = semantic_input_descriptor(config, language)
    return _canonical_hash(descriptor), descriptor


def index_manifest_path(config: EcosystemConfig, language: str) -> Path:
    """Return the generated semantic index manifest path."""
    return index_root(config, language) / "index-manifest.json"


def semantic_index_state(config: EcosystemConfig, language: str) -> dict[str, Any]:
    """Return CURRENT, STALE, MISSING, or INVALID for one semantic index set."""
    manifest_path = index_manifest_path(config, language)
    if not manifest_path.is_file():
        return {"state": "MISSING", "reason": "Index manifest is absent."}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"state": "INVALID", "reason": f"Index manifest cannot be read: {exc}"}
    if not isinstance(manifest, dict) or manifest.get("schema_version") != INDEX_MANIFEST_SCHEMA:
        return {
            "state": "INVALID",
            "reason": f"Index manifest must use schema {INDEX_MANIFEST_SCHEMA}; rebuild indexes.",
        }
    try:
        current, descriptor = current_input_fingerprint(config, language)
    except ValidationError as exc:
        return {"state": "INVALID", "reason": str(exc)}
    built = str(manifest.get("input_fingerprint", ""))
    if not built or built != current:
        return {
            "state": "STALE",
            "reason": "Active imports, selected authorities, or reviewed evidence changed after the index build.",
            "built_fingerprint": built or None,
            "current_fingerprint": current,
        }
    return {
        "state": "CURRENT",
        "input_fingerprint": current,
        "descriptor": descriptor,
    }



def _structural_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic inputs that define sense identity, excluding review-state overlays."""
    return {
        "schema_version": descriptor.get("schema_version"),
        "language": descriptor.get("language"),
        "active_imports": descriptor.get("active_imports", []),
        "active_authorities": descriptor.get("active_authorities", {}),
    }


def require_reviewable_index(config: EcosystemConfig, language: str) -> dict[str, Any]:
    """Allow batched human review only while imports/authorities still match the built index."""
    manifest_path = index_manifest_path(config, language)
    if not manifest_path.is_file():
        raise ValidationError(f"Semantic indexes for {language} are MISSING; build them before semantic evidence review.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Semantic indexes for {language} are INVALID: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != INDEX_MANIFEST_SCHEMA:
        raise ValidationError(
            f"Semantic indexes for {language} are INVALID; rebuild them before semantic evidence review."
        )
    built_descriptor = manifest.get("input_descriptor")
    if not isinstance(built_descriptor, dict):
        raise ValidationError(
            f"Semantic indexes for {language} lack a valid input descriptor; rebuild before semantic evidence review."
        )
    current_descriptor = semantic_input_descriptor(config, language)
    if _canonical_hash(_structural_descriptor(built_descriptor)) != _canonical_hash(
        _structural_descriptor(current_descriptor)
    ):
        raise ValidationError(
            f"Semantic indexes for {language} are structurally STALE; active imports or selected authorities changed. "
            "Rebuild before semantic evidence review."
        )
    fully_current = str(manifest.get("input_fingerprint", "")) == _canonical_hash(current_descriptor)
    return {
        "state": "CURRENT" if fully_current else "REVIEW_PENDING",
        "review_changes_pending": not fully_current,
        "built_descriptor": built_descriptor,
        "current_descriptor": current_descriptor,
    }

def require_current_index(config: EcosystemConfig, language: str, *, purpose: str) -> dict[str, Any]:
    """Fail closed when a bound semantic index is missing, stale, or invalid."""
    state = semantic_index_state(config, language)
    if state.get("state") != "CURRENT":
        raise ValidationError(
            f"Semantic indexes for {language} are {state.get('state')}; rebuild them before {purpose}. "
            f"{state.get('reason', '')}".strip()
        )
    return state
