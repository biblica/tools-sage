"""Subprocess mechanics shared by the governed provider CLI executors (Codex, Claude)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

TEXT_ENCODING = "utf-8"


def normalize_command(command: str | None) -> str | None:
    """Remove accidental shell quoting from one executable/shim path.

    Windows command discovery and persisted environment overrides can contain a path
    wrapped in quotes.  Passing those quote characters to ``cmd.exe`` makes the
    quotes part of the command token, producing ``'\"...codex.CMD\"' is not
    recognized``.  SAGE stores an executable path, never a pre-rendered shell
    command, so matching outer quotes are always transport noise and are removed.
    """
    value = str(command or "").strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        value = value[1:-1].strip()
    return value or None


def windows_command_argv(command: str, args: list[str]) -> list[str]:
    """Wrap a Windows .cmd/.bat shim so cmd.exe receives the shim path as a normal argument."""
    comspec = os.environ.get("COMSPEC", "").strip() or str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "cmd.exe")
    # Do not pre-render a nested quoted command string and then pass that string
    # as one argv element.  Python would escape the embedded quotes for
    # CreateProcess and ``cmd /s /c`` can then treat them literally.  ``call``
    # lets cmd.exe receive the shim path as a normal argument and correctly
    # returns control to SAGE after the batch shim finishes.
    return [comspec, "/d", "/c", "call", command, *args]


def windows_creationflags() -> int:
    """Create a separable Windows process group where the host supports it."""
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate one provider process and its Windows descendants after timeout/cleanup."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        taskkill = Path(system_root) / "System32" / "taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_governed(
    argv: list[str],
    *,
    timeout: int,
    input_text: str,
    cwd: Path,
    env: dict[str, str],
    log_prefix: str,
) -> subprocess.CompletedProcess[str]:
    """Run one governed task without stdout/stderr pipe inheritance and clean its process tree."""
    stdout_path = cwd / f"{log_prefix}-stdout.log"
    stderr_path = cwd / f"{log_prefix}-stderr.log"
    # Windows commonly defaults Python text pipes to a legacy code page such as
    # cp1252. Workflow prompts can contain Scripture text in any Unicode script,
    # so validate and force UTF-8 before the child is created.  Without this, a
    # writer-thread UnicodeEncodeError can leave the provider alive waiting for
    # stdin until SAGE's outer timeout expires.
    input_text.encode(TEXT_ENCODING, errors="strict")
    with (
        stdout_path.open("w+", encoding=TEXT_ENCODING) as stdout_handle,
        stderr_path.open("w+", encoding=TEXT_ENCODING) as stderr_handle,
    ):
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            encoding=TEXT_ENCODING,
            errors="strict",
            env=env,
            cwd=str(cwd),
            creationflags=windows_creationflags(),
        )
        try:
            process.communicate(input=input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_process_tree(process)
            raise
        finally:
            if process.poll() is None:
                terminate_process_tree(process)
        stdout_handle.flush()
        stderr_handle.flush()
        stdout_handle.seek(0)
        stderr_handle.seek(0)
        stdout = stdout_handle.read()
        stderr = stderr_handle.read()
    return subprocess.CompletedProcess(argv, int(process.returncode or 0), stdout=stdout, stderr=stderr)
