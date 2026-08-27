"""RC1 execution disposition, Job-layout migration, and Windows Codex contracts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from sage.storage import storage_layout
from sage.errors import ValidationError
from sage.execution_events import classify_exception, record_exception_event
from sage.executors.codex_cli import CodexCLIExecutor
from sage.job_layout import audit_job_layout, migrate_job_layout, write_job_layout_audit
from sage.task_retry import archive_rejected_task_output
from sage.cli import _configure_utf8_standard_streams, command_launcher_shortcut


def _job_tree(root: Path) -> tuple[Path, Path]:
    """Create one minimal canonical SAW Job/Run tree for storage-maintenance tests."""
    job = storage_layout(root, create=True).jobs_root / "saw" / "SAW_fixture"
    run = job / "runs" / "SAW_fixture-20260818-001"
    (job / ".sage" / "state").mkdir(parents=True)
    for name in ("reports", "exports", "runs"):
        (job / name).mkdir(exist_ok=True)
    (job / "job.yml").write_text("schema_version: '1.0'\njob_id: SAW_fixture\ntool: saw\n", encoding="utf-8")
    for name in ("tasks", "plans", "reports", "decisions", "findings"):
        (run / name).mkdir(parents=True, exist_ok=True)
    (run / "run.json").write_text('{"schema_version":"1.0"}', encoding="utf-8")
    return job, run


def test_execution_event_dispositions_are_boundary_specific(tmp_path: Path) -> None:
    """Provider and task-output failures pause/reject narrowly while real scope defects block."""
    provider = ValidationError("offline", code="CODEX_EXECUTION_CONNECTION_FAILED")
    output = ValidationError("bad provider result", code="VALIDATION_ERROR")
    scope = ValidationError("missing source", code="SCRIPTURE_NOT_FOUND")
    assert classify_exception(provider) == ("TASK_PAUSED", "TASK_ATTEMPT", "RETRY_SAME_TASK")
    assert classify_exception(output)[0] == "ERROR"
    assert classify_exception(output, boundary_hint="TASK_ATTEMPT") == (
        "ERROR",
        "TASK_ATTEMPT",
        "DEVELOPER_REVIEW",
    )
    contract = ValidationError("sealed evidence mismatch", code="SAW_TASK_CONTRACT_INVALID")
    assert classify_exception(contract, boundary_hint="TASK_ATTEMPT") == (
        "STALE",
        "STAGE",
        "REBUILD_AFFECTED_STAGE",
    )
    assert classify_exception(scope)[0:2] == ("BLOCKED", "WORK_UNIT")


def test_execution_event_persists_sanitized_jsonl_and_markdown(tmp_path: Path) -> None:
    """Every execution-affecting event gets durable machine and human evidence without secrets."""
    sage_root = tmp_path / "SAGE" / "app"
    sage_root.mkdir(parents=True)
    job, run = _job_tree(sage_root)
    exc = ValidationError(
        "Codex sampling connection failed",
        code="CODEX_EXECUTION_CONNECTION_FAILED",
        next_action="Check network and retry the same task.",
        details={"API_KEY": "secret", "diagnostic": "connection refused"},
    )
    event = record_exception_event(
        sage_root,
        exc,
        workflow="saw",
        job_id=job.name,
        run_id=run.name,
        task_id="task-001",
        work_unit_scope="JUD 1-25",
        run_root=run,
    )
    assert event["disposition"] == "TASK_PAUSED"
    payload = (run / "diagnostics" / "EXECUTION-EVENTS.jsonl").read_text(encoding="utf-8")
    assert "secret" not in payload
    assert "[redacted]" in payload
    report = (run / "diagnostics" / "BLOCK-REPORT.md").read_text(encoding="utf-8")
    assert "Task Paused" in report
    assert "CODEX_EXECUTION_CONNECTION_FAILED" in report
    assert "JUD 1-25" in report


def test_rejected_task_output_is_archived_for_same_task_retry(tmp_path: Path) -> None:
    """Rejected provider output is evidence-preserved while the sealed task becomes retryable."""
    task = tmp_path / "task"
    (task / "output").mkdir(parents=True)
    (task / "validation").mkdir()
    manifest = task / "task.json"
    manifest.write_text('{"task_id":"task-1"}', encoding="utf-8")
    (task / "output" / "findings.json").write_text('{"bad":true}', encoding="utf-8")
    (task / "validation" / "llm-execution-receipt.json").write_text('{"provider":"codex"}', encoding="utf-8")
    receipt = archive_rejected_task_output(
        manifest,
        reason_code="VALIDATION_ERROR",
        message="invalid provider output",
        event_id="EVT-1",
    )
    attempt = Path(receipt["attempt_path"])
    assert (attempt / "output" / "findings.json").is_file()
    assert (attempt / "validation" / "llm-execution-receipt.json").is_file()
    assert list((task / "output").iterdir()) == []
    assert json.loads((attempt / "attempt-receipt.json").read_text(encoding="utf-8"))["event_id"] == "EVT-1"


def test_job_layout_audit_hash_is_stable_and_migration_is_dry_run_first(tmp_path: Path) -> None:
    """Legacy cleanup is reproducible, dry-run-first, and leaves unknown non-empty paths untouched."""
    sage_root = tmp_path / "SAGE" / "app"
    sage_root.mkdir(parents=True)
    job, run = _job_tree(sage_root)
    (job / "archive").mkdir()
    (job / ".sage" / "workspace_data").mkdir()
    (run / "operator-note-text").mkdir()
    legacy = run / "reports" / "ACTION-REPORT.md"
    legacy.write_text("legacy report\n", encoding="utf-8")
    unknown = job / "old-custom"
    unknown.mkdir()
    (unknown / "keep.txt").write_text("preserve", encoding="utf-8")

    first = audit_job_layout(sage_root)
    second = audit_job_layout(sage_root)
    assert first["audit_sha256"] == second["audit_sha256"]
    written = write_job_layout_audit(sage_root)
    audit_path = Path(written["json_path"])
    dry = migrate_job_layout(sage_root, audit_path, apply=False)
    assert dry["status"] == "DRY_RUN"
    assert legacy.is_file()
    assert unknown.is_dir()

    applied = migrate_job_layout(sage_root, audit_path, apply=True)
    assert applied["status"] == "MIGRATED"
    assert not (job / "archive").exists()
    assert not (job / ".sage" / "workspace_data").exists()
    assert not (run / "operator-note-text").exists()
    assert not legacy.exists()
    assert (storage_layout(sage_root).diagnostics_root / "legacy-reports" / "work__jobs__saw__SAW_fixture__runs__SAW_fixture-20260818-001__reports__ACTION-REPORT.md").is_file()
    assert (unknown / "keep.txt").read_text(encoding="utf-8") == "preserve"


def test_windows_prefers_official_standalone_codex_over_path_shim(monkeypatch, tmp_path: Path) -> None:
    """A legacy npm codex.cmd must not win PATH order over the official standalone codex.exe."""
    local = tmp_path / "LocalAppData"
    standalone = local / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
    standalone.parent.mkdir(parents=True)
    standalone.write_text("fake", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("SAGE_CODEX_COMMAND", raising=False)
    monkeypatch.setattr(CodexCLIExecutor, "_is_windows", staticmethod(lambda: True))
    monkeypatch.setattr("sage.executors.codex_cli.shutil.which", lambda name: r"C:\\npm\\codex.cmd" if name == "codex" else None)
    assert CodexCLIExecutor().command == str(standalone)


def test_windows_legacy_codex_cmd_is_wrapped_by_comspec(monkeypatch) -> None:
    """Explicit legacy cmd/bat Codex commands remain executable without shell=True."""
    monkeypatch.setattr(CodexCLIExecutor, "_is_windows", staticmethod(lambda: True))
    monkeypatch.setenv("COMSPEC", r"C:\\Windows\\System32\\cmd.exe")
    executor = CodexCLIExecutor(command=r"C:\\npm\\codex.cmd")
    argv = executor._command_argv(["login", "status"])  # noqa: SLF001 - Windows subprocess contract
    assert argv == [
        r"C:\\Windows\\System32\\cmd.exe",
        "/d",
        "/c",
        "call",
        r"C:\\npm\\codex.cmd",
        "login",
        "status",
    ]


def test_windows_quoted_codex_cmd_is_normalized_before_comspec_launch(monkeypatch) -> None:
    """Persisted/discovered quote characters must not become part of the cmd command token."""
    monkeypatch.setattr(CodexCLIExecutor, "_is_windows", staticmethod(lambda: True))
    monkeypatch.setenv("COMSPEC", r"C:\\Windows\\System32\\cmd.exe")
    executor = CodexCLIExecutor(command='"C:\\Users\\Test User\\AppData\\Local\\Programs\\OpenAI\\Codex\\bin\\codex.CMD"')
    assert executor.command == r"C:\Users\Test User\AppData\Local\Programs\OpenAI\Codex\bin\codex.CMD"
    argv = executor._command_argv(["login"])  # noqa: SLF001 - Windows subprocess contract
    assert argv == [
        r"C:\\Windows\\System32\\cmd.exe",
        "/d",
        "/c",
        "call",
        r"C:\Users\Test User\AppData\Local\Programs\OpenAI\Codex\bin\codex.CMD",
        "login",
    ]
    rendered = subprocess.list2cmdline(argv)
    assert r'\"C:\\Users' not in rendered


def test_windows_quoted_codex_cmd_browser_login_uses_call_wrapper(monkeypatch) -> None:
    """Interactive ChatGPT sign-in must launch a legacy/alternate Codex CMD shim safely."""
    monkeypatch.setattr(CodexCLIExecutor, "_is_windows", staticmethod(lambda: True))
    monkeypatch.setenv("COMSPEC", r"C:\\Windows\\System32\\cmd.exe")
    executor = CodexCLIExecutor(command='"C:\\Users\\Test User\\AppData\\Local\\Programs\\OpenAI\\Codex\\bin\\codex.CMD"')
    calls = []

    def fake_run(args, **_kwargs):
        """Capture the Windows login argv without starting the real Codex CLI."""
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(executor, "status", lambda: type("Status", (), {"ready": True, "auth_mode": "CHATGPT"})())
    executor.connect_chatgpt()
    assert calls[0] == [
        r"C:\\Windows\\System32\\cmd.exe",
        "/d",
        "/c",
        "call",
        r"C:\Users\Test User\AppData\Local\Programs\OpenAI\Codex\bin\codex.CMD",
        "login",
    ]


def test_windows_codex_environment_synthesizes_identity_without_api_keys(monkeypatch) -> None:
    """The minimized Windows environment keeps platform/proxy data and still excludes API credentials."""
    monkeypatch.setattr(CodexCLIExecutor, "_is_windows", staticmethod(lambda: True))
    monkeypatch.delenv("OS", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    env = CodexCLIExecutor._environment()  # noqa: SLF001 - subprocess environment contract
    assert env["OS"] == "Windows_NT"
    assert env["HTTPS_PROXY"] == "http://proxy.example:8080"
    assert "OPENAI_API_KEY" not in env


def test_governed_codex_uses_file_backed_output_and_process_cleanup(monkeypatch, tmp_path: Path) -> None:
    """Governed execution avoids inherited stdout/stderr pipes and returns captured diagnostics."""
    executor = CodexCLIExecutor(command="codex")
    calls: dict[str, object] = {}

    class FakeProcess:
        """Stand-in Popen object for asserting governed Windows-safe file-backed execution."""
        returncode = 0
        pid = 123
        stdin = None
        def __init__(self, argv, **kwargs):
            """Capture subprocess arguments and redirected file handles for the fake process."""
            calls["argv"] = argv
            calls["stdout"] = kwargs["stdout"]
            calls["stderr"] = kwargs["stderr"]
            calls["encoding"] = kwargs.get("encoding")
            calls["errors"] = kwargs.get("errors")
        def communicate(self, input=None, timeout=None):
            """Simulate one successful governed Codex exchange into redirected output files."""
            calls["input"] = input
            calls["timeout"] = timeout
            calls["stdout"].write("ok-out")
            calls["stderr"].write("ok-err")
            return (None, None)
        def poll(self):
            """Report the deterministic completed status used by cleanup assertions."""
            return self.returncode

    monkeypatch.setattr("sage.executors.codex_cli.subprocess.Popen", FakeProcess)
    completed = executor._run_governed(["exec", "-"], timeout=12, input_text="sealed", cwd=tmp_path)  # noqa: SLF001
    assert completed.returncode == 0
    assert completed.stdout == "ok-out"
    assert completed.stderr == "ok-err"
    assert calls["input"] == "sealed"
    assert calls["timeout"] == 12
    assert calls["encoding"] == "utf-8"
    assert calls["errors"] == "strict"
    assert hasattr(calls["stdout"], "write") and hasattr(calls["stderr"], "write")


def test_codex_text_run_forces_utf8_for_unicode_stdin(monkeypatch) -> None:
    """Codex text-mode subprocesses never inherit a Windows legacy code page."""
    executor = CodexCLIExecutor(command="codex")
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        """Capture the text transport contract without starting a provider process."""
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="OK", stderr="")

    monkeypatch.setattr("sage.executors.codex_cli.subprocess.run", fake_run)
    completed = executor._run(["exec", "-"], input_text="Проаналізуй")  # noqa: SLF001

    assert completed.returncode == 0
    assert captured["input"] == "Проаналізуй"
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "strict"


def test_governed_codex_rejects_invalid_unicode_before_child_start(monkeypatch, tmp_path: Path) -> None:
    """Malformed Unicode fails synchronously instead of leaving Codex waiting on stdin."""
    executor = CodexCLIExecutor(command="codex")
    started = False

    def fake_popen(*_args, **_kwargs):
        """Record any forbidden child-process start during invalid-Unicode validation."""
        nonlocal started
        started = True
        raise AssertionError("Codex child must not start for invalid UTF-8 input")

    monkeypatch.setattr("sage.executors.codex_cli.subprocess.Popen", fake_popen)
    with pytest.raises(UnicodeEncodeError):
        executor._run_governed(  # noqa: SLF001
            ["exec", "-"],
            timeout=12,
            input_text="\ud800",
            cwd=tmp_path,
        )
    assert started is False


def test_windows_workflow_launcher_preserves_shifted_arguments_in_python(monkeypatch) -> None:
    """Windows BIC/SAW wrappers hand raw argv to Python so batch SHIFT cannot duplicate the original arguments."""
    captured: dict[str, object] = {}

    def fake_route(routed: argparse.Namespace) -> int:
        """Capture the canonical launcher namespace without executing a workflow command."""
        captured.update(vars(routed))
        return 0

    monkeypatch.setattr("sage.cli.command_shortcut", fake_route)
    args = argparse.Namespace(
        workflow_id="saw",
        arguments=[
            "--", "--settings", r"C:\SAGE Work\ecosystem.yml", "--json", "--debug",
            "qa", "--wip", "ukrNPUv1", "--reference", "usNASB", "--scope", "JUD 1:1-25",
        ],
        settings="ecosystem.yml",
        json=False,
        no_prompt=False,
    )
    assert command_launcher_shortcut(args) == 0
    assert captured["settings"] == r"C:\SAGE Work\ecosystem.yml"
    assert captured["shortcut_command"] == "qa"
    assert captured["arguments"] == [
        "--wip", "ukrNPUv1", "--reference", "usNASB", "--scope", "JUD 1:1-25",
    ]
    assert captured["json"] is True
    assert captured["debug"] is True


def test_windows_bic_saw_batch_wrappers_do_not_parse_with_shift(package_root: Path) -> None:
    """Windows workflow wrappers must pass untouched argv to Python instead of mixing SHIFT with percent-star expansion."""
    for name, workflow in (("bic.cmd", "bic"), ("saw.cmd", "saw")):
        text = (package_root / "system" / "bin" / name).read_text(encoding="utf-8").casefold()
        assert "shift" not in text
        assert f"launcher-shortcut --workflow {workflow} -- %*" in text

from sage.bounded_target import preflight_bounded_target_commit


def test_bic_target_commit_preflight_blocks_uncommittable_shape_before_provider() -> None:
    """BIC detects deterministic TARGET bridge/shape impossibility before spending a provider call."""
    source = "\\id MAT\n\\c 1\n\\v 1 one\n\\v 2 two\n"
    target = "\\id MAT\n\\c 1\n\\v 1-2 existing bridge\n"
    with pytest.raises(ValidationError) as caught:
        preflight_bounded_target_commit(target, source, "MAT 1:1-2")
    assert caught.value.code == "TARGET_SCOPE_VERSE_SHAPE_MISMATCH"


def test_bic_target_commit_preflight_allows_missing_ordinary_verse_in_existing_chapter() -> None:
    """An ordinary missing verse remains insertable and must not be over-blocked."""
    source = "\\id MAT\n\\c 1\n\\v 1 one\n\\v 2 two\n"
    target = "\\id MAT\n\\c 1\n\\v 1 existing\n"
    result = preflight_bounded_target_commit(target, source, "MAT 1:1-2")
    assert result["status"] == "READY"
    assert [1, 2, 2] in result["ordinary_insertions_allowed"]


def test_cli_standard_streams_reconfigure_to_utf8(monkeypatch) -> None:
    """SAGE CLI does not inherit a legacy Windows code page for stdin/stdout/stderr."""
    class FakeStream:
        """Capture standard-stream reconfiguration calls without touching the host terminal."""

        def __init__(self) -> None:
            """Initialize an empty reconfiguration-call ledger."""
            self.calls: list[dict[str, str]] = []

        def reconfigure(self, **kwargs) -> None:
            """Record one requested stream encoding/error-policy change."""
            self.calls.append(dict(kwargs))

    stdin = FakeStream()
    stdout = FakeStream()
    stderr = FakeStream()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    _configure_utf8_standard_streams()

    for stream in (stdin, stdout, stderr):
        assert stream.calls == [{"encoding": "utf-8", "errors": "strict"}]
