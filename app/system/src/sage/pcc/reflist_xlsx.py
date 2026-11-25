"""Reference-list workbook: export a version, edit it in a spreadsheet, import it as a new version (plan §5b.4, D15).

Sheet ``Entries`` has one row per concept. The concept key is locked; the Operator edits **Status** (``KEEP``,
``DROP``, ``NEW`` or blank for "no decision"), **Category** and **Notes**, and adds ``NEW`` rows with a wording
in **Wordings** and no key. Sheet ``About`` names the list and the base version.

Import always writes a **new version** (never edits one) plus ``RL-DIFF-<id>-v<n>.md``. Rows are applied by
concept key; a bad row is reported with its row number and the other rows still apply (never hard-block). A
``NEW`` row is located in the reference text when the caller supplies the reference's ``BuildContext``; a
wording found nowhere is kept with no senses and reported (AT30). These verdicts replace the former global
core-list overlay: they live in the list's own versions. Cells are written so a spreadsheet never runs them
as formulas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_text
from ..errors import ValidationError
from .reflist import ReferenceListStore
from .rlbuild import DEFAULT_MIN_VERSES, BuildContext, Concept, _entry, declared_concepts, partition
from .segment import tokenize

ENTRIES_SHEET = "Entries"
ABOUT_SHEET = "About"
COLUMNS = ("Concept key", "Label", "Category", "Wordings", "Verses", "Examples", "Status", "Notes", "Origin")
STATUS_IN = {"KEEP": "ACTIVE", "DROP": "DROPPED"}
STATUS_OUT = {"ACTIVE": "KEEP", "DROPPED": "DROP", "PROPOSED": ""}
FORMULA_START = ("=", "+", "-", "@")


def _out(value: Any) -> Any:
    """A cell a spreadsheet keeps as text."""
    return "'" + value if isinstance(value, str) and value.startswith(FORMULA_START) else value


def _in(value: Any) -> str:
    """Cell text as the Operator meant it (the protective quote removed)."""
    text = "" if value is None else str(value).strip()
    return text[1:] if text.startswith("'") and text[1:2] in FORMULA_START else text


def workbook_name(rl_id: str, version: int) -> str:
    """``RL-<id>-v<n>.xlsx``."""
    return f"RL-{rl_id}-v{version}.xlsx"


def export_workbook(store: ReferenceListStore, rl_id: str, version: int | None, folder: Path) -> Path:
    """Write the workbook of one version into ``folder``; return its path."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Protection

    manifest, entries = store.load(rl_id, version)
    book = Workbook()
    sheet = book.active
    sheet.title = ENTRIES_SHEET
    sheet.append(list(COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for entry in entries:
        senses = [s for s in entry["senses"] if s["kind"] == "SENSE"]
        wordings = "; ".join(f"{s['label']} ({s['verses']})" for s in senses)
        sheet.append([_out(v) for v in (entry["concept_key"], entry["label"], entry["category"], wordings,
                                        entry["verses"], ", ".join(entry["examples"]), STATUS_OUT[entry["status"]],
                                        entry["notes"], entry["origin"])])
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.protection = Protection(locked=cell.column != 1)
    sheet.freeze_panes = "B2"
    about = book.create_sheet(ABOUT_SHEET)
    for key in ("rl_id", "version", "title", "entries_sha256"):
        about.append([key, manifest[key]])
    about.append(["reference", manifest["reference"]["project_id"]])
    about.append(["how to edit", "Status: KEEP, DROP, NEW (new row, wording in Wordings, no key) or blank. "
                                 "Edit Category and Notes freely. Import writes a new version."])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / workbook_name(rl_id, manifest["version"])
    book.save(path)
    return path


@dataclass
class ImportResult:
    """The new manifest (None when nothing changed), counts, problems and the diff report."""

    manifest: dict[str, Any] | None
    added: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    diff_path: Path | None = None

    def lines(self) -> list[str]:
        """Operator summary."""
        head = (f"New version {self.manifest['rl_id']} v{self.manifest['version']}" if self.manifest
                else "No change: no new version written.")
        return [head, f"Added {len(self.added)}, dropped {len(self.dropped)}, kept {len(self.kept)}, "
                      f"other edits {len(self.changed)}; {len(self.problems)} row problem(s)."] + [f"- {p}" for p in self.problems]


def _rows(path: Path) -> tuple[dict[str, Any], list[tuple[int, dict[str, str]]]]:
    """About values and Entries rows (row number, column -> text)."""
    from openpyxl import load_workbook

    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any unreadable workbook is one clear error
        raise ValidationError(f"{path.name} is not a readable workbook: {exc}", code="PCC_RL_WORKBOOK_INVALID") from exc
    if ENTRIES_SHEET not in book.sheetnames or ABOUT_SHEET not in book.sheetnames:
        raise ValidationError(f"{path.name} is not a reference-list workbook (sheets {ENTRIES_SHEET}, {ABOUT_SHEET})",
                              code="PCC_RL_WORKBOOK_INVALID", next_action="Export the list again and edit that file.")
    about = {str(r[0]): r[1] for r in book[ABOUT_SHEET].iter_rows(values_only=True) if r and r[0]}
    rows = []
    header = None
    for number, values in enumerate(book[ENTRIES_SHEET].iter_rows(values_only=True), 1):
        if number == 1:
            header = [str(v or "").strip() for v in values]
            continue
        if not any(v not in (None, "") for v in values):
            continue
        rows.append((number, {name: _in(values[i]) if i < len(values) else "" for i, name in enumerate(header or COLUMNS)}))
    return about, rows


def import_workbook(store: ReferenceListStore, path: Path, *, report_folder: Path, context: BuildContext | None = None,
                    language_tag: str | None = None, created_utc: str | None = None) -> ImportResult:
    """Apply an edited workbook to its base version and store the result as a new version."""
    about, rows = _rows(path)
    rl_id = str(about.get("rl_id") or "")
    try:
        base_version = int(about.get("version"))
    except (TypeError, ValueError):
        base_version = 0
    if not rl_id or base_version < 1 or base_version not in store.versions(rl_id):
        raise ValidationError(f"{path.name} names reference list {rl_id or '?'} version {base_version or '?'}, which is "
                              "not in this SAGE instance", code="PCC_RL_WORKBOOK_BASE_MISSING",
                              next_action="Import the base list package first, or export the workbook from this instance.")
    manifest, entries = store.load(rl_id, base_version)
    language_tag = language_tag or manifest["reference"]["language_tag"]
    by_key = {e["concept_key"]: dict(e) for e in entries}
    result = ImportResult(None)
    new_rows: list[tuple[int, str]] = []
    for number, row in rows:
        key, status = row.get("Concept key", ""), row.get("Status", "").upper()
        if status not in ("", "KEEP", "DROP", "NEW"):
            result.problems.append(f"row {number}: status '{row.get('Status')}' is not KEEP, DROP, NEW or blank; row not used")
            continue
        if not key:
            wording = row.get("Wordings", "") or row.get("Label", "")
            if status == "NEW" and wording:
                new_rows.append((number, wording))
            else:
                result.problems.append(f"row {number}: a row without a concept key needs status NEW and a wording; row not used")
            continue
        entry = by_key.get(key)
        if entry is None:
            result.problems.append(f"row {number}: concept {key} is not in {rl_id} v{base_version}; row not used")
            continue
        before = dict(entry)
        if status in STATUS_IN:
            entry["status"] = STATUS_IN[status]
        if row.get("Category"):
            entry["category"] = row["Category"]
        entry["notes"] = row.get("Notes", "")
        if entry != before:
            if entry["status"] != before["status"]:
                (result.dropped if entry["status"] == "DROPPED" else result.kept).append(entry["label"])
            else:
                result.changed.append(entry["label"])
    for number, wording in new_rows:
        entry = _new_entry(number, wording, context, language_tag, manifest, result)
        if entry is None:
            continue
        if entry["concept_key"] in by_key:
            existing = by_key[entry["concept_key"]]
            if existing["status"] != "ACTIVE":
                existing["status"] = "ACTIVE"
                result.kept.append(existing["label"])
            result.problems.append(f"row {number}: '{wording}' is already on the list as {existing['label']}; kept")
            continue
        by_key[entry["concept_key"]] = entry
        result.added.append(wording)
    if not (result.added or result.dropped or result.kept or result.changed):
        result.diff_path = _write_diff(report_folder, rl_id, base_version, None, result)
        return result
    created = created_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    build = {**manifest["build"], "mode": "MERGE", "imported_from": None,
             "summary": {**manifest["build"].get("summary", {}),
                         "workbook": {"file": path.name, "added": len(result.added), "dropped": len(result.dropped),
                                      "kept": len(result.kept), "changed": len(result.changed),
                                      "problems": len(result.problems)}}}
    build["base_version"] = base_version
    result.manifest = store.save(rl_id=rl_id, title=manifest["title"], reference=manifest["reference"],
                                 license=manifest["license"], build=build, entries=list(by_key.values()),
                                 created_utc=created)
    result.diff_path = _write_diff(report_folder, rl_id, base_version, result.manifest["version"], result)
    return result


def _new_entry(number: int, wording: str, ctx: BuildContext | None, language_tag: str, manifest: dict[str, Any],
               result: ImportResult) -> dict[str, Any] | None:
    """A NEW row as an entry: anchored and realized in the reference text when it is available."""
    if ctx is None:
        tokens = [t.norm for t in tokenize(wording)]
        if not tokens:
            result.problems.append(f"row {number}: '{wording}' has no letters; row not used")
            return None
        concept = Concept("WORDING", (f"{language_tag}|{' '.join(tokens)}",), wording, "DECLARED", "ACTIVE",
                          (f"DECLARED:workbook row {number}",))
        result.problems.append(f"row {number}: '{wording}' kept without senses: the reference text was not available "
                               "to locate it")
        return _entry(concept, [], {}, [], 0)
    tokens = tuple(t.norm for t in tokenize(wording, cased=ctx.cased))
    if not tokens:
        result.problems.append(f"row {number}: '{wording}' has no letters; row not used")
        return None
    concepts, located, problems = declared_concepts(ctx, [(wording, tokens, number)], language_tag)
    concept = concepts[0]
    concept = Concept(concept.kind, concept.anchor, wording, "DECLARED", "ACTIVE", (f"DECLARED:workbook row {number}",))
    counts, rendered = ctx.realize_concept(concept, located.get(concept.key))
    if not rendered:
        result.problems.append(f"row {number}: '{wording}' does not occur in the reference text; kept with no senses")
        return _entry(concept, [], counts, [], 0)
    min_verses = int(manifest["build"].get("settings", {}).get("min_verses", DEFAULT_MIN_VERSES))
    senses = partition(concept.key, rendered, min_verses=min_verses)
    from .rlbuild import _examples
    return _entry(concept, senses, counts, _examples((r.order, r.verse) for r in rendered), len({r.verse for r in rendered}))


def _write_diff(folder: Path, rl_id: str, base: int, version: int | None, result: ImportResult) -> Path:
    """``RL-DIFF-<id>-v<n>.md``: what the import changed and what it could not use."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"RL-DIFF-{rl_id}-v{version or base}.md"
    lines = [f"# Reference list {rl_id}: v{base} -> " + (f"v{version}" if version else "no new version"), ""]
    for title, items in (("Added", result.added), ("Dropped", result.dropped), ("Kept (status set)", result.kept),
                         ("Other edits (category, notes)", result.changed), ("Rows not used or kept with a note", result.problems)):
        lines += [f"## {title} ({len(items)})", ""] + [f"- {item}" for item in items] + [""]
    atomic_write_text(path, "\n".join(lines))
    return path
