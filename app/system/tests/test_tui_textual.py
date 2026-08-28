"""Headless Textual interaction tests for the Alpha TUI when Textual is installed."""

from __future__ import annotations

import asyncio
import importlib.util

import pytest

TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None
pytestmark = pytest.mark.skipif(
    not TEXTUAL_AVAILABLE,
    reason="Textual is an optional TUI dependency and is not installed on this host",
)

from sage.runtime_status import RuntimeStatus
from sage.ui_services import OperatorUIService, probe_workflow_ai

if TEXTUAL_AVAILABLE:
    from sage.tui import SageTUIApp


def test_tui_keyboard_and_mouse_navigation_preserve_position_across_status(make_workspace) -> None:
    """Verify tui keyboard and mouse navigation preserve position across status."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    runtime = RuntimeStatus(interface_language="en-US")
    probe_workflow_ai(root, runtime, refresh=True, dry_run_provider=True)
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml", runtime_status=runtime)
    app = SageTUIApp(service)

    async def exercise() -> None:
        """Exercise the mounted TUI through its headless Textual pilot."""
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.click("#nav-bic")
            assert app.current_view == "bic"
            await pilot.press("f")
            assert app.current_view == "bic"
            await pilot.press("escape")
            assert app.current_view == "bic"
            await pilot.press("a")
            assert app.current_view == "main"
            await pilot.click("#nav-projects")
            assert app.current_view == "projects"
            await pilot.click("#footer-home")
            assert app.current_view == "main"

    asyncio.run(exercise())


def test_tui_language_modal_changes_interface_without_losing_current_view(make_workspace) -> None:
    """Verify tui language modal changes interface without losing current view."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")
    app = SageTUIApp(service)

    async def exercise() -> None:
        """Exercise the mounted TUI through its headless Textual pilot."""
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.click("#nav-saw")
            assert app.current_view == "saw"
            await pilot.press("d")
            await pilot.click("#lang-fr")
            assert app.current_view == "saw"
            assert service.localizer.language == "fr"

    asyncio.run(exercise())
