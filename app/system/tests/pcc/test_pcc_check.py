"""PCC P6: forward consistency check. Fabricated texts and the handover's fictional synthetic corpus only."""

from __future__ import annotations

import json
import random
from pathlib import Path

from sage.pcc.align import DirectModel
from sage.pcc.check import (CheckInput, Morphology, pair_verses, run_check, side_tokens, stop_forms,
                            train_pair_model)
from sage.pcc.contracts import validate_record
from sage.pcc.discovery import SourceUnit
from sage.pcc.glossary import _rule
from sage.pcc.ids import group_id
from sage.vrs import VerseRef

SYNTHETIC = Path(__file__).parent / "fixtures" / "handover" / "synthetic"
SHA = "a" * 64


class _Schema:
    """Identity versification."""

    def local_to_canonical(self, ref):
        """Same verse."""
        return frozenset({ref})


class _Map:
    """Versification that maps WIP GEN 1:9 onto canonical GEN 1:8 (a bridge on the WIP side)."""

    def local_to_canonical(self, ref):
        """Shift one verse."""
        return frozenset({VerseRef("GEN", 1, 8)}) if ref == VerseRef("GEN", 1, 9) else frozenset({ref})


def _units(prefix, texts):
    """Units ``<prefix><n>`` at GEN 1:n."""
    return [SourceUnit(f"{prefix}{n}", f"GEN 1:{n}", (f"GEN 1:{n}",), t) for n, t in texts]


def _occurrences(units, wording, gid="G", sense="SENSE-1", state="CONFIRMED", expr="EXPR-1"):
    """Every occurrence of ``wording`` in the SOURCE units, in one group."""
    occs = []
    for u in units:
        start = u.text.casefold().find(wording)
        if start >= 0:
            occs.append({"occurrence_id": f"OCC-{u.unit_id}", "expression_id": expr, "source_unit_id": u.unit_id,
                         "canonical_ref": u.canonical_ref, "body_start": start, "body_end": start + len(wording),
                         "source_text_span": u.text[start:start + len(wording)], "sense_id": sense, "sense_state": state})
    return occs


def _token_occurrences(units, token):
    """Occurrences of one whole token."""
    from sage.pcc.segment import tokenize
    occs = []
    for u in units:
        for t in tokenize(u.text):
            if t.norm == token:
                occs.append({"occurrence_id": f"OCC-{u.unit_id}", "expression_id": "EXPR-1", "source_unit_id": u.unit_id,
                             "canonical_ref": u.canonical_ref, "body_start": t.start, "body_end": t.end,
                             "source_text_span": t.text, "sense_id": "SENSE-1", "sense_state": "CONFIRMED"})
                break
    return occs


def _input(source, target, occs, *, rules=(), model=None, morph=None, groups=None, schema=None, expressions=None):
    """A CheckInput over fabricated units."""
    s_units, t_units = {u.unit_id: u for u in source}, {u.unit_id: u for u in target}
    pairs, unit_pair = pair_verses(source, target, _Schema(), schema or _Schema())
    s_side = side_tokens(pairs, s_units, "source", cased=True)
    t_side = side_tokens(pairs, t_units, "target", cased=True)
    model = model or train_pair_model(pairs, s_side, t_side)
    gid = group_id("CPT-0000000000000001", "SENSE-1")
    groups = groups if groups is not None else [{"group_id": gid, "expression_id": "EXPR-1", "sense_id": "SENSE-1",
                                                 "state": "CONFIRMED"}]
    exprs = expressions or [{"expression_id": "EXPR-1", "source_surface": "stand firm",
                             "senses": [{"sense_id": "SENSE-1", "discriminator": "original-language lemma x (BE; CPT)"}]}]
    return CheckInput("RUN-1", SHA, s_units, t_units, pairs, unit_pair, s_side, t_side, model, morph or Morphology(),
                      exprs, occs, groups, {r["rule_id"]: r for r in rules},
                      stop_forms(t_side), stop_forms(s_side)), gid


def _approve(gid, form, state="APPROVED", effect="ACCEPT", scope=None):
    """One glossary rule."""
    return _rule(gid, "en", form, effect, state, scope or {"level": "SECG", "identifier": gid}, "team", [], "t", "2026-11-25")


def _synthetic(ids):
    """Units of the fictional handover corpus (invented sentences, GEN.1.x ids only)."""
    rows = {}
    for side in ("source", "target"):
        rows[side] = [json.loads(line) for line in (SYNTHETIC / f"{side}.jsonl").read_text(encoding="utf-8").splitlines()]
    pick = lambda side: [(int(r["canonical_ref"].split(".")[-1]), r["scripture_body"]) for r in rows[side]  # noqa: E731
                         if int(r["canonical_ref"].split(".")[-1]) in ids]
    return _units("S", pick("source")), _units("T", pick("target"))


def _code(result, code):
    """Findings with ``code``."""
    return [f for f in result.findings if f["code"] == code]


def test_synthetic_s1_unapproved_variant_is_pc10_until_approved():
    """Handover syn-S1 / AT04 and AT02: a proposed third form is PC10; approving it gives PC01."""
    source, target = _synthetic({1, 2, 3})
    occs = _occurrences(source, "stand firm")
    gid = group_id("CPT-0000000000000001", "SENSE-1")
    rules = [_approve(gid, "remain steadfast"), _approve(gid, "not to give up", state="PROPOSED")]
    inp, gid = _input(source, target, occs, rules=rules)
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC10"
    pc10 = _code(result, "PC10")[0]
    assert pc10["evidence"][0].startswith("remain steadfast (2)") and any("not to give up" in e for e in pc10["evidence"])
    for record in result.findings:
        validate_record("finding", record)
    rules[1] = _approve(gid, "not to give up")
    inp, gid = _input(source, target, occs, rules=rules)
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC01" and not _code(result, "PC10")


def test_synthetic_s4_identical_but_unapproved_is_pc02_and_approved_is_pc00():
    """Handover syn-S4 / AT27 and AT01: uniform unapproved -> PC02; approved and confirmed -> PC00."""
    source, target = _synthetic({7, 8})
    occs = _occurrences(source, "keep the promise")
    pairs = [("honor", "keep"), ("their", "the"), ("commitment", "promise")]
    model = DirectModel({(e, f): 0.9 for e, f in pairs}, {(f, e): 0.9 for e, f in pairs})
    inp, gid = _input(source, target, occs, model=model)
    assert run_check(inp, qualify=False).outcomes[gid] == "PC02"
    inp, gid = _input(source, target, occs, model=model, rules=[_approve(gid, "honor their commitment")])
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC00"
    assert {r["disposition"] for r in result.audit} == {"EVALUATED"}
    occs = _occurrences(source, "keep the promise", state="PROVISIONAL")
    inp, gid = _input(source, target, occs, model=model, rules=[_approve(gid, "honor their commitment")])
    assert run_check(inp, qualify=False).outcomes[gid] == "PC02"


def test_learned_inflection_and_declared_spelling_are_approved_variants():
    """AT05: a learned suffix or a declared spelling variant of an approved form is PC01, not PC10."""
    source = _units("S", [(1, "the lamp shone"), (2, "a lamp burned"), (3, "my lamp fell")])
    target = _units("T", [(1, "taa iliwaka"), (2, "taani iliungua"), (3, "tah ilianguka")])
    occs = _occurrences(source, "lamp")
    gid = group_id("CPT-0000000000000001", "SENSE-1")
    morph = Morphology(suffixes=("ni",), equivalences={"tah": "taa"})
    inp, gid = _input(source, target, occs, rules=[_approve(gid, "taa")], morph=morph)
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC01"
    inp, gid = _input(source, target, occs, rules=[_approve(gid, "taa")])
    assert run_check(inp, qualify=False).outcomes[gid] in ("PC10", "PC11", "PC21")  # undeclared: never a pass


def test_negation_shift_only_with_declared_markers():
    """AT06: a declared negation marker next to one rendering gives PC13; without markers it is not checked."""
    source = _units("S", [(1, "they trust"), (2, "we trust"), (3, "you trust")])
    target = _units("T", [(1, "wanaamini"), (2, "tunaamini"), (3, "hamwamini si")])
    occs = _occurrences(source, "trust")
    gid = group_id("CPT-0000000000000001", "SENSE-1")
    rules = [_approve(gid, "wanaamini"), _approve(gid, "tunaamini"), _approve(gid, "hamwamini")]
    inp, gid = _input(source, target, occs, rules=rules, morph=Morphology(negation=("si",)))
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC13" and _code(result, "PC13")[0]["source_refs"] == ["GEN 1:3"]
    inp, gid = _input(source, target, occs, rules=rules)
    assert run_check(inp, qualify=False).outcomes[gid] == "PC01"


def _corpus(verses=300, seed=5):
    """A fabricated parallel corpus with a consistent lexicon (sN -> tN), lightly reordered."""
    rng = random.Random(seed)
    source, target = [], []
    for v in range(1, verses + 1):
        words = rng.sample(range(2, 40), 5) + ([1] if v % 4 == 0 else [])
        rng.shuffle(words)
        out = [f"t{w}" if w != 3 or v % 5 else "t99" for w in words]  # word 3 has a second rendering
        i, j = rng.randrange(len(out)), rng.randrange(len(out))
        out[i], out[j] = out[j], out[i]
        source.append((v, " ".join(f"s{w}" for w in words)))
        target.append((v, " ".join(out)))
    return source, target


def _wordy(pairs):
    """Turn sN/tN into letter-only tokens (the tokenizer drops digits)."""
    spell = lambda w: w[0] + "".join("abcdefghij"[int(d)] for d in w[1:])  # noqa: E731
    return [(n, " ".join(spell(w) for w in text.split())) for n, text in pairs]


def test_omission_with_reliable_alignment_is_pc11_and_weak_alignment_is_pc21():
    """AT07 / AT12: dropping the rendering in a well-aligned verse is PC11; a verse of unknown words is PC21."""
    s, t = _corpus()
    s, t = _wordy(s), _wordy(t)
    concept = "sb"                     # word 1
    t = [(n, " ".join(w for w in text.split() if w != "tb") if n == 4 else text) for n, text in t]
    present = set(s[7][1].split())
    unrelated = [w for w in ("tc", "td", "te", "tf", "tg", "th", "ti", "tj", "tba", "tbb") if "s" + w[1:] not in present][:4]
    t = [(n, " ".join(unrelated) if n == 8 else text) for n, text in t]
    source, target = _units("S", s), _units("T", t)
    occs = _token_occurrences(source, concept)
    inp, gid = _input(source, target, occs)
    result = run_check(inp, qualify=False)
    by_ref = {r["occurrence_id"]: r["result_code"] for r in result.audit}
    assert by_ref["OCC-S4"] == "PC11" and by_ref["OCC-S8"] == "PC21"
    assert _code(result, "PC11")[0]["evidence"][0].startswith("tb (")


def test_self_qualification_measures_recall_and_labels_unqualified_kinds():
    """L4: on a consistent corpus substitutions are found (CHECKED); on a tiny text both kinds are BEST_EFFORT
    and their findings stay, labelled with the measurement (PO 2026-11-25)."""
    s, t = _wordy(_corpus()[0]), _wordy(_corpus()[1])
    source, target = _units("S", s), _units("T", t)
    occs = _token_occurrences(source, "sb")
    inp, gid = _input(source, target, occs)
    result = run_check(inp)
    assert result.qualification["SUBSTITUTION"]["status"] == "CHECKED"
    assert result.qualification["SUBSTITUTION"]["recall"] >= 0.8
    tiny_s, tiny_t = _synthetic({7, 8})
    inp, _ = _input(tiny_s, tiny_t, _occurrences(tiny_s, "keep the promise"))
    small = run_check(inp)
    assert set(small.best_effort) == {"SUBSTITUTION", "REMOVAL"}
    for finding in small.findings:
        if finding["code"] in ("PC10", "PC11"):
            assert "Best effort for this WIP" in finding["evidence"][-1]


def test_single_verse_groups_are_informational_and_unresolved_senses_are_pc20():
    """AT16 and AT11: one confirmed verse is listed, not compared; an unresolved sense is PC20, never consistent."""
    source, target = _synthetic({4, 5, 6})
    occs = _occurrences(source, "light")
    occs[0]["sense_state"], occs[0]["sense_id"] = "UNRESOLVED", None
    inp, gid = _input(source, target, occs[:2])
    result = run_check(inp, qualify=False)
    codes = sorted((r["disposition"], r["result_code"]) for r in result.audit)
    assert codes == [("INFORMATIONAL", "PC02"), ("REVIEW", "PC20")]
    assert _code(result, "PC20") and gid not in result.outcomes


def test_equal_scope_accept_and_reject_blocks_the_group():
    """AT14: an approved ACCEPT and REJECT of the same form at one scope is PC23 for that group only."""
    source, target = _synthetic({1, 2})
    occs = _occurrences(source, "stand firm")
    gid = group_id("CPT-0000000000000001", "SENSE-1")
    rules = [_approve(gid, "remain steadfast"), _approve(gid, "remain steadfast", effect="REJECT")]
    inp, gid = _input(source, target, occs, rules=rules)
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC23" and {r["disposition"] for r in result.audit} == {"BLOCKED"}
    assert _code(result, "PC23")[0]["is_blocking"]


def test_bridged_and_missing_verses():
    """AT25: verses joined through versification form one pair; a SOURCE verse without a WIP verse is PC21."""
    source = _units("S", [(1, "a"), (2, "b"), (8, "c")])
    target = [SourceUnit("T1", "GEN 1:1", ("GEN 1:1",), "x"), SourceUnit("T9", "GEN 1:9", ("GEN 1:9",), "z")]
    pairs, unit_pair = pair_verses(source, target, _Schema(), _Map())
    assert [(p.source, p.target) for p in pairs] == [(("S1",), ("T1",)), (("S8",), ("T9",))]
    assert "S:S2" not in unit_pair
    joined, _ = pair_verses(_units("S", [(1, "a"), (2, "b")]), [SourceUnit("T1", "GEN 1:1", ("GEN 1:1", "GEN 1:2"), "xy")],
                            _Schema(), _Schema())
    assert joined[0].kind == "EQUIVALENCE_GROUP" and joined[0].source == ("S1", "S2")


def test_every_eligible_occurrence_is_audited_once_and_output_is_deterministic():
    """AT18: one audit row per occurrence; identical inputs give identical findings and audit."""
    source, target = _synthetic({1, 2, 3})
    occs = _occurrences(source, "stand firm")
    gid = group_id("CPT-0000000000000001", "SENSE-1")
    rules = [_approve(gid, "remain steadfast"), _approve(gid, "not to give up", state="PROPOSED")]
    first = run_check(_input(source, target, occs, rules=rules)[0])
    second = run_check(_input(source, target, occs, rules=rules)[0])
    assert sorted(r["occurrence_id"] for r in first.audit) == sorted(o["occurrence_id"] for o in occs)
    assert first.findings == second.findings and first.audit == second.audit
    for row in first.audit:
        validate_record("occurrence_audit", row)


def test_planted_synonyms_are_caught_as_variation():
    """A word with a second learned rendering: planting that synonym must give PC10, not a pass or a gap."""
    s, t = _wordy(_corpus()[0]), _wordy(_corpus()[1])
    source, target = _units("S", s), _units("T", t)
    inp, _ = _input(source, target, _token_occurrences(source, "sd"))
    q = run_check(inp).qualification["SUBSTITUTION"]
    assert q["known_synonyms"] == q["trials"] > 0 and q["recall"] >= 0.8
