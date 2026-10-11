"""Public-domain versional witnesses for indexed numbers (cached from ebible.org, never vendored).

Independent of the NET notes, four public-domain English witnesses are read verse by verse and
their numbers counted with the shared convention (index_build/english.py):

- ``LXX_BRENTON``  Brenton, *The Septuagint Version of the Old Testament* (1851), in Septuagint
  numbering, linked through ``lxx.vrs``;
- ``VULGATE_DRA``  Douay-Rheims (Challoner), the Latin Vulgate in English, linked through
  ``vul.vrs``;
- ``KJV``          King James Version (1769 text, eng-kjv2006), following the Masoretic Text and
  the Textus Receptus, linked through ``eng.vrs``;
- ``BSB``          Berean Standard Bible (public domain since 2023), a modern translation of the
  Masoretic Text and the critical Greek text, linked through ``eng.vrs``. It is a rendering
  reference, never versional evidence: each BSB reading is cited with where to look next (the
  original language, the NIV and the other witnesses), and its footnotes that report a number in
  another text ("Hebrew; LXX one for each capital") are apparatus evidence (``textual_notes``).

Each reading is related to the index: ``AGREES_OL``, ``AGREES_NIV``, ``AGREES_BOTH``, ``OTHER``
(different numbers), ``ABSENT`` (the witness lacks the verse but has its chapter) or
``UNAVAILABLE`` (the witness does not cover that chapter under its versification). A Septuagint or Vulgate reading
that agrees with the NIV against the original language, or reads another number, is versional
evidence of a number variant; the KJV shows the Masoretic/Received-text reading in English.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import re

from sage.canon import NT_27, OT_39
from sage.vrs import VerseRef, parse_vrs_file

from .english import count
from .niv import Verse, read_book

WITNESSES = {
    "LXX_BRENTON": {"folder": "eng-Brenton", "vrs": "lxx.vrs", "testament": "OT",
                    "label": "Septuagint (Brenton 1851, public domain)",
                    "url": "https://ebible.org/find/show.php?id=eng-Brenton"},
    "VULGATE_DRA": {"folder": "engDRA", "vrs": "vul.vrs", "testament": "ALL",
                    "label": "Vulgate (Douay-Rheims, public domain)",
                    "url": "https://ebible.org/find/show.php?id=engDRA"},
    "KJV": {"folder": "eng-kjv2006", "vrs": "eng.vrs", "testament": "ALL",
            "label": "King James Version (Masoretic / Received text, public domain)",
            "url": "https://ebible.org/find/show.php?id=eng-kjv2006"},
    "BSB": {"folder": "engbsb", "vrs": "eng.vrs", "testament": "ALL", "archaic": False,
            "label": "Berean Standard Bible (public domain)",
            "url": "https://ebible.org/find/show.php?id=engbsb"},
}
# Short names for a witness in a "see also" list.
SHORT = {"LXX_BRENTON": "LXX", "VULGATE_DRA": "Vulgate", "KJV": "KJV", "BSB": "BSB"}
_CANON = set(OT_39) | set(NT_27)


@dataclass(frozen=True)
class Reading:
    """One witness at one Western verse."""

    witness: str
    reference: str
    text: str
    values: tuple[Fraction, ...]
    relation: str


def _label(ref: VerseRef) -> str:
    """'BOOK C:V'."""
    return ref.label()


def _tidy(text: str) -> str:
    """Close the gaps word-level markup leaves after opening quotes and dashes ("“ Let", "morning— the")."""
    return re.sub(r"\s+([”’])", r"\1", re.sub(r"([“‘—])\s+", r"\1", text))


def _verses(cache: Path, scripture_root: Path, witness: str):
    """(Western label, verse) for every verse of one witness, linked through its own versification."""
    spec = WITNESSES[witness]
    eng = parse_vrs_file(scripture_root / "eng.vrs", schema_id="eng", canonical_id="org")
    local = parse_vrs_file(scripture_root / spec["vrs"], schema_id=witness, canonical_id="org")
    for path in sorted((cache / "witnesses" / spec["folder"]).glob("*.usfm")):
        match = re.search(r"\\id\s+([1-4A-Z]{3})", path.read_text(encoding="utf-8-sig")[:400])
        # ESG is Greek Esther; lxx.vrs maps it onto Esther (EST).
        if not match or (match[1] not in _CANON and match[1] != "ESG"):
            continue
        for label, verse in read_book(path, match[1]).items():
            book, _, cv = label.partition(" ")
            chapter, _, number = cv.partition(":")
            if not number.isdigit():
                continue  # lettered sub-verses are Greek additions with no Hebrew counterpart
            ref = VerseRef(book, int(chapter), int(number))
            canonical = sorted(local.local_to_canonical(ref), key=lambda item: (item.chapter, item.verse))
            targets = sorted({item for c in canonical for item in eng.canonical_to_local(c)},
                             key=lambda item: (item.chapter, item.verse)) or [ref]
            yield _label(targets[0]), Verse(verse.ref, _tidy(verse.text), list(verse.notes))


def quoted_verses(cache: Path, scripture_root: Path, witness: str = "BSB") -> dict[str, Verse]:
    """One witness's verses (text and footnotes) keyed by Western coordinate, for quoting."""
    found: dict[str, Verse] = {}
    for western, verse in _verses(cache, scripture_root, witness):
        if western in found:
            found[western].text = (found[western].text + " " + verse.text).strip()
            found[western].notes.extend(verse.notes)
        else:
            found[western] = Verse(western, verse.text, list(verse.notes))
    return found


def load(cache: Path, scripture_root: Path, witness: str) -> dict[str, str]:
    """One witness's verse texts keyed by Western (eng.vrs) coordinate."""
    found: dict[str, str] = {}
    for western, verse in _verses(cache, scripture_root, witness):
        found[western] = (found.get(western, "") + " " + verse.text).strip()
    return found


# A footnote reports another text when it names a version or manuscripts ("LXX and Syriac; Hebrew
# seventh", "BYZ and TR include ..."); "Hebrew half a yoke" alone is a literal rendering, not a variant.
_OTHER_TEXT = re.compile(r"\b(LXX|Septuagint|MT|Masoretic|Syriac|Vulgate|DSS|Dead Sea|Samaritan|Targums?|"
                         r"manuscripts?|BYZ|TR|NE|WH|NA|SBL|ECM)\b")
_NOTE_NUMBER = re.compile(
    r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundreds?|thousands?|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"half)\b", re.I)
_NOTE_NOISE = re.compile(
    r"\b(?:[1-3] )?[A-Z][a-z]+ \d+:\d+(?:[–-]\d+)?(?:,? (?:and )?\d+(?:[–-]\d+)?)*|\bverses? \d+(?:[–-]\d+)?(?:,? (?:and )?\d+)*|"
    r"\b(?:one|two|some|most|many|several|a few|other)\s+(?:\w+\s+)?manuscripts?\b", re.I)


def reports_a_number(note: str) -> bool:
    """Whether a footnote reports a number in another text, ignoring Scripture references and
    manuscript counts ("One Hebrew manuscript and LXX")."""
    return bool(_OTHER_TEXT.search(note)) and bool(_NOTE_NUMBER.search(_NOTE_NOISE.sub(" ", note)))


def textual_notes(cache: Path, scripture_root: Path, witness: str = "BSB") -> dict[str, list[str]]:
    """Footnotes of one witness that report a number in another text, keyed by Western coordinate."""
    found: dict[str, list[str]] = {}
    for western, verse in _verses(cache, scripture_root, witness):
        for note in verse.notes:
            if reports_a_number(note):
                found.setdefault(western, []).append(note)
    return found


def relation(values: tuple[Fraction, ...], ol: list[Fraction], niv: list[Fraction], present: bool,
             chapter_present: bool = True) -> str:
    """How one witness's numbers relate to the index layers at a verse.

    ``ABSENT`` needs the witness to have the rest of the chapter (the verse is really missing);
    a chapter the witness does not cover at all under its versification is ``UNAVAILABLE``.
    """
    if not present:
        return "ABSENT" if chapter_present else "UNAVAILABLE"
    mine, original, english = Counter(values), Counter(ol), Counter(niv)
    if mine == original and mine == english:
        return "AGREES_BOTH"
    if mine == original:
        return "AGREES_OL"
    if mine == english:
        return "AGREES_NIV"
    return "OTHER"


def readings(cache: Path, scripture_root: Path, rows: list[dict[str, str]],
             values: dict[str, tuple[list[Fraction], list[Fraction]]]) -> list[Reading]:
    """Every witness reading at the given index verses (only witnesses that cover the testament)."""
    found = []
    for witness, spec in WITNESSES.items():
        texts = load(cache, scripture_root, witness)
        chapters = {label.rsplit(":", 1)[0] for label in texts}
        for row in rows:
            ref = row["WESTERN_REF"]
            if spec["testament"] == "OT" and ref.split()[0] not in OT_39:
                continue
            ol, niv = values.get(ref, ([], []))
            text = texts.get(ref)
            archaic = spec.get("archaic", True)
            numbers = tuple(item.value for item in count(text, archaic=archaic)) if text else ()
            found.append(Reading(witness, ref, text or "", numbers,
                                 relation(numbers, ol, niv, text is not None, ref.rsplit(":", 1)[0] in chapters)))
    return found


def attests_variant(reading: Reading, ol: list[Fraction]) -> bool:
    """Whether a reading is versional evidence of a number variant (not just another rendering).

    It lacks the verse while having its chapter, agrees with the NIV against the original
    language, or reads a number the original language does not have.
    """
    if reading.relation in {"ABSENT", "AGREES_NIV"}:
        return True
    return reading.relation == "OTHER" and bool(set(reading.values) - set(ol))


def see_also(reference: str, ol: list[Fraction], niv: list[Fraction], others: dict[str, Reading]) -> str:
    """Where to look next beside one witness: the original language (MT or Greek NT), the NIV and
    the other witnesses at the verse ("MT 7, 7, 2; NIV 7, 1; LXX 7, 7, 2; Vulgate 7, 2; KJV 7, 7, 2")."""
    def numbers(values) -> str:
        """Values as a short list ("7, 1"), or "no numbers"."""
        return ", ".join(str(value) for value in values) or "no numbers"

    original = "MT" if reference.split()[0] in OT_39 else "Greek NT"
    parts = [f"{original} {numbers(ol)}", f"NIV {numbers(niv)}"]
    for name, reading in others.items():
        if reading.relation == "UNAVAILABLE":
            continue
        parts.append(f"{SHORT.get(name, name)} " + ("verse absent" if reading.relation == "ABSENT"
                                                     else numbers(reading.values)))
    return "; ".join(parts)
