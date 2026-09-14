"""Canonical analysis Skill bindings and shared evidence routing."""

from pathlib import Path
import json
import shutil

import pytest

from sage.act_tasks import _skill_files, load_skill_registry
from sage.errors import ConfigurationError


def test_legacy_analysis_operations_use_migrated_skills(package_root: Path) -> None:
    """Old operation identities resolve to the owning current Skill contract."""
    registry = load_skill_registry(package_root)
    assert registry[("saw", "rtc")] is registry[("rtc", "rtc")]
    assert registry[("saw", "stc")] is registry[("stc", "stc")]
    assert registry[("saw", "focused")].skill_id == "rtc-focused-check"
    assert registry[("saw", "ol")].skill_id == "rtc-original-language-review"
    assert not any(binding.skill_id.startswith("saw-") for binding in registry.values())


def test_analysis_skills_route_global_evidence_contracts(package_root: Path) -> None:
    """Shared rules are actually routed, while archived source prompts stay excluded."""
    registry = load_skill_registry(package_root)
    for key in (("rtc", "rtc"), ("stc", "stc"), ("saw", "focused"), ("saw", "ol")):
        files = _skill_files(registry[key])
        shared = package_root / "system/skills/global/references"
        assert shared / "LOCAL-EVIDENCE-AND-LINGUISTIC-COMPETENCE.md" in files
        assert shared / "SEMANTIC-INDEX-AND-LOCAL-FIRST.md" in files
        assert len(files) == len(set(files))
        assert not any(path.name.startswith(("ORIGINAL-", "LEGACY-")) for path in files)


@pytest.mark.parametrize("damage", ["changed", "missing", "escape", "duplicate"])
def test_shared_contracts_fail_closed(package_root: Path, tmp_path: Path, damage: str) -> None:
    """A shared rule cannot disappear, change, escape, or be routed twice silently."""
    root = tmp_path / "app"
    shutil.copytree(package_root / "system/skills", root / "system/skills")
    (root / "system/config").mkdir()
    registry_path = root / "system/config/skills.json"
    registry = json.loads((package_root / "system/config/skills.json").read_text())
    refs = registry["skills"]["rtc"]["shared_references"]
    path = root / refs[0]["file"]
    if damage == "changed":
        path.write_text("Trust recalled Scripture as evidence.\n")
    elif damage == "missing":
        path.unlink()
    elif damage == "escape":
        refs[0]["file"] = "../outside.md"
    else:
        refs.append(dict(refs[0]))
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(ConfigurationError, match="shared reference"):
        load_skill_registry(root)
