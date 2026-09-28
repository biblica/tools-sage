"""Coverage for best-effort project-.ldml number/quotation convention extraction."""
from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.language_identification import parse_ldml_locale_conventions


def test_standard_ldml_numbers_block_is_extracted_reliably(tmp_path: Path) -> None:
    """The spec-defined <numbers> element is parsed with confidence."""
    path = tmp_path / "fr-FR.ldml"
    path.write_text(
        """
        <ldml>
          <numbers>
            <defaultNumberingSystem>latn</defaultNumberingSystem>
            <symbols numberSystem="latn">
              <decimal>,</decimal>
              <group>&#160;</group>
            </symbols>
          </numbers>
        </ldml>
        """,
        encoding="utf-8",
    )
    result = parse_ldml_locale_conventions(path)
    assert result["file"] == "fr-FR.ldml"
    assert result["numbers"] == {"numbering_system": "latn", "decimal_separator": ",", "group_separator": " "}


def test_plausible_sil_punctuation_block_is_extracted_as_best_effort(tmp_path: Path) -> None:
    """A SIL/Palaso-style quotation-mark special block yields an open/close pair."""
    path = tmp_path / "custom.ldml"
    path.write_text(
        """
        <ldml>
          <special xmlns:sil="urn:sil-example">
            <sil:quotationMarks open="«" close="»"/>
          </special>
        </ldml>
        """,
        encoding="utf-8",
    )
    result = parse_ldml_locale_conventions(path)
    assert result["punctuation"] == {"quote_start": "«", "quote_end": "»"}


def test_neither_block_present_returns_none_gracefully(tmp_path: Path) -> None:
    """No <numbers> or quotation-shaped <special> content must not raise."""
    path = tmp_path / "bare.ldml"
    path.write_text("<ldml><identity><language type=\"en\"/></identity></ldml>", encoding="utf-8")
    result = parse_ldml_locale_conventions(path)
    assert result == {"file": "bare.ldml", "numbers": None, "punctuation": None}


def test_malformed_ldml_raises_validation_error(tmp_path: Path) -> None:
    """Genuinely malformed XML must raise, distinct from merely-absent expected content."""
    path = tmp_path / "broken.ldml"
    path.write_text("<ldml><numbers>", encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        parse_ldml_locale_conventions(path)
    assert caught.value.code == "PARATEXT_LDML_INVALID"
