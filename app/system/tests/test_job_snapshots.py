"""Canonical RTC/STC identity and immutable WIP snapshot contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from sage.errors import ValidationError
from sage.job_snapshots import capture_wip_snapshot, seal_run_snapshot
from sage.workflow_identity import canonical_analysis_job_id, runtime_workflow_id


def test_analysis_job_identity_uses_snapshot_date_and_internal_adapter() -> None:
    """Wrong workflow prefixes, execution dates, or legacy routing break Job identity."""
    assert canonical_analysis_job_id("rtc", "ukrNPUv1", "20260901") == (
        "RTC-ukrNPUv1_20260901"
    )
    assert canonical_analysis_job_id("stc", "ukrNPUv1", "20260901") == (
        "STC-ukrNPUv1_20260901"
    )
    assert runtime_workflow_id("rtc") == "rtc"
    assert runtime_workflow_id("stc") == "stc"


@pytest.mark.parametrize(
    ("tool", "project_id", "snapshot_date"),
    (
        ("saw", "ukrNPUv1", "20260901"),
        ("rtc", "bad/project", "20260901"),
        ("stc", "ukrNPUv1", "2026-09-01"),
    ),
)
def test_analysis_job_identity_rejects_noncanonical_inputs(
    tool: str,
    project_id: str,
    snapshot_date: str,
) -> None:
    """Unsafe Project IDs and non-snapshot dates cannot enter persisted path identity."""
    with pytest.raises(ValidationError):
        canonical_analysis_job_id(tool, project_id, snapshot_date)


def test_capture_and_seal_wip_snapshot(make_workspace) -> None:
    """A Run owns copied USJ evidence and a receipt independent from the mutable Job."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    imported_at = datetime(2026, 9, 1, 10, 30, tzinfo=timezone.utc)
    job_snapshot = root.parent / "job-snapshot-fixture"

    receipt = capture_wip_snapshot(
        root,
        settings_path=root / "ecosystem.yml",
        project_id="usWIP",
        destination=job_snapshot,
        imported_at=imported_at,
    )

    assert receipt["project_id"] == "usWIP"
    assert receipt["snapshot_date"] == "20260901"
    assert receipt["imported_utc"] == "2026-09-01T10:30:00+00:00"
    assert len(receipt["content_fingerprint"]) == 64
    assert receipt["books"] == ["MAT"]
    assert receipt["atomic_coordinates"] == 3
    assert receipt["source_location"].endswith("/usWIP")
    assert (job_snapshot / "usj" / "MAT.json").is_file()

    run_snapshot = root.parent / "run-snapshot-fixture"
    sealed = seal_run_snapshot(
        job_snapshot,
        run_snapshot,
        run_id="RTC-usWIP_20260901-001",
    )
    sealed_bytes = (run_snapshot / "usj" / "MAT.json").read_bytes()
    (job_snapshot / "usj" / "MAT.json").write_text("changed", encoding="utf-8")

    assert sealed["content_fingerprint"] == receipt["content_fingerprint"]
    assert (run_snapshot / "usj" / "MAT.json").read_bytes() == sealed_bytes
    sealed_receipt = json.loads(
        (run_snapshot / "SNAPSHOT.json").read_text(encoding="utf-8")
    )
    assert sealed_receipt["run_id"] == "RTC-usWIP_20260901-001"
    assert sealed_receipt["sealed_from_snapshot_date"] == "20260901"
