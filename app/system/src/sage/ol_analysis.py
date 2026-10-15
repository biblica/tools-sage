"""Pinned MACULA original-language analysis: verse word lookup and checks of model claims about OL words.

The package (``system/resources/ol-analysis/<date>/``, pinned by ``system/config/ol-analysis-reference.json``)
holds every MACULA Hebrew and Greek word with its lemma, Strong's number, morphology fields, and a gloss. A
model that bases a conclusion on original-language words lists them in ``ol_words`` (surface form, lemma,
and parse fields). ``check_ol_words`` compares each entry with MACULA for the routed verses:

- ``VERIFIED``: a word with that surface in those verses carries the claimed lemma and every claimed field;
- ``MISMATCH``: the surface is there, but the claimed lemma or a field differs; the check names MACULA's value;
- ``NOT_FOUND``: MACULA has no such word in those verses (often an edition or numbering difference). This is
  neutral, never an error.

The checks never block a Run: a mismatch marks the finding unverified and is reported.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .canon import NT_27, OT_39
from .errors import SageError, ValidationError
from .references import expand_reference_atoms
from .vrs import VerseRef

PIN_PATH = Path("system/config/ol-analysis-reference.json")
CLAIM_FIELDS = ("pos", "type", "tense", "voice", "mood", "stem", "person", "number", "gender", "case", "state")
FAMILY_FILES = {"GRK": "greek.tsv", "HEB": "hebrew.tsv"}
_PUNCTUATION = {"־", "׀", "׃", "·", "·", ";", ",", ".", "·", "׃", "־", "׀"}
_CACHE: dict[Path, "OlAnalysis"] = {}


def _key(text: str, *, loose: bool) -> str:
    """Comparison key: NFC, no punctuation, casefolded; ``loose`` also drops every combining mark."""
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    kept = []
    for char in decomposed:
        if char in _PUNCTUATION or char.isspace():
            continue
        point = ord(char)
        if unicodedata.category(char).startswith("M") and (loose or 0x0591 <= point <= 0x05AF):
            continue
        kept.append(char)
    return unicodedata.normalize("NFC", "".join(kept)).casefold().replace("ς", "σ")


@dataclass(frozen=True)
class OlWord:
    """One MACULA word; a Hebrew word keeps its prefix and suffix segments."""

    word_id: str
    reference: VerseRef
    text: str
    segments: tuple[Mapping[str, str], ...]

    def lemmas(self) -> list[str]:
        """Every segment's lemma."""
        return [segment["lemma"] for segment in self.segments if segment.get("lemma")]

    def summary(self) -> dict[str, str]:
        """The main segment's lemma, Strong's number, gloss, and parse, for reports."""
        main = next((s for s in self.segments if s.get("pos") in {"verb", "noun", "adjective", "adj"}), self.segments[-1])
        return {
            "text": self.text,
            "lemma": main.get("lemma", ""),
            "strong": main.get("strong", ""),
            "gloss": main.get("gloss", ""),
            **{field: main[field] for field in CLAIM_FIELDS if main.get(field)},
        }


class OlAnalysis:
    """The loaded package: MACULA words by original-language verse, each family parsed on first use."""

    def __init__(self, package_id: str, manifest: Mapping[str, Any], blobs: Mapping[str, bytes]):
        """Keep the verified files; each family's table is parsed on first use."""
        self.package_id = package_id
        self.manifest = manifest
        self._blobs = dict(blobs)
        self._verses: dict[str, dict[VerseRef, list[OlWord]]] = {}

    def words(self, family: str, references: Iterable[VerseRef]) -> list[OlWord]:
        """MACULA words of one family in the given verses, in order."""
        if family not in self._verses:
            self._verses[family] = _read_family(self._blobs[FAMILY_FILES[family]], family) if family in FAMILY_FILES else {}
        table = self._verses[family]
        return [word for ref in references for word in table.get(ref, [])]

    def vocabulary(self, family: str) -> dict[str, list[str]]:
        """Allowed values of each claim field for one family."""
        return dict(dict(self.manifest["families"][family]).get("vocabulary") or {})


def _read_family(data: bytes, family: str) -> dict[VerseRef, list[OlWord]]:
    """Parse one family table and group Hebrew segments into whole words."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter="\t")
    verses: dict[VerseRef, list[OlWord]] = {}
    current_id = ""
    pending: list[dict[str, str]] = []

    def flush() -> None:
        """Close the word being assembled."""
        if not pending:
            return
        book, _, rest = pending[0]["ref"].partition(" ")
        chapter, _, verse = rest.split("!")[0].partition(":")
        reference = VerseRef(book, int(chapter), int(verse))
        verses.setdefault(reference, []).append(
            OlWord(current_id, reference, "".join(s["text"] for s in pending), tuple(pending))
        )
        pending.clear()

    for row in reader:
        # ``ref`` (BOOK C:V!position) names the word; a Hebrew word's prefix and suffix segments share it.
        word_id = row["ref"]
        if word_id != current_id:
            flush()
            current_id = word_id
        pending.append(dict(row))
    flush()
    return verses


def load_ol_analysis(root: Path) -> OlAnalysis | None:
    """Load and integrity-check the pinned package once per process; None when SAGE has no pin."""
    pin_path = Path(root) / PIN_PATH
    if not pin_path.is_file():
        return None
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    package = (Path(root) / str(pin["path"])).resolve()
    if package in _CACHE:
        return _CACHE[package]
    checksums_bytes = (package / "CHECKSUMS.sha256").read_bytes()
    if hashlib.sha256(checksums_bytes).hexdigest() != pin["sha256"]:
        raise ValidationError("OL analysis package checksums differ from the Core pin", code="OL_ANALYSIS_INTEGRITY")
    expected = dict(reversed(line.split("  ", 1)) for line in checksums_bytes.decode("utf-8").splitlines() if line)
    blobs: dict[str, bytes] = {}
    for name, digest in expected.items():
        data = (package / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValidationError(f"OL analysis package file {name} differs from its checksum", code="OL_ANALYSIS_INTEGRITY")
        blobs[name] = data
    manifest = json.loads(blobs["MANIFEST.json"].decode("utf-8"))
    analysis = OlAnalysis(str(pin["package_id"]), manifest, blobs)
    _CACHE[package] = analysis
    return analysis


def _candidate_refs(references: Sequence[str]) -> tuple[list[VerseRef], list[VerseRef]]:
    """The claimed verses, then their immediate neighbours for small numbering differences."""
    exact = [ref for value in references for ref in expand_reference_atoms([value])]
    nearby = [
        VerseRef(ref.book, ref.chapter, ref.verse + delta)
        for ref in exact
        for delta in (-1, 1)
        if ref.verse + delta >= 0
    ]
    return exact, [ref for ref in nearby if ref not in exact]


def _matches_surface(word: OlWord, claim_key: str, loose: bool) -> bool:
    """Whether a claimed surface names this word, the whole word or one of its Hebrew segments."""
    if not claim_key:
        return False
    keys = {_key(word.text, loose=loose)} | {_key(segment["text"], loose=loose) for segment in word.segments}
    # A quote without its prefix segments (conjunction, preposition, article) still names the word.
    for start in range(1, len(word.segments)):
        keys.add(_key("".join(segment["text"] for segment in word.segments[start:]), loose=loose))
    return claim_key in keys


def _differences(word: OlWord, claim: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Claimed fields that no segment of the word carries, with MACULA's value."""
    differences: dict[str, dict[str, str]] = {}
    lemma = str(claim.get("lemma") or "").strip()
    if lemma and _key(lemma, loose=True) not in {_key(value, loose=True) for value in word.lemmas()}:
        differences["lemma"] = {"claimed": lemma, "macula": ", ".join(word.lemmas())}
    claimed = {field: str(claim[field]).strip().lower() for field in CLAIM_FIELDS if claim.get(field)}
    if claimed:
        segments = [s for s in word.segments if not lemma or _key(s.get("lemma", ""), loose=True) == _key(lemma, loose=True)]
        best: dict[str, dict[str, str]] | None = None
        for segment in segments or list(word.segments):
            missing = {
                field: {"claimed": value, "macula": segment.get(field, "") or "none"}
                for field, value in claimed.items()
                if (segment.get(field, "") or "").lower() != value
            }
            if best is None or len(missing) < len(best):
                best = missing
        differences.update(best or {})
    return differences


def check_ol_words(
    analysis: OlAnalysis | None,
    family: str,
    references: Sequence[str],
    claims: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Check each claimed original-language word against MACULA for the given verses."""
    results: list[dict[str, Any]] = []
    exact, nearby = _candidate_refs(references)
    for claim in claims:
        surface = str(claim.get("surface") or "").strip()
        if analysis is None or family not in FAMILY_FILES:
            results.append({"surface": surface, "status": "NOT_CHECKED"})
            continue
        candidates: list[OlWord] = []
        for verses in (exact, nearby):
            words = analysis.words(family, verses)
            for loose in (False, True):
                key = _key(surface, loose=loose)
                candidates = [word for word in words if _matches_surface(word, key, loose)]
                if candidates:
                    break
            if candidates:
                break
        if not candidates:
            results.append({"surface": surface, "status": "NOT_FOUND"})
            continue
        scored = sorted(((len(_differences(word, claim)), index, word) for index, word in enumerate(candidates)))
        _, _, word = scored[0]
        differences = _differences(word, claim)
        results.append(
            {
                "surface": surface,
                "status": "MISMATCH" if differences else "VERIFIED",
                "macula_reference": word.reference.label(),
                "macula": word.summary(),
                **({"differences": differences} if differences else {}),
            }
        )
    return results


def ol_words_schema(analysis: OlAnalysis | None, family: str, *, max_items: int = 8) -> dict[str, Any]:
    """Response schema for the ``ol_words`` list, with MACULA's own value vocabularies."""
    vocabulary = analysis.vocabulary(family) if analysis is not None and family in FAMILY_FILES else {}
    properties: dict[str, Any] = {
        "surface": {
            "type": "string",
            "minLength": 1,
            "description": "The original-language word exactly as the routed packet writes it.",
        },
        "lemma": {"type": "string", "description": "Its dictionary form (lemma) in the original language."},
    }
    for field in CLAIM_FIELDS:
        values = vocabulary.get(field)
        properties[field] = (
            {"type": ["string", "null"], "enum": [*values, None]} if values else {"type": ["string", "null"]}
        )
    return {
        "type": "array",
        "maxItems": max_items,
        "description": (
            "Each original-language word this conclusion depends on, with its lemma and the parse fields you "
            "rely on (null for the rest). SAGE checks every entry against MACULA; list none if no specific "
            "word matters."
        ),
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["surface", "lemma", *CLAIM_FIELDS],
            "properties": properties,
        },
    }


def ol_family_for_book(book: str) -> str | None:
    """The MACULA family for one canonical book: GRK for the New Testament, HEB for the Old."""
    code = str(book).strip().upper()
    return "GRK" if code in NT_27 else "HEB" if code in OT_39 else None


OlChecker = Callable[[Sequence[Mapping[str, Any]], str], list[dict[str, Any]]]


def make_ol_checker(
    root: Path,
    book: str,
    correspondence: Iterable[Mapping[str, Any]] = (),
) -> tuple[OlChecker, str | None]:
    """Return ``(checker, package_id)``: ``checker(claims, wip_reference)`` checks claims for one verse.

    ``correspondence`` rows (``{"wip": ..., "original_language": [...]}``) map a WIP verse to the
    original-language verses it corresponds to; any other verse keeps its own reference. When the package
    is missing or fails its integrity check, every claim comes back ``NOT_CHECKED`` with the reason.
    """
    family = ol_family_for_book(book)
    mapping = {str(row.get("wip")): [str(value) for value in row.get("original_language") or []] for row in correspondence}
    reason = ""
    try:
        analysis = load_ol_analysis(root)
        if analysis is None:
            reason = "SAGE has no original-language analysis package"
    except (SageError, OSError, ValueError, KeyError) as exc:
        analysis, reason = None, f"original-language analysis package unavailable: {exc}"

    def checker(claims: Sequence[Mapping[str, Any]], wip_reference: str) -> list[dict[str, Any]]:
        """Check one finding's claimed words for one WIP verse."""
        if analysis is None or family is None:
            return [
                {"surface": str(claim.get("surface") or ""), "status": "NOT_CHECKED", "reason": reason or "book has no MACULA family"}
                for claim in claims
            ]
        return check_ol_words(analysis, family, mapping.get(wip_reference) or [wip_reference], claims)

    return checker, analysis.package_id if analysis is not None else None


def summarize_ol_checks(checks: Sequence[Mapping[str, Any]]) -> bool | None:
    """True when every checked word was verified, False when any mismatched, None when nothing was decided."""
    statuses = {str(check.get("status")) for check in checks}
    if "MISMATCH" in statuses:
        return False
    return True if "VERIFIED" in statuses else None


def unverified_message(finding_label: str, checks: Sequence[Mapping[str, Any]]) -> str:
    """One report line naming each claimed field MACULA does not support."""
    parts = []
    for check in checks:
        if check.get("status") != "MISMATCH":
            continue
        fields = "; ".join(
            f"{field} {value['claimed']} (MACULA: {value['macula']})"
            for field, value in dict(check.get("differences") or {}).items()
        )
        parts.append(f"{check.get('surface')}: {fields}")
    return (
        f"The original-language analysis in {finding_label} is not supported by MACULA ("
        + " | ".join(parts)
        + "); the finding is kept and marked unverified."
    )


def render_ol_word_checks(checks: Sequence[Mapping[str, Any]]) -> list[str]:
    """Report lines for checked original-language words: MACULA's analysis, and any field it contradicts."""
    lines: list[str] = []
    for check in checks:
        status = str(check.get("status") or "")
        surface = str(check.get("surface") or "")
        macula = dict(check.get("macula") or {})
        parse = " ".join(str(macula[field]) for field in CLAIM_FIELDS if macula.get(field))
        facts = f"lemma {macula.get('lemma', '')}, {parse}, \"{macula.get('gloss', '')}\"" if macula else ""
        if status == "VERIFIED":
            lines.append(f"- MACULA confirms `{surface}`: {facts}")
        elif status == "MISMATCH":
            fields = "; ".join(
                f"{field} {value['claimed']} (MACULA: {value['macula']})"
                for field, value in dict(check.get("differences") or {}).items()
            )
            lines.append(f"- MACULA does not support `{surface}`: {fields}")
        elif status == "NOT_FOUND":
            lines.append(f"- `{surface}` is not in MACULA's text of this verse (edition or numbering difference)")
    return ["", *lines] if lines else []
