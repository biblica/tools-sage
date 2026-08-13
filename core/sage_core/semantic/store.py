"""Filesystem layout and immutable snapshot helpers for semantic resources."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_json
from ..errors import ValidationError
from ..hashing import sha256_file
from ..registry import EcosystemConfig

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def safe_id(value: str, label: str) -> str:
    """Validate one path component used by the semantic store."""
    normalized = str(value).strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValidationError(
            f"{label} must start with an alphanumeric character and use only letters, digits, dot, underscore, or hyphen"
        )
    return normalized


def semantic_root(config: EcosystemConfig) -> Path:
    """Return the project-local semantic/RWC workspace root."""
    return config.workspace_data_root / "sage" / "semantic"


def language_root(config: EcosystemConfig, language: str) -> Path:
    """Return one language namespace without conflating it with a Paratext project ID."""
    return semantic_root(config) / "languages" / safe_id(language, "language")


def authority_root(config: EcosystemConfig) -> Path:
    """Return the immutable authority-resource root."""
    return semantic_root(config) / "authority"


def import_root(config: EcosystemConfig, language: str, source_id: str) -> Path:
    """Return one immutable import snapshot directory."""
    return language_root(config, language) / "imports" / safe_id(source_id, "source_id")


def import_selection_path(config: EcosystemConfig, language: str) -> Path:
    """Return the external active-import selection path for one language namespace."""
    return language_root(config, language) / "imports-active.json"


def available_import_ids(config: EcosystemConfig, language: str) -> list[str]:
    """List immutable semantic import identifiers without changing active selection."""
    root = language_root(config, language) / "imports"
    if not root.is_dir():
        return []
    return sorted(path.parent.name for path in root.glob("*/manifest.json"))


def load_import_selection(config: EcosystemConfig, language: str) -> list[str]:
    """Load the explicit active semantic-import registry; absence means no active imports."""
    import json

    path = import_selection_path(config, language)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid semantic import selection {path}: {exc}") from exc
    active = raw.get("active", []) if isinstance(raw, dict) else []
    if not isinstance(active, list) or any(not isinstance(value, str) for value in active):
        raise ValidationError("Semantic import selection must contain an active list")
    available = set(available_import_ids(config, language))
    unknown = sorted(set(active) - available)
    if unknown:
        raise ValidationError(f"Semantic import selection cites unavailable imports: {', '.join(unknown)}")
    return sorted(set(active))


def set_import_active(
    config: EcosystemConfig,
    *,
    language: str,
    source_id: str,
    active: bool,
) -> list[str]:
    """Activate or deactivate one immutable import through a separate selection registry."""
    safe_source = safe_id(source_id, "source_id")
    manifest = import_root(config, language, safe_source) / "manifest.json"
    if not manifest.is_file():
        raise ValidationError(f"Semantic import is not available for {language}: {source_id}")
    selected = set(load_import_selection(config, language))
    if active:
        selected.add(safe_source)
    else:
        selected.discard(safe_source)
    atomic_write_json(
        import_selection_path(config, language),
        {
            "schema_version": "1.0",
            "language": safe_id(language, "language"),
            "active": sorted(selected),
            "rule": "Import snapshots are immutable; this external registry controls which snapshots feed generated indexes.",
        },
    )
    return sorted(selected)


def ensure_import_active(config: EcosystemConfig, *, language: str, source_id: str) -> list[str]:
    """Activate a newly imported immutable snapshot without changing any other selection."""
    return set_import_active(config, language=language, source_id=source_id, active=True)


def index_root(config: EcosystemConfig, language: str) -> Path:
    """Return one generated local semantic-index directory."""
    return language_root(config, language) / "indexes"


def export_root(config: EcosystemConfig, language: str) -> Path:
    """Return one generated interchange-export directory."""
    return language_root(config, language) / "exports"


def snapshot_file(source: Path, destination: Path) -> dict[str, Any]:
    """Copy one source file into an immutable snapshot and return its provenance."""
    source = source.resolve()
    if not source.is_file():
        raise ValidationError(f"Semantic source file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing = sha256_file(destination)
        incoming = sha256_file(source)
        if existing != incoming:
            raise ValidationError(
                f"Immutable semantic snapshot already exists with different content: {destination}"
            )
    else:
        shutil.copy2(source, destination)
    return {
        "source_path": str(source),
        "snapshot_path": str(destination),
        "sha256": sha256_file(destination),
        "bytes": destination.stat().st_size,
    }


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    """Write one deterministic semantic-resource manifest."""
    atomic_write_json(path, payload)


def bindings_path(config: EcosystemConfig) -> Path:
    """Return the project-to-semantic-language binding registry path."""
    return semantic_root(config) / "bindings.json"


def load_bindings(config: EcosystemConfig) -> dict[str, str]:
    """Load local semantic bindings without mutating state."""
    import json

    path = bindings_path(config)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid semantic bindings file {path}: {exc}") from exc
    bindings = raw.get("bindings", {}) if isinstance(raw, dict) else {}
    if not isinstance(bindings, dict):
        raise ValidationError("Semantic bindings must be a mapping")
    return {str(key): str(value) for key, value in bindings.items()}


def set_binding(config: EcosystemConfig, *, project_id: str, language: str) -> dict[str, str]:
    """Bind one SAGE Project/resource identifier to a semantic language namespace."""
    config.project(project_id)
    namespace = safe_id(language, "language")
    bindings = load_bindings(config)
    bindings[project_id] = namespace
    atomic_write_json(
        bindings_path(config),
        {
            "schema_version": "1.0",
            "bindings": dict(sorted(bindings.items())),
            "rule": "Project IDs identify Scripture resources; semantic namespaces identify languages and must remain distinct.",
        },
    )
    return bindings


def semantic_language_for_project(config: EcosystemConfig, project_id: str) -> str | None:
    """Resolve an explicit semantic namespace for one project; never infer KKH from idKKHv0."""
    return load_bindings(config).get(project_id)

def authority_selection_path(config: EcosystemConfig) -> Path:
    """Return the explicit active semantic-authority selection path."""
    return authority_root(config) / "active.json"


def load_authority_selection(config: EcosystemConfig) -> dict[str, str]:
    """Load active authority source IDs without selecting among multiple imports implicitly."""
    import json

    path = authority_selection_path(config)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid semantic authority selection {path}: {exc}") from exc
    active = raw.get("active", {}) if isinstance(raw, dict) else {}
    if not isinstance(active, dict):
        raise ValidationError("Semantic authority selection must contain an active mapping")
    return {str(key): str(value) for key, value in active.items()}


def set_authority_selection(
    config: EcosystemConfig,
    *,
    authority_type: str,
    source_id: str,
) -> dict[str, str]:
    """Select one already imported semantic authority source explicitly."""
    kinds = {
        "semdom": ("sil_semdom", authority_root(config) / "sil-semdom"),
        "folders": ("rapidwords_folders", authority_root(config) / "rapidwords-folders"),
    }
    normalized = str(authority_type).strip().casefold()
    if normalized not in kinds:
        raise ValidationError("authority_type must be semdom or folders")
    key, root = kinds[normalized]
    safe_source = safe_id(source_id, "source_id")
    manifest = root / safe_source / "manifest.json"
    if not manifest.is_file():
        raise ValidationError(f"Semantic authority source is not imported: {source_id}")
    active = load_authority_selection(config)
    active[key] = safe_source
    atomic_write_json(
        authority_selection_path(config),
        {
            "schema_version": "1.0",
            "active": dict(sorted(active.items())),
            "rule": "Authority selection controls classification/traversal metadata only; it never grants translation authority.",
        },
    )
    return active


def ensure_authority_selected(
    config: EcosystemConfig,
    *,
    authority_type: str,
    source_id: str,
) -> dict[str, str]:
    """Select the first imported source for one authority type while preserving later explicit choice."""
    key = "sil_semdom" if authority_type == "semdom" else "rapidwords_folders"
    active = load_authority_selection(config)
    if key in active:
        return active
    return set_authority_selection(config, authority_type=authority_type, source_id=source_id)



def review_state_path(config: EcosystemConfig, language: str) -> Path:
    """Return the governed sense-review state registry for one semantic namespace."""
    return language_root(config, language) / "review-status.json"


def load_review_states(config: EcosystemConfig, language: str) -> dict[str, dict[str, Any]]:
    """Load explicit sense-level review states; imported evidence never populates this registry."""
    import json

    path = review_state_path(config, language)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid semantic review registry {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValidationError("Semantic review registry must use schema 1.0")
    entries = raw.get("senses", {})
    if not isinstance(entries, dict):
        raise ValidationError("Semantic review registry must contain a senses mapping")
    return {
        str(sense_id): dict(value)
        for sense_id, value in entries.items()
        if isinstance(value, dict)
    }


def set_review_state(
    config: EcosystemConfig,
    *,
    language: str,
    sense_id: str,
    status: str,
    reviewer: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Set one explicit reviewed evidence state with human provenance."""
    from datetime import datetime, timezone

    from .policy import REVIEW_STATES

    normalized_status = str(status).strip().upper()
    if normalized_status not in REVIEW_STATES:
        raise ValidationError(
            "Reviewed semantic status must be one of " + ", ".join(REVIEW_STATES)
        )
    normalized_reviewer = str(reviewer).strip()
    if not normalized_reviewer:
        raise ValidationError("reviewer is required for semantic evidence-state changes")
    normalized_sense = safe_id(sense_id, "sense_id")

    # A review action must cite a sense in a current generated index.
    from .freshness import require_reviewable_index
    require_reviewable_index(config, language)
    sense_path = index_root(config, language) / "sense-semdom.json"
    if not sense_path.is_file():
        raise ValidationError(f"Build semantic indexes for {language} before reviewing evidence states")
    import json

    try:
        sense_doc = json.loads(sense_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid semantic sense index {sense_path}: {exc}") from exc
    senses = sense_doc.get("senses", {}) if isinstance(sense_doc, dict) else {}
    if normalized_sense not in senses:
        raise ValidationError(f"Semantic sense is not present in the current index: {sense_id}")

    entries = load_review_states(config, language)
    entry = {
        "status": normalized_status,
        "reviewer": normalized_reviewer,
        "note": str(note or "").strip(),
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    entries[normalized_sense] = entry
    atomic_write_json(
        review_state_path(config, language),
        {
            "schema_version": "1.0",
            "language": safe_id(language, "language"),
            "senses": dict(sorted(entries.items())),
            "rule": (
                "Import provenance never grants TEAM_CONFIRMED, ESTABLISHED, or APPROVED. "
                "Those states require an explicit governed review action."
            ),
        },
    )
    return {"language": language, "sense_id": normalized_sense, **entry}


def clear_review_state(config: EcosystemConfig, *, language: str, sense_id: str) -> dict[str, Any]:
    """Remove one explicit sense review so the imported evidence state becomes effective again."""
    normalized_sense = safe_id(sense_id, "sense_id")
    entries = load_review_states(config, language)
    existed = normalized_sense in entries
    entries.pop(normalized_sense, None)
    if entries:
        atomic_write_json(
            review_state_path(config, language),
            {
                "schema_version": "1.0",
                "language": safe_id(language, "language"),
                "senses": dict(sorted(entries.items())),
                "rule": (
                    "Import provenance never grants TEAM_CONFIRMED, ESTABLISHED, or APPROVED. "
                    "Those states require an explicit governed review action."
                ),
            },
        )
    else:
        review_state_path(config, language).unlink(missing_ok=True)
    return {"language": language, "sense_id": normalized_sense, "cleared": existed}
