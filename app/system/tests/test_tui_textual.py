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
    from sage.tui import InfoModal, LanguageModal, ProjectRootModal, SageTUIApp, StatusModal


def test_tui_keyboard_and_mouse_navigation_preserve_position_across_status(
    make_workspace,
    monkeypatch,
) -> None:
    """Verify tui keyboard and mouse navigation preserve position across status."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    runtime = RuntimeStatus(interface_language="en-US")
    probe_workflow_ai(root, runtime, refresh=True, dry_run_provider=True)
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml", runtime_status=runtime)
    readiness = service.startup_readiness
    monkeypatch.setattr(
        service,
        "startup_readiness",
        lambda *args, **kwargs: {**readiness(*args, **kwargs), "status": "READY"},
    )
    app = SageTUIApp(service, live_ai=False)

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


def test_tui_menu_controls_use_sentence_case_and_protocol_entities(make_workspace) -> None:
    """Keep TUI menu capitalization aligned with the classic menu contract."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")
    app = SageTUIApp(service, live_ai=False)

    async def exercise() -> None:
        """Inspect the rendered navigation and action labels."""
        async with app.run_test(size=(100, 30)):
            assert str(app.query_one("#nav-projects").label) == "  1. Scripture PROJECTS"
            assert str(app.query_one("#action-set-root").label) == "P. Set PROJECTS root"
            assert str(app.query_one("#action-quick-scan").label) == "Q. Quick scan"
            assert str(app.query_one("#footer-home").label) == "B. Main menu"

    asyncio.run(exercise())


def test_tui_language_modal_changes_interface_without_losing_current_view(
    make_workspace,
    monkeypatch,
) -> None:
    """Verify tui language modal changes interface without losing current view."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")
    readiness = service.startup_readiness
    monkeypatch.setattr(
        service,
        "startup_readiness",
        lambda *args, **kwargs: {**readiness(*args, **kwargs), "status": "READY"},
    )
    app = SageTUIApp(service, live_ai=False)

    async def exercise() -> None:
        """Exercise the mounted TUI through its headless Textual pilot."""
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.click("#nav-rtc")
            assert app.current_view == "rtc"
            await pilot.press("d")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "LanguageModal"
            app.screen.query_one("#lang-fr").focus()
            await pilot.press("enter")
            await pilot.pause()
            assert app.current_view == "rtc"
            assert service.localizer.language == "fr"

    asyncio.run(exercise())


def test_tui_controls_and_status_modal_stay_inside_a_narrow_viewport(make_workspace) -> None:
    """Catch fixed widget widths pushing navigation or information blocks off-screen."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")
    app = SageTUIApp(service, live_ai=False)

    async def exercise() -> None:
        """Measure mounted widgets against the actual narrow screen boundary."""
        async with app.run_test(size=(60, 24)) as pilot:
            screen_width = app.screen.size.width
            overflowing = [
                widget.id
                for widget in app.screen.query("Button")
                if widget.region.x < 0 or widget.region.right > screen_width
            ]
            assert overflowing == []

            await pilot.press("f")
            dialog = app.screen.query_one("#modal-dialog")
            assert dialog.region.x >= 0
            assert dialog.region.right <= app.screen.size.width

    asyncio.run(exercise())


def test_all_tui_modals_stay_inside_a_40_by_20_viewport(make_workspace) -> None:
    """Catch fixed modal dimensions and action buttons escaping either screen axis."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")
    app = SageTUIApp(service, live_ai=False)

    async def exercise() -> None:
        """Open every modal type and verify its dialog remains inside the screen."""
        async with app.run_test(size=(40, 20)) as pilot:
            modals = (
                InfoModal("Help", "Compact help body"),
                StatusModal(lambda: "Compact status body"),
                LanguageModal("en-US"),
                ProjectRootModal(""),
            )
            for modal in modals:
                app.push_screen(modal)
                await pilot.pause()
                dialog = app.screen.query_one("#modal-dialog")
                assert dialog.region.x >= 0
                assert dialog.region.y >= 0
                assert dialog.region.right <= app.screen.size.width
                assert dialog.region.bottom <= app.screen.size.height
                if isinstance(modal, ProjectRootModal):
                    for button in app.screen.query("#project-root-actions Button"):
                        assert button.region.x >= dialog.region.x
                        assert button.region.right <= dialog.region.right
                await pilot.press("escape")
                await pilot.pause()

    asyncio.run(exercise())
