"""OpenAI Codex CLI executor using existing ChatGPT-managed login only."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .. import __version__
from ..errors import ValidationError
from .base import (
    ModelCapability,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ReasoningEffortOption,
    sage_supports_reasoning_effort,
)


class CodexCLIExecutor:
    """Run Codex while prohibiting API credentials and querying the live ChatGPT catalog."""

    provider_id = "codex"
    _TEXT_ENCODING = "utf-8"
    _CLIENT_INFO = {
        "name": "sage_cli",
        "title": "SAGE CLI",
        "version": __version__,
    }

    def __init__(self, command: str | None = None) -> None:
        """Resolve one unambiguous Codex CLI command, never a desktop-app launcher."""
        explicit = self._cli_candidate(command or os.environ.get("SAGE_CODEX_COMMAND", ""))
        discovered = explicit or self._preferred_installed_command() or self._path_cli_command()
        self.command = self._cli_candidate(discovered)

    @staticmethod
    def _normalize_command(command: str | None) -> str | None:
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

    @classmethod
    def _windows_cli_candidates(cls, env: dict[str, str] | None = None) -> tuple[Path, ...]:
        """Return only official standalone Codex CLI locations on Windows."""
        values = os.environ if env is None else env
        local_app_data = str(values.get("LOCALAPPDATA", "")).strip()
        user_profile = str(values.get("USERPROFILE", "")).strip()
        candidates: list[Path] = []
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe")
        if user_profile:
            current = Path(user_profile) / ".codex" / "packages" / "standalone" / "current"
            candidates.extend((current / "bin" / "codex.exe", current / "codex.exe"))
        return tuple(candidates)

    @classmethod
    def _cli_candidate(cls, command: str | None) -> str | None:
        """Accept a CLI executable/shim while rejecting Windows desktop-app aliases."""
        value = cls._normalize_command(command)
        if not value or not cls._is_windows():
            return value
        if "\\" not in value and "/" not in value:
            resolved = shutil.which(value)
            if not resolved or resolved == value:
                return None
            value = cls._normalize_command(resolved)
            if not value:
                return None
        folded = value.replace("/", "\\").casefold()
        # Windows Store/App Execution Alias entries can launch the desktop application
        # instead of the terminal CLI.  Likewise, Programs\Codex has been observed in
        # the field as a desktop/legacy launcher location.  SAGE never treats either as
        # the governed CLI.
        if "\\microsoft\\windowsapps\\" in folded or "\\windowsapps\\" in folded:
            return None
        if "\\programs\\codex\\" in folded and "\\programs\\openai\\codex\\" not in folded:
            return None
        suffix = Path(value).suffix.casefold()
        if suffix and suffix not in {".exe", ".cmd", ".bat"}:
            return None
        return value

    @classmethod
    def _path_cli_command(cls) -> str | None:
        """Resolve a PATH Codex CLI while filtering Windows desktop-app aliases."""
        names = ("codex.exe", "codex.cmd", "codex.bat", "codex") if cls._is_windows() else ("codex",)
        seen: set[str] = set()
        for name in names:
            candidate = shutil.which(name)
            normalized = cls._cli_candidate(candidate)
            if normalized and normalized.casefold() not in seen:
                return normalized
            if candidate:
                seen.add(str(candidate).casefold())
        return None

    @classmethod
    def _preferred_installed_command(cls) -> str | None:
        """Prefer the official standalone Windows CLI over PATH shims and app aliases."""
        if not cls._is_windows():
            return None
        for candidate in cls._windows_cli_candidates():
            if candidate.is_file():
                return str(candidate)
        return None

    def _command_argv(self, args: list[str]) -> list[str]:
        """Return a Windows-safe executable argv, including legacy .cmd/.bat compatibility."""
        if not self.command:
            raise ValidationError("Codex CLI is not installed", code="CODEX_CLI_NOT_FOUND")
        command = self._normalize_command(self.command)
        if not command:
            raise ValidationError("Codex CLI is not installed", code="CODEX_CLI_NOT_FOUND")
        if self._is_windows() and Path(command).suffix.casefold() in {".cmd", ".bat"}:
            comspec = os.environ.get("COMSPEC", "").strip() or str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "cmd.exe")
            # Do not pre-render a nested quoted command string and then pass that string
            # as one argv element.  Python would escape the embedded quotes for
            # CreateProcess and ``cmd /s /c`` can then treat them literally.  ``call``
            # lets cmd.exe receive the shim path as a normal argument and correctly
            # returns control to SAGE after the batch shim finishes.
            return [comspec, "/d", "/c", "call", command, *args]
        return [command, *args]

    @staticmethod
    def _windows_creationflags() -> int:
        """Create a separable Windows process group where the host supports it."""
        if os.name != "nt":
            return 0
        return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        """Terminate one Codex process and its Windows descendants after timeout/cleanup."""
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

    @staticmethod
    def _is_windows() -> bool:
        """Return whether SAGE is running on Windows; isolated for cross-platform install tests."""
        return os.name == "nt"

    @classmethod
    def _environment(cls) -> dict[str, str]:
        """Pass only operating-system/Codex essentials and never API credentials."""
        allowed = {
            "PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "OS", "CODEX_HOME", "CODEX_INSTALL_DIR",
            "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TERM", "SYSTEMROOT",
            "COMSPEC", "PATHEXT", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY",
            "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
            "NODE_EXTRA_CA_CERTS", "BROWSER", "DISPLAY", "WAYLAND_DISPLAY",
            "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
        }
        allowed_folded = {key.casefold() for key in allowed}
        env = {key: value for key, value in os.environ.items() if key.casefold() in allowed_folded}
        if cls._is_windows():
            env.setdefault("OS", "Windows_NT")
            env.setdefault("USERPROFILE", str(Path.home()))
            env.setdefault("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
            env.setdefault("COMSPEC", os.environ.get("COMSPEC", str(Path(env["SYSTEMROOT"]) / "System32" / "cmd.exe")))
        return env

    def _run(
        self,
        args: list[str],
        *,
        timeout: int = 15,
        input_text: str | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run Codex with a minimized environment and optional isolated working directory."""
        if not self.command:
            raise ValidationError("Codex CLI is not installed", code="CODEX_CLI_NOT_FOUND")
        if input_text is not None:
            # Validate before starting Codex so malformed Unicode cannot fail inside
            # Python's background stdin writer and leave the child waiting for EOF.
            input_text.encode(self._TEXT_ENCODING, errors="strict")
        return subprocess.run(
            self._command_argv(args),
            input=input_text,
            capture_output=True,
            text=True,
            encoding=self._TEXT_ENCODING,
            errors="strict",
            check=False,
            timeout=timeout,
            env=self._environment(),
            cwd=str(cwd) if cwd is not None else None,
        )


    def _run_governed(
        self,
        args: list[str],
        *,
        timeout: int,
        input_text: str,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        """Run a governed Codex task without stdout/stderr pipe inheritance and clean its process tree."""
        if not self.command:
            raise ValidationError("Codex CLI is not installed", code="CODEX_CLI_NOT_FOUND")
        stdout_path = cwd / "codex-stdout.log"
        stderr_path = cwd / "codex-stderr.log"
        argv = self._command_argv(args)
        # Windows commonly defaults Python text pipes to a legacy code page such as
        # cp1252.  SAW/BIC prompts can contain Scripture text in any Unicode script,
        # so validate and force UTF-8 before the child is created.  Without this, a
        # writer-thread UnicodeEncodeError can leave Codex alive waiting for stdin
        # until SAGE's outer timeout expires.
        input_text.encode(self._TEXT_ENCODING, errors="strict")
        with (
            stdout_path.open("w+", encoding=self._TEXT_ENCODING) as stdout_handle,
            stderr_path.open("w+", encoding=self._TEXT_ENCODING) as stderr_handle,
        ):
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding=self._TEXT_ENCODING,
                errors="strict",
                env=self._environment(),
                cwd=str(cwd),
                creationflags=self._windows_creationflags(),
            )
            try:
                process.communicate(input=input_text, timeout=timeout)
            except subprocess.TimeoutExpired:
                self._terminate_process_tree(process)
                raise
            finally:
                if process.poll() is None:
                    self._terminate_process_tree(process)
            stdout_handle.flush()
            stderr_handle.flush()
            stdout_handle.seek(0)
            stderr_handle.seek(0)
            stdout = stdout_handle.read()
            stderr = stderr_handle.read()
        return subprocess.CompletedProcess(argv, int(process.returncode or 0), stdout=stdout, stderr=stderr)

    @staticmethod
    def _execution_failure_detail(raw: str, prompt: str, *, limit: int = 2000) -> str:
        """Return the actionable tail of Codex diagnostics without echoing sealed evidence."""
        detail = str(raw or "").strip()
        if prompt and prompt in detail:
            detail = detail.replace(prompt, "[sealed governed prompt omitted]")
        if len(detail) > limit:
            detail = "[earlier Codex output omitted]\n" + detail[-limit:]
        return detail or "Codex returned a non-zero status without a diagnostic."

    @staticmethod
    def installation_guidance() -> str:
        """Return the official Codex CLI installer command; never direct users to the desktop app."""
        if CodexCLIExecutor._is_windows():
            return (
                "Install the Codex CLI (not the Codex desktop app): "
                'powershell -NoProfile -ExecutionPolicy Bypass -c "irm https://chatgpt.com/codex/install.ps1 | iex"'
            )
        return "Install the Codex CLI (not the desktop app): curl -fsSL https://chatgpt.com/codex/install.sh | sh"

    def quick_status(self) -> ProviderStatus:
        """Check CLI presence and ChatGPT login without querying the live model catalog."""
        if not self.command:
            return ProviderStatus(
                provider=self.provider_id,
                available=False,
                ready=False,
                auth_mode="NONE",
                diagnostic="Codex CLI is not installed.",
                capabilities=("chatgpt_login",),
            )
        try:
            version = self._run(["--version"], timeout=5)
            version_text = ((version.stdout or version.stderr or "").strip() or None) if version.returncode == 0 else None
            if version.returncode != 0:
                detail = (version.stderr or version.stdout).strip() or "Codex --version returned a non-zero status."
                return ProviderStatus(
                    provider=self.provider_id,
                    available=True,
                    ready=False,
                    auth_mode="UNVERIFIED",
                    version=None,
                    diagnostic=f"Codex CLI was found but could not be verified: {detail}",
                    capabilities=("chatgpt_login",),
                )
            login = self._run(["login", "status"], timeout=8)
        except (subprocess.SubprocessError, OSError) as exc:
            return ProviderStatus(
                provider=self.provider_id,
                available=True,
                ready=False,
                auth_mode="UNVERIFIED",
                diagnostic=f"Codex CLI could not be checked: {exc}",
                capabilities=("chatgpt_login",),
            )
        text = " ".join(part.strip() for part in (login.stdout, login.stderr) if part).strip()
        folded = text.casefold()
        chatgpt = login.returncode == 0 and "chatgpt" in folded
        return ProviderStatus(
            provider=self.provider_id,
            available=True,
            ready=chatgpt,
            auth_mode="CHATGPT" if chatgpt else "UNVERIFIED",
            version=version_text,
            diagnostic=(
                "Codex CLI and ChatGPT sign-in detected."
                if chatgpt
                else (text or "Codex CLI is installed but ChatGPT sign-in was not verified.")
            ),
            capabilities=("chatgpt_login",),
        )

    def _installed_command_candidate(self, env: dict[str, str]) -> str | None:
        """Resolve the binary installed by SAGE, refusing desktop-app/Windows alias fallbacks."""
        install_dir = env.get("CODEX_INSTALL_DIR")
        if self._is_windows():
            candidates: list[Path] = []
            if install_dir:
                candidates.append(Path(install_dir) / "codex.exe")
            candidates.extend(self._windows_cli_candidates(env))
            seen: set[str] = set()
            for candidate in candidates:
                key = str(candidate).casefold()
                if key in seen:
                    continue
                seen.add(key)
                if candidate.is_file():
                    return str(candidate)
            # Installation verification intentionally does not fall back to PATH here:
            # a PATH `codex` may be the desktop app alias that caused installation in
            # the first place.  SAGE must prove that the standalone CLI was installed.
            return None
        visible = self._path_cli_command()
        if visible:
            return visible
        home = env.get("HOME")
        candidate = (
            Path(install_dir).expanduser() / "codex"
            if install_dir
            else (Path(home).expanduser() / ".local" / "bin" / "codex" if home else None)
        )
        if candidate is not None and candidate.is_file():
            return str(candidate)
        return None

    @staticmethod
    def installation_prerequisites() -> tuple[bool, tuple[str, ...]]:
        """Return whether the platform tools needed by the official Codex installer are present."""
        if CodexCLIExecutor._is_windows():
            missing = () if (shutil.which("powershell") or shutil.which("pwsh")) else ("PowerShell",)
        else:
            missing_items = []
            if not shutil.which("curl"):
                missing_items.append("curl")
            if not shutil.which("sh"):
                missing_items.append("sh")
            missing = tuple(missing_items)
        return not missing, missing

    def install(self) -> ProviderStatus:
        """Install Codex without entering its TUI, verify the binary, then return control to SAGE."""
        if self.command:
            return self.quick_status()
        env = self._environment()
        if self._is_windows():
            powershell = shutil.which("powershell") or shutil.which("pwsh")
            if not powershell:
                raise ValidationError(
                    "Codex CLI is missing and PowerShell is not available for the Windows standalone installer.",
                    code="CODEX_INSTALL_PREREQUISITE_MISSING",
                    next_action=self.installation_guidance(),
                )
            # The official Windows installer explicitly requires OS=Windows_NT.
            # SAGE uses a minimized subprocess environment, so preserve/synthesize
            # the Windows identity variables the installer depends on.
            env["OS"] = "Windows_NT"
            env["CODEX_NON_INTERACTIVE"] = "1"
            local_app_data = str(env.get("LOCALAPPDATA", "")).strip()
            if not local_app_data:
                raise ValidationError(
                    "Codex CLI installation requires LOCALAPPDATA on Windows.",
                    code="CODEX_INSTALL_PREREQUISITE_MISSING",
                    next_action=self.installation_guidance(),
                )
            # Force the official standalone CLI destination.  Do not inherit a custom
            # CODEX_INSTALL_DIR that could point at a desktop-app/legacy Codex folder.
            env["CODEX_INSTALL_DIR"] = str(Path(local_app_data) / "Programs" / "OpenAI" / "Codex" / "bin")
            command = [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "irm https://chatgpt.com/codex/install.ps1 | iex",
            ]
        else:
            curl = shutil.which("curl")
            shell = shutil.which("sh")
            if not curl or not shell:
                raise ValidationError(
                    "Codex CLI is missing and curl/sh are not available for the standalone installer.",
                    code="CODEX_INSTALL_PREREQUISITE_MISSING",
                    next_action=self.installation_guidance(),
                )
            # The official installer otherwise offers `Start Codex now?`, which would put
            # the operator inside the Codex TUI. SAGE must remain the parent process.
            env["CODEX_NON_INTERACTIVE"] = "1"
            command = [shell, "-c", "curl -fsSL https://chatgpt.com/codex/install.sh | sh"]
        try:
            completed = subprocess.run(command, check=False, env=env, text=True)
        except OSError as exc:
            raise ValidationError(
                f"Codex CLI installer could not start: {exc}",
                code="CODEX_INSTALL_START_FAILED",
                next_action=self.installation_guidance(),
            ) from exc

        # Verify installation independently of the installer's final status. Older or
        # interactive installer behavior may return non-zero after installing the binary.
        self.command = self._installed_command_candidate(env)
        if self.command:
            status = self.quick_status()
            if status.version:
                # Keep this SAGE process connected to the newly installed binary even
                # before the operator opens a fresh shell with the updated PATH.
                os.environ["SAGE_CODEX_COMMAND"] = self.command
                return status

        if completed.returncode != 0:
            raise ValidationError(
                f"Codex CLI installation ended with exit code {completed.returncode} and no verified binary was found.",
                code="CODEX_INSTALL_FAILED",
                next_action=self.installation_guidance(),
            )
        raise ValidationError(
            "Codex CLI installation completed but SAGE could not locate a verified `codex` binary.",
            code="CODEX_INSTALL_PATH_REFRESH_REQUIRED",
            next_action="Close and reopen the terminal, then run SAGE again.",
        )

    def connect_chatgpt(self, *, device_auth: bool = False) -> ProviderStatus:
        """Run interactive ChatGPT sign-in through the local Codex CLI and verify the resulting account."""
        if not self.command:
            raise ValidationError(
                "Codex CLI is not installed; SAGE connects through the CLI and does not require the Codex desktop app.",
                code="CODEX_CLI_NOT_FOUND",
                next_action=self.installation_guidance(),
            )
        args = ["login"]
        if device_auth:
            args.append("--device-auth")
        elif self._is_windows():
            # Codex browser OAuth hands the authorization result back to a temporary
            # localhost listener owned by the CLI.  The browser can occasionally show
            # an unattractive localhost error page even though the CLI has already
            # received and stored the authorization.  Explain the handoff before the
            # browser opens; SAGE verifies the CLI account after the process returns.
            print(
                "Codex CLI browser sign-in uses a temporary localhost callback. "
                "After approving access, return to SAGE even if the final browser page "
                "cannot display localhost; SAGE will verify the sign-in here."
            )
        try:
            completed = subprocess.run(
                self._command_argv(args),
                check=False,
                env=self._environment(),
                text=True,
            )
        except OSError as exc:
            raise ValidationError(
                f"Codex login could not start: {exc}",
                code="CODEX_LOGIN_START_FAILED",
                next_action=self.installation_guidance(),
            ) from exc

        # The browser callback page is not authoritative.  Some Windows/browser
        # combinations can leave Codex with a non-zero launcher status after the OAuth
        # token was successfully stored.  Always ask the CLI whether ChatGPT login is
        # actually present before converting the launcher status into a SAGE failure.
        if completed.returncode != 0:
            quick = self.quick_status()
            if quick.ready and quick.auth_mode == "CHATGPT":
                verified = self.status()
                if verified.ready and verified.auth_mode == "CHATGPT":
                    return verified
            raise ValidationError(
                f"Codex ChatGPT sign-in ended with exit code {completed.returncode} and the CLI did not verify a ChatGPT session.",
                code="CODEX_CHATGPT_LOGIN_FAILED",
                next_action=(
                    "Browser sign-in returns through a temporary localhost callback. "
                    "If that page failed to load and SAGE did not verify sign-in, choose "
                    "device-code sign-in from SAGE Setup / system configuration and try again."
                ),
            )
        status = self.status()
        if not status.ready or status.auth_mode != "CHATGPT":
            raise ValidationError(
                status.diagnostic or "Codex did not verify a ChatGPT-managed account after sign-in.",
                code="CODEX_CHATGPT_AUTH_REQUIRED",
                next_action=(
                    "Browser sign-in returns through a temporary localhost callback. "
                    "If the callback did not complete, use device-code sign-in from SAGE Setup / system configuration. "
                    "API-key and access-token authentication are not accepted."
                ),
            )
        return status

    def _app_server_roundtrip(
        self,
        requests: list[tuple[int, str, dict[str, Any]]],
        *,
        timeout: int = 20,
    ) -> dict[int, dict[str, Any]]:
        """Run a sequenced stdio App Server exchange: initialize, await response, then issue requests."""
        if not self.command:
            raise ValidationError("Codex CLI is not installed", code="CODEX_CLI_NOT_FOUND")
        with tempfile.TemporaryDirectory(prefix="sage-codex-catalog-") as tmp:
            try:
                process = subprocess.Popen(
                    self._command_argv(["app-server", "--stdio"]),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding=self._TEXT_ENCODING,
                    errors="strict",
                    bufsize=1,
                    env=self._environment(),
                    cwd=tmp,
                    creationflags=self._windows_creationflags(),
                )
            except OSError as exc:
                raise ValidationError(
                    f"Codex App Server could not start: {exc}",
                    code="CODEX_APP_SERVER_UNAVAILABLE",
                ) from exc

            lines: queue.Queue[str | None] = queue.Queue()
            errors: list[str] = []

            def read_stdout() -> None:
                """Stream App Server stdout into a bounded response queue."""
                assert process.stdout is not None
                for line in process.stdout:
                    lines.put(line)
                lines.put(None)

            def read_stderr() -> None:
                """Collect App Server diagnostics without blocking stdout response handling."""
                assert process.stderr is not None
                for line in process.stderr:
                    errors.append(line.rstrip())

            out_thread = threading.Thread(target=read_stdout, name="sage-codex-app-server-out", daemon=True)
            err_thread = threading.Thread(target=read_stderr, name="sage-codex-app-server-err", daemon=True)
            out_thread.start()
            err_thread.start()
            deadline = time.monotonic() + timeout
            responses: dict[int, dict[str, Any]] = {}

            def send(message: dict[str, Any]) -> None:
                """Write one JSON-RPC line to the running App Server."""
                if process.stdin is None:
                    raise ValidationError("Codex App Server stdin is unavailable", code="CODEX_APP_SERVER_UNAVAILABLE")
                process.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
                process.stdin.flush()

            def wait_for(ids: set[int]) -> None:
                """Read until every requested response ID arrives, ignoring unrelated notifications."""
                pending = set(ids)
                while pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValidationError("Codex App Server capability query timed out", code="CODEX_APP_SERVER_TIMEOUT")
                    try:
                        line = lines.get(timeout=remaining)
                    except queue.Empty as exc:
                        raise ValidationError("Codex App Server capability query timed out", code="CODEX_APP_SERVER_TIMEOUT") from exc
                    if line is None:
                        detail = "\n".join(errors[-20:]).strip()
                        raise ValidationError(
                            f"Codex App Server ended before replying{': ' + detail[:1600] if detail else ''}",
                            code="CODEX_APP_SERVER_UNAVAILABLE",
                        )
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(message, dict) or "id" not in message:
                        continue
                    try:
                        response_id = int(message["id"])
                    except (TypeError, ValueError):
                        continue
                    responses[response_id] = message
                    pending.discard(response_id)

            try:
                # Keep the JSON-RPC handshake ordered; capability requests are invalid before initialization completes.
                send({"method": "initialize", "id": 0, "params": {"clientInfo": dict(self._CLIENT_INFO)}})
                wait_for({0})
                init = responses.get(0)
                if not init or "error" in init:
                    raise ValidationError(
                        "Codex App Server initialization failed or returned an error",
                        code="CODEX_APP_SERVER_PROTOCOL_ERROR",
                    )
                send({"method": "initialized", "params": {}})
                for request_id, method, params in requests:
                    send({"method": method, "id": request_id, "params": params})
                wait_for({request_id for request_id, _method, _params in requests})
                for request_id, method, _params in requests:
                    response = responses.get(request_id)
                    if response is None:
                        raise ValidationError(
                            f"Codex App Server returned no response for {method}",
                            code="CODEX_APP_SERVER_PROTOCOL_ERROR",
                        )
                    if "error" in response:
                        raise ValidationError(
                            f"Codex App Server {method} failed: {response.get('error')}",
                            code="CODEX_APP_SERVER_PROTOCOL_ERROR",
                        )
                return responses
            finally:
                try:
                    if process.stdin is not None:
                        process.stdin.close()
                except OSError:
                    pass
                if process.poll() is None:
                    self._terminate_process_tree(process)

    @staticmethod
    def _normalize_effort(item: Any) -> ReasoningEffortOption | None:
        """Normalize one App Server reasoning option inside SAGE's hard XHigh ceiling."""
        if isinstance(item, str):
            value = item.strip().lower()
            return ReasoningEffortOption(value) if value and sage_supports_reasoning_effort(value) else None
        if not isinstance(item, dict):
            return None
        value = str(item.get("reasoningEffort") or item.get("reasoning_effort") or "").strip().lower()
        if not value or not sage_supports_reasoning_effort(value):
            return None
        return ReasoningEffortOption(value, str(item.get("description") or "").strip())

    @classmethod
    def _normalize_model(cls, item: Any) -> ModelCapability | None:
        """Normalize one App Server model row while preserving reasoning progression order."""
        if not isinstance(item, dict):
            return None
        model = str(item.get("model") or item.get("id") or "").strip()
        model_id = str(item.get("id") or model).strip()
        if not model:
            return None
        efforts: list[ReasoningEffortOption] = []
        raw_efforts = item.get("supportedReasoningEfforts", item.get("supported_reasoning_efforts", []))
        if isinstance(raw_efforts, list):
            for raw in raw_efforts:
                normalized = cls._normalize_effort(raw)
                if normalized is not None:
                    efforts.append(normalized)
        modalities = item.get("inputModalities", item.get("input_modalities", []))
        if not isinstance(modalities, list):
            modalities = []
        service_rows = item.get("serviceTiers", item.get("service_tiers", []))
        service_tiers: list[str] = []
        if isinstance(service_rows, list):
            for row in service_rows:
                if isinstance(row, str) and row.strip():
                    service_tiers.append(row.strip())
                elif isinstance(row, dict):
                    value = str(row.get("serviceTier") or row.get("id") or row.get("tier") or "").strip()
                    if value:
                        service_tiers.append(value)
        specialty = item.get("modelSpecialty", item.get("model_specialty"))
        supports_personality = item.get("supportsPersonality", item.get("supports_personality"))
        default_reasoning = (
            str(item.get("defaultReasoningEffort") or item.get("default_reasoning_effort") or "").strip().lower()
            or None
        )
        if not sage_supports_reasoning_effort(default_reasoning):
            default_reasoning = None
        return ModelCapability(
            id=model_id,
            model=model,
            display_name=str(item.get("displayName") or item.get("display_name") or model).strip(),
            description=str(item.get("description") or "").strip(),
            supported_reasoning_efforts=tuple(efforts),
            default_reasoning_effort=default_reasoning,
            is_default=bool(item.get("isDefault", item.get("is_default", False))),
            hidden=bool(item.get("hidden", False)),
            input_modalities=tuple(str(value) for value in modalities if str(value).strip()),
            supports_personality=(bool(supports_personality) if supports_personality is not None else None),
            model_specialty=(str(specialty).strip() if specialty is not None and str(specialty).strip() else None),
            service_tiers=tuple(service_tiers),
            default_service_tier=(
                str(item.get("defaultServiceTier") or item.get("default_service_tier") or "").strip() or None
            ),
        )

    def query_catalog(self, *, include_hidden: bool = False) -> tuple[str, str | None, tuple[ModelCapability, ...]]:
        """Query ChatGPT account state and the live Codex catalog within SAGE's XHigh ceiling."""
        responses = self._app_server_roundtrip(
            [
                (1, "account/read", {"refreshToken": False}),
                (2, "model/list", {"includeHidden": include_hidden, "limit": 500}),
            ]
        )
        account_result = responses[1].get("result", {})
        if not isinstance(account_result, dict):
            raise ValidationError("Codex account/read returned an invalid result", code="CODEX_APP_SERVER_PROTOCOL_ERROR")
        account = account_result.get("account")
        account_type = str(account.get("type") if isinstance(account, dict) else "").strip().casefold()
        plan_type = (
            str(account.get("planType") or "").strip() or None
            if isinstance(account, dict)
            else None
        )
        if account_type != "chatgpt":
            observed = account_type or "signed-out"
            raise ValidationError(
                f"Codex authentication mode is {observed}; SAGE requires ChatGPT-managed authentication and prohibits API/access-token modes",
                code="CODEX_CHATGPT_AUTH_REQUIRED",
            )

        model_result = responses[2].get("result", {})
        if not isinstance(model_result, dict):
            raise ValidationError("Codex model/list returned an invalid result", code="CODEX_APP_SERVER_PROTOCOL_ERROR")
        raw_models = model_result.get("data", [])
        if not isinstance(raw_models, list):
            raise ValidationError("Codex model/list data is invalid", code="CODEX_APP_SERVER_PROTOCOL_ERROR")
        models = [row for raw in raw_models if (row := self._normalize_model(raw)) is not None]
        cursor = model_result.get("nextCursor")
        seen_cursors: set[str] = set()
        request_id = 10
        while cursor:
            cursor_text = str(cursor)
            if cursor_text in seen_cursors or len(seen_cursors) >= 20:
                raise ValidationError("Codex model/list pagination did not converge", code="CODEX_APP_SERVER_PROTOCOL_ERROR")
            seen_cursors.add(cursor_text)
            page = self._app_server_roundtrip(
                [(request_id, "model/list", {"includeHidden": include_hidden, "limit": 500, "cursor": cursor_text})]
            )[request_id].get("result", {})
            if not isinstance(page, dict) or not isinstance(page.get("data", []), list):
                raise ValidationError("Codex model/list pagination returned invalid data", code="CODEX_APP_SERVER_PROTOCOL_ERROR")
            for raw in page.get("data", []):
                normalized = self._normalize_model(raw)
                if normalized is not None:
                    models.append(normalized)
            cursor = page.get("nextCursor")
            request_id += 1
        # Preserve provider order but de-duplicate repeated model slugs defensively.
        unique: list[ModelCapability] = []
        seen_models: set[str] = set()
        for item in models:
            if item.model not in seen_models:
                seen_models.add(item.model)
                unique.append(item)
        return "CHATGPT", plan_type, tuple(unique)

    @staticmethod
    def _model_entry(models: tuple[ModelCapability, ...], model: str | None) -> ModelCapability | None:
        """Resolve one requested model by executable slug or catalog id."""
        if model is None:
            return next((item for item in models if item.is_default), models[0] if models else None)
        return next((item for item in models if item.model == model or item.id == model), None)

    def status(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderStatus:
        """Verify Codex installation, ChatGPT authentication, live model, and reasoning readiness."""
        if not self.command:
            return ProviderStatus(
                provider=self.provider_id,
                available=False,
                ready=False,
                selected_model=model,
                selected_reasoning_effort=reasoning_effort,
                diagnostic="Codex CLI not found. The desktop app is not required; install the Codex CLI and sign in with ChatGPT.",
                capabilities=("structured_output", "chatgpt_login", "live_model_catalog"),
            )
        try:
            version = self._run(["--version"], timeout=5)
            version_text = (version.stdout or version.stderr).strip() or None
        except (subprocess.SubprocessError, OSError):
            version_text = None
        quick = self.quick_status()
        if not quick.ready:
            return ProviderStatus(
                provider=self.provider_id,
                available=True,
                ready=False,
                auth_mode=quick.auth_mode,
                version=version_text or quick.version,
                selected_model=model,
                selected_reasoning_effort=reasoning_effort,
                diagnostic=quick.diagnostic,
                capabilities=("structured_output", "chatgpt_login"),
            )
        try:
            auth_mode, plan_type, models = self.query_catalog()
        except ValidationError as exc:
            catalog_required = bool(model or reasoning_effort)
            return ProviderStatus(
                provider=self.provider_id,
                available=True,
                ready=not catalog_required,
                auth_mode="CHATGPT",
                version=version_text or quick.version,
                selected_model=model,
                selected_reasoning_effort=reasoning_effort,
                diagnostic=(
                    f"Codex CLI and ChatGPT execution are ready; live model catalog is unavailable: {exc}"
                    if not catalog_required
                    else f"Codex CLI and ChatGPT are connected, but the requested model/reasoning cannot be verified because the live model catalog is unavailable: {exc}"
                ),
                capabilities=("structured_output", "chatgpt_login"),
            )
        selected = self._model_entry(models, model)
        if selected is None:
            diagnostic = f"Requested Codex model is not available to the current ChatGPT workspace: {model}"
            ready = False
        elif reasoning_effort and not sage_supports_reasoning_effort(reasoning_effort):
            diagnostic = (
                f"Reasoning effort {reasoning_effort!r} exceeds SAGE's supported ceiling; "
                "highest supported reasoning level is xhigh"
            )
            ready = False
        elif reasoning_effort and reasoning_effort not in selected.reasoning_efforts:
            diagnostic = (
                f"Reasoning effort {reasoning_effort!r} is not available within SAGE for {selected.model}; "
                f"supported={list(selected.reasoning_efforts)}"
            )
            ready = False
        else:
            diagnostic = "ChatGPT authentication and live Codex model catalog verified."
            ready = True
        return ProviderStatus(
            provider=self.provider_id,
            available=True,
            ready=ready,
            auth_mode=auth_mode,
            version=version_text,
            selected_model=selected.model if selected is not None else model,
            selected_reasoning_effort=reasoning_effort,
            models=tuple(item.model for item in models),
            model_capabilities=models,
            account_plan_type=plan_type,
            diagnostic=diagnostic,
            capabilities=(
                "structured_output",
                "chatgpt_login",
                "sandbox_read_only",
                "live_model_catalog",
                "reasoning_catalog",
            ),
        )

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Run one schema-constrained Codex execution after a fresh readiness verification."""
        status = self.status(model=request.model, reasoning_effort=request.reasoning_effort)
        return self.execute_prevalidated(request, status)

    def execute_prevalidated(
        self, request: ProviderRequest, status: ProviderStatus
    ) -> ProviderResponse:
        """Run one request against a readiness/catalog snapshot already verified for this task."""
        if not status.ready:
            raise ValidationError(status.diagnostic, code="CODEX_MODEL_OR_AUTH_NOT_READY")
        selected = self._model_entry(status.model_capabilities, request.model)
        if request.model and selected is None:
            raise ValidationError(
                f"Requested Codex model is not available in the prevalidated task catalog: {request.model}",
                code="CODEX_MODEL_OR_AUTH_NOT_READY",
            )
        selected_model = selected.model if selected is not None else (status.selected_model or request.model)
        if request.reasoning_effort:
            if not sage_supports_reasoning_effort(request.reasoning_effort):
                raise ValidationError(
                    f"Reasoning effort {request.reasoning_effort!r} exceeds SAGE's supported ceiling",
                    code="CODEX_MODEL_OR_AUTH_NOT_READY",
                )
            if selected is not None and request.reasoning_effort not in selected.reasoning_efforts:
                raise ValidationError(
                    f"Reasoning effort {request.reasoning_effort!r} is not available within SAGE for {selected.model}",
                    code="CODEX_MODEL_OR_AUTH_NOT_READY",
                )
        with tempfile.TemporaryDirectory(prefix="sage-codex-") as tmp:
            root = Path(tmp)
            schema_path = root / "response-schema.json"
            output_path = root / "response.json"
            schema_path.write_text(json.dumps(request.schema, ensure_ascii=False, indent=2), encoding="utf-8")
            args: list[str] = []
            if request.reasoning_effort:
                args.extend(["--config", f'model_reasoning_effort="{request.reasoning_effort}"'])
            args.extend(
                [
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--color",
                    "never",
                    "--sandbox",
                    "read-only",
                    "--skip-git-repo-check",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                ]
            )
            if selected_model:
                args.extend(["--model", selected_model])
            args.append("-")
            try:
                completed = self._run_governed(args, timeout=request.timeout_seconds, input_text=request.prompt, cwd=root)
            except subprocess.TimeoutExpired as exc:
                raise ValidationError(
                    f"Codex execution exceeded {request.timeout_seconds} seconds",
                    code="LLM_PROVIDER_TIMEOUT",
                ) from exc
            if completed.returncode != 0:
                error = self._execution_failure_detail(
                    completed.stderr or completed.stdout,
                    request.prompt,
                )
                raise ValidationError(
                    f"Codex execution failed: {error}",
                    code="LLM_PROVIDER_EXECUTION_FAILED",
                    next_action=(
                        "Retry the governed task. If the failure persists, run the Codex connectivity "
                        "test in SAGE Setup / system configuration and review the final provider diagnostic."
                    ),
                )
            content = output_path.read_text(encoding="utf-8") if output_path.is_file() else completed.stdout.strip()
            return ProviderResponse(
                provider=self.provider_id,
                model=selected_model,
                content=content,
                reasoning_effort=request.reasoning_effort,
                metadata={
                    "returncode": completed.returncode,
                    "auth_mode": status.auth_mode,
                    "account_plan_type": status.account_plan_type,
                },
            )
