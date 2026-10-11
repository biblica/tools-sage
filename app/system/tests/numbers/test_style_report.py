"""Number formatting consistency (numbers/style_report.py)."""
from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

from sage.numbers.models import Extraction
from sage.numbers.style import validate_style_profile
from sage.numbers.style_report import analyze, reconstructed_profile, render
from sage.vrs import VerseRef

F = Fraction


def group(ref, numbers, notes=()):
    """A minimal group: body numbers as (surface, value) pairs and footnote texts."""
    surfaces = tuple(surface for surface, _value in numbers)
    values = tuple(F(value) for _surface, value in numbers)
    target = SimpleNamespace(target_references=(VerseRef(*ref),),
                             notes=tuple(SimpleNamespace(text=text) for text in notes))
    return SimpleNamespace(projected=SimpleNamespace(target=target, western_references=(VerseRef(*ref),)),
                           extraction=Extraction(values, "COMPLETE", surfaces=surfaces))


UNCONFIGURED = validate_style_profile(None)


def body():
    """A translation that writes numbers as words, with a few digit slips and footnote metrics."""
    groups = [group(("EZR", 2, verse), [("сорок дві тисячі", 42000)], notes=("Близько 8,4 кг.",))
              for verse in range(1, 6)]
    groups.append(group(("EZR", 2, 6), [("2 172", 2172)], notes=("Близько 1.2 т.",)))
    groups.append(group(("EZR", 2, 7), [("тридцять", 30), ("п'ять", 5), ("сім", 7), ("двадцять", 20)]))
    return groups


def test_reconstruction_finds_the_dominant_style_and_the_slips():
    """Words dominate in the body: a digit numeral is a slip; a decimal point stands out in notes."""
    style = analyze(body(), UNCONFIGURED)
    assert style["basis"] == "RECONSTRUCTED"
    rules = {(rule["location"], rule["area"], rule.get("band", "")): rule["rule"] for rule in style["rules"]}
    assert rules[("BODY", "bands", "1000+")] == "WORDS"
    assert rules[("NOTE", "decimal", "")] == "comma"
    found = {(item["location"], item["area"], item["found"]): item for item in style["patterns"]}
    assert found[("BODY", "form", "digits")]["examples"] == ["EZR 2:6 «2 172»"]
    assert found[("NOTE", "decimal", "period")]["references"] == ["EZR 2:6"]


def test_reconstructed_profile_is_a_valid_importable_number_style_profile():
    """The reconstructed guide validates as a Number Style Profile, so importing it is the approval."""
    style = analyze(body(), UNCONFIGURED)
    profile = reconstructed_profile(style, project="ukrNPUv1", language="uk", script="Cyrl",
                                    recorded_date="2026-10-08", run_id="RUN-1")
    validated = validate_style_profile(profile, language="uk", script="Cyrl", project="ukrNPUv1")
    assert validated["rules"]["bands"]["status"] == "CONFIGURED"
    assert {band["form"] for band in validated["rules"]["bands"]["bands"]} == {"WORDS"}


def test_configured_profile_reports_variance():
    """With a profile, every number that departs from its rules is reported."""
    style = analyze(body(), UNCONFIGURED)
    profile = validate_style_profile(reconstructed_profile(
        style, project="ukrNPUv1", language="uk", script="Cyrl", recorded_date="2026-10-08", run_id="RUN-1"))
    checked = analyze(body(), profile)
    assert checked["basis"] == "PROFILE"
    assert any(item["area"] == "form" and item["found"] == "digits" for item in checked["patterns"])


def test_report_shows_rules_and_grouped_inconsistencies():
    """NUMBER-STYLE.md lists the reconstructed rules and one row per inconsistency pattern."""
    markdown = render(analyze(body(), UNCONFIGURED), project="ukrNPUv1", profile_path="RUN-1_PROFILE.yml")
    assert "# Number style — ukrNPUv1 (reconstructed)" in markdown
    assert "Reconstructed profile: `RUN-1_PROFILE.yml`" in markdown
    assert "## Inconsistencies" in markdown and "EZR 2:6 «2 172»" in markdown


def test_mixed_number_is_not_read_as_ungrouped():
    """ "12 тисяч" (12 000) says nothing about digit grouping: no false "none" grouping rule."""
    groups = [group(("EZR", 2, verse), [("12 тисяч", 12000)]) for verse in range(1, 6)]
    style = analyze(groups, UNCONFIGURED)
    assert not [rule for rule in style["rules"] if rule["area"] == "grouping"]


def test_reconstructed_profile_keeps_the_translation_digit_script():
    """A translation in Arabic-Indic digits gets an Arabic-Indic profile, not a Latin one."""
    groups = [group(("EZR", 2, verse), [("٣٠٠", 300)]) for verse in range(1, 6)]
    profile = reconstructed_profile(analyze(groups, UNCONFIGURED), project="arbWIP", language="ar",
                                    script="Arab", recorded_date="2026-10-09", run_id="RUN-1")
    assert profile["rules"]["digits"]["preferred"] == "٠١٢٣٤٥٦٧٨٩"
    validate_style_profile(profile, language="ar", script="Arab", project="arbWIP")
