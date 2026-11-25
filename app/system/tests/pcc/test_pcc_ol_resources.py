"""PCC original-language resource package (plan §5b.7, D19, D20): build, map, verify, load.

All inputs are fabricated (placeholder words, no Scripture text). One test checks the shipped package's
integrity and manifest only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.pcc import ol_build, ol_resources
from sage.pcc.ol_build import (BSB_ALIGNMENT, OL_GROUPS, OL_SENSES, TableWord, align_table, build_package,
                               extract_groups, git_blob_sha, listing_digest, read_macula, table_words)

APP_ROOT = Path(__file__).resolve().parents[3]
HEADER = ["Heb Sort", "Greek Sort", "BSB Sort", "Verse", "Language", "WLC / Nestle Base TR RP WH NE NA SBL",
          "WLC / Nestle Base {TR}", "Translit", "Parsing", "Parsing", "Str Heb", "Str Grk", "VerseId", "Hdg",
          "Crossref", "Par", "Space", "begQ", " BSB version ", "pnc", "endQ", "footnotes"]


def _row(heb=0, grk=0, bsb=0, lang="Greek", text="xa", sh="", sg="", verse="", english="", pnc=""):
    """One fabricated BSB table row in the real column layout."""
    row = [None] * len(HEADER)
    row[0], row[1], row[2], row[4], row[5] = heb, grk, bsb, lang, text
    row[10], row[11], row[12], row[18], row[19] = sh, sg, verse, english, pnc
    return row


LOWFAT = b"""<book><sentence><wg class="cl" rule="S-V">
  <wg class="np" rule="DetNP" role="s"><w ref="MAT 1:1!1" ln="1.1" domain="000001">qa</w>
    <w ref="MAT 1:1!2" ln="2.2" domain="000002">qb</w></wg>
  <w ref="MAT 1:1!3">qc</w>
  <wg class="np" rule="Np"><w ref="MAT 1:1!4">qd</w></wg>
  <wg class="pp" Rule="PrepNp"><w ref="MAT 1:1!5">qe</w><w ref="MAT 1:1!5">qf</w><w ref="MAT 1:1!6">qg</w></wg>
</wg></sentence></book>"""


def test_groups_read_structure_only():
    """Phrase groups keep class/rule/role/refs; clauses and one-word groups are out; segments merge by ref."""
    groups = extract_groups(LOWFAT)
    assert groups == [("np", "DetNP", "s", ("MAT 1:1!1", "MAT 1:1!2")),
                      ("pp", "PrepNp", "", ("MAT 1:1!5", "MAT 1:1!6"))]
    assert "000001" not in repr(groups) and "1.1" not in repr(groups)


def test_table_words_carry_verse_rank_english_and_skip_untranslated():
    """VerseId carries forward; BSB order ranks rendered chunks only; Aramaic counts as HEB."""
    rows = [HEADER,
            _row(heb=2, bsb=1, lang="Hebrew", text="ha", sh="10", verse="Genesis 1:1", english=" Alpha "),
            _row(heb=1, bsb=3, lang="Hebrew", text="hb", sh="20", english=" beta ", pnc="."),
            _row(heb=3, bsb=2, lang="Aramaic", text="hc", sh="H0030b", english=" - "),
            _row(heb=4, bsb=4, lang="z", text="", english=""),
            _row(grk=1, bsb=5, lang="Greek", text="ga", sg="7", verse="Matthew 2:3", english=" gamma ")]
    words = table_words(rows)
    assert [(w.family, w.bsb_ref, w.bsb_order, w.english, w.strong) for w in words] == [
        ("HEB", "GEN 1:1", 1, "Alpha", "10"), ("HEB", "GEN 1:1", 2, "beta", "20"), ("HEB", "GEN 1:1", 0, "-", "30"),
        ("GRK", "MAT 2:3", 1, "gamma", "7")]


def _tw(sort, strong, english):
    """A fabricated table word in MAT."""
    return TableWord("GRK", "MAT", sort, strong, "MAT 1:1", sort, english, "")


def test_align_pairs_by_strong_fills_short_equal_gaps_and_leaves_text_differences():
    """Anchors pair by Strong's; a 1-word equal gap pairs by position; an extra table word stays unpaired."""
    table = [_tw(1, "1", "a"), _tw(2, "99", "b"), _tw(3, "3", "c"), _tw(4, "50", "extra"), _tw(5, "4", "d")]
    macula = [("MAT 1:1!1", "1"), ("MAT 1:1!2", "2"), ("MAT 1:1!3", "3"), ("MAT 1:1!4", "4")]
    pairs, stats = align_table(table, macula)
    assert [(ref, w.english, how) for ref, w, how in sorted(pairs, key=lambda p: p[0])] == [
        ("MAT 1:1!1", "a", "strong"), ("MAT 1:1!2", "b", "position"), ("MAT 1:1!3", "c", "strong"),
        ("MAT 1:1!4", "d", "strong")]
    assert stats == {"table_words": 5, "macula_words": 4, "paired_by_strong": 3, "paired_by_position": 1}


def test_hebrew_segments_group_into_words_with_content_strong_and_senses():
    """Segments sharing a ref form one word; the content segment gives the Strong's; senses keep the segment."""
    rows = [{"xml:id": "o1", "ref": "GEN 1:1!1", "strongnumberx": "0871a", "pos": "preposition", "lemma": "p",
             "sensenumber": ""},
            {"xml:id": "o2", "ref": "GEN 1:1!1", "strongnumberx": "7225", "pos": "noun", "lemma": "n", "sensenumber": "2"},
            {"xml:id": "o3", "ref": "GEN 1:1!2", "strongnumberx": "0853", "pos": "particle", "lemma": "m",
             "sensenumber": ""}]
    family = read_macula(rows, "HEB")
    assert family.words == [("GEN 1:1!1", "7225"), ("GEN 1:1!2", "853")]
    assert family.senses == [("GEN 1:1!1", 1, "n", "2")]
    assert family.by_id["o3"] == ("GEN 1:1!2", 0, "m")


def _tsv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a fabricated TSV."""
    columns = list(rows[0])
    path.write_text("\t".join(columns) + "\n" + "".join("\t".join(r[c] for c in columns) + "\n" for r in rows),
                    encoding="utf-8")


def _cache(tmp: Path) -> tuple[Path, dict, dict]:
    """A fabricated SAGE cache with every input, and the pins that match it."""
    import openpyxl
    cache = tmp / "cache"
    (cache / "macula" / "lowfat-greek").mkdir(parents=True)
    (cache / "macula" / "lowfat-hebrew").mkdir(parents=True)
    (cache / "witnesses" / "bsb-tables").mkdir(parents=True)
    _tsv(cache / "macula" / "g.tsv", [
        {"xml:id": "n1", "ref": "MAT 1:1!1", "strong": "1", "lemma": "ga"},
        {"xml:id": "n2", "ref": "MAT 1:1!2", "strong": "2", "lemma": "gb"}])
    _tsv(cache / "macula" / "h.tsv", [
        {"xml:id": "o1", "ref": "GEN 1:1!1", "strongnumberx": "10", "pos": "noun", "lemma": "ha", "sensenumber": "1"},
        {"xml:id": "o2", "ref": "GEN 1:1!2", "strongnumberx": "20", "pos": "verb", "lemma": "hb", "sensenumber": ""}])
    _tsv(cache / "macula" / "greek-wordsenses.tsv", [{"macula_greek_word_id": "n2", "sense_number": "3"},
                                                      {"macula_greek_word_id": "n99", "sense_number": "1"}])
    (cache / "macula" / "lowfat-greek" / "01-x.xml").write_bytes(LOWFAT)
    (cache / "macula" / "lowfat-hebrew" / "01-y.xml").write_bytes(
        b'<chapter><wg class="np" rule="NpaNp"><w ref="GEN 1:1!1" sdbh="0001">ha</w>'
        b'<w ref="GEN 1:1!2" lexdomain="0002">hb</w></wg></chapter>')
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "biblosinterlinear96"
    for row in [HEADER,
                _row(heb=1, bsb=2, lang="Hebrew", text="ha", sh="10", verse="Genesis 1:1", english=" Alpha "),
                _row(heb=2, bsb=1, lang="Hebrew", text="hb", sh="20", english=" Beta "),
                _row(grk=1, bsb=3, lang="Greek", text="ga", sg="1", verse="Matthew 1:1", english=" Gamma "),
                _row(grk=2, bsb=4, lang="Greek", text="gb", sg="2", english=" Delta ", pnc=".")]:
        sheet.append(row)
    book.save(cache / "witnesses" / "bsb-tables" / "bsb_tables.xlsx")
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    sources = {
        "bsb_tables": {"file": "witnesses/bsb-tables/bsb_tables.xlsx", "url": "u",
                       "sha256": sha(cache / "witnesses/bsb-tables/bsb_tables.xlsx"), "attribution": "a"},
        "greek_wordsenses": {"file": "macula/greek-wordsenses.tsv", "url": "u",
                             "sha256": sha(cache / "macula/greek-wordsenses.tsv"), "attribution": "a"},
        "lowfat_greek": {"dir": "macula/lowfat-greek", "url": "u", "tree": "t", "repo": "r", "attribution": "a",
                         "listing_sha256": listing_digest(cache / "macula/lowfat-greek")},
        "lowfat_hebrew": {"dir": "macula/lowfat-hebrew", "url": "u", "tree": "t", "repo": "r", "attribution": "a",
                          "listing_sha256": listing_digest(cache / "macula/lowfat-hebrew")},
    }
    macula = {"GRK": {"file": "g.tsv", "url": "u", "commit": "c", "attribution": "a", "sha256": sha(cache / "macula/g.tsv")},
              "HEB": {"file": "h.tsv", "url": "u", "commit": "c", "attribution": "a", "sha256": sha(cache / "macula/h.tsv")}}
    return cache, sources, macula


def _install(root: Path, package: Path, package_id: str) -> None:
    """Pin ``package`` inside a fabricated SAGE root."""
    (root / "system/config").mkdir(parents=True, exist_ok=True)
    pin = {"package_id": package_id, "path": str(package.relative_to(root)),
           "sha256": hashlib.sha256((package / "CHECKSUMS.sha256").read_bytes()).hexdigest()}
    (root / ol_resources.PIN_PATH).write_text(json.dumps(pin), encoding="utf-8")


def test_build_is_deterministic_loads_and_fails_closed_on_tamper(tmp_path, monkeypatch):
    """Byte-identical rebuild; the loader returns the three tables; an edited file is refused."""
    monkeypatch.setattr(ol_resources, "_CACHE", {})
    cache, sources, macula = _cache(tmp_path)
    root = tmp_path / "root"
    first = root / "system/resources/pcc-ol/t1"
    manifest = build_package(first, "t1", cache=cache, macula_sources=macula, sources=sources)
    build_package(tmp_path / "again", "t1", cache=cache, macula_sources=macula, sources=sources)
    for name in (BSB_ALIGNMENT, OL_SENSES, OL_GROUPS, "MANIFEST.json", "CHECKSUMS.sha256"):
        assert (first / name).read_bytes() == (tmp_path / "again" / name).read_bytes()
    assert manifest["files"][OL_SENSES]["greek_ids_not_in_sblgnt"] == 1
    assert set(ol_build.EXCLUDED_FIELDS) <= set(manifest["excluded_fields"])
    payload = b"".join((first / n).read_bytes() for n in (BSB_ALIGNMENT, OL_SENSES, OL_GROUPS))
    assert b"0001" not in payload and b"000001" not in payload

    _install(root, first, "SAGE_PCC_OL_t1")
    loaded = ol_resources.load_pcc_ol(root)
    assert loaded.bsb_alignment["GEN 1:1!1"].english == "Alpha"
    assert loaded.bsb_alignment["GEN 1:1!1"].order == 2 and loaded.bsb_alignment["GEN 1:1!1"].match == "strong"
    assert loaded.bsb_alignment["MAT 1:1!2"].punct == "."
    assert loaded.senses == {("GEN 1:1!1", 0): "1", ("MAT 1:1!2", 0): "3"}
    assert [g.refs for g in loaded.groups_by_ref["GEN 1:1!2"]] == [("GEN 1:1!1", "GEN 1:1!2")]

    monkeypatch.setattr(ol_resources, "_CACHE", {})
    with (first / OL_SENSES).open("a", encoding="utf-8") as handle:
        handle.write("MAT 1:1!1\t0\t9\n")
    with pytest.raises(ValidationError) as caught:
        ol_resources.load_pcc_ol(root)
    assert caught.value.code == "PCC_OL_RESOURCES_INTEGRITY"


def test_changed_input_is_refused(tmp_path):
    """A source that differs from its pin stops the build before anything is written."""
    cache, sources, macula = _cache(tmp_path)
    (cache / "macula" / "lowfat-greek" / "01-x.xml").write_bytes(LOWFAT + b" ")
    with pytest.raises(ValidationError) as caught:
        build_package(tmp_path / "out", "t1", cache=cache, macula_sources=macula, sources=sources)
    assert caught.value.code == "PCC_OL_SOURCE_CHANGED"
    assert not (tmp_path / "out").exists()


def test_git_blob_sha_matches_git(tmp_path):
    """The blob SHA equals what git (and GitHub's tree listing) reports for the same bytes."""
    import shutil
    import subprocess
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    path = tmp_path / "f.xml"
    path.write_bytes(LOWFAT)
    expected = subprocess.run(["git", "hash-object", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    assert git_blob_sha(LOWFAT) == expected


def test_shipped_package_is_pinned_and_intact():
    """The distro's package loads against its Core pin and records its excluded fields."""
    resources = ol_resources.load_pcc_ol(APP_ROOT)
    assert resources is not None
    assert resources.manifest["package_id"] == resources.package_id
    assert set(ol_build.EXCLUDED_FIELDS) <= set(resources.manifest["excluded_fields"])
    files = resources.manifest["files"]
    assert files[BSB_ALIGNMENT]["rows"] > 400_000 and files[OL_GROUPS]["rows"] > 100_000
