"""Deterministic contracts of the NCA release gate (tools/qualify_nca.py); no model calls."""

from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys

from sage.numbers.models import ReferenceRow
from sage.vrs import VerseRef


TOOL = Path(__file__).parents[2] / "tools" / "qualify_nca.py"
_spec = importlib.util.spec_from_file_location("qualify_nca", TOOL)
gate = importlib.util.module_from_spec(_spec)
# Loading a tool must not leave bytecode beside the distributed source (runtime roots stay clean).
_writes_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
try:
    _spec.loader.exec_module(gate)
finally:
    sys.dont_write_bytecode = _writes_bytecode


def _row(label: str, ol: tuple, niv: tuple | None = None, *, kind: str = "CARDINAL", role: str = "COUNT",
         tc: str = "NONE", review: str = "AGREES") -> ReferenceRow:
    """Build one typed reference row with the given OL (and optional NIV) values."""
    book, coordinate = label.split(" ", 1)
    chapter, verse = coordinate.split(":")
    ol_values = tuple(Fraction(value) for value in ol)
    niv_values = ol_values if niv is None else tuple(Fraction(value) for value in niv)
    items = tuple({"VALUE": str(value), "KIND": kind, "ROLE": role, "REFERENT": "men"} for value in ol_values)
    return ReferenceRow(VerseRef(book, int(chapter), int(verse)), label, "HEB", "ol text", ol_values,
                        "bsb text", niv_values, {"TC_STATUS": tc, "OL_REVIEW_STATUS": review}, (), items, ())


class _Bundle:
    """Minimal reference bundle exposing rows and lookup, like ReferenceBundle."""
    def __init__(self, rows):
        """Key the rows by Western reference."""
        self.rows = {row.western_reference: row for row in rows}

    def lookup(self, ref):
        """Return the row for one coordinate, or None when it is not indexed."""
        return self.rows.get(ref)


def test_row_classes_name_the_hard_cases():
    """Each typed row is filed under the hard classes its values and kinds imply."""
    assert gate.row_classes(_row("GEN 1:1", ("3/2",), kind="FRACTION", role="MEASURE")) == ("FRACTION", "MEASURE")
    assert gate.row_classes(_row("GEN 1:2", (), ("12",))) == ("NIV_ONLY",)
    assert gate.row_classes(_row("GEN 1:3", ("42360",))) == ("LARGE",)
    assert gate.row_classes(_row("GEN 1:4", ("14", "1"), kind="ORDINAL", role="DATE")) == ("DATE", "ONE")
    assert gate.row_classes(_row("GEN 1:5", ("7",))) == ("PLAIN",)
    assert "APPARATUS" in gate.row_classes(_row("GEN 1:6", ("7",), tc="VARIANT_ATTESTED"))


def test_selection_is_seeded_reproducible_and_covers_every_class_present():
    """The same seed gives the same selection, and each class gets its quota."""
    rows = {row.western_reference: row for row in
            [_row(f"NUM 1:{verse}", (str(verse),)) for verse in range(1, 40)]
            + [_row(f"EXO 2:{verse}", ("1/2",), kind="FRACTION") for verse in range(1, 6)]}
    first = gate.select_gold(rows, per_class=3, seed="s")
    assert first == gate.select_gold(rows, per_class=3, seed="s")
    assert first != gate.select_gold(rows, per_class=3, seed="other")
    assert sum("FRACTION" in case["classes"] for case in first) == 3
    assert len({case["reference"] for case in first}) == len(first)


def test_gold_values_need_every_judge_to_agree():
    """Gold values exist only when all judges return the same numbers."""
    agree = {"a": {"values": ["12", "3/2"]}, "b": {"values": ["1.5", "12"]}}
    assert gate.consensus_values(agree, ["a", "b"]) == [Fraction(12), Fraction(3, 2)]
    assert gate.consensus_values({"a": {"values": ["12"]}, "b": {"values": ["13"]}}, ["a", "b"]) is None
    assert gate.consensus_values({"a": {"values": ["12"]}}, ["a", "b"]) is None
    assert gate.consensus_values({"a": {"values": ["twelve"]}, "b": {"values": ["twelve"]}}, ["a", "b"]) is None


def test_fail_verdict_is_split_unless_judges_agree():
    """A FAIL verdict is GENUINE or FALSE_ALARM only by agreement; otherwise SPLIT."""
    assert gate.verdict({"a": {"verdict": "GENUINE"}, "b": {"verdict": "GENUINE"}}, ["a", "b"]) == "GENUINE"
    assert gate.verdict({"a": {"verdict": "GENUINE"}, "b": {"verdict": "FALSE_ALARM"}}, ["a", "b"]) == "SPLIT"
    assert gate.verdict({"a": {"verdict": "GENUINE"}}, ["a", "b"]) == "SPLIT"


def test_fail_cause_decides_the_verdict_and_reading_is_decided_by_code():
    """Only VALUE_CHANGED is GENUINE; a FAIL is READ_CORRECTLY only when extraction equals gold."""
    changed, restructured = {"cause": "VALUE_CHANGED"}, {"cause": "RESTRUCTURED"}
    assert gate.verdict({"a": changed, "b": changed}, ["a", "b"]) == "GENUINE"
    assert gate.verdict({"a": restructured, "b": {"cause": "NOT_A_QUANTITY"}}, ["a", "b"]) == "FALSE_ALARM"
    assert gate.verdict({"a": changed, "b": restructured}, ["a", "b"]) == "SPLIT"
    assert gate.fail_cause({"a": restructured, "b": restructured}, ["a", "b"]) == "RESTRUCTURED"
    assert gate.fail_cause({"a": changed, "b": restructured}, ["a", "b"]) == "MIXED"
    assert gate.fail_reading([Fraction(2), Fraction(3)], [Fraction(3), Fraction(2)], True) == "READ_CORRECTLY"
    assert gate.fail_reading([Fraction(3)], [Fraction(1), Fraction(3)], True) == "MISREAD"
    assert gate.fail_reading([Fraction(3)], [Fraction(3)], False) == "MISREAD"
    assert gate.fail_reading(None, [Fraction(3)], True) == "DISPUTED"


def test_judges_see_one_fail_per_call_with_kind_and_referents(tmp_path):
    """Each FAIL is judged alone, so a rescore that adds or drops a FAIL cannot move another verdict."""
    bundle = _Bundle([_row("JOS 4:2", ("12",)), _row("JOS 4:8", ("12",))])
    groups = [_group("JOS 4:2", "FAIL", ("13",), ("12",)), _group("JOS 4:8", "FAIL", ("11",), ("12",))]
    prompts = []

    def judge(system, prompt, schema):
        """Record each prompt and answer every case it holds."""
        prompts.append((system, json.loads(prompt)))
        key = "cases" if "cases" in prompt else "verses"
        items = [{"id": item["id"], "cause": "VALUE_CHANGED", "reason": "r"} if key == "cases"
                 else {"id": item["id"], "values": [], "kinds": []} for item in json.loads(prompt)[key]]
        return {"output": {"items": items}, "cost_usd": 0}

    labels = gate.judge_cases(groups, "uk-UA", {"a": judge}, tmp_path, bundle)
    # Judge calls run on worker threads, so order the recorded prompts by case.
    verdict_prompts = sorted((prompt for system, prompt in prompts if "cases" in prompt),
                             key=lambda prompt: prompt["cases"][0]["id"])
    assert [len(prompt["cases"]) for prompt in verdict_prompts] == [1, 1]
    assert verdict_prompts[0]["cases"][0]["fail_kind"] == "VALUE_DIFFERENCE"
    assert verdict_prompts[0]["cases"][0]["wip_values_read_by_checker"] == [{"value": "13", "counts": ""}]
    assert labels["verdicts"]["c1"]["a"]["cause"] == "VALUE_CHANGED"


def _group(label: str, outcome: str, values: tuple, expected: tuple, counts: str = "") -> dict:
    """Build one serialized group as qualify_nca reads it from sut.json."""
    return {"western_references": [label], "evidence": {"wip_text": "text"},
            "extraction": {"status": "COMPLETE", "limitations": [], "values": list(values), "kinds": ["CARDINAL"] * len(values),
                           "counts_en": [counts] * len(values), "issues": []},
            "comparison": {"outcome": outcome, "expected_values": list(expected), "wip_values": list(values),
                           "review_context": {}}}


def test_planted_error_fails_and_skips_rows_that_only_review():
    """A changed index value must FAIL; provisional and apparatus rows are not planted."""
    bundle = _Bundle([_row("JOS 4:2", ("12",)), _row("JOS 4:3", ("12",), review="PROVISIONAL"),
                      _row("JOS 4:4", ("12",), tc="VARIANT_ATTESTED")])
    assert gate.planted_outcome(_group("JOS 4:2", "PASS", ("12",), ("12",), "men"), bundle, "UNORDERED") == "FAIL"
    assert gate.planted_outcome(_group("JOS 4:3", "PASS", ("12",), ("12",)), bundle, "UNORDERED") is None
    assert gate.planted_outcome(_group("JOS 4:4", "PASS", ("12",), ("12",)), bundle, "UNORDERED") is None


def test_metrics_and_gate_pool_languages_and_apply_thresholds():
    """Metrics count per WIP; the gate pools them and applies every threshold."""
    bundle = _Bundle([_row("JOS 4:2", ("12",)), _row("JOS 4:8", ("12",))])
    sut = {"project_id": "p", "language": "uk-UA",
           "groups": [_group("JOS 4:2", "PASS", ("12",), ("12",), "men"), _group("JOS 4:8", "FAIL", (), ("12",))]}
    labels = {"values": {"c0": {"a": {"values": ["12"]}, "b": {"values": ["12"]}},
                         "c1": {"a": {"values": ["12"]}, "b": {"values": ["12"]}}},
              "verdicts": {"c1": {"a": {"verdict": "FALSE_ALARM"}, "b": {"verdict": "FALSE_ALARM"}}}}
    measured = gate.language_metrics(sut, labels, ["a", "b"], bundle, "UNORDERED", {"JOS 4:2": ["PLAIN"]})
    assert measured["fail_precision"] == {"numerator": 0, "denominator": 1, "percent": 0.0,
                                          "wilson95_percent": [0.0, 79.3]}
    assert measured["extraction_recall"]["numerator"] == 1 and measured["extraction_recall"]["denominator"] == 2
    assert measured["planted_detection"]["numerator"] == 1 and measured["planted_detection"]["denominator"] == 1
    assert measured["cases"][1]["fail_verdict"] == "FALSE_ALARM"
    # The judges read 12 where the checker read nothing: the FAIL rests on a misreading.
    assert measured["cases"][1]["fail_reading"] == "MISREAD"
    assert measured["false_fail_rate"]["numerator"] == 1 and measured["false_fail_rate"]["denominator"] == 2
    assert measured["false_fails_by_reading"] == {"MISREAD": 1}
    result = gate.gate_status([measured, {**measured, "language": "es-419"}])
    assert result["status"] == "FAIL"
    # Two false FAILs in four verses and 2/4 recall are past their bars across the whole interval;
    # 2/2 planted errors is too little evidence to pass, and no text plants ran.
    assert result["checks"] == {"false_fail_rate": "FAIL", "extraction_recall": "FAIL",
                                "planted_detection": "INSUFFICIENT_EVIDENCE",
                                "text_plant_detection": "INSUFFICIENT_EVIDENCE", "two_languages": "PASS"}
    # Precision is still reported, but it is not a gate check.
    assert result["totals"]["fail_precision"]["denominator"] == 2
    assert result["totals"]["false_fail_rate"]["denominator"] == 4


def test_checks_need_enough_evidence_to_pass_and_a_clear_shortfall_to_fail():
    """A ratio PASSes on enough cases at the bar, FAILs below its interval, and is otherwise undecided."""
    bar = Fraction(9, 10)
    assert gate.check_ratio({"numerator": 19, "denominator": 20}, bar, 20) == "PASS"
    assert gate.check_ratio({"numerator": 4, "denominator": 4}, bar, 20) == "INSUFFICIENT_EVIDENCE"
    assert gate.check_ratio({"numerator": 1, "denominator": 4}, bar, 20) == "FAIL"
    # 85% of 40 is under the bar, but the interval still reaches it.
    assert gate.check_ratio({"numerator": 34, "denominator": 40}, bar, 20) == "INSUFFICIENT_EVIDENCE"
    low, high = gate.wilson_interval(1, 4)
    assert round(low, 3) == 0.046 and round(high, 3) == 0.699


def test_gate_needs_enough_verses_to_bound_false_fails():
    """No false FAIL in a few verses is no evidence; enough verses with almost none pass."""
    full = {"numerator": 200, "denominator": 200}
    def languages(false, verses):
        """Two WIPs with the given false FAILs and verses each, every other measure passing."""
        return [{"language": language, "false_fail_rate": {"numerator": false, "denominator": verses},
                 "extraction_recall": full, "planted_detection": full, "text_plant_detection": full}
                for language in ("uk-UA", "es-419")]
    assert gate.gate_status(languages(0, 10))["status"] == "INSUFFICIENT_EVIDENCE"
    assert gate.gate_status(languages(0, 160))["status"] == "PASS"
    # 2/318 (0.6%) is above the bar but its interval still reaches below it; 6/318 does not.
    assert gate.gate_status(languages(1, 159))["checks"]["false_fail_rate"] == "INSUFFICIENT_EVIDENCE"
    assert gate.gate_status(languages(3, 159))["checks"]["false_fail_rate"] == "FAIL"
    assert gate.check_rate({"numerator": 1, "denominator": 300}, Fraction(1, 200), 300) == "PASS"


def test_held_out_selection_avoids_development_coordinates():
    """A held-out selection never reuses a development coordinate."""
    rows = {row.western_reference: row for row in [_row(f"NUM 1:{verse}", (str(verse),)) for verse in range(1, 30)]}
    development = {case["reference"] for case in gate.select_gold(rows, per_class=5, seed="s")}
    held_out = gate.select_gold(rows, per_class=5, seed="t", exclude=frozenset(development))
    assert held_out and not development & {case["reference"] for case in held_out}


def test_provider_failures_are_not_scored_and_make_the_gate_incomplete():
    """Verses the provider never answered are excluded and make the gate INCOMPLETE."""
    bundle = _Bundle([_row("JOS 4:2", ("12",))])
    failed = _group("JOS 4:2", "NOT_ASSESSED", (), ("12",))
    failed["extraction"].update(status="UNSUPPORTED", limitations=["NCA_BATCH_SINGLETON_FAILED: NCA_MODEL_PROVIDER_FAILED"])
    measured = gate.language_metrics({"project_id": "p", "language": "es-419", "groups": [failed]},
                                     {"values": {}, "verdicts": {}}, ["a", "b"], bundle, "UNORDERED", {})
    assert measured["provider_failed"] == ["JOS 4:2"] and measured["extraction_recall"]["denominator"] == 0
    assert gate.gate_status([measured, {**measured, "language": "uk-UA"}])["status"] == "INCOMPLETE"


BOOK = ("\\id GEN\n\\c 1\n\\p\n\\v 1 Seven days and seven nights. \\v 2 Two \\w men|strong=\"H1\"\\w* came.\n"
        "\\c 10\n\\p\n\\v 1 Ten men.\n")


def test_text_plant_changes_only_its_own_verse():
    """An edit is applied inside its verse and kept only when that verse alone changes as planned."""
    text, applied = gate.plant_book_text(BOOK, "01GEN.SFM", {"GEN:10:1": ("Ten", "Eleven")})
    assert applied == ["GEN:10:1"] and "\\v 1 Eleven men." in text and "Seven days" in text
    # "seven" twice in its verse is ambiguous; "men" crosses markup in 1:2; 1:9 does not exist.
    _same, applied = gate.plant_book_text(BOOK, "01GEN.SFM", {"GEN:1:1": ("even", "ight"),
                                                              "GEN:1:2": ("Two men", "Three men"),
                                                              "GEN:1:9": ("x", "y")})
    assert applied == [] and _same == BOOK
    # A verse-1 edit lands in the chapter it names, not in chapter 1.
    text, applied = gate.plant_book_text(BOOK, "01GEN.SFM", {"GEN:1:1": ("Seven days", "Eight days")})
    assert applied == ["GEN:1:1"] and text.count("Ten men") == 1 and "Eight days and seven nights" in text


def test_plant_candidates_are_seeded_and_need_an_exact_reading():
    """Plants come only from PASS verses read exactly as the judges read them, in seeded order."""
    bundle = _Bundle([_row("JOS 4:2", ("12",)), _row("JOS 4:3", ("12",)), _row("JOS 4:4", ("3/2",))])
    groups = []
    for label, values in (("JOS 4:2", ("12",)), ("JOS 4:3", ("12",)), ("JOS 4:4", ("3/2",))):
        group = _group(label, "PASS", values, values)
        group["unit_id"] = f"{'0' * 64}:JOS:4:{label[-1]}"
        groups.append(group)
    labels = {"values": {"c0": {"a": {"values": ["12"]}}, "c1": {"a": {"values": ["11"]}},
                         "c2": {"a": {"values": ["3/2"]}}}}
    found = gate.plant_candidates(groups, labels, ["a"], bundle, seed="s", limit=5)
    # 4:3 was misread (gold 11) and 4:4 holds a fraction: only 4:2 is planted, 12 -> 13.
    assert [(plant["key"], plant["from"], plant["to"], plant["planned_values"]) for plant in found] == [
        ("JOS:4:2", "12", "13", ["13"])]
    assert found == gate.plant_candidates(groups, labels, ["a"], bundle, seed="s", limit=5)


def test_plants_are_kept_only_when_every_judge_counts_the_planned_values(tmp_path):
    """A plant whose rewrite the judges do not count as planned is not measured."""
    candidates = [{"id": "p0", "key": "JOS:4:2", "western_references": ["JOS 4:2"], "text": "twelve stones",
                   "values": ["12"], "position": 1, "from": "12", "to": "13", "planned_values": ["13"]},
                  {"id": "p1", "key": "JOS:4:3", "western_references": ["JOS 4:3"], "text": "twelve men",
                   "values": ["12"], "position": 1, "from": "12", "to": "13", "planned_values": ["13"]}]

    def judge(system, prompt, schema):
        """Plant both verses; count 13 in the first rewrite and 12 in the second."""
        request = json.loads(prompt)
        if "change" in prompt:
            items = [{"id": verse["id"], "old": "twelve", "new": "thirteen"} for verse in request["verses"]]
        else:
            items = [{"id": verse["id"], "values": ["13" if "stones" in verse["text"] else "12"], "kinds": []}
                     for verse in request["verses"]]
        return {"output": {"items": items}, "cost_usd": 0}

    plants = gate.make_plants(candidates, "en", {"a": judge, "b": judge}, tmp_path)
    assert [(plant["planted_text"], plant["verified"]) for plant in plants] == [
        ("thirteen stones", True), ("thirteen men", False)]
    sut = {"applied": ["JOS:4:2"], "groups": [{**_group("JOS 4:2", "FAIL", ("13",), ("12",)),
                                               "unit_id": f"{'1' * 64}:JOS:4:2"}]}
    measured = gate.plant_metrics({"plants": plants}, sut)
    assert measured["text_plant_detection"]["numerator"] == 1 and measured["text_plant_detection"]["denominator"] == 1
    assert measured["text_plants"]["verified"] == 1 and measured["text_plant_cases"][0]["read_exactly"] is True


class _Identity:
    """Route identity as NcaModelTasks pins it."""
    model_id, reasoning_id = "m", "medium"


class _Tasks:
    """Just the parts of NcaModelTasks the provider probe reads."""
    def __init__(self, executor):
        """Pin a fake route, status and executor."""
        self._route = type("Route", (), {"identity": _Identity()})()
        self._provider_status = "status"
        self._executor = executor


def test_provider_probe_reports_a_refusal_and_passes_an_answer():
    """One tiny request shows a signed-in provider that refuses calls, such as one out of credits."""
    class Refusing:
        """A provider whose workspace has no credits."""
        def execute_prevalidated(self, request, status):
            """Refuse like the codex CLI does."""
            raise RuntimeError("ERROR: Your workspace is out of credits.")

    class Answering:
        """A provider that answers; records the request it got."""
        def execute(self, request):
            """Accept the request."""
            self.request = request

    assert "out of credits" in gate.provider_probe(_Tasks(Refusing()))
    answering = Answering()
    assert gate.provider_probe(_Tasks(answering)) is None
    assert answering.request.model == "m" and answering.request.reasoning_effort == "medium"


def test_provider_is_probed_only_when_a_result_will_be_made(tmp_path):
    """Cached and replayed results need no provider, so a run that only rescores never probes."""
    assert gate.provider_needed("all", tmp_path, ["p"], 50, False)
    assert not gate.provider_needed("all", tmp_path, ["p"], 50, True)
    assert not gate.provider_needed("gate", tmp_path, ["p"], 50, False)
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "sut.json").write_text("{}")
    assert not gate.provider_needed("sut", tmp_path, ["p"], 50, False)
    assert gate.provider_needed("plant", tmp_path, ["p"], 50, False)
    assert not gate.provider_needed("plant", tmp_path, ["p"], 0, False)
