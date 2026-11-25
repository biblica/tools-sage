"""PCC P5b-2: top-down reference-list build (inventory, occurrences, realization, senses, selection).

Fabricated data only: invented words, invented lemmas and Strong's numbers, no Scripture text.
"""

from __future__ import annotations

import gzip
from collections import Counter

from sage.pcc.align import Alignment, AlignmentCache, Link, cache_key
from sage.pcc.discovery import SourceUnit
from sage.pcc.glossary import BiblicalTerm, read_biblical_term_entries
from sage.pcc.ids import concept_key
from sage.pcc.reflist import verify_reference_list, write_reference_list
from sage.pcc.rlbuild import (SOLO, Concept, Occurrence, Realization, _Rendered, build_reference_list,
                              concepts_from_biblical_terms, concepts_from_entries, find_occurrences, function_forms,
                              merge_inventory, ol_words, partition, realize, stem)
from sage.pcc.segment import measure_elisions, split_elisions, tokenize
from sage.pcc.traits import Affix, WipTraits
from sage.vrs import VerseRef


def _traits(suffixes=("s",)):
    """Cased fabricated traits with learned suffixes."""
    return WipTraits(letters=1, words=1, script="LATIN", unspaced=False, cased=True, letter_marks=(),
                     letter_inventory=(), punctuation_inventory=(), suffixes=tuple(Affix(s, 9) for s in suffixes))


# --- inventory ----------------------------------------------------------------------------------------


def test_biblical_terms_map_to_lemma_keys_or_term_ids():
    """One word (pointed Hebrew too) or one lemma per content word -> OL key; a phrase naming fewer -> BT id."""
    terms = [
        BiblicalTerm("מַחְסֶה-1", "HEB", (4268,), "AT", "shelter", ("00100100100002",)),
        BiblicalTerm("ζυγόν-1", "GRK", (9001,), "RE", "yoke", ()),
        BiblicalTerm("ζυγόν-2", "GRK", (9001,), "MI", "burden", ()),
        BiblicalTerm("οἶκος τοῦ ἄρτου", "GRK", (9002, 9003), "RE", "bread house", ()),
        BiblicalTerm("ἐν ζυγῷ, εἰς ζυγόν", "GRK", (9001,), "MI", "under the yoke", ("04000100100004",)),
        BiblicalTerm("Καφαρ", "GRK", (9004,), "PN", "Kaphar", ()),
    ]
    concepts, skipped = concepts_from_biblical_terms(terms)
    by_label = {c.label: c for c in concepts}
    assert by_label["מַחְסֶה"].kind == "OL" and by_label["מַחְסֶה"].anchor == ("HEB:4268",)
    assert by_label["οἶκος τοῦ ἄρτου"].anchor == ("GRK:9002", "GRK:9003")
    phrase = by_label["ἐν ζυγῷ, εἰς ζυγόν"]
    assert phrase.kind == "BT" and phrase.surfaces == (("εν", "ζυγω"), ("εισ", "ζυγον"))
    merged = merge_inventory(concepts)
    yoke = merged[concept_key("OL", ["GRK:9001"])]
    assert yoke.sources == ("BT:ζυγόν-1", "BT:ζυγόν-2") and len(merged) == 5
    _, skipped = concepts_from_biblical_terms(terms, categories=["PN"])
    assert skipped == Counter(CATEGORY_OFF=5)
    assert ol_words("דְּבַר־יְהוָה, (x)") == ["דְּבַר", "יְהוָה", "x"]


def test_inventory_union_keeps_active_and_drops_what_the_base_dropped():
    """A PROPOSED source and an ACTIVE one merge to ACTIVE; a base DROPPED entry is returned as dropped."""
    proposed = Concept("OL", ("GRK:1",), "one", "KEY_CONCEPT", "PROPOSED", ("KEY_CONCEPTS",))
    active = Concept("OL", ("GRK:1",), "uno", "BE", "ACTIVE", ("BT:uno",))
    merged = merge_inventory([proposed], [active])
    assert merged[proposed.key].status == "ACTIVE" and merged[proposed.key].label == "one"
    base = [{"concept_key": proposed.key, "anchor": {"kind": "OL", "value": ["GRK:1"]}, "label": "one",
             "category": "BE", "status": "DROPPED"},
            {"concept_key": concept_key("WORDING", "en|lamp stand"), "anchor": {"kind": "WORDING", "value": ["en|lamp stand"]},
             "label": "lamp stand", "category": "DECLARED", "status": "ACTIVE", "notes": "team"}]
    kept, dropped = concepts_from_entries(base, "INHERITED:x@1")
    assert dropped == {proposed.key} and kept[0].key == concept_key("WORDING", "en|lamp stand")
    assert kept[0].notes == "team"


def test_read_biblical_term_entries_reads_strongs_categories_and_references(tmp_path):
    """Strong's lists (with suffix letters) and word-level references are read; nothing is written back."""
    path = tmp_path / "BiblicalTerms.xml"
    path.write_text("""<?xml version="1.0" encoding="UTF-8"?><BiblicalTermsList>
<Term Id="ζυγόν-1"><Strong>G9001</Strong><Category>RE</Category><Language>greek</Language><Gloss>yoke</Gloss>
<References><Verse>04000100100004</Verse></References></Term>
<Term Id="קַו"><Strong>H0218b, H0219</Strong><Category>MI</Category><Language>aramaic</Language></Term>
</BiblicalTermsList>""", encoding="utf-8")
    first, second = read_biblical_term_entries(path)
    assert (first.name, first.family, first.strongs, first.references) == ("ζυγόν", "GRK", (9001,), ("04000100100004",))
    assert (second.family, second.strongs, second.category, second.gloss) == ("HEB", (218, 219), "MI", "")


# --- occurrences ----------------------------------------------------------------------------------------


class _W:
    """Stand-in for an ``OlWord``."""

    def __init__(self, word_id, text, *segments):
        """Keep id, text and segments."""
        self.word_id, self.text, self.segments = word_id, text, segments


def _seg(strong, lemma, pos="noun"):
    """One fabricated MACULA segment."""
    return {"strong": strong, "lemma": lemma, "pos": pos, "gloss": lemma}


class _Analysis:
    """Fabricated Greek verses MAT 1:1-1:4."""

    def __init__(self, verses):
        """Keep {VerseRef: [words]}."""
        self._verses = verses

    def verses(self, family):
        """Fabricated verses of the Greek family only."""
        return self._verses if family == "GRK" else {}


class _Schema:
    """Identity versification."""

    schema_id, canonical_id, mappings = "id", "org", ()

    def local_to_canonical(self, ref):
        """Same reference."""
        return frozenset({ref})


class _Group:
    """Stand-in for an ``OlGroup``."""

    def __init__(self, *refs):
        """Keep refs."""
        self.refs = refs


def test_multi_lemma_concepts_occur_only_inside_one_phrase_group():
    """Both lemmas in a short window count once; with groups given, only a window inside one group counts."""
    from sage.pcc.rlbuild import ol_words_by_unit
    verses = {VerseRef("MAT", 1, 1): [_W("MAT 1:1!1", "a", _seg("10", "οἶκος")), _W("MAT 1:1!2", "b", _seg("11", "ἄρτος"))],
              VerseRef("MAT", 1, 2): [_W("MAT 1:2!1", "b", _seg("11", "ἄρτος")), _W("MAT 1:2!2", "c", _seg("12", "καί", "conj")),
                                      _W("MAT 1:2!3", "a", _seg("10", "οἶκος"))]}
    units = [SourceUnit("u1", "MAT 1:1", ("MAT 1:1",), "x"), SourceUnit("u2", "MAT 1:2", ("MAT 1:2",), "x")]
    words = ol_words_by_unit(units, _Analysis(verses), _Schema())
    index: dict[str, list] = {}
    for unit, items in words.items():
        for i, word in enumerate(items):
            for key in word.keys:
                index.setdefault(key, []).append((unit, i))
    concept = Concept("OL", ("GRK:10", "GRK:11"), "house of bread", "RE", "ACTIVE", ("BT:x",))
    assert [o.words for o in find_occurrences(concept, index, words, {})] == [("MAT 1:1!1", "MAT 1:1!2"),
                                                                               ("MAT 1:2!1", "MAT 1:2!3")]
    groups = {"MAT 1:1!1": [_Group("MAT 1:1!1", "MAT 1:1!2")], "MAT 1:2!1": [_Group("MAT 1:2!1", "MAT 1:2!2")]}
    assert [o.unit for o in find_occurrences(concept, index, words, {}, groups)] == ["u1"]


# --- realization ----------------------------------------------------------------------------------------


def _alignment(text, links, hints=None, unit="u1"):
    """An alignment of one unit: ``links`` = [(token, word ref, key)]."""
    return Alignment({unit: tokenize(text)}, {unit: [Link(t, r, "transitive", 1.0, k) for t, r, k in links]}, {},
                     {unit: hints or {}})


def _span(result, alignment, unit="u1"):
    """Raw wording of a realization."""
    tokens = alignment.tokens[unit]
    return " ".join(t.text for t in tokens[result.first:result.last + 1])


def test_realization_takes_only_the_concepts_own_segment():
    """A prefixed word linked as 'and the lamp' realizes the noun segment only."""
    alignment = _alignment("and the lamp shone", [(0, "W1", "HEB:1"), (1, "W1", "HEB:2"), (2, "W1", "HEB:50"),
                                                   (3, "W2", "HEB:60")])
    occ = Occurrence("u1", ("W1",), frozenset({"HEB:50"}))
    result = realize(occ, alignment, frozenset(), {}, "and the lamp shone")
    assert isinstance(result, Realization) and _span(result, alignment) == "lamp"


def test_function_only_no_realization_and_edge_trim():
    """A pronoun rendering is function_only; nothing linked is no_realization; a chunked copula is trimmed."""
    text = "then he spoke"
    alignment = _alignment(text, [(1, "W1", "GRK:5")])
    occ = Occurrence("u1", ("W1",), frozenset({"GRK:5"}))
    assert realize(occ, alignment, frozenset({"he"}), {}, text) == "function_only"
    assert realize(Occurrence("u1", ("W9",), frozenset({"GRK:9"})), alignment, frozenset(), {}, text) == "no_realization"
    text = "the word is Ruler"
    alignment = _alignment(text, [(2, "W1", "GRK:5"), (3, "W1", "GRK:5")])
    forms = {"is": Counter({"GRK:1510": 500, "GRK:5": 3}), "ruler": Counter({"GRK:5": 40, SOLO: 20})}
    result = realize(Occurrence("u1", ("W1",), frozenset({"GRK:5"})), alignment, frozenset(), forms, text)
    assert _span(result, alignment) == "Ruler"


def test_spans_stop_at_clause_punctuation_and_other_content_words():
    """Two links of one word across a sentence end, or around another content word, keep only one run."""
    text = "Ruler. Praise the Ruler"
    alignment = _alignment(text, [(0, "W1", "GRK:5"), (3, "W1", "GRK:5")])
    result = realize(Occurrence("u1", ("W1",), frozenset({"GRK:5"})), alignment, frozenset(), {}, text)
    assert _span(result, alignment) == "Ruler" and result.first == 0
    text = "Ruler bread Ruler"
    alignment = _alignment(text, [(0, "W1", "GRK:5"), (1, "W2", "GRK:7"), (2, "W1", "GRK:5")])
    result = realize(Occurrence("u1", ("W1",), frozenset({"GRK:5"})), alignment, frozenset(), {}, text,
                     content_keys={"GRK:7": True, "GRK:5": True})
    assert result.last - result.first == 0


def test_neighbor_extension_needs_a_strong_hint_and_no_other_word():
    """'Judean elders': 'elders' joins with a strong hint; a weak hint or a form another word explains does not."""
    text = "the Judean elders came"
    links = [(1, "W1", "GRK:20")]
    strong = _alignment(text, links, {2: ("W1", "GRK:20", 0.8)})
    occ = Occurrence("u1", ("W1",), frozenset({"GRK:20"}))
    assert _span(realize(occ, strong, frozenset(), {}, text), strong) == "Judean elders"
    weak = _alignment(text, links, {2: ("W1", "GRK:20", 0.3)})
    assert _span(realize(occ, weak, frozenset(), {}, text), weak) == "Judean"
    forms = {"elders": Counter({"GRK:30": 50})}
    assert _span(realize(occ, strong, frozenset(), forms, text, frozenset({"GRK:20", "GRK:30"})), strong) == "Judean"


def test_function_forms_are_measured_from_the_alignment():
    """Non-content top lemma, auxiliary-like spread, and never-alone companions are function forms."""
    content = {f"K:{i}": True for i in range(40)} | {"K:art": False}
    linked = {
        "the": Counter({"K:art": 90, "K:1": 10}),
        "shall": Counter({f"K:{i}": 3 for i in range(25)}) | Counter({SOLO: 2}),
        "o": Counter({"K:1": 30, "K:2": 2, "K:3": 2, "K:4": 2, "K:5": 2}),
        "leaders": Counter({f"K:{i}": 3 for i in range(25)}) | Counter({SOLO: 30}),
        "lamp": Counter({"K:7": 50, SOLO: 40}),
    }
    assert function_forms(linked, content) == frozenset({"the", "shall", "o"})


# --- senses ---------------------------------------------------------------------------------------------


def _r(verse, wording, case, stems=None, order=None):
    """One rendered occurrence."""
    head = wording.split(" ")[0].casefold()
    return _Rendered(verse, order if order is not None else int(verse.split(":")[1]), wording.casefold(), wording,
                     stem(head, ["s"]), stems or stem(head, ["s"]), case, "gold", ())


def test_stem_strips_to_a_fixpoint():
    """Learned suffixes are stripped repeatedly, never below three letters."""
    assert stem("lampers", ["s", "er"]) == stem("lamper", ["s", "er"]) == "lamp"
    assert stem("gods", ["s", "d"]) == "god"


def test_senses_split_by_case_and_recurring_wording_and_pool_the_rest():
    """Upper/lower split; a sentence start joins its stem's usual case; a recurring phrase is its own sense."""
    rendered = ([_r(f"MAT 1:{v}", "Breath", "UPPER") for v in range(1, 5)]
                + [_r(f"MAT 2:{v}", "breath", "LOWER") for v in range(1, 4)]
                + [_r("MAT 3:1", "Breath", "")]
                + [_r(f"MAT 4:{v}", "Judean elders", "UPPER", "judean elder") for v in range(1, 4)]
                + [_r("MAT 5:1", "Judean elders", "UPPER", "judean elder")]
                + [_r(f"MAT 6:{v}", "Judeans", "UPPER") for v in range(1, 4)]
                + [_r("MAT 7:1", "Judean scribes", "UPPER", "judean scribe")]
                + [_r("MAT 8:1", "wind", "LOWER")])
    senses = partition("CPT-0000000000000000", rendered, min_verses=3)
    table = {s["label"]: (s["kind"], s["verses"], [w["wording"] for w in s["wordings"]]) for s in senses}
    assert table["Breath"] == ("SENSE", 5, ["Breath"])
    assert table["breath"] == ("SENSE", 3, ["breath"])
    assert table["Judean elders"] == ("SENSE", 4, ["Judean elders"])
    assert table["Judeans"] == ("SENSE", 4, ["Judeans", "Judean scribes"])
    assert table["(other renderings)"] == ("OTHER", 1, ["wind"])
    assert senses[-1]["kind"] == "OTHER"
    assert partition("CPT-0000000000000000", list(reversed(rendered)), min_verses=3) == senses


# --- the build ------------------------------------------------------------------------------------------


def _fixture():
    """Four verses; 'lamp' (GRK:50) in three, 'house of bread' (GRK:10+11) in three, a name only in one."""
    verses = {}
    texts = {}
    plan = {
        1: ("Lamp of the house of bread", [("Lamp", 0), ("of", None), ("the", None),
                                           ("house", 1), ("of", None), ("bread", 2)]),
        2: ("A lamp, said Kaphar, in the house of bread", [("A", None), ("lamp", 0), ("said", 3), ("Kaphar", 4),
                                                            ("in", None), ("the", None), ("house", 1), ("of", None),
                                                            ("bread", 2)]),
        3: ("Then the lamp stood up", [("Then", None), ("the", None), ("lamp", 0), ("stood", 5), ("up", None)]),
        4: ("He stood by the house of bread", [("He", 6), ("stood", 5), ("by", None), ("the", None), ("house", 1),
                                               ("of", None), ("bread", 2)]),
    }
    lemmas = [("50", "λύχνος", "noun"), ("10", "οἶκος", "noun"), ("11", "ἄρτος", "noun"), ("12", "λέγω", "verb"),
              ("13", "Καφαρ", "noun"), ("14", "ἵστημι", "verb"), ("15", "αὐτός", "pronoun")]
    links, units = {}, []
    for v, (text, tokens) in plan.items():
        used = sorted({w for _, w in tokens if w is not None})
        verses[VerseRef("MAT", 1, v)] = [_W(f"MAT 1:{v}!{i + 1}", lemmas[w][1], _seg(*lemmas[w])) for i, w in enumerate(used)]
        refs = {w: f"MAT 1:{v}!{i + 1}" for i, w in enumerate(used)}
        links[f"u{v}"] = [Link(i, refs[w], "gold", 1.0, f"GRK:{lemmas[w][0]}") for i, (_, w) in enumerate(tokens)
                          if w is not None]
        units.append(SourceUnit(f"u{v}", f"MAT 1:{v}", (f"MAT 1:{v}",), text))
        texts[v] = text
    alignment = Alignment({u.unit_id: tokenize(u.text) for u in units}, links, {"tokens": 0}, {})
    return units, alignment, _Analysis(verses)


def test_build_realizes_selects_and_reports_left_out_concepts(tmp_path):
    """Entries for recurring concepts, a declared phrase anchored on its lemmas, and counted left-outs."""
    units, alignment, analysis = _fixture()
    terms = [BiblicalTerm("λύχνος", "GRK", (50,), "RE", "lamp", ()),
             BiblicalTerm("Καφαρ", "GRK", (13,), "PN", "Kaphar", ()),
             BiblicalTerm("θρόνος", "GRK", (77,), "RE", "throne", ())]
    concepts, skipped = concepts_from_biblical_terms(terms)
    result = build_reference_list(units, alignment, analysis, _Schema(), traits=_traits(), language_tag="xx",
                                  inventory=merge_inventory(concepts), skipped=skipped, min_verses=3,
                                  declared=[("house of bread", ("house", "of", "bread"), 1),
                                            ("stood up", ("stood", "up"), 2), ("silver lamp", ("silver", "lamp"), 3)])
    by_label = {e["label"]: e for e in result.entries}
    lamp = by_label["λύχνος"]
    assert [s["label"] for s in lamp["senses"]] == ["lamp"]  # "Lamp" at the verse start joins "lamp"
    assert lamp["realization"]["occurrences"] == 3 and lamp["verses"] == 3 and lamp["origin"] == "BIBLICAL_TERMS"
    house = by_label["house of bread"]
    assert house["anchor"] == {"kind": "OL", "value": ["GRK:10", "GRK:11"]}
    assert house["senses"][0]["label"] == "house of bread" and house["senses"][0]["verses"] == 3
    assert by_label["silver lamp"]["anchor"]["kind"] == "WORDING" and by_label["silver lamp"]["senses"] == []
    assert "stood up" not in by_label  # anchored on ἵστημι, which recurs in two verses only
    assert result.left_out["NOT_IN_REFERENCE"] == 1 and result.left_out["BELOW_RECURRENCE"] == 2
    assert result.declared_problems == ["line 3: not found in the reference"]
    again = build_reference_list(units, alignment, analysis, _Schema(), traits=_traits(), language_tag="xx",
                                 inventory=merge_inventory(concepts), skipped=skipped, min_verses=3,
                                 declared=[("house of bread", ("house", "of", "bread"), 1),
                                           ("stood up", ("stood", "up"), 2), ("silver lamp", ("silver", "lamp"), 3)])
    assert again.entries == result.entries
    write_reference_list(tmp_path / "rl", rl_id="syn-0123abcd", version=1, title="Syn",
                         reference={"project_id": "SYN", "edition": "Syn", "language_tag": "xx",
                                    "content_sha256": "c" * 64, "versification_id": "id"},
                         license={"license_id": "SYNTHETIC", "local_only": False, "note": ""},
                         build={"mode": "SCRATCH", "summary": result.summary()}, entries=result.entries,
                         created_utc="2026-11-25T00:00:00Z")
    assert verify_reference_list(tmp_path / "rl")["counts"]["entries"] == len(result.entries)


# --- aligner additions ------------------------------------------------------------------------------------


def test_elided_prefixes_are_measured_and_split():
    """A short prefix with an apostrophe-letter splits off only when its remainders are frequent words."""
    words = [f"m{c}ra" for c in "abcdefghijkl"]
    text = " ".join(words * 3) + " " + " ".join(f"l'{w}" for w in words) + " qu'x b'bbb"
    tokens = tokenize(text, letter_marks=("'",))
    prefixes = measure_elisions([tokens], ("'",))
    assert prefixes == frozenset({"l'"})
    split = split_elisions(tokens, prefixes, ("'",))
    pieces = [t for t in split if t.start >= text.index("l'")]
    assert [t.text for t in pieces[:2]] == ["l'", "mara"] and text[pieces[1].start:pieces[1].end] == "mara"
    assert any(t.text == "qu'x" for t in split)


def test_alignment_cache_round_trips_and_ignores_bad_files(tmp_path):
    """Links, hints and stats come back; tokens are rebuilt from the units; a corrupt file means realign."""
    units = [SourceUnit("u1", "MAT 1:1", ("MAT 1:1",), "Alpha beta")]
    alignment = Alignment({"u1": tokenize("Alpha beta")}, {"u1": [Link(0, "W1", "gold", 1.0, "GRK:1")]},
                          {"tokens": 2}, {"u1": {1: ("W2", "GRK:2", 0.7)}})
    cache = AlignmentCache(tmp_path)
    key = cache_key("a" * 64, "P")
    first = cache.put(key, alignment).read_bytes()
    assert cache.get(key, units, cased=True, letter_marks=()) == alignment
    assert cache.put(key, alignment).read_bytes() == first
    (tmp_path / f"{key}.json.gz").write_bytes(gzip.compress(b"{not json"))
    assert cache.get(key, units, cased=True, letter_marks=()) is None
    assert cache.get("missing", units, cased=True, letter_marks=()) is None
