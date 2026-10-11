"""Low-level NCA extraction contract helpers: rationals, conventions, and item validation.

Batch envelope validation (accepted/pending membership, identity reconciliation)
is covered end-to-end in test_batch_extraction.py. This file covers the small
building blocks build_batch_extraction_payload/validate_batch_extraction_response
are built from.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from sage.errors import ValidationError
from sage.numbers import extraction
from sage.numbers.models import Extraction


def test_fraction_requires_canonical_reduced_rational_strings() -> None:
    """Only exact, already-reduced rational spellings are accepted."""
    assert extraction._fraction("318", "values[0]") == Fraction(318)
    assert extraction._fraction("-3/4", "values[0]") == Fraction(-3, 4)
    for bad in ("01", "+1", "2/4", " 1", "1 ", "1.5", "1/0"):
        with pytest.raises(ValidationError) as exc:
            extraction._fraction(bad, "values[0]")
        assert exc.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"


@pytest.mark.parametrize("stage", ["parse", "format"])
@pytest.mark.parametrize("error_type", [ValueError, ZeroDivisionError, OverflowError])
def test_rational_conversion_failures_become_evidence_validation_errors(monkeypatch, stage, error_type):
    """Interpreter conversion failures cannot escape the shared exact-rational boundary."""

    class UnrenderableRational:
        """Represent a successful parse whose canonical rendering exceeds a runtime limit."""

        def __str__(self):
            """Raise the recorded canonical-conversion failure."""
            raise error_type("recorded rational conversion failure")

    def failed_fraction(value):
        """Reproduce the conversion boundary independently of interpreter digit-limit defaults."""
        if stage == "parse":
            raise error_type("recorded rational conversion failure")
        return UnrenderableRational()

    monkeypatch.setattr(extraction, "Fraction", failed_fraction)
    with pytest.raises(ValidationError) as exc:
        extraction._fraction("3", "values[0]")
    assert exc.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"
    assert isinstance(exc.value.__cause__, error_type)


def test_parsing_conventions_select_only_allowlisted_numeric_notation_fields() -> None:
    """Reference hints and unrecognized rule areas cannot enter the request."""
    profile = {
        "rules": {
            "digits": {"status": "CONFIGURED", "preferred": "0123456789", "unrelated": "x"},
            "grouping": {"status": "CONFIGURED", "separator": ","},
            "contexts": {"status": "CONFIGURED", "instructions": "Use NIV"},
        },
        "ol_values": [318],
    }

    conventions = extraction._parsing_conventions(profile)

    assert conventions == {
        "digits": {"preferred": "0123456789"},
        "grouping": {"separator": ","},
    }


def test_parsing_conventions_reject_unsupported_value_types() -> None:
    """A convention value outside the safe JSON-like set fails closed."""
    with pytest.raises(ValidationError) as exc:
        extraction._safe_convention_value(object())
    assert exc.value.code == "NCA_EXTRACTION_PAYLOAD_INVALID"


def _item(numbers, text="", status="COMPLETE", limitations=(), conventions=None):
    """Validate one contract-3.0 work unit against its text."""
    return extraction._validated_extraction_item(
        {"status": status, "limitations": list(limitations), "numbers": numbers}, text, conventions)


def _number(text, value, kind="CARDINAL", counts="", counts_en=""):
    """One contract-3.0 number object."""
    return {"text": text, "value": value, "kind": kind, "counts": counts, "counts_en": counts_en}


def test_validated_extraction_item_preserves_ordered_values_and_completeness() -> None:
    """Multiplicity and reading order survive validation; each value keeps its exact text."""
    text = "three men, three women, on the fourteenth day"
    item = _item([_number("three", "3"), _number("three", "3"), _number("fourteenth", "14", "ORDINAL")], text)
    assert item.values == (Fraction(3), Fraction(3), Fraction(14))
    assert item.kinds == ("CARDINAL", "CARDINAL", "ORDINAL")
    assert item.surfaces == ("three", "three", "fourteenth")
    assert item.spans == ((0, 5), (11, 16), (31, 41)) and item.status == "COMPLETE"


def test_incomplete_status_without_a_limitation_is_rejected() -> None:
    """PARTIAL/UNSUPPORTED must state why -- silence cannot pass as completeness."""
    with pytest.raises(ValidationError) as exc:
        _item([], status="PARTIAL")
    assert exc.value.code == "NCA_EXTRACTION_SCHEMA_INVALID"


def test_unknown_status_is_rejected() -> None:
    """An invented completeness vocabulary cannot enter typed extraction state."""
    with pytest.raises(ValidationError) as exc:
        _item([], status="CERTAIN")
    assert exc.value.code == "NCA_EXTRACTION_SCHEMA_INVALID"


def test_non_canonical_value_strings_are_dropped_as_partial() -> None:
    """A float, unreduced fraction, or non-string value is dropped with a limitation, never coerced."""
    for value in (318, "318.0", "318/2"):
        item = _item([_number("three hundred eighteen", value)], "three hundred eighteen men")
        assert item.status == "PARTIAL" and item.values == ()
        assert item.limitations[0].startswith("NCA_VALUE_MALFORMED")


def test_unknown_kind_or_missing_fields_stay_pending() -> None:
    """Each number carries exactly the contract fields and a convention kind."""
    for number in ({"text": "two", "value": "2", "kind": "NUMBER", "counts": "", "counts_en": ""},
                   {"text": "two", "value": "2", "kind": "CARDINAL"}):
        with pytest.raises(ValidationError) as exc:
            _item([number], "two men")
        assert exc.value.code == "NCA_EXTRACTION_SCHEMA_INVALID"


def test_model_cannot_claim_the_controller_only_not_required_status() -> None:
    """NOT_REQUIRED is assigned by SAGE for unindexed groups, never accepted from a model."""
    with pytest.raises(ValidationError):
        _item([], status="NOT_REQUIRED", limitations=["x"])


def test_number_text_must_be_in_the_verse() -> None:
    """A number whose text is not in the work unit is dropped (the model cannot invent evidence)."""
    item = _item([_number("сорок", "40"), _number("двісті", "200")], "сорок років")
    assert item.values == (Fraction(40),) and item.status == "PARTIAL"
    assert item.limitations == ("NCA_SURFACE_NOT_IN_TEXT: 'двісті'",)


def test_digit_numerals_are_read_locally_and_missed_ones_added() -> None:
    """SAGE reads digits itself: a wrong model value is corrected and flagged, a missed numeral is added."""
    text = "30 gold bowls, 410 matching silver bowls, and 1,000 other articles"
    item = _item([_number("30", "30", counts="gold bowls", counts_en="gold bowls"), _number("410", "400")], text)
    assert item.values == (Fraction(30), Fraction(410), Fraction(1000))
    assert item.origins == ("MODEL", "MODEL", "LOCAL")
    assert item.issues == ("NUMERAL_VALUE_DIFFERS:410:model=400",)
    assert item.counts_en[0] == "gold bowls"


def test_malformed_numeral_is_an_issue_not_a_value() -> None:
    """A numeral with no well-formed reading ("10,0000") is reported, not guessed."""
    item = _item([], "They counted 10,0000 men and 8,4 kg.")
    assert "MALFORMED_NUMERAL:10,0000" in item.issues
    assert item.values == (Fraction(42, 5),) and item.origins == ("LOCAL",)


def test_configured_conventions_decide_ambiguous_numerals() -> None:
    """With a style profile, "1,200" is read strictly under its separators."""
    grouped = _item([], "1,200 men", conventions={"grouping": {"separator": ","}})
    decimal = _item([], "1,2 kg", conventions={"decimal": {"separator": ","}, "grouping": {"separator": " "}})
    assert grouped.values == (Fraction(1200),) and decimal.values == (Fraction(6, 5),)


def test_parsing_conventions_carry_ordinal_rules_and_located_unit_forms() -> None:
    """Style-profile unit forms (stored per location) and ordinal rules reach the extractor."""
    from sage.numbers.style import validate_style_profile
    from .test_style import configured_profile, rule
    profile = configured_profile()
    rule(profile, 'ordinals', form='WORDS', suffixes=['th'])
    configured = {'status': 'CONFIGURED', 'form': 'FULL', 'spacing': 'SPACE', 'forms': {'CUBIT': ['cubit', 'cubits']}}
    rule(profile, 'units', locations={'body': configured, 'heading': {'status': 'NOT_SPECIFIED'},
                                      'footnote': {**configured, 'forms': {'CUBIT': ['cubits', 'cu.']}}})
    conventions = extraction._parsing_conventions(validate_style_profile(profile))
    assert conventions['ordinals'] == {'form': 'WORDS', 'suffixes': ['th']}
    assert conventions['units'] == {'forms': {'CUBIT': ['cubit', 'cubits', 'cu.']}}


def test_number_text_is_anchored_to_a_whole_token_never_inside_a_longer_numeral() -> None:
    """A "7" inside "17" is not the number: no LOCAL duplicate, no false VALUE_DIFFERENCE."""
    assert _item([_number("7", "7")], "on day 17, 7 rams").values == (Fraction(17), Fraction(7))
    assert _item([_number("7", "7"), _number("17", "17")], "17 sons and 7 daughters").values \
        == (Fraction(17), Fraction(7))
    assert _item([_number("seven", "7"), _number("seventy", "70")], "seventy elders and seven sons").values \
        == (Fraction(70), Fraction(7))


def test_unhashable_kind_is_a_schema_error_not_a_crash() -> None:
    """A malformed model kind is retried as invalid output, never a TypeError that stops the Run."""
    with pytest.raises(ValidationError) as caught:
        _item([_number("7", "7", kind=["CARDINAL"])], "7 rams")
    assert caught.value.code == "NCA_EXTRACTION_SCHEMA_INVALID"


def test_selected_conventions_with_unit_forms_select_the_same_way_twice() -> None:
    """Payload building re-selects conventions; unit forms must survive so stream hashes agree."""
    profile = {"rules": {"grouping": {"status": "CONFIGURED", "style": "WESTERN", "separator": " "},
                         "units": {"status": "CONFIGURED", "locations": {"body": {
                             "status": "CONFIGURED", "forms": {"cubit": ["kubit"]}}}}}}
    selected = extraction._parsing_conventions(profile)
    assert extraction._parsing_conventions({"rules": selected}) == selected
    assert selected["units"] == {"forms": {"cubit": ["kubit"]}}


def test_no_break_space_groups_like_the_configured_space() -> None:
    """ "12 000" with a no-break space is read under a space grouping, and the model's plain
    space still finds it."""
    conventions = {"grouping": {"style": "WESTERN", "separator": " "}}
    result = _item([_number("12 000", "12000")], "12 000 men", conventions=conventions)
    assert result.values == (Fraction(12000),) and result.status == "COMPLETE" and not result.issues
