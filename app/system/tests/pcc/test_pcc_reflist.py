"""PCC P5b-1: concept keys (D13) and reference-list packages and store (D12). Fabricated data only."""

from __future__ import annotations

import json

import pytest

from sage.errors import ValidationError
from sage.pcc.ids import concept_key, group_id, sense_key
from sage.pcc.reflist import (CHECKSUMS, ENTRIES, MANIFEST, ReferenceListStore, new_rl_id, verify_reference_list,
                              write_reference_list)

REFERENCE = {"project_id": "SYN", "edition": "Synthetic 1", "language_tag": "en", "content_sha256": "c" * 64,
             "versification_id": "eng"}
LICENSE = {"license_id": "SYNTHETIC-PUBLIC-DOMAIN", "local_only": False, "note": ""}
CREATED = "2026-11-25T00:00:00Z"


def _entry(keys, label, status="ACTIVE", wording="lamp"):
    """One fabricated concept entry."""
    concept = concept_key("OL", keys)
    return {"concept_key": concept, "anchor": {"kind": "OL", "value": sorted(keys)}, "label": label,
            "category": "KEY_TERM", "status": status, "origin": "KEY_CONCEPTS", "sources": ["KEY_CONCEPTS"],
            "senses": [{"sense_key": sense_key(concept, wording), "kind": "SENSE", "label": wording,
                        "wordings": [{"wording": wording, "verses": 3}], "verses": 3, "examples": ["GEN 1:1"],
                        "ol_senses": ["1"], "state": "PROPOSED"}],
            "realization": {"occurrences": 3, "realized": 3, "function_only": 0, "no_realization": 0, "gold": 3,
                            "transitive": 0, "direct": 0, "located": 0},
            "verses": 3, "examples": ["GEN 1:1"], "notes": ""}


ENTRIES_IN = [_entry(["GRK:1"], "one"), _entry(["GRK:3", "GRK:2"], "two-three", "PROPOSED"),
              _entry(["HEB:9"], "nine", "DROPPED")]


def _write(path, entries=ENTRIES_IN, **kw):
    """Write one fabricated package."""
    args = dict(rl_id="syn-list-0123abcd", version=1, title="Syn list", reference=REFERENCE, license=LICENSE,
                build={"mode": "SCRATCH"}, entries=entries, created_utc=CREATED)
    args.update(kw)
    return write_reference_list(path, **args)


def test_concept_key_is_language_neutral_order_free_and_scope_free():
    """OL anchors ignore order and duplicates; kinds stay apart; group ids depend on concept and sense only."""
    assert concept_key("OL", ["GRK:166", "GRK:2222"]) == concept_key("OL", ["GRK:2222", "GRK:166", "GRK:166"])
    assert concept_key("OL", ["GRK:166"]) != concept_key("BT", "GRK:166")
    assert concept_key("WORDING", "en|stand firm").startswith("CPT-")
    concept = concept_key("OL", ["GRK:2453"])
    assert group_id(concept, sense_key(concept, "jews")) != group_id(concept, sense_key(concept, "jewish leaders"))
    with pytest.raises(ValidationError):
        concept_key("LEMMA", ["x"])
    with pytest.raises(ValidationError):
        concept_key("OL", [])


def test_package_is_deterministic_and_verifies(tmp_path):
    """Same inputs give byte-identical files; counts follow the statuses; entries are sorted by key."""
    manifest = _write(tmp_path / "a")
    _write(tmp_path / "b", entries=list(reversed(ENTRIES_IN)))
    for name in (ENTRIES, MANIFEST, CHECKSUMS):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert manifest["counts"] == {"entries": 3, "active": 1, "proposed": 1, "dropped": 1}
    assert verify_reference_list(tmp_path / "a")["rl_id"] == "syn-list-0123abcd"


def test_tampered_or_invalid_packages_are_refused(tmp_path):
    """An edited file fails verification; a duplicate concept, a bad entry or a used folder are refused."""
    _write(tmp_path / "a")
    (tmp_path / "a" / ENTRIES).write_text((tmp_path / "a" / ENTRIES).read_text(encoding="utf-8").replace("one", "uno"),
                                          encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        verify_reference_list(tmp_path / "a")
    assert caught.value.code == "PCC_RL_INTEGRITY"
    with pytest.raises(ValidationError) as caught:
        _write(tmp_path / "b", entries=[ENTRIES_IN[0], ENTRIES_IN[0]])
    assert caught.value.code == "PCC_RL_DUPLICATE"
    with pytest.raises(ValidationError):
        _write(tmp_path / "c", entries=[{**ENTRIES_IN[0], "status": "MAYBE"}])
    with pytest.raises(ValidationError) as caught:
        _write(tmp_path / "a")
    assert caught.value.code == "PCC_RL_EXISTS"


def test_new_rl_id_is_a_slug_plus_instance_hash():
    """Ids are readable, valid and differ per instance."""
    first = new_rl_id("NIV 2011 — key terms!", "instance-a", CREATED)
    assert first.startswith("niv-2011-key-terms-") and len(first.rsplit("-", 1)[1]) == 8
    assert first != new_rl_id("NIV 2011 — key terms!", "instance-b", CREATED)


def test_store_versions_lists_loads_and_imports_without_overwriting(tmp_path):
    """Each save is a new version; import keeps identical packages and forks a different one."""
    store = ReferenceListStore(tmp_path / "resources")
    rl = "syn-list-0123abcd"
    common = dict(title="Syn list", reference=REFERENCE, license=LICENSE, created_utc=CREATED)
    store.save(rl_id=rl, build={"mode": "SCRATCH"}, entries=ENTRIES_IN, **common)
    second = store.save(rl_id=rl, build={"mode": "MERGE"}, entries=ENTRIES_IN[:2], **common)
    assert store.versions(rl) == [1, 2] and second["build"]["base_version"] == 1
    manifest, entries = store.load(rl)
    assert manifest["version"] == 2 and len(entries) == 2
    assert [m["rl_id"] for m in store.lists()] == [rl]

    other = ReferenceListStore(tmp_path / "elsewhere")
    assert other.import_package(store.path(rl, 1))[1] == "imported"
    assert other.import_package(store.path(rl, 1))[1] == "kept"
    _write(tmp_path / "clash", rl_id=rl, version=1, entries=ENTRIES_IN[:1])
    forked, how = other.import_package(tmp_path / "clash")
    assert how == "forked" and forked["rl_id"] != rl
    assert forked["build"]["imported_from"] == {"rl_id": rl, "version": 1}
    assert other.load(rl, 1)[0]["counts"]["entries"] == 3
    with pytest.raises(ValidationError):
        other.load(rl, 7)


def test_manifest_records_license_and_lineage(tmp_path):
    """The license flag and lineage fields are part of the manifest contract."""
    manifest = _write(tmp_path / "a", license={"license_id": "NIV", "local_only": True, "note": "NIV-derived"},
                      build={"mode": "INHERIT", "derived_from": {"rl_id": "bsb-key-concepts-89abcdef", "version": 3}})
    stored = json.loads((tmp_path / "a" / MANIFEST).read_text(encoding="utf-8"))
    assert stored["license"]["local_only"] is True
    assert stored["build"]["derived_from"] == {"rl_id": "bsb-key-concepts-89abcdef", "version": 3}
    assert manifest == stored
