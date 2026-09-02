"""Operator-facing RTC/STC primary navigation contracts."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from sage.jobs import Job
from sage.menu import MenuIO, SageControlCenter, ScriptedInput


def _center(root, *responses: str) -> tuple[SageControlCenter, io.StringIO]:
    """Build a scripted control center and capture its Operator-facing output."""
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
    assert "2. Bible Index & Context (BIC)" in rendered
    assert "RTC active Job:" in rendered
    assert "STC active Job:" in rendered
    assert "\n3. SAW\n" not in rendered
    assert "Reference Text Comparison (RTC)" in rendered
    assert "Source Text Correspondence (STC)" in rendered


def test_analysis_creation_labels_use_sentence_case_and_review_context(make_workspace) -> None:
    """Catch title-case job nouns and generic chooser headings in RTC/STC setup."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center, output = _center(root, "a")

    center.analysis_menu("stc")

    rendered = output.getvalue()
    assert "Add STC job [WIP]" in rendered
    assert "Add STC Job [WIP]" not in rendered

    center, output = _center(root, "a")
    assert center.create_job_wizard("stc") is None
    assert "Start new STC review <WIP Project>" in output.getvalue()


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


def test_run_completion_preserves_report_only_structure_status(make_workspace) -> None:
    """A finalized task with a structural deficiency closes without becoming failed."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center, output = _center(root)
    job = center.store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC fixture",
        bindings={"wip": "usWIP"},
        imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
    )
    run = center.store.create_run(job, operation="stc", scope="MAT 1:1")
    task_root = run.root / "tasks" / "unit-001"
    validation = task_root / "validation"
    validation.mkdir(parents=True)
    manifest = task_root / "task-manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    (validation / "normalized-findings.json").write_text(
        json.dumps(
            {
                "source_comparison_status": "COMPLETE_WITH_STRUCTURE_PROBLEMS",
                "structural_issues": [
                    {
                        "classification": "STRUCTURE_PROBLEM",
                        "structure_status": "VERSIFICATION_MISMATCH",
                        "reference": "MAT 1:1",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    run = center.store.update_run(run, task_manifests=[str(manifest)])

    status = center._saw_completion_status(run)
    completed = center.store.update_run(run, status=status, current_stage=status)
    center._write_saw_run_complete(job, completed)

    assert completed.status == "COMPLETE_WITH_STRUCTURE_PROBLEMS"
    assert completed.result == "DONE"
    assert "STC RUN COMPLETE" in output.getvalue()
    assert "COMPLETE_WITH_STRUCTURE_PROBLEMS" in output.getvalue()
