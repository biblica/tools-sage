"""Canonical embedded original-language authority profile tests."""

from __future__ import annotations

import json

import yaml

from sage.registry import load_ecosystem
from sage.original_language_resources import ol_state_path, resolve_ol_authority_profile, resolved_ol_entry


def test_bundled_grk_profile_explicitly_excludes_modern_greek(package_root) -> None:
    """Require the GRK authority profile to lock Ancient Greek and reject Modern Greek drift."""
    profile = resolve_ol_authority_profile(package_root, "GRK")
    text = open(profile["path"], encoding="utf-8").read()
    assert profile["status"] == "READY"
    assert profile["historical_register"] == "NEW_TESTAMENT_GREEK"
    assert "not Modern Greek" in text


def test_bundled_heb_profile_explicitly_excludes_modern_hebrew(package_root) -> None:
    """Require the HEB authority profile to lock Biblical Hebrew and reject Modern Hebrew drift."""
    profile = resolve_ol_authority_profile(package_root, "HEB")
    text = open(profile["path"], encoding="utf-8").read()
    assert profile["status"] == "READY"
    assert profile["historical_register"] == "BIBLICAL_HEBREW"
    assert "not Modern Israeli Hebrew" in text


def test_ol_resource_carries_authority_role_without_language_profile_requirement(package_root) -> None:
    """Keep OL authority roles independent from user-selected project language profiles."""
    row = resolved_ol_entry(package_root, "GRK")
    assert row["authority_family"] == "GRK"
    assert row["authority_role"] == "PRIMARY"
    assert row["secondary_authorities"] == []
    assert row["language_profile_required"] is False
    assert row["authority_profile"]["status"] == "READY"


def test_secondary_ol_authorities_are_registered_but_inert_until_explicitly_routed(make_workspace) -> None:
    """Allow 0..n future secondary authorities without injecting them into current analytics."""
    root = make_workspace()
    state_path = ol_state_path(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "resources": {
                    "GRK": {
                        "source": "BUNDLED",
                        "secondary_authorities": [
                            {
                                "authority_id": "GRK-ALT-1",
                                "authority_role": "SECONDARY",
                                "source": "LOCAL",
                                "path": "/future/grk-alt-1",
                            },
                            {
                                "authority_id": "GRK-ALT-2",
                                "authority_role": "SECONDARY",
                                "source": "PARATEXT",
                                "path": "/future/grk-alt-2",
                            },
                        ],
                    },
                    "HEB": {"source": "BUNDLED", "secondary_authorities": []},
                },
            }
        ),
        encoding="utf-8",
    )

    row = resolved_ol_entry(root, "GRK")
    assert [item["authority_id"] for item in row["secondary_authorities"]] == ["GRK-ALT-1", "GRK-ALT-2"]
    assert {item["authority_role"] for item in row["secondary_authorities"]} == {"SECONDARY"}
    assert {item["analytical_effect"] for item in row["secondary_authorities"]} == {"INERT_UNLESS_EXPLICITLY_ROUTED"}

    config = load_ecosystem(root / "ecosystem.yml")
    assert config.project("GRK").project_id == "GRK"
    assert "GRK-ALT-1" not in config.projects
    assert "GRK-ALT-2" not in config.projects


def test_work_unit_schema_names_only_routed_sfm_hard_limit(package_root) -> None:
    """Prevent serialized packet/PACK language from becoming a second sizing authority."""
    schema = yaml.safe_load((package_root / "system" / "config" / "schemas" / "work-unit-manifest.schema.yml").read_text(encoding="utf-8"))
    controls = set(schema["controls"])
    assert "final_routed_sfm_review_item_within_hard_limits" in controls
    assert "final_serialized_packet_within_hard_limits" not in controls
