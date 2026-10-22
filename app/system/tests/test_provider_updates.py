"""Provider CLI update-check contracts: cached, non-blocking, and never fatal."""

from __future__ import annotations

import io
import subprocess

import pytest

from sage.errors import ValidationError
from sage.executors.codex_cli import CodexCLIExecutor
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.provider_updates import compare_codex_version, latest_codex_release, parse_cli_version


def test_versions_parse_from_cli_text_and_release_tags() -> None:
    """Both `codex --version` output and `rust-v` release tags yield comparable triples."""
    assert parse_cli_version("codex-cli 0.163.0") == (0, 163, 0)
    assert parse_cli_version("rust-v0.164.2") == (0, 164, 2)
    assert parse_cli_version("unknown") is None


def test_update_is_available_only_when_latest_is_newer() -> None:
    """Equal, older, and unparseable versions never offer an update."""
    assert compare_codex_version("codex-cli 0.163.0", "0.164.0", "LIVE").update_available is True
    assert compare_codex_version("codex-cli 0.163.0", "0.163.0", "LIVE").update_available is False
    assert compare_codex_version("codex-cli 0.170.0", "0.164.0", "LIVE").update_available is False
    assert compare_codex_version(None, "0.164.0", "LIVE").update_available is False
    assert compare_codex_version("codex-cli 0.163.0", None, "UNAVAILABLE").summary() == "Update check unavailable"


def test_latest_release_is_cached_and_failures_fall_back_quietly(make_workspace) -> None:
    """A fresh cache avoids the network; a failed fetch keeps the last known release or reports none."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    calls: list[int] = []

    def fetch() -> str:
        """Count network lookups and return a release tag."""
        calls.append(1)
        return "rust-v0.164.0"

    now = [1_000_000.0]
    assert latest_codex_release(root, fetch=fetch, clock=lambda: now[0]) == ("0.164.0", "LIVE")
    assert latest_codex_release(root, fetch=fetch, clock=lambda: now[0] + 60) == ("0.164.0", "CACHE")
    assert len(calls) == 1

    def offline() -> str:
        """Simulate a host without network access."""
        raise OSError("offline")

    expired = now[0] + 13 * 3600
    assert latest_codex_release(root, fetch=offline, clock=lambda: expired) == ("0.164.0", "CACHE")


def test_latest_release_without_cache_or_network_is_unavailable(make_workspace) -> None:
    """With no cache and no network the check reports unavailable instead of raising."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")

    def offline() -> str:
        """Simulate a host without network access."""
        raise OSError("offline")

    assert latest_codex_release(root, fetch=offline) == (None, "UNAVAILABLE")
    assert latest_codex_release(root) == (None, "UNAVAILABLE")  # disabled by the test environment


def test_codex_update_runs_update_subcommand_without_a_prompt(monkeypatch, tmp_path) -> None:
    """The update runs `codex update` with no stdin and re-verifies the CLI afterwards."""
    codex = tmp_path / "codex"
    codex.write_text("fake", encoding="utf-8")
    calls: list[tuple[list[str], dict]] = []

    def fake_run(args, **kwargs):
        """Answer update, version, and login calls like a working Codex CLI."""
        argv = [str(item) for item in args]
        calls.append((argv, kwargs))
        if argv[-1] == "update":
            return subprocess.CompletedProcess(args, 0, stdout="updated", stderr="")
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(args, 0, stdout="codex-cli 0.164.0\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="Logged in using ChatGPT\n", stderr="")

    monkeypatch.setattr("sage.executors.codex_cli.subprocess.run", fake_run)
    status = CodexCLIExecutor(command=str(codex)).update()

    assert status.version == "codex-cli 0.164.0"
    update_call = next(item for item in calls if item[0][-1] == "update")
    assert update_call[1]["stdin"] is subprocess.DEVNULL


def test_codex_update_failure_names_the_manual_path(monkeypatch, tmp_path) -> None:
    """A failed update surfaces the CLI output and the manual install guidance."""
    codex = tmp_path / "codex"
    codex.write_text("fake", encoding="utf-8")
    monkeypatch.setattr(
        "sage.executors.codex_cli.subprocess.run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, stdout="", stderr="permission denied"),
    )
    with pytest.raises(ValidationError) as caught:
        CodexCLIExecutor(command=str(codex)).update()
    assert caught.value.code == "CODEX_UPDATE_FAILED"
    assert "permission denied" in caught.value.message


def test_update_menu_action_asks_before_updating(make_workspace, monkeypatch) -> None:
    """The Configure AI action shows the versions and updates only after the operator agrees."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["n", "y"]), output=io.StringIO()),
        skip_setup=True,
    )
    monkeypatch.setattr(
        "sage.menu.latest_codex_release", lambda root, force=False: ("0.164.0", "LIVE")
    )
    versions = iter(["codex-cli 0.163.0", "codex-cli 0.163.0", "codex-cli 0.164.0"])
    center._setup_model_probe = lambda *a, **k: {  # noqa: SLF001
        "available": True, "ready": True, "provider_id": "codex", "version": next(versions)
    }

    class FakeService:
        """Count update requests that reach the service."""

        def selected_provider(self):
            """Report Codex as the selected governed provider."""
            return "codex"

        updates = 0

        def update_provider(self, _provider=None):
            """Record one update request."""
            self.updates += 1
            return {}

        def list_models(self, _provider):
            """Return the refreshed listing with one new model recorded by the snapshot."""
            return {"catalog_changes": {"detected_utc": "2026-10-21T10:00:00Z", "added_models": ["gpt-new"]}}

    service = FakeService()
    center._update_provider_cli(service)  # noqa: SLF001 - operator declines
    assert service.updates == 0
    center._update_provider_cli(service)  # noqa: SLF001 - operator agrees
    assert service.updates == 1
    rendered = center.io.output.getvalue()
    assert "0.163.0 -> 0.164.0" in rendered
    assert "Codex CLI: codex-cli 0.164.0" in rendered
    assert "New models: gpt-new" in rendered
