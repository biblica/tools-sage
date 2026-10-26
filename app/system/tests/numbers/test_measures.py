"""Measure-system consistency (numbers/measures.py and style_report): deterministic, report only."""
from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

from sage.numbers.measures import has_lexicon, measure_system
from sage.numbers.models import Extraction
from sage.numbers.style import validate_style_profile
from sage.numbers.style_report import analyze, render
from sage.vrs import VerseRef


def group(ref, surface, value, counts):
    """One group with one body number and what it counts, in the WIP language (Spanish here)."""
    target = SimpleNamespace(target_references=(VerseRef(*ref),), notes=())
    return SimpleNamespace(projected=SimpleNamespace(target=target, western_references=(VerseRef(*ref),)),
                           extraction=Extraction((Fraction(value),), "COMPLETE", surfaces=(surface,),
                                                 counts=(counts,)))


def test_counted_items_are_classified_by_the_word_list_of_the_wip_language():
    """Ancient and modern measure words classify per language; inflected forms match; unknowns have no system."""
    assert measure_system("codos", "es") == "ANCIENT" and measure_system("seahs de cebada", "es-419") == "ANCIENT"
    assert measure_system("kilómetros", "es") == "MODERN" and measure_system("años", "es") == ""
    assert measure_system("ліктів", "uk-UA") == "ANCIENT" and measure_system("лікоть", "uk") == "ANCIENT"
    assert measure_system("батів вина", "uk") == "ANCIENT" and measure_system("кілометрів", "uk") == "MODERN"
    assert measure_system("батько", "uk") == "" and measure_system("корів", "uk") == ""
    assert measure_system("cubits", "en") == "ANCIENT" and measure_system("metres", "en") == "MODERN"
    assert measure_system("codos (unos 45 centímetros)", "es") == ""
    assert measure_system("cubits", "xx") == "" and not has_lexicon("xx") and has_lexicon("uk-UA")


def test_a_translation_keeps_to_one_measure_system_or_the_minority_is_reported():
    """Six ancient uses and one modern: ancient is the rule and the modern use is listed with its verse."""
    groups = [group(("EZK", 40, verse), "cinco", 5, "codos") for verse in range(1, 7)]
    groups.append(group(("REV", 16, 21), "cuarenta", 40, "kilogramos"))
    style = analyze(groups, validate_style_profile(None), "es")
    assert any(rule["area"] == "measures" and rule["rule"] == "ancient measures" for rule in style["rules"])
    [pattern] = [item for item in style["patterns"] if item["area"] == "measures"]
    assert (pattern["expected"], pattern["found"], pattern["count"]) == ("ancient measures", "modern measures", 1)
    assert pattern["references"] == ["REV 16:21"]
    assert "modern measures" in render(style, project="P")


def test_an_even_mix_is_reported_without_choosing_a_system():
    """No dominant system: both uses are listed against 'one measure system'."""
    groups = [group(("NUM", 7, verse), "dos", 2, "codos") for verse in (1, 2)]
    groups += [group(("NUM", 8, verse), "dos", 2, "metros") for verse in (1, 2)]
    patterns = [item for item in analyze(groups, validate_style_profile(None), "es")["patterns"]
                if item["area"] == "measures"]
    assert {item["found"] for item in patterns} == {"ancient measures", "modern measures"}
    assert all(item["expected"] == "one measure system (none dominant)" for item in patterns)


def test_a_consistent_translation_has_no_measure_finding():
    """Only ancient measures, or numbers that count no measure, produce no measure pattern."""
    groups = [group(("EZK", 40, verse), "cinco", 5, "codos") for verse in range(1, 5)]
    groups.append(group(("GEN", 5, 3), "treinta", 30, "años"))
    assert not [item for item in analyze(groups, validate_style_profile(None), "es")["patterns"]
                if item["area"] == "measures"]


def test_a_language_without_a_word_list_is_reported_as_not_checked():
    """No list, no guess: the report says the measure check did not run."""
    groups = [group(("EZK", 40, verse), "cinco", 5, "codos") for verse in range(1, 5)]
    style = analyze(groups, validate_style_profile(None), "xx")
    assert not [item for item in style["patterns"] if item["area"] == "measures"]
    assert "no measure word list for language xx" in style["not_checked"][0]
    assert "Not checked: Measure-system consistency" in render(style, project="P")
