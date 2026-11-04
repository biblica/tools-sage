"""PCC phase P3: phrases.txt, discovery, occurrence tracing, nested dedupe, unfound phrases."""

from __future__ import annotations

from sage.pcc.contracts import validate_record
from sage.pcc.discovery import Seed, SourceUnit, discover
from sage.pcc.phrases import parse_phrases
from sage.pcc.traits import measure_traits

SHA = "b" * 64
VERSES = [
    "He told them to stand firm in the faith, and the faith held.",
    "Stand firm, for the lamp of the Lord is bright.",
    "Keep the promise and stand firm in the faith.",
    "A light weight rested on him; the lamp was bright.",
    "The café stood quiet.",
]


def _units(texts=VERSES):
    """Implement units."""
    return [SourceUnit(f"u{i}", f"GEN 1:{i + 1}", (f"GEN 1:{i + 1}",), t) for i, t in enumerate(texts)]


def _run(seeds=(), texts=VERSES, **kw):
    """Implement run."""
    traits = measure_traits(texts)
    return discover(_units(texts), source_corpus_id="SRC", source_sha256=SHA, traits=traits, seeds=seeds, **kw)


def _forms(result):
    """Implement forms."""
    return {e["normalized_source_form"]: e for e in result.expressions}


def test_discovers_recurring_phrases_and_validates_records():
    """Verify that discovers recurring phrases and validates records."""
    result = _run()
    forms = _forms(result)
    assert "stand firm" in forms
    assert "lamp" in forms and "faith" in forms
    assert "stand firm" in forms and forms["stand firm"]["origin"] == "SOURCE_DISCOVERY"
    for e in result.expressions:
        validate_record("expression", e)
    for o in result.occurrences:
        validate_record("occurrence", o)


def test_every_occurrence_reconstructs_raw_text():
    """Verify that every occurrence reconstructs raw text."""
    result = _run()
    texts = {u.unit_id: u.text for u in _units()}
    assert result.occurrences
    for o in result.occurrences:
        assert texts[o["source_unit_id"]][o["body_start"]:o["body_end"]] == o["source_text_span"]


def test_single_occurrence_candidates_are_not_discovered():
    """Verify that single occurrence candidates are not discovered."""
    assert "quiet" not in _forms(_run())


def test_local_phrase_never_pruned_and_unfound_reported():
    """Verify that local phrase never pruned and unfound reported."""
    seeds = [
        Seed("keep the promise", ("keep", "the", "promise"), "LOCAL_INPUT", line=3),
        Seed("never found here", ("never", "found", "here"), "LOCAL_INPUT", line=7),
    ]
    result = _run(seeds)
    assert _forms(result)["keep the promise"]["origin"] == "LOCAL_INPUT"
    assert [s.line for s in result.unfound] == [7]
    assert "never found here" not in _forms(result)


def test_curated_origin_and_senses_kept():
    """Verify that curated origin and senses kept."""
    sense = {"sense_id": "SENSE-X", "label": "x", "discriminator": "d", "review_state": "CURATED"}
    result = _run([Seed("lamp", ("lamp",), "AUTHORIZED_REFERENCE", "TERM", (sense,))])
    expr = _forms(result)["lamp"]
    assert expr["origin"] == "AUTHORIZED_REFERENCE" and expr["senses"] == [sense]


def test_same_wording_different_nfc_forms_match():
    """Verify that same wording different nfc forms match."""
    texts = ["café here", "café there"]
    forms = _forms(_run(texts=texts))
    assert forms["café"]["origin"] == "SOURCE_DISCOVERY"
    assert len([o for o in _run(texts=texts).occurrences]) == 2


def test_nested_phrase_deduped_for_display_but_kept():
    """Verify that nested phrase deduped for display but kept."""
    result = _run()
    forms = _forms(result)
    assert "stand firm in the faith" in forms
    assert "faith" in forms  # nested evidence stays
    ids = {e["expression_id"]: e["normalized_source_form"] for e in result.expressions}
    for sub, parent in result.nested_in.items():
        assert sub in ids and parent in ids and ids[sub] != ids[parent]


def test_punctuation_blocks_automatic_ngrams():
    """Verify that punctuation blocks automatic ngrams."""
    texts = ["red, green blue", "red, green blue"]
    forms = _forms(_run(texts=texts))
    assert "green blue" in forms and "red green" not in forms


def test_unspaced_source_skips_automatic_discovery():
    """Verify that unspaced source skips automatic discovery."""
    texts = ["你好世界"] * 3
    result = _run(texts=texts)
    assert result.auto_discovery == "SKIPPED_UNSPACED" and not result.expressions
    seeds = [Seed("世界", ("世", "界"), "LOCAL_INPUT", line=1)]
    assert len(_run(seeds, texts=texts).occurrences) == 3


def test_deterministic():
    """Verify that deterministic."""
    assert _run().occurrences == _run().occurrences


def test_phrases_file_problems_have_line_numbers():
    """Verify that phrases file problems have line numbers."""
    traits = measure_traits(VERSES)
    phrases, problems = parse_phrases("# note\n\nStand Firm\n!!!\nstand  firm\nkeep the promise\n", traits)
    assert [(p.line, p.tokens) for p in phrases] == [(3, ("stand", "firm")), (6, ("keep", "the", "promise"))]
    assert [(p.line, p.reason) for p in problems] == [(4, "NO_LETTERS"), (5, "DUPLICATE_OF_LINE_3")]
