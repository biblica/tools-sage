"""Independent RTC/STC Job persistence and serial Run identity contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from sage.errors import ValidationError
from sage.act_tasks import create_act_task
from sage.jobs import JobStore
from sage.registry import load_ecosystem

IMPORT_TIME = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def _initialize(package_root: Path, root: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system/src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(root / "ecosystem.yml"),
            "workspace",
            "initialize",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_rtc_and_stc_use_independent_bindings(make_workspace) -> None:
    """RTC owns WIP+REFERENCE while STC owns WIP only."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")

    rtc = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="RTC fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=IMPORT_TIME,
    )
    stc = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC fixture",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )

    assert rtc.bindings == {"wip": "usWIP", "reference": "usNIVv2"}
    assert stc.bindings == {"wip": "usWIP"}
    assert rtc.wip_snapshot is not None
    assert stc.wip_snapshot is not None
    assert rtc.wip_snapshot["snapshot_date"] == "20260901"
    assert stc.wip_snapshot["snapshot_date"] == "20260901"
    assert rtc.runtime_tool == "saw"
    assert stc.runtime_tool == "saw"
    assert stc.contemporary_source is None

    stc_profile = yaml.safe_load(stc.runtime_profile_path.read_text(encoding="utf-8"))
    assert stc_profile["bindings"] == {
        "WIP": "usWIP",
        "ORIGINAL_LANGUAGE_GREEK": "GRK",
        "ORIGINAL_LANGUAGE_HEBREW": "HEB",
    }


def test_rtc_rejects_self_comparison_and_stc_rejects_reference(make_workspace) -> None:
    """The workflow-specific role model is enforced before Job data persists."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")

    with pytest.raises(ValidationError, match="different"):
        store.create_job(
            tool="rtc",
            job_id="RTC-usWIP_20260901",
            display_name="bad",
            bindings={"wip": "usWIP", "reference": "usWIP"},
            imported_at=IMPORT_TIME,
        )
    with pytest.raises(ValidationError, match="unsupported bindings"):
        store.create_job(
            tool="stc",
            job_id="STC-usWIP_20260901",
            display_name="bad",
            bindings={"wip": "usWIP", "reference": "usNIVv2"},
            imported_at=IMPORT_TIME,
        )


def test_run_identity_uses_snapshot_job_and_serial_only(make_workspace) -> None:
    """Repeated analysis of one imported snapshot increments only the Run serial."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC fixture",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )

    first = store.create_run(job, operation="stc", scope="MAT 1")
    second = store.create_run(job, operation="stc", scope="MAT 2")

    assert first.run_id == "STC-usWIP_20260901-001"
    assert second.run_id == "STC-usWIP_20260901-002"
    assert (first.root / "snapshot" / "SNAPSHOT.json").is_file()
    sealed_before = (first.root / "snapshot" / "SNAPSHOT.json").read_bytes()
    current = job.root / "snapshot" / "SNAPSHOT.json"
    assert job.wip_snapshot is not None
    current.write_text(
        current.read_text(encoding="utf-8").replace(
            job.wip_snapshot["content_fingerprint"],
            "f" * 64,
        ),
        encoding="utf-8",
    )
    assert (first.root / "snapshot" / "SNAPSHOT.json").read_bytes() == sealed_before

    with pytest.raises(ValidationError, match="only STC Runs"):
        store.create_run(job, operation="rtc", scope="MAT 3")


def test_same_day_refresh_replaces_job_snapshot_but_not_sealed_run(make_workspace) -> None:
    """Mutable imported WIP data may refresh while completed Run evidence stays immutable."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="RTC refresh fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=IMPORT_TIME,
    )
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    completed = store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
    sealed_before = (completed.root / "snapshot" / "SNAPSHOT.json").read_bytes()

    assert job.wip_snapshot is not None
    source = next(Path(job.wip_snapshot["source_location"]).glob("*.SFM"))
    source.write_text(
        source.read_text(encoding="utf-8").replace("Verse 1.", "Reimported verse 1."),
        encoding="utf-8",
    )
    refreshed = store.refresh_job_snapshot(
        job,
        imported_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
    )

    assert refreshed.job_id == job.job_id
    assert refreshed.configuration_revision == 2
    assert refreshed.wip_snapshot is not None
    assert (
        refreshed.wip_snapshot["content_fingerprint"]
        != job.wip_snapshot["content_fingerprint"]
    )
    assert (completed.root / "snapshot" / "SNAPSHOT.json").read_bytes() == sealed_before


def test_new_snapshot_date_creates_new_job_and_archives_old_container(make_workspace) -> None:
    """A new WIP import date changes Job identity without retaining mutable old Job evidence."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC refresh fixture",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    store.set_active_job("stc", job.job_id)

    refreshed = store.refresh_job_snapshot(
        job,
        imported_at=datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc),
    )

    assert refreshed.job_id == "STC-usWIP_20260902"
    assert refreshed.configuration_revision == 2
    assert refreshed.status == "ACTIVE"
    assert store.active_jobs()["stc"] == refreshed.job_id
    archived = store.load_job(job.job_id, tool="stc")
    assert archived.status == "ARCHIVED"
    assert not (archived.root / "snapshot").exists()


def test_snapshot_refresh_refuses_nonclosed_run(make_workspace) -> None:
    """The Job snapshot cannot move underneath a Run that is still in progress."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC active Run fixture",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    store.create_run(job, operation="stc", scope="MAT 1")

    with pytest.raises(ValidationError, match="non-closed Run"):
        store.refresh_job_snapshot(
            job,
            imported_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        )


def test_primary_stc_task_uses_its_job_without_any_reference(
    package_root: Path,
    make_workspace,
) -> None:
    """The internal SAW adapter resolves an STC Job and routes only WIP + GRK."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    shutil.copy2(
        package_root
        / "system/resources/scripture/original-language/grk/authority-profile.yml",
        root.parent
        / "localdata/work/projects/GRK/authority-profile.yml",
    )
    _initialize(package_root, root)
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC without Reference",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    run = store.create_run(job, operation="stc", scope="MAT 1:1")
    runtime = load_ecosystem(store.ensure_runtime_files(job))

    task = create_act_task(
        runtime,
        workflow="saw",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:1",
        auto_partition=False,
        job_id=job.job_id,
        run_id=run.run_id,
    )

    manifest = json.loads(Path(task["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["contemporary_source"] is None
    assert manifest["resource_bindings"] == {
        "WIP": "usWIP",
        "ORIGINAL_LANGUAGE_GREEK": "GRK",
    }
