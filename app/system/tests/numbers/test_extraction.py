"""Exact NCA model evidence validation over immutable target streams."""

from __future__ import annotations

from fractions import Fraction

import pytest

from sage.errors import ValidationError
from sage.numbers.extraction import build_extraction_payload, validate_extraction_response
from sage.numbers.models import TargetNote, TargetUnit
from sage.vrs import VerseRef


def target(text: str, *, note: str = "") -> TargetUnit:
    """Build one hand-specified target unit with an optional isolated note."""
    notes = ()
    if note:
        notes = (
            TargetNote("note-1", "+", note, (VerseRef("GEN", 14, 14),), ()),
        )
    return TargetUnit(
        "GEN 14:14",
        (VerseRef("GEN", 14, 14),),
        text,
        notes,
        "0" * 64,
        {"line_start": 14, "line_end": 14},
    )


def expression(
    expression_id: str,
    surface: str,
    start: int,
    end: int,
    value: str,
    **changes: object,
) -> dict[str, object]:
    """Return one literal response expression for validator tests."""
    item: dict[str, object] = {
        "expression_id": expression_id,
        "stream_id": "main",
        "surface": surface,
        "span": {"start": start, "end": end},
        "values": [value],
        "kind": "CARDINAL",
        "unit": None,
        "qualifier": "EXACT",
        "role": "men",
        "role_spans": [],
        "representations": [],
    }
    item.update(changes)
    return item


def response(
    unit: TargetUnit,
    expressions: list[dict[str, object]],
    *,
    status: str = "COMPLETE",
    limitations: list[str] | None = None,
    confidence: float | None = None,
) -> dict[str, object]:
    """Wrap expressions in the one-unit extraction response contract."""
    item: dict[str, object] = {
        "unit_id": unit.unit_id,
        "status": status,
        "limitations": limitations or [],
        "expressions": expressions,
    }
    if confidence is not None:
        item["confidence"] = confidence
    return {"schema_version": "1.0", "phase": "EXTRACTION", "work_units": [item]}


def test_payload_contains_only_bounded_target_and_parsing_conventions() -> None:
    """Extraction input cannot reveal OL/NIV values, notes, locators, or arbitrary profile prose."""
    unit = target("three hundred and eighteen men", note="variant 317")
    profile = {
        "profile": {"language": "en", "source_guide": "OL value is 318"},
        "rules": {
            "digits": {"status": "CONFIGURED", "preferred": "0123456789"},
            "grouping": {"status": "CONFIGURED", "separator": ",", "minimum": "1000"},
            "contexts": {"status": "CONFIGURED", "instructions": "Use NIV"},
        },
        "ol_values": [318],
    }

    payload = build_extraction_payload(unit, language="en", style_profile=profile)

    assert payload == {
        "schema_version": "1.0",
        "phase": "EXTRACTION",
        "language": "en",
        "work_units": [
            {
                "unit_id": "GEN 14:14",
                "streams": [{"stream_id": "main", "text": "three hundred and eighteen men"}],
            }
        ],
        "parsing_conventions": {
            "digits": {"preferred": "0123456789"},
            "grouping": {"separator": ","},
        },
        "output_schema_id": "sage-nca-extraction-1.0#extraction",
    }


def test_exact_cardinal_span_and_fraction_value_are_preserved() -> None:
    """Changing slice equality or exact Fraction parsing breaks accepted extraction evidence."""
    unit = target("three hundred and eighteen men")

    result = validate_extraction_response(
        unit,
        response(unit, [expression("target-1", "three hundred and eighteen", 0, 26, "318")]),
    )

    item = result.expressions[0]
    assert item.values == (Fraction(318),)
    assert item.surface == "three hundred and eighteen"
    assert item.span == (0, 26)
    assert item.expression_id == "target-1"
    assert item.stream_id == "main"


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [("the third man", "ORDINAL", "3"), ("a third of the men", "FRACTION", "1/3")],
)
def test_ordinal_and_fraction_meanings_remain_distinct(text: str, kind: str, value: str) -> None:
    """Equal numeric values cannot collapse ordinal and fractional kinds."""
    unit = target(text)
    start = text.index("third")
    item = expression("target-1", "third", start, start + 5, value, kind=kind)

    result = validate_extraction_response(unit, response(unit, [item]))

    assert result.expressions[0].kind == kind
    assert result.expressions[0].values == (Fraction(value),)


def test_partial_status_survives_self_reported_high_confidence() -> None:
    """Model confidence cannot upgrade explicitly ambiguous interpretation evidence."""
    unit = target("a disputed number word")

    result = validate_extraction_response(
        unit,
        response(
            unit,
            [],
            status="PARTIAL",
            limitations=["Number word has two plausible readings"],
            confidence=0.999,
        ),
    )

    assert result.status == "PARTIAL"
    assert result.limitations == ("Number word has two plausible readings",)


@pytest.mark.parametrize(
    ("text", "items", "expected"),
    [
        ("٣ men", [expression("target-1", "٣", 0, 1, "3")], ((Fraction(3),),)),
        ("1,234 men", [expression("target-1", "1,234", 0, 5, "1234")], ((Fraction(1234),),)),
        ("1,2 men", [expression("target-1", "1,2", 0, 3, "6/5")], ((Fraction(6, 5),),)),
        ("2 1/2 cubits", [expression("target-1", "2 1/2", 0, 5, "5/2", kind="FRACTION", unit="cubit")], ((Fraction(5, 2),),)),
        ("3:5 ratio", [expression("target-1", "3:5", 0, 3, "3", kind="RATIO", values=["3", "5"])], ((Fraction(3), Fraction(5)),)),
        ("3–5 men", [expression("target-1", "3–5", 0, 3, "3", kind="RANGE", values=["3", "5"])], ((Fraction(3), Fraction(5)),)),
        ("about 3 men", [expression("target-1", "about 3", 0, 7, "3", qualifier="ABOUT")], ((Fraction(3),),)),
    ],
)
def test_exact_numeric_forms_do_not_round_trip_through_float(
    text: str,
    items: list[dict[str, object]],
    expected: tuple[tuple[Fraction, ...], ...],
) -> None:
    """Unicode and ambiguous display forms retain model-declared reduced rational meanings exactly."""
    unit = target(text)

    result = validate_extraction_response(unit, response(unit, items))

    assert tuple(item.values for item in result.expressions) == expected


def test_repeated_quantities_require_distinct_ids_and_exact_spans() -> None:
    """Multiplicity survives validation instead of collapsing repeated values into a set."""
    unit = target("three men and three women")
    items = [
        expression("target-1", "three", 0, 5, "3", role="men"),
        expression("target-2", "three", 14, 19, "3", role="women"),
    ]

    result = validate_extraction_response(unit, response(unit, items))

    assert [item.expression_id for item in result.expressions] == ["target-1", "target-2"]
    assert [item.span for item in result.expressions] == [(0, 5), (14, 19)]


def test_words_and_parenthesized_digits_preserve_equal_representations() -> None:
    """One dual-form quantity retains both exact evidence spans only when their values agree."""
    unit = target("three (3) men")
    item = expression(
        "target-1",
        "three (3)",
        0,
        9,
        "3",
        representations=[
            {"surface": "three", "span": {"start": 0, "end": 5}, "value": "3"},
            {"surface": "3", "span": {"start": 7, "end": 8}, "value": "3"},
        ],
    )

    result = validate_extraction_response(unit, response(unit, [item]))

    assert result.expressions[0].representations == (
        {"surface": "three", "span": (0, 5), "value": "3"},
        {"surface": "3", "span": (7, 8), "value": "3"},
    )


def test_conflicting_parenthesized_representation_values_are_rejected() -> None:
    """A parenthetical digit cannot silently contradict its word representation."""
    unit = target("three (4) men")
    item = expression(
        "target-1",
        "three (4)",
        0,
        9,
        "3",
        representations=[
            {"surface": "three", "span": {"start": 0, "end": 5}, "value": "3"},
            {"surface": "4", "span": {"start": 7, "end": 8}, "value": "4"},
        ],
    )

    with pytest.raises(ValidationError) as exc:
        validate_extraction_response(unit, response(unit, [item]))
    assert exc.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"


def test_parenthesized_dual_form_cannot_omit_one_representation_span() -> None:
    """A words-plus-digits surface must not discard either independently checkable representation."""
    unit = target("three (3) men")
    item = expression(
        "target-1",
        "three (3)",
        0,
        9,
        "3",
        representations=[
            {"surface": "3", "span": {"start": 7, "end": 8}, "value": "3"},
        ],
    )

    with pytest.raises(ValidationError) as exc:
        validate_extraction_response(unit, response(unit, [item]))

    assert exc.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.update(surface="invented"),
        lambda item: item.update(span={"start": 0, "end": 99}),
        lambda item: item.update(values=[318]),
        lambda item: item.update(values=[318.0]),
        lambda item: item.update(values=["318/2"]),
        lambda item: item.update(stream_id="note:note-1"),
        lambda item: item.update(role_spans=[{"start": 27, "end": 99, "surface": "men"}]),
    ],
)
def test_fabricated_or_noncanonical_expression_evidence_is_rejected(mutate) -> None:
    """Unsupported types, invented streams, bad spans, and unreduced values fail closed."""
    unit = target("three hundred and eighteen men", note="note 317")
    item = expression("target-1", "three hundred and eighteen", 0, 26, "318")
    mutate(item)

    with pytest.raises(ValidationError) as exc:
        validate_extraction_response(unit, response(unit, [item]))
    assert exc.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"


def test_absent_work_unit_duplicate_ids_and_duplicate_spans_are_rejected() -> None:
    """The validator cannot accept missing coverage or count one target span twice."""
    unit = target("three men")
    missing = response(unit, [])
    missing["work_units"] = []
    with pytest.raises(ValidationError) as absent:
        validate_extraction_response(unit, missing)
    assert absent.value.code == "NCA_EXTRACTION_COVERAGE_INVALID"

    duplicated = [
        expression("target-1", "three", 0, 5, "3"),
        expression("target-1", "three", 0, 5, "3"),
    ]
    with pytest.raises(ValidationError) as duplicate_id:
        validate_extraction_response(unit, response(unit, duplicated))
    assert duplicate_id.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"

    duplicated[1]["expression_id"] = "target-2"
    with pytest.raises(ValidationError) as duplicate_span:
        validate_extraction_response(unit, response(unit, duplicated))
    assert duplicate_span.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"


def test_overlapping_primary_expressions_cannot_double_count_one_span() -> None:
    """A range and nested cardinal cannot claim the same target characters as separate quantities."""
    unit = target("3-5 men")
    items = [
        expression("target-1", "3-5", 0, 3, "3", kind="RANGE", values=["3", "5"]),
        expression("target-2", "3", 0, 1, "3"),
    ]

    with pytest.raises(ValidationError) as exc:
        validate_extraction_response(unit, response(unit, items))

    assert exc.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"


@pytest.mark.parametrize(
    ("kind", "values"),
    [("CARDINAL", ["3", "5"]), ("ORDINAL", ["3", "5"]), ("FRACTION", ["1/3", "1/2"]), ("RANGE", ["3"]), ("RATIO", ["3"])],
)
def test_numeric_kind_requires_its_exact_value_arity(kind: str, values: list[str]) -> None:
    """Malformed scalar and pair meanings cannot enter deterministic comparison."""
    unit = target("3-5 men")
    item = expression("target-1", "3-5", 0, 3, values[0], kind=kind, values=values)

    with pytest.raises(ValidationError) as exc:
        validate_extraction_response(unit, response(unit, [item]))

    assert exc.value.code == "NCA_EXTRACTION_EVIDENCE_INVALID"


def test_unknown_response_fields_and_invalid_status_contracts_are_rejected() -> None:
    """Schema drift and unsupported status vocabularies cannot enter typed extraction state."""
    unit = target("three men")
    raw = response(unit, [expression("target-1", "three", 0, 5, "3")])
    raw["unexpected"] = True
    with pytest.raises(ValidationError) as unknown:
        validate_extraction_response(unit, raw)
    assert unknown.value.code == "NCA_EXTRACTION_SCHEMA_INVALID"

    raw = response(unit, [], status="CERTAIN")
    with pytest.raises(ValidationError) as status:
        validate_extraction_response(unit, raw)
    assert status.value.code == "NCA_EXTRACTION_SCHEMA_INVALID"


def test_shared_expression_boundary_requires_the_admitted_note_stream() -> None:
    """The v2 note inventory uses its own exact text and identity with legacy semantics."""
    from sage.numbers.extraction import _validated_expression
    raw = expression('note-local', 'three', 0, 5, '3', stream_id='note-2')
    result = _validated_expression(raw, text='three women', expected_stream_id='note-2')
    assert result.stream_id == 'note-2' and result.values == (Fraction(3),)
    with pytest.raises(ValidationError):
        _validated_expression(raw, text='three women', expected_stream_id='note-1')
