"""PCC phase P4: sense evidence from original-language lemmas, sense splits, groups, unresolved."""

from __future__ import annotations

from sage.pcc.discovery import SourceUnit, discover
from sage.pcc.sense import OlItem, assign_senses
from sage.pcc.traits import measure_traits

SHA = "e" * 64
WEIGHT = OlItem("G1", "baros", "1", "weight")
LAMP = OlItem("G2", "phos", "2", "light")
OTHER = OlItem("G9", "other", "9", "other")


def _setup(rows):
    """rows: (english text, [OlItem...]) per verse."""
    units = [SourceUnit(f"u{i}", f"MAT 1:{i + 1}", (f"MAT 1:{i + 1}",), t) for i, (t, _) in enumerate(rows)]
    ol = {f"u{i}": items for i, (_, items) in enumerate(rows)}
    found = discover(units, source_corpus_id="S", source_sha256=SHA, traits=measure_traits(u.text for u in units))
    return found, ol


def _assign(rows, **kw):
    found, ol = _setup(rows)
    return assign_senses(found.expressions, found.occurrences, ol, scope_policy_sha256="f" * 64, **kw)


def _by_form(result):
    return {e["normalized_source_form"]: e for e in result.expressions}


def _occ(result, expr):
    return [o for o in result.occurrences if o["expression_id"] == expr["expression_id"]]


def test_one_lemma_confirms_one_sense_with_evidence():
    rows = [("a light yoke", [WEIGHT, OTHER]), ("a light load", [WEIGHT]), ("a light burden", [WEIGHT, OTHER])]
    result = _assign(rows)
    expr = _by_form(result)["light"]
    assert len(expr["senses"]) == 1 and "baros" in expr["senses"][0]["discriminator"]
    occs = _occ(result, expr)
    assert {o["sense_state"] for o in occs} == {"CONFIRMED"}
    assert occs[0]["sense_evidence"][0].startswith("SENSE-OL-LEMMA:baros")
    assert [g["status"] for g in result.groups if g["expression_id"] == expr["expression_id"]] == ["ELIGIBLE"]


def test_divergent_lemmas_split_into_separate_groups_without_cross_obligation():
    rows = [("light weight", [WEIGHT]), ("light load", [WEIGHT]), ("light lamp", [LAMP]), ("light day", [LAMP])]
    result = _assign(rows)
    expr = _by_form(result)["light"]
    assert len(expr["senses"]) == 2
    groups = [g for g in result.groups if g["expression_id"] == expr["expression_id"]]
    assert len(groups) == 2 and {g["confirmed_occurrences"] for g in groups} == {2}
    assert len({g["sense_id"] for g in groups}) == 2


def test_single_confirmed_occurrence_group_is_informational():
    rows = [("light weight", [WEIGHT]), ("light load", [WEIGHT]), ("light lamp", [LAMP]), ("light day", [OTHER])]
    result = _assign(rows, min_support=2)
    groups = {g["sense_id"]: g for g in result.groups if g["expression_id"] == _by_form(result)["light"]["expression_id"]}
    assert len(groups) == 1  # LAMP has support 1: no sense of its own
    unresolved = [u for u in result.unresolved if u["expression_id"] == _by_form(result)["light"]["expression_id"]]
    assert unresolved[0]["code"] == "PC20" and unresolved[0]["unresolved_occurrences"] == 2


def test_ambiguity_and_missing_alignment_stay_unresolved_never_majority():
    rows = [("light weight", [WEIGHT, LAMP]), ("light load", [WEIGHT]), ("light lamp", [LAMP]), ("light day", [LAMP]),
            ("light road", [WEIGHT])]
    found, ol = _setup(rows)
    del ol["u4"]
    result = assign_senses(found.expressions, found.occurrences, ol, scope_policy_sha256="f" * 64)
    states = {o["canonical_ref"]: (o["sense_state"], o["sense_evidence"][0].split(":")[0])
              for o in _occ(result, _by_form(result)["light"])}
    assert states["MAT 1:1"][1] == "AMBIGUOUS_LEMMAS" and states["MAT 1:1"][0] == "UNRESOLVED"
    assert states["MAT 1:5"] == ("UNRESOLVED", "NO_OL_ALIGNMENT")


def test_function_lemma_present_everywhere_is_not_evidence():
    everywhere = OlItem("G0", "kai", "0", "and")
    rows = [(f"light verse {i}", [everywhere]) for i in range(3)] + [(f"other text {i}", [everywhere]) for i in range(30)]
    result = _assign(rows)
    expr = _by_form(result)["light"]
    assert {o["sense_state"] for o in _occ(result, expr)} == {"UNRESOLVED"}


def test_polysemous_lemma_is_unresolved():
    rows = [("spirit one", [WEIGHT]), ("spirit two", [WEIGHT])]
    result = _assign(rows, polysemous={"G1"})
    assert {o["sense_state"] for o in _occ(result, _by_form(result)["spirit"])} == {"UNRESOLVED"}
    assert _occ(result, _by_form(result)["spirit"])[0]["sense_evidence"] == ["POLYSEMOUS_LEMMA:G1"]


def test_curated_senses_are_kept():
    from sage.pcc.discovery import Seed
    sense = {"sense_id": "SENSE-C", "label": "c", "discriminator": "d", "review_state": "CURATED"}
    units = [SourceUnit("u0", "MAT 1:1", ("MAT 1:1",), "the lamp"), SourceUnit("u1", "MAT 1:2", ("MAT 1:2",), "a lamp")]
    found = discover(units, source_corpus_id="S", source_sha256=SHA, traits=measure_traits(["the lamp", "a lamp"]),
                     seeds=[Seed("lamp", ("lamp",), "AUTHORIZED_REFERENCE", "TERM", (sense,))])
    result = assign_senses(found.expressions, found.occurrences, {}, scope_policy_sha256="f" * 64)
    expr = _by_form(result)["lamp"]
    assert expr["senses"] == [sense]
    assert {o["sense_id"] for o in _occ(result, expr)} == {"SENSE-C"}


def test_deterministic_and_inputs_not_mutated():
    rows = [("light weight", [WEIGHT]), ("light load", [WEIGHT]), ("light lamp", [LAMP]), ("light day", [LAMP])]
    found, ol = _setup(rows)
    before = [dict(o) for o in found.occurrences]
    a = assign_senses(found.expressions, found.occurrences, ol, scope_policy_sha256="f" * 64)
    b = assign_senses(found.expressions, found.occurrences, ol, scope_policy_sha256="f" * 64)
    assert a.occurrences == b.occurrences and a.groups == b.groups
    assert found.occurrences == before
