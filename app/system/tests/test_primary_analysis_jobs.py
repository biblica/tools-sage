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
from sage.plan_continuation import continue_saw_plan
from sage.registry import load_ecosystem
from sage.storage import storage_layout
import sage.workflow_identity as workflow_identity

IMPORT_TIME = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def _initialize(package_root: Path, root: Path) -> None:
    """Initialize a fixture workspace through the public CLI boundary."""
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
    assert rtc.runtime_tool == "rtc"
    assert stc.runtime_tool == "stc"
    assert stc.contemporary_source is None

    stc_profile = yaml.safe_load(stc.runtime_profile_path.read_text(encoding="utf-8"))
    assert stc_profile["bindings"] == {
        "WIP": "usWIP",
        "ORIGINAL_LANGUAGE_GREEK": "GRK",
        "ORIGINAL_LANGUAGE_HEBREW": "HEB",
    }


def test_canonical_analysis_identity_normalizes_only_explicit_legacy_operations() -> None:
    """New RTC/STC work stays canonical while a stored legacy workflow remains readable."""
    assert workflow_identity.runtime_workflow_id("rtc") == "rtc"
    assert workflow_identity.runtime_workflow_id("stc") == "stc"
    canonicalize = getattr(workflow_identity, "canonical_analysis_workflow")
    assert canonicalize("rtc") == "rtc"
    assert canonicalize("stc") == "stc"
    assert canonicalize("saw", "rtc") == "rtc"
    assert canonicalize("saw", "stc") == "stc"
    assert workflow_identity.is_analysis_workflow("rtc") is True
    assert workflow_identity.is_analysis_workflow("stc") is True
    assert workflow_identity.is_analysis_workflow("saw") is True
    assert workflow_identity.is_analysis_workflow("bic") is False
    with pytest.raises(ValidationError, match="legacy analysis workflow"):
        canonicalize("saw")


def test_analysis_labels_and_new_reason_codes_are_operation_specific() -> None:
    """Shared analysis failures must not leak the retired identity to current work."""
    operation_label = getattr(workflow_identity, "analysis_operation_label")
    reason_code = getattr(workflow_identity, "analysis_reason_code")

    assert operation_label("rtc") == "Reference Text Comparison (RTC)"
    assert operation_label("stc") == "Source Text Correspondence (STC)"
    assert operation_label("focused") == "Targeted Check"
    assert operation_label("ol") == "Original-Language Review"
    assert reason_code("SAW_RTC_ROUTE_LIMIT_EXCEEDED", "rtc") == "RTC_ROUTE_LIMIT_EXCEEDED"
    assert reason_code("SAW_TASK_RESULT_INVALID", "stc") == "STC_TASK_RESULT_INVALID"


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


@pytest.mark.parametrize(
    ("tool", "job_id", "bindings", "replacement"),
    (
        (
            "rtc",
            "RTC-usWIP_20260901",
            {"wip": "usWIP", "reference": "usNIVv2"},
            {"wip": "usWIP", "reference": "usNIRVv2"},
        ),
        (
            "stc",
            "STC-usWIP_20260901",
            {"wip": "usWIP"},
            {"wip": "usNIRVv2"},
        ),
    ),
)
def test_analysis_job_project_bindings_are_immutable(
    make_workspace,
    tool,
    job_id,
    bindings,
    replacement,
) -> None:
    """Changing an RTC/STC Project binding requires creating a different Job."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool=tool,
        job_id=job_id,
        display_name="Immutable binding fixture",
        bindings=bindings,
        imported_at=IMPORT_TIME,
    )

    with pytest.raises(ValidationError) as caught:
        store.revise_job(job, bindings=replacement)

    assert caught.value.code == "JOB_BINDINGS_IMMUTABLE"
    assert "new Job" in caught.value.next_action
    assert store.load_job(job.job_id, tool=tool).bindings == bindings


@pytest.mark.parametrize("remove_reports", (False, True))
def test_delete_analysis_job_removes_all_owned_work_and_optionally_reports(
    make_workspace,
    remove_reports,
) -> None:
    """Delete Job removes runtime work and pointers while preserving external Projects."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="Disposable RTC fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=IMPORT_TIME,
    )
    store.set_active_job("rtc", job.job_id)
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    compiled_usj = run.root / "tasks" / "MAT-001" / "compiled" / "WIP.usj.json"
    compiled_usj.parent.mkdir(parents=True)
    compiled_usj.write_text('{}\n', encoding="utf-8")
    controller_cache = job.controller_root / "cache" / "compiled.json"
    controller_cache.write_text('{}\n', encoding="utf-8")
    report_root = storage_layout(root).reports_root / job.job_id
    published_report = report_root / "MAT" / "001" / "RTC_ACTION-REPORT.md"
    published_report.parent.mkdir(parents=True)
    published_report.write_text("# Published report\n", encoding="utf-8")
    project_paths = (
        storage_layout(root).projects_root / "usWIP",
        storage_layout(root).projects_root / "usNIVv2",
    )

    store.remove_job(job, remove_reports=remove_reports)

    assert not job.root.exists()
    assert not job.controller_root.exists()
    assert not compiled_usj.exists()
    assert not controller_cache.exists()
    assert store.active_jobs()["rtc"] is None
    assert not store.last_run_path.exists()
    assert report_root.exists() is (not remove_reports)
    assert all(path.is_dir() for path in project_paths)


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
    """A canonical STC task resolves its Job and routes only WIP + GRK."""
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
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1:1",
        auto_partition=False,
        job_id=job.job_id,
        run_id=run.run_id,
    )

    manifest = json.loads(Path(task["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["workflow"] == "stc"
    assert manifest["task_id"].startswith("stc-")
    assert manifest["skill"]["entrypoint"] == "system/skills/stc/SKILL.md"
    assert "SAW" not in Path(task["act_path"]).read_text(encoding="utf-8")
    assert "SAW" not in json.dumps(manifest, sort_keys=True)
    assert manifest["contemporary_source"] is None
    assert manifest["resource_bindings"] == {
        "WIP": "usWIP",
        "ORIGINAL_LANGUAGE_GREEK": "GRK",
    }


def test_primary_rtc_task_and_composite_plan_keep_canonical_identity(
    package_root: Path,
    make_workspace,
) -> None:
    """A new RTC Run must not serialize the retired workflow identity."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _initialize(package_root, root)
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="Canonical RTC fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=IMPORT_TIME,
    )
    run = store.create_run(job, operation="rtc", scope="MAT 1:1")

    result = create_act_task(
        load_ecosystem(store.ensure_runtime_files(job)),
        workflow="rtc",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value=run.scope,
        auto_partition=False,
        job_id=job.job_id,
        run_id=run.run_id,
    )

    assert result["workflow"] == "rtc"
    assert result["plan_type"] == "RTC_COMPOSITE"
    assert result["plan_id"].startswith("RTC-")
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["workflow"] == "rtc"
    assert manifest["task_id"].startswith("rtc-")
    assert manifest["skill"]["entrypoint"] == "system/skills/rtc/SKILL.md"
    assert "SAW" not in Path(result["act_path"]).read_text(encoding="utf-8")
    assert "SAW" not in json.dumps(manifest, sort_keys=True)
    continuation = continue_saw_plan(
        load_ecosystem(store.ensure_runtime_files(job)),
        Path(result["plan_path"]),
    )
    assert continuation["status"] == "NEXT_WORK_UNIT"
    assert continuation["composite_stage"] == result["current_stage"]


def test_discontinuous_stc_run_partitions_each_selected_portion(
    package_root: Path,
    make_workspace,
) -> None:
    """STC keeps separated same-book chapters as independent governed tasks."""
    root = make_workspace(configured=True, qualification_status="VALIDATED", verse_max=1)
    scripture = (
        "\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 Chapter one.\n"
        "\\c 3\n\\p\n\\v 1 Chapter three.\n"
    )
    for project in storage_layout(root).projects_root.iterdir():
        path = project / "41MAT.SFM"
        if path.is_file():
            path.write_text(scripture, encoding="utf-8")
    for name in ("eng.vrs", "org.vrs"):
        (root / "system" / "resources" / "scripture" / name).write_text(
            "MAT 1:1 3:1\n",
            encoding="utf-8",
        )
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
        display_name="STC discontinuous scope",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    run = store.create_run(job, operation="stc", scope="MAT 1; MAT 3")

    result = create_act_task(
        load_ecosystem(store.ensure_runtime_files(job)),
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value=run.scope,
        job_id=job.job_id,
        run_id=run.run_id,
    )

    assert result["status"] == "PARTITIONED"
    assert result["requested_scope"] == "MAT 1; MAT 3"
    assert [unit["scope"] for unit in result["work_units"]] == ["MAT 1:1", "MAT 3:1"]
