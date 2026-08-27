"""Sequential Job/Run progress-contract and compact TUI rendering regressions."""

from __future__ import annotations

import argparse
import io
import json

import pytest
import yaml

from sage.errors import ValidationError
from sage.cli import command_overview
from sage.jobs import JobStore
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.progress import (
    DEFAULT_JOB_PROGRESS_POLICY,
    PROGRESS_BASIS_ACT_ESTIMATED_TOKENS,
    PROGRESS_BASIS_PROJECTED_HANDOFF_ESTIMATED_TOKENS,
    format_activity_label,
    format_progress_line,
    quantify_run,
    render_progress_bar,
)


def _task_manifest(path, *, task_id: str, operation: str, skill_id: str, tokens: int) -> None:
    """Write one minimal governed-task-shaped manifest for progress quantification tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "operation": operation,
                "skill": {"id": skill_id},
                "context_budget": {"final_estimated_tokens": tokens},
                "allowed_writes": ["output/result.json"],
            }
        ),
        encoding="utf-8",
    )


def test_progress_bar_uses_ten_visual_cells_with_integer_percent() -> None:
    """Keep the agreed 10-percent visual cells while retaining integer percentage precision."""
    assert render_progress_bar(7) == "[░░░░░░░░░░]"
    assert render_progress_bar(43) == "[████░░░░░░]"
    assert render_progress_bar(99) == "[█████████░]"
    assert render_progress_bar(100) == "[██████████]"

    line = format_progress_line("SAW_UK-ENG", {"percent": 43})
    assert "[████░░░░░░]  43%" in line
    assert format_progress_line("SAW_UK-ENG", {"percent": 7}).endswith("   7%")
    assert format_progress_line("SAW_UK-ENG", {"percent": 100}).endswith(" 100%")


def test_run_progress_is_token_weighted_and_advances_only_on_finalized_tasks(tmp_path) -> None:
    """Weight unequal ACT tasks by sealed token estimate and advance only after governed finalization."""
    first = tmp_path / "run" / "tasks" / "task-1" / "task.json"
    second = tmp_path / "run" / "tasks" / "task-2" / "task.json"
    _task_manifest(first, task_id="task-1", operation="rtc", skill_id="saw-rtc", tokens=1000)
    _task_manifest(second, task_id="task-2", operation="ol", skill_id="staw-original-language-review", tokens=3000)
    validation = first.parent / "validation"
    validation.mkdir()
    (validation / "submission.json").write_text(
        json.dumps({"status": "FINALIZED"}), encoding="utf-8"
    )

    progress = quantify_run(
        root=tmp_path,
        task_manifests=(str(first), str(second)),
        run_status="PARTITIONED_IN_PROGRESS",
        current_stage="SELECTIVE_OL_ADJUDICATION",
    ).to_dict()

    assert progress["total"] == 4000
    assert progress["completed"] == 1000
    assert progress["percent"] == 25
    assert progress["task_completed"] == 1
    assert progress["task_total"] == 2
    assert progress["active_operation"] == "OL"
    assert progress["active_skill_id"] == "staw-original-language-review"
    assert format_activity_label(progress) == "OL / staw-original-language-review / RUNNING"


def test_progress_prefers_projected_handoff_but_preserves_legacy_raw_basis(tmp_path) -> None:
    """New Jobs track projected provider work while historical Jobs can retain raw ACT weighting."""
    first = tmp_path / "run" / "tasks" / "task-1" / "task.json"
    second = tmp_path / "run" / "tasks" / "task-2" / "task.json"
    for path, task_id, projected, raw in (
        (first, "task-1", 1000, 9000),
        (second, "task-2", 3000, 3000),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "operation": "rtc",
                    "skill": {"id": "saw-rtc"},
                    "context_budget": {
                        "final_estimated_tokens": projected,
                        "provider_handoff": {"total_estimated_tokens": projected},
                        "governance_context": {"final_estimated_tokens": raw},
                    },
                    "allowed_writes": ["output/result.json"],
                }
            ),
            encoding="utf-8",
        )
    validation = first.parent / "validation"
    validation.mkdir()
    (validation / "submission.json").write_text(json.dumps({"status": "FINALIZED"}), encoding="utf-8")

    projected = quantify_run(
        root=tmp_path,
        task_manifests=(str(first), str(second)),
        run_status="PARTITIONED_IN_PROGRESS",
        current_stage="REFERENCE_TEXT_COMPARISON",
        basis=PROGRESS_BASIS_PROJECTED_HANDOFF_ESTIMATED_TOKENS,
    )
    legacy = quantify_run(
        root=tmp_path,
        task_manifests=(str(first), str(second)),
        run_status="PARTITIONED_IN_PROGRESS",
        current_stage="REFERENCE_TEXT_COMPARISON",
        basis=PROGRESS_BASIS_ACT_ESTIMATED_TOKENS,
    )

    assert (projected.completed, projected.total, projected.percent) == (1000, 4000, 25)
    assert (legacy.completed, legacy.total, legacy.percent) == (9000, 12000, 75)


def test_job_contract_records_canonical_progress_quantifier(make_workspace) -> None:
    """New Jobs persist the canonical progress policy used by every interactive surface."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Progress contract",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )

    raw = yaml.safe_load(job.manifest_path.read_text(encoding="utf-8"))
    assert raw["progress_quantifier"] == DEFAULT_JOB_PROGRESS_POLICY.to_dict()
    assert job.progress_quantifier == DEFAULT_JOB_PROGRESS_POLICY.to_dict()


def test_run_terminal_result_is_separate_and_blocked_requires_reason(make_workspace) -> None:
    """Treat BLOCKED as a terminator with a reason rather than an active execution phase."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Progress result contract",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    run = store.create_run(job, operation="rtc", scope="MAT 1")

    with pytest.raises(ValidationError, match="requires result_reason"):
        store.update_run(run, status="BLOCKED")

    blocked = store.update_run(run, status="BLOCKED", result_reason="AI_AUTH_REQUIRED")
    assert blocked.result == "BLOCKED"
    assert blocked.result_reason == "AI_AUTH_REQUIRED"

    replacement = store.create_run(job, operation="rtc", scope="MAT 2")
    done = store.update_run(replacement, status="COMPLETE", current_stage="COMPLETE")
    assert done.result == "DONE"
    assert store.active_run(job) is None
    assert not (job.root / ".sage" / "state" / "active-run.json").exists()


def test_completed_run_pointer_is_not_reported_as_active(make_workspace) -> None:
    """Discard a stale controller pointer that references a completed Run."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Legacy active Run pointer",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    run = store.create_run(job, operation="rtc", scope="EXO 1-2")
    completed = store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
    pointer = job.controller_state_root / "active-run.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps({"schema_version": "1.0", "run_id": completed.run_id}),
        encoding="utf-8",
    )

    assert store.active_run(job) is None
    assert not pointer.exists()
    with pytest.raises(ValidationError, match="Cannot make a complete Run active"):
        store.set_active_run(job, completed.run_id)


def test_ui_service_reports_persisted_run_progress(make_workspace) -> None:
    """Expose the canonical Run quantifier through the shared UI service used by dashboard and Status."""
    from sage.ui_services import OperatorUIService

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="TUI progress",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    first = run.root / "tasks" / "task-1" / "task.json"
    second = run.root / "tasks" / "task-2" / "task.json"
    _task_manifest(first, task_id="task-1", operation="rtc", skill_id="saw-rtc", tokens=1000)
    _task_manifest(second, task_id="task-2", operation="ol", skill_id="staw-original-language-review", tokens=3000)
    validation = first.parent / "validation"
    validation.mkdir()
    (validation / "submission.json").write_text(json.dumps({"status": "FINALIZED"}), encoding="utf-8")
    run = store.update_run(
        run,
        status="PARTITIONED_IN_PROGRESS",
        current_stage="SELECTIVE_OL_ADJUDICATION",
        task_manifests=[str(first), str(second)],
    )

    snapshot = OperatorUIService(root=root, settings_path=root / "ecosystem.yml").runtime_snapshot()
    progress = snapshot["job_progress"]

    assert snapshot["current_job"] == job.job_id
    assert snapshot["current_run"] == run.run_id
    assert progress["percent"] == 25
    assert "[██░░░░░░░░]  25%" in progress["line"]
    assert progress["activity"] == "OL / staw-original-language-review / RUNNING"


def _progress_run(root):
    """Create one active two-task Run at 25 percent for status-surface regressions."""
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Status progress",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    first = run.root / "tasks" / "task-1" / "task.json"
    second = run.root / "tasks" / "task-2" / "task.json"
    _task_manifest(first, task_id="task-1", operation="rtc", skill_id="saw-rtc", tokens=1000)
    _task_manifest(second, task_id="task-2", operation="ol", skill_id="staw-original-language-review", tokens=3000)
    validation = first.parent / "validation"
    validation.mkdir()
    (validation / "submission.json").write_text(json.dumps({"status": "FINALIZED"}), encoding="utf-8")
    run = store.update_run(
        run,
        status="PARTITIONED_IN_PROGRESS",
        current_stage="SELECTIVE_OL_ADJUDICATION",
        task_manifests=[str(first), str(second)],
    )
    return job, run


def test_classic_status_exposes_canonical_active_job_progress(make_workspace) -> None:
    """F Status in the classic menu must show the same governed Run quantifier as the TUI."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    job, run = _progress_run(root)
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
    assert "ACTIVE JOB" in rendered
    assert f"{job.job_id}" in rendered
    assert "[██░░░░░░░░]  25%" in rendered
    assert "OL / staw-original-language-review / RUNNING" in rendered
    assert f"Run: {run.run_id}" in rendered
    assert "Tasks: 1/2" in rendered


def test_cli_status_json_exposes_canonical_active_job_progress(make_workspace, capsys) -> None:
    """Top-level local status must expose the same Run progress snapshot without a provider probe."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    job, run = _progress_run(root)
    args = argparse.Namespace(settings=str(root / "ecosystem.yml"), json=True, live=False)

    assert command_overview(args) == 0

    payload = json.loads(capsys.readouterr().out)
    progress = payload["job_progress"]
    assert progress["job_id"] == job.job_id
    assert progress["run_id"] == run.run_id
    assert progress["percent"] == 25
    assert "[██░░░░░░░░]  25%" in progress["line"]
    assert progress["activity"] == "OL / staw-original-language-review / RUNNING"
