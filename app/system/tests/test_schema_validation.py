"""Schema-contract integrity and package-gate tests."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from sage.schema_validation import validate_schema_contracts
from sage.validation import validate_package


def test_all_schema_contracts_and_source_instances_validate(package_root: Path) -> None:
    """Verify every shipped schema and source-owned instance passes the schema gate."""
    result = validate_schema_contracts(package_root)
    assert result["status"] == "PASS", result
    assert result["schema_count"] == 39
    assert result["schema_ids"] == 39
    assert result["owner_count"] == 39
    assert result["source_instance_groups"] == 9


def test_schema_validation_rejects_duplicate_yaml_keys(package_root: Path, tmp_path: Path) -> None:
    """Verify duplicate YAML keys block schema validation."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    path = copy / "system/config/schemas/run.schema.yml"
    path.write_text(path.read_text(encoding="utf-8") + "required: []\n", encoding="utf-8")
    result = validate_schema_contracts(copy)
    assert result["status"] == "BLOCKED"
    assert any("duplicate key" in item for item in result["errors"])


def test_package_gate_requires_every_schema_contract(package_root: Path, tmp_path: Path) -> None:
    """Verify package validation blocks omission of any governed schema contract."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    (copy / "system/config/schemas/resource-rights.schema.yml").unlink()
    result = validate_package(copy)
    assert result["status"] == "BLOCKED"
    assert any("resource-rights.schema.yml" in item for item in result["errors"])


def test_schema_validation_checks_bundled_ol_authority_profile_instances(package_root: Path, tmp_path: Path) -> None:
    """Require bundled GRK/HEB authority profiles to satisfy their registered schema."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    path = copy / "system/resources/scripture/original-language/grk/authority-profile.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.pop("interpretation")
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    result = validate_schema_contracts(copy)
    assert result["status"] == "BLOCKED"
    assert any("authority-profile.yml missing required fields: interpretation" in item for item in result["errors"])
