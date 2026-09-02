"""Parent-process, setup independence, and escape-path UX contracts."""

from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from sage.storage import storage_layout
from sage.executors.codex_cli import CodexCLIExecutor
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.jobs import JobStore
from sage.hashing import sha256_file
from sage.registry import load_ecosystem
from sage.resource_mounts import set_project_root
from sage.state import ecosystem_state_path


def _center(root: Path, inputs: list[str]) -> SageControlCenter:
    """Build one deterministic control center for current UI contracts."""
    return SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(inputs), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )


def test_unix_codex_install_is_noninteractive_and_never_launches_bare_codex(monkeypatch, tmp_path: Path) -> None:
    """Verify SAGE suppresses the installer TUI launch and accepts a verified installed binary."""
    home = tmp_path / "home"
    installed = home / ".local" / "bin" / "codex"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("SAGE_CODEX_COMMAND", raising=False)

    def fake_which(name: str) -> str | None:
        """Expose installer prerequisites but keep Codex off the current shell PATH."""
        if name == "curl":
            return "/usr/system/bin/curl"
        if name == "sh":
            return "/system/bin/sh"
        if name == "codex":
            return None
        return None

    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(args, **kwargs):
        """Simulate install success followed by the legacy post-install nonzero status."""
        argv = [str(item) for item in args]
        env = dict(kwargs.get("env") or {})
        calls.append((argv, env))
        if argv[:2] == ["/system/bin/sh", "-c"]:
            installed.parent.mkdir(parents=True, exist_ok=True)
            installed.write_text("fake codex", encoding="utf-8")
            return subprocess.CompletedProcess(args, 1, stdout="installed successfully", stderr="")
        if argv == [str(installed), "--version"]:
            return subprocess.CompletedProcess(args, 0, stdout="codex-cli 0.147.0\n", stderr="")
        if argv == [str(installed), "login", "status"]:
            return subprocess.CompletedProcess(args, 0, stdout="Logged in using ChatGPT\n", stderr="")
        if argv == [str(installed)]:
            raise AssertionError("SAGE must never launch the interactive Codex TUI during installation")
        raise AssertionError(f"Unexpected subprocess: {argv}")

    monkeypatch.setattr("sage.executors.codex_cli.shutil.which", fake_which)
    monkeypatch.setattr("sage.executors.codex_cli.subprocess.run", fake_run)
    executor = CodexCLIExecutor()
    status = executor.install()

    assert status.version == "codex-cli 0.147.0"
    assert status.ready is True
    assert calls[0][1]["CODEX_NON_INTERACTIVE"] == "1"
    assert os.environ["SAGE_CODEX_COMMAND"] == str(installed)
    assert all(argv != [str(installed)] for argv, _ in calls)


def test_one_configured_workflow_is_enough_for_setup_completion(make_workspace) -> None:
    """Verify BIC and SAW are independent and setup does not require both workflow bindings."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_project_root(root, project_root=storage_layout(root).projects_root)
    store = JobStore(root, root / "ecosystem.yml")
    jobs = store.bootstrap_default_jobs()
    bic = next(job for job in jobs if job.tool == "bic")
    store.set_active_job("saw", None)
    center = _center(root, [])

    next_step, label = center._setup_next_step(  # noqa: SLF001 - setup contract
        {"available": True, "ready": True},
        {"bic"},
        {bic.job_id: {"status": "READY"}},
    )

    assert center._setup_configured_tools() == {"bic"}  # noqa: SLF001
    assert next_step == "COMPLETE"
    assert label == "SAGE is ready"


def test_startup_reconciles_stale_setup_summary_from_live_job_receipt(make_workspace) -> None:
    """A ready active Job must not reopen Setup because its cached summary is stale."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_project_root(root, project_root=storage_layout(root).projects_root)
    store = JobStore(root, root / "ecosystem.yml")
    jobs = store.bootstrap_default_jobs()
    saw = next(job for job in jobs if job.tool == "saw")
    store.set_active_job("bic", None)
    store.set_active_job("saw", saw.job_id)
    runtime_path = store.ensure_runtime_files(saw)
    runtime = load_ecosystem(runtime_path)
    state_path = ecosystem_state_path(runtime.runtime_state_root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state": "READY_WITH_ACTIONS",
                "settings_sha256": sha256_file(runtime_path),
                "operator_overrides_sha256": None,
            }
        ),
        encoding="utf-8",
    )
    store.write_setup_state(
        {
            "status": "INCOMPLETE",
            "next_step": "VALIDATE",
            "next_label": "Manage active Jobs",
            "llm": {"available": True, "ready": True},
            "initialization": {},
            "scripture_resources": {"status": "READY"},
        }
    )
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        dry_run_provider=True,
    )

    assert center.setup_required({"available": True, "ready": True}) is False
    receipt = store.setup_state()
    assert receipt is not None
    assert receipt["status"] == "COMPLETE"
    assert receipt["next_step"] == "COMPLETE"
    assert receipt["initialization"][saw.job_id]["status"] == "READY_WITH_ACTIONS"


def test_uninitialized_active_job_starts_at_main_and_defers_validation_to_workflow(make_workspace) -> None:
    """Job validation needed is visible state, not a reason to replace Main with Manage Jobs."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_project_root(root, project_root=storage_layout(root).projects_root)
    store = JobStore(root, root / "ecosystem.yml")
    saw = next(job for job in store.bootstrap_default_jobs() if job.tool == "saw")
    store.set_active_job("bic", None)
    store.set_active_job("saw", saw.job_id)
    store.write_setup_state(
        {
            "status": "INCOMPLETE",
            "next_step": "VALIDATE",
            "next_label": "Manage active Jobs",
            "llm": {"available": True, "ready": True},
            "initialization": {},
            "scripture_resources": {"status": "READY"},
        }
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["c"]), output=output),
        dry_run_provider=True,
    )

    snapshot = center.ui_service.startup_readiness({"available": True, "ready": True})
    assert snapshot["status"] == "READY"
    assert snapshot["requires_setup"] is False
    assert snapshot["next_step"] == "VALIDATE"
    assert center.run() == 0
    rendered = output.getvalue()
    assert "MAIN MENU" in rendered
    assert "MANAGE JOBS" not in rendered


def test_startup_reports_stale_active_job_pointer_as_recoverable(make_workspace) -> None:
    """A missing Job manifest must produce an actionable startup report, not a late crash."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_project_root(root, project_root=storage_layout(root).projects_root)
    store = JobStore(root, root / "ecosystem.yml")
    store.active_jobs_path.parent.mkdir(parents=True, exist_ok=True)
    store.active_jobs_path.write_text(
        '{"schema_version":"1.0","bic":null,"saw":"SAW_missing-usREF"}\n',
        encoding="utf-8",
    )
    center = _center(root, [])

    snapshot = center.ui_service.startup_readiness({"available": True, "ready": True})
    center._render_startup_report({"available": True, "ready": True})  # noqa: SLF001

    assert snapshot["status"] == "INCOMPLETE"
    assert snapshot["requires_setup"] is True
    assert snapshot["next_step"] == "RECOVER_ACTIVE_JOB_POINTERS"
    assert "Job state                ACTION NEEDED - SAW SAW_missing-usREF [manifest missing]" in center.io.output.getvalue()
    assert "Reason code              ACTIVE_JOB_POINTER_STALE" in center.io.output.getvalue()
    assert "Overall                  INCOMPLETE" in center.io.output.getvalue()


def test_missing_projects_root_prevents_setup_completion(make_workspace) -> None:
    """A clean empty inventory must not hide an unconfigured workstation Projects root."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    jobs = store.bootstrap_default_jobs()
    bic = next(job for job in jobs if job.tool == "bic")
    store.set_active_job("saw", None)
    store.write_setup_state({"status": "COMPLETE", "next_step": "COMPLETE"})
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        dry_run_provider=True,
    )

    assert center.setup_required({"available": True, "ready": True}) is True
    next_step, label = center._setup_next_step(  # noqa: SLF001 - setup contract
        {"available": True, "ready": True},
        {"bic"},
        {bic.job_id: {"status": "READY"}},
        {"status": "READY_EMPTY", "projects_root": None},
    )
    assert next_step == "CONFIGURE_PROJECT_ROOT"
    assert label == "Configure Paratext Projects root"


def test_complete_system_check_is_incomplete_without_projects_root(make_workspace, monkeypatch) -> None:
    """The complete diagnostic must never report overall readiness without the required root."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = _center(root, ["6", "a"])
    monkeypatch.setattr(
        center,
        "_setup_model_probe",
        lambda _service, **_kwargs: {"available": True, "ready": True},
    )
    monkeypatch.setattr(
        "sage.menu.validate_original_language_resources",
        lambda _root: {"status": "READY", "resources": []},
    )
    monkeypatch.setattr(
        center.ollama_admin,
        "status",
        lambda: SimpleNamespace(ready=False),
    )

    center.system_diagnostics_menu()

    rendered = center.io.output.getvalue()
    assert "Paratext Projects root    NOT CONFIGURED" in rendered
    assert "Overall                  INCOMPLETE" in rendered
    assert "PROJECTS_ROOT_NOT_CONFIGURED" in rendered


def test_guided_setup_has_system_autosave_and_exit_paths(make_workspace, monkeypatch) -> None:
    """Verify setup exposes configuration, auto-persisted Main return, and full-exit paths."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["7"]), output=output),
        dry_run_provider=True,
    )
    monkeypatch.setattr(
        center,
        "_setup_model_probe",
        lambda service, **_kwargs: {"available": True, "ready": True, "auth_mode": "CHATGPT", "version": "codex-cli 0.147.0"},
    )

    assert center.guided_setup(pause_at_end=False) is False
    rendered = output.getvalue()
    assert "BIC jobs" in rendered
    assert "RTC jobs" in rendered
    assert "STC jobs" in rendered
    assert "SAGE Maintenance" in rendered
    assert "Setup options" not in rendered
    assert "B. Main Menu   C. Exit SAGE" in rendered
    assert "D. Language   E. Help   F. Status" in rendered
    assert "Save and return" not in rendered


def test_system_configuration_has_back_main_and_exit_routes(make_workspace) -> None:
    """Verify the permanent system menu can always return, go to main, or exit SAGE."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    for selection, expected in (("A", "BACK"), ("B", "MAIN"), ("C", "EXIT")):
        center = _center(root, [selection])
        assert center.system_configuration_menu() == expected
        rendered = center.io.output.getvalue()
        assert "A. Back   B. Main Menu   C. Exit SAGE" in rendered
        assert "D. Language   E. Help   F. Status" in rendered


def test_windows_codex_install_is_noninteractive_and_returns_to_sage(monkeypatch, tmp_path: Path) -> None:
    """Verify the Windows standalone installer also suppresses the Codex TUI and verifies the binary."""
    local_app_data = tmp_path / "LocalAppData"
    installed = local_app_data / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setenv("PATH", "C:\\Windows\\System32")
    monkeypatch.delenv("SAGE_CODEX_COMMAND", raising=False)
    monkeypatch.setattr(CodexCLIExecutor, "_is_windows", staticmethod(lambda: True))

    def fake_which(name: str) -> str | None:
        """Expose PowerShell while keeping Codex off the current shell PATH."""
        if name in {"powershell", "pwsh"}:
            return "powershell.exe"
        if name == "codex":
            return None
        return None

    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(args, **kwargs):
        """Simulate the standalone PowerShell installer and subsequent binary verification."""
        argv = [str(item) for item in args]
        env = dict(kwargs.get("env") or {})
        calls.append((argv, env))
        if argv and argv[0] == "powershell.exe":
            installed.parent.mkdir(parents=True, exist_ok=True)
            installed.write_text("fake codex", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, stdout="installed successfully", stderr="")
        if argv == [str(installed), "--version"]:
            return subprocess.CompletedProcess(args, 0, stdout="codex-cli 0.147.0\n", stderr="")
        if argv == [str(installed), "login", "status"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="Not logged in")
        if argv == [str(installed)]:
            raise AssertionError("SAGE must never launch the interactive Codex TUI during installation")
        raise AssertionError(f"Unexpected subprocess: {argv}")

    monkeypatch.setattr("sage.executors.codex_cli.shutil.which", fake_which)
    monkeypatch.setattr("sage.executors.codex_cli.subprocess.run", fake_run)
    executor = CodexCLIExecutor()
    status = executor.install()

    assert status.version == "codex-cli 0.147.0"
    assert status.ready is False
    assert calls[0][1]["CODEX_NON_INTERACTIVE"] == "1"
    assert calls[0][1]["OS"] == "Windows_NT"
    assert "-NonInteractive" in calls[0][0]
    assert "https://chatgpt.com/codex/install.ps1" in calls[0][0][-1]
    assert os.environ["SAGE_CODEX_COMMAND"] == str(installed)
    assert all(argv != [str(installed)] for argv, _ in calls)


def test_chatgpt_connection_runs_login_not_codex_tui(monkeypatch, tmp_path: Path) -> None:
    """Verify ChatGPT authentication starts only the Codex login subcommand and returns to SAGE."""
    codex = tmp_path / "codex"
    codex.write_text("fake", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        """Record login/status calls while rejecting a bare interactive Codex invocation."""
        argv = [str(item) for item in args]
        calls.append(argv)
        if argv == [str(codex), "login"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if argv == [str(codex), "--version"]:
            return subprocess.CompletedProcess(args, 0, stdout="codex-cli 0.147.0\n", stderr="")
        if argv == [str(codex), "login", "status"]:
            return subprocess.CompletedProcess(args, 0, stdout="Logged in using ChatGPT\n", stderr="")
        if argv == [str(codex)]:
            raise AssertionError("SAGE must not enter the Codex interactive TUI")
        raise AssertionError(f"Unexpected subprocess: {argv}")

    monkeypatch.setattr("sage.executors.codex_cli.subprocess.run", fake_run)
    executor = CodexCLIExecutor(command=str(codex))
    monkeypatch.setattr(executor, "status", executor.quick_status)
    status = executor.connect_chatgpt()

    assert status.ready is True
    assert calls[0] == [str(codex), "login"]
    assert [str(codex)] not in calls


def test_live_ai_probe_records_actual_model_and_reasoning_in_one_canonical_status(make_workspace) -> None:
    """Startup/AI Setup consume the same live provider result rather than configured labels."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
    )

    class FakeService:
        """Provide deterministic live AI-status responses for startup reporting."""

        def quick_codex_status(self):
            """Return an authenticated provider status."""
            return {
                "available": True,
                "ready": True,
                "auth_mode": "CHATGPT",
                "version": "codex-cli test",
                "diagnostic": "ready",
            }

        def readiness_check(self):
            """Return selected model/reasoning without simulating model generation."""
            return {"provider": "codex", "model": "gpt-test-live", "reasoning_effort": "high"}

        def settings(self):
            """Return the configured provider selection used by the probe."""
            return {"selected_provider": "codex", "providers": {"codex": {}}}

    service = FakeService()
    row = center._setup_model_probe(service, refresh=True)  # noqa: SLF001 - canonical startup contract
    assert row["connection"] == "READY"
    assert row["provider"] == "OpenAI / ChatGPT"
    assert row["model"] == "gpt-test-live"
    assert row["reasoning_level"] == "HIGH"
    assert row == center.runtime_status.ai.to_dict()

    center._write_ai_status(center.runtime_status.ai.to_dict())  # noqa: SLF001 - shared rendering contract
    rendered = output.getvalue()
    assert "Model                    gpt-test-live" in rendered
    assert "Reasoning level          HIGH" in rendered


def test_ai_prerequisite_blocks_main_menu_escape_during_guided_setup(make_workspace, monkeypatch) -> None:
    """Neither Continue nor the global Main hotkey may bypass a failed workflow-AI prerequisite."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["n", "7", "", "b", "", "c"]), output=output),
    )
    blocked = {
        "available": True,
        "ready": False,
        "connection": "ACTION NEEDED",
        "provider": "OpenAI / ChatGPT",
        "model": None,
        "reasoning_level": None,
        "prerequisite_status": "BLOCKED",
        "reason_code": "AI_CONNECTION_FAILED",
        "diagnostic": "offline",
    }
    monkeypatch.setattr(center, "_setup_model_probe", lambda _service, **_kwargs: dict(blocked))

    assert center.guided_setup(pause_at_end=False) is True
    rendered = output.getvalue()
    assert rendered.count("AI prerequisite: BLOCKED") >= 2
    assert "required before entering the Main Menu" in rendered
