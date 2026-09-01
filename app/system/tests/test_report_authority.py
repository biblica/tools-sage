"""Authority-explicit RTC/STC report identity and path contracts."""

from __future__ import annotations

from datetime import datetime, timezone

from sage.jobs import JobStore
from sage.plan_continuation import _chapter_bundle_paths
from sage.registry import load_ecosystem
from sage.report_authority import authority_header, chapter_report_path


def _stc_job_and_run(root):
    """Create a canonical STC fixture Job and its first serial Run."""
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC fixture",
        bindings={"wip": "usWIP"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )
    return job, store.create_run(job, operation="stc", scope="JHN 5")


def test_stc_header_names_project_and_grk(make_workspace) -> None:
    """STC headers identify the WIP Project and exact Greek authority."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    job, run = _stc_job_and_run(root)

    rendered = "\n".join(
        authority_header(job, run, family="GRK", fingerprints={"GRK": "a" * 64})
    )

    assert "Analysis                     STC" in rendered
    assert "WIP Project                  usWIP" in rendered
    assert "Original-language authority  GRK" in rendered
    assert "REFERENCE Project            NOT USED" in rendered
    assert "GRK:PRIMARY" not in rendered


def test_rtc_header_names_reference_and_snapshot(make_workspace) -> None:
    """RTC headers identify both Projects and the imported WIP snapshot."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="RTC fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )
    run = store.create_run(job, operation="rtc", scope="JHN 5")

    rendered = "\n".join(
        authority_header(
            job,
            run,
            fingerprints={"usNIVv2": "b" * 64},
        )
    )

    assert "Analysis                     RTC" in rendered
    assert "WIP snapshot date            2026-09-01" in rendered
    assert "REFERENCE Project            usNIVv2" in rendered
    assert "Original-language authority  NOT USED" in rendered


def test_chapter_report_path_uses_job_run_book_and_chapter(
    make_workspace,
    tmp_path,
) -> None:
    """Chapter reports nest beneath Job, Book, and zero-padded chapter."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    job, run = _stc_job_and_run(root)

    path = chapter_report_path(tmp_path, job, run, "JHN", 5)

    assert path == (
        tmp_path
        / job.job_id
        / "JHN"
        / "005"
        / f"{run.run_id}_JHN-005_ACTION-REPORT.md"
    )


def test_primary_rtc_plan_resolves_its_rtc_job_container(make_workspace) -> None:
    """The reused SAW report adapter accepts canonical RTC storage without leaking it."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="RTC fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )
    run = store.create_run(job, operation="rtc", scope="JHN 5")
    plan_path = run.root / "plans" / "RTC-report-fixture.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("{}\n", encoding="utf-8")
    runtime = load_ecosystem(store.ensure_runtime_files(job))

    report, note, data = _chapter_bundle_paths(
        runtime,
        plan_path,
        book="JHN",
        chapter=5,
        report_id="RTC",
    )

    stem = f"{run.run_id}_JHN-005"
    assert report.name == f"{stem}_ACTION-REPORT.md"
    assert note.name == f"{stem}_OPERATOR-NOTE.txt"
    assert data.name == f"{stem}_CONSOLIDATED.json"
    assert report.parent.name == "005"
    assert data.parent.name == "005"
