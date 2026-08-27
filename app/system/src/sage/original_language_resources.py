"""Governed Greek/Hebrew resource defaults with explicit operator override support."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .atomic import atomic_write_json
from .canon import NT_27, OT_39
from .errors import ConfigurationError, ValidationError
from .project_inventory import detect_scripture_books
from .resource_mounts import normalize_operator_path
from .storage import storage_layout

SCHEMA_VERSION = "1.0"
OL_RESOURCE_IDS = ("GRK", "HEB")
OL_ALIASES = {"GRK": "@GRK", "HEB": "@HEB"}
OL_LANGUAGE_CODES = {"GRK": "grc", "HEB": "hbo"}
OL_DISPLAY_NAMES = {"GRK": "Greek original-language resource", "HEB": "Hebrew original-language resource"}
OL_BUNDLED_SUBDIRS = {"GRK": "grk", "HEB": "heb"}
OL_PARATEXT_PATTERNS = {
    "GRK": re.compile(r"^grcSRCv[0-9]$"),
    "HEB": re.compile(r"^hboSRCv[0-9]$"),
}


def ol_state_path(root: Path) -> Path:
    """Return the operator-owned OL source-selection state path."""
    return storage_layout(root).state_root / "original-language-resources.json"


def bundled_ol_path(root: Path, resource_id: str) -> Path:
    """Resolve one stable logical alias to its packaged default directory."""
    rid = resource_id.strip().upper()
    if rid not in OL_RESOURCE_IDS:
        raise ValidationError(f"Unsupported original-language resource: {resource_id}", code="OL_RESOURCE_ID_INVALID")
    return (
        root.expanduser().resolve()
        / "system"
        / "resources"
        / "scripture"
        / "original-language"
        / OL_BUNDLED_SUBDIRS[rid]
    )


def _default_state() -> dict[str, Any]:
    """Return the immutable default selection of both bundled OL aliases."""
    return {
        "schema_version": SCHEMA_VERSION,
        "resources": {
            "GRK": {"source": "BUNDLED"},
            "HEB": {"source": "BUNDLED"},
        },
    }


def load_ol_state(root: Path) -> dict[str, Any]:
    """Load explicit OL overrides, falling back to bundled aliases when state is absent."""
    path = ol_state_path(root)
    if not path.is_file():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid original-language resource state: {path}: {exc}") from exc
    if not isinstance(raw, dict) or str(raw.get("schema_version")) != SCHEMA_VERSION:
        raise ConfigurationError(f"Unsupported original-language resource state: {path}")
    resources = raw.get("resources", {})
    if not isinstance(resources, dict):
        raise ConfigurationError("original-language resources must be a mapping")
    result = _default_state()
    for rid in OL_RESOURCE_IDS:
        value = resources.get(rid)
        if isinstance(value, dict):
            result["resources"][rid] = dict(value)
    return result


def _write_ol_state(root: Path, state: dict[str, Any]) -> Path:
    """Persist OL source selections atomically under operator state."""
    destination = ol_state_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, state)
    return destination


def configure_ol_resource(
    root: Path,
    *,
    resource_id: str,
    source: str,
    path: Path | None = None,
    paratext_project: str | None = None,
) -> Path:
    """Persist an explicit OL source choice without registering it as a normal Project."""
    rid = resource_id.strip().upper()
    if rid not in OL_RESOURCE_IDS:
        raise ValidationError(f"Unsupported original-language resource: {resource_id}", code="OL_RESOURCE_ID_INVALID")
    source_kind = source.strip().upper()
    if source_kind not in {"BUNDLED", "PARATEXT", "LOCAL"}:
        raise ValidationError(f"Unsupported original-language source type: {source}", code="OL_RESOURCE_SOURCE_INVALID")
    entry: dict[str, Any] = {"source": source_kind}
    if source_kind != "BUNDLED":
        if path is None:
            raise ValidationError("An absolute original-language resource folder is required", code="OL_RESOURCE_PATH_INVALID")
        value = Path(normalize_operator_path(str(path))).expanduser()
        if not value.is_absolute():
            raise ValidationError("Original-language resource path must be absolute", code="OL_RESOURCE_PATH_INVALID")
        value = value.resolve()
        if not value.is_dir():
            raise ValidationError(f"Original-language resource folder not found: {value}", code="OL_RESOURCE_NOT_FOUND")
        entry["path"] = str(value)
        if source_kind == "PARATEXT":
            code = str(paratext_project or value.name).strip()
            entry["paratext_project"] = code
    state = load_ol_state(root)
    state["resources"][rid] = entry
    return _write_ol_state(root, state)


def restore_bundled_ol_defaults(root: Path) -> Path:
    """Restore both logical OL aliases to their packaged resource locations."""
    return _write_ol_state(root, _default_state())


def resolved_ol_entry(root: Path, resource_id: str) -> dict[str, Any]:
    """Resolve one configured alias to a concrete path and validation status."""
    rid = resource_id.strip().upper()
    if rid not in OL_RESOURCE_IDS:
        raise ValidationError(f"Unsupported original-language resource: {resource_id}", code="OL_RESOURCE_ID_INVALID")
    state = load_ol_state(root)
    configured = dict(state["resources"].get(rid, {"source": "BUNDLED"}))
    source = str(configured.get("source", "BUNDLED")).upper()
    if source == "BUNDLED":
        path = bundled_ol_path(root, rid)
    else:
        raw_path = configured.get("path")
        path = Path(str(raw_path)).expanduser().resolve() if raw_path else Path("/") / "__missing__"
    books = detect_scripture_books(path) if path.is_dir() else ()
    expected = set(NT_27 if rid == "GRK" else OT_39)
    outside = sorted(set(books) - expected)
    missing = sorted(expected - set(books))
    if not path.is_dir():
        status = "MISSING"
        code = "OL_RESOURCE_FOLDER_NOT_FOUND"
    elif not books:
        status = "MISSING"
        code = "OL_RESOURCE_SCRIPTURE_NOT_FOUND"
    elif outside:
        status = "WARNING"
        code = "OL_RESOURCE_UNEXPECTED_BOOKS"
    elif source == "BUNDLED" and missing:
        status = "WARNING"
        code = "OL_RESOURCE_INCOMPLETE_BUNDLED_CANON"
    else:
        status = "READY"
        code = None
    return {
        "resource_id": rid,
        "alias": OL_ALIASES[rid],
        "display_name": OL_DISPLAY_NAMES[rid],
        "language_code": OL_LANGUAGE_CODES[rid],
        "source": source,
        "path": str(path),
        "paratext_project": configured.get("paratext_project"),
        "books": list(books),
        "expected_books": list(NT_27 if rid == "GRK" else OT_39),
        "missing_books": missing,
        "source_format": "USFM",
        "comparison_format": "USJ",
        "status": status,
        "code": code,
    }


def validate_original_language_resources(root: Path) -> dict[str, Any]:
    """Return a non-fatal capability status for the two governed OL aliases."""
    rows = [resolved_ol_entry(root, rid) for rid in OL_RESOURCE_IDS]
    ready = sum(1 for row in rows if row["status"] == "READY")
    status = "READY" if ready == 2 else ("PARTIAL" if ready else "UNAVAILABLE")
    return {"schema_version": SCHEMA_VERSION, "status": status, "resources": rows}


def paratext_ol_candidates(catalogue: Mapping[str, Any], resource_id: str) -> tuple[dict[str, Any], ...]:
    """Return recognized ``grcSRCv#``/``hboSRCv#`` override candidates from the catalog."""
    rid = resource_id.strip().upper()
    pattern = OL_PARATEXT_PATTERNS[rid]
    language = OL_LANGUAGE_CODES[rid]
    rows: list[dict[str, Any]] = []
    projects = catalogue.get("projects", {}) if isinstance(catalogue, Mapping) else {}
    if isinstance(projects, Mapping):
        for code, value in projects.items():
            if not isinstance(value, Mapping):
                continue
            if pattern.fullmatch(str(code)) and str(value.get("language_iso") or "").casefold() == language:
                rows.append(dict(value))
    return tuple(sorted(rows, key=lambda row: int((row.get("code_metadata") or {}).get("iteration") or -1), reverse=True))


def active_ol_project_id(root: Path, resource_id: str) -> str | None:
    """Return the stable machine binding ID only when the configured alias is usable."""
    row = resolved_ol_entry(root, resource_id)
    return str(row["resource_id"]) if row["status"] == "READY" else None


def active_ol_provenance(root: Path) -> dict[str, Any]:
    """Return stable provenance for Job/run reporting."""
    return {rid: resolved_ol_entry(root, rid) for rid in OL_RESOURCE_IDS}


def apply_original_language_resources(raw: dict[str, Any], root: Path) -> dict[str, Any]:
    """Inject READY governed OL aliases into runtime configuration as read-only resources."""
    projects = raw.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise ConfigurationError("projects must be a mapping")
    for rid in OL_RESOURCE_IDS:
        row = resolved_ol_entry(root, rid)
        # Never override an explicit fixture/static declaration. This keeps tests and
        # controlled evaluation settings deterministic while production config remains empty.
        if rid in projects or row["status"] != "READY":
            continue
        books = tuple(str(book) for book in row["books"])
        expected = set(NT_27 if rid == "GRK" else OT_39)
        if set(books) == expected:
            testament = "NT" if rid == "GRK" else "OT"
            canon = "GREEK_NT_27" if rid == "GRK" else "HEBREW_BIBLE_39"
        else:
            testament = "PORTIONS"
            canon = "GREEK_NT_27" if rid == "GRK" and set(books).issubset(set(NT_27)) else (
                "HEBREW_BIBLE_39" if rid == "HEB" and set(books).issubset(set(OT_39)) else "CUSTOM"
            )
        projects[rid] = {
            "project_id": rid,
            "display_name": row["display_name"],
            "enabled": False,
            "path": rid,
            "external_path": row["path"],
            "external_access_mode": "READ_ONLY_SCRIPTURE",
            "language": {"code": row["language_code"], "profile": row["language_code"]},
            "format": "USFM",
            "kind": "SCRIPTURE",
            "content_state": "LOCKED",
            "scope": {
                "testament": testament,
                "canon": canon,
                "expected_books": list(books),
                "roles": [],
            },
            "coverage_policy": "CONFIGURED_BOOKS_COMPLETE",
            "versification": {"base_file": "org.vrs", "custom_file": "auto"},
            "allow_empty": False,
            "governed_alias": OL_ALIASES[rid],
            "ol_provenance": row,
        }
    return raw
