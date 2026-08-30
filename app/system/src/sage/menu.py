"""Menu-driven SAGE Control Center for Job-scoped BIC and SAW operation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Thread
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence, TextIO

from .ui_format import menu_item
from .atomic import atomic_write_json, atomic_write_text
from .canon import NT_27, OT_39
from .external_access import READ_ONLY_SCRIPTURE, READ_WRITE_SCRIPTURE, READ_WRITE_TARGET
from .errors import ConfigurationError, InputRequiredError, OperatorCancelledError, SageError, ValidationError
from .display_paths import operator_path, operator_text
from .execution_events import classify_exception, record_exception_event, terminal_heading
from .task_retry import archive_rejected_task_output
from .hashing import sha256_file
from .grammar import load_grammar_profile
from .llm_settings import load_llm_settings, local_ai_policy_status, update_llm_selection
from .build_policy import ENABLED_AUTOMATED_PROVIDER_IDS
from .ollama_admin import OllamaAdminService, OllamaAdminStatus
from .platform_commands import render_sage_command
from .ollama_policy import (
    SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
    SAGE_LOCAL_ADMIN_MODEL,
    SAGE_LOCAL_ADMIN_SOURCE_BYTES,
    SAGE_LOCAL_ADMIN_SOURCE_REPOSITORY,
    SAGE_LOCAL_ADMIN_SOURCE_REVISION,
    SAGE_LOCAL_ADMIN_SOURCE_SHA256,
)
from .iso_languages import iso_language, regional_profile_candidates, preferred_operational_primary
from .language_identification import resolve_country, resolve_country_input
from .language_profiles import ensure_language_profile_namespace, language_profile_status
from .saw_policy import default_rtc_policy, write_run_policy_snapshot
from .interface_localization import (
    InterfaceLocalizer,
    LANGUAGE_DISPLAY_NAMES,
    SUPPORTED_INTERFACE_LANGUAGES,
)
from .language_codes import canonical_language_tag, canonical_regional_language_tag, canonical_script_code
from .model_service import ModelService
from .executors.codex_cli import CodexCLIExecutor
from .references import parse_scope
from .scripture import VERSIFICATION_ADVISORY_CODES, compile_project_scope, is_default_vrs_compatible_issue
from .resource_mounts import (
    clear_base_vrs_root,
    discover_project_folders,
    load_resource_mount_state,
    load_resource_mounts,
    interpret_operator_project_location,
    normalize_operator_path,
    remove_resource_mount,
    invalidate_runtime_settings,
    set_base_vrs_root,
    set_project_root,
    set_resource_mount,
)
from .resource_registration import compatible_language_options, register_external_scripture_resource, register_catalogued_scripture_project
from .resource_validation import validate_scripture_resources
from .runtime_status import AIStatus, RuntimeStatus, utc_now
from .ui_services import OperatorUIService, context_help_lines, probe_workflow_ai
from .registry import load_ecosystem
from .semantic import (
    build_semantic_indexes,
    export_lift,
    import_lift_snapshot,
    import_rwc_seed_xlsx,
    import_semdom_authority_json,
    import_specific_first_docx,
    semantic_status,
)
from .semantic.evidence import evidence_for_form
from .semantic.policy import EXPORT_VIEWS, REVIEW_STATES
from .semantic.store import (
    clear_review_state,
    load_bindings,
    load_import_selection,
    load_review_states,
    set_authority_selection,
    set_binding,
    set_import_active,
    set_review_state,
)
from .state import ecosystem_state_path, read_state
from .storage import declare_governed_path, resolve_declared_path, storage_layout
from .stc_reporting import publish_stc_task_reports
from .operator_overrides import load_effective_settings, write_local_settings
from .job_layout import audit_job_layout, migrate_job_layout, render_job_layout_audit, verify_job_layout, write_job_layout_audit
from .out_of_box_reset import reset_to_out_of_box
from .jobs import (
    RUN_CLOSED_STATUSES,
    TOOL_IDS,
    Job as Job,
    JobStore as JobStore,
    Run as Run,
    default_job_name,
)
from .project_inventory import (
    load_project_registry, registered_project_records, unregister_project, update_project_record,
    summarize_scope, scope_testament,
)
from .paratext_catalog import (
    catalog_summary, filtered_projects, inspect_paratext_project, language_filter_counts,
    load_paratext_catalog, rescan_catalog_project, scan_paratext_projects,
)
from .original_language_resources import (
    OL_ALIASES, active_ol_project_id, configure_ol_resource, paratext_ol_candidates,
    resolved_ol_entry, restore_bundled_ol_defaults, validate_original_language_resources,
)


@dataclass
class MenuHomeRequested(Exception):
    """Unwind the current menu stack and return to the SAGE main menu."""


class MenuExitRequested(Exception):
    """Unwind the current menu stack and exit SAGE."""


@dataclass
class MenuIO:
    """Small injectable terminal I/O surface used by the interactive menu and tests."""

    input_func: Callable[[str], str] = input
    output: TextIO = sys.stdout
    localizer: InterfaceLocalizer | None = None
    language_handler: Callable[[], None] | None = None
    help_handler: Callable[[str], None] | None = None
    status_handler: Callable[[], None] | None = None

    def request_panel_reset(self) -> None:
        """Retain the menu-transition hook without clearing terminal history."""

    def _prepare_panel_output(self) -> None:
        """Retain the output hook; classic menus form one continuous scrollback."""

    def write(self, value: str = "") -> None:
        """Implement `write` in the deterministic terminal control flow."""
        self._prepare_panel_output()
        rendered = self.localizer.text(value) if self.localizer is not None else value
        print(rendered, file=self.output)

    def write_box(self, lines: Sequence[str], *, double: bool = False) -> None:
        """Render one separated box using a complete single- or double-line Unicode set."""
        rendered_lines = [
            self.localizer.text(line) if self.localizer is not None else line
            for line in lines
        ]
        inner_width = max(70, *(len(line) for line in rendered_lines))
        if double:
            top_left, horizontal, top_right = "╔", "═", "╗"
            vertical = "║"
            bottom_left, bottom_right = "╚", "╝"
        else:
            top_left, horizontal, top_right = "┌", "─", "┐"
            vertical = "│"
            bottom_left, bottom_right = "└", "┘"
        self.write()
        self.write(top_left + horizontal * inner_width + top_right)
        for line in rendered_lines:
            self.write(vertical + line.ljust(inner_width) + vertical)
        self.write(bottom_left + horizontal * inner_width + bottom_right)
        self.write()

    def write_menu_header(self, title: str, *, major: bool = True) -> None:
        """Render a boxed major title or an indented, underlined minor heading."""
        rendered = self.localizer.text(title) if self.localizer is not None else title
        if major:
            self.write_box((f" {rendered}",), double=True)
            return
        self.write()
        self.write(f"> {rendered}")
        self.write("─" * 72)
        self.write()

    def write_menu_footer(self, *, include_back: bool, allow_language: bool = True) -> None:
        """Render the invariant A-F controls in one separated single-line box."""
        tr = self.localizer.text if self.localizer is not None else lambda value: value
        navigation = []
        if include_back:
            navigation.append(f"A. {tr('Back')}")
        navigation.extend((f"B. {tr('Main Menu')}", f"C. {tr('Exit SAGE')}"))
        services: list[str] = []
        if allow_language and self.language_handler is not None:
            services.append(f"D. {tr('Language')}")
        if self.help_handler is not None:
            services.append(f"E. {tr('Help')}")
        if self.status_handler is not None:
            services.append(f"F. {tr('Status')}")
        lines = ["  " + "   ".join(navigation)]
        if services:
            lines.append("  " + "   ".join(services))
        self.write_box(lines, double=False)

    def status(self, value: str) -> None:
        """Render one replaceable terminal status line without polluting redirected logs."""
        if not bool(getattr(self.output, "isatty", lambda: False)()):
            return
        self._prepare_panel_output()
        print(f"\r{value}", end="", file=self.output, flush=True)

    def clear_status(self) -> None:
        """Finish the current replaceable status line when interactive status is visible."""
        if not bool(getattr(self.output, "isatty", lambda: False)()):
            return
        print(file=self.output, flush=True)

    @contextmanager
    def working(self, label: str = "Working", *, ellipsis: bool = True) -> Iterator[None]:
        """Show a live spinner for bounded work without changing scripted-test behavior."""
        rendered = self.localizer.text(label) if self.localizer is not None else label
        is_tty = bool(getattr(self.output, "isatty", lambda: False)())
        suffix = "..." if ellipsis else ""
        if not is_tty:
            self.write(f"{rendered}{suffix}")
            yield
            return
        self._prepare_panel_output()
        stop = Event()
        spinner = "|/-\\"

        def animate() -> None:
            """Advance the terminal spinner until the bounded work completes."""
            index = 0
            while not stop.wait(0.12):
                marker = spinner[index % len(spinner)]
                print(f"\r{rendered}{suffix}      {marker}", end="", file=self.output, flush=True)
                index += 1

        worker = Thread(target=animate, name="sage-working-spinner", daemon=True)
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join(timeout=0.5)
            print(f"\r{' ' * (len(rendered) + len(suffix) + 8)}\r", end="", file=self.output, flush=True)

    def read(self, prompt: str) -> str:
        """Read one operator response and convert closed input into a governed cancellation."""
        try:
            return self.input_func(prompt)
        except EOFError as exc:
            raise OperatorCancelledError(
                "Interactive input closed before the menu action completed",
                next_action="Rerun the command in an interactive terminal or use --no-prompt/--json.",
            ) from exc

    def choose(
        self,
        title: str,
        options: Sequence[tuple[str, str]],
        *,
        prompt: str = "Choose: ",
        allow_blank: bool = False,
        direct_validator: Callable[[str], str] | None = None,
        context: Sequence[str] = (),
        option_heading: str | None = None,
        allow_language_hotkey: bool = True,
        blank_before: Sequence[str] = (),
    ) -> str:
        """Choose a numeric operation or one invariant footer navigation/service control."""
        option_map = {key: label for key, label in options}
        internal_navigation = {key for key in ("B", "H", "X") if key in option_map}
        visible = [(key, label) for key, label in options if key not in internal_navigation]
        invalid_visible = [key for key, _label in visible if not key.isdigit()]
        if invalid_visible:
            raise ConfigurationError(
                "Visible menu operations must use numeric keys; reserved footer controls are A-F: "
                + ", ".join(invalid_visible)
            )
        valid = {key.casefold(): key for key, _ in visible}

        def tr(value: str) -> str:
            """Return one menu label in the active interface locale."""
            return self.localizer.text(value) if self.localizer is not None else value

        def render() -> None:
            """Render operations plus the invariant two-line navigation/service footer."""
            self.write_menu_header(title)
            for row in context:
                self.write(row)
            if option_heading is not None:
                self.write_menu_header(option_heading, major=False)
            elif context:
                self.write()
            blank_keys = set(blank_before)
            for key, label in visible:
                if key in blank_keys:
                    self.write()
                self.write(menu_item(key, tr(label)))
            self.write_menu_footer(
                include_back="B" in internal_navigation,
                allow_language=allow_language_hotkey,
            )

        render()
        while True:
            value = self.read(tr(prompt)).strip()
            if allow_blank and not value:
                self.request_panel_reset()
                return ""
            folded = value.casefold()
            if folded == "a" and "B" in internal_navigation:
                self.request_panel_reset()
                return "B"
            if folded == "b":
                self.request_panel_reset()
                if "H" in internal_navigation:
                    return "H"
                raise MenuHomeRequested()
            if folded == "c":
                self.request_panel_reset()
                if "X" in internal_navigation:
                    return "X"
                raise MenuExitRequested()
            if folded == "d" and allow_language_hotkey and self.language_handler is not None:
                self.request_panel_reset()
                self.language_handler()
                render()
                continue
            if folded in {"e", "?"} and self.help_handler is not None:
                self.request_panel_reset()
                self.help_handler(title)
                render()
                continue
            if folded == "f" and self.status_handler is not None:
                self.request_panel_reset()
                self.status_handler()
                render()
                continue
            key = valid.get(folded)
            if key is not None:
                self.request_panel_reset()
                return key
            if direct_validator is not None:
                try:
                    result = direct_validator(value)
                except SageError as exc:
                    self.write(str(exc))
                    continue
                self.request_panel_reset()
                return result
            self.write("Invalid choice. Choose one listed option.")

    def text(
        self,
        label: str,
        *,
        default: str | None = None,
        required: bool = True,
        validator: Callable[[str], str] | None = None,
    ) -> str:
        """Implement `text` in the deterministic terminal control flow."""
        suffix = f" [{default}]" if default is not None else ""
        while True:
            rendered_label = self.localizer.text(label) if self.localizer is not None else label
            value = self.read(f"{rendered_label}{suffix}: ").strip()
            if not value and default is not None:
                value = default
            if not value and required:
                self.write(f"{rendered_label} is required.")
                continue
            if validator is not None and value:
                try:
                    value = validator(value)
                except Exception as exc:  # bounded UI conversion
                    self.write(str(exc))
                    continue
            return value

    def confirm(self, prompt: str, *, default: bool = True) -> bool:
        """Implement `confirm` in the deterministic terminal control flow."""
        marker = "Y/n" if default else "y/N"
        rendered_prompt = self.localizer.text(prompt) if self.localizer is not None else prompt
        while True:
            value = self.read(f"{rendered_prompt} [{marker}]: ").strip().casefold()
            if not value:
                return default
            if value in {"y", "yes"}:
                return True
            if value in {"n", "no"}:
                return False
            self.write("Enter yes or no.")

    def pause(self) -> None:
        """Return immediately; subsequent menu headings delimit completed actions."""


class ScriptedInput:
    """One-response-per-line input provider for deterministic menu tests and demos."""

    def __init__(self, values: Iterable[str]) -> None:
        """Implement `  init  ` in the deterministic terminal control flow."""
        self.values = iter(values)

    def __call__(self, prompt: str) -> str:
        """Implement `  call  ` in the deterministic terminal control flow."""
        try:
            value = next(self.values)
        except StopIteration as exc:
            raise EOFError(f"Menu script ended at prompt: {prompt}") from exc
        return value.rstrip("\r\n")


def _json_file(path: Path) -> dict[str, Any]:
    """Implement ` json file` in the deterministic terminal control flow."""
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _relative(root: Path, path: Path) -> str:
    """Implement ` relative` in the deterministic terminal control flow."""
    return operator_path(root, path)


class SageControlCenter:
    """Operate BIC and SAW from one deterministic terminal menu."""

    def __init__(
        self,
        *,
        sage_root: Path,
        settings_path: Path | None = None,
        io: MenuIO | None = None,
        force_setup: bool = False,
        skip_setup: bool = False,
        dry_run_provider: bool = False,
    ) -> None:
        """Implement `  init  ` in the deterministic terminal control flow."""
        self.root = sage_root.expanduser().resolve()
        self.store = JobStore(self.root, settings_path)
        self.io = io or MenuIO()
        self.localizer = InterfaceLocalizer.load(self.root, self.store.settings_path)
        self.io.localizer = self.localizer
        self.io.language_handler = self.interface_language_menu
        self.io.help_handler = self._context_help
        self.io.status_handler = self.status_overlay
        self.force_setup = force_setup
        self.skip_setup = skip_setup
        self.dry_run_provider = dry_run_provider
        self.ollama_admin = OllamaAdminService(self.root)
        self.runtime_status = RuntimeStatus(interface_language=self.localizer.language)
        self.ui_service = OperatorUIService(
            root=self.root, settings_path=self.store.settings_path, runtime_status=self.runtime_status
        )
        # A successful Codex sampling probe is cached briefly so partitioned SAW/BIC
        # work does not spend one extra model request on every work unit.  Login and
        # catalog readiness alone do not prove the WebSocket sampling channel works.
        self._codex_transport_verified_until = 0.0
        self._compact_saw_progress = False

    # ---------- Controller bridge ----------

    def controller(self, project: Job, arguments: Sequence[str]) -> Any:
        """Run one canonical controller command against a Job-scoped config."""
        settings = self.store.ensure_runtime_files(project)
        command = [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(settings),
            "--json",
            "--no-prompt",
            *arguments,
        ]
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
        env["SAGE_DISABLE_HUMAN_CONSOLE"] = "1"
        core_path = str(self.root / "system" / "src")
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            core_path if not existing_pythonpath else os.pathsep.join((core_path, existing_pythonpath))
        )
        completed = subprocess.run(
            command,
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
        )
        text = completed.stdout.strip()
        payload: Any = None
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"status": "UNPARSEABLE_OUTPUT", "stdout": text}
        if completed.returncode != 0:
            details = payload if isinstance(payload, dict) else {}
            reported_errors = [str(value) for value in details.get("errors", [])]
            message = str(
                details.get("message")
                or ("; ".join(reported_errors) if reported_errors else "")
                or completed.stderr.strip()
                or "Controller command failed"
            )
            blocked = str(details.get("state") or "").upper() == "BLOCKED"
            raise ValidationError(
                message,
                code=str(
                    details.get("reason_code")
                    or ("WORKSPACE_INITIALIZATION_BLOCKED" if blocked else "MENU_CONTROLLER_COMMAND_FAILED")
                ),
                next_action=(str(details.get("next_action")) if details.get("next_action") else None),
                details={
                    "command": command,
                    "returncode": completed.returncode,
                    "payload": details,
                    "stderr": completed.stderr.strip(),
                },
            )
        return payload

    def project_state(self, project: Job) -> dict[str, Any]:
        """Implement `project state` in the deterministic terminal control flow."""
        config = load_ecosystem(self.store.ensure_runtime_files(project))
        return read_state(ecosystem_state_path(config.runtime_state_root))

    def ensure_initialized(self, project: Job, *, force: bool = False) -> dict[str, Any]:
        """Implement `ensure initialized` in the deterministic terminal control flow."""
        settings = self.store.ensure_runtime_files(project)
        config = load_ecosystem(settings)
        state = read_state(ecosystem_state_path(config.runtime_state_root))
        settings_hash = sha256_file(settings)
        if (
            not force
            and state.get("state") in {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}
            and state.get("settings_sha256") == settings_hash
        ):
            return state
        if project.tool == "saw":
            label = f"Initializing {project.output_project} analyzed against {project.contemporary_source}"
        else:
            label = f"Initializing {project.display_name}"
        with self.io.working(label, ellipsis=False):
            payload = self.controller(project, ["workspace", "initialize"])
        return dict(payload) if isinstance(payload, dict) else {}

    # ---------- Setup ----------

    def setup_required(self, model_row: dict[str, Any] | None = None) -> bool:
        """Return whether canonical live prerequisites still require guided setup."""
        if self.force_setup:
            return True
        if self.skip_setup:
            return False
        snapshot = self.ui_service.startup_readiness(model_row, persist_completion=True)
        return bool(snapshot.get("requires_setup"))

    def _setup_document_paths(self) -> tuple[str, str, str]:
        """Return the platform cheat-sheet, recovery, and error references."""
        folder = "windows" if os.name == "nt" else "macos-linux"
        return (
            f"docs/{folder}/CHEAT-SHEET.md",
            f"docs/{folder}/RECOVERY.md",
            f"docs/{folder}/ERRORS.md",
        )

    def _write_ai_status(self, row: dict[str, Any], *, prefix: str = "") -> None:
        """Render the canonical AI prerequisite fields in the common aligned report style."""
        self.io.write(f"{prefix + 'AI connection':<25}{row.get('connection') or 'NOT CHECKED'}")
        self.io.write(f"{prefix + 'Provider':<25}{row.get('provider') or 'NOT CONFIGURED'}")
        self.io.write(f"{prefix + 'Model':<25}{row.get('model') or 'NOT AVAILABLE'}")
        self.io.write(f"{prefix + 'Reasoning level':<25}{row.get('reasoning_level') or 'NOT REPORTED'}")
        self.io.write(f"{prefix + 'AI prerequisite':<25}{row.get('prerequisite_status') or 'BLOCKED'}")

    def _render_startup_report(self, ai: dict[str, Any]) -> None:
        """Render the live prerequisite report before normal menu entry."""
        projects_root_status, projects_root = self._setup_projects_root_status()
        readiness = self.ui_service.startup_readiness(ai)
        stale_pointers = self.store.stale_active_job_pointers()
        catalogue = load_paratext_catalog(self.root)
        summary = catalog_summary(catalogue)
        self.io.write()
        self.io.write("SAGE STARTUP")
        self.io.write("=" * 72)
        self.io.write(f"{'Runtime':<25}READY")
        self.io.write(f"{'SAGE configuration':<25}{'READY' if self.store.settings_path.is_file() else 'ACTION NEEDED'}")
        root_text = projects_root_status.replace("_", " ")
        if projects_root_status == "READY" and projects_root is not None:
            root_text = f"READY - {projects_root}"
        self.io.write(f"{'Paratext Projects root':<25}{root_text}")
        self.io.write(f"{'Projects discovered':<25}{summary.get('discovered', summary.get('projects', 0))}")
        self.io.write(f"{'Projects pending':<25}{summary.get('pending', 0)}")
        self._write_ai_status(ai)
        if stale_pointers:
            detail = ", ".join(f"{tool.upper()} {job_id}" for tool, job_id in sorted(stale_pointers.items()))
            self.io.write(f"{'Job state':<25}ACTION NEEDED - {detail} [manifest missing]")
        overall = str(readiness.get("status") or "INCOMPLETE")
        self.io.write()
        self.io.write(f"{'Overall':<25}{overall}")
        if stale_pointers:
            self.io.write(f"{'Reason code':<25}ACTIVE_JOB_POINTER_STALE")
            self.io.write(
                f"{'Next action':<25}Open SAGE Maintenance > System recovery and diagnostics > "
                "Clear active Job and Run selections."
            )
        elif not ai.get("ready"):
            self.io.write(f"{'Reason code':<25}{ai.get('reason_code') or 'AI_CONNECTION_FAILED'}")
            self.io.write(f"{'Next action':<25}Open AI Setup and test the connection.")

    def _context_help(self, title: str) -> None:
        """Show concise context-sensitive help and return to the invoking menu."""
        self.io.write()
        self.io.write(f"HELP - {title}")
        self.io.write("-" * 72)
        for line in context_help_lines(title):
            self.io.write(line)
        self.io.pause()

    def status_overlay(self) -> None:
        """Show the shared canonical runtime/configuration state without deep validation."""
        snapshot = self.ui_service.runtime_snapshot()
        ai = dict(snapshot.get("ai") or {})
        projects = dict(snapshot.get("projects") or {})
        root_value = snapshot.get("projects_root") or "NOT CONFIGURED"
        self.io.write()
        self.io.write("SAGE STATUS")
        self.io.write("=" * 72)
        self.io.write(f"{'State':<25}{snapshot.get('state') or 'IDLE'}")
        self.io.write(f"{'Task':<25}{snapshot.get('active_task') or 'NONE'}")
        self.io.write(f"{'Stage':<25}{snapshot.get('stage') or '—'}")
        self.io.write(f"{'Progress':<25}{snapshot.get('progress') or '—'}")
        self.io.write(f"{'Current Job':<25}{snapshot.get('current_job') or 'NONE'}")
        self.io.write(f"{'Current Project':<25}{snapshot.get('current_project') or 'NONE'}")
        self.io.write(f"{'Current Run':<25}{snapshot.get('current_run') or 'NONE'}")
        progress = dict(snapshot.get("job_progress") or {})
        if progress:
            self.io.write()
            self.io.write("ACTIVE JOB")
            self.io.write(str(progress.get("line") or "—"))
            self.io.write(str(progress.get("activity") or "—"))
            self.io.write(
                f"Run: {progress.get('run_id') or '—'}    "
                f"Stage: {str(progress.get('stage') or '—').replace('_', ' ')}"
            )
            self.io.write(
                f"Tasks: {progress.get('task_completed', 0)}/{progress.get('task_total', 0)}"
            )
            if progress.get("result") == "BLOCKED" and progress.get("reason_code"):
                self.io.write(f"Block reason: {progress.get('reason_code')}")
        self.io.write()
        self.io.write(f"{'Paratext root':<25}{root_value}")
        self.io.write(f"{'Projects registered':<25}{projects.get('registered', 0)}")
        self.io.write(f"{'Projects discovered':<25}{projects.get('discovered', 0)}")
        self.io.write(f"{'Projects validated':<25}{projects.get('validated', 0)}")
        self.io.write(f"{'Projects pending':<25}{projects.get('pending', 0)}")
        self.io.write(f"{'Resource tree':<25}{snapshot.get('resource_status') or 'NOT CHECKED'}")
        if snapshot.get("resource_change_count"):
            self.io.write(f"{'Resource changes':<25}{snapshot['resource_change_count']}")
        self.io.write()
        self._write_ai_status(ai)
        self.io.write(f"{'Last AI check':<25}{ai.get('last_checked') or 'NEVER'}")
        local_ai = dict(snapshot.get("local_ai") or {})
        self.io.write(f"{'Local AI':<25}{'ON' if local_ai.get('enabled') else 'OFF'}")
        self.io.write(f"{'Local AI model':<25}{local_ai.get('model') or '—'}")
        self.io.write(f"{'Local AI authority':<25}{local_ai.get('authority') or 'ASSISTIVE_ONLY'}")
        self.io.write(f"{'Local AI readiness':<25}{local_ai.get('readiness') or 'NOT_PROBED'}")
        self.io.write(f"{'Reporting mode':<25}{local_ai.get('reporting_mode') or 'MULTILINGUAL_AVAILABLE'}")
        self.io.write(
            f"{'Secondary reporting':<25}"
            f"{'AVAILABLE' if local_ai.get('secondary_language_allowed') else 'DISABLED'}"
        )
        if local_ai.get("enablement_blocked"):
            self.io.write(f"{'Local AI reason':<25}{local_ai.get('reason_code')}")
        assistive = self.ui_service.assistive_status_explanation(snapshot)
        if assistive and assistive.get("text"):
            self.io.write()
            self.io.write("LOCAL AI NOTE - NON-AUTHORITATIVE")
            self.io.write(str(assistive["text"]))
        self.io.write(
            f"{'Interface language':<25}{snapshot.get('interface_language_name')} "
            f"[{snapshot.get('interface_language')}]"
        )
        self.io.pause()

    def _setup_model_probe(
        self,
        service: ModelService,
        *,
        refresh: bool = False,
        allow_dry_run: bool = True,
    ) -> dict[str, Any]:
        """Return the canonical live workflow-AI prerequisite status."""
        return probe_workflow_ai(
            self.root,
            self.runtime_status,
            service=service,
            refresh=refresh,
            dry_run_provider=self.dry_run_provider,
            allow_dry_run=allow_dry_run,
        )

    def _setup_install_codex(self, service: ModelService) -> dict[str, Any]:
        """Offer an explicit, platform-aware Codex CLI install and return refreshed status."""
        self.io.write("Codex CLI is required for SAGE AI work; the desktop app is not required.")
        ready, missing = CodexCLIExecutor.installation_prerequisites()
        if not ready:
            raise ValidationError(
                f"Codex installer prerequisites are missing: {', '.join(missing)}",
                code="CODEX_INSTALL_PREREQUISITE_MISSING",
                next_action=CodexCLIExecutor.installation_guidance(),
            )
        self.io.write(CodexCLIExecutor.installation_guidance())
        if not self.io.confirm("Install Codex CLI now?", default=True):
            return self._setup_model_probe(service, refresh=True, allow_dry_run=False)
        self.store.record_cue("CODEX_INSTALL_APPROVED")
        self.io.write("Running the official Codex CLI installer in non-interactive mode...")
        service.install_codex()
        self.io.write("Codex CLI verified. Returning to SAGE; the Codex interactive shell was not launched.")
        return self._setup_model_probe(service, refresh=True)

    def _setup_configured_tools(self) -> set[str]:
        """Return workflows that currently have one active project binding."""
        return self.ui_service.configured_tools()

    def _setup_projects_root_status(self) -> tuple[str, Path | None]:
        """Return shared live readiness for the workstation Paratext Projects root."""
        return self.ui_service.projects_root_status()

    def _setup_workflow_status(self, tool: str, init_results: dict[str, Any]) -> str:
        """Return one concise independent setup status for BIC or SAW."""
        return self.ui_service.workflow_setup_status(tool, init_results)

    def _setup_live_initialisation_results(
        self,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reconcile setup summaries through the shared startup-readiness service."""
        return self.ui_service.live_initialization_results(previous)

    def _setup_initialize_projects(self) -> dict[str, Any]:
        """Initialize selected projects and report blocked actions without leaving setup."""
        results: dict[str, Any] = {}
        for tool in TOOL_IDS:
            project = self.store.active_job(tool)
            if project is None:
                continue
            try:
                state = self.ensure_initialized(project, force=False)
                project_status = state.get("state", state.get("status", "UNKNOWN"))
                results[project.job_id] = {"status": project_status}
                self.io.write(f"{tool.upper()} {project.job_id}: {project_status}")
            except SageError as exc:
                results[project.job_id] = {
                    "status": "BLOCKED",
                    "reason_code": exc.code,
                    "message": exc.message,
                }
                self.io.write(f"{tool.upper()} {project.job_id}: BLOCKED - {exc.message}")
                if exc.next_action:
                    self.io.write(f"  Next: {exc.next_action}")
        if not results:
            self.io.write("No active BIC or SAW Job yet.")
        return results

    def _setup_next_step(
        self,
        model_row: dict[str, Any],
        enabled_tools: set[str],
        init_results: dict[str, Any],
        scripture_resources: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Return the shared recommended next setup action."""
        return self.ui_service.startup_next_step(
            model_row, enabled_tools, init_results, scripture_resources
        )

    def _save_setup_state(
        self,
        *,
        service: ModelService,
        model_row: dict[str, Any],
        enabled_tools: set[str],
        init_results: dict[str, Any],
        scripture_resources: dict[str, Any],
    ) -> tuple[str, str]:
        """Persist resumable setup state after every meaningful setup transition."""
        next_step, next_label = self._setup_next_step(
            model_row, enabled_tools, init_results, scripture_resources
        )
        status = "COMPLETE" if next_step == "COMPLETE" else "INCOMPLETE"
        llm_settings = service.settings()
        provider_item = dict(llm_settings["providers"].get("codex", {}))
        self.store.write_setup_state(
            {
                "status": status,
                "next_step": next_step,
                "next_label": next_label,
                "sage_root": str(self.root),
                "settings_path": str(self.store.settings_path),
                "enabled_tools": sorted(enabled_tools),
                "active_jobs": self.store.active_jobs(),
                "llm": {
                    "selected_provider": llm_settings["selected_provider"],
                    "available": bool(model_row.get("available")),
                    "ready": bool(model_row.get("ready")),
                    "connection": model_row.get("connection"),
                    "provider": model_row.get("provider"),
                    "provider_id": model_row.get("provider_id"),
                    "auth_mode": model_row.get("auth_mode"),
                    "version": model_row.get("version"),
                    "model": model_row.get("model"),
                    "reasoning_level": model_row.get("reasoning_level"),
                    "prerequisite_status": model_row.get("prerequisite_status"),
                    "last_checked": model_row.get("last_checked"),
                    "reason_code": model_row.get("reason_code"),
                    "selected_model": provider_item.get("model"),
                    "selected_reasoning_effort": provider_item.get("reasoning_effort"),
                    "diagnostic": model_row.get("diagnostic"),
                },
                "initialization": init_results,
                "scripture_resources": scripture_resources,
                "interface_language": self.localizer.language,
                "operator_docs": list(self._setup_document_paths()),
            }
        )
        return next_step, next_label

    def _setup_scripture_resource_status(self, *, render: bool = False) -> dict[str, Any]:
        """Validate Scripture/VRS resources and optionally render the first-run summary."""
        result = validate_scripture_resources(
            self.root, self.store.settings_path, persist_discovery=True
        )
        discovery = dict(result.get("resource_discovery") or {})
        self.runtime_status.resource_status = str(discovery.get("status") or "NOT CHECKED")
        self.runtime_status.resource_change_count = int(discovery.get("change_count") or 0)
        if render:
            self.io.write()
            self.io.write("SCRIPTURE RESOURCE CHECK")
            self.io.write("-" * 72)
            self.io.write(f"Status:              {self._human_scripture_status(result)}")
            self.io.write(f"Base VRS files:      {sum(1 for row in result['base_vrs'] if row['status'] == 'READY')}/{len(result['base_vrs'])} READY")
            self.io.write(f"SAGE Projects:      {result['registered_projects']}")
            self.io.write(f"Mapped projects:     {result['mapped_projects']}")
            self.io.write(f"Projects root:       {result.get('projects_root') or 'NOT CONFIGURED'}")
            catalogue = result.get("catalog", {})
            self.io.write(
                f"Paratext catalog:    {catalogue.get('discovered', catalogue.get('projects', 0))} discovered; "
                f"{catalogue.get('validated', 0)} validated; {catalogue.get('pending', 0)} pending"
            )
            self.io.write(
                f"Resource tree:       {discovery.get('status', 'NOT CHECKED')}"
                + (f" - {discovery.get('change_count', 0)} change(s)" if discovery.get("change_count") else "")
            )
            ol = result.get("original_language", {})
            self.io.write(f"OL capability:       {ol.get('status', 'UNKNOWN')}")
            for row in ol.get("resources", []):
                self.io.write(f"  {row['alias']}: {row['status']} [{row['source']}]")
            if result["status"] == "READY_EMPTY":
                self.io.write("Project inventory is empty. Add a Paratext Project to SAGE when required.")
            for row in result.get("projects", []):
                self.io.write(
                    f"  {row['project_id']}: {row['status']} "
                    f"scope={row['detected_scope']} path={row.get('path') or 'UNMAPPED'}"
                )
            for item in result.get("errors", []):
                self.io.write(f"  BLOCKED: {item['resource']} - {item['code']}")
            for item in result.get("warnings", []):
                self.io.write(f"  ATTENTION: {item['resource']} - {item['code']}")
            for item in result.get("nonblocking_warnings", []):
                self.io.write(f"  OL NOTICE: {item['resource']} - {item['code']}")
        return result

    @staticmethod
    def _human_scripture_status(result: dict[str, Any]) -> str:
        """Render a Scripture-resource machine state as concise Operator wording."""
        status = str(result.get("status") or "UNKNOWN")
        count = int(result.get("registered_projects") or 0)
        project_label = "SAGE Project" if count == 1 else "SAGE Projects"
        if status == "READY_EMPTY":
            return "No SAGE Projects added yet"
        if status == "READY":
            return f"Ready - {count} {project_label}"
        if status == "READY_WITH_WARNINGS":
            return f"Attention needed - {count} {project_label}"
        if status == "BLOCKED":
            return f"Action needed - {count} {project_label}"
        return status.replace("_", " ").title()

    def _show_support_docs(self) -> None:
        """Show only the platform-specific fallback cheat sheets."""
        self.io.write("SAGE normally guides setup and operation in the terminal.")
        self.io.write("Use these only for recovery, errors, or command lookup:")
        for path in self._setup_document_paths():
            self.io.write(f"  {path}")
        self.io.pause()

    def _system_runtime_status(self) -> None:
        """Show only Python and managed-runtime dependency state."""
        self.io.write(f"Python: {sys.version.split()[0]}")
        layout = storage_layout(self.root)
        self.io.write(f"Managed environment: {layout.venv_root}")
        self.io.write(f"Managed environment present: {'YES' if layout.venv_root.is_dir() else 'NO'}")
        try:
            import yaml
            self.io.write(f"PyYAML: {getattr(yaml, '__version__', 'installed')}")
        except ImportError:
            self.io.write("PyYAML: MISSING")
        self.io.pause()

    def _system_show_paths(self) -> None:
        """Show the small set of paths needed for configuration and recovery."""
        config = load_ecosystem(self.store.settings_path)
        self.io.write(f"SAGE root: {self.root}")
        self.io.write(f"Settings: {self.store.settings_path}")
        self.io.write(f"localdata: {config.data_root}")
        self.io.write(f"State: {self.store.state_root}")
        layout = storage_layout(self.root)
        self.io.write(f"SAGE Project Inventory: {layout.state_root / 'project-inventory.json'}")
        self.io.write(f"External resource mappings: {layout.state_root / 'resource-mounts.json'}")
        self.io.write(f"Jobs: {layout.jobs_root}")
        self.io.pause()

    def _scan_progress(self, done: int, total: int) -> None:
        """Show the current single-line Paratext scan heartbeat."""
        spinner = "|/-\\"
        marker = spinner[done % len(spinner)]
        suffix = f" {done}/{total}" if total else ""
        self.runtime_status.state = "RUNNING"
        self.runtime_status.active_task = "Paratext scan"
        self.runtime_status.stage = "Project discovery"
        self.runtime_status.progress = f"{done}/{total}" if total else None
        self.io.status(f"Scanning Paratext Projects... {marker}{suffix}")

    def _scan_projects(self, projects_root: Path, *, full: bool) -> dict[str, Any]:
        """Scan Paratext Projects with a visible heartbeat and finish on a normal line."""
        try:
            configured_status, configured_root = self.ui_service.projects_root_status()
            if configured_status == "READY" and configured_root == projects_root.expanduser().resolve():
                return self.ui_service.scan_projects(full=full, progress=self._scan_progress)
            return scan_paratext_projects(
                self.root,
                projects_root,
                full=full,
                progress=self._scan_progress,
            )
        finally:
            self.io.clear_status()
            self.runtime_status.state = "IDLE"
            self.runtime_status.active_task = None
            self.runtime_status.stage = None
            self.runtime_status.progress = None

    def _write_catalog_summary(self, catalogue: dict[str, Any]) -> None:
        """Render the Project catalog as an operator report rather than raw JSON."""
        summary = catalog_summary(catalogue)
        self.io.write("PARATEXT PROJECT CATALOG")
        self.io.write("=" * 72)
        self.io.write(f"{'Projects root':<25}{catalogue.get('projects_root') or 'NOT CONFIGURED'}")
        self.io.write(f"{'Projects discovered':<25}{summary.get('discovered', summary.get('projects', 0))}")
        self.io.write(f"{'Languages known':<25}{summary.get('languages', 0)}")
        self.io.write()
        self.io.write("Detailed validation")
        self.io.write(f"{'Validated':<25}{summary.get('validated', 0)}")
        self.io.write(f"{'Pending':<25}{summary.get('pending', 0)}")
        self.io.write(f"{'Ready':<25}{summary.get('ready', 0)}")
        self.io.write(f"{'Warnings':<25}{summary.get('warnings', 0)}")
        self.io.write(f"{'Invalid':<25}{summary.get('invalid', 0)}")
        self.io.write()
        self.io.write(f"{'Last quick scan':<25}{summary.get('last_quick_scan') or 'NEVER'}")
        self.io.write(f"{'Last full scan':<25}{summary.get('last_full_scan') or 'NEVER'}")

    def _run_with_status(
        self,
        message: str,
        action: Callable[[], Any],
        *,
        visible: bool = True,
    ) -> Any:
        """Run one blocking action with an optional Operator-facing heartbeat."""
        if not visible:
            return action()
        if getattr(self, "_compact_saw_progress", False):
            return action()
        if not bool(getattr(self.io.output, "isatty", lambda: False)()):
            self.io.write(message.rstrip())
            return action()
        frames = "|/-\\"
        frame = 0
        self.runtime_status.state = "RUNNING"
        self.runtime_status.active_task = message.rstrip(". ")
        self.runtime_status.stage = "Executing"
        self.runtime_status.progress = None
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="sage-menu-status") as pool:
            future = pool.submit(action)
            try:
                self.io.status(f"{message} {frames[frame]}")
                while not future.done():
                    time.sleep(0.12)
                    if future.done():
                        break
                    frame = (frame + 1) % len(frames)
                    self.io.status(f"{message} {frames[frame]}")
                return future.result()
            finally:
                self.io.clear_status()
                self.runtime_status.state = "IDLE"
                self.runtime_status.active_task = None
                self.runtime_status.stage = None
                self.runtime_status.progress = None

    def paths_and_workspace_menu(self) -> None:
        """Configure operator paths, including the primary Paratext/PTLite Projects root."""
        while True:
            config = load_ecosystem(self.store.settings_path)
            state = load_resource_mount_state(self.root)
            primary = state.get("projects_root")
            base_mode = "[override]" if state.get("base_vrs_root") else "[default: Paratext root]"
            choice = self.io.choose(
                "PATHS AND WORKSPACE LOCATIONS",
                (("1", "Paratext Projects root"), ("2", "Base VRS folder override"), ("3", "Use Paratext root for base VRS"), ("B", "Back")),
                context=(
                    f"{'Paratext Projects root':<28}{primary or 'NOT CONFIGURED'}",
                    f"{'Scripture resources':<28}{config.projects_root}",
                    f"{'Base VRS root':<28}{config.base_vrs_root} {base_mode}",
                    f"{'localdata':<28}{config.data_root}",
                    f"{'State':<28}{self.store.state_root}",
                    f"{'Project inventory':<28}{storage_layout(self.root).state_root / 'project-inventory.json'}",
                    f"{'Resource mappings':<28}{storage_layout(self.root).state_root / 'resource-mounts.json'}",
                ),
                option_heading="PATH ACTIONS",
            )
            if choice == "B":
                return
            if choice == "1":
                value = Path(normalize_operator_path(self.io.text("Paratext Projects root"))).expanduser()
                set_project_root(self.root, project_root=value, progress=self._scan_progress)
                self.io.clear_status()
                self.io.write(f"Saved primary Projects root: {value.resolve()}")
                self.io.pause()
            elif choice == "2":
                value = Path(normalize_operator_path(self.io.text("Absolute base VRS folder"))).expanduser()
                destination = set_base_vrs_root(self.root, base_vrs_root=value)
                self.io.write(f"Base VRS root configured. Registry: {destination}")
                self.io.pause()
            elif choice == "3":
                clear_base_vrs_root(self.root)
                self.io.write("Base VRS root now follows the configured Paratext Projects root.")
                self.io.pause()

    def interface_language_menu(self) -> None:
        """Configure the Setup-owned SAGE interface language only."""
        while True:
            current = self.localizer.language
            self.io.write()
            self.io.write("INTERFACE LANGUAGE")
            self.io.write("-" * 72)
            self.io.write(f"Current interface language: {self.localizer.language_name(current)} [{current}]")
            options = tuple(
                (str(index), f"{LANGUAGE_DISPLAY_NAMES[language]} [{language}]")
                for index, language in enumerate(SUPPORTED_INTERFACE_LANGUAGES, 1)
            ) + (("B", "Back"),)
            choice = self.io.choose(
                "Choose interface language",
                options,
                allow_language_hotkey=False,
            )
            if choice == "B":
                return
            selected = SUPPORTED_INTERFACE_LANGUAGES[int(choice) - 1]
            self.localizer.set_language(selected)
            self.ui_service.refresh_localizer()
            self.store.record_cue("INTERFACE_LANGUAGE_CHANGED", language=selected)
            self.io.write(f"Interface language: {self.localizer.language_name(selected)} [{selected}]")
            return

    def system_configuration_menu(self) -> str:
        """Keep system administration separate from BIC/SAW Job work."""
        while True:
            choice = self.io.choose(
                "SAGE MAINTENANCE",
                (
                    ("1", "Configure AI"),
                    ("2", "Configure languages"),
                    ("3", "Configure paths and storage"),
                    ("4", "Run system checks"),
                    ("5", "System information, recovery and diagnostics"),
                    ("B", "Back"), ("H", "Main Menu"), ("X", "Exit SAGE"),
                ),
            )
            if choice == "B": return "BACK"
            if choice == "H": return "MAIN"
            if choice == "X": return "EXIT"
            try:
                if choice == "1": self.model_menu()
                elif choice == "2": self.configure_languages_menu()
                elif choice == "3": self.paths_and_workspace_menu()
                elif choice == "4": self.system_diagnostics_menu()
                elif choice == "5":
                    self.system_recovery_menu()
            except SageError as exc:
                self.show_error(exc)

    def _language_ui_config(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Load governed language identity, relationship, and competency display configuration."""
        base = self.root / "system" / "config" / "languages"
        return (
            dict(load_yaml_compat(base / "registry.yml") or {}),
            dict(load_yaml_compat(base / "relationships.yml") or {}),
            dict(load_yaml_compat(base / "competency.yml") or {}),
        )

    @staticmethod
    def _display_competency_tier(tier: str, tag: str, competency_cfg: dict[str, Any]) -> str:
        """Map internal competency tiers to the concise Operator vocabulary."""
        display = dict(competency_cfg.get("display") or {})
        baseline = {str(value) for value in display.get("baseline_profiles", [])}
        if tag in baseline:
            return "BASELINE"
        mapping = dict(display.get("tier_map") or {})
        return str(mapping.get(str(tier or "UNASSESSED").upper(), tier or "NOT CHECKED")).replace("_", " ")

    def _configured_competency_map(self) -> dict[str, str]:
        """Return competency labels for the currently selected model keyed by configured profile tag."""
        _, _, competency_cfg = self._language_ui_config()
        try:
            status = ModelService(self.root).language_competency_status("codex")
        except SageError:
            status = {}
        result: dict[str, str] = {}
        for row in status.get("rows", []) if isinstance(status, dict) else []:
            if isinstance(row, (list, tuple)) and len(row) >= 3:
                tag, _language, tier = row[:3]
                result[str(tag)] = self._display_competency_tier(str(tier), str(tag), competency_cfg)
        for tag in dict((load_ecosystem(self.store.settings_path).language_profiles)):
            if tag in set(dict(competency_cfg.get("display") or {}).get("baseline_profiles", [])):
                result[tag] = "BASELINE"
            else:
                result.setdefault(tag, "NOT CHECKED")
        return result

    def _language_tree_rows(self) -> list[dict[str, str]]:
        """Return configured Language Profiles grouped under explicit parent/member identities."""
        registry_cfg, relationship_cfg, competency_cfg = self._language_ui_config()
        identities = dict(registry_cfg.get("identities") or {})
        relationships = dict(relationship_cfg.get("profiles") or {})
        configured = load_ecosystem(self.store.settings_path).language_profiles
        competency = self._configured_competency_map()
        children: dict[str, list[str]] = {}
        for tag in configured:
            parent = str(dict(relationships.get(tag) or {}).get("parent") or tag.split("-", 1)[0])
            # Member identities (pes/prs) are shown as children of their macrolanguage while retaining the regional tag.
            identity = dict(identities.get(parent) or {})
            root_parent = str(identity.get("parent") or parent)
            children.setdefault(root_parent, []).append(tag)
        rows: list[dict[str, str]] = []
        for parent in identities:
            profile_tags = sorted(children.get(parent, []))
            if not profile_tags:
                continue
            item = dict(identities[parent] or {})
            parent_label = parent
            if item.get("iso_639_3") and item.get("iso_639_1"):
                parent_label = f"{item['iso_639_1']} / {item['iso_639_3']}"
            elif item.get("iso_639_3"):
                parent_label = str(item['iso_639_3'])
            rows.append({
                "level": "0", "name": str(item.get("name") or parent), "tag": parent_label,
                "script": str(item.get("script") or "?"),
                "competency": "BASELINE" if parent in {"en"} else "", "identity": parent,
            })
            for tag in profile_tags:
                rel = dict(relationships.get(tag) or {})
                direct_parent = str(rel.get("parent") or tag.split("-", 1)[0])
                member = dict(identities.get(direct_parent) or {})
                name = str(rel.get("name") or member.get("name") or (iso_language(tag.split("-",1)[0]) or {}).get("name") or tag)
                rows.append({
                    "level": "1", "name": name, "tag": tag,
                    "script": str(configured[tag].script or member.get("script") or item.get("script") or "?"),
                    "competency": competency.get(tag, "NOT CHECKED"), "identity": direct_parent,
                })
        # Preserve dynamically configured profiles not represented by a governed parent definition.
        represented = {row["tag"] for row in rows if row["level"] == "1"}
        for tag, namespace in sorted(configured.items()):
            if tag not in represented:
                base = tag.split("-", 1)[0]
                name = str((iso_language(base) or {}).get("name") or base)
                rows.append({"level":"1", "name":name, "tag":tag, "script":namespace.script or "?", "competency":competency.get(tag,"NOT CHECKED"), "identity":base})
        return rows

    def _render_language_table(self) -> list[dict[str, str]]:
        """Render the configured language hierarchy and return the same rows for selection."""
        rows = self._language_tree_rows()
        self.io.write()
        self.io.write("CONFIGURE LANGUAGES")
        self.io.write("=" * 72)
        self.io.write()
        self.io.write(f"{'Language':<25}{'Profile':<13}{'Script':<12}Competency")
        self.io.write("-" * 72)
        for row in rows:
            indent = "  " if row["level"] == "1" else ""
            name = (indent + row["name"])[:24]
            self.io.write(f"{name:<25}{row['tag']:<13}[{row['script']}]".ljust(50) + row["competency"])
        if not rows:
            self.io.write("No Language Profiles are configured.")
        return rows

    def _language_profile_detail(self, tag: str) -> None:
        """Open one language identity or regional working profile with its dependencies."""
        registry_cfg, relationship_cfg, _ = self._language_ui_config()
        identities = dict(registry_cfg.get("identities") or {})
        relationships = dict(relationship_cfg.get("profiles") or {})
        configured = load_ecosystem(self.store.settings_path).language_profiles
        competency = self._configured_competency_map()
        if tag in identities:
            identity = dict(identities[tag] or {})
            child_tags: list[str] = []
            for profile_tag in configured:
                rel = dict(relationships.get(profile_tag) or {})
                parent = str(rel.get("parent") or profile_tag.split("-", 1)[0])
                parent_identity = dict(identities.get(parent) or {})
                if parent == tag or str(parent_identity.get("parent") or "") == tag:
                    child_tags.append(profile_tag)
            context = [
                f"{'Language':<28}{identity.get('name') or tag}",
                f"{'Profile':<28}{identity.get('iso_639_1') or identity.get('iso_639_3') or tag}",
            ]
            if identity.get("iso_639_1"):
                context.append(f"{'ISO 639-1':<28}{identity.get('iso_639_1')}")
            if identity.get("iso_639_3"):
                context.append(f"{'ISO 639-3':<28}{identity.get('iso_639_3')}")
            context.extend([
                f"{'Type':<28}{str(identity.get('type') or 'language').replace('_', ' ').title()}",
                f"{'Primary script':<28}{identity.get('script') or '?'}",
                "",
                "Dependent language profiles [Choose number to open]",
                "-" * 72,
            ])
            options: list[tuple[str, str]] = []
            ordered = sorted(child_tags)
            for index, child in enumerate(ordered, 1):
                rel = dict(relationships.get(child) or {})
                name = str(rel.get("name") or child)
                options.append((str(index), f"Open {name:<27}{child:<12}[{configured[child].script}] {competency.get(child, 'NOT CHECKED')}"))
            if not options:
                context.append("No dependent regional profiles are configured.")
                options.append(("1", "Check model competency"))
            options.append(("B", "Back"))
            choice = self.io.choose(
                f"LANGUAGE PROFILE: {str(identity.get('name') or tag).upper()}",
                tuple(options),
                context=tuple(context),
            )
            if choice == "B":
                return
            if child_tags:
                self._language_profile_detail(ordered[int(choice) - 1])
            else:
                self._check_configured_language_competency()
            return

        namespace = configured.get(tag)
        if namespace is None:
            raise ValidationError(f"Language Profile is not configured: {tag}")
        rel = dict(relationships.get(tag) or {})
        parent = str(rel.get("parent") or tag.split("-", 1)[0])
        parent_identity = dict(identities.get(parent) or {})
        grandparent = str(parent_identity.get("parent") or "")
        parent_name = str(parent_identity.get("name") or parent)
        if grandparent:
            macro = dict(identities.get(grandparent) or {})
            parent_display = f"{parent_name} [{parent}] under {macro.get('name') or grandparent} [{grandparent}]"
        else:
            parent_display = f"{parent_name} [{parent}]"
        projects = registered_project_records(self.root)
        bound_projects: list[str] = []
        for project_id, row in sorted(projects.items()):
            language = dict(row.get("language") or {})
            bound_tag = str(row.get("language_profile_tag") or language.get("profile_tag") or language.get("regional_tag") or "")
            if bound_tag == tag:
                bound_projects.append(project_id)
        context = [
            f"{'Language':<28}{rel.get('name') or parent_name}",
            f"{'Profile':<28}{tag}",
            f"{'Parent':<28}{parent_display}",
            f"{'Script':<28}{namespace.script}",
            f"{'Model competency':<28}{competency.get(tag, 'NOT CHECKED')}",
            "",
            "Bound Projects",
            "-" * 72,
        ]
        context.extend(bound_projects or ["None"] )
        context.extend(["", "Grammar profiles", "-" * 72])
        if namespace.variants:
            for variant_id, variant in sorted(namespace.variants.items()):
                context.append(f"{variant.role:<28}{variant_id}")
        else:
            context.append("No Grammar Profiles configured.")
        choice = self.io.choose(
            f"LANGUAGE PROFILE: {str(rel.get('name') or tag).upper()}",
            (("1", "Configure grammar profiles"), ("2", "Check model competency"), ("3", "Review bound Projects"), ("B", "Back")),
            context=tuple(context),
        )
        if choice == "1":
            self.maintain_grammar_profiles(language=tag)
        elif choice == "2":
            self._check_configured_language_competency()
        elif choice == "3":
            self.io.write()
            self.io.write("BOUND PROJECTS")
            self.io.write("=" * 72)
            for project_id in bound_projects or ["None"]:
                self.io.write(project_id)
            self.io.pause()

    def _open_language_profile_menu(self) -> None:
        """Choose and open one configured language identity/profile."""
        rows = self._language_tree_rows()
        options = []
        values = []
        seen = set()
        for row in rows:
            value = row["identity"] if row["level"] == "0" else row["tag"]
            if value in seen:
                continue
            seen.add(value)
            values.append(value)
            options.append((str(len(values)), f"Open {row['name']} [{row['tag']}]"))
        options.append(("B", "Back"))
        choice = self.io.choose("OPEN LANGUAGE PROFILE", tuple(options))
        if choice != "B": self._language_profile_detail(values[int(choice)-1])

    def _add_language_profile(self) -> None:
        """Add one explicit regional Language Profile namespace without forcing a Grammar Profile."""
        raw = self.io.text("Regional language profile tag [Enter to cancel]", required=False).strip()
        if not raw:
            return
        tag = canonical_regional_language_tag(raw, "language profile")
        registry_cfg, relationship_cfg, _ = self._language_ui_config()
        rel = dict(dict(relationship_cfg.get("profiles") or {}).get(tag) or {})
        identities = dict(registry_cfg.get("identities") or {})
        parent = str(rel.get("parent") or tag.split("-",1)[0])
        identity = dict(identities.get(parent) or {})
        script = str(identity.get("script") or "")
        if not script:
            script = self.io.text("Script code (ISO 15924) [Enter to cancel]", required=False).strip()
            if not script:
                return
            script = canonical_script_code(script, "language profile script")
        ensure_language_profile_namespace(self.store.settings_path, tag=tag, script=script)
        self.io.write(f"Language Profile configured: {tag} [{script}]")

    def _validate_language_configuration(self) -> None:
        """Validate explicit relationships and configured regional profile namespaces."""
        registry_cfg, relationship_cfg, _ = self._language_ui_config()
        identities = dict(registry_cfg.get("identities") or {})
        profiles = dict(relationship_cfg.get("profiles") or {})
        errors = []
        for identity, row in identities.items():
            parent = str(dict(row or {}).get("parent") or "")
            if parent and parent not in identities:
                errors.append(f"{identity}: unknown parent {parent}")
        for tag, row in profiles.items():
            parent = str(dict(row or {}).get("parent") or "")
            if parent and parent not in identities:
                errors.append(f"{tag}: unknown parent {parent}")
        if errors:
            raise ValidationError("Language relationship validation failed: " + "; ".join(errors))
        self.io.write(f"Language configuration: READY - {len(identities)} identities, {len(profiles)} governed regional relationships.")

    def _check_configured_language_competency(self) -> None:
        """Look up configured non-baseline languages in the versioned evidence registry."""
        config = load_ecosystem(self.store.settings_path)
        registry_cfg, relationship_cfg, competency_cfg = self._language_ui_config()
        relationships = dict(relationship_cfg.get("profiles") or {})
        baseline = set(dict(competency_cfg.get("display") or {}).get("baseline_profiles", []))
        rows = []
        for tag, namespace in sorted(config.language_profiles.items()):
            if tag in baseline:
                continue
            rel = dict(relationships.get(tag) or {})
            base = str(rel.get("parent") or tag.split("-",1)[0])
            identity = dict(dict(registry_cfg.get("identities") or {}).get(base) or {})
            rows.append({"canonical_tag": tag, "language": str(rel.get("name") or identity.get("name") or tag), "region": str(rel.get("region") or ""), "script": namespace.script})
        if not rows:
            self.io.write("No non-baseline configured languages require a competency lookup.")
            return
        with self.io.working("Loading competency evidence for configured languages", ellipsis=False):
            result = ModelService(self.root).lookup_language_competency(rows, provider="codex")
        self._write_language_competency_evidence(result)

    def configure_languages_menu(self) -> None:
        """Configure explicit Language Profile relationships, namespaces, and model competency."""
        while True:
            rows = self._language_tree_rows()
            context = [f"{'Language':<25}{'Profile':<13}{'Script':<12}Competency"]
            for row in rows:
                indent = "  " if row["level"] == "1" else ""
                name = (indent + row["name"])[:24]
                context.append(f"{name:<25}{row['tag']:<13}[{row['script']}]".ljust(50) + row["competency"])
            if not rows:
                context.append("No Language Profiles are configured.")
            choice = self.io.choose(
                "CONFIGURE LANGUAGES",
                (("1", "Open language profile"), ("2", "Add language profile"), ("3", "Check competency for configured languages"), ("4", "Validate language configuration"), ("B", "Back")),
                context=tuple(context),
                option_heading="LANGUAGE ACTIONS",
            )
            if choice == "B":
                return
            try:
                if choice == "1":
                    self._open_language_profile_menu()
                elif choice == "2":
                    self._add_language_profile()
                elif choice == "3":
                    self._check_configured_language_competency()
                elif choice == "4":
                    self._validate_language_configuration()
            except SageError as exc:
                self.show_error(exc)
            self.io.pause()

    def job_storage_maintenance_menu(self, tool: str) -> None:
        """Maintain one workflow's Jobs and audit shared legacy storage safely."""
        if tool not in TOOL_IDS:
            raise ConfigurationError(f"Unsupported Job-storage workflow: {tool}")
        audit_path = storage_layout(self.root).diagnostics_root / "job-layout" / "JOB-LAYOUT-AUDIT.json"
        while True:
            choice = self.io.choose(
                f"{tool.upper()} JOB STORAGE",
                (
                    ("1", "Rebuild Job configuration"),
                    ("2", "Audit Job folders"),
                    ("3", "Review migration plan"),
                    ("4", "Migrate legacy layout"),
                    ("5", "Verify Job layout"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            if choice == "1":
                jobs = self.store.discover(tool)
                if not jobs:
                    self.io.write(f"No {tool.upper()} Jobs found.")
                for job in jobs:
                    self.store.write_runtime_files(job)
                    self.io.write(f"Rebuilt: {job.job_id}")
                self.io.pause()
            elif choice == "2":
                result = write_job_layout_audit(self.root)
                self.io.write(render_job_layout_audit(result))
                self.io.write(f"Audit: {result['json_path']}")
                self.io.pause()
            elif choice == "3":
                if not audit_path.is_file():
                    result = write_job_layout_audit(self.root)
                else:
                    result = _json_file(audit_path)
                self.io.write(render_job_layout_audit(result))
                self.io.write("Migration is dry-run-first. Unknown/non-empty paths are always preserved.")
                self.io.pause()
            elif choice == "4":
                if not audit_path.is_file():
                    self.io.write("Run Audit Job folders first.")
                    self.io.pause()
                    continue
                dry = migrate_job_layout(self.root, audit_path, apply=False)
                self.io.write(f"Dry-run actions: {len(dry['actions'])}")
                self.io.write(f"Dry-run receipt: {dry['receipt_path']}")
                if not dry["actions"]:
                    self.io.write("No legacy layout changes are required.")
                    self.io.pause()
                    continue
                if not self.io.confirm("Apply the audited migration now?", default=False):
                    continue
                applied = migrate_job_layout(self.root, audit_path, apply=True)
                self.io.write(f"Applied actions: {len(applied['actions'])}")
                self.io.write(f"Migration receipt: {applied['receipt_path']}")
                self.io.pause()
            elif choice == "5":
                result = verify_job_layout(self.root)
                self.io.write(f"Status: {result['status']}")
                self.io.write(f"Legacy migratable paths remaining: {result['legacy_remaining']}")
                self.io.write(f"Unknown preserved paths: {result['unknown_preserved']}")
                self.io.pause()

    def operator_language_menu(self) -> None:
        """Configure the global Operator language used as the default for new Jobs."""
        while True:
            config = load_ecosystem(self.store.settings_path)
            self.io.write()
            self.io.write("OPERATOR LANGUAGE")
            self.io.write("-" * 72)
            self.io.write(f"Global Operator language: {config.human_output.operator_language}")
            policy = config.human_output.operator_language_policy
            self.io.write(f"Status: {policy.status(config.human_output.operator_language)}")
            self.io.write("Selectable: " + ", ".join(policy.selectable()))
            self.io.write("Operational candidate priorities: " + ", ".join(policy.operational_priorities))
            self.io.write("This is the default primary report language for newly created Jobs.")
            self.io.write("Each Job owns its primary language and may optionally add one secondary language.")
            self.io.write("A secondary rendering adds model usage, compilation time, and human-review effort.")
            choice = self.io.choose(
                "Global Operator language",
                (("1", "Change Operator language"), ("2", "Preview language ownership"), ("B", "Back")),
            )
            if choice == "B": return
            if choice == "2":
                self.io.write(f"New-Job primary default: {config.human_output.operator_language}")
                self.io.write("Job primary: required and snapshotted when the Job is created.")
                self.io.write("Job secondary: optional; configure it in that Job's settings.")
                self.io.write("Secondary output requires more human review than a single-language report.")
                self.io.pause()
                continue
            requested = canonical_language_tag(
                self.io.text(
                    "Operator language",
                    default=config.human_output.operator_language,
                ),
                "operator language",
            )
            if requested not in policy.selectable():
                status = policy.status(requested)
                self.show_error(
                    ValidationError(
                        f"Operator language {requested} is {status} and is not selectable",
                        code="OPERATOR_LANGUAGE_NOT_CANDIDATE",
                        next_action=(
                            "An advanced Operator may add the canonical tag to "
                            "human_output.operator_language_policy.candidates in ecosystem.yml, "
                            "then reopen this menu."
                        ),
                        details={"language": requested, "status": status},
                    )
                )
                continue
            raw, _override_path, _resolutions = load_effective_settings(self.store.settings_path)
            human = dict(raw.get("human_output") or {})
            out = dict(human.get("logs_and_reports") or {})
            challenges = dict(human.get("translation_challenges") or {})
            out.update({"primary_language": "OPERATOR_LANGUAGE", "secondary_language": None, "bilingual": False})
            challenges.update({"primary_language": "OPERATOR_LANGUAGE", "secondary_language": None, "bilingual": False})
            human["operator_language"] = requested
            human["logs_and_reports"] = out
            human["translation_challenges"] = challenges
            write_local_settings(self.store.settings_path, {"human_output": human})
            load_ecosystem(self.store.settings_path)
            invalidate_runtime_settings(self.root)
            self.io.write("Operator language saved as the default primary language for new Jobs.")
            self.io.pause()

    def system_diagnostics_menu(self) -> None:
        """Run focused or complete system checks with human-readable results."""
        service = ModelService(self.root)
        while True:
            projects_root_status, projects_root = self._setup_projects_root_status()
            ai = self.runtime_status.ai.to_dict()
            root_display = (
                str(projects_root)
                if projects_root_status == "READY" and projects_root is not None
                else projects_root_status.replace("_", " ")
            )
            choice = self.io.choose(
                "SYSTEM CHECKS",
                (("1", "Python environment"), ("2", "SAGE configuration"), ("3", "Scripture Projects"), ("4", "Original-language resources"), ("5", "OpenAI and ChatGPT"), ("6", "Complete system check"), ("B", "Back")),
                context=(
                    "CURRENT SYSTEM STATE [LAST KNOWN]",
                    f"{'Python':<28}{sys.version.split()[0]}",
                    f"{'Managed environment':<28}{'READY' if storage_layout(self.root).venv_root.is_dir() else 'MISSING'}",
                    f"{'SAGE configuration':<28}READY",
                    f"{'Paratext Projects root':<28}{root_display}",
                    f"{'SAGE Projects':<28}{len(registered_project_records(self.root))}",
                    f"{'Greek resource':<28}{active_ol_project_id(self.root, 'GRK') or 'NOT CONFIGURED'}",
                    f"{'Hebrew resource':<28}{active_ol_project_id(self.root, 'HEB') or 'NOT CONFIGURED'}",
                    f"{'AI connection':<28}{ai.get('connection') or 'NOT CHECKED'}",
                    f"{'Last AI check':<28}{ai.get('last_checked') or 'NEVER'}",
                    "Entering this menu does not run checks or test the AI connection.",
                ),
                option_heading="CHECK ACTIONS",
            )
            if choice == "B": return
            try:
                if choice == "1": self._system_runtime_status()
                elif choice == "2":
                    load_ecosystem(self.store.settings_path)
                    self.io.write("SAGE configuration: READY")
                    self.io.pause()
                elif choice == "3": self.validate_shared_registry()
                elif choice == "4":
                    result = validate_original_language_resources(self.root)
                    self.io.write(json.dumps(result, indent=2, ensure_ascii=False))
                    self.io.pause()
                elif choice == "5":
                    row = self._setup_model_probe(service, refresh=True)
                    self._write_ai_status(row)
                    self.io.write(f"{'Last checked':<25}{row.get('last_checked') or 'NEVER'}")
                    self.io.pause()
                elif choice == "6":
                    load_ecosystem(self.store.settings_path)
                    scripture = self._setup_scripture_resource_status()
                    ol = validate_original_language_resources(self.root)
                    provider = self._setup_model_probe(service)
                    local_admin = self.ollama_admin.status()
                    projects_root_status, projects_root = self._setup_projects_root_status()
                    scripture_status = str(scripture.get("status", "UNKNOWN"))
                    ol_status = str(ol.get("status", "UNKNOWN"))
                    required_ready = (
                        projects_root_status == "READY"
                        and scripture_status in {"READY", "READY_EMPTY"}
                        and ol_status == "READY"
                        and bool(provider.get("ready"))
                    )
                    self.io.write()
                    self.io.write("SYSTEM CHECK")
                    self.io.write("-" * 72)
                    self.io.write("Runtime                  READY")
                    self.io.write(
                        "Paratext Projects root    "
                        + (
                            f"READY - {projects_root}"
                            if projects_root_status == "READY"
                            else projects_root_status.replace("_", " ")
                        )
                    )
                    catalog = scripture.get('catalog', {})
                    self.io.write(
                        f"Paratext catalog         {catalog.get('discovered', catalog.get('projects', 0))} discovered; "
                        f"{catalog.get('validated', 0)} validated; {catalog.get('pending', 0)} pending"
                    )
                    self.io.write(f"SAGE Projects            {scripture.get('registered_projects', 0)}")
                    self.io.write(f"Original languages       {ol_status}")
                    self._write_ai_status(provider)
                    self.io.write(
                        "Local AI                  "
                        + ("READY" if local_admin.ready else "OPTIONAL, NOT READY")
                    )
                    self.io.write(f"Overall                  {'READY' if required_ready else 'INCOMPLETE'}")
                    if projects_root_status == "NOT_CONFIGURED":
                        self.io.write("Reason code              PROJECTS_ROOT_NOT_CONFIGURED")
                        self.io.write("Next action              Configure the Paratext Projects root under Scripture Projects.")
                    elif projects_root_status == "MISSING":
                        self.io.write("Reason code              PROJECTS_ROOT_NOT_FOUND")
                        self.io.write("Next action              Repair the configured Paratext Projects root path.")
                    self.io.pause()
            except SageError as exc: self.show_error(exc)

    def guided_setup(self, *, pause_at_end: bool = True) -> bool:
        """Run resumable guided setup; return True only when the operator requests Exit SAGE."""
        self.io.write()
        self.io.write("SAGE SETUP")
        self.io.write("=" * 72)
        self.io.write("SAGE checks prerequisites and remembers completed setup steps.")

        try:
            import yaml  # noqa: F401
        except ImportError as exc:  # pragma: no cover - dependency contract
            raise InputRequiredError("PyYAML is not installed", code="PYYAML_NOT_FOUND") from exc

        scripture_resources = self._setup_scripture_resource_status(render=True)
        service = ModelService(self.root)
        existing = self.store.setup_state() or {}
        enabled_tools = self._setup_configured_tools()
        init_results = self._setup_live_initialisation_results(
            existing.get("initialization") if isinstance(existing.get("initialization"), dict) else None
        )
        self.store.record_cue("SETUP_OPENED", previous_status=existing.get("status", "NEW"))
        exit_requested = False

        # First launch is Q&A driven: offer missing prerequisites immediately, but never
        # trap the operator and never enter the interactive Codex TUI.
        model_row = self._setup_model_probe(service)
        try:
            if not model_row.get("available"):
                model_row = self._setup_install_codex(service)
            if model_row.get("available") and not model_row.get("ready"):
                if self.io.confirm("Connect ChatGPT now?", default=True):
                    self._model_connect_chatgpt(service)
        except SageError as exc:
            self.show_error(exc)

        while True:
            enabled_tools = self._setup_configured_tools()
            init_results = self._setup_live_initialisation_results(init_results)
            model_row = self._setup_model_probe(service)
            scripture_resources = self._setup_scripture_resource_status()
            next_step, next_label = self._save_setup_state(
                service=service,
                model_row=model_row,
                enabled_tools=enabled_tools,
                init_results=init_results,
                scripture_resources=scripture_resources,
            )
            self.io.write()
            self.io.write("JOB STATUS")
            self.io.write("-" * 72)
            system_action_needed = next_step in {
                "INSTALL_CODEX",
                "LOGIN_CHATGPT",
                "VALIDATE_SCRIPTURE",
                "CONFIGURE_PROJECT_ROOT",
                "RECOVER_ACTIVE_JOB_POINTERS",
            }
            self.io.write(
                "System:    "
                + (f"ACTION NEEDED - {next_label}" if system_action_needed else "READY")
            )
            self.io.write(f"BIC:       {self._setup_workflow_status('bic', init_results)}")
            self.io.write(f"SAW:       {self._setup_workflow_status('saw', init_results)}")
            self.io.write(f"Interface: {self.localizer.language_name()} [{self.localizer.language}]")
            self.io.write(f"Next:      {next_label}")

            system_label = self.localizer.text("SAGE Maintenance")
            if system_action_needed:
                system_label += f" [{self.localizer.text('Recommended')}: {next_label}]"
            try:
                choice = self.io.choose(
                    "MANAGE JOBS",
                    (
                        ("1", "BIC Jobs"),
                        ("2", "SAW Jobs"),
                        ("3", "Manage active Jobs"),
                        ("4", system_label),
                        ("5", "Interface language"),
                        ("6", "Continue to Main Menu"),
                        ("X", "Exit SAGE"),
                    ),
                )
            except MenuHomeRequested:
                if model_row.get("ready"):
                    raise
                self.io.write("AI prerequisite: BLOCKED")
                self.io.write("Connect and test workflow AI before entering the Main Menu.")
                self.io.pause()
                continue
            if choice == "6":
                if not model_row.get("ready"):
                    self.io.write("AI prerequisite: BLOCKED")
                    self.io.write("A working workflow-AI connection is required before entering the Main Menu.")
                    self.io.write("Open SAGE Maintenance > Configure AI, then test the connection.")
                    self.io.pause()
                    continue
                break
            if choice == "X":
                exit_requested = True
                break
            try:
                if choice == "1":
                    self.job_management_menu("bic")
                elif choice == "2":
                    self.job_management_menu("saw")
                elif choice == "3":
                    init_results = self._setup_initialize_projects()
                    self.io.pause()
                elif choice == "4":
                    destination = self.system_configuration_menu()
                    if destination == "EXIT":
                        exit_requested = True
                        break
                    if destination == "MAIN":
                        break
                elif choice == "5":
                    self.interface_language_menu()
            except SageError as exc:
                self.show_error(exc)

        enabled_tools = self._setup_configured_tools()
        model_row = self._setup_model_probe(service)
        scripture_resources = self._setup_scripture_resource_status()
        next_step, next_label = self._save_setup_state(
            service=service,
            model_row=model_row,
            enabled_tools=enabled_tools,
            init_results=init_results,
            scripture_resources=scripture_resources,
        )
        status = "COMPLETE" if next_step == "COMPLETE" else "INCOMPLETE"
        self.store.record_cue("SETUP_SAVED", status=status, next_step=next_step)
        self.io.write(f"SAGE readiness: {status}")
        if status != "COMPLETE":
            self.io.write(f"Next launch will resume at: {next_label}")
        if pause_at_end and not exit_requested:
            self.io.pause()
        return exit_requested

    # ---------- Main menu ----------

    def run(self) -> int:
        """Run one resumable SAGE operator session from the single normal entry point."""
        self.store.record_cue("SAGE_STARTED")
        service = ModelService(self.root)
        startup = self._setup_model_probe(service, refresh=True)
        self._render_startup_report(startup)
        try:
            if not self.skip_setup and (self.setup_required(startup) or not startup.get("ready")):
                if self.guided_setup(pause_at_end=False):
                    self.store.record_cue("SAGE_EXITED")
                    return 0
        except MenuHomeRequested:
            pass
        except MenuExitRequested:
            self.store.record_cue("SAGE_EXITED")
            return 0
        while True:
            try:
                choice = self.main_menu()
                self.store.record_cue("MAIN_MENU_SELECTED", selection=choice)
                if choice == "1": self.resource_menu()
                elif choice == "2": self.bic_menu()
                elif choice == "3": self.saw_menu()
                elif choice == "4":
                    destination = self.system_configuration_menu()
                    if destination == "EXIT":
                        self.store.record_cue("SAGE_EXITED")
                        return 0
                elif choice == "X":
                    self.store.record_cue("SAGE_EXITED")
                    return 0
            except MenuHomeRequested:
                continue
            except MenuExitRequested:
                self.store.record_cue("SAGE_EXITED")
                return 0

    def reports_home_menu(self) -> None:
        """Choose a Job before entering its generated reports/history surface."""
        while True:
            choice = self.io.choose("REPORTS", (("1", "BIC reports and history"), ("2", "SAW reports and history"), ("B", "Back")))
            if choice == "B": return
            tool = "bic" if choice == "1" else "saw"
            project = self.store.active_job(tool) or self.choose_job(tool)
            if project is not None: self.reports_menu(project)

    def operator_guide_menu(self) -> None:
        """Mirror the live menu vocabulary and point to detailed platform references."""
        while True:
            choice = self.io.choose("HELP", (
                ("1", "First-time setup"), ("2", "Add a Paratext Project to SAGE"),
                ("3", "Create a BIC Job"), ("4", "Create a SAW Job"),
                ("5", "Enter Scripture ranges"), ("6", "How SAGE splits large scopes"),
                ("7", "Project status meanings"), ("8", "Reporting languages"),
                ("9", "Greek and Hebrew resources"), ("10", "Command and recovery guides"), ("B", "Back")))
            if choice == "B": return
            guides = {
                "1": "Configure paths and resources first; Project addition and Job setup are separate tasks.",
                "2": "Scripture Projects > Add Projects to SAGE. Scan, choose, review metadata, then add. No Job role is assigned here.",
                "3": "BIC > Add BIC Job. Assign a SAGE Project as SOURCE, DONOR and TARGET; only TARGET receives governed write access.",
                "4": "SAW > Add SAW Job. Assign a SAGE Project as WIP and another as REFERENCE.",
                "5": "Choose a Book, then leave range blank for the whole book or enter 1, 1-3, 1:1-10, or 1:1-2:20. Expert entry such as LUK 1:1-10 remains available.",
                "6": "Before a Run, SAGE shows measured work units and conservative estimated routed-SFM tokens; sections are preferred split points only when the combined packet does not fit.",
                "7": "READY can be used directly; WARNING is usable with a disclosed issue; ERROR requires correction before affected work.",
                "8": "The global Operator language is the default primary language for new Jobs. Each Job owns one required primary and may add one optional secondary reporting language.",
                "9": "@GRK and @HEB are governed original-language resources and are not ordinary SAGE Projects.",
            }
            if choice == "10": self._show_support_docs()
            else:
                self.io.write(guides[choice])
                self.io.pause()

    def _job_summary(self, tool: str) -> str:
        """Return one compact active-Job readiness summary."""
        return self.ui_service.job_summary(tool)

    def _last_run_summary(self) -> str:
        """Return one compact last-Run summary."""
        return self.ui_service.last_run_summary()

    def _last_run_is_resumable(self) -> bool:
        """Return whether the recorded last Run represents unfinished operator work."""
        return self.ui_service.last_run_is_resumable()

    def _model_summary(self) -> str:
        """Return the selected provider and optional model for the Control Center header."""
        return self.ui_service.model_summary()

    def _active_run_route_row(self, run: Run | None) -> dict[str, Any] | None:
        """Return the latest actual attempt route without substituting a recommendation."""
        if run is None:
            return None
        for raw_path in reversed(tuple(run.task_manifests)):
            manifest_path = Path(str(raw_path)).expanduser()
            receipt_path = manifest_path.parent / "validation" / "llm-execution-receipt.json"
            if not receipt_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            task_id = manifest.get("task_id") if isinstance(manifest, dict) else None
            if (
                isinstance(receipt, dict)
                and receipt.get("schema_version") == "2.0"
                and task_id
                and receipt.get("task_id") == task_id
            ):
                return {
                    "skill_id": receipt.get("skill_id"),
                    "provider": receipt.get("provider"),
                    "model_id": receipt.get("model"),
                    "reasoning_id": receipt.get("reasoning_effort"),
                    "qualification": receipt.get("qualification_status"),
                    "availability": "EXECUTED",
                }
        return None

    def _write_job_ai_routing(self, tool: str, run: Run | None) -> None:
        """Render actual-attempt or current-recommendation routing in one compact table."""
        service = ModelService(self.root)
        try:
            mode = service.routing_override_status()["routing_mode"]
        except Exception:
            mode = "UNKNOWN"
        self.io.write(f"{'AI Routing':<29}{mode}")
        actual = self._active_run_route_row(run)
        rows: list[dict[str, Any]] = []
        label = "Current attempt receipt" if actual else "Current recommendation"
        if actual is not None:
            rows = [actual]
        elif not self.dry_run_provider:
            try:
                routes = service.skill_routes()
                rows = [
                    dict(row)
                    for row in routes.get("skills", [])
                    if str(row.get("skill_id") or "").startswith(tool + "-")
                ]
            except Exception:
                rows = []
        self.io.write(label)
        self.io.write(f"{'SKILL':<12}{'PROVIDER':<12}{'MODEL':<22}{'REASONING':<14}STATUS")
        self.io.write("-" * 72)
        labels = {
            "saw-rtc": "RTC",
            "saw-stc": "STC",
            "saw-focused-check": "TARGETED",
            "saw-original-language-review": "SRC REVIEW",
            "bic-inspect": "INSPECT",
            "bic-rewrite": "REWRITE",
            "bic-self-check": "SELF-CHECK",
        }
        if not rows:
            self.io.write(f"{'—':<12}{'—':<12}{'—':<22}{'—':<14}NOT CHECKED")
        for row in rows:
            self.io.write(
                f"{labels.get(str(row.get('skill_id')), str(row.get('skill_id') or '—')):<12}"
                f"{str(row.get('provider') or '—'):<12}"
                f"{str(row.get('model_id') or '—'):<22}"
                f"{str(row.get('reasoning_id') or '—'):<14}"
                f"{str(row.get('qualification') or 'UNASSESSED')}"
            )
        self.io.write()

    def main_menu(self) -> str:
        """Render the task-oriented current Main Menu."""
        self.io.write()
        from . import __version__
        self.io.write(f"SAGE v{__version__}")
        release = self.ui_service.release_snapshot()
        self.io.write(f"{release['release_status']} - PRE-RELEASE")
        self.io.write("-" * 72)
        self.io.write(f"BIC active Job: {self._job_summary('bic')}")
        self.io.write(f"SAW active Job: {self._job_summary('saw')}")
        if self._last_run_is_resumable():
            self.io.write(f"Unfinished Run: {self._last_run_summary()}")
        return self.io.choose(
            "MAIN MENU",
            (
                ("1", "Manage SAGE Scripture Projects"),
                ("2", "BIC"),
                ("3", "SAW"),
                ("4", "SAGE Maintenance"),
                ("X", "Exit SAGE"),
            ),
            blank_before=("2", "4"),
        )

    def resume_or_start_task(self) -> None:
        """Resume unfinished state from its recorded checkpoint or choose a new workflow."""
        if self._last_run_is_resumable():
            self.continue_last_run()
            return
        choice = self.io.choose(
            "New Task",
            (("1", "BIC"), ("2", "SAW"), ("B", "Back")),
        )
        if choice == "1":
            project = self.store.active_job("bic") or self.choose_job("bic")
            if project is not None:
                self.store.record_cue("NEW_TASK_SELECTED", tool="bic", job_id=project.job_id)
                self.start_bic_run(project)
        elif choice == "2":
            project = self.store.active_job("saw") or self.choose_job("saw")
            if project is None:
                return
            operation = self.io.choose(
                "SAW Task",
                (
                    ("1", "Run Reference Text Comparison (RTC)"),
                    ("2", "Run Source Text Correspondence (STC)"),
                    ("3", "Run Targeted Check"),
                    ("4", "Run Original-Language Review"),
                    ("B", "Back"),
                ),
            )
            operation_id = {"1": "rtc", "2": "stc", "3": "focused", "4": "ol"}.get(operation)
            if operation_id is not None:
                self.store.record_cue(
                    "NEW_TASK_SELECTED",
                    tool="saw",
                    job_id=project.job_id,
                    operation=operation_id,
                )
                self.start_saw_run(project, operation_id)

    def continue_last_run(self) -> None:
        """Continue the recorded run through its existing checkpoint-aware state machine."""
        item = self.store.last_run()
        if not item:
            self.io.write("No last run is recorded.")
            self.io.pause()
            return
        project, run = item
        if run.status in RUN_CLOSED_STATUSES:
            self.io.write("The last run is already complete or closed. Start a new task instead.")
            self.io.pause()
            return
        self.store.set_active_job(project.tool, project.job_id)
        self.store.set_active_run(project, run.run_id)
        self.store.record_cue(
            "RUN_RESUMED", tool=project.tool, job_id=project.job_id, run_id=run.run_id,
            stage=run.current_stage, status=run.status, scope=run.scope,
        )
        self.continue_run(project, run)

    # ---------- Project selection ----------

    def select_active_project_menu(self) -> None:
        """Manage project selection and shared resources from one non-operational menu."""
        while True:
            choice = self.io.choose(
                "Jobs and Projects",
                (
                    ("1", "Choose active BIC Job"),
                    ("2", "Choose active SAW Job"),
                    ("3", "BIC Jobs"),
                    ("4", "SAW Jobs"),
                    ("5", "Scripture Projects"),
                    ("6", "Active Job status"),
                    ("7", "Clear active BIC Job"),
                    ("8", "Clear active SAW Job"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            if choice in {"1", "2"}:
                self.choose_job("bic" if choice == "1" else "saw")
            elif choice == "3":
                self.job_management_menu("bic")
            elif choice == "4":
                self.job_management_menu("saw")
            elif choice == "5":
                self.resource_menu()
            elif choice == "6":
                self.show_active_readiness()
            elif choice == "7":
                self.store.set_active_job("bic", None)
            elif choice == "8":
                self.store.set_active_job("saw", None)

    def choose_job(self, tool: str) -> Job | None:
        """Implement `choose project` in the deterministic terminal control flow."""
        projects = self.store.discover(tool)
        if not projects:
            self.io.write(f"No {tool.upper()} Jobs exist. Open {tool.upper()} from the Main Menu to create one.")
            self.io.pause()
            return None
        options = [(str(index), f"{project.display_name} [{project.job_id}]") for index, project in enumerate(projects, 1)]
        options.append(("B", "Back"))
        choice = self.io.choose(f"{self.localizer.text('Choose active Job')} [{tool.upper()}]", options)
        if choice == "B":
            return None
        project = projects[int(choice) - 1]
        self.store.set_active_job(tool, project.job_id)
        self.io.write(f"Active {tool.upper()} job: {project.display_name}")
        return project

    def show_active_readiness(self) -> None:
        """Implement `show active readiness` in the deterministic terminal control flow."""
        self.io.write()
        self.io.write("ACTIVE JOB READINESS")
        self.io.write("-" * 72)
        for tool in TOOL_IDS:
            project = self.store.active_job(tool)
            if project is None:
                self.io.write(f"{tool.upper()}: NONE")
                continue
            state = self.project_state(project)
            self.io.write(
                f"{tool.upper()}: {project.job_id} - {state.get('state', 'NOT INITIALIZED')}"
            )
            if state.get("actions"):
                self.io.write(f"  Actions: {len(state['actions'])}")
        self.io.pause()

    # ---------- BIC ----------

    def bic_menu(self) -> None:
        """Open BIC even when no Job exists; Job creation is a tool-setup task."""
        while True:
            project = self.store.active_job("bic")
            active = project.display_name if project is not None else "NONE"
            choice = self.io.choose(
                "BIC JOBS",
                (
                    ("1", f"Open active BIC Job [{active}]"),
                    ("2", "BIC Jobs"),
                    ("3", "Add BIC Job [SOURCE, DONOR, TARGET]"),
                    ("4", "Reports and history"),
                    ("5", "Recovery and diagnostics"),
                    ("6", "Maintain Job storage"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            if choice == "2":
                self.job_management_menu("bic")
                continue
            if choice == "3":
                self.create_job_wizard("bic")
                continue
            if choice == "4":
                selected = project or self.choose_job("bic")
                if selected is not None:
                    self.reports_menu(selected)
                continue
            if choice == "5":
                selected = project or self.choose_job("bic")
                if selected is not None:
                    self.recovery_menu(selected)
                continue
            if choice == "6":
                self.job_storage_maintenance_menu("bic")
                continue
            if project is None:
                project = self.choose_job("bic")
            if project is not None:
                self._bic_job_menu(project)

    def _bic_job_menu(self, project: Job) -> None:
        """Operate one selected BIC Job."""
        while True:
            project = self.store.active_job("bic") or project
            self.io.write()
            self.io.write(f"BIC JOB - {project.job_id}")
            self.io.write("-" * 72)
            self.io.write(f"SOURCE: {project.bindings.get('content_source')}")
            self.io.write(f"DONOR:  {project.bindings.get('lexical_donor')}")
            self.io.write(f"TARGET: {project.bindings.get('generated_target')}")
            self.io.write()
            self._write_job_ai_routing("bic", self.store.active_run(project))
            choice = self.io.choose(
                "BIC Job",
                (
                    ("1", "Continue active Run"),
                    ("2", "Run BIC check"),
                    ("3", "Runs and task history"),
                    ("4", "Memory and terminology"),
                    ("5", "TARGET generations"),
                    ("6", "Reports and exports"),
                    ("7", "Job settings"),
                    ("8", "Recovery and diagnostics"),
                    ("B", "Back"),
                ),
            )
            if choice == "B": return
            if choice == "1":
                run = self.store.active_run(project)
                if run: self.continue_run(project, run)
                else:
                    self.io.write("No active BIC Run. Start a new Run or open one from history.")
                    self.io.pause()
            elif choice == "2": self.start_bic_run(project)
            elif choice == "3": self.runs_menu(project)
            elif choice == "4": self.bic_memory_menu(project)
            elif choice == "5": self.bic_generation_menu(project)
            elif choice == "6": self.reports_menu(project)
            elif choice == "7": self._job_settings_menu(project)
            elif choice == "8": self.recovery_menu(project)

    def start_bic_run(self, project: Job) -> None:
        """Choose scope, preview bounded work, then create one BIC Run."""
        self.ensure_initialized(project)
        while True:
            scope = self._select_scripture_scope(project, primary_binding="content_source")
            if scope is None:
                return
            action = self._review_work_before_run(project, operation="inspect", scope=scope)
            if action == "CHANGE":
                continue
            if action != "RUN":
                return
            run = self.store.create_run(project, operation="bic", scope=scope)
            self.io.write(f"Created BIC Run: {run.run_id}")
            self.continue_run(project, run)
            return

    def saw_menu(self) -> None:
        """Choose/setup one SAW Job; checks are run only from the selected Job screen."""
        while True:
            active = self.store.active_job("saw")
            context: list[str] = [f"Active Job                   {active.job_id if active else 'NONE'}"]
            if active is not None:
                context.extend([
                    f"WIP                          {active.bindings.get('wip')}",
                    f"REFERENCE                    {active.bindings.get('reference')}",
                ])
                options = (
                    ("1", "Open active SAW Job"),
                    ("2", "Choose active SAW Job"),
                    ("3", "Add SAW Job [WIP, REFERENCE]"),
                    ("4", "Manage SAW Jobs"),
                    ("5", "Reports and history"),
                    ("6", "Recovery and diagnostics"),
                    ("7", "Maintain Job storage"),
                    ("B", "Back"),
                )
            else:
                options = (
                    ("1", "Choose active SAW Job"),
                    ("2", "Add SAW Job [WIP, REFERENCE]"),
                    ("3", "Manage SAW Jobs"),
                    ("4", "Reports and history"),
                    ("5", "Recovery and diagnostics"),
                    ("6", "Maintain Job storage"),
                    ("B", "Back"),
                )
            choice = self.io.choose("SAW", options, context=tuple(context))
            if choice == "B":
                return
            if active is not None:
                if choice == "1":
                    self._saw_job_menu(active)
                elif choice == "2":
                    selected = self.choose_job("saw")
                    if selected is not None:
                        self._saw_job_menu(selected)
                elif choice == "3":
                    selected = self.create_job_wizard("saw")
                    if isinstance(selected, Job):
                        self._saw_job_menu(selected)
                elif choice == "4":
                    self.job_management_menu("saw")
                elif choice == "5":
                    self.reports_menu(active)
                elif choice == "6":
                    self.recovery_menu(active)
                elif choice == "7":
                    self.job_storage_maintenance_menu("saw")
            else:
                if choice == "1":
                    selected = self.choose_job("saw")
                    if selected is not None:
                        self._saw_job_menu(selected)
                elif choice == "2":
                    selected = self.create_job_wizard("saw")
                    if isinstance(selected, Job):
                        self._saw_job_menu(selected)
                elif choice == "3":
                    self.job_management_menu("saw")
                elif choice in {"4", "5"}:
                    selected = self.choose_job("saw")
                    if selected is not None:
                        if choice == "4":
                            self.reports_menu(selected)
                        else:
                            self.recovery_menu(selected)
                elif choice == "6":
                    self.job_storage_maintenance_menu("saw")

    def _saw_job_menu(self, project: Job) -> None:
        """Run checks on one selected SAW Job; Back returns to SAW setup/choice."""
        while True:
            project = self.store.active_job("saw") or project
            run = self.store.active_run(project)
            self.io.write()
            self.io.write(f"SAW JOB - {project.job_id}")
            self.io.write("-" * 72)
            self.io.write(f"WIP                          {project.bindings.get('wip')}")
            self.io.write(f"REFERENCE                    {project.bindings.get('reference')}")
            self.io.write()
            self._write_job_ai_routing("saw", run)
            if run is None:
                self.io.write("Active Run                   NONE")
                options = (
                    ("1", "Run Reference Text Comparison (RTC)"),
                    ("2", "Run Source Text Correspondence (STC)"),
                    ("3", "Run Targeted Check"),
                    ("4", "Run Original-Language Review"),
                    ("5", "Reports and exports"),
                    ("6", "Recovery and diagnostics"),
                    ("B", "Back"),
                )
            else:
                self.io.write("Active Run")
                self.io.write(f"  Run                        {run.run_id}")
                self.io.write(f"  Check                      {self._saw_operation_label(run.operation)}")
                self.io.write(f"  Scope                      {run.scope}")
                self.io.write(f"  Task                       {run.current_stage}")
                self.io.write(f"  Status                     {run.status}")
                options = (
                    ("1", "Continue active Run"),
                    ("2", "Run Reference Text Comparison (RTC)"),
                    ("3", "Run Source Text Correspondence (STC)"),
                    ("4", "Run Targeted Check"),
                    ("5", "Run Original-Language Review"),
                    ("6", "Reports and exports"),
                    ("7", "Recovery and diagnostics"),
                    ("B", "Back"),
                )
            choice = self.io.choose(
                "SAW CHECKS",
                options,
                blank_before=("5",) if run is None else ("6",),
            )
            if choice == "B":
                return
            if run is None:
                if choice == "5":
                    self.reports_menu(project)
                elif choice == "6":
                    self.recovery_menu(project)
                else:
                    {"1": lambda: self.start_saw_run(project, "rtc"),
                     "2": lambda: self.start_saw_run(project, "stc"),
                     "3": lambda: self.start_saw_run(project, "focused"),
                     "4": lambda: self.start_saw_run(project, "ol")}[choice]()
            else:
                if choice == "1":
                    self.continue_run(project, run)
                elif choice == "2":
                    self.start_saw_run(project, "rtc")
                elif choice == "3":
                    self.start_saw_run(project, "stc")
                elif choice == "4":
                    self.start_saw_run(project, "focused")
                elif choice == "5":
                    self.start_saw_run(project, "ol")
                elif choice == "6":
                    self.reports_menu(project)
                elif choice == "7":
                    self.recovery_menu(project)

    @staticmethod
    def _saw_operation_label(operation: str) -> str:
        """Return the Alpha Operator label while preserving stable machine operation IDs."""
        return {"rtc": "Reference Text Comparison (RTC)", "stc": "Source Text Correspondence (STC)", "focused": "Targeted Check", "ol": "Original-Language Review"}.get(
            str(operation).lower(), str(operation).upper()
        )

    def _rtc_policy_menu(self, scope: str) -> dict[str, Any] | None:
        """Let the Operator tune RTC checks/policies before the Run snapshot is sealed."""
        profile_path = self.root / "system" / "config" / "workflows" / "saw" / "profile.yml"
        defaults = default_rtc_policy(profile_path)
        policy = {
            "policy_version": defaults["policy_version"],
            "checks": dict(defaults["checks"]),
            "usfm_contexts": dict(defaults["usfm_contexts"]),
            "original_language": dict(defaults.get("original_language") or {}),
        }
        check_rows = [
            ("structure_completeness", "Check structure and completeness"),
            ("translation_meaning", "Check translation and meaning"),
            ("language_readability", "Check language and readability"),
            ("consistency", "Check consistency"),
        ]
        context_rows = [
            ("add", r"Check added text        \add...\add*"),
            ("nd", r"Check Name of Deity     \nd...\nd*"),
            ("f", r"Check footnotes         \f...\f*"),
        ]
        policy_cycle = ("NORMAL", "MATERIAL_ONLY", "STRUCTURE_ONLY")
        while True:
            self.io.write_menu_header(f"REFERENCE TEXT COMPARISON (RTC): {scope}")
            self.io.write(menu_item(1, "Run Reference Text Comparison (RTC)"))
            self.io.write(menu_item(2, "Restore defaults"))
            self.io.write_menu_header("Checks [Choose number to toggle ON/OFF]", major=False)
            for index, (key, label) in enumerate(check_rows, 3):
                self.io.write(menu_item(index, f"{label:<40}{'ON' if policy['checks'][key] else 'OFF'}"))
            self.io.write_menu_header("Text policy [Choose number to cycle]", major=False)
            for index, (key, label) in enumerate(context_rows, 7):
                self.io.write(menu_item(index, f"{label:<40}{policy['usfm_contexts'][key].replace('_', ' ')}"))
            self.io.write_menu_header("Original-language evidence [Choose number to toggle]", major=False)
            drift = str((policy.get("original_language") or {}).get("source_text_drift_adjudication") or "PROHIBITED")
            self.io.write(menu_item(10, f"{'Adjudicate WIP-Reference variance':<40}{drift}"))
            self.io.write_menu_footer(include_back=True)
            value = self.io.read("Choose: ").strip().casefold()
            if value == "a":
                return None
            if value == "b":
                raise MenuHomeRequested()
            if value == "c":
                raise MenuExitRequested()
            if value == "d" and self.io.language_handler:
                self.io.language_handler()
                continue
            if value in {"e", "?"} and self.io.help_handler:
                self.io.help_handler("REFERENCE TEXT COMPARISON (RTC)")
                continue
            if value == "f" and self.io.status_handler:
                self.io.status_handler()
                continue
            if value == "1":
                if not any(bool(item) for item in policy.get("checks", {}).values()):
                    self.io.write("Enable at least one Reference Text Comparison (RTC) check before running.")
                    continue
                return policy
            if value == "2":
                policy = {
                    "policy_version": defaults["policy_version"],
                    "checks": dict(defaults["checks"]),
                    "usfm_contexts": dict(defaults["usfm_contexts"]),
                    "original_language": dict(defaults.get("original_language") or {}),
                }
                continue
            if value in {"3", "4", "5", "6"}:
                key = check_rows[int(value) - 3][0]
                policy["checks"][key] = not policy["checks"][key]
                continue
            if value in {"7", "8", "9"}:
                key = context_rows[int(value) - 7][0]
                current = str(policy["usfm_contexts"][key]).upper()
                try:
                    position = policy_cycle.index(current)
                except ValueError:
                    position = 0
                policy["usfm_contexts"][key] = policy_cycle[(position + 1) % len(policy_cycle)]
                continue
            if value == "10":
                current = str((policy.get("original_language") or {}).get("source_text_drift_adjudication") or "PROHIBITED").upper()
                policy.setdefault("original_language", {})["source_text_drift_adjudication"] = (
                    "ENABLED" if current == "PROHIBITED" else "PROHIBITED"
                )
                continue
            self.io.write("Invalid choice. Choose one listed option.")

    def start_saw_run(self, project: Job, operation: str) -> None:
        """Choose scope, preview bounded work, then create one SAW Run."""
        focus = None
        check_type = None
        if operation in {"focused", "ol"}:
            focus = self.io.text("One specific bounded question")
        if operation == "focused":
            types = (
                "CUSTOM_BOUNDED_CHECK", "MEANING_EQUIVALENCE", "KEY_TERM_CONSISTENCY",
                "PARTICIPANT_REFERENCE", "QUOTATION_STRUCTURE", "GRAMMATICAL_RELATIONSHIP",
                "DIVINE_NAME_CORRELATION",
            )
            selected = self.io.choose("Targeted check type", [(str(i), value) for i, value in enumerate(types, 1)])
            check_type = types[int(selected) - 1]
        self.ensure_initialized(project)
        while True:
            scope = self._select_scripture_scope(project, primary_binding="wip")
            if scope is None:
                return
            effective_policy = None
            if operation == "rtc":
                effective_policy = self._rtc_policy_menu(scope)
                if effective_policy is None:
                    return
            review = self._review_work_before_run(
                project, operation=operation, scope=scope, include_plan=True
            )
            assert isinstance(review, tuple)
            action, preview = review
            if action == "CHANGE":
                continue
            if action != "RUN":
                return
            ol_variance_enabled = bool(
                operation == "rtc"
                and str(
                    dict((effective_policy or {}).get("original_language") or {}).get(
                        "source_text_drift_adjudication", "PROHIBITED"
                    )
                ).upper() == "ENABLED"
            )
            preflight = self._preflight_saw_preview(
                project,
                preview,
                operation=operation,
                require_original_language=(operation == "stc" or ol_variance_enabled),
            )
            if preflight == "CHANGE":
                continue
            if preflight != "READY":
                return
            run = self.store.create_run(project, operation=operation, scope=scope, focus=focus, check_type=check_type)
            approved_plan_path = run.root / "plans" / "APPROVED-WORK-UNITS.json"
            approved_preview = dict(preview)
            approved_preview.update({
                "approval_status": "OPERATOR_APPROVED",
                "approved_run_id": run.run_id,
                "approved_job_id": project.job_id,
            })
            atomic_write_json(approved_plan_path, approved_preview)
            run = self.store.update_run(
                run,
                approved_work_plan_path=str(approved_plan_path),
            )
            if operation == "rtc" and effective_policy is not None:
                write_run_policy_snapshot(run.root, effective_policy)
            self._persist_saw_vrs_advisories(
                run,
                list(getattr(self, "_pending_saw_vrs_advisories", []) or []),
            )
            self.continue_run(project, run)
            return

    def _select_scripture_scope(self, project: Job, *, primary_binding: str) -> str | None:
        """Offer guided book/range selection while retaining expert direct scope entry."""
        while True:
            choice = self.io.choose(
                "CHOOSE SCRIPTURE SCOPE",
                (("1", "Choose Book"), ("2", "Enter complete scope directly"), ("B", "Back")),
                prompt="Choose or enter scope [1]: ",
                allow_blank=True,
                direct_validator=lambda value: parse_scope(value).label(),
            )
            if choice == "":
                choice = "1"
            if choice == "B": return None
            if choice == "2":
                return self.io.text(
                    "Scope (book = whole book; book chapter = whole chapter; example LUK 1:1-10)",
                    validator=lambda value: parse_scope(value).label(),
                )
            if choice != "1":
                return choice
            project_id = project.bindings[primary_binding]
            record = registered_project_records(self.root).get(project_id, {})
            books = tuple(str(value) for value in record.get("detected_books", []) if str(value))
            if not books:
                config = load_ecosystem(project.runtime_settings_path)
                books = tuple(config.project(project_id).expected_books)
            if not books:
                self.io.write("No detected Scripture books are available for this Project.")
                self.io.pause()
                continue
            selected = self.io.choose("CHOOSE BOOK", [(str(i), book) for i, book in enumerate(books, 1)] + [("B", "Back")])
            if selected == "B": continue
            book = books[int(selected) - 1]
            self.io.write()
            self.io.write(f"SCRIPTURE SCOPE - {book}")
            self.io.write("-" * 72)
            self.io.write("Range examples: [blank] whole book; 1 chapter 1; 1-3 chapters 1-3; 1:1-10 verses; 1:1-2:20 cross-chapter")
            value = self.io.text("Range", default="", required=False)
            scope = book if not value.strip() else f"{book} {value.strip()}"
            try:
                return parse_scope(scope).label()
            except SageError as exc:
                self.show_error(exc)

    def _review_work_before_run(
        self,
        project: Job,
        *,
        operation: str,
        scope: str,
        include_plan: bool = False,
    ) -> str | tuple[str, dict[str, Any]]:
        """Build the deterministic work-unit/token plan and return the operator action.

        SAW uses the optional returned plan for exact work-unit resource preflight before
        a Run is persisted. Existing callers retain the historical string-only result.
        """
        output = f"plans/pre-run-{project.tool}-{project.job_id}.manifest.json"
        result = self._run_with_status(
            f"Planning bounded {project.tool.upper()} work...",
            lambda: self.controller(
                project,
                ["workflow", "plan", "--workflow", project.tool, "--operation", operation, "--scope", scope, "--output", output],
            ),
            visible=not (
                project.tool == "saw"
                and operation.strip().lower() in {"rtc", "stc"}
            ),
        )
        if not isinstance(result, dict):
            raise ValidationError("Work preview did not return a plan", code="WORK_PREVIEW_FAILED")
        summary = dict(result.get("summary") or {})
        policy = dict(result.get("policy") or {})
        units = list(result.get("units") or [])
        self.io.write()
        self.io.write("REVIEW WORK BEFORE RUNNING")
        self.io.write("-" * 72)
        rtc_preview = project.tool == "saw" and operation.strip().lower() == "rtc"
        stc_preview = project.tool == "saw" and operation.strip().lower() == "stc"
        operation_label = (
            "Reference Text Comparison (RTC)"
            if rtc_preview
            else "Source Text Correspondence (STC)"
            if stc_preview
            else f"{project.tool.upper()} {operation.upper()}"
        )
        self.io.write(f"Operation:     {operation_label}")
        self.io.write(f"Scope:         {scope}")
        self.io.write(f"Planned work:  {summary.get('work_units', len(units))} work unit(s)")
        if not rtc_preview and not stc_preview and policy.get("hard_estimated_tokens") is not None:
            self.io.write(f"Token limit:   {policy['hard_estimated_tokens']:,}")
        if rtc_preview and (
            not units or any(not isinstance(unit.get("rtc_package"), dict) for unit in units)
        ):
            raise ValidationError(
                "RTC preview is missing governed WIP/REF/ROUTE package measurements",
                code="SAW_RTC_PREVIEW_INVALID",
            )
        if stc_preview and (
            not units or any(not isinstance(unit.get("stc_package"), dict) for unit in units)
        ):
            raise ValidationError(
                "STC preview is missing governed WIP/SRC/ROUTE package measurements",
                code="SAW_STC_PREVIEW_INVALID",
            )
        if rtc_preview:
            self.io.write()
            self.io.write(
                f"{'#':>3}  {'SCOPE':<20} {'WIP':>9} {'REF':>9} {'ROUTE':>10}"
            )
        elif stc_preview:
            self.io.write()
            self.io.write(
                f"{'#':>3}  {'SCOPE':<20} {'WIP':>9} {'SRC':>9} {'ROUTE':>10}"
            )
        for index, unit in enumerate(units, 1):
            package = dict(unit.get("rtc_package") or {})
            if rtc_preview and package:
                self.io.write(
                    f"{index:>3}. {str(unit.get('primary_scope', '?')):<20} "
                    f"{'~' + format(int(dict(package.get('wip') or {}).get('estimated_tokens', 0)), ','):>9} "
                    f"{'~' + format(int(dict(package.get('ref') or {}).get('estimated_tokens', 0)), ','):>9} "
                    f"{'~' + format(int(dict(package.get('route') or {}).get('estimated_tokens', 0)), ','):>10}"
                )
            elif stc_preview and unit.get("stc_package"):
                stc_package = dict(unit.get("stc_package") or {})
                self.io.write(
                    f"{index:>3}. {str(unit.get('primary_scope', '?')):<20} "
                    f"{'~' + format(int(dict(stc_package.get('wip') or {}).get('estimated_tokens', 0)), ','):>9} "
                    f"{'~' + format(int(dict(stc_package.get('ol') or {}).get('estimated_tokens', 0)), ','):>9} "
                    f"{'~' + format(int(dict(stc_package.get('route') or {}).get('estimated_tokens', 0)), ','):>10}"
                )
            else:
                measurement = dict(unit.get("measurement") or {})
                tokens = measurement.get("estimated_tokens", "?")
                self.io.write(menu_item(index, f"{unit.get('primary_scope', '?'):<20} ~{tokens} estimated routed-SFM tokens"))
        if rtc_preview:
            self.io.write(
                f"{'':>3}  {'Largest work unit':<20} "
                f"{'~' + format(int(summary.get('largest_wip_estimated_tokens', 0)), ','):>9} "
                f"{'~' + format(int(summary.get('largest_ref_estimated_tokens', 0)), ','):>9} "
                f"{'~' + format(int(summary.get('largest_route_estimated_tokens', 0)), ','):>10}"
            )
        elif stc_preview:
            self.io.write(
                f"{'':>3}  {'Largest work unit':<20} "
                f"{'~' + format(int(summary.get('largest_wip_estimated_tokens', 0)), ','):>9} "
                f"{'~' + format(int(summary.get('largest_ol_estimated_tokens', 0)), ','):>9} "
                f"{'~' + format(int(summary.get('largest_route_estimated_tokens', 0)), ','):>10}"
            )
        else:
            self.io.write(f"Largest work unit: ~{summary.get('largest_estimated_tokens', 0)} estimated routed-SFM tokens")
        choice = self.io.choose(
            "Next",
            (("1", "Run"), ("2", "Change scope"), ("B", "Back")),
        )
        action = {"1": "RUN", "2": "CHANGE", "B": "CANCEL"}[choice]
        return (action, result) if include_plan else action

    def _saw_preview_findings(
        self,
        project: Job,
        preview: dict[str, Any],
        *,
        require_original_language: bool = False,
    ) -> dict[str, list[dict[str, str]]]:
        """Return blocking resource defects and non-blocking VRS advisories per SAW work unit."""
        runtime_settings = self.store.ensure_runtime_files(project)
        config = load_ecosystem(runtime_settings)
        operation = str(preview.get("operation") or "").strip().lower()
        base_bindings = [("SAW WIP", str(project.bindings.get("wip") or ""))]
        if operation != "stc":
            base_bindings.append(
                ("SAW REFERENCE", str(project.bindings.get("reference") or ""))
            )
        units = list(preview.get("units") or [])
        blockers: list[dict[str, str]] = []
        advisories: list[dict[str, str]] = []
        seen_blockers: set[tuple[str, ...]] = set()
        seen_advisories: set[tuple[str, ...]] = set()
        for unit in units:
            unit_scope = str(unit.get("primary_scope") or "").strip()
            if not unit_scope:
                continue
            parsed_scope = parse_scope(unit_scope)
            bindings = list(base_bindings)
            if require_original_language:
                if parsed_scope.book in NT_27:
                    ol_label = "SAW OL GREEK"
                    ol_project_id = str(project.bindings.get("original_language_greek") or "")
                elif parsed_scope.book in OT_39:
                    ol_label = "SAW OL HEBREW"
                    ol_project_id = str(project.bindings.get("original_language_hebrew") or "")
                else:
                    ol_label = "SAW OL"
                    ol_project_id = ""
                if not ol_project_id:
                    row = {
                        "role": ol_label,
                        "project_id": "NOT_CONFIGURED",
                        "scope": unit_scope,
                        "status": "BLOCKED",
                        "code": "APPLICABLE_ORIGINAL_LANGUAGE_NOT_CONFIGURED",
                        "reference": unit_scope,
                        "message": (
                            "Option 11 requires the applicable Job-bound original-language "
                            "resource before the Run can start."
                        ),
                        "effective_vrs": "UNKNOWN",
                        "default_vrs": config.default_versification,
                    }
                    key = tuple(row[name] for name in ("role", "project_id", "scope", "code", "reference", "message"))
                    if key not in seen_blockers:
                        seen_blockers.add(key)
                        blockers.append(row)
                else:
                    bindings.append((ol_label, ol_project_id))
            for role, project_id in bindings:
                if not project_id:
                    continue
                bound_project = config.project(project_id)
                result = compile_project_scope(config, bound_project, parsed_scope)
                status = str(result.get("status") or "BLOCKED")
                issues = list(result.get("issues") or [])
                warnings = [
                    item for item in list(result.get("warnings") or [])
                    if str(item.get("code") or "").upper() in VERSIFICATION_ADVISORY_CODES
                ]
                findings = issues + warnings
                if not findings and status in {"READY", "READY_WITH_WARNINGS"}:
                    continue
                if not findings:
                    findings = [{
                        "code": f"RESOURCE_{status}",
                        "reference": unit_scope,
                        "message": f"Bound resource state is {status} for this work unit.",
                    }]
                for issue in findings:
                    code = str(issue.get("code") or "UNKNOWN").upper()
                    advisory = code in VERSIFICATION_ADVISORY_CODES or is_default_vrs_compatible_issue(config, bound_project, issue)
                    row = {
                        "role": role,
                        "project_id": project_id,
                        "scope": unit_scope,
                        "status": "ADVISORY" if advisory else status,
                        "code": str(issue.get("code") or "UNKNOWN"),
                        "reference": str(issue.get("reference") or unit_scope),
                        "message": str(issue.get("message") or "Resource validation failed."),
                        "effective_vrs": bound_project.versification.base,
                        "default_vrs": config.default_versification,
                    }
                    key = tuple(row[name] for name in ("role", "project_id", "scope", "code", "reference", "message"))
                    if advisory:
                        if key not in seen_advisories:
                            seen_advisories.add(key)
                            advisories.append(row)
                    elif key not in seen_blockers:
                        seen_blockers.add(key)
                        blockers.append(row)
        return {"blockers": blockers, "advisories": advisories}

    def _saw_preview_blockers(
        self,
        project: Job,
        preview: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Compatibility helper returning only defects that must block SAW execution."""
        return self._saw_preview_findings(project, preview)["blockers"]

    def _persist_saw_vrs_advisories(self, run: Run, advisories: list[dict[str, str]]) -> None:
        """Persist preflight VRS differences so the final SAW report retains them."""
        if not advisories:
            return
        atomic_write_json(
            run.root / "diagnostics" / "VERSIFICATION-ADVISORIES.json",
            {
                "schema_version": "1.0",
                "run_id": run.run_id,
                "status": "ADVISORY",
                "policy": "REPORT_AND_CONTINUE",
                "advisories": advisories,
            },
        )

    def _preflight_saw_preview(
        self,
        project: Job,
        preview: dict[str, Any],
        *,
        operation: str | None = None,
        require_original_language: bool = False,
    ) -> str:
        """Block real resource defects while reporting default-VRS-compatible differences."""
        while True:
            findings = self._run_with_status(
                "Checking SAW resources for each planned section...",
                lambda: self._saw_preview_findings(
                    project,
                    preview,
                    require_original_language=require_original_language,
                ),
                visible=str(operation or preview.get("operation") or "").strip().lower()
                not in {"rtc", "stc"},
            )
            blockers = list(findings.get("blockers") or [])
            advisories = list(findings.get("advisories") or [])
            self._pending_saw_vrs_advisories = advisories
            # Routine Run preflight keeps non-blocking VRS differences silent in the
            # interactive UI. They remain persisted with the Run and available in the
            # final Action Report and explicit Job-validation surfaces.
            if not blockers:
                return "READY"
            self.io.write()
            self.io.write("SAW RESOURCE PREFLIGHT BLOCKED")
            self.io.write("-" * 72)
            self.io.write(
                "Only sections with non-versification resource defects are blocked. No SAW Run has been created yet."
            )
            for index, row in enumerate(blockers[:20], 1):
                self.io.write(
                    menu_item(index, f"{row['scope']} | {row['role']} {row['project_id']} | {row['code']} | {row['reference']}")
                )
                self.io.write(f"   {row['message']}")
            if len(blockers) > 20:
                self.io.write(f"... {len(blockers) - 20} additional blocking defect(s).")
            self.io.write(
                "Next action: Correct the listed non-versification Scripture/resource defect in its source Project, "
                "then validate/recheck. SAGE will not bypass malformed or unavailable REFERENCE content."
            )
            project_ids = list(dict.fromkeys(row["project_id"] for row in blockers))
            options: list[tuple[str, str]] = []
            for index, project_id in enumerate(project_ids, 1):
                options.append((str(index), f"Maintain blocking Project [{project_id}]"))
            recheck_key = str(len(options) + 1)
            change_key = str(len(options) + 2)
            options.extend(((recheck_key, "Recheck resources"), (change_key, "Change scope"), ("B", "Back")))
            choice = self.io.choose("Next", options)
            if choice == "B":
                return "CANCEL"
            if choice == recheck_key:
                continue
            if choice == change_key:
                return "CHANGE"
            self.registered_project_detail(project_ids[int(choice) - 1])

    def _load_manifest(self, path: str | Path) -> dict[str, Any]:
        """Implement ` load manifest` in the deterministic terminal control flow."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return _json_file(candidate)

    def _manifest_path(self, value: str) -> Path:
        """Implement ` manifest path` in the deterministic terminal control flow."""
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    def _task_state(self, manifest_path: Path) -> tuple[str, dict[str, Any]]:
        """Implement ` task state` in the deterministic terminal control flow."""
        manifest = _json_file(manifest_path)
        if not manifest:
            return "MISSING", {}
        task_root = manifest_path.parent
        submission = _json_file(task_root / "validation" / "submission.json")
        if submission:
            return str(submission.get("status", "SUBMITTED")).upper(), manifest
        allowed = [str(value) for value in manifest.get("allowed_writes", [])]
        if allowed and all((task_root / value).is_file() for value in allowed):
            return "OUTPUT_READY", manifest
        return "TASK_CREATED", manifest

    def _append_task(self, run: Run, manifest_path: str) -> Run:
        """Implement ` append task` in the deterministic terminal control flow."""
        values = list(run.task_manifests)
        if manifest_path not in values:
            values.append(manifest_path)
        return self.store.update_run(run, task_manifests=values)

    def _create_task(
        self,
        project: Job,
        run: Run,
        operation: str,
        *,
        scope: str | None = None,
        predecessor: str | None = None,
    ) -> tuple[Run, dict[str, Any]]:
        """Implement ` create task` in the deterministic terminal control flow."""
        arguments = [
            "task",
            "create",
            "--workflow",
            project.tool,
            "--operation",
            operation,
        ]
        if project.tool == "bic":
            arguments.extend([
                "--target", project.output_project,
                "--source", project.contemporary_source,
            ])
            if project.lexical_donor:
                arguments.extend(["--donor", project.lexical_donor])
        else:
            arguments.extend([
                "--wip", project.output_project,
                "--reference", project.contemporary_source,
            ])
        arguments.extend([
            "--scope",
            scope or run.scope,
            "--job-id",
            project.job_id,
            "--run-id",
            run.run_id,
        ])
        if run.focus and operation in {"focused", "ol"}:
            arguments.extend(["--focus", run.focus])
        if run.check_type and operation == "focused":
            arguments.extend(["--type", run.check_type])
        if predecessor:
            arguments.extend(["--predecessor-task", predecessor])
        result = self._run_with_status(
            f"Preparing governed {project.tool.upper()} task plan...",
            lambda: self.controller(project, arguments),
        )
        if not isinstance(result, dict):
            raise ValidationError("Task creation returned no structured result")
        if result.get("status") in {"PARTITIONED", "COMPOSITE"}:
            manifests = (
                [str(item["manifest_path"]) for item in result.get("work_units", [])]
                if result.get("status") == "PARTITIONED"
                else [str(item) for item in result.get("task_manifests", [])]
            )
            run = self.store.update_run(
                run,
                plan_path=str(result["plan_path"]),
                status=str(result.get("status")),
                current_stage=str(result.get("current_stage") or operation.upper()),
                task_manifests=manifests,
            )
        else:
            run = self._append_task(run, str(result["manifest_path"]))
            run = self.store.update_run(
                run,
                status="TASK_CREATED",
                current_stage=operation.upper(),
            )
        return run, result

    def _ensure_codex_execution_transport(self) -> None:
        """Verify Codex runtime readiness without sending a preliminary model prompt."""
        if self.dry_run_provider or time.monotonic() < self._codex_transport_verified_until:
            return
        service = ModelService(self.root)
        settings = service.settings()
        if str(settings.get("selected_provider") or "").strip().lower() != "codex":
            return
        try:
            self._run_with_status(
                "Checking Codex execution readiness...",
                service.readiness_check,
            )
        except ValidationError as exc:
            raise ValidationError(
                "Codex is not ready for governed task execution.",
                code="CODEX_EXECUTION_NOT_READY",
                next_action=(
                    "Open Configure AI, correct installation/login/model selection, and use "
                    "Check LLM connection only when an explicit end-to-end test is needed."
                ),
                details={"provider_error": exc.message, "provider_code": exc.code},
            ) from exc
        self._codex_transport_verified_until = time.monotonic() + 600.0

    def _launch_task(
        self,
        project: Job,
        run: Run,
        manifest_path: Path,
        *,
        pause: bool = True,
    ) -> bool:
        """Execute one sealed task and report whether provider output is ready."""
        declared_manifest = declare_governed_path(self.root, manifest_path, "task manifest")
        arguments = ["task", "execute", "--task", declared_manifest]
        self.runtime_status.current_job = project.job_id
        self.runtime_status.current_project = project.output_project
        self.runtime_status.current_run = run.run_id
        self.runtime_status.stage = run.current_stage
        if self.dry_run_provider:
            arguments.append("--dry-run")
        try:
            self._ensure_codex_execution_transport()
            result = self._run_with_status(
                f"Running governed {project.tool.upper()} task...",
                lambda: self.controller(project, arguments),
            )
        except SageError as exc:
            self._record_execution_issue(
                project,
                run,
                exc,
                manifest_path=manifest_path,
                boundary_hint="TASK_ATTEMPT",
                pause=False,
            )
            self.io.write(f"Task remains resumable: {manifest_path}")
            self.io.pause()
            return False
        if not getattr(self, "_compact_saw_progress", False):
            if isinstance(result, dict):
                self.io.write(f"Task execution: {result.get('status', 'UNKNOWN')}")
                self.io.write(f"Provider: {result.get('provider', 'unknown')}")
                self.io.write(f"Model: {result.get('model') or 'provider default'}")
                if result.get("reasoning_effort"):
                    self.io.write(f"Reasoning: {result.get('reasoning_effort')}")
                if result.get("selection_mode"):
                    self.io.write(f"Selection: {result.get('selection_mode')}")
                if result.get("receipt_path"):
                    self.io.write(f"Receipt: {result['receipt_path']}")
            self.io.write(f"ACT: {manifest_path.parent / 'ACT.md'}")
        if pause:
            self.io.pause()
        return True

    def _submit_task(
        self,
        project: Job,
        run: Run,
        manifest_path: Path,
    ) -> Run:
        """Submit one governed result; rejected provider output is retryable at task scope."""
        declared_manifest = declare_governed_path(self.root, manifest_path, "task manifest")
        result = self._run_with_status(
            f"Submitting governed {project.tool.upper()} result...",
            lambda: self.controller(project, ["task", "submit", "--task", declared_manifest]),
        )
        status = str(result.get("status", "SUBMITTED")) if isinstance(result, dict) else "SUBMITTED"
        if not getattr(self, "_compact_saw_progress", False):
            self.io.write(f"Task submission: {status}")
        return self.store.update_run(run, status=status)

    def _task_action(
        self,
        project: Job,
        run: Run,
        manifest_path: Path,
    ) -> tuple[Run, bool]:
        """Advance one task; provider/output interruptions remain task-local and resumable."""
        state, manifest = self._task_state(manifest_path)
        if state == "TASK_CREATED":
            if not self._launch_task(project, run, manifest_path, pause=False):
                return run, False
            executed_state, _ = self._task_state(manifest_path)
            if executed_state == "OUTPUT_READY":
                try:
                    return self._submit_task(project, run, manifest_path), True
                except SageError as exc:
                    return self._handle_task_submission_failure(project, run, manifest_path, manifest, exc)
            self.io.write(
                "Provider execution completed without every required output; "
                "the task remains open."
            )
            self.io.pause()
            return run, False
        if state == "OUTPUT_READY":
            try:
                return self._submit_task(project, run, manifest_path), True
            except SageError as exc:
                return self._handle_task_submission_failure(project, run, manifest_path, manifest, exc)
        if state == "MISSING":
            raise ValidationError(f"Task manifest is missing: {manifest_path}")
        self.io.write(f"Task already submitted: {manifest.get('operation')} - {state}")
        return run, True

    def _handle_task_submission_failure(
        self,
        project: Job,
        run: Run,
        manifest_path: Path,
        manifest: dict[str, Any],
        exc: SageError,
    ) -> tuple[Run, bool]:
        """Persist submission failure evidence and prepare same-task retry when output is rejected."""
        event = self._record_execution_issue(
            project,
            run,
            exc,
            manifest_path=manifest_path,
            boundary_hint="TASK_ATTEMPT",
            pause=False,
        )
        if event["disposition"] == "TASK_OUTPUT_REJECTED":
            retry = archive_rejected_task_output(
                manifest_path,
                reason_code=exc.code,
                message=exc.message,
                event_id=event["event_id"],
            )
            if self._compact_saw_progress:
                scope = self._saw_task_scope_label(manifest, run)
                self.io.write(f"Work unit {scope} requires retry. The Run remains active.")
            else:
                self.io.write(f"Rejected output preserved: {retry['attempt_path']}")
                self.io.write("The same sealed task is ready for another provider attempt; the Run was not restarted.")
        if not self._compact_saw_progress:
            self.io.pause()
        return run, False

    def _tasks_by_operation(self, run: Run) -> dict[str, list[tuple[Path, dict[str, Any], str]]]:
        """Implement ` tasks by operation` in the deterministic terminal control flow."""
        result: dict[str, list[tuple[Path, dict[str, Any], str]]] = {}
        for value in run.task_manifests:
            path = self._manifest_path(value)
            state, manifest = self._task_state(path)
            operation = str(manifest.get("operation", "unknown"))
            result.setdefault(operation, []).append((path, manifest, state))
        return result

    @staticmethod
    def _saw_task_scope_label(manifest: dict[str, Any], run: Run) -> str:
        """Return the exact stage boundary represented by one SAW task."""
        if str(manifest.get("rtc_stage") or "") in {
            "STRUCTURAL_ADJUDICATION", "SELECTIVE_OL_ADJUDICATION"
        }:
            references = [
                str(value).strip()
                for value in (
                    manifest.get("rtc_stage_references")
                    or manifest.get("expected_references")
                    or []
                )
                if str(value).strip()
            ]
            if references:
                return "; ".join(references)
        return str(manifest.get("scope") or run.scope)

    def _record_execution_issue(
        self,
        project: Job,
        run: Run,
        exc: SageError,
        *,
        manifest_path: Path | None = None,
        boundary_hint: str | None = None,
        pause: bool = True,
    ) -> dict[str, Any]:
        """Persist one execution-affecting condition and render its narrow terminal projection."""
        manifest = _json_file(manifest_path) if manifest_path is not None else {}
        event = record_exception_event(
            self.root,
            exc,
            boundary_hint=boundary_hint,
            workflow=project.tool,
            job_id=project.job_id,
            run_id=run.run_id,
            task_id=str(manifest.get("task_id") or "") or None,
            operation=str(manifest.get("operation") or run.operation or "") or None,
            stage=str(manifest.get("rtc_stage") or run.current_stage or "") or None,
            requested_scope=run.scope,
            work_unit_scope=(self._saw_task_scope_label(manifest, run) if manifest else None),
            job_root=project.root,
            run_root=run.root,
            source_module="sage.menu",
        )
        if self._compact_saw_progress:
            scope = self._saw_task_scope_label(manifest, run)
            self.io.write(
                f"Work unit {scope} requires retry: {event['reason_code']} - {event['message']}"
            )
            self.io.write(f"Diagnostic report: {operator_path(self.root, event['report_path'])}")
            return event
        self.io.write()
        self.io.write(terminal_heading(event["disposition"]))
        self.io.write(f"Reason: {event['reason_code']}")
        self.io.write(f"Affected boundary: {event['blocks']}")
        self.io.write(f"Message: {operator_text(self.root, str(event['message']))}")
        blocking_issues = list((exc.details or {}).get("blocking_issues", []))
        if blocking_issues:
            self.io.write("Blocking defects:")
            for item in blocking_issues[:12]:
                self.io.write(
                    f"  - {item.get('code', 'UNKNOWN')} | "
                    f"{item.get('reference', exc.affected_scope or 'scope')} | "
                    f"{item.get('message', 'Resource validation failed.')}"
                )
            if len(blocking_issues) > 12:
                self.io.write(f"  ... {len(blocking_issues) - 12} additional defect(s).")
        if event.get("next_action"):
            self.io.write(f"Next action: {operator_text(self.root, str(event['next_action']))}")
        self.io.write(f"Diagnostic report: {operator_path(self.root, event['report_path'])}")
        if pause:
            self.io.pause()
        return event

    def continue_run(self, project: Job, run: Run) -> None:
        """Implement `continue run` in the deterministic terminal control flow."""
        try:
            self.ensure_initialized(project)
            if project.tool == "bic":
                run = self._continue_bic(project, run)
            else:
                run = self._continue_saw(project, run)
            if run.status in RUN_CLOSED_STATUSES:
                self.store.set_active_run(project, None)
            else:
                self.store.set_active_run(project, run.run_id)
        except SageError as exc:
            self._record_execution_issue(project, run, exc, pause=True)
        except Exception as exc:
            self.store.record_cue(
                "RUN_CONTINUATION_FAILED",
                tool=project.tool,
                job_id=project.job_id,
                run_id=run.run_id,
                error_type=type(exc).__name__,
            )
            wrapped = ValidationError(
                f"{type(exc).__name__}: {exc}",
                code="RUN_CONTINUATION_FAILED",
                next_action="Restart SAGE and continue the same Run; its saved state was preserved.",
            )
            self._record_execution_issue(project, run, wrapped, pause=True)

    def _restart_run_with_current_configuration(
        self,
        project: Job,
        run: Run | None,
    ) -> Run | None:
        """Confirm a recoverable restart while preserving the superseded Run."""
        if run is None:
            self.io.write("No active Run is available to restart.")
            self.io.pause()
            return None
        if run.status in RUN_CLOSED_STATUSES:
            self.io.write(f"Run {run.run_id} is already {run.status.lower()}.")
            self.io.pause()
            return None
        self.io.write(f"Run to preserve: {run.run_id}")
        self.io.write(f"Replacement scope: {run.scope}")
        self.io.write("Existing tasks and outputs will remain available under the abandoned Run.")
        if not self.io.confirm("Restart this Run using the current configuration?", default=False):
            return None
        self.ensure_initialized(project)
        replacement = self.store.restart_run(project, run)
        self.store.record_cue(
            "RUN_RESTARTED",
            tool=project.tool,
            job_id=project.job_id,
            abandoned_run_id=run.run_id,
            replacement_run_id=replacement.run_id,
            scope=run.scope,
        )
        self.io.write(f"Preserved old Run as ABANDONED: {run.run_id}")
        self.io.write(f"Created replacement Run: {replacement.run_id}")
        return replacement

    def _continue_bic(self, project: Job, run: Run) -> Run:
        """Implement ` continue bic` in the deterministic terminal control flow."""
        tasks = self._tasks_by_operation(run)
        if run.plan_path:
            return self._continue_partitioned_bic(project, run)
        inspect_tasks = tasks.get("inspect", [])
        if not inspect_tasks:
            run, result = self._create_task(project, run, "inspect")
            if result.get("status") == "PARTITIONED":
                self.io.write(f"BIC scope was partitioned into {len(result.get('work_units', []))} units.")
                return run
            self.io.write(f"Created INSPECT ACT: {result['act_path']}")
            return run
        inspect_path, inspect_manifest, inspect_state = inspect_tasks[-1]
        if inspect_state not in {"COMMITTED"}:
            run, _ = self._task_action(project, run, inspect_path)
            return self.store.update_run(run, current_stage="INSPECT")

        rewrite_tasks = tasks.get("rewrite", [])
        if not rewrite_tasks:
            run, result = self._create_task(project, run, "rewrite")
            self.io.write(f"Created REWRITE ACT: {result['act_path']}")
            return run
        rewrite_path, rewrite_manifest, rewrite_state = rewrite_tasks[-1]
        if rewrite_state not in {"STAGED_VALIDATED", "STAGED_VALIDATED_WITH_CHALLENGES", "ABANDONED"}:
            run, _ = self._task_action(project, run, rewrite_path)
            return self.store.update_run(run, current_stage="REWRITE")
        if rewrite_state == "ABANDONED":
            return self.store.update_run(run, status="ABANDONED", current_stage="REWRITE")

        self_check_tasks = tasks.get("self_check", [])
        if not self_check_tasks:
            run, result = self._create_task(
                project,
                run,
                "self_check",
                predecessor=str(rewrite_path),
            )
            self.io.write(f"Created SELF-CHECK ACT: {result['act_path']}")
            return run
        self_path, _, self_state = self_check_tasks[-1]
        if self_state != "COMMITTED":
            run, _ = self._task_action(project, run, self_path)
            if self._task_state(self_path)[0] != "COMMITTED":
                return self.store.update_run(run, current_stage="SELF_CHECK")
        run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
        self.io.write("BIC run is complete and the bounded target commit is recorded.")
        self.io.pause()
        return run

    def _continue_partitioned_bic(self, project: Job, run: Run) -> Run:
        """Implement ` continue partitioned bic` in the deterministic terminal control flow."""
        plan = _json_file(self._manifest_path(run.plan_path or ""))
        units = plan.get("work_units", []) if isinstance(plan, dict) else []
        if not units:
            raise ValidationError("Partitioned BIC run has no valid work units")
        tasks = self._tasks_by_operation(run)
        for unit in units:
            inspect_path = self._manifest_path(str(unit["manifest_path"]))
            inspect_state, inspect_manifest = self._task_state(inspect_path)
            unit_scope = str(unit["scope"])
            if inspect_state != "COMMITTED":
                run, _ = self._task_action(project, run, inspect_path)
                return self.store.update_run(
                    run,
                    current_stage=f"INSPECT {unit.get('unit_id')}",
                    status="PARTITIONED_IN_PROGRESS",
                )
            rewrite = next(
                (
                    row
                    for row in tasks.get("rewrite", [])
                    if str(row[1].get("scope")) == unit_scope
                ),
                None,
            )
            if rewrite is None:
                run, result = self._create_task(project, run, "rewrite", scope=unit_scope)
                self.io.write(f"Created REWRITE for {unit_scope}: {result['act_path']}")
                return run
            rewrite_path, _, rewrite_state = rewrite
            if rewrite_state not in {"STAGED_VALIDATED", "STAGED_VALIDATED_WITH_CHALLENGES"}:
                run, _ = self._task_action(project, run, rewrite_path)
                return self.store.update_run(run, current_stage=f"REWRITE {unit_scope}")
            self_check = next(
                (
                    row
                    for row in tasks.get("self_check", [])
                    if str(row[1].get("scope")) == unit_scope
                ),
                None,
            )
            if self_check is None:
                run, result = self._create_task(
                    project,
                    run,
                    "self_check",
                    scope=unit_scope,
                    predecessor=str(rewrite_path),
                )
                self.io.write(f"Created SELF-CHECK for {unit_scope}: {result['act_path']}")
                return run
            self_path, _, self_state = self_check
            if self_state != "COMMITTED":
                run, _ = self._task_action(project, run, self_path)
                return self.store.update_run(run, current_stage=f"SELF_CHECK {unit_scope}")
        run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
        self.io.write("All partitioned BIC work units are committed.")
        self.io.pause()
        return run

    def _preflight_saw_route(self, run: Run) -> dict[str, Any] | None:
        """Resolve the exact current SAW route before task creation or visible work."""
        skill_ids = {
            "rtc": "saw-rtc",
            "stc": "saw-stc",
            "focused": "saw-focused-check",
            "ol": "saw-original-language-review",
        }
        actual = self._active_run_route_row(run)
        if self.dry_run_provider:
            return actual
        return ModelService(self.root).recommendation_for_skill(skill_ids[run.operation])

    def _write_saw_run_header(
        self,
        project: Job,
        run: Run,
        *,
        route: dict[str, Any] | None = None,
    ) -> None:
        """Render the shared STC/RTC Run header before live work-unit progress."""
        route_text = "AUTOMATIC Skill routing (resolved per task)"
        route = route or self._active_run_route_row(run)
        if route is not None:
            route_text = (
                f"{route.get('provider')} / {route.get('model_id')} / "
                f"{route.get('reasoning_id')} [{route.get('qualification')}]"
            )
        self.io.write()
        self.io.write(project.job_id)
        self.io.write("=" * 72)
        self.io.write()
        comparison_project = project.contemporary_source
        if run.operation == "stc":
            book = parse_scope(run.scope).book
            comparison_project = str(
                project.bindings.get(
                    "original_language_greek" if book in NT_27 else "original_language_hebrew"
                )
                or ("GRK" if book in NT_27 else "HEB")
            ) + " OL"
        self.io.write(f"{project.output_project} checked against {comparison_project}")
        self.io.write(f"Checking {self._saw_operation_label(run.operation)} for {run.scope}")
        self.io.write(f"Using {route_text}")
        self.io.write()
        self.io.write("-" * 72)

    @contextmanager
    def _saw_work_unit_status(
        self,
        *,
        index: int,
        total: int,
        scope: str,
    ) -> Iterator[None]:
        """Render the one shared STC/RTC work-unit line and suppress nested admin chatter."""
        previous = getattr(self, "_compact_saw_progress", False)
        self._compact_saw_progress = True
        try:
            with self.io.working(
                f"Working on SAW work unit {index}/{total}: {scope}",
                ellipsis=False,
            ):
                yield
        finally:
            self._compact_saw_progress = previous

    def _write_saw_run_complete(
        self,
        project: Job,
        run: Run,
        *,
        report_directory: str | None = None,
    ) -> None:
        """Render one completion template for standalone and planned STC/RTC Runs."""
        self.io.write()
        self.io.write("SAW RUN COMPLETE")
        self.io.write("=" * 72)
        self.io.write(f"{'Job':<20}{project.job_id}")
        self.io.write(f"{'Check':<20}{self._saw_operation_label(run.operation)}")
        self.io.write(f"{'Scope':<20}{run.scope}")
        self.io.write(f"{'Status':<20}COMPLETE")
        if str(report_directory or "").strip():
            self.io.write(
                f"{'Reports':<20}{operator_path(self.root, str(report_directory))}"
            )

    def _ensure_stc_task_publication(self, project: Job, manifest_path: Path) -> dict[str, Any]:
        """Regenerate a standalone STC report before closing or repairing its Run."""
        config = load_ecosystem(self.store.ensure_runtime_files(project))
        return publish_stc_task_reports(config, manifest_path)

    def _continue_saw(self, project: Job, run: Run) -> Run:
        """Implement ` continue saw` in the deterministic terminal control flow."""
        standard_run_ui = run.operation in {"rtc", "stc"}
        preflight_route = self._preflight_saw_route(run) if standard_run_ui else None
        if not run.task_manifests and not run.plan_path:
            if standard_run_ui:
                self._compact_saw_progress = True
                try:
                    run, result = self._create_task(project, run, run.operation)
                finally:
                    self._compact_saw_progress = False
            else:
                run, result = self._create_task(project, run, run.operation)
            result_status = str(result.get("status") or "")
            if result_status in {"PARTITIONED", "COMPOSITE"}:
                pass
            else:
                act_path = result.get("act_path")
                if not act_path:
                    raise ValidationError(
                        "SAW task creation returned neither a governed task nor a recognized plan",
                        code="SAW_TASK_RESULT_INVALID",
                    )
                if not standard_run_ui:
                    self.io.write(f"Created SAW ACT: {act_path}")
            if run.plan_path:
                return self._continue_saw_plan(project, run)
            path = self._manifest_path(run.task_manifests[-1])
            if standard_run_ui:
                self._write_saw_run_header(project, run, route=preflight_route)
                with self._saw_work_unit_status(index=1, total=1, scope=run.scope):
                    run, submitted = self._task_action(project, run, path)
            else:
                run, submitted = self._task_action(project, run, path)
            if submitted and self._task_state(path)[0] == "FINALIZED":
                publication = (
                    self._ensure_stc_task_publication(project, path)
                    if run.operation == "stc"
                    else {}
                )
                run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
                if standard_run_ui:
                    self._write_saw_run_complete(
                        project,
                        run,
                        report_directory=str(publication.get("report_directory") or ""),
                    )
                else:
                    self.io.write("SAW Run complete. Governed findings remain with the Job; open Reports from the Main Menu.")
                self.io.pause()
            return run
        if run.plan_path:
            return self._continue_saw_plan(project, run)
        path = self._manifest_path(run.task_manifests[-1])
        state, _ = self._task_state(path)
        if state != "FINALIZED":
            if standard_run_ui:
                self._write_saw_run_header(project, run, route=preflight_route)
                with self._saw_work_unit_status(index=1, total=1, scope=run.scope):
                    run, _ = self._task_action(project, run, path)
            else:
                run, _ = self._task_action(project, run, path)
            if self._task_state(path)[0] != "FINALIZED":
                return self.store.update_run(run, current_stage=run.operation.upper())
        publication = (
            self._ensure_stc_task_publication(project, path)
            if run.operation == "stc"
            else {}
        )
        run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
        if standard_run_ui:
            self._write_saw_run_complete(
                project,
                run,
                report_directory=str(publication.get("report_directory") or ""),
            )
        else:
            self.io.write("SAW Run complete. Governed findings remain with the Job; open Reports from the Main Menu.")
        self.io.pause()
        return run

    def _continue_saw_plan(self, project: Job, run: Run) -> Run:
        """Advance a SAW plan with one compact live work-unit progress line."""
        route = self._preflight_saw_route(run)
        self._write_saw_run_header(project, run, route=route)
        while True:
            result = self.controller(project, ["task", "continue", "--plan", str(run.plan_path)])
            if not isinstance(result, dict):
                raise ValidationError("SAW continuation returned no structured result")
            status = str(result.get("status"))
            if status == "NEXT_WORK_UNIT":
                next_unit = dict(result["next_unit"])
                path = self._manifest_path(str(next_unit["manifest_path"]))
                if str(path) not in run.task_manifests:
                    run = self._append_task(run, str(path))
                completed = int(result.get("completed_units", 0) or 0)
                total = int(result.get("total_units", 0) or 0) or 1
                unit_scope = str(next_unit.get("scope") or run.scope)
                with self._saw_work_unit_status(
                    index=completed + 1,
                    total=total,
                    scope=unit_scope,
                ):
                    run, submitted = self._task_action(project, run, path)
                progress = f"{completed + (1 if submitted else 0)}/{total}"
                stage = str(result.get("composite_stage") or f"WORK_UNIT {progress}")
                run = self.store.update_run(
                    run,
                    status="PARTITIONED_IN_PROGRESS",
                    current_stage=stage,
                )
                if not submitted:
                    return run
                continue
            if status == "READY_TO_AGGREGATE":
                aggregate_plan = str(result.get("aggregate_plan_path") or run.plan_path)
                self._compact_saw_progress = True
                try:
                    with self.io.working("Aggregating SAW results", ellipsis=False):
                        aggregate = self.controller(project, ["task", "aggregate", "--plan", aggregate_plan])
                finally:
                    self._compact_saw_progress = False
                if result.get("aggregate_plan_path"):
                    run = self.store.update_run(
                        run,
                        status="COMPOSITE_IN_PROGRESS",
                        current_stage=str(result.get("composite_stage") or "RTC"),
                    )
                    continue
                run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
                report_directory = str(aggregate.get("report_directory") or "").strip()
                self._write_saw_run_complete(
                    project,
                    run,
                    report_directory=report_directory,
                )
                self.io.pause()
                return run
            if status == "COMPLETE":
                run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
                report_directory = str(result.get("report_directory") or "").strip()
                self._write_saw_run_complete(
                    project,
                    run,
                    report_directory=report_directory,
                )
                self.io.pause()
                return run
            raise ValidationError(f"Unsupported SAW continuation status: {status}")

    # ---------- Run dashboard/history ----------

    def runs_menu(self, project: Job) -> None:
        """Implement `runs menu` in the deterministic terminal control flow."""
        while True:
            runs = self.store.list_runs(project)
            choice = self.io.choose(
                f"{project.tool.upper()} - {self.localizer.text('Runs and task history')}",
                (
                    ("1", "Open active Run"),
                    ("2", "Incomplete Runs"),
                    ("3", "Completed Runs"),
                    ("4", "Search Runs"),
                    ("5", "Open another Run"),
                    ("6", "Task and plan files"),
                    ("7", "Export Run"),
                    ("8", "Archive completed Run"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            if choice == "1":
                run = self.store.active_run(project)
                if run:
                    self.run_dashboard(project, run)
                else:
                    self.io.write("No active run.")
                    self.io.pause()
            elif choice == "2":
                self.show_run_list(
                    [item for item in runs if item.status not in {"COMPLETE", "ARCHIVED", "ABANDONED"}]
                )
            elif choice == "3":
                self.show_run_list(
                    [item for item in runs if item.status in {"COMPLETE", "ARCHIVED"}]
                )
            elif choice == "4":
                query = self.io.text("Book, scope, operation, date, or run ID").casefold()
                matches = [
                    item
                    for item in runs
                    if query
                    in " ".join(
                        (
                            item.run_id,
                            item.scope,
                            item.operation,
                            item.status,
                            item.current_stage,
                            item.created_utc,
                        )
                    ).casefold()
                ]
                self.show_run_list(matches)
            elif choice == "5":
                run = self.choose_run(project, runs)
                if run:
                    if run.status not in RUN_CLOSED_STATUSES:
                        self.store.set_active_run(project, run.run_id)
                    self.run_dashboard(project, run)
            elif choice == "6":
                for run in runs:
                    self.io.write(f"{run.run_id} [{run.status}]")
                    if run.plan_path:
                        self.io.write(f"  PLAN {_relative(self.root, self._manifest_path(run.plan_path))}")
                    for task in run.task_manifests:
                        self.io.write(f"  TASK {_relative(self.root, self._manifest_path(task))}")
                self.io.pause()
            elif choice == "7":
                run = self.choose_run(project, runs)
                if run:
                    path = self.store.export_run(project, run)
                    self.io.write(f"Run bundle: {path}")
                    self.io.pause()
            elif choice == "8":
                run = self.choose_run(project, [item for item in runs if item.status == "COMPLETE"])
                if run:
                    self.store.update_run(run, status="ARCHIVED", current_stage="ARCHIVED")

    def show_run_list(self, runs: Sequence[Run]) -> None:
        """Implement `show run list` in the deterministic terminal control flow."""
        if not runs:
            self.io.write("No runs match this view.")
        for run in runs:
            self.io.write(
                f"{run.run_id} | {run.scope} | {run.operation.upper()} | "
                f"{run.current_stage}, {run.status}"
            )
        self.io.pause()

    def choose_run(self, project: Job, runs: Sequence[Run]) -> Run | None:
        """Implement `choose run` in the deterministic terminal control flow."""
        if not runs:
            self.io.write("No runs match this action.")
            self.io.pause()
            return None
        options = [
            (
                str(index),
                f"{run.scope}: {run.operation.upper()} [{run.current_stage}, {run.status}] ({run.run_id})",
            )
            for index, run in enumerate(runs, 1)
        ]
        options.append(("B", "Back"))
        choice = self.io.choose("Choose Run", options)
        return None if choice == "B" else runs[int(choice) - 1]

    def run_dashboard(self, project: Job, run: Run) -> None:
        """Implement `run dashboard` in the deterministic terminal control flow."""
        while True:
            run = self.store.load_run(project, run.run_id)
            choice = self.io.choose(
                f"Run {run.run_id} | {run.scope} | {run.current_stage}, {run.status}",
                (
                    ("1", "Continue Run"),
                    ("2", "Execute current governed task"),
                    ("3", "Submit current task"),
                    ("4", "Run status and blockers"),
                    ("5", "ACT and manifest paths"),
                    ("6", "Outputs and reports"),
                    ("7", "Diagnostics and control records"),
                    ("8", "Archive or abandon Run"),
                    ("9", "Advanced Run controls"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            if choice == "1":
                self.continue_run(project, run)
            elif choice in {"2", "3"}:
                current = self.current_open_task(run)
                if current is None:
                    self.io.write("No open task is available.")
                    self.io.pause()
                elif choice == "2":
                    self._launch_task(project, run, current)
                else:
                    self._submit_task(project, run, current)
            elif choice == "4":
                self.io.write(json.dumps(_json_file(run.status_path), indent=2, ensure_ascii=False))
                self.io.pause()
            elif choice == "5":
                current = self.current_open_task(run)
                if current:
                    self.io.write(f"Manifest: {current}")
                    self.io.write(f"ACT: {current.parent / 'ACT.md'}")
                else:
                    self.io.write("No open task.")
                self.io.pause()
            elif choice == "6":
                self.list_files(run.root, patterns=("*.md", "*.json", "*.txt", "*.tsv"))
            elif choice == "7":
                self.list_files(run.root / "diagnostics", patterns=("*.json", "*.jsonl", "*.md"))
            elif choice == "8":
                action = self.io.choose(
                    "Run disposition",
                    (
                        ("1", "Archive"),
                        ("2", "Abandon"),
                        ("3", "Restart with current settings"),
                        ("B", "Back"),
                    ),
                )
                if action == "1":
                    self.store.update_run(run, status="ARCHIVED", current_stage="ARCHIVED")
                    return
                if action == "2":
                    self.store.update_run(run, status="ABANDONED", current_stage="ABANDONED")
                    return
                if action == "3":
                    replacement = self._restart_run_with_current_configuration(project, run)
                    if replacement is not None:
                        self.continue_run(project, replacement)
                        return
            elif choice == "9":
                self.advanced_run_menu(project, run)

    def current_open_task(self, run: Run) -> Path | None:
        """Implement `current open task` in the deterministic terminal control flow."""
        for value in reversed(run.task_manifests):
            path = self._manifest_path(value)
            state, _ = self._task_state(path)
            if state in {"TASK_CREATED", "OUTPUT_READY"}:
                return path
        return None

    def advanced_run_menu(self, project: Job, run: Run) -> None:
        """Implement `advanced run menu` in the deterministic terminal control flow."""
        choice = self.io.choose(
            "Advanced Run Controls",
            (
                ("1", "Reinitialize Job"),
                ("2", "Show task commands"),
                ("3", "Clear active Run selection"),
                ("B", "Back"),
            ),
        )
        if choice == "1":
            self.ensure_initialized(project, force=True)
        elif choice == "2":
            for value in run.task_manifests:
                self.io.write(
                    render_sage_command(
                        [
                            "--settings",
                            project.runtime_settings_path,
                            "task",
                            "submit",
                            "--task",
                            self._manifest_path(value),
                        ]
                    )
                )
            self.io.pause()
        elif choice == "3":
            self.store.set_active_run(project, None)

    # ---------- BIC project operations ----------

    def bic_memory_menu(self, project: Job) -> None:
        """Implement `bic memory menu` in the deterministic terminal control flow."""
        while True:
            choice = self.io.choose(
                "BIC Memory and Terminology",
                (
                    ("1", "All memory records"),
                    ("2", "Records by state"),
                    ("3", "Change record state"),
                    ("4", "Record INSPECT review"),
                    ("5", "Import governed lexicon"),
                    ("6", "Roll back lexicon import"),
                    ("7", "Show memory folder"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            try:
                if choice == "1":
                    self.print_payload(self.controller(project, ["memory", "list"]))
                elif choice == "2":
                    state = self.io.text("State (for example PROPOSED or APPROVED_FOR_USE)").upper()
                    self.print_payload(self.controller(project, ["memory", "list", "--state", state]))
                elif choice == "3":
                    record_id = self.io.text("Record ID")
                    expected = self.io.text("Current state").upper()
                    new = self.io.text("New state").upper()
                    decision = self.io.text("Decision ID")
                    operator = self.io.text("Operator")
                    self.print_payload(
                        self.controller(
                            project,
                            [
                                "memory",
                                "transition",
                                "--record-id",
                                record_id,
                                "--from",
                                expected,
                                "--to",
                                new,
                                "--decision-id",
                                decision,
                                "--operator",
                                operator,
                            ],
                        )
                    )
                elif choice == "4":
                    scope = self.io.text("INSPECT scope", validator=lambda value: parse_scope(value).label())
                    decision_id = self.io.text("Decision ID")
                    reviewer = self.io.text("Reviewer")
                    decision = self.io.choose(
                        "Review decision",
                        (("1", "APPROVED_FOR_REWRITE"), ("2", "RETURN_FOR_REVIEW"), ("3", "REJECTED")),
                    )
                    mapped = {"1": "APPROVED_FOR_REWRITE", "2": "RETURN_FOR_REVIEW", "3": "REJECTED"}[decision]
                    self.print_payload(
                        self.controller(
                            project,
                            [
                                "memory",
                                "review",
                                "--scope",
                                scope,
                                "--decision-id",
                                decision_id,
                                "--reviewer",
                                reviewer,
                                "--decision",
                                mapped,
                            ],
                        )
                    )
                elif choice == "5":
                    source = self.io.text("Lexicon YAML or JSON path")
                    decision = self.io.text("Decision ID")
                    operator = self.io.text("Operator")
                    self.print_payload(
                        self.controller(project, ["memory", "import-lexicon", "--file", source, "--decision-id", decision, "--operator", operator])
                    )
                elif choice == "6":
                    import_id = self.io.text("Import ID")
                    decision = self.io.text("Decision ID")
                    operator = self.io.text("Operator")
                    self.print_payload(
                        self.controller(project, ["memory", "rollback-import", "--import-id", import_id, "--decision-id", decision, "--operator", operator])
                    )
                elif choice == "7":
                    self.io.write(str(project.root / "memory"))
                    self.list_files(project.root / "memory", patterns=("*.json", "*.md"))
            except SageError as exc:
                self.show_error(exc)

    def bic_generation_menu(self, project: Job) -> None:
        """Implement `bic generation menu` in the deterministic terminal control flow."""
        target = project.bindings["generated_target"]
        while True:
            choice = self.io.choose(
                "Generated Target and Generations",
                (
                    ("1", "Generations"),
                    ("2", "Verify current generation"),
                    ("3", "Publish generated TARGET"),
                    ("4", "Show TARGET folder"),
                    ("5", "TARGET commit history"),
                    ("6", "Revert one TARGET scope"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            try:
                if choice == "1":
                    self.print_payload(self.controller(project, ["generation", "list", "--project", target]))
                elif choice == "2":
                    self.print_payload(self.controller(project, ["generation", "verify", "--project", target, "--selector", "current"]))
                elif choice == "3":
                    if self.io.confirm("Publish an immutable generation from the current validated target?", default=False):
                        self.print_payload(self.controller(project, ["generation", "publish", "--project", target]))
                elif choice == "4":
                    config = load_ecosystem(project.runtime_settings_path)
                    self.io.write(str(config.project(target).path))
                    self.io.pause()
                elif choice == "5":
                    scope = self.io.text("Scope filter (blank for all)", required=False)
                    arguments = ["project", "target-history", "--job", project.job_id]
                    if scope:
                        arguments.extend(["--scope", parse_scope(scope).label()])
                    self.print_payload(self.controller(project, arguments))
                elif choice == "6":
                    scope = self.io.text("Exact committed TARGET scope", validator=lambda value: parse_scope(value).label())
                    if self.io.confirm(
                        f"Revert TARGET scope {scope} to its immediately preceding committed state?",
                        default=False,
                    ):
                        self.print_payload(
                            self.controller(
                                project,
                                ["project", "revert-target-scope", "--job", project.job_id, "--scope", scope],
                            )
                        )
            except SageError as exc:
                self.show_error(exc)

    # ---------- Shared menus ----------

    def reports_menu(self, project: Job) -> None:
        """Implement `reports menu` in the deterministic terminal control flow."""
        choice = self.io.choose(
            f"{project.tool.upper()} - {self.localizer.text('Reports and exports')}",
            (
                ("1", "Run report data"),
                ("2", "Job reports"),
                ("3", "Exports"),
                ("4", "Job data folder"),
                ("B", "Back"),
            ),
        )
        if choice == "1":
            self.list_files(project.root / "runs", patterns=("*.md", "*.json", "*.txt", "*.tsv"))
        elif choice == "2":
            self.list_files(storage_layout(self.root).reports_root / project.job_id, patterns=("*.md", "*.txt"))
        elif choice == "3":
            self.list_files(project.root / "exports", patterns=("*",))
        elif choice == "4":
            self.io.write(str(project.root))
            self.io.pause()

    def recovery_menu(self, project: Job) -> None:
        """Implement `recovery menu` in the deterministic terminal control flow."""
        while True:
            recovery_options = [
                ("1", "List incomplete transactions"),
                ("2", "Recover one transaction"),
                ("3", "Reinitialize Job"),
                ("4", "Abandon active Run"),
                ("5", "Export diagnostics"),
                ("6", "Restart active Run"),
            ]
            if project.tool == "bic":
                recovery_options.append(("7", "Restart one BIC scope [TARGET unchanged]"))
            recovery_options.append(("B", "Back"))
            choice = self.io.choose(
                f"{project.tool.upper()} - {self.localizer.text('Recovery and Reset')}",
                tuple(recovery_options),
            )
            if choice == "B":
                return
            try:
                if choice == "1":
                    self.print_payload(self.controller(project, ["transaction", "list", "--workflow", project.tool]))
                elif choice == "2":
                    transaction_id = self.io.text("Transaction ID")
                    self.print_payload(
                        self.controller(project, ["transaction", "recover", "--workflow", project.tool, "--id", transaction_id])
                    )
                elif choice == "3":
                    self.print_payload(self.ensure_initialized(project, force=True))
                elif choice == "4":
                    run = self.store.active_run(project)
                    if run and self.io.confirm(f"Abandon run {run.run_id}?", default=False):
                        self.store.update_run(run, status="ABANDONED", current_stage="ABANDONED")
                        self.store.set_active_run(project, None)
                elif choice == "5":
                    destination = project.root / "diagnostics" / "diagnostic-files.json"
                    files = [
                        _relative(project.root, path)
                        for path in sorted(project.root.rglob("*"))
                        if path.is_file()
                    ]
                    destination.write_text(json.dumps({"project": project.job_id, "files": files}, indent=2), encoding="utf-8")
                    self.io.write(f"Diagnostic listing: {destination}")
                    self.io.pause()
                elif choice == "6":
                    run = self.store.active_run(project)
                    replacement = self._restart_run_with_current_configuration(project, run)
                    if replacement is not None:
                        self.io.pause()
                elif choice == "7" and project.tool == "bic":
                    scope = self.io.text("BIC scope to restart", validator=lambda value: parse_scope(value).label())
                    run = self.store.restart_bic_scope(project, scope=scope)
                    self.io.write(f"Restarted BIC analytical scope {scope}: {run.run_id}")
                    self.io.write("TARGET Scripture changed: NO")
                    self.io.pause()
            except SageError as exc:
                self.show_error(exc)

    def project_readiness(self, project: Job) -> None:
        """Validate one Job freshly, offer safe remediation, and show a bounded summary."""
        try:
            self._offer_detected_vrs_updates(project)
            state = self.ensure_initialized(project, force=True)
            self._show_job_readiness_summary(project, state)
        except SageError as exc:
            self.show_error(exc)

    def _offer_detected_vrs_updates(self, project: Job) -> bool:
        """Offer explicit base-VRS corrections derived from each bound Project's comments."""
        config = load_ecosystem(self.store.settings_path)
        records = registered_project_records(self.root)
        mounts = load_resource_mounts(self.root)
        candidates: list[tuple[str, dict[str, Any], str, str]] = []
        for project_id in dict.fromkeys(project.bindings.values()):
            record = records.get(project_id)
            mount = mounts.get(project_id)
            if not isinstance(record, dict) or not isinstance(mount, dict):
                continue
            path = Path(str(mount.get("path") or "")).expanduser()
            if not path.is_dir():
                continue
            row = inspect_paratext_project(path)
            detected = dict(row.get("versification") or {})
            detected_base = str(detected.get("base_file") or "").strip()
            current_vrs = dict(record.get("versification") or {})
            current_base = str(current_vrs.get("base_file") or "").strip()
            if (
                not detected_base
                or detected_base.casefold() not in config.base_vrs_files
                or detected_base.casefold() == current_base.casefold()
            ):
                continue
            candidates.append((project_id, detected, current_base, detected_base))
        if not candidates:
            return False

        self.io.write()
        self.io.write("VERSIFICATION SETUP")
        self.io.write("-" * 72)
        self.io.write("SAGE found a configured base VRS named by the Project's custom.vrs comments.")
        for project_id, detected, current_base, detected_base in candidates:
            self.io.write(
                f"{project_id}: {current_base or 'UNKNOWN'} -> {detected_base} "
                f"({detected.get('base_description') or 'Project-declared base'})"
            )
        selected = self.io.choose(
            "UPDATE PROJECT VERSIFICATION",
            (
                ("1", "Use detected base VRS and retry"),
                ("B", "Back"),
            ),
        )
        if selected == "B":
            return False
        for project_id, detected, _current_base, detected_base in candidates:
            record = records[project_id]
            vrs = dict(record.get("versification") or {})
            vrs.update(
                {
                    "base_file": detected_base,
                    "custom_file": str(detected.get("file") or vrs.get("custom_file") or "auto"),
                    "name": detected.get("name"),
                    "reported_base_file": detected_base,
                    "base_selection": "PROJECT_DECLARED",
                    "base_description": detected.get("base_description"),
                    "metadata_status": detected.get("metadata_status"),
                }
            )
            update_project_record(self.root, project_id, {"versification": vrs})
            self.io.write(f"Updated {project_id}: base VRS = {detected_base}")
        invalidate_runtime_settings(self.root)
        self.io.write("Continuing Job validation with the approved versification settings.")
        return True

    def _show_job_readiness_summary(self, project: Job, state: dict[str, Any]) -> None:
        """Render bounded Job validation results instead of a full controller payload."""
        self.io.write()
        self.io.write(f"VALIDATE {project.tool.upper()} JOB - {project.job_id}")
        self.io.write("-" * 72)
        self.io.write(f"State:       {state.get('state', 'UNKNOWN')}")
        self.io.write(f"Capability:  {state.get('capability', 'UNKNOWN')}")
        projects = dict(state.get("projects") or {})
        for role, project_id in project.bindings.items():
            result = dict(projects.get(project_id) or {})
            issues = [dict(value) for value in result.get("issues", []) if isinstance(value, dict)]
            warnings = [dict(value) for value in result.get("warnings", []) if isinstance(value, dict)]
            vrs_advisories = [
                value for value in warnings
                if str(value.get("code") or "").upper() in VERSIFICATION_ADVISORY_CODES
            ]
            other_warnings = [value for value in warnings if value not in vrs_advisories]
            self.io.write(
                f"{role.upper():<11} {project_id}: {result.get('status', 'UNKNOWN')} "
                f"({len(issues)} blocking issues, {len(vrs_advisories)} VRS advisories, "
                f"{len(other_warnings)} other warnings)"
            )
            for issue in issues[:8]:
                reference = str(issue.get("reference") or "").strip()
                prefix = f"{reference}: " if reference else ""
                source_file = str(issue.get("file") or "").strip()
                source_label = f" [{Path(source_file).name}]" if source_file else ""
                self.io.write(
                    f"  - {issue.get('code', 'PROJECT_VALIDATION_FAILED')}: "
                    f"{prefix}{issue.get('message', 'Validation failed')}{source_label}"
                )
            if len(issues) > 8:
                self.io.write(f"  - ... {len(issues) - 8} more issues in the initialization report")
            for advisory in vrs_advisories[:8]:
                reference = str(advisory.get("reference") or "").strip()
                prefix = f"{reference}: " if reference else ""
                source_file = str(advisory.get("file") or "").strip()
                source_label = f" [{Path(source_file).name}]" if source_file else ""
                self.io.write(
                    f"  ~ {advisory.get('code', 'VERSIFICATION_ADVISORY')}: "
                    f"{prefix}{advisory.get('message', 'Versification difference')}{source_label}"
                )
            if len(vrs_advisories) > 8:
                self.io.write(
                    f"  ~ ... {len(vrs_advisories) - 8} more VRS advisories in the initialization report"
                )
        restrictions = [str(value) for value in state.get("restrictions", [])]
        if restrictions:
            self.io.write("Actions:")
            for value in restrictions:
                self.io.write(f"  - {value}")
        self.io.write(f"Next action: {state.get('next_action') or 'No further action required.'}")
        self.io.pause()

    def batch_menu(self, project: Job) -> None:
        """Implement `batch menu` in the deterministic terminal control flow."""
        self.io.write("Batch queues remain global definitions in ecosystem.yml, but each task executes in its selected SAW project.")
        config = load_ecosystem(project.runtime_settings_path)
        if config.evaluation_sets:
            for set_id, value in config.evaluation_sets.items():
                self.io.write(f"{set_id}: {len(value.entries)} sequential entries")
        else:
            self.io.write("No evaluation sets are registered.")
        self.io.pause()

    # ---------- Job management ----------

    def job_management_menu(self, tool: str) -> None:
        """List Jobs, choose the active Job, or open it for governed work."""
        while True:
            jobs = self.store.discover(tool, include_archived=True)
            active = self.store.active_job(tool)
            self.io.write()
            self.io.write(f"{tool.upper()} JOBS")
            self.io.write("-" * 72)
            if jobs:
                for job in jobs:
                    if active and job.job_id == active.job_id:
                        marker = " [ACTIVE]"
                    elif job.status != "ACTIVE":
                        marker = f" [{job.status}]"
                    else:
                        marker = ""
                    self.io.write(f"  - {job.job_id} - {job.display_name}{marker}")
            else:
                self.io.write(f"No {tool.upper()} Jobs exist.")
            open_label = (
                "Open active SAW Job" if tool == "saw" else "Open active BIC Job"
            )
            choice = self.io.choose(
                f"{tool.upper()} - {self.localizer.text('Job management')}",
                (("1", open_label), ("2", "Choose active Job"), ("3", "Add Job"),
                 ("4", "Job settings"), ("5", "Validate Job"),
                 ("6", "Archive Job"), ("7", "Remove Job"), ("B", "Back")),
            )
            if choice == "B": return
            if choice == "1":
                if active is None:
                    self.io.write(f"No active {tool.upper()} Job. Choose or add one first.")
                    self.io.pause()
                elif tool == "saw":
                    self._saw_job_menu(active)
                else:
                    self._bic_job_menu(active)
                continue
            if choice == "2":
                self.choose_job(tool)
                continue
            if choice == "3":
                self.create_job_wizard(tool)
                continue
            project = self.store.active_job(tool)
            if choice == "7":
                candidates = self.store.discover(tool, include_archived=True)
                if not candidates:
                    self.io.write(f"No {tool.upper()} Jobs exist.")
                    self.io.pause()
                    continue
                selected = self.io.choose("REMOVE JOB", [(str(i), f"{job.job_id}: {job.display_name}") for i, job in enumerate(candidates, 1)] + [("B", "Back")])
                if selected == "B": continue
                target = candidates[int(selected) - 1]
                runs = self.store.list_runs(target)
                self.io.write()
                self.io.write(f"REMOVE JOB - {target.job_id}")
                self.io.write("-" * 72)
                self.io.write("This deletes this SAGE Job and its Job-local Runs and reports.")
                self.io.write("SAGE Projects and Paratext Project files will NOT be deleted or modified.")
                self.io.write(f"Runs in this Job: {len(runs)}")
                if self.io.confirm(f"Remove Job {target.job_id}?", default=False):
                    self.store.remove_job(target)
                    self.io.write(f"Removed Job: {target.job_id}")
                    self.io.pause()
                continue
            if project is None:
                self.io.write(f"No active {tool.upper()} Job. Choose or add one first.")
                self.io.pause()
                continue
            if choice == "4":
                self._job_settings_menu(project)
            elif choice == "5": self.project_readiness(project)
            elif choice == "6":
                if self.io.confirm(f"Archive Job {project.job_id}?", default=False):
                    self.store.revise_job(project, status="ARCHIVED")
                    self.store.set_active_job(tool, None)
                    self.io.write("Job archived. Data was not deleted.")
                    self.io.pause()

    def _choose_secondary_reporting_language(
        self,
        *,
        role: str,
        project_language: str,
        operator_language: str,
        current: str | None,
    ) -> tuple[bool, str | None]:
        """Recommend the audience Project language while allowing another or no secondary."""
        while True:
            recommended = project_language != operator_language
            if role == "WIP":
                recommended_label = "Use WIP language [Recommended]"
            else:
                recommended_label = "Use TARGET language [Recommended]"
            options: list[tuple[str, str]] = []
            if recommended:
                options.append(("1", recommended_label))
            other_key = str(len(options) + 1)
            options.append((other_key, "Choose other language"))
            none_key = str(len(options) + 1)
            options.append((none_key, "No secondary reporting language"))
            options.append(("B", "Back"))
            recommendation_state = "[RECOMMENDED]" if recommended else "[SAME AS PRIMARY]"
            choice = self.io.choose(
                "CHOOSE SECONDARY REPORTING LANGUAGE",
                tuple(options),
                context=(
                    f"{role} language: {project_language} {recommendation_state}",
                    f"Primary report language: {operator_language}",
                ),
            )
            if choice == "B":
                return False, current
            if recommended and choice == "1":
                return True, project_language
            if choice == none_key:
                return True, None
            requested = self.io.text(
                "Other secondary reporting language",
                default=current if current and current != project_language else None,
                validator=lambda value: canonical_language_tag(
                    value,
                    "job secondary reporting language",
                ),
            )
            if requested == operator_language:
                self.show_error(
                    ValidationError(
                        "Job secondary reporting language must differ from its primary reporting language",
                        code="JOB_REPORTING_LANGUAGE_CONFLICT",
                    )
                )
                continue
            return True, requested

    def _job_settings_menu(self, project: Job) -> None:
        """Configure Job-owned primary and optional secondary report languages."""
        while True:
            project = self.store.load_job(project.job_id, tool=project.tool)
            primary = project.primary_report_language
            secondary = project.secondary_report_language
            self.io.write()
            self.io.write(f"JOB SETTINGS - {project.job_id}")
            self.io.write("-" * 72)
            self.io.write(f"Primary report language:   {primary} [JOB, REQUIRED]")
            self.io.write(f"Secondary report language: {secondary or 'NONE'} [JOB]")
            if secondary:
                self.io.write(
                    "Authority: the primary Job-language rendering governs; "
                    "the secondary is assistive and may contain ambiguity."
                )
                self.io.write(
                    "Cost and review: secondary output adds model usage and compilation time, "
                    "and requires more human review than a single-language report."
                )
            choice = self.io.choose(
                "Job settings",
                (
                    ("1", "Set secondary reporting language"),
                    ("2", "Clear secondary reporting language"),
                    ("3", "Set primary reporting language"),
                    ("4", "Show Job manifest"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            if choice == "4":
                self.io.write(project.manifest_path.read_text(encoding="utf-8"))
                self.io.pause()
                continue
            if choice == "3":
                config = load_ecosystem(self.store.settings_path)
                requested = canonical_language_tag(
                    self.io.text("Primary reporting language", default=primary),
                    "job primary reporting language",
                )
                if requested not in config.human_output.operator_language_policy.selectable():
                    self.show_error(
                        ValidationError(
                            f"Primary reporting language {requested} is not approved or enabled",
                            code="OPERATOR_LANGUAGE_NOT_CANDIDATE",
                            next_action="Enable the canonical tag in the Operator language policy first.",
                        )
                    )
                    continue
                if requested == secondary:
                    self.show_error(
                        ValidationError(
                            "Job primary and secondary reporting languages must differ",
                            code="JOB_REPORTING_LANGUAGE_CONFLICT",
                        )
                    )
                    continue
                project = self.store.revise_job(
                    project,
                    reporting={
                        "primary_language": requested,
                        "secondary_language": secondary,
                    },
                )
                self.io.write(f"Job primary reporting language saved: {requested}")
                self.io.pause()
                continue
            if choice == "2":
                project = self.store.revise_job(project, reporting={"secondary_language": None})
                self.io.write("Job secondary reporting language cleared.")
                self.io.pause()
                continue
            config = load_ecosystem(self.store.settings_path)
            audience_role = "WIP" if project.tool == "saw" else "TARGET"
            audience_binding = "wip" if project.tool == "saw" else "generated_target"
            audience_language = config.project(project.bindings[audience_binding]).language_code
            changed, requested = self._choose_secondary_reporting_language(
                role=audience_role,
                project_language=audience_language,
                operator_language=primary,
                current=secondary,
            )
            if not changed:
                continue
            project = self.store.revise_job(
                project,
                reporting={"secondary_language": requested},
            )
            self.io.write(f"Job secondary reporting language saved: {requested}")
            self.io.pause()

    def create_job_wizard(self, tool: str) -> None:
        """Create one Job by assigning roles to Projects already in the SAGE Project Inventory."""
        # The wizard deliberately resolves every binding before it asks JobStore to persist anything.
        if tool == "bic":
            source = self.choose_or_add_resource("CHOOSE BIC <SOURCE>", "CONTENT_SOURCE")
            if not source: return
            donor = self.choose_or_add_resource("CHOOSE BIC <DONOR>", "LEXICAL_DONOR")
            if not donor: return
            output = self.choose_or_add_resource("CHOOSE BIC <TARGET>", "GENERATED_TARGET")
            if not output: return
            self.io.write("The TARGET is the only Project that BIC may modify. All changes remain governed and auditable.")
            if not self.io.confirm(f"Use {output.project_id} as BIC TARGET?", default=False): return
            job_id = default_job_name("bic", output.project_id, source.project_id, donor.project_id)
            name = f"{source.project_id} via {donor.project_id} vocabulary to {output.project_id}"
            greek = active_ol_project_id(self.root, "GRK")
            hebrew = active_ol_project_id(self.root, "HEB")
            bindings = {"content_source": source.project_id, "lexical_donor": donor.project_id, "generated_target": output.project_id,
                        **({"original_language_greek": greek} if greek else {}), **({"original_language_hebrew": hebrew} if hebrew else {})}
            profiles: dict[str, str] = {}
            defaults = {"publication_enabled": True}
        else:
            output = self.choose_or_add_resource("CHOOSE SAW <WIP>", "WIP")
            if not output: return
            source = self.choose_or_add_resource("CHOOSE SAW <REFERENCE>", "REFERENCE")
            if not source: return
            job_id = default_job_name("saw", output.project_id, source.project_id)
            name = f"{output.project_id} analyzed against {source.project_id}"
            greek = active_ol_project_id(self.root, "GRK")
            hebrew = active_ol_project_id(self.root, "HEB")
            bindings = {"wip": output.project_id, "reference": source.project_id,
                        **({"original_language_greek": greek} if greek else {}), **({"original_language_hebrew": hebrew} if hebrew else {})}
            profiles = {}
            defaults = {}
        secondary_report_language: str | None = None
        while True:
            self.io.write()
            self.io.write(f"REVIEW {tool.upper()} JOB")
            self.io.write("=" * 72)
            if tool == "bic":
                self.io.write(f"{'SOURCE':<20}{source.project_id}")
                self.io.write(f"{'DONOR':<20}{donor.project_id}")
                self.io.write(f"{'TARGET':<20}{output.project_id}")
                self.io.write(f"{'TARGET access':<20}GOVERNED WRITE")
            else:
                self.io.write(f"{'WIP':<20}{output.project_id}")
                self.io.write(f"{'REFERENCE':<20}{source.project_id}")
            self.io.write(f"{'Job name':<20}{job_id}")
            self.io.write(
                f"{'Report languages':<20}"
                + load_ecosystem(self.store.settings_path).human_output.operator_language
                + (f" + {secondary_report_language}" if secondary_report_language else "")
            )
            if secondary_report_language:
                self.io.write()
                self.io.write("Primary Job-language rendering governs.")
                self.io.write("Secondary rendering is assistive and has lower,")
                self.io.write("unverified translation confidence.")
            choice = self.io.choose(
                "Create Job",
                (
                    ("1", "Create Job"),
                    ("2", "Change display name"),
                    ("3", "Set secondary reporting language"),
                    ("B", "Back"),
                ),
            )
            if choice == "B": return
            if choice == "2":
                name = self.io.text("Display name", default=name)
                continue
            if choice == "3":
                self.io.write(
                    "Secondary output adds model usage and compilation time and requires "
                    "more human review than a single-language report."
                )
                operator_language = load_ecosystem(
                    self.store.settings_path
                ).human_output.operator_language
                changed, requested = self._choose_secondary_reporting_language(
                    role="WIP" if tool == "saw" else "TARGET",
                    project_language=output.language_code,
                    operator_language=operator_language,
                    current=secondary_report_language,
                )
                if changed:
                    secondary_report_language = requested
                continue
            try:
                project = self.store.create_job(
                    tool=tool,
                    job_id=job_id,
                    display_name=name,
                    bindings=bindings,
                    profiles=profiles,
                    defaults=defaults,
                    secondary_report_language=secondary_report_language,
                )
                self.store.set_active_job(tool, project.job_id)
                self.io.write(f"Created and selected Job: {project.job_id}")
                self.io.pause()
                return
            except ValidationError as exc:
                if exc.code == "LANGUAGE_PROFILE_SELECTION_REQUIRED":
                    details = dict(exc.details or {})
                    candidates = [str(value) for value in details.get("candidates", [])]
                    if candidates:
                        selected = self.io.choose("CHOOSE LANGUAGE PROFILE FOR JOB ROLE", [(str(i), value) for i, value in enumerate(candidates, 1)] + [("B", "Back")])
                        if selected == "B": return
                        role = str(details.get("role", ""))
                        profiles["source_grammar" if role == "CONTENT_SOURCE" else "target_grammar"] = candidates[int(selected) - 1]
                        continue
                if exc.code == "LANGUAGE_PROFILE_NOT_CONFIGURED":
                    if self._maintain_missing_language_profile(exc):
                        continue
                self.show_error(exc)
                self.io.pause()
                return
            except SageError as exc:
                self.show_error(exc)
                self.io.pause()
                return

    @staticmethod
    def _grammar_roles_for_job_role(role: str) -> set[str]:
        """Return grammar-profile roles compatible with one Job binding role."""
        normalized = role.strip().upper()
        return {
            "CONTENT_SOURCE": {"CONTENT_SOURCE"},
            "GENERATED_TARGET": {"GENERATED_TARGET", "TARGET"},
            "WIP": {"WIP", "TARGET"},
        }.get(normalized, {normalized})

    def _grammar_profile_library(
        self,
        *,
        language: str | None = None,
        role: str | None = None,
    ) -> list[tuple[Path, Any]]:
        """Return valid, non-inactive grammar profiles already present in SAGE's profile library."""
        wanted_roles = self._grammar_roles_for_job_role(role) if role else None
        roots = (
            self.root / "system" / "config" / "profiles" / "grammar",
            storage_layout(self.root).resources_root / "grammar-profiles",
        )
        candidates: list[tuple[Path, Any]] = []
        seen: set[Path] = set()
        for library_root in roots:
            if not library_root.is_dir():
                continue
            for path in sorted(library_root.rglob("*.yml")):
                resolved = path.resolve()
                if resolved in seen:
                    continue
                try:
                    profile = load_grammar_profile(path)
                except SageError:
                    continue
                if profile.status == "INACTIVE":
                    continue
                if language and profile.language.casefold() != language.casefold():
                    continue
                if wanted_roles is not None and profile.role not in wanted_roles:
                    continue
                seen.add(resolved)
                candidates.append((path, profile))
        return candidates

    def _profile_is_configured(self, *, language: str, profile_id: str, path: Path) -> bool:
        """Return whether one exact profile file is already registered under a language selector."""
        config = load_ecosystem(self.store.settings_path)
        namespace = config.language_profiles.get(language)
        if namespace is None or namespace.profile_alias is not None:
            return False
        variant = namespace.variants.get(profile_id)
        return bool(variant is not None and variant.path.resolve() == path.resolve())

    def _has_compatible_grammar_profile(self, *, language: str, role: str) -> bool:
        """Return whether the ecosystem currently exposes a compatible profile for language/role."""
        config = load_ecosystem(self.store.settings_path)
        namespace = config.language_profiles.get(language)
        if namespace is None:
            return False
        wanted = self._grammar_roles_for_job_role(role)
        return any(variant.role in wanted for variant in namespace.variants.values())

    def _register_grammar_profile_path(
        self,
        path: Path,
        *,
        expected_language: str | None = None,
        expected_role: str | None = None,
    ) -> bool:
        """Register one validated grammar-profile YAML without rewriting Project or Job content."""
        source = path.expanduser().resolve()
        if not source.is_file():
            raise ValidationError(
                f"Grammar profile file not found: {source}",
                code="GRAMMAR_PROFILE_FILE_NOT_FOUND",
                next_action="Choose an existing grammar profile or provide a valid YAML profile file.",
            )
        profile = load_grammar_profile(source)
        if expected_language and profile.language.casefold() != expected_language.casefold():
            raise ValidationError(
                f"Grammar profile {profile.profile_id} is for {profile.language}, not {expected_language}",
                code="GRAMMAR_PROFILE_LANGUAGE_MISMATCH",
                next_action=f"Choose or add a grammar profile for {expected_language}.",
            )
        if expected_role and profile.role not in self._grammar_roles_for_job_role(expected_role):
            raise ValidationError(
                f"Grammar profile {profile.language}/{profile.profile_id} role {profile.role} is not compatible with {expected_role}",
                code="GRAMMAR_PROFILE_ROLE_MISMATCH",
                next_action=f"Choose or add a grammar profile compatible with {expected_role}.",
            )

        destination = source
        copied = False
        try:
            source.relative_to(self.root)
        except ValueError:
            destination = (
                storage_layout(self.root).resources_root / "grammar-profiles"
                / profile.language
                / f"{profile.profile_id}.yml"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if sha256_file(destination) != sha256_file(source):
                    raise ValidationError(
                        f"A different local grammar profile already exists at {destination}",
                        code="GRAMMAR_PROFILE_LOCAL_CONFLICT",
                        next_action="Use a different profile ID or review the existing local profile before replacing it.",
                    )
            else:
                shutil.copy2(source, destination)
                copied = True
            destination = destination.resolve()
            profile = load_grammar_profile(destination)

        raw, _override_path, _resolutions = load_effective_settings(self.store.settings_path)
        profile_rows = dict(raw.get("language_profiles") or {})
        existing = dict(profile_rows.get(profile.language) or {})
        if existing.get("profile_alias"):
            if copied:
                destination.unlink(missing_ok=True)
            raise ValidationError(
                f"Language {profile.language} is currently a profile alias and cannot also define variants",
                code="GRAMMAR_PROFILE_ALIAS_CONFLICT",
                next_action=f"Review the {profile.language} alias before adding a direct grammar profile.",
            )
        script = str(profile.raw.get("profile", {}).get("script") or "").strip()
        if not script:
            if copied:
                destination.unlink(missing_ok=True)
            raise ValidationError("Grammar profile script is missing", code="GRAMMAR_PROFILE_SCRIPT_MISSING")
        if existing.get("script") and str(existing.get("script")) != script:
            if copied:
                destination.unlink(missing_ok=True)
            raise ValidationError(
                f"Grammar profile script {script} conflicts with configured {profile.language} script {existing.get('script')}",
                code="GRAMMAR_PROFILE_SCRIPT_MISMATCH",
            )

        variants = dict(existing.get("variants") or {})
        relative = declare_governed_path(self.root, destination, "grammar profile")
        prior = variants.get(profile.profile_id)
        if prior:
            prior_file = str(dict(prior).get("file") or "")
            prior_role = str(dict(prior).get("role") or "").upper()
            prior_path = (
                resolve_declared_path(self.root, prior_file, "grammar profile")
                if prior_file
                else None
            )
            if prior_path == destination and prior_role == profile.role:
                return True
            if copied:
                destination.unlink(missing_ok=True)
            raise ValidationError(
                f"Grammar selector {profile.language}/{profile.profile_id} is already registered to a different profile",
                code="GRAMMAR_PROFILE_SELECTOR_CONFLICT",
                next_action="Review the configured selector instead of replacing it implicitly.",
            )

        variants[profile.profile_id] = {"file": relative, "role": profile.role}
        profile_rows[profile.language] = {"script": existing.get("script") or script, "variants": variants}
        raw["language_profiles"] = profile_rows
        try:
            write_local_settings(self.store.settings_path, {"language_profiles": profile_rows})
            load_ecosystem(self.store.settings_path)
        except SageError:
            if copied:
                destination.unlink(missing_ok=True)
            raise
        invalidate_runtime_settings(self.root)
        self.io.write(
            f"Updated local settings: language_profiles.{profile.language}.variants.{profile.profile_id}"
        )
        self.io.write(
            f"Grammar profile registered: {profile.language}/{profile.profile_id} "
            f"[{profile.role}; {profile.status}]"
        )
        return True

    def _choose_existing_grammar_profile(
        self,
        *,
        language: str | None = None,
        role: str | None = None,
    ) -> bool:
        """Choose and register one compatible profile already present in the SAGE profile library."""
        candidates = self._grammar_profile_library(language=language, role=role)
        if not candidates:
            qualifier = ""
            if language:
                qualifier += f" for {language}"
            if role:
                qualifier += f" as {role}"
            self.io.write(f"No existing grammar profiles are available{qualifier}.")
            return False
        options: list[tuple[str, str]] = []
        for index, (path, profile) in enumerate(candidates, 1):
            script = str(profile.raw.get("profile", {}).get("script") or "?")
            configured = self._profile_is_configured(
                language=profile.language,
                profile_id=profile.profile_id,
                path=path,
            )
            suffix = " [configured]" if configured else ""
            options.append((str(index), f"{profile.language:<12} [{script}]{suffix}"))
        options.append(("B", "Back"))
        selected = self.io.choose("Existing grammar profiles", options)
        if selected == "B":
            return False
        path, profile = candidates[int(selected) - 1]
        script = str(profile.raw.get("profile", {}).get("script") or "?")
        self.io.write()
        self.io.write("GRAMMAR PROFILE")
        self.io.write("=" * 72)
        self.io.write(f"{'Profile':<20}{profile.language}/{profile.profile_id}")
        self.io.write(f"{'Script':<20}{script}")
        self.io.write(f"{'Role':<20}{profile.role}")
        self.io.write(f"{'Status':<20}{profile.status.replace('PROJECT_REVIEW_REQUIRED', 'REVIEW REQUIRED')}")
        if self._profile_is_configured(language=profile.language, profile_id=profile.profile_id, path=path):
            self.io.write()
            self.io.write("Already configured; no changes needed.")
            self.io.pause()
            return False
        self.io.write()
        self.io.write("Registering changes ecosystem.yml only; Project and Job content is not rewritten.")
        if not self.io.confirm("Register this grammar profile?", default=True):
            return False
        return self._register_grammar_profile_path(
            path,
            expected_language=language,
            expected_role=role,
        )

    def _add_grammar_profile_from_file(
        self,
        *,
        language: str | None = None,
        role: str | None = None,
    ) -> bool:
        """Add a validated grammar-profile YAML file to the governed SAGE profile registry."""
        raw_path = normalize_operator_path(
            self.io.text("Grammar profile YAML file [Enter to cancel]", required=False)
        )
        if not raw_path:
            return False
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (self.root / path).resolve()
        profile = load_grammar_profile(path)
        self.io.write()
        self.io.write("GRAMMAR PROFILE REVIEW")
        self.io.write("-" * 72)
        self.io.write(f"Profile:   {profile.language}/{profile.profile_id}")
        self.io.write(f"Role:      {profile.role}")
        self.io.write(f"Status:    {profile.status}")
        self.io.write(f"SHA-256:   {profile.sha256}")
        if not self.io.confirm("Add this grammar profile to SAGE?", default=True):
            return False
        return self._register_grammar_profile_path(
            path,
            expected_language=language,
            expected_role=role,
        )

    def _show_configured_grammar_profiles(self) -> None:
        """Render a compact, script-aware configured grammar-profile inventory."""
        config = load_ecosystem(self.store.settings_path)
        self.io.write()
        self.io.write("CONFIGURED GRAMMAR PROFILES")
        self.io.write("=" * 72)
        self.io.write()
        self.io.write(f"{'Profile':<18}{'Script':<10}Status")
        self.io.write("-" * 72)
        rows = 0
        for language, namespace in sorted(config.language_profiles.items()):
            script = namespace.script or "?"
            if namespace.profile_alias is not None:
                self.io.write(f"{language:<18}{script:<10}ALIAS -> {namespace.profile_alias}")
                rows += 1
                continue
            if not namespace.variants:
                self.io.write(f"{language:<18}{script:<10}NOT CONFIGURED")
                rows += 1
                continue
            for variant_id, variant in sorted(namespace.variants.items()):
                profile = load_grammar_profile(
                    variant.path,
                    expected_profile_id=variant_id,
                    expected_language=namespace.profile_language,
                    expected_role=variant.role,
                )
                selector = language if len(namespace.variants) == 1 else f"{language}/{variant_id}"
                status = profile.status.replace("PROJECT_REVIEW_REQUIRED", "REVIEW REQUIRED")
                self.io.write(f"{selector:<18}{script:<10}{status}")
                rows += 1
        if rows == 0:
            self.io.write("No grammar profiles are configured.")

    def _validate_configured_grammar_profiles(self) -> bool:
        """Validate every configured profile binding against its executable profile schema."""
        config = load_ecosystem(self.store.settings_path)
        count = 0
        for language, namespace in sorted(config.language_profiles.items()):
            if namespace.profile_alias is not None:
                continue
            for variant_id, variant in sorted(namespace.variants.items()):
                load_grammar_profile(
                    variant.path,
                    expected_profile_id=variant_id,
                    expected_language=namespace.profile_language,
                    expected_role=variant.role,
                )
                count += 1
        self.io.write(f"Grammar profile validation: READY - {count} configured profile(s) validated.")
        return True

    def _build_guided_grammar_profile(
        self,
        *,
        language: str | None = None,
        role: str | None = None,
    ) -> bool:
        """Build one review-required regional grammar profile from a generic or derived starter."""
        tag = canonical_regional_language_tag(
            language or self.io.text(
                "Canonical language tag with region (example en-US)",
                validator=lambda value: canonical_regional_language_tag(value, "grammar profile language"),
            ),
            "grammar profile language",
        )
        config = load_ecosystem(self.store.settings_path)
        namespace = config.language_profiles.get(tag)
        if namespace is not None:
            script = namespace.script
        else:
            script = self.io.text(
                "Script code (ISO 15924, example Latn)",
                validator=lambda value: canonical_script_code(value, "grammar profile script"),
            )
        normalized_role = str(role or "").strip().upper()
        if not normalized_role:
            selected = self.io.choose(
                "PROFILE ROLE",
                (("1", "WIP / SAW review"), ("2", "CONTENT_SOURCE / BIC source"), ("3", "TARGET / generated target"), ("B", "Back")),
            )
            if selected == "B":
                return False
            normalized_role = {"1": "WIP", "2": "CONTENT_SOURCE", "3": "TARGET"}[selected]
        compatible = self._grammar_roles_for_job_role(normalized_role)
        profile_role = normalized_role if normalized_role in {"WIP", "CONTENT_SOURCE", "TARGET"} else sorted(compatible)[0]
        profile_id = {"WIP": "wip", "CONTENT_SOURCE": "source", "TARGET": "target"}.get(profile_role, profile_role.casefold().replace("_", "-"))

        self.io.write()
        self.io.write("BUILD LANGUAGE PROFILE")
        self.io.write("=" * 72)
        self.io.write(f"{'Language':<20}{tag}")
        self.io.write(f"{'Script':<20}{script}")
        self.io.write(f"{'Role':<20}{profile_role}")
        choice = self.io.choose(
            "Profile starting point",
            (("1", "Build generic governed starter"), ("2", "Derive from an existing profile"), ("B", "Back")),
        )
        if choice == "B":
            return False

        # Keep derivation explicit: copying another profile is an operator-selected starting point, never implicit language equivalence.
        derivation: dict[str, Any] | None = None
        if choice == "2":
            candidates = self._grammar_profile_library(role=normalized_role)
            if not candidates:
                self.io.write("No compatible existing profile is available; using the generic starter.")
                choice = "1"
            else:
                primary = tag.split("-", 1)[0]
                candidates.sort(key=lambda item: (item[1].language.split("-", 1)[0] != primary, item[1].language, item[1].profile_id))
                options = [
                    (
                        str(i),
                        f"{profile.language:<12} [{str(profile.raw.get('profile', {}).get('script') or '?')}]",
                    )
                    for i, (_path, profile) in enumerate(candidates, 1)
                ] + [("B", "Back")]
                selected = self.io.choose("DERIVE FROM PROFILE", options)
                if selected == "B":
                    return False
                source_path, source_profile = candidates[int(selected) - 1]
                raw_profile = load_yaml_compat(source_path)
                raw_profile = dict(raw_profile)
                profile_meta = dict(raw_profile.get("profile") or {})
                profile_meta.update({
                    "schema_version": "2.0",
                    "id": profile_id,
                    "language": tag,
                    "script": script,
                    "role": profile_role,
                    "status": "PROJECT_REVIEW_REQUIRED",
                    "purpose": f"guided_derivation_{tag.casefold().replace('-', '_')}_{profile_id}",
                    "owner_role": "PROJECT_TEAM",
                    "last_reviewed": None,
                })
                raw_profile["profile"] = profile_meta
                prefix = "".join(ch for ch in tag.upper() if ch.isalnum())
                checks = []
                for index, row in enumerate(list(raw_profile.get("checks") or []), 1):
                    item = dict(row)
                    item["id"] = f"{prefix}-GR-{index:03d}"
                    checks.append(item)
                raw_profile["checks"] = checks
                raw_profile["project_decisions"] = []
                raw_profile["approved_exceptions"] = []
                raw_profile["provenance"] = {
                    "type": "SAGE_GUIDED_DERIVATION",
                    "project_validated": False,
                    "source_profile": f"{source_profile.language}/{source_profile.profile_id}",
                }
                derivation = {
                    "mode": "OPERATOR_SELECTED_DERIVATION",
                    "parent_language_profile": source_profile.language,
                    "parent_variant": source_profile.profile_id,
                    "review_required": True,
                }
                raw_profile["derivation"] = derivation
        if choice == "1":
            prefix = "".join(ch for ch in tag.upper() if ch.isalnum())
            checks = [
                ("meaning", "Check that the bounded wording preserves the complete proposition and logical relation.", "Report uncertainty; do not approve or rewrite automatically."),
                ("participant_reference", "Check explicit and implicit participant references across the bounded discourse unit.", "Do not infer an antecedent that the project evidence does not support."),
                ("morphology_and_agreement", "Check language-relevant morphology and agreement where they affect interpretation or naturalness.", "Treat plausible alternatives as project-review questions when evidence does not decide between them."),
                ("verb_form", "Check tense, aspect, mood, voice, polarity, agreement, and auxiliary choices in context.", "Do not replace a form merely because another form is more frequent outside the project."),
                ("word_order_and_information_structure", "Check constituent order against focus, emphasis, quotation structure, and discourse flow.", "Treat marked order as potentially meaningful until Project Team review resolves it."),
                ("clause_structure", "Check coordination, subordination, negation, ellipsis, and clause linkage for grammatical coherence.", "Preserve logical and quotation boundaries; do not normalize them silently."),
                ("terminology_and_lexical_form", "Check Project terminology, lexical forms, register, and consistency within the bounded scope.", "Project-approved terminology takes precedence over general-language preference."),
                ("orthography_and_punctuation", f"Check {tag} orthography, script conventions, spacing, capitalization, and punctuation against Project usage.", "This generic starter requires Project Team review and must not invent language-specific rules."),
            ]
            raw_profile = {
                "profile": {
                    "schema_version": "2.0", "id": profile_id, "language": tag, "script": script,
                    "role": profile_role, "status": "PROJECT_REVIEW_REQUIRED",
                    "purpose": f"guided_generic_{tag.casefold().replace('-', '_')}_{profile_id}",
                    "owner_role": "PROJECT_TEAM", "last_reviewed": None,
                },
                "checks": [
                    {"id": f"{prefix}-GR-{index:03d}", "dimension": dimension, "review": review, "caution": caution}
                    for index, (dimension, review, caution) in enumerate(checks, 1)
                ],
                "normalization": {"unicode": "NFC", "preserve_script": True},
                "project_decisions": [], "approved_exceptions": [],
                "governance": {"authority": "project_team_required", "human_approval_required": True},
                "evidence_priority": ["bounded_project_text", "approved_project_decisions", "declared_contemporary_source", "relevant_original_language_source"],
                "usage": {"apply_to": ["rtc", "focused", "ol"], "report_rule_ids": True},
                "finding_requirements": ["Cite each applicable rule ID.", "Separate grammar findings from general meaning findings."],
                "restrictions": ["Do not invent project rules.", "Do not promote this starter profile to approved Project grammar without human review."],
                "provenance": {"type": "SAGE_GUIDED_STARTER", "project_validated": False},
            }

        destination = storage_layout(self.root).resources_root / "grammar-profiles" / tag / f"{profile_id}.yml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValidationError(
                f"A local grammar profile already exists at {destination}",
                code="GRAMMAR_PROFILE_LOCAL_CONFLICT",
                next_action="Review the existing local profile or choose a different selector.",
            )
        atomic_write_text(destination, yaml_dump_compat(raw_profile))
        try:
            load_grammar_profile(destination, expected_profile_id=profile_id, expected_language=tag, expected_role=profile_role)
            if not self.io.confirm("Register this review-required profile?", default=True):
                destination.unlink(missing_ok=True)
                return False
            return self._register_grammar_profile_path(destination, expected_language=tag, expected_role=normalized_role)
        except SageError:
            destination.unlink(missing_ok=True)
            raise

    def maintain_grammar_profiles(
        self,
        *,
        language: str | None = None,
        role: str | None = None,
        missing_error: ValidationError | None = None,
        return_on_change: bool = False,
    ) -> bool:
        """Maintain grammar profiles through one stable, contiguous Operator menu."""
        while True:
            context: list[str] = []
            if language:
                context.append(f"Required language: {language}")
            if role:
                context.append(f"Required Job role: {role}")
            choice = self.io.choose(
                "MAINTAIN GRAMMAR PROFILES",
                (
                    ("1", "Choose from existing profile list"),
                    ("2", "Add grammar profile from YAML file"),
                    ("3", "Show configured grammar profiles"),
                    ("4", "Validate grammar profiles"),
                    ("5", "Build guided regional profile"),
                    ("B", "Back"),
                ),
                context=tuple(context),
            )
            if choice == "B":
                return False
            try:
                changed = False
                if choice == "1":
                    changed = self._choose_existing_grammar_profile(language=language, role=role)
                elif choice == "2":
                    changed = self._add_grammar_profile_from_file(language=language, role=role)
                elif choice == "3":
                    self._show_configured_grammar_profiles()
                    self.io.pause()
                elif choice == "4":
                    self._validate_configured_grammar_profiles()
                    self.io.pause()
                elif choice == "5":
                    changed = self._build_guided_grammar_profile(language=language, role=role)
                if changed:
                    if language and role and not self._has_compatible_grammar_profile(language=language, role=role):
                        self.io.write(
                            f"The change did not configure a {language} grammar profile compatible with {role}."
                        )
                        continue
                    if return_on_change:
                        return True
                    self.io.pause()
            except SageError as exc:
                self.show_error(exc)
                self.io.pause()

    def _maintain_missing_language_profile(self, exc: ValidationError) -> bool:
        """Route every missing-language setup through the reusable grammar-profile maintenance menu."""
        details = dict(exc.details or {})
        language = str(details.get("language") or "").strip()
        role = str(details.get("role") or "").strip().upper()
        if not language or not role:
            return False
        self.io.write()
        self.io.write("GRAMMAR PROFILE REQUIRED")
        self.io.write("-" * 72)
        self.io.write(f"Language: {language}")
        self.io.write(f"Job role: {role}")
        self.io.write(
            "Choose an existing compatible profile or add a grammar-profile YAML file. "
            "SAGE will retry setup only after a compatible profile is configured."
        )
        return self.maintain_grammar_profiles(
            language=language,
            role=role,
            missing_error=exc,
            return_on_change=True,
        )

    def _offer_packaged_language_profile(self, exc: ValidationError) -> bool:
        """Offer one packaged role-compatible grammar profile to an existing ecosystem."""
        details = dict(exc.details or {})
        language = str(details.get("language") or "").strip()
        role = str(details.get("role") or "").strip().upper()
        if not language or not role:
            return False

        wanted = {
            "CONTENT_SOURCE": {"CONTENT_SOURCE"},
            "GENERATED_TARGET": {"GENERATED_TARGET", "TARGET"},
            "WIP": {"WIP", "TARGET"},
        }.get(role, {role})
        grammar_root = self.root / "system" / "config" / "profiles" / "grammar" / language
        if not grammar_root.is_dir():
            return False

        candidates: list[tuple[Path, Any]] = []
        for path in sorted(grammar_root.glob("*.yml")):
            try:
                profile = load_grammar_profile(path, expected_language=language)
            except SageError:
                continue
            if profile.role in wanted and profile.status != "INACTIVE":
                candidates.append((path, profile))
        if not candidates:
            return False

        if len(candidates) == 1:
            path, profile = candidates[0]
        else:
            options = [
                (str(index), f"{profile.profile_id} [{profile.role}; {profile.status}]")
                for index, (_, profile) in enumerate(candidates, 1)
            ]
            options.append(("B", "Back"))
            selected = self.io.choose("CHOOSE LANGUAGE PROFILE FOR JOB ROLE", options)
            if selected == "B":
                return False
            path, profile = candidates[int(selected) - 1]

        config = load_ecosystem(self.store.settings_path)
        namespace = config.language_profiles.get(language)
        if namespace is not None and profile.profile_id in namespace.variants:
            return True
        if namespace is not None and namespace.profile_alias is not None:
            return False

        relative = path.resolve().relative_to(self.root).as_posix()
        script = str(profile.raw.get("profile", {}).get("script") or "").strip()
        if not script:
            return False

        self.io.write()
        self.io.write("LANGUAGE PROFILE SETUP")
        self.io.write("-" * 72)
        self.io.write(f"Language:          {language}")
        self.io.write(f"Job role:          {role}")
        self.io.write(f"Packaged profile:  {language}/{profile.profile_id} [{profile.status}]")
        self.io.write(
            "SAGE includes a role-compatible starter but this existing ecosystem does not "
            "register it. Registering it changes only local localdata settings; Project and Job content "
            "is not rewritten."
        )
        selected = self.io.choose(
            "UPDATE ECOSYSTEM LANGUAGE PROFILES",
            (
                ("1", f"Register {language}/{profile.profile_id} and retry Job creation"),
                ("B", "Back"),
            ),
        )
        if selected == "B":
            return False

        raw, _override_path, _resolutions = load_effective_settings(self.store.settings_path)
        profile_rows = dict(raw.get("language_profiles") or {})
        existing = dict(profile_rows.get(language) or {})
        if existing.get("profile_alias"):
            return False
        variants = dict(existing.get("variants") or {})
        variants[profile.profile_id] = {"file": relative, "role": profile.role}
        profile_rows[language] = {"script": existing.get("script") or script, "variants": variants}
        raw["language_profiles"] = profile_rows
        write_local_settings(self.store.settings_path, {"language_profiles": profile_rows})
        load_ecosystem(self.store.settings_path)
        self.io.write(
            f"Updated local settings: language_profiles.{language}.variants.{profile.profile_id}"
        )
        self.io.write("Retrying Job creation with the packaged profile.")
        return True

    def choose_resource(self, title: str, resources: Sequence[Any]) -> Any | None:
        """Choose one already-authorized resource for a bounded operator selection."""
        if not resources:
            self.io.write(f"No resources are authorized for {title.lower()}.")
            self.io.pause()
            return None
        options = [
            (str(index), f"{item.project_id} - {item.language_code} [{item.content_state}]")
            for index, item in enumerate(resources, 1)
        ]
        options.append(("B", "Back"))
        choice = self.io.choose(title, options)
        return None if choice == "B" else resources[int(choice) - 1]

    def choose_registered_project_id(self, title: str, *, language_codes: set[str] | None = None) -> str:
        """Choose one SAGE Project from the Project Inventory instead of typing its ID."""
        config = load_ecosystem(self.store.settings_path)
        inventory = registered_project_records(self.root)
        values = [p for p in config.projects.values() if p.project_id in inventory and (language_codes is None or p.language_code in language_codes)]
        values.sort(key=lambda item: item.project_id.casefold())
        if not values:
            qualifier = " for the required language" if language_codes else ""
            raise ValidationError(f"No SAGE Projects are available{qualifier}", code="PROJECT_INVENTORY_EMPTY",
                                  next_action="Add the Paratext Project under Scripture Projects > Add Projects to SAGE, then retry.")
        options = [
            (str(i), f"{item.project_id}: {inventory[item.project_id].get('display_name', item.project_id)}, {item.language_code} [{inventory[item.project_id].get('scope_summary', 'UNKNOWN')}]")
            for i, item in enumerate(values, 1)
        ]
        choice = self.io.choose(title, options)
        return values[int(choice)-1].project_id

    def _resource_eligible_for_role(self, project: Any, role: str) -> bool:
        """Return whether a role-neutral SAGE Project can be considered for one Job role."""
        role = role.strip().upper()
        if role == "ORIGINAL_LANGUAGE_GREEK": return project.content_state == "LOCKED" and project.language_code == "grc"
        if role == "ORIGINAL_LANGUAGE_HEBREW": return project.content_state == "LOCKED" and project.language_code == "hbo"
        return role in {"CONTENT_SOURCE", "LEXICAL_DONOR", "REFERENCE", "WIP", "GENERATED_TARGET"} and project.language_code not in {"grc", "hbo"}

    def choose_or_add_resource(self, title: str, role: str) -> Any | None:
        """Assign a Job role only from SAGE Projects; addition is a temporary system detour."""
        while True:
            config = load_ecosystem(self.store.settings_path)
            inventory = registered_project_records(self.root)
            resources = [p for p in config.projects.values() if p.project_id in inventory and self._resource_eligible_for_role(p, role)]
            resources.sort(key=lambda item: item.project_id.casefold())
            options = [
                (str(i), f"{item.project_id:<9} {str(inventory[item.project_id].get('display_name', item.project_id))[:38]:<38} {item.language_code}")
                for i, item in enumerate(resources, 1)
            ]
            add_key = str(len(options) + 1)
            options.extend(((add_key, "Add another Project to SAGE"), ("B", "Back")))
            choice = self.io.choose(title, options)
            if choice == "B": return None
            if choice == add_key:
                self.discover_register_projects_menu(return_on_register=True)
                continue
            return resources[int(choice)-1]

    def _ensure_project_root(self) -> Path | None:
        """Return the configured primary Paratext/PTLite projects root."""
        state = load_resource_mount_state(self.root)
        primary = state.get("projects_root")
        if primary:
            return Path(primary)
        self.io.write("No primary Paratext Projects root is configured yet.")
        if not self.io.confirm("Configure the primary Projects root now?", default=True):
            return None
        value = Path(normalize_operator_path(self.io.text("Paratext Projects root"))).expanduser()
        try:
            set_project_root(self.root, project_root=value, progress=self._scan_progress)
        finally:
            self.io.clear_status()
        return value.resolve()

    def register_resource_from_project_root(self, role: str | None = None) -> str | None:
        """Compatibility entry point: add a Project to SAGE without assigning a Job role."""
        return self.discover_register_projects_menu(return_on_register=True)

    def unique_resource(self, config: Any, role: str) -> str:
        """Implement `unique resource` in the deterministic terminal control flow."""
        values = [project.project_id for project in config.projects.values() if self._resource_eligible_for_role(project, role)]
        if len(values) != 1:
            raise ValidationError(f"Expected one configured resource with role {role}; found {len(values)}")
        return values[0]

    # ---------- Help/global ----------

    def help_menu(self) -> None:
        """Show the small fallback documentation set retained for support and recovery."""
        self._show_support_docs()

    def system_recovery_menu(self) -> None:
        """Expose system recovery without mixing in BIC/SAW Job recovery actions."""
        while True:
            from . import __version__
            config = load_ecosystem(self.store.settings_path)
            choice = self.io.choose(
                "SYSTEM RECOVERY AND DIAGNOSTICS",
                (
                    ("1", "Export global diagnostics"),
                    ("2", "Clear active Job and Run selections"),
                    ("3", "Recovery guides"),
                    ("4", "Reset SAGE to out-of-box state"),
                    ("B", "Back"),
                ),
                context=(
                    "SYSTEM INFORMATION",
                    f"{'SAGE':<28}{__version__}",
                    f"{'Platform':<28}{sys.platform}",
                    f"{'Python':<28}{sys.version.split()[0]}",
                    f"{'Installation':<28}{self.root}",
                    "",
                    "SAGE DATA FOLDERS",
                    f"{'Settings':<28}{self.store.settings_path}",
                    f"{'Scripture resources':<28}{config.projects_root}",
                    f"{'localdata':<28}{config.data_root}",
                    f"{'State':<28}{self.store.state_root}",
                    f"{'Project inventory':<28}{storage_layout(self.root).state_root / 'project-inventory.json'}",
                    f"{'Resource mappings':<28}{storage_layout(self.root).state_root / 'resource-mounts.json'}",
                    f"{'BIC Jobs':<28}{self.store.tool_root('bic')}",
                    f"{'SAW Jobs':<28}{self.store.tool_root('saw')}",
                    f"{'Reports':<28}{storage_layout(self.root).reports_root}",
                    f"{'Setup state':<28}{self.store.setup_state_path}",
                    f"{'Last Run':<28}{self.store.last_run_path}",
                    f"{'Operator cues':<28}{self.store.operator_cues_path}",
                    "",
                    "Use BIC/SAW Recovery and diagnostics for Job or Run recovery.",
                    "Use the system actions below for installation-wide maintenance.",
                ),
                option_heading="SYSTEM ACTIONS",
            )
            if choice == "B":
                return
            if choice == "1":
                self.export_global_diagnostics()
            elif choice == "2":
                if self.io.confirm("Clear active job and last-run pointers? Job data will remain.", default=False):
                    self.store.active_jobs_path.unlink(missing_ok=True)
                    self.store.last_run_path.unlink(missing_ok=True)
                    self.store.record_cue("GLOBAL_POINTERS_RESET")
            elif choice == "3":
                self._show_support_docs()
            elif choice == "4":
                self.io.write()
                self.io.write("OUT-OF-BOX RESET")
                self.io.write("=" * 72)
                self.io.write("This permanently removes all Projects, Jobs, Runs, reports, caches,")
                self.io.write("local profiles, Operator settings, and generated workspace data.")
                self.io.write("The managed localdata runtime and packaged SAGE Core resources are preserved.")
                if not self.io.confirm("Reset this SAGE installation to out-of-box state?", default=False):
                    continue
                typed = self.io.text("Type RESET SAGE to confirm")
                if typed != "RESET SAGE":
                    self.io.write("Out-of-box reset cancelled; confirmation text did not match.")
                    continue
                result = reset_to_out_of_box(self.root)
                self.io.write(f"Out-of-box reset complete: {result['receipt_path']}")
                self.io.write("SAGE will exit. Relaunch SAGE to begin first-use Setup.")
                raise MenuExitRequested()

    def _model_connect_chatgpt(self, service: ModelService) -> None:
        """Offer browser or device-code ChatGPT sign-in through Codex CLI, then verify readiness."""
        choice = self.io.choose(
            "Connect OpenAI and ChatGPT",
            (
                ("1", "Browser sign-in [recommended]"),
                ("2", "Device-code sign-in"),
                ("B", "Back"),
            ),
        )
        if choice == "B":
            return
        self.io.write("SAGE will run the local Codex CLI sign-in. No OpenAI API key is used or accepted.")
        result = service.connect_chatgpt(device_auth=(choice == "2"))
        self.io.write("OpenAI and ChatGPT: CONNECTED")
        self.io.write("Returned to SAGE. Codex was used only for sign-in; its interactive shell was not started.")
        self.io.write("Transport: local Codex CLI; Codex desktop app not required")
        if result.get("account_plan_type"):
            self.io.write(f"ChatGPT plan or workspace: {result['account_plan_type']}")
        self.io.write(f"Live models available: {result['model_count']}")
        self.io.write("Model routing: SAGE automatic task policy")
        live = self._setup_model_probe(service, refresh=True)
        if live.get("ready"):
            self.io.write(f"Connected model: {live.get('model') or 'provider default'}")
            self.io.write(f"Reasoning level: {live.get('reasoning_level') or 'provider default'}")

    def _model_show_status(self, service: ModelService) -> None:
        """Render enabled-provider readiness without repeating disabled future-provider noise."""
        result = service.status()
        self.io.write(f"Selected provider: {result['selected_provider']}")
        disabled: list[str] = []
        for row in result["providers"]:
            if "build_disabled" in set(row.get("capabilities") or ()):
                disabled.append(row["provider"])
                continue
            marker = " *" if row["provider"] == result["selected_provider"] else ""
            self.io.write(f"{row['provider']}{marker}: {'READY' if row['ready'] else 'NOT READY'}")
            if row.get("auth_mode"):
                self.io.write(f"  ChatGPT: {row['auth_mode']}")
            if row.get("selected_model"):
                self.io.write(f"  model: {row['selected_model']}")
            if row.get("selected_reasoning_effort"):
                self.io.write(f"  reasoning: {row['selected_reasoning_effort']}")
            self.io.write(f"  {row.get('diagnostic', '')}")
        if disabled:
            self.io.write(f"Other provisionable providers disabled by this build: {', '.join(disabled)}")

    def _local_admin_status_lines(self, status: OllamaAdminStatus) -> tuple[str, ...]:
        """Return the compact operator configuration shown in the Local AI menu."""
        return (
            f"{'Local AI':<22}{'ENABLED' if status.enabled else 'DISABLED'}",
            f"{'Model':<22}{status.model} - "
            f"{'INSTALLED' if status.model_installed else 'NOT INSTALLED'}",
        )

    def _ollama_progress(self, done: int, total: int) -> None:
        """Render bounded installer/model download progress."""
        if total:
            percent = min(100.0, done * 100.0 / total)
            self.io.status(
                f"Downloading... {percent:5.1f}% "
                f"({done / 1024**3:.2f}/{total / 1024**3:.2f} GiB)"
            )
        else:
            self.io.status(f"Downloading... {done / 1024**2:.1f} MiB")

    def local_ai_models_menu(self) -> None:
        """Manage the configured Local AI model through an extensible model surface."""
        while True:
            status = self.ollama_admin.status()
            install_label = (
                "Reinstall configured model" if status.model_installed else "Install configured model"
            )
            choice = self.io.choose(
                "CONFIGURE LOCAL AI MODELS",
                (("1", install_label), ("B", "Back")),
                context=(
                    f"{'Configured model':<22}{status.model}",
                    f"{'Installation':<22}"
                    f"{'INSTALLED' if status.model_installed else 'NOT INSTALLED'}",
                    f"{'Source':<22}{SAGE_LOCAL_ADMIN_SOURCE_REPOSITORY}",
                    f"{'Revision':<22}{SAGE_LOCAL_ADMIN_SOURCE_REVISION}",
                    f"{'Integrity':<22}SHA-256 {SAGE_LOCAL_ADMIN_SOURCE_SHA256}",
                ),
                option_heading="MODEL ACTIONS",
            )
            if choice == "B":
                return
            self.io.write(
                f"Download: approximately {SAGE_LOCAL_ADMIN_SOURCE_BYTES / 1000**3:.2f} GB; "
                "temporary import space: 10 GiB."
            )
            if self.io.confirm(
                "Download, hash-verify, and import the governed Q5_K_M model?",
                default=False,
            ):
                try:
                    self.ollama_admin.install_model(self._ollama_progress)
                finally:
                    self.io.clear_status()
                self.io.write("Governed Gemma 4 E2B model installed and verified.")

    def local_admin_assistant_menu(self) -> None:
        """Configure Local AI and refresh its displayed state after every action."""
        while True:
            status = self.ollama_admin.status()
            service_label = "Stop Ollama" if status.service_running else "Start Ollama"
            enable_label = "Disable Local AI" if status.enabled else "Enable Local AI"
            actions: list[tuple[str, str, str]] = [("1", enable_label, "enable")]
            if not status.installed and not status.service_running:
                actions.append(("2", "Install Ollama on this host", "install"))
            else:
                actions.append(("2", service_label, "service"))
            actions.extend((("3", "Manage Local AI models", "models"), ("4", "Test Local AI", "test")))
            actions.append(("B", "Back", "back"))
            choice = self.io.choose(
                "CONFIGURE LOCAL AI",
                tuple((key, label) for key, label, _action in actions),
                context=self._local_admin_status_lines(status),
                option_heading="LOCAL AI ACTIONS",
            )
            action = next(action for key, _label, action in actions if key == choice)
            if action == "back":
                return
            try:
                if action == "install":
                    if status.installed:
                        self.io.write("Ollama is already installed on this host.")
                    elif self.io.confirm(
                        "Download and run the official Ollama installer for this operating system?",
                        default=False,
                    ):
                        try:
                            result = self.ollama_admin.install_runtime(self._ollama_progress)
                        finally:
                            self.io.clear_status()
                        self.io.write(json.dumps(result, indent=2, ensure_ascii=False))
                elif action == "service":
                    if status.service_running:
                        if status.service_ownership != "SAGE_MANAGED":
                            self.io.write(
                                "This Ollama service is external. SAGE will not stop a service it does not own."
                            )
                            self.io.write("Stop it from the Ollama tray application or operating-system service.")
                        elif self.io.confirm("Stop the SAGE-managed Ollama service?", default=True):
                            self.ollama_admin.stop()
                    else:
                        self.ollama_admin.start()
                elif action == "enable":
                    self.ollama_admin.enable(not status.enabled)
                elif action == "models":
                    self.local_ai_models_menu()
                elif action == "test":
                    result = self.ollama_admin.test()
                    self.io.write(json.dumps(result, indent=2, ensure_ascii=False))
                self.io.pause()
            except SageError as exc:
                self.show_error(exc)

    def _model_show_codex_catalog(self, service: ModelService) -> None:
        """Render the live provider catalog as read-only capability information."""
        result = service.list_models("codex")
        if not result["models"]:
            self.io.write(result.get("diagnostic", "No live Codex catalog is available."))
        for row in result["models"]:
            selected = " *" if row.get("selected") else ""
            self.io.write(f"{row.get('display_name') or row['model']} [{row['model']}]{selected}")
            efforts = row.get("reasoning_efforts") or []
            self.io.write(f"  reasoning: {', '.join(efforts) if efforts else 'provider default only'}")
            approved = row.get("qualified_skill_routes") or []
            labels = [
                f"{item['skill_id']}:{item['reasoning_id']}"
                for item in approved
                if isinstance(item, dict)
            ]
            self.io.write(f"  Qualified Skills: {', '.join(labels) if labels else 'none'}")
            provisional = row.get("provisional_skill_routes") or []
            provisional_labels = [
                f"{item['skill_id']}:{item['reasoning_id']}"
                for item in provisional
                if isinstance(item, dict)
            ]
            if provisional_labels:
                self.io.write(f"  Provisional Skills: {', '.join(provisional_labels)}")

    def _model_show_recommendation_status(self, service: ModelService) -> None:
        """Render exact per-Skill availability and qualification independently."""
        result = service.skill_routes()
        self.io.write(f"Routing mode: {result.get('routing_mode') or 'AUTOMATIC'}")
        self.io.write(f"{'SKILL':<32}{'PROVIDER':<12}{'MODEL':<20}{'REASONING':<14}STATUS")
        self.io.write("-" * 96)
        for row in result.get("skills", []):
            status = str(row.get("qualification") or "UNASSESSED")
            availability = str(row.get("availability") or "UNKNOWN")
            self.io.write(
                f"{str(row.get('skill_id') or ''):<32}"
                f"{str(row.get('provider') or '—'):<12}"
                f"{str(row.get('model_id') or '—'):<20}"
                f"{str(row.get('reasoning_id') or '—'):<14}"
                f"{status} / {availability}"
            )

    def _model_routing_override_menu(self, service: ModelService) -> None:
        """Inspect, clear, or set the explicitly advanced exact-route override."""
        state = service.routing_override_status()
        self.io.write(f"Routing mode: {state['routing_mode']}")
        override = state.get("override")
        if isinstance(override, dict):
            selection = dict(override.get("selection") or {})
            self.io.write(
                "Override: "
                f"{selection.get('provider')} / {selection.get('model_id')} / "
                f"{selection.get('reasoning_id')}"
            )
            self.io.write(
                f"Qualified Skill coverage: {override.get('qualified_skill_count', 0)}/"
                f"{override.get('registered_skill_count', 0)}"
            )
        choice = self.io.choose(
            "Advanced routing override",
            (("1", "Set qualified exact route"), ("2", "Clear override"), ("B", "Back")),
        )
        if choice == "B":
            return
        if choice == "2":
            cleared = service.clear_global_override()
            self.io.write(f"Routing mode: {cleared['routing_mode']}")
            return
        catalog = service.list_models("codex")
        candidates: list[dict[str, Any]] = []
        for model_row in catalog.get("models", []):
            for route_row in model_row.get("qualified_skill_routes", []):
                candidates.append(
                    {
                        "provider": "codex",
                        "model_id": model_row.get("model"),
                        "capability_fingerprint": model_row.get("capability_fingerprint"),
                        "reasoning_id": route_row.get("reasoning_id"),
                    }
                )
        unique = {
            (
                row["provider"], row["model_id"], row["capability_fingerprint"], row["reasoning_id"]
            ): row
            for row in candidates
        }
        rows = list(unique.values())
        if not rows:
            raise ValidationError(
                "No currently qualified exact route is available for override",
                code="GLOBAL_OVERRIDE_NO_QUALIFIED_SKILLS",
            )
        selected = self.io.choose(
            "Qualified routes",
            tuple(
                (
                    str(index),
                    f"{row['provider']} / {row['model_id']} / {row['reasoning_id']}",
                )
                for index, row in enumerate(rows, 1)
            ),
        )
        if not self.io.confirm("Apply this global route override?", default=False):
            return
        result = service.set_global_override(rows[int(selected) - 1])
        self.io.write(
            f"Override enabled for {result['qualified_skill_count']}/"
            f"{result['registered_skill_count']} registered Skills."
        )

    def _model_test_selected(self, service: ModelService) -> dict[str, Any]:
        """Run and return the explicit structured connectivity test for the selected provider."""
        if self.dry_run_provider:
            result = self._setup_model_probe(service, refresh=True)
        else:
            tested = service.connectivity_test(timeout_seconds=120)
            preflight = service.quick_codex_status()
            provider_id = str(tested.get("provider") or "codex")
            status = AIStatus(
                connection="READY",
                provider_id=provider_id,
                provider="OpenAI / ChatGPT" if provider_id == "codex" else provider_id,
                model=str(tested.get("model") or "PROVIDER DEFAULT"),
                reasoning_level=str(tested.get("reasoning_effort") or "PROVIDER DEFAULT").upper(),
                prerequisite_status="READY",
                last_checked=utc_now(),
                available=True,
                ready=True,
                auth_mode=preflight.get("auth_mode"),
                version=preflight.get("version"),
            )
            self.runtime_status.ai = status
            result = status.to_dict()
        return result

    def _model_show_policy(self, service: ModelService) -> None:
        """Render provider-neutral qualification and recommendation policy."""
        policy = service.policy()
        self.io.write(f"Qualification policy: {policy['qualification_policy_version']}")
        self.io.write("Accepted: " + ", ".join(policy["accepted_operational_statuses"]))
        self.io.write("Recommendation: " + " → ".join(policy["recommendation_order"]))
        self.io.write("Skills: " + ", ".join(policy["skill_routes"]))

    def _write_language_competency_evidence(self, result: dict[str, Any]) -> None:
        """Render one concise versioned competency-evidence lookup."""
        status = str(result.get("status") or "UNKNOWN")
        model = str(result.get("model") or "UNKNOWN")
        version = str(result.get("model_version") or model)
        runtime = str(result.get("provider_runtime_version") or "UNKNOWN")
        assessments = list(result.get("assessments") or [])
        if result.get("assessment"):
            assessments = [dict(result["assessment"])]
        self.io.write()
        self.io.write("LLM LANGUAGE COMPETENCY EVIDENCE")
        self.io.write("-" * 72)
        self.io.write(f"Model:            {model}")
        self.io.write(f"Model release:    {version}")
        self.io.write(f"Provider runtime: {runtime}")
        if assessments:
            self.io.write()
            self.io.write(f"{'Language':<24}{'Profile':<13}{'Level':<12}Confidence")
            self.io.write("-" * 72)
            for item in assessments:
                tag = str(item.get("canonical_tag") or "UNKNOWN")
                language = str(item.get("language") or tag)[:23]
                tier = str(item.get("tier") or "UNASSESSED")
                confidence = str(item.get("confidence") or "UNKNOWN")
                self.io.write(f"{language:<24}{tag:<13}{tier:<12}{confidence}")
                limitations = [str(value).strip() for value in item.get("limitations", []) if str(value).strip()]
                if limitations:
                    self.io.write("  Limits: " + "; ".join(limitations))
            self.io.write()
            self.io.write("Registry/evaluation evidence only; the model was not asked to rate itself.")
        elif status == "EVIDENCE_ALREADY_REGISTERED":
            self.io.write("No change: this model release already has registered evidence for the language.")
        else:
            self.io.write(f"Status: {status}")

    def _show_language_competency_table(self, service: ModelService) -> None:
        """Show the concise per-model competency view; detailed evidence stays in YAML."""
        result = service.language_competency_status("codex")
        self.io.write()
        self.io.write("REGISTERED LLM LANGUAGE COMPETENCY")
        self.io.write("-" * 72)
        self.io.write(str((result.get("policy") or {}).get("operator_disclaimer") or "Heuristic estimate; not a benchmark or guarantee."))
        self.io.write(f"Provider: {result.get('provider') or 'codex'}")
        self.io.write(f"Model:    {result.get('model') or 'UNKNOWN'}")
        self.io.write(f"Release:  {result.get('model_version') or result.get('model') or 'UNKNOWN'}")
        self.io.write(f"Runtime:  {result.get('provider_runtime_version') or 'UNKNOWN'}")
        if result.get("status") == "EVIDENCE_REQUIRED":
            self.io.write("Status:   EVIDENCE REQUIRED - this model release has not been evaluated yet.")
            return
        if result.get("status") != "READY":
            self.io.write(f"Status:   {result.get('status')}")
            self.io.write(str(result.get("diagnostic") or ""))
            return
        grouped: dict[str, list[str]] = {"EXCELLENT": [], "GOOD": [], "FAIR": [], "UNASSESSED": []}
        for tag, language, tier in result.get("rows", []):
            grouped.setdefault(tier, []).append(f"{language} [{tag}]")
        for tier in ("EXCELLENT", "GOOD", "FAIR", "UNASSESSED"):
            values = grouped.get(tier) or []
            if values:
                self.io.write(f"{tier:<12} " + ", ".join(values))

    def _report_missing_model_competency_evidence(self, service: ModelService) -> None:
        """Report missing evidence for a newly observed concrete model release."""
        status = service.language_competency_status("codex")
        if status.get("status") != "EVIDENCE_REQUIRED":
            return
        self.io.write()
        self.io.write("NEW MODEL RELEASE DETECTED")
        self.io.write("-" * 72)
        self.io.write(f"Model: {status.get('model')}")
        self.io.write("No trusted versioned or measured competency evidence is registered.")
        self.io.write("Languages remain UNASSESSED; SAGE will not ask the model to rate itself.")

    def _cycle_ai_provider(self, service: ModelService) -> bool:
        """Cycle configured providers without performing a live connection check."""
        settings = service.settings()
        enabled = [
            provider
            for provider in settings.get("providers", {})
            if provider in ENABLED_AUTOMATED_PROVIDER_IDS
        ]
        enabled = [item for item in enabled if item]
        if not enabled:
            raise ValidationError("No automated LLM provider is enabled in this build.", code="LLM_PROVIDER_NOT_READY")
        current = str(settings.get("selected_provider") or enabled[0])
        if len(enabled) == 1:
            return False
        index = enabled.index(current) if current in enabled else -1
        selected = enabled[(index + 1) % len(enabled)]
        update_llm_selection(self.root, provider=selected, auto=(selected == "codex"))
        return True

    def _show_configured_language_competency_table(self, service: ModelService) -> None:
        """Show competency only for Language Profiles currently configured in SAGE."""
        configured = load_ecosystem(self.store.settings_path).language_profiles
        competency = self._configured_competency_map()
        registry_cfg, relationship_cfg, _ = self._language_ui_config()
        identities = dict(registry_cfg.get("identities") or {})
        relationships = dict(relationship_cfg.get("profiles") or {})
        self.io.write()
        self.io.write("LANGUAGE COMPETENCY")
        self.io.write("=" * 72)
        status = service.language_competency_status("codex")
        self.io.write(f"{'Model':<28}{status.get('model') or 'UNKNOWN'}")
        self.io.write()
        self.io.write(f"{'Language':<25}{'Profile':<13}{'Script':<12}Competency")
        self.io.write("-" * 72)
        for tag, namespace in sorted(configured.items()):
            rel = dict(relationships.get(tag) or {})
            parent = str(rel.get("parent") or tag.split("-",1)[0])
            identity = dict(identities.get(parent) or {})
            name = str(rel.get("name") or identity.get("name") or tag)
            self.io.write(f"{name[:24]:<25}{tag:<13}[{namespace.script}]".ljust(50) + competency.get(tag,"NOT CHECKED"))

    def _load_ai_model_catalog(
        self,
        service: ModelService,
        ai: dict[str, Any],
    ) -> dict[str, Any]:
        """Load model capabilities from an already-ready provider state."""
        if not ai.get("ready") or str(ai.get("provider_id") or "") != "codex":
            return {"models": [], "diagnostic": ai.get("diagnostic")}
        try:
            return service.list_models("codex")
        except SageError as exc:
            return {"models": [], "diagnostic": exc.message, "reason_code": exc.code}

    def model_menu(self) -> None:
        """Load readiness once on entry; sample the model only on explicit request."""
        service = ModelService(self.root)
        with self.io.working("Loading LLM state"):
            ai = self._setup_model_probe(service, refresh=True)
            catalog = self._load_ai_model_catalog(service, ai)
        selection_checked = True
        while True:
            settings = service.settings()
            provider = str(settings.get("selected_provider") or "codex")
            item = dict(settings.get("providers", {}).get(provider, {}) or {})
            override_state = service.routing_override_status()
            connection = (
                ("READY" if ai.get("ready") else "NOT READY")
                if selection_checked
                else "NOT CHECKED FOR CURRENT SELECTION"
            )
            runtime_version = str(ai.get("version") or "UNKNOWN") if selection_checked else "NOT CHECKED"

            self.io.write_menu_header("CONFIGURE HOSTED AI")
            self.io.write(f"{'Connection':<28}{connection}")
            self.io.write(f"{'Provider':<28}{provider.title()}")
            self.io.write(f"{'AI Routing':<28}{override_state['routing_mode']}")
            policy_default = str(
                service.policy()["provisional_routing"]["default_reasoning_by_provider"].get(
                    provider,
                    "UNAVAILABLE",
                )
            )
            self.io.write(
                f"{'Auto / no data':<28}{policy_default} (POLICY DEFAULT)"
            )
            self.io.write(f"{'Provider runtime':<28}{provider}-cli {runtime_version}" if provider == "codex" else f"{'Provider runtime':<28}{runtime_version}")
            if selection_checked and not ai.get("ready") and ai.get("diagnostic"):
                self.io.write(f"{'Status detail':<28}{ai.get('diagnostic')}")
            elif not selection_checked:
                self.io.write(f"{'Status detail':<28}Choose 7 to check the current configuration")

            self.io.write_menu_header("AI settings", major=False)
            self.io.write(menu_item(1, "Change provider"))
            self.io.write(menu_item(2, "Available provider models"))
            self.io.write(menu_item(3, "Skill routing recommendations"))
            self.io.write(menu_item(4, "Advanced routing override"))
            self.io.write_menu_header("Provider management", major=False)
            self.io.write(menu_item(5, "Connect OpenAI and ChatGPT"))
            self.io.write(menu_item(6, "Configure Local AI"))
            self.io.write(menu_item(7, "Check LLM connection"))
            self.io.write_menu_footer(include_back=True)
            value = self.io.read("Choose: ").strip().casefold()
            if value == "a":
                return
            if value == "b":
                raise MenuHomeRequested()
            if value == "c":
                raise MenuExitRequested()
            if value == "d" and self.io.language_handler:
                self.io.language_handler()
                continue
            if value in {"e", "?"} and self.io.help_handler:
                self.io.help_handler("CONFIGURE HOSTED AI")
                continue
            if value == "f" and self.io.status_handler:
                self.io.status_handler()
                continue
            try:
                if value == "1":
                    if self._cycle_ai_provider(service):
                        selection_checked = False
                elif value == "2":
                    self._model_show_codex_catalog(service)
                elif value == "3":
                    self._model_show_recommendation_status(service)
                elif value == "4":
                    self._model_routing_override_menu(service)
                    selection_checked = False
                elif value == "5":
                    self._model_connect_chatgpt(service)
                    selection_checked = False
                elif value == "6":
                    self.local_admin_assistant_menu()
                elif value == "7":
                    with self.io.working("Checking LLM connection"):
                        ai = self._model_test_selected(service)
                        catalog = self._load_ai_model_catalog(service, ai)
                    selection_checked = True
                else:
                    self.io.write("Invalid choice. Choose 1-7 or a footer action.")
                    continue
            except SageError as exc:
                self.show_error(exc)
            self.io.pause()

    def _project_purposes(self, project_id: str) -> tuple[str, ...]:
        """Return Job IDs and bindings that currently use one SAGE Project."""
        labels = {"content_source":"BIC SOURCE", "lexical_donor":"BIC DONOR", "generated_target":"BIC TARGET", "wip":"SAW WIP", "reference":"SAW REFERENCE", "original_language_greek":"OL GRK", "original_language_hebrew":"OL HEB"}
        values: set[str] = set()
        for job in self.store.discover(include_archived=True):
            for key, value in job.bindings.items():
                if value == project_id and key in labels:
                    values.add(f"{job.job_id} - {labels[key]}")
        return tuple(sorted(values))

    def _project_vrs_summary(self, value: dict[str, Any]) -> str:
        """Render one compact custom/base VRS summary without inventing missing metadata."""
        custom = str(value.get("custom_file") or value.get("file") or "auto")
        configured_base = str(value.get("base_file") or "").strip()
        reported_base = str(value.get("reported_base_file") or "").strip()
        description = str(value.get("base_description") or "").strip()
        name = str(value.get("name") or "").strip()
        if custom.lower() in {"auto", "none", ""}:
            return f"base {configured_base or 'unknown'}"
        text = custom
        if reported_base:
            text += f" based on {reported_base}"
        else:
            text += " (base unknown)"
        if description:
            text += f" ({description})"
        elif name and not reported_base:
            text += f" - {name}"
        return text

    def registered_projects_menu(self) -> None:
        """Maintain Projects already added to SAGE."""
        while True:
            records = registered_project_records(self.root)
            ids = sorted(records, key=str.casefold)
            self.io.write()
            self.io.write("SAGE SCRIPTURE PROJECTS")
            self.io.write("-"*72)
            self.io.write("#   Project     Name                               Lang      Scope       Status")
            for i, pid in enumerate(ids,1):
                row=records[pid]
                language=str(row.get("language",{}).get("code","?"))
                name=str(row.get("display_name") or pid)
                scope=str(row.get("scope_summary") or "UNKNOWN")
                status=str(row.get("validation_status") or "UNKNOWN")
                self.io.write(f"{i:<3} {pid:<11} {name[:34]:<34} {language:<9} {scope:<11} {status}")
            if not ids: self.io.write("No Projects have been added to SAGE yet.")
            add_key = str(len(ids) + 1)
            validate_key = str(len(ids) + 2)
            selected=self.io.choose(
                "SAGE Scripture Projects",
                [(str(i),pid) for i,pid in enumerate(ids,1)]
                + [(add_key,"Add another Project to SAGE"),(validate_key,"Validate all SAGE Projects"),("B", "Back")],
            )
            if selected=="B": return
            if selected==add_key:
                self.discover_register_projects_menu()
                continue
            if selected==validate_key:
                self.validate_shared_registry()
                continue
            self.registered_project_detail(ids[int(selected)-1])

    def _refresh_registered_from_catalog(self, project_id: str) -> dict[str, Any]:
        """Refresh filesystem-derived Project facts while preserving operator overrides and Job roles."""
        record = registered_project_records(self.root).get(project_id)
        if not isinstance(record, dict):
            raise ValidationError(f"Project is not in SAGE: {project_id}", code="PROJECT_NOT_IN_SAGE")
        mount = load_resource_mounts(self.root).get(project_id, {})
        resolved_path = Path(str(mount.get("path") or "")).expanduser() if mount else None
        catalogue = load_paratext_catalog(self.root)
        catalogue_row = dict(catalogue.get("projects", {}).get(project_id, {}))
        catalogue_path = Path(str(catalogue_row.get("path") or "")).expanduser() if catalogue_row else None
        if resolved_path is not None and resolved_path.is_dir() and (catalogue_path is None or resolved_path.resolve() != catalogue_path.resolve()):
            # <Other location> Projects are intentionally outside the primary catalog root.
            # Refresh them directly rather than pretending they belong under projects_root/project_id.
            row = inspect_paratext_project(resolved_path)
        else:
            row = rescan_catalog_project(self.root, project_id)
        books = tuple(str(book) for book in row.get("books", []))
        scope = dict(record.get("scope") or {})
        scope["testament"] = scope_testament(books)
        scope["expected_books"] = list(books) if books else scope.get("expected_books", [])
        scope["roles"] = []
        vrs = dict(record.get("versification") or {})
        parsed_vrs = dict(row.get("versification") or {})
        vrs.update({
            "custom_file": str(parsed_vrs.get("file") or "auto"),
            "name": parsed_vrs.get("name"),
            "reported_base_file": parsed_vrs.get("base_file"),
            "base_description": parsed_vrs.get("base_description"),
            "metadata_status": parsed_vrs.get("metadata_status"),
        })
        return update_project_record(
            self.root,
            project_id,
            {
                "display_name": row.get("full_name") or project_id,
                "detected_books": list(books),
                "sfm_books": list(row.get("sfm_books", [])),
                "scope": scope,
                "scope_summary": summarize_scope(books),
                "versification": vrs,
                "paratext_metadata": {
                    "full_name": row.get("full_name"),
                    "language_name": row.get("language_name"),
                    "language_iso": row.get("language_iso"),
                    "language_iso_raw": row.get("language_iso_raw"),
                    "catalog_status": row.get("status"),
                },
                "validation_status": "VALID" if row.get("status") == "READY" else str(row.get("status") or "WARNING"),
            },
        )

    def registered_project_detail(self, project_id: str) -> None:
        """Render one SAGE Project maintenance screen using current section grammar."""
        while True:
            record=registered_project_records(self.root).get(project_id)
            if record is None:
                self.io.write(f"SAGE Project not found: {project_id}")
                self.io.pause()
                return
            mount=load_resource_mounts(self.root).get(project_id,{})
            meta=dict(record.get("paratext_metadata") or {})
            vrs=dict(record.get("versification") or {})
            self.io.write()
            self.io.write(f"PROJECT - {project_id}")
            self.io.write("-"*72)
            self.io.write("# Details ______________________________________________________________")
            self.io.write(f"Name:             {record.get('display_name', project_id)}")
            self.io.write(f"Language:         {meta.get('language_name') or 'UNKNOWN'} [{record.get('language',{}).get('code','?')}]")
            self.io.write(f"Scope:            {record.get('scope_summary','UNKNOWN')}")
            self.io.write(f"Versification:    {self._project_vrs_summary(vrs)}")
            self.io.write(f"Status:           {record.get('validation_status','UNKNOWN')}")
            action = self.io.choose(
                "PROJECT ACTIONS",
                (
                    ("1", "Project information"),
                    ("2", "Scripture books"),
                    ("3", "Versification"),
                    ("4", "Project location"),
                    ("5", "Validate Project"),
                    ("6", "Jobs using this Project"),
                    ("7", "Advanced settings"),
                    ("8", "Remove Project from SAGE"),
                    ("B", "Back"),
                ),
            )
            if action=="B": return
            if action=="1": self._project_information_menu(project_id)
            elif action=="2": self._project_books_menu(project_id)
            elif action=="3": self._project_vrs_menu(project_id)
            elif action=="4": self._project_storage_menu(project_id)
            elif action=="5":
                try:
                    refreshed=self._refresh_registered_from_catalog(project_id)
                    self.io.write(f"Validated {project_id}: scope={refreshed.get('scope_summary')} status={refreshed.get('validation_status')}")
                except SageError as exc: self.show_error(exc)
                self._setup_scripture_resource_status(render=True)
                self.io.pause()
            elif action=="6": self._project_jobs_menu(project_id)
            elif action=="7": self._project_advanced_menu(project_id)
            elif action=="8":
                if self._unregister_project_menu(project_id): return

    def _project_information_menu(self, project_id: str) -> None:
        """Show Paratext-derived identity separately from operator-owned Project settings."""
        record = registered_project_records(self.root)[project_id]
        meta = dict(record.get("paratext_metadata") or {})
        code = dict(record.get("code_metadata") or {})
        self.io.write(f"Project code:      {project_id}")
        self.io.write(f"Full name:         {record.get('display_name', project_id)}")
        self.io.write(f"Language:          {meta.get('language_name') or 'UNKNOWN'}")
        self.io.write(f"ISO language:      {record.get('language', {}).get('code', '?')}")
        self.io.write(f"Type:              {code.get('type_name') or code.get('type_code') or 'UNPARSED'}")
        self.io.write(f"Iteration:         {code.get('iteration') if code.get('iteration') is not None else 'UNPARSED'}")
        self.io.write(f"Code parse:        {code.get('parse_status', 'UNPARSED')}")
        if self.io.confirm("Refresh detected identity from Paratext now?", default=False):
            self._refresh_registered_from_catalog(project_id)
        self.io.pause()

    def _project_books_menu(self, project_id: str) -> None:
        """Show canons.xml-derived inclusion and actual .SFM inventory."""
        record = registered_project_records(self.root)[project_id]
        catalogue = load_paratext_catalog(self.root)
        row = dict(catalogue.get("projects", {}).get(project_id, {}))
        canon_books = tuple(row.get("canon_books", record.get("detected_books", [])))
        sfm_books = tuple(row.get("sfm_books", record.get("sfm_books", [])))
        self.io.write(f"Project:              {project_id}")
        self.io.write(f"Derived scope:        {record.get('scope_summary', 'UNKNOWN')}")
        self.io.write(f"canons.xml books:     {len(canon_books)}")
        self.io.write(f"Scripture .SFM books: {len(sfm_books)}")
        missing = [book for book in canon_books if book not in sfm_books]
        unexpected = [book for book in sfm_books if book not in canon_books] if canon_books else []
        self.io.write(f"Missing .SFM:         {', '.join(missing) if missing else 'NONE'}")
        self.io.write(f"Unexpected .SFM:      {', '.join(unexpected) if unexpected else 'NONE'}")
        if canon_books:
            self.io.write("Included books:       " + ", ".join(canon_books))
        self.io.pause()

    def _project_vrs_menu(self, project_id: str) -> None:
        """Show executable and descriptive custom/base VRS information."""
        record = registered_project_records(self.root)[project_id]
        vrs = dict(record.get("versification") or {})
        self.io.write(f"Project:             {project_id}")
        self.io.write(f"Versification:       {self._project_vrs_summary(vrs)}")
        self.io.write(f"Configured base VRS: {vrs.get('base_file') or 'UNKNOWN'}")
        self.io.write(f"Custom VRS name:     {vrs.get('name') or 'NOT DECLARED'}")
        self.io.write(f"Comment base VRS:    {vrs.get('reported_base_file') or 'UNKNOWN'}")
        self.io.write(f"Description:         {vrs.get('base_description') or 'NONE'}")
        self.io.write("Note: custom.vrs comments are descriptive metadata; executable VRS content remains authoritative.")
        self.io.pause()

    def _project_storage_menu(self, project_id: str) -> None:
        """Maintain one Project mapping without exposing unrelated resource-registry internals."""
        while True:
            state = load_resource_mount_state(self.root)
            mount = load_resource_mounts(self.root).get(project_id)
            self.io.write(f"Projects root: {state.get('projects_root') or 'NOT CONFIGURED'}")
            self.io.write(f"Resolved path: {mount.get('path') if mount else 'UNMAPPED'}")
            self.io.write(f"Access:        {mount.get('access_mode') if mount else 'UNMAPPED'}")
            action = self.io.choose(
                "Project storage",
                (
                    ("1", "Re-detect from Projects root"),
                    ("2", "Use <Other location>"),
                    ("3", "Test access"),
                    ("B", "Back"),
                ),
            )
            if action == "B":
                return
            try:
                if action == "1":
                    root_path = self._ensure_project_root()
                    if root_path is None:
                        continue
                    catalogue = self._scan_projects(root_path, full=False)
                    if project_id not in catalogue.get("projects", {}):
                        raise ValidationError(
                            f"{project_id} was not discovered as a valid direct child of {root_path}",
                            code="PROJECT_NOT_DISCOVERED",
                        )
                    set_resource_mount(self.root, project_id=project_id, project_folder=project_id)
                    self.io.write(f"Mapped {project_id} from the configured Projects root.")
                elif action == "2":
                    raw_value = self.io.text("Project folder or parent Projects root")
                    value, inferred_root, inferred_folder = interpret_operator_project_location(project_id, raw_value)
                    if inferred_root is not None and inferred_folder is not None:
                        if not state.get("projects_root"):
                            set_project_root(self.root, project_root=inferred_root, progress=self._scan_progress)
                            self.io.clear_status()
                            set_resource_mount(self.root, project_id=project_id, project_folder=inferred_folder)
                        else:
                            set_resource_mount(self.root, project_id=project_id, external_path=value)
                    else:
                        set_resource_mount(self.root, project_id=project_id, external_path=value)
                    self.io.write(f"Mapped {project_id}: {value}")
                elif action == "3":
                    if not mount:
                        raise ValidationError("Project is not mapped", code="PROJECT_NOT_MAPPED")
                    path = Path(str(mount["path"]))
                    self.io.write(f"Directory: {'READY' if path.is_dir() else 'MISSING'}")
                    self.io.write(f"settings.xml: {'READY' if (path / 'settings.xml').is_file() else 'MISSING'}")
                self.io.pause()
            except SageError as exc:
                self.show_error(exc)

    def _project_jobs_menu(self, project_id: str) -> None:
        """Show workflow purposes as Job bindings, never as intrinsic Project roles."""
        found = False
        for job in self.store.discover(include_archived=False):
            for key, value in job.bindings.items():
                if value != project_id:
                    continue
                found = True
                self.io.write(f"{job.job_id} - {key.upper()}")
        if not found:
            self.io.write("This Project is not currently bound to an active Job.")
        self.io.pause()

    def _project_advanced_menu(self, project_id: str) -> None:
        """Keep raw registry/code diagnostics out of normal Project maintenance."""
        record = registered_project_records(self.root)[project_id]
        choice = self.io.choose(
            "Advanced Project settings",
            (("1", "Show parsed project-code metadata"), ("2", "Show raw SAGE Project record"), ("B", "Back")),
        )
        if choice == "1":
            self.io.write(json.dumps(record.get("code_metadata", {}), indent=2, ensure_ascii=False, sort_keys=True))
            self.io.pause()
        elif choice == "2":
            self.io.write(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True))
            self.io.pause()

    def _unregister_project_menu(self, project_id: str) -> bool:
        """Remove one Project from SAGE only; never delete Paratext files."""
        purposes=self._project_purposes(project_id)
        self.io.write()
        self.io.write(f"REMOVE PROJECT FROM SAGE - {project_id}")
        self.io.write("-"*72)
        self.io.write(f"This removes {project_id} from SAGE only.")
        self.io.write("The Paratext Project and its Scripture files will NOT be deleted or modified.")
        if purposes:
            self.io.write("Jobs currently using this Project:")
            for purpose in purposes: self.io.write(f"  {purpose}")
            self.io.write("The Project cannot be removed while it is used by a Job. Remove the Job binding first.")
            self.io.pause()
            return False
        if not self.io.confirm(f"Remove {project_id} from SAGE?", default=False): return False
        remove_resource_mount(self.root, project_id=project_id)
        unregister_project(self.root, project_id=project_id)
        self.io.write(f"Removed {project_id} from SAGE. Paratext files were unchanged.")
        self.io.pause()
        return True

    def remove_project_from_sage_menu(self) -> None:
        """Choose one SAGE Project for safe removal without opening its detail screen first."""
        records = registered_project_records(self.root)
        project_ids = sorted(records, key=str.casefold)
        self.io.write()
        self.io.write("REMOVE PROJECT FROM SAGE")
        self.io.write("-" * 72)
        self.io.write("This removes SAGE inventory and mapping state only.")
        self.io.write("Paratext Project folders and Scripture files are never deleted or modified.")
        if not project_ids:
            self.io.write("No Projects have been added to SAGE yet.")
            self.io.pause()
            return
        options = [
            (
                str(index),
                f"{project_id:<11} {str(records[project_id].get('display_name') or project_id)}",
            )
            for index, project_id in enumerate(project_ids, 1)
        ]
        options.append(("B", "Back"))
        selected = self.io.choose("Choose SAGE Project", tuple(options))
        if selected == "B":
            return
        self._unregister_project_menu(project_ids[int(selected) - 1])

    def _catalogue_filter_menu(self, scope_filter: str, language_filter: str | None) -> tuple[str, str | None]:
        """Configure only the two approved discovery filters: FB/NT/Portions and language."""
        while True:
            catalogue = load_paratext_catalog(self.root)
            language_label = language_filter or "All"
            choice = self.io.choose(
                "Filter Projects",
                (("1", f"{self.localizer.text('Scope'):<10}{scope_filter}"), ("2", f"{self.localizer.text('Language'):<10}{language_label}"), ("3", "Clear filters"), ("B", "Back")),
            )
            if choice == "B":
                return scope_filter, language_filter
            if choice == "3":
                scope_filter, language_filter = "ALL", None
            elif choice == "1":
                selected = self.io.choose(
                    "Scope",
                    (("1", "Full Bible [FB]"), ("2", "New Testament [NT]"), ("3", "Portions"), ("4", "All")),
                )
                scope_filter = {"1": "FB", "2": "NT", "3": "PORTIONS", "4": "ALL"}[selected]
            elif choice == "2":
                languages = language_filter_counts(catalogue)
                options = [(str(index), f"{row['language_name']} [{row['language_iso']}] [{row['count']}]") for index, row in enumerate(languages, 1)]
                all_key = str(len(options) + 1)
                options.append((all_key, "All languages"))
                selected = self.io.choose("Language", options)
                language_filter = None if selected == all_key else str(languages[int(selected) - 1]["language_iso"])

    def _project_language_identification_menu(self, row: dict[str, Any]) -> bool:
        """Confirm ISO language and primary audience country, then ensure one regional Language Profile."""
        identification = dict(row.get("language_identification") or {})
        candidates = [dict(item) for item in identification.get("candidates", []) if isinstance(item, dict)]
        selected = dict(identification.get("selected") or (candidates[0] if candidates else {}))
        country_evidence = [dict(item) for item in identification.get("country_evidence", []) if isinstance(item, dict)]
        primary_country = dict(identification.get("primary_country") or {})

        def recompute_tag() -> str | None:
            """Derive the current regional BCP-47 candidate from Operator selections."""
            primary = str(selected.get("preferred") or selected.get("alpha_2") or selected.get("alpha_3") or "").casefold()
            code = str(primary_country.get("code") or "").upper()
            if not primary or not code:
                return None
            try:
                return canonical_regional_language_tag(f"{primary}-{code}", "Language Profile candidate")
            except SageError:
                return None

        while True:
            tag = recompute_tag()
            self.io.write()
            self.io.write("LANGUAGE IDENTIFICATION")
            self.io.write("-" * 72)
            self.io.write()
            self.io.write("Language")
            alpha2 = str(selected.get("alpha_2") or "")
            alpha3 = str(selected.get("alpha_3") or "")
            iso_display = " / ".join(value for value in (alpha2, alpha3) if value) or "UNRESOLVED"
            self.io.write(f"  ISO                             {iso_display}")
            self.io.write(f"  Language                        {selected.get('name') or row.get('language_name') or 'UNKNOWN'}")
            self.io.write()
            self.io.write("Country evidence")
            if country_evidence:
                self.io.write("  Paratext                        " + ", ".join(str(item.get("name") or item.get("code")) for item in country_evidence))
            else:
                self.io.write("  Paratext                        NONE")
            country_name = str(primary_country.get("name") or "NOT SELECTED")
            if primary_country and not country_evidence:
                country_name += " [suggested]"
            self.io.write()
            self.io.write(f"Primary audience country          {country_name}")
            self.io.write(f"Current BCP-47 candidate          {tag or 'PENDING'}")
            choice = self.io.choose(
                "LANGUAGE IDENTIFICATION",
                (("1", "Accept"), ("2", "Change ISO"), ("3", "Change primary country"),
                 ("4", "Review language evidence"), ("5", "Review country evidence"), ("B", "Back")),
            )
            if choice == "B":
                return False
            if choice == "2":
                options = []
                for index, item in enumerate(candidates, 1):
                    a2 = str(item.get("alpha_2") or "")
                    a3 = str(item.get("alpha_3") or "")
                    codes = " / ".join(value for value in (a2, a3) if value)
                    options.append((str(index), f"{codes} - {item.get('name') or 'ISO language'}"))
                manual_key = str(len(options) + 1)
                options.extend(((manual_key, "Enter ISO code manually"), ("B", "Back")))
                picked = self.io.choose("CHANGE ISO", tuple(options))
                if picked == "B":
                    continue
                if picked == manual_key:
                    while True:
                        code = self.io.text("ISO language code").casefold()
                        found = iso_language(code)
                        if found is None:
                            self.io.write("That code was not found in SAGE's bundled ISO language registry.")
                            continue
                        selected = {
                            "alpha_2": str(found.get("alpha_2") or "").casefold(),
                            "alpha_3": str(found.get("alpha_3") or "").casefold(),
                            "preferred": str(found.get("alpha_2") or found.get("alpha_3") or "").casefold(),
                            "name": str(found.get("name") or ""),
                        }
                        break
                else:
                    selected = dict(candidates[int(picked) - 1])
                continue
            if choice == "3":
                options = [(str(i), f"{item.get('name')} [{item.get('code')}]") for i, item in enumerate(country_evidence, 1)]
                manual_key = str(len(options) + 1)
                options.extend(((manual_key, "Enter country code or name manually"), ("B", "Back")))

                def country_selection(value: str) -> str:
                    """Accept common country identifiers directly from the country-selection prompt."""
                    country = resolve_country_input(value)
                    if country is not None:
                        return country["code"]
                    raise InputRequiredError(
                        "Enter a listed number or a country as US, USA, 840, United States, or en-US.",
                        code="COUNTRY_SELECTION_INVALID",
                        received=value,
                    )

                picked = self.io.choose(
                    "CHANGE PRIMARY AUDIENCE COUNTRY",
                    tuple(options),
                    prompt="Choose number or enter country: ",
                    direct_validator=country_selection,
                    context=(
                        "Enter a listed number, or type a country directly.",
                        "Accepted examples: US, USA, 840, United States, en-US.",
                    ),
                )
                if picked == "B":
                    continue
                direct_country = resolve_country(picked)
                if direct_country is not None:
                    primary_country = direct_country
                    continue
                if picked == manual_key:
                    while True:
                        value = self.io.text("Country (US, USA, 840, United States, or en-US)")
                        try:
                            country_code = country_selection(value)
                        except SageError as exc:
                            self.io.write(str(exc))
                            continue
                        country = resolve_country(country_code)
                        if country is not None:
                            primary_country = country
                            break
                else:
                    primary_country = dict(country_evidence[int(picked) - 1])
                continue
            if choice == "4":
                self.io.write()
                self.io.write("LANGUAGE EVIDENCE")
                self.io.write("-" * 72)
                self.io.write(f"Settings.xml                   {row.get('paratext_language_code') or row.get('language_iso_raw') or 'NONE'}")
                for item in identification.get("ldml", []):
                    self.io.write(f"LDML {item.get('file'):<24}{item.get('language') or 'NONE'}")
                prefix = dict(row.get("code_metadata") or {}).get("paratext_language_code")
                self.io.write(f"Project prefix                 {prefix or 'NONE'}")
                self.io.write(f"Confidence                     {identification.get('confidence') or 'LOW'}")
                self.io.pause()
                continue
            if choice == "5":
                self.io.write()
                self.io.write("COUNTRY EVIDENCE")
                self.io.write("-" * 72)
                if country_evidence:
                    for item in country_evidence:
                        self.io.write(f"Paratext                       {item.get('name')} [{item.get('code')}]")
                else:
                    self.io.write("Paratext                       NONE")
                    if primary_country:
                        self.io.write(f"SAGE suggestion                {primary_country.get('name')} [{primary_country.get('code')}]")
                self.io.pause()
                continue
            if choice == "1":
                if not selected.get("alpha_3"):
                    self.io.write("Choose a valid ISO language before accepting.")
                    continue
                if not primary_country:
                    self.io.write("Choose the primary audience country before accepting.")
                    continue
                if not tag:
                    self.io.write("SAGE could not derive a regional BCP-47 candidate from the selections.")
                    continue
                config = load_ecosystem(self.store.settings_path)
                if tag not in config.language_profiles:
                    compatible = [code for code in config.language_profiles if code.split("-")[0].casefold() == tag.split("-")[0].casefold()]
                    options = [("1", f"Create Language Profile [{tag}]")]
                    if compatible:
                        options.append(("2", "Choose existing compatible Language Profile"))
                    options.append(("B", "Back"))
                    picked = self.io.choose("LANGUAGE PROFILE", tuple(options), context=(
                        f"Language                      {selected.get('name')}",
                        f"ISO                           {iso_display}",
                        f"Primary audience country      {primary_country.get('name')}",
                        f"BCP-47                        {tag}",
                        "Language Profile              NOT CONFIGURED",
                    ))
                    if picked == "B":
                        continue
                    if picked == "2":
                        profile_options = [(str(i), code) for i, code in enumerate(compatible, 1)] + [("B", "Back")]
                        chosen = self.io.choose("CHOOSE LANGUAGE PROFILE", tuple(profile_options))
                        if chosen == "B":
                            continue
                        tag = compatible[int(chosen) - 1]
                        region = tag.split("-")[-1]
                        country = resolve_country(region)
                        if country is not None:
                            primary_country = country
                    else:
                        script = str((identification.get("scripts") or [""])[0] or "")
                        if not script:
                            same_language = next((item for code, item in config.language_profiles.items() if code.split("-")[0].casefold() == tag.split("-")[0].casefold()), None)
                            script = str(same_language.script if same_language is not None else "")
                        if not script:
                            script = self.io.text("ISO 15924 script code (example Latn)", validator=lambda value: canonical_script_code(value, "Language Profile script"))
                        ensure_language_profile_namespace(self.store.settings_path, tag=tag, script=script)
                        invalidate_runtime_settings(self.root)
                row["paratext_language_code"] = row.get("paratext_language_code") or row.get("language_iso_raw")
                row["canonical_iso_639_3"] = selected.get("alpha_3")
                row["preferred_language_subtag"] = selected.get("preferred") or selected.get("alpha_2") or selected.get("alpha_3")
                row["language_name"] = selected.get("name") or row.get("language_name")
                row["primary_audience_country"] = primary_country.get("code")
                row["language_profile_tag"] = tag
                row["language_iso"] = tag  # compatibility: Project inventory stores regional language identity.
                return True

    def _register_catalogue_row(self, row: dict[str, Any], role: str | None = None) -> str | None:
        """Review one discovered Project and add it to SAGE without assigning a Job role."""
        project_id=str(row.get("project_code"))
        if str(row.get("detail_status") or "VALIDATED").upper() == "PENDING":
            try:
                row = rescan_catalog_project(self.root, project_id)
            except SageError as exc:
                self.show_error(exc)
                self.io.pause()
                return None
        vrs=dict(row.get("versification") or {})
        self.io.write()
        self.io.write(f"ADD PROJECT TO SAGE - {project_id}")
        self.io.write("-"*72)
        self.io.write("SAGE detected this information from the Paratext Project.")
        self.io.write(f"Name:             {row.get('full_name') or project_id}")
        self.io.write(f"Language:         {row.get('language_name') or 'UNKNOWN'} [{row.get('language_iso') or '?'}]")
        resolution=dict(row.get("language_resolution") or {})
        if resolution:
            self.io.write(f"ISO status:       {resolution.get('status','UNKNOWN')}")
            if resolution.get("prefix_evidence"): self.io.write(f"Project prefix:   {resolution['prefix_evidence']}")
            if resolution.get("suggestions"): self.io.write("Suggestions:      " + ", ".join(str(v) for v in resolution["suggestions"]))
        self.io.write(f"Scope:            {row.get('scope')} ({row.get('book_count',0)} books)")
        self.io.write(f"Versification:    {self._project_vrs_summary(vrs)}")
        self.io.write(f"Project code:     {row.get('code_metadata',{}).get('parse_status','UNPARSED')}")
        self.io.write(f"Validation:       {row.get('status')}")
        if row.get("warnings"): self.io.write("Warnings:         " + ", ".join(row["warnings"]))
        if not self._project_language_identification_menu(row):
            return None
        if not self.io.confirm("Add this Project to SAGE?", default=True): return None
        try:
            created=register_catalogued_scripture_project(self.store.settings_path, catalogue_row=row)
            self.io.write()
            self.io.write("PROJECT ADDED TO SAGE")
            self.io.write("-"*72)
            self.io.write(f"{created} - {row.get('full_name') or created}")
            return created
        except SageError as exc:
            self.show_error(exc)
            self.io.pause()
            return None

    def discover_register_projects_menu(self, role: str | None = None, *, return_on_register: bool = False) -> str | None:
        """Add selected discovered Paratext Projects to the SAGE Project Inventory."""
        root_path=self._ensure_project_root()
        if root_path is None: return None
        catalogue=load_paratext_catalog(self.root)
        if catalogue.get("projects_root") != str(root_path.resolve()): catalogue=self._scan_projects(root_path, full=False)
        scope_filter="ALL"
        language_filter: str|None=None
        while True:
            inventory=set(registered_project_records(self.root))
            rows=filtered_projects(catalogue, scope=scope_filter, language_iso=language_filter, registered_ids=inventory, unregistered_only=True)
            summary=catalog_summary(catalogue)
            self.io.write()
            self.io.write("ADD PROJECTS TO SAGE")
            self.io.write("-"*72)
            self.io.write("Choose Paratext Projects that SAGE should make available to BIC and SAW.")
            self.io.write(f"Paratext root:    {catalogue.get('projects_root')}")
            self.io.write(
                f"Catalog:          {summary.get('discovered', summary['projects'])} discovered; "
                f"{summary.get('validated', 0)} validated; {summary.get('pending', 0)} pending"
            )
            self.io.write(f"Already in SAGE:  {len(inventory)}")
            self.io.write(f"Available:        {len(rows)}")
            self.io.write(f"Filter:           Scope={scope_filter}  Language={language_filter or 'ALL'}")
            options=[]
            for i,row in enumerate(rows,1):
                code=str(row.get("project_code"))
                name=str(row.get("full_name") or code)
                scope = row.get('filter_scope') or 'PENDING'
                options.append((str(i),f"{code:<9} {name[:38]:<38} {row.get('language_iso') or '?':<5} {scope}"))
            filter_key = str(len(options) + 1)
            rescan_key = str(len(options) + 2)
            invalid_key = str(len(options) + 3)
            other_key = str(len(options) + 4)
            options += [(filter_key,"Filter catalog"),(rescan_key,"Rescan Paratext Projects"),(invalid_key,"Invalid Project folders"),(other_key,"Other Project location"),("B", "Back")]
            selected=self.io.choose("Available Paratext Projects", options)
            if selected=="B": return None
            if selected==filter_key:
                scope_filter,language_filter=self._catalogue_filter_menu(scope_filter,language_filter)
                continue
            if selected==rescan_key:
                mode=self.io.choose("RESCAN PARATEXT PROJECTS", (("1","Quick rescan"),("2","Full rescan"),("B", "Back")))
                if mode!="B": catalogue=self._scan_projects(root_path, full=mode=="2")
                continue
            if selected==invalid_key:
                invalid=dict(catalogue.get("invalid_folders",{}))
                if not invalid: self.io.write("No invalid Project folders are cataloged.")
                for code,item in sorted(invalid.items()): self.io.write(f"{code}: {item.get('code')} - {item.get('message')}")
                self.io.pause()
                continue
            if selected==other_key:
                raw=normalize_operator_path(self.io.text("Full Paratext Project folder"))
                try: row=inspect_paratext_project(Path(raw))
                except SageError as exc:
                    self.show_error(exc)
                    self.io.pause()
                    continue
            else: row=rows[int(selected)-1]
            created=self._register_catalogue_row(dict(row))
            if created and return_on_register: return created
            if created: catalogue=load_paratext_catalog(self.root)

    def projects_root_menu(self) -> None:
        """Configure Paratext Projects root and its persistent Project Catalog."""
        while True:
            state=load_resource_mount_state(self.root)
            primary=state.get("projects_root")
            catalogue=load_paratext_catalog(self.root)
            summary=catalog_summary(catalogue)
            self.io.write()
            self.io.write("PARATEXT PROJECT CATALOG")
            self.io.write("-"*72)
            self.io.write(f"Paratext Projects root: {primary or 'NOT CONFIGURED'}")
            self.io.write(f"Projects discovered:    {summary.get('discovered', summary['projects'])}")
            self.io.write(f"Pending validation:     {summary.get('pending', 0)}")
            self.io.write(f"Last scan:              {summary['last_scan'] or 'NEVER'}")
            choice=self.io.choose("Paratext Project Catalog", (("1","Set Paratext Projects root"),("2","Quick rescan"),("3","Full rescan"),("4","Show catalog summary"),("B", "Back")))
            if choice=="B": return
            try:
                if choice=="1":
                    value=Path(normalize_operator_path(self.io.text("Paratext Projects root"))).expanduser()
                    try: set_project_root(self.root, project_root=value, progress=self._scan_progress)
                    finally: self.io.clear_status()
                    self.io.write(f"Paratext Projects root: {value.resolve()}")
                elif choice in {"2","3"}:
                    if not primary: raise ValidationError("Configure the Paratext Projects root first", code="PROJECT_ROOT_NOT_FOUND")
                    result=self._scan_projects(Path(primary), full=choice=="3")
                    row=catalog_summary(result)
                    self.io.write(
                        f"Paratext scan complete: {row.get('discovered', row['projects'])} discovered; "
                        f"{row.get('validated', 0)} validated; {row.get('pending', 0)} pending; {row['invalid']} invalid"
                    )
                elif choice=="4": self._write_catalog_summary(catalogue)
                self.io.pause()
            except SageError as exc: self.show_error(exc)

    def scan_rescan_projects_menu(self) -> None:
        """Refresh the Paratext Project Catalog from the configured Projects root."""
        state = load_resource_mount_state(self.root)
        primary = state.get("projects_root")
        if not primary:
            self.show_error(
                ValidationError(
                    "Paratext Projects root is not configured",
                    code="PROJECTS_ROOT_NOT_CONFIGURED",
                    next_action="Choose Paratext Projects root from the Scripture Projects menu first.",
                )
            )
            self.io.pause()
            return
        choice = self.io.choose(
            "SCAN PARATEXT PROJECTS",
            (("1", "Quick rescan"), ("2", "Full rescan"), ("B", "Back")),
            context=(f"Paratext Projects root: {primary}",),
        )
        if choice == "B":
            return
        try:
            result = self._scan_projects(Path(str(primary)), full=choice == "2")
            row = catalog_summary(result)
            self.io.write(
                f"Paratext scan complete: {row.get('discovered', row['projects'])} discovered; "
                f"{row.get('validated', 0)} validated; {row.get('pending', 0)} pending; {row['invalid']} invalid"
            )
            self.io.pause()
        except SageError as exc:
            self.show_error(exc)

    def _map_registered_resource(self) -> None:
        """Advanced path update for a SAGE Project whose location has changed."""
        records=registered_project_records(self.root)
        ids=sorted(records,key=str.casefold)
        if not ids:
            self.io.write("No SAGE Projects exist.")
            self.io.pause()
            return
        selected=self.io.choose("Choose SAGE Project", [(str(i),pid) for i,pid in enumerate(ids,1)] + [("B", "Back")])
        if selected=="B": return
        self._project_storage_menu(ids[int(selected)-1])

    def _configure_ol_resource_menu(self, resource_id: str) -> None:
        """Explicitly choose the source behind one stable governed @GRK/@HEB alias."""
        while True:
            row = resolved_ol_entry(self.root, resource_id)
            self.io.write(f"Alias:      {row['alias']}")
            self.io.write(f"Source:     {row['source']}")
            self.io.write(f"Path:       {row['path']}")
            self.io.write(f"Status:     {row['status']}")
            if row.get("paratext_project"):
                self.io.write(f"Paratext:   {row['paratext_project']}")
            choice = self.io.choose(
                f"Configure {row['alias']}",
                (("1", f"{self.localizer.text('Use bundled')} {row['alias']}"), ("2", "Use detected Paratext SRC Project"), ("3", "Use other local resource"), ("4", "Show resource details"), ("B", "Back")),
            )
            if choice == "B":
                return
            try:
                if choice == "1":
                    configure_ol_resource(self.root, resource_id=resource_id, source="BUNDLED")
                elif choice == "2":
                    catalogue = load_paratext_catalog(self.root)
                    candidates = paratext_ol_candidates(catalogue, resource_id)
                    if not candidates:
                        self.io.write(f"No recognized {resource_id} Paratext SRC candidates are cataloged.")
                        self.io.write("Expected pattern: grcSRCv# for Greek or hboSRCv# for Hebrew.")
                        self.io.pause()
                        continue
                    options = [(str(index), f"{item['project_code']} - {item.get('full_name')} [{item.get('scope')}]") for index, item in enumerate(candidates, 1)] + [("B", "Back")]
                    selected = self.io.choose("Detected original-language Projects", options)
                    if selected == "B":
                        continue
                    item = candidates[int(selected) - 1]
                    configure_ol_resource(
                        self.root,
                        resource_id=resource_id,
                        source="PARATEXT",
                        path=Path(str(item["path"])),
                        paratext_project=str(item["project_code"]),
                    )
                elif choice == "3":
                    value = Path(normalize_operator_path(self.io.text("Absolute local original-language resource folder"))).expanduser()
                    configure_ol_resource(self.root, resource_id=resource_id, source="LOCAL", path=value)
                elif choice == "4":
                    self.io.write(json.dumps(row, indent=2, ensure_ascii=False, sort_keys=True))
                    self.io.pause()
                    continue
                updated = resolved_ol_entry(self.root, resource_id)
                self.io.write(f"{updated['alias']}: {updated['status']} from {updated['source']}")
                self.io.pause()
            except SageError as exc:
                self.show_error(exc)

    def original_language_resources_menu(self) -> None:
        """Manage stable governed OL aliases separately from ordinary Paratext Projects."""
        while True:
            status = validate_original_language_resources(self.root)
            self.io.write()
            self.io.write("ORIGINAL-LANGUAGE RESOURCES")
            self.io.write("-" * 72)
            for row in status["resources"]:
                suffix = f" ({row.get('paratext_project')})" if row.get("paratext_project") else ""
                self.io.write(f"{row['alias']:<5} {row['status']:<10} {row['source']}{suffix}")
            self.io.write(f"Capability: {status['status']}")
            choice = self.io.choose(
                "Original-language resources",
                (("1", "Greek [@GRK]"), ("2", "Hebrew [@HEB]"), ("3", "Validate resources"), ("4", "Restore bundled resources"), ("B", "Back")),
            )
            if choice == "B":
                return
            if choice == "1":
                self._configure_ol_resource_menu("GRK")
            elif choice == "2":
                self._configure_ol_resource_menu("HEB")
            elif choice == "3":
                for row in validate_original_language_resources(self.root)["resources"]:
                    self.io.write(json.dumps(row, indent=2, ensure_ascii=False, sort_keys=True))
                self.io.pause()
            elif choice == "4":
                if self.io.confirm("Restore both @GRK and @HEB to bundled defaults?", default=False):
                    restore_bundled_ol_defaults(self.root)
                    self.io.write("Bundled OL defaults restored.")
                    self.io.pause()

    def language_profiles_menu(self) -> None:
        """Browse first-class Language Profiles and maintain subordinate Grammar Profiles."""
        while True:
            config = load_ecosystem(self.store.settings_path)
            rows = sorted(config.language_profiles)
            options = []
            for index, tag in enumerate(rows, 1):
                status = language_profile_status(self.store.settings_path, tag)
                options.append((str(index), f"{tag:<14} {status['script'] or '?':<6} {status['status']}"))
            options.append(("B", "Back"))
            selected = self.io.choose("LANGUAGE PROFILES", tuple(options))
            if selected == "B":
                return
            tag = rows[int(selected) - 1]
            while True:
                status = language_profile_status(self.store.settings_path, tag)
                context = (
                    f"Language Profile              {tag}",
                    f"Script                        {status.get('script') or 'UNKNOWN'}",
                    f"Status                        {status.get('status')}",
                    "Grammar profiles              " + (", ".join(status.get("variants") or []) or "NONE"),
                )
                action = self.io.choose(
                    f"LANGUAGE PROFILE - {tag}",
                    (("1", "Maintain grammar profiles"), ("2", "Validate grammar profiles"), ("B", "Back")),
                    context=context,
                )
                if action == "B":
                    break
                if action == "1":
                    self.maintain_grammar_profiles(language=tag)
                elif action == "2":
                    self._validate_configured_grammar_profiles()
                    self.io.pause()

    def resource_menu(self) -> None:
        """System-level Project administration; Job roles are assigned only inside BIC/SAW."""
        while True:
            primary = load_resource_mount_state(self.root).get("projects_root")
            choice=self.io.choose("SCRIPTURE PROJECTS", (
                ("1","List / manage SAGE Scripture Projects"),
                ("2","Add Projects to SAGE"),
                ("3","Remove Project from SAGE"),
                ("4","Language Profiles"),
                ("5","Validate SAGE Projects"),
                ("6","Paratext Projects root"),
                ("7","Scan Paratext Projects"),
                ("8","Original-language resources"),
                ("9","Advanced resources"),
                ("B", "Back")), context=(f"Paratext Projects root: {primary or 'NOT CONFIGURED'}",))
            if choice=="B": return
            if choice=="1": self.registered_projects_menu()
            elif choice=="2": self.discover_register_projects_menu()
            elif choice=="3": self.remove_project_from_sage_menu()
            elif choice=="4": self.language_profiles_menu()
            elif choice=="5": self.validate_shared_registry()
            elif choice=="6": self.projects_root_menu()
            elif choice=="7": self.scan_rescan_projects_menu()
            elif choice=="8": self.original_language_resources_menu()
            elif choice=="9":
                advanced=self.io.choose("Advanced resources", (("1","Base VRS folder override"),("2","Use Paratext root for base VRS"),("3","RWC, SEMDOM, FLEx and Combine"),("4","Resource folders"),("B", "Back")))
                if advanced=="1":
                    value=Path(normalize_operator_path(self.io.text("Absolute base VRS folder"))).expanduser()
                    destination=set_base_vrs_root(self.root,base_vrs_root=value)
                    self.io.write(f"Base VRS override configured: {destination}")
                    self.io.pause()
                elif advanced=="2":
                    clear_base_vrs_root(self.root)
                    self.io.write("Base VRS root now follows the Paratext Projects root.")
                    self.io.pause()
                elif advanced=="3": self.rwc_menu()
                elif advanced=="4": self._system_show_paths()

    def rwc_menu(self) -> None:
        """Operate RWC/SEMDOM through task-oriented operator surfaces."""
        while True:
            choice = self.io.choose(
                "RWC, SEMDOM, FLEx AND COMBINE",
                (
                    ("1", "Status"),
                    ("2", "Update indexes"),
                    ("3", "Project bindings"),
                    ("4", "Source references"),
                    ("5", "Review evidence"),
                    ("6", "Build and validate indexes"),
                    ("7", "Export to FLEx or Combine"),
                    ("8", "Manage source data"),
                    ("B", "Back"),
                ),
            )
            if choice == "B":
                return
            try:
                if choice == "1":
                    self._rwc_show_status()
                elif choice == "2":
                    self._rwc_initialise()
                elif choice == "3":
                    self._rwc_bindings()
                elif choice == "4":
                    self._rwc_reference_sources()
                elif choice == "5":
                    self._rwc_review()
                elif choice == "6":
                    self._rwc_build_validate()
                elif choice == "7":
                    self._rwc_export()
                elif choice == "8":
                    self._rwc_advanced_sources()
            except SageError as exc:
                self.show_error(exc)
            self.io.pause()

    def _rwc_show_status(self) -> None:
        """Show one semantic namespace with explicit freshness and bindings."""
        config = load_ecosystem(self.store.settings_path)
        language = self.io.text("Semantic language")
        result = semantic_status(config, language=language)
        self.io.write(json.dumps({**result, "bindings": load_bindings(config)}, ensure_ascii=False, indent=2))

    def _rwc_initialise(self) -> None:
        """Bind primary/local project indexes and build their current indexes."""
        config = load_ecosystem(self.store.settings_path)
        project_id = self.choose_registered_project_id("Primary SAGE Project")
        language = self.io.text("Primary semantic language")
        if not load_import_selection(config, language):
            raise ValidationError(f"No active semantic imports exist for {language}; import reference sources first")
        set_binding(config, project_id=project_id, language=language)
        result: dict[str, Any] = {"bindings": {project_id: language}, "indexes": {}}
        result["indexes"][language] = build_semantic_indexes(config, language=language)
        if self.io.confirm("Bind and build a configured @GRK local project index too?", default=False):
            greek_project = active_ol_project_id(self.root, "GRK")
            if greek_project is None:
                raise ValidationError("Configured @GRK resource is not READY", code="OL_RESOURCE_NOT_READY", next_action="Configure @GRK under Scripture Projects > Original-language resources.")
            greek_language = self.io.text("Greek semantic language", default="grc")
            if not load_import_selection(config, greek_language):
                raise ValidationError(
                    f"No active governed project-index imports exist for {greek_language}"
                )
            set_binding(config, project_id=greek_project, language=greek_language)
            result["bindings"][greek_project] = greek_language
            result["indexes"][greek_language] = build_semantic_indexes(config, language=greek_language)
        self.io.write(json.dumps(result, ensure_ascii=False, indent=2))

    def _rwc_bindings(self) -> None:
        """List or set explicit Scripture-resource to semantic-namespace bindings."""
        config = load_ecosystem(self.store.settings_path)
        bindings = load_bindings(config)
        self.io.write("Current bindings:")
        self.io.write(json.dumps(bindings, ensure_ascii=False, indent=2))
        if not self.io.confirm("Add or replace a binding?", default=False):
            return
        project_id = self.choose_registered_project_id("SAGE Project")
        language = self.io.text("Semantic language")
        updated = set_binding(config, project_id=project_id, language=language)
        self.io.write(json.dumps(updated, ensure_ascii=False, indent=2))

    def _rwc_reference_sources(self) -> None:
        """Import immutable reference/authority sources without granting translation approval."""
        config = load_ecosystem(self.store.settings_path)
        choice = self.io.choose(
            "RWC reference sources",
            (
                ("1", "Import RWC seed XLSX"),
                ("2", "Import FLEx LIFT snapshot"),
                ("3", "Import Combine LIFT snapshot"),
                ("4", "Import SIL Semantic Domains JSON"),
                ("5", "Import RapidWords folders DOCX"),
                ("B", "Back"),
            ),
        )
        if choice == "B":
            return
        if choice == "1":
            path = Path(normalize_operator_path(self.io.text("RWC seed XLSX path"))).expanduser()
            source_id = self.io.text("Immutable source ID")
            language = self.io.text("Semantic language")
            result = import_rwc_seed_xlsx(config, path, source_id=source_id, language=language)
        elif choice in {"2", "3"}:
            application = "FLEx" if choice == "2" else "Combine"
            path = Path(normalize_operator_path(self.io.text(f"{application} LIFT path"))).expanduser()
            source_id = self.io.text("Immutable source ID")
            language = self.io.text("Semantic language")
            result = import_lift_snapshot(
                config,
                path,
                source_id=source_id,
                source_application=application,
                language=language,
            )
        elif choice == "4":
            path = Path(normalize_operator_path(self.io.text("SIL Semantic Domains JSON path"))).expanduser()
            result = import_semdom_authority_json(config, path)
        else:
            path = Path(normalize_operator_path(self.io.text("RapidWords folder divisions DOCX path"))).expanduser()
            result = import_specific_first_docx(config, path)
        self.io.write(json.dumps(result, ensure_ascii=False, indent=2))

    def _rwc_review(self) -> None:
        """Govern sense evidence states independently of imported source labels."""
        config = load_ecosystem(self.store.settings_path)
        language = self.io.text("Semantic language")
        choice = self.io.choose(
            "Semantic evidence review",
            (("1", "List reviewed senses"), ("2", "Set reviewed status"), ("3", "Clear reviewed status"), ("B", "Back")),
        )
        if choice == "B":
            return
        if choice == "1":
            self.io.write(json.dumps(load_review_states(config, language), ensure_ascii=False, indent=2))
            return
        lookup_form = self.io.text("Surface form to inspect", default="")
        if lookup_form:
            lookup = evidence_for_form(config, language=language, form=lookup_form)
            self.io.write(json.dumps(lookup, ensure_ascii=False, indent=2))
        sense_id = self.io.text("Sense ID")
        if choice == "3":
            self.io.write(json.dumps(clear_review_state(config, language=language, sense_id=sense_id), indent=2))
            self.io.write("Index state is now STALE; rebuild before BIC, SAW, or export.")
            return
        status_choice = self.io.choose(
            "Reviewed status",
            tuple((str(index), status) for index, status in enumerate(REVIEW_STATES, 1)),
        )
        status = REVIEW_STATES[int(status_choice) - 1]
        reviewer = self.io.text("Reviewer or role")
        note = self.io.text("Review note", default="")
        result = set_review_state(
            config,
            language=language,
            sense_id=sense_id,
            status=status,
            reviewer=reviewer,
            note=note,
        )
        self.io.write(json.dumps(result, ensure_ascii=False, indent=2))
        self.io.write("Index state is now STALE; rebuild before BIC, SAW, or export.")

    def _rwc_build_validate(self) -> None:
        """Show freshness and rebuild one local semantic namespace when requested."""
        config = load_ecosystem(self.store.settings_path)
        language = self.io.text("Semantic language")
        before = semantic_status(config, language=language)
        self.io.write(f"Index state: {before.get('index_state')}")
        if before.get("index_state") == "CURRENT" and not self.io.confirm("Rebuild current indexes anyway?", default=False):
            return
        result = build_semantic_indexes(config, language=language)
        self.io.write(json.dumps(result, ensure_ascii=False, indent=2))

    def _rwc_export(self) -> None:
        """Generate an explicit status-filtered FLEx or Combine LIFT view."""
        config = load_ecosystem(self.store.settings_path)
        profile_choice = self.io.choose("Export profile", (("1", "FLEx"), ("2", "Combine"), ("B", "Back")))
        if profile_choice == "B":
            return
        view_choice = self.io.choose(
            "Evidence-state export view",
            tuple((str(index), view) for index, view in enumerate(EXPORT_VIEWS, 1)),
        )
        view = tuple(EXPORT_VIEWS)[int(view_choice) - 1]
        language = self.io.text("Semantic language")
        result = export_lift(
            config,
            language=language,
            profile="flex" if profile_choice == "1" else "combine",
            view=view,
        )
        self.io.write(json.dumps(result, ensure_ascii=False, indent=2))

    def _rwc_advanced_sources(self) -> None:
        """Expose snapshot activation and authority selection away from the normal operator path."""
        config = load_ecosystem(self.store.settings_path)
        choice = self.io.choose(
            "Advanced RWC source management",
            (("1", "Set imported snapshot state"), ("2", "Choose SEMDOM or folder authority"), ("B", "Back")),
        )
        if choice == "B":
            return
        if choice == "1":
            language = self.io.text("Semantic language")
            source_id = self.io.text("Immutable source ID")
            state = self.io.choose("Import state", (("1", "Active"), ("2", "Inactive"), ("B", "Back")))
            if state == "B":
                return
            active = set_import_active(config, language=language, source_id=source_id, active=state == "1")
            self.io.write(json.dumps({"active_imports": active}, ensure_ascii=False, indent=2))
            self.io.write("Any existing index is now STALE until rebuilt.")
            return
        authority_type = self.io.choose(
            "Authority type", (("1", "SIL Semantic Domains"), ("2", "RapidWords folders"), ("B", "Back"))
        )
        if authority_type == "B":
            return
        source_id = self.io.text("Imported authority source ID")
        active = set_authority_selection(
            config,
            authority_type="semdom" if authority_type == "1" else "folders",
            source_id=source_id,
        )
        self.io.write(json.dumps({"active_authority": active}, ensure_ascii=False, indent=2))
        self.io.write("Any existing index is now STALE until rebuilt.")

    def validate_shared_registry(self) -> None:
        """Validate packaged VRS plus every SAGE and mapped Scripture Project."""
        try:
            self._setup_scripture_resource_status(render=True)
        except SageError as exc:
            self.show_error(exc)
            return
        self.io.pause()

    def export_global_diagnostics(self, *, pause: bool = True) -> Path:
        """Export global diagnostics and optionally pause before returning the report path."""
        destination = self.store.state_root / "diagnostics" / "menu-diagnostics.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sage_root": str(self.root),
            "settings": str(self.store.settings_path),
            "active_jobs": self.store.active_jobs(),
            "last_run": _json_file(self.store.last_run_path),
            "setup_state": self.store.setup_state(),
            "llm": {
                "settings": load_llm_settings(self.root),
                "providers": ModelService(self.root).status()["providers"],
                "local_admin": self.ollama_admin.status().to_dict(),
            },
            "resource_mounts": load_resource_mounts(self.root),
            "jobs": [
                {
                    "job_id": project.job_id,
                    "tool": project.tool,
                    "root": str(project.root),
                    "runtime_settings": str(project.runtime_settings_path),
                }
                for project in self.store.discover(include_archived=True)
            ],
        }
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.io.write(f"Diagnostics: {operator_path(self.root, destination)}")
        if pause:
            self.io.pause()
        return destination

    # ---------- Display helpers ----------

    def print_payload(self, payload: Any) -> None:
        """Implement `print payload` in the deterministic terminal control flow."""
        self.io.write(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        self.io.pause()

    def list_files(self, root: Path, *, patterns: Sequence[str]) -> None:
        """Implement `list files` in the deterministic terminal control flow."""
        if not root.exists():
            self.io.write(f"Directory does not exist: {root}")
            self.io.pause()
            return
        found: set[Path] = set()
        for pattern in patterns:
            found.update(path for path in root.rglob(pattern) if path.is_file())
        if not found:
            self.io.write(f"No matching files under {root}")
        else:
            for path in sorted(found):
                self.io.write(_relative(self.root, path))
        self.io.pause()

    def show_error(self, exc: SageError) -> None:
        """Render an actionable operator error: event, impact, and next action."""
        self.io.write("SAGE ERROR")
        self.io.write("-" * 72)
        self.io.write(f"What happened: {operator_text(self.root, exc.message)}")
        self.io.write(f"Reason code:   {exc.code}")
        self.io.write("Why it matters: The requested action did not complete; existing governed Project and Job data was not silently changed.")
        if exc.next_action:
            self.io.write(f"Next action:   {operator_text(self.root, exc.next_action)}")
        else:
            self.io.write("Next action:   Review the details above, correct the indicated configuration or input, and retry.")
        self.io.pause()

# Keep YAML imports local to the rarely used archive operation.
def load_yaml_compat(path: Path) -> dict[str, Any]:
    """Implement `load yaml compat` in the deterministic terminal control flow."""
    import yaml

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError(f"YAML root must be a mapping: {path}")
    return value


def yaml_dump_compat(value: dict[str, Any]) -> str:
    """Implement `yaml dump compat` in the deterministic terminal control flow."""
    import yaml

    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)


def run_setup(
    *,
    sage_root: Path,
    settings_path: Path | None = None,
    script_path: Path | None = None,
) -> int:
    """Run only the guided first-use setup, then return to the shell."""
    io = MenuIO()
    if script_path is not None:
        values = script_path.read_text(encoding="utf-8").splitlines()
        io = MenuIO(input_func=ScriptedInput(values))
    center = SageControlCenter(
        sage_root=sage_root,
        settings_path=settings_path,
        io=io,
        force_setup=True,
    )
    try:
        center.guided_setup(pause_at_end=False)
    except (MenuHomeRequested, MenuExitRequested):
        pass
    return 0


def run_menu(
    *,
    sage_root: Path,
    settings_path: Path | None = None,
    script_path: Path | None = None,
    force_setup: bool = False,
    skip_setup: bool = False,
    dry_run_provider: bool = False,
) -> int:
    """Run the menu with terminal or scripted input."""
    io = MenuIO()
    if script_path is not None:
        values = script_path.read_text(encoding="utf-8").splitlines()
        io = MenuIO(input_func=ScriptedInput(values))
    center = SageControlCenter(
        sage_root=sage_root,
        settings_path=settings_path,
        io=io,
        force_setup=force_setup,
        skip_setup=skip_setup,
        dry_run_provider=dry_run_provider,
    )
    return center.run()
