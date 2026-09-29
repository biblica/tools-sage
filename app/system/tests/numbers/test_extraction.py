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


def test_validated_extraction_item_preserves_ordered_values_and_completeness() -> None:
    """Multiplicity and reading order survive validation without becoming a set."""
    item = extraction._validated_extraction_item(
        {"status": "COMPLETE", "limitations": [], "values": ["3", "3", "14"]}
    )
    assert item == Extraction((Fraction(3), Fraction(3), Fraction(14)), "COMPLETE", ())


def test_incomplete_status_without_a_limitation_is_rejected() -> None:
    """PARTIAL/UNSUPPORTED must state why -- silence cannot pass as completeness."""
    with pytest.raises(ValidationError) as exc:
        extraction._validated_extraction_item({"status": "PARTIAL", "limitations": [], "values": []})
    assert exc.value.code == "NCA_EXTRACTION_SCHEMA_INVALID"


def test_unknown_status_is_rejected() -> None:
    """An invented completeness vocabulary cannot enter typed extraction state."""
    with pytest.raises(ValidationError) as exc:
        extraction._validated_extraction_item({"status": "CERTAIN", "limitations": [], "values": []})
    assert exc.value.code == "NCA_EXTRACTION_SCHEMA_INVALID"


def test_non_canonical_value_strings_are_rejected() -> None:
    """A float, unreduced fraction, or non-string value fails the item, not the batch."""
    for values in ([318], ["318.0"], ["318/2"]):
        with pytest.raises(ValidationError) as exc:
            extraction._validated_extraction_item({"status": "COMPLETE", "limitations": [], "values": values})
        assert exc.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"
