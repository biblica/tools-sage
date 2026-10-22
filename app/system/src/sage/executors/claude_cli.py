"""Claude Code CLI executor using the Operator's own Claude subscription login only."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from .base import (
    ModelCapability,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ReasoningEffortOption,
)
from .cli_process import TEXT_ENCODING, normalize_command, run_governed, windows_command_argv

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "claude-catalog.json"
# `--restricted` (no command-running tools, no WebFetch, only managed + explicit settings)
# arrived in Claude Code 2.1.248; every governed call depends on it.
MINIMUM_CLI_VERSION = (2, 1, 248)
_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")
# Observed with Claude Code 2.1.307: a failed `-p --output-format json` run exits 1 and still
# prints one result object with `is_error: true`, the human message in `result`, and the HTTP
# status in `api_error_status` (`subtype` stays "success", so it is not a failure signal).
# "Not logged in · Please run /login" was observed; the subscription limit wording
# ("You've hit your session/weekly/Opus limit") is quoted from the Claude Code error reference
# and has not yet been seen live by SAGE.
_LOGIN_PATTERN = re.compile(r"not logged in|login expired|please run /login", re.IGNORECASE)
_USAGE_LIMIT_PATTERN = re.compile(r"hit your [\w ]*limit", re.IGNORECASE)
_RESETS_PATTERN = re.compile(r"resets?\s+(?:at\s+)?([^·\n]+)", re.IGNORECASE)
# Replaces Claude Code's own coding-agent system prompt for governed calls. The governed task,
# its evidence, and its output contract are all in the sealed user prompt and the JSON schema.
GOVERNED_SYSTEM_PROMPT = (
    "You are executing one sealed SAGE task. Follow the task in the user message exactly and "
    "return the answer only through the required structured output."
)


def _parse_version(text: str) -> tuple[int, int, int] | None:
    """Return the first semantic version in CLI output."""
    match = _VERSION_PATTERN.search(text or "")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def load_catalog(path: Path = _CATALOG_PATH) -> tuple[ModelCapability, ...]:
    """Load the reviewed Claude model catalog; the CLI has no live model list."""
    document = json.loads(path.read_text(encoding="utf-8"))
    models = []
    for row in document["models"]:
        models.append(
            ModelCapability(
                id=row["id"],
                model=row["id"],
                display_name=row["display_name"],
                supported_reasoning_efforts=tuple(
                    ReasoningEffortOption(effort) for effort in row["supported_reasoning_efforts"]
                ),
                default_reasoning_effort=row.get("default_reasoning_effort"),
                is_default=bool(row.get("is_default", False)),
                input_modalities=tuple(row.get("input_modalities", ())),
            )
        )
    return tuple(models)


class ClaudeCLIExecutor:
    """Run Claude Code with tools disabled, settings isolated, and API credentials prohibited."""

    provider_id = "claude"

    def __init__(self, command: str | None = None) -> None:
        """Resolve one Claude Code CLI command, never a desktop-app launcher."""
        explicit = self._cli_candidate(command or os.environ.get("SAGE_CLAUDE_COMMAND", ""))
        discovered = explicit or self._preferred_installed_command() or self._path_cli_command()
        self.command = self._cli_candidate(discovered)

    @staticmethod
    def _is_windows() -> bool:
        """Return whether SAGE is running on Windows; isolated for cross-platform tests."""
        return os.name == "nt"

    @classmethod
    def _windows_cli_candidates(cls, env: dict[str, str] | None = None) -> tuple[Path, ...]:
        """Return the native-installer Claude Code location on Windows."""
        values = os.environ if env is None else env
        user_profile = str(values.get("USERPROFILE", "")).strip()
        return (Path(user_profile) / ".local" / "bin" / "claude.exe",) if user_profile else ()

    @classmethod
    def _cli_candidate(cls, command: str | None) -> str | None:
        """Accept a CLI executable/shim while rejecting Windows app-execution aliases."""
        value = normalize_command(command)
        if not value or not cls._is_windows():
            return value
        if "\\" not in value and "/" not in value:
            resolved = shutil.which(value)
            if not resolved or resolved == value:
                return None
            value = normalize_command(resolved)
            if not value:
                return None
        folded = value.replace("/", "\\").casefold()
        # A Store/App Execution Alias or the Claude desktop app folder can launch the desktop
        # application instead of the terminal CLI; SAGE never treats either as the governed CLI.
        if "\\windowsapps\\" in folded or "\\anthropicclaude\\" in folded:
            return None
        suffix = Path(value).suffix.casefold()
        if suffix and suffix not in {".exe", ".cmd", ".bat"}:
            return None
        return value

    @classmethod
    def _path_cli_command(cls) -> str | None:
        """Resolve a PATH Claude Code CLI while filtering Windows desktop-app aliases."""
        names = ("claude.exe", "claude.cmd", "claude") if cls._is_windows() else ("claude",)
        for name in names:
            normalized = cls._cli_candidate(shutil.which(name))
            if normalized:
                return normalized
        return None

    @classmethod
    def _preferred_installed_command(cls) -> str | None:
        """Prefer the native-installer Windows CLI over PATH shims and app aliases."""
        if not cls._is_windows():
            return None
        return next((str(path) for path in cls._windows_cli_candidates() if path.is_file()), None)

    def _command_argv(self, args: list[str]) -> list[str]:
        """Return a Windows-safe executable argv, including npm .cmd shim compatibility."""
        command = normalize_command(self.command)
        if not command:
            raise ValidationError("Claude Code CLI is not installed", code="CLAUDE_CLI_NOT_FOUND")
        if self._is_windows() and Path(command).suffix.casefold() in {".cmd", ".bat"}:
            return windows_command_argv(command, args)
        return [command, *args]

    @classmethod
    def _environment(cls) -> dict[str, str]:
        """Pass only operating-system essentials; never an API key, auth token, or cloud route.

        In `-p` mode Claude Code uses ANTHROPIC_API_KEY whenever it is present, silently
        replacing the Operator's subscription login, so the allowlist must never admit it,
        ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, or the Bedrock/Vertex/Foundry switches.
        USER is required: without it the macOS keychain login is not found.
        """
        allowed = {
            "PATH", "HOME", "USER", "LOGNAME", "USERNAME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
            "OS", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
            "TERM", "SYSTEMROOT", "COMSPEC", "PATHEXT", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY",
            "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "NODE_EXTRA_CA_CERTS", "BROWSER", "DISPLAY",
            "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
        }
        allowed_folded = {key.casefold() for key in allowed}
        env = {key: value for key, value in os.environ.items() if key.casefold() in allowed_folded}
        # SAGE updates the CLI explicitly; a background self-update must not swap the binary
        # between the readiness check and a governed call.
        env["DISABLE_AUTOUPDATER"] = "1"
        if cls._is_windows():
            env.setdefault("OS", "Windows_NT")
            env.setdefault("USERPROFILE", str(Path.home()))
            env.setdefault("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
            env.setdefault("COMSPEC", os.environ.get("COMSPEC", str(Path(env["SYSTEMROOT"]) / "System32" / "cmd.exe")))
        return env

    def _run(self, args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        """Run one short non-governed Claude Code command with the minimized environment."""
        return subprocess.run(
            self._command_argv(args),
            capture_output=True,
            text=True,
            encoding=TEXT_ENCODING,
            errors="replace",
            check=False,
            timeout=timeout,
            env=self._environment(),
            stdin=subprocess.DEVNULL,
        )

    @staticmethod
    def installation_guidance() -> str:
        """Return the official Claude Code native installer command."""
        if ClaudeCLIExecutor._is_windows():
            return 'Install Claude Code (the CLI): powershell -NoProfile -c "irm https://claude.ai/install.ps1 | iex"'
        return "Install Claude Code (the CLI): curl -fsSL https://claude.ai/install.sh | bash"

    @staticmethod
    def installation_prerequisites() -> tuple[bool, tuple[str, ...]]:
        """Return whether the platform tools needed by the official Claude Code installer are present."""
        if ClaudeCLIExecutor._is_windows():
            missing: tuple[str, ...] = () if (shutil.which("powershell") or shutil.which("pwsh")) else ("PowerShell",)
        else:
            missing = tuple(name for name in ("curl", "bash") if not shutil.which(name))
        return not missing, missing

    def _installed_command_candidate(self, env: dict[str, str]) -> str | None:
        """Resolve the binary the native installer just placed, refusing desktop-app aliases."""
        if self._is_windows():
            return next((str(path) for path in self._windows_cli_candidates(env) if path.is_file()), None)
        visible = self._path_cli_command()
        if visible:
            return visible
        home = env.get("HOME")
        candidate = Path(home).expanduser() / ".local" / "bin" / "claude" if home else None
        return str(candidate) if candidate is not None and candidate.is_file() else None

    def install(self) -> ProviderStatus:
        """Install Claude Code with the official native installer, verify it, and return to SAGE."""
        if self.command:
            return self.quick_status()
        ready, missing = self.installation_prerequisites()
        if not ready:
            raise ValidationError(
                f"Claude Code CLI is missing and the installer needs: {', '.join(missing)}",
                code="CLAUDE_INSTALL_PREREQUISITE_MISSING",
                next_action=self.installation_guidance(),
            )
        env = self._environment()
        env.pop("DISABLE_AUTOUPDATER", None)
        if self._is_windows():
            powershell = shutil.which("powershell") or shutil.which("pwsh")
            command = [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                       "-Command", "irm https://claude.ai/install.ps1 | iex"]
        else:
            command = [str(shutil.which("bash")), "-c", "curl -fsSL https://claude.ai/install.sh | bash"]
        try:
            completed = subprocess.run(command, check=False, env=env, text=True, stdin=subprocess.DEVNULL)
        except OSError as exc:
            raise ValidationError(
                f"Claude Code installer could not start: {exc}",
                code="CLAUDE_INSTALL_START_FAILED",
                next_action=self.installation_guidance(),
            ) from exc
        # Verify the binary independently of the installer's own exit status.
        self.command = self._installed_command_candidate(env)
        if self.command:
            # Keep this SAGE process connected to the new binary before the shell PATH refreshes.
            os.environ["SAGE_CLAUDE_COMMAND"] = self.command
            return self.quick_status(version_timeout=60, login_timeout=30)
        if completed.returncode != 0:
            raise ValidationError(
                f"Claude Code installation ended with exit code {completed.returncode} and no verified binary was found.",
                code="CLAUDE_INSTALL_FAILED",
                next_action=self.installation_guidance(),
            )
        raise ValidationError(
            "Claude Code installation completed but SAGE could not locate a verified `claude` binary.",
            code="CLAUDE_INSTALL_PATH_REFRESH_REQUIRED",
            next_action="Close and reopen the terminal, then run SAGE again.",
        )

    def update(self) -> ProviderStatus:
        """Run `claude update` without any prompt, then return the re-verified status."""
        if not self.command:
            raise ValidationError(
                "Claude Code CLI is not installed; there is nothing to update.",
                code="CLAUDE_CLI_NOT_FOUND",
                next_action=self.installation_guidance(),
            )
        env = self._environment()
        env.pop("DISABLE_AUTOUPDATER", None)
        try:
            completed = subprocess.run(
                self._command_argv(["update"]),
                check=False,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding=TEXT_ENCODING,
                errors="replace",
                timeout=600,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValidationError(
                f"Claude Code update could not run: {exc}",
                code="CLAUDE_UPDATE_FAILED",
                next_action=self.installation_guidance(),
            ) from exc
        if completed.returncode != 0:
            detail = " ".join(((completed.stderr or completed.stdout) or "").split())[-400:]
            raise ValidationError(
                f"Claude Code update ended with exit code {completed.returncode}. {detail}".strip(),
                code="CLAUDE_UPDATE_FAILED",
                next_action="Homebrew and WinGet installs update through their package manager. "
                f"Otherwise update manually, then run SAGE again. {self.installation_guidance()}",
            )
        return self.quick_status(version_timeout=60, login_timeout=30)

    def connect(self, *, device_auth: bool = False) -> ProviderStatus:
        """Run interactive Claude subscription sign-in through the local CLI and verify the account."""
        if not self.command:
            raise ValidationError(
                "Claude Code CLI is not installed; SAGE signs in through the CLI, not the Claude desktop app.",
                code="CLAUDE_CLI_NOT_FOUND",
                next_action=self.installation_guidance(),
            )
        if device_auth:
            raise ValidationError(
                "Claude Code has no separate device-code sign-in; use the standard sign-in, which prints a "
                "link and accepts a pasted code when no browser is available.",
                code="CLAUDE_SUBSCRIPTION_LOGIN_FAILED",
            )
        try:
            # `--claudeai` forces subscription sign-in; Console (API billing) sign-in is never offered.
            subprocess.run(self._command_argv(["auth", "login", "--claudeai"]), check=False, env=self._environment(), text=True)
        except OSError as exc:
            raise ValidationError(
                f"Claude Code sign-in could not start: {exc}",
                code="CLAUDE_SUBSCRIPTION_LOGIN_FAILED",
                next_action=self.installation_guidance(),
            ) from exc
        # The launcher status is not authoritative; ask the CLI which account is actually signed in.
        status = self.status()
        if not status.ready or status.auth_mode != "CLAUDE_SUBSCRIPTION":
            raise ValidationError(
                status.diagnostic or "Claude Code did not verify a Claude subscription sign-in.",
                code="CLAUDE_SUBSCRIPTION_AUTH_REQUIRED",
                next_action="Sign in with your own Claude subscription. API-key, token, and Console sign-in are not accepted.",
            )
        return status

    def quick_status(self, *, version_timeout: int = 5, login_timeout: int = 8) -> ProviderStatus:
        """Check CLI presence, minimum version, and Claude subscription login without a model call."""
        capabilities = ("subscription_login",)
        if not self.command:
            return ProviderStatus(
                provider=self.provider_id,
                available=False,
                ready=False,
                diagnostic=f"Claude Code CLI is not installed. {self.installation_guidance()}",
                capabilities=capabilities,
            )
        try:
            version = self._run(["--version"], timeout=version_timeout)
            version_text = (version.stdout or version.stderr or "").strip() or None
            if version.returncode != 0:
                return ProviderStatus(
                    provider=self.provider_id,
                    available=True,
                    ready=False,
                    auth_mode="UNVERIFIED",
                    diagnostic=f"Claude Code CLI was found but could not be verified: {version_text or 'no diagnostic'}",
                    capabilities=capabilities,
                )
            login = self._run(["auth", "status"], timeout=login_timeout)
        except (subprocess.SubprocessError, OSError) as exc:
            return ProviderStatus(
                provider=self.provider_id,
                available=True,
                ready=False,
                auth_mode="UNVERIFIED",
                diagnostic=f"Claude Code CLI could not be checked: {exc}",
                capabilities=capabilities,
            )
        parsed_version = _parse_version(version_text or "")
        if parsed_version is None or parsed_version < MINIMUM_CLI_VERSION:
            minimum = ".".join(str(part) for part in MINIMUM_CLI_VERSION)
            return ProviderStatus(
                provider=self.provider_id,
                available=True,
                ready=False,
                auth_mode="UNVERIFIED",
                version=version_text,
                diagnostic=f"Claude Code {version_text or 'of unknown version'} is older than the {minimum} SAGE requires; update the CLI.",
                capabilities=capabilities,
            )
        try:
            account = json.loads(login.stdout or "{}")
        except json.JSONDecodeError:
            account = {}
        if not isinstance(account, dict):
            account = {}
        method = str(account.get("authMethod") or "none")
        subscription = login.returncode == 0 and bool(account.get("loggedIn")) and method == "claude.ai"
        if subscription:
            diagnostic = "Claude Code CLI and Claude subscription sign-in detected."
        elif method in {"none", ""}:
            diagnostic = "Claude Code CLI is installed but not signed in. Sign in with your Claude subscription."
        else:
            diagnostic = (
                f"Claude Code is authenticated by {method}; SAGE requires your own Claude subscription "
                "sign-in and prohibits API-key, token, and cloud-provider authentication."
            )
        # Only the plan type is kept: the account e-mail and organization never enter SAGE state.
        return ProviderStatus(
            provider=self.provider_id,
            available=True,
            ready=subscription,
            auth_mode="CLAUDE_SUBSCRIPTION" if subscription else "UNVERIFIED",
            version=version_text,
            account_plan_type=(str(account.get("subscriptionType") or "").strip() or None) if subscription else None,
            diagnostic=diagnostic,
            capabilities=capabilities,
        )

    @staticmethod
    def _model_entry(models: tuple[ModelCapability, ...], model: str | None) -> ModelCapability | None:
        """Resolve one requested model by catalog id, or the catalog default."""
        if model is None:
            return next((item for item in models if item.is_default), models[0] if models else None)
        return next((item for item in models if item.model == model or item.id == model), None)

    def status(self, *, model: str | None = None, reasoning_effort: str | None = None) -> ProviderStatus:
        """Verify the CLI, the subscription login, and the requested model/reasoning in the reviewed catalog."""
        quick = self.quick_status()
        if not quick.ready:
            return ProviderStatus(
                provider=self.provider_id,
                available=quick.available,
                ready=False,
                auth_mode=quick.auth_mode,
                version=quick.version,
                selected_model=model,
                selected_reasoning_effort=reasoning_effort,
                diagnostic=quick.diagnostic,
                capabilities=quick.capabilities,
            )
        models = load_catalog()
        selected = self._model_entry(models, model)
        if selected is None:
            diagnostic = f"Claude model {model} is not in SAGE's reviewed Claude catalog."
            ready = False
        elif reasoning_effort and reasoning_effort not in selected.reasoning_efforts:
            diagnostic = (
                f"Reasoning effort {reasoning_effort!r} is not available within SAGE for {selected.model}; "
                f"supported={list(selected.reasoning_efforts)}"
            )
            ready = False
        else:
            diagnostic = "Claude subscription sign-in and reviewed Claude model catalog verified."
            ready = True
        return ProviderStatus(
            provider=self.provider_id,
            available=True,
            ready=ready,
            auth_mode=quick.auth_mode,
            version=quick.version,
            selected_model=selected.model if selected is not None else model,
            selected_reasoning_effort=reasoning_effort,
            models=tuple(item.model for item in models),
            model_capabilities=models,
            account_plan_type=quick.account_plan_type,
            diagnostic=diagnostic,
            capabilities=("structured_output", "subscription_login", "tools_disabled", "reviewed_model_catalog", "reasoning_catalog"),
        )

    @staticmethod
    def governed_args(schema: dict[str, Any], model: str, reasoning_effort: str | None) -> list[str]:
        """Return the sealed `claude -p` arguments: no tools, no settings, MCP, or session state."""
        args = [
            "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
            "--model", model,
            "--system-prompt", GOVERNED_SYSTEM_PROMPT,
            "--tools", "",
            "--restricted",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--max-turns", "1",
        ]
        if reasoning_effort and reasoning_effort != "provider-default":
            args.extend(["--effort", reasoning_effort])
        return args

    @staticmethod
    def _failure_detail(text: str, prompt: str, *, limit: int = 2000) -> str:
        """Return the actionable tail of Claude Code diagnostics without echoing sealed evidence."""
        detail = str(text or "").strip()
        if prompt and prompt in detail:
            detail = detail.replace(prompt, "[sealed governed prompt omitted]")
        if len(detail) > limit:
            detail = "[earlier Claude Code output omitted]\n" + detail[-limit:]
        return detail or "Claude Code returned a non-zero status without a diagnostic."

    @staticmethod
    def classify_failure(message: str, api_error_status: Any) -> tuple[str, dict[str, Any] | None]:
        """Map one failed result to a SAGE error code and, for limits, a rate-limit classification."""
        if _LOGIN_PATTERN.search(message):
            return "CLAUDE_SUBSCRIPTION_AUTH_REQUIRED", None
        if _USAGE_LIMIT_PATTERN.search(message):
            reset = _RESETS_PATTERN.search(message)
            return "LLM_PROVIDER_RATE_LIMITED", {
                "kind": "USAGE_LIMIT",
                "retry_after_seconds": None,
                "retry_at": reset.group(1).strip() if reset else None,
            }
        if api_error_status == 429:
            # Claude Code already retries short 429s itself before giving up, so SAGE does not
            # add a second retry loop on top.
            return "LLM_PROVIDER_RATE_LIMITED", {"kind": "TOKEN_RATE_LIMIT", "retry_after_seconds": None, "retry_at": None}
        if api_error_status == 404:
            return "LLM_PROVIDER_NOT_READY", None
        return "LLM_PROVIDER_EXECUTION_FAILED", None

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Run one schema-constrained Claude execution after a fresh readiness verification."""
        status = self.status(model=request.model, reasoning_effort=request.reasoning_effort)
        return self.execute_prevalidated(request, status)

    def execute_prevalidated(self, request: ProviderRequest, status: ProviderStatus) -> ProviderResponse:
        """Run one request against a readiness/catalog snapshot already verified for this task."""
        if not status.ready:
            raise ValidationError(status.diagnostic, code="LLM_PROVIDER_NOT_READY")
        selected = self._model_entry(status.model_capabilities, request.model)
        if selected is None:
            raise ValidationError(
                f"Requested Claude model is not available in the prevalidated task catalog: {request.model}",
                code="LLM_PROVIDER_NOT_READY",
            )
        if request.reasoning_effort and request.reasoning_effort != "provider-default" and request.reasoning_effort not in selected.reasoning_efforts:
            raise ValidationError(
                f"Reasoning effort {request.reasoning_effort!r} is not available within SAGE for {selected.model}",
                code="LLM_PROVIDER_NOT_READY",
            )
        args = self.governed_args(request.schema, selected.model, request.reasoning_effort)
        with tempfile.TemporaryDirectory(prefix="sage-claude-") as tmp:
            try:
                # The prompt goes on stdin: ACT-sized prompts exceed the Windows command-line limit.
                completed = run_governed(
                    self._command_argv(args),
                    timeout=request.timeout_seconds,
                    input_text=request.prompt,
                    cwd=Path(tmp),
                    env=self._environment(),
                    log_prefix="claude",
                )
            except subprocess.TimeoutExpired as exc:
                raise ValidationError(
                    f"Claude execution exceeded {request.timeout_seconds} seconds",
                    code="LLM_PROVIDER_TIMEOUT",
                ) from exc
        try:
            document = json.loads(completed.stdout)
        except json.JSONDecodeError:
            document = None
        if not isinstance(document, dict):
            raise ValidationError(
                f"Claude execution failed: {self._failure_detail(completed.stderr or completed.stdout, request.prompt)}",
                code="LLM_PROVIDER_EXECUTION_FAILED",
            )
        if completed.returncode != 0 or document.get("is_error"):
            message = self._failure_detail(str(document.get("result") or completed.stderr), request.prompt)
            code, rate_limit = self.classify_failure(message, document.get("api_error_status"))
            if rate_limit is not None:
                raise ValidationError(
                    f"Claude execution was rate-limited: {message}",
                    code=code,
                    next_action=(
                        "This is a Claude subscription usage/rate limit, not a task failure. Wait for "
                        "the reported reset before retrying."
                    ),
                    details=rate_limit,
                )
            if code == "CLAUDE_SUBSCRIPTION_AUTH_REQUIRED":
                raise ValidationError(
                    f"Claude Code is not signed in: {message}",
                    code=code,
                    next_action="Sign in with your Claude subscription from SAGE Setup / system configuration.",
                )
            raise ValidationError(
                f"Claude execution failed: {message}",
                code=code,
                next_action=(
                    "Retry the governed task. If the failure persists, run the provider connectivity "
                    "test in SAGE Setup / system configuration and review the final provider diagnostic."
                ),
            )
        answering = sorted(str(name) for name in (document.get("modelUsage") or {}))
        if answering != [selected.model]:
            raise ValidationError(
                f"Claude answered with {answering or 'no reported model'}, not the routed {selected.model}",
                code="LLM_RESPONSE_ROUTE_MISMATCH",
            )
        output = document.get("structured_output")
        if not isinstance(output, dict):
            raise ValidationError(
                "Claude execution ended without structured output "
                f"(terminal_reason={document.get('terminal_reason')}, stop_reason={document.get('stop_reason')})",
                code="LLM_PROVIDER_EXECUTION_FAILED",
            )
        usage = document.get("usage") if isinstance(document.get("usage"), dict) else {}
        return ProviderResponse(
            provider=self.provider_id,
            model=selected.model,
            content=json.dumps(output, ensure_ascii=False),
            reasoning_effort=request.reasoning_effort,
            metadata={
                "returncode": completed.returncode,
                "auth_mode": status.auth_mode,
                "account_plan_type": status.account_plan_type,
                "cli_version": status.version,
                "num_turns": document.get("num_turns"),
                "duration_ms": document.get("duration_ms"),
                "usage": {
                    key: usage.get(key)
                    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                },
            },
        )
