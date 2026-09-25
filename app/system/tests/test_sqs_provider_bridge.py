"""CodexCLIExecutor-backed SQS ProviderAdapter bridge (Codex-workspace provider plan)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sage.errors import ValidationError
from sage.executors.base import ModelCapability, ProviderStatus, ReasoningEffortOption
from sage.executors.codex_cli import CodexCLIExecutor
from sage.sqs_provider_bridge import CodexWorkspaceProviderAdapter, ensure_sage_sqs_importable

_APP_ROOT = Path(__file__).resolve().parents[2]


def _fake_ready_status() -> ProviderStatus:
    """Return a minimal ready ChatGPT status for one governed model, mirroring the rate-limit tests."""
    capability = ModelCapability(
        id="gpt-5.6-sol", model="gpt-5.6-sol", display_name="GPT-5.6 Sol",
        supported_reasoning_efforts=(ReasoningEffortOption("medium"),),
        default_reasoning_effort="medium", is_default=True,
    )
    return ProviderStatus(
        provider="codex", available=True, ready=True, auth_mode="CHATGPT",
        model_capabilities=(capability,), selected_model="gpt-5.6-sol",
    )


def _executor_with_fake_run(stdout: str, *, returncode: int = 0) -> CodexCLIExecutor:
    """Return a CodexCLIExecutor whose subprocess call always returns scripted output."""
    executor = CodexCLIExecutor(command="codex")

    def fake_run(args, **_kwargs):
        """Simulate one codex exec invocation with scripted output."""
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    executor._run_governed = fake_run
    executor.status = lambda **_kwargs: _fake_ready_status()
    return executor


def test_ensure_sage_sqs_importable_adds_the_sibling_checkout_in_this_repo():
    """Against this real monorepo checkout, the sibling services/sqs/src path makes sage_sqs importable."""
    completed = subprocess.run(
        [sys.executable, "-c", (
            "import sys; sys.path.insert(0, %r)\n"
            "from sage.sqs_provider_bridge import ensure_sage_sqs_importable\n"
            "assert ensure_sage_sqs_importable(%r) is True\n"
            "import sage_sqs.evaluation.runner  # noqa: F401\n"
            "print('OK')\n"
        ) % (str(_APP_ROOT / "system" / "src"), str(_APP_ROOT))],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout


def test_ensure_sage_sqs_importable_returns_false_without_a_sibling_checkout(tmp_path):
    """A root with no services/sqs sibling reports sage_sqs as not importable, without raising."""
    completed = subprocess.run(
        [sys.executable, "-c", (
            "import sys; sys.path.insert(0, %r)\n"
            "from sage.sqs_provider_bridge import ensure_sage_sqs_importable\n"
            "assert ensure_sage_sqs_importable(%r) is False\n"
            "print('OK')\n"
        ) % (str(_APP_ROOT / "system" / "src"), str(tmp_path / "app"))],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout


def test_adapter_executes_through_codex_cli_executor_and_returns_a_provider_result():
    """The bridge runs a prompt through CodexCLIExecutor and returns an sage_sqs ProviderResult."""
    assert ensure_sage_sqs_importable(_APP_ROOT) is True
    from sage_sqs.providers.base import ProviderResult

    executor = _executor_with_fake_run('{"finding": {"material": false, "relation": "none"}}')
    adapter = CodexWorkspaceProviderAdapter(executor)

    result = adapter.execute(model_id="gpt-5.6-sol", reasoning="medium", prompt="check this")

    assert isinstance(result, ProviderResult)
    assert result.text == '{"finding": {"material": false, "relation": "none"}}'
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.usage_raw["returncode"] == 0


def test_adapter_propagates_a_provider_failure_for_the_worker_to_catch():
    """A Codex execution failure raises SAGE's own ValidationError, which the SQS worker already catches broadly."""
    assert ensure_sage_sqs_importable(_APP_ROOT) is True
    executor = _executor_with_fake_run("Codex crashed: invalid sandbox configuration", returncode=1)
    adapter = CodexWorkspaceProviderAdapter(executor)

    try:
        adapter.execute(model_id="gpt-5.6-sol", reasoning="medium", prompt="check this")
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "LLM_PROVIDER_EXECUTION_FAILED"
