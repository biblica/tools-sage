"""WIP lists: a Job's own clone of a master reference list, and merging its changes back (PO 2026-11-26).

A PCC Job clones the master list of its reference text when it pins it. The clone is an ordinary reference list in
the shared store (build mode ``LOCAL``) whose manifest names its master version (``build.parent``) and records what
it changed against it (``build.local``). Every list action (workbook, Operator wordings, Biblical Terms) works on a
clone exactly as on a master; the change record is recomputed on every save, so it is always the difference
between the clone and its master version:

* ``ADD``: a concept the master version does not have (the full entry is kept, so it survives a master update);
* ``SET``: a concept both have, with this WIP's own ``status`` (``DROPPED`` = left out for this WIP, ``ACTIVE``
  over a master ``DROPPED`` = explicitly kept), ``category`` or ``notes``.

**Update from the master** re-applies the changes to a newer master version: a change the master now has is
retired, a master drop wins unless the clone explicitly kept the concept, and a concept the master removed takes
its changes with it. Everything is reported, nothing stops. **Merge to the master** applies chosen changes (all,
picked, or as edited in the changes workbook) to the newest master version, writing a new master version that
every Job can pin. The master is never changed any other way from a Job.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..atomic import atomic_write_text
from ..errors import ValidationError
from .reflist import ReferenceListStore, new_rl_id

FIELDS = ("status", "category", "notes")
CHANGES_SHEET = "Changes"
ABOUT_SHEET = "About"
CHANGE_COLUMNS = ("Change id", "Change", "Concept key", "Label", "Master now", "This WIP", "Category", "Notes", "Merge")


def is_clone(manifest: Mapping[str, Any]) -> bool:
    """True for a Job's WIP list (a clone of a master list)."""
    return bool(manifest["build"].get("parent"))


def change_id(op: str, key: str) -> str:
    """Stable id of one change: op + concept key."""
    return "CHG-" + hashlib.sha256(f"{op}|{key}".encode("utf-8")).hexdigest()[:12]


def diff_changes(master: Iterable[Mapping[str, Any]], clone: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The clone's changes against one master version, sorted by label then key."""
    base = {e["concept_key"]: e for e in master}
    mine = {e["concept_key"]: e for e in clone}
    changes: list[dict[str, Any]] = []
    for key, entry in mine.items():
        old = base.get(key)
        if old is None:
            changes.append({"change_id": change_id("ADD", key), "op": "ADD", "concept_key": key,
                            "label": entry["label"], "entry": dict(entry)})
            continue
        fields = {name: entry[name] for name in FIELDS if entry[name] != old[name]}
        if fields:
            changes.append({"change_id": change_id("SET", key), "op": "SET", "concept_key": key,
                            "label": entry["label"], "fields": fields})
    for key in base.keys() - mine.keys():
        changes.append({"change_id": change_id("SET", key), "op": "SET", "concept_key": key,
                        "label": base[key]["label"], "fields": {"status": "DROPPED"}})
    return sorted(changes, key=lambda c: (c["label"].casefold(), c["concept_key"]))


def describe(change: Mapping[str, Any], master_entry: Mapping[str, Any] | None = None) -> str:
    """A short Operator description of one change."""
    if change["op"] == "ADD":
        senses = [s["label"] for s in change["entry"]["senses"] if s["kind"] == "SENSE"]
        return f"added: {change['label']}" + (f" ({'; '.join(senses[:3])})" if senses else " (no senses)")
    fields = change["fields"]
    status = fields.get("status")
    if status == "DROPPED":
        text = f"left out: {change['label']}"
    elif status and master_entry is not None and master_entry["status"] == "DROPPED":
        text = f"kept although the master dropped it: {change['label']}"
    elif status:
        text = f"status {status}: {change['label']}"
    else:
        text = f"edited: {change['label']}"
    extra = [name for name in ("category", "notes") if name in fields]
    return text + (f" ({', '.join(extra)} changed)" if extra else "")


def apply_changes(master: Iterable[Mapping[str, Any]], changes: Iterable[Mapping[str, Any]]
                  ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Apply a clone's changes to a master version; returns (entries, notes, retired changes)."""
    by_key = {e["concept_key"]: dict(e) for e in master}
    notes: list[str] = []
    retired: list[str] = []
    for change in changes:
        key = change["concept_key"]
        current = by_key.get(key)
        if change["op"] == "ADD":
            if current is None:
                by_key[key] = dict(change["entry"])
            elif current["status"] == "DROPPED":
                notes.append(f"{change['label']}: the master dropped it, so this WIP's addition no longer applies "
                             "(set it to KEEP in this WIP's list to keep it)")
            else:
                retired.append(f"{change['label']}: now on the master")
            continue
        if current is None:
            retired.append(f"{change['label']}: no longer on the master")
            continue
        fields = dict(change["fields"])
        if current["status"] == "DROPPED" and fields.get("status") not in (None, "DROPPED"):
            notes.append(f"{change['label']}: the master dropped it; kept for this WIP (an explicit keep)")
        current.update(fields)
    return list(by_key.values()), notes, retired


@dataclass
class LayerResult:
    """What an update or merge did."""

    manifest: dict[str, Any] | None
    master: dict[str, Any] | None = None
    applied: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    report_path: Path | None = None

    def lines(self) -> list[str]:
        """Operator summary."""
        head = []
        if self.master:
            head.append(f"Master {self.master['rl_id']} v{self.master['version']} written.")
        if self.manifest:
            head.append(f"WIP list {self.manifest['rl_id']} v{self.manifest['version']} written.")
        if not head:
            head.append("No change: nothing written.")
        return head + [f"Applied {len(self.applied)}, retired {len(self.retired)}, notes {len(self.notes)}."] + \
            [f"- {n}" for n in self.notes]


def _now() -> str:
    """Creation time."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_clone(store: ReferenceListStore, master_id: str, master_version: int | None, *, title: str,
                 instance_id: str, created_utc: str | None = None) -> dict[str, Any]:
    """Clone a master list version into a new WIP list (v1, no changes yet)."""
    manifest, entries = store.load(master_id, master_version)
    if is_clone(manifest):
        raise ValidationError(f"{master_id} is already a WIP list; clone its master instead",
                              code="PCC_RL_CLONE_OF_CLONE")
    created = created_utc or _now()
    parent = {"rl_id": master_id, "version": manifest["version"]}
    build = {"mode": "LOCAL", "parent": parent, "derived_from": parent, "local": [],
             "settings": manifest["build"].get("settings", {}), "summary": {}}
    return store.save(rl_id=new_rl_id(title, instance_id, created), title=title, reference=manifest["reference"],
                      license=manifest["license"], build=build, entries=entries, created_utc=created)


def update_clone(store: ReferenceListStore, clone_id: str, *, report_folder: Path,
                 master_version: int | None = None, created_utc: str | None = None) -> LayerResult:
    """Re-apply a WIP list's changes to the newest (or given) master version, as its next version."""
    clone, _ = store.load(clone_id, None)
    if not is_clone(clone):
        raise ValidationError(f"{clone_id} is a master list, not a WIP list", code="PCC_RL_NOT_CLONE")
    parent = clone["build"]["parent"]
    master, master_entries = store.load(parent["rl_id"], master_version)
    result = LayerResult(None)
    if master["version"] == parent["version"]:
        result.notes.append(f"Already on the newest master version (v{master['version']}).")
        return result
    entries, result.notes, result.retired = apply_changes(master_entries, clone["build"].get("local", []))
    changes = diff_changes(master_entries, entries)
    result.applied = [describe(c) for c in changes]
    new_parent = {"rl_id": parent["rl_id"], "version": master["version"]}
    build = {**clone["build"], "mode": "LOCAL", "parent": new_parent, "local": changes,
             "summary": {**clone["build"].get("summary", {}),
                         "update": {"from_master_version": parent["version"], "to_master_version": master["version"],
                                    "changes": len(changes), "retired": len(result.retired)}}}
    result.manifest = store.save(rl_id=clone_id, title=clone["title"], reference=clone["reference"],
                                 license=clone["license"], build=build, entries=entries,
                                 created_utc=created_utc or _now())
    result.report_path = _report(report_folder, f"RL-UPDATE-{clone_id}-v{result.manifest['version']}.md",
                                 f"WIP list {clone_id}: master v{parent['version']} -> v{master['version']}", result)
    return result


def merge_to_master(store: ReferenceListStore, clone_id: str, change_ids: Iterable[str] | None, *, report_folder: Path,
                    edits: Mapping[str, Mapping[str, str]] | None = None, created_utc: str | None = None) -> LayerResult:
    """Apply chosen changes of a WIP list (all when ``change_ids`` is None) to the newest master version.

    ``edits`` (change id -> {category, notes}) are the Operator's manual edits of a change before it goes into the
    master. The master's newest version is the base, so changes made to the master meanwhile are kept.
    """
    clone, _ = store.load(clone_id, None)
    if not is_clone(clone):
        raise ValidationError(f"{clone_id} is a master list, not a WIP list", code="PCC_RL_NOT_CLONE")
    master_id = clone["build"]["parent"]["rl_id"]
    master, master_entries = store.load(master_id, None)
    changes = clone["build"].get("local", [])
    wanted = None if change_ids is None else set(change_ids)
    chosen = []
    result = LayerResult(None)
    for change in changes:
        if wanted is not None and change["change_id"] not in wanted:
            continue
        change = {**change, "entry": dict(change["entry"])} if change["op"] == "ADD" else \
            {**change, "fields": dict(change["fields"])}
        for name, value in (edits or {}).get(change["change_id"], {}).items():
            if change["op"] == "ADD":
                change["entry"][name] = value
            else:
                change["fields"][name] = value
        chosen.append(change)
    if wanted is not None:
        unknown = wanted - {c["change_id"] for c in changes}
        result.notes += [f"{cid}: not a current change of {clone_id}; not used" for cid in sorted(unknown)]
    if not chosen:
        result.notes.append("No change chosen.")
        return result
    by_master = {e["concept_key"]: e for e in master_entries}
    entries, notes, retired = apply_changes(master_entries, chosen)
    result.notes += notes
    result.retired = retired
    result.applied = [describe(c, by_master.get(c["concept_key"])) for c in chosen
                      if not any(r.startswith(f"{c['label']}:") for r in retired)]
    if diff_changes(master_entries, entries) == []:
        result.notes.append("The master already has these changes; nothing written.")
        return result
    build = {**master["build"], "mode": "MERGE", "imported_from": None, "base_version": master["version"],
             "summary": {**master["build"].get("summary", {}),
                         "merged_from_wip_list": {"rl_id": clone_id, "version": clone["version"],
                                                  "changes": len(chosen)}}}
    result.master = store.save(rl_id=master_id, title=master["title"], reference=master["reference"],
                               license=master["license"], build=build, entries=entries,
                               created_utc=created_utc or _now())
    result.report_path = _report(report_folder, f"RL-MERGE-{master_id}-v{result.master['version']}.md",
                                 f"Merged from WIP list {clone_id} v{clone['version']} into {master_id} "
                                 f"v{result.master['version']}", result)
    return result


def _report(folder: Path, name: str, title: str, result: LayerResult) -> Path:
    """Write an update or merge report."""
    folder.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    for heading, items in (("Applied", result.applied), ("Retired (no longer needed)", result.retired),
                           ("Notes", result.notes)):
        lines += [f"## {heading} ({len(items)})", ""] + [f"- {item}" for item in items] + [""]
    path = folder / name
    atomic_write_text(path, "\n".join(lines))
    return path


# --- manual merge: the changes workbook ----------------------------------------------------------------


def export_changes(store: ReferenceListStore, clone_id: str, folder: Path) -> Path:
    """Write ``RL-CHANGES-<clone>-v<n>.xlsx``: one row per change; the Operator marks Merge and may edit."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Protection

    clone, _ = store.load(clone_id, None)
    if not is_clone(clone):
        raise ValidationError(f"{clone_id} is a master list, not a WIP list", code="PCC_RL_NOT_CLONE")
    parent = clone["build"]["parent"]
    _, master_entries = store.load(parent["rl_id"], parent["version"])
    by_master = {e["concept_key"]: e for e in master_entries}
    book = Workbook()
    sheet = book.active
    sheet.title = CHANGES_SHEET
    sheet.append(list(CHANGE_COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for change in clone["build"].get("local", []):
        master = by_master.get(change["concept_key"])
        mine = change["entry"] if change["op"] == "ADD" else {**(master or {}), **change["fields"]}
        values = (change["change_id"], describe(change, master), change["concept_key"], change["label"],
                  master["status"] if master else "not on the master", mine.get("status", ""),
                  mine.get("category", ""), mine.get("notes", ""), "")
        sheet.append([("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v) for v in values])
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.protection = Protection(locked=cell.column not in (7, 8, 9))
    sheet.freeze_panes = "B2"
    about = book.create_sheet(ABOUT_SHEET)
    for key, value in (("wip_list", clone_id), ("version", clone["version"]), ("master", parent["rl_id"]),
                       ("master_version", parent["version"]),
                       ("how to edit", "Merge: YES to merge the change into the master, blank to leave it in this "
                                       "WIP only. Category and Notes may be edited; the edited values go into the "
                                       "master.")):
        about.append([key, value])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"RL-CHANGES-{clone_id}-v{clone['version']}.xlsx"
    book.save(path)
    return path


def read_changes(path: Path) -> tuple[str, list[str], dict[str, dict[str, str]], list[str]]:
    """Read an edited changes workbook: (WIP list id, change ids to merge, edits, problems)."""
    from openpyxl import load_workbook

    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any unreadable workbook is one clear error
        raise ValidationError(f"{path.name} is not a readable workbook: {exc}", code="PCC_RL_WORKBOOK_INVALID") from exc
    if CHANGES_SHEET not in book.sheetnames or ABOUT_SHEET not in book.sheetnames:
        raise ValidationError(f"{path.name} is not a WIP-list changes workbook", code="PCC_RL_WORKBOOK_INVALID",
                              next_action="Export the changes again and edit that file.")
    about = {str(r[0]): r[1] for r in book[ABOUT_SHEET].iter_rows(values_only=True) if r and r[0]}

    def text(value: Any) -> str:
        """Cell text without the protective quote."""
        value = "" if value is None else str(value).strip()
        return value[1:] if value.startswith("'") and value[1:2] in ("=", "+", "-", "@") else value

    chosen, edits, problems = [], {}, []
    rows = list(book[CHANGES_SHEET].iter_rows(values_only=True))
    header = [text(v) for v in rows[0]] if rows else list(CHANGE_COLUMNS)
    for number, values in enumerate(rows[1:], 2):
        row = {name: text(values[i]) if i < len(values) else "" for i, name in enumerate(header)}
        merge = row.get("Merge", "").upper()
        if not row.get("Change id"):
            continue
        if merge not in ("", "YES", "Y", "NO", "N"):
            problems.append(f"row {number}: Merge '{row.get('Merge')}' is not YES or blank; row not used")
            continue
        if merge in ("YES", "Y"):
            chosen.append(row["Change id"])
            edit = {"notes": row.get("Notes", "")}
            if row.get("Category"):
                edit["category"] = row["Category"]
            edits[row["Change id"]] = edit
    return str(about.get("wip_list") or ""), chosen, edits, problems
