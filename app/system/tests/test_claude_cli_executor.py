"""Claude Code CLI executor: subscription-only auth, sealed invocation, and result classification.

Result documents mirror real `claude -p --output-format json` output captured from Claude Code
2.1.307 (success, "Not logged in", unknown model). The usage-limit wording is quoted from the
Claude Code error reference because SAGE has not yet observed one live.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from sage.errors import ValidationError
from sage.executors.base import ProviderRequest, ProviderStatus
from sage.executors.claude_cli import ClaudeCLIExecutor, load_catalog

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["status"],
          "properties": {"status": {"type": "string", "enum": ["OK"]}}}
PROMPT = "Sealed task: Ἐν ἀρχῇ ἦν ὁ λόγος. Reply with status OK."
SUBSCRIPTION = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
                "email": "operator@example.org", "orgId": "org-1", "orgName": "Example", "subscriptionType": "team"}


def _result(**overrides) -> str:
    """Return one `claude -p --output-format json` result document."""
    document = {
        "type": "result", "subtype": "success", "is_error": False, "api_error_status": None,
        "num_turns": 2, "duration_ms": 1448, "terminal_reason": "completed", "stop_reason": "tool_use",
        "result": '{"status":"OK"}', "structured_output": {"status": "OK"},
        "usage": {"input_tokens": 2, "output_tokens": 52, "cache_creation_input_tokens": 3241,
                  "cache_read_input_tokens": 0},
        "modelUsage": {"claude-opus-5-5": {"inputTokens": 2, "outputTokens": 52, "canonicalModel": "claude-opus-5-5"}},
    }
    document.update(overrides)
    return json.dumps(document)


def _ready_status() -> ProviderStatus:
    """Return a ready subscription status carrying the reviewed catalog."""
    models = load_catalog()
    return ProviderStatus(provider="claude", available=True, ready=True, auth_mode="CLAUDE_SUBSCRIPTION",
                          version="2.1.307 (Claude Code)", models=tuple(item.model for item in models),
                          model_capabilities=models, account_plan_type="team")


def _quick_executor(version: str, auth: dict, auth_returncode: int = 0) -> ClaudeCLIExecutor:
    """Return an executor whose short commands answer with the given version and auth status."""
    executor = ClaudeCLIExecutor(command="claude")

    def fake_run(args, **_kwargs):
        """Answer `--version` and `auth status` with the scripted values."""
        if args == ["--version"]:
            return subprocess.CompletedProcess(args, 0, stdout=version, stderr="")
        assert args == ["auth", "status"]
        return subprocess.CompletedProcess(args, auth_returncode, stdout=json.dumps(auth), stderr="")

    executor._run = fake_run
    return executor


def _execute(monkeypatch, stdout: str, returncode: int = 0, *, model: str = "claude-opus-5-5"):
    """Run execute_prevalidated against a scripted governed subprocess and return (response, call)."""
    call: dict = {}

    def fake_run_governed(argv, *, timeout, input_text, cwd, env, log_prefix):
        """Record the governed call and return the scripted result document."""
        call.update(argv=argv, input_text=input_text, env=env, cwd=cwd, log_prefix=log_prefix)
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr("sage.executors.claude_cli.run_governed", fake_run_governed)
    executor = ClaudeCLIExecutor(command="claude")
    request = ProviderRequest(prompt=PROMPT, schema=SCHEMA, model=model, reasoning_effort="medium")
    return executor.execute_prevalidated(request, _ready_status()), call


def test_environment_never_carries_api_credentials_or_cloud_routes(monkeypatch):
    """An API key in the parent environment would silently replace the subscription in -p mode."""
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                 "CLAUDE_CODE_EFFORT_LEVEL", "ANTHROPIC_BASE_URL", "CLAUDECODE"):
        monkeypatch.setenv(name, "set-by-parent")
    monkeypatch.setenv("USER", "operator")
    env = ClaudeCLIExecutor._environment()
    assert not any(key.upper().startswith(("ANTHROPIC_", "CLAUDE_CODE_")) or key.upper() == "CLAUDECODE" for key in env)
    assert env["USER"] == "operator"
    assert env["DISABLE_AUTOUPDATER"] == "1"


def test_subscription_login_is_ready_and_keeps_only_the_plan_type():
    """A claude.ai login is accepted; the account e-mail and organization never enter SAGE state."""
    status = _quick_executor("2.1.307 (Claude Code)", SUBSCRIPTION).quick_status()
    assert status.ready and status.auth_mode == "CLAUDE_SUBSCRIPTION"
    assert status.account_plan_type == "team"
    rendered = json.dumps(status.to_dict())
    assert "operator@example.org" not in rendered and "org-1" not in rendered


@pytest.mark.parametrize("method", ["api_key", "oauth_token", "api_key_helper", "third_party"])
def test_non_subscription_authentication_is_refused(method):
    """API-key, token, helper, and cloud-provider authentication are never accepted."""
    status = _quick_executor("2.1.307 (Claude Code)", {**SUBSCRIPTION, "authMethod": method}).quick_status()
    assert not status.ready
    assert method in status.diagnostic


def test_signed_out_cli_is_not_ready():
    """`claude auth status` exits 1 with authMethod none when signed out."""
    status = _quick_executor("2.1.307 (Claude Code)", {"loggedIn": False, "authMethod": "none"}, 1).quick_status()
    assert not status.ready and "not signed in" in status.diagnostic


def test_cli_older_than_restricted_mode_is_not_ready():
    """Governed calls depend on --restricted, so an older CLI must be updated first."""
    status = _quick_executor("2.1.200 (Claude Code)", SUBSCRIPTION).quick_status()
    assert not status.ready and "2.1.248" in status.diagnostic


def test_missing_cli_reports_install_guidance():
    """No resolvable CLI is reported as unavailable with the official installer command."""
    executor = ClaudeCLIExecutor(command="claude")
    executor.command = None
    status = executor.quick_status()
    assert not status.available and "claude.ai/install" in status.diagnostic


def test_status_rejects_models_and_reasoning_outside_the_reviewed_catalog():
    """The reviewed catalog is the only source of routable Claude models and efforts."""
    executor = _quick_executor("2.1.307 (Claude Code)", SUBSCRIPTION)
    assert executor.status(model="claude-opus-5-5", reasoning_effort="medium").ready
    assert not executor.status(model="claude-unknown-9").ready
    assert not executor.status(model="claude-opus-5-5", reasoning_effort="minimal").ready


def test_catalog_lists_efforts_in_progression_order_with_one_default():
    """Every reviewed model keeps provider progression order and exactly one model is default."""
    models = load_catalog()
    assert sum(item.is_default for item in models) == 1
    for item in models:
        assert item.reasoning_efforts == ("low", "medium", "high", "xhigh", "max")


def test_governed_arguments_disable_tools_settings_and_sessions():
    """The sealed call has no tools, settings, MCP, session state, or subscription-ignoring --bare."""
    args = ClaudeCLIExecutor.governed_args(SCHEMA, "claude-opus-5-5", "medium")
    assert args[0] == "-p"
    for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == ""
    assert args[args.index("--max-turns") + 1] == "1"
    assert args[args.index("--effort") + 1] == "medium"
    assert json.loads(args[args.index("--json-schema") + 1]) == SCHEMA
    assert "--bare" not in args
    assert "--effort" not in ClaudeCLIExecutor.governed_args(SCHEMA, "claude-opus-5-5", "provider-default")


def test_successful_execution_returns_structured_output_and_usage(monkeypatch):
    """The prompt goes on stdin, the answer comes from structured_output, and usage is recorded."""
    response, call = _execute(monkeypatch, _result())
    assert call["input_text"] == PROMPT
    assert PROMPT not in " ".join(call["argv"])
    assert call["log_prefix"] == "claude"
    assert json.loads(response.content) == {"status": "OK"}
    assert (response.provider, response.model, response.reasoning_effort) == ("claude", "claude-opus-5-5", "medium")
    assert response.metadata["usage"]["output_tokens"] == 52
    assert response.metadata["auth_mode"] == "CLAUDE_SUBSCRIPTION"


def test_signed_out_execution_asks_for_subscription_sign_in(monkeypatch):
    """The observed 'Not logged in' result becomes an Operator-input error, not a task failure."""
    stdout = _result(is_error=True, terminal_reason="api_error", result="Not logged in · Please run /login",
                     structured_output=None, modelUsage={})
    with pytest.raises(ValidationError) as caught:
        _execute(monkeypatch, stdout, 1)
    assert caught.value.code == "CLAUDE_SUBSCRIPTION_AUTH_REQUIRED"


def test_subscription_usage_limit_is_rate_limited_with_reset_hint(monkeypatch):
    """A session/weekly limit is a rate limit the NCA and Run layers already back off from."""
    stdout = _result(is_error=True, api_error_status=429, result="You've hit your session limit · resets 3pm (Europe/London)",
                     structured_output=None, modelUsage={})
    with pytest.raises(ValidationError) as caught:
        _execute(monkeypatch, stdout, 1)
    assert caught.value.code == "LLM_PROVIDER_RATE_LIMITED"
    assert caught.value.details["kind"] == "USAGE_LIMIT"
    assert caught.value.details["retry_at"] == "3pm (Europe/London)"


def test_bare_http_429_is_a_token_rate_limit(monkeypatch):
    """A 429 without limit wording is still classified as a rate limit."""
    stdout = _result(is_error=True, api_error_status=429, result="API Error: 429 rate_limit_error",
                     structured_output=None, modelUsage={})
    with pytest.raises(ValidationError) as caught:
        _execute(monkeypatch, stdout, 1)
    assert caught.value.code == "LLM_PROVIDER_RATE_LIMITED"
    assert caught.value.details["kind"] == "TOKEN_RATE_LIMIT"


def test_unknown_model_result_is_provider_not_ready(monkeypatch):
    """The observed 404 unknown-model result is a configuration problem, not a task failure."""
    stdout = _result(is_error=True, api_error_status=404, structured_output=None, modelUsage={},
                     result="There's an issue with the selected model (claude-opus-5-5).")
    with pytest.raises(ValidationError) as caught:
        _execute(monkeypatch, stdout, 1)
    assert caught.value.code == "LLM_PROVIDER_NOT_READY"


def test_answer_from_another_model_is_a_route_mismatch(monkeypatch):
    """A response produced by any model other than the routed one is rejected."""
    stdout = _result(modelUsage={"claude-sonnet-5-5": {"outputTokens": 52}})
    with pytest.raises(ValidationError) as caught:
        _execute(monkeypatch, stdout)
    assert caught.value.code == "LLM_RESPONSE_ROUTE_MISMATCH"


def test_missing_structured_output_fails_the_attempt(monkeypatch):
    """A run that ends without schema-valid output is a failed attempt."""
    stdout = _result(structured_output=None, terminal_reason="max_turns")
    with pytest.raises(ValidationError) as caught:
        _execute(monkeypatch, stdout)
    assert caught.value.code == "LLM_PROVIDER_EXECUTION_FAILED"
    assert "max_turns" in str(caught.value)


def test_unparseable_output_never_echoes_the_sealed_prompt(monkeypatch):
    """Diagnostics from a crashed CLI omit the sealed governed prompt."""
    with pytest.raises(ValidationError) as caught:
        _execute(monkeypatch, f"panic while handling {PROMPT}", 1)
    assert caught.value.code == "LLM_PROVIDER_EXECUTION_FAILED"
    assert PROMPT not in str(caught.value)


def test_timeout_is_a_provider_timeout(monkeypatch):
    """A governed call that outlives its budget is reported as LLM_PROVIDER_TIMEOUT."""
    def fake_run_governed(argv, **kwargs):
        """Simulate a governed call that outlives its timeout."""
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr("sage.executors.claude_cli.run_governed", fake_run_governed)
    request = ProviderRequest(prompt=PROMPT, schema=SCHEMA, model="claude-opus-5-5", reasoning_effort="medium",
                              timeout_seconds=5)
    with pytest.raises(ValidationError) as caught:
        ClaudeCLIExecutor(command="claude").execute_prevalidated(request, _ready_status())
    assert caught.value.code == "LLM_PROVIDER_TIMEOUT"


def test_windows_desktop_app_aliases_are_not_the_cli(monkeypatch):
    """App-execution aliases and the desktop app folder never resolve as the governed CLI."""
    monkeypatch.setattr(ClaudeCLIExecutor, "_is_windows", staticmethod(lambda: True))
    assert ClaudeCLIExecutor._cli_candidate(r"C:\Users\op\AppData\Local\Microsoft\WindowsApps\claude.exe") is None
    assert ClaudeCLIExecutor._cli_candidate(r"C:\Users\op\AppData\Local\AnthropicClaude\claude.exe") is None
    assert ClaudeCLIExecutor._cli_candidate(r"C:\Users\op\.local\bin\claude.exe") == r"C:\Users\op\.local\bin\claude.exe"
