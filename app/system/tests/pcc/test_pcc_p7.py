"""PCC P7: rule scopes, the resolver, staleness, finding decisions, determinism. Fabricated data only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from sage.errors import ValidationError
from sage.pcc import glossary
from sage.pcc.check import run_check
from sage.pcc.check_run import write_reports
from sage.pcc.decisions import DETAIL_FILE, HASHES_FILE, current_finding_decisions, import_finding_decisions
from sage.pcc.glossary import _append_rule, _rule, change_rule_state, current_rules
from sage.pcc.ids import group_id
from sage.pcc.jsonl import write_json, write_jsonl
from sage.pcc.resolver import (Site, applies, occurrence_identifier, passage_hash, passage_identifier, resolve,
                               text_hash)

from .test_pcc_check import _input, _occurrences, _synthetic

GID = group_id("CPT-0000000000000001", "SENSE-1")
KEY = lambda form: " ".join(form.casefold().split())  # noqa: E731


def _r(form, effect="ACCEPT", state="APPROVED", level="SECG", ident=GID):
    """One rule."""
    return _rule(GID, "en", form, effect, state, {"level": level, "identifier": ident}, "t", [], "t", "2026-11-25")


SITE = Site(GID, "GEN 1:3", 0, "h3")
HASHES = {"GEN 1:1": "a", "GEN 1:2": "b", "GEN 1:3": "c"}


def test_most_specific_rule_wins_and_a_specific_reject_beats_a_broad_accept():
    """AT24: an occurrence REJECT overrides a group ACCEPT of the same form; elsewhere the group rule holds."""
    rules = [_r("give up"), _r("give up", "REJECT", level="OCCURRENCE", ident=occurrence_identifier("GEN 1:3", 0, "h3"))]
    assert resolve(rules, SITE, "give up", KEY, HASHES).effect == "REJECT"
    elsewhere = Site(GID, "GEN 1:2", 0, "h2")
    decided = resolve(rules, elsewhere, "give up", KEY, HASHES)
    assert decided.effect == "ACCEPT" and decided.level == "SECG"


def test_proposed_revoked_and_stale_rules_never_accept():
    """AT23."""
    for state in ("PROPOSED", "REVOKED", "STALE"):
        assert resolve([_r("give up", state=state)], SITE, "give up", KEY, HASHES).effect is None


def test_equal_scope_accept_and_reject_conflict_but_different_scopes_do_not():
    """AT14: same level -> CONFLICT; a passage REJECT over a group ACCEPT is simply the decision."""
    assert resolve([_r("x"), _r("x", "REJECT")], SITE, "x", KEY, HASHES).effect == "CONFLICT"
    passage = passage_identifier("GEN 1:3", HASHES)
    assert resolve([_r("x"), _r("x", "REJECT", level="PASSAGE", ident=passage)], SITE, "x", KEY, HASHES).effect == "REJECT"


def test_text_bound_rules_go_stale_when_their_text_changes():
    """AT13: an occurrence or passage rule whose verse text changed does not apply and is reported stale."""
    occ = _r("x", level="OCCURRENCE", ident=occurrence_identifier("GEN 1:3", 0, "h3"))
    assert applies(occ, SITE, HASHES) == "YES"
    assert applies(occ, Site(GID, "GEN 1:3", 0, "changed"), HASHES) == "STALE"
    passage = _r("x", level="PASSAGE", ident=passage_identifier("GEN 1:1-3", HASHES))
    assert applies(passage, SITE, HASHES) == "YES"
    changed = {**HASHES, "GEN 1:2": "z"}
    decided = resolve([passage], SITE, "x", KEY, changed)
    assert decided.effect is None and decided.stale == (passage["rule_id"],)
    assert passage_hash(HASHES, "GEN 1:1-3") != passage_hash(changed, "GEN 1:1-3")
    assert applies(_r("x", level="PASSAGE", ident="GEN 1:1-2"), SITE, HASHES) == "NO"


def test_occurrence_scoped_approval_accepts_only_its_occurrence_and_audit_names_the_rule():
    """An approval at one occurrence makes only that occurrence accepted; the audit row names the rule."""
    source, target = _synthetic({1, 2, 3})
    occs = _occurrences(source, "stand firm")
    inp, gid = _input(source, target, occs, rules=[_r("remain steadfast"), _r("not to give up", state="PROPOSED")])
    first = run_check(inp, qualify=False)
    third = next(e for e in first.evidence[gid] if e.ref == "GEN 1:3")
    ident = occurrence_identifier("GEN 1:3", third.nth, third.verse_hash)
    rules = [_r("remain steadfast"), _r("not to give up", level="OCCURRENCE", ident=ident)]
    inp, gid = _input(source, target, occs, rules=rules)
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC01"
    row = next(r for r in result.audit if r["occurrence_id"] == third.occurrence_id)
    assert rules[1]["rule_id"] in row["reason"] and "OCCURRENCE" in row["reason"]
    changed = [(n, t.replace("not to give up", "not to give up at all") if n == 3 else t) for n, t in
               [(int(u.canonical_ref.split(":")[1]), u.text) for u in target]]
    from .test_pcc_check import _units
    inp, gid = _input(source, _units("T", changed), occs, rules=rules)
    stale = run_check(inp, qualify=False)
    assert stale.stale_rules == {rules[1]["rule_id"]: ["GEN 1:3"]} and stale.outcomes[gid] == "PC10"


def _decide(tmp_path, result, inp, run_id, fill):
    """Write the Run's findings outputs and workbook, fill Decision/Scope/Note by finding code."""
    output = tmp_path / "out"
    write_json(output / "run-manifest.json", {"run_id": run_id})
    write_jsonl(output / DETAIL_FILE, result.details, sort_key="finding_id")
    write_json(output / HASHES_FILE, dict(inp.verse_hashes))
    snapshot = {"scope": "GEN 1", "source": {"project_id": "S"}, "target": {"project_id": "T"}}
    fields = {k: 0 for k in ("evaluated_groups", "fully_resolved_groups", "review_groups", "blocked_groups",
                             "eligible_occurrences", "evaluated_occurrences")}
    _, xlsx = write_reports(tmp_path / "reports", "JOB", run_id, snapshot, result, inp, fields)
    book = load_workbook(xlsx)
    sheet = book["Findings"]
    header = [c.value for c in sheet[1]]
    for row in sheet.iter_rows(min_row=2):
        values = fill.get(row[header.index("Code")].value)
        if values:
            for column, value in values.items():
                row[header.index(column)].value = value
    book.save(xlsx)
    return xlsx, output


def test_approve_variant_from_the_findings_sheet_resolves_the_group(tmp_path):
    """P7-4: APPROVE_VARIANT on a PC10 finding journals approved rules; the next check gives PC01."""
    source, target = _synthetic({1, 2, 3})
    occs = _occurrences(source, "stand firm")
    job = SimpleNamespace(root=tmp_path / "job", job_id="PCC_T-en")
    lock = tmp_path / "lock"
    _append_rule(job, lock, "a" * 64, _r("remain steadfast"), "APPROVE", "t", {})
    _append_rule(job, lock, "a" * 64, _r("not to give up", state="PROPOSED"), "PROPOSE", "t", current_rules(job.root))
    inp, gid = _input(source, target, occs, rules=list(current_rules(job.root).values()))
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC10"
    xlsx, output = _decide(tmp_path, result, inp, "RUN-1", {"PC10": {"Decision": "approve variant", "Note": "both fine"}})
    report = import_finding_decisions(job, xlsx, output, lock_path=lock, source_corpus_sha256="a" * 64, target_language="en")
    assert report.imported == 1 and not report.problems
    approved = [r for r in current_rules(job.root).values() if r["state"] == "APPROVED"]
    assert sorted(r["target_form"] for r in approved) == ["not to give up", "remain steadfast"]
    inp, gid = _input(source, target, occs, rules=list(current_rules(job.root).values()))
    assert run_check(inp, qualify=False).outcomes[gid] == "PC01"
    again = import_finding_decisions(job, xlsx, output, lock_path=lock, source_corpus_sha256="a" * 64, target_language="en")
    assert again.imported == 0 and again.unchanged == 1


def test_dismissed_finding_stays_dismissed_until_its_evidence_changes(tmp_path):
    """P7-4: DISMISS sets the status in later Runs; a changed rendering makes a new, open finding."""
    source, target = _synthetic({1, 2, 3})
    occs = _occurrences(source, "stand firm")
    job = SimpleNamespace(root=tmp_path / "job", job_id="PCC_T-en")
    lock = tmp_path / "lock"
    rules = [_r("remain steadfast"), _r("not to give up", state="PROPOSED")]
    inp, gid = _input(source, target, occs, rules=rules)
    result = run_check(inp, qualify=False)
    xlsx, output = _decide(tmp_path, result, inp, "RUN-1", {"PC10": {"Decision": "DISMISS"}, "PC11": {"Decision": "maybe"}})
    report = import_finding_decisions(job, xlsx, output, lock_path=lock, source_corpus_sha256="a" * 64, target_language="en")
    assert report.imported == 1
    decided = current_finding_decisions(job.root)
    inp, _ = _input(source, target, occs, rules=rules)
    inp.decisions = decided
    later = run_check(inp, qualify=False)
    assert [f["review_status"] for f in later.findings if f["code"] == "PC10"] == ["DISMISSED"]
    from .test_pcc_check import _units
    changed = _units("T", [(int(u.canonical_ref.split(":")[1]), u.text.replace("give up", "yield")) for u in target])
    inp, _ = _input(source, changed, occs, rules=[_r("remain steadfast"), _r("not to yield", state="PROPOSED")])
    inp.decisions = decided
    assert [f["review_status"] for f in run_check(inp, qualify=False).findings if f["code"] == "PC10"] == ["OPEN"]


def test_bad_rows_are_reported_and_a_foreign_workbook_is_refused(tmp_path):
    """Unknown decisions and unusable scopes are reported by row; another Run's workbook is refused."""
    source, target = _synthetic({1, 2, 3})
    occs = _occurrences(source, "stand firm")
    job = SimpleNamespace(root=tmp_path / "job", job_id="PCC_T-en")
    inp, _ = _input(source, target, occs, rules=[_r("remain steadfast"), _r("not to give up", state="PROPOSED")])
    result = run_check(inp, qualify=False)
    xlsx, output = _decide(tmp_path, result, inp, "RUN-1", {"PC10": {"Decision": "APPROVE_VARIANT", "Scope": "CHAPTER"}})
    report = import_finding_decisions(job, xlsx, output, lock_path=tmp_path / "l", source_corpus_sha256="a" * 64,
                                      target_language="en")
    assert report.imported == 0 and "not GROUP, OCCURRENCE or PASSAGE" in report.problems[0]
    xlsx2, _ = _decide(tmp_path / "b", result, inp, "RUN-2", {})
    with pytest.raises(ValidationError) as caught:
        import_finding_decisions(job, xlsx2, output, lock_path=tmp_path / "l", source_corpus_sha256="a" * 64,
                                 target_language="en")
    assert caught.value.code == "PCC_FINDINGS_RUN_MISMATCH"


def test_revoke_and_stale_are_journaled_and_rule_view_rebuilds_from_the_journal(tmp_path):
    """P7-3/P7-5: state changes are events; the rule view is rebuilt from the journal alone."""
    job = SimpleNamespace(root=tmp_path / "job", job_id="PCC_T-en")
    lock = tmp_path / "lock"
    rule = _r("remain steadfast")
    _append_rule(job, lock, "a" * 64, rule, "APPROVE", "t", {})
    assert change_rule_state(job, rule["rule_id"], "STALE", lock_path=lock, source_corpus_sha256="a" * 64, reason="r")
    assert not change_rule_state(job, rule["rule_id"], "STALE", lock_path=lock, source_corpus_sha256="a" * 64, reason="r")
    assert change_rule_state(job, rule["rule_id"], "REVOKED", lock_path=lock, source_corpus_sha256="a" * 64, reason="r")
    assert current_rules(job.root)[rule["rule_id"]]["state"] == "REVOKED"
    ops = [e["operation"] for e in glossary.read_journal(job.root)]
    assert ops == ["APPROVE", "MARK_STALE", "REVOKE"]
    with pytest.raises(ValidationError):
        change_rule_state(job, rule["rule_id"], "APPROVED", lock_path=lock, source_corpus_sha256="a" * 64, reason="r")


def test_check_outputs_and_finding_ids_are_deterministic():
    """P7-5 / AT18: same inputs and rules give identical findings, ids, details and audit."""
    source, target = _synthetic({1, 2, 3})
    occs = _occurrences(source, "stand firm")
    rules = [_r("remain steadfast"), _r("not to give up", state="PROPOSED")]
    a = run_check(_input(source, target, occs, rules=rules)[0])
    b = run_check(_input(source, target, occs, rules=list(reversed(rules)))[0])
    assert a.findings == b.findings and a.details == b.details and a.audit == b.audit
    assert text_hash("x") == text_hash("x") != text_hash("y")
