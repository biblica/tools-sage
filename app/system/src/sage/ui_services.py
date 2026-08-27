"""UI-independent presentation and session services shared by SAGE interfaces.

This module is the first extraction boundary for the 0.01 Beta TUI migration. It keeps
operator-facing state assembly out of terminal-specific rendering code so the
classic menu, Textual TUI, and future interfaces can consume the same facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import SageError, ValidationError
from .hashing import sha256_file
from .interface_localization import InterfaceLocalizer
from .jobs import TOOL_IDS, JobStore
from .llm_settings import load_llm_settings, local_ai_policy_status
from .model_service import ModelService
from .paratext_catalog import catalog_summary, load_paratext_catalog, scan_paratext_projects
from .project_inventory import registered_project_records
from .progress import format_activity_label, format_progress_line, quantify_run
from .resource_mounts import load_resource_mount_state, normalize_operator_path, set_project_root
from .runtime_status import AIStatus, RuntimeStatus, utc_now
from .registry import load_ecosystem
from .storage import storage_layout
from .state import ecosystem_state_path, read_state
from .standard import load_standard


@dataclass(frozen=True)
class UISection:
    """One top-level operator surface exposed by interactive SAGE interfaces."""

    view_id: str
    label: str
    description: str


@dataclass(frozen=True)
class StartupReadiness:
    """Canonical startup prerequisite state shared by every interactive interface."""

    status: str
    requires_setup: bool
    next_step: str
    next_label: str
    configuration: str
    projects_root_status: str
    projects_root: str | None
    scripture_resources: str
    configured_tools: tuple[str, ...]
    initialization: dict[str, Any]
    workflows: dict[str, str]
    projects: dict[str, Any]
    ai: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly startup report for menus, TUI panels, and diagnostics."""
        return {
            "status": self.status,
            "requires_setup": self.requires_setup,
            "next_step": self.next_step,
            "next_label": self.next_label,
            "runtime": "READY",
            "configuration": self.configuration,
            "projects_root_status": self.projects_root_status,
            "projects_root": self.projects_root,
            "scripture_resources": self.scripture_resources,
            "configured_tools": list(self.configured_tools),
            "initialization": self.initialization,
            "workflows": self.workflows,
            "projects": self.projects,
            "ai": self.ai,
        }


TOP_LEVEL_SECTIONS: tuple[UISection, ...] = (
    UISection("projects", "Scripture Projects", "Project discovery, registration, validation and Scripture resources."),
    UISection("bic", "BIC", "BIC Jobs, Runs, reports, recovery, generations and governed TARGET work."),
    UISection("saw", "SAW", "SAW Jobs, checks, reports, and workflow recovery."),
    UISection("configure", "SAGE Maintenance", "System settings, diagnostics, storage maintenance and system recovery."),
)


def context_help_lines(title: str) -> tuple[str, ...]:
    """Return concise context-sensitive help independent of the rendering interface."""
    key = str(title).strip().upper()
    if "PARATEXT" in key or "PROJECT" in key:
        return (
            "Quick Scan discovers immediate Project folders by Settings.xml marker only.",
            "Full Scan opens and validates Project metadata, Scripture inventory, canon and VRS.",
            "Selecting a newly discovered Project validates that Project on demand.",
        )
    if key == "AI" or "AI SETUP" in key or "MODEL" in key or "CODEX" in key or "CONFIGURE" in key:
        return (
            "AI status verifies the configured provider, authentication, model and reasoning without generating output.",
            "Check LLM connection is the explicit end-to-end model-generation test.",
        )
    if "BIC" in key:
        return (
            "BIC operates through governed Jobs and Runs. SOURCE and DONOR remain read-only; TARGET writes are governed.",
            "Status shows the active task and current AI configuration without leaving the current view.",
        )
    if "SAW" in key:
        return (
            "SAW operates through governed Jobs and Runs using WIP and REFERENCE bindings.",
            "Status shows the active task and current AI configuration without leaving the current view.",
        )
    return (
        "A Back returns one view; B Main Menu returns home; C exits SAGE.",
        "D changes interface language; E shows context Help; F shows current Status.",
        "The TUI is EXPERIMENTAL / UNSTABLE; the classic menu and scriptable CLI remain authoritative.",
    )


def probe_workflow_ai(
    root: Path,
    runtime_status: RuntimeStatus,
    *,
    service: ModelService | None = None,
    refresh: bool = False,
    dry_run_provider: bool = False,
    allow_dry_run: bool = True,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Return the canonical workflow-AI prerequisite result for any interactive UI."""
    cached = runtime_status.ai
    if cached.last_checked and not refresh:
        return cached.to_dict()
    if dry_run_provider and allow_dry_run:
        status = AIStatus(
            connection="READY",
            provider_id="dry-run",
            provider="Dry-run test provider",
            model="dry-run",
            reasoning_level="NOT APPLICABLE",
            prerequisite_status="READY",
            last_checked=utc_now(),
            available=True,
            ready=True,
            auth_mode="TEST",
        )
        runtime_status.ai = status
        return status.to_dict()

    model_service = service or ModelService(root)
    try:
        preflight = dict(model_service.quick_codex_status())
    except SageError as exc:
        preflight = {
            "available": False,
            "ready": False,
            "diagnostic": exc.message,
            "reason_code": exc.code,
        }
    if not preflight.get("available") or not preflight.get("ready"):
        status = AIStatus(
            connection="ACTION NEEDED",
            provider_id="codex",
            provider="OpenAI / ChatGPT",
            model=None,
            reasoning_level=None,
            prerequisite_status="BLOCKED",
            last_checked=utc_now(),
            reason_code=str(preflight.get("reason_code") or "LLM_PROVIDER_NOT_READY"),
            diagnostic=str(preflight.get("diagnostic") or "Workflow AI is not ready"),
            available=bool(preflight.get("available")),
            ready=False,
            auth_mode=preflight.get("auth_mode"),
            version=preflight.get("version"),
        )
        runtime_status.ai = status
        return status.to_dict()

    try:
        result = model_service.readiness_check()
        provider_id = str(result.get("provider") or "codex")
        status = AIStatus(
            connection="READY",
            provider_id=provider_id,
            provider="OpenAI / ChatGPT" if provider_id == "codex" else provider_id,
            model=str(result.get("model") or "PROVIDER DEFAULT"),
            reasoning_level=str(result.get("reasoning_effort") or "PROVIDER DEFAULT").upper(),
            prerequisite_status="READY",
            last_checked=utc_now(),
            available=True,
            ready=True,
            auth_mode=preflight.get("auth_mode"),
            version=preflight.get("version"),
        )
    except SageError as exc:
        settings = model_service.settings()
        provider_id = str(settings.get("selected_provider") or "codex")
        item = dict(settings.get("providers", {}).get(provider_id, {}))
        status = AIStatus(
            connection="ACTION NEEDED",
            provider_id=provider_id,
            provider="OpenAI / ChatGPT" if provider_id == "codex" else provider_id,
            model=item.get("model"),
            reasoning_level=(str(item.get("reasoning_effort")).upper() if item.get("reasoning_effort") else None),
            prerequisite_status="BLOCKED",
            last_checked=utc_now(),
            reason_code=exc.code,
            diagnostic=exc.message,
            available=True,
            ready=False,
            auth_mode=preflight.get("auth_mode"),
            version=preflight.get("version"),
        )
    runtime_status.ai = status
    return status.to_dict()


class OperatorUIService:
    """Assemble read-only operator state for classic and full-screen interfaces."""

    # Keep aggregation here so interactive surfaces never re-implement governed state reads.

    def __init__(
        self,
        *,
        root: Path,
        settings_path: Path,
        runtime_status: RuntimeStatus | None = None,
    ) -> None:
        """Initialize shared paths, stores, localization, and runtime status."""
        self.root = root.expanduser().resolve()
        self.settings_path = settings_path.expanduser().resolve()
        self.store = JobStore(self.root, self.settings_path)
        self.localizer = InterfaceLocalizer.load(self.root, self.settings_path)
        self.runtime_status = runtime_status or RuntimeStatus(interface_language=self.localizer.language)

    def refresh_localizer(self) -> InterfaceLocalizer:
        """Reload interface-localization state after an external or TUI language change."""
        self.localizer = InterfaceLocalizer.load(self.root, self.settings_path)
        self.runtime_status.interface_language = self.localizer.language
        return self.localizer

    def set_interface_language(self, language: str) -> str:
        """Persist one supported interface language and refresh this service."""
        self.localizer.set_language(language)
        self.refresh_localizer()
        return self.localizer.language

    def configured_tools(self) -> set[str]:
        """Return workflows that currently have one active Job binding."""
        return {tool for tool in TOOL_IDS if self.store.active_job(tool) is not None}

    def projects_root_status(self) -> tuple[str, Path | None]:
        """Return live readiness for the required workstation Paratext Projects root."""
        state = load_resource_mount_state(self.root)
        raw = state.get("projects_root")
        if not raw:
            return "NOT_CONFIGURED", None
        path = Path(str(raw)).expanduser()
        return ("READY" if path.is_dir() else "MISSING"), path

    def configure_projects_root(
        self,
        value: str | Path,
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Persist one Paratext Projects root and perform its governed Quick Scan."""
        project_root = Path(normalize_operator_path(str(value))).expanduser()
        set_project_root(self.root, project_root=project_root, progress=progress)
        catalogue = load_paratext_catalog(self.root)
        return {
            "projects_root": catalogue.get("projects_root"),
            "catalog": catalog_summary(catalogue),
        }

    def scan_projects(
        self,
        *,
        full: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Rescan the configured Projects root using the canonical Paratext catalog service."""
        root_status, projects_root = self.projects_root_status()
        if root_status != "READY" or projects_root is None:
            raise ValidationError(
                "Configure a valid Paratext/PTLite Projects root first",
                code="PROJECT_ROOT_NOT_FOUND",
            )
        return scan_paratext_projects(self.root, projects_root, full=full, progress=progress)

    def live_initialization_results(self, previous: dict[str, Any] | None = None) -> dict[str, Any]:
        """Reconcile cached setup summaries with each active Job's current state receipt."""
        prior = dict(previous or {})
        results: dict[str, Any] = {}
        ready_states = {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}
        for tool in TOOL_IDS:
            job = self.store.active_job(tool)
            if job is None:
                continue
            try:
                settings = self.store.ensure_runtime_files(job)
                config = load_ecosystem(settings)
                state = read_state(ecosystem_state_path(config.runtime_state_root))
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
                results[job.job_id] = {
                    **dict(prior.get(job.job_id) or {}),
                    "status": status,
                    "source": "JOB_INITIALISATION_RECEIPT",
                    "ready": status in ready_states,
                }
            except SageError as exc:
                results[job.job_id] = {
                    "status": "BLOCKED",
                    "reason_code": exc.code,
                    "message": exc.message,
                    "source": "JOB_INITIALISATION_RECEIPT",
                    "ready": False,
                }
        return results

    def workflow_setup_status(self, tool: str, initialization: dict[str, Any]) -> str:
        """Return one concise independent setup status for BIC or SAW."""
        job = self.store.active_job(tool)
        if job is None:
            stale_pointer = self.store.stale_active_job_pointers().get(tool)
            if stale_pointer:
                return f"RECOVERY NEEDED - {stale_pointer} [Job manifest missing]"
            return "NOT CONFIGURED"
        ready_states = {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}
        status = str(initialization.get(job.job_id, {}).get("status", ""))
        if status in ready_states:
            return f"READY - {job.display_name}"
        return f"CONFIGURED - {job.display_name} [validation needed]"

    def startup_next_step(
        self,
        ai: dict[str, Any],
        configured_tools: set[str],
        initialization: dict[str, Any],
        scripture_resources: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Return the next prerequisite action from canonical live startup state."""
        if not self.settings_path.is_file():
            return "REPAIR_CONFIGURATION", "Repair SAGE configuration"
        if self.store.stale_active_job_pointers():
            return "RECOVER_ACTIVE_JOB_POINTERS", "Clear stale active Job and Run selections"
        scripture_status = str((scripture_resources or {}).get("status") or "NOT CHECKED")
        if scripture_status == "BLOCKED":
            return "VALIDATE_SCRIPTURE", "Resolve Scripture resource validation"
        if not ai.get("available"):
            return "INSTALL_CODEX", "Install Codex CLI"
        if not ai.get("ready"):
            return "LOGIN_CHATGPT", "Sign in with ChatGPT"
        projects_root_status, _projects_root = self.projects_root_status()
        if projects_root_status == "NOT_CONFIGURED":
            return "CONFIGURE_PROJECT_ROOT", "Configure Paratext Projects root"
        if projects_root_status != "READY":
            return "CONFIGURE_PROJECT_ROOT", "Repair Paratext Projects root"
        if not configured_tools:
            return "CONFIGURE_WORKFLOW", "Configure BIC or SAW"
        ready_states = {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}
        for tool in sorted(configured_tools):
            job = self.store.active_job(tool)
            if job is None:
                continue
            status = str(initialization.get(job.job_id, {}).get("status", ""))
            if status not in ready_states:
                return "VALIDATE", "Manage active Jobs"
        return "COMPLETE", "SAGE is ready"

    def startup_readiness(
        self,
        ai: dict[str, Any] | None = None,
        *,
        persist_completion: bool = False,
    ) -> dict[str, Any]:
        """Return one canonical startup gate from current local state and the latest AI probe."""
        setup = self.store.setup_state() or {}
        provider = dict(setup.get("llm") or {})
        if ai is not None:
            provider.update(dict(ai))
        elif self.runtime_status.ai.last_checked or self.runtime_status.ai.connection == "CHECKING":
            provider.update(self.runtime_status.ai.to_dict())
        initialization = self.live_initialization_results(
            setup.get("initialization") if isinstance(setup.get("initialization"), dict) else None
        )
        scripture = dict(setup.get("scripture_resources") or {})
        configured = self.configured_tools()
        projects_root_status, projects_root = self.projects_root_status()
        catalog = catalog_summary(load_paratext_catalog(self.root))
        next_step, next_label = self.startup_next_step(provider, configured, initialization, scripture)
        scripture_status = str(scripture.get("status") or "NOT CHECKED")
        if next_step == "COMPLETE" and scripture_status not in {"READY", "READY_EMPTY"}:
            next_step, next_label = "VALIDATE_SCRIPTURE", "Validate Scripture resources"
        # Job initialization is a workflow-entry gate, not a system-startup gate.
        # Once host prerequisites are ready, Main remains available and the Job
        # advertises validation needed until its first governed operation.
        requires_setup = next_step not in {"COMPLETE", "VALIDATE"}
        status = "READY" if not requires_setup else "INCOMPLETE"
        workflows = {tool: self.workflow_setup_status(tool, initialization) for tool in TOOL_IDS}
        snapshot = StartupReadiness(
            status=status,
            requires_setup=requires_setup,
            next_step=next_step,
            next_label=next_label,
            configuration="READY" if self.settings_path.is_file() else "ACTION NEEDED",
            projects_root_status=projects_root_status,
            projects_root=str(projects_root) if projects_root is not None else None,
            scripture_resources=str(scripture.get("status") or "NOT CHECKED"),
            configured_tools=tuple(sorted(configured)),
            initialization=initialization,
            workflows=workflows,
            projects={
                "discovered": catalog.get("discovered", catalog.get("projects", 0)),
                "validated": catalog.get("validated", 0),
                "pending": catalog.get("pending", 0),
                "registered": len(registered_project_records(self.root)),
            },
            ai=provider,
        ).to_dict()
        if persist_completion and next_step == "COMPLETE":
            refreshed = {key: value for key, value in setup.items() if key not in {"schema_version", "updated_utc"}}
            refreshed.update(
                {
                    "status": "COMPLETE",
                    "next_step": "COMPLETE",
                    "next_label": "SAGE is ready",
                    "active_jobs": self.store.active_jobs(),
                    "enabled_tools": sorted(configured),
                    "initialization": initialization,
                    "llm": provider,
                }
            )
            self.store.write_setup_state(refreshed)
        return snapshot

    def release_snapshot(self) -> dict[str, Any]:
        """Return current release identity from the governed standard."""
        standard = load_standard(self.root)
        return {
            "version": standard.version,
            "release_status": standard.release_status,
            "public_release_ready": standard.public_release_ready,
            "feature_classifications": dict(standard.feature_classifications),
        }

    def job_summary(self, tool: str) -> str:
        """Return one compact active-Job readiness summary."""
        job = self.store.active_job(tool)
        if job is None:
            return "NONE"
        try:
            from .registry import load_ecosystem
            from .state import ecosystem_state_path, read_state

            config = load_ecosystem(self.store.ensure_runtime_files(job))
            state = read_state(ecosystem_state_path(config.runtime_state_root))
            readiness = str(state.get("state", "NOT INITIALIZED")).replace("_", " ")
        except SageError:
            readiness = "ACTION NEEDED"
        return f"{job.display_name} [{readiness}]"

    def last_run_summary(self, tool: str | None = None) -> str:
        """Return one compact last-Run summary, optionally restricted to one workflow."""
        item = self.store.last_run() if tool is None else self._latest_workflow_run(tool)
        if not item:
            return "NONE"
        job, run = item
        return f"{run.tool.upper()} {job.display_name}: {run.scope} [{run.current_stage}, {run.status}]"

    def _latest_workflow_run(self, tool: str) -> tuple[Any, Any] | None:
        """Return the most recently updated Run for one workflow across all of its Jobs."""
        normalized = tool.strip().lower()
        if normalized not in TOOL_IDS:
            raise ValueError(f"Unknown workflow: {tool}")
        candidates: list[tuple[Any, Any]] = []
        for job in self.store.discover(normalized, include_archived=True):
            try:
                candidates.extend((job, run) for run in self.store.list_runs(job, include_archived=True))
            except SageError:
                continue
        if not candidates:
            return None
        return max(candidates, key=lambda item: (str(item[1].updated_utc), str(item[1].run_id)))

    def last_run_is_resumable(self) -> bool:
        """Return whether the recorded last Run represents unfinished operator work."""
        item = self.store.last_run()
        if not item:
            return False
        _, run = item
        return run.status not in {"COMPLETE", "ARCHIVED", "ABANDONED"}

    def model_summary(self) -> str:
        """Return selected workflow-AI policy/model summary without a network probe."""
        settings = load_llm_settings(self.root)
        provider = str(settings["selected_provider"])
        item = settings["providers"].get(provider, {})
        model = item.get("model")
        reasoning = item.get("reasoning_effort")
        if provider == "codex" and item.get("selection_mode") == "AUTO":
            return "codex, automatic task policy"
        suffix = f", {model}" if model else ", provider default"
        if reasoning:
            suffix += f", {reasoning}"
        return f"{provider}{suffix}"

    def run_progress_snapshot(self, job: Any, run: Any) -> dict[str, Any]:
        """Return one canonical sequential Run progress snapshot derived from governed ACT manifests."""
        policy = dict(getattr(job, "progress_quantifier", {}) or {})
        progress = quantify_run(
            root=self.root,
            task_manifests=getattr(run, "task_manifests", ()),
            run_status=str(getattr(run, "status", "")),
            current_stage=str(getattr(run, "current_stage", "")),
            basis=str(policy.get("basis") or "PROJECTED_HANDOFF_ESTIMATED_TOKENS"),
            result=getattr(run, "result", None),
            reason_code=getattr(run, "result_reason", None),
        ).to_dict()
        progress["job_id"] = getattr(job, "job_id", None)
        progress["run_id"] = getattr(run, "run_id", None)
        progress["stage"] = getattr(run, "current_stage", None)
        progress["line"] = format_progress_line(str(getattr(job, "job_id", "IDLE")), progress)
        progress["activity"] = format_activity_label(progress)
        return progress

    def active_progress_snapshot(self) -> dict[str, Any] | None:
        """Return progress for the single current/most-recent Run used by interactive status surfaces."""
        last = self.store.last_run()
        if last is None:
            return None
        job, run = last
        return self.run_progress_snapshot(job, run)

    def runtime_snapshot(self) -> dict[str, Any]:
        """Return canonical session/configuration status without deep Project validation."""
        status = self.runtime_status
        status.interface_language = self.localizer.language
        catalogue = load_paratext_catalog(self.root)
        summary = catalog_summary(catalogue)
        mount_state = load_resource_mount_state(self.root)
        projects_root = mount_state.get("projects_root")
        last = self.store.last_run()
        job_progress = None
        if last:
            job, run = last
            job_progress = self.run_progress_snapshot(job, run)
            if not status.current_run:
                status.current_job = job.job_id
                status.current_project = status.current_project or job.output_project
                status.current_run = getattr(run, "run_id", None) or str(getattr(run, "scope", ""))
            if run.status not in {"COMPLETE", "ARCHIVED", "ABANDONED"}:
                if status.state not in {"RUNNING", "CHECKING"}:
                    status.state = "ACTIVE"
                status.active_task = status.active_task or job_progress.get("active_skill_id") or job_progress.get("active_operation") or run.operation
                status.stage = status.stage or run.current_stage
                percent = job_progress.get("percent")
                status.progress = status.progress or (f"{percent}%" if percent is not None else run.status)
            elif status.state == "ACTIVE":
                status.state = "IDLE"
                status.active_task = None
                status.stage = None
                status.progress = None
        return {
            **status.to_dict(),
            "job_progress": job_progress,
            "local_ai": local_ai_policy_status(self.root),
            "projects_root": projects_root,
            "projects": {
                "discovered": summary.get("discovered", summary.get("projects", 0)),
                "validated": summary.get("validated", 0),
                "pending": summary.get("pending", 0),
                "registered": len(registered_project_records(self.root)),
            },
            "interface_language_name": self.localizer.language_name(),
        }

    def assistive_status_explanation(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Optionally phrase canonical status facts through assistive-only Local AI."""
        state = snapshot or self.runtime_snapshot()
        local_ai = dict(state.get("local_ai") or {})
        if not local_ai.get("enabled"):
            return None
        ai = dict(state.get("ai") or {})
        progress = dict(state.get("job_progress") or {})
        facts = {
            "state": state.get("state"),
            "active_task": state.get("active_task"),
            "stage": state.get("stage"),
            "current_job": state.get("current_job"),
            "current_run": state.get("current_run"),
            "resource_status": state.get("resource_status"),
            "ai_connection": ai.get("connection"),
            "ai_prerequisite": ai.get("prerequisite"),
            "reporting_mode": local_ai.get("reporting_mode"),
            "secondary_language_allowed": local_ai.get("secondary_language_allowed"),
            "reason_code": progress.get("reason_code") or local_ai.get("reason_code"),
        }
        try:
            from .local_assistive import LocalTransformService

            return LocalTransformService(self.root).explain_status(facts).to_dict()
        except Exception:
            # Optional assistive phrasing must never prevent deterministic status display.
            return None

    def assistive_diagnostic_explanation(
        self,
        *,
        reason_code: str,
        status: str,
        approved_actions: tuple[str, ...] = (),
        component: str | None = None,
        severity: str | None = None,
    ) -> dict[str, Any] | None:
        """Optionally phrase a controller diagnostic without changing its approved actions."""
        if not local_ai_policy_status(self.root)["enabled"]:
            return None
        facts = {
            "reason_code": reason_code,
            "status": status,
            "component": component,
            "severity": severity,
            "approved_action_count": len(approved_actions),
        }
        try:
            from .local_assistive import LocalTransformService

            return LocalTransformService(self.root).explain_diagnostic(
                facts,
                approved_actions=approved_actions,
            ).to_dict()
        except Exception:
            return None

    def assistive_action_explanation(
        self,
        *,
        status: str,
        action_context: str,
        approved_actions: tuple[str, ...],
        reason_code: str | None = None,
    ) -> dict[str, Any] | None:
        """Optionally explain an already-approved action set without adding alternatives."""
        if not local_ai_policy_status(self.root)["enabled"]:
            return None
        facts = {
            "status": status,
            "reason_code": reason_code,
            "action_context": action_context,
            "approved_action_count": len(approved_actions),
        }
        try:
            from .local_assistive import LocalTransformService

            return LocalTransformService(self.root).explain_approved_actions(
                facts,
                approved_actions=approved_actions,
            ).to_dict()
        except Exception:
            return None

    def main_snapshot(self) -> dict[str, Any]:
        """Return the top-level dashboard facts used by both interactive shells."""
        release = self.release_snapshot()
        runtime = self.runtime_snapshot()
        return {
            **release,
            "bic_job": self.job_summary("bic"),
            "saw_job": self.job_summary("saw"),
            "last_run": self.last_run_summary(),
            "unfinished_run": self.last_run_is_resumable(),
            "model": self.model_summary(),
            "ai": runtime["ai"],
            "projects": runtime["projects"],
            "projects_root": runtime["projects_root"],
            "interface_language": runtime["interface_language"],
            "interface_language_name": runtime["interface_language_name"],
            "job_progress": runtime.get("job_progress"),
        }

    def section_snapshot(self, view_id: str) -> dict[str, Any]:
        """Return bounded read-only data for one top-level TUI section."""
        view = view_id.strip().lower()
        if view == "main":
            return self.main_snapshot()
        if view == "projects":
            records = registered_project_records(self.root)
            catalog = catalog_summary(load_paratext_catalog(self.root))
            mount_state = load_resource_mount_state(self.root)
            rows = []
            for project_id, record in sorted(records.items(), key=lambda item: item[0].casefold()):
                language = record.get("language")
                if isinstance(language, dict):
                    language_value = language.get("code") or language.get("profile") or "—"
                else:
                    language_value = language or record.get("language_code") or "—"
                metadata = record.get("paratext_metadata")
                metadata_name = metadata.get("full_name") if isinstance(metadata, dict) else None
                rows.append(
                    {
                        "project_id": project_id,
                        "name": record.get("display_name") or metadata_name or project_id,
                        "language": language_value,
                        "status": record.get("validation_status") or record.get("status") or "UNKNOWN",
                    }
                )
            return {
                "projects_root": mount_state.get("projects_root"),
                "catalog": catalog,
                "registered": rows,
            }
        if view in {"bic", "saw"}:
            jobs = []
            active = self.store.active_job(view)
            for job in self.store.discover(view, include_archived=True):
                jobs.append(
                    {
                        "job_id": job.job_id,
                        "display_name": job.display_name,
                        "active": bool(active and active.job_id == job.job_id),
                        "archived": str(job.status).upper() == "ARCHIVED",
                    }
                )
            return {
                "active_job": active.job_id if active else None,
                "jobs": jobs,
                "last_run": self.last_run_summary(view),
            }
        if view == "reports":
            report_root = storage_layout(self.root).reports_root
            report_files = []
            if report_root.is_dir():
                paths = [
                    path
                    for path in report_root.rglob("*")
                    if path.is_file() and path.name.lower() != "readme.md" and path.suffix.lower() in {".md", ".txt"}
                ]
                paths.sort(
                    key=lambda path: (path.stat().st_mtime_ns, path.as_posix().casefold()),
                    reverse=True,
                )
                report_files = [path.relative_to(self.root).as_posix() for path in paths[:25]]
            return {"report_root": str(report_root), "files": report_files}
        if view == "configure":
            mount_state = load_resource_mount_state(self.root)
            config = load_ecosystem(self.settings_path)
            language_rows = [
                {"profile": tag, "script": namespace.script, "grammar_profiles": len(namespace.variants)}
                for tag, namespace in sorted(config.language_profiles.items())
            ]
            return {
                "interface_language": self.localizer.language,
                "interface_language_name": self.localizer.language_name(),
                "localization_source": str(self.localizer.source_path),
                "workflow_ai": self.runtime_status.ai.to_dict(),
                "local_ai": local_ai_policy_status(self.root),
                "model_policy": self.model_summary(),
                "projects_root": mount_state.get("projects_root"),
                "settings": str(self.settings_path),
                "languages": language_rows,
                "language_relationships": str(self.root / "system" / "config" / "languages" / "relationships.yml"),
            }
        if view == "recovery":
            setup = self.store.setup_state() or {}
            return {
                "setup_status": setup.get("status") or "NOT RECORDED",
                "next_step": setup.get("next_step") or "—",
                "last_run": self.last_run_summary(),
                "sage_home": str(self.root),
                "state_root": str(self.store.state_root),
                "diagnostics": str(self.store.state_root / "diagnostics"),
            }
        raise ValueError(f"Unknown UI section: {view_id}")
