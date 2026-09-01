"""Experimental, unstable Textual full-screen shell for the SAGE 0.01beta2 Beta line.

The first TUI slice is intentionally read-mostly. It establishes cross-platform
keyboard/mouse navigation, view history, Help/Status overlays, language switching,
and shared canonical status consumption while the classic menu remains the action
fallback during migration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

try:
    from textual import work
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import Button, Header, Input, Static
except ImportError as exc:  # pragma: no cover - exercised only on an incomplete installation
    raise ImportError(
        "SAGE TUI requires Textual. Repair the SAGE runtime dependencies and retry `sage tui`."
    ) from exc

from .errors import SageError
from .interface_localization import LANGUAGE_DISPLAY_NAMES, SUPPORTED_INTERFACE_LANGUAGES
from .runtime_status import RuntimeStatus
from .ui_format import menu_item
from .ui_services import TOP_LEVEL_SECTIONS, OperatorUIService, context_help_lines, probe_workflow_ai


class InfoModal(ModalScreen[None]):
    """Non-destructive Help/Status overlay that returns to the invoking TUI view."""

    BINDINGS = [("escape", "close", "Close"), ("enter", "close", "Close")]

    def __init__(self, title: str, body: str) -> None:
        """Initialize the overlay title and read-only body."""
        super().__init__()
        self.dialog_title = title
        self.dialog_body = body

    def compose(self) -> ComposeResult:
        """Compose the modal title, scrollable body, and close control."""
        yield Container(
            Static(self.dialog_title, id="modal-title", markup=False),
            VerticalScroll(Static(self.dialog_body, id="modal-body", markup=False)),
            Button("Close", id="modal-close", variant="primary"),
            id="modal-dialog",
        )

    def action_close(self) -> None:
        """Dismiss the overlay without changing the underlying view."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Close the overlay when its explicit Close button is pressed."""
        if event.button.id == "modal-close":
            self.dismiss(None)


class StatusModal(ModalScreen[None]):
    """Live F-Status overlay that preserves the underlying TUI view and navigation history."""

    BINDINGS = [("escape", "close", "Close"), ("f", "close", "Close"), ("r", "refresh", "Refresh")]

    def __init__(self, body_provider: Callable[[], str]) -> None:
        """Initialize the live overlay with a canonical status-text provider."""
        super().__init__()
        self.body_provider = body_provider

    def compose(self) -> ComposeResult:
        """Compose the fixed-size status overlay and compact control hint."""
        yield Container(
            Static("SAGE STATUS", id="modal-title", markup=False),
            VerticalScroll(Static("", id="modal-body", markup=False)),
            Static("[R] Refresh    [F/Esc] Close", id="modal-footer", markup=False),
            id="modal-dialog",
        )

    def on_mount(self) -> None:
        """Populate the overlay immediately and refresh live state once per second."""
        self.action_refresh()
        self.set_interval(1.0, self.action_refresh)

    def action_refresh(self) -> None:
        """Refresh canonical status without changing the underlying application position."""
        self.query_one("#modal-body", Static).update(self.body_provider())

    def action_close(self) -> None:
        """Dismiss the overlay without adding a navigation-history entry."""
        self.dismiss(None)


class LanguageModal(ModalScreen[str | None]):
    """Mouse/keyboard language chooser backed by the existing governed locale set."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str) -> None:
        """Initialize the language picker with the currently active locale."""
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        """Compose one selectable button for every governed interface locale."""
        buttons = []
        for language in SUPPORTED_INTERFACE_LANGUAGES:
            marker = " *" if language == self.current else ""
            buttons.append(
                Button(
                    f"{LANGUAGE_DISPLAY_NAMES[language]} - {language}{marker}",
                    id=f"lang-{language.replace('-', '_')}",
                )
            )
        yield Container(
            Static("Interface language", id="modal-title"),
            Vertical(*buttons, id="language-buttons"),
            Button("Cancel", id="language-cancel"),
            id="modal-dialog",
        )

    def action_cancel(self) -> None:
        """Dismiss the language picker without changing configuration."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Return the selected governed locale or cancel the picker."""
        button_id = event.button.id or ""
        if button_id == "language-cancel":
            self.dismiss(None)
            return
        if button_id.startswith("lang-"):
            selected = button_id.removeprefix("lang-").replace("_", "-")
            # Locale tags in the governed set contain no ambiguous underscores.
            self.dismiss(selected)


class ProjectRootModal(ModalScreen[str | None]):
    """Collect one absolute Paratext/PTLite Projects-root path for governed setup."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str = "") -> None:
        """Initialize the path editor with the currently configured root, when present."""
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        """Compose the path input and explicit Apply/Cancel controls."""
        yield Container(
            Static("Paratext/PTLite Projects root", id="modal-title", markup=False),
            Static("Enter the absolute folder containing the Paratext/PTLite Project folders.", markup=False),
            Input(value=self.current, placeholder="Absolute Projects-root path", id="project-root-input"),
            Horizontal(
                Button("Apply", id="project-root-apply", variant="primary"),
                Button("Cancel", id="project-root-cancel"),
                id="project-root-actions",
            ),
            id="modal-dialog",
        )

    def on_mount(self) -> None:
        """Focus the path input so keyboard-only setup can begin immediately."""
        self.query_one("#project-root-input", Input).focus()

    def action_cancel(self) -> None:
        """Dismiss path setup without changing configuration."""
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Apply the entered path when Enter is pressed in the input control."""
        self.dismiss(event.value.strip() or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Apply the entered root or cancel without changing state."""
        button_id = event.button.id or ""
        if button_id == "project-root-cancel":
            self.dismiss(None)
        elif button_id == "project-root-apply":
            value = self.query_one("#project-root-input", Input).value.strip()
            self.dismiss(value or None)


class SageTUIApp(App[None]):
    """Initial mouse-capable full-screen SAGE operator shell."""

    # Keep workflow-changing operations outside this shell until their service boundaries are shared.

    TITLE = "SAGE"
    SUB_TITLE = "0.01beta2 Beta TUI — EXPERIMENTAL / UNSTABLE"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        ("1", "open_projects", "Scripture Projects"),
        ("2", "open_bic", "BIC"),
        ("3", "open_rtc", "RTC"),
        ("4", "open_stc", "STC"),
        ("5", "open_configure", "SAGE Maintenance"),
        ("a", "back", "Back"),
        ("escape", "back", "Back"),
        ("b", "home", "Main Menu"),
        ("home", "home", "Main Menu"),
        ("c", "quit_sage", "Exit SAGE"),
        ("ctrl+q", "quit_sage", "Exit SAGE"),
        ("d", "language", "Language"),
        ("e", "help", "Help"),
        ("?", "help", "Help"),
        ("f", "status", "Status"),
        ("p", "set_projects_root", "Set Projects root"),
        ("q", "quick_scan", "Quick Scan"),
        ("r", "retry_readiness", "Retest AI / readiness"),
    ]

    CSS = """
    Screen {
        layout: vertical;
        min-width: 80;
        min-height: 24;
    }
    Header {
        height: 1;
    }
    #overview {
        height: 6;
    }
    .overview-block {
        width: 1fr;
        height: 6;
        border: solid $primary;
        padding: 0 1;
    }
    .block-title {
        height: 1;
        text-style: bold;
    }
    .block-body {
        height: 1fr;
    }
    #active-job-block {
        height: 5;
        border: solid $primary;
        padding: 0 1;
    }
    #job-progress-line {
        height: 1;
        text-style: bold;
    }
    #job-activity-line {
        height: 1;
    }
    #content-scroll {
        height: 1fr;
        padding: 0 1;
    }
    #view-title {
        height: 2;
        text-style: bold;
    }
    #view-content {
        width: 100%;
        height: auto;
    }
    #migration-note {
        height: auto;
        margin-top: 1;
        padding: 0 1;
        border: round $secondary;
    }
    #view-actions {
        height: 3;
        margin-top: 1;
    }
    #view-actions Button {
        width: 1fr;
        min-width: 18;
        margin-right: 1;
    }
    #nav-row, #footer-row {
        height: 3;
        border-top: solid $primary;
        padding: 0 1;
    }
    #nav-row Button, #footer-row Button {
        width: 1fr;
        min-width: 12;
        margin-right: 1;
    }
    InfoModal, LanguageModal, ProjectRootModal, StatusModal {
        align: center middle;
    }
    #modal-dialog {
        width: 72%;
        max-width: 90;
        height: 72%;
        max-height: 24;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    StatusModal #modal-dialog {
        width: 90;
        height: 24;
        max-width: 90;
        max-height: 24;
    }
    #modal-title {
        height: 2;
        text-style: bold;
    }
    #modal-body {
        width: 100%;
        height: 1fr;
    }
    #modal-footer {
        height: 1;
        content-align: center middle;
    }
    #language-buttons Button {
        width: 100%;
        margin-bottom: 1;
    }
    #project-root-input {
        width: 100%;
        margin: 1 0;
    }
    #project-root-actions {
        height: 3;
    }
    #project-root-actions Button {
        width: 1fr;
        margin-right: 1;
    }
    """

    def __init__(
        self,
        service: OperatorUIService,
        *,
        live_ai: bool = True,
        dry_run_provider: bool = False,
    ) -> None:
        """Initialize shared services, readiness gating, view history, and canonical labels."""
        super().__init__()
        self.service = service
        self.live_ai = live_ai
        self.dry_run_provider = dry_run_provider
        self.current_view = "startup" if live_ai else "main"
        self.view_history: list[str] = []
        self._readiness: dict[str, Any] = {}
        self._last_error: SageError | None = None
        self._view_titles = {section.view_id: section.label for section in TOP_LEVEL_SECTIONS}
        self._view_titles["main"] = "Main Menu"
        self._view_titles["startup"] = "Startup Readiness"

    def tr(self, value: str) -> str:
        """Localize one canonical menu phrase using the existing JSON source."""
        return self.service.localizer.text(value)

    def compose(self) -> ComposeResult:
        """Compose the fixed 100x30 dashboard, content surface, numeric menu, and global footer."""
        yield Header(show_clock=True)
        with Horizontal(id="overview"):
            with Vertical(classes="overview-block"):
                yield Static("SYSTEM STATUS", classes="block-title", markup=False)
                yield Static("", id="system-block", classes="block-body", markup=False)
            with Vertical(classes="overview-block"):
                yield Static("ACTIVE AI", classes="block-title", markup=False)
                yield Static("", id="ai-block", classes="block-body", markup=False)
            with Vertical(classes="overview-block"):
                yield Static("PROJECT", classes="block-title", markup=False)
                yield Static("", id="project-block", classes="block-body", markup=False)
        with Vertical(id="active-job-block"):
            yield Static("ACTIVE JOB", classes="block-title", markup=False)
            yield Static("— IDLE —", id="job-progress-line", markup=False)
            yield Static("", id="job-activity-line", markup=False)
        with VerticalScroll(id="content-scroll"):
            yield Static("", id="view-title", markup=False)
            yield Static("", id="view-content", markup=False)
            yield Static("", id="migration-note", markup=False)
            with Horizontal(id="view-actions"):
                yield Button("P. Set Projects root", id="action-set-root")
                yield Button("Q. Quick Scan", id="action-quick-scan")
                yield Button("R. Retest AI", id="action-retest-ai")
        with Horizontal(id="nav-row"):
            for index, section in enumerate(TOP_LEVEL_SECTIONS, start=1):
                yield Button(menu_item(index, self.tr(section.label)), id=f"nav-{section.view_id}")
        with Horizontal(id="footer-row"):
            yield Button(f"A. {self.tr('Back')}", id="footer-back")
            yield Button(f"B. {self.tr('Main Menu')}", id="footer-home")
            yield Button(f"C. {self.tr('Exit SAGE')}", id="footer-exit")
            yield Button(f"D. {self.tr('Language')}", id="footer-language")
            yield Button(f"E. {self.tr('Help')}", id="footer-help")
            yield Button(f"F. {self.tr('Status')}", id="footer-status")

    def on_mount(self) -> None:
        """Mount immediately, render local readiness, then probe workflow AI off the UI thread."""
        self._readiness = self.service.startup_readiness()
        if not self.live_ai:
            self.current_view = "main" if self._readiness.get("status") == "READY" else "startup"
        self._render_current_view()
        self.set_interval(1.0, self._refresh_session_status)
        if self.live_ai:
            self._probe_ai_worker()

    def _set_view(self, view_id: str, *, remember: bool = True) -> None:
        """Navigate while enforcing startup gates for workflow-operational surfaces."""
        if view_id not in {"startup", "projects", "configure"} and self._readiness.get("status") != "READY":
            next_label = self._readiness.get("next_label") or "Complete startup readiness"
            self.push_screen(InfoModal("Startup incomplete", f"{next_label}.\n\nUse 1 Scripture Projects, 4 SAGE Maintenance, or R to retry readiness."))
            return
        if view_id == self.current_view:
            self._render_current_view()
            return
        if remember:
            self.view_history.append(self.current_view)
        self.current_view = view_id
        self._render_current_view()

    def _render_current_view(self) -> None:
        """Render the active snapshot without allowing recoverable state errors to terminate the TUI."""
        title = self._view_titles.get(self.current_view, self.current_view)
        try:
            if self.current_view == "startup":
                snapshot = self._readiness or self.service.startup_readiness()
            else:
                snapshot = self.service.section_snapshot(self.current_view)
            rendered = self._render_snapshot(self.current_view, snapshot)
            self._last_error = None
        except SageError as exc:
            self._last_error = exc
            rendered = "\n".join(
                [
                    self._kv("Result", "ACTION NEEDED"),
                    self._kv("Reason code", exc.code),
                    self._kv("Problem", exc.message),
                    self._kv("Next action", exc.next_action or "Open Recovery / Status for diagnostics"),
                ]
            )
        self.query_one("#view-title", Static).update(self.tr(title))
        self.query_one("#view-content", Static).update(rendered)
        if self.current_view == "startup":
            note = (
                "Startup gates workflow surfaces until required local state and workflow AI are READY. "
                "P sets the Projects root, Q performs a Quick Scan, and R retests AI/readiness."
            )
        elif self.current_view in {"projects", "configure"}:
            note = (
                "Native remediation is enabled for Projects-root setup, Quick Scan, and AI retest. "
                "Other workflow-changing actions remain in the classic menu/CLI while they migrate."
            )
        elif self.current_view == "main":
            note = (
                "EXPERIMENTAL / UNSTABLE TUI: navigation/status/readiness are native here. "
                "Workflow-changing actions remain governed by existing services while migration continues."
            )
        else:
            note = (
                "This panel is read-only in the current TUI slice. "
                "Projects, configuration, and recovery remain available even when startup is incomplete."
            )
        self.query_one("#migration-note", Static).update(note)
        self._refresh_session_status()
        self._refresh_nav_variants()
        self._refresh_action_controls()

    def _refresh_nav_variants(self) -> None:
        """Mark the active navigation control and update Back availability."""
        for view_id in (section.view_id for section in TOP_LEVEL_SECTIONS):
            button = self.query_one(f"#nav-{view_id}", Button)
            button.variant = "primary" if view_id == self.current_view else "default"
        self.query_one("#footer-back", Button).disabled = not self.view_history and self.current_view in {"main", "startup"}

    def _refresh_action_controls(self) -> None:
        """Enable remediation controls only on startup/configuration surfaces."""
        remediation_surface = self.current_view in {"startup", "projects", "configure"}
        root_ready = self._readiness.get("projects_root_status") == "READY"
        self.query_one("#action-set-root", Button).disabled = not remediation_surface
        self.query_one("#action-quick-scan", Button).disabled = not remediation_surface or not root_ready
        self.query_one("#action-retest-ai", Button).disabled = not remediation_surface or not self.live_ai

    def _refresh_session_status(self) -> None:
        """Refresh the fixed dashboard blocks from canonical runtime and progress state."""
        try:
            status = self.service.runtime_snapshot()
        except SageError as exc:
            self.query_one("#system-block", Static).update(
                f"Runtime  ACTION NEEDED\nReason   {exc.code}\nF Status for details"
            )
            self.query_one("#ai-block", Static).update("Connection  —\nProvider    —\nModel       —")
            self.query_one("#project-block", Static).update("Project     —\nCatalog     —\nLanguage    —")
            self.query_one("#job-progress-line", Static).update("— STATUS UNAVAILABLE —")
            self.query_one("#job-activity-line", Static).update(exc.code)
            return
        ai = status.get("ai") or {}
        local_ai = status.get("local_ai") or {}
        projects = status.get("projects") or {}
        readiness = self._readiness or {}
        system_lines = [
            f"Runtime   {status.get('state') or 'IDLE'}",
            f"Startup   {readiness.get('status') or 'NOT CHECKED'}",
            f"Resources {status.get('resource_status') or 'NOT CHECKED'}",
        ]
        provider = ai.get("provider") or "—"
        model = ai.get("model") or "—"
        if len(str(model)) > 20:
            model = str(model)[:19] + "…"
        ai_lines = [
            f"{ai.get('connection') or 'NOT CHECKED'}",
            f"{provider} / {model}",
            f"Reasoning {ai.get('reasoning_level') or '—'}",
        ]
        project_lines = [
            f"Project    {status.get('current_project') or 'NONE'}",
            f"Catalog    {projects.get('registered', 0)} reg / {projects.get('discovered', 0)} found",
            f"Language   {status.get('interface_language') or '—'}",
        ]
        self.query_one("#system-block", Static).update("\n".join(system_lines))
        self.query_one("#ai-block", Static).update("\n".join(ai_lines))
        self.query_one("#project-block", Static).update("\n".join(project_lines))
        progress = status.get("job_progress") or {}
        terminal = str(progress.get("result") or "").upper()
        if progress and terminal not in {"DONE", "CANCELLED"}:
            self.query_one("#job-progress-line", Static).update(str(progress.get("line") or "—"))
            activity = str(progress.get("activity") or "")
            stage = str(progress.get("stage") or "").replace("_", " ")
            detail = " / ".join(value for value in (stage, activity) if value)
            self.query_one("#job-activity-line", Static).update(detail or "—")
        else:
            self.query_one("#job-progress-line", Static).update("— IDLE —")
            if progress and terminal == "DONE":
                self.query_one("#job-activity-line", Static).update(f"Last: {progress.get('job_id')} / DONE")
            else:
                self.query_one("#job-activity-line", Static).update("")

    @staticmethod
    def _kv(label: str, value: Any) -> str:
        """Format one status label and value for fixed-width terminal display."""
        return f"{label:<22} {value if value not in (None, '') else '—'}"

    def _render_snapshot(self, view_id: str, data: dict[str, Any]) -> str:
        """Render a bounded service snapshot for the requested TUI view."""
        lines: list[str] = []
        # Keep renderer branches data-only so migrated actions stay in shared services, not presentation code.
        if view_id == "startup":
            ai = data.get("ai") or {}
            projects = data.get("projects") or {}
            workflows = data.get("workflows") or {}
            root_status = str(data.get("projects_root_status") or "NOT CONFIGURED").replace("_", " ")
            if root_status == "READY" and data.get("projects_root"):
                root_status = f"READY - {data.get('projects_root')}"
            lines.extend(
                [
                    self._kv("Runtime", data.get("runtime") or "READY"),
                    self._kv("SAGE configuration", data.get("configuration")),
                    self._kv("Paratext Projects root", root_status),
                    self._kv("Projects discovered", projects.get("discovered", 0)),
                    self._kv("Projects pending", projects.get("pending", 0)),
                    self._kv("Scripture resources", data.get("scripture_resources")),
                    self._kv("AI connection", ai.get("connection") or "NOT CHECKED"),
                    self._kv("Provider", ai.get("provider") or "NOT CONFIGURED"),
                    self._kv("Model", ai.get("model") or "NOT AVAILABLE"),
                    self._kv("Reasoning", ai.get("reasoning_level") or "NOT REPORTED"),
                    self._kv("BIC", workflows.get("bic") or "NOT CONFIGURED"),
                    self._kv("RTC", workflows.get("rtc") or "NOT CONFIGURED"),
                    self._kv("STC", workflows.get("stc") or "NOT CONFIGURED"),
                    "",
                    self._kv("Overall", data.get("status") or "INCOMPLETE"),
                    self._kv("Next", data.get("next_label") or "Complete setup"),
                ]
            )
            if ai.get("connection") == "CHECKING":
                lines.extend(["", "Workflow AI is being checked in the background; the interface remains usable."])
            return "\n".join(lines)

        if view_id == "main":
            lines.extend(
                [
                    self._kv("Release", f"v{data['version']} {data['release_status']}"),
                    self._kv("BIC active Job", data["bic_job"]),
                    self._kv("RTC active Job", data["rtc_job"]),
                    self._kv("STC active Job", data["stc_job"]),
                    self._kv("Last Run", data["last_run"]),
                    self._kv("Workflow AI", (data.get("ai") or {}).get("connection")),
                    self._kv("Model policy", data["model"]),
                    self._kv("Projects registered", data["projects"].get("registered", 0)),
                    self._kv("Projects discovered", data["projects"].get("discovered", 0)),
                    self._kv("Interface", f"{data['interface_language_name']} [{data['interface_language']}]"),
                ]
            )
            if data.get("unfinished_run"):
                lines.extend(["", "Unfinished Run is available through the classic menu while Run actions migrate."])
            return "\n".join(lines)

        if view_id == "projects":
            catalog = data.get("catalog") or {}
            lines.extend(
                [
                    self._kv("Paratext root", data.get("projects_root") or "NOT CONFIGURED"),
                    self._kv("Discovered", catalog.get("discovered", catalog.get("projects", 0))),
                    self._kv("Validated", catalog.get("validated", 0)),
                    self._kv("Pending", catalog.get("pending", 0)),
                    "",
                    "Registered SAGE Projects",
                ]
            )
            rows = data.get("registered") or []
            if not rows:
                lines.append("  None")
            else:
                for row in rows:
                    lines.append(
                        f"  {str(row['project_id']):<14} {str(row['name'])} "
                        f"[{str(row['language'])}; {str(row['status'])}]"
                    )
            return "\n".join(lines)

        if view_id in {"bic", "rtc", "stc"}:
            lines.extend([self._kv("Active Job", data.get("active_job") or "NONE"), self._kv("Last Run", data.get("last_run")), "", "Jobs"])
            jobs = data.get("jobs") or []
            if not jobs:
                lines.append("  None")
            else:
                for row in jobs:
                    flags = []
                    if row.get("active"):
                        flags.append("ACTIVE")
                    if row.get("archived"):
                        flags.append("ARCHIVED")
                    flag_text = f" [{', '.join(flags)}]" if flags else ""
                    lines.append(f"  {str(row['job_id'])}: {str(row['display_name'])}{flag_text}")
            lines.extend(["", "Reports, history, and Job recovery belong to this workflow."])
            return "\n".join(lines)

        if view_id == "reports":
            lines.extend([self._kv("Reports root", data.get("report_root")), "", "Recent report files"])
            files = data.get("files") or []
            lines.extend(f"  {str(item)}" for item in files) if files else lines.append("  None")
            return "\n".join(lines)

        if view_id == "configure":
            ai = data.get("workflow_ai") or {}
            lines = [
                self._kv("Interface", f"{data.get('interface_language_name')} [{data.get('interface_language')}]"),
                self._kv("Paratext root", data.get("projects_root") or "NOT CONFIGURED"),
                self._kv("LLM connection", ai.get("connection")),
                self._kv("Provider", ai.get("provider")),
                self._kv("Model", ai.get("model")),
                self._kv("Reasoning", ai.get("reasoning_level")),
                "",
                "Configured Language Profiles",
            ]
            rows = data.get("languages") or []
            lines.extend(
                f"  {str(row.get('profile')):<14} [{str(row.get('script'))}] grammar={row.get('grammar_profiles', 0)}"
                for row in rows
            ) if rows else lines.append("  None")
            lines.extend(["", "Text UI owns system settings and recovery writes until TUI write parity is completed."])
            return "\n".join(lines)

        if view_id == "recovery":
            return "\n".join(
                [
                    self._kv("Setup", data.get("setup_status")),
                    self._kv("Next step", data.get("next_step")),
                    self._kv("Last Run", data.get("last_run")),
                    self._kv("SAGE Home", data.get("sage_home")),
                    self._kv("State root", data.get("state_root")),
                    self._kv("Diagnostics", data.get("diagnostics")),
                ]
            )
        return str(data)

    def action_open_projects(self) -> None:
        """Open Scripture Projects through the shared numeric navigation grammar."""
        self._set_view("projects")

    def action_open_bic(self) -> None:
        """Open BIC when startup prerequisites are ready."""
        self._set_view("bic")

    def action_open_rtc(self) -> None:
        """Open Reference Text Comparison when startup prerequisites are ready."""
        self._set_view("rtc")

    def action_open_stc(self) -> None:
        """Open Source Text Correspondence when startup prerequisites are ready."""
        self._set_view("stc")

    def action_open_reports(self) -> None:
        """Open Reports when startup prerequisites are ready."""
        self._set_view("reports")

    def action_open_configure(self) -> None:
        """Open SAGE Maintenance even when startup remediation is required."""
        self._set_view("configure")

    def action_open_recovery(self) -> None:
        """Open Recovery even when startup remediation is required."""
        self._set_view("recovery")

    def action_set_projects_root(self) -> None:
        """Prompt for and govern the workstation Paratext/PTLite Projects root."""
        if self.current_view not in {"startup", "projects", "configure"}:
            self.push_screen(InfoModal("Projects root", "Open Scripture Projects or SAGE Maintenance to change the Projects root."))
            return
        _status, current = self.service.projects_root_status()
        self.push_screen(ProjectRootModal(str(current) if current is not None else ""), self._project_root_selected)

    def _project_root_selected(self, value: str | None) -> None:
        """Start background Projects-root validation and Quick Scan after modal submission."""
        if not value:
            return
        self._begin_remediation("Projects root setup", "Quick Scan")
        self._configure_project_root_worker(value)

    def action_quick_scan(self) -> None:
        """Run the cheap tree-only Paratext Project discovery scan in the background."""
        if self.current_view not in {"startup", "projects", "configure"}:
            self.push_screen(InfoModal("Quick Scan", "Open Scripture Projects or SAGE Maintenance before rescanning."))
            return
        status, _root = self.service.projects_root_status()
        if status != "READY":
            self.push_screen(InfoModal("Quick Scan", "Configure a valid Paratext/PTLite Projects root first."))
            return
        self._begin_remediation("Paratext scan", "Quick Scan")
        self._quick_scan_worker()

    def _begin_remediation(self, task: str, stage: str) -> None:
        """Publish one bounded remediation task in the shared runtime-status header."""
        runtime = self.service.runtime_status
        runtime.state = "RUNNING"
        runtime.active_task = task
        runtime.stage = stage
        runtime.progress = "STARTING"
        self._refresh_session_status()

    @work(exclusive=True, group="project-remediation", thread=True, exit_on_error=False)
    def _configure_project_root_worker(self, value: str) -> None:
        """Persist and scan a Projects root off the Textual UI thread."""
        try:
            result = self.service.configure_projects_root(value)
        except SageError as exc:
            self.call_from_thread(self._remediation_failed, "Projects root setup", exc)
            return
        self.call_from_thread(self._remediation_complete, "Projects root configured", result)

    @work(exclusive=True, group="project-remediation", thread=True, exit_on_error=False)
    def _quick_scan_worker(self) -> None:
        """Refresh the tree-only Project catalog off the Textual UI thread."""
        try:
            catalogue = self.service.scan_projects(full=False)
        except SageError as exc:
            self.call_from_thread(self._remediation_failed, "Quick Scan", exc)
            return
        from .paratext_catalog import catalog_summary

        self.call_from_thread(
            self._remediation_complete,
            "Quick Scan complete",
            {"projects_root": catalogue.get("projects_root"), "catalog": catalog_summary(catalogue)},
        )

    def _clear_remediation_runtime(self) -> None:
        """Return the shared runtime header to idle after one bounded remediation action."""
        runtime = self.service.runtime_status
        runtime.state = "IDLE"
        runtime.active_task = None
        runtime.stage = None
        runtime.progress = None

    def _remediation_complete(self, title: str, result: dict[str, Any]) -> None:
        """Refresh readiness and report the bounded Project remediation result."""
        self._clear_remediation_runtime()
        self._readiness = self.service.startup_readiness()
        self._render_current_view()
        summary = dict(result.get("catalog") or {})
        body = "\n".join(
            [
                self._kv("Projects root", result.get("projects_root")),
                self._kv("Discovered", summary.get("discovered", summary.get("projects", 0))),
                self._kv("Validated", summary.get("validated", 0)),
                self._kv("Pending", summary.get("pending", 0)),
                self._kv("Overall startup", self._readiness.get("status")),
                self._kv("Next", self._readiness.get("next_label")),
            ]
        )
        self.push_screen(InfoModal(title, body))

    def _remediation_failed(self, title: str, exc: SageError) -> None:
        """Keep the TUI alive and report a failed remediation with its governed reason code."""
        self._clear_remediation_runtime()
        self._readiness = self.service.startup_readiness()
        self._render_current_view()
        body = "\n".join(
            [
                self._kv("Result", "ACTION NEEDED"),
                self._kv("Reason code", exc.code),
                self._kv("Problem", exc.message),
                self._kv("Next action", exc.next_action or self._readiness.get("next_label")),
            ]
        )
        self.push_screen(InfoModal(title, body))

    def action_retry_readiness(self) -> None:
        """Refresh local startup facts and rerun the workflow-AI prerequisite probe."""
        self._readiness = self.service.startup_readiness()
        self.current_view = "startup" if self._readiness.get("status") != "READY" else self.current_view
        self._render_current_view()
        if self.live_ai:
            self._probe_ai_worker()

    @work(exclusive=True, group="ai-probe", thread=True, exit_on_error=False)
    def _probe_ai_worker(self) -> None:
        """Probe blocking workflow-AI connectivity in a managed Textual thread worker."""
        result = probe_workflow_ai(
            self.service.root,
            self.service.runtime_status,
            refresh=True,
            dry_run_provider=self.dry_run_provider,
        )
        self.call_from_thread(self._apply_ai_probe_result, result)

    def _apply_ai_probe_result(self, result: dict[str, Any]) -> None:
        """Apply a completed AI probe on the UI thread and reevaluate the startup gate."""
        self._readiness = self.service.startup_readiness(result, persist_completion=True)
        if self._readiness.get("status") == "READY" and self.current_view == "startup":
            self.current_view = "main"
            self.view_history.clear()
        elif self._readiness.get("status") != "READY" and self.current_view not in {"projects", "configure", "recovery"}:
            self.current_view = "startup"
            self.view_history.clear()
        self._render_current_view()

    def action_back(self) -> None:
        """Return to the previous TUI position without discarding state."""
        if self.view_history:
            self.current_view = self.view_history.pop()
            self._render_current_view()
        elif self.current_view != "main":
            self.current_view = "main"
            self._render_current_view()

    def action_home(self) -> None:
        """Return to Main Menu when ready, otherwise return to Startup Readiness."""
        self.view_history.clear()
        self.current_view = "main" if self._readiness.get("status") == "READY" else "startup"
        self._render_current_view()

    def action_quit_sage(self) -> None:
        """Exit the TUI through the Textual application lifecycle."""
        self.exit(None)

    def action_help(self) -> None:
        """Open contextual Help for the current view as a modal overlay."""
        title = self._view_titles.get(self.current_view, self.current_view)
        body = "\n".join(context_help_lines(title))
        self.push_screen(InfoModal(f"Help - {self.tr(title)}", body))

    def _status_overlay_text(self, *, assistive_text: str | None = None) -> str:
        """Render the live 90x24 diagnostic overlay from the same state used by dashboard blocks."""
        try:
            status = self.service.runtime_snapshot()
            release = self.service.release_snapshot()
        except SageError as exc:
            return "\n".join(
                [
                    "ACTION NEEDED",
                    self._kv("Reason code", exc.code),
                    self._kv("Problem", exc.message),
                    self._kv("Next action", exc.next_action or "Open Recovery"),
                ]
            )
        ai = status.get("ai") or {}
        local_ai = status.get("local_ai") or {}
        projects = status.get("projects") or {}
        progress = status.get("job_progress") or {}

        def col(label: str, value: Any, width: int = 28) -> str:
            """Format one compact status-overlay cell."""
            text = f"{label:<10} {value if value not in (None, '') else '—'}"
            return text[:width].ljust(width)

        lines = [
            f"{col('SYSTEM', '', 28)}{col('ACTIVE AI', '', 28)}{col('PROJECT', '', 28)}",
            f"{col('Version', release.get('version'))}{col('Connection', ai.get('connection'))}{col('Current', status.get('current_project') or 'NONE')}",
            f"{col('Release', release.get('release_status'))}{col('Provider', ai.get('provider'))}{col('Registered', projects.get('registered', 0))}",
            f"{col('Runtime', status.get('state'))}{col('Model', ai.get('model'))}{col('Discovered', projects.get('discovered', 0))}",
            f"{col('Resources', status.get('resource_status'))}{col('Reasoning', ai.get('reasoning_level'))}{col('Validated', projects.get('validated', 0))}",
            "",
            "ACTIVE JOB",
        ]
        if progress:
            lines.extend(
                [
                    str(progress.get("line") or "—"),
                    str(progress.get("activity") or "—"),
                    f"Run: {progress.get('run_id') or '—'}    Stage: {str(progress.get('stage') or '—').replace('_', ' ')}",
                    f"Tasks: {progress.get('task_completed', 0)}/{progress.get('task_total', 0)}",
                ]
            )
            if progress.get("result") == "BLOCKED" and progress.get("reason_code"):
                lines.append(f"Block reason: {progress.get('reason_code')}")
        else:
            lines.extend(["— IDLE —", "No current or previous Run progress is available."])
        lines.extend(
            [
                "",
                "SESSION",
                f"Interface: {status.get('interface_language_name')} [{status.get('interface_language')}]",
                f"Projects root: {status.get('projects_root') or 'NOT CONFIGURED'}",
                f"AI last check: {ai.get('last_checked') or 'NEVER'}",
                (
                    "Local AI: "
                    f"{'ON' if local_ai.get('enabled') else 'OFF'} / "
                    f"{local_ai.get('model') or '—'} / "
                    f"{local_ai.get('authority') or 'ASSISTIVE_ONLY'} / "
                    f"{local_ai.get('readiness') or 'NOT_PROBED'} / "
                    f"{local_ai.get('reporting_mode') or 'MULTILINGUAL_AVAILABLE'}"
                ),
                (
                    "Secondary reporting: "
                    + ("AVAILABLE" if local_ai.get("secondary_language_allowed") else "DISABLED")
                ),
            ]
        )
        if assistive_text:
            lines.extend(["", "LOCAL AI NOTE - NON-AUTHORITATIVE", assistive_text])
        return "\n".join(lines)

    def action_status(self) -> None:
        """Open F Status as a live modal overlay without altering navigation history or selection."""
        assistive_text = None
        try:
            snapshot = self.service.runtime_snapshot()
            assistive = self.service.assistive_status_explanation(snapshot)
            if assistive:
                assistive_text = str(assistive.get("text") or "") or None
        except SageError:
            pass
        self.push_screen(StatusModal(lambda: self._status_overlay_text(assistive_text=assistive_text)))

    def action_language(self) -> None:
        """Open the governed interface-language selector."""
        self.push_screen(LanguageModal(self.service.localizer.language), self._language_selected)

    def _language_selected(self, language: str | None) -> None:
        """Persist a selected locale and refresh all visible localized labels."""
        if language is None:
            return
        if language not in SUPPORTED_INTERFACE_LANGUAGES:
            return
        self.service.set_interface_language(language)
        self._refresh_labels()
        self._render_current_view()

    def _refresh_labels(self) -> None:
        """Refresh navigation and footer labels after a language change."""
        for index, section in enumerate(TOP_LEVEL_SECTIONS, start=1):
            self.query_one(f"#nav-{section.view_id}", Button).label = menu_item(index, self.tr(section.label))
        self.query_one("#footer-back", Button).label = f"A. {self.tr('Back')}"
        self.query_one("#footer-home", Button).label = f"B. {self.tr('Main Menu')}"
        self.query_one("#footer-exit", Button).label = f"C. {self.tr('Exit SAGE')}"
        self.query_one("#footer-language", Button).label = f"D. {self.tr('Language')}"
        self.query_one("#footer-help", Button).label = f"E. {self.tr('Help')}"
        self.query_one("#footer-status", Button).label = f"F. {self.tr('Status')}"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route mouse button presses through the same navigation actions as keys."""
        button_id = event.button.id or ""
        if button_id.startswith("nav-"):
            self._set_view(button_id.removeprefix("nav-"))
            return
        actions: dict[str, Callable[[], None]] = {
            "footer-back": self.action_back,
            "footer-home": self.action_home,
            "footer-exit": self.action_quit_sage,
            "footer-language": self.action_language,
            "footer-help": self.action_help,
            "footer-status": self.action_status,
            "action-set-root": self.action_set_projects_root,
            "action-quick-scan": self.action_quick_scan,
            "action-retest-ai": self.action_retry_readiness,
        }
        action = actions.get(button_id)
        if action is not None:
            action()


def run_tui(
    *,
    sage_root: Path,
    settings_path: Path,
    dry_run_provider: bool = False,
    live_ai: bool = True,
) -> int:
    """Run the initial full-screen TUI without removing the classic-menu fallback."""
    runtime = RuntimeStatus()
    if live_ai:
        runtime.ai.connection = "CHECKING"
        runtime.ai.prerequisite_status = "CHECKING"
    service = OperatorUIService(root=sage_root, settings_path=settings_path, runtime_status=runtime)
    app = SageTUIApp(service, live_ai=live_ai, dry_run_provider=dry_run_provider)
    app.run()
    return 0
