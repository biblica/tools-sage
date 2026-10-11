"""Versification-aware linking of index sources (numbers/index_build/versify.py)."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from sage.numbers.index_build.versify import Linker
from sage.vrs import parse_vrs_file


def _linker(package_root: Path) -> Linker:
    """The linker over SAGE's standard eng.vrs."""
    return Linker(package_root / "system/resources/scripture")


def test_original_language_numbering_maps_to_western(package_root):
    """org-numbered verses move to their English coordinates; superscriptions become verse 0."""
    link = _linker(package_root)
    assert [link.ol_to_western(ref) for ref in ("JOL 3:1", "MAL 3:19", "PSA 60:2", "1KI 5:1", "NEH 3:33")] == [
        "JOL 2:28", "MAL 4:1", "PSA 60:0", "1KI 4:21", "NEH 4:1"]
    assert link.western_to_ol("PSA 60:0") == ("PSA 60:1", "PSA 60:2")


def test_english_numbered_sources_keep_their_label_where_eng_vrs_has_it(package_root):
    """NIV/NET labels are already English-numbered, so an eng.vrs verse keeps its label."""
    link = _linker(package_root)
    assert [link.english_to_western(ref) for ref in ("NEH 7:68", "ISA 64:1", "MAL 4:6")] == [
        "NEH 7:68", "ISA 64:1", "MAL 4:6"]


def test_package_mapping_rules_agree_with_eng_vrs(package_root):
    """The runtime package's Western mapping is eng.vrs for the 66 books (one known ACT 19:40 span)."""
    from sage.canon import NT_27, OT_39
    canon = set(OT_39) | set(NT_27)
    pin = json.loads((package_root / "system/config/numbers-reference.json").read_text(encoding="utf-8"))
    package = parse_vrs_file(package_root / pin["path"] / "reference/eng_org_map_rules.txt", schema_id="pkg",
                             canonical_id="org")
    eng = parse_vrs_file(package_root / "system/resources/scripture/eng.vrs", schema_id="eng", canonical_id="org")

    def rules(schema):
        """Canon-book mapping rules as labels."""
        return {(item.local.label(), item.canonical.label()) for item in schema.mappings
                if item.local.start.book in canon}
    assert rules(package) <= rules(eng)
    assert rules(eng) - rules(package) == {("ACT 19:40-41", "ACT 19:40")}


def test_every_indexed_verse_is_a_western_verse_and_ol_refs_link_back(package_root):
    """All index rows are eng.vrs coordinates, and every OL reference links to its own Western row."""
    link = _linker(package_root)
    pin = json.loads((package_root / "system/config/numbers-reference.json").read_text(encoding="utf-8"))
    with (package_root / pin["path"] / "reference/verses.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert all(link.in_western(row["WESTERN_REF"]) for row in rows)
    assert all(link.ol_to_western(ref) == row["WESTERN_REF"]
               for row in rows for ref in re.findall(r"[1-3A-Z]{3} \d+:\d+", row["OL_REFS"]))
