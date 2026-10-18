"""Deterministic contracts of the NCA release gate (tools/qualify_nca.py); no model calls."""

from fractions import Fraction
import importlib.util
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
    items = tuple({"VALUE": str(value), "KIND": kind, "ROLE": role} for value in ol_values)
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


def _group(label: str, outcome: str, values: tuple, expected: tuple) -> dict:
    """Build one serialized group as qualify_nca reads it from sut.json."""
    return {"western_references": [label], "evidence": {"wip_text": "text"},
            "extraction": {"status": "COMPLETE", "limitations": [], "values": list(values), "kinds": ["CARDINAL"] * len(values),
                           "counts_en": [""] * len(values), "issues": []},
            "comparison": {"outcome": outcome, "expected_values": list(expected), "wip_values": list(values),
                           "review_context": {}}}


def test_planted_error_fails_and_skips_rows_that_only_review():
    """A changed index value must FAIL; provisional and apparatus rows are not planted."""
    bundle = _Bundle([_row("JOS 4:2", ("12",)), _row("JOS 4:3", ("12",), review="PROVISIONAL"),
                      _row("JOS 4:4", ("12",), tc="VARIANT_ATTESTED")])
    assert gate.planted_outcome(_group("JOS 4:2", "PASS", ("12",), ("12",)), bundle, "UNORDERED") == "FAIL"
    assert gate.planted_outcome(_group("JOS 4:3", "PASS", ("12",), ("12",)), bundle, "UNORDERED") is None
    assert gate.planted_outcome(_group("JOS 4:4", "PASS", ("12",), ("12",)), bundle, "UNORDERED") is None


def test_metrics_and_gate_pool_languages_and_apply_thresholds():
    """Metrics count per WIP; the gate pools them and applies every threshold."""
    bundle = _Bundle([_row("JOS 4:2", ("12",)), _row("JOS 4:8", ("12",))])
    sut = {"project_id": "p", "language": "uk-UA",
           "groups": [_group("JOS 4:2", "PASS", ("12",), ("12",)), _group("JOS 4:8", "FAIL", (), ("12",))]}
    labels = {"values": {"c0": {"a": {"values": ["12"]}, "b": {"values": ["12"]}},
                         "c1": {"a": {"values": ["12"]}, "b": {"values": ["12"]}}},
              "verdicts": {"c1": {"a": {"verdict": "FALSE_ALARM"}, "b": {"verdict": "FALSE_ALARM"}}}}
    measured = gate.language_metrics(sut, labels, ["a", "b"], bundle, "UNORDERED", {"JOS 4:2": ["PLAIN"]})
    assert measured["fail_precision"] == {"numerator": 0, "denominator": 1, "percent": 0.0}
    assert measured["extraction_recall"]["numerator"] == 1 and measured["extraction_recall"]["denominator"] == 2
    assert measured["planted_detection"] == {"numerator": 1, "denominator": 1, "percent": 100.0}
    assert measured["cases"][1]["fail_verdict"] == "FALSE_ALARM"
    result = gate.gate_status([measured, {**measured, "language": "es-419"}])
    assert result["status"] == "FAIL"
    assert result["checks"] == {"fail_precision": False, "extraction_recall": False,
                                "planted_detection": True, "two_languages": True}
    assert result["totals"]["fail_precision"]["denominator"] == 2


def test_gate_without_fails_has_no_precision_evidence():
    """Zero FAILs is no evidence of precision, so that check does not pass."""
    empty = {"numerator": 0, "denominator": 0, "percent": None}
    full = {"numerator": 10, "denominator": 10, "percent": 100.0}
    languages = [{"language": language, "fail_precision": empty, "extraction_recall": full,
                  "planted_detection": full} for language in ("uk-UA", "es-419")]
    assert gate.gate_status(languages)["checks"]["fail_precision"] is False


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
