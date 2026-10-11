"""Read pinned MACULA word tables into ordered verse token lists."""
from __future__ import annotations

import csv
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import unicodedata

from sage.errors import ValidationError
from sage.hashing import sha256_file

# Pinned upstream sources (MACULA Hebrew/Greek Linguistic Datasets, CC BY 4.0, Biblica, Inc.).
# Only identity, surface, lemma, morphology and gloss columns are read; MACULA's Semantic
# Dictionary of Biblical Hebrew fields (UBS, used with permission) are never copied.
SOURCES = {
    "HEB": {
        "file": "macula-hebrew.tsv",
        "url": "https://media.githubusercontent.com/media/Clear-Bible/macula-hebrew/"
               "df1ea5d85c8cb194278a874d6c670cd1d8abd97f/WLC/tsv/macula-hebrew.tsv",
        "commit": "df1ea5d85c8cb194278a874d6c670cd1d8abd97f",
        "sha256": "965cb0599beed2fe31283b615bcc369178141c0e718a66d97518d94309cfc124",
        "edition": "Westminster Leningrad Codex (MACULA Hebrew, OSHB morphology)",
        "attribution": "MACULA Hebrew Linguistic Datasets, available at https://github.com/Clear-Bible/macula-hebrew/",
    },
    "GRK": {
        "file": "macula-greek-SBLGNT.tsv",
        "url": "https://raw.githubusercontent.com/Clear-Bible/macula-greek/"
               "076282a3926625a5e670823b0738ce5f1e619528/SBLGNT/tsv/macula-greek-SBLGNT.tsv",
        "commit": "076282a3926625a5e670823b0738ce5f1e619528",
        "sha256": "7f71504fdee8659bdd9f85342e4103d645864c2851b8205915bb298f0c004cc5",
        "edition": "SBL Greek New Testament (MACULA Greek)",
        "attribution": "MACULA Greek Linguistic Datasets, available at https://github.com/Clear-Bible/macula-greek/",
    },
}


def normalized(text: str | None) -> str:
    """Canonical Unicode form, so lexicon keys match MACULA's mark ordering."""
    return unicodedata.normalize("NFC", text or "")


@dataclass(frozen=True)
class Word:
    """One MACULA word with the fields the numeral lexicon and composer use."""

    word_id: str
    ref: str
    position: int
    text: str
    lemma: str
    pos: str
    subtype: str
    number: str
    state: str
    gloss: str
    lang: str
    strong: str = ""
    english: str = ""
    gender: str = ""
    case: str = ""
    after: str = ""  # text MACULA prints after the word (space, maqaf, nothing)


def _hebrew_word(row: dict[str, str]) -> Word:
    """Project one MACULA Hebrew row (WLC, Hebrew + Aramaic)."""
    ref, _, position = row["ref"].partition("!")
    return Word(row["xml:id"], ref, int(position or 0), normalized(row["text"]), normalized(row["lemma"]),
                row["pos"], row["type"], row["number"], row["state"], row["gloss"] or "", row["lang"],
                row.get("strongnumberx") or "", row.get("english") or "", after=row.get("after") or "")


def _greek_word(row: dict[str, str]) -> Word:
    """Project one MACULA Greek row (SBLGNT); its class field plays the role of part of speech."""
    ref, _, position = row["ref"].partition("!")
    return Word(row["xml:id"], ref, int(position or 0), normalized(row["text"]), normalized(row["lemma"]),
                row["class"], row["type"], row["number"], "", row["english"] or row["gloss"] or "", "G",
                row.get("strong") or "", row["english"] or "", row.get("gender") or "", row.get("case") or "",
                row.get("after") or "")


def verify_source(path: Path, family: str) -> None:
    """Refuse to build from anything but the pinned upstream bytes."""
    expected = SOURCES[family]["sha256"]
    if not path.is_file() or sha256_file(path) != expected:
        raise ValidationError(
            f"MACULA {family} source is missing or differs from the pinned release: {path}",
            code="NCA_INDEX_SOURCE_INVALID",
            next_action="Run tools/build_numbers_index.py fetch to download the pinned sources.",
        )


def read_verses(path: Path, family: str) -> "OrderedDict[str, list[Word]]":
    """Read one pinned MACULA table into verse-ordered word lists keyed 'BOOK C:V'."""
    verify_source(path, family)
    project = _hebrew_word if family == "HEB" else _greek_word
    csv.field_size_limit(1 << 30)
    verses: OrderedDict[str, list[Word]] = OrderedDict()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            word = project(row)
            verses.setdefault(word.ref, []).append(word)
    return verses
