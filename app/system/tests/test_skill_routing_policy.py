"""Execution-ownership and exact Skill-route policy contracts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from sage.model_policy import load_model_policy
from sage.schema_validation import validate_schema_contracts


REGISTERED_SKILLS = (
    "bic-inspect",
    "bic-rewrite",
    "bic-self-check",
    "saw-rtc",
    "saw-stc",
    "saw-focused-check",
    "saw-original-language-review",
)


def _write_yaml(path: Path, value: dict[str, object]) -> None:
    """Write one controlled YAML fixture."""
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _ownership_fixture() -> dict[str, object]:
    """Return a complete independently specified ownership registry."""
    return {
        "schema_version": "1.0",
        "policy_version": "alpha1-1",
        "deterministic_python": {
            "planning": {"justification": "bounded local planning"},
            "report-composition": {"justification": "deterministic projection"},
            "token-measurement": {"justification": "local byte and token measurement"},
        },
        "local_assistive": {
            "status-explanation": {"authority": "NON_AUTHORITATIVE_ASSISTIVE"},
        },
        "governed_skills": {
            skill_id: {"execution_class": "GOVERNED_SKILL"}
            for skill_id in REGISTERED_SKILLS
        },
        "governed_subtasks": {
            "secondary-language-rendering": {
                "execution_class": "GOVERNED_SKILL",
                "route_source": "ORIGINATING_SKILL",
                "isolation": "ONE_REPORTED_ITEM_PER_REQUEST",
                "authority": "ASSISTIVE_TRANSLATION_ONLY",
            }
        },
    }


def test_schema_gate_rejects_an_unowned_registered_skill(package_root: Path, tmp_path: Path) -> None:
    """Deleting one Skill owner must block execution-policy validation."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    ownership = _ownership_fixture()
    del ownership["governed_skills"]["saw-stc"]  # type: ignore[index]
    _write_yaml(copy / "system/config/execution-ownership.yml", ownership)

    result = validate_schema_contracts(copy)

    assert result["status"] == "BLOCKED"
    assert "execution-ownership.yml missing registered Skill ownership: saw-stc" in result["errors"]


def test_schema_gate_rejects_model_routing_on_deterministic_work(package_root: Path, tmp_path: Path) -> None:
    """A Python-owned operation must not acquire a model route or token policy."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    ownership = _ownership_fixture()
    ownership["deterministic_python"]["report-composition"]["model_route"] = "codex"  # type: ignore[index]
    _write_yaml(copy / "system/config/execution-ownership.yml", ownership)

    result = validate_schema_contracts(copy)

    assert result["status"] == "BLOCKED"
    assert "execution-ownership.yml deterministic_python.report-composition contains prohibited model_route" in result["errors"]


def test_schema_gate_requires_exact_registered_skill_route_keys(package_root: Path, tmp_path: Path) -> None:
    """Routing policy must neither omit nor invent a registered analytical Skill."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    policy_path = copy / "system/config/model-policy.yml"
    policy = {
        "schema_version": "2.0",
        "qualification_policy_version": "alpha1-1",
        "unknown_route_status": "UNASSESSED",
        "accepted_operational_statuses": ["RECOMMENDED", "QUALIFIED"],
        "recommendation_order": [
            "hard_contracts",
            "cost_class",
            "provider_native_reasoning_order",
            "material_semantic_score",
            "release_preference",
        ],
        "skill_routes": {
            skill_id: {
                "suite_id": f"alpha1-{skill_id}",
                "execution_class": "GOVERNED_SKILL",
            }
            for skill_id in REGISTERED_SKILLS
            if skill_id != "saw-stc"
        },
    }
    _write_yaml(policy_path, policy)

    result = validate_schema_contracts(copy)

    assert result["status"] == "BLOCKED"
    assert "model-policy.yml missing registered Skill routes: saw-stc" in result["errors"]


def test_shipped_skill_route_keys_equal_the_registered_skill_inventory(package_root: Path) -> None:
    """The installed policy must route the exact governed Skill inventory."""
    skills = json.loads((package_root / "system/config/skills.json").read_text(encoding="utf-8"))
    policy = yaml.safe_load((package_root / "system/config/model-policy.yml").read_text(encoding="utf-8"))

    assert policy["schema_version"] == "2.0"
    assert set(policy["skill_routes"]) == set(skills["skills"])


def test_runtime_policy_loader_accepts_the_provider_neutral_contract(package_root: Path) -> None:
    """Runtime policy loading must return the same exact Skill-keyed contract."""
    policy = load_model_policy(package_root)

    assert policy["schema_version"] == "2.0"
    assert policy["qualification_policy_version"] == "alpha1-1"
    assert policy["accepted_operational_statuses"] == ["RECOMMENDED", "QUALIFIED"]
