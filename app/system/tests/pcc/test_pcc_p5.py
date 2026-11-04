"""PCC phase P5: terms-list export, filled-sheet import, language facts, Paratext proposals."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from sage.errors import ValidationError
from sage.pcc import glossary
from sage.pcc.discovery import SourceUnit, discover
from sage.pcc.jsonl import write_jsonl
from sage.pcc.journal import read_journal
from sage.pcc.sense import OlItem, assign_senses
from sage.pcc.traits import measure_traits

SHA = "e" * 64
WEIGHT = OlItem("G1", "βάρος", "1", "weight")
LAMP = OlItem("G2", "φῶς", "2", "light")


def _terms_output(tmp_path: Path) -> Path:
    """Implement terms output."""
    rows = [("a light yoke", [WEIGHT]), ("a light load", [WEIGHT]), ("light lamp", [LAMP]), ("light day", [LAMP])]
    units = [SourceUnit(f"u{i}", f"MAT 1:{i + 1}", (f"MAT 1:{i + 1}",), t) for i, (t, _) in enumerate(rows)]
    found = discover(units, source_corpus_id="S", source_sha256=SHA, traits=measure_traits(u.text for u in units))
    sensed = assign_senses(found.expressions, found.occurrences, {f"u{i}": r[1] for i, r in enumerate(rows)},
                           scope_policy_sha256="f" * 64)
    out = tmp_path / "out"
    write_jsonl(out / "expressions.jsonl", sensed.expressions, kind="expression", sort_key="expression_id")
    write_jsonl(out / "occurrences.jsonl", sensed.occurrences, kind="occurrence", sort_key="occurrence_id")
    write_jsonl(out / "groups.jsonl", sensed.groups, sort_key="group_id")
    return out


@pytest.fixture
def setup(tmp_path):
    """Implement setup."""
    rows = glossary.terms_rows(_terms_output(tmp_path))
    job = SimpleNamespace(root=tmp_path / "job", job_id="PCC_S-en")
    return job, rows, tmp_path / "lock"


def _export(rows, tmp_path) -> Path:
    """Implement export."""
    glossary.write_terms_list(rows, job_id="PCC_S-en", run_id="R1", target_language="en",
                              markdown=tmp_path / "t.md", xlsx=tmp_path / "t.xlsx")
    return tmp_path / "t.xlsx"


def _fill(xlsx: Path, fill: dict[str, tuple], facts: dict[int, str] | None = None) -> None:
    """Implement fill."""
    book = load_workbook(xlsx)
    sheet = book[glossary.TERMS_SHEET]
    for row in sheet.iter_rows(min_row=2):
        wording_sense = (row[2].value, row[4].value)
        if wording_sense in fill:
            for column, value in zip((9, 10, 11), fill[wording_sense]):
                row[column].value = value
    for index, value in (facts or {}).items():
        book[glossary.FACTS_SHEET].cell(row=index, column=2, value=value)
    book.save(xlsx)


def _lime(rows, lemma):
    """Implement lime."""
    return next(r for r in rows if r["normalized"] == "light" and r["lemma"] == lemma)


def test_rows_split_senses_and_export_md_and_xlsx(setup, tmp_path):
    """Verify that rows split senses and export md and xlsx."""
    job, rows, _ = setup
    light = [r for r in rows if r["normalized"] == "light"]
    assert {r["lemma"] for r in light} == {"βάρος", "φῶς"} and len({r["entry_id"] for r in light}) == 2
    xlsx = _export(rows, tmp_path)
    sheet = load_workbook(xlsx)[glossary.TERMS_SHEET]
    assert [c.value for c in sheet[1]] == list(glossary.COLUMNS)
    assert "light" in (tmp_path / "t.md").read_text(encoding="utf-8")
    assert glossary.terms_rows(tmp_path / "out") == rows  # stable order


def test_round_trip_creates_chained_events_and_materialized_rules(setup, tmp_path):
    """Verify that round trip creates chained events and materialized rules."""
    job, rows, lock = setup
    xlsx = _export(rows, tmp_path)
    _fill(xlsx, {("light", "βάρος"): ("Licht; !Leicht", "", "weight sense")})
    report = glossary.import_filled_list(job, xlsx, rows, lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    assert report.imported == 2 and not report.problems
    rules = glossary.current_rules(job.root)
    by_form = {r["target_form"]: r for r in rules.values()}
    assert by_form["Licht"]["effect"] == "ACCEPT" and by_form["Leicht"]["effect"] == "REJECT"
    assert all(r["state"] == "APPROVED" and r["group_id"] == _lime(rows, "βάρος")["entry_id"] for r in rules.values())
    assert len(read_journal(job.root)) == 2
    again = glossary.import_filled_list(job, xlsx, rows, lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    assert again.imported == 0 and again.unchanged == 2 and len(read_journal(job.root)) == 2


def test_malformed_rows_are_reported_with_row_numbers_and_the_rest_imports(setup, tmp_path):
    """Verify that malformed rows are reported with row numbers and the rest imports."""
    job, rows, lock = setup
    xlsx = _export(rows, tmp_path)
    _fill(xlsx, {("light", "βάρος"): ("Licht", "", ""), ("light", "φῶς"): ("Lampe", "BOOK:MAT", "")})
    book = load_workbook(xlsx)
    book[glossary.TERMS_SHEET].append(["NOPE", "TERM", "ghost", "", "", 0, 0, "", "", "x", "", ""])
    book.save(xlsx)
    report = glossary.import_filled_list(job, xlsx, rows, lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    assert report.imported == 1
    text = "\n".join(report.problems)
    assert "Terms row" in text and "BOOK:MAT" in text and "NOPE" in text
    assert [p for p in report.problems if p.startswith("Terms row")]


def test_sheet_for_another_terms_list_is_refused_whole(setup, tmp_path):
    """Verify that sheet for another terms list is refused whole."""
    job, rows, lock = setup
    xlsx = _export(rows, tmp_path)
    _fill(xlsx, {("light", "βάρος"): ("Licht", "", "")})
    report = glossary.import_filled_list(job, xlsx, rows[:-1], lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    assert report.imported == 0 and "different terms list" in report.problems[0]
    assert read_journal(job.root) == []


def test_passage_scope_and_unreadable_workbook(setup, tmp_path):
    """Verify that passage scope and unreadable workbook."""
    job, rows, lock = setup
    xlsx = _export(rows, tmp_path)
    _fill(xlsx, {("light", "βάρος"): ("Licht", "PASSAGE:MAT 1:1", "")})
    glossary.import_filled_list(job, xlsx, rows, lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    (rule,) = glossary.current_rules(job.root).values()
    assert rule["scope"] == {"level": "PASSAGE", "identifier": "MAT 1:1"}
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not a workbook")
    assert "cannot be read" in glossary.import_filled_list(job, bad, rows, lock_path=lock, source_corpus_sha256=SHA,
                                                           target_language="en").problems[0]


def test_language_facts_are_validated_and_switch_capabilities_on(setup, tmp_path):
    """Verify that language facts are validated and switch capabilities on."""
    job, rows, lock = setup
    xlsx = _export(rows, tmp_path)
    _fill(xlsx, {}, facts={2: "ta; nga", 3: "ʼʼ", 4: "k=c; broken", 5: "write joined"})
    report = glossary.import_filled_list(job, xlsx, rows, lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    facts = glossary.current_language_facts(job.root)
    assert facts["negation_markers"] == ["nga", "ta"] and facts["spelling_equivalences"] == [["c", "k"]]
    assert "apostrophe" not in facts and facts["word_break"] == "write joined"
    assert any("apostrophe" in p for p in report.problems) and any("broken" in p for p in report.problems)
    from sage.pcc.traits import capability_matrix
    caps = capability_matrix(measure_traits(["one two three"]), facts)
    assert caps["negation"] == "SUPPORTED" and caps["orthographic_equivalence"] == "SUPPORTED"


PARATEXT = """<?xml version="1.0" encoding="utf-8"?>
<TermRenderings>
  <TermRendering Id="βάρος" Guess="false"><Renderings>Licht||*ndzito||ab*cd</Renderings><Notes/></TermRendering>
  <TermRendering Id="ἄλλο"><Renderings>zzz</Renderings></TermRendering>
</TermRenderings>
"""


def test_paratext_renderings_become_proposals_until_confirmed(setup, tmp_path):
    """Verify that paratext renderings become proposals until confirmed."""
    job, rows, lock = setup
    path = tmp_path / "TermRenderings.xml"
    path.write_text(PARATEXT, encoding="utf-8")
    before = path.read_bytes()
    report = glossary.propose_from_paratext(job, path, rows, lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    assert path.read_bytes() == before
    entries = sum(1 for r in rows if r["lemma"] == "βάρος")
    assert entries >= 1 and report.imported == 2 * entries and any("ab*cd" in p for p in report.problems) and any("1 Paratext term" in p for p in report.problems)
    proposals = glossary.proposed_rules(job.root)
    assert {r["target_form"] for r in proposals} == {"Licht", "ndzito"} and len(proposals) == 2 * entries and all(r["approved_by"] is None for r in proposals)
    again = glossary.propose_from_paratext(job, path, rows, lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    assert again.imported == 0 and again.unchanged == 2 * entries
    assert glossary.decide_proposals(job, [proposals[0]["rule_id"]], approve=True, lock_path=lock, source_corpus_sha256=SHA) == 1
    assert glossary.decide_proposals(job, [proposals[1]["rule_id"]], approve=False, lock_path=lock, source_corpus_sha256=SHA) == 1
    rest = [r["rule_id"] for r in glossary.proposed_rules(job.root)]
    assert glossary.decide_proposals(job, rest, approve=True, lock_path=lock, source_corpus_sha256=SHA) == len(rest)
    states = {r["state"] for r in glossary.current_rules(job.root).values()}
    assert states == {"APPROVED", "REVOKED"} and glossary.proposed_rules(job.root) == []


def test_unsafe_or_invalid_paratext_files_are_refused(tmp_path):
    """Verify that unsafe or invalid paratext files are refused."""
    for name, body in (("a.xml", '<!DOCTYPE x [<!ENTITY e "x">]><TermRenderings/>'), ("b.xml", "<oops")):
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        with pytest.raises(ValidationError):
            glossary.read_term_renderings(path)


def test_edited_rule_record_fails_closed(setup, tmp_path):
    """Verify that edited rule record fails closed."""
    job, rows, lock = setup
    xlsx = _export(rows, tmp_path)
    _fill(xlsx, {("light", "βάρος"): ("Licht", "", "")})
    glossary.import_filled_list(job, xlsx, rows, lock_path=lock, source_corpus_sha256=SHA, target_language="en")
    record = next((job.root / "glossary" / "records").glob("*.json"))
    record.write_text(record.read_text(encoding="utf-8").replace("Licht", "Dunkel"), encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        glossary.current_rules(job.root)
    assert caught.value.code == "PCC_GLOSSARY_RECORD_TAMPERED"
