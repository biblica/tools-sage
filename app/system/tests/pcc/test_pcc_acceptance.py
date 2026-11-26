"""PCC acceptance cases the 2026-11-26 audit found untested or wrong (handover doc 08: AT12, AT17, AT21, AT26).
Fabricated texts only. The full AT01-AT30 matrix is in the PCC implementation plan."""

from __future__ import annotations

from pathlib import Path

from sage.pcc.align import DirectModel
from sage.pcc.check import (CheckInput, Evidence, Morphology, classify, pair_verses, run_check, side_tokens,
                            stop_forms)
from sage.pcc.ids import group_id
from sage.pcc.source_text import reference_units
from .test_pcc_check import (SHA, _Schema, _approve, _code, _corpus, _input, _token_occurrences, _units, _wordy,
                             _occurrences)


def test_at26_unspaced_wip_matches_a_multi_character_approved_rendering():
    """An approved 灯火 matches the WIP's single-character tokens 灯 火 (before: never matched, no pass possible)."""
    source = _units("S", [(1, "the lamp shone"), (2, "a lamp burned"), (3, "my lamp fell")])
    target = _units("T", [(1, "灯火亮了"), (2, "灯火燃烧"), (3, "我的灯火掉了")])
    occs = _occurrences(source, "lamp")
    s_units, t_units = {u.unit_id: u for u in source}, {u.unit_id: u for u in target}
    pairs, unit_pair = pair_verses(source, target, _Schema(), _Schema())
    s_side = side_tokens(pairs, s_units, "source", cased=True)
    t_side = side_tokens(pairs, t_units, "target", cased=False, unspaced=True)
    assert [t.norm for t in t_side.tokens[unit_pair["S:S1"]]][:2] == ["灯", "火"]
    gid = group_id("CPT-0000000000000001", "SENSE-1")
    groups = [{"group_id": gid, "expression_id": "EXPR-1", "sense_id": "SENSE-1", "state": "CONFIRMED"}]
    exprs = [{"expression_id": "EXPR-1", "source_surface": "lamp",
              "senses": [{"sense_id": "SENSE-1", "discriminator": "original-language lemma x (BE; CPT)"}]}]
    rule = _approve(gid, "灯火")
    inp = CheckInput("RUN-1", SHA, s_units, t_units, pairs, unit_pair, s_side, t_side, DirectModel({}, {}),
                     Morphology(), exprs, occs, groups, {rule["rule_id"]: rule}, stop_forms(t_side), stop_forms(s_side))
    result = run_check(inp, qualify=False)
    assert result.outcomes[gid] == "PC00"
    assert {r["result_code"] for r in result.audit} == {"PC00"}


def test_at12_a_group_with_undecidable_occurrences_is_never_uniform():
    """PC21 outranks PC02 in every branch (before: unapproved uniform forms plus a PC21 gave PC02)."""
    evs = [Evidence("O1", "G", "GEN 1:1", "FORM", form="kipo", form_key="kipo"),
           Evidence("O2", "G", "GEN 1:2", "FORM", form="kipo", form_key="kipo"),
           Evidence("O3", "G", "GEN 1:3", "UNCERTAIN")]
    group, per = classify(evs, confirmed=True, morph=Morphology())
    assert group == "PC21" and per == {"O1": "PC02", "O2": "PC02", "O3": "PC21"}
    assert classify(evs[:2], confirmed=True, morph=Morphology())[0] == "PC02"


def test_at21_overlapping_concepts_are_one_issue_with_both_evidence_spans():
    """Two concepts over the same SOURCE spans, rendering dropped in one verse: both PC11 findings are kept and
    share one issue cluster (before: two issues for one omission)."""
    s, t = _wordy(_corpus()[0]), _wordy(_corpus()[1])
    t = [(n, " ".join(w for w in text.split() if w != "tb") if n == 4 else text) for n, text in t]
    source, target = _units("S", s), _units("T", t)
    first = _token_occurrences(source, "sb")
    second = [dict(o, occurrence_id=o["occurrence_id"] + "-B", expression_id="EXPR-2", sense_id="SENSE-2") for o in first]
    g1, g2 = group_id("CPT-0000000000000001", "SENSE-1"), group_id("CPT-0000000000000002", "SENSE-2")
    groups = [{"group_id": g1, "expression_id": "EXPR-1", "sense_id": "SENSE-1", "state": "CONFIRMED"},
              {"group_id": g2, "expression_id": "EXPR-2", "sense_id": "SENSE-2", "state": "CONFIRMED"}]
    exprs = [{"expression_id": e, "source_surface": "sb", "senses": [{"sense_id": s_, "discriminator": "lemma x (BE; CPT)"}]}
             for e, s_ in (("EXPR-1", "SENSE-1"), ("EXPR-2", "SENSE-2"))]
    inp, _ = _input(source, target, first + second, groups=groups, expressions=exprs)
    result = run_check(inp, qualify=False)
    omissions = _code(result, "PC11")
    assert {f["group_id"] for f in omissions} == {g1, g2}
    assert len({f["issue_cluster_id"] for f in omissions}) == 1
    assert result.counts["clusters_merged_overlap"] >= 1


def test_at17_headings_and_notes_are_not_scripture_text(tmp_path: Path):
    """A wording only in a section heading, a footnote or a cross reference is never read as verse text."""
    folder = tmp_path / "PRJ"
    folder.mkdir()
    (folder / "41MATPRJ.SFM").write_text(
        "\\id MAT fabricated\n\\c 1\n\\s1 Grace and truth\n\\p\n"
        "\\v 1 The lamp shone\\f + \\fr 1:1 \\ft grace upon grace\\f* in the house.\n"
        "\\v 2 The lamp fell.\\x - \\xo 1:2 \\xt grace\\x*\n\\r (grace)\n", encoding="utf-8")
    units = reference_units(folder)
    assert [u.canonical_ref for u in units] == ["MAT 1:1", "MAT 1:2"]
    assert all("grace" not in u.text.casefold() for u in units)
    assert "lamp shone" in units[0].text


def test_at20_malformed_biblical_terms_references_are_reported_not_skipped():
    """A Biblical Terms reference that is not BBBCCCVVVWWWWW is named in the build's problems (before: silent)."""
    from sage.pcc.rlbuild import Concept, build_reference_list, merge_inventory
    from .test_pcc_rlbuild import _Schema as _RlSchema, _fixture, _traits
    units, alignment, analysis = _fixture()
    concept = Concept("BT", ("bt-bread",), "bread of life", "RE", "ACTIVE", ("BT:bt-bread",),
                      surfaces=(("αρτος",),), references=("MAT 1:1 bad", "04000100100022"))
    result = build_reference_list(units, alignment, analysis, _RlSchema(), traits=_traits(), language_tag="xx",
                                  inventory=merge_inventory([concept]), min_verses=3)
    assert any("bread of life" in p and "MAT 1:1 bad" in p for p in result.declared_problems)
    assert result.stats["bt_bad_references"] == 1


def test_at15_a_secondary_source_never_changes_groups_or_findings(make_workspace):
    """The primary SOURCE alone decides groups (D7): a Job with a secondary SOURCE gets the same groups, audit and
    findings as one without; the secondary is sealed and its authority recorded. No advisory comparison is made yet."""
    import json

    from sage.jobs import pcc_default_settings
    from sage.pcc.run import execute_pcc_run, load_run_snapshot
    from .test_pcc_p1 import _run, _store

    store, _ = _store(make_workspace)
    seen = []
    for bindings in ({"source": "usNIVv2", "wip": "usWIP"},
                     {"source": "usNIVv2", "secondary_source": "usNIRVv2", "wip": "usWIP"}):
        job = store.create_job(tool="pcc", job_id="", display_name="x", bindings=bindings,
                               defaults=pcc_default_settings("en"))
        outputs = {}
        for operation in ("terms", "check"):
            config, run = _run(store, job, operation=operation)
            execute_pcc_run(store, config, job, run)
            folder = run.root / "validation" / "pcc"
            for name in ("groups.jsonl", "findings.jsonl", "occurrence-audit.jsonl"):
                if (folder / name).is_file():
                    rows = [json.loads(line) for line in (folder / name).read_text(encoding="utf-8").splitlines()]
                    outputs[f"{operation}/{name}"] = [{k: v for k, v in r.items() if k != "run_id"} for r in rows]
            if operation == "check":
                authority = load_run_snapshot(run.root)["source_authority"]
        seen.append((outputs, authority))
        store.remove_job(job, remove_reports=True)  # the Job ID comes from the bindings; free it for the next one
    assert seen[0][0] == seen[1][0] and seen[0][0]
    assert (seen[0][1], seen[1][1]) == ("SINGLE_SOURCE", "PRIMARY_CONTROLS")
