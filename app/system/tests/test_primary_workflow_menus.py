"""Operator-facing RTC/STC primary navigation contracts."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from sage.jobs import Job
from sage.menu import MenuIO, SageControlCenter, ScriptedInput


def _center(root, *responses: str) -> tuple[SageControlCenter, io.StringIO]:
    output = io.StringIO()
    return (
        SageControlCenter(
            sage_root=root,
            settings_path=root / "ecosystem.yml",
            io=MenuIO(input_func=ScriptedInput(responses), output=output),
            skip_setup=True,
            dry_run_provider=True,
        ),
        output,
    )


def test_main_menu_exposes_rtc_and_stc_without_saw(make_workspace) -> None:
    """SAW is an internal adapter, not an operator-facing primary flow."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center, output = _center(root, "c")

    assert center.main_menu() == "X"

    rendered = output.getvalue()
    assert "BIC active Job:" in rendered
    assert "RTC active Job:" in rendered
    assert "STC active Job:" in rendered
    assert "\n3. SAW\n" not in rendered
    assert "Reference Text Comparison (RTC)" in rendered
    assert "Source Text Correspondence (STC)" in rendered


def test_stc_menu_has_no_reference_or_parked_checks(make_workspace) -> None:
    """STC shows its WIP Project and one fixed STC Run action only."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center, output = _center(root, "a")
    job = center.store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC fixture",
        bindings={"wip": "usWIP"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )

    center.analysis_job_menu(job)

    rendered = output.getvalue()
    assert "WIP Project                  usWIP" in rendered
    assert "REFERENCE" not in rendered
    assert "Run Source Text Correspondence (STC)" in rendered
    assert "Targeted Check" not in rendered
    assert "Original-Language Review" not in rendered


def test_rtc_menu_keeps_reference_and_one_fixed_rtc_action(make_workspace) -> None:
    """RTC retains WIP+REFERENCE and does not expose parked standalone checks."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center, output = _center(root, "a")
    job = center.store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="RTC fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )

    center.analysis_job_menu(job)

    rendered = output.getvalue()
    assert "WIP Project                  usWIP" in rendered
    assert "REFERENCE Project            usNIVv2" in rendered
    assert "Run Reference Text Comparison (RTC)" in rendered
    assert "Targeted Check" not in rendered
    assert "Original-Language Review" not in rendered


def test_analysis_creation_returns_selected_job(make_workspace) -> None:
    """The fixed-flow wizard returns the created Job to its caller."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center, _output = _center(root)
    created = center.store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC fixture",
        bindings={"wip": "usWIP"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )

    assert isinstance(created, Job)
    assert center.store.discover("stc") == [created]
