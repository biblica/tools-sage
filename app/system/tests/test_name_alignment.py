"""Name renderings learned from a WIP, and the NAME candidates STC hands to the model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sage.candidates import candidate_inventory
from sage.name_alignment import (
    NameModel,
    OlName,
    fold,
    wip_name_candidate_table,
    words,
)
from sage.ol_analysis import OlWord
from sage.vrs import VerseRef

RENDERINGS = ("Abramo", "Jakobo", "Moseso", "Davido", "Saulo", "Petero", "Johano", "Tobiaso")
ENDINGS = ("", "a", "u", "om")
FILLER = ("and", "the", "went", "to", "land", "said", "son", "of", "house", "city", "gave", "came", "him", "them")


def _corpus() -> tuple[dict[str, str], dict[str, set[str]], dict[str, OlName]]:
    """Eight names in 15 verses each, inflected with four endings, plus 100 verses without names."""
    names = {f"HEB:N{i}": OlName(f"HEB:N{i}", f"N{i}", rendering) for i, rendering in enumerate(RENDERINGS)}
    verses: dict[str, str] = {}
    occurrences: dict[str, set[str]] = {}
    verse = 0
    for i, rendering in enumerate(RENDERINGS):
        for j in range(15):
            verse += 1
            reference = f"GEN 1:{verse}"
            partner = (i + 1 + j % 3) % len(RENDERINGS)
            filler = " ".join(FILLER[(verse + k) % len(FILLER)] for k in range(6))
            text = f"{rendering}{ENDINGS[j % 4]} {filler}"
            keys = {f"HEB:N{i}"}
            if j % 2:
                text += f" {RENDERINGS[partner]}{ENDINGS[(j + 1) % 4]}"
                keys.add(f"HEB:N{partner}")
            verses[reference] = text
            occurrences[reference] = keys
    for k in range(100):
        verses[f"GEN 2:{k + 1}"] = " ".join(FILLER[(k * 3 + n) % len(FILLER)] for n in range(8))
    return verses, occurrences, names


def _verse_with(verses: dict[str, str], occurrences: dict[str, set[str]], key: str) -> str:
    """A verse whose only name is ``key``."""
    return next(ref for ref, keys in sorted(occurrences.items()) if keys == {key})


def test_learns_each_names_stem_and_inflection() -> None:
    """Every name gets a stem covering all its verses, and the shared endings are learned as inflection."""
    verses, occurrences, names = _corpus()
    model = NameModel(verses, occurrences, names)
    for i, rendering in enumerate(RENDERINGS):
        learned = model.renderings[f"HEB:N{i}"]
        assert learned.strong and learned.coverage == 1.0
        assert all(rendering.lower().startswith(stem) or stem.startswith(rendering.lower()[:4]) for stem in learned.stems)
    assert {"", "a", "u", "om"} <= model.suffixes
    assert set(model.status("GEN 1:1").values()) == {"OK"}


def test_flags_misspelled_swapped_and_missing_names() -> None:
    """A misspelling is a VARIANT, another name's rendering a SUBSTITUTION, a missing name ABSENT."""
    verses, occurrences, names = _corpus()
    jacob = _verse_with(verses, occurrences, "HEB:N1")
    moses = _verse_with(verses, occurrences, "HEB:N2")
    saul = _verse_with(verses, occurrences, "HEB:N4")
    verses[jacob] = verses[jacob].replace("Jakobo", "Jakbo")
    verses[moses] = verses[moses].replace("Moseso", "Davido")
    verses[saul] = verses[saul].replace("Saulo", "he")
    model = NameModel(verses, occurrences, names)
    assert model.status(jacob) == {"HEB:N1": "VARIANT"}
    assert model.status(moses) == {"HEB:N2": "SUBSTITUTION"}
    assert model.status(saul) == {"HEB:N4": "ABSENT"}
    by_kind = {candidate.kind: candidate for candidate in model.candidates([jacob, moses, saul])}
    assert by_kind["VARIANT"].words[0].startswith("jakbo")
    assert by_kind["SUBSTITUTION"].other_names == ("Davido",)
    assert "Davido" in by_kind["SUBSTITUTION"].question() and "Moseso" in by_kind["SUBSTITUTION"].question()
    assert set(by_kind) == {"VARIANT", "SUBSTITUTION", "ABSENT"}


def test_inflected_and_unknown_names_are_not_candidates() -> None:
    """A learned ending is no variant; a name seen in too few verses stays unchecked."""
    verses, occurrences, names = _corpus()
    jacob = _verse_with(verses, occurrences, "HEB:N1")
    verses[jacob] = verses[jacob].replace("Jakobo", "Jakoboom", 1) if "Jakobo " in verses[jacob] else verses[jacob]
    verses["GEN 3:1"] = "Zerah went to the land"
    occurrences["GEN 3:1"] = {"HEB:N9"}
    names["HEB:N9"] = OlName("HEB:N9", "N9", "Zerah")
    model = NameModel(verses, occurrences, names)
    assert model.status(jacob)["HEB:N1"] == "OK"
    assert model.status("GEN 3:1") == {"HEB:N9": "NOT_CHECKED"}
    assert model.candidates(["GEN 3:1"]) == []


def test_folding_keeps_vowel_signs_but_drops_diacritics() -> None:
    """Hebrew points and Latin accents are dropped; Malayalam vowel signs and virama are part of the word."""
    assert fold("בְּרֵאשִׁית") == "בראשית"
    assert fold("Élie") == "elie"
    assert words("യേശു പറഞ്ഞു") == ["യേശു", "പറഞ്ഞു"]
    assert words("Ісус, Ісуса!") == ["ісус", "ісуса"]


def test_name_candidates_become_stc_candidates_with_stable_ids() -> None:
    """Each NAME candidate gets an ID from its verse and name, and keeps its question."""
    row = {"wip_reference": "GEN 1:4", "name_key": "HEB:N1", "question": "Is the name rendered inconsistently?"}
    inventory = candidate_inventory(names=[row, dict(row)])
    assert len(inventory) == 1
    assert inventory[0]["kind"] == "NAME" and inventory[0]["candidate_id"].startswith("NM-GEN1:4-")
    assert inventory[0]["candidate_id"] == candidate_inventory(names=[row])[0]["candidate_id"]
    assert inventory[0]["question"] == row["question"]


@dataclass(frozen=True)
class _Record:
    """The parts of a WIP verse record the name table reads."""

    book: str
    reference: str
    payload: dict = field(hash=False, compare=False)


class _Analysis:
    """A MACULA stand-in: proper names per verse."""

    package_id = "TEST_PACKAGE"

    def __init__(self, occurrences: dict[str, set[str]], names: dict[str, OlName]) -> None:
        """One OL word per name in each verse."""
        self._table: dict[VerseRef, list[OlWord]] = {}
        for reference, keys in occurrences.items():
            ref = VerseRef("GEN", int(reference.split(":")[0].split()[1]), int(reference.split(":")[1]))
            self._table[ref] = [
                OlWord(f"{reference}!{n}", ref, names[key].lemma, ({"lemma": names[key].lemma, "type": "proper", "gloss": names[key].gloss},))
                for n, key in enumerate(sorted(keys))
            ]

    def verses(self, family: str) -> dict[VerseRef, list[OlWord]]:
        """Hebrew verses only."""
        return self._table if family == "HEB" else {}


def test_whole_wip_table_is_cached_by_content(tmp_path: Path) -> None:
    """The table maps WIP verses to STC candidates (no ABSENT), is written once, and is reused for unchanged text."""
    verses, occurrences, names = _corpus()
    jacob = _verse_with(verses, occurrences, "HEB:N1")
    verses[jacob] = verses[jacob].replace("Jakobo", "Jakbo")
    saul = _verse_with(verses, occurrences, "HEB:N4")
    verses[saul] = verses[saul].replace("Saulo", "he")
    records = [_Record("GEN", ref, {"body_text": text}) for ref, text in verses.items()]
    by_ref = {(int(r.reference.split(":")[0].split()[1]), int(r.reference.split(":")[1])): r for r in records}

    def lookup(refs):
        """Identity versification."""
        return [by_ref[(ref.chapter, ref.verse)] for ref in refs if (ref.chapter, ref.verse) in by_ref]

    analysis = _Analysis(occurrences, names)
    table = wip_name_candidate_table(analysis, records, lookup, cache_dir=tmp_path)
    assert [row["kind"] for row in table[jacob]] == ["VARIANT"]
    assert saul not in table  # ABSENT is not an STC candidate
    assert table[jacob][0]["gloss"] == "Jakobo" and table[jacob][0]["question"]
    cached = list(tmp_path.glob("*.json"))
    assert len(cached) == 1
    document = json.loads(cached[0].read_text(encoding="utf-8"))
    document["candidates"] = {"GEN 1:1": [{"kind": "MARKED"}]}
    cached[0].write_text(json.dumps(document), encoding="utf-8")
    assert wip_name_candidate_table(analysis, records, lookup, cache_dir=tmp_path) == {"GEN 1:1": [{"kind": "MARKED"}]}


def test_endings_are_measured_in_letters_not_code_points() -> None:
    """A Malayalam case ending of five code points (-ിന്റെ, two letters) is still inflection."""
    from sage.name_alignment import _letters

    assert _letters("ിന്റെ") == 2 and _letters("ക്കും") == 2 and _letters("om") == 2
