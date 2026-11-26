"""Move terms lists between Jobs (WIPs) and bring in the Operator's own lists.

* ``export_bundle`` writes one portable JSON file from a Job: its SOURCE wordings, key terms, approved
  renderings. (Core-list verdicts now live in reference-list versions, plan P5b-4; a bundle that still carries
  them is read and their count reported.)
* ``import_bundle`` loads it into another Job. Renderings arrive as PROPOSED rules (same target language only) that the Operator
  still approves. A bundle whose checksum does not match is refused.
* ``import_operator_list`` reads a CSV, TSV, TXT or XLSX list (wording[, rendering(s)[, note]]).

SOURCE wordings never go into the Job: wordings that are not on the terms list are returned in
``ImportReport.missing_wordings`` and the menu offers to add them to the pinned reference list (a new version
that every Job on that list can use).

Nothing here blocks on content: unusable lines are reported with their line numbers.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_text
from ..errors import ValidationError
from .glossary import (ImportReport, _append_rule, _rule, current_key_terms, current_rules,
                       split_renderings)
from .ids import canonical_json, full_digest

BUNDLE_FORMAT = "SAGE-PCC-TERMS-BUNDLE"
BUNDLE_VERSION = 1
_HEADER_WORDS = {"wording", "source", "term", "phrase", "source wording"}


def match_key(text: str) -> str:
    """Case- and punctuation-insensitive key used to match wording across lists."""
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold()))


def export_bundle(job: Any, rows: Sequence[Mapping[str, Any]], *, source_project: str, source_sha256: str,
                  target_language: str, path: Path) -> dict[str, int]:
    """Write the portable bundle; return counts of what it carries."""
    by_entry = {r["entry_id"]: r for r in rows}
    entries = [{"wording": r["wording"], "category": r["category"], "lemma": r["lemma"], "sense": r["sense"]}
               for r in rows if r["occurrences"]]
    rules = []
    for rule in current_rules(job.root).values():
        row = by_entry.get(rule["group_id"])
        if rule["state"] == "APPROVED" and row is not None:
            rules.append({"wording": row["wording"], "lemma": row["lemma"], "target_language": rule["target_language"],
                          "target_form": rule["target_form"], "effect": rule["effect"]})
    body = {"format": BUNDLE_FORMAT, "version": BUNDLE_VERSION, "from_job": job.job_id, "source_project": source_project,
            "source_sha256": source_sha256, "target_language": target_language,
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "entries": entries,
            "rules": sorted(rules, key=lambda r: (r["wording"], r["target_form"])),
            "key_terms": current_key_terms(job.root)}
    atomic_write_text(path, canonical_json({**body, "bundle_sha256": full_digest(body)}) + "\n")
    return {"entries": len(entries), "rules": len(rules), "key_terms": len(body["key_terms"])}


def read_bundle(path: Path) -> dict[str, Any]:
    """Read and verify a bundle; a wrong format or checksum raises."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        claimed = data.pop("bundle_sha256")
    except (OSError, ValueError, AttributeError, KeyError) as exc:
        raise ValidationError(f"{path.name} is not a PCC terms bundle.", code="PCC_BUNDLE_INVALID") from exc
    if data.get("format") != BUNDLE_FORMAT or data.get("version") != BUNDLE_VERSION or full_digest(data) != claimed:
        raise ValidationError(f"{path.name} is not a PCC terms bundle this version can read, or it was edited.",
                              code="PCC_BUNDLE_INVALID", next_action="Export the bundle again from the original Job.")
    return data


def _propose(job: Any, lock_path: Path, snapshot_sha: str, target_language: str, rows: Sequence[Mapping[str, Any]],
             wording: str, lemma: str, form: str, effect: str, why: str, evidence: str, report: ImportReport,
             existing: dict[str, dict[str, Any]], actor: str) -> bool:
    """Propose one rendering against every matching row; True when a row matched."""
    key = match_key(wording)
    matched = [r for r in rows if match_key(r["wording"]) == key and (not lemma or not r["lemma"] or r["lemma"] == lemma)]
    for row in matched:
        rule = _rule(row["entry_id"], target_language, form, effect, "PROPOSED",
                     {"level": "SECG", "identifier": row["entry_id"]}, why, [evidence], None, None)
        if rule["rule_id"] in existing:
            report.unchanged += 1
        elif _append_rule(job, lock_path, snapshot_sha, rule, "PROPOSE", actor, existing) == "imported":
            existing[rule["rule_id"]] = rule
            report.imported += 1
    return bool(matched)


def import_bundle(job: Any, path: Path, rows: Sequence[Mapping[str, Any]], *, lock_path: Path,
                  source_corpus_sha256: str, target_language: str,
                  actor: str = "operator") -> ImportReport:
    """Load a bundle into this Job; returns what was proposed plus anything that could not be used."""
    bundle = read_bundle(path)
    report = ImportReport()
    on_list = {match_key(r["wording"]) for r in rows}
    report.missing_wordings = [(n, e["wording"]) for n, e in enumerate(bundle["entries"], 1)
                               if e["category"] != "KEY_TERM" and match_key(e["wording"]) not in on_list]
    if bundle.get("key_terms"):
        report.problems.append(f"{len(bundle['key_terms'])} key term(s) in this bundle were not used: key terms belong "
                               "to the reference list (add Paratext Biblical Terms to the list).")
    if bundle.get("verdicts"):
        report.problems.append(f"{len(bundle['verdicts'])} core-list verdict(s) in this bundle were not used: verdicts "
                               "now live in reference-list versions (edit the list's workbook instead).")
    existing = current_rules(job.root)
    skipped = unmatched = 0
    for rule in bundle["rules"]:
        if rule["target_language"] != target_language:
            skipped += 1
        elif not _propose(job, lock_path, source_corpus_sha256, target_language, rows, rule["wording"], rule["lemma"],
                          rule["target_form"], rule["effect"], f"Transferred from {bundle['from_job']}.",
                          f"BUNDLE:{bundle['from_job']}", report, existing, actor):
            unmatched += 1
    if skipped:
        report.problems.append(f"{skipped} rendering(s) are for another target language than {target_language}; not used.")
    if unmatched:
        report.problems.append(f"{unmatched} rendering(s) match no entry in this Job's latest terms list; run the terms list and import again.")
    return report


def _operator_lines(path: Path) -> list[tuple[int, list[str]]]:
    """Read a CSV/TSV/TXT/XLSX list into (line number, cells)."""
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        sheet = load_workbook(path, read_only=True, data_only=True).worksheets[0]
        return [(n, ["" if c is None else str(c) for c in row]) for n, row in enumerate(sheet.iter_rows(values_only=True), 1)]
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{path.name} is not UTF-8 text.", code="PCC_LIST_NOT_UTF8") from exc
    delimiter = "\t" if "\t" in text else ";" if path.suffix.lower() == ".csv" and ";" in text and "," not in text else ","
    if path.suffix.lower() == ".txt" and "\t" not in text:
        return [(n, [line]) for n, line in enumerate(text.splitlines(), 1)]
    return [(n, row) for n, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), 1)]


def import_operator_list(job: Any, path: Path, rows: Sequence[Mapping[str, Any]], *, lock_path: Path,
                         source_corpus_sha256: str, target_language: str, actor: str = "operator") -> ImportReport:
    """Import the Operator's list: wording[, rendering(s)[, note]]; renderings become proposals."""
    report = ImportReport()
    wordings: list[tuple[int, str]] = []
    pairs: list[tuple[int, str, list[str], str]] = []
    for number, cells in _operator_lines(path):
        cells = [unicodedata.normalize("NFC", c).strip() for c in cells]
        if not any(cells) or cells[0].startswith("#"):
            continue
        if number == 1 and cells[0].casefold() in _HEADER_WORDS:
            continue
        if not match_key(cells[0]):
            report.problems.append(f"Line {number}: no wording; line not used.")
            continue
        wordings.append((number, cells[0]))
        if len(cells) > 1 and cells[1]:
            pairs.append((number, cells[0], split_renderings(cells[1]), cells[2] if len(cells) > 2 else ""))
    on_list = {match_key(r["wording"]) for r in rows}
    seen: set[str] = set()
    for number, wording in wordings:
        key = match_key(wording)
        if key not in on_list and key not in seen:
            seen.add(key)
            report.missing_wordings.append((number, wording))
    existing = current_rules(job.root)
    for number, wording, forms, note in pairs:
        for form in forms:
            effect, text = ("REJECT", form[1:].strip()) if form.startswith("!") else ("ACCEPT", form)
            if text and not _propose(job, lock_path, source_corpus_sha256, target_language, rows, wording, "", text, effect,
                                     f"From the Operator's list{': ' + note if note else ''}.", f"OPERATOR_LIST:{path.name}",
                                     report, existing, actor):
                report.problems.append(f"Line {number}: '{wording}' is not on the latest terms list yet; its "
                                       "renderings were not used.")
                break
    return report
