"""PCC WIP lists (PO 2026-11-26): a Job clones the master list; its changes are recorded, survive master updates and
are merged into the master only when the Operator chooses (all, chosen, or through the changes workbook).
Fabricated data only."""

from __future__ import annotations

import pytest
from openpyxl import load_workbook

from sage.errors import ValidationError
from sage.pcc import layers
from sage.pcc.reflist import ReferenceListStore
from sage.pcc.reflist_xlsx import add_wordings, export_workbook, import_workbook
from sage.pcc.rlbuild import build_context
from .test_pcc_reflist_xlsx import _edit, _entry
from .test_pcc_rlbuild import _Schema, _fixture

REF = {"project_id": "idKKH", "edition": "idKKH", "language_tag": "xx", "content_sha256": "c" * 64,
       "versification_id": "id"}
LICENSE = {"license_id": "SYNTHETIC", "local_only": True, "note": ""}
MASTER = "idkkh-list-0123abcd"


@pytest.fixture
def store(tmp_path):
    """A master list v1: lamp, wall, bread (dropped)."""
    rl = ReferenceListStore(tmp_path / "store")
    rl.save(rl_id=MASTER, title="idKKH list", reference=REF, license=LICENSE,
            build={"mode": "SCRATCH", "settings": {"min_verses": 3}},
            entries=[_entry(["GRK:50"], "lamp"), _entry(["GRK:70"], "wall"), _entry(["GRK:80"], "bread", "DROPPED")],
            created_utc="2026-11-26T00:00:00Z")
    return rl


def _labels(entries, status=None):
    """Labels of entries (optionally with one status)."""
    return sorted(e["label"] for e in entries if status is None or e["status"] == status)


def _clone(store):
    """Clone the master for a Karon Dori Job."""
    return layers.create_clone(store, MASTER, None, title="idKKH list - Karon Dori", instance_id="t",
                               created_utc="2026-11-26T01:00:00Z")


def test_a_clone_is_a_separate_list_that_records_its_changes(store, tmp_path):
    """Workbook DROP / KEEP / notes on the clone are recorded as changes; the master is untouched."""
    clone = _clone(store)
    assert layers.is_clone(clone) and clone["build"]["parent"] == {"rl_id": MASTER, "version": 1}
    assert clone["build"]["local"] == [] and clone["rl_id"] != MASTER
    path = export_workbook(store, clone["rl_id"], 1, tmp_path)
    _edit(path, {"wall": {"Status": "DROP"}, "bread": {"Status": "KEEP"}, "lamp": {"Notes": "Karon Dori: torch"}})
    result = import_workbook(store, path, report_folder=tmp_path)
    v2 = result.manifest
    assert v2["rl_id"] == clone["rl_id"] and v2["build"]["mode"] == "LOCAL" and v2["build"]["parent"]["version"] == 1
    described = sorted(layers.describe(c) for c in v2["build"]["local"])
    assert described == ["edited: lamp (notes changed)", "left out: wall", "status ACTIVE: bread"]
    assert store.versions(MASTER) == [1]
    with pytest.raises(ValidationError):
        layers.create_clone(store, clone["rl_id"], None, title="x", instance_id="t")


def test_added_wordings_are_recorded_as_additions(store, tmp_path):
    """A wording added for this WIP is an ADD change carrying the full entry."""
    units, alignment, analysis = _fixture()
    ctx = build_context(units, alignment, analysis, _Schema(), suffixes=["s"], cased=True)
    clone = _clone(store)
    result = add_wordings(store, clone["rl_id"], None, [(1, "house of bread")], report_folder=tmp_path, context=ctx,
                          origin="karon.csv")
    adds = [c for c in result.manifest["build"]["local"] if c["op"] == "ADD"]
    assert [c["label"] for c in adds] == ["house of bread"] and adds[0]["entry"]["senses"]


def test_update_from_a_newer_master_reapplies_changes_and_master_drop_wins(store, tmp_path):
    """Changes the master now has retire; a master drop wins unless the clone explicitly kept the concept."""
    clone = _clone(store)
    path = export_workbook(store, clone["rl_id"], 1, tmp_path)
    _edit(path, {"wall": {"Status": "DROP"}, "bread": {"Status": "KEEP"}}, new_rows=[{"Status": "NEW", "Wordings": "torch"}])
    import_workbook(store, path, report_folder=tmp_path)
    # the master meanwhile: drops lamp, keeps bread dropped, adds torch itself
    _, master_entries = store.load(MASTER, 1)
    by = {e["label"]: dict(e) for e in master_entries}
    by["lamp"]["status"] = "DROPPED"
    clone_v2, clone_entries = store.load(clone["rl_id"], None)
    torch = next(e for e in clone_entries if e["label"] == "torch")
    store.save(rl_id=MASTER, title="idKKH list", reference=REF, license=LICENSE, build={"mode": "MERGE"},
               entries=list(by.values()) + [torch], created_utc="2026-11-26T02:00:00Z")
    result = layers.update_clone(store, clone["rl_id"], report_folder=tmp_path)
    _, entries = store.load(clone["rl_id"], None)
    assert result.manifest["build"]["parent"]["version"] == 2
    assert _labels(entries, "DROPPED") == ["lamp", "wall"], "master drop wins for lamp; wall stays left out"
    assert "bread" in _labels(entries, "ACTIVE"), "an explicit keep survives the master's drop"
    assert any("torch" in r for r in result.retired)
    assert sorted(layers.describe(c) for c in result.manifest["build"]["local"]) == ["left out: wall", "status ACTIVE: bread"]
    assert result.report_path.is_file()
    assert layers.update_clone(store, clone["rl_id"], report_folder=tmp_path).manifest is None


def test_merge_all_chosen_and_through_the_changes_workbook(store, tmp_path):
    """Merging writes a new master version from the chosen changes only; manual edits reach the master."""
    clone = _clone(store)
    path = export_workbook(store, clone["rl_id"], 1, tmp_path)
    _edit(path, {"wall": {"Status": "DROP"}, "lamp": {"Notes": "local note"}})
    import_workbook(store, path, report_folder=tmp_path)
    changes = store.load(clone["rl_id"], None)[0]["build"]["local"]
    wall = next(c["change_id"] for c in changes if c["label"] == "wall")
    chosen = layers.merge_to_master(store, clone["rl_id"], [wall], report_folder=tmp_path)
    assert chosen.master["version"] == 2 and "wall" in _labels(store.load(MASTER, 2)[1], "DROPPED")
    assert "local note" not in [e["notes"] for e in store.load(MASTER, 2)[1]], "only the chosen change is merged"
    assert chosen.master["build"]["summary"]["merged_from_wip_list"]["rl_id"] == clone["rl_id"]
    book_path = layers.export_changes(store, clone["rl_id"], tmp_path)
    book = load_workbook(book_path)
    sheet = book["Changes"]
    header = [c.value for c in sheet[1]]
    for row in sheet.iter_rows(min_row=2):
        if row[header.index("Label")].value == "lamp":
            row[header.index("Merge")].value = "YES"
            row[header.index("Notes")].value = "edited by the Operator"
    book.save(book_path)
    clone_id, picked, edits, problems = layers.read_changes(book_path)
    assert clone_id == clone["rl_id"] and len(picked) == 1 and not problems
    manual = layers.merge_to_master(store, clone_id, picked, report_folder=tmp_path, edits=edits)
    lamp = next(e for e in store.load(MASTER, manual.master["version"])[1] if e["label"] == "lamp")
    assert lamp["notes"] == "edited by the Operator" and manual.report_path.is_file()
    unknown = layers.merge_to_master(store, clone["rl_id"], ["CHG-000000000000"], report_folder=tmp_path)
    assert unknown.master is None and any("not a current change" in n for n in unknown.notes)
