"""A PCC check Run (plan P6-7): prepare the check's inputs, run it, write the machine outputs and the reports.

Machine outputs (Run ``validation/pcc``): the terms analysis of the scope, ``findings.jsonl``,
``occurrence-audit.jsonl`` (one row per eligible occurrence), ``reverse-audit.jsonl`` (one row per group
rendering the reverse scan found outside the group's verses, P8), ``summary.json`` and ``qualification.json``.
Operator reports (``localdata/reports/<job>/``): ``PCC-CHECK.md`` and ``PCC-FINDINGS.xlsx`` with blank
*decision* / *scope* / *note* columns for P7. TARGET wording is quoted verbatim with references; SOURCE text is
referred to by reference and short wording only. A kind the WIP could not be qualified for, and negation
without declared markers, are exception reports (``NOT_ASSESSED``), never a pass.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_text
from ..exception_reports import NOT_ASSESSED, ExceptionRecord, record_exception
from ..registry import EcosystemConfig
from ..vrs import load_project_vrs
from . import glossary
from .align import ALIGNER_VERSION, load_model, save_model
from dataclasses import replace

from .check import (CheckInput, Morphology, pair_verses, run_check, side_tokens, stop_forms, train_pair_model,
                    wip_verse_hashes)
from .decisions import DETAIL_FILE, HASHES_FILE, current_finding_decisions
from .resolver import language_equivalences
from .ids import full_digest
from .jsonl import read_jsonl, write_json, write_jsonl
from .rlservice import CACHE_FOLDER
from ..references import parse_scope
from .source_text import reference_units, source_units as scope_source_units
from .traits import measure_traits

CHECK_LIMITATION = (
    "Consistency check (plan phases P6-P8): each compared concept and sense was located in the WIP through "
    "glossary forms and learned word alignment; the reverse scan looked for each group's renderings in the scope's "
    "other verses. A rendering there is PC12 only when no other listed concept, no SOURCE wording of the group and "
    "no SOURCE word of the verse supports it. PC12 is a lower-confidence review candidate; its false-alarm rate is "
    "not measured yet, and original-language referents (subjref) are not consulted."
)
REVIEW_CODES = ("PC10", "PC11", "PC12", "PC13", "PC20", "PC21")
REVERSE_FILE = "reverse-audit.jsonl"


def testament_of(ref: str) -> str:
    """``NT`` or ``OT`` for a ``BOOK C:V`` reference: the model is trained per testament (time, vocabulary)."""
    from ..canon import NT_27
    return "NT" if ref.split(" ")[0] in NT_27 else "OT"


def check_analysis(config: EcosystemConfig, job: Any, snapshot: dict[str, Any], output: Path, run: Any,
                   stages: tuple[str, ...]) -> tuple[dict[str, Any], int]:
    """Run the check over the scope; return (summary fields, number of exception notes)."""
    source = config.project(snapshot["source"]["project_id"])
    wip = config.project(snapshot["target"]["project_id"])
    source_units = {u.unit_id: u for u in reference_units(source.path)}
    target_units = {u.unit_id: u for u in reference_units(wip.path)}
    pairs, unit_pair = pair_verses(list(source_units.values()), list(target_units.values()),
                                   load_project_vrs(config, source), load_project_vrs(config, wip))
    source_traits = measure_traits(u.text for u in source_units.values())
    wip_traits = measure_traits(u.text for u in target_units.values())
    source_side = side_tokens(pairs, source_units, "source", cased=source_traits.cased,
                              letter_marks=source_traits.letter_marks, unspaced=source_traits.unspaced)
    target_side = side_tokens(pairs, target_units, "target", cased=wip_traits.cased,
                              letter_marks=wip_traits.letter_marks, unspaced=wip_traits.unspaced)
    occurrences = read_jsonl(output / "occurrences.jsonl", kind="occurrence")
    testaments = sorted({testament_of(o["canonical_ref"]) for o in occurrences}) or ["NT", "OT"]
    training = [p for p in pairs if testament_of(source_units[p.source[0]].canonical_ref) in testaments]
    key = hashlib.sha256("|".join((ALIGNER_VERSION, snapshot["source"]["content_sha256"],
                                   snapshot["target"]["content_sha256"], source.project_id, wip.project_id,
                                   *testaments)).encode()).hexdigest()
    model_path = Path(config.cache_root) / CACHE_FOLDER / f"model-{key}.json.gz"
    model = load_model(model_path)
    if model is None:
        model = train_pair_model(training, source_side, target_side)
        save_model(model_path, model)
    facts = glossary.current_language_facts(job.root)
    rules = glossary.current_rules(job.root)
    morph = Morphology.from_traits(wip_traits, facts)
    morph = replace(morph, equivalences={**morph.equivalences, **language_equivalences(rules.values())})
    inp = CheckInput(
        run_id=run.run_id,
        run_input_sha256=full_digest({k: snapshot[k] for k in ("source", "target", "scope", "decision_snapshot_sha256",
                                                               "reference_list")}),
        source_units=source_units, target_units=target_units, pairs=pairs, unit_pair=unit_pair,
        source_side=source_side, target_side=target_side, model=model, morph=morph,
        expressions=read_jsonl(output / "expressions.jsonl", kind="expression"),
        occurrences=occurrences,
        groups=read_jsonl(output / "groups.jsonl") if (output / "groups.jsonl").is_file() else [],
        rules=rules, target_stops=stop_forms(target_side), source_stops=stop_forms(source_side),
        verse_hashes=wip_verse_hashes(target_units), decisions=current_finding_decisions(job.root),
        scope_units=frozenset(u.unit_id for u in scope_source_units(source.path, parse_scope(snapshot["scope"]))))
    result = run_check(inp)
    write_jsonl(output / "findings.jsonl", result.findings, kind="finding", sort_key="finding_id")
    write_jsonl(output / "occurrence-audit.jsonl", result.audit, kind="occurrence_audit", sort_key="occurrence_id")
    write_jsonl(output / DETAIL_FILE, result.details, sort_key="finding_id")
    write_jsonl(output / REVERSE_FILE, result.reverse)
    write_json(output / HASHES_FILE, dict(sorted(inp.verse_hashes.items())))
    write_json(output / "stale-rules.json", {rule: sorted(set(refs)) for rule, refs in sorted(result.stale_rules.items())})
    write_json(output / "qualification.json", {"kinds": result.qualification, "pairs": len(pairs),
                                               "pair_kinds": dict(Counter(p.kind for p in pairs)),
                                               "wip_traits": wip_traits.as_record(), "counts": dict(sorted(result.counts.items()))})
    notes: list[tuple[str, str]] = []
    for kind in result.best_effort:
        q = result.qualification[kind]
        notes.append(("PCC_KIND_BEST_EFFORT", f"{kind.lower()} detection is best effort for this WIP: measured recall "
                      f"{q['recall'] if q['recall'] is not None else 'n/a'} on {q['trials']} planted case(s), bar {q['bar']}. "
                      "Its findings are shown, labelled; some cases may be missed. Tune the reference list and glossary "
                      "through their import/export."))
    if result.stale_rules:
        notes.append(("PCC_RULES_STALE", f"{len(result.stale_rules)} approved rule(s) were not applied because the text "
                      "they are bound to changed. Review them under 'Review stale rules'; they are never deleted."))
    for gid, code in sorted(result.outcomes.items()):
        if code == "PC23":
            notes.append(("PCC_RULE_CONFLICT", f"Group {gid}: approved rules accept and reject the same form at the same "
                          "scope; the group was not assessed (PC23). Revoke one of the rules."))
    if not morph.negation:
        notes.append(("PCC_NEGATION_NOT_CHECKED", "No negation markers are declared for the WIP language, so negation "
                      "shifts (PC13) were not checked. Declare them in the language facts sheet to switch this on."))
    for code, message in notes:
        record_exception(run.root, ExceptionRecord(tool="pcc", code=code, message=message, effect=NOT_ASSESSED,
                                                   run_id=run.run_id, job_id=job.job_id, stage=stages[2],
                                                   coordinates=(snapshot["scope"],), severity="WARNING"))
    codes = Counter(f["code"] for f in result.findings)
    outcomes = Counter(result.outcomes.values())
    fields = {
        "eligible_groups": len(result.outcomes) + result.counts["informational_groups"],
        "evaluated_groups": len(result.outcomes),
        "fully_resolved_groups": outcomes["PC00"] + outcomes["PC01"],
        "eligible_occurrences": len(result.audit),
        "evaluated_occurrences": sum(1 for r in result.audit if r["disposition"] == "EVALUATED"),
        "review_groups": sum(n for c, n in outcomes.items() if c in REVIEW_CODES),
        "blocked_groups": outcomes["PC23"],
        "findings_by_code": dict(sorted(codes.items())),
        "issue_clusters": len({f["issue_cluster_id"] for f in result.findings if f["code"] in REVIEW_CODES + ("PC23",)}),
        "reverse_scan": dict(sorted(Counter(r["disposition"] for r in result.reverse).items())),
        "limitations": [CHECK_LIMITATION] + [f"{kind} BEST_EFFORT (self-qualification below the bar)" for kind in result.best_effort],
    }
    write_reports(Path(config.reports_root) / job.job_id, job.job_id, run.run_id, snapshot, result, inp, fields)
    return fields, len(notes)


def write_reports(folder: Path, job_id: str, run_id: str, snapshot: dict[str, Any], result: Any, inp: CheckInput,
                  fields: dict[str, Any]) -> tuple[Path, Path]:
    """``PCC-CHECK.md`` and ``PCC-FINDINGS.xlsx`` (one row per finding, blank decision columns)."""
    from openpyxl import Workbook

    folder.mkdir(parents=True, exist_ok=True)
    exprs = {e["expression_id"]: e for e in inp.expressions}
    groups = {g["group_id"]: g for g in inp.groups}

    def wording(finding):
        """SOURCE wording of a finding's group."""
        group = groups.get(finding["group_id"] or "")
        return exprs.get(group["expression_id"], {}).get("source_surface", "") if group else ""

    lines = [f"# PCC consistency check: {job_id}", "",
             f"Run {run_id} · scope {snapshot['scope']} · SOURCE {snapshot['source']['project_id']} · "
             f"WIP {snapshot['target']['project_id']}", "",
             f"- Groups compared: {fields['evaluated_groups']} ({fields['fully_resolved_groups']} consistent with approved "
             f"renderings); groups needing review: {fields['review_groups']}; blocked: {fields['blocked_groups']}.",
             f"- Occurrences: {fields['eligible_occurrences']} listed, {fields['evaluated_occurrences']} evaluated without review.",
             "- Uniform but unapproved renderings are PC02: they look consistent, but no rendering has been approved yet.",
             f"- Issues: {fields.get('issue_clusters', 0)} (findings on the same problem, such as a PC11 omission and a PC12 "
             "rendering in the next verse, count once).",
             "- Reverse scan: " + (", ".join(f"{n} {k.lower().replace('_', ' ')}" for k, n in fields.get("reverse_scan", {}).items())
                                   or "no group rendering found outside its verses") + ". Only 'added' ones are PC12.", ""]
    for kind, q in sorted(result.qualification.items()):
        lines.append(f"- Self-check {kind.lower()}: {q['status']} (found {q['detected']} of {q['trials']} planted cases).")
    lines += ["", "| Code | Severity | SOURCE wording | References | TARGET renderings |", "|---|---|---|---|---|"]
    for f in sorted(result.findings, key=lambda f: (f["code"], f["source_refs"][:1], f["finding_id"])):
        lines.append(f"| {f['code']} | {f['severity']} | {wording(f)} | {', '.join(f['source_refs'][:6])} | "
                     + "; ".join(e.replace("|", "\\|") for e in f["evidence"][:4]) + " |")
    markdown = folder / "PCC-CHECK.md"
    atomic_write_text(markdown, "\n".join(lines) + "\n")
    book = Workbook()
    sheet = book.active
    sheet.title = "Findings"
    sheet.append(["Finding ID", "Code", "Severity", "SOURCE wording", "SOURCE references", "TARGET references",
                  "Evidence", "Reason", "Issue", "Decision", "Scope", "Note"])
    for f in sorted(result.findings, key=lambda f: f["finding_id"]):
        sheet.append([_safe(v) for v in (f["finding_id"], f["code"], f["severity"], wording(f), ", ".join(f["source_refs"]),
                                         ", ".join(f["target_refs"]), "\n".join(f["evidence"]), f["reason"],
                                         f["issue_cluster_id"], "", "", "")])
    about = book.create_sheet("About")
    about.append(["Run", run_id])
    about.append(["Run input", full_digest(snapshot)[:16]])
    xlsx = folder / "PCC-FINDINGS.xlsx"
    book.save(xlsx)
    return markdown, xlsx


def _safe(value: Any) -> Any:
    """Cell text that a spreadsheet will not run as a formula."""
    return "'" + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@") else value
