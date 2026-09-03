"""Deterministic admission rules for selective source referrals."""

from __future__ import annotations

import pytest

from sage.errors import ValidationError
from sage.ol_referrals import (
    normalize_referral_admission,
    referral_conflict_key,
)


def _admission(**overrides: str) -> dict[str, str]:
    """Build one valid referral-admission record with optional field overrides."""
    value = {
        "conflict_class": "NEGATION_OR_POLARITY_CONFLICT",
        "wip_proposition": "The subject did not leave.",
        "reference_proposition": "The subject left.",
        "fundamental_impact": "The event polarity is reversed.",
        "source_dependency": "UNRESOLVED_REQUIRES_ORIGINAL_LANGUAGE",
    }
    value.update(overrides)
    return value


def test_normalize_referral_admission_accepts_closed_contract() -> None:
    """Verify that the closed V1 admission record survives normalization."""
    result = normalize_referral_admission(_admission(), index=1)

    assert result == _admission()


def test_referral_conflict_key_normalizes_case_and_whitespace() -> None:
    """Verify that harmless casing and spacing changes keep one conflict key."""
    first = referral_conflict_key(
        target_reference="JHN 1:1",
        conflict_class="NEGATION_OR_POLARITY_CONFLICT",
        wip_proposition="  He DID not leave. ",
        reference_proposition="He left.",
    )
    second = referral_conflict_key(
        target_reference="jhn 1:1",
        conflict_class="negation_or_polarity_conflict",
        wip_proposition="he did not leave.",
        reference_proposition="he left.",
    )

    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize(
    "field",
    (
        "conflict_class",
        "wip_proposition",
        "reference_proposition",
        "fundamental_impact",
        "source_dependency",
    ),
)
def test_normalize_referral_admission_rejects_missing_fields(field: str) -> None:
    """Verify that every V1 admission field is mandatory."""
    request = _admission()
    del request[field]

    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(request, index=2)

    assert caught.value.code == "SAW_OL_REFERRAL_FIELDS_MISSING"


def test_current_rtc_referral_errors_use_the_rtc_namespace() -> None:
    """Current RTC validation must never expose a retired workflow error code."""
    request = _admission()
    del request["source_dependency"]

    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(request, index=1, workflow="rtc")

    assert caught.value.code == "RTC_OL_REFERRAL_FIELDS_MISSING"
    assert "SAW" not in caught.value.message


def test_normalize_referral_admission_rejects_open_ended_class() -> None:
    """Verify that an unlisted conflict class cannot open a source referral."""
    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(
            _admission(conflict_class="LEXICAL_INTENSITY_DIFFERENCE"),
            index=3,
        )

    assert caught.value.code == "SAW_OL_REFERRAL_CLASS_INVALID"


def test_normalize_referral_admission_rejects_non_source_dependency() -> None:
    """Verify that reference-resolvable differences cannot reach source review."""
    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(
            _admission(source_dependency="RESOLVABLE_FROM_REFERENCE"),
            index=4,
        )

    assert caught.value.code == "SAW_OL_REFERRAL_ADMISSION_INVALID"


def test_normalize_referral_admission_rejects_identical_propositions() -> None:
    """Verify that identical normalized propositions cannot form a conflict."""
    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(
            _admission(
                wip_proposition=" The subject left. ",
                reference_proposition="the subject left.",
            ),
            index=5,
        )

    assert caught.value.code == "SAW_OL_REFERRAL_ADMISSION_INVALID"
