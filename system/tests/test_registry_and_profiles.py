"""Project registry, workflow isolation, and permission tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sage.errors import ConfigurationError
from sage.profiles import load_workflow_profile
from sage.registry import load_ecosystem
from sage.standard import load_standard
from sage.validation import validate_static_ecosystem


def test_default_package_static_validation_passes(package_root: Path) -> None:
    """Verify that default package static validation passes."""
    config = load_ecosystem(package_root / "ecosystem.yml")
    result = validate_static_ecosystem(config, load_standard(package_root))
    assert result["status"] == "READY"
    assert result["errors"] == []


def test_projects_resolve_relative_to_projects_root(make_workspace) -> None:
    """Verify that projects resolve relative to projects root."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    assert config.project("idKKHv0").path == (root.parent / "SAGEdata" / "projects" / "idKKHv0").resolve()


def test_project_absolute_path_is_rejected(make_workspace) -> None:
    """Verify that project absolute path is rejected."""
    root = make_workspace()
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["projects"]["idKKHv0"]["path"] = str((root.parent / "SAGEdata" / "projects" / "idKKHv0").resolve())
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="must be relative"):
        load_ecosystem(path)


def test_workflow_roots_must_not_collide(make_workspace) -> None:
    """Verify that workflow roots must not collide."""
    root = make_workspace()
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["workflows"]["saw"]["state_root"] = data["workflows"]["bic"]["state_root"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(path)
    result = validate_static_ecosystem(config, load_standard(root))
    assert result["status"] == "BLOCKED"
    assert any("collides" in item for item in result["errors"])


def test_saw_cannot_receive_project_write_permission(make_workspace) -> None:
    """Verify that SAW cannot receive project write permission."""
    root = make_workspace()
    path = root / "system" / "config" / "workflows" / "saw" / "profile.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["permissions"]["may_write_projects"] = ["usBOLx1"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    result = validate_static_ecosystem(config, load_standard(root))
    assert result["status"] == "BLOCKED"
    assert any("SAW must not" in item for item in result["errors"])


def test_bic_can_write_only_bic_generated_project(make_workspace) -> None:
    """Verify that BIC can write only BIC generated project."""
    root = make_workspace()
    path = root / "system" / "config" / "workflows" / "bic" / "profile.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["permissions"]["may_write_projects"] = ["idKKHv0"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(ConfigurationError, match="producer"):
        load_workflow_profile(config, config.workflow("bic"))


def test_configured_workspace_rejects_disabled_required_binding(make_workspace) -> None:
    """Verify that configured workspace rejects disabled required binding."""
    root = make_workspace()
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["projects"]["GRK"]["enabled"] = False
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(path)
    result = validate_static_ecosystem(config, load_standard(root))
    assert result["status"] == "BLOCKED"
    assert any("required bindings are disabled" in item for item in result["errors"])


def test_missing_required_core_profile_binding_is_rejected(make_workspace) -> None:
    """Verify that a missing core authority binding is rejected while OL remains optional."""
    root = make_workspace()
    path = root / "system" / "config" / "workflows" / "saw" / "profile.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["bindings"]["REFERENCE"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(ConfigurationError, match="missing required bindings"):
        load_workflow_profile(config, config.workflow("saw"))


def test_invalid_structure_policy_blocks_static_validation(make_workspace) -> None:
    """Verify that invalid structure policy blocks static validation."""
    root = make_workspace()
    policy_path = root / "system" / "config" / "structure-planning.yml"
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    data["split_markers"]["section"]["s1"] = "strong"
    policy_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    result = validate_static_ecosystem(config, load_standard(root))
    assert result["status"] == "BLOCKED"
    assert any("Structure-planning policy" in item for item in result["errors"])
