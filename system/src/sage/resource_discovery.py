"""Tree-only discovery snapshots for fast resource drift checks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .storage import storage_layout
from .original_language_resources import OL_RESOURCE_IDS, bundled_ol_path, load_ol_state
from .resource_mounts import discover_project_folders, load_resource_mount_state

SCHEMA_VERSION = "1.0"
FILENAME = "resource-discovery.json"


def _utc_now() -> str:
    """Return a stable UTC timestamp for discovery-state provenance."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resource_discovery_path(root: Path) -> Path:
    """Return the derived machine-state path for resource tree snapshots."""
    return storage_layout(root).state_root / FILENAME


def _names(path: Path, *, suffix: str | None = None) -> tuple[str, ...]:
    """Return immediate entry names without opening any entry contents."""
    if not path.is_dir():
        return ()
    values: list[str] = []
    for item in path.iterdir():
        if suffix is not None and item.suffix.casefold() != suffix.casefold():
            continue
        values.append(item.name)
    return tuple(sorted(values, key=str.casefold))


def _load_previous(root: Path) -> dict[str, Any]:
    """Load the previous compatible tree snapshot or return one empty baseline."""
    path = resource_discovery_path(root)
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "groups": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "groups": {}}
    if not isinstance(raw, dict) or str(raw.get("schema_version")) != SCHEMA_VERSION:
        return {"schema_version": SCHEMA_VERSION, "groups": {}}
    return raw


def _ol_path(root: Path, resource_id: str, state: dict[str, Any]) -> Path:
    """Resolve an OL alias path without invoking Scripture/content validation."""
    entry = dict(state.get("resources", {}).get(resource_id, {}))
    if str(entry.get("source") or "BUNDLED").upper() == "BUNDLED":
        return bundled_ol_path(root, resource_id)
    raw = str(entry.get("path") or "").strip()
    return Path(raw).expanduser() if raw else root / "__missing_resource__"


def quick_resource_discovery(root: Path, *, persist: bool = True) -> dict[str, Any]:
    """Compare configured resource trees with the previous tree-only snapshot.

    This check opens no Scripture, VRS, XML, or other resource content. It only enumerates
    immediate directory entries and performs path/marker existence checks. When ``persist``
    is false the comparison is read-only, which keeps diagnostic/package validation clean.
    """
    sage_root = root.expanduser().resolve()
    has_previous = resource_discovery_path(sage_root).is_file()
    previous = _load_previous(sage_root)
    prior_groups = previous.get("groups", {}) if isinstance(previous.get("groups"), dict) else {}
    mounts = load_resource_mount_state(sage_root)
    ol_state = load_ol_state(sage_root)

    groups: dict[str, dict[str, Any]] = {}
    projects_root_raw = mounts.get("projects_root")
    if projects_root_raw:
        projects_root = Path(str(projects_root_raw)).expanduser()
        entries = discover_project_folders(projects_root) if projects_root.is_dir() else ()
        groups["paratext_projects"] = {"path": str(projects_root), "entries": list(entries)}

    base_root_raw = mounts.get("base_vrs_root") or projects_root_raw
    base_root = Path(str(base_root_raw)).expanduser() if base_root_raw else sage_root / "system" / "resources" / "scripture"
    groups["base_vrs"] = {"path": str(base_root), "entries": list(_names(base_root, suffix=".vrs"))}

    for resource_id in OL_RESOURCE_IDS:
        path = _ol_path(sage_root, resource_id, ol_state)
        groups[f"ol_{resource_id.casefold()}"] = {
            "path": str(path),
            "entries": list(_names(path)),
        }

    changes: dict[str, dict[str, list[str]]] = {}
    for name, group in groups.items():
        current = set(str(value) for value in group.get("entries", []))
        prior = prior_groups.get(name, {}) if isinstance(prior_groups.get(name), dict) else {}
        old = set(str(value) for value in prior.get("entries", []))
        changes[name] = {
            "added": sorted(current - old, key=str.casefold),
            "removed": sorted(old - current, key=str.casefold),
        }

    # Report a whole removed group if a previously configured resource root disappears.
    for name, prior in prior_groups.items():
        if name in groups or not isinstance(prior, dict):
            continue
        old = [str(value) for value in prior.get("entries", [])]
        changes[str(name)] = {"added": [], "removed": sorted(old, key=str.casefold)}

    if not has_previous:
        changes = {name: {"added": [], "removed": []} for name in groups}
    changed = sum(len(value["added"]) + len(value["removed"]) for value in changes.values())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "scanned_utc": _utc_now(),
        "groups": groups,
        "changes": changes,
        "change_count": changed,
        "status": "BASELINE" if not has_previous else ("CHANGED" if changed else "UNCHANGED"),
    }
    if persist:
        destination = resource_discovery_path(sage_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(destination, payload)
    return payload
