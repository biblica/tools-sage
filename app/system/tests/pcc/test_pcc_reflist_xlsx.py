"""PCC P5b-4: reference-list workbook export -> edit -> import as a new version. Fabricated data only."""

from __future__ import annotations

import pytest
from openpyxl import load_workbook

from sage.errors import ValidationError
from sage.pcc.reflist import ReferenceListStore
from sage.pcc.reflist_xlsx import export_workbook, import_workbook
from .test_pcc_rlbuild import _Schema, _fixture

from sage.pcc.ids import concept_key, sense_key
from sage.pcc.rlbuild import build_context


def _entry(keys, label, status="ACTIVE"):
    """One fabricated entry."""
    concept = concept_key("OL", keys)
    return {"concept_key": concept, "anchor": {"kind": "OL", "value": sorted(keys)}, "label": label,
            "category": "RE", "status": status, "origin": "BIBLICAL_TERMS", "sources": ["BT:x"],
            "senses": [{"sense_key": sense_key(concept, "x|LOWER"), "kind": "SENSE", "label": label,
                        "wordings": [{"wording": label, "verses": 3}], "verses": 3, "examples": ["MAT 1:1"],
                        "ol_senses": [], "state": "PROPOSED"}],
            "realization": {k: 0 for k in ("occurrences", "realized", "function_only", "no_realization", "gold",
                                           "transitive", "direct", "located")},
            "verses": 3, "examples": ["MAT 1:1"], "notes": ""}


@pytest.fixture
def store(tmp_path):
    """A store with one fabricated list version."""
    rl = ReferenceListStore(tmp_path / "store")
    rl.save(rl_id="syn-list-0123abcd", title="Syn", reference={"project_id": "SYN", "edition": "SYN", "language_tag": "xx",
                                                                "content_sha256": "c" * 64, "versification_id": "id"},
            license={"license_id": "SYNTHETIC", "local_only": False, "note": ""},
            build={"mode": "SCRATCH", "settings": {"min_verses": 3}},
            entries=[_entry(["GRK:50"], "lamp"), _entry(["GRK:60"], "=SUM(A1)", "PROPOSED"), _entry(["GRK:70"], "wall")],
            created_utc="2026-11-25T00:00:00Z")
    return rl


def _edit(path, changes, new_rows=()):
    """Set Status/Notes by label and append NEW rows."""
    book = load_workbook(path)
    sheet = book["Entries"]
    header = [c.value for c in sheet[1]]
    for row in sheet.iter_rows(min_row=2):
        label = row[header.index("Label")].value
        for column, value in changes.get(label, {}).items():
            row[header.index(column)].value = value
    for values in new_rows:
        sheet.append([values.get(name, "") for name in header])
    book.save(path)


def test_round_trip_writes_a_new_version_and_a_diff(store, tmp_path):
    """KEEP / DROP / notes apply by key; bad rows are reported by number; the base version never changes."""
    path = export_workbook(store, "syn-list-0123abcd", 1, tmp_path / "out")
    cells = [c.value for c in load_workbook(path)["Entries"]["B"]]
    assert "'=SUM(A1)" in cells and path.name == "RL-syn-list-0123abcd-v1.xlsx"
    _edit(path, {"lamp": {"Status": "DROP"}, "'=SUM(A1)": {"Status": "KEEP", "Notes": "team term"},
                 "wall": {"Status": "MAYBE"}},
          new_rows=[{"Concept key": "CPT-ffffffffffffffff", "Status": "KEEP"}, {"Status": "", "Wordings": "x"}])
    result = import_workbook(store, path, report_folder=tmp_path / "reports", created_utc="2026-11-26T00:00:00Z")
    assert result.manifest["version"] == 2 and result.manifest["build"]["base_version"] == 1
    _, entries = store.load("syn-list-0123abcd", 2)
    status = {e["label"]: (e["status"], e["notes"]) for e in entries}
    assert status == {"lamp": ("DROPPED", ""), "=SUM(A1)": ("ACTIVE", "team term"), "wall": ("ACTIVE", "")}
    assert [p.split(":")[0] for p in result.problems] == ["row 4", "row 5", "row 6"]
    assert result.diff_path.is_file() and "lamp" in result.diff_path.read_text(encoding="utf-8")
    assert store.load("syn-list-0123abcd", 1)[1][0]["status"] in ("ACTIVE", "PROPOSED", "DROPPED")


def test_unchanged_workbook_writes_no_version_and_foreign_workbooks_are_refused(store, tmp_path):
    """No edit -> no new version; a workbook naming a version this instance lacks is refused."""
    path = export_workbook(store, "syn-list-0123abcd", None, tmp_path)
    assert import_workbook(store, path, report_folder=tmp_path).manifest is None
    book = load_workbook(path)
    book["About"]["B2"].value = 9
    book.save(path)
    with pytest.raises(ValidationError) as caught:
        import_workbook(store, path, report_folder=tmp_path)
    assert caught.value.code == "PCC_RL_WORKBOOK_BASE_MISSING"


def test_new_rows_are_located_in_the_reference_text(tmp_path):
    """A NEW wording is anchored and realized when the reference text is given; an absent one is kept and reported."""
    units, alignment, analysis = _fixture()

    ctx = build_context(units, alignment, analysis, _Schema(), suffixes=["s"], cased=True)
    rl = ReferenceListStore(tmp_path / "store")
    rl.save(rl_id="syn-list-0123abcd", title="Syn", reference={"project_id": "SYN", "edition": "SYN", "language_tag": "xx",
                                                                "content_sha256": "c" * 64, "versification_id": "id"},
            license={"license_id": "SYNTHETIC", "local_only": False, "note": ""},
            build={"mode": "SCRATCH", "settings": {"min_verses": 3}}, entries=[_entry(["GRK:50"], "lamp")],
            created_utc="2026-11-25T00:00:00Z")
    path = export_workbook(rl, "syn-list-0123abcd", 1, tmp_path)
    _edit(path, {}, new_rows=[{"Status": "NEW", "Wordings": "house of bread"}, {"Status": "NEW", "Wordings": "silver lamp"}])
    result = import_workbook(rl, path, report_folder=tmp_path, context=ctx)
    _, entries = rl.load("syn-list-0123abcd", 2)
    house = next(e for e in entries if e["label"] == "house of bread")
    assert house["anchor"] == {"kind": "OL", "value": ["GRK:10", "GRK:11"]} and house["senses"][0]["verses"] == 3
    assert next(e for e in entries if e["label"] == "silver lamp")["senses"] == []
    assert any("silver lamp" in p for p in result.problems) and result.added == ["house of bread", "silver lamp"]
