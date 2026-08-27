"""Governed active-installation out-of-box reset contracts."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sage.hashing import sha256_file
from sage.operator_overrides import write_local_settings
from sage.out_of_box_reset import reset_to_out_of_box
from sage.registry import load_ecosystem
from sage.storage import storage_layout


def test_out_of_box_reset_removes_local_data_and_preserves_core(make_workspace) -> None:
    """Reset localdata while preserving the managed runtime and byte-identical Core."""
    root = make_workspace(configured=False, qualification_status="VALIDATED")
    settings = root / "ecosystem.yml"
    raw = yaml.safe_load(settings.read_text(encoding="utf-8"))
    raw["projects"] = {}
    settings.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    core_hash = sha256_file(settings)

    # Simulate completed local setup without changing Core.
    write_local_settings(settings, {"ecosystem": {"configured": True}})
    assert load_ecosystem(settings).configured is True

    layout = storage_layout(root, create=True)
    managed_runtime = layout.venv_root / "preserved.txt"
    managed_runtime.parent.mkdir(parents=True, exist_ok=True)
    managed_runtime.write_text("keep", encoding="utf-8")

    for tool, job_id in (("bic", "BIC_fixture"), ("saw", "SAW_fixture")):
        job = layout.jobs_root / tool / job_id
        job.mkdir(parents=True, exist_ok=True)
        (job / "job.yml").write_text("schema_version: '1.0'\n", encoding="utf-8")
    report = layout.reports_root / "local-report.md"
    report.write_text("generated", encoding="utf-8")
    local_resource = layout.resources_root / "grammar-profiles" / "pes-IR" / "wip.yml"
    local_resource.parent.mkdir(parents=True, exist_ok=True)
    local_resource.write_text("profile: {language: pes-IR}\n", encoding="utf-8")

    result = reset_to_out_of_box(root)

    assert result["status"] == "OUT_OF_BOX_RESET"
    assert managed_runtime.read_text(encoding="utf-8") == "keep"
    assert not report.exists()
    assert not local_resource.exists()
    assert not list((layout.jobs_root / "bic").glob("BIC_*"))
    assert not list((layout.jobs_root / "saw").glob("SAW_*"))
    assert sha256_file(settings) == core_hash
    config = load_ecosystem(settings)
    assert config.configured is False
    assert config.projects == {}
    receipt = Path(result["receipt_path"])
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["next_action"] == "Relaunch SAGE to begin first-use Setup."
    assert "localdata/.system/runtime/venv" in payload["preserved"]
