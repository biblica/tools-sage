"""Project-import date persistence and operator-surface contracts."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import io
import json

import pytest

from sage.errors import ValidationError
from sage.cli import command_overview
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.jobs import JobStore
from sage.project_inventory import (
    load_project_registry,
    project_import_date,
    project_imported_at,
    register_project,
    registered_project_records,
    update_project_record,
    write_project_registry,
)
from sage.storage import storage_layout
from sage.registry import load_ecosystem
from sage.ui_format import display_width
from sage.ui_services import OperatorUIService


IMPORT_TIME = datetime(2026, 8, 29, 14, 35, tzinfo=timezone.utc)


def _register_fixture_project(root, project_id: str, *, imported_at: datetime = IMPORT_TIME):
    """Register one real fixture Scripture directory at a controlled import time."""
    register_project(
        root,
        project_id=project_id,
        project_path=storage_layout(root).projects_root / project_id,
        language_code="en",
        base_vrs_file="eng.vrs",
        display_name=f"{project_id} fixture",
        imported_at=imported_at,
    )
    return update_project_record(root, project_id, {"enabled": True})


def test_project_registration_persists_full_utc_and_stable_import_date(make_workspace) -> None:
    """Catch registrations that lose the auditable timestamp or operator-facing date."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")

    created = _register_fixture_project(root, "usWIP")
    persisted = registered_project_records(root)["usWIP"]

    assert created["imported_utc"] == "2026-08-29T14:35:00+00:00"
    assert created["imported_date"] == "20260829"
    assert persisted["imported_utc"] == "2026-08-29T14:35:00+00:00"
    assert persisted["imported_date"] == "20260829"


@pytest.mark.parametrize(
    "record",
    (
        {
            "imported_utc": "2026-02-28T10:00:00+00:00",
            "imported_date": "20260231",
        },
        {
            "imported_utc": "2026-08-30T00:30:00+00:00",
            "imported_date": "20260829",
        },
        {
            "imported_utc": "2026-08-29T14:35:00+02:00",
            "imported_date": "20260829",
        },
    ),
)
def test_corrupt_project_import_metadata_is_unknown(record) -> None:
    """Catch malformed or non-UTC metadata being presented as trusted provenance."""
    assert project_import_date(record) is None
    assert project_imported_at(record) is None


def test_project_import_metadata_cannot_be_rewritten_by_project_refresh(make_workspace) -> None:
    """Catch metadata refreshes that silently replace the original SAGE import date."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")

    updated = update_project_record(root, "usWIP", {"display_name": "Refreshed name"})

    assert updated["imported_utc"] == "2026-08-29T14:35:00+00:00"
    assert updated["imported_date"] == "20260829"
    with pytest.raises(ValidationError) as exc_info:
        update_project_record(root, "usWIP", {"imported_date": "20260901"})
    assert exc_info.value.code == "PROJECT_IMPORT_DATE_IMMUTABLE"


def test_project_inventory_reports_the_original_sage_import_date(make_workspace) -> None:
    """Catch Project views that hide the persisted import date from the operator."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.registered_projects_menu()
    center.registered_project_detail("usWIP")

    rendered = output.getvalue()
    assert "Imported" in rendered
    assert "Imported to SAGE: 20260829" in rendered
    assert "\n  1. usWIP\n\n  2. Add another PROJECT to SAGE" in rendered


def test_registered_project_summary_keeps_fields_associated_at_72_columns(
    make_workspace,
) -> None:
    """Catch project-table columns wrapping into detached, unlabelled lines."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    update_project_record(
        root,
        "usWIP",
        {"display_name": "New Ukrainian Translation with a deliberately long Project name"},
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["a"]),
            output=output,
            viewport_columns=72,
        ),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.registered_projects_menu()

    lines = output.getvalue().splitlines()
    assert max(display_width(line) for line in lines) <= 72
    assert "  1. usWIP" in lines
    assert "     Name            New Ukrainian Translation with a deliberately long" in lines
    assert "                     Project name" in lines
    assert "     Date imported   20260829" in lines
    assert any(line.startswith("     Status          ") for line in lines)
    assert not any(line == "Imported  Status" for line in lines)


def test_rtc_job_setup_uses_and_reports_each_project_import_date(
    make_workspace,
    monkeypatch,
) -> None:
    """Catch RTC setup deriving snapshot identity from Job creation time or hiding resource dates."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    _register_fixture_project(
        root,
        "usNIVv2",
        imported_at=datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc),
    )
    config = load_ecosystem(root / "ecosystem.yml")
    selected = iter((config.project("usWIP"), config.project("usNIVv2")))
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", ""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    monkeypatch.setattr(
        center,
        "choose_or_add_resource",
        lambda *_args, **_kwargs: next(selected),
    )

    created = center.create_job_wizard("rtc")

    assert created is not None, output.getvalue()
    assert created.job_id == "RTC-usWIP_20260829"
    assert created.wip_snapshot is not None
    assert created.wip_snapshot["snapshot_date"] == "20260829"
    rendered = output.getvalue()
    assert (
        "WIP Project         usWIP\n"
        "Date imported       20260829\n"
        "REFERENCE Project   usNIVv2\n"
        "Date imported       20260830"
    ) in rendered
    assert "WIP imported to SAGE" not in rendered


def test_analysis_job_identity_uses_utc_import_date_across_day_boundary(
    make_workspace,
    monkeypatch,
) -> None:
    """Catch host-local timezone conversion changing the persisted UTC import date."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(
        root,
        "usWIP",
        imported_at=datetime(
            2026,
            8,
            30,
            0,
            30,
            tzinfo=timezone(timedelta(hours=2)),
        ),
    )
    project = load_ecosystem(root / "ecosystem.yml").project("usWIP")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", ""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    monkeypatch.setattr(
        center,
        "choose_or_add_resource",
        lambda *_args, **_kwargs: project,
    )

    created = center.create_job_wizard("stc")

    assert created is not None, output.getvalue()
    assert created.job_id == "STC-usWIP_20260829"
    assert created.wip_snapshot is not None
    assert created.wip_snapshot["snapshot_date"] == "20260829"
    assert "WIP Project         usWIP\nDate imported       20260829" in output.getvalue()


def test_job_store_uses_registered_wip_import_date_when_caller_omits_it(
    make_workspace,
) -> None:
    """Catch non-menu RTC/STC callers defaulting snapshot provenance to creation time."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")

    created = JobStore(root, root / "ecosystem.yml").create_job(
        tool="stc",
        job_id="STC-usWIP_20260829",
        display_name="Stored import provenance",
        bindings={"wip": "usWIP"},
    )

    assert created.wip_snapshot is not None
    assert created.wip_snapshot["snapshot_date"] == "20260829"


def test_newly_registered_role_neutral_project_can_create_first_snapshot(
    make_workspace,
) -> None:
    """Catch initial Job setup compiling the inventory's pre-Job disabled state."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    registered = register_project(
        root,
        project_id="usWIP",
        project_path=storage_layout(root).projects_root / "usWIP",
        language_code="en",
        base_vrs_file="eng.vrs",
        imported_at=IMPORT_TIME,
    )
    assert registered["enabled"] is False

    created = JobStore(root, root / "ecosystem.yml").create_job(
        tool="stc",
        job_id="STC-usWIP_20260829",
        display_name="First snapshot after onboarding",
        bindings={"wip": "usWIP"},
        profiles={"target_grammar": "en/bol-target"},
    )

    assert created.wip_snapshot is not None
    assert created.wip_snapshot["project_status"] in {"READY", "READY_WITH_WARNINGS"}
    assert registered_project_records(root)["usWIP"]["enabled"] is False


def test_job_store_rejects_import_time_that_differs_from_registered_wip(
    make_workspace,
) -> None:
    """Catch callers overriding immutable Project import provenance."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")

    with pytest.raises(ValidationError) as exc_info:
        JobStore(root, root / "ecosystem.yml").create_job(
            tool="stc",
            job_id="STC-usWIP_20260901",
            display_name="Conflicting import provenance",
            bindings={"wip": "usWIP"},
            imported_at=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
        )

    assert exc_info.value.code == "PROJECT_IMPORT_DATE_MISMATCH"


def test_analysis_job_setup_blocks_legacy_project_without_import_date(
    make_workspace,
    monkeypatch,
) -> None:
    """Catch analysis setup inventing a snapshot date for legacy Project records."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    state = load_project_registry(root)
    state["projects"]["usWIP"].pop("imported_utc")
    state["projects"]["usWIP"].pop("imported_date")
    write_project_registry(root, state)
    project = load_ecosystem(root / "ecosystem.yml").project("usWIP")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    monkeypatch.setattr(
        center,
        "choose_or_add_resource",
        lambda *_args, **_kwargs: project,
    )

    created = center.create_job_wizard("stc")

    assert created is None
    rendered = output.getvalue()
    assert "Reason code:   PROJECT_IMPORT_DATE_MISSING" in rendered
    assert "Remove and re-add this Project to SAGE" in rendered


def test_job_project_chooser_reports_sage_import_date(make_workspace) -> None:
    """Catch Job setup selectors that omit when each candidate entered SAGE."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    selected = center.choose_or_add_resource("CHOOSE RTC <WIP Project>", "WIP")

    assert selected is not None
    assert selected.project_id == "usWIP"
    assert "Imported 20260829" in output.getvalue()


def test_job_project_chooser_wraps_long_project_rows_and_separates_add_action(
    make_workspace,
) -> None:
    """Catch long Project metadata overflowing or merging into the add action."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    update_project_record(
        root,
        "usWIP",
        {"display_name": "ukrNPUv1 New Ukrainian Translation ver. uk-UA"},
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["1"]),
            output=output,
            viewport_columns=72,
        ),
        skip_setup=True,
        dry_run_provider=True,
    )

    selected = center.choose_or_add_resource("Start new STC review <WIP PROJECT>", "WIP")

    rendered = output.getvalue()
    assert selected is not None
    assert selected.project_id == "usWIP"
    assert "ukrNPUv1 New Ukrainian Translation ver. uk-UA" in rendered
    assert max(len(line) for line in rendered.splitlines()) <= 72
    assert "[Imported 20260829]\n\n  2. Add another PROJECT to SAGE" in rendered


def test_bic_job_review_reports_all_selected_project_import_dates(
    make_workspace,
    monkeypatch,
) -> None:
    """Catch BIC review hiding SOURCE, DONOR, or TARGET import provenance."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "idKKHv0")
    _register_fixture_project(
        root,
        "usNIVv2",
        imported_at=datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc),
    )
    _register_fixture_project(
        root,
        "usBOLx1",
        imported_at=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
    )
    config = load_ecosystem(root / "ecosystem.yml")
    selected = iter(
        (
            config.project("idKKHv0"),
            config.project("usNIVv2"),
            config.project("usBOLx1"),
        )
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["yes", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    monkeypatch.setattr(
        center,
        "choose_or_add_resource",
        lambda *_args, **_kwargs: next(selected),
    )

    assert center.create_job_wizard("bic") is None

    rendered = output.getvalue()
    assert "SOURCE              idKKHv0\nDate imported       20260829" in rendered
    assert "DONOR               usNIVv2\nDate imported       20260830" in rendered
    assert "TARGET              usBOLx1\nDate imported       20260831" in rendered


def test_snapshot_refresh_retains_the_wip_project_import_date(make_workspace) -> None:
    """Catch snapshot refreshes that replace Project import provenance with refresh time."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260829",
        display_name="Import-date refresh",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["5", "", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center._job_settings_menu(job)

    refreshed = store.load_job("STC-usWIP_20260829", tool="stc")
    assert refreshed.status == "ACTIVE"
    assert refreshed.wip_snapshot is not None
    assert refreshed.wip_snapshot["snapshot_date"] == "20260829"
    assert not (store.job_root("stc", "STC-usWIP_20260901") / "job.yml").exists()
    assert "WIP snapshot refreshed: 20260829" in output.getvalue()


@pytest.mark.parametrize(
    ("tool", "job_id", "bindings"),
    (
        ("rtc", "RTC-usWIP_20260829", {"wip": "usWIP", "reference": "usNIVv2"}),
        ("stc", "STC-usWIP_20260829", {"wip": "usWIP"}),
    ),
)
def test_analysis_manage_job_exposes_delete_but_no_binding_replacement(
    make_workspace,
    tool,
    job_id,
    bindings,
) -> None:
    """RTC/STC Job bindings remain fixed throughout the Job lifetime."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool=tool,
        job_id=job_id,
        display_name="Immutable menu fixture",
        bindings=bindings,
        imported_at=IMPORT_TIME,
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center._job_settings_menu(job)

    rendered = output.getvalue()
    assert "6. Delete JOB" in rendered
    assert "Replace WIP Project" not in rendered
    assert "Update REFERENCE Project" not in rendered


@pytest.mark.parametrize(
    ("report_answer", "reports_remain"),
    (("n", True), ("y", False)),
)
def test_manage_job_delete_prompts_separately_for_published_reports(
    make_workspace,
    report_answer,
    reports_remain,
) -> None:
    """Deleting a Job preserves reports by default and never touches its Projects."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260829",
        display_name="Delete prompt fixture",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    store.set_active_job("stc", job.job_id)
    store.create_run(job, operation="stc", scope="MAT 1")
    report_root = storage_layout(root).reports_root / job.job_id
    published_report = report_root / "MAT" / "001" / "STC_ACTION-REPORT.md"
    published_report.parent.mkdir(parents=True)
    published_report.write_text("# Published report\n", encoding="utf-8")
    wip_project = storage_layout(root).projects_root / "usWIP"
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["6", report_answer, "y"]),
            output=output,
        ),
        skip_setup=True,
        dry_run_provider=True,
    )

    deleted = center._job_settings_menu(job)

    assert deleted is True
    assert not job.root.exists()
    assert report_root.exists() is reports_remain
    assert wip_project.is_dir()
    rendered = output.getvalue()
    assert "Published report files:       1" in rendered
    assert "SAGE Projects and Paratext Project files will NOT be deleted or modified." in rendered
    assert "Deleted Job: STC-usWIP_20260829" in rendered


def test_manage_job_delete_defaults_preserve_everything_on_final_cancellation(
    make_workspace,
) -> None:
    """Blank answers preserve reports and cancel the final destructive action."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260829",
        display_name="Delete cancellation fixture",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    report_root = storage_layout(root).reports_root / job.job_id
    published_report = report_root / "MAT" / "001" / "STC_ACTION-REPORT.md"
    published_report.parent.mkdir(parents=True)
    published_report.write_text("# Published report\n", encoding="utf-8")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["6", "", "", "a"]),
            output=output,
        ),
        skip_setup=True,
        dry_run_provider=True,
    )

    deleted = center._job_settings_menu(job)

    assert deleted is False
    assert job.root.is_dir()
    assert published_report.is_file()
    assert "Published reports:            PRESERVE" in output.getvalue()
    assert "Delete Job cancelled. No Job or report data was changed." in output.getvalue()


def test_delete_from_open_analysis_job_returns_to_parent_without_reloading_it(
    make_workspace,
) -> None:
    """The open RTC/STC Job screen must not reload a Job after deleting it."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _register_fixture_project(root, "usWIP")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260829",
        display_name="Open Job deletion fixture",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    store.set_active_job("stc", job.job_id)
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["3", "6", "y"]),
            output=io.StringIO(),
        ),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.analysis_job_menu(job)

    assert not job.root.exists()
    assert store.active_jobs()["stc"] is None


def _rtc_run_with_import_dates(root):
    """Create one real RTC Run whose bound Projects have distinct import dates."""
    _register_fixture_project(root, "usWIP")
    _register_fixture_project(
        root,
        "usNIVv2",
        imported_at=datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc),
    )
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260829",
        display_name="Run status imports",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=IMPORT_TIME,
    )
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    return job, run


def test_run_status_snapshot_reports_each_bound_project_import(make_workspace) -> None:
    """Catch shared Run Status data omitting Project import provenance."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _rtc_run_with_import_dates(root)

    snapshot = OperatorUIService(
        root=root,
        settings_path=root / "ecosystem.yml",
    ).runtime_snapshot()

    assert snapshot["job_progress"]["project_imports"] == [
        {
            "role": "WIP",
            "project_id": "usWIP",
            "imported_date": "20260829",
            "imported_utc": "2026-08-29T14:35:00+00:00",
        },
        {
            "role": "REFERENCE",
            "project_id": "usNIVv2",
            "imported_date": "20260830",
            "imported_utc": "2026-08-30T08:00:00+00:00",
        },
    ]


def test_run_status_does_not_expose_corrupt_import_timestamp(make_workspace) -> None:
    """Catch status JSON pairing UNKNOWN dates with unvalidated raw timestamps."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _rtc_run_with_import_dates(root)
    state = load_project_registry(root)
    state["projects"]["usWIP"]["imported_date"] = "20260231"
    write_project_registry(root, state)

    snapshot = OperatorUIService(
        root=root,
        settings_path=root / "ecosystem.yml",
    ).runtime_snapshot()

    wip = snapshot["job_progress"]["project_imports"][0]
    assert wip["imported_date"] == "UNKNOWN"
    assert wip["imported_utc"] is None


def test_classic_and_cli_run_status_render_project_import_dates(
    make_workspace,
    capsys,
) -> None:
    """Catch classic or CLI Run Status dropping canonical Project import rows."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _rtc_run_with_import_dates(root)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.status_overlay()

    rendered = output.getvalue()
    assert "PROJECT IMPORTS" in rendered
    assert "WIP               usWIP       Imported to SAGE 20260829" in rendered
    assert "REFERENCE         usNIVv2     Imported to SAGE 20260830" in rendered

    json_args = argparse.Namespace(
        settings=str(root / "ecosystem.yml"),
        json=True,
        live=False,
    )
    assert command_overview(json_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["job_progress"]["project_imports"][0]["imported_date"] == "20260829"

    text_args = argparse.Namespace(
        settings=str(root / "ecosystem.yml"),
        json=False,
        live=False,
    )
    assert command_overview(text_args) == 0
    cli_output = capsys.readouterr().out
    assert "Project import: WIP usWIP / 20260829" in cli_output
    assert "Project import: REFERENCE usNIVv2 / 20260830" in cli_output
