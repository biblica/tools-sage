"""A BIC Job can bind SOURCE and TARGET to languages that ship only their one WIP profile."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from sage.grammar import compatible_variant_ids, profile_roles_for_job_role
from sage.jobs import JobStore


def _variants(**roles: str) -> dict[str, SimpleNamespace]:
    """Build a variant mapping like a language-profile namespace."""
    return {variant_id: SimpleNamespace(role=role) for variant_id, role in roles.items()}


def test_exact_role_variants_win_and_a_lone_wip_variant_serves_every_binding() -> None:
    """A dedicated variant keeps its binding without a new choice; otherwise the language's WIP profile serves."""
    only_wip = _variants(wip="WIP")
    for role in ("CONTENT_SOURCE", "GENERATED_TARGET", "WIP", "LEXICAL_DONOR", "REFERENCE"):
        assert compatible_variant_ids(only_wip, role) == ["wip"], role
    dedicated = _variants(source="CONTENT_SOURCE", wip="WIP", target="GENERATED_TARGET")
    assert compatible_variant_ids(dedicated, "CONTENT_SOURCE") == ["source"]
    assert compatible_variant_ids(dedicated, "GENERATED_TARGET") == ["target"]
    assert compatible_variant_ids(dedicated, "WIP") == ["wip"]
    assert "WIP" in profile_roles_for_job_role("CONTENT_SOURCE")
    assert profile_roles_for_job_role("ORIGINAL_LANGUAGE_GREEK") == frozenset({"ORIGINAL_LANGUAGE_GREEK"})


def test_bic_job_binds_source_and_target_to_wip_only_languages(make_workspace) -> None:
    """With every language reduced to one WIP variant, as SAGE ships, a BIC Job resolves its grammar itself."""
    root = make_workspace(qualification_status="VALIDATED")
    ecosystem_path = root / "ecosystem.yml"
    ecosystem = yaml.safe_load(ecosystem_path.read_text(encoding="utf-8"))
    for language, variant in (("id", "source"), ("en", "bol-target")):
        ecosystem["language_profiles"][language]["variants"][variant]["role"] = "WIP"
        profile_path = root / "system" / "config" / "profiles" / "grammar" / language / f"{variant}.yml"
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        profile["profile"]["role"] = "WIP"
        profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    ecosystem_path.write_text(yaml.safe_dump(ecosystem, sort_keys=False), encoding="utf-8")

    job = JobStore(root, ecosystem_path).create_job(
        tool="bic",
        job_id="BIC_idKKHv0-usNIVv2-usBOLx1",
        display_name="WIP-only languages",
        bindings={"content_source": "idKKHv0", "lexical_donor": "usNIVv2", "generated_target": "usBOLx1"},
    )
    assert job.profiles["source_grammar"] == "id/source"
    assert job.profiles["target_grammar"] == "en/bol-target"
    assert Path(root / "system" / "config" / "profiles" / "grammar" / "id" / "source.yml").is_file()
