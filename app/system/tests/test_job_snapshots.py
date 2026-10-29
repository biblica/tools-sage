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
    assert canonical_analysis_job_id("rtc", "ukrNPUv1", "20260901", "usNIV") == (
        "RTC-ukrNPUv1-usNIV_20260901"
    )
    assert canonical_analysis_job_id("rtc", "ukrNPUv1", "20260901", "usNASB") == (
        "RTC-ukrNPUv1-usNASB_20260901"
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
        ("rtc", "ukrNPUv1", "20260901"),
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


def _write_wip_book(root, filename: str, content: bytes) -> None:
    """Write one WIP book and declare it in the usWIP Project scope."""
    import yaml

    from sage.storage import storage_layout

    (storage_layout(root).projects_root / "usWIP" / filename).write_bytes(content)
    settings = root / "ecosystem.yml"
    raw = yaml.safe_load(settings.read_text(encoding="utf-8"))
    book = filename[2:5]
    projects = raw.get("projects") or raw["ecosystem"]["projects"]
    scope = projects["usWIP"]["scope"]
    if book not in scope["expected_books"]:
        scope["expected_books"].append(book)
    settings.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def test_snapshot_keeps_chapter_defect_and_records_exception(make_workspace) -> None:
    """A defect located in a chapter no longer stops the import; the chapter is reported not assessed."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _write_wip_book(root, "41MAT.SFM", b"\\id MAT\n\\c 1\n\\p\n\\v 1 One.\n\\v 2 Two.\n\\v 2 Again.\n\\v 3 Three.\n")

    receipt = capture_wip_snapshot(
        root, settings_path=root / "ecosystem.yml", project_id="usWIP",
        destination=root.parent / "chapter-defect-snapshot",
    )

    assert receipt["books"] == ["MAT"]
    assert receipt["project_status"] == "READY_WITH_EXCEPTIONS"
    assert receipt["left_out_books"] == []
    row = next(row for row in receipt["exceptions"] if row["code"] == "DUPLICATE_VERSE_RANGE")
    assert row["effect"] == "CHAPTER_NOT_ASSESSED"
    assert row["chapters"] == [1]


def test_snapshot_leaves_out_undecodable_book(make_workspace) -> None:
    """An undecodable book is left out of the snapshot; the other books are imported."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _write_wip_book(root, "42MRK.SFM", b"\\id MRK\n\\c 1\n\\p\n\\v 1 bad\xff\n")

    receipt = capture_wip_snapshot(
        root, settings_path=root / "ecosystem.yml", project_id="usWIP",
        destination=root.parent / "undecodable-snapshot",
    )

    assert receipt["books"] == ["MAT"]
    assert receipt["left_out_books"] == ["MRK"]
    assert receipt["project_status"] == "READY_WITH_EXCEPTIONS"
    row = next(row for row in receipt["exceptions"] if row["code"] == "INVALID_UTF8")
    assert row["effect"] == "BOOK_LEFT_OUT"
    assert row["file"] == "42MRK.SFM"
    assert not (root.parent / "undecodable-snapshot" / "usj" / "MRK.json").exists()


def test_snapshot_fails_when_every_book_is_left_out(make_workspace) -> None:
    """With no usable book left there is nothing to import, so the import still stops."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _write_wip_book(root, "41MAT.SFM", b"\\id MAT\n\\c 1\n\\p\n\\v 1 bad\xff\n")

    with pytest.raises(ValidationError) as failure:
        capture_wip_snapshot(
            root, settings_path=root / "ecosystem.yml", project_id="usWIP",
            destination=root.parent / "empty-snapshot",
        )
    assert failure.value.code == "WIP_SNAPSHOT_IMPORT_FAILED"
    assert not (root.parent / "empty-snapshot").exists()


def test_snapshot_exception_summary_names_books_and_chapters() -> None:
    """The Job screen names left-out books and not-assessed chapters in one line."""
    from sage.job_menus import snapshot_exception_summary

    snapshot = {"exceptions": [
        {"book": "MRK", "effect": "BOOK_LEFT_OUT", "chapters": []},
        {"book": "MAT", "effect": "CHAPTER_NOT_ASSESSED", "chapters": [10, 2]},
    ]}
    assert snapshot_exception_summary(snapshot) == "books left out: MRK; chapters not assessed: MAT 2, MAT 10"
    assert snapshot_exception_summary({}) == ""
