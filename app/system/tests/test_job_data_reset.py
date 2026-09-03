"""Bounded Job-data wipe contracts."""

from __future__ import annotations

import json
import io
from pathlib import Path

from sage.job_data_reset import wipe_all_job_data
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.project_inventory import project_inventory_path
from sage.storage import storage_layout


def test_job_wipe_preserves_environment_projects_and_resources(make_workspace) -> None:
    """Job-data wipe removes analysis artifacts but retains runtime and resource authority."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    layout = storage_layout(root, create=True)
    keep = layout.venv_root / "keep.txt"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("managed", encoding="utf-8")
    registry = project_inventory_path(root)
    registry.write_text(
        '{"schema_version":"1.0","projects":{"fixture":{"project_id":"fixture"}}}\n',
        encoding="utf-8",
    )
    before = registry.read_bytes()
    resource_mapping = layout.state_root / "resource-mounts.json"
    resource_mapping.write_text('{"schema_version":"1.0"}\n', encoding="utf-8")
    mapping_before = resource_mapping.read_bytes()
    (layout.jobs_root / "rtc" / "RTC-fixture_20260901").mkdir(parents=True)
    (layout.reports_root / "RTC-fixture_20260901").mkdir(parents=True)
    (layout.exports_root / "fixture.zip").write_text("export", encoding="utf-8")
    (layout.system_root / "jobs" / "rtc").mkdir(parents=True)
    (layout.workflow_root / "saw" / "state").mkdir(parents=True)
    (layout.state_root / "active-jobs.json").write_text("{}\n", encoding="utf-8")

    result = wipe_all_job_data(root)

    assert result["status"] == "JOB_DATA_WIPED"
    assert keep.read_text(encoding="utf-8") == "managed"
    assert registry.read_bytes() == before
    assert resource_mapping.read_bytes() == mapping_before
    assert not any(layout.jobs_root.iterdir())
    assert not any(layout.reports_root.iterdir())
    assert not any(layout.exports_root.iterdir())
    assert not (layout.state_root / "active-jobs.json").exists()
    receipt = Path(result["receipt_path"])
    assert receipt.is_file()
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "JOB_DATA_WIPED"


def test_job_wipe_does_not_follow_symlinked_job_target(make_workspace, tmp_path) -> None:
    """A symlink in the Job tree is unlinked without deleting its external target."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    layout = storage_layout(root, create=True)
    outside = tmp_path / "outside-job-data"
    outside.mkdir()
    protected = outside / "keep.txt"
    protected.write_text("outside", encoding="utf-8")
    link = layout.jobs_root / "rtc"
    link.symlink_to(outside, target_is_directory=True)

    wipe_all_job_data(root)

    assert protected.read_text(encoding="utf-8") == "outside"
    assert not link.exists()


def test_maintenance_routes_job_wipe_through_system_actions(make_workspace) -> None:
    """Maintenance keeps bounded Job cleanup inside the System actions submenu."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.system_configuration_menu()
    rendered = output.getvalue()
    assert "Resource Status Report" in rendered
    assert "6. System actions" in rendered
    assert "Wipe all JOB data" not in rendered


def test_system_actions_exposes_bounded_job_wipe(make_workspace) -> None:
    """System actions places Job-data wipe before the stronger out-of-box reset."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.system_actions_menu()
    rendered = output.getvalue()
    assert "║ System actions" in rendered
    assert "4. Wipe all JOB data" in rendered
    assert "5. Reset SAGE to out-of-box state" in rendered
    assert rendered.index("Wipe all JOB data") < rendered.index("Reset SAGE to out-of-box state")


def test_menu_job_wipe_requires_exact_confirmation(make_workspace) -> None:
    """The destructive maintenance action accepts only its exact confirmation phrase."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    layout = storage_layout(root, create=True)
    job_data = layout.jobs_root / "rtc" / "RTC-fixture_20260901"
    job_data.mkdir(parents=True)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["y", "WIPE JOB DATA"]),
            output=output,
        ),
        skip_setup=True,
        dry_run_provider=True,
    )

    center._wipe_all_job_data_menu()

    assert not job_data.exists()
    assert "JOB DATA WIPED" in output.getvalue()
