"""Persistent Paratext/PTLite discovery catalog for fast SAGE menu construction."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from xml.etree import ElementTree as ET

from .atomic import atomic_write_json
from .storage import storage_layout
from .canon import BOOK_ORDER, NT_27, OT_39
from .errors import ConfigurationError, ValidationError
from .project_codes import parse_project_code
from .project_inventory import detect_scripture_books
from .iso_languages import resolve_paratext_language
from .language_identification import estimate_language_identity, parse_ldml_identity
from .resource_mounts import normalize_operator_path

SCHEMA_VERSION = "2.0"
LEGACY_SCHEMA_VERSION = "1.0"
CATALOG_FILENAME = "paratext-project-catalog.json"
_BOOK_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:[1-3][A-Z]{2}|[A-Z]{3})(?![A-Za-z0-9])")
_BASE_VRS_RE = re.compile(r"\b([A-Za-z0-9._-]+\.vrs)\b", re.IGNORECASE)
_VERSIFICATION_NAME_RE = re.compile(r"Versification\s+[\"']([^\"']+)[\"']", re.IGNORECASE)
_BASE_DESCRIPTION_RE = re.compile(r"\(([^)]*(?:versification|vrs)[^)]*)\)", re.IGNORECASE)


def _utc_now() -> str:
    """Return a stable UTC timestamp for catalog provenance."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def catalog_path(root: Path) -> Path:
    """Return the machine-local persisted Paratext discovery catalog path."""
    return storage_layout(root).state_root / CATALOG_FILENAME


def _clean_iso(value: str | None) -> str | None:
    """Normalize Paratext LanguageIsoCode values such as ``en:::`` to ``en``."""
    text = str(value or "").strip()
    if not text:
        return None
    primary = text.split(":", 1)[0].strip()
    return primary.casefold() or None


def _element_text(root: ET.Element, name: str) -> str | None:
    """Return the first non-empty element text matching a local XML tag name."""
    wanted = name.casefold()
    for element in root.iter():
        local = str(element.tag).rsplit("}", 1)[-1].casefold()
        if local == wanted and element.text and element.text.strip():
            return element.text.strip()
    return None


def parse_settings_xml(path: Path) -> dict[str, Any]:
    """Parse the small metadata subset SAGE needs from one Paratext ``settings.xml``."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValidationError(f"Invalid Paratext settings.xml: {path}: {exc}", code="PARATEXT_SETTINGS_INVALID") from exc
    language = _element_text(root, "Language")
    full_name = _element_text(root, "FullName")
    raw_iso = _element_text(root, "LanguageIsoCode")
    iso = _clean_iso(raw_iso)
    country_values = []
    for country_name in ("Country", "CountryCode", "LanguageCountry", "Countries"):
        value = _element_text(root, country_name)
        if value:
            country_values.extend(part.strip() for part in re.split(r"[,;|]", value) if part.strip())
    # A parseable XML file with none of the known Paratext project metadata is not a
    # valid discovery sentinel. This prevents unrelated settings.xml files appearing.
    if not any((language, full_name, raw_iso)):
        raise ValidationError(
            f"settings.xml does not contain recognized Paratext project metadata: {path}",
            code="PARATEXT_SETTINGS_METADATA_MISSING",
        )
    return {
        "language_name": language,
        "full_name": full_name,
        "language_iso_raw": raw_iso,
        "language_iso": iso,
        "country_values": country_values,
    }


def _book_tokens(values: Iterable[str]) -> tuple[str, ...]:
    """Extract supported canonical book IDs from arbitrary XML text/attributes."""
    found: set[str] = set()
    for value in values:
        for match in _BOOK_TOKEN_RE.findall(str(value).upper()):
            if match in BOOK_ORDER:
                found.add(match)
    return tuple(sorted(found, key=BOOK_ORDER.__getitem__))


def parse_canons_xml(path: Path) -> tuple[str, ...]:
    """Extract canonical USFM book IDs from Paratext ``canons.xml`` generically."""
    if not path.is_file():
        return ()
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValidationError(f"Invalid Paratext canons.xml: {path}: {exc}", code="PARATEXT_CANONS_INVALID") from exc
    values: list[str] = []
    for element in root.iter():
        if element.text:
            values.append(element.text)
        if element.tail:
            values.append(element.tail)
        values.extend(str(value) for value in element.attrib.values())
    return _book_tokens(values)


def parse_custom_vrs(path: Path) -> dict[str, Any]:
    """Parse descriptive base-VRS metadata from leading comments in ``custom.vrs``."""
    if not path.is_file():
        return {
            "file": None,
            "name": None,
            "base_file": None,
            "base_description": None,
            "metadata_status": "NONE",
        }
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as exc:
        raise ValidationError(f"Cannot read custom.vrs: {path}: {exc}", code="PARATEXT_CUSTOM_VRS_UNREADABLE") from exc
    comments: list[str] = []
    for line in lines[:80]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            comments.append(stripped.lstrip("#").strip())
            continue
        # Metadata convention is at the start of the file; stop at executable VRS data.
        break
    text = "\n".join(comments)
    name_match = _VERSIFICATION_NAME_RE.search(text)
    base_matches = [
        match
        for match in _BASE_VRS_RE.finditer(text)
        if match.group(1).casefold() != path.name.casefold()
    ]
    description_match = _BASE_DESCRIPTION_RE.search(text)
    base_file = base_matches[0].group(1) if base_matches else None
    return {
        "file": path.name,
        "name": name_match.group(1).strip() if name_match else None,
        "base_file": base_file,
        "base_description": description_match.group(1).strip() if description_match else None,
        "metadata_status": "PARSED" if any((name_match, base_matches, description_match)) else "BASE_UNKNOWN",
    }


def _scope_from_books(books: Iterable[str]) -> tuple[str, str]:
    """Return detailed scope and the deliberately small FB/NT/PORTIONS filter class."""
    values = set(books)
    if values == set(OT_39 + NT_27):
        return "FB", "FB"
    if values == set(NT_27):
        return "NT", "NT"
    if values == set(OT_39):
        return "OT", "PORTIONS"
    return ("NONE" if not values else "PORTIONS"), "PORTIONS"


def _source_signature(project_path: Path) -> str:
    """Hash discovery-driving file names, mtimes, and sizes for cheap incremental rescans."""
    rows: list[str] = []
    for name in ("settings.xml", "canons.xml", "custom.vrs"):
        path = project_path / name
        if path.is_file():
            stat = path.stat()
            rows.append(f"{name}|{stat.st_mtime_ns}|{stat.st_size}")
        else:
            rows.append(f"{name}|MISSING")
    for path in sorted(project_path.iterdir(), key=lambda item: item.name.casefold()):
        if path.is_file() and not path.is_symlink() and path.suffix.casefold() in {".sfm", ".ldml"}:
            stat = path.stat()
            rows.append(f"{path.name}|{stat.st_mtime_ns}|{stat.st_size}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def inspect_paratext_project(project_path: Path) -> dict[str, Any]:
    """Preparse one discovered Paratext project into persistent catalog/menu metadata."""
    path = project_path.expanduser().resolve()
    settings_path = path / "settings.xml"
    if not settings_path.is_file():
        raise ValidationError(f"settings.xml not found: {settings_path}", code="PARATEXT_SETTINGS_NOT_FOUND")
    settings = parse_settings_xml(settings_path)
    warnings: list[str] = []
    errors: list[str] = []

    canons_path = path / "canons.xml"
    try:
        canon_books = parse_canons_xml(canons_path)
    except ValidationError as exc:
        canon_books = ()
        errors.append(exc.code)
    sfm_books = detect_scripture_books(path)
    effective_books = canon_books or sfm_books
    if not canons_path.is_file():
        warnings.append("PARATEXT_CANONS_NOT_FOUND")
    elif not canon_books and not errors:
        warnings.append("PARATEXT_CANONS_BOOKS_NOT_DETECTED")
    if not sfm_books:
        warnings.append("PARATEXT_SCRIPTURE_NOT_FOUND")
    if canon_books and sfm_books and set(canon_books) != set(sfm_books):
        warnings.append("PARATEXT_CANONS_SFM_MISMATCH")

    try:
        vrs = parse_custom_vrs(path / "custom.vrs")
    except ValidationError as exc:
        vrs = {"file": "custom.vrs", "name": None, "base_file": None, "base_description": None, "metadata_status": "INVALID"}
        warnings.append(exc.code)
    detailed_scope, filter_scope = _scope_from_books(effective_books)
    code = parse_project_code(path.name).to_dict()
    resolution = resolve_paratext_language(
        settings_code=settings.get("language_iso"),
        language_name=settings.get("language_name"),
        project_prefix=code.get("paratext_language_code"),
    )
    ldml_rows: list[dict[str, Any]] = []
    for ldml_path in sorted(path.glob("*.ldml"), key=lambda item: item.name.casefold()):
        try:
            ldml_rows.append(parse_ldml_identity(ldml_path))
        except ValidationError as exc:
            warnings.append(exc.code)
    identification = estimate_language_identity(
        project_code=path.name,
        settings_code=settings.get("language_iso"),
        language_name=settings.get("language_name"),
        ldml_rows=ldml_rows,
        settings_countries=settings.get("country_values") or (),
    )
    selected = dict(identification.get("selected") or {})
    iso = selected.get("preferred") or settings.get("language_iso") or resolution.get("canonical_alpha_3") or code.get("paratext_language_code")
    if resolution.get("status") == "MISSING":
        warnings.append("PARATEXT_ISO_NOT_DECLARED")
    elif resolution.get("status") == "INVALID":
        warnings.append("PARATEXT_ISO_INVALID")
    if resolution.get("prefix_consistent") is False:
        warnings.append("PROJECT_LANGUAGE_PREFIX_REVIEW_REQUIRED")
    if code.get("parse_status") in {"INVALID", "UNPARSED", "PARTIAL"}:
        warnings.append("PROJECT_CODE_REVIEW_REQUIRED")
    status = "INVALID" if errors else ("WARNING" if warnings else "READY")
    now = _utc_now()
    return {
        "project_code": path.name,
        "folder": path.name,
        "path": str(path),
        "full_name": settings.get("full_name") or path.name,
        "language_name": settings.get("language_name"),
        "language_iso": iso,
        "language_iso_raw": settings.get("language_iso_raw"),
        "language_resolution": resolution,
        "language_identification": identification,
        "paratext_language_code": settings.get("language_iso"),
        "canonical_iso_639_3": selected.get("alpha_3"),
        "preferred_language_subtag": selected.get("preferred"),
        "primary_audience_country": dict(identification.get("primary_country") or {}).get("code"),
        "language_profile_tag": identification.get("bcp47_candidate"),
        "ldml_evidence": ldml_rows,
        "code_metadata": code,
        "canon_books": list(canon_books),
        "sfm_books": list(sfm_books),
        "books": list(effective_books),
        "book_count": len(effective_books),
        "scope": detailed_scope,
        "filter_scope": filter_scope,
        "versification": vrs,
        "status": status,
        "warnings": sorted(set(warnings)),
        "errors": sorted(set(errors)),
        "discovery_status": "DISCOVERED",
        "detail_status": "VALIDATED",
        "source_signature": _source_signature(path),
        "discovered_utc": now,
        "validated_utc": now,
        "scanned_utc": now,
    }


def _discovered_row(project_path: Path, *, discovered_utc: str) -> dict[str, Any]:
    """Return a tree-only discovery row without opening any Project file."""
    path = project_path.expanduser().resolve()
    return {
        "project_code": path.name,
        "folder": path.name,
        "path": str(path),
        "full_name": path.name,
        "language_name": None,
        "language_iso": None,
        "language_iso_raw": None,
        "language_resolution": {},
        "code_metadata": parse_project_code(path.name).to_dict(),
        "canon_books": [],
        "sfm_books": [],
        "books": [],
        "book_count": 0,
        "scope": None,
        "filter_scope": None,
        "versification": {},
        "status": "PENDING",
        "warnings": [],
        "errors": [],
        "discovery_status": "DISCOVERED",
        "detail_status": "PENDING",
        "source_signature": None,
        "discovered_utc": discovered_utc,
        "validated_utc": None,
        "scanned_utc": None,
    }


def _upgrade_legacy_catalog(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade the v1 derived catalog in memory; the next scan persists v2 state."""
    scanned = raw.get("scanned_utc")
    projects: dict[str, Any] = {}
    for code, value in dict(raw.get("projects", {})).items():
        if not isinstance(value, dict):
            continue
        row = dict(value)
        row.setdefault("discovery_status", "DISCOVERED")
        row.setdefault("detail_status", "VALIDATED")
        row.setdefault("discovered_utc", row.get("scanned_utc") or scanned)
        row.setdefault("validated_utc", row.get("scanned_utc") or scanned)
        projects[str(code)] = row
    return {
        "schema_version": SCHEMA_VERSION,
        "projects_root": raw.get("projects_root"),
        "scanned_utc": scanned,
        "quick_scanned_utc": scanned,
        "full_scanned_utc": scanned,
        "folders_examined": raw.get("folders_examined", 0),
        "projects": projects,
        "invalid_folders": dict(raw.get("invalid_folders", {})),
    }


def load_paratext_catalog(root: Path) -> dict[str, Any]:
    """Load the persisted Project catalog; missing state is a clean empty catalog."""
    path = catalog_path(root)
    if not path.is_file():
        return {
            "schema_version": SCHEMA_VERSION,
            "projects_root": None,
            "scanned_utc": None,
            "quick_scanned_utc": None,
            "full_scanned_utc": None,
            "folders_examined": 0,
            "projects": {},
            "invalid_folders": {},
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid Paratext project catalog: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"Unsupported Paratext project catalog: {path}")
    if str(raw.get("schema_version")) == LEGACY_SCHEMA_VERSION:
        raw = _upgrade_legacy_catalog(raw)
    elif str(raw.get("schema_version")) != SCHEMA_VERSION:
        raise ConfigurationError(f"Unsupported Paratext project catalog: {path}")
    projects = raw.get("projects", {})
    invalid = raw.get("invalid_folders", {})
    if not isinstance(projects, dict) or not isinstance(invalid, dict):
        raise ConfigurationError("Paratext project catalog projects/invalid_folders must be mappings")
    return {
        "schema_version": SCHEMA_VERSION,
        "projects_root": raw.get("projects_root"),
        "scanned_utc": raw.get("scanned_utc"),
        "quick_scanned_utc": raw.get("quick_scanned_utc"),
        "full_scanned_utc": raw.get("full_scanned_utc"),
        "folders_examined": int(raw.get("folders_examined") or 0),
        "projects": dict(projects),
        "invalid_folders": dict(invalid),
    }


def clear_paratext_catalog(root: Path) -> None:
    """Delete only the derived Paratext catalog when the primary root is cleared."""
    path = catalog_path(root)
    if path.exists():
        path.unlink()


def scan_paratext_projects(
    root: Path,
    projects_root: Path,
    *,
    full: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Discover Projects cheaply or fully validate every discovered Project.

    Quick scans are deliberately tree-only: enumerate immediate child directories and
    test for the ``settings.xml`` marker without opening Project files. Existing detailed
    metadata is retained for unchanged folder names. Full scans parse and revalidate all
    marker-bearing folders.
    """
    sage_root = root.expanduser().resolve()
    pt_root = Path(normalize_operator_path(str(projects_root))).expanduser()
    if not pt_root.is_absolute():
        raise ValidationError("Paratext/PTLite Projects root must be absolute", code="PROJECT_ROOT_PATH_INVALID")
    pt_root = pt_root.resolve()
    if not pt_root.is_dir():
        raise ValidationError(f"Paratext/PTLite Projects root not found: {pt_root}", code="PROJECT_ROOT_NOT_FOUND")

    prior = load_paratext_catalog(sage_root)
    same_root = prior.get("projects_root") == str(pt_root)
    prior_projects = prior.get("projects", {}) if same_root else {}
    projects: dict[str, Any] = {}
    invalid: dict[str, Any] = {}
    examined = 0
    scan_time = _utc_now()
    children = sorted((item for item in pt_root.iterdir() if item.is_dir()), key=lambda item: item.name.casefold())
    total = len(children)
    if progress is not None:
        progress(0, total)
    for child in children:
        examined += 1
        settings_path = child / "settings.xml"
        if not settings_path.is_file():
            if progress is not None:
                progress(examined, total)
            continue
        previous = prior_projects.get(child.name) if isinstance(prior_projects, dict) else None
        if not full:
            if isinstance(previous, dict):
                row = dict(previous)
                row["path"] = str(child.resolve())
                row["folder"] = child.name
                row["project_code"] = child.name
                row["discovery_status"] = "DISCOVERED"
                row["discovered_utc"] = scan_time
                projects[child.name] = row
            else:
                projects[child.name] = _discovered_row(child, discovered_utc=scan_time)
        else:
            try:
                projects[child.name] = inspect_paratext_project(child)
            except (OSError, ValidationError) as exc:
                invalid[child.name] = {
                    "folder": child.name,
                    "path": str(child.resolve()),
                    "code": getattr(exc, "code", "PARATEXT_PROJECT_INVALID"),
                    "message": getattr(exc, "message", str(exc)),
                    "discovery_status": "DISCOVERED",
                    "detail_status": "INVALID",
                    "scanned_utc": scan_time,
                }
        if progress is not None:
            progress(examined, total)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "projects_root": str(pt_root),
        "scanned_utc": scan_time,
        "quick_scanned_utc": scan_time if not full else prior.get("quick_scanned_utc"),
        "full_scanned_utc": scan_time if full else prior.get("full_scanned_utc"),
        "folders_examined": examined,
        "projects": projects,
        "invalid_folders": invalid if full else {
            code: dict(value)
            for code, value in dict(prior.get("invalid_folders", {})).items()
            if (pt_root / code / "settings.xml").is_file() and code not in projects
        },
    }
    destination = catalog_path(sage_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, payload)
    return payload


def rescan_catalog_project(root: Path, project_code: str) -> dict[str, Any]:
    """Refresh one cataloged Project without rebuilding the rest of the catalog."""
    catalogue = load_paratext_catalog(root)
    projects_root = catalogue.get("projects_root")
    if not projects_root:
        raise ValidationError("Paratext/PTLite Projects root is not configured", code="PROJECT_ROOT_NOT_FOUND")
    candidate = Path(str(projects_root)) / str(project_code)
    row = inspect_paratext_project(candidate)
    catalogue["projects"][str(project_code)] = row
    catalogue.get("invalid_folders", {}).pop(str(project_code), None)
    now = _utc_now()
    catalogue["scanned_utc"] = now
    atomic_write_json(catalog_path(root), catalogue)
    return row


def filtered_projects(
    catalogue: dict[str, Any],
    *,
    scope: str | None = None,
    language_iso: str | None = None,
    registered_ids: set[str] | None = None,
    unregistered_only: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Return deterministic catalog rows for the two operator-facing filters."""
    wanted_scope = str(scope or "ALL").strip().upper()
    if wanted_scope not in {"ALL", "FB", "NT", "PORTIONS"}:
        raise ValidationError(f"Unsupported Project scope filter: {scope}", code="PROJECT_FILTER_INVALID")
    wanted_language = str(language_iso or "").strip().casefold()
    registered = registered_ids or set()
    rows: list[dict[str, Any]] = []
    for code, value in dict(catalogue.get("projects", {})).items():
        if not isinstance(value, dict):
            continue
        if str(value.get("detail_status") or "VALIDATED").upper() == "INVALID":
            continue
        filter_scope = str(value.get("filter_scope") or "").upper()
        if wanted_scope != "ALL" and filter_scope != wanted_scope:
            continue
        if wanted_language and str(value.get("language_iso") or "").casefold() != wanted_language:
            continue
        if unregistered_only and code in registered:
            continue
        rows.append(dict(value))
    return tuple(sorted(rows, key=lambda row: str(row.get("project_code", "")).casefold()))


def language_filter_counts(catalogue: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Build the dynamic language menu directly from cached settings.xml metadata."""
    values: dict[str, dict[str, Any]] = {}
    for row in dict(catalogue.get("projects", {})).values():
        if not isinstance(row, dict):
            continue
        code = str(row.get("language_iso") or "").casefold()
        if not code:
            continue
        item = values.setdefault(code, {"language_iso": code, "language_name": row.get("language_name") or code, "count": 0})
        item["count"] += 1
        if not item.get("language_name") and row.get("language_name"):
            item["language_name"] = row.get("language_name")
    return tuple(sorted(values.values(), key=lambda row: (str(row.get("language_name", "")).casefold(), row["language_iso"])))


def catalog_summary(catalogue: dict[str, Any]) -> dict[str, Any]:
    """Return compact counts used by setup and project menus."""
    rows = [row for row in dict(catalogue.get("projects", {})).values() if isinstance(row, dict)]
    invalid_count = len(dict(catalogue.get("invalid_folders", {})))
    validated = sum(1 for row in rows if str(row.get("detail_status") or "VALIDATED").upper() == "VALIDATED")
    pending = sum(1 for row in rows if str(row.get("detail_status") or "VALIDATED").upper() == "PENDING")
    return {
        "projects": len(rows),
        "discovered": len(rows) + invalid_count,
        "languages": len({str(row.get("language_iso")) for row in rows if row.get("language_iso")}),
        "validated": validated,
        "pending": pending,
        "invalid": invalid_count,
        "warnings": sum(1 for row in rows if row.get("status") == "WARNING"),
        "ready": sum(1 for row in rows if row.get("status") == "READY"),
        "last_scan": catalogue.get("scanned_utc"),
        "last_quick_scan": catalogue.get("quick_scanned_utc"),
        "last_full_scan": catalogue.get("full_scanned_utc"),
    }
