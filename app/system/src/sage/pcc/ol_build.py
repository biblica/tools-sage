"""Build the PCC original-language resource package (plan §5b.7, D19, D20; build time only).

Three tables, each keyed by the MACULA word ``ref`` that the shipped OL analysis package already uses
(``GEN 1:1!1``):

* ``bsb-alignment.tsv``: the gold word alignment between each original-language word and its Berean
  Standard Bible English, taken from the BSB tables (BSB public domain; the alignment derives from MACULA,
  CC BY 4.0, Biblica). Columns ``ol_ref``, ``bsb_ref`` (BSB verse, English numbering), ``bsb_order``
  (1-based position of the chunk in that BSB verse, 0 when not rendered), ``english`` (``-`` when the word
  is not rendered), ``punct`` and ``match``. The BSB tables' Greek is not SBLGNT, so words are paired per
  book by their Strong's sequence (``match`` blank). A gap of at most 3 words between two such anchors,
  equally long on both sides, is the same words numbered differently (e.g. a form-specific Strong's number)
  and is paired in order (``match`` = ``position``). Other unpaired words are text differences:
  counted, never guessed.
* ``ol-senses.tsv``: Clear word senses (CC BY 4.0, Biblica): Greek from ``sources/Clear/wordsense``, Hebrew
  from ``@sensenumber``. Columns ``ol_ref``, ``seg`` (segment index within the word, 0 for Greek; the same
  segment order as the OL analysis package) and ``sense``.
* ``ol-groups.tsv``: MACULA syntax-tree word groups (lowfat ``wg``, CC BY 4.0): noun, adjective and
  prepositional phrases of 2 to 6 words. Columns ``class``, ``rule``, ``role`` and ``refs`` (word refs joined
  by ``;``).

Only those fields are read. The UBS-licensed fields (``ln``, ``domain``, ``sdbh``, ``lexdomain``,
``coredomain``, ``contextualdomain``) are never read (plan D3).
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from ..references import resolve_book

BSB_ALIGNMENT = "bsb-alignment.tsv"
OL_SENSES = "ol-senses.tsv"
OL_GROUPS = "ol-groups.tsv"
GROUP_CLASSES = ("adjp", "np", "pp")
GROUP_MIN_WORDS = 2
GROUP_MAX_WORDS = 6
CONTENT_POS = {"verb", "noun", "adjective", "adj"}
ALIGNMENT_COLUMNS = ("ol_ref", "bsb_ref", "bsb_order", "english", "punct", "match")
SENSE_COLUMNS = ("ol_ref", "seg", "sense")
MAX_POSITION_GAP = 3
REFS_SEPARATOR = ";"  # MACULA refs contain spaces ("GEN 1:1!1")
GROUP_COLUMNS = ("class", "rule", "role", "refs")
EXCLUDED_FIELDS = ("ln", "domain", "sdbh", "lexdomain", "coredomain", "contextualdomain")

# Pinned inputs, relative to the SAGE cache (``localdata/.system/cache``). The MACULA word tables are the
# ones pinned in ``sage.numbers.index_build.macula.SOURCES``.
MACULA_GREEK_COMMIT = "076282a3926625a5e670823b0738ce5f1e619528"
MACULA_HEBREW_COMMIT = "df1ea5d85c8cb194278a874d6c670cd1d8abd97f"
SOURCES: dict[str, dict[str, str]] = {
    "bsb_tables": {
        "file": "witnesses/bsb-tables/bsb_tables.xlsx",
        "url": "https://bereanbible.com/bsb_tables.xlsx",
        "sha256": "4763b1fa530c9f69ace032ee5b1bdbfe6e471b889fdcf00e1c1de9d8cc09cf3d",
        "attribution": "Berean Standard Bible tables (bereanbible.com), public domain; word alignment derived "
                       "from MACULA (CC BY 4.0, Biblica, Inc.)",
    },
    "greek_wordsenses": {
        "file": "macula/greek-wordsenses.tsv",
        "url": "https://raw.githubusercontent.com/Clear-Bible/macula-greek/"
               f"{MACULA_GREEK_COMMIT}/sources/Clear/wordsense/greek-wordsenses.tsv",
        "sha256": "10a6b4fe1e262fc187c7425c009b796ebfbcd634c657866cbd2032c2efa788bd",
        "attribution": "MACULA Greek Linguistic Datasets (Clear word senses), available at "
                       "https://github.com/Clear-Bible/macula-greek/",
    },
    "lowfat_greek": {
        "dir": "macula/lowfat-greek",
        "url": f"https://raw.githubusercontent.com/Clear-Bible/macula-greek/{MACULA_GREEK_COMMIT}/SBLGNT/lowfat/",
        "tree": "458623037e4d53adc3049ebb287a46ddeb3629e9",
        "repo": "Clear-Bible/macula-greek",
        "listing_sha256": "08b1aeba8ea917bc9ee8f2bff423cb02188d1fa094ce35853a2fe350bc513a97",
        "attribution": "MACULA Greek Linguistic Datasets (syntax trees), available at "
                       "https://github.com/Clear-Bible/macula-greek/",
    },
    "lowfat_hebrew": {
        "dir": "macula/lowfat-hebrew",
        "url": f"https://raw.githubusercontent.com/Clear-Bible/macula-hebrew/{MACULA_HEBREW_COMMIT}/WLC/lowfat/",
        "tree": "1d3da3bddd05f7e0a825acd0966e08b91a883203",
        "repo": "Clear-Bible/macula-hebrew",
        "listing_sha256": "d6874dd48fdd5e899ab2ade0100a74794db0d36685a65258c023d6c3a2399e92",
        "attribution": "MACULA Hebrew Linguistic Datasets (syntax trees), available at "
                       "https://github.com/Clear-Bible/macula-hebrew/; Westminster Hebrew Syntax without "
                       "Morphology, Copyright (C) 1991-2018 by The J. Alan Groves Center for Advanced Biblical "
                       "Research (CC BY 4.0)",
    },
}


def digits(value: object) -> str:
    """Strong's number reduced to its digits without leading zeros (``H0218b`` -> ``218``)."""
    match = re.search(r"(\d+)", str(value or ""))
    return str(int(match.group(1))) if match else ""


def sha256_bytes(data: bytes) -> str:
    """Implement sha256 of bytes."""
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    """The git blob SHA-1 of ``data`` (what GitHub lists for a file)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def listing_digest(folder: Path) -> str:
    """SHA-256 over the sorted ``<name> <git blob sha>`` lines of every ``*.xml`` in ``folder``."""
    lines = "".join(f"{path.name} {git_blob_sha(path.read_bytes())}\n" for path in sorted(folder.glob("*.xml")))
    return sha256_bytes(lines.encode("utf-8"))


def verify_inputs(cache: Path, sources: Mapping[str, Mapping[str, str]] = SOURCES) -> None:
    """Fail closed unless every pinned input in ``cache`` matches its pin."""
    for name, source in sources.items():
        if "file" in source:
            path = cache / source["file"]
            if not path.is_file():
                raise ValidationError(f"Missing PCC source {name}: {path}", code="PCC_OL_SOURCE_MISSING",
                                      next_action="Run tools/build_pcc_ol_resources.py fetch.")
            if sha256_bytes(path.read_bytes()) != source["sha256"]:
                raise ValidationError(f"PCC source {name} differs from its pin: {path}", code="PCC_OL_SOURCE_CHANGED")
        else:
            folder = cache / source["dir"]
            if not folder.is_dir() or listing_digest(folder) != source["listing_sha256"]:
                raise ValidationError(f"PCC source {name} is missing or differs from its pin: {folder}",
                                      code="PCC_OL_SOURCE_CHANGED",
                                      next_action="Run tools/build_pcc_ol_resources.py fetch.")


# --- MACULA word tables ---------------------------------------------------------------------------------


@dataclass
class MaculaFamily:
    """One MACULA word table reduced to what the package needs."""

    words: list[tuple[str, str]]                       # (ref, main Strong's digits), word order
    by_id: dict[str, tuple[str, int, str]]             # xml:id -> (ref, segment index, lemma)
    senses: list[tuple[str, int, str, str]]            # (ref, seg, lemma, sense) from @sensenumber


def read_macula(rows: Iterable[Mapping[str, str]], family: str) -> MaculaFamily:
    """Group MACULA rows (Hebrew: one per segment) into words; keep ids and Hebrew senses."""
    words: list[tuple[str, str]] = []
    segments: dict[str, list[Mapping[str, str]]] = {}
    by_id: dict[str, tuple[str, int, str]] = {}
    senses: list[tuple[str, int, str, str]] = []
    for row in rows:
        ref = row["ref"]
        if ref not in segments:
            segments[ref] = []
            words.append((ref, ""))
        seg = len(segments[ref])
        segments[ref].append(row)
        lemma = row.get("lemma", "")
        if row.get("xml:id"):
            by_id[row["xml:id"]] = (ref, seg, lemma)
        if family == "HEB" and row.get("sensenumber"):
            senses.append((ref, seg, lemma, row["sensenumber"]))
    resolved = []
    for ref, _ in words:
        segs = segments[ref]
        if family == "HEB":
            main = next((s for s in segs if (s.get("pos") or "") in CONTENT_POS), segs[-1])
            resolved.append((ref, digits(main.get("strongnumberx"))))
        else:
            resolved.append((ref, digits(segs[0].get("strong"))))
    return MaculaFamily(resolved, by_id, senses)


def read_macula_file(path: Path, family: str) -> MaculaFamily:
    """Read one pinned MACULA TSV."""
    csv.field_size_limit(1 << 30)
    with path.open(encoding="utf-8", newline="") as handle:
        return read_macula(csv.DictReader(handle, delimiter="\t"), family)


# --- BSB tables --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TableWord:
    """One original-language word row of the BSB tables."""

    family: str          # GRK or HEB (Aramaic counts as HEB, as in MACULA)
    book: str
    ol_sort: int
    strong: str
    bsb_ref: str
    bsb_order: int
    english: str
    punct: str


_VERSE_ID = re.compile(r"(.+?) (\d+):(\d+)$")
_HEADERS = {"heb_sort": "Heb Sort", "grk_sort": "Greek Sort", "bsb_sort": "BSB Sort", "language": "Language",
            "str_heb": "Str Heb", "str_grk": "Str Grk", "verse_id": "VerseId", "english": "BSB version",
            "punct": "pnc"}


def table_words(rows: Iterable[Sequence[Any]]) -> list[TableWord]:
    """Original-language words from the BSB table rows (header first); the BSB verse is carried forward."""
    iterator = iter(rows)
    header = [str(cell or "").strip() for cell in next(iterator)]
    index = {key: header.index(name) for key, name in _HEADERS.items()}
    text_col = next(i for i, name in enumerate(header) if name.startswith("WLC / Nestle Base"))
    verse_ref = ""
    book = ""
    raw: list[tuple[str, str, int, str, str, int, str, str]] = []
    for row in iterator:
        verse_id = str(row[index["verse_id"]] or "").strip()
        if verse_id:
            match = _VERSE_ID.match(verse_id)
            if match:
                book = resolve_book(match.group(1))
                verse_ref = f"{book} {int(match.group(2))}:{int(match.group(3))}"
        language = str(row[index["language"]] or "")
        family = "GRK" if language == "Greek" else "HEB" if language in ("Hebrew", "Aramaic") else ""
        english = str(row[index["english"]] or "").strip()
        has_text = bool(str(row[text_col] or "").strip())
        if not verse_ref or not (has_text or english):
            continue
        sort_value = row[index["grk_sort"] if family == "GRK" else index["heb_sort"]]
        raw.append((family if has_text else "", book, _int(sort_value),
                    digits(row[index["str_grk"] if family == "GRK" else index["str_heb"]]),
                    verse_ref, _int(row[index["bsb_sort"]]), english, str(row[index["punct"]] or "").strip()))
    # The position of each rendered English chunk inside its BSB verse; "-" (not rendered) has none.
    by_verse: dict[str, list[int]] = defaultdict(list)
    for item in raw:
        if _rendered(item[6]):
            by_verse[item[4]].append(item[5])
    rank = {verse: {value: n for n, value in enumerate(sorted(values), start=1)} for verse, values in by_verse.items()}
    return [TableWord(family, bk, sort, strong, verse, rank[verse].get(bsb_sort, 0) if _rendered(english) else 0,
                      english, punct)
            for family, bk, sort, strong, verse, bsb_sort, english, punct in raw if family]


def _int(value: object) -> int:
    """A table number cell (int, float or text) as int; blank is 0."""
    text = str(value or "").strip()
    return int(float(text)) if text else 0


def _rendered(english: str) -> bool:
    """True when the chunk is real English (not blank and not the ``-`` not-rendered mark)."""
    return bool(english) and english != "-"


def read_table_file(path: Path) -> list[TableWord]:
    """Read the pinned ``bsb_tables.xlsx`` (sheet ``biblosinterlinear96``)."""
    import openpyxl
    workbook = openpyxl.load_workbook(path, read_only=True)
    try:
        return table_words(workbook["biblosinterlinear96"].iter_rows(values_only=True))
    finally:
        workbook.close()


def align_table(words: Sequence[TableWord], macula: Sequence[tuple[str, str]]
                ) -> tuple[list[tuple[str, TableWord, str]], dict[str, int]]:
    """Pair BSB table words with MACULA words per book; return (ref, word, match) pairs and counts."""
    by_book_table: dict[str, list[TableWord]] = defaultdict(list)
    for word in words:
        by_book_table[word.book].append(word)
    by_book_macula: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ref, strong in macula:
        by_book_macula[ref.split(" ")[0]].append((ref, strong))
    pairs: list[tuple[str, TableWord, str]] = []
    for book in sorted(set(by_book_table) | set(by_book_macula)):
        table = sorted(by_book_table.get(book, []), key=lambda w: w.ol_sort)
        ol = by_book_macula.get(book, [])
        matcher = difflib.SequenceMatcher(None, [w.strong for w in table], [s for _, s in ol], autojunk=False)
        next_a = next_b = 0
        for block in matcher.get_matching_blocks():
            gap = block.a - next_a
            if 0 < gap <= MAX_POSITION_GAP and gap == block.b - next_b:
                pairs += [(ol[next_b + k][0], table[next_a + k], "position") for k in range(gap)]
            pairs += [(ol[block.b + k][0], table[block.a + k], "strong") for k in range(block.size)]
            next_a, next_b = block.a + block.size, block.b + block.size
    by_match = {kind: sum(1 for p in pairs if p[2] == kind) for kind in ("strong", "position")}
    stats = {"table_words": len(words), "macula_words": len(macula), "paired_by_strong": by_match["strong"],
             "paired_by_position": by_match["position"]}
    return pairs, stats


# --- Syntax-tree word groups -----------------------------------------------------------------------------


def extract_groups(xml: bytes) -> list[tuple[str, str, str, tuple[str, ...]]]:
    """Phrase groups of one lowfat file: (class, rule, role, word refs). Only structure attributes are read."""
    root = ET.fromstring(xml)
    found = []
    for group in root.iter("wg"):
        cls = group.get("class") or ""
        if cls not in GROUP_CLASSES:
            continue
        refs = tuple(dict.fromkeys(w.get("ref") for w in group.iter("w") if w.get("ref")))
        if GROUP_MIN_WORDS <= len(refs) <= GROUP_MAX_WORDS:
            found.append((cls, group.get("rule") or group.get("Rule") or "", group.get("role") or "", refs))
    return found


# --- Package ---------------------------------------------------------------------------------------------


def _tsv(columns: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes:
    """Deterministic UTF-8 TSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([str(value).replace("\t", " ").replace("\n", " ") for value in row])
    return buffer.getvalue().encode("utf-8")


def build_package(destination: Path, date: str, *, cache: Path, macula_sources: Mapping[str, Mapping[str, str]],
                  sources: Mapping[str, Mapping[str, str]] = SOURCES) -> dict[str, Any]:
    """Write the package into ``destination`` (created) and return its manifest."""
    verify_inputs(cache, sources)
    for family in ("GRK", "HEB"):
        path = cache / "macula" / macula_sources[family]["file"]
        if not path.is_file() or sha256_bytes(path.read_bytes()) != macula_sources[family]["sha256"]:
            raise ValidationError(f"MACULA {family} table is missing or differs from its pin: {path}",
                                  code="PCC_OL_SOURCE_CHANGED", next_action="Run tools/build_pcc_ol_resources.py fetch.")
    families = {family: read_macula_file(cache / "macula" / macula_sources[family]["file"], family)
                for family in ("GRK", "HEB")}
    order = {ref: n for n, ref in enumerate(ref for family in ("HEB", "GRK") for ref, _ in families[family].words)}

    table = read_table_file(cache / sources["bsb_tables"]["file"])
    alignment_rows = []
    mapping: dict[str, dict[str, int]] = {}
    for family in ("HEB", "GRK"):
        pairs, stats = align_table([w for w in table if w.family == family], families[family].words)
        mapping[family] = stats
        alignment_rows += [(ref, w.bsb_ref, w.bsb_order, w.english, w.punct, "" if match == "strong" else match)
                           for ref, w, match in pairs]
    alignment_rows.sort(key=lambda r: order[r[0]])

    sense_rows = [(ref, seg, sense) for ref, seg, _lemma, sense in families["HEB"].senses]
    with (cache / sources["greek_wordsenses"]["file"]).open(encoding="utf-8", newline="") as handle:
        unjoined = 0
        for row in csv.DictReader(handle, delimiter="\t"):
            hit = families["GRK"].by_id.get(row["macula_greek_word_id"])
            if hit is None:
                unjoined += 1
                continue
            sense_rows.append((hit[0], hit[1], row["sense_number"]))
    sense_rows.sort(key=lambda r: (order.get(r[0], len(order)), r[1]))

    groups: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for name in ("lowfat_hebrew", "lowfat_greek"):
        for path in sorted((cache / sources[name]["dir"]).glob("*.xml")):
            groups.update(extract_groups(path.read_bytes()))
    group_rows = sorted(groups, key=lambda g: (order.get(g[3][0], len(order)), len(g[3]), g[3], g[0], g[1], g[2]))

    destination.mkdir(parents=True, exist_ok=True)
    payload = {
        BSB_ALIGNMENT: _tsv(ALIGNMENT_COLUMNS, alignment_rows),
        OL_SENSES: _tsv(SENSE_COLUMNS, sense_rows),
        OL_GROUPS: _tsv(GROUP_COLUMNS, ((c, r, o, REFS_SEPARATOR.join(refs)) for c, r, o, refs in group_rows)),
    }
    for name, data in payload.items():
        (destination / name).write_bytes(data)
    manifest = {
        "schema_version": "1.0",
        "package_id": f"SAGE_PCC_OL_{date}",
        "purpose": "PCC reference-list builder: gold BSB word alignment, Clear word senses and syntax-tree "
                   "phrase groups, keyed by MACULA word ref (the key of SAGE_OL_ANALYSIS).",
        "license": "CC BY 4.0 (MACULA, (c) 2022-2024 Biblica, Inc.) and public domain (Berean Standard Bible); "
                   "see docs/advanced/projects-and-resources/THIRD-PARTY-NOTICES.md",
        "excluded_fields": list(EXCLUDED_FIELDS),
        "files": {
            BSB_ALIGNMENT: {"columns": list(ALIGNMENT_COLUMNS), "rows": len(alignment_rows), "mapping": mapping},
            OL_SENSES: {"columns": list(SENSE_COLUMNS), "rows": len(sense_rows), "greek_ids_not_in_sblgnt": unjoined},
            OL_GROUPS: {"columns": list(GROUP_COLUMNS), "rows": len(group_rows), "classes": list(GROUP_CLASSES),
                        "words": [GROUP_MIN_WORDS, GROUP_MAX_WORDS]},
        },
        "sources": {
            **{name: {k: v for k, v in source.items() if k != "dir"} for name, source in sorted(sources.items())},
            **{f"macula_{family.lower()}": {"url": macula_sources[family]["url"], "sha256": macula_sources[family]["sha256"],
                                            "commit": macula_sources[family]["commit"],
                                            "attribution": macula_sources[family]["attribution"]}
               for family in ("GRK", "HEB")},
        },
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (destination / "MANIFEST.json").write_bytes(manifest_bytes)
    checksums = {name: sha256_bytes(data) for name, data in {**payload, "MANIFEST.json": manifest_bytes}.items()}
    (destination / "CHECKSUMS.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())), encoding="utf-8")
    return manifest
