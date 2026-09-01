"""Read-only SAGE Scripture Resource Status Report contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from sage.jobs import JobStore
from sage.project_inventory import load_project_registry
from sage.resource_status_report import (
    build_resource_status_report,
    render_resource_status_report,
)


def test_resource_report_names_projects_and_authorities_without_mutation(
    make_workspace,
) -> None:
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    rtc = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="RTC fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )
    stc = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC fixture",
        bindings={"wip": "usWIP"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )
    store.set_active_job("rtc", rtc.job_id)
    store.set_active_job("stc", stc.job_id)
    before = deepcopy(load_project_registry(root))

    report = build_resource_status_report(
        root,
        settings_path=root / "ecosystem.yml",
    )
    rendered = render_resource_status_report(report)

    assert "usWIP" in rendered
    assert "usNIVv2" in rendered
    assert "GRK" in rendered
    assert "HEB" in rendered
    assert "RTC WIP" in rendered
    assert "RTC REFERENCE" in rendered
    assert "STC WIP" in rendered
    assert report["status"] in {
        "READY",
        "READY_WITH_STRUCTURE_PROBLEMS",
        "ACTION_NEEDED",
    }
    assert load_project_registry(root) == before


def test_resource_report_collects_run_structure_problems(make_workspace) -> None:
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC fixture",
        bindings={"wip": "usWIP"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )
    store.set_active_job("stc", job.job_id)
    run = store.create_run(job, operation="stc", scope="JHN 5")
    diagnostics = run.root / "diagnostics" / "VERSIFICATION-ADVISORIES.json"
    diagnostics.write_text(
        '{"advisories":[{"project_id":"GRK","reference":"JHN 5:4",'
        '"code":"VERSIFICATION_MISMATCH","message":"Missing coordinate"}]}\n',
        encoding="utf-8",
    )

    report = build_resource_status_report(
        root,
        settings_path=root / "ecosystem.yml",
    )

    grk = next(row for row in report["resources"] if row["project_id"] == "GRK")
    assert grk["status"] == "READY_WITH_STRUCTURE_PROBLEMS"
    assert grk["structural_issues"][0]["reference"] == "JHN 5:4"

