"""PCC P5b-6: reference lists move between SAGE instances as one checksummed .sagerl.zip; glossary bundles match
renderings by concept group. Fabricated data only."""

from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

import pytest

from sage.errors import ValidationError
from sage.pcc import glossary, layers, rlexchange, transfer
from sage.pcc.reflist import ReferenceListStore
from sage.pcc.reflist_xlsx import export_workbook, import_workbook
from .test_pcc_reflist_xlsx import _edit, _entry

REF = {"project_id": "idKKH", "edition": "idKKH", "language_tag": "xx", "content_sha256": "c" * 64,
       "versification_id": "id"}
MASTER = "idkkh-list-0123abcd"


def _master(store, local_only=False):
    """A master list v1 on one instance."""
    return store.save(rl_id=MASTER, title="idKKH list", reference=REF,
                      license={"license_id": "SYNTHETIC", "local_only": local_only, "note": ""},
                      build={"mode": "SCRATCH", "settings": {"min_verses": 3}},
                      entries=[_entry(["GRK:50"], "lamp"), _entry(["GRK:70"], "wall")],
                      created_utc="2026-11-26T00:00:00Z")


def test_a_master_moves_to_another_instance_byte_for_byte(tmp_path):
    """Export on instance A, import on instance B: same package; a second import keeps it; export is reproducible."""
    a, b = ReferenceListStore(tmp_path / "a"), ReferenceListStore(tmp_path / "b")
    _master(a)
    path, index = rlexchange.export_list(a, MASTER, None, tmp_path / "out")
    assert path.name == f"{MASTER}-v1.sagerl.zip" and index["kind"] == "MASTER" and not index["local_only"]
    first = path.read_bytes()
    assert rlexchange.export_list(a, MASTER, None, tmp_path / "out")[0].read_bytes() == first
    result = rlexchange.import_list(b, path)
    assert result.stored == [(MASTER, 1, "imported")] and result.main["rl_id"] == MASTER
    assert (b.path(MASTER, 1) / "CHECKSUMS.sha256").read_bytes() == (a.path(MASTER, 1) / "CHECKSUMS.sha256").read_bytes()
    assert rlexchange.import_list(b, path).stored == [(MASTER, 1, "kept")]


def test_a_wip_list_travels_with_its_master_and_still_merges(tmp_path):
    """A WIP list package carries its master version; on the other SAGE it can merge into that master."""
    a, b = ReferenceListStore(tmp_path / "a"), ReferenceListStore(tmp_path / "b")
    _master(a, local_only=True)
    clone = layers.create_clone(a, MASTER, None, title="idKKH list - Karon Dori", instance_id="a")
    wb = export_workbook(a, clone["rl_id"], 1, tmp_path)
    _edit(wb, {"wall": {"Status": "DROP"}})
    import_workbook(a, wb, report_folder=tmp_path)
    path, index = rlexchange.export_list(a, clone["rl_id"], None, tmp_path / "out")
    assert index["kind"] == "WIP_LIST" and [p["rl_id"] for p in index["packages"]] == [MASTER, clone["rl_id"]]
    result = rlexchange.import_list(b, path)
    assert [s[2] for s in result.stored] == ["imported", "imported"] and any("local only" in n for n in result.notes)
    merged = layers.merge_to_master(b, clone["rl_id"], None, report_folder=tmp_path)
    assert merged.master["version"] == 2


def test_a_different_list_under_the_same_id_is_forked_never_overwritten(tmp_path):
    """Same id and version with other content: stored under a new id; the receiving list stays as it was."""
    a, b = ReferenceListStore(tmp_path / "a"), ReferenceListStore(tmp_path / "b")
    _master(a)
    b.save(rl_id=MASTER, title="idKKH list", reference=REF,
           license={"license_id": "SYNTHETIC", "local_only": False, "note": ""}, build={"mode": "SCRATCH"},
           entries=[_entry(["GRK:50"], "lamp")], created_utc="2026-11-26T00:00:00Z")
    before = (b.path(MASTER, 1) / "CHECKSUMS.sha256").read_bytes()
    result = rlexchange.import_list(b, rlexchange.export_list(a, MASTER, None, tmp_path / "out")[0])
    assert result.stored[0][2] == "forked" and result.stored[0][0] != MASTER
    assert (b.path(MASTER, 1) / "CHECKSUMS.sha256").read_bytes() == before


def _rewrite(path, target, change):
    """Copy a package, changing one member."""
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(target, "w") as out:
        for info in source.infolist():
            data = source.read(info.filename)
            out.writestr(info.filename, change(info.filename, data))
    return target


def test_tampered_or_unsafe_packages_are_refused(tmp_path):
    """A changed index, a changed list, an unexpected member or a non-zip is refused before anything is stored."""
    a, b = ReferenceListStore(tmp_path / "a"), ReferenceListStore(tmp_path / "b")
    _master(a)
    path, _ = rlexchange.export_list(a, MASTER, None, tmp_path / "out")
    index_changed = _rewrite(path, tmp_path / "i.zip", lambda n, d: d.replace(b'"MASTER"', b'"WIP_LIST"')
                             if n == "SAGERL.json" else d)
    entries_changed = _rewrite(path, tmp_path / "e.zip", lambda n, d: d.replace(b"lamp", b"lamb")
                               if n.endswith("entries.jsonl") else d)
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(tmp_path / "u.zip", "w") as out:
        for info in source.infolist():
            out.writestr(info.filename, source.read(info.filename))
        out.writestr("../evil.txt", b"x")
    (tmp_path / "n.zip").write_text("not a zip", encoding="utf-8")
    for bad in (index_changed, entries_changed, tmp_path / "u.zip", tmp_path / "n.zip"):
        with pytest.raises(ValidationError) as caught:
            rlexchange.import_list(b, bad)
        assert caught.value.code == "PCC_RL_PACKAGE_INVALID"
    assert b.lists() == []
    index = json.loads(zipfile.ZipFile(path).read("SAGERL.json"))
    assert index["format"] == "SAGE-PCC-REFERENCE-LIST" and len(index["index_sha256"]) == 64


def test_glossary_bundle_matches_renderings_by_concept_group_first(tmp_path):
    """A rendering whose wording differs in the receiving Job still lands on the same concept + sense group."""
    rows = [{"entry_id": "GRP-1", "wording": "pelita", "lemma": "", "category": "KEY_TERM", "sense": "", "occurrences": 2}]
    job = SimpleNamespace(root=tmp_path / "job", job_id="PCC_T-xx")
    report = glossary.ImportReport()
    matched = transfer._propose(job, tmp_path / "lock", "a" * 64, "xx", rows, "lamp", "", "suluh", "ACCEPT", "why",
                                "BUNDLE:x", report, {}, "operator", "GRP-1")
    assert matched and report.imported == 1
    assert [r["group_id"] for r in glossary.current_rules(job.root).values()] == ["GRP-1"]
    assert not transfer._propose(job, tmp_path / "lock", "a" * 64, "xx", rows, "lamp", "", "x", "ACCEPT", "why",
                                 "BUNDLE:x", glossary.ImportReport(), {}, "operator", "GRP-2")
