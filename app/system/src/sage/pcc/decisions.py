"""Decisions on check findings (plan P7-4): import a filled ``PCC-FINDINGS.xlsx`` into the Job journal.

One row per finding; the Operator fills **Decision** and optionally **Scope** and **Note**:

* ``APPROVE_VARIANT``: the finding's unapproved TARGET forms become approved ``ACCEPT`` rules;
* ``REJECT_FORM``: they become approved ``REJECT`` rules;
* ``CONFIRMED_ISSUE``, ``DISMISS``, ``DEFER``: the finding keeps that review status in later Runs until its
  evidence changes (finding ids cover group, code, place, form and verse text).

**Scope** for the two rule decisions: blank or ``GROUP`` (the concept + sense), ``PASSAGE:<range>`` (bound to the
WIP text of that range) or ``OCCURRENCE`` (one rule per occurrence, bound to its verse text). Every decision is a
``review_event`` with the actor and the finding as evidence; rules go through the same records as the glossary.
A bad row is reported with its row number and the others still apply (never hard-block).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from ..references import parse_scope
from .glossary import ImportReport, _append_rule, _load_record, _rule, _store_record, current_rules
from .journal import append_review_event, read_journal
from .jsonl import read_json, read_jsonl
from .resolver import occurrence_identifier, passage_identifier

DECISIONS = ("APPROVE_VARIANT", "REJECT_FORM", "CONFIRMED_ISSUE", "DISMISS", "DEFER")
STATUS_OPERATIONS = {"CONFIRMED_ISSUE": "CONFIRM_ISSUE", "DISMISS": "DISMISS", "DEFER": "DEFER"}
DETAIL_FILE = "finding-detail.jsonl"
HASHES_FILE = "wip-verse-hashes.json"


def current_finding_decisions(job_root: Path) -> dict[str, str]:
    """finding id -> latest status decision (``CONFIRMED_ISSUE`` / ``DISMISS`` / ``DEFER``)."""
    latest: dict[str, str] = {}
    for event in read_journal(job_root):
        if event["subject_type"] == "FINDING" and event["after_hash"]:
            latest[event["subject_id"]] = _load_record(job_root, event["after_hash"])["decision"]
    return latest


def _sheet_rows(path: Path) -> tuple[dict[str, Any], list[tuple[int, dict[str, str]]]]:
    """About values and Findings rows."""
    from openpyxl import load_workbook

    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"{path.name} is not a readable workbook: {exc}", code="PCC_FINDINGS_WORKBOOK_INVALID") from exc
    if "Findings" not in book.sheetnames or "About" not in book.sheetnames:
        raise ValidationError(f"{path.name} is not a PCC findings workbook", code="PCC_FINDINGS_WORKBOOK_INVALID",
                              next_action="Use the PCC-FINDINGS.xlsx of the check Run you are deciding on.")
    about = {str(r[0]): r[1] for r in book["About"].iter_rows(values_only=True) if r and r[0]}
    rows, header = [], None
    for number, values in enumerate(book["Findings"].iter_rows(values_only=True), 1):
        if number == 1:
            header = [str(v or "").strip() for v in values]
            continue
        rows.append((number, {name: ("" if values[i] is None else str(values[i]).strip()) if i < len(values) else ""
                              for i, name in enumerate(header)}))
    return about, rows


def import_finding_decisions(job: Any, path: Path, run_output: Path, *, lock_path: Path, source_corpus_sha256: str,
                             target_language: str, actor: str = "operator", now: datetime | None = None) -> ImportReport:
    """Journal the decisions of a filled findings workbook from the check Run in ``run_output``."""
    about, rows = _sheet_rows(path)
    run_id = read_json(run_output / "run-manifest.json")["run_id"]
    if str(about.get("Run")) != run_id:
        raise ValidationError(f"{path.name} belongs to Run {about.get('Run')}, not {run_id}", code="PCC_FINDINGS_RUN_MISMATCH",
                              next_action="Import the workbook into the Job whose check Run wrote it.")
    details = {d["finding_id"]: d for d in read_jsonl(run_output / DETAIL_FILE)}
    hashes = read_json(run_output / HASHES_FILE) if (run_output / HASHES_FILE).is_file() else {}
    when = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = ImportReport()
    for number, row in rows:
        decision = row.get("Decision", "").upper().replace(" ", "_").replace("-", "_")
        if not decision:
            continue
        finding = details.get(row.get("Finding ID", ""))
        if decision not in DECISIONS:
            report.problems.append(f"row {number}: decision '{row.get('Decision')}' is not one of {', '.join(DECISIONS)}")
            continue
        if finding is None:
            report.problems.append(f"row {number}: finding {row.get('Finding ID') or '?'} is not in Run {run_id}")
            continue
        note = row.get("Note", "")
        if decision in STATUS_OPERATIONS:
            record = {"finding_id": finding["finding_id"], "decision": decision, "note": note, "run_id": run_id}
            digest = _store_record(job.root, record)
            if current_finding_decisions(job.root).get(finding["finding_id"]) == decision:
                report.unchanged += 1
                continue
            append_review_event(
                job.root, lock_path=lock_path, actor_id=actor, operation=STATUS_OPERATIONS[decision], subject_type="FINDING",
                subject_id=finding["finding_id"], rationale=note or decision.replace("_", " ").lower(),
                scope={"level": "SECG", "identifier": finding["group_id"] or finding["finding_id"]}, job_id=job.job_id,
                source_corpus_sha256=source_corpus_sha256, target_language=target_language,
                evidence_refs=[finding["finding_id"], run_id], after_hash=digest)
            report.imported += 1
            continue
        if finding["code"] == "PC12":
            report.problems.append(f"row {number}: PC12 is a possible addition, not a rendering choice; "
                                   "only CONFIRMED_ISSUE, DISMISS or DEFER apply")
            continue
        if not finding["group_id"]:
            report.problems.append(f"row {number}: {finding['code']} has no group; only CONFIRMED_ISSUE, DISMISS or DEFER apply")
            continue
        forms = [i for i in finding["items"] if i["status"] == "FORM" and i["form"]]
        if not forms:
            report.problems.append(f"row {number}: the finding has no unapproved TARGET form to {decision.lower()}")
            continue
        scopes = _scopes(row.get("Scope", ""), finding, forms, hashes)
        if isinstance(scopes, str):
            report.problems.append(f"row {number}: {scopes}")
            continue
        effect = "ACCEPT" if decision == "APPROVE_VARIANT" else "REJECT"
        for scope, form in scopes:
            rule = _rule(finding["group_id"], target_language, form, effect, "APPROVED", scope,
                         f"Decided on finding {finding['finding_id']} ({finding['code']}).{(' ' + note) if note else ''}",
                         [finding["finding_id"], run_id], actor, when)
            outcome = _append_rule(job, lock_path, source_corpus_sha256, rule, "APPROVE" if effect == "ACCEPT" else "REJECT",
                                   actor, current_rules(job.root))
            if outcome == "imported":
                report.imported += 1
            else:
                report.unchanged += 1
    return report


def _scopes(cell: str, finding: dict[str, Any], forms: list[dict[str, Any]],
            hashes: dict[str, str]) -> list[tuple[dict[str, str], str]] | str:
    """(scope, form) pairs for the rules of one decision, or the reason the scope cell cannot be used."""
    text = cell.strip()
    distinct: dict[str, str] = {}
    for item in forms:
        distinct.setdefault(item["form_key"], item["form"])
    if not text or text.upper() in ("GROUP", "SECG"):
        return [({"level": "SECG", "identifier": finding["group_id"]}, form) for form in distinct.values()]
    if text.upper() == "OCCURRENCE":
        return [({"level": "OCCURRENCE", "identifier": occurrence_identifier(i["ref"], i["nth"], i["verse_hash"])}, i["form"])
                for i in forms]
    if text.upper().startswith("PASSAGE:"):
        passage = text.split(":", 1)[1].strip()
        try:
            parse_scope(passage)
        except Exception as exc:  # noqa: BLE001
            return f"scope '{text}' is not a passage reference ({exc})"
        return [({"level": "PASSAGE", "identifier": passage_identifier(passage, hashes)}, form) for form in distinct.values()]
    return f"scope '{text}' is not GROUP, OCCURRENCE or PASSAGE:<reference>"
