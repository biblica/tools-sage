"""STC operation registration and operator-surface regressions."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sage import act_tasks, cli, stage_reset
from sage.menu import SageControlCenter

ROOT = Path(__file__).resolve().parents[1]


def test_stc_is_registered_as_fourth_saw_operation() -> None:
    """Every governed runtime operation vocabulary includes STC after RTC."""
    assert "stc" in act_tasks.ACT_OPERATIONS["saw"]
    assert "stc" in cli.SHORTCUT_COMMANDS["saw"]
    assert "stc" in stage_reset.STAGES["saw"]
    assert SageControlCenter._saw_operation_label("stc") == "Source Text Correspondence (STC)"


def test_saw_workflow_profile_declares_stc_evidence_policy() -> None:
    """STC has a dedicated general-slicer profile rather than borrowing RTC policy."""
    profile = yaml.safe_load((ROOT / "config/workflows/saw/profile.yml").read_text(encoding="utf-8"))
    assert "stc" in profile["evidence_policies"]


def test_stc_governed_skill_is_registered_and_hashed() -> None:
    """Release skill registry includes a dedicated STC analytical contract."""
    registry = json.loads((ROOT / "config/skills.json").read_text(encoding="utf-8"))
    item = registry["skills"]["saw-stc"]
    assert item["workflow"] == "saw"
    assert item["operation"] == "stc"
    assert (ROOT.parent / item["file"]).is_file()
    assert (ROOT.parent / item["original_file"]).is_file()
