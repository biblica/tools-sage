"""Operator-owned Scripture-project inventory for SAGE."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .atomic import atomic_write_json
from .canon import BOOK_ORDER, NT_27, OT_39
from .errors import ConfigurationError, ValidationError
from .project_codes import DEFAULT_TYPE_CODES, parse_project_code, project_code_is_path_safe
from .storage import storage_layout

SCHEMA_VERSION = "1.0"
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,7}$")
BOOK_ID_RE = re.compile(rb"(?m)^\\id[ \t]+([A-Za-z0-9]{3})(?:[ \t\r]|$)")


def project_inventory_path(root: Path) -> Path:
    """Return the operator-owned SAGE Project Inventory path."""
    return storage_layout(root).state_root / "project-inventory.json"


def project_registry_path(root: Path) -> Path:
    """Compatibility alias for the current SAGE Project Inventory path."""
    return project_inventory_path(root)


def load_project_registry(root: Path) -> dict[str, Any]:
    """Load operator-owned SAGE Projects. Missing state is an empty inventory."""
    path = project_registry_path(root)
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "projects": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid SAGE Project Inventory file: {path}: {exc}") from exc
    if not isinstance(raw, dict) or str(raw.get("schema_version")) != SCHEMA_VERSION:
        raise ConfigurationError(f"Unsupported SAGE Project Inventory file: {path}")
    projects = raw.get("projects", {})
    if not isinstance(projects, dict):
        raise ConfigurationError("SAGE Project Inventory projects must be a mapping")
    return {"schema_version": SCHEMA_VERSION, "projects": dict(projects)}


def write_project_registry(root: Path, state: dict[str, Any]) -> Path:
    """Persist the role-neutral Project inventory atomically."""
    destination = project_registry_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "projects": dict(state.get("projects", {}))}
    atomic_write_json(destination, payload)
    return destination


def _peek_book_id(path: Path) -> str | None:
    """Read only enough of one .SFM file to validate its canonical USFM book ID."""
    try:
        with path.open("rb") as handle:
            prefix = handle.read(65536)
    except OSError:
        return None
    match = BOOK_ID_RE.search(prefix)
    if not match:
        return None
    code = match.group(1).decode("ascii").upper()
    return code if code in BOOK_ORDER else None


def detect_scripture_books(project_path: Path) -> tuple[str, ...]:
    """Detect valid canonical books from readable top-level .SFM files only."""
    root = project_path.expanduser().resolve()
    if not root.is_dir():
        return ()
    books: set[str] = set()
    for path in root.iterdir():
        if not path.is_file() or path.is_symlink() or path.suffix.casefold() != ".sfm":
            continue
        book = _peek_book_id(path)
        if book:
            books.add(book)
    return tuple(sorted(books, key=BOOK_ORDER.__getitem__))


def summarize_scope(books: tuple[str, ...]) -> str:
    """Render a compact FB/OT/NT/portion summary from detected canonical books."""
    values = set(books)
    if values == set(OT_39 + NT_27):
        return "FB"
    if values == set(OT_39):
        return "OT"
    if values == set(NT_27):
        return "NT"
    if not books:
        return "NONE"
    if len(books) <= 6:
        return ",".join(books)
    return f"{len(books)} BOOKS"


def scope_testament(books: tuple[str, ...]) -> str:
    """Map detected canonical books to the governed testament/scope category."""
    values = set(books)
    if values == set(OT_39 + NT_27):
        return "FB"
    if values and values.issubset(set(OT_39)):
        return "OT" if values == set(OT_39) else "PORTIONS"
    if values and values.issubset(set(NT_27)):
        return "NT" if values == set(NT_27) else "PORTIONS"
    return "PORTIONS"


def project_code_policy(raw: Mapping[str, Any]) -> dict[str, str]:
    """Return the configured lowercase project-type code mapping."""
    policy = raw.get("project_codes", {})
    if not isinstance(policy, Mapping):
        policy = {}
    types_raw = policy.get("type_codes", DEFAULT_TYPE_CODES)
    types = {
        str(key): str(value)
        for key, value in (types_raw.items() if isinstance(types_raw, Mapping) else DEFAULT_TYPE_CODES.items())
    }
    return types


def register_project(
    root: Path,
    *,
    project_id: str,
    project_path: Path,
    language_code: str,
    language_profile: str | None = None,
    profile_variant: str | None = None,
    base_vrs_file: str,
    display_name: str | None = None,
    kind: str = "SCRIPTURE",
    content_state: str = "LOCKED",
    allow_empty: bool = False,
    coverage_policy: str = "CONFIGURED_BOOKS_COMPLETE",
    type_codes: Mapping[str, str] | None = None,
    declared_books: tuple[str, ...] | None = None,
    paratext_metadata: Mapping[str, Any] | None = None,
    versification_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Add one role-neutral Scripture Project to SAGE and return its stored record."""
    project_id = project_id.strip()
    if not PROJECT_ID_RE.fullmatch(project_id) or not project_code_is_path_safe(project_id):
        raise ValidationError(
            "Paratext project code must be at most 8 cross-platform-safe characters and not a Windows reserved path name",
            code="PROJECT_ID_INVALID",
        )
    path = project_path.expanduser().resolve()
    if not path.is_dir():
        raise ValidationError(f"Project folder not found: {path}", code="PROJECT_FOLDER_NOT_FOUND")
    sfm_books = detect_scripture_books(path)
    books = tuple(declared_books) if declared_books else sfm_books
    if not sfm_books and not allow_empty:
        raise ValidationError(
            f"Project folder does not contain readable canonical Scripture .SFM files: {path}",
            code="PROJECT_SCRIPTURE_NOT_FOUND",
        )
    base = base_vrs_file.strip()
    if Path(base).name != base or Path(base).suffix.casefold() != ".vrs":
        raise ValidationError("Base VRS must be one .vrs filename", code="BASE_VRS_FILE_INVALID")
    parts = parse_project_code(project_id, type_codes=type_codes)
    state = load_project_registry(root)
    if project_id in state["projects"]:
        raise ValidationError(f"Project is already in SAGE: {project_id}", code="PROJECT_ALREADY_IN_SAGE")
    language: dict[str, Any] = {"code": language_code, "profile": language_profile or language_code}
    if profile_variant:
        language["variant"] = profile_variant
    record: dict[str, Any] = {
        "project_id": project_id,
        "display_name": (display_name or project_id).strip() or project_id,
        "enabled": False,
        "path": project_id,
        "language": language,
        "format": "USFM",
        "kind": kind.strip().upper(),
        "content_state": content_state.strip().upper(),
        "scope": {
            "testament": scope_testament(books),
            "canon": "PROTESTANT_66",
            "expected_books": list(books) if books else ["MAT"],
            "roles": [],
        },
        "detected_books": list(books),
        "sfm_books": list(sfm_books),
        "scope_summary": summarize_scope(books),
        "coverage_policy": coverage_policy.strip().upper(),
        "versification": {"base_file": base, "custom_file": "auto", **dict(versification_metadata or {})},
        "paratext_metadata": dict(paratext_metadata or {}),
        "allow_empty": bool(allow_empty),
        "code_metadata": parts.to_dict(),
        "validation_status": "VALID" if books or allow_empty else "BLOCKED",
    }
    state["projects"][project_id] = record
    write_project_registry(root, state)
    return record


def registered_project_records(root: Path) -> dict[str, dict[str, Any]]:
    """Return a defensive copy of all SAGE Project Inventory records."""
    state = load_project_registry(root)
    return {str(key): dict(value) for key, value in state["projects"].items() if isinstance(value, dict)}


def merge_registered_projects(raw: dict[str, Any], root: Path) -> dict[str, Any]:
    """Overlay operator inventory onto static configuration declarations in memory."""
    projects = raw.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise ConfigurationError("projects must be a mapping")
    runtime_context = raw.get("runtime_context", {})
    effective_job = isinstance(runtime_context, dict) and runtime_context.get("kind") == "JOB"
    versification = raw.get("versification", {})
    default_vrs = str(versification.get("default_file") or "eng.vrs").strip() or "eng.vrs"
    canonical_vrs = str(versification.get("canonical_file") or "org.vrs").strip() or "org.vrs"
    for project_id, record in registered_project_records(root).items():
        if effective_job and project_id in projects:
            continue
        effective = dict(record)
        vrs = dict(effective.get("versification") or {})
        reported = str(vrs.get("reported_base_file") or "").strip()
        selection = str(vrs.get("base_selection") or "").strip().upper()
        # Legacy registrations used canonical_file (org.vrs) when Paratext
        # declared no base.  Treat only that unmarked legacy shape as the default,
        # never an explicitly declared/operator-selected VRS.
        if not selection and not reported and str(vrs.get("base_file") or "").casefold() == canonical_vrs.casefold():
            vrs["base_file"] = default_vrs
            vrs["base_selection"] = "DEFAULT_LEGACY"
            effective["versification"] = vrs
        projects[project_id] = effective
    return raw


def update_project_record(root: Path, project_id: str, updates: Mapping[str, Any]) -> dict[str, Any]:
    """Apply operator-owned metadata updates without changing workflow role bindings."""
    state = load_project_registry(root)
    current = state["projects"].get(project_id)
    if not isinstance(current, dict):
        raise ValidationError(f"Project is not in SAGE: {project_id}", code="PROJECT_NOT_IN_SAGE")
    record = dict(current)
    record.update(dict(updates))
    state["projects"][project_id] = record
    write_project_registry(root, state)
    return record


def unregister_project(root: Path, *, project_id: str) -> None:
    """Remove one Project from SAGE only; external Paratext data is never deleted."""
    state = load_project_registry(root)
    state["projects"].pop(project_id, None)
    write_project_registry(root, state)
