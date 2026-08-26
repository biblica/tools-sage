"""Paratext/PTLite project short-name grammar tests."""

from sage.project_codes import parse_project_code


def test_three_character_language_pattern_is_case_delimited() -> None:
    """Parse the common three-character language plus three-letter abbreviation pattern."""
    parts = parse_project_code("xxxYYYv0")
    assert parts.parse_status == "PARSED"
    assert parts.paratext_language_code == "xxx"
    assert parts.abbreviation == "YYY"
    assert parts.type_code == "v"
    assert parts.iteration == 0


def test_two_character_language_pattern_is_case_delimited() -> None:
    """Parse the common two-character language plus four-letter abbreviation pattern."""
    parts = parse_project_code("xxYYYYx0")
    assert parts.parse_status == "PARSED"
    assert parts.paratext_language_code == "xx"
    assert parts.abbreviation == "YYYY"
    assert parts.type_name == "BACKTRANSLATION"
    assert parts.iteration == 0


def test_common_shorter_project_codes_are_valid() -> None:
    """Accept established shorter names that still satisfy the governed case grammar."""
    assert parse_project_code("idKKHv0").parse_status == "PARSED"
    assert parse_project_code("usNIVv2").iteration == 2


def test_unknown_type_is_registrable_but_requires_review() -> None:
    """Keep an unknown lowercase type code usable while requiring operator review."""
    parts = parse_project_code("idKKHq3")
    assert parts.parse_status == "PARTIAL"
    assert parts.type_name is None
    assert parts.iteration == 3
    assert parts.review_required is True


def test_iteration_does_not_encode_scope_or_role() -> None:
    """Keep lifecycle iteration independent from Scripture scope and Job role."""
    parts = parse_project_code("idKKHv9")
    payload = parts.to_dict()
    assert "scope" not in payload
    assert "role" not in payload
    assert parts.iteration == 9


def test_over_eight_characters_is_invalid() -> None:
    """Reject a project short name that exceeds the Paratext eight-character ceiling."""
    parts = parse_project_code("xxxxYYYYv0")
    assert parts.parse_status == "INVALID"
    assert parts.review_required is True


def test_nonconforming_established_code_remains_unparsed_not_inferred() -> None:
    """Keep a safe nonconforming established code registrable without invented metadata."""
    parts = parse_project_code("GRK")
    assert parts.parse_status == "UNPARSED"
    assert parts.abbreviation is None
    assert parts.iteration is None
