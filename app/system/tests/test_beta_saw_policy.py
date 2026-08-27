"""Beta language-identification and SAW check-policy regression contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.language_identification import (
    estimate_language_identity,
    parse_ldml_identity,
    resolve_country,
    resolve_country_input,
)
from sage.saw_policy import default_standard_qa_policy, should_elevate, write_run_policy_snapshot


def test_beta_standard_qa_policy_defaults(package_root: Path) -> None:
    """Verify Beta enables four standard checks and uses explicit marker-context policy modes."""
    policy = default_standard_qa_policy(package_root / "system/config/workflows/saw/profile.yml")
    assert all(policy["checks"].values())
    assert policy["usfm_contexts"]["add"] == "MATERIAL_ONLY"
    assert policy["usfm_contexts"]["nd"] == "MATERIAL_ONLY"
    assert policy["usfm_contexts"]["f"] == "STRUCTURE_ONLY"
    assert policy["usfm_contexts"]["x"] == "STRUCTURE_ONLY"
    assert "qt" not in policy["usfm_contexts"]
    assert policy["original_language"]["source_text_drift_adjudication"] == "PROHIBITED"


def test_beta_material_only_omits_nonmaterial_without_downgrading() -> None:
    """Verify MATERIAL_ONLY controls finding elevation rather than converting findings to LOW severity."""
    assert not should_elevate(mode="MATERIAL_ONLY", category="STYLE", material=False, structural=False)
    assert should_elevate(mode="MATERIAL_ONLY", category="MEANING", material=True, structural=False)
    assert should_elevate(mode="MATERIAL_ONLY", category="USFM", material=False, structural=True)
    assert not should_elevate(mode="STRUCTURE_ONLY", category="MEANING", material=True, structural=False)


def test_beta_run_policy_snapshot_is_immutable(tmp_path: Path) -> None:
    """Verify the effective Standard-QA policy is sealed once inside a Run and cannot drift later."""
    policy = default_standard_qa_policy()
    path = write_run_policy_snapshot(tmp_path, policy)
    assert json.loads(path.read_text(encoding="utf-8"))["usfm_contexts"]["add"] == "MATERIAL_ONLY"
    changed = default_standard_qa_policy()
    changed["usfm_contexts"]["add"] = "NORMAL"
    with pytest.raises(ValidationError) as caught:
        write_run_policy_snapshot(tmp_path, changed)
    assert caught.value.code == "SAW_POLICY_IMMUTABLE"


def test_beta_language_evidence_reads_all_ldml_and_requires_country_choice_when_multiple(tmp_path: Path) -> None:
    """Verify LDML identities and project prefix corroborate ISO while multiple countries remain Operator-selected."""
    (tmp_path / "id.ldml").write_text(
        '<ldml><identity><language type="id"/><script type="Latn"/><territory type="ID"/></identity></ldml>',
        encoding="utf-8",
    )
    (tmp_path / "id-MY.ldml").write_text(
        '<ldml><identity><language type="id"/><script type="Latn"/><territory type="MY"/></identity></ldml>',
        encoding="utf-8",
    )
    rows = [parse_ldml_identity(path) for path in sorted(tmp_path.glob("*.ldml"))]
    result = estimate_language_identity(
        project_code="idKKHv0",
        settings_code="id",
        language_name="Indonesian",
        ldml_rows=rows,
    )
    assert result["selected"]["alpha_3"] == "ind"
    assert result["selected"]["preferred"] == "id"
    assert {row["code"] for row in result["country_evidence"]} == {"ID", "MY"}
    assert result["primary_country"] is None
    assert result["bcp47_candidate"] is None


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("us", "US"),
        ("USA", "US"),
        ("840", "US"),
        ("United States", "US"),
        ("United States of America", "US"),
    ),
)
def test_beta_country_resolver_accepts_common_iso_identifiers_and_names(value: str, expected: str) -> None:
    """Verify country entry accepts the identifiers Operators commonly try at the selector."""
    country = resolve_country(value)
    assert country is not None
    assert country["code"] == expected


@pytest.mark.parametrize("value", ("en-US", "en-us", "en_US"))
def test_beta_country_input_accepts_regional_language_tags(value: str) -> None:
    """Verify a regional language tag can supply its country component at country selection."""
    country = resolve_country_input(value)
    assert country is not None
    assert country["code"] == "US"


@pytest.mark.parametrize("value", ("", "not-a-country", "en"))
def test_beta_country_input_rejects_blank_or_unresolved_values(value: str) -> None:
    """Verify invalid country input remains unresolved so the menu can return actionable guidance."""
    assert resolve_country_input(value) is None
