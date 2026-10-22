"""One selected provider for all governed LLM work: Claude selection, gating, and provider-neutral surfaces.

Claude is implemented but not yet enabled by the 0.02b1 build policy; tests that exercise a
Claude selection enable it by patching the build policy, exactly as a later release would.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage import build_policy
from sage.errors import ConfigurationError
from sage.executors import ProviderResponse, ProviderStatus, receipt_transport_policy
from sage.executors.claude_cli import ClaudeCLIExecutor
from sage.llm_settings import load_llm_settings, settings_path, update_llm_selection
from sage.model_service import ModelService
from sage.sqs_provider_coverage import SAGE_PROVIDER_TO_EXECUTION_CHANNEL, sqs_execution_channel_ids
from sage.ui_services import OperatorUIService


@pytest.fixture
def claude_enabled(monkeypatch):
    """Enable Claude for automated execution as a later build policy would."""
    monkeypatch.setattr(build_policy, "ENABLED_AUTOMATED_PROVIDER_IDS", ("codex", "claude"))


def _root(tmp_path: Path) -> Path:
    """Return an empty SAGE Core root for settings-only tests."""
    root = tmp_path / "SAGE" / "app"
    root.mkdir(parents=True)
    return root


def test_claude_is_implemented_but_not_selectable_in_this_build(tmp_path):
    """The 0.02b1 build keeps Codex the only selectable provider."""
    root = _root(tmp_path)
    assert "claude" in build_policy.IMPLEMENTED_PROVIDER_IDS
    assert not build_policy.provider_is_enabled("claude")
    with pytest.raises(ConfigurationError, match="disabled by the 0.02b1 build policy"):
        update_llm_selection(root, provider="claude", auto=True)


def test_a_persisted_claude_selection_falls_back_to_codex_while_claude_is_disabled(tmp_path):
    """A settings file naming a disabled provider never routes work to it."""
    root = _root(tmp_path)
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"selected_provider": "claude"}), encoding="utf-8")
    assert load_llm_settings(root)["selected_provider"] == "codex"


def test_claude_selection_persists_and_carries_no_model_or_credentials(tmp_path, claude_enabled):
    """Selecting Claude stores only the provider choice; model and reasoning stay with routing."""
    root = _root(tmp_path)
    value = update_llm_selection(root, provider="claude", auto=True)
    assert value["selected_provider"] == "claude"
    assert load_llm_settings(root)["providers"]["claude"] == {"enabled": True}
    assert load_llm_settings(root)["policy"]["provider_api_keys"] == "PROHIBITED"
    with pytest.raises(ConfigurationError, match="does not accept an endpoint"):
        update_llm_selection(root, provider="claude", endpoint="http://127.0.0.1:1")


def test_credential_fields_are_rejected_for_claude_settings(tmp_path):
    """A token or key smuggled into the Claude provider block fails closed."""
    root = _root(tmp_path)
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"selected_provider": "codex", "providers": {"claude": {"token": "x"}}}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="must not contain API keys"):
        load_llm_settings(root)


def test_routing_probes_only_the_selected_provider(tmp_path, claude_enabled, monkeypatch):
    """With one selected provider, the other governed provider never contributes a route."""
    root = _root(tmp_path)
    update_llm_selection(root, provider="claude", auto=True)
    probed: list[str] = []

    def fake_probe(self, provider, **_kwargs):
        """Record which provider was probed."""
        probed.append(provider)
        return ProviderStatus(provider=provider, available=True, ready=True), None

    monkeypatch.setattr(ModelService, "probe", fake_probe)
    statuses = ModelService(root)._routing_statuses()  # noqa: SLF001 - routing contract
    assert probed == ["claude"]
    assert [status.provider for status in statuses] == ["claude"]


def test_signing_in_to_a_disabled_provider_does_not_select_it(tmp_path, monkeypatch):
    """Claude sign-in can be verified ahead of enablement without moving governed work off Codex."""
    root = _root(tmp_path)
    monkeypatch.setattr(
        ClaudeCLIExecutor,
        "connect",
        lambda self, *, device_auth=False: ProviderStatus(provider="claude", available=True, ready=True,
                                                         auth_mode="CLAUDE_SUBSCRIPTION"),
    )
    result = ModelService(root).connect_provider("claude")
    assert result["provider"] == "claude" and result["provider_label"] == "Anthropic / Claude"
    assert result["selected_provider"] == "codex"


def test_receipt_policy_names_the_catalog_source_and_prohibits_keys():
    """Receipts record a live Codex catalog but a reviewed static Claude catalog."""
    claude = receipt_transport_policy("claude")
    assert claude["provider_api_keys"] == "PROHIBITED"
    assert claude["provider_catalog"] == "REVIEWED_STATIC"
    assert claude["filesystem_writes_by_provider"] is False
    assert receipt_transport_policy("codex")["provider_catalog"] == "LIVE"


def test_startup_next_step_names_the_selected_provider(make_workspace, claude_enabled):
    """Setup asks to install or sign in to Claude Code, not Codex, when Claude is selected."""
    root = make_workspace(configured=True)
    update_llm_selection(root, provider="claude", auto=True)
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")
    assert service.startup_next_step({"available": False}, set(), {}) == (
        "INSTALL_PROVIDER_CLI",
        "Install Claude Code CLI",
    )
    assert service.startup_next_step({"available": True, "ready": False}, set(), {}) == (
        "SIGN_IN_PROVIDER",
        "Sign in with Claude subscription",
    )


def test_claude_has_a_registered_sqs_execution_channel():
    """Onboarding Claude records both the SAGE mapping and the SQS channel descriptor."""
    assert SAGE_PROVIDER_TO_EXECUTION_CHANNEL["claude"] == "claude_workspace"
    assert "claude_workspace" in sqs_execution_channel_ids()


def test_sqs_bridge_reports_claude_token_usage():
    """Claude results carry prompt (including cache) and output token counts into SQS."""
    from sage.sqs_provider_bridge import WorkspaceProviderAdapter, ensure_sage_sqs_importable

    assert ensure_sage_sqs_importable(Path(__file__).resolve().parents[2]) is True

    class FakeClaude:
        """Return one Claude response with usage metadata."""

        provider_id = "claude"

        def execute(self, request):
            """Answer every request with a fixed structured result."""
            return ProviderResponse(
                provider="claude", model=request.model, content='{"ok": true}',
                metadata={"usage": {"input_tokens": 2, "cache_creation_input_tokens": 1184,
                                    "cache_read_input_tokens": 10, "output_tokens": 123}},
            )

    adapter = WorkspaceProviderAdapter(FakeClaude())
    result = adapter.execute(model_id="claude-opus-5-5", reasoning="medium", prompt="check")
    assert adapter.execution_channel == "claude_workspace"
    assert (result.input_tokens, result.output_tokens) == (1196, 123)
