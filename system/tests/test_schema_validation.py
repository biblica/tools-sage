"""Schema-contract integrity and package-gate tests."""
from __future__ import annotations

import shutil
from pathlib import Path

from sage.schema_validation import validate_schema_contracts
from sage.validation import validate_package


def test_all_schema_contracts_and_source_instances_validate(package_root: Path) -> None:
    """Verify every shipped schema and source-owned instance passes the schema gate."""
    result = validate_schema_contracts(package_root)
    assert result["status"] == "PASS", result
    assert result["schema_count"] == 35
    assert result["schema_ids"] == 35
    assert result["owner_count"] == 35


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
