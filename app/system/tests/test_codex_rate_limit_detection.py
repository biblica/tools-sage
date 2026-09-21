"""Codex provider-call rate-limit detection (integration plan Task 3a).

Message text is quoted verbatim from confirmed real Codex CLI failure
reports, not fabricated: usage-limit exhaustion and short per-model token
rate limits are two distinct, real failure shapes.
"""
from __future__ import annotations

import subprocess

from sage.errors import ValidationError
from sage.executors.base import ModelCapability, ProviderRequest, ProviderStatus, ReasoningEffortOption
from sage.executors.codex_cli import CodexCLIExecutor


def _fake_ready_status() -> ProviderStatus:
    """Return a minimal ready ChatGPT status for one governed model."""
    capability = ModelCapability(
        id="gpt-5.6-sol",
        model="gpt-5.6-sol",
        display_name="GPT-5.6 Sol",
        supported_reasoning_efforts=(ReasoningEffortOption("medium"),),
        default_reasoning_effort="medium",
        is_default=True,
    )
    return ProviderStatus(
        provider="codex",
        available=True,
        ready=True,
        auth_mode="CHATGPT",
        model_capabilities=(capability,),
        selected_model="gpt-5.6-sol",
    )


def _executor_with_fake_run(stdout: str, stderr: str = "") -> CodexCLIExecutor:
    """Return a CodexCLIExecutor whose subprocess call always returns the given failed output."""
    executor = CodexCLIExecutor(command="codex")

    def fake_run(args, **_kwargs):
        """Simulate a failed (returncode 1) codex exec invocation with scripted output."""
        return subprocess.CompletedProcess(args, 1, stdout=stdout, stderr=stderr)

    executor._run_governed = fake_run
    return executor


def test_classifies_usage_limit_exhaustion():
    """A real 'usage limit' failure message is classified as USAGE_LIMIT with its retry-at hint."""
    text = (
        "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
        "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again "
        "at Mar 20th, 2027 3:36 PM."
    )
    result = CodexCLIExecutor._classify_rate_limit(text)
    assert result["kind"] == "USAGE_LIMIT"
    assert result["retry_at"] == "Mar 20th, 2027 3:36 PM"
    assert result["retry_after_seconds"] is None


def test_classifies_token_rate_limit_with_seconds_hint():
    """A real per-model token rate-limit message is classified with its retry-after-seconds hint."""
    text = (
        "Rate limit reached for o4-mini in organization org-mdt28vhrVuhXiMZEnjyLSjcV on tokens "
        "per min (TPM): Limit 200000, Used 162582, Requested 45297. Please try again in 2.363s."
    )
    result = CodexCLIExecutor._classify_rate_limit(text)
    assert result["kind"] == "TOKEN_RATE_LIMIT"
    assert result["retry_after_seconds"] == 2.363


def test_does_not_classify_an_unrelated_failure_as_rate_limited():
    """A generic, unrelated Codex failure is not misclassified as a rate limit."""
    assert CodexCLIExecutor._classify_rate_limit("Codex crashed: invalid sandbox configuration") is None


def test_execute_prevalidated_raises_a_distinct_code_for_a_usage_limit_failure():
    """A real usage-limit failure surfaces as CODEX_RATE_LIMITED, not the generic execution-failed code."""
    executor = _executor_with_fake_run(
        "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to purchase "
        "more credits or try again at Mar 20th, 2027 3:36 PM."
    )
    try:
        executor.execute_prevalidated(
            ProviderRequest(prompt="bounded prompt", schema={"type": "object"}, model="gpt-5.6-sol"),
            _fake_ready_status(),
        )
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "CODEX_RATE_LIMITED"
        assert exc.details["kind"] == "USAGE_LIMIT"


def test_execute_prevalidated_still_raises_the_generic_code_for_an_unrelated_failure():
    """An unrelated Codex failure keeps the existing generic error code, unaffected by this change."""
    executor = _executor_with_fake_run("Codex crashed: invalid sandbox configuration")
    try:
        executor.execute_prevalidated(
            ProviderRequest(prompt="bounded prompt", schema={"type": "object"}, model="gpt-5.6-sol"),
            _fake_ready_status(),
        )
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "LLM_PROVIDER_EXECUTION_FAILED"


_TOKEN_RATE_LIMIT_TEXT = (
    "Rate limit reached for o4-mini in organization org-mdt28vhrVuhXiMZEnjyLSjcV on tokens "
    "per min (TPM): Limit 200000, Used 162582, Requested 45297. Please try again in 2.363s."
)


def _executor_with_scripted_runs(*results, monkeypatch) -> CodexCLIExecutor:
    """Return an executor whose successive _run_governed calls yield the given results in order.

    Also stubs out time.sleep so a scripted bounded wait never actually blocks the test.
    """
    import sage.executors.codex_cli as codex_cli_module

    monkeypatch.setattr(codex_cli_module.time, "sleep", lambda _seconds: None)
    executor = CodexCLIExecutor(command="codex")
    remaining = list(results)

    def fake_run(args, **_kwargs):
        """Return the next scripted (returncode, stdout, stderr) result for this call."""
        returncode, stdout, stderr = remaining.pop(0)
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)

    executor._run_governed = fake_run
    return executor


def test_execute_prevalidated_auto_retries_a_short_token_rate_limit_once(monkeypatch):
    """A short, bounded per-model token rate limit is retried once and can still succeed."""
    executor = _executor_with_scripted_runs(
        (1, "", _TOKEN_RATE_LIMIT_TEXT),
        (0, '{"result": "ok"}', ""),
        monkeypatch=monkeypatch,
    )
    response = executor.execute_prevalidated(
        ProviderRequest(prompt="bounded prompt", schema={"type": "object"}, model="gpt-5.6-sol"),
        _fake_ready_status(),
    )
    assert response.metadata["returncode"] == 0


def test_execute_prevalidated_gives_up_after_one_auto_retry(monkeypatch):
    """A token rate limit that persists through the one auto-retry still fails closed."""
    executor = _executor_with_scripted_runs(
        (1, "", _TOKEN_RATE_LIMIT_TEXT),
        (1, "", _TOKEN_RATE_LIMIT_TEXT),
        monkeypatch=monkeypatch,
    )
    try:
        executor.execute_prevalidated(
            ProviderRequest(prompt="bounded prompt", schema={"type": "object"}, model="gpt-5.6-sol"),
            _fake_ready_status(),
        )
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "CODEX_RATE_LIMITED"
        assert exc.details["kind"] == "TOKEN_RATE_LIMIT"


def test_execute_prevalidated_never_auto_retries_a_usage_limit_failure(monkeypatch):
    """Usage-limit exhaustion (potentially hours away) never gets an automatic retry."""
    import sage.executors.codex_cli as codex_cli_module

    calls: list[float] = []
    monkeypatch.setattr(codex_cli_module.time, "sleep", lambda seconds: calls.append(seconds))
    executor = _executor_with_fake_run(
        "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to purchase "
        "more credits or try again at Mar 20th, 2027 3:36 PM."
    )
    try:
        executor.execute_prevalidated(
            ProviderRequest(prompt="bounded prompt", schema={"type": "object"}, model="gpt-5.6-sol"),
            _fake_ready_status(),
        )
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "CODEX_RATE_LIMITED"
        assert exc.details["kind"] == "USAGE_LIMIT"
    assert calls == []


def test_execute_prevalidated_never_auto_retries_past_the_bounded_ceiling(monkeypatch):
    """A token rate limit reporting a wait longer than the small ceiling is not auto-retried."""
    import sage.executors.codex_cli as codex_cli_module

    calls: list[float] = []
    monkeypatch.setattr(codex_cli_module.time, "sleep", lambda seconds: calls.append(seconds))
    long_wait_text = (
        "Rate limit reached for o4-mini in organization org-mdt28vhrVuhXiMZEnjyLSjcV on tokens "
        "per min (TPM): Limit 200000, Used 162582, Requested 45297. Please try again in 90.0s."
    )
    executor = _executor_with_fake_run(long_wait_text)
    try:
        executor.execute_prevalidated(
            ProviderRequest(prompt="bounded prompt", schema={"type": "object"}, model="gpt-5.6-sol"),
            _fake_ready_status(),
        )
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "CODEX_RATE_LIMITED"
    assert calls == []
