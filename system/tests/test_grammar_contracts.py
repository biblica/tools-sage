"""Language-profile identity, role compatibility, and provenance tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sage.errors import ConfigurationError
from sage.grammar import compile_grammar_contract, load_grammar_profile
from sage.profiles import load_workflow_profile
from sage.registry import load_ecosystem


def test_target_language_profile_is_derived_for_bic_and_saw(make_workspace) -> None:
    """Verify that target language profile is derived for BIC and SAW."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    bic = load_workflow_profile(config, config.workflow("bic"))
    saw = load_workflow_profile(config, config.workflow("saw"))
    assert bic.language_profile_bindings["GENERATED_TARGET"] == "en/bol-target"
    assert saw.language_profile_bindings["WIP"] == "en/bol-target"


def test_language_profile_contract_is_content_addressed(make_workspace) -> None:
    """Verify that language profile contract is content addressed."""
    root = make_workspace()
    path = root / "system" / "config" / "profiles" / "grammar" / "en" / "bol-target.yml"
    first = load_grammar_profile(
        path,
        expected_profile_id="bol-target",
        expected_language="en",
        expected_role="TARGET",
    )
    first_contract = compile_grammar_contract(first, root / "cache")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["checks"][0]["review"] = "Changed governed rule."
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    second = load_grammar_profile(path)
    second_contract = compile_grammar_contract(second, root / "cache")
    assert first_contract["profile_sha256"] != second_contract["profile_sha256"]
    assert first_contract["cache"] != second_contract["cache"]
    assert Path(first_contract["cache"]).exists()
    assert Path(second_contract["cache"]).exists()


def test_project_language_profile_mismatch_is_blocked(make_workspace) -> None:
    """Verify that project language profile mismatch is blocked."""
    root = make_workspace()
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["projects"]["usBOLx1"]["language"]["profile"] = "id"
    settings.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="must match"):
        load_ecosystem(settings)


def test_nonpreferred_language_code_is_rejected(make_workspace) -> None:
    """Verify that nonpreferred language code is rejected."""
    root = make_workspace()
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["projects"]["usBOLx1"]["language"]["code"] = "eng"
    data["projects"]["usBOLx1"]["language"]["profile"] = "eng"
    settings.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="use 'en'"):
        load_ecosystem(settings)


def test_workflow_grammar_bindings_are_obsolete(make_workspace) -> None:
    """Verify that workflow grammar bindings are obsolete."""
    root = make_workspace()
    path = root / "system" / "config" / "workflows" / "bic" / "profile.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["grammar_bindings"] = {"GENERATED_TARGET": "legacy"}
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(ConfigurationError, match="obsolete grammar_bindings"):
        load_workflow_profile(config, config.workflow("bic"))
