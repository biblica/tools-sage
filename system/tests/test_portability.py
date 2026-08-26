"""New-host Project subfolder rebinding contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.errors import ValidationError
from sage.portability import rebind_new_host_projects
from sage.resource_mounts import load_resource_mount_state


def _write_mapping(path: Path, value: dict[str, object]) -> None:
    """Write one compact portable YAML fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _paratext_project(path: Path, *, iso: str) -> None:
    """Create one minimally discoverable Paratext Project subfolder."""
    path.mkdir(parents=True)
    (path / "settings.xml").write_text(
        f"<Settings><Language>Test</Language><FullName>{path.name}</FullName>"
        f"<LanguageIsoCode>{iso}</LanguageIsoCode></Settings>\n",
        encoding="utf-8",
    )
    (path / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 Test.\n", encoding="utf-8")


def _portable_job(root: Path) -> Path:
    """Create one preserved Job with enough runtime evidence for rebinding."""
    job = storage_layout(root, create=True).jobs_root / "saw" / "SAW_faTMNv4-usNIVv2"
    _write_mapping(
        job / "job.yml",
        {
            "schema_version": "1.0",
            "job_id": "SAW_faTMNv4-usNIVv2",
            "tool": "saw",
            "bindings": {"wip": "faTMNv4", "reference": "usNIVv2"},
        },
    )
    projects = {
        "faTMNv4": {
            "project_id": "faTMNv4",
            "path": "faTMNv4",
            "enabled": True,
            "language": {"code": "pes", "profile": "pes", "variant": "wip"},
            "external_path": "/old-host/Paratext Projects/faTMNv4",
            "external_access_mode": "READ_ONLY_SCRIPTURE",
        },
        "usNIVv2": {
            "project_id": "usNIVv2",
            "path": "usNIVv2",
            "enabled": True,
            "language": {"code": "en", "profile": "en"},
            "external_path": "/old-host/Paratext Projects/usNIVv2",
            "external_access_mode": "READ_ONLY_SCRIPTURE",
        },
    }
    _write_mapping(storage_layout(root).system_root / "jobs" / "saw" / job.name / "runtime.yml", {"projects": projects})
    report = (
        storage_layout(root).reports_root
        / "SAW_faTMNv4-usNIVv2"
        / "GEN"
        / "GEN_001_ACTION-REPORT.md"
    )
    report.parent.mkdir(parents=True)
    report.write_text("portable report\n", encoding="utf-8")
    return job


def test_new_host_rebinds_same_project_subfolders_and_preserves_report(tmp_path: Path) -> None:
    """Replace only the host parent path when Paratext child names remain stable."""
    sage = tmp_path / "SAGE"
    job = _portable_job(sage)
    projects = tmp_path / "New Host" / "Paratext Projects"
    _paratext_project(projects / "faTMNv4", iso="pes")
    _paratext_project(projects / "usNIVv2", iso="eng")

    result = rebind_new_host_projects(sage, projects)

    assert result["rebound_projects"] == 2
    mounts = load_resource_mount_state(sage)
    assert mounts["projects_root"] == str(projects.resolve())
    assert mounts["mounts"]["faTMNv4"]["project_folder"] == "faTMNv4"
    assert mounts["mounts"]["usNIVv2"]["project_folder"] == "usNIVv2"
    inventory = json.loads((storage_layout(sage).state_root / "project-inventory.json").read_text(encoding="utf-8"))
    assert set(inventory["projects"]) == {"faTMNv4", "usNIVv2"}
    assert not (storage_layout(sage).system_root / "jobs" / "saw" / job.name / "runtime.yml").exists()
    assert (
        storage_layout(sage).reports_root
        / "SAW_faTMNv4-usNIVv2"
        / "GEN"
        / "GEN_001_ACTION-REPORT.md"
    ).is_file()


def test_new_host_blocks_before_state_change_when_subfolder_is_missing(tmp_path: Path) -> None:
    """Require the Operator to resolve a missing Project folder without silent remapping."""
    sage = tmp_path / "SAGE"
    _portable_job(sage)
    projects = tmp_path / "Paratext Projects"
    _paratext_project(projects / "faTMNv4", iso="pes")

    with pytest.raises(ValidationError) as caught:
        rebind_new_host_projects(sage, projects)

    assert caught.value.code == "NEW_HOST_PROJECT_SUBFOLDER_MISMATCH"
    assert "usNIVv2" in str(caught.value)
    assert not (storage_layout(sage).state_root / "project-inventory.json").exists()
    assert not (storage_layout(sage).state_root / "resource-mounts.json").exists()
