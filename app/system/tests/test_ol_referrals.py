"""Deterministic admission rules for selective source referrals."""

from __future__ import annotations

import pytest

from sage.errors import ValidationError
from sage.ol_referrals import (
    normalize_referral_admission,
    referral_conflict_key,
)


def _admission(**overrides: str) -> dict[str, str]:
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
    result = normalize_referral_admission(_admission(), index=1)

    assert result == _admission()


def test_referral_conflict_key_normalizes_case_and_whitespace() -> None:
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
    request = _admission()
    del request[field]

    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(request, index=2)

    assert caught.value.code == "SAW_OL_REFERRAL_FIELDS_MISSING"


def test_normalize_referral_admission_rejects_open_ended_class() -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(
            _admission(conflict_class="LEXICAL_INTENSITY_DIFFERENCE"),
            index=3,
        )

    assert caught.value.code == "SAW_OL_REFERRAL_CLASS_INVALID"


def test_normalize_referral_admission_rejects_non_source_dependency() -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(
            _admission(source_dependency="RESOLVABLE_FROM_REFERENCE"),
            index=4,
        )

    assert caught.value.code == "SAW_OL_REFERRAL_ADMISSION_INVALID"


def test_normalize_referral_admission_rejects_identical_propositions() -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_referral_admission(
            _admission(
                wip_proposition=" The subject left. ",
                reference_proposition="the subject left.",
            ),
            index=5,
        )

    assert caught.value.code == "SAW_OL_REFERRAL_ADMISSION_INVALID"
