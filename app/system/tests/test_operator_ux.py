"""Guided-launch, resume-state, and streamlined operator UX contracts."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from sage.storage import storage_layout
from sage.errors import ValidationError
from sage.executors.codex_cli import CodexCLIExecutor
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.jobs import JobStore


def _center(root: Path, inputs: list[str]) -> SageControlCenter:
    """Build one deterministic control center for operator-UX regression tests."""
    return SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(inputs), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )


def test_controller_surfaces_blocking_validation_errors_and_next_action(make_workspace, monkeypatch) -> None:
    """A blocked controller response must not collapse into an unactionable generic error."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    center = _center(root, [])
    payload = {
        "state": "BLOCKED",
        "errors": ["Project demo contains books outside declared scope: MRK"],
        "next_action": "Correct the declared Project scope and retry.",
    }
    monkeypatch.setattr(center.store, "ensure_runtime_files", lambda _job: job.runtime_settings_path)
    monkeypatch.setattr(
        "sage.menu.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 2, stdout=json.dumps(payload), stderr=""
        ),
    )

    with pytest.raises(ValidationError) as caught:
        center.controller(job, ["workspace", "initialize"])
    assert caught.value.code == "WORKSPACE_INITIALIZATION_BLOCKED"
    assert caught.value.message == payload["errors"][0]
    assert caught.value.next_action == payload["next_action"]


def test_blocking_menu_action_has_visible_status_and_clears_line(make_workspace) -> None:
    """Long controller phases expose an immediate heartbeat and finish on a normal line."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = _center(root, [])

    result = center._run_with_status(
        "Preparing governed SAW task plan...",
        lambda: {"ok": True},
    )

    rendered = center.io.output.getvalue()
    assert result == {"ok": True}
    assert "Preparing governed SAW task plan..." in rendered
    assert rendered.endswith("\n")


def test_codex_quick_status_is_bounded_to_version_and_login_status(monkeypatch) -> None:
    """Verify startup preflight avoids live model discovery and accepts ChatGPT CLI login."""
    executor = CodexCLIExecutor(command="codex")
    calls: list[list[str]] = []

    def fake_run(args, *, timeout):
        """Return deterministic CLI preflight responses without starting Codex."""
        calls.append(list(args))
        if args == ["--version"]:
            return subprocess.CompletedProcess(args, 0, stdout="codex-cli 1.2.3\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="Logged in using ChatGPT\n", stderr="")

    monkeypatch.setattr(executor, "_run", fake_run)
    status = executor.quick_status()

    assert calls == [["--version"], ["login", "status"]]
    assert status.available is True
    assert status.ready is True
    assert status.auth_mode == "CHATGPT"
    assert status.version == "codex-cli 1.2.3"


def test_codex_execution_failure_omits_prompt_and_keeps_diagnostic_tail() -> None:
    """Provider failures must surface the final cause without leaking sealed task evidence."""
    prompt = "SAGE GOVERNED LLM EXECUTION\n" + ("sealed evidence\n" * 300)
    raw = (
        "OpenAI Codex\nuser\n"
        + prompt
        + "\nprovider event\nERROR: structured output schema rejected field coverage"
    )

    detail = CodexCLIExecutor._execution_failure_detail(raw, prompt, limit=240)

    assert "sealed evidence" not in detail
    assert "structured output schema rejected field coverage" in detail
    assert len(detail) <= 275


def test_setup_never_installs_codex_without_operator_confirmation(make_workspace) -> None:
    """Verify missing Codex installation remains opt-in even inside guided setup."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = _center(root, ["n"])

    class FakeService:
        """Expose only the install/status methods used by the guided install action."""

        installs = 0

        def quick_codex_status(self):
            """Report the CLI as absent."""
            return {"available": False, "ready": False, "auth_mode": "NONE"}

        def install_codex(self):
            """Fail the test if installation occurs without consent."""
            self.installs += 1
            return {"available": True, "ready": False, "auth_mode": "UNVERIFIED"}

    service = FakeService()
    result = center._setup_install_codex(service)  # noqa: SLF001 - intentional UI contract test

    assert service.installs == 0
    assert result["available"] is False


def test_operator_cue_journal_is_append_only_and_not_workflow_state(make_workspace) -> None:
    """Verify high-level operator cues append independently from transactional workflow state."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")

    store.record_cue("sage_started")
    store.record_cue("new_task_selected", tool="bic", project_id="demo")

    rows = [json.loads(line) for line in store.operator_cues_path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["SAGE_STARTED", "NEW_TASK_SELECTED"]
    assert rows[1]["tool"] == "bic"
    assert not (storage_layout(root).transactions_root / "transaction-journal.jsonl").exists()


def test_start_new_task_goes_directly_to_bic_scope_entry(make_workspace, monkeypatch) -> None:
    """Verify the main new-task action does not force a second pass through the BIC menu."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    jobs = store.bootstrap_default_jobs()
    bic = next(job for job in jobs if job.tool == "bic")
    store.set_active_job("bic", bic.job_id)
    center = _center(root, ["1"])
    started: list[str] = []

    def fake_start(job):
        """Capture the selected BIC Job instead of opening scope prompts."""
        started.append(job.job_id)

    monkeypatch.setattr(center, "start_bic_run", fake_start)
    center.resume_or_start_task()

    assert started == [bic.job_id]
    cue_rows = [json.loads(line) for line in center.store.operator_cues_path.read_text(encoding="utf-8").splitlines()]
    assert cue_rows[-1]["event"] == "NEW_TASK_SELECTED"
    assert cue_rows[-1]["tool"] == "bic"


@pytest.mark.parametrize(("entered", "expected"), (("gen 1", "GEN 1"), ("gen", "GEN")))
def test_scope_menu_accepts_direct_chapter_or_book(make_workspace, entered, expected) -> None:
    """A scope typed at the selection prompt preserves whole-chapter/book semantics."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    center = _center(root, [entered])

    assert center._select_scripture_scope(job, primary_binding="wip") == expected


def test_scope_menu_blank_selection_defaults_to_choose_book(make_workspace, monkeypatch) -> None:
    """Pressing Enter at scope selection defaults to the guided Choose Book path."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    center = _center(root, ["", "1", ""])
    monkeypatch.setattr("sage.menu.registered_project_records", lambda _root: {job.bindings["wip"]: {"detected_books": ["MAT"]}})

    assert center._select_scripture_scope(job, primary_binding="wip") == "MAT"
    rendered = center.io.output.getvalue()
    assert "1. Choose Book" in rendered
    assert "2. Enter complete scope directly" in rendered


def test_scope_menu_blank_range_selects_entire_chosen_book(make_workspace, monkeypatch) -> None:
    """Pressing Enter at Range must accept the advertised whole-book selection."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    center = _center(root, ["1", "1", ""])
    monkeypatch.setattr("sage.menu.registered_project_records", lambda _root: {job.bindings["wip"]: {"detected_books": ["MAT"]}})

    assert center._select_scripture_scope(job, primary_binding="wip") == "MAT"
    rendered = center.io.output.getvalue()
    assert "[blank] whole book" in rendered
    assert "Range is required." not in rendered


def test_saw_composite_creation_reports_plan_without_requiring_act_path(
    make_workspace,
    monkeypatch,
) -> None:
    """A composite RTC stage continues immediately without being formatted as one ACT."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    plan_path = run.root / "plans" / "composite.json"
    planned = store.update_run(
        run,
        status="COMPOSITE",
        current_stage="REFERENCE_TEXT_COMPARISON",
        plan_path=str(plan_path),
        task_manifests=["task-1.json", "task-2.json"],
    )
    center = _center(root, [])
    monkeypatch.setattr(
        center,
        "_create_task",
        lambda _job, _run, _operation: (
            planned,
            {
                "status": "COMPOSITE",
                "current_stage": "REFERENCE_TEXT_COMPARISON",
                "plan_path": str(plan_path),
                "task_manifests": ["task-1.json", "task-2.json"],
            },
        ),
    )
    continued: list[str] = []

    def fake_continue(_job, current):
        """Capture automatic plan continuation after the operator authorizes the Run."""
        continued.append(str(current.plan_path))
        return current

    monkeypatch.setattr(center, "_continue_saw_plan", fake_continue)

    result = center._continue_saw(job, run)

    assert result.plan_path == str(plan_path)
    assert continued == [str(plan_path)]
    assert "Created SAW Reference Text Comparison (RTC) composite plan" not in center.io.output.getvalue()
    assert center.io.output.getvalue() == ""


def test_unexpected_run_continuation_error_is_bounded_at_menu_boundary(
    make_workspace,
    monkeypatch,
) -> None:
    """An internal continuation defect must preserve the Run and return to the menu."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    center = _center(root, [""])
    monkeypatch.setattr(center, "ensure_initialized", lambda _job: {"state": "READY"})

    def fail(_job, _run):
        """Simulate an unexpected implementation error after Run persistence."""
        raise KeyError("act_path")

    monkeypatch.setattr(center, "_continue_saw", fail)

    center.continue_run(job, run)

    rendered = center.io.output.getvalue()
    assert "SAGE ERROR" in rendered
    assert "RUN_CONTINUATION_FAILED" in rendered
    assert store.load_run(job, run.run_id).status == "NEW"


def test_saw_continuation_displays_composite_unit_progress(make_workspace, monkeypatch) -> None:
    """A composite continuation names the next scope and its position before execution."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    plan_path = run.root / "plans" / "composite.json"
    run = store.update_run(run, plan_path=str(plan_path), status="COMPOSITE")
    manifest_path = run.root / "tasks" / "unit-1" / "task-manifest.json"
    center = _center(root, [])
    monkeypatch.setattr(
        center,
        "controller",
        lambda _job, _arguments: {
            "status": "NEXT_WORK_UNIT",
            "completed_units": 0,
            "total_units": 10,
            "composite_stage": "REFERENCE_TEXT_COMPARISON",
            "next_unit": {
                "manifest_path": str(manifest_path),
                "scope": "MAT 1:1-2",
            },
        },
    )
    monkeypatch.setattr(center, "_task_action", lambda _job, current, _path: (current, False))

    center._continue_saw_plan(job, run)

    assert "SAW work unit 1/10: MAT 1:1-2" in center.io.output.getvalue()


def test_saw_plan_continuation_advances_all_submitted_units_without_menu_round_trips(
    make_workspace,
    monkeypatch,
) -> None:
    """One authorized Continue action advances every ready unit until the plan completes."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    plan_path = run.root / "plans" / "composite.json"
    run = store.update_run(run, plan_path=str(plan_path), status="COMPOSITE")
    manifests = [
        run.root / "tasks" / "unit-1" / "task-manifest.json",
        run.root / "tasks" / "unit-2" / "task-manifest.json",
    ]
    responses = iter(
        (
            {
                "status": "NEXT_WORK_UNIT",
                "completed_units": 0,
                "total_units": 2,
                "composite_stage": "REFERENCE_TEXT_COMPARISON",
                "next_unit": {"manifest_path": str(manifests[0]), "scope": "MAT 1:1-12"},
            },
            {
                "status": "NEXT_WORK_UNIT",
                "completed_units": 1,
                "total_units": 2,
                "composite_stage": "REFERENCE_TEXT_COMPARISON",
                "next_unit": {"manifest_path": str(manifests[1]), "scope": "MAT 1:13-25"},
            },
            {"status": "COMPLETE"},
        )
    )
    center = _center(root, [""])
    monkeypatch.setattr(center, "controller", lambda _job, _arguments: next(responses))
    actions: list[Path] = []

    def fake_action(_job, current, path):
        """Treat each generated task as executed and submitted."""
        actions.append(path)
        return current, True

    monkeypatch.setattr(center, "_task_action", fake_action)

    completed = center._continue_saw_plan(job, run)

    assert completed.status == "COMPLETE"
    assert actions == manifests
    rendered = center.io.output.getvalue()
    assert "SAW work unit 1/2: MAT 1:1-12" in rendered
    assert "SAW work unit 2/2: MAT 1:13-25" in rendered
    assert "SAW RUN COMPLETE" in rendered
    assert "Reference Text Comparison (RTC)" in rendered


def test_stc_run_template_uses_primary_source_and_shared_completion_layout(
    make_workspace,
) -> None:
    """STC mirrors RTC Run chrome while naming the testament-routed primary source."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="stc", scope="MAT 1")
    center = _center(root, [])

    center._write_saw_run_header(job, run)
    center._write_saw_run_complete(
        job,
        run,
        report_directory=str(storage_layout(root).reports_root / job.job_id / "MAT"),
    )

    rendered = center.io.output.getvalue()
    assert f"{job.output_project} checked against GRK OL" in rendered
    assert f"checked against {job.contemporary_source}" not in rendered
    assert "Checking Source Text Correspondence (STC) for MAT 1" in rendered
    assert "SAW RUN COMPLETE" in rendered
    assert f"{'Check':<20}Source Text Correspondence (STC)" in rendered
    assert "SAGE/localdata/reports" in rendered


def test_stc_normal_run_hides_controller_chatter_behind_rtc_progress_template(
    make_workspace,
    monkeypatch,
) -> None:
    """Normal STC execution exposes only the shared SAW Run/progress/completion surface."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="stc", scope="MAT 1")
    center = _center(root, [""])
    manifest = run.root / "tasks" / "stc-unit" / "task-manifest.json"

    def create(_job, current, _operation):
        """Return a sealed standalone task without invoking the real controller."""
        updated = store.update_run(
            current,
            task_manifests=[str(manifest)],
            status="TASK_CREATED",
            current_stage="STC",
        )
        return updated, {
            "status": "TASK_CREATED",
            "manifest_path": str(manifest),
            "act_path": str(manifest.parent / "ACT.md"),
        }

    monkeypatch.setattr(center, "_create_task", create)
    monkeypatch.setattr(center, "_task_action", lambda _job, current, _path: (current, True))
    monkeypatch.setattr(center, "_task_state", lambda _path: ("FINALIZED", {"operation": "stc"}))
    monkeypatch.setattr(
        center,
        "_ensure_stc_task_publication",
        lambda _job, _path: {
            "report_directory": str(storage_layout(root).reports_root / job.job_id / "MAT")
        },
    )

    completed = center._continue_saw(job, run)

    rendered = center.io.output.getvalue()
    assert completed.status == "COMPLETE"
    assert "Working on SAW work unit 1/1: MAT 1" in rendered
    assert "SAW RUN COMPLETE" in rendered
    for internal in (
        "Checking SAW resources for each planned section",
        "Preparing governed SAW task plan",
        "Created SAW ACT",
        "Checking Codex execution readiness",
    ):
        assert internal not in rendered


def test_continue_executes_and_submits_the_same_task_without_second_menu_round_trip(
    make_workspace,
    monkeypatch,
) -> None:
    """A successful provider execution should flow directly into governed submission."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    center = _center(root, [])
    states = iter(("TASK_CREATED", "OUTPUT_READY"))
    launches: list[bool] = []
    submissions: list[Path] = []

    monkeypatch.setattr(
        center,
        "_task_state",
        lambda _path: (next(states), {"operation": "rtc"}),
    )

    def fake_launch(_job, _run, _path, *, pause=True):
        """Record that continuation suppresses the intermediate pause."""
        launches.append(pause)
        return True

    def fake_submit(_job, current, path):
        """Record immediate submission without changing fixture state."""
        submissions.append(path)
        return current

    monkeypatch.setattr(center, "_launch_task", fake_launch)
    monkeypatch.setattr(center, "_submit_task", fake_submit)
    manifest_path = run.root / "tasks" / "unit-1" / "task-manifest.json"

    returned, submitted = center._task_action(job, run, manifest_path)

    assert returned.run_id == run.run_id
    assert submitted is True
    assert launches == [False]
    assert submissions == [manifest_path]


def test_continue_repairs_missing_stc_report_before_closing_finalized_run(
    make_workspace,
    monkeypatch,
) -> None:
    """Continue must publish an already-finalized STC task whose earlier CLI path failed."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="stc", scope="MAT 1")
    manifest_path = run.root / "tasks" / "stc-unit" / "task-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"operation": "stc"}) + "\n", encoding="utf-8")
    validation = manifest_path.parent / "validation"
    validation.mkdir()
    (validation / "submission.json").write_text(
        json.dumps({"status": "FINALIZED"}) + "\n",
        encoding="utf-8",
    )
    run = store.update_run(run, task_manifests=[str(manifest_path)])
    center = _center(root, [""])
    calls: list[Path] = []

    def publish(_job, path):
        """Record deterministic repair publication without compiling a real report."""
        calls.append(path)
        return {"report_directory": str(storage_layout(root).reports_root / job.job_id / "MAT")}

    monkeypatch.setattr(center, "_ensure_stc_task_publication", publish)

    completed = center._continue_saw(job, run)

    assert completed.status == "COMPLETE"
    assert calls == [manifest_path]
    assert "SAGE/localdata/reports" in center.io.output.getvalue()


def test_menu_declares_external_task_paths_at_controller_boundary(make_workspace, monkeypatch) -> None:
    """Menu task commands must use portable governed paths for localdata artifacts."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    center = _center(root, [])
    manifest_path = run.root / "tasks" / "unit-1" / "task-manifest.json"
    commands: list[list[str]] = []

    monkeypatch.setattr(center, "_ensure_codex_execution_transport", lambda: None)

    def capture(_job, arguments):
        """Capture both controller commands without invoking a provider or validator."""
        commands.append(list(arguments))
        if arguments[1] == "execute":
            return {"status": "OUTPUT_READY"}
        return {"status": "FINALIZED"}

    monkeypatch.setattr(center, "controller", capture)

    assert center._launch_task(job, run, manifest_path, pause=False) is True
    center._submit_task(job, run, manifest_path)

    expected = (
        "@jobs/saw/"
        f"{job.job_id}/runs/{run.run_id}/tasks/unit-1/task-manifest.json"
    )
    assert commands == [
        ["task", "execute", "--task", expected, "--dry-run"],
        ["task", "submit", "--task", expected],
    ]


def test_rejected_saw_submission_defers_retry_policy_to_task_boundary(make_workspace, monkeypatch) -> None:
    """A sealed malformed result remains raw until the task-attempt boundary records retry policy."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    center = _center(root, [])
    manifest_path = run.root / "tasks" / "unit-1" / "task-manifest.json"

    def reject(_job, _arguments):
        """Simulate deterministic findings validation rejecting sealed provider output."""
        raise ValidationError("SAW findings operation does not match the ACT task")

    monkeypatch.setattr(center, "controller", reject)

    with pytest.raises(ValidationError) as caught:
        center._submit_task(job, run, manifest_path)

    assert caught.value.message == "SAW findings operation does not match the ACT task"
    assert caught.value.next_action is None


def test_restart_run_preserves_old_outputs_and_recreates_operator_request(make_workspace) -> None:
    """Reset abandons no data and carries the exact scope and check settings forward."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(
        job,
        operation="focused",
        scope="MAT 1:1-2",
        focus="Is participant reference clear?",
        check_type="PARTICIPANT_REFERENCE",
    )
    retained = run.root / "diagnostics" / "retained.txt"
    retained.write_text("keep", encoding="utf-8")

    replacement = store.restart_run(job, run)

    abandoned = store.load_run(job, run.run_id)
    assert abandoned.status == "ABANDONED"
    assert retained.read_text(encoding="utf-8") == "keep"
    assert replacement.run_id != run.run_id
    assert replacement.operation == run.operation
    assert replacement.scope == run.scope
    assert replacement.focus == run.focus
    assert replacement.check_type == run.check_type
    assert store.active_run(job).run_id == replacement.run_id


def test_restart_menu_action_explains_preservation_and_activates_replacement(
    make_workspace,
    monkeypatch,
) -> None:
    """The operator-facing reset action is explicit, confirmed, and recoverable."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    center = _center(root, ["y"])
    monkeypatch.setattr(center, "ensure_initialized", lambda _job: {"state": "READY"})

    replacement = center._restart_run_with_current_configuration(job, run)

    assert replacement is not None
    assert center.store.load_run(job, run.run_id).status == "ABANDONED"
    assert center.store.active_run(job).run_id == replacement.run_id
    rendered = center.io.output.getvalue()
    assert "Existing tasks and outputs will remain available" in rendered
    assert "Created replacement Run" in rendered


def test_ai_recommended_settings_are_reported_as_status(make_workspace) -> None:
    """Exact per-Skill routes are rendered as provider-neutral informational status."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = _center(root, [])

    class Service:
        """Minimal model-service fixture for recommendation status."""

        def skill_routes(self):
            """Return one exact current Skill route."""
            return {
                "status": "READY",
                "routing_mode": "AUTOMATIC",
                "ready_skills": 1,
                "total_skills": 1,
                "skills": [{
                    "skill_id": "saw-rtc",
                    "provider": "codex",
                    "model_id": "gpt-5.6-terra",
                    "reasoning_id": "medium",
                    "availability": "AVAILABLE",
                    "qualification": "RECOMMENDED",
                }],
            }

    center._model_show_recommendation_status(Service())
    rendered = center.io.output.getvalue()
    assert "Routing mode: AUTOMATIC" in rendered
    assert "SKILL" in rendered and "PROVIDER" in rendered and "REASONING" in rendered
    assert "saw-rtc" in rendered
    assert "gpt-5.6-terra" in rendered
    assert "medium" in rendered
    assert "RECOMMENDED" in rendered


def test_codex_transport_preflight_fails_fast_with_network_diagnostic(make_workspace, monkeypatch) -> None:
    """A stalled sampling connection must fail before a governed task waits for the full provider timeout."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([]), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=False,
    )

    class FakeService:
        """Simulate a Codex service whose sampling transport stalls."""

        def __init__(self, _root):
            """Accept the normal ModelService root argument."""

        def settings(self):
            """Report Codex as the selected governed provider."""
            return {"selected_provider": "codex", "providers": {"codex": {}}}

        def readiness_check(self):
            """Fail the non-generative runtime readiness check."""
            raise ValidationError(
                "Codex is not ready",
                code="LLM_PROVIDER_NOT_READY",
            )

    monkeypatch.setattr("sage.menu.ModelService", FakeService)
    with pytest.raises(ValidationError) as caught:
        center._ensure_codex_execution_transport()  # noqa: SLF001 - governed transport contract

    assert caught.value.code == "CODEX_EXECUTION_NOT_READY"
    assert "not ready" in caught.value.message
    assert "Check LLM connection" in (caught.value.next_action or "")


def test_codex_transport_preflight_is_cached_for_partitioned_work(make_workspace, monkeypatch) -> None:
    """One successful execution probe should cover adjacent partitioned work units for ten minutes."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([]), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=False,
    )
    calls = []

    class FakeService:
        """Simulate a healthy Codex service for probe-cache verification."""

        def __init__(self, _root):
            """Accept the normal ModelService root argument."""

        def settings(self):
            """Report Codex as the selected governed provider."""
            return {"selected_provider": "codex", "providers": {"codex": {}}}

        def readiness_check(self):
            """Record one successful non-generative readiness check."""
            calls.append(True)
            return {"status": "READY"}

    monkeypatch.setattr("sage.menu.ModelService", FakeService)
    center._ensure_codex_execution_transport()  # noqa: SLF001
    center._ensure_codex_execution_transport()  # noqa: SLF001
    assert calls == [True]


def test_controller_child_forces_utf8_json_transport(make_workspace, monkeypatch) -> None:
    """Controller subprocesses exchange Unicode JSON through explicit UTF-8 pipes on Windows and POSIX."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    center = _center(root, [])
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        """Capture the controller subprocess options and return one Unicode JSON response."""
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout='{"text":"Українська"}', stderr="")

    monkeypatch.setattr(center.store, "ensure_runtime_files", lambda _job: job.runtime_settings_path)
    monkeypatch.setattr("sage.menu.subprocess.run", fake_run)
    payload = center.controller(job, ["workspace", "status"])

    assert payload["text"] == "Українська"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "strict"
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


def test_working_spinner_is_visible_for_non_tty_output() -> None:
    """Bounded post-registration work must show an immediate working indicator in captured output."""
    output = io.StringIO()
    menu = MenuIO(input_func=ScriptedInput([]), output=output)

    with menu.working("Working - checking language competency"):
        pass

    assert "Working - checking language competency..." in output.getvalue()
