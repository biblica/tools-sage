"""PCC shared reference lists (PO 2026-11-26): lists live outside Jobs, are built from other lists, and take the
Operator's own wordings as new versions. Fabricated data only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sage.pcc import rlservice, transfer
from sage.pcc.phrases import job_phrase_lines, retire_job_phrases
from sage.pcc.reflist import ReferenceListStore
from sage.pcc.reflist_xlsx import add_wordings, compare_versions
from sage.pcc.rlbuild import build_context
from .test_pcc_reflist_xlsx import _entry
from .test_pcc_rlbuild import _Schema, _fixture

REF = {"project_id": "BASE", "edition": "BASE", "language_tag": "en", "content_sha256": "c" * 64,
       "versification_id": "id"}
LICENSE = {"license_id": "SYNTHETIC", "local_only": True, "note": ""}


def _wording_entry(label, language="en"):
    """An Operator wording without an original-language key."""
    entry = _entry(["GRK:99"], label)
    from sage.pcc.ids import concept_key
    entry["anchor"] = {"kind": "WORDING", "value": [f"{language}|{label}"]}
    entry["concept_key"] = concept_key("WORDING", f"{language}|{label}")
    entry["origin"] = "DECLARED"
    return entry


@pytest.fixture
def fake_text(monkeypatch):
    """Replace reading and aligning a reference text by the four fabricated verses."""
    units, alignment, analysis = _fixture()
    analysis.package_id = "SYN-OL"
    monkeypatch.setattr(rlservice, "load_ol_analysis", lambda root: analysis)
    monkeypatch.setattr(rlservice, "load_pcc_ol", lambda root: None)
    monkeypatch.setattr(rlservice, "reference_units", lambda path, books=None: units)
    monkeypatch.setattr(rlservice, "cached_alignment", lambda *a, **k: (alignment, True))
    monkeypatch.setattr(rlservice, "source_content_sha256", lambda path: "d" * 64)
    return units, alignment, analysis


def _build(store, tmp_path, project_id, base=None, language="en"):
    """Build through the service on the fabricated text."""
    return rlservice.build_reference_list_for(
        app_root=tmp_path, store=store, cache_root=tmp_path / "cache", reference_path=tmp_path / project_id,
        project_id=project_id, title=f"{project_id} list", language_tag=language, schema=_Schema(),
        versification_id="id", base=base, instance_id="test")


def test_a_list_built_from_another_text_is_a_new_list_with_proposed_concepts(fake_text, tmp_path):
    """usNIV -> NVI: a new rl_id; kept concepts arrive PROPOSED; drops stay out; foreign Operator wordings reported."""
    store = ReferenceListStore(tmp_path / "store")
    base = store.save(rl_id="base-list-0123abcd", title="Base", reference=REF, license=LICENSE,
                      build={"mode": "SCRATCH", "settings": {"min_verses": 3}},
                      entries=[_entry(["GRK:50"], "lamp"), _entry(["GRK:10", "GRK:11"], "house of bread", "DROPPED"),
                               _wording_entry("bread of life", "es")], created_utc="2026-11-25T00:00:00Z")
    outcome = _build(store, tmp_path, "OTHER", base=(base["rl_id"], None), language="xx")
    manifest = outcome.manifest
    assert manifest["rl_id"] != base["rl_id"] and manifest["version"] == 1
    assert manifest["build"]["mode"] == "INHERIT" and manifest["build"]["derived_from"] == {"rl_id": base["rl_id"], "version": 1}
    _, entries = store.load(manifest["rl_id"], 1)
    lamp = next(e for e in entries if e["label"] == "lamp")
    assert lamp["status"] == "PROPOSED" and lamp["senses"]
    assert all(e["label"] != "house of bread" for e in entries)
    carried = outcome.report["inherited"]
    assert carried["dropped"] == 1 and carried["wordings_other_language"] == ["bread of life"]
    assert store.versions(base["rl_id"]) == [1], "the base list is never changed"


def test_rebuilding_the_same_text_is_the_next_version_and_keeps_statuses(fake_text, tmp_path):
    """Same reference text: same rl_id, next version, ACTIVE stays ACTIVE."""
    store = ReferenceListStore(tmp_path / "store")
    base = store.save(rl_id="base-list-0123abcd", title="Base", reference=REF, license=LICENSE,
                      build={"mode": "SCRATCH", "settings": {"min_verses": 3}}, entries=[_entry(["GRK:50"], "lamp")],
                      created_utc="2026-11-25T00:00:00Z")
    manifest = _build(store, tmp_path, "BASE", base=(base["rl_id"], None)).manifest
    assert (manifest["rl_id"], manifest["version"]) == (base["rl_id"], 2)
    assert [e["status"] for e in store.load(base["rl_id"], 2)[1]] == ["ACTIVE"]


def test_operator_wordings_become_a_new_version_and_versions_compare(tmp_path):
    """Wordings are located in the text; a dropped one comes back; nothing new writes no version."""
    units, alignment, analysis = _fixture()
    ctx = build_context(units, alignment, analysis, _Schema(), suffixes=["s"], cased=True)
    store = ReferenceListStore(tmp_path / "store")
    store.save(rl_id="syn-list-0123abcd", title="Syn", reference={**REF, "language_tag": "xx"}, license=LICENSE,
               build={"mode": "SCRATCH", "settings": {"min_verses": 3}},
               entries=[_entry(["GRK:50"], "lamp"), _entry(["GRK:70"], "wall", "DROPPED")],
               created_utc="2026-11-25T00:00:00Z")
    result = add_wordings(store, "syn-list-0123abcd", None, [(1, "house of bread"), (2, "!!!"), (3, "lamp")],
                          report_folder=tmp_path / "r", context=ctx, origin="mine.csv")
    assert result.manifest["version"] == 2 and result.added == ["house of bread"]
    assert any("line 2" in p for p in result.problems) and any("already on the list" in p for p in result.problems)
    assert result.manifest["build"]["summary"]["operator_wordings"]["added"] == 1
    again = add_wordings(store, "syn-list-0123abcd", None, [(1, "house of bread")], report_folder=tmp_path / "r",
                         context=ctx, origin="mine.csv")
    assert again.manifest is None and store.versions("syn-list-0123abcd") == [1, 2]
    compared, path = compare_versions(store, "syn-list-0123abcd", 1, 2, report_folder=tmp_path / "r")
    assert compared.added == ["house of bread"] and path.is_file() and "## Added (1)" in path.read_text(encoding="utf-8")


def test_glossary_imports_return_missing_wordings_instead_of_writing_the_job(tmp_path):
    """An Operator list never writes phrases.txt; unknown SOURCE wordings come back for the reference list."""
    rows = [{"entry_id": "G1", "wording": "light", "lemma": "", "category": "KEY_TERM", "sense": "", "occurrences": 1}]
    mine = tmp_path / "mine.csv"
    mine.write_text("wording,rendering\nlight,Lampe\nnothing here,x\nnothing here,y\n", encoding="utf-8")
    job = SimpleNamespace(root=tmp_path / "job", job_id="PCC_T-en")
    report = transfer.import_operator_list(job, mine, rows, lock_path=tmp_path / "lock", source_corpus_sha256="a" * 64,
                                           target_language="en")
    assert report.missing_wordings == [(3, "nothing here")]
    assert not (job.root / "input" / "phrases.txt").exists()


def test_old_job_phrases_are_read_and_retired_not_deleted(tmp_path):
    """phrases.txt of an older Job: lines are read for the move, then the file is renamed and kept."""
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "phrases.txt").write_text("# team\nbread of life\n\nSon of Man\n", encoding="utf-8")
    assert job_phrase_lines(tmp_path) == [(2, "bread of life"), (4, "Son of Man")]
    kept = retire_job_phrases(tmp_path, "20261126")
    assert kept.name == "phrases.moved-20261126.txt" and kept.is_file() and job_phrase_lines(tmp_path) == []
