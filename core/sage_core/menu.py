"""Menu-driven SAGE Control Center for Job-scoped BIC and SAW operation."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, TextIO

from .atomic import atomic_write_text
from .external_access import READ_ONLY_SCRIPTURE, READ_WRITE_SCRIPTURE, READ_WRITE_TARGET
from .errors import ConfigurationError, InputRequiredError, OperatorCancelledError, SageError, ValidationError
from .hashing import sha256_file
from .llm_settings import load_llm_settings
from .iso_languages import iso_language
from .model_service import ModelService
from .executors.codex_cli import CodexCLIExecutor
from .references import parse_scope
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
from .registry import load_ecosystem
from .semantic import (
    build_semantic_indexes,
    export_lift,
    import_greek_reference_xlsx,
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
from .jobs import (
    TOOL_IDS,
    Job as Job,
    JobStore as JobStore,
    Run as Run,
    default_job_name,
)
from .project_inventory import (
    clear_project_reporting_languages, load_project_registry, registered_project_records,
    set_project_reporting_languages, unregister_project, update_project_record, summarize_scope, scope_testament,
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
class MenuIO:
    """Small injectable terminal I/O surface used by the interactive menu and tests."""

    input_func: Callable[[str], str] = input
    output: TextIO = sys.stdout

    def write(self, value: str = "") -> None:
        """Implement `write` in the deterministic terminal control flow."""
        print(value, file=self.output)

    def status(self, value: str) -> None:
        """Render one replaceable terminal status line for bounded long-running local work."""
        print(f"\r{value}", end="", file=self.output, flush=True)

    def clear_status(self) -> None:
        """Finish the current replaceable status line."""
        print(file=self.output, flush=True)

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
        prompt: str = "Select: ",
        allow_blank: bool = False,
        direct_validator: Callable[[str], str] | None = None,
    ) -> str:
        """Choose a listed key or return one validated direct-entry value when enabled."""
        self.write()
        self.write(title)
        self.write("-" * max(44, len(title)))
        valid = {key.casefold(): key for key, _ in options}
        for key, label in options:
            self.write(f"{key}. {label}")
        while True:
            value = self.read(prompt).strip()
            if allow_blank and not value:
                return ""
            key = valid.get(value.casefold())
            if key is not None:
                return key
            if direct_validator is not None:
                try:
                    return direct_validator(value)
                except SageError:
                    pass
            self.write("Invalid selection. Choose one listed option.")

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
            value = self.read(f"{label}{suffix}: ").strip()
            if not value and default is not None:
                value = default
            if not value and required:
                self.write(f"{label} is required.")
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
        while True:
            value = self.read(f"{prompt} [{marker}]: ").strip().casefold()
            if not value:
                return default
            if value in {"y", "yes"}:
                return True
            if value in {"n", "no"}:
                return False
            self.write("Enter yes or no.")

    def pause(self) -> None:
        """Implement `pause` in the deterministic terminal control flow."""
        self.read("Press Enter to continue...")


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
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


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
        self.force_setup = force_setup
        self.skip_setup = skip_setup
        self.dry_run_provider = dry_run_provider

    # ---------- Controller bridge ----------

    def controller(self, project: Job, arguments: Sequence[str]) -> Any:
        """Run one canonical controller command against a Job-scoped config."""
        settings = self.store.ensure_runtime_files(project)
        command = [
            sys.executable,
            "-m",
            "sage_core.cli",
            "--settings",
            str(settings),
            "--json",
            "--no-prompt",
            *arguments,
        ]
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
        env["SAGE_DISABLE_HUMAN_CONSOLE"] = "1"
        core_path = str(self.root / "core")
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
        return read_state(ecosystem_state_path(config.workspace_data_root))

    def ensure_initialized(self, project: Job, *, force: bool = False) -> dict[str, Any]:
        """Implement `ensure initialised` in the deterministic terminal control flow."""
        settings = self.store.ensure_runtime_files(project)
        config = load_ecosystem(settings)
        state = read_state(ecosystem_state_path(config.workspace_data_root))
        settings_hash = sha256_file(settings)
        if (
            not force
            and state.get("state") in {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}
            and state.get("settings_sha256") == settings_hash
        ):
            return state
        self.io.write(f"Initialising {project.display_name}...")
        payload = self.controller(project, ["workspace", "initialize"])
        return dict(payload) if isinstance(payload, dict) else {}

    # ---------- Setup ----------

    def setup_required(self, model_row: dict[str, Any] | None = None) -> bool:
        """Return whether live prerequisites still require guided setup."""
        state = self.store.setup_state()
        if self.force_setup:
            return True
        if self.skip_setup:
            return False
        if not state:
            return True
        if state.get("status") == "COMPLETE":
            return False
        scripture = state.get("scripture_resources")
        if not isinstance(scripture, dict) or scripture.get("status") not in {"READY", "READY_EMPTY"}:
            return True
        live_results = self._setup_live_initialisation_results(
            state.get("initialisation") if isinstance(state.get("initialisation"), dict) else None
        )
        provider = dict(state.get("llm") or {})
        if model_row is not None:
            provider.update(model_row)
        next_step, next_label = self._setup_next_step(
            provider,
            self._setup_configured_tools(),
            live_results,
            scripture,
        )
        if next_step != "COMPLETE":
            return True
        refreshed = {
            key: value
            for key, value in state.items()
            if key not in {"schema_version", "updated_utc"}
        }
        refreshed.update(
            {
                "status": "COMPLETE",
                "next_step": next_step,
                "next_label": next_label,
                "active_jobs": self.store.active_jobs(),
                "enabled_tools": sorted(self._setup_configured_tools()),
                "initialisation": live_results,
                "llm": provider,
            }
        )
        self.store.write_setup_state(refreshed)
        return False

    def _setup_document_paths(self) -> tuple[str, str, str]:
        """Return the platform cheat-sheet, recovery, and error references."""
        folder = "windows" if os.name == "nt" else "macos-linux"
        return (
            f"docs/{folder}/CHEAT-SHEET.md",
            f"docs/{folder}/RECOVERY.md",
            f"docs/{folder}/ERRORS.md",
        )

    def _setup_model_probe(self, service: ModelService) -> dict[str, Any]:
        """Return a lightweight Codex installation/authentication row for startup and setup."""
        try:
            return dict(service.quick_codex_status())
        except SageError as exc:
            return {"available": False, "ready": False, "diagnostic": exc.message, "reason_code": exc.code}

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
            return self._setup_model_probe(service)
        self.store.record_cue("CODEX_INSTALL_APPROVED")
        self.io.write("Running the official Codex CLI installer in non-interactive mode...")
        result = service.install_codex()
        self.io.write("Codex CLI verified. Returning to SAGE; the Codex interactive shell was not launched.")
        return dict(result)

    def _setup_configured_tools(self) -> set[str]:
        """Return workflows that currently have one active project binding."""
        return {tool for tool in TOOL_IDS if self.store.active_job(tool) is not None}

    def _setup_workflow_status(self, tool: str, init_results: dict[str, Any]) -> str:
        """Return one concise independent setup status for BIC or SAW."""
        project = self.store.active_job(tool)
        if project is None:
            return "NOT CONFIGURED"
        ready_states = {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}
        status = str(init_results.get(project.job_id, {}).get("status", ""))
        if status in ready_states:
            return f"READY - {project.display_name}"
        return f"CONFIGURED - {project.display_name} (validation needed)"

    def _setup_live_initialisation_results(
        self,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reconcile setup summaries with each active Job's current state receipt."""
        prior = dict(previous or {})
        results: dict[str, Any] = {}
        ready_states = {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}
        for tool in TOOL_IDS:
            project = self.store.active_job(tool)
            if project is None:
                continue
            try:
                settings = self.store.ensure_runtime_files(project)
                config = load_ecosystem(settings)
                state = read_state(ecosystem_state_path(config.workspace_data_root))
                status = str(state.get("state") or state.get("status") or "NOT_INITIALISED")
                current_override_hash = (
                    sha256_file(config.operator_overrides_path)
                    if config.operator_overrides_path and config.operator_overrides_path.is_file()
                    else None
                )
                stale = bool(state) and (
                    state.get("settings_sha256") != sha256_file(settings)
                    or state.get("operator_overrides_sha256") != current_override_hash
                )
                if stale:
                    status = "STALE"
                results[project.job_id] = {
                    **dict(prior.get(project.job_id) or {}),
                    "status": status,
                    "source": "JOB_INITIALISATION_RECEIPT",
                    "ready": status in ready_states,
                }
            except SageError as exc:
                results[project.job_id] = {
                    "status": "BLOCKED",
                    "reason_code": exc.code,
                    "message": exc.message,
                    "source": "JOB_INITIALISATION_RECEIPT",
                    "ready": False,
                }
        return results

    def _setup_initialize_projects(self) -> dict[str, Any]:
        """Initialise selected projects and report blocked actions without leaving setup."""
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
            self.io.write("No active BIC or SAW job is selected yet.")
        return results

    def _setup_next_step(
        self,
        model_row: dict[str, Any],
        enabled_tools: set[str],
        init_results: dict[str, Any],
        scripture_resources: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Return the recommended next setup action without requiring both workflows."""
        if scripture_resources and scripture_resources.get("status") == "BLOCKED":
            return "VALIDATE_SCRIPTURE", "Resolve Scripture resource validation"
        if not model_row.get("available"):
            return "INSTALL_CODEX", "Install Codex CLI"
        if not model_row.get("ready"):
            return "LOGIN_CHATGPT", "Sign in with ChatGPT"
        configured_tools = self._setup_configured_tools()
        if not configured_tools:
            return "CONFIGURE_WORKFLOW", "Configure BIC or SAW"
        ready_states = {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}
        for tool in sorted(configured_tools):
            project = self.store.active_job(tool)
            if project is None:
                continue
            status = str(init_results.get(project.job_id, {}).get("status", ""))
            if status not in ready_states:
                return "VALIDATE", "Validate and initialise configured workflow(s)"
        return "COMPLETE", "SAGE is ready"

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
                    "auth_mode": model_row.get("auth_mode"),
                    "version": model_row.get("version"),
                    "selected_model": provider_item.get("model"),
                    "selected_reasoning_effort": provider_item.get("reasoning_effort"),
                    "diagnostic": model_row.get("diagnostic"),
                },
                "initialisation": init_results,
                "scripture_resources": scripture_resources,
                "operator_docs": list(self._setup_document_paths()),
            }
        )
        return next_step, next_label

    def _setup_scripture_resource_status(self, *, render: bool = False) -> dict[str, Any]:
        """Validate Scripture/VRS resources and optionally render the first-run summary."""
        result = validate_scripture_resources(self.root, self.store.settings_path)
        if render:
            self.io.write()
            self.io.write("SCRIPTURE RESOURCE CHECK")
            self.io.write("-" * 72)
            self.io.write(f"Status:              {result['status']}")
            self.io.write(f"Base VRS files:      {sum(1 for row in result['base_vrs'] if row['status'] == 'READY')}/{len(result['base_vrs'])} READY")
            self.io.write(f"SAGE Projects:      {result['registered_projects']}")
            self.io.write(f"Mapped projects:     {result['mapped_projects']}")
            self.io.write(f"Projects root:       {result.get('projects_root') or 'NOT CONFIGURED'}")
            catalogue = result.get("catalogue", {})
            self.io.write(
                f"Paratext catalogue:  {catalogue.get('projects', 0)} Projects / "
                f"{catalogue.get('languages', 0)} languages"
            )
            ol = result.get("original_language", {})
            self.io.write(f"OL capability:       {ol.get('status', 'UNKNOWN')}")
            for row in ol.get("resources", []):
                self.io.write(f"  {row['alias']}: {row['status']} [{row['source']}]")
            if result["status"] == "READY_EMPTY":
                self.io.write("Project inventory is empty by design for a clean RC start.")
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

    def _setup_review_menu(
        self,
        service: ModelService,
        enabled_tools: set[str],
        init_results: dict[str, Any],
    ) -> tuple[set[str], dict[str, Any]]:
        """Review or change setup details without reintroducing workflow-selection duplication."""
        while True:
            choice = self.io.choose(
                "Review / Change Setup",
                (
                    ("1", "OpenAI / ChatGPT connection"),
                    ("2", "BIC job configuration"),
                    ("3", "SAW job configuration"),
                    ("4", "Scripture Projects / VRS / advanced resources"),
                    ("5", "Advanced model settings"),
                    ("6", "Validate and initialise configured workflows"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
                return self._setup_configured_tools(), init_results
            if choice == "1":
                row = self._setup_model_probe(service)
                if not row.get("available"):
                    self._setup_install_codex(service)
                else:
                    self._model_connect_chatgpt(service)
            elif choice == "2":
                self.job_management_menu("bic")
            elif choice == "3":
                self.job_management_menu("saw")
            elif choice == "4":
                self.resource_menu()
            elif choice == "5":
                self.model_menu()
            elif choice == "6":
                init_results = self._setup_initialize_projects()
                self.io.pause()
            enabled_tools = self._setup_configured_tools()

    def _show_support_docs(self) -> None:
        """Show only the platform-specific fallback cheat sheets."""
        self.io.write("SAGE normally guides setup and operation in the terminal.")
        self.io.write("Use these only for recovery, errors, or command lookup:")
        for path in self._setup_document_paths():
            self.io.write(f"  {path}")
        self.io.pause()

    def _system_runtime_status(self, service: ModelService) -> None:
        """Show compact runtime/dependency state without launching any interactive provider shell."""
        self.io.write(f"Python: {sys.version.split()[0]}")
        self.io.write(f"Managed .venv: {self.root / '.venv'}")
        self.io.write(f".venv present: {'YES' if (self.root / '.venv').is_dir() else 'NO'}")
        try:
            import yaml
            self.io.write(f"PyYAML: {getattr(yaml, '__version__', 'installed')}")
        except ImportError:
            self.io.write("PyYAML: MISSING")
        row = self._setup_model_probe(service)
        self.io.write(f"Codex CLI: {'INSTALLED' if row.get('available') else 'MISSING'}")
        if row.get("version"):
            self.io.write(f"Codex version: {row['version']}")
        self.io.write(f"ChatGPT: {'CONNECTED' if row.get('ready') else 'ACTION NEEDED'}")
        self.io.write("Runtime rule: SAGE is the parent process; Codex is invoked only for login or AI work.")
        self.io.pause()

    def _system_show_paths(self) -> None:
        """Show the small set of paths needed for configuration and recovery."""
        config = load_ecosystem(self.store.settings_path)
        self.io.write(f"SAGE root: {self.root}")
        self.io.write(f"Settings: {self.store.settings_path}")
        self.io.write(f"Workspace data: {config.workspace_data_root}")
        self.io.write(f"State: {self.store.state_root}")
        self.io.write(f"SAGE Project Inventory: {self.root / 'state' / 'project-inventory.json'}")
        self.io.write(f"External resource mappings: {self.root / 'state' / 'resource-mounts.json'}")
        self.io.write(f"Jobs: {self.root / 'jobs'}")
        self.io.pause()

    def _scan_progress(self, done: int, total: int) -> None:
        """Show the RC7.04 single-line Paratext scan heartbeat."""
        spinner = "|/-\\"
        marker = spinner[done % len(spinner)]
        suffix = f" {done}/{total}" if total else ""
        self.io.status(f"Scanning Paratext Projects... {marker}{suffix}")

    def _scan_projects(self, projects_root: Path, *, full: bool) -> dict[str, Any]:
        """Scan Paratext Projects with a visible heartbeat and finish on a normal line."""
        try:
            return scan_paratext_projects(
                self.root,
                projects_root,
                full=full,
                progress=self._scan_progress,
            )
        finally:
            self.io.clear_status()

    def _run_with_status(self, message: str, action: Callable[[], Any]) -> Any:
        """Run one blocking local action while rotating a bounded terminal heartbeat."""
        frames = "|/-\\"
        frame = 0
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

    def paths_and_workspace_menu(self) -> None:
        """Configure operator paths, including the primary Paratext/PTLite Projects root."""
        while True:
            config = load_ecosystem(self.store.settings_path)
            state = load_resource_mount_state(self.root)
            primary = state.get("projects_root")
            self.io.write()
            self.io.write("PATHS AND WORKSPACE LOCATIONS")
            self.io.write("-" * 72)
            self.io.write(f"Paratext/PTLite Projects root: {primary or 'NOT CONFIGURED'}")
            self.io.write(f"Internal Scripture projects:  {config.projects_root}")
            base_mode = "[override]" if state.get("base_vrs_root") else "[default: Paratext root]"
            self.io.write(f"Base VRS root:                {config.base_vrs_root} {base_mode}")
            self.io.write(f"Workspace data:               {config.workspace_data_root}")
            self.io.write(f"State:                        {self.store.state_root}")
            choice = self.io.choose(
                "Paths and workspace locations",
                (("1", "Set / change Paratext/PTLite Projects root"), ("2", "Configure base VRS root override"), ("3", "Use Paratext Projects root as base VRS default"), ("4", "Show state / inventory paths"), ("0", "Back")),
            )
            if choice == "0":
                return
            if choice == "1":
                value = Path(normalize_operator_path(self.io.text("Paratext/PTLite Projects root"))).expanduser()
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
            elif choice == "4":
                self._system_show_paths()

    def system_configuration_menu(self) -> str:
        """Keep system administration separate from BIC/SAW Job work."""
        while True:
            choice = self.io.choose(
                "SYSTEM / CONFIGURATION",
                (
                    ("1", "Scripture Projects - Project Catalogue, SAGE Projects and validation"),
                    ("2", "Paths and storage - Paratext root, workspace and VRS locations"),
                    ("3", "Reporting languages - global bilingual report defaults"),
                    ("4", "Original-language resources - configure @GRK and @HEB"),
                    ("5", "LLM / provider settings - connection, model and provider access"),
                    ("6", "Advanced linguistic resources - RWC, semantic domains, FLEx and Combine"),
                    ("7", "System diagnostics - runtime, dependencies, paths and configuration checks"),
                    ("8", "About / version information"),
                    ("B", "Back"), ("M", "Main Menu"), ("0", "Exit SAGE"),
                ),
            )
            if choice == "B": return "BACK"
            if choice == "M": return "MAIN"
            if choice == "0": return "EXIT"
            try:
                if choice == "1": self.resource_menu()
                elif choice == "2": self.paths_and_workspace_menu()
                elif choice == "3": self.reporting_languages_menu()
                elif choice == "4": self.original_language_resources_menu()
                elif choice == "5": self.model_menu()
                elif choice == "6": self.rwc_menu()
                elif choice == "7": self.system_diagnostics_menu()
                elif choice == "8":
                    from . import __version__
                    self.io.write(f"SAGE version: {__version__}")
                    self.io.write("Provider policy: Codex CLI with ChatGPT login; no OpenAI API keys.")
                    self.io.write("Process model: shell -> SAGE -> bounded Codex subprocesses.")
                    self.io.pause()
            except SageError as exc:
                self.show_error(exc)

    def reporting_languages_menu(self) -> None:
        """Configure global bilingual report defaults; the operator UI remains English."""
        while True:
            config = load_ecosystem(self.store.settings_path)
            logs = config.human_output.logs_and_reports
            self.io.write()
            self.io.write("REPORTING LANGUAGES")
            self.io.write("-" * 72)
            self.io.write("SAGE's interface is English. Generated reports can use two languages.")
            self.io.write(f"Primary:      {logs.primary_language}")
            self.io.write(f"Secondary:    {logs.secondary_language or 'NONE'}")
            self.io.write(f"Bilingual:    {'ON' if logs.bilingual else 'OFF'}")
            choice = self.io.choose("Global reporting defaults", (("1", "Change primary reporting language"), ("2", "Change secondary reporting language"), ("3", "Toggle bilingual reports"), ("4", "Preview reporting configuration"), ("0", "Back")))
            if choice == "0": return
            if choice == "4":
                self.io.write(f"Primary report text: {logs.primary_language}")
                self.io.write(f"Secondary report text: {logs.secondary_language or 'NONE'}")
                self.io.write("Individual SAGE Projects may override these report languages.")
                self.io.pause()
                continue
            raw = load_yaml_compat(self.store.settings_path)
            human = dict(raw.get("human_output") or {})
            out = dict(human.get("logs_and_reports") or {})
            challenges = dict(human.get("translation_challenges") or {})
            if choice == "1": out["primary_language"] = self.io.text("Primary reporting language", default=logs.primary_language)
            elif choice == "2": out["secondary_language"] = self.io.text("Secondary reporting language", default=logs.secondary_language or "")
            elif choice == "3": out["bilingual"] = not logs.bilingual
            # Translation-challenge reports invert the pair so translation language appears first.
            challenges["primary_language"] = out.get("secondary_language") or out.get("primary_language")
            challenges["secondary_language"] = out.get("primary_language")
            challenges["bilingual"] = bool(out.get("bilingual", True))
            human["operator_language"] = "en"
            human["logs_and_reports"] = out
            human["translation_challenges"] = challenges
            raw["human_output"] = human
            self.store.settings_path.write_text(yaml_dump_compat(raw), encoding="utf-8")
            load_ecosystem(self.store.settings_path)
            self.io.write("Reporting defaults saved. Job runtime configuration will refresh automatically.")
            self.io.pause()

    def system_diagnostics_menu(self) -> None:
        """Run focused or complete system checks with human-readable results."""
        service = ModelService(self.root)
        while True:
            choice = self.io.choose("SYSTEM DIAGNOSTICS", (("1", "Validate runtime and Python environment"), ("2", "Validate SAGE configuration"), ("3", "Validate Scripture Projects"), ("4", "Validate original-language resources"), ("5", "Validate provider / authentication"), ("6", "Show configured paths"), ("7", "Run complete system check"), ("0", "Back")))
            if choice == "0": return
            try:
                if choice == "1": self._system_runtime_status(service)
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
                    row = self._setup_model_probe(service)
                    self.io.write(f"Provider: {'READY' if row.get('ready') else 'ACTION NEEDED'}")
                    self.io.pause()
                elif choice == "6": self._system_show_paths()
                elif choice == "7":
                    load_ecosystem(self.store.settings_path)
                    scripture = self._setup_scripture_resource_status()
                    ol = validate_original_language_resources(self.root)
                    provider = self._setup_model_probe(service)
                    self.io.write()
                    self.io.write("SYSTEM CHECK")
                    self.io.write("-" * 72)
                    self.io.write("Runtime                  READY")
                    self.io.write(f"Paratext catalogue       {scripture.get('catalogue', {}).get('projects', 0)} Projects")
                    self.io.write(f"SAGE Projects            {scripture.get('registered_projects', 0)}")
                    self.io.write(f"Original languages       {ol.get('status', 'UNKNOWN')}")
                    self.io.write(f"Provider                 {'READY' if provider.get('ready') else 'ACTION NEEDED'}")
                    self.io.write(f"Overall                  {scripture.get('status', 'UNKNOWN')}")
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
            existing.get("initialisation") if isinstance(existing.get("initialisation"), dict) else None
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
            self.io.write("SETUP STATUS")
            self.io.write("-" * 72)
            self.io.write(f"Codex CLI: {'INSTALLED' if model_row.get('available') else 'MISSING'}")
            self.io.write(f"ChatGPT:   {'CONNECTED' if model_row.get('ready') else 'ACTION NEEDED'}")
            self.io.write(
                f"Scripture: {scripture_resources['status']} "
                f"({scripture_resources['registered_projects']} SAGE Projects)"
            )
            self.io.write(f"BIC:       {self._setup_workflow_status('bic', init_results)}")
            self.io.write(f"SAW:       {self._setup_workflow_status('saw', init_results)}")
            self.io.write(f"Next:      {next_label}")

            system_label = "System / configuration"
            if next_step in {"INSTALL_CODEX", "LOGIN_CHATGPT", "VALIDATE_SCRIPTURE"}:
                system_label += f" [Recommended: {next_label}]"
            choice = self.io.choose(
                "Setup",
                (
                    ("1", "Configure BIC"),
                    ("2", "Configure SAW"),
                    ("3", "Review / change setup"),
                    ("4", "Recovery / error cheat sheets"),
                    ("5", system_label),
                    ("6", "Go to Main Menu - settings save automatically"),
                    ("0", "Exit SAGE"),
                ),
            )
            if choice == "6":
                break
            if choice == "0":
                exit_requested = True
                break
            try:
                if choice == "1":
                    self.job_management_menu("bic")
                elif choice == "2":
                    self.job_management_menu("saw")
                elif choice == "3":
                    enabled_tools, init_results = self._setup_review_menu(service, enabled_tools, init_results)
                elif choice == "4":
                    self._show_support_docs()
                elif choice == "5":
                    destination = self.system_configuration_menu()
                    if destination == "EXIT":
                        exit_requested = True
                        break
                    if destination == "MAIN":
                        break
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
        self.io.write(f"Setup state: {status}")
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
        startup = self._setup_model_probe(service)
        if not self.skip_setup and (self.setup_required(startup) or not startup.get("ready")):
            if self.guided_setup(pause_at_end=False):
                self.store.record_cue("SAGE_EXITED")
                return 0
        while True:
            choice = self.main_menu()
            self.store.record_cue("MAIN_MENU_SELECTED", selection=choice)
            if choice == "1": self.resource_menu()
            elif choice == "2": self.bic_menu()
            elif choice == "3": self.saw_menu()
            elif choice == "4": self.reports_home_menu()
            elif choice == "5":
                destination = self.system_configuration_menu()
                if destination == "EXIT":
                    self.store.record_cue("SAGE_EXITED")
                    return 0
            elif choice == "6": self.operator_guide_menu()
            elif choice == "7": self.global_menu()
            elif choice == "0":
                self.store.record_cue("SAGE_EXITED")
                return 0

    def reports_home_menu(self) -> None:
        """Choose a Job before entering its generated reports/history surface."""
        while True:
            choice = self.io.choose("REPORTS", (("1", "BIC reports / history"), ("2", "SAW reports / history"), ("0", "Back")))
            if choice == "0": return
            tool = "bic" if choice == "1" else "saw"
            project = self.store.active_job(tool) or self.choose_job(tool)
            if project is not None: self.reports_menu(project)

    def operator_guide_menu(self) -> None:
        """Mirror the live menu vocabulary and point to detailed platform references."""
        while True:
            choice = self.io.choose("HELP / OPERATOR GUIDE", (
                ("1", "First-time setup"), ("2", "Add a Paratext Project to SAGE"),
                ("3", "Create a BIC Job"), ("4", "Create a SAW Job"),
                ("5", "Enter Scripture ranges"), ("6", "Understand token splitting"),
                ("7", "Project validation statuses"), ("8", "Reporting languages"),
                ("9", "Greek / Hebrew resources"), ("10", "CLI / recovery references"), ("0", "Back")))
            if choice == "0": return
            guides = {
                "1": "Configure paths and resources first; Project addition and Job setup are separate tasks.",
                "2": "Scripture Projects > Add Projects to SAGE. Scan, select, review metadata, then add. No Job role is assigned here.",
                "3": "BIC > Add BIC Job. Assign a SAGE Project as SOURCE, DONOR and TARGET; only TARGET receives governed write access.",
                "4": "SAW > Add SAW Job. Assign a SAGE Project as WIP and another as REFERENCE.",
                "5": "Choose a Book, then leave range blank for the whole book or enter 1, 1-3, 1:1-10, or 1:1-2:20. Expert entry such as LUK 1:1-10 remains available.",
                "6": "Before a Run, SAGE shows the bounded work-unit plan and estimated tokens per section.",
                "7": "READY can be used directly; WARNING is usable with a disclosed issue; ERROR requires correction before affected work.",
                "8": "Generated reports may use global bilingual defaults or a Project-level reporting override. The UI remains English.",
                "9": "@GRK and @HEB are governed original-language resources and are not ordinary SAGE Projects.",
            }
            if choice == "10": self._show_support_docs()
            else:
                self.io.write(guides[choice])
                self.io.pause()

    def _job_summary(self, tool: str) -> str:
        """Return one compact active-Job readiness summary."""
        project = self.store.active_job(tool)
        if project is None:
            return "NONE"
        state = self.project_state(project)
        readiness = str(state.get("state", "NOT INITIALISED")).replace("_", " ")
        return f"{project.display_name} [{readiness}]"

    def _last_run_summary(self) -> str:
        """Return one compact last-Run summary."""
        item = self.store.last_run()
        if not item:
            return "NONE"
        project, run = item
        return f"{run.tool.upper()} {project.display_name} / {run.scope} [{run.current_stage}: {run.status}]"

    def _last_run_is_resumable(self) -> bool:
        """Return whether the recorded last Run represents unfinished operator work."""
        item = self.store.last_run()
        if not item:
            return False
        _, run = item
        return run.status not in {"COMPLETE", "ARCHIVED", "ABANDONED"}

    def _model_summary(self) -> str:
        """Return the selected provider and optional model for the Control Center header."""
        settings = load_llm_settings(self.root)
        provider = str(settings["selected_provider"])
        item = settings["providers"].get(provider, {})
        model = item.get("model")
        reasoning = item.get("reasoning_effort")
        if provider == "codex" and item.get("selection_mode") == "AUTO":
            return "codex / AUTO task policy"
        suffix = f" / {model}" if model else " / provider default"
        if reasoning:
            suffix += f" / {reasoning}"
        return f"{provider}{suffix}"

    def main_menu(self) -> str:
        """Render the task-oriented RC7.04 Main Menu."""
        self.io.write()
        from . import __version__
        self.io.write(f"SAGE v{__version__}")
        self.io.write("-" * 72)
        self.io.write(f"BIC active Job: {self._job_summary('bic')}")
        self.io.write(f"SAW active Job: {self._job_summary('saw')}")
        if self._last_run_is_resumable():
            self.io.write(f"Unfinished Run: {self._last_run_summary()}")
        return self.io.choose(
            "MAIN MENU",
            (
                ("1", "Scripture Projects - find, add, configure and validate Projects used by SAGE"),
                ("2", "BIC - compare Scripture and work with a translation TARGET"),
                ("3", "SAW - review a WIP translation against a REFERENCE"),
                ("4", "Reports - review previous BIC / SAW results"),
                ("5", "System / Configuration - paths, reporting, providers and SAGE resources"),
                ("6", "Help / Operator Guide - common workflows, scope syntax and recovery references"),
                ("7", "Recovery / Diagnostics"),
                ("0", "Exit"),
            ),
        )

    def resume_or_start_task(self) -> None:
        """Resume unfinished state from its recorded checkpoint or choose a new workflow."""
        if self._last_run_is_resumable():
            self.continue_last_run()
            return
        choice = self.io.choose(
            "New Task",
            (("1", "BIC"), ("2", "SAW"), ("0", "Back")),
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
                    ("1", "Normal QA"),
                    ("2", "Focused check"),
                    ("3", "Original-language review"),
                    ("0", "Back"),
                ),
            )
            operation_id = {"1": "qa", "2": "focused", "3": "ol"}.get(operation)
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
        if run.status in {"COMPLETE", "ARCHIVED", "ABANDONED"}:
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
                "Jobs & Projects",
                (
                    ("1", "Select active BIC job"),
                    ("2", "Select active SAW job"),
                    ("3", "Manage BIC jobs"),
                    ("4", "Manage SAW jobs"),
                    ("5", "Scripture Projects"),
                    ("6", "Show active-job readiness"),
                    ("7", "Clear active BIC job pointer"),
                    ("8", "Clear active SAW job pointer"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
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
            self.io.write(f"No {tool.upper()} jobs exist. Use Jobs & Projects (main menu option 4) to create one.")
            self.io.pause()
            return None
        options = [(str(index), f"{project.display_name} ({project.job_id})") for index, project in enumerate(projects, 1)]
        options.append(("0", "Back"))
        choice = self.io.choose(f"Select active {tool.upper()} job", options)
        if choice == "0":
            return None
        project = projects[int(choice) - 1]
        self.store.set_active_job(tool, project.job_id)
        self.io.write(f"Active {tool.upper()} job: {project.display_name}")
        return project

    def show_active_readiness(self) -> None:
        """Implement `show active readiness` in the deterministic terminal control flow."""
        self.io.write()
        self.io.write("ACTIVE JOB READINESS")
        self.io.write("-" * 60)
        for tool in TOOL_IDS:
            project = self.store.active_job(tool)
            if project is None:
                self.io.write(f"{tool.upper()}: NONE")
                continue
            state = self.project_state(project)
            self.io.write(
                f"{tool.upper()}: {project.job_id} - {state.get('state', 'NOT INITIALISED')}"
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
                "BIC - BIBLE IN CONTEXT",
                (
                    ("1", f"Open active BIC Job [{active}]"),
                    ("2", "BIC Jobs - select, add or remove Jobs"),
                    ("3", "Add BIC Job - assign SOURCE, DONOR and TARGET"),
                    ("4", "BIC Reports / History"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
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
            choice = self.io.choose(
                "BIC Job",
                (
                    ("1", "Continue active Run"),
                    ("2", "Run BIC check"),
                    ("3", "Runs / task history"),
                    ("4", "Memory / terminology"),
                    ("5", "TARGET history / generations"),
                    ("6", "Reports / exports"),
                    ("7", "Job settings"),
                    ("0", "Back"),
                ),
            )
            if choice == "0": return
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
            elif choice == "7": self.job_management_menu("bic")

    def start_bic_run(self, project: Job) -> None:
        """Select scope, preview bounded work, then create one BIC Run."""
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
        """Open SAW even when no Job exists; Job creation is a tool-setup task."""
        while True:
            project = self.store.active_job("saw")
            active = project.display_name if project is not None else "NONE"
            choice = self.io.choose(
                "SAW - SCRIPTURE ANALYSIS WORKFLOW",
                (
                    ("1", f"Open active SAW Job [{active}]"),
                    ("2", "SAW Jobs - select, add or remove Jobs"),
                    ("3", "Add SAW Job - assign WIP and REFERENCE"),
                    ("4", "SAW Reports"),
                    ("0", "Back"),
                ),
            )
            if choice == "0": return
            if choice == "2":
                self.job_management_menu("saw")
                continue
            if choice == "3":
                self.create_job_wizard("saw")
                continue
            if choice == "4":
                selected = project or self.choose_job("saw")
                if selected is not None: self.reports_menu(selected)
                continue
            if project is None:
                project = self.choose_job("saw")
            if project is not None:
                self._saw_job_menu(project)

    def _saw_job_menu(self, project: Job) -> None:
        """Operate one selected SAW Job."""
        while True:
            project = self.store.active_job("saw") or project
            self.io.write()
            self.io.write(f"SAW JOB - {project.job_id}")
            self.io.write("-" * 72)
            self.io.write(f"WIP:       {project.bindings.get('wip')}")
            self.io.write(f"REFERENCE: {project.bindings.get('reference')}")
            choice = self.io.choose(
                "SAW Job",
                (
                    ("1", "Continue active Run"),
                    ("2", "Normal QA"),
                    ("3", "Focused check"),
                    ("4", "Original-language review"),
                    ("5", "Runs / partition plans"),
                    ("6", "Findings / reports"),
                    ("7", "Batch evaluation queues"),
                    ("8", "Job settings"),
                    ("9", "Reset / restart active Run with current configuration"),
                    ("0", "Back"),
                ),
            )
            if choice == "0": return
            if choice == "1":
                run = self.store.active_run(project)
                if run: self.continue_run(project, run)
                else:
                    self.io.write("No active SAW Run. Start a check or open one from history.")
                    self.io.pause()
            elif choice == "2": self.start_saw_run(project, "qa")
            elif choice == "3": self.start_saw_run(project, "focused")
            elif choice == "4": self.start_saw_run(project, "ol")
            elif choice == "5": self.runs_menu(project)
            elif choice == "6": self.reports_menu(project)
            elif choice == "7": self.batch_menu(project)
            elif choice == "8": self.job_management_menu("saw")
            elif choice == "9":
                run = self.store.active_run(project)
                replacement = self._restart_run_with_current_configuration(project, run)
                if replacement is not None:
                    self.continue_run(project, replacement)

    def start_saw_run(self, project: Job, operation: str) -> None:
        """Select scope, preview bounded work, then create one SAW Run."""
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
            selected = self.io.choose("Focused check type", [(str(i), value) for i, value in enumerate(types, 1)])
            check_type = types[int(selected) - 1]
        self.ensure_initialized(project)
        while True:
            scope = self._select_scripture_scope(project, primary_binding="wip")
            if scope is None:
                return
            action = self._review_work_before_run(project, operation=operation, scope=scope)
            if action == "CHANGE":
                continue
            if action != "RUN":
                return
            run = self.store.create_run(project, operation=operation, scope=scope, focus=focus, check_type=check_type)
            self.io.write(f"Created SAW Run: {run.run_id}")
            self.continue_run(project, run)
            return

    def _select_scripture_scope(self, project: Job, *, primary_binding: str) -> str | None:
        """Offer guided book/range selection while retaining expert direct scope entry."""
        while True:
            choice = self.io.choose(
                "SELECT SCRIPTURE SCOPE",
                (("1", "Choose Book"), ("2", "Enter complete scope directly"), ("0", "Back")),
                prompt="Select or enter scope: ",
                direct_validator=lambda value: parse_scope(value).label(),
            )
            if choice == "0": return None
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
            selected = self.io.choose("CHOOSE BOOK", [(str(i), book) for i, book in enumerate(books, 1)] + [("0", "Back")])
            if selected == "0": continue
            book = books[int(selected) - 1]
            self.io.write()
            self.io.write(f"SCRIPTURE SCOPE - {book}")
            self.io.write("-" * 72)
            self.io.write("Range examples: [blank] whole book; 1 chapter 1; 1-3 chapters 1-3; 1:1-10 verses; 1:1-2:20 cross-chapter")
            value = self.io.text("Range", default="")
            scope = book if not value.strip() else f"{book} {value.strip()}"
            try:
                return parse_scope(scope).label()
            except SageError as exc:
                self.show_error(exc)

    def _review_work_before_run(self, project: Job, *, operation: str, scope: str) -> str:
        """Build the deterministic work-unit/token plan and return RUN, CHANGE, or CANCEL."""
        output = f"plans/pre-run-{project.tool}-{project.job_id}.manifest.json"
        result = self._run_with_status(
            f"Planning bounded {project.tool.upper()} work...",
            lambda: self.controller(
                project,
                ["workflow", "plan", "--workflow", project.tool, "--operation", operation, "--scope", scope, "--output", output],
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
        self.io.write(f"Operation:     {project.tool.upper()} {operation.upper()}")
        self.io.write(f"Scope:         {scope}")
        self.io.write(f"Planned work:  {summary.get('work_units', len(units))} section(s)")
        if policy.get("hard_estimated_tokens") is not None:
            self.io.write(f"Token limit:   {policy['hard_estimated_tokens']:,}")
        for index, unit in enumerate(units, 1):
            measurement = dict(unit.get("measurement") or {})
            tokens = measurement.get("estimated_tokens", "?")
            self.io.write(f"  {index}. {unit.get('primary_scope', '?'):<20} ~{tokens} tokens")
        self.io.write(f"Largest section: ~{summary.get('largest_estimated_tokens', 0)} tokens")
        choice = self.io.choose(
            "Next",
            (("1", "Run"), ("2", "Change scope"), ("0", "Cancel")),
        )
        return {"1": "RUN", "2": "CHANGE", "0": "CANCEL"}[choice]

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

    def _launch_task(
        self,
        project: Job,
        run: Run,
        manifest_path: Path,
        *,
        pause: bool = True,
    ) -> bool:
        """Execute one sealed task and report whether provider output is ready."""
        arguments = ["task", "execute", "--task", str(manifest_path)]
        if self.dry_run_provider:
            arguments.append("--dry-run")
        try:
            result = self._run_with_status(
                f"Running governed {project.tool.upper()} task...",
                lambda: self.controller(project, arguments),
            )
        except SageError as exc:
            self.show_error(exc)
            self.io.write(f"Task remains unexecuted: {manifest_path}")
            self.io.pause()
            return False
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
        """Implement ` submit task` in the deterministic terminal control flow."""
        try:
            result = self._run_with_status(
                f"Submitting governed {project.tool.upper()} result...",
                lambda: self.controller(project, ["task", "submit", "--task", str(manifest_path)]),
            )
        except ValidationError as exc:
            if exc.next_action:
                raise
            if project.tool == "saw":
                next_action = (
                    "Choose Reset / restart active Run with current configuration from the "
                    "SAW Job menu; the rejected Run and its outputs will be preserved."
                )
            else:
                next_action = (
                    "Open the active Run from Runs / task history, then choose Run disposition > "
                    "Reset / restart with current configuration."
                )
            raise ValidationError(
                exc.message,
                code=exc.code,
                next_action=next_action,
                affected_scope=exc.affected_scope,
                details=exc.details,
            ) from exc
        status = str(result.get("status", "SUBMITTED")) if isinstance(result, dict) else "SUBMITTED"
        self.io.write(f"Task submission: {status}")
        return self.store.update_run(run, status=status)

    def _task_action(
        self,
        project: Job,
        run: Run,
        manifest_path: Path,
    ) -> tuple[Run, bool]:
        """Implement ` task action` in the deterministic terminal control flow."""
        state, manifest = self._task_state(manifest_path)
        if state == "TASK_CREATED":
            if not self._launch_task(project, run, manifest_path, pause=False):
                return run, False
            executed_state, _ = self._task_state(manifest_path)
            if executed_state == "OUTPUT_READY":
                return self._submit_task(project, run, manifest_path), True
            self.io.write(
                "Provider execution completed without every required output; "
                "the task remains open."
            )
            self.io.pause()
            return run, False
        if state == "OUTPUT_READY":
            return self._submit_task(project, run, manifest_path), True
        if state == "MISSING":
            raise ValidationError(f"Task manifest is missing: {manifest_path}")
        self.io.write(f"Task already submitted: {manifest.get('operation')} - {state}")
        return run, True

    def _tasks_by_operation(self, run: Run) -> dict[str, list[tuple[Path, dict[str, Any], str]]]:
        """Implement ` tasks by operation` in the deterministic terminal control flow."""
        result: dict[str, list[tuple[Path, dict[str, Any], str]]] = {}
        for value in run.task_manifests:
            path = self._manifest_path(value)
            state, manifest = self._task_state(path)
            operation = str(manifest.get("operation", "unknown"))
            result.setdefault(operation, []).append((path, manifest, state))
        return result

    def continue_run(self, project: Job, run: Run) -> None:
        """Implement `continue run` in the deterministic terminal control flow."""
        try:
            self.ensure_initialized(project)
            if project.tool == "bic":
                run = self._continue_bic(project, run)
            else:
                run = self._continue_saw(project, run)
            self.store.set_active_run(project, run.run_id)
        except SageError as exc:
            self.io.write()
            self.io.write("SAGE RUN BLOCKED")
            self.io.write(f"Reason: {exc.code}")
            self.io.write(f"Message: {exc.message}")
            if exc.next_action:
                self.io.write(f"Next action: {exc.next_action}")
            self.io.pause()
        except Exception as exc:
            self.store.record_cue(
                "RUN_CONTINUATION_FAILED",
                tool=project.tool,
                job_id=project.job_id,
                run_id=run.run_id,
                error_type=type(exc).__name__,
            )
            self.io.write()
            self.io.write("SAGE RUN ERROR")
            self.io.write("Reason: RUN_CONTINUATION_FAILED")
            self.io.write(f"Message: {type(exc).__name__}: {exc}")
            self.io.write("Next action: Restart SAGE and continue the same Run; its saved state was preserved.")
            self.io.pause()

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
        if run.status in {"COMPLETE", "ARCHIVED", "ABANDONED"}:
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

    def _continue_saw(self, project: Job, run: Run) -> Run:
        """Implement ` continue saw` in the deterministic terminal control flow."""
        if not run.task_manifests and not run.plan_path:
            run, result = self._create_task(project, run, run.operation)
            result_status = str(result.get("status") or "")
            if result_status == "PARTITIONED":
                self.io.write(f"SAW scope was partitioned into {len(result.get('work_units', []))} work units.")
            elif result_status == "COMPOSITE":
                stage = str(result.get("current_stage") or "QA").replace("_", " ")
                task_count = len(result.get("task_manifests", []))
                self.io.write(
                    f"Created SAW Normal QA composite plan: {stage} "
                    f"({task_count} task{'s' if task_count != 1 else ''})."
                )
            else:
                act_path = result.get("act_path")
                if not act_path:
                    raise ValidationError(
                        "SAW task creation returned neither a governed task nor a recognised plan",
                        code="SAW_TASK_RESULT_INVALID",
                    )
                self.io.write(f"Created SAW ACT: {act_path}")
            if run.plan_path:
                return self._continue_saw_plan(project, run)
            path = self._manifest_path(run.task_manifests[-1])
            run, submitted = self._task_action(project, run, path)
            if submitted and self._task_state(path)[0] == "FINALIZED":
                run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
                self.io.write("SAW run is complete. Findings and report outputs are available in the run folder.")
                self.io.pause()
            return run
        if run.plan_path:
            return self._continue_saw_plan(project, run)
        path = self._manifest_path(run.task_manifests[-1])
        state, _ = self._task_state(path)
        if state != "FINALIZED":
            run, _ = self._task_action(project, run, path)
            if self._task_state(path)[0] != "FINALIZED":
                return self.store.update_run(run, current_stage=run.operation.upper())
        run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
        self.io.write("SAW run is complete. Findings and report outputs are available in the run folder.")
        self.io.pause()
        return run

    def _continue_saw_plan(self, project: Job, run: Run) -> Run:
        """Advance a SAW plan until completion or the current task needs attention."""
        while True:
            result = self._run_with_status(
                "Loading next SAW work unit...",
                lambda: self.controller(project, ["task", "continue", "--plan", str(run.plan_path)]),
            )
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
                self.io.write(f"SAW work unit {completed + 1}/{total}: {unit_scope}")
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
                aggregate = self._run_with_status(
                    "Aggregating SAW results...",
                    lambda: self.controller(project, ["task", "aggregate", "--plan", aggregate_plan]),
                )
                if result.get("aggregate_plan_path"):
                    self.io.write(f"SAW QA stage aggregate created: {aggregate.get('aggregate_path')}")
                    run = self.store.update_run(
                        run,
                        status="COMPOSITE_IN_PROGRESS",
                        current_stage=str(result.get("composite_stage") or "QA"),
                    )
                    continue
                run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
                self.io.write(f"SAW aggregate created: {aggregate.get('aggregate_path')}")
                self.io.pause()
                return run
            if status == "COMPLETE":
                run = self.store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
                self.io.write("SAW run is complete.")
                if result.get("report_path"):
                    self.io.write(f"Action report: {result['report_path']}")
                if result.get("operator_note_text_path"):
                    self.io.write(f"Operator note: {result['operator_note_text_path']}")
                self.io.pause()
                return run
            raise ValidationError(f"Unsupported SAW continuation status: {status}")

    # ---------- Run dashboard/history ----------

    def runs_menu(self, project: Job) -> None:
        """Implement `runs menu` in the deterministic terminal control flow."""
        while True:
            runs = self.store.list_runs(project)
            choice = self.io.choose(
                f"{project.tool.upper()} Runs and Task History",
                (
                    ("1", "Open active run"),
                    ("2", "List incomplete runs"),
                    ("3", "List completed runs"),
                    ("4", "Search runs"),
                    ("5", "Open selected run dashboard"),
                    ("6", "List task manifests and partition plans"),
                    ("7", "Export one run bundle"),
                    ("8", "Archive completed run"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
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
                f"{run.current_stage}/{run.status}"
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
                f"{run.scope} - {run.operation.upper()} [{run.current_stage}/{run.status}] ({run.run_id})",
            )
            for index, run in enumerate(runs, 1)
        ]
        options.append(("0", "Back"))
        choice = self.io.choose("Select run", options)
        return None if choice == "0" else runs[int(choice) - 1]

    def run_dashboard(self, project: Job, run: Run) -> None:
        """Implement `run dashboard` in the deterministic terminal control flow."""
        while True:
            run = self.store.load_run(project, run.run_id)
            choice = self.io.choose(
                f"Run {run.run_id} | {run.scope} | {run.current_stage}/{run.status}",
                (
                    ("1", "Continue next required step"),
                    ("2", "Execute current governed task"),
                    ("3", "Submit current task output"),
                    ("4", "View run status and blockers"),
                    ("5", "View current ACT and manifest paths"),
                    ("6", "View outputs and reports"),
                    ("7", "View decisions and control records"),
                    ("8", "Archive or abandon run"),
                    ("9", "Advanced run controls"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
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
                self.list_files(run.root / "decisions", patterns=("*.json", "*.md"))
            elif choice == "8":
                action = self.io.choose(
                    "Run disposition",
                    (
                        ("1", "Archive"),
                        ("2", "Abandon"),
                        ("3", "Reset / restart with current configuration"),
                        ("0", "Cancel"),
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
                ("1", "Re-run project initialisation"),
                ("2", "Print exact controller commands for run tasks"),
                ("3", "Clear active-run pointer without deleting data"),
                ("0", "Back"),
            ),
        )
        if choice == "1":
            self.ensure_initialized(project, force=True)
        elif choice == "2":
            for value in run.task_manifests:
                self.io.write(
                    f"./sage --settings {shlex.quote(str(project.runtime_settings_path))} "
                    f"task submit --task {shlex.quote(str(self._manifest_path(value)))}"
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
                    ("1", "List all memory records"),
                    ("2", "List records by state"),
                    ("3", "Transition one record"),
                    ("4", "Record optional INSPECT review provenance"),
                    ("5", "Import governed lexicon"),
                    ("6", "Roll back lexicon import"),
                    ("7", "Open memory folder"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
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
                    source = self.io.text("Lexicon YAML/JSON path")
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
                    ("1", "List immutable generations"),
                    ("2", "Verify current generation"),
                    ("3", "Publish current generated target"),
                    ("4", "Show generated target resource folder"),
                    ("5", "List bounded TARGET commit history"),
                    ("6", "Revert one committed TARGET scope"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
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
            f"{project.tool.upper()} Reports and Exports",
            (
                ("1", "List run reports"),
                ("2", "List job reports"),
                ("3", "List exports"),
                ("4", "Show job data path"),
                ("0", "Back"),
            ),
        )
        if choice == "1":
            self.list_files(project.root / "runs", patterns=("*.md", "*.json", "*.txt", "*.tsv"))
        elif choice == "2":
            self.list_files(project.root / "reports", patterns=("*.md", "*.json", "*.txt", "*.tsv"))
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
                ("2", "Recover one incomplete transaction (journal rollback; may restore file bytes)"),
                ("3", "Reinitialise project readiness"),
                ("4", "Abandon active run without deleting data"),
                ("5", "Export diagnostic file listing"),
                ("6", "Reset / restart active Run with current configuration"),
            ]
            if project.tool == "bic":
                recovery_options.append(("7", "Restart one BIC analytical scope (TARGET unchanged)"))
            recovery_options.append(("0", "Back"))
            choice = self.io.choose(
                f"{project.tool.upper()} Recovery and Reset",
                tuple(recovery_options),
            )
            if choice == "0":
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
                    destination = project.root / "reports" / "diagnostic-files.json"
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
                ("1", "Apply detected base VRS selection and retry validation"),
                ("0", "Keep current Project settings"),
            ),
        )
        if selected == "0":
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
            self.io.write(
                f"{role.upper():<11} {project_id}: {result.get('status', 'UNKNOWN')} "
                f"({len(issues)} issues, {len(warnings)} warnings)"
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
                self.io.write(f"  - ... {len(issues) - 8} more issues in the initialisation report")
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
        """List, add, select, validate, archive or permanently remove Jobs."""
        while True:
            jobs = self.store.discover(tool, include_archived=True)
            active = self.store.active_job(tool)
            self.io.write()
            self.io.write(f"{tool.upper()} JOBS")
            self.io.write("-" * 72)
            if jobs:
                for index, job in enumerate(jobs, 1):
                    marker = " [ACTIVE]" if active and job.job_id == active.job_id else ""
                    self.io.write(f"{index}. {job.job_id} - {job.display_name} [{job.status}]{marker}")
            else:
                self.io.write(f"No {tool.upper()} Jobs exist.")
            choice = self.io.choose(
                f"{tool.upper()} Job management",
                (("1", "Select existing Job"), ("2", "Add Job"), ("3", "Open active Job settings"),
                 ("4", "Validate active Job"), ("5", "Archive active Job"), ("6", "Remove Job"), ("0", "Back")),
            )
            if choice == "0": return
            if choice == "1":
                self.choose_job(tool)
                continue
            if choice == "2":
                self.create_job_wizard(tool)
                continue
            project = self.store.active_job(tool)
            if choice == "6":
                candidates = self.store.discover(tool, include_archived=True)
                if not candidates:
                    self.io.write(f"No {tool.upper()} Jobs exist.")
                    self.io.pause()
                    continue
                selected = self.io.choose("REMOVE JOB", [(str(i), f"{job.job_id} - {job.display_name}") for i, job in enumerate(candidates, 1)] + [("0", "Back")])
                if selected == "0": continue
                target = candidates[int(selected) - 1]
                runs = self.store.list_runs(target)
                self.io.write()
                self.io.write(f"REMOVE JOB - {target.job_id}")
                self.io.write("-" * 72)
                self.io.write("This deletes this SAGE Job and its Job-local Runs/reports.")
                self.io.write("SAGE Projects and Paratext Project files will NOT be deleted or modified.")
                self.io.write(f"Runs in this Job: {len(runs)}")
                if self.io.confirm(f"Remove Job {target.job_id}?", default=False):
                    self.store.remove_job(target)
                    self.io.write(f"Removed Job: {target.job_id}")
                    self.io.pause()
                continue
            if project is None:
                self.io.write(f"No active {tool.upper()} Job. Select or add one first.")
                self.io.pause()
                continue
            if choice == "3":
                self.io.write(project.manifest_path.read_text(encoding="utf-8"))
                self.io.pause()
            elif choice == "4": self.project_readiness(project)
            elif choice == "5":
                if self.io.confirm(f"Archive Job {project.job_id}?", default=False):
                    self.store.revise_job(project, status="ARCHIVED")
                    self.store.set_active_job(tool, None)
                    self.io.write("Job archived. Data was not deleted.")
                    self.io.pause()

    def create_job_wizard(self, tool: str) -> None:
        """Create one Job by assigning roles to Projects already in the SAGE Project Inventory."""
        if tool == "bic":
            source = self.choose_or_add_resource("SELECT BIC SOURCE", "CONTENT_SOURCE")
            if not source: return
            donor = self.choose_or_add_resource("SELECT BIC DONOR", "LEXICAL_DONOR")
            if not donor: return
            output = self.choose_or_add_resource("SELECT BIC TARGET", "GENERATED_TARGET")
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
            output = self.choose_or_add_resource("SELECT SAW WIP", "WIP")
            if not output: return
            source = self.choose_or_add_resource("SELECT SAW REFERENCE", "REFERENCE")
            if not source: return
            job_id = default_job_name("saw", output.project_id, source.project_id)
            name = f"{output.project_id} analysed against {source.project_id}"
            greek = active_ol_project_id(self.root, "GRK")
            hebrew = active_ol_project_id(self.root, "HEB")
            bindings = {"wip": output.project_id, "reference": source.project_id,
                        **({"original_language_greek": greek} if greek else {}), **({"original_language_hebrew": hebrew} if hebrew else {})}
            profiles = {}
            defaults = {}
        while True:
            self.io.write()
            self.io.write(f"REVIEW {tool.upper()} JOB")
            self.io.write("-" * 72)
            if tool == "bic":
                self.io.write(f"SOURCE: {source.project_id}")
                self.io.write(f"DONOR:  {donor.project_id}")
                self.io.write(f"TARGET: {output.project_id}")
                self.io.write("TARGET access: GOVERNED WRITE")
            else:
                self.io.write(f"WIP:       {output.project_id}")
                self.io.write(f"REFERENCE: {source.project_id}")
            self.io.write(f"Job name: {job_id}")
            choice = self.io.choose("Create Job", (("1", "Create Job"), ("2", "Change display name"), ("0", "Cancel")))
            if choice == "0": return
            if choice == "2":
                name = self.io.text("Display name", default=name)
                continue
            try:
                project = self.store.create_job(tool=tool, job_id=job_id, display_name=name, bindings=bindings, profiles=profiles, defaults=defaults)
                self.store.set_active_job(tool, project.job_id)
                self.io.write(f"Created and selected Job: {project.job_id}")
                self.io.pause()
                return
            except ValidationError as exc:
                if exc.code == "LANGUAGE_PROFILE_SELECTION_REQUIRED":
                    details = dict(exc.details or {})
                    candidates = [str(value) for value in details.get("candidates", [])]
                    if candidates:
                        selected = self.io.choose("SELECT LANGUAGE PROFILE FOR JOB ROLE", [(str(i), value) for i, value in enumerate(candidates, 1)] + [("0", "Cancel")])
                        if selected == "0": return
                        role = str(details.get("role", ""))
                        profiles["source_grammar" if role == "CONTENT_SOURCE" else "target_grammar"] = candidates[int(selected) - 1]
                        continue
                if exc.code == "LANGUAGE_PROFILE_NOT_CONFIGURED" and self._offer_language_profile_alias(exc):
                    continue
                self.show_error(exc)
                self.io.pause()
                return
            except SageError as exc:
                self.show_error(exc)
                self.io.pause()
                return

    def _offer_language_profile_alias(self, exc: ValidationError) -> bool:
        """Offer an ISO-supported, operator-approved ecosystem profile alias and persist it."""
        suggestion = dict((exc.details or {}).get("profile_alias_suggestion") or {})
        language = str(suggestion.get("language") or "")
        alias = str(suggestion.get("profile_alias") or "")
        variants = [str(value) for value in suggestion.get("variants", [])]
        if not language or not alias or not variants:
            return False
        config = load_ecosystem(self.store.settings_path)
        if language in config.language_profiles:
            return True
        if alias not in config.language_profiles:
            return False

        self.io.write()
        self.io.write("LANGUAGE PROFILE SETUP")
        self.io.write("-" * 72)
        self.io.write(
            f"ISO language:    {language} - {suggestion.get('language_name') or 'ISO language'}"
        )
        self.io.write(
            f"Project prefix:  {suggestion.get('project_prefix')} - "
            f"{suggestion.get('prefix_language_name') or 'ISO language'} [consistent]"
        )
        self.io.write(f"Existing profile: {alias}/" + ", ".join(variants))
        self.io.write(
            "SAGE can register an explicit profile alias. The Project language remains "
            f"{language}; no Project or Job data will be rewritten."
        )
        selected = self.io.choose(
            "UPDATE ECOSYSTEM LANGUAGE PROFILES",
            (
                ("1", f"Add {language} -> {alias} profile alias to ecosystem.yml and retry"),
                ("0", "Cancel - leave ecosystem.yml unchanged"),
            ),
        )
        if selected == "0":
            return False

        original = self.store.settings_path.read_text(encoding="utf-8")
        raw = load_yaml_compat(self.store.settings_path)
        profile_rows = dict(raw.get("language_profiles") or {})
        if language not in profile_rows:
            profile_rows[language] = {
                "script": str(suggestion.get("script") or config.language_profiles[alias].script),
                "profile_alias": alias,
            }
            raw["language_profiles"] = profile_rows
            atomic_write_text(self.store.settings_path, yaml_dump_compat(raw))
            try:
                load_ecosystem(self.store.settings_path)
            except SageError:
                atomic_write_text(self.store.settings_path, original)
                raise
        self.io.write(f"Updated ecosystem.yml: language_profiles.{language}.profile_alias = {alias}")
        self.io.write("Retrying Job creation with the operator-approved profile alias.")
        return True

    def choose_resource(self, title: str, resources: Sequence[Any]) -> Any | None:
        """Select one already-authorised resource for a bounded operator selection."""
        if not resources:
            self.io.write(f"No resources are authorised for {title.lower()}.")
            self.io.pause()
            return None
        options = [
            (str(index), f"{item.project_id} - {item.language_code} [{item.content_state}]")
            for index, item in enumerate(resources, 1)
        ]
        options.append(("0", "Cancel"))
        choice = self.io.choose(title, options)
        return None if choice == "0" else resources[int(choice) - 1]

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
            (str(i), f"{item.project_id} - {inventory[item.project_id].get('display_name', item.project_id)} / {item.language_code} [{inventory[item.project_id].get('scope_summary', 'UNKNOWN')}]")
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
            options.extend((("A", "Add another Project to SAGE"), ("0", "Back")))
            choice = self.io.choose(title, options)
            if choice == "0": return None
            if choice == "A":
                self.discover_register_projects_menu(return_on_register=True)
                continue
            return resources[int(choice)-1]

    def _ensure_project_root(self) -> Path | None:
        """Return the configured primary Paratext/PTLite projects root."""
        state = load_resource_mount_state(self.root)
        primary = state.get("projects_root")
        if primary:
            return Path(primary)
        self.io.write("No primary Paratext/PTLite Projects root is configured yet.")
        if not self.io.confirm("Configure the primary Projects root now?", default=True):
            return None
        value = Path(normalize_operator_path(self.io.text("Paratext/PTLite Projects root"))).expanduser()
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

    def global_menu(self) -> None:
        """Centralise recovery and diagnostics so workflow menus stay task-focused."""
        while True:
            choice = self.io.choose(
                "Recovery & Diagnostics",
                (
                    ("1", "Recover/reset active BIC job"),
                    ("2", "Recover/reset active SAW job"),
                    ("3", "Rebuild job runtime configurations"),
                    ("4", "Show SAGE paths and state files"),
                    ("5", "Export global diagnostics"),
                    ("6", "Reset global menu pointers only"),
                    ("7", "Recovery / error cheat sheets"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
                return
            if choice in {"1", "2"}:
                tool = "bic" if choice == "1" else "saw"
                project = self.store.active_job(tool)
                if project is None:
                    self.io.write(f"No active {tool.upper()} job is selected.")
                    self.io.pause()
                else:
                    self.recovery_menu(project)
            elif choice == "3":
                for project in self.store.discover():
                    self.store.write_runtime_files(project)
                    self.io.write(f"Rebuilt: {project.project_id}")
                self.io.pause()
            elif choice == "4":
                self.io.write(f"SAGE Home: {self.root}")
                self.io.write(f"Internal Scripture resources: {load_ecosystem(self.store.settings_path).projects_root}")
                self.io.write(f"External resource mounts: {self.root / 'state' / 'resource-mounts.json'}")
                self.io.write(f"Setup state: {self.store.setup_state_path}")
                self.io.write(f"Last run: {self.store.last_run_path}")
                self.io.write(f"Operator cue journal: {self.store.operator_cues_path}")
                self.io.write(f"BIC job data: {self.store.tool_root('bic')}")
                self.io.write(f"SAW job data: {self.store.tool_root('saw')}")
                self.io.pause()
            elif choice == "5":
                self.export_global_diagnostics()
            elif choice == "6":
                if self.io.confirm("Clear active job and last-run pointers? Job data will remain.", default=False):
                    self.store.active_jobs_path.unlink(missing_ok=True)
                    self.store.last_run_path.unlink(missing_ok=True)
                    self.store.record_cue("GLOBAL_POINTERS_RESET")
            elif choice == "7":
                self._show_support_docs()

    def _model_connect_chatgpt(self, service: ModelService) -> None:
        """Offer browser or device-code ChatGPT sign-in through Codex CLI, then verify readiness."""
        choice = self.io.choose(
            "Connect OpenAI / ChatGPT",
            (
                ("1", "Browser sign-in (recommended)"),
                ("2", "Device-code sign-in"),
                ("0", "Cancel"),
            ),
        )
        if choice == "0":
            return
        self.io.write("SAGE will run the local Codex CLI sign-in. No OpenAI API key is used or accepted.")
        result = service.connect_chatgpt(device_auth=(choice == "2"))
        self.io.write("OpenAI / ChatGPT: CONNECTED")
        self.io.write("Returned to SAGE. Codex was used only for sign-in; its interactive shell was not started.")
        self.io.write("Transport: local Codex CLI; Codex desktop app not required")
        if result.get("account_plan_type"):
            self.io.write(f"ChatGPT plan/workspace: {result['account_plan_type']}")
        self.io.write(f"Live models available: {result['model_count']}")
        self.io.write("Model routing: SAGE automatic task policy")

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

    def _model_show_codex_catalog(self, service: ModelService) -> None:
        """Render the live Codex model catalogue with SAGE-approved task profiles."""
        result = service.list_models("codex")
        if not result["models"]:
            self.io.write(result.get("diagnostic", "No live Codex catalogue is available."))
        for row in result["models"]:
            selected = " *" if row.get("selected") else ""
            self.io.write(f"{row.get('display_name') or row['model']} [{row['model']}]{selected}")
            efforts = row.get("reasoning_efforts") or []
            self.io.write(f"  reasoning: {', '.join(efforts) if efforts else 'provider default only'}")
            approved = row.get("qualified_profiles") or []
            self.io.write(f"  SAGE approved: {', '.join(approved) if approved else 'none'}")

    def _model_select_codex_explicit(self, service: ModelService) -> None:
        """Prompt for one live Codex model and one provider-advertised SAGE-supported effort."""
        result = service.list_models("codex")
        models = result["models"]
        if not result.get("ready") or not models:
            raise ValidationError(
                result.get("diagnostic") or "No live Codex models are available",
                code="LLM_PROVIDER_NOT_READY",
            )
        selected = self.io.choose(
            "Available Codex models",
            tuple(
                (str(index), f"{row.get('display_name') or row['model']} [{row['model']}]")
                for index, row in enumerate(models, 1)
            ),
        )
        row = models[int(selected) - 1]
        efforts = tuple(row.get("reasoning_efforts") or ())
        reasoning = None
        if efforts:
            effort_choice = self.io.choose(
                "Reasoning level",
                tuple((str(index), effort) for index, effort in enumerate(efforts, 1)),
            )
            reasoning = efforts[int(effort_choice) - 1]
        selected_result = service.select(
            provider="codex",
            model=row["model"],
            reasoning_effort=reasoning,
        )
        self.io.write(f"Selected Codex: {row['model']} / {reasoning or 'provider default'}")
        self.io.write(selected_result["provider_status"].get("diagnostic", ""))

    def _model_configure_local(self, service: ModelService, provider: str) -> None:
        """Provision one disabled local-provider configuration without activating execution."""
        settings = service.settings()
        current = settings["providers"][provider]
        endpoint = self.io.text("Local endpoint", default=str(current["endpoint"]))
        model = self.io.text("Preferred local model (optional)", default=str(current.get("model") or ""))
        result = service.provision(provider, model=model or None, endpoint=endpoint)
        self.io.write(f"Provisioned {provider}: {result.get('model') or 'model not fixed'}")
        self.io.write("Execution is disabled for this provider by the current build policy.")

    def _model_show_recommendation(self, service: ModelService) -> None:
        """Prompt for one SAGE task profile and render the current live recommendation."""
        profiles = (
            ("1", "BIC INSPECT", "bic", "inspect"),
            ("2", "BIC REWRITE", "bic", "rewrite"),
            ("3", "BIC SELF-CHECK", "bic", "self_check"),
            ("4", "SAW normal QA", "saw", "qa"),
            ("5", "SAW focused check", "saw", "focused"),
            ("6", "SAW original-language review", "saw", "ol"),
        )
        selected = self.io.choose(
            "Task profile",
            tuple((key, label) for key, label, _, _ in profiles),
        )
        _, label, workflow, operation = next(item for item in profiles if item[0] == selected)
        recommendation = service.recommendation(workflow, operation)
        self.io.write(f"{label}: {recommendation['display_name']} [{recommendation['model']}]")
        self.io.write(f"Reasoning: {recommendation.get('reasoning_effort') or 'provider default'}")
        if recommendation.get("conditional_second_pass_reasoning_effort"):
            self.io.write(
                "Conditional second pass: "
                f"{recommendation['conditional_second_pass_reasoning_effort']}"
            )
        self.io.write(f"Qualification: {recommendation['qualification_status']}")

    def _model_test_selected(self, service: ModelService) -> None:
        """Run the minimal structured connectivity test for the selected provider."""
        result = service.connectivity_test(timeout_seconds=120)
        self.io.write(f"{result['provider']}: READY")
        self.io.write(f"Model: {result.get('model') or 'provider default'}")
        if result.get("reasoning_effort"):
            self.io.write(f"Reasoning: {result['reasoning_effort']}")

    def _model_show_policy(self, service: ModelService) -> None:
        """Render the release-governed reasoning ceiling and task-profile bounds."""
        policy = service.policy()
        global_policy = policy["global"]
        self.io.write("Supported reasoning: " + ", ".join(global_policy["allowed_reasoning_efforts"]))
        self.io.write(
            "Hard ceiling: "
            f"{global_policy['maximum_supported_reasoning_effort']} (higher levels are unsupported)"
        )
        for profile, row in policy["task_profiles"].items():
            self.io.write(
                f"{profile}: target={row['target_reasoning_effort']} "
                f"bounds={row['minimum_reasoning_effort']}..{row['maximum_reasoning_effort']}"
            )

    def model_menu(self) -> None:
        """Configure providers through the same policy-aware service used by the CLI."""
        service = ModelService(self.root)
        actions = {
            "1": lambda: self._model_connect_chatgpt(service),
            "2": lambda: self._model_show_status(service),
            "3": lambda: self._model_show_codex_catalog(service),
            "4": lambda: self.io.write(
                service.select(provider="codex", auto=True)["provider_status"].get("diagnostic", "")
            ),
            "5": lambda: self._model_select_codex_explicit(service),
            "6": lambda: self._model_configure_local(service, "ollama"),
            "7": lambda: self._model_configure_local(service, "lmstudio"),
            "8": lambda: self._model_show_recommendation(service),
            "9": lambda: self._model_test_selected(service),
            "A": lambda: self._model_show_policy(service),
        }
        while True:
            choice = self.io.choose(
                "Models",
                (
                    ("1", "Connect OpenAI / ChatGPT (Codex CLI; no desktop app)"),
                    ("2", "Provider status"),
                    ("3", "OpenAI Codex live models + reasoning"),
                    ("4", "Use automatic Codex task routing"),
                    ("5", "Select explicit Codex model + reasoning"),
                    ("6", "Provision Ollama (disabled in this build)"),
                    ("7", "Provision LM Studio (disabled in this build)"),
                    ("8", "Recommend model for a SAGE task"),
                    ("9", "Test selected provider"),
                    ("A", "Show SAGE model policy"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
                return
            try:
                if choice == "4":
                    self.io.write("Codex selection: SAGE automatic task routing")
                actions[choice]()
            except SageError as exc:
                self.show_error(exc)
                continue
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
            self.io.write("SAGE PROJECTS")
            self.io.write("-"*96)
            self.io.write("#   Project     Name                               Lang      Scope       Status")
            for i, pid in enumerate(ids,1):
                row=records[pid]
                language=str(row.get("language",{}).get("code","?"))
                name=str(row.get("display_name") or pid)
                scope=str(row.get("scope_summary") or "UNKNOWN")
                status=str(row.get("validation_status") or "UNKNOWN")
                self.io.write(f"{i:<3} {pid:<11} {name[:34]:<34} {language:<9} {scope:<11} {status}")
            if not ids: self.io.write("No Projects have been added to SAGE yet.")
            selected=self.io.choose("SAGE Projects", [(str(i),pid) for i,pid in enumerate(ids,1)] + [("A","Add another Project to SAGE"),("V","Validate all SAGE Projects"),("0","Back")])
            if selected=="0": return
            if selected=="A":
                self.discover_register_projects_menu()
                continue
            if selected=="V":
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
            # <Other location> Projects are intentionally outside the primary catalogue root.
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
        """Render one SAGE Project maintenance screen using RC7.04 section grammar."""
        while True:
            record=registered_project_records(self.root).get(project_id)
            if record is None:
                self.io.write(f"SAGE Project not found: {project_id}")
                self.io.pause()
                return
            mount=load_resource_mounts(self.root).get(project_id,{})
            meta=dict(record.get("paratext_metadata") or {})
            vrs=dict(record.get("versification") or {})
            reporting=dict(record.get("reporting") or {})
            self.io.write()
            self.io.write(f"PROJECT - {project_id}")
            self.io.write("-"*72)
            self.io.write("# Details ______________________________________________________________")
            self.io.write(f"Name:             {record.get('display_name', project_id)}")
            self.io.write(f"Language:         {meta.get('language_name') or 'UNKNOWN'} [{record.get('language',{}).get('code','?')}]")
            self.io.write(f"Scope:            {record.get('scope_summary','UNKNOWN')}")
            self.io.write(f"Versification:    {self._project_vrs_summary(vrs)}")
            self.io.write(f"Status:           {record.get('validation_status','UNKNOWN')}")
            self.io.write()
            self.io.write("# Project Settings _____________________________________________________")
            self.io.write("1. Project information\n2. Scripture books\n3. Versification\n4. Reporting languages")
            self.io.write()
            self.io.write("# Maintenance __________________________________________________________")
            self.io.write("5. Project location\n6. Validate this Project\n7. Show Jobs using this Project")
            self.io.write()
            self.io.write("# Advanced _____________________________________________________________")
            self.io.write("8. Advanced settings\n9. Remove Project from SAGE")
            self.io.write("_"*72)
            self.io.write("0. Back")
            action=self.io.read("Select: ").strip()
            if action=="0": return
            if action=="1": self._project_information_menu(project_id)
            elif action=="2": self._project_books_menu(project_id)
            elif action=="3": self._project_vrs_menu(project_id)
            elif action=="4": self._project_reporting_menu(project_id)
            elif action=="5": self._project_storage_menu(project_id)
            elif action=="6":
                try:
                    refreshed=self._refresh_registered_from_catalog(project_id)
                    self.io.write(f"Validated {project_id}: scope={refreshed.get('scope_summary')} status={refreshed.get('validation_status')}")
                except SageError as exc: self.show_error(exc)
                self._setup_scripture_resource_status(render=True)
                self.io.pause()
            elif action=="7": self._project_jobs_menu(project_id)
            elif action=="8": self._project_advanced_menu(project_id)
            elif action=="9":
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

    def _project_reporting_menu(self, project_id: str) -> None:
        """Configure bilingual report languages for one translation Project; UI remains English."""
        while True:
            record = registered_project_records(self.root)[project_id]
            override = dict(record.get("reporting") or {})
            config = load_ecosystem(self.store.settings_path)
            global_logs = config.human_output.logs_and_reports
            primary = override.get("primary_language") or global_logs.primary_language
            secondary = override.get("secondary_language") or global_logs.secondary_language
            bilingual = bool(override.get("bilingual", global_logs.bilingual))
            source = "PROJECT OVERRIDE" if override else "GLOBAL DEFAULT"
            self.io.write(f"Primary:    {primary}")
            self.io.write(f"Secondary:  {secondary}")
            self.io.write(f"Bilingual:  {'ON' if bilingual else 'OFF'}")
            self.io.write(f"Source:     {source}")
            choice = self.io.choose(
                "Reporting languages",
                (("1", "Set primary + secondary languages"), ("2", "Reset to global defaults"), ("0", "Back")),
            )
            if choice == "0":
                return
            if choice == "1":
                new_primary = self.io.text("Primary reporting language", default=str(primary))
                new_secondary = self.io.text("Secondary reporting language", default=str(secondary))
                set_project_reporting_languages(
                    self.root,
                    project_id=project_id,
                    primary_language=new_primary,
                    secondary_language=new_secondary,
                    bilingual=True,
                )
                self.io.write("Project reporting saved: bilingual ON. UI remains English.")
                self.io.pause()
            elif choice == "2":
                clear_project_reporting_languages(self.root, project_id=project_id)
                self.io.write("Project reporting override cleared.")
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
                    ("0", "Back"),
                ),
            )
            if action == "0":
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
            (("1", "Show parsed project-code metadata"), ("2", "Show raw SAGE Project record"), ("0", "Back")),
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

    def _catalogue_filter_menu(self, scope_filter: str, language_filter: str | None) -> tuple[str, str | None]:
        """Configure only the two approved discovery filters: FB/NT/Portions and language."""
        while True:
            catalogue = load_paratext_catalog(self.root)
            language_label = language_filter or "All"
            choice = self.io.choose(
                "Filter Projects",
                (("1", f"Scope      {scope_filter}"), ("2", f"Language   {language_label}"), ("C", "Clear filters"), ("0", "Apply / Back")),
            )
            if choice == "0":
                return scope_filter, language_filter
            if choice == "C":
                scope_filter, language_filter = "ALL", None
            elif choice == "1":
                selected = self.io.choose(
                    "Scope",
                    (("1", "Full Bible [FB]"), ("2", "New Testament [NT]"), ("3", "Portions"), ("0", "All")),
                )
                scope_filter = {"1": "FB", "2": "NT", "3": "PORTIONS", "0": "ALL"}[selected]
            elif choice == "2":
                languages = language_filter_counts(catalogue)
                options = [(str(index), f"{row['language_name']} [{row['language_iso']}] [{row['count']}]") for index, row in enumerate(languages, 1)]
                options.append(("0", "All languages"))
                selected = self.io.choose("Language", options)
                language_filter = None if selected == "0" else str(languages[int(selected) - 1]["language_iso"])

    def _register_catalogue_row(self, row: dict[str, Any], role: str | None = None) -> str | None:
        """Review one discovered Project and add it to SAGE without assigning a Job role."""
        project_id=str(row.get("project_code"))
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
        if resolution and resolution.get("status") != "VALID":
            suggestions = [str(value) for value in resolution.get("suggestions", [])]
            options = [(str(i), f"Use {code} - {(iso_language(code) or {}).get('name', 'ISO language')}") for i, code in enumerate(suggestions, 1)]
            options.extend((("C", "Choose another ISO language code"), ("U", "Keep language unresolved [und]"), ("0", "Cancel")))
            selected = self.io.choose("LANGUAGE METADATA REVIEW", options)
            if selected == "0": return None
            if selected == "U": row["language_iso"] = "und"
            elif selected == "C":
                while True:
                    candidate = self.io.text("ISO 639 language code").casefold()
                    found = iso_language(candidate)
                    if found is not None:
                        row["language_iso"] = str(found.get("alpha_3") or candidate)
                        break
                    self.io.write("That code was not found in SAGE's bundled ISO language registry.")
            else:
                row["language_iso"] = suggestions[int(selected) - 1]
        if not self.io.confirm("Add this Project to SAGE?", default=True): return None
        try:
            created=register_catalogued_scripture_project(self.store.settings_path, catalogue_row=row)
            self.io.write()
            self.io.write("PROJECT ADDED TO SAGE")
            self.io.write("-"*72)
            self.io.write(f"{created} - {row.get('full_name') or created}")
            config=load_ecosystem(self.store.settings_path)
            language=str(row.get("language_iso") or "")
            if language and language not in config.language_profiles:
                self.io.write(f"Language profile: Not configured for {language}")
                self.io.write("This does not prevent the Project from being stored in SAGE. A compatible profile is required only when a Job operation needs language-specific analysis.")
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
        if catalogue.get("projects_root") != str(root_path.resolve()): catalogue=self._scan_projects(root_path, full=True)
        scope_filter="ALL"
        language_filter: str|None=None
        while True:
            inventory=set(registered_project_records(self.root))
            rows=filtered_projects(catalogue, scope=scope_filter, language_iso=language_filter, registered_ids=inventory, unregistered_only=True)
            summary=catalog_summary(catalogue)
            self.io.write()
            self.io.write("ADD PROJECTS TO SAGE")
            self.io.write("-"*88)
            self.io.write("Choose Paratext Projects that SAGE should make available to BIC and SAW.")
            self.io.write(f"Paratext root:    {catalogue.get('projects_root')}")
            self.io.write(f"Catalogue:        {summary['projects']} Projects / {summary['languages']} languages")
            self.io.write(f"Already in SAGE:  {len(inventory)}")
            self.io.write(f"Available:        {len(rows)}")
            self.io.write(f"Filter:           Scope={scope_filter}  Language={language_filter or 'ALL'}")
            options=[]
            for i,row in enumerate(rows,1):
                code=str(row.get("project_code"))
                name=str(row.get("full_name") or code)
                options.append((str(i),f"{code:<9} {name[:38]:<38} {row.get('language_iso') or '?':<5} {row.get('filter_scope')}"))
            options += [("F","Filter by scope / language"),("R","Scan / Rescan Paratext Projects"),("I","Show invalid Project folders"),("O","Add Project from another location"),("0","Back")]
            selected=self.io.choose("Available Paratext Projects", options)
            if selected=="0": return None
            if selected=="F":
                scope_filter,language_filter=self._catalogue_filter_menu(scope_filter,language_filter)
                continue
            if selected=="R":
                mode=self.io.choose("Scan / Rescan Paratext Projects", (("1","Quick rescan"),("2","Full rescan"),("0","Back")))
                if mode!="0": catalogue=self._scan_projects(root_path, full=mode=="2")
                continue
            if selected=="I":
                invalid=dict(catalogue.get("invalid_folders",{}))
                if not invalid: self.io.write("No invalid Project folders are catalogued.")
                for code,item in sorted(invalid.items()): self.io.write(f"{code}: {item.get('code')} - {item.get('message')}")
                self.io.pause()
                continue
            if selected=="O":
                raw=normalize_operator_path(self.io.text("Full Paratext/PTLite Project folder"))
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
        """Configure Paratext Projects root and its persistent Project Catalogue."""
        while True:
            state=load_resource_mount_state(self.root)
            primary=state.get("projects_root")
            catalogue=load_paratext_catalog(self.root)
            summary=catalog_summary(catalogue)
            self.io.write()
            self.io.write("PARATEXT PROJECT CATALOGUE")
            self.io.write("-"*72)
            self.io.write(f"Paratext Projects root: {primary or 'NOT CONFIGURED'}")
            self.io.write(f"Projects discovered:    {summary['projects']}")
            self.io.write(f"Last scan:              {summary['last_scan'] or 'NEVER'}")
            choice=self.io.choose("Paratext Project Catalogue", (("1","Set / change Paratext Projects root"),("2","Quick rescan"),("3","Full rescan"),("4","Show catalogue summary"),("0","Back")))
            if choice=="0": return
            try:
                if choice=="1":
                    value=Path(normalize_operator_path(self.io.text("Paratext/PTLite Projects root"))).expanduser()
                    try: set_project_root(self.root, project_root=value, progress=self._scan_progress)
                    finally: self.io.clear_status()
                    self.io.write(f"Paratext Projects root: {value.resolve()}")
                elif choice in {"2","3"}:
                    if not primary: raise ValidationError("Configure the Paratext Projects root first", code="PROJECT_ROOT_NOT_FOUND")
                    result=self._scan_projects(Path(primary), full=choice=="3")
                    row=catalog_summary(result)
                    self.io.write(f"Paratext scan complete: {row['projects']} Projects / {row['languages']} languages / {row['invalid']} invalid")
                elif choice=="4": self.io.write(json.dumps({**summary,"projects_root":catalogue.get("projects_root")},indent=2,ensure_ascii=False))
                self.io.pause()
            except SageError as exc: self.show_error(exc)

    def _map_registered_resource(self) -> None:
        """Advanced path update for a SAGE Project whose location has changed."""
        records=registered_project_records(self.root)
        ids=sorted(records,key=str.casefold)
        if not ids:
            self.io.write("No SAGE Projects exist.")
            self.io.pause()
            return
        selected=self.io.choose("Select SAGE Project", [(str(i),pid) for i,pid in enumerate(ids,1)] + [("0","Back")])
        if selected=="0": return
        self._project_storage_menu(ids[int(selected)-1])

    def _configure_ol_resource_menu(self, resource_id: str) -> None:
        """Explicitly select the source behind one stable governed @GRK/@HEB alias."""
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
                (("1", f"Use bundled {row['alias']}"), ("2", "Use detected Paratext SRC Project"), ("3", "Use other local resource"), ("4", "Show resource details"), ("0", "Back")),
            )
            if choice == "0":
                return
            try:
                if choice == "1":
                    configure_ol_resource(self.root, resource_id=resource_id, source="BUNDLED")
                elif choice == "2":
                    catalogue = load_paratext_catalog(self.root)
                    candidates = paratext_ol_candidates(catalogue, resource_id)
                    if not candidates:
                        self.io.write(f"No recognised {resource_id} Paratext SRC candidates are catalogued.")
                        self.io.write("Expected pattern: grcSRCv# for Greek or hboSRCv# for Hebrew.")
                        self.io.pause()
                        continue
                    options = [(str(index), f"{item['project_code']} - {item.get('full_name')} [{item.get('scope')}]") for index, item in enumerate(candidates, 1)] + [("0", "Back")]
                    selected = self.io.choose("Detected original-language Projects", options)
                    if selected == "0":
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
                suffix = f" / {row.get('paratext_project')}" if row.get("paratext_project") else ""
                self.io.write(f"{row['alias']:<5} {row['status']:<10} {row['source']}{suffix}")
            self.io.write(f"Capability: {status['status']}")
            choice = self.io.choose(
                "Original-language resources",
                (("1", "Configure Greek @GRK"), ("2", "Configure Hebrew @HEB"), ("3", "Validate OL resources"), ("4", "Restore bundled defaults"), ("0", "Back")),
            )
            if choice == "0":
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

    def resource_menu(self) -> None:
        """System-level Project administration; Job roles are assigned only inside BIC/SAW."""
        while True:
            choice=self.io.choose("SCRIPTURE PROJECTS", (
                ("1","SAGE Projects - view and maintain Projects already added to SAGE"),
                ("2","Add Projects to SAGE - choose from the Paratext Project Catalogue"),
                ("3","Validate SAGE Projects - check READY / WARNING / ERROR status"),
                ("4","Scan / Rescan Paratext Projects - refresh the discovery catalogue"),
                ("5","Original-language resources - configure governed @GRK and @HEB"),
                ("6","Advanced resources - VRS / RWC / SEMDOM / FLEx / Combine"),
                ("0","Back")))
            if choice=="0": return
            if choice=="1": self.registered_projects_menu()
            elif choice=="2": self.discover_register_projects_menu()
            elif choice=="3": self.validate_shared_registry()
            elif choice=="4": self.projects_root_menu()
            elif choice=="5": self.original_language_resources_menu()
            elif choice=="6":
                advanced=self.io.choose("Advanced resources", (("1","Configure base VRS override"),("2","Use Paratext root as base VRS default"),("3","RWC / SEMDOM / FLEx / Combine"),("4","Show resource paths"),("0","Back")))
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
                "RWC / SEMDOM / FLEx / Combine",
                (
                    ("1", "Status"),
                    ("2", "Initialise / update indexes"),
                    ("3", "Project bindings"),
                    ("4", "Reference sources"),
                    ("5", "Review semantic evidence"),
                    ("6", "Build / validate indexes"),
                    ("7", "Export FLEx / Combine"),
                    ("8", "Advanced source management"),
                    ("0", "Back"),
                ),
            )
            if choice == "0":
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
        """Bind primary/Greek resources and build their current indexes in one operator action."""
        config = load_ecosystem(self.store.settings_path)
        project_id = self.choose_registered_project_id("Primary SAGE Project")
        language = self.io.text("Primary semantic language")
        if not load_import_selection(config, language):
            raise ValidationError(f"No active semantic imports exist for {language}; import reference sources first")
        set_binding(config, project_id=project_id, language=language)
        result: dict[str, Any] = {"bindings": {project_id: language}, "indexes": {}}
        result["indexes"][language] = build_semantic_indexes(config, language=language)
        if self.io.confirm("Bind and build Greek semantic reference data too?", default=True):
            greek_project = active_ol_project_id(self.root, "GRK")
            if greek_project is None:
                raise ValidationError("Configured @GRK resource is not READY", code="OL_RESOURCE_NOT_READY", next_action="Configure @GRK under Scripture Projects > Original-language resources.")
            greek_language = self.io.text("Greek semantic language", default="grc")
            if not load_import_selection(config, greek_language):
                raise ValidationError(
                    f"No active semantic imports exist for {greek_language}; import the Greek reference first"
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
                ("2", "Import Greek biblical-term reference XLSX"),
                ("3", "Import FLEx LIFT snapshot"),
                ("4", "Import Combine LIFT snapshot"),
                ("5", "Import SIL Semantic Domains JSON"),
                ("6", "Import RapidWords specific-first folders DOCX"),
                ("0", "Back"),
            ),
        )
        if choice == "0":
            return
        if choice == "1":
            path = Path(normalize_operator_path(self.io.text("RWC seed XLSX path"))).expanduser()
            source_id = self.io.text("Immutable source ID")
            language = self.io.text("Semantic language")
            result = import_rwc_seed_xlsx(config, path, source_id=source_id, language=language)
        elif choice == "2":
            path = Path(normalize_operator_path(self.io.text("Greek reference XLSX path"))).expanduser()
            source_id = self.io.text("Immutable source ID", default="Greek-Luke-KeyTerms")
            result = import_greek_reference_xlsx(config, path, source_id=source_id)
        elif choice in {"3", "4"}:
            application = "FLEx" if choice == "3" else "Combine"
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
        elif choice == "5":
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
            (("1", "List reviewed senses"), ("2", "Set reviewed status"), ("3", "Clear reviewed status"), ("0", "Back")),
        )
        if choice == "0":
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
        reviewer = self.io.text("Reviewer / role")
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
        profile_choice = self.io.choose("Export profile", (("1", "FLEx"), ("2", "Combine"), ("0", "Back")))
        if profile_choice == "0":
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
            (("1", "Activate/deactivate imported snapshot"), ("2", "Select active SEMDOM/folder authority"), ("0", "Back")),
        )
        if choice == "0":
            return
        if choice == "1":
            language = self.io.text("Semantic language")
            source_id = self.io.text("Immutable source ID")
            state = self.io.choose("Import state", (("1", "Active"), ("2", "Inactive"), ("0", "Back")))
            if state == "0":
                return
            active = set_import_active(config, language=language, source_id=source_id, active=state == "1")
            self.io.write(json.dumps({"active_imports": active}, ensure_ascii=False, indent=2))
            self.io.write("Any existing index is now STALE until rebuilt.")
            return
        authority_type = self.io.choose(
            "Authority type", (("1", "SIL Semantic Domains"), ("2", "RapidWords folders"), ("0", "Back"))
        )
        if authority_type == "0":
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
                "providers": [
                    make_executor(provider, load_llm_settings(self.root)).status(
                        model=load_llm_settings(self.root)["providers"].get(provider, {}).get("model")
                    ).to_dict()
                    for provider in ("codex", "ollama", "lmstudio")
                ],
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
        self.io.write(f"Diagnostics: {destination}")
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
        self.io.write(f"What happened: {exc.message}")
        self.io.write(f"Reason code:   {exc.code}")
        self.io.write("Why it matters: The requested action did not complete; existing governed Project and Job data was not silently changed.")
        if exc.next_action:
            self.io.write(f"Next action:   {exc.next_action}")
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
    center.guided_setup(pause_at_end=False)
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
