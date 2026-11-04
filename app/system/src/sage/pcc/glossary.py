"""PCC glossary (plan phase P5): terms-list export, team import, language facts, Paratext proposals.

The terms list is built from a ``terms`` Run's machine outputs: one row per SOURCE expression and sense.
The team fills in *chosen rendering(s)* per row (Markdown for reading, XLSX for filling in), then imports
the sheet. Every rendering becomes a ``variant_rule`` stored by content hash under ``glossary/records/``
and a chained ``review_event`` in the Job journal; the journal stays the only source of truth and the
rule view is rebuilt from it (``current_rules``). A malformed row is reported with its row number and the
reason, and never stops the other rows (never hard-block). Nothing is written back to Paratext.

Rendering cell syntax: several renderings are separated by ``;`` or a line break; a rendering that starts
with ``!`` is a *rejected* rendering (a negative-equivalence entry, handover doc 04).
Scope cell: blank means the whole group; ``PASSAGE:<reference>`` limits the rule to one passage.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_text
from ..errors import ValidationError
from ..hashing import sha256_file
from .contracts import SCHEMA_VERSION, validate_record
from .ids import canonical_json, full_digest, make_id
from .journal import append_review_event, journal_path, read_journal
from .jsonl import read_json, read_jsonl

RECORDS_DIRECTORY = "records"
LIST_ID_SHEET = "About"
TERMS_SHEET = "Terms"
FACTS_SHEET = "Language facts"
COLUMNS = (
    "Entry ID", "Category", "Wording", "Sense", "OL lemma", "Occurrences", "Verses", "Books",
    "Examples", "Chosen rendering(s)", "Scope", "Notes",
)
FACT_KEYS = (
    ("negation_markers", "Negation markers or affixes (separate with ;)"),
    ("apostrophe", "Correct apostrophe / glottal-stop character (one character)"),
    ("spelling_equivalences", "Declared spelling variants (a=b; separate pairs with ;)"),
    ("word_break", "Word-break conventions (free text)"),
)
_LEMMA = re.compile(r"original-language lemma (\S+)")
_PASSAGE = re.compile(r"^PASSAGE:\s*(\S.*)$", re.IGNORECASE)


@dataclass
class ImportReport:
    """What an import changed and what it could not use."""

    imported: int = 0
    unchanged: int = 0
    problems: list[str] = field(default_factory=list)

    def as_lines(self) -> list[str]:
        """Return Operator-readable lines."""
        lines = [f"Imported {self.imported} rendering rule(s); {self.unchanged} already recorded."]
        lines += [f"- {problem}" for problem in self.problems]
        return lines


def normalize_rendering(text: str) -> str:
    """NFC with folded whitespace; case, diacritics and punctuation are never normalized away."""
    return " ".join(unicodedata.normalize("NFC", text).split())


# --- terms list -----------------------------------------------------------------------------------


def terms_rows(output: Path) -> list[dict[str, Any]]:
    """Return one row per expression and sense from a ``terms`` Run's output folder, in a stable order."""
    expressions = read_jsonl(output / "expressions.jsonl", kind="expression")
    occurrences = read_jsonl(output / "occurrences.jsonl", kind="occurrence")
    groups_path = output / "groups.jsonl"
    groups = read_jsonl(groups_path) if groups_path.is_file() else []
    group_ids = {(g["expression_id"], g["sense_id"]): g["group_id"] for g in groups}
    by_pair: dict[tuple[str, str | None], list[Mapping[str, Any]]] = defaultdict(list)
    for occ in occurrences:
        sense = occ["sense_id"] if occ["sense_state"] == "CONFIRMED" else None
        by_pair[(occ["expression_id"], sense)].append(occ)
    rows: list[dict[str, Any]] = []
    for expr in expressions:
        eid = expr["expression_id"]
        for sense in expr["senses"]:
            mine = by_pair.get((eid, sense["sense_id"]), [])
            if not mine and sense["review_state"] == "PROVISIONAL" and len(expr["senses"]) > 1:
                continue
            rows.append(_row(expr, sense, mine, group_ids.get((eid, sense["sense_id"]))))
        unresolved = by_pair.get((eid, None), [])
        if unresolved:
            rows.append(_row(expr, None, unresolved, None))
        elif not expr["senses"]:
            rows.append(_row(expr, None, [], None))
    rows.sort(key=lambda r: (r["category"], r["normalized"], r["sense"], r["entry_id"]))
    return rows


def _row(expr: Mapping[str, Any], sense: Mapping[str, Any] | None, occs: Sequence[Mapping[str, Any]],
         group: str | None) -> dict[str, Any]:
    """Build one terms-list row."""
    sense_id = sense["sense_id"] if sense else None
    entry_id = group or make_id("group", ["entry", expr["expression_id"], sense_id])
    refs = sorted({o["canonical_ref"] for o in occs})
    lemma = ""
    if sense:
        found = _LEMMA.search(sense["discriminator"])
        lemma = unicodedata.normalize("NFC", found.group(1)) if found else ""
    books = sorted({ref.split(" ")[0] for ref in refs})
    return {
        "entry_id": entry_id,
        "expression_id": expr["expression_id"],
        "sense_id": sense_id,
        "category": expr["category"],
        "wording": expr["source_surface"],
        "normalized": expr["normalized_source_form"],
        "sense": sense["label"] if sense else "UNRESOLVED (team decides)",
        "lemma": lemma,
        "occurrences": len(occs),
        "verses": len({o["source_unit_id"] for o in occs}),
        "books": ", ".join(books),
        "examples": "; ".join(refs[:3]),
    }


def terms_list_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    """Fingerprint the list a filled sheet answers (identity, wording and counts)."""
    return full_digest([[r["entry_id"], r["normalized"], r["sense_id"], r["occurrences"], r["verses"]] for r in rows])


def write_terms_list(rows: Sequence[Mapping[str, Any]], *, job_id: str, run_id: str, target_language: str,
                     markdown: Path, xlsx: Path) -> str:
    """Write ``TERMS-LIST.md`` and ``TERMS-LIST.xlsx``; return the list hash both carry."""
    from openpyxl import Workbook

    digest = terms_list_hash(rows)
    lines = [f"# PCC terms list: {job_id}", "", f"Run {run_id} · target language {target_language} · list {digest[:16]}", "",
             "Senses come from original-language lemmas as evidence, not authority. Fill in the XLSX and import it.", ""]
    category = None
    for row in rows:
        if row["category"] != category:
            category = row["category"]
            lines += ["", f"## {category}", "", "| Wording | Sense | Occurrences | Verses | Books | Examples |",
                      "|---|---|---|---|---|---|"]
        lines.append("| " + " | ".join(str(row[k]).replace("|", "\\|") for k in
                                       ("wording", "sense", "occurrences", "verses", "books", "examples")) + " |")
    atomic_write_text(markdown, "\n".join(lines) + "\n")
    book = Workbook()
    sheet = book.active
    sheet.title = TERMS_SHEET
    sheet.append(list(COLUMNS))
    for row in rows:
        sheet.append([row["entry_id"], row["category"], row["wording"], row["sense"], row["lemma"],
                      row["occurrences"], row["verses"], row["books"], row["examples"], "", "", ""])
    facts = book.create_sheet(FACTS_SHEET)
    facts.append(["Fact", "Value (optional; blank means not declared)"])
    for key, label in FACT_KEYS:
        facts.append([label, ""])
    about = book.create_sheet(LIST_ID_SHEET)
    for item in (["list_hash", digest], ["job_id", job_id], ["run_id", run_id], ["target_language", target_language]):
        about.append(item)
    xlsx.parent.mkdir(parents=True, exist_ok=True)
    book.save(xlsx)
    return digest


# --- rule store -----------------------------------------------------------------------------------


def _record_path(job_root: Path, digest: str) -> Path:
    """Return the content-addressed record path."""
    return journal_path(job_root).parent / RECORDS_DIRECTORY / f"{digest}.json"


def _store_record(job_root: Path, record: Mapping[str, Any]) -> str:
    """Write one record under its own hash (idempotent) and return the hash."""
    digest = full_digest(record)
    path = _record_path(job_root, digest)
    if not path.is_file():
        atomic_write_text(path, canonical_json(record) + "\n")
    return digest


def _load_record(job_root: Path, digest: str) -> dict[str, Any]:
    """Read one record and prove it still matches the hash the journal names."""
    path = _record_path(job_root, digest)
    if not path.is_file():
        raise ValidationError(f"PCC glossary record {digest[:12]} is missing", code="PCC_GLOSSARY_RECORD_MISSING",
                              details={"path": str(path)})
    value = read_json(path)
    if full_digest(value) != digest:
        raise ValidationError(f"PCC glossary record {digest[:12]} was edited", code="PCC_GLOSSARY_RECORD_TAMPERED",
                              details={"path": str(path)})
    return value


def current_rules(job_root: Path) -> dict[str, dict[str, Any]]:
    """Return ``rule_id -> variant_rule`` as the journal's latest events define them (REVOKED included)."""
    latest: dict[str, dict[str, Any]] = {}
    for event in read_journal(job_root):
        if event["subject_type"] == "VARIANT_RULE" and event["subject_id"].startswith("RULE-") and event["after_hash"]:
            latest[event["subject_id"]] = event
    return {rid: validate_record("variant_rule", _load_record(job_root, ev["after_hash"]), where=rid)
            for rid, ev in latest.items()}


def current_language_facts(job_root: Path) -> dict[str, Any]:
    """Return the team-declared language facts (empty when none were declared)."""
    last = None
    for event in read_journal(job_root):
        if event["subject_id"].startswith("FACTS-") and event["after_hash"]:
            last = event
    return _load_record(job_root, last["after_hash"])["facts"] if last else {}


def _rule(group_id: str, language: str, form: str, effect: str, state: str, scope: Mapping[str, str],
          rationale: str, evidence: Sequence[str], actor: str | None, when: str | None) -> dict[str, Any]:
    """Build a ``variant_rule`` record."""
    normalized = normalize_rendering(form)
    return {
        "schema_version": SCHEMA_VERSION,
        "rule_id": make_id("rule", [group_id, normalized, effect, dict(scope)]),
        "group_id": group_id, "target_language": language, "target_form": form,
        "normalized_target_form": normalized, "type": "EXACT", "effect": effect, "state": state,
        "scope": dict(scope), "protected_features": [], "rationale": rationale,
        "evidence_refs": sorted(set(evidence)), "approved_by": actor if state == "APPROVED" else None,
        "approved_at_utc": when if state == "APPROVED" else None,
    }


def _append_rule(job: Any, lock_path: Path, snapshot_sha: str, rule: dict[str, Any], operation: str, actor: str,
                 existing: Mapping[str, Mapping[str, Any]]) -> str:
    """Journal one rule transition; returns ``imported`` or ``unchanged``."""
    before = existing.get(rule["rule_id"])
    if before is not None and before["state"] == rule["state"]:
        return "unchanged"
    digest = _store_record(job.root, rule)
    append_review_event(
        job.root, lock_path=lock_path, actor_id=actor, operation=operation, subject_type="VARIANT_RULE",
        subject_id=rule["rule_id"], rationale=rule["rationale"], scope=rule["scope"], job_id=job.job_id,
        source_corpus_sha256=snapshot_sha, target_language=rule["target_language"],
        evidence_refs=rule["evidence_refs"], before_hash=full_digest(before) if before else None, after_hash=digest)
    return "imported"


# --- import of a filled sheet ----------------------------------------------------------------------


def _cells(sheet: Any) -> list[tuple[int, list[Any]]]:
    """Return (row number, values) for every non-empty row after the header."""
    out = []
    for number, row in enumerate(sheet.iter_rows(values_only=True), 1):
        if number > 1 and any(c not in (None, "") for c in row):
            out.append((number, list(row)))
    return out


def _text(value: Any) -> str:
    """Return a cell as trimmed text."""
    return "" if value is None else str(value).strip()


def split_renderings(cell: str) -> list[str]:
    """Split a rendering cell on ``;`` and line breaks."""
    return [part.strip() for part in re.split(r"[;\n\r]+", cell) if part.strip()]


def parse_scope(cell: str, group_id: str) -> dict[str, str] | None:
    """Return a legal rule scope, or None for an illegal cell."""
    if not cell:
        return {"level": "SECG", "identifier": group_id}
    found = _PASSAGE.match(cell)
    return {"level": "PASSAGE", "identifier": " ".join(found.group(1).split())} if found else None


def import_filled_list(job: Any, xlsx: Path, rows: Sequence[Mapping[str, Any]], *, lock_path: Path,
                       source_corpus_sha256: str, target_language: str, actor: str = "operator") -> ImportReport:
    """Import a filled terms-list workbook into the Job journal; report, never skip silently."""
    from openpyxl import load_workbook

    report = ImportReport()
    try:
        book = load_workbook(xlsx, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any unreadable workbook is one reported problem
        report.problems.append(f"{xlsx.name}: cannot be read as an XLSX workbook ({exc})")
        return report
    try:
        about = {_text(r[0]): _text(r[1]) for r in book[LIST_ID_SHEET].iter_rows(values_only=True) if r and r[0]} \
            if LIST_ID_SHEET in book.sheetnames else {}
        if about.get("list_hash") != terms_list_hash(rows):
            report.problems.append("The sheet answers a different terms list than the current one (or has no About sheet); "
                                   "nothing was imported. Export the list again and copy the answers over.")
            return report
        known = {r["entry_id"] for r in rows}
        existing = current_rules(job.root)
        if TERMS_SHEET not in book.sheetnames:
            report.problems.append(f"The workbook has no '{TERMS_SHEET}' sheet; nothing was imported.")
            return report
        for number, values in _cells(book[TERMS_SHEET]):
            values += [None] * (len(COLUMNS) - len(values))
            entry = _text(values[0])
            renderings = split_renderings(_text(values[9]))
            if not renderings and not _text(values[10]):
                continue
            where = f"Terms row {number}"
            if entry not in known:
                report.problems.append(f"{where}: entry '{entry}' is not in the current terms list; row not used.")
                continue
            scope = parse_scope(_text(values[10]), entry)
            if scope is None:
                report.problems.append(f"{where}: scope '{_text(values[10])}' is not blank or PASSAGE:<reference>; row not used.")
                continue
            if not renderings:
                report.problems.append(f"{where}: a scope was given without a chosen rendering; row not used.")
                continue
            note = _text(values[11])
            for form in renderings:
                reject = form.startswith("!")
                text = form[1:].strip() if reject else form
                if not text:
                    report.problems.append(f"{where}: an empty rendering after '!'; not used.")
                    continue
                rule = _rule(entry, target_language, text, "REJECT" if reject else "ACCEPT", "APPROVED", scope,
                             note or "Team rendering from the terms list.", [f"TERMS-LIST:{about['list_hash'][:16]}"],
                             actor, _now())
                outcome = _append_rule(job, lock_path, source_corpus_sha256, rule, "REJECT" if reject else "APPROVE",
                                       actor, existing)
                existing[rule["rule_id"]] = rule
                setattr(report, outcome, getattr(report, outcome) + 1)
        if FACTS_SHEET in book.sheetnames:
            _import_facts(job, book[FACTS_SHEET], report, lock_path, source_corpus_sha256, target_language, actor)
    finally:
        book.close()
    return report


def _now() -> str:
    """Return the current UTC time in SAGE's second-precision form."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_facts(values: Mapping[str, str]) -> tuple[dict[str, Any], list[str]]:
    """Validate declared language facts; return the usable facts and one problem per bad entry."""
    facts: dict[str, Any] = {}
    problems: list[str] = []
    negation = split_renderings(values.get("negation_markers", ""))
    if negation:
        facts["negation_markers"] = sorted({unicodedata.normalize("NFC", n) for n in negation})
    apostrophe = unicodedata.normalize("NFC", values.get("apostrophe", "").strip())
    if apostrophe:
        if len(apostrophe) == 1:
            facts["apostrophe"] = apostrophe
        else:
            problems.append(f"apostrophe '{apostrophe}' must be exactly one character; not used.")
    pairs = []
    for part in split_renderings(values.get("spelling_equivalences", "")):
        sides = [s.strip() for s in part.split("=")]
        if len(sides) == 2 and all(sides) and sides[0] != sides[1]:
            pairs.append(sorted(unicodedata.normalize("NFC", s) for s in sides))
        else:
            problems.append(f"spelling variant '{part}' is not in the form a=b; not used.")
    if pairs:
        facts["spelling_equivalences"] = sorted({tuple(p) for p in pairs})
        facts["spelling_equivalences"] = [list(p) for p in facts["spelling_equivalences"]]
    if values.get("word_break", "").strip():
        facts["word_break"] = " ".join(values["word_break"].split())
    return facts, problems


def _import_facts(job: Any, sheet: Any, report: ImportReport, lock_path: Path, sha: str, language: str,
                  actor: str) -> None:
    """Journal the declared facts when they differ from the current ones."""
    keys = {label: key for key, label in FACT_KEYS}
    raw = {keys[_text(r[0])]: _text(r[1]) for r in sheet.iter_rows(min_row=2, values_only=True)
           if r and _text(r[0]) in keys}
    facts, problems = parse_facts(raw)
    report.problems += [f"Language facts: {p}" for p in problems]
    if not facts or facts == current_language_facts(job.root):
        return
    record = {"schema_version": SCHEMA_VERSION, "target_language": language, "facts": facts}
    digest = _store_record(job.root, record)
    append_review_event(
        job.root, lock_path=lock_path, actor_id=actor, operation="APPROVE", subject_type="VARIANT_RULE",
        subject_id=f"FACTS-{language}", rationale="Team-declared language facts.",
        scope={"level": "LANGUAGE_PROFILE", "identifier": language}, job_id=job.job_id,
        source_corpus_sha256=sha, target_language=language, after_hash=digest)
    report.imported += 1


# --- Paratext TermRenderings (read-only, D10) -----------------------------------------------------


@dataclass(frozen=True)
class ParatextTerm:
    """One term from TermRenderings.xml: the lemma-keyed Id and its renderings."""

    term_id: str
    renderings: tuple[str, ...]
    skipped: tuple[str, ...] = ()


def read_term_renderings(path: Path) -> list[ParatextTerm]:
    """Parse a Paratext ``TermRenderings.xml`` read-only; patterns SAGE cannot match are listed, not used."""
    raw = path.read_bytes()
    if b"<!ENTITY" in raw or b"<!DOCTYPE" in raw:
        raise ValidationError(f"{path.name} declares a DTD or entities; SAGE will not parse it.",
                              code="PCC_PARATEXT_XML_UNSAFE", next_action="Export a plain TermRenderings.xml.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValidationError(f"{path.name} is not valid XML: {exc}", code="PCC_PARATEXT_XML_INVALID") from exc
    terms: list[ParatextTerm] = []
    for element in root.iter("TermRendering"):
        term_id = unicodedata.normalize("NFC", (element.get("Id") or "").strip())
        text = (element.findtext("Renderings") or "").strip()
        if not term_id or not text:
            continue
        usable, skipped = [], []
        for part in (p.strip() for p in text.split("||")):
            core = part.strip("*").strip()
            if not core:
                continue
            if any(c in core for c in "*[]()"):
                skipped.append(part)
            else:
                usable.append(core)
        terms.append(ParatextTerm(term_id, tuple(dict.fromkeys(usable)), tuple(skipped)))
    return terms


def propose_from_paratext(job: Any, path: Path, rows: Sequence[Mapping[str, Any]], *, lock_path: Path,
                          source_corpus_sha256: str, target_language: str, actor: str = "operator") -> ImportReport:
    """Turn matching Paratext renderings into PROPOSED rules the Operator still has to confirm."""
    report = ImportReport()
    terms = read_term_renderings(path)
    digest = sha256_file(path)
    by_lemma: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["lemma"]:
            by_lemma[row["lemma"]].append(row)
    existing = current_rules(job.root)
    unmatched = 0
    for term in terms:
        matched = by_lemma.get(term.term_id)
        for item in term.skipped:
            report.problems.append(f"Paratext term {term.term_id}: pattern '{item}' cannot be matched; not used.")
        if not matched:
            unmatched += 1
            continue
        for row in matched:
            for form in term.renderings:
                rule = _rule(row["entry_id"], target_language, form, "ACCEPT", "PROPOSED",
                             {"level": "SECG", "identifier": row["entry_id"]},
                             f"Proposed from Paratext TermRenderings for {term.term_id}.",
                             [f"PARATEXT:TermRenderings:{digest}", f"term:{term.term_id}"], None, None)
                if rule["rule_id"] in existing:
                    report.unchanged += 1
                    continue
                _append_rule(job, lock_path, source_corpus_sha256, rule, "PROPOSE", actor, existing)
                existing[rule["rule_id"]] = rule
                report.imported += 1
    if unmatched:
        report.problems.append(f"{unmatched} Paratext term(s) matched no entry in this terms list; they were not used.")
    return report


def proposed_rules(job_root: Path) -> list[dict[str, Any]]:
    """Return the rules still waiting for an Operator decision, in a stable order."""
    return sorted((r for r in current_rules(job_root).values() if r["state"] == "PROPOSED"),
                  key=lambda r: (r["group_id"], r["normalized_target_form"]))


def decide_proposals(job: Any, rule_ids: Iterable[str], *, approve: bool, lock_path: Path,
                     source_corpus_sha256: str, actor: str = "operator") -> int:
    """Approve (or revoke) proposed rules by ID; returns how many changed."""
    rules = current_rules(job.root)
    changed = 0
    for rid in rule_ids:
        rule = rules.get(rid)
        if rule is None or rule["state"] != "PROPOSED":
            continue
        updated = dict(rule, state="APPROVED" if approve else "REVOKED",
                       approved_by=actor if approve else None, approved_at_utc=_now() if approve else None,
                       rationale=rule["rationale"] + (" Confirmed by the Operator." if approve else " Declined by the Operator."))
        _append_rule(job, lock_path, source_corpus_sha256, updated, "APPROVE" if approve else "REVOKE", actor, rules)
        changed += 1
    return changed
