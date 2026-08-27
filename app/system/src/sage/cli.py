"""Command-line interface for the SAGE v0.01beta build."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .atomic import atomic_write_json, atomic_write_text
from .act_tasks import (
    SAW_CHECK_TYPES,
    _one_book_file,
    aggregate_act_plan,
    create_act_task,
    submit_act_task,
    validate_act_request_readiness,
)
from .auto_resolution import render_auto_resolution_report, resolve_auto_settings
from .bounded_target import list_target_history, revert_target_scope
from .bic_memory import (
    MEMORY_STATES,
    import_lexicon_transactionally,
    list_memory_records,
    record_human_memory_review,
    rollback_lexicon_import_transactionally,
    transition_memory_record_transactionally,
)
from .external_access import READ_ONLY_SCRIPTURE, READ_WRITE_TARGET, validate_external_file
from .errors import (
    ConfigurationError,
    InputRequiredError,
    OperatorCancelledError,
    SageError,
    ValidationError,
)
from .display_paths import operator_path, operator_text
from .platform_commands import (
    is_sage_launcher_token,
    render_sage_command,
    sage_launcher,
    split_operator_command,
)
from .generations import (
    project_validation_fingerprint,
    publish_generated_target,
    resolve_generation,
    verify_generation,
)
from .grammar import compile_grammar_contract, load_grammar_profile
from .grammar_governance import (
    GRAMMAR_REVIEW_DECISIONS,
    list_grammar_profile_reviews,
    record_grammar_profile_review,
)
from .hashing import sha256_bytes, sha256_file
from .human_output import (
    LocalizedConsoleStream,
    OperationalLogger,
    paired_catalogue_text,
    report_language_authority,
    render_report_language_authority,
    resolved_languages,
)
from .locking import WorkspaceLock
from .llm_tasks import execute_task
from .llm_settings import load_llm_settings
from .model_policy import task_profile_key
from .model_service import ModelService
from .executors import PROVIDER_IDS
from .natural_language import append_request_log, interpret_request
from .init_remediation import run_guided_init_remediation, run_targeted_init_remediation
from .operator_overrides import clear_operator_overrides
from .profiles import WorkflowProfile, load_workflow_profile
from .rtc_planner import (
    RTC_HANDOFF_CONTRACT_VERSION,
    RTC_PLANNER_VERSION,
    RTC_PROMPT_SCHEMA_PROJECTION_VERSION,
    package_summary,
    plan_rtc_work_units,
    rtc_slicing_policy,
    vrs_source_equivalence_spans,
)
from .guided_input import (
    GuidedArgumentParser,
    Suggestion,
    confirm_correction,
    configure_prompt_renderer,
    prompt_for_value,
    rank_suggestions,
    parse_args_with_guidance,
    resolve_from_choices,
    suggestions_payload,
    suggest_existing_paths,
)
from .references import (
    BOOK_ALIASES,
    BOOK_LABELS,
    BOOK_ORDER,
    parse_scope,
    replace_scope_book,
    resolve_book,
    split_scope_book,
)
from .registry import EcosystemConfig, load_ecosystem
from .reset_state import reset_project_state
from .runtime_paths import workflow_memory_root
from .stage_reset import STAGES, reset_workflow_stage
from .plan_continuation import continue_saw_plan
from .resource_mounts import (
    clear_base_vrs_root,
    load_resource_mount_state,
    load_resource_mounts,
    remove_resource_mount,
    set_base_vrs_root,
    set_resource_mount,
)
from .resource_rights import validate_resource_rights
from .scripture import compile_project, compile_project_scope, discover_book_ids
from .semantic_cli import register_rwc_parser
from .standard import SageStandard, load_standard
from .storage import clear_persisted_data_home, persist_data_home, storage_layout, resolve_declared_path
from .state import ecosystem_state_path, read_state, write_ecosystem_state, write_state
from .transactions import incomplete_transactions, recover_transaction
from .jobs import JobStore as JobStore
from .job_layout import migrate_job_layout, render_job_layout_audit, verify_job_layout, write_job_layout_audit
from .validation import validate_package, validate_static_ecosystem
from .work_units import (
    build_evidence_packet,
    manifest,
    plan_work_units,
    records_from_project_result,
    select_records_for_scope,
)
from .evidence import serialize_evidence
from .ui_format import menu_item
from .usj import USJ_COMPILER
from .vocabulary import CANONICAL_TARGET_TEXT_OPERATION, require_canonical_operation_set


SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
PRIMARY_ROLE = {"bic": "CONTENT_SOURCE", "saw": "WIP"}
ALLOWED_OPERATIONS = {
    "bic": {"inspect", CANONICAL_TARGET_TEXT_OPERATION, "self_check"},
    "saw": {"rtc", "focused", "ol"},
}
SHORTCUT_COMMANDS: dict[str, dict[str, tuple[str, ...]]] = {
    "bic": {
        "status": ("workflow", "status", "--workflow", "bic"),
        "inspect": ("task", "create", "--workflow", "bic", "--operation", "inspect"),
        CANONICAL_TARGET_TEXT_OPERATION: (
            "task", "create", "--workflow", "bic", "--operation", CANONICAL_TARGET_TEXT_OPERATION
        ),
        "self_check": ("task", "create", "--workflow", "bic", "--operation", "self_check"),
        "submit": ("task", "submit"),
        "plan": ("workflow", "plan", "--workflow", "bic"),
        "restart-scope": ("project", "restart-scope"),
        "target-history": ("project", "target-history"),
        "revert-target-scope": ("project", "revert-target-scope"),
    },
    "saw": {
        "status": ("workflow", "status", "--workflow", "saw"),
        "rtc": ("task", "create", "--workflow", "saw", "--operation", "rtc"),
        "focused": ("task", "create", "--workflow", "saw", "--operation", "focused"),
        "ol": ("task", "create", "--workflow", "saw", "--operation", "ol"),
        "submit": ("task", "submit"),
        "plan": ("workflow", "plan", "--workflow", "saw"),
    },
}

require_canonical_operation_set(ALLOWED_OPERATIONS["bic"])


GUIDE_TOPICS = ("start", "setup", "surfaces", "task", "recovery")


def _guide_payload(topic: str) -> dict[str, Any]:
    """Return compact fallback guidance; normal first-use guidance lives in the interactive launcher."""
    launcher = sage_launcher()
    platform_docs = "windows" if os.name == "nt" else "macos-linux"
    common_documents = [
        "docs/OPERATOR-GUIDE.md",
        f"docs/{platform_docs}/CHEAT-SHEET.md",
        f"docs/{platform_docs}/RECOVERY.md",
        f"docs/{platform_docs}/ERRORS.md",
    ]
    topics: dict[str, dict[str, Any]] = {
        "start": {
            "title": "SAGE START",
            "summary": "Run SAGE directly; guided setup and resume state are built into the launcher.",
            "steps": [
                f"Run `{launcher}`.",
                "If prerequisites or setup are incomplete, follow the recommended setup action.",
                "If unfinished work exists, choose Resume; otherwise select a new BIC or SAW task.",
            ],
        },
        "setup": {
            "title": "SAGE STARTUP",
            "summary": "Startup readiness is resumable and menu-driven rather than documentation-driven.",
            "steps": [
                f"Run `{launcher}` and choose SAGE Maintenance when needed.",
                "SAGE checks Codex CLI, ChatGPT sign-in, Jobs, Projects, and Project initialization in sequence.",
                "Exit safely at any point; the next launch resumes from localdata/.system/state/setup-state.json.",
            ],
        },
        "surfaces": {
            "title": "SAGE SURFACES",
            "summary": "SAGE owns state and writes; the provider receives sealed governed tasks only.",
            "steps": [
                "SAGE controller: project selection, evidence, task state, validation, commits, and recovery.",
                "Codex CLI: OpenAI connection using ChatGPT sign-in; desktop app is not required.",
                "API keys, service accounts, direct OpenAI API calls, and API fallback are prohibited.",
            ],
        },
        "task": {
            "title": "SAGE TASK",
            "summary": "Use the BIC/SAW menus for normal work; direct task commands remain available for advanced use.",
            "steps": [
                f"Run `{launcher}` and select BIC or SAW.",
                "Create or resume one bounded run.",
                "SAGE continues through the recorded checkpoint-aware state machine.",
            ],
        },
        "recovery": {
            "title": "SAGE RECOVERY",
            "summary": "Use recorded controller state; never patch generated task controls manually.",
            "steps": [
                f"Run `{launcher}` and open BIC/SAW Recovery and diagnostics, or SAGE Maintenance for system recovery.",
                f"Run `{launcher} workspace doctor` for direct diagnostics when needed.",
                f"Read docs/{platform_docs}/RECOVERY.md or ERRORS.md only when guided recovery is insufficient.",
            ],
        },
    }
    selected = topics[topic]
    return {
        "status": "GUIDANCE",
        "topic": topic,
        "title": selected["title"],
        "summary": selected["summary"],
        "steps": selected["steps"],
        "documents": common_documents,
        "mutates_workspace": False,
    }

def command_guide(args: argparse.Namespace) -> int:
    """Print integrated setup, surface, task, or recovery guidance."""
    topic = getattr(args, "guide_topic", None) or "start"
    payload = _guide_payload(topic)
    if args.json:
        _print_json(payload)
        return 0
    print(payload["title"])
    print(payload["summary"])
    print()
    for index, step in enumerate(payload["steps"], start=1):
        print(menu_item(index, step))
    print()
    print("Normal operation: run SAGE directly; documentation is fallback only.")
    print("Help index: docs/OPERATOR-GUIDE.md")
    return 0


def command_menu(args: argparse.Namespace) -> int:
    """Open the menu-driven SAGE Control Center."""
    from .menu import run_menu

    settings = _settings_path(args.settings)
    config = load_ecosystem(settings)
    return run_menu(
        sage_root=config.root,
        settings_path=settings,
        script_path=Path(args.script).expanduser().resolve() if args.script else None,
        force_setup=bool(args.force_setup),
        skip_setup=bool(args.skip_setup),
        dry_run_provider=bool(args.dry_run_provider),
    )


def command_tui(args: argparse.Namespace) -> int:
    """Open the experimental, unstable mouse-capable Textual SAGE shell."""
    try:
        from .tui import run_tui
    except ImportError as exc:
        raise ConfigurationError(
            str(exc),
            code="TUI_DEPENDENCY_MISSING",
            next_action="Repair SAGE runtime dependencies, then rerun `sage tui`; `sage menu` remains available as fallback.",
        ) from exc

    settings = _settings_path(args.settings)
    config = load_ecosystem(settings)
    return run_tui(
        sage_root=config.root,
        settings_path=settings,
        dry_run_provider=bool(args.dry_run_provider),
        live_ai=not bool(args.no_live_ai),
    )


def command_overview(args: argparse.Namespace) -> int:
    """Show a fast local overview, optionally adding one explicit live provider probe."""
    config, standard = _load(args)
    store = JobStore(config.root, config.settings_path)
    setup_state = store.setup_state() or {}
    workspace_state = read_state(ecosystem_state_path(config.runtime_state_root))
    model_service = ModelService(config.root)
    from .llm_settings import local_ai_policy_status

    local_ai = local_ai_policy_status(config.root)
    settings = model_service.settings()
    selected_provider = str(settings["selected_provider"])
    selected_item = dict(settings["providers"].get(selected_provider, {}))
    setup_llm = setup_state.get("llm", {}) if isinstance(setup_state.get("llm"), dict) else {}
    provider_ready: bool | None = None
    provider_diagnostic = "Not probed. Use 'sage status --live' or 'sage model status'."
    selected_model = selected_item.get("model")
    selected_reasoning = selected_item.get("reasoning_effort")
    if bool(getattr(args, "live", False)):
        provider_status, _ = model_service.probe(selected_provider, cache_catalog=False)
        provider_ready = provider_status.ready
        provider_diagnostic = provider_status.diagnostic
        selected_model = provider_status.selected_model or selected_model
        selected_reasoning = provider_status.selected_reasoning_effort or selected_reasoning
    elif setup_llm.get("selected_provider") == selected_provider and isinstance(setup_llm.get("ready"), bool):
        provider_ready = bool(setup_llm["ready"])
        provider_diagnostic = str(setup_llm.get("diagnostic") or "Last setup provider state.")

    last = store.last_run()
    job_progress = None
    if last:
        # Keep CLI status on the same local progress contract as menu/TUI without probing a provider.
        from .ui_services import OperatorUIService

        job_progress = OperatorUIService(
            root=config.root,
            settings_path=config.settings_path,
        ).run_progress_snapshot(last[0], last[1])
    provider_state = "READY" if provider_ready is True else "NOT READY" if provider_ready is False else "NOT PROBED"
    setup_status = str(setup_state.get("status", "NOT_RUN"))
    active_jobs = store.active_jobs()
    stale_active_jobs = store.stale_active_job_pointers()
    result = {
        "status": (
            "READY"
            if setup_status in {"COMPLETE", "READY_WITH_ACTIONS"}
            and provider_ready is not False
            and not stale_active_jobs
            else "ACTION_REQUIRED"
        ),
        "version": (config.root / "VERSION").read_text(encoding="utf-8").strip(),
        "release_status": standard.release_status,
        "public_release_ready": standard.public_release_ready,
        "setup": setup_status,
        "workspace": workspace_state.get("state", workspace_state.get("status", "NOT_INITIALISED")),
        "active_jobs": active_jobs,
        "stale_active_jobs": stale_active_jobs,
        "selected_provider": selected_provider,
        "provider_ready": provider_ready,
        "provider_state": provider_state,
        "provider_live_probe": bool(getattr(args, "live", False)),
        "selected_model": selected_model,
        "selected_reasoning_effort": selected_reasoning,
        "provider_diagnostic": provider_diagnostic,
        "local_ai": local_ai,
        "job_progress": job_progress,
        "last_run": (
            {
                "job_id": last[0].job_id,
                "run_id": last[1].run_id,
                "tool": last[1].tool,
                "scope": last[1].scope,
                "stage": last[1].current_stage,
                "run_status": last[1].status,
            }
            if last
            else None
        ),
    }
    if args.json:
        _print_json(result)
        return 0
    print(f"SAGE {result['version']}")
    readiness = "READY FOR PUBLIC USE" if standard.public_release_ready else "NOT READY FOR PUBLIC USE"
    print(f"Development status: {standard.release_status} - {readiness}")
    print(f"Setup: {result['setup']}")
    print(f"Workspace: {result['workspace']}")
    for tool in ("bic", "saw"):
        job_id = result["active_jobs"].get(tool)
        display = (
            f"STALE POINTER - {job_id} (Job manifest missing)"
            if tool in result["stale_active_jobs"]
            else job_id or "NONE"
        )
        print(f"{tool.upper()} job: {display}")
    model = result.get("selected_model") or "AUTO/provider default"
    effort = f" / {result['selected_reasoning_effort']}" if result.get("selected_reasoning_effort") else ""
    print(f"Model: {selected_provider} / {model}{effort} / {provider_state}")
    print(
        "Local AI: "
        f"{'ON' if local_ai['enabled'] else 'OFF'} / {local_ai['model']} / "
        f"{local_ai['authority']} / {local_ai['readiness']} / {local_ai['reporting_mode']}"
    )
    if local_ai["enablement_blocked"]:
        print(f"Local AI enablement: BLOCKED / {local_ai['reason_code']}")
    if result["last_run"]:
        item = result["last_run"]
        print(
            f"Last run: {item['tool'].upper()} {item['job_id']} / {item['scope']} "
            f"[{item['stage']}: {item['run_status']}]"
        )
    if job_progress:
        print(f"Run progress: {job_progress.get('line') or '—'}")
        print(f"Run activity: {job_progress.get('activity') or '—'}")
    if setup_status not in {"COMPLETE", "READY_WITH_ACTIONS"}:
        print(f"Next: {render_sage_command(['setup'])}")
    if bool(getattr(args, "live", False)) and provider_ready is False:
        print(f"Action: {provider_diagnostic}")
    elif not bool(getattr(args, "live", False)):
        print(f"Live provider check: {render_sage_command(['status', '--live'])}")
    return 0


def command_setup(args: argparse.Namespace) -> int:
    """Run first-use setup interactively, or fail fast when prompting is disabled."""
    if bool(getattr(args, "no_prompt", False)):
        raise InputRequiredError(
            "First-use setup requires operator input when prerequisites are incomplete",
            code="SETUP_INPUT_REQUIRED",
            suggestions=[
                {
                    "value": "sage setup",
                    "label": "Run interactive first-use setup",
                }
            ],
            next_action=(
                "Run `sage setup` in an interactive terminal, or use the canonical "
                "configuration commands for the prerequisite you need to change."
            ),
        )

    from .menu import run_setup

    settings = _settings_path(args.settings)
    config = load_ecosystem(settings)
    return run_setup(
        sage_root=config.root,
        settings_path=settings,
        script_path=Path(args.script).expanduser().resolve() if args.script else None,
    )


def _app_root_for_settings(settings_path: Path) -> Path:
    """Resolve the Core application root without requiring localdata to be available."""
    path = settings_path.expanduser().resolve()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Cannot read SAGE settings: {path}: {exc}") from exc
    paths = raw.get("paths", {}) if isinstance(raw, dict) else {}
    root_value = paths.get("sage_root") if isinstance(paths, dict) else None
    if root_value in (None, ""):
        return path.parent
    raw_root = Path(str(root_value)).expanduser()
    return raw_root.resolve() if raw_root.is_absolute() else (path.parent / raw_root).resolve()


def command_data_home_show(args: argparse.Namespace) -> int:
    """Show the effective localdata location for this Core checkout."""
    root = _app_root_for_settings(_settings_path(args.settings))
    layout = storage_layout(root, create=True)
    result = {"status": "READY", "sage_root": str(root), "data_home": str(layout.data_root)}
    if args.json:
        _print_json(result)
    else:
        print(f"SAGE root: {root}")
        print(f"localdata:  {layout.data_root}")
    return 0


def command_data_home_set(args: argparse.Namespace) -> int:
    """Persist a custom localdata location without moving or deleting existing data."""
    root = _app_root_for_settings(_settings_path(args.settings))
    target = Path(args.path).expanduser()
    layout = storage_layout(root, explicit=target, create=True)
    locator = persist_data_home(root, layout.data_root)
    result = {
        "status": "CONFIGURED",
        "sage_root": str(root),
        "data_home": str(layout.data_root),
        "locator": str(locator),
        "data_moved": False,
    }
    if args.json:
        _print_json(result)
    else:
        print(f"localdata location configured: {layout.data_root}")
        print("Existing data was not moved or copied.")
    return 0


def command_data_home_reset(args: argparse.Namespace) -> int:
    """Clear only the persisted custom pointer; no localdata content is deleted."""
    root = _app_root_for_settings(_settings_path(args.settings))
    locator = clear_persisted_data_home(root)
    default = root.parent / "localdata"
    result = {
        "status": "RESET",
        "sage_root": str(root),
        "default_data_home": str(default),
        "locator": str(locator),
        "data_deleted": False,
    }
    if args.json:
        _print_json(result)
    else:
        print(f"Custom localdata pointer cleared. Default: {default}")
        if os.environ.get("SAGE_DATA_HOME"):
            print("SAGE_DATA_HOME is set and still overrides the default for this process/environment.")
    return 0


def _settings_path(value: str) -> Path:
    """Expand and resolve the settings path before any configuration is loaded."""
    return Path(value).expanduser().resolve()


def _preconfigure_prompt_language(argv: Sequence[str]) -> None:
    """Best-effort configure guided parser prompts before argument validation."""
    settings_value = "ecosystem.yml"
    for index, token in enumerate(argv):
        if token == "--settings" and index + 1 < len(argv):
            settings_value = argv[index + 1]
            break
        if token.startswith("--settings="):
            settings_value = token.split("=", 1)[1]
            break
    try:
        config = load_ecosystem(_settings_path(settings_value))
    except Exception:
        # Argument remediation must remain available even when settings cannot yet load.
        return
    configure_prompt_renderer(
        lambda key: paired_catalogue_text(
            config.human_output.logs_and_reports,
            key,
            operator_language=config.human_output.operator_language,
        )
    )


def _load(args: argparse.Namespace) -> tuple[EcosystemConfig, SageStandard]:
    """Load the effective ecosystem and SAGE standard selected by the command arguments."""
    config = load_ecosystem(_settings_path(args.settings))
    configure_prompt_renderer(
        lambda key: paired_catalogue_text(
            config.human_output.logs_and_reports,
            key,
            operator_language=config.human_output.operator_language,
        )
    )
    return config, load_standard(config.root)


def _configure_utf8_standard_streams() -> None:
    """Force SAGE text I/O to UTF-8 instead of inheriting a platform locale such as Windows cp1252."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def _print_json(value: Any) -> None:
    """Print stable, UTF-8 JSON for non-interactive and audit consumers."""
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _interactive(args: argparse.Namespace) -> bool:
    """Return whether guided prompting is permitted for this invocation."""
    return bool(getattr(args, "_guided_interactive", False))


def _record_correction(args: argparse.Namespace, correction: dict[str, Any] | None) -> None:
    """Attach one confirmed correction to command provenance and canonical arguments."""
    if not correction:
        return
    corrections = getattr(args, "_input_corrections", None)
    if corrections is None:
        corrections = []
        setattr(args, "_input_corrections", corrections)
    corrections.append(correction)
    argv = getattr(args, "_canonical_argv", None)
    if not isinstance(argv, list):
        return
    field = str(correction.get("field", "")).strip().casefold().replace(" ", "_")
    original = str(correction.get("original", ""))
    resolved = str(correction.get("resolved", ""))
    option_map = {
        "settings": "--settings",
        "scope": "--scope",
        "operation": "--operation",
        "output_project": "--output-project",
        "contemporary_source": "--contemporary-source",
        "lexical_donor": "--lexical-donor",
        "project": "--project",
        "set_id": "--set",
        "task": "--task",
        "plan": "--plan",
        "predecessor_task": "--predecessor-task",
        "transaction_id": "--id",
        "selector": "--selector",
        "focus": "--focus",
        "grammar_override_id": "--grammar-override-id",
    }
    option = option_map.get(field)
    if option:
        for index, token in enumerate(argv):
            if token == option and index + 1 < len(argv):
                argv[index + 1] = resolved
                return
            if token.startswith(option + "="):
                argv[index] = option + "=" + resolved
                return
        if original == "<missing>":
            argv.extend([option, resolved])
        return
    if field in {"shortcut_command", "workflow_command"}:
        for index, token in enumerate(argv):
            if token == original:
                argv[index] = resolved
                return


def _book_aliases_by_code() -> dict[str, tuple[str, ...]]:
    """Invert the book-alias registry for ranked Operator correction prompts."""
    result: dict[str, list[str]] = {code: [] for code in BOOK_ORDER}
    for alias, code in BOOK_ALIASES.items():
        result.setdefault(code, []).append(alias)
    return {code: tuple(values) for code, values in result.items()}


def _resolve_settings_input(args: argparse.Namespace) -> None:
    """Resolve or prompt for a valid settings file without silently changing the request."""
    raw = str(args.settings)
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.is_file():
        args.settings = str(candidate.resolve())
        return
    candidates = sorted(
        {path.resolve() for pattern in ("*.yml", "*.yaml") for path in Path.cwd().glob(pattern) if path.is_file()},
        key=lambda item: item.name.casefold(),
    )
    suggestions = suggest_existing_paths(raw, candidates)
    if not _interactive(args):
        raise InputRequiredError(
            f"Settings file was not found: {raw}",
            code="SETTINGS_FILE_NOT_FOUND",
            received=raw,
            suggestions=suggestions_payload(suggestions),
            next_action="Choose an existing .yml settings file and retry.",
        )
    corrected = prompt_for_value(
        label="Settings file",
        received=raw,
        suggestions=suggestions,
    )
    corrected_path = Path(corrected).expanduser()
    if not corrected_path.is_absolute():
        corrected_path = Path.cwd() / corrected_path
    if not corrected_path.is_file():
        raise InputRequiredError(
            f"Settings file was not found: {corrected}",
            code="SETTINGS_FILE_NOT_FOUND",
            received=corrected,
            suggestions=suggestions_payload(suggestions),
            next_action="Enter an existing .yml settings file.",
        )
    args.settings = str(corrected_path.resolve())
    _record_correction(
        args,
        {
            "field": "settings",
            "original": raw,
            "resolved": args.settings,
            "resolution": "OPERATOR_CONFIRMED",
        },
    )


def _resolve_scope_input(args: argparse.Namespace, field: str = "scope") -> None:
    """Resolve a Scripture scope, offer ranked book corrections, and revalidate the result."""
    value = getattr(args, field, None)
    if not isinstance(value, str) or not value.strip():
        return
    original = value.strip()
    try:
        scope = parse_scope(original)
        setattr(args, field, scope.label())
        return
    except ValidationError as first_error:
        book_token, _ = split_scope_book(original)
        try:
            resolve_book(book_token)
            book_is_valid = True
        except ValidationError:
            book_is_valid = False
        if not book_is_valid:
            corrected_book, correction = resolve_from_choices(
                book_token,
                BOOK_ORDER.keys(),
                label="Scripture book",
                code="UNKNOWN_BOOK_CODE",
                labels=BOOK_LABELS,
                aliases=_book_aliases_by_code(),
                interactive=_interactive(args),
            )
            candidate = replace_scope_book(original, corrected_book)
            try:
                scope = parse_scope(candidate)
            except ValidationError as exc:
                if not _interactive(args):
                    raise InputRequiredError(
                        f"Invalid Scripture scope: {candidate!r}",
                        code="INVALID_SCOPE_INPUT",
                        received=original,
                        suggestions=[
                            {
                                "value": candidate,
                                "label": candidate,
                                "score": 1.0,
                                "confidence": "HIGH",
                            }
                        ],
                        next_action="Correct the chapter or verse range and retry.",
                    ) from exc
                candidate = prompt_for_value(
                    label="Scripture scope",
                    received=candidate,
                    suggestions=(),
                )
                scope = parse_scope(candidate)
            setattr(args, field, scope.label())
            _record_correction(
                args,
                {
                    "field": field,
                    "original": original,
                    "resolved": scope.label(),
                    "resolution": "OPERATOR_CONFIRMED",
                    **({"book_resolution": correction} if correction else {}),
                },
            )
            return
        if not _interactive(args):
            raise InputRequiredError(
                str(first_error),
                code="INVALID_SCOPE_INPUT",
                received=original,
                suggestions=[],
                next_action=(
                    "Use BOOK, BOOK CHAPTER, BOOK CHAPTER-CHAPTER, "
                    "BOOK CHAPTER:VERSE, or a bounded verse range."
                ),
            ) from first_error
        corrected = prompt_for_value(
            label="Scripture scope",
            received=original,
            suggestions=(),
        )
        try:
            scope = parse_scope(corrected)
        except ValidationError as exc:
            raise InputRequiredError(
                str(exc),
                code="INVALID_SCOPE_INPUT",
                received=corrected,
                suggestions=[],
                next_action="Enter a valid bounded Scripture scope.",
            ) from exc
        setattr(args, field, scope.label())
        _record_correction(
            args,
            {
                "field": field,
                "original": original,
                "resolved": scope.label(),
                "resolution": "OPERATOR_CONFIRMED",
            },
        )


def _resolve_project_input(
    args: argparse.Namespace,
    config: EcosystemConfig,
    field: str,
) -> None:
    """Resolve a SAGE Project ID with role-aware ranked alternatives."""
    value = getattr(args, field, None)
    if value in (None, ""):
        return
    labels = {
        project_id: (
            f"{project.language_code}; roles={','.join(project.scope.roles)}; "
            f"state={project.content_state}"
        )
        for project_id, project in config.projects.items()
    }
    corrected, correction = resolve_from_choices(
        str(value),
        config.projects.keys(),
        label=field.replace("_", " ").title(),
        code="UNKNOWN_PROJECT_ID",
        labels=labels,
        interactive=_interactive(args),
    )
    setattr(args, field, corrected)
    if correction:
        correction["field"] = field
    _record_correction(args, correction)


def _runtime_project_ids(args: argparse.Namespace, config: EcosystemConfig) -> tuple[str, ...]:
    """Return SAGE Projects directly required by one operator request."""
    values: list[str] = []
    for field in ("output_project", "contemporary_source", "project"):
        value = getattr(args, field, None)
        if isinstance(value, str) and value in config.projects:
            values.append(value)
    set_id = getattr(args, "set_id", None)
    if isinstance(set_id, str) and set_id in config.evaluation_sets:
        for entry in config.evaluation_sets[set_id].entries:
            values.extend((entry.output_project, entry.contemporary_source))
    return tuple(dict.fromkeys(values))


def _all_workflow_project_ids(config: EcosystemConfig) -> tuple[str, ...]:
    """Return every project bound by the configured workflow profiles."""
    result: list[str] = []
    for workflow in config.workflows.values():
        profile = load_workflow_profile(config, workflow)
        result.extend(profile.bindings.values())
    return tuple(dict.fromkeys(result))


def _init_input_requirements(
    config: EcosystemConfig,
    *,
    project_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Describe recoverable INIT settings for the requested operational scope."""
    selected = list(dict.fromkeys(project_ids or _all_workflow_project_ids(config)))
    disabled = [project_id for project_id in selected if not config.project(project_id).enabled]
    auto_rows = [
        row
        for row in resolve_auto_settings(config)
        if row.get("project_id") in selected and row.get("resolution_status") != "ACCEPTED"
    ]
    return {
        "configured": config.configured,
        "disabled_projects": disabled,
        "unresolved_auto_settings": [
            {
                "project_id": row.get("project_id"),
                "setting": row.get("setting"),
                "status": row.get("resolution_status"),
                "proposed": row.get("resolved_summary", row.get("resolved")),
            }
            for row in auto_rows
        ],
        "project_ids": selected,
    }


def _raise_init_input_required(requirements: dict[str, Any]) -> None:
    """Raise a structured INIT remediation request with safe next actions."""
    suggestions: list[dict[str, Any]] = [
        {
            "value": "sage project init",
            "label": "Run guided INIT to review and confirm recoverable settings",
            "score": 1.0,
            "confidence": "AUTHORITATIVE",
        }
    ]
    for project_id in requirements.get("disabled_projects", []):
        suggestions.append(
            {
                "value": project_id,
                "label": f"Review enablement for SAGE Project {project_id}",
                "score": 1.0,
                "confidence": "AUTHORITATIVE",
            }
        )
    raise InputRequiredError(
        "INIT requires Operator input before validation or initialization can continue",
        code="INIT_INPUT_REQUIRED",
        received={
            "configured": requirements.get("configured"),
            "disabled_projects": requirements.get("disabled_projects", []),
            "unresolved_auto_settings": requirements.get("unresolved_auto_settings", []),
        },
        suggestions=suggestions[:4],
        next_action=f"Run interactively or run `{render_sage_command(['project', 'init'])}` to review the proposed settings.",
    )


def _request_needs_runtime_configuration(args: argparse.Namespace) -> bool:
    """Return whether the selected command requires initialized runtime configuration."""
    command = getattr(args, "command", None)
    if command == "task":
        return True
    if command == "evaluation":
        return True
    if command == "generation":
        return getattr(args, "generation_command", None) in {"publish", "verify"}
    if command == "workflow":
        return getattr(args, "workflow_command", None) == "plan"
    return False


def _remediate_runtime_configuration(
    args: argparse.Namespace,
    config: EcosystemConfig,
) -> EcosystemConfig:
    """Prompt for recoverable effective configuration before execution."""
    if not _request_needs_runtime_configuration(args):
        return config
    selected = _runtime_project_ids(args, config)
    disabled = [project_id for project_id in selected if not config.project(project_id).enabled]
    if config.configured and not disabled:
        return config
    if not _interactive(args):
        suggestions: list[dict[str, Any]] = []
        if not config.configured:
            suggestions.append(
                {
                    "value": "sage project init",
                    "label": "Run guided INIT and mark the effective configuration configured",
                    "score": 1.0,
                    "confidence": "AUTHORITATIVE",
                }
            )
        suggestions.extend(
            {
                "value": project_id,
                "label": f"Enable SAGE Project {project_id} through guided INIT",
                "score": 1.0,
                "confidence": "AUTHORITATIVE",
            }
            for project_id in disabled
        )
        raise InputRequiredError(
            "The requested operation needs recoverable INIT settings before it can run",
            code="INIT_REMEDIATION_REQUIRED",
            received={"configured": config.configured, "disabled_projects": disabled},
            suggestions=suggestions,
            next_action=f"Run interactively or run `{render_sage_command(['project', 'init'])}` and confirm the required settings.",
        )
    remediation = run_targeted_init_remediation(
        config,
        project_ids=selected,
        input_stream=sys.stdin,
        output_stream=sys.stderr,
    )
    for item in remediation.get("operator_resolutions", []):
        if not isinstance(item, dict):
            continue
        _record_correction(
            args,
            {
                "field": str(item.get("setting", "init_setting")),
                "original": item.get("original_value"),
                "resolved": item.get("resolved_value"),
                "resolution": item.get("method", "OPERATOR_CONFIRMED"),
            },
        )
    return load_ecosystem(_settings_path(args.settings))


def _grammar_profile_for_project(config: EcosystemConfig, project_id: str):
    """Resolve the effective grammar profile for a project and task role."""
    project = config.project(project_id)
    if not project.profile_variant:
        return None
    namespace = config.language_profile(project.language_profile)
    variant = namespace.variants[project.profile_variant]
    return load_grammar_profile(
        variant.path,
        expected_profile_id=variant.variant_id,
        expected_language=namespace.profile_language,
        expected_role=variant.role,
    )


def _initialization_is_stale(config: EcosystemConfig, state: dict[str, Any]) -> bool:
    """Return whether effective settings have changed since the last initialization receipt."""
    if state.get("settings_sha256") != sha256_file(config.settings_path):
        return True
    current_override_hash = (
        sha256_file(config.operator_overrides_path)
        if config.operator_overrides_path and config.operator_overrides_path.is_file()
        else None
    )
    return state.get("operator_overrides_sha256") != current_override_hash


def _ensure_workspace_initialized_input(
    args: argparse.Namespace,
    config: EcosystemConfig,
) -> EcosystemConfig:
    """Offer an immediate safe initialization retry for analytical task creation."""
    if getattr(args, "command", None) != "task" or getattr(args, "task_command", None) != "create":
        return config
    state = read_state(ecosystem_state_path(config.runtime_state_root))
    missing = not state
    stale = bool(state) and _initialization_is_stale(config, state)
    if not missing and not stale:
        return config
    reason = "not been run" if missing else "become stale after effective settings changed"
    if not _interactive(args):
        raise InputRequiredError(
            f"Workspace initialization has {reason}",
            code="WORKSPACE_INITIALIZATION_INPUT_REQUIRED",
            received={"state": "NOT_RUN" if missing else state.get("state"), "stale": stale},
            suggestions=[
                {
                    "value": "sage workspace initialize",
                    "label": "Run guided workspace initialization, then retry this task",
                    "score": 1.0,
                    "confidence": "AUTHORITATIVE",
                }
            ],
            next_action=f"Run `{render_sage_command(['workspace', 'initialize'])}` or repeat this command interactively.",
        )
    choice = prompt_for_value(
        label="Initialization action",
        received="NOT_RUN" if missing else "STALE",
        suggestions=[
            Suggestion(
                value="initialize",
                label="Run guided workspace initialization now",
                score=1.0,
                confidence="AUTHORITATIVE",
            ),
            Suggestion(
                value="cancel",
                label="Cancel without creating the task",
                score=1.0,
                confidence="AUTHORITATIVE",
            ),
        ],
    )
    if choice != "initialize":
        raise InputRequiredError(
            "Workspace initialization remains required",
            code="WORKSPACE_INITIALIZATION_INPUT_REQUIRED",
            received=choice,
            suggestions=[],
            next_action=f"Run `{render_sage_command(['workspace', 'initialize'])}` before task creation.",
        )
    init_args = argparse.Namespace(
        settings=args.settings,
        json=False,
        break_stale_lock=False,
        _guided_interactive=True,
        target_project_ids=_runtime_project_ids(args, config),
    )
    result_code = command_initialize(init_args)
    _record_correction(
        args,
        {
            "field": "workspace_initialization",
            "original": "NOT_RUN" if missing else "STALE",
            "resolved": "RERUN",
            "resolution": "OPERATOR_CONFIRMED",
        },
    )
    if result_code != 0:
        raise ValidationError(
            "Guided initialization completed with in-scope blocking errors",
            code="WORKSPACE_INITIALIZATION_BLOCKED",
            next_action="Resolve the initialization report errors and retry task creation.",
        )
    return load_ecosystem(_settings_path(args.settings))


def _resolve_grammar_override_input(args: argparse.Namespace, config: EcosystemConfig) -> None:
    """Retain an optional grammar decision ID without gating task creation."""
    return


def _resolve_evaluation_set_input(args: argparse.Namespace, config: EcosystemConfig) -> None:
    """Resolve one registered evaluation set or request a corrected selection."""
    value = getattr(args, "set_id", None)
    if value in (None, ""):
        return
    corrected, correction = resolve_from_choices(
        str(value),
        config.evaluation_sets.keys(),
        label="Evaluation set",
        code="UNKNOWN_EVALUATION_SET",
        interactive=_interactive(args),
    )
    args.set_id = corrected
    if correction:
        correction["field"] = "set_id"
    _record_correction(args, correction)


def _resolve_operation_input(args: argparse.Namespace) -> None:
    """Resolve an operation against the selected workflow command contract."""
    workflow = getattr(args, "workflow_id", None)
    operation = getattr(args, "operation", None)
    if not workflow or not operation or workflow not in ALLOWED_OPERATIONS:
        return
    corrected, correction = resolve_from_choices(
        str(operation),
        sorted(ALLOWED_OPERATIONS[workflow]),
        label=f"{workflow.upper()} operation",
        code="OPERATION_NOT_SUPPORTED_BY_WORKFLOW",
        interactive=_interactive(args),
    )
    args.operation = corrected
    if correction:
        correction["field"] = "operation"
    _record_correction(args, correction)


def _resolve_required_focus(args: argparse.Namespace) -> None:
    """Require one bounded focus question for FOCUSED or OL analysis."""
    operation = getattr(args, "operation", None)
    command = getattr(args, "command", None)
    subcommand = getattr(args, "task_command", None) or getattr(args, "evaluation_command", None)
    if operation not in {"focused", "ol"} or (command, subcommand) not in {
        ("task", "create"),
        ("evaluation", "plan"),
    }:
        return
    focus = getattr(args, "focus", None)
    if isinstance(focus, str) and focus.strip():
        args.focus = focus.strip()
        return
    if not _interactive(args):
        raise InputRequiredError(
            f"SAW {operation} requires one bounded focus question",
            code="FOCUS_REQUIRED",
            received=focus,
            suggestions=[],
            next_action="Supply --focus with one bounded question and retry.",
        )
    args.focus = prompt_for_value(label="Bounded focus question")
    _record_correction(
        args,
        {
            "field": "focus",
            "original": "<missing>",
            "resolved": args.focus,
            "resolution": "OPERATOR_SUPPLIED",
        },
    )


def _resolve_path_input(
    args: argparse.Namespace,
    config: EcosystemConfig,
    field: str,
    patterns: tuple[str, ...],
) -> None:
    """Resolve a governed input path and keep it inside the authorized root."""
    value = getattr(args, field, None)
    if value in (None, ""):
        return
    raw = str(value)
    if raw.startswith("@"):
        path = resolve_declared_path(config.root, raw, field.replace("_", " "))
    else:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = config.root / path
    if path.exists():
        # Keep governed declarations intact for command handlers that enforce the
        # portable Core/localdata boundary themselves.
        setattr(args, field, raw if raw.startswith("@") else str(path.resolve()))
        return
    candidates: set[Path] = set()
    for pattern in patterns:
        candidates.update(item.resolve() for item in config.runtime_state_root.glob(pattern) if item.is_file())
    suggestions = suggest_existing_paths(raw, sorted(candidates))
    if not _interactive(args):
        raise InputRequiredError(
            f"{field.replace('_', ' ').title()} was not found: {raw}",
            code="INPUT_PATH_NOT_FOUND",
            received=raw,
            suggestions=suggestions_payload(suggestions),
            next_action="Choose an existing governed file and retry.",
            details={"field": field},
        )
    corrected = prompt_for_value(
        label=field.replace("_", " ").title(),
        received=raw,
        suggestions=suggestions,
    )
    if corrected.startswith("@"):
        corrected_path = resolve_declared_path(
            config.root,
            corrected,
            field.replace("_", " "),
        )
    else:
        corrected_path = Path(corrected).expanduser()
        if not corrected_path.is_absolute():
            corrected_path = config.root / corrected_path
    if not corrected_path.is_file():
        raise InputRequiredError(
            f"Governed file was not found: {corrected}",
            code="INPUT_PATH_NOT_FOUND",
            received=corrected,
            suggestions=suggestions_payload(suggestions),
            next_action="Select one existing governed file.",
        )
    resolved_value = corrected if corrected.startswith("@") else str(corrected_path.resolve())
    setattr(args, field, resolved_value)
    _record_correction(
        args,
        {
            "field": field,
            "original": raw,
            "resolved": resolved_value,
            "resolution": "OPERATOR_CONFIRMED",
        },
    )


def _resolve_transaction_input(args: argparse.Namespace, config: EcosystemConfig) -> None:
    """Resolve an incomplete transaction ID for controlled recovery."""
    value = getattr(args, "transaction_id", None)
    workflow = getattr(args, "workflow_id", None)
    if not value or not workflow:
        return
    candidates = [path.name for path in incomplete_transactions(config.workflow(workflow).transaction_root)]
    corrected, correction = resolve_from_choices(
        str(value),
        candidates,
        label="Transaction ID",
        code="UNKNOWN_TRANSACTION_ID",
        interactive=_interactive(args),
    )
    args.transaction_id = corrected
    if correction:
        correction["field"] = "transaction_id"
    _record_correction(args, correction)


def _resolve_shortcut_input(args: argparse.Namespace) -> None:
    """Resolve a BIC or SAW shortcut action before canonical command expansion."""
    workflow = getattr(args, "workflow_id", None)
    command = getattr(args, "shortcut_command", None)
    if not workflow or command is None:
        return
    aliases = {
        "self_check": ("self-check", "selfcheck"),
        "focused": ("focus",),
    }
    alias_to_canonical = {
        alias.casefold(): canonical
        for canonical, values in aliases.items()
        for alias in values
    }
    exact_alias = alias_to_canonical.get(str(command).casefold())
    if exact_alias is not None:
        # Public launchers use hyphenated verbs; canonicalise them silently.
        args.shortcut_command = exact_alias
        return
    corrected, correction = resolve_from_choices(
        str(command),
        SHORTCUT_COMMANDS[workflow].keys(),
        label=f"{workflow.upper()} command",
        code="UNKNOWN_WORKFLOW_COMMAND",
        aliases=aliases,
        interactive=_interactive(args),
    )
    args.shortcut_command = corrected
    if correction:
        correction["field"] = "shortcut_command"
    _record_correction(args, correction)


def _resolve_generation_selector_input(args: argparse.Namespace, config: EcosystemConfig) -> None:
    """Resolve an immutable BIC generation selector for verification."""
    selector = getattr(args, "selector", None)
    project_id = getattr(args, "project", None)
    if not selector or not project_id or selector == "current":
        return
    publication_root = config.workflow("bic").publication_root
    if publication_root is None:
        return
    project_root = publication_root / project_id
    candidates = ["current"]
    if project_root.is_dir():
        candidates.extend(
            path.name for path in sorted(project_root.iterdir()) if path.is_dir() and not path.name.startswith(".")
        )
    corrected, correction = resolve_from_choices(
        str(selector),
        candidates,
        label="Generation selector",
        code="UNKNOWN_GENERATION_SELECTOR",
        interactive=_interactive(args),
    )
    args.selector = corrected
    if correction:
        correction["field"] = "selector"
    _record_correction(args, correction)


def _prepare_runtime_inputs(args: argparse.Namespace) -> None:
    """Resolve remediable operator input before controller execution."""
    if getattr(args, "command", None) in {"guide", "help", "menu", "tui"}:
        return
    _resolve_settings_input(args)
    for field in ("scope",):
        _resolve_scope_input(args, field)
    _resolve_operation_input(args)
    _resolve_shortcut_input(args)
    _resolve_required_focus(args)
    # Package validation and Doctor still need a valid settings file but no dynamic IDs.
    if (
        getattr(args, "command", None) == "project"
        and getattr(args, "project_command", None) == "init"
        and getattr(args, "clear_overrides", False)
    ):
        return
    try:
        config = load_ecosystem(_settings_path(args.settings))
    except ConfigurationError as exc:
        if exc.code != "OPERATOR_OVERRIDE_STALE" or not _interactive(args):
            raise
        answer = prompt_for_value(
            label="Stale override action",
            received="operator-overrides.yml",
            suggestions=[
                Suggestion(
                    value="clear",
                    label="Clear stale overrides and continue from source settings",
                    score=1.0,
                    confidence="AUTHORITATIVE",
                ),
                Suggestion(
                    value="cancel",
                    label="Cancel without changing overrides",
                    score=1.0,
                    confidence="AUTHORITATIVE",
                ),
            ],
        )
        if answer != "clear":
            raise
        cleared = clear_operator_overrides(_settings_path(args.settings))
        _record_correction(
            args,
            {
                "field": "operator_overrides",
                "original": str(cleared or "stale override"),
                "resolved": "cleared",
                "resolution": "OPERATOR_CONFIRMED",
            },
        )
        config = load_ecosystem(_settings_path(args.settings))
    for field in ("output_project", "contemporary_source", "project"):
        _resolve_project_input(args, config, field)
    _resolve_evaluation_set_input(args, config)
    config = _remediate_runtime_configuration(args, config)
    config = _ensure_workspace_initialized_input(args, config)
    _resolve_grammar_override_input(args, config)
    _resolve_path_input(args, config, "task", ("**/task-manifest.json",))
    _resolve_path_input(args, config, "predecessor_task", ("**/task-manifest.json",))
    _resolve_path_input(args, config, "plan", ("**/*plan*.json", "**/*.queue.json"))
    _resolve_transaction_input(args, config)
    _resolve_generation_selector_input(args, config)


def _print_corrections(args: argparse.Namespace) -> None:
    """Render confirmed input corrections before execution continues."""
    corrections = getattr(args, "_input_corrections", [])
    if not corrections or getattr(args, "json", False):
        return
    print("SAGE INPUT REMEDIATION", file=sys.stderr)
    for item in corrections:
        print(
            f"- {item.get('field')}: {item.get('original')} -> {item.get('resolved')}",
            file=sys.stderr,
        )
    canonical = getattr(args, "_canonical_argv", [])
    if canonical:
        print(f"Canonical command: {render_sage_command(canonical)}", file=sys.stderr)


def _safe_id(value: str, *, fallback: str = "scope") -> str:
    """Convert an Operator label into a filesystem-safe deterministic identifier."""
    result = SAFE_ID_RE.sub("-", value).strip("-.")
    return (result or fallback)[:100]


def _workflow_output_path(value: str | None, output_root: Path, default_name: str) -> Path:
    """Resolve a generated artifact inside its owning workflow output root."""
    governed_root = output_root.expanduser().resolve()
    candidate = (
        Path(value).expanduser()
        if value
        else Path("plans") / default_name
    )
    if not candidate.is_absolute():
        candidate = governed_root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(governed_root)
    except ValueError as exc:
        raise ValidationError(
            f"Generated workflow output must remain inside {governed_root}: {candidate}"
        ) from exc
    return candidate


def _grammar_contracts(
    config: EcosystemConfig,
    profile: WorkflowProfile,
) -> dict[str, dict[str, Any]]:
    """Compile project-selected language profile variants into task contracts."""
    contracts: dict[str, dict[str, Any]] = {}
    for role, profile_ref in sorted(profile.language_profile_bindings.items()):
        project = config.project(profile.bindings[role])
        if not project.profile_variant:
            continue
        namespace = config.language_profile(project.language_profile)
        spec = namespace.variants[project.profile_variant]
        grammar = load_grammar_profile(
            spec.path,
            expected_profile_id=spec.variant_id,
            expected_language=namespace.profile_language,
            expected_role=spec.role,
        )
        contract = compile_grammar_contract(grammar, config.cache_root)
        contracts[role] = {
            **contract,
            "language_profile": project.language_profile,
            "profile_variant": project.profile_variant,
            "profile_ref": profile_ref,
        }
    return contracts


def _report_text(config: EcosystemConfig, key: str) -> str:
    """Render one approved logs-and-reports label in configured language order."""
    return paired_catalogue_text(
        config.human_output.logs_and_reports,
        key,
        operator_language=config.human_output.operator_language,
    )




def _report_languages(config: EcosystemConfig) -> tuple[str, ...]:
    """Return effective logs-and-reports languages in display order."""
    return resolved_languages(
        config.human_output.logs_and_reports,
        operator_language=config.human_output.operator_language,
    )


def _report_language_authority_notice(config: EcosystemConfig) -> str:
    """Return the mandatory authority notice for bilingual operational reports."""
    return render_report_language_authority(
        report_language_authority(
            config.human_output.logs_and_reports,
            operator_language=config.human_output.operator_language,
        ),
        markdown=True,
    )

def _render_initialization_report(config: EcosystemConfig, result: dict[str, Any]) -> str:
    """Render the ecosystem initialization result in configured report languages."""
    yes = _report_text(config, "label.yes")
    no = _report_text(config, "label.no")
    none = _report_text(config, "label.none")
    lines = [
        f"# {_report_text(config, 'report.ecosystem_initialisation')}",
        "",
        f"- {_report_text(config, 'label.report_languages')}: `" + "/".join(_report_languages(config)) + "`",
        f"- {_report_text(config, 'label.status')}: `{result['state']}`",
        f"- Capability: `{result['capability']}`",
        f"- {_report_text(config, 'label.version')}: `{result['version']}`",
        f"- {_report_text(config, 'label.projects_root')}: `{result['projects_root']}`",
        f"- {_report_text(config, 'label.effective_overrides')}: `{result.get('operator_overrides_path') or none}`",
        "",
        f"## {_report_text(config, 'label.workflows')}",
        "",
        "| " + " | ".join([_report_text(config, "label.workflow"), _report_text(config, "label.qualification"), _report_text(config, "label.resources"), _report_text(config, "label.execution"), _report_text(config, "label.language_contracts"), _report_text(config, "label.pending_transactions")]) + " |",
        "|---|---|---|---|---:|---:|",
    ]
    for workflow_id, item in sorted(result.get("workflows", {}).items()):
        lines.append(
            f"| {workflow_id.upper()} | `{item['qualification_status']}` | "
            f"`{item.get('resource_state', 'NOT_RUN')}` | "
            f"{yes if item.get('execution_available') else no} | "
            f"{len(item.get('language_contracts', {}))} | "
            f"{item.get('pending_transactions', 0)} |"
        )
    lines.extend([
        "",
        f"## {_report_text(config, 'label.projects')}",
        "",
        "| " + " | ".join([_report_text(config, "label.project"), _report_text(config, "label.status"), _report_text(config, "label.files"), _report_text(config, "label.books"), _report_text(config, "label.verse_units"), _report_text(config, "label.sections"), _report_text(config, "label.paragraphs"), "VRS"]) + " |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for project_id, item in sorted(result.get("projects", {}).items()):
        summary = item.get("summary", {})
        vrs = item.get("effective_vrs", {})
        lines.append(
            f"| {project_id} | `{item.get('status', 'UNKNOWN')}` | "
            f"{summary.get('files', 0)} | {len(summary.get('books', []))} | "
            f"{summary.get('verse_units', 0)} | {summary.get('sections', 0)} | "
            f"{summary.get('paragraphs', 0)} | `{vrs.get('schema_id', '—')}` |"
        )
    lines.extend([
        "",
        f"## {_report_text(config, 'label.auto_resolved_settings')}",
        "",
        "| " + " | ".join([_report_text(config, "label.project"), _report_text(config, "label.setting"), _report_text(config, "label.resolved"), _report_text(config, "label.confidence"), _report_text(config, "label.status")]) + " |",
        "|---|---|---|---|---|",
    ])
    auto_rows = result.get("auto_resolutions", [])
    if auto_rows:
        for row in auto_rows:
            resolved = str(row.get("resolved_summary", row.get("resolved"))).replace("|", "\\|")
            lines.append(
                f"| {row['project_id']} | `{row['setting']}` | {resolved} | "
                f"`{row['confidence']}` | `{row['resolution_status']}` |"
            )
    else:
        lines.append(f"| — | — | {_report_text(config, 'label.no_auto_settings')} | — | — |")
    lines.extend([
        "",
        f"## {_report_text(config, 'label.operator_resolution_history')}",
        "",
        "| " + " | ".join([_report_text(config, "label.setting"), _report_text(config, "label.original"), _report_text(config, "label.effective_value"), _report_text(config, "label.method")]) + " |",
        "|---|---|---|---|",
    ])
    resolution_rows = result.get("operator_resolutions", [])
    if resolution_rows:
        for row in resolution_rows:
            setting = str(row.get("setting", "—")).replace("|", "\\|")
            original = str(row.get("original_value", "—")).replace("|", "\\|")
            resolved = str(row.get("resolved_value", "—")).replace("|", "\\|")
            method = str(row.get("method", "—")).replace("|", "\\|")
            lines.append(f"| `{setting}` | {original} | {resolved} | `{method}` |")
    else:
        lines.append(f"| — | — | {_report_text(config, 'label.no_operator_corrections')} | — |")
    lines.extend(["", f"## {_report_text(config, 'label.restrictions_errors')}", ""])
    messages = list(result.get("restrictions", [])) + list(result.get("errors", []))
    if messages:
        lines.extend(f"- {message}" for message in messages)
        lines.append(f"- {_report_text(config, 'label.canonical_fallback')}")
    else:
        lines.append(none + ".")
    lines.extend([
        "",
        f"## {_report_text(config, 'label.next_action')}",
        "",
        result.get("next_action", "No action recorded."),
        "",
    ])
    authority_notice = _report_language_authority_notice(config)
    if authority_notice:
        lines.extend([authority_notice, ""])
    return "\n".join(lines)

def _render_project_init_report(config: EcosystemConfig, result: dict[str, Any]) -> str:
    """Render Project INIT results in the effective global/Job report languages."""
    yes = _report_text(config, "label.yes")
    no = _report_text(config, "label.no")
    none = _report_text(config, "label.none")
    lines = [
        f"# {_report_text(config, 'report.project_init')}",
        "",
        f"- {_report_text(config, 'label.report_languages')}: `" + "/".join(_report_languages(config)) + "`",
        f"- {_report_text(config, 'label.status')}: `{result['status']}`",
        f"- {_report_text(config, 'label.settings')}: `{result['settings']}`",
        f"- {_report_text(config, 'label.interactive_review')}: `{yes if result['interactive'] else no}`",
        "",
        _report_text(config, "report.init_preserves_source"),
        "",
        "| " + " | ".join([
            _report_text(config, "label.project"),
            _report_text(config, "label.language_profile"),
            _report_text(config, "label.state"),
            _report_text(config, "label.scope"),
            _report_text(config, "label.roles"),
            _report_text(config, "label.observed_books"),
            _report_text(config, "label.review"),
        ]) + " |",
        "|---|---|---|---|---|---:|---|",
    ]
    for item in result["projects"]:
        roles = ", ".join(item["roles"])
        scope = f"{item['testament']}/{item['canon']}"
        profile = item["profile"]
        lines.append(
            f"| {item['project_id']} | `{item['language']}` / `{profile}` | "
            f"`{item['content_state']}` | `{scope}` | {roles} | "
            f"{item['observed_book_count']} | `{item['review']}` |"
        )
    lines.extend([
        "",
        f"## {_report_text(config, 'label.operator_confirmed_fields')}",
        "",
        _report_text(config, "report.confirm_project_fields"),
        "",
        f"## {_report_text(config, 'label.effective_configuration')}",
        "",
        f"- {_report_text(config, 'label.source_settings_sha256')}: `{result.get('source_settings_sha256', '—')}`",
        f"- {_report_text(config, 'label.effective_overrides')}: `{result.get('operator_overrides_path') or none}`",
        f"- {_report_text(config, 'label.confirmed_resolutions')}: `{len(result.get('operator_resolutions', []))}`",
        "",
        "| " + " | ".join([_report_text(config, "label.setting"), _report_text(config, "label.original"), _report_text(config, "label.effective_value"), _report_text(config, "label.method")]) + " |",
        "|---|---|---|---|",
    ])
    resolution_rows = result.get("operator_resolutions", [])
    if resolution_rows:
        for row in resolution_rows:
            setting = str(row.get("setting", "—")).replace("|", "\\|")
            original = str(row.get("original_value", "—")).replace("|", "\\|")
            resolved = str(row.get("resolved_value", "—")).replace("|", "\\|")
            method = str(row.get("method", "—")).replace("|", "\\|")
            lines.append(f"| `{setting}` | {original} | {resolved} | `{method}` |")
    else:
        lines.append(f"| — | — | {_report_text(config, 'label.no_operator_corrections')} | — |")
    lines.extend(["", f"## {_report_text(config, 'label.unregistered_project_folders')}", ""])
    if result["unregistered_projects"]:
        for item in result["unregistered_projects"]:
            lines.append(
                f"- `{item['folder']}`: {item['observed_book_count']} observed book(s). "
                "Add an explicit project entry before use. "
                + _report_text(config, "label.canonical_fallback")
            )
    else:
        lines.append(_report_text(config, "label.no_unregistered_projects") + ".")
    lines.extend(["", f"## {_report_text(config, 'label.auto_resolution_review')}", ""])
    if result["auto_resolutions"]:
        for row in result["auto_resolutions"]:
            lines.append(
                f"- `{row['setting']}` → {row['resolved_summary']} "
                f"(`{row['confidence']}`, `{row['resolution_status']}`)"
            )
        lines.append(_report_text(config, "label.canonical_fallback"))
    else:
        lines.append(_report_text(config, "label.no_auto_settings") + ".")
    lines.extend(["", _report_text(config, "report.guided_init_next"), ""])
    authority_notice = _report_language_authority_notice(config)
    if authority_notice:
        lines.extend([authority_notice, ""])
    return "\n".join(lines)

def command_init(args: argparse.Namespace) -> int:
    """Compile project facts and guide recoverable Operator configuration choices."""
    # Report recoverable settings before writing any governed effective override.
    settings_path = _settings_path(args.settings)
    cleared_override = None
    if getattr(args, "clear_overrides", False):
        cleared_override = clear_operator_overrides(settings_path)
    config, _ = _load(args)
    interactive = _interactive(args) and not args.non_interactive
    remediation: dict[str, Any] = {
        "changed": False,
        "operator_overrides_path": (
            str(config.operator_overrides_path) if config.operator_overrides_path else None
        ),
        "operator_resolutions": list(config.operator_resolutions),
        "project_decisions": {},
    }
    if interactive:
        remediation = run_guided_init_remediation(
            config,
            full_project_review=True,
            required_only=False,
            input_stream=sys.stdin,
            output_stream=sys.stderr,
        )
        if remediation.get("changed"):
            config, _ = _load(args)

    auto_resolutions = resolve_auto_settings(config)
    auto_by_project: dict[str, list[dict[str, Any]]] = {}
    for row in auto_resolutions:
        auto_by_project.setdefault(str(row["project_id"]), []).append(row)
    projects: list[dict[str, Any]] = []
    review_required = not config.configured
    registered_paths = {project.path.resolve() for project in config.projects.values()}
    project_decisions = remediation.get("project_decisions", {})
    for project_id, project in sorted(config.projects.items()):
        observed = sorted(discover_book_ids(project.path)) if project.path.is_dir() else []
        review = str(project_decisions.get(project_id, "NOT_ANSWERED"))
        if interactive and review == "NOT_ANSWERED":
            review_required = True
        projects.append(
            {
                "project_id": project_id,
                "enabled": project.enabled,
                "language": project.language_code,
                "profile": project.profile_ref,
                "content_state": project.content_state,
                "testament": project.scope.testament,
                "canon": project.scope.canon,
                "expected_books": (
                    project.scope.expected_books
                    if isinstance(project.scope.expected_books, str)
                    else list(project.scope.expected_books)
                ),
                "roles": list(project.scope.roles),
                "base_file": project.versification.base_file,
                "custom_file": project.versification.custom_file,
                "observed_books": observed,
                "observed_book_count": len(observed),
                "operator_confirmed_fields": [
                    "enabled",
                    "content_state",
                    "scope.roles",
                    "scope.testament",
                    "scope.canon",
                    "scope.expected_books",
                    "versification.base_file",
                    "versification.custom_file",
                    "language.profile",
                    "language.variant",
                ],
                "resolution": {
                    "language": {"source": "DECLARED_OR_OPERATOR_OVERRIDE", "confidence": "AUTHORITATIVE"},
                    "profile": {"source": "DECLARED_OR_OPERATOR_OVERRIDE", "confidence": "AUTHORITATIVE"},
                    "content_state": {"source": "OPERATOR_DECLARATION", "confidence": "CONFIRMATION_REQUIRED"},
                    "roles": {"source": "OPERATOR_DECLARATION", "confidence": "CONFIRMATION_REQUIRED"},
                    "scope": {"source": "DECLARED_CONFIGURATION_PLUS_OBSERVED_COVERAGE", "confidence": "REVIEW_RECOMMENDED"},
                    "observed_books": {"source": "USFM_FILE_DISCOVERY", "confidence": "AUTHORITATIVE"},
                },
                "auto_resolutions": auto_by_project.get(project_id, []),
                "review": review,
            }
        )
    unregistered: list[dict[str, Any]] = []
    if config.projects_root.is_dir():
        for folder in sorted(path for path in config.projects_root.iterdir() if path.is_dir() and not path.name.startswith(".")):
            if folder.resolve() in registered_paths:
                continue
            observed = sorted(discover_book_ids(folder))
            if not observed:
                continue
            unregistered.append(
                {
                    "folder": folder.name,
                    "path": str(folder),
                    "observed_books": observed,
                    "observed_book_count": len(observed),
                    "status": "REGISTER_REQUIRED",
                }
            )
    if unregistered:
        review_required = True
    if review_required:
        status = "READY_WITH_ACTIONS"
    elif remediation.get("changed"):
        status = "READY_FOR_INITIALIZE"
    else:
        status = "READY_FOR_EDIT_OR_INITIALIZE"
    result = {
        "schema_version": "3.0",
        "status": status,
        "settings": str(config.settings_path),
        "source_settings_sha256": sha256_file(config.settings_path),
        "interactive": interactive,
        "configured": config.configured,
        "projects": projects,
        "unregistered_projects": unregistered,
        "auto_resolutions": auto_resolutions,
        "operator_overrides_path": (
            str(config.operator_overrides_path)
            if config.operator_overrides_path
            else remediation.get("operator_overrides_path")
        ),
        "operator_resolutions": list(config.operator_resolutions),
        "override_cleared": str(cleared_override) if cleared_override else None,
        "attention": {
            "level": 2 if review_required else 0,
            "classification": "REVIEW_RECOMMENDED" if review_required else "NONE",
            "next_stage_allowed": True,
            "prompt_required": False,
        },
        "rules": [
            "INIT never rewrites the selected source settings file.",
            "Confirmed corrections are stored in a governed effective-configuration sidecar.",
            "Every corrected or inferred setting is revalidated before initialization continues.",
            "Recoverable settings are prompted or reported as actions; review attention does not block execution.",
            "Observed books do not silently change declared scope.",
        ],
    }
    output_root = config.reports_root / "setup"
    result["report"] = str(output_root / "PROJECT-INIT-REPORT.md")
    result["review_data"] = str(output_root / "operator-review.json")
    atomic_write_json(output_root / "operator-review.json", result)
    atomic_write_text(output_root / "PROJECT-INIT-REPORT.md", _render_project_init_report(config, result))
    if args.json:
        _print_json(result)
    else:
        print("SAGE PROJECT INIT")
        print(f"Status: {result['status']}")
        print(f"Effective configured: {'YES' if result['configured'] else 'NO'}")
        for item in projects:
            print(
                f"{item['project_id']}: enabled={str(item['enabled']).lower()} "
                f"language={item['language']} profile={item['profile']} "
                f"state={item['content_state']} scope={item['testament']}/{item['canon']} "
                f"roles={','.join(item['roles'])} books={item['observed_book_count']} "
                f"review={item['review']}"
            )
        if unregistered:
            print(f"Project folders not yet in SAGE: {len(unregistered)}")
        if result.get("operator_overrides_path"):
            print(f"Effective overrides: {result['operator_overrides_path']}")
        print(f"Report: {output_root / 'PROJECT-INIT-REPORT.md'}")
    return 0


def _model_service(config: EcosystemConfig) -> ModelService:
    """Return the shared provider/model service for one loaded SAGE workspace."""
    return ModelService(config.root)


def command_model_status(args: argparse.Namespace) -> int:
    """Show readiness and live model capability state for configured SAGE providers."""
    config, _ = _load(args)
    result = _model_service(config).status(getattr(args, "provider", None))
    if args.json:
        _print_json(result)
        return 0
    print("SAGE MODELS")
    print(f"Selected provider: {result['selected_provider']}")
    for row in result["providers"]:
        selected = " *" if row["provider"] == result["selected_provider"] else ""
        print(f"{row['provider']}{selected}: {'READY' if row['ready'] else 'NOT READY'}")
        if row.get("selected_model"):
            print(f"  Model: {row['selected_model']}")
        if row.get("selected_reasoning_effort"):
            print(f"  Reasoning: {row['selected_reasoning_effort']}")
        if row.get("account_plan_type"):
            print(f"  ChatGPT plan/workspace: {row['account_plan_type']}")
        if row.get("model_capabilities"):
            print(f"  Live models: {len(row['model_capabilities'])}")
        if row.get("endpoint"):
            print(f"  Endpoint: {row['endpoint']}")
        print(f"  Auth: {row.get('auth_mode', 'NONE')}")
        print(f"  {row.get('diagnostic', '')}")
    return 0


def command_model_connect(args: argparse.Namespace) -> int:
    """Connect OpenAI through interactive ChatGPT-managed Codex CLI sign-in."""
    if getattr(args, "json", False):
        raise ValidationError(
            "Interactive ChatGPT sign-in cannot run with --json.",
            code="INTERACTIVE_LOGIN_REQUIRED",
            next_action="Run `sage model connect` in an interactive terminal.",
        )
    config, _ = _load(args)
    result = _model_service(config).connect_chatgpt(device_auth=bool(getattr(args, "device_auth", False)))
    print("OpenAI and ChatGPT: CONNECTED")
    print("Transport: local Codex CLI (Codex desktop app not required)")
    print(f"Auth: {result['auth_mode']}")
    if result.get("account_plan_type"):
        print(f"ChatGPT plan/workspace: {result['account_plan_type']}")
    print(f"Live models: {result['model_count']}")
    print("Model routing: SAGE automatic task policy")
    return 0


def command_model_refresh(args: argparse.Namespace) -> int:
    """Refresh the live model catalog exposed to the current provider account."""
    config, _ = _load(args)
    result = _model_service(config).refresh(args.provider)
    if args.json:
        _print_json(result)
        return 0
    print(f"{result['provider']}: REFRESHED")
    print(f"Auth: {result['auth_mode']}")
    if result.get("account_plan_type"):
        print(f"ChatGPT plan/workspace: {result['account_plan_type']}")
    print(f"Models: {result['model_count']}")
    if result.get("catalog_cache"):
        print(f"Catalog cache: {result['catalog_cache']}")
    return 0


def command_model_list(args: argparse.Namespace) -> int:
    """List live provider models with Codex reasoning and SAGE qualification metadata."""
    config, _ = _load(args)
    result = _model_service(config).list_models(args.provider)
    if args.json:
        _print_json(result)
        return 0
    print(f"SAGE MODELS - {result['provider']}")
    rows = result["models"]
    if not rows:
        print("No provider model list is available from this transport.")
    for row in rows:
        suffix = " *" if row.get("selected") else ""
        label = row.get("display_name") or row.get("model")
        model_id = row.get("model")
        print(f"- {label} [{model_id}]{suffix}")
        if row.get("reasoning_efforts"):
            default = row.get("default_reasoning_effort")
            detail = ", ".join(row["reasoning_efforts"])
            print("  Reasoning: " + detail + (f" (default {default})" if default else ""))
        if row.get("qualified_profiles"):
            print("  SAGE approved: " + ", ".join(row["qualified_profiles"]))
        elif result["provider"] == "codex":
            print("  SAGE approved: none (available but unqualified)")
    print(result.get("diagnostic", ""))
    return 0


def command_model_recommend(args: argparse.Namespace) -> int:
    """Recommend a currently available Codex model/reasoning pair for one task profile."""
    config, _ = _load(args)
    result = _model_service(config).recommendation(args.workflow, args.operation)
    if args.json:
        _print_json(result)
        return 0
    print("SAGE MODEL RECOMMENDATION")
    print(f"Task profile: {result['task_profile']}")
    print(f"Complexity: {result['complexity']}")
    print(f"Model: {result['display_name']} [{result['model']}]")
    print(f"Reasoning: {result.get('reasoning_effort') or 'provider default'}")
    if result.get("conditional_second_pass_reasoning_effort"):
        print(f"Conditional second pass: {result['conditional_second_pass_reasoning_effort']}")
    print(f"Qualification: {result['qualification_status']}")
    return 0


def command_model_policy(args: argparse.Namespace) -> int:
    """Show the release-governed model qualification and reasoning policy."""
    config, _ = _load(args)
    policy = _model_service(config).policy()
    if args.json:
        _print_json(policy)
        return 0
    print("SAGE MODEL POLICY")
    print(f"Schema: {policy['schema_version']}")
    allowed = policy.get("global", {}).get("allowed_reasoning_efforts", [])
    ceiling = policy.get("global", {}).get("maximum_supported_reasoning_effort", "xhigh")
    print("Supported reasoning: " + (", ".join(allowed) if allowed else "none"))
    print(f"Reasoning ceiling: {ceiling}")
    print("Task profiles:")
    for key, row in policy.get("task_profiles", {}).items():
        print(
            f"- {key}: preferred={','.join(row.get('preferred_models', []))} "
            f"target={row.get('target_reasoning_effort')} "
            f"bounds={row.get('minimum_reasoning_effort')}..{row.get('maximum_reasoning_effort')}"
        )
    return 0


def command_model_use(args: argparse.Namespace) -> int:
    """Persist automatic routing or an explicit provider/model/reasoning selection."""
    config, _ = _load(args)
    result = _model_service(config).select(
        provider=args.provider,
        model=args.model,
        endpoint=getattr(args, "endpoint", None),
        reasoning_effort=getattr(args, "reasoning", None),
        auto=bool(args.auto),
    )
    if args.json:
        _print_json(result)
        return 0
    print(f"Selected provider: {result['selected_provider']}")
    if result['selected_provider'] == "codex" and result.get("selection_mode") == "AUTO":
        print("Selection: SAGE automatic task routing")
    else:
        print(f"Selected model: {result.get('selected_model') or 'provider default'}")
        if result.get("selected_reasoning_effort"):
            print(f"Selected reasoning: {result['selected_reasoning_effort']}")
    provider_status = result["provider_status"]
    print(f"Readiness: {'READY' if provider_status['ready'] else 'NOT READY'}")
    print(provider_status.get("diagnostic", ""))
    return 0



def command_model_provision(args: argparse.Namespace) -> int:
    """Persist non-secret configuration for a disabled local provider without activating it."""
    config, _ = _load(args)
    result = _model_service(config).provision(
        provider=args.provider,
        model=getattr(args, "model", None),
        endpoint=getattr(args, "endpoint", None),
    )
    if args.json:
        _print_json(result)
        return 0
    print(f"{result['provider']}: PROVISIONED / DISABLED FOR EXECUTION")
    print(f"Model: {result.get('model') or 'not set'}")
    if result.get('endpoint'):
        print(f"Endpoint: {result['endpoint']}")
    return 0

def command_model_test(args: argparse.Namespace) -> int:
    """Run a tiny structured-output connectivity test through one selected provider."""
    config, _ = _load(args)
    result = _model_service(config).connectivity_test(
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        reasoning_effort=getattr(args, "reasoning", None),
        timeout_seconds=args.timeout,
    )
    if args.json:
        _print_json(result)
        return 0
    print(f"{result['provider']}: READY")
    print(f"Model: {result.get('model') or 'provider default'}")
    if result.get("reasoning_effort"):
        print(f"Reasoning: {result['reasoning_effort']}")
    return 0


def command_task_execute(args: argparse.Namespace) -> int:
    """Execute one immutable task through the provider-neutral SAGE LLM harness."""
    config, _ = _load(args)
    result = execute_task(
        config,
        task_manifest=Path(args.task),
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        reasoning_effort=getattr(args, "reasoning", None),
        policy_override=bool(getattr(args, "policy_override", False)),
        timeout_seconds=args.timeout,
        dry_run=bool(args.dry_run),
    )
    if args.json:
        _print_json(result)
    else:
        print("SAGE TASK EXECUTION")
        print(f"Status: {result['status']}")
        print(f"Task: {result['task_id']}")
        print(f"Provider: {result['provider']}")
        print(f"Model: {result.get('model') or 'provider default'}")
        if result.get("reasoning_effort"):
            print(f"Reasoning: {result['reasoning_effort']}")
        if result.get("selection_mode"):
            print(f"Selection: {result['selection_mode']}")
        if result.get("operator_policy_override"):
            print("Policy override: YES")
        if result.get("receipt_path"):
            print(f"Receipt: {result['receipt_path']}")
        if result["status"] == "READY_TO_EXECUTE":
            print(f"Prompt bytes: {result['prompt_bytes']}")
            print(f"Conditional second pass: {result['conditional_second_pass']}")
    return 0

def command_act_create(args: argparse.Namespace) -> int:
    """Generate one isolated provider-neutral governed task."""
    config, _ = _load(args)
    result = create_act_task(
        config,
        workflow=args.workflow_id,
        operation=args.operation,
        output_project_id=args.output_project,
        contemporary_source_id=args.contemporary_source,
        lexical_donor_id=getattr(args, "lexical_donor", None),
        scope_value=args.scope,
        focus=args.focus,
        check_type=getattr(args, "check_type", None),
        predecessor_task=args.predecessor_task,
        grammar_override_id=getattr(args, "grammar_override_id", None),
        job_id=getattr(args, "job_id", None),
        run_id=getattr(args, "run_id", None),
    )
    if args.json:
        _print_json(result)
    else:
        if result.get("status") == "PARTITIONED":
            print("SAGE ACT WORK-UNIT PLAN")
            print(f"Plan: {result['plan_id']}")
            print(f"Workflow: {result['workflow'].upper()}")
            print(f"Operation: {result['operation']}")
            print(f"Requested scope: {result['requested_scope']}")
            print(f"Work units: {len(result['work_units'])}")
            print(f"Plan file: {result['plan_path']}")
        elif result.get("status") == "COMPOSITE":
            print("SAGE SAW Reference Text Comparison (RTC) COMPOSITE PLAN")
            print(f"Plan: {result['plan_id']}")
            print(f"Scope: {result['requested_scope']}")
            print(f"Current stage: {result['current_stage']}")
            print(f"Plan file: {result['plan_path']}")
        else:
            print("SAGE GOVERNED TASK")
            print(f"Task: {result['task_id']}")
            print(f"Workflow: {result['workflow'].upper()}")
            print(f"Operation: {result['operation']}")
            if result["workflow"] == "bic":
                print(f"SOURCE: {result['contemporary_source']}")
                print(f"DONOR: {result.get('lexical_donor') or 'NOT_CONFIGURED'} (vocabulary only)")
                print(f"TARGET: {result['output_project']} (write destination)")
            else:
                print(f"WIP: {result['output_project']}")
                print(f"REFERENCE: {result['contemporary_source']} (authorized Reference Project)")
            print(f"Scope: {result['scope']}")
            if result.get("focus"):
                print(f"Focus: {result['focus']}")
            print(f"Task prompt: {result['act_path']}")
    return 0


def command_act_submit(args: argparse.Namespace) -> int:
    """Validate one completed ACT task and report material REWRITE challenges."""
    config, _ = _load(args)
    task_path = resolve_declared_path(config.root, str(args.task), "task manifest")
    result = submit_act_task(config, task_path)
    source_project = config.project(str(result.get("contemporary_source")))
    target_project = config.project(str(result.get("output_project")))
    event_logger = OperationalLogger(
        root=config.root,
        spec=config.human_output,
        mode=_operational_log_mode(args),
        source_language=source_project.language_code,
        target_language=target_project.language_code,
    )
    if result.get("operation") == "rewrite":
        ledger_path = task_path.parent / "validation" / "translation-challenge-ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {}
        challenges = list(ledger.get("challenges", []))
        referrals = sum(1 for item in challenges if item.get("ol_referral", {}).get("performed"))
        changes = sum(1 for item in challenges if item.get("ol_referral", {}).get("candidate_changed"))
        if referrals:
            event_logger.emit(
                "OL_CHECK_COMPLETED",
                severity="NOTICE",
                context={"task": result.get("task_id"), "referrals": referrals, "candidate_changes": changes},
                console=not args.json,
            )
        material_count = int(
            result.get("validation", {})
            .get("translation_challenges", {})
            .get("material_count", 0)
            or 0
        )
        if material_count:
            event_logger.emit(
                "CHALLENGE_RECORDED",
                severity=(
                    "CRITICAL"
                    if result.get("validation", {}).get("translation_challenges", {}).get("highest_urgency") == 4
                    else "WARNING"
                ),
                context={
                    "task": result.get("task_id"),
                    "material": material_count,
                    "minor_aggregated": result.get("validation", {}).get("translation_challenges", {}).get("minor_aggregated", 0),
                },
                console=not args.json,
            )
        event_logger.emit(
            "REWRITE_COMPLETED",
            severity="SUCCESS",
            context={"task": result.get("task_id"), "status": result.get("status")},
            console=not args.json,
        )
        event_logger.emit(
            "SELF_CHECK_AVAILABLE",
            severity="INFO",
            context={"task": result.get("task_id")},
            console=not args.json,
        )
    if args.json:
        _print_json(result)
    else:
        print(_report_text(config, "report.act_submission"))
        print(f"{_report_text(config, 'label.task')}: {result['task_id']}")
        print(f"{_report_text(config, 'label.status')}: {result['status']}")
    return 0


def command_act_aggregate(args: argparse.Namespace) -> int:
    """Aggregate a `FINALIZED` SAW work-unit plan."""
    config, _ = _load(args)
    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = config.root / plan_path
    result = aggregate_act_plan(config, plan_path)
    if args.json:
        _print_json(result)
    else:
        print("SAGE ACT AGGREGATE")
        print(f"Plan: {result['plan_id']}")
        print(f"Status: {result['status']}")
        print(f"Work units: {len(result['work_units'])}")
        print(f"Reviewed coordinates: {len(result['coverage']['reviewed_references'])}")
        print(f"Findings: {result['finding_count']}")
        print(f"Aggregate: {result['aggregate_path']}")
    return 0


def command_act_continue(args: argparse.Namespace) -> int:
    """Return the next governed sequential SAW work unit or aggregation action."""
    config, _ = _load(args)
    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = config.root / plan_path
    result = continue_saw_plan(config, plan_path)
    if args.json:
        _print_json(result)
    else:
        print("SAGE SAW PLAN CONTINUATION")
        print(f"Plan: {result['plan_id']}")
        print(f"Status: {result['status']}")
        if result["status"] == "NEXT_WORK_UNIT":
            unit = result["next_unit"]
            print(f"Progress: {result['completed_units']}/{result['total_units']}")
            print(f"Next unit: {unit['unit_id']}")
            print(f"Scope: {unit['scope']}")
            print(f"ACT: {result['act_path']}")
            print(f"Submit: {result['submit_command']}")
        elif result["status"] == "READY_TO_AGGREGATE":
            print(f"Progress: {result['completed_units']}/{result['total_units']}")
            print(f"Aggregate: {result['aggregate_command']}")
        elif result.get("aggregate_path"):
            print(f"Aggregate: {result['aggregate_path']}")
            if result.get("operator_note_text_path"):
                print(f"Operator note text: {result['operator_note_text_path']}")
    return 0


def command_workflow_reset_stage(args: argparse.Namespace) -> int:
    """Reset generated runtime state for exactly one workflow stage."""
    config, _ = _load(args)
    result = reset_workflow_stage(
        config,
        workflow_id=args.workflow_id,
        stage=args.stage,
        operator=args.operator,
        decision_id=args.decision_id,
        notes=args.notes or "",
    )
    if args.json:
        _print_json(result)
    else:
        print("SAGE WORKFLOW STAGE RESET")
        print(f"Workflow: {result['workflow'].upper()}")
        print(f"Stage: {result['stage'].replace('_', '-')}")
        print(f"Tasks removed: {len(result['task_ids'])}")
        print(f"Paths removed: {len(result['removed'])}")
        print(f"Receipt: {result['receipt_path']}")
    return 0


def command_grammar_list(args: argparse.Namespace) -> int:
    """List configured grammar profiles and exact-hash review status."""
    config, _ = _load(args)
    rows = list_grammar_profile_reviews(config)
    if args.json:
        _print_json(rows)
    else:
        print("SAGE GRAMMAR PROFILE REVIEWS")
        for row in rows:
            review = row.get("review") or {}
            decision = review.get("decision", "NONE")
            print(
                f"{row['profile_key']}: declared={row['declared_status']} "
                f"effective={row['effective_status']} decision={decision} "
                f"sha256={row['profile_sha256']}"
            )
    return 0


def command_grammar_review(args: argparse.Namespace) -> int:
    """Record one Operator decision for the exact current grammar profile hash."""
    config, _ = _load(args)
    result = record_grammar_profile_review(
        config,
        profile_key=args.profile,
        decision_id=args.decision_id,
        operator=args.operator,
        decision=args.decision,
        notes=args.notes or "",
    )
    if args.json:
        _print_json(result)
    else:
        print("SAGE GRAMMAR PROFILE REVIEW")
        print(f"Profile: {result['profile_key']}")
        print(f"Decision: {result['decision']}")
        print(f"Declared status: {result['declared_status']}")
        print(f"Profile SHA-256: {result['profile_sha256']}")
        print(f"Registry: {result['registry_path']}")
    return 0


def command_resource_list(args: argparse.Namespace) -> int:
    """List SAGE Scripture Projects, access modes, and VRS-root configuration."""
    config, _ = _load(args)
    state = load_resource_mount_state(config.root)
    mounts = state["mounts"]
    rows = []
    for project_id, project in sorted(config.projects.items()):
        rows.append(
            {
                "project_id": project_id,
                "kind": project.kind,
                "content_state": project.content_state,
                "path": str(project.path),
                "external": project.external,
                "external_access_mode": project.external_access_mode,
                "mounted_path": (mounts.get(project_id) or {}).get("path"),
                "present": project.path.is_dir(),
                "roles": list(project.scope.roles),
            }
        )
    result = {
        "status": "READY",
        "mounts_path": str(config.system_root / "state" / "resource-mounts.json"),
        "base_vrs_root": str(config.base_vrs_root),
        "base_vrs_root_override": state.get("base_vrs_root"),
        "resources": rows,
    }
    if args.json:
        _print_json(result)
    else:
        print("SAGE RESOURCES")
        print(f"Base VRS root: {config.base_vrs_root}")
        for row in rows:
            mode = row["external_access_mode"] or "INTERNAL"
            present = "PRESENT" if row["present"] else "MISSING"
            print(f"{row['project_id']}: {present} {mode} {row['path']}")
    return 0


def command_resource_map(args: argparse.Namespace) -> int:
    """Map one USFM resource to an absolute Paratext/PTLite folder with governed access."""
    config, _ = _load(args)
    project = config.project(args.project)
    if project.kind not in {"SCRIPTURE", "GENERATED_SCRIPTURE"}:
        raise ValidationError(
            f"Only Scripture resources may be externally mapped: {project.project_id}",
            code="RESOURCE_MOUNT_KIND_INVALID",
        )
    access_mode = str(args.access).strip().upper()
    if access_mode == READ_WRITE_TARGET:
        if not (
            project.kind == "GENERATED_SCRIPTURE"
            and project.producer == "bic"
            and "GENERATED_TARGET" in project.scope.roles
        ):
            raise ValidationError(
                "READ_WRITE_TARGET is reserved for an explicitly configured BIC TARGET",
                code="RESOURCE_WRITE_ROLE_PROHIBITED",
            )
    destination = set_resource_mount(
        config.root,
        project_id=project.project_id,
        external_path=Path(args.path),
        access_mode=access_mode,
    )
    refreshed = load_ecosystem(config.settings_path).project(project.project_id)
    result = {
        "status": "MAPPED",
        "project_id": project.project_id,
        "path": str(refreshed.path),
        "external_access_mode": refreshed.external_access_mode,
        "mounts_path": str(destination),
    }
    if args.json:
        _print_json(result)
    else:
        print(f"Mapped {project.project_id}: {refreshed.external_access_mode} {refreshed.path}")
        print("External reads: .SFM and .VRS only (case-insensitive)")
        if refreshed.external_access_mode == READ_WRITE_TARGET:
            print("External writes: .SFM only")
        print(f"Mount registry: {destination}")
    return 0


def command_resource_unmap(args: argparse.Namespace) -> int:
    """Remove one external resource mapping and return to the configured internal path."""
    config, _ = _load(args)
    config.project(args.project)
    destination = remove_resource_mount(config.root, project_id=args.project)
    refreshed = load_ecosystem(config.settings_path).project(args.project)
    result = {
        "status": "UNMAPPED",
        "project_id": args.project,
        "path": str(refreshed.path),
        "external_access_mode": refreshed.external_access_mode,
        "mounts_path": str(destination),
    }
    if args.json:
        _print_json(result)
    else:
        print(f"Removed external mapping for {args.project}")
        print(f"Configured path: {refreshed.path}")
    return 0


def command_resource_vrs_root(args: argparse.Namespace) -> int:
    """Show, set, or clear the machine-local base VRS root."""
    config, _ = _load(args)
    if bool(args.clear):
        destination = clear_base_vrs_root(config.root)
    elif args.path:
        destination = set_base_vrs_root(config.root, base_vrs_root=Path(args.path))
    else:
        destination = config.system_root / "state" / "resource-mounts.json"
    refreshed = load_ecosystem(config.settings_path)
    state = load_resource_mount_state(config.root)
    result = {
        "status": "READY",
        "base_vrs_root": str(refreshed.base_vrs_root),
        "override": state.get("base_vrs_root"),
        "mounts_path": str(destination),
    }
    if args.json:
        _print_json(result)
    else:
        print(f"Base VRS root: {refreshed.base_vrs_root}")
        print(f"Override: {state.get('base_vrs_root') or 'NONE'}")
    return 0


def command_resource_validate_rights(args: argparse.Namespace) -> int:
    """Validate machine-readable provenance and rights records for configured resources."""
    config, _ = _load(args)
    if args.metadata_root == "auto":
        candidates = (
            config.root / "resource-provenance" / "metadata",
            config.root.parent / "resource-provenance" / "metadata",
            config.root.parent.parent / "resource-provenance" / "metadata",
        )
        metadata_root = next((path for path in candidates if path.is_dir()), candidates[0])
    else:
        metadata_root = Path(args.metadata_root).expanduser()
        if not metadata_root.is_absolute():
            metadata_root = config.root / metadata_root
    result = validate_resource_rights(config, metadata_root=metadata_root)
    if args.json:
        _print_json(result)
    else:
        print("SAGE RESOURCE RIGHTS VALIDATION")
        print(f"Status: {result['status']}")
        print(f"Configured projects: {result['configured_projects']}")
        print(f"Blocking projects: {result['blocking_projects']}")
        print(f"Report: {result['report_path']}")
        for row in result["projects"]:
            print(
                f"{row['project_id']}: {row['status']} "
                f"errors={len(row['errors'])} warnings={len(row['warnings'])}"
            )
    return 2 if result["status"] == "BLOCKED" else 0


def command_memory_review(args: argparse.Namespace) -> int:
    """Record optional human memory-review provenance for one committed INSPECT scope."""
    config, _ = _load(args)
    result = record_human_memory_review(
        memory_root=workflow_memory_root(config.workflow("bic")),
        transaction_root=config.workflow("bic").transaction_root,
        scope=args.scope,
        decision_id=args.decision_id,
        reviewer=args.reviewer,
        decision=args.decision,
        notes=args.notes or "",
    )
    if args.json:
        _print_json(result)
    else:
        print("SAGE BIC MEMORY REVIEW PROVENANCE")
        print(f"Scope: {result['scope']}")
        print(f"Decision: {result['decision']}")
        print(f"Review ID: {result['review_id']}")
    return 0


def command_memory_list(args: argparse.Namespace) -> int:
    """List individual BIC memory records and their governed source states."""
    config, _ = _load(args)
    records = list_memory_records(
        workflow_memory_root(config.workflow("bic")),
        state=args.state,
        source=args.source,
    )
    result = {
        "schema_version": "1.0",
        "status": "READY",
        "record_count": len(records),
        "records": records,
    }
    if args.json:
        _print_json(result)
    else:
        print("SAGE BIC MEMORY RECORDS")
        print(f"Records: {len(records)}")
        for row in records:
            print(
                f"- {row['record_id']} | {row.get('memory_state', '')} | "
                f"{row.get('record_source', '')} | {row.get('record_type', '')}"
            )
    return 0


def command_memory_transition(args: argparse.Namespace) -> int:
    """Apply one governed, stale-safe transition to an individual BIC memory record."""
    config, _ = _load(args)
    result = transition_memory_record_transactionally(
        memory_root=workflow_memory_root(config.workflow("bic")),
        transaction_root=config.workflow("bic").transaction_root,
        record_id=args.record_id,
        expected_state=args.expected_state,
        new_state=args.new_state,
        operator_decision_id=args.decision_id,
        operator=args.operator,
        notes=args.notes or "",
    )
    if args.json:
        _print_json(result)
    else:
        print("SAGE BIC MEMORY TRANSITION")
        print(f"Record: {result['record_id']}")
        print(f"State: {result['from_state']} -> {result['to_state']}")
        print(f"Transition: {result['transition_id']}")
        print(f"Transaction: {result['transaction_id']}")
    return 0


def command_memory_import_lexicon(args: argparse.Namespace) -> int:
    """Import one governed lexicon document as unapproved BIC memory records."""
    config, _ = _load(args)
    import_path = Path(args.file).expanduser()
    if not import_path.is_absolute():
        import_path = (config.root / import_path).resolve()
    else:
        import_path = import_path.resolve()
    if not import_path.is_file():
        raise ValidationError(f"Lexicon import file does not exist: {import_path}")
    try:
        if import_path.suffix.casefold() == ".json":
            document = json.loads(import_path.read_text(encoding="utf-8"))
        else:
            document = yaml.safe_load(import_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValidationError(f"Invalid lexicon import document {import_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValidationError("Lexicon import document must contain one mapping")
    result = import_lexicon_transactionally(
        document,
        source_sha256=sha256_file(import_path),
        operator=args.operator,
        operator_decision_id=args.decision_id,
        notes=args.notes or "",
        memory_root=workflow_memory_root(config.workflow("bic")),
        transaction_root=config.workflow("bic").transaction_root,
        bic_job_id=(
            active_bic.job_id
            if (active_bic := JobStore(config.root, config.settings_path).active_job("bic")) is not None
            else None
        ),
    )
    result["source_file"] = str(import_path)
    if args.json:
        _print_json(result)
    else:
        print("SAGE BIC LEXICON IMPORT")
        print(f"Import: {result['import_id']}")
        print(f"Records: {result['record_count']}")
        print("Initial state: PROPOSED")
        print(f"Transaction: {result['transaction_id']}")
    return 0


def command_memory_rollback_import(args: argparse.Namespace) -> int:
    """Deactivate every record from one governed lexicon import."""
    config, _ = _load(args)
    result = rollback_lexicon_import_transactionally(
        import_id=args.import_id,
        operator=args.operator,
        operator_decision_id=args.decision_id,
        notes=args.notes or "",
        memory_root=workflow_memory_root(config.workflow("bic")),
        transaction_root=config.workflow("bic").transaction_root,
    )
    if args.json:
        _print_json(result)
    else:
        print("SAGE BIC LEXICON IMPORT ROLLBACK")
        print(f"Import: {result['import_id']}")
        print(f"Records deactivated: {len(result['affected_records'])}")
        print(f"Rollback: {result['rollback_id']}")
        print(f"Transaction: {result['transaction_id']}")
    return 0


def command_job_layout_audit(args: argparse.Namespace) -> int:
    """Audit canonical and legacy Job folders without mutation."""
    config, _ = _load(args)
    result = write_job_layout_audit(config.root)
    if args.json:
        _print_json(result)
    else:
        print(render_job_layout_audit(result), end="")
        print(f"Audit: {result['json_path']}")
    return 0


def command_job_layout_migrate(args: argparse.Namespace) -> int:
    """Run dry-run-first Job-layout migration against one exact audit receipt."""
    config, _ = _load(args)
    audit_path = Path(args.from_audit).expanduser()
    if not audit_path.is_absolute():
        audit_path = (config.root / audit_path).resolve()
    result = migrate_job_layout(config.root, audit_path, apply=bool(args.apply))
    if args.json:
        _print_json(result)
    else:
        print("SAGE JOB LAYOUT MIGRATION")
        print(f"Status: {result['status']}")
        print(f"Actions: {len(result['actions'])}")
        print(f"Receipt: {result['receipt_path']}")
        if not args.apply:
            print("Dry run only. Re-run with --apply after reviewing the exact audit and action receipt.")
    return 0


def command_job_layout_verify(args: argparse.Namespace) -> int:
    """Verify current Job layout after audit/migration without changing state."""
    config, _ = _load(args)
    result = verify_job_layout(config.root)
    if args.json:
        _print_json(result)
    else:
        print("SAGE JOB LAYOUT VERIFY")
        print(f"Status: {result['status']}")
        print(f"Legacy remaining: {result['legacy_remaining']}")
        print(f"Unknown preserved: {result['unknown_preserved']}")
    return 0 if result["legacy_remaining"] == 0 else 1


def command_reset_state(args: argparse.Namespace) -> int:
    """Remove generated project state and caches before a clean test or pilot run."""
    config, _ = _load(args)
    result = reset_project_state(config, include_test_artifacts=not args.keep_test_artifacts)
    if args.json:
        _print_json(result)
    else:
        print("SAGE PROJECT STATE RESET")
        print(f"Status: {result['status']}")
        print(f"Removed entries: {len(result['removed'])}")
        print("Projects and configuration were preserved.")
    return 0


def command_evaluation_plan(args: argparse.Namespace) -> int:
    """Create a sequential queue of one-project SAW ACT commands."""
    config, _ = _load(args)
    try:
        evaluation = config.evaluation_sets[args.set_id]
    except KeyError as exc:
        raise ValidationError(f"Unknown evaluation set: {args.set_id}") from exc
    scope = parse_scope(args.scope)
    focus = args.focus.strip() if isinstance(args.focus, str) and args.focus.strip() else None
    if args.operation in {"focused", "ol"} and not focus:
        raise ValidationError(f"SAW {args.operation} evaluation requires --focus")
    if args.operation == "rtc" and focus:
        raise ValidationError("--focus is valid only for focused or ol evaluation")
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(evaluation.entries, start=1):
        readiness = validate_act_request_readiness(
            config,
            workflow="saw",
            output_project_id=entry.output_project,
            contemporary_source_id=entry.contemporary_source,
            scope_value=scope.label(),
        )
        command_argv = [
            "--settings",
            config.settings_path.name,
            "task",
            "create",
            "--workflow",
            "saw",
            "--operation",
            args.operation,
            "--wip",
            entry.output_project,
            "--reference",
            entry.contemporary_source,
            "--scope",
            scope.label(),
        ]
        if focus:
            command_argv.extend(["--focus", focus])
        if getattr(args, "check_type", None):
            command_argv.extend(["--type", args.check_type])
        command = render_sage_command(command_argv, windows=False)
        command_windows = render_sage_command(command_argv, windows=True)
        entries.append(
            {
                "sequence": index,
                "output_project": entry.output_project,
                "contemporary_source": entry.contemporary_source,
                "scope": scope.label(),
                "focus": focus,
                "readiness": readiness,
                "commands": {"posix": command, "windows": command_windows},
                "command": command,
            }
        )
    result = {
        "schema_version": "1.0",
        "evaluation_set": evaluation.set_id,
        "execution_mode": evaluation.execution_mode,
        "operation": args.operation,
        "scope": scope.label(),
        "focus": focus,
        "entries": entries,
        "tasks": entries,
        "rule": "Run one command at a time; do not combine projects in one prompt.",
    }
    safe_scope = _safe_id(scope.label()).lower()
    output = (
        config.workflow("saw").output_root
        / "evaluations"
        / evaluation.set_id
        / f"{safe_scope}.queue.json"
    )
    atomic_write_json(output, result)
    result["queue_path"] = str(output)
    if args.json:
        _print_json(result)
    else:
        print("SAGE EVALUATION QUEUE")
        print(f"Set: {evaluation.set_id}")
        print("Mode: SEQUENTIAL")
        for item in entries:
            print(menu_item(item["sequence"], f"macOS/Linux: {item['commands']['posix']}"))
            print(f"   Windows: {item['commands']['windows']}")
        print(f"Queue: {output}")
    return 0


def command_initialize(args: argparse.Namespace) -> int:
    """Validate resources, guide recoverable settings, and write readiness state."""
    # Persist readiness only after remediation, validation, compilation, and restriction collection agree.
    config, standard = _load(args)
    init_remediation: dict[str, Any] = {
        "changed": False,
        "operator_overrides_path": (
            str(config.operator_overrides_path) if config.operator_overrides_path else None
        ),
        "operator_resolutions": list(config.operator_resolutions),
    }
    init_requirements = _init_input_requirements(
        config,
        project_ids=getattr(args, "target_project_ids", None),
    )
    needs_input = (
        not init_requirements["configured"]
        or bool(init_requirements["disabled_projects"])
        or bool(init_requirements["unresolved_auto_settings"])
    )
    if needs_input and not _interactive(args):
        _raise_init_input_required(init_requirements)
    if needs_input and _interactive(args):
        init_remediation = run_targeted_init_remediation(
            config,
            project_ids=init_requirements["project_ids"],
            input_stream=sys.stdin,
            output_stream=sys.stderr,
        )
        if init_remediation.get("changed"):
            config, standard = _load(args)
    lock_path = config.system_root / "locks" / "initialize.lock"
    with WorkspaceLock(lock_path, "SAGE_INITIALIZE", break_stale=args.break_stale_lock):
        for workflow in config.workflows.values():
            workflow.state_root.mkdir(parents=True, exist_ok=True)
            workflow.lock_root.mkdir(parents=True, exist_ok=True)
            workflow.transaction_root.mkdir(parents=True, exist_ok=True)
            workflow.output_root.mkdir(parents=True, exist_ok=True)
            if workflow.publication_root is not None:
                workflow.publication_root.mkdir(parents=True, exist_ok=True)
        config.cache_root.mkdir(parents=True, exist_ok=True)
        static = validate_static_ecosystem(config, standard)
        auto_resolutions = resolve_auto_settings(config)
        errors = list(static["errors"])
        restrictions: list[str] = []
        projects: dict[str, Any] = {}
        workflows: dict[str, Any] = {}

        for workflow_id, workflow in config.workflows.items():
            profile = load_workflow_profile(config, workflow)
            contracts = _grammar_contracts(config, profile)
            pending = incomplete_transactions(workflow.transaction_root)
            workflows[workflow_id] = {
                "name": profile.name,
                "qualification_status": profile.qualification_status,
                "bindings": profile.bindings,
                "language_profile_bindings": profile.language_profile_bindings,
                "language_contracts": {
                    role: {
                        "language_profile": contract["language_profile"],
                        "profile_variant": contract["profile_variant"],
                        "profile_ref": contract["profile_ref"],
                        "profile_sha256": contract["profile_sha256"],
                        "cache": contract["cache"],
                    }
                    for role, contract in contracts.items()
                },
                "evidence_policies": {
                    name: policy.to_dict()
                    for name, policy in sorted(profile.evidence_policies.items())
                },
                "state_root": str(workflow.state_root),
                "output_root": str(workflow.output_root),
                "publication_root": (
                    str(workflow.publication_root) if workflow.publication_root else None
                ),
                "pending_transactions": len(pending),
            }
            if pending:
                restrictions.append(
                    f"{workflow_id.upper()} has {len(pending)} incomplete transaction(s); "
                    "recover them before write operations."
                )
            if profile.qualification_status != "VALIDATED":
                restrictions.append(
                    f"{workflow_id.upper()} workflow qualification is {profile.qualification_status}; "
                    "shared planning and validation are available, but analytical execution is disabled."
                )

        if not config.configured:
            errors.append(
                "ecosystem.configured is false; configure project paths before operational initialization"
            )
        if not errors:
            for project_id, project in config.projects.items():
                try:
                    projects[project_id] = compile_project(config, project)
                except SageError as exc:
                    projects[project_id] = {
                        "project_id": project_id,
                        "path": str(project.path),
                        "status": "BLOCKED",
                        "issues": [
                            {
                                "code": "PROJECT_VALIDATION_FAILED",
                                "reference": "",
                                "message": str(exc),
                            }
                        ],
                        "warnings": [],
                        "files": [],
                    }
                project_status = projects[project_id].get("status")
                if project_status == "BLOCKED":
                    restrictions.append(
                        f"Project {project_id} failed validation; workflows that require it are blocked."
                    )

            ready_statuses = {"READY", "READY_WITH_WARNINGS"}
            required_roles = {
                "bic": {"CONTENT_SOURCE", "LEXICAL_DONOR", "GENERATED_TARGET"},
                "saw": {"WIP", "REFERENCE"},
            }
            for workflow_id, item in workflows.items():
                binding_statuses = {
                    role: projects.get(project_id, {}).get("status", "BLOCKED")
                    for role, project_id in item["bindings"].items()
                }
                blocked_roles: list[str] = []
                limited_roles: list[str] = []
                for role, project_status in binding_statuses.items():
                    if workflow_id == "bic" and role == "GENERATED_TARGET":
                        acceptable = project_status in ready_statuses | {"NOT_GENERATED"}
                    else:
                        acceptable = project_status in ready_statuses
                    if acceptable:
                        continue
                    label = f"{role}={project_status}"
                    if role in required_roles[workflow_id]:
                        blocked_roles.append(label)
                    elif role.startswith("ORIGINAL_LANGUAGE_"):
                        limited_roles.append(label)
                    else:
                        blocked_roles.append(label)
                resource_state = (
                    "BLOCKED" if blocked_roles else ("READY_WITH_LIMITATIONS" if limited_roles else "READY")
                )
                controller_available = (
                    item["qualification_status"] == "VALIDATED"
                    and item["pending_transactions"] == 0
                )
                default_execution_available = controller_available and resource_state in {"READY", "READY_WITH_LIMITATIONS"}
                item["binding_statuses"] = binding_statuses
                item["resource_state"] = resource_state
                item["controller_available"] = controller_available
                item["default_execution_available"] = default_execution_available
                item["execution_available"] = default_execution_available
                item["optional_resource_limitations"] = limited_roles
                if blocked_roles:
                    restrictions.append(
                        f"{workflow_id.upper()} resource readiness is BLOCKED: "
                        + ", ".join(blocked_roles)
                    )
                if limited_roles:
                    restrictions.append(
                        f"{workflow_id.upper()} is READY_WITH_LIMITATIONS: optional original-language "
                        "resource unavailable (" + ", ".join(limited_roles) + "). Normal non-OL work remains executable; only an invoked applicable OL stage is constrained."
                    )
                write_state(
                    config.workflows[workflow_id].state_root / "workflow.json",
                    {
                        "schema_version": "1.0",
                        "workflow_id": workflow_id,
                        "state": resource_state,
                        "qualification_status": item["qualification_status"],
                        "resource_state": resource_state,
                        "controller_available": controller_available,
                        "default_execution_available": default_execution_available,
                        "execution_available": default_execution_available,
                        "binding_statuses": binding_statuses,
                        "optional_resource_limitations": limited_roles,
                        "pending_transactions": item["pending_transactions"],
                    },
                )

        state = "BLOCKED" if errors else ("READY_WITH_ACTIONS" if restrictions else "READY")
        capability = "RESTRICTED" if errors or restrictions else "VALIDATED"
        if errors:
            next_action = (
                f"Correct the listed ecosystem configuration errors, then rerun `{render_sage_command(['workspace', 'initialize'])}`."
            )
        elif restrictions:
            next_action = (
                "Review the listed actions. Exact-scope task validation will decide whether any item prevents execution."
            )
        else:
            next_action = "The shared ecosystem and both workflow profiles are validated."
        payload = {
            "version": standard.version,
            "settings": str(config.settings_path),
            "settings_sha256": sha256_file(config.settings_path),
            "operator_overrides_sha256": (
                sha256_file(config.operator_overrides_path)
                if config.operator_overrides_path and config.operator_overrides_path.is_file()
                else None
            ),
            "projects_root": str(config.projects_root),
            "capability": capability,
            "workflows": workflows,
            "projects": projects,
            "static_validation": static,
            "auto_resolutions": auto_resolutions,
            "operator_overrides_path": (
                str(config.operator_overrides_path)
                if config.operator_overrides_path
                else init_remediation.get("operator_overrides_path")
            ),
            "operator_resolutions": list(config.operator_resolutions),
            "guided_remediation": init_remediation,
            "restrictions": sorted(set(restrictions)),
            "errors": sorted(set(errors)),
            "next_action": next_action,
        }
        write_ecosystem_state(config.runtime_state_root, standard, state, payload)
        result = {"state": state, **payload}
        report_root = config.reports_root / "initialization"
        atomic_write_json(report_root / "initialization-report.json", result)
        atomic_write_text(
            report_root / "initialization-report.md",
            _render_initialization_report(config, result),
        )
        atomic_write_json(report_root / "auto-resolution-report.json", auto_resolutions)
        atomic_write_text(
            report_root / "auto-resolution-report.md",
            render_auto_resolution_report(config, auto_resolutions),
        )
    if args.json:
        _print_json(result)
    else:
        print("SAGE INITIALIZATION RESULT")
        print(f"State: {state}")
        print(f"Capability: {capability}")
        print(f"Projects: {len(projects)}")
        print(f"Errors: {len(errors)}")
        print(f"Restrictions: {len(restrictions)}")
        print(f"Auto settings: {len(auto_resolutions)}")
        print(f"Report: {report_root / 'initialization-report.md'}")
        print(f"Auto report: {report_root / 'auto-resolution-report.md'}")
        print(f"Next: {next_action}")
    return 2 if errors else 0


def command_validate(args: argparse.Namespace) -> int:
    """Validate either the source package or the configured ecosystem."""
    config, standard = _load(args)
    remediation: dict[str, Any] | None = None
    if not args.package:
        init_requirements = _init_input_requirements(config)
        needs_input = (
            not init_requirements["configured"]
            or bool(init_requirements["disabled_projects"])
            or bool(init_requirements["unresolved_auto_settings"])
        )
        if needs_input and not _interactive(args):
            _raise_init_input_required(init_requirements)
        if needs_input and _interactive(args):
            remediation = run_targeted_init_remediation(
                config,
                project_ids=init_requirements["project_ids"],
                input_stream=sys.stdin,
                output_stream=sys.stderr,
            )
            if remediation.get("changed"):
                config, standard = _load(args)
    result = (
        validate_package(config.root)
        if args.package
        else validate_static_ecosystem(config, standard)
    )
    if remediation is not None:
        result["guided_remediation"] = remediation
    if args.json:
        _print_json(result)
    else:
        print("SAGE VALIDATION RESULT")
        print(f"Status: {result['status']}")
        for error in result.get("errors", []):
            print(f"ERROR: {error}")
        for warning in result.get("warnings", []):
            print(f"WARNING: {warning}")
    return 2 if result["status"] == "BLOCKED" else 0


def command_status(args: argparse.Namespace) -> int:
    """Report the last governed ecosystem state without changing it."""
    config, standard = _load(args)
    state = read_state(ecosystem_state_path(config.runtime_state_root))
    if not state:
        state = {
            "state": "NOT_RUN",
            "version": standard.version,
            "next_action": f"Run `{render_sage_command(['workspace', 'initialize'])}`.",
        }
    if args.json:
        _print_json(state)
    else:
        print("SAGE STATUS")
        print(f"State: {state.get('state', 'UNKNOWN')}")
        print(f"Capability: {state.get('capability', 'NOT_IMPLEMENTED')}")
        print(f"Version: {state.get('version', standard.version)}")
        print(f"Next: {state.get('next_action', 'Run validation.')}")
    return 0


def command_bic_restart_scope(args: argparse.Namespace) -> int:
    """Restart one BIC analytical scope without changing committed TARGET Scripture."""
    config, _ = _load(args)
    store = JobStore(config.root, config.settings_path)
    project = store.load_job(args.job, tool="bic")
    run = store.restart_bic_scope(project, scope=parse_scope(args.scope).label())
    result = {
        "status": "RESTARTED",
        "job_id": project.job_id,
        "scope": run.scope,
        "run_id": run.run_id,
        "target_changed": False,
    }
    if args.json:
        _print_json(result)
    else:
        print("BIC SCOPE RESTARTED")
        print(f"Job: {project.job_id}")
        print(f"Scope: {run.scope}")
        print(f"New run: {run.run_id}")
        print("TARGET Scripture changed: NO")
    return 0


def command_bic_target_history(args: argparse.Namespace) -> int:
    """List bounded BIC TARGET commit history without modifying Scripture."""
    config, _ = _load(args)
    store = JobStore(config.root, config.settings_path)
    project = store.load_job(args.job, tool="bic")
    scope = parse_scope(args.scope).label() if args.scope else None
    rows = list_target_history(project.root, scope_value=scope)
    if args.json:
        _print_json(rows)
    else:
        print("BIC TARGET HISTORY")
        if not rows:
            print("No bounded TARGET commits found.")
        for row in rows:
            print(f"{row['commit_id']}: {row['scope']} -> {row['after_scope_sha256']}")
    return 0


def command_bic_revert_target_scope(args: argparse.Namespace) -> int:
    """Revert one exact BIC TARGET scope to its immediately preceding bounded commit state."""
    config, _ = _load(args)
    store = JobStore(config.root, config.settings_path)
    project = store.load_job(args.job, tool="bic")
    runtime_path = store.ensure_runtime_files(project)
    runtime = load_ecosystem(runtime_path)
    target = runtime.project(project.bindings["generated_target"])
    scope = parse_scope(args.scope)
    target_file = _one_book_file(target, scope.book, optional=False)
    assert target_file is not None
    if target.external:
        if not target.external_writable_target:
            raise ValidationError(
                f"External BIC TARGET {target.project_id} is read-only",
                code="EXTERNAL_TARGET_WRITE_PROHIBITED",
            )
        target_file = validate_external_file(target_file, roots=(target.path,), write=True)
    result = revert_target_scope(
        job_root=project.root,
        target_file=target_file,
        scope_value=scope.label(),
        transaction_root=runtime.workflow("bic").transaction_root,
        allowed_roots=(target.path,),
    )
    if args.json:
        _print_json(result)
    else:
        print("BIC TARGET SCOPE REVERTED")
        print(f"Job: {project.job_id}")
        print(f"Scope: {result['scope']}")
        print(f"Reverted commit: {result['reverted_commit_id']}")
        print(f"TARGET: {result['target_file']}")
    return 0


def command_projects(args: argparse.Namespace) -> int:
    """List SAGE Projects and any effective Job-scoped roles in this configuration."""
    config, _ = _load(args)
    rows = [
        {
            "project_id": project.project_id,
            "enabled": project.enabled,
            "path": str(project.path),
            "language_code": project.language_code,
            "language_profile": project.language_profile,
            "profile_variant": project.profile_variant,
            "kind": project.kind,
            "content_state": project.content_state,
            "roles": list(project.scope.roles),
            "producer": project.producer,
            "allow_empty": project.allow_empty,
            "vrs_base_file": project.versification.base_file,
            "custom_vrs_file": project.versification.custom_file,
            "scope_testament": project.scope.testament,
            "scope_canon": project.scope.canon,
            "expected_books": project.scope.expected_books,
        }
        for project in config.projects.values()
    ]
    if args.json:
        _print_json(rows)
    else:
        print("SAGE PROJECTS")
        for row in rows:
            print(
                f"{row['project_id']}: enabled={str(row['enabled']).lower()} "
                f"language={row['language_code']} profile={row['language_profile']}"
                f"/{row['profile_variant'] or '-'} kind={row['kind']} "
                f"state={row['content_state']} scope={row['scope_testament']}/{row['scope_canon']} "
                f"roles={','.join(row['roles'])} "
                f"vrs={row['vrs_base_file']}+{row['custom_vrs_file']} path={row['path']}"
            )
    return 0


def command_workflow_status(args: argparse.Namespace) -> int:
    """Report one workflow profile, resource state, and qualification restrictions."""
    config, _ = _load(args)
    workflow = config.workflow(args.workflow_id)
    profile = load_workflow_profile(config, workflow)
    state = read_state(workflow.state_root / "workflow.json")
    ecosystem_state = read_state(ecosystem_state_path(config.runtime_state_root))
    ecosystem_workflow = (ecosystem_state.get("workflows", {}) or {}).get(
        profile.workflow_id,
        {},
    )
    result = {
        "workflow_id": profile.workflow_id,
        "name": profile.name,
        "qualification_status": profile.qualification_status,
        "runtime_state": state.get("state", "NOT_RUN"),
        "resource_state": ecosystem_workflow.get("resource_state", "NOT_RUN"),
        "bindings": profile.bindings,
        "language_profile_bindings": profile.language_profile_bindings,
        "evidence_policies": {
            name: policy.to_dict()
            for name, policy in sorted(profile.evidence_policies.items())
        },
        "binding_statuses": ecosystem_workflow.get("binding_statuses", {}),
        "may_write_projects": list(profile.may_write_projects),
        "state_root": str(workflow.state_root),
        "output_root": str(workflow.output_root),
        "publication_root": str(profile.publication_root) if profile.publication_root else None,
        "pending_transactions": len(incomplete_transactions(workflow.transaction_root)),
        "execution_available": bool(ecosystem_workflow.get("execution_available", False)),
    }
    if args.json:
        _print_json(result)
    else:
        print(f"{profile.workflow_id.upper()} WORKFLOW STATUS")
        print(f"Qualification: {profile.qualification_status}")
        print(f"Runtime: {result['runtime_state']}")
        print(f"Resources: {result['resource_state']}")
        print(f"Pending transactions: {result['pending_transactions']}")
        print(f"Execution available: {'YES' if result['execution_available'] else 'NO'}")
        print(
            "Bindings: "
            + ", ".join(
                f"{role}={project}" for role, project in sorted(profile.bindings.items())
            )
        )
    return 0


def command_plan(args: argparse.Namespace) -> int:
    """Build a bounded auditable plan without running BIC or SAW analysis."""
    # Keep planning read-only and retain exact project and scope provenance for every proposed action.
    config, standard = _load(args)
    workflow = config.workflow(args.workflow_id)
    profile = load_workflow_profile(config, workflow)
    operation = args.operation.strip().lower()
    if operation not in ALLOWED_OPERATIONS[profile.workflow_id]:
        allowed = ", ".join(sorted(ALLOWED_OPERATIONS[profile.workflow_id]))
        raise ValidationError(
            f"Unsupported {profile.workflow_id.upper()} planning operation {operation!r}; "
            f"expected one of: {allowed}"
        )
    policy = profile.evidence_policy(operation)
    role = PRIMARY_ROLE[profile.workflow_id]
    default_project = profile.bindings[role]
    project_id = args.project or default_project
    matching_roles = [
        bound_role
        for bound_role, bound_project in profile.bindings.items()
        if bound_project == project_id
    ]
    if not matching_roles:
        raise ValidationError(
            f"Project {project_id} is not bound to the {profile.workflow_id.upper()} workflow"
        )
    selected_role = role if project_id == default_project else matching_roles[0]
    project = config.project(project_id)
    scope = parse_scope(args.scope)
    result = compile_project_scope(config, project, scope)
    if result.get("status") not in {"READY", "READY_WITH_WARNINGS"}:
        raise ValidationError(
            f"Project {project_id} is not ready for evidence planning in {scope.label()}: "
            f"{result.get('status')}"
        )
    all_records = records_from_project_result(
        project_id,
        result,
        resource_role=selected_role,
    )
    selected = select_records_for_scope(all_records, scope)
    rtc_sizing = None
    reference_project_id: str | None = None
    reference_result: dict[str, Any] | None = None
    reference_records = ()
    effective_policy = policy
    if profile.workflow_id == "saw" and operation == "rtc":
        if selected_role != "WIP":
            raise ValidationError("SAW RTC planning must use the bound WIP as its slicing stream")
        rtc_sizing = profile.require_rtc_sizing()
        active_provider = str(load_llm_settings(config.root).get("selected_provider") or "")
        rtc_sizing.validate_active_provider(active_provider)
        effective_policy = rtc_slicing_policy(policy, rtc_sizing)
        reference_project_id = profile.bindings["REFERENCE"]
        reference_project = config.project(reference_project_id)
        reference_result = compile_project_scope(config, reference_project, scope)
        if reference_result.get("status") not in {"READY", "READY_WITH_WARNINGS"}:
            raise ValidationError(
                f"REFERENCE project {reference_project_id} is not ready for RTC package "
                f"planning in {scope.label()}: {reference_result.get('status')}",
                code="SAW_RTC_REFERENCE_NOT_READY",
            )
        reference_records = records_from_project_result(
            reference_project_id,
            reference_result,
            resource_role="REFERENCE",
        )
    contracts = _grammar_contracts(config, profile)
    evidence_contracts = {
        contract_role: {
            key: value
            for key, value in contract.items()
            if key != "cache"
        }
        for contract_role, contract in contracts.items()
    }
    shared_hashes = {
        "resource_sha256": str(result.get("resource_sha256", "")),
        "effective_vrs_sha256": str(
            result.get("effective_vrs", {}).get("effective_sha256", "")
        ),
        "structure_policy_sha256": str(
            result.get("structure_policy", {}).get("effective_sha256", "")
        ),
        "compiled_files_sha256": str(result.get("compiled_files_sha256", "")),
        **{
            f"language-profile:{role_name}": str(contract["profile_sha256"])
            for role_name, contract in contracts.items()
        },
    }
    if reference_result is not None:
        shared_hashes.update({
            "reference_resource_sha256": str(reference_result.get("resource_sha256", "")),
            "reference_effective_vrs_sha256": str(
                reference_result.get("effective_vrs", {}).get("effective_sha256", "")
            ),
            "reference_structure_policy_sha256": str(
                reference_result.get("structure_policy", {}).get("effective_sha256", "")
            ),
            "reference_compiled_files_sha256": str(
                reference_result.get("compiled_files_sha256", "")
            ),
        })
    plan_key = {
        "sage_version": standard.version,
        "usj_compiler": USJ_COMPILER,
        "workflow_id": profile.workflow_id,
        "operation": operation,
        "operator_scope": scope.label(),
        "project_id": project_id,
        "policy": effective_policy.to_dict(),
        "shared_hashes": shared_hashes,
        **(
            {
                "reference_project_id": reference_project_id,
                "rtc_sizing": rtc_sizing.to_dict(),
                "rtc_planner_version": RTC_PLANNER_VERSION,
                "handoff_contract_version": RTC_HANDOFF_CONTRACT_VERSION,
                "prompt_schema_projection_version": RTC_PROMPT_SCHEMA_PROJECTION_VERSION,
            }
            if rtc_sizing is not None
            else {}
        ),
    }
    plan_fingerprint = sha256_bytes(serialize_evidence(plan_key))
    plan_digest = plan_fingerprint[:12].upper()
    scope_prefix = _safe_id(
        f"{profile.workflow_id}-{operation}-{scope.label()}"
    ).upper()
    plan_id = f"{scope_prefix}-{plan_digest}"
    shared = {
        "plan_id": plan_id,
        "plan_fingerprint": plan_fingerprint,
        "sage_version": standard.version,
        "usj_compiler": USJ_COMPILER,
        "workflow_id": profile.workflow_id,
        "operation": operation,
        "operator_scope": scope.label(),
        "project_id": project_id,
        "resource_role": selected_role,
        "resource_sha256": result.get("resource_sha256", ""),
        "compiled_files_sha256": result.get("compiled_files_sha256", ""),
        "effective_vrs_sha256": result.get("effective_vrs", {}).get("effective_sha256", ""),
        "structure_policy_sha256": result.get("structure_policy", {}).get("effective_sha256", ""),
        "source_files": [
            {
                "book": str(item.get("book", "")),
                "name": Path(str(item.get("source", ""))).name,
                "sha256": str(item.get("source_sha256", "")),
            }
            for item in result.get("files", [])
        ],
        "language_contracts": evidence_contracts,
        "language_profile_bindings": profile.language_profile_bindings,
        **(
            {
                "reference_project_id": reference_project_id,
                "reference_resource_sha256": reference_result.get("resource_sha256", ""),
                "reference_compiled_files_sha256": reference_result.get("compiled_files_sha256", ""),
            }
            if reference_result is not None
            else {}
        ),
    }
    rtc_packages: tuple[dict[str, Any], ...] = ()
    if rtc_sizing is not None:
        units, rtc_packages, effective_policy = plan_rtc_work_units(
            selected,
            policy,
            rtc_sizing,
            unit_prefix=plan_id,
            shared=shared,
            wip_context_pool=all_records,
            reference_records=reference_records,
            wip_equivalence_spans=vrs_source_equivalence_spans(
                dict(result.get("effective_vrs") or {}),
                requested_book=scope.book,
            ),
            reference_equivalence_spans=vrs_source_equivalence_spans(
                dict((reference_result or {}).get("effective_vrs") or {}),
                requested_book=scope.book,
            ),
        )
    else:
        units = plan_work_units(
            selected,
            policy,
            unit_prefix=plan_id,
            shared=shared,
            context_pool=all_records,
        )
    document = manifest(
        units,
        effective_policy,
        operator_scope=scope.label(),
        project_id=project_id,
        plan_id=plan_id,
        plan_fingerprint=plan_fingerprint,
        workflow_id=profile.workflow_id,
        operation=operation,
        shared_hashes=shared_hashes,
    )
    if rtc_sizing is not None:
        document.update({
            "schema_version": "1.4",
            "reference_project_id": reference_project_id,
            "rtc_sizing": rtc_sizing.to_dict(),
            "rtc_planner": {
                "version": RTC_PLANNER_VERSION,
                "handoff_contract_version": RTC_HANDOFF_CONTRACT_VERSION,
                "prompt_schema_projection_version": RTC_PROMPT_SCHEMA_PROJECTION_VERSION,
                "slicing_stream": "WIP",
                "boundary_streams": ["WIP", "REFERENCE"],
                "reference_correlation": "EXACT_WIP_SCRIPTURE_RANGE",
            },
        })
        for unit_document, package in zip(document["units"], rtc_packages, strict=True):
            unit_document["rtc_package"] = package
        document["summary"].update(package_summary(rtc_packages))
    output = _workflow_output_path(
        args.output,
        workflow.output_root,
        f"{plan_id}.manifest.json",
    )
    if workflow.publication_root is not None:
        try:
            output.relative_to(workflow.publication_root.resolve())
        except ValueError:
            pass
        else:
            raise ValidationError(
                "Planning artifacts may not be written inside the immutable publication root"
            )
    packet_root: Path | None = None
    identity_lock = workflow.lock_root / f"plan-{plan_id}.lock"
    output_lock_id = sha256_bytes(str(output).encode("utf-8"))[:16]
    output_lock = workflow.lock_root / f"plan-output-{output_lock_id}.lock"
    operation_name = f"{profile.workflow_id.upper()}_{operation.upper()}_PLAN_WRITE"
    with WorkspaceLock(identity_lock, operation_name), WorkspaceLock(
        output_lock,
        operation_name,
    ):
        if args.write_packets:
            packet_root = _workflow_output_path(
                None,
                workflow.output_root,
                f"{plan_id}.packets",
            )
            if packet_root.exists():
                if not packet_root.is_dir():
                    raise ValidationError(
                        f"Evidence packet path is not a directory: {packet_root}"
                    )
                shutil.rmtree(packet_root)
            packet_root.mkdir(parents=True, exist_ok=False)
        for unit, unit_document in zip(units, document["units"], strict=True):
            packet = build_evidence_packet(unit, shared)
            payload = serialize_evidence(packet)
            unit_document["packet_sha256"] = sha256_bytes(payload)
            if packet_root is not None:
                packet_path = packet_root / f"{unit.unit_id}.json"
                atomic_write_json(packet_path, packet)
                unit_document["packet_path"] = str(packet_path)
        atomic_write_json(output, document)
    response = {**document, "manifest_path": str(output)}
    if args.json:
        _print_json(response)
    else:
        summary = document["summary"]
        print("SAGE WORK-UNIT PLAN")
        print(f"Plan: {plan_id}")
        print(f"Workflow: {profile.workflow_id.upper()}")
        print(f"Operation: {operation}")
        print(f"Scope: {scope.label()}")
        print(f"Project: {project_id} ({selected_role})")
        print(f"Work units: {summary['work_units']}")
        print(f"Primary coordinates: {summary['primary_atomic_coordinates']}")
        if rtc_packages:
            for index, (unit, package) in enumerate(
                zip(document["units"], rtc_packages, strict=True), start=1
            ):
                print(menu_item(
                    index,
                    f"{unit['primary_scope']}   "
                    f"WIP ~{package['wip']['estimated_tokens']:,} | "
                    f"REF ~{package['ref']['estimated_tokens']:,} | "
                    f"OH ~{package['oh']['estimated_tokens']:,} | "
                    f"PACK ~{package['pack']['estimated_tokens']:,}"
                ))
            print(
                "Largest work unit: "
                f"WIP ~{summary['largest_wip_estimated_tokens']:,} | "
                f"REF ~{summary['largest_ref_estimated_tokens']:,} | "
                f"OH ~{summary['largest_oh_estimated_tokens']:,} | "
                f"PACK ~{summary['largest_pack_estimated_tokens']:,}"
            )
        else:
            print(f"Largest estimated packet tokens: {summary['largest_estimated_tokens']}")
            print(f"Largest serialized packet bytes: {summary['largest_serialized_bytes']}")
        print(f"Manifest: {operator_path(config.root, output)}")
    return 0


def command_transactions(args: argparse.Namespace) -> int:
    """List incomplete transactions or perform controlled rollback recovery."""
    config, _ = _load(args)
    workflow = config.workflow(args.workflow_id)
    workflow.transaction_root.mkdir(parents=True, exist_ok=True)
    if args.recover:
        transaction_path = (workflow.transaction_root / args.recover).resolve()
        try:
            transaction_path.relative_to(workflow.transaction_root.resolve())
        except ValueError as exc:
            raise ValidationError("Transaction selector escapes the workflow transaction root") from exc
        lock_path = workflow.lock_root / "transaction-recovery.lock"
        with WorkspaceLock(lock_path, "TRANSACTION_RECOVERY"):
            result = recover_transaction(
                transaction_path,
                mode="rollback",
                allowed_roots=(workflow.state_root.parent,),
            )
    else:
        pending = incomplete_transactions(workflow.transaction_root)
        result = {
            "workflow_id": args.workflow_id,
            "pending": [path.name for path in pending],
            "count": len(pending),
        }
    if args.json:
        _print_json(result)
    else:
        if args.recover:
            print("SAGE TRANSACTION RECOVERY")
            print(f"Transaction: {result.get('transaction_id', args.recover)}")
            print(f"State: {result.get('state', 'UNKNOWN')}")
        else:
            print(f"{args.workflow_id.upper()} TRANSACTIONS")
            print(f"Pending: {result['count']}")
            for transaction_id in result["pending"]:
                print(f"- {transaction_id}")
    return 0


def command_generation_list(args: argparse.Namespace) -> int:
    """List committed BIC TARGET generations and verification state."""
    config, _ = _load(args)
    workflow = config.workflow("bic")
    if workflow.publication_root is None:
        raise ValidationError("BIC publication_root is not configured")
    project_root = workflow.publication_root / args.project
    generations: list[dict[str, Any]] = []
    if project_root.exists():
        for path in sorted(item for item in project_root.iterdir() if item.is_dir()):
            if path.name.startswith("."):
                continue
            try:
                manifest_value = verify_generation(path)
                generations.append(
                    {
                        "generation_id": manifest_value.get("generation_id", path.name),
                        "resource_sha256": manifest_value.get("resource_sha256", ""),
                        "created_utc": manifest_value.get("created_utc", ""),
                        "publication_basis": manifest_value.get("publication_basis", ""),
                        "path": str(path),
                        "status": "INTEGRITY_VALIDATED",
                    }
                )
            except SageError as exc:
                generations.append(
                    {
                        "generation_id": path.name,
                        "path": str(path),
                        "status": "BLOCKED",
                        "error": str(exc),
                    }
                )
    result = {"project_id": args.project, "generations": generations}
    if args.json:
        _print_json(result)
    else:
        print(f"SAGE TARGET GENERATIONS — {args.project}")
        for item in generations:
            basis = item.get("publication_basis", "UNKNOWN")
            print(f"{item['generation_id']}: {item['status']} ({basis})")
        if not generations:
            print("None.")
    return 0


def command_generation_publish(args: argparse.Namespace) -> int:
    """Validate and publish the current BIC generated project immutably."""
    config, _ = _load(args)
    workflow = config.workflow("bic")
    profile = load_workflow_profile(config, workflow)
    development_override = bool(args.development_override)
    if profile.qualification_status != "VALIDATED" and not development_override:
        raise ValidationError(
            "BIC TARGET publication is disabled while the BIC workflow qualification is "
            f"{profile.qualification_status}. Use --development-override only for controlled "
            "integration testing; it does not certify INSPECT, REWRITE, or SELF-CHECK."
        )
    publication_basis = (
        "VALIDATED_WORKFLOW"
        if profile.qualification_status == "VALIDATED"
        else "DEVELOPMENT_OVERRIDE"
    )
    project_id = args.project or profile.bindings["GENERATED_TARGET"]
    if project_id != profile.bindings["GENERATED_TARGET"]:
        raise ValidationError(
            f"BIC generated TARGET binding is {profile.bindings['GENERATED_TARGET']}, "
            f"not {project_id}"
        )
    lock_path = workflow.lock_root / "publish-target.lock"
    with WorkspaceLock(lock_path, "BIC_TARGET_PUBLICATION"):
        pending = incomplete_transactions(workflow.transaction_root)
        if pending:
            raise ValidationError(
                "BIC TARGET publication is blocked by incomplete transactions: "
                + ", ".join(path.name for path in pending)
            )
        target_result = compile_project(config, config.project(project_id))
        source_fingerprints: dict[str, str] = {}
        for role, source_project_id in sorted(profile.bindings.items()):
            if role == "GENERATED_TARGET":
                continue
            source_result = compile_project(config, config.project(source_project_id))
            if source_result.get("status") not in {"READY", "READY_WITH_WARNINGS"}:
                raise ValidationError(
                    f"BIC source binding {role}={source_project_id} is not ready: "
                    f"{source_result.get('status')}"
                )
            source_fingerprints[f"{role}:{source_project_id}"] = (
                project_validation_fingerprint(source_result)
            )
        contracts = _grammar_contracts(config, profile)
        grammar_hashes = {
            role: str(contract["profile_sha256"])
            for role, contract in sorted(contracts.items())
        }
        result = publish_generated_target(
            config,
            profile,
            project_id,
            target_result,
            source_fingerprints=source_fingerprints,
            grammar_contracts=grammar_hashes,
            publication_basis=publication_basis,
        )
    if args.json:
        _print_json(result)
    else:
        print("SAGE TARGET GENERATION PUBLICATION")
        print(f"Project: {project_id}")
        print(f"Generation: {result['generation_id']}")
        print(f"Publication basis: {result['publication_basis']}")
        print(f"Reused: {'YES' if result.get('reused') else 'NO'}")
        print(f"Path: {result['path']}")
    return 0


def command_generation_verify(args: argparse.Namespace) -> int:
    """Verify one exact immutable TARGET generation and file inventory."""
    config, _ = _load(args)
    workflow = config.workflow("bic")
    if workflow.publication_root is None:
        raise ValidationError("BIC publication_root is not configured")
    generation = resolve_generation(workflow.publication_root, args.project, args.selector)
    manifest_value = verify_generation(generation)
    result = {**manifest_value, "path": str(generation), "verification": "VALIDATED"}
    if args.json:
        _print_json(result)
    else:
        print("SAGE TARGET GENERATION VERIFICATION")
        print(f"Project: {args.project}")
        print(f"Generation: {result['generation_id']}")
        print(f"Publication basis: {result['publication_basis']}")
        print("Integrity status: VALIDATED")
        print(f"Path: {generation}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    """Check Python, dependencies, package paths, and local workspace access."""
    config, standard = _load(args)
    checks = {
        "python": {
            "version": platform.python_version(),
            "supported": sys.version_info >= (3, 10),
        },
        "pyyaml": {
            "version": getattr(yaml, "__version__", "unknown"),
            "available": True,
        },
        "settings": {
            "path": str(config.settings_path),
            "readable": config.settings_path.is_file(),
        },
        "projects_root": {
            "path": str(config.projects_root),
            "present": config.projects_root.is_dir(),
        },
        "standard": {
            "version": standard.version,
            "status": standard.release_status,
            "public_release_ready": standard.public_release_ready,
        },
    }
    failed = not checks["python"]["supported"] or not checks["settings"]["readable"]
    if args.json:
        _print_json(checks)
    else:
        print("SAGE DOCTOR")
        print(
            f"Python: {checks['python']['version']} "
            f"({'PASS' if checks['python']['supported'] else 'FAIL'})"
        )
        print(f"PyYAML: {checks['pyyaml']['version']} (PASS)")
        print(
            f"Settings: {checks['settings']['path']} "
            f"({'PASS' if checks['settings']['readable'] else 'FAIL'})"
        )
        print(
            f"Projects root: {checks['projects_root']['path']} "
            f"({'PRESENT' if checks['projects_root']['present'] else 'MISSING'})"
        )
    return 2 if failed else 0


def command_shortcut(args: argparse.Namespace) -> int:
    """Route BIC/SAW convenience commands through the canonical guided parser."""
    mapped = SHORTCUT_COMMANDS[args.workflow_id][args.shortcut_command]
    remainder = list(args.arguments or [])
    if remainder and remainder[0] == "--":
        remainder = remainder[1:]
    forwarded: list[str] = ["--settings", str(args.settings)]
    if args.json:
        forwarded.append("--json")
    if args.no_prompt:
        forwarded.append("--no-prompt")
    for attr, flag in (("quiet", "--quiet"), ("verbose", "--verbose"), ("debug", "--debug")):
        if bool(getattr(args, attr, False)):
            forwarded.append(flag)
    forwarded.extend(mapped)
    forwarded.extend(remainder)
    child = parse_args_with_guidance(build_parser(), forwarded)
    _prepare_runtime_inputs(child)
    _print_corrections(child)
    return child.handler(child)


def command_launcher_shortcut(args: argparse.Namespace) -> int:
    """Parse raw Windows launcher arguments without batch SHIFT/%* rewriting, then use the canonical shortcut router."""
    raw = list(args.arguments or [])
    if raw and raw[0] == "--":
        raw = raw[1:]
    settings = str(args.settings)
    json_mode = bool(args.json)
    no_prompt = bool(args.no_prompt)
    log_mode: str | None = None
    while raw:
        token = raw[0]
        if token == "--settings":
            if len(raw) < 2:
                raise ConfigurationError("--settings requires a .yml filename", code="INPUT_REQUIRED")
            settings = raw[1]
            del raw[:2]
            continue
        if token == "--json":
            json_mode = True
            del raw[0]
            continue
        if token == "--no-prompt":
            no_prompt = True
            del raw[0]
            continue
        if token in {"--quiet", "--verbose", "--debug"}:
            log_mode = token[2:]
            del raw[0]
            continue
        break
    command = raw.pop(0) if raw else "status"
    if command.casefold() in {"help", "-h", "--help"}:
        commands = ", ".join(SHORTCUT_COMMANDS[args.workflow_id])
        print(
            f"usage: {args.workflow_id}.cmd [--settings FILE.yml] [--json] [--no-prompt] "
            f"[--quiet|--verbose|--debug] <command> [options]\nCommands: {commands}"
        )
        return 0
    routed = argparse.Namespace(
        workflow_id=args.workflow_id,
        shortcut_command=command,
        arguments=raw,
        settings=settings,
        json=json_mode,
        no_prompt=no_prompt,
        quiet=log_mode == "quiet",
        verbose=log_mode == "verbose",
        debug=log_mode == "debug",
        _guided_interactive=not (json_mode or no_prompt),
        _canonical_argv=[args.workflow_id, command, *raw],
        _input_corrections=[],
    )
    _resolve_shortcut_input(routed)
    return command_shortcut(routed)


def _proposal_suggestions(interpretation: dict[str, Any]) -> list[dict[str, Any]]:
    """Render command proposals in the common INPUT_REQUIRED suggestion grammar."""
    suggestions: list[dict[str, Any]] = []
    for proposal in interpretation.get("command_proposals", [])[:3]:
        suggestions.append(
            {
                "value": proposal.get("canonical_command"),
                "label": proposal.get("title"),
                "score": proposal.get("score", 0.0),
                "confidence": proposal.get("confidence", "LOW"),
            }
        )
    return suggestions


def _request_proposal(interpretation: dict[str, Any], choice: int) -> dict[str, Any] | None:
    """Return one ranked command proposal by its stable command ID."""
    proposals = interpretation.get("command_proposals", [])
    index = choice - 1
    if not isinstance(proposals, list) or index < 0 or index >= len(proposals):
        return None
    proposal = proposals[index]
    return proposal if isinstance(proposal, dict) else None


def _render_request_interpretation(interpretation: dict[str, Any]) -> None:
    """Print one governed natural-language interpretation for an Operator."""
    print("SAGE REQUEST INTERPRETATION")
    print(f"Request: {interpretation.get('original_request', '')}")
    print(f"Result: {interpretation.get('status', 'INTERPRETATION_REQUIRED')}")
    print(interpretation.get("message", ""))
    top = interpretation.get("most_likely_command")
    if isinstance(top, dict):
        print("")
        print("Most likely interpretation:")
        print(f"  Operation: {top.get('title')}")
        if top.get("workflow"):
            print(f"  Workflow: {str(top.get('workflow')).upper()}")
        if top.get("scope"):
            print(f"  Scope: {top.get('scope')}")
        workflow = str(top.get("workflow") or "").lower()
        if top.get("output_project"):
            label = "TARGET" if workflow == "bic" else "WIP" if workflow == "saw" else "Output project"
            print(f"  {label}: {top.get('output_project')}")
        if top.get("contemporary_source"):
            label = "SOURCE" if workflow == "bic" else "REFERENCE" if workflow == "saw" else "Contemporary source"
            print(f"  {label}: {top.get('contemporary_source')}")
        if workflow == "bic" and top.get("lexical_donor"):
            print(f"  DONOR: {top.get('lexical_donor')} (vocabulary only)")
        print(f"  Confidence: {top.get('confidence')}")
        print("")
        print("Canonical command:")
        print(f"  {top.get('canonical_command')}")
        for correction in top.get("corrections", []):
            print(
                "  Proposed correction: "
                f"{correction.get('original')} -> {correction.get('resolved')} "
                f"[{str(correction.get('confidence', '')).lower()} confidence]"
            )
        if top.get("defaults_used"):
            print("  Defaults requiring confirmation: " + ", ".join(top["defaults_used"]))
        if top.get("missing_inputs"):
            print("  Missing inputs: " + ", ".join(top["missing_inputs"]))
    else:
        print("")
        print("No command is safe to recommend for execution.")
    print("")
    print("Choose:")
    for index, label in enumerate(interpretation.get("operator_choices", []), start=1):
        print(menu_item(index, label))


def _show_related_request_operations(interpretation: dict[str, Any]) -> None:
    """Print ranked alternative commands or the general supported-operation set."""
    proposals = interpretation.get("command_proposals", [])
    if isinstance(proposals, list) and proposals:
        print("RELATED REGISTERED COMMANDS")
        for index, proposal in enumerate(proposals, start=1):
            if not isinstance(proposal, dict):
                continue
            print(menu_item(index, f"{proposal.get('title')} [{str(proposal.get('confidence', 'LOW')).lower()} confidence]"))
            print(f"   {proposal.get('canonical_command')}")
        return
    print("RELATED SUPPORTED OPERATIONS")
    for index, item in enumerate(interpretation.get("related_operations", []), start=1):
        print(menu_item(index, str(item.get("label") or "")))


def _explain_request_proposal(proposal: dict[str, Any]) -> None:
    """Explain what one proposed command will do before execution."""
    print("SAGE COMMAND EXPLANATION")
    print(f"Operation: {proposal.get('title')}")
    print(f"Command: {proposal.get('canonical_command')}")
    print(f"Read-only command: {'YES' if proposal.get('read_only') else 'NO'}")
    print(f"Changes SAGE runtime state: {'YES' if proposal.get('state_changing') else 'NO'}")
    print(f"Details: {proposal.get('explanation', '')}")
    if proposal.get("missing_inputs"):
        print("Required before execution: " + ", ".join(proposal["missing_inputs"]))
    print("All normal SAGE parsing, INIT, scope, grammar, review, transaction, and write controls still apply.")


def _execute_request_argv(args: argparse.Namespace, argv: list[str]) -> int:
    """Execute one confirmed canonical command through the authoritative parser."""
    if not argv or argv[0] == "request":
        raise InputRequiredError(
            "A natural-language request cannot recursively execute the request router",
            code="REQUEST_ROUTER_RECURSION_REJECTED",
            received=argv,
            suggestions=[],
            next_action="Choose a registered non-request SAGE command.",
        )
    forwarded: list[str] = ["--settings", str(args.settings)]
    if getattr(args, "json", False):
        forwarded.append("--json")
    if getattr(args, "no_prompt", False):
        forwarded.append("--no-prompt")
    forwarded.extend(argv)
    child = parse_args_with_guidance(build_parser(), forwarded)
    _prepare_runtime_inputs(child)
    _print_corrections(child)
    return child.handler(child)


def _edited_request_argv(value: str) -> list[str]:
    """Parse an Operator-edited command while retaining the SAGE boundary."""
    tokens = split_operator_command(value)
    if tokens and is_sage_launcher_token(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        raise InputRequiredError(
            "Edited command must not be empty",
            code="EMPTY_EDITED_COMMAND",
            received=value,
            suggestions=[],
            next_action="Enter one canonical SAGE command or cancel.",
        )
    if tokens[0] == "request":
        raise InputRequiredError(
            "Edited command must resolve to a registered execution command, not another request",
            code="REQUEST_ROUTER_RECURSION_REJECTED",
            received=value,
            suggestions=[],
            next_action="Choose a registered SAGE command shown by the router.",
        )
    return tokens


def _read_menu_selection(maximum: int) -> int:
    """Read one bounded interactive menu selection."""
    for _ in range(3):
        sys.stdout.write("Selection: ")
        sys.stdout.flush()
        value = sys.stdin.readline()
        if value == "":
            raise OperatorCancelledError("Input stream closed during request routing")
        value = value.strip()
        if value.isdigit() and 1 <= int(value) <= maximum:
            return int(value)
        print(f"Enter one number from 1 to {maximum}.")
    raise InputRequiredError(
        "No valid request-routing choice was selected",
        code="REQUEST_ROUTING_CHOICE_REQUIRED",
        received=None,
        suggestions=[],
        next_action="Rerun the request and choose one listed option.",
    )


def command_request(args: argparse.Namespace) -> int:
    """Interpret natural language, confirm a registered command, or remain advisory-only."""
    config, _ = _load(args)
    request_text = " ".join(args.request_text).strip()
    while True:
        interpretation = interpret_request(request_text, config)
        proposal = _request_proposal(interpretation, int(args.choice))

        if args.advisory:
            log_path = append_request_log(config, interpretation, decision="ADVISORY_ONLY")
            result = {
                **interpretation,
                "decision": "ADVISORY_ONLY",
                "project_execution": False,
                "request_log": str(log_path),
            }
            if args.json:
                _print_json(result)
            else:
                _render_request_interpretation(interpretation)
                print("")
                print("Advisory-only mode selected. No project command was executed.")
            return 0

        if args.execute:
            if proposal is None or not proposal.get("executable"):
                raise InputRequiredError(
                    "No selected command is complete and safe to execute",
                    code="NATURAL_LANGUAGE_COMMAND_SELECTION_REQUIRED",
                    received=request_text,
                    suggestions=_proposal_suggestions(interpretation),
                    next_action="Refine the request or select one complete proposed command.",
                    details={"interpretation": interpretation},
                )
            append_request_log(
                config,
                interpretation,
                decision="EXECUTE_CONFIRMED",
                selected_command=proposal,
            )
            return _execute_request_argv(args, list(proposal["canonical_argv"]))

        if not _interactive(args):
            log_path = append_request_log(config, interpretation, decision="INTERPRETATION_RETURNED")
            result = {**interpretation, "decision": "INTERPRETATION_REQUIRED", "request_log": str(log_path)}
            if args.json:
                _print_json(result)
            else:
                _render_request_interpretation(interpretation)
            return 0

        _render_request_interpretation(interpretation)
        executable = isinstance(proposal, dict) and bool(proposal.get("executable"))
        selection = _read_menu_selection(7 if executable else 4)

        if selection == 1:
            request_text = prompt_for_value(label="Refined request")
            continue

        if executable:
            if selection == 2:
                append_request_log(
                    config,
                    interpretation,
                    decision="EXECUTE_CONFIRMED",
                    selected_command=proposal,
                )
                return _execute_request_argv(args, list(proposal["canonical_argv"]))
            if selection == 3:
                edited = prompt_for_value(label="Canonical SAGE command")
                edited_argv = _edited_request_argv(edited)
                edited_command = render_sage_command(edited_argv)
                if not confirm_correction(
                    str(proposal.get("canonical_command")),
                    edited_command,
                    label="canonical command",
                ):
                    continue
                edited_proposal = {
                    "command_id": "operator-edited",
                    "canonical_command": edited_command,
                    "confidence": "OPERATOR_CONFIRMED",
                }
                append_request_log(
                    config,
                    interpretation,
                    decision="EDITED_COMMAND_CONFIRMED",
                    selected_command=edited_proposal,
                )
                return _execute_request_argv(args, edited_argv)
            if selection == 4:
                _explain_request_proposal(proposal)
                continue
            if selection == 5:
                _show_related_request_operations(interpretation)
                continue
            if selection == 6:
                append_request_log(config, interpretation, decision="ADVISORY_ONLY")
                print("Advisory-only mode selected. No project command was executed.")
                return 0
            append_request_log(config, interpretation, decision="CANCELLED")
            raise OperatorCancelledError("Operator cancelled natural-language request routing")

        if selection == 2:
            _show_related_request_operations(interpretation)
            continue
        if selection == 3:
            append_request_log(config, interpretation, decision="ADVISORY_ONLY")
            print("Advisory-only mode selected. No project command was executed.")
            return 0
        append_request_log(config, interpretation, decision="CANCELLED")
        raise OperatorCancelledError("Operator cancelled natural-language request routing")

def _transaction_list(args: argparse.Namespace) -> int:
    """List incomplete transactions without changing workflow state."""
    args.recover = None
    return command_transactions(args)


def _transaction_recover(args: argparse.Namespace) -> int:
    """Run controlled transaction recovery for the explicitly selected transaction ID."""
    args.recover = args.transaction_id
    return command_transactions(args)


def _add_task_create_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the shared canonical arguments for immutable ACT task creation."""
    parser.add_argument("--workflow", dest="workflow_id", choices=("bic", "saw"), required=True)
    parser.add_argument(
        "--operation",
        choices=("inspect", CANONICAL_TARGET_TEXT_OPERATION, "self_check", "rtc", "focused", "ol"),
        required=True,
        help="Operation permitted by the selected workflow",
    )
    parser.add_argument(
        "--output-project", "--target", "--wip",
        dest="output_project",
        required=True,
        help="BIC TARGET write destination or SAW WIP translation",
    )
    parser.add_argument(
        "--contemporary-source", "--source", "--reference",
        dest="contemporary_source",
        required=True,
        help="BIC SOURCE content authority or SAW authorized REFERENCE",
    )
    parser.add_argument(
        "--lexical-donor", "--donor",
        dest="lexical_donor",
        help="BIC DONOR project; vocabulary evidence only. Defaults to the active BIC workflow binding.",
    )
    parser.add_argument("--scope", required=True, help='One bounded Scripture scope, for example "PHP 1:1-11"')
    parser.add_argument("--focus", help="One bounded question; required for SAW focused and ol operations")
    parser.add_argument(
        "--type",
        dest="check_type",
        choices=tuple(sorted(SAW_CHECK_TYPES)),
        help="Optional SAW Targeted Check type; defaults to CUSTOM_BOUNDED_CHECK",
    )
    parser.add_argument(
        "--predecessor-task",
        help="Validated BIC REWRITE task-manifest.json; SELF-CHECK verifies the sealed completed candidate",
    )
    parser.add_argument(
        "--grammar-override-id",
        help="Optional governed decision ID documenting provisional grammar-profile use",
    )
    parser.add_argument(
        "--job-id",
        dest="job_id",
        help="Persistent BIC/SAW Job identity owning this task",
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        help="Persistent operational Run identity owning this task",
    )


def _add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the shared planning arguments used by BIC and SAW convenience commands."""
    parser.add_argument("--workflow", dest="workflow_id", choices=("bic", "saw"), required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--project")
    parser.add_argument(
        "--output",
        help="Manifest path relative to, or contained within, the workflow output root",
    )
    parser.add_argument("--write-packets", action="store_true")


def build_parser(*, include_internal: bool = False) -> GuidedArgumentParser:
    """Build the public SAGE command grammar."""
    # Keep parser construction declarative; registered handlers remain the sole execution authority.
    parser = GuidedArgumentParser(
        prog="sage",
        description="SAGE Scripture Analysis and Generation Engine",
        epilog=(
            "Canonical pattern: sage <domain> <action>. "
            "Convenience commands: sage status, sage setup. "
            "Run 'sage <domain> --help' for domain-specific guidance."
        ),
    )
    parser.add_argument("--settings", default="ecosystem.yml", help="Settings file, including its .yml extension")
    parser.add_argument("--data-home", help="Override localdata for this invocation (also available as SAGE_DATA_HOME)")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Disable guided correction and return structured INPUT_REQUIRED results",
    )
    log_mode = parser.add_mutually_exclusive_group()
    log_mode.add_argument("--quiet", action="store_true", help="Show only errors and critical events")
    log_mode.add_argument("--verbose", action="store_true", help="Show detailed operational events")
    log_mode.add_argument("--debug", action="store_true", help="Show diagnostic operational events")
    subparsers = parser.add_subparsers(dest="command", required=True)

    overview = subparsers.add_parser(
        "status",
        help="Show a fast local SAGE overview; use --live for provider probing",
    )
    overview.add_argument("--live", action="store_true", help="Probe the selected provider instead of using local/last-known state")
    overview.set_defaults(handler=command_overview)

    setup = subparsers.add_parser(
        "setup",
        help="Run the short first-use setup and return to the shell",
    )
    setup.add_argument("--script", help="Read deterministic setup responses from one text file")
    setup.set_defaults(handler=command_setup)

    data_home = subparsers.add_parser("data-home", help="Show or configure the persistent localdata location")
    data_home_actions = data_home.add_subparsers(dest="data_home_command", required=True)
    data_home_show = data_home_actions.add_parser("show", help="Show the effective localdata location")
    data_home_show.set_defaults(handler=command_data_home_show)
    data_home_set = data_home_actions.add_parser("set", help="Persist a custom localdata location without moving data")
    data_home_set.add_argument("path")
    data_home_set.set_defaults(handler=command_data_home_set)
    data_home_reset = data_home_actions.add_parser("reset", help="Return to the sibling localdata default without deleting data")
    data_home_reset.set_defaults(handler=command_data_home_reset)

    menu = subparsers.add_parser(
        "menu",
        help="Open the menu-driven Control Center for Job-scoped BIC and SAW work",
    )
    menu.add_argument("--script", help="Read deterministic menu responses from one text file")
    setup_mode = menu.add_mutually_exclusive_group()
    setup_mode.add_argument("--force-setup", action="store_true", help="Run first-use setup before the menu")
    setup_mode.add_argument("--skip-setup", action="store_true", help="Open the menu without first-use setup")
    menu.add_argument(
        "--dry-run-provider",
        dest="dry_run_provider",
        action="store_true",
        help="Validate and assemble governed provider requests without calling a model",
    )
    menu.set_defaults(handler=command_menu)

    tui = subparsers.add_parser(
        "tui",
        help="Open the EXPERIMENTAL / UNSTABLE 0.01 Beta full-screen interface",
    )
    tui.add_argument(
        "--dry-run-provider",
        dest="dry_run_provider",
        action="store_true",
        help="Use the deterministic test AI status instead of calling a model",
    )
    tui.add_argument(
        "--no-live-ai",
        action="store_true",
        help="Open the TUI without the normal startup workflow-AI probe",
    )
    tui.set_defaults(handler=command_tui)

    for guide_command in ("guide", "help"):
        guide = subparsers.add_parser(
            guide_command,
            help="Show integrated first-use, surface, task, or recovery guidance",
        )
        guide.add_argument(
            "guide_topic",
            nargs="?",
            default="start",
            choices=GUIDE_TOPICS,
            help="Guidance topic; default: start",
        )
        guide.set_defaults(handler=command_guide)

    request = subparsers.add_parser(
        "request",
        help="Map a natural-language request to registered SAGE commands before execution",
    )
    request.add_argument("request_text", nargs="+", help="Natural-language Operator request")
    request.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly execute the selected complete command proposal",
    )
    request.add_argument(
        "--choice",
        type=int,
        default=1,
        help="One-based proposal number used with --execute; default: 1",
    )
    request.add_argument(
        "--advisory",
        action="store_true",
        help="Return advisory routing only and perform no project execution",
    )
    request.set_defaults(handler=command_request)

    workspace = subparsers.add_parser("workspace", help="Review, validate, initialize, and inspect the workspace")
    workspace_actions = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_validate = workspace_actions.add_parser("validate", help="Validate ecosystem configuration or clean source package")
    workspace_validate.add_argument("--package", action="store_true", help="Apply clean-source package rules")
    workspace_validate.set_defaults(handler=command_validate)
    workspace_initialize = workspace_actions.add_parser("initialize", help="Compile resources and write governed readiness state")
    workspace_initialize.add_argument("--break-stale-lock", action="store_true")
    workspace_initialize.set_defaults(handler=command_initialize)
    workspace_status = workspace_actions.add_parser("status", help="Show the last governed workspace state")
    workspace_status.set_defaults(handler=command_status)
    workspace_doctor = workspace_actions.add_parser("doctor", help="Check Python, dependencies, settings, and workspace paths")
    workspace_doctor.set_defaults(handler=command_doctor)
    workspace_reset = workspace_actions.add_parser("reset-state", help="Remove generated runtime state and caches")
    workspace_reset.add_argument("--keep-test-artifacts", action="store_true")
    workspace_reset.set_defaults(handler=command_reset_state)

    project = subparsers.add_parser("project", help="Review or list SAGE Scripture Projects and resources")
    project_actions = project.add_subparsers(dest="project_command", required=True)
    project_init = project_actions.add_parser(
        "init",
        help="Review projects and guide recoverable effective-configuration settings",
    )
    project_init.add_argument("--non-interactive", action="store_true")
    project_init.add_argument(
        "--clear-overrides",
        action="store_true",
        help="Clear the governed INIT override sidecar before reviewing source settings",
    )
    project_init.set_defaults(handler=command_init)
    project_list = project_actions.add_parser("list", help="List SAGE Projects, effective roles, scope, state, and profiles")
    project_list.set_defaults(handler=command_projects)
    project_restart = project_actions.add_parser("restart-scope", help="Restart one BIC analytical scope without changing TARGET Scripture")
    project_restart.add_argument("--job", dest="job", required=True, help="BIC Job ID")
    project_restart.add_argument("--scope", required=True)
    project_restart.set_defaults(handler=command_bic_restart_scope)
    project_history = project_actions.add_parser("target-history", help="List bounded BIC TARGET commit history")
    project_history.add_argument("--job", dest="job", required=True, help="BIC Job ID")
    project_history.add_argument("--scope")
    project_history.set_defaults(handler=command_bic_target_history)
    project_revert = project_actions.add_parser("revert-target-scope", help="Restore the immediately previous committed BIC TARGET content for one exact scope")
    project_revert.add_argument("--job", dest="job", required=True, help="BIC Job ID")
    project_revert.add_argument("--scope", required=True)
    project_revert.set_defaults(handler=command_bic_revert_target_scope)

    model = subparsers.add_parser("model", help="Configure and diagnose SAGE LLM providers and models")
    model_actions = model.add_subparsers(dest="model_command", required=True)
    model_connect = model_actions.add_parser("connect", help="Connect OpenAI through ChatGPT sign-in using the local Codex CLI; desktop app not required")
    model_connect.add_argument("--device-auth", action="store_true", help="Use device-code sign-in instead of the normal browser flow")
    model_connect.set_defaults(handler=command_model_connect)
    model_status = model_actions.add_parser("status", help="Show provider readiness and current model capability state")
    model_status.add_argument("--provider", choices=PROVIDER_IDS)
    model_status.set_defaults(handler=command_model_status)
    model_refresh = model_actions.add_parser("refresh", help="Refresh the live model catalog for the signed-in provider account")
    model_refresh.add_argument("--provider", choices=PROVIDER_IDS, default="codex")
    model_refresh.set_defaults(handler=command_model_refresh)
    model_list = model_actions.add_parser("list", help="List live models, reasoning levels, and SAGE qualification")
    model_list.add_argument("--provider", choices=PROVIDER_IDS, required=True)
    model_list.set_defaults(handler=command_model_list)
    model_recommend = model_actions.add_parser("recommend", help="Recommend a live Codex model/reasoning pair for one SAGE task profile")
    model_recommend.add_argument("--workflow", choices=("bic", "saw"), required=True)
    model_recommend.add_argument("--operation", required=True)
    model_recommend.set_defaults(handler=command_model_recommend)
    model_policy = model_actions.add_parser("policy", help="Show release-governed model qualification and reasoning policy")
    model_policy.set_defaults(handler=command_model_policy)
    model_use = model_actions.add_parser("use", help="Select automatic Codex routing or an explicit provider/model/reasoning level")
    model_use.add_argument("--provider", choices=("codex",), required=True)
    model_use.add_argument("--model", help="Exact provider model ID")
    model_use.add_argument("--reasoning", help="Exact provider-advertised reasoning effort, for example high or xhigh")
    model_use.add_argument("--auto", action="store_true", help="Use SAGE task-aware automatic Codex model/reasoning routing")
    model_use.set_defaults(handler=command_model_use)
    model_provision = model_actions.add_parser("provision", help="Configure governed Ollama settings without enabling workflow execution")
    model_provision.add_argument("--provider", choices=("ollama",), required=True)
    model_provision.add_argument("--model", help="Local model identifier to retain for future activation")
    model_provision.add_argument("--endpoint", help="Validated localhost endpoint")
    model_provision.set_defaults(handler=command_model_provision)
    model_test = model_actions.add_parser("test", help="Run a minimal structured-output connectivity test")
    model_test.add_argument("--provider", choices=PROVIDER_IDS)
    model_test.add_argument("--model")
    model_test.add_argument("--reasoning")
    model_test.add_argument("--timeout", type=int, default=120)
    model_test.set_defaults(handler=command_model_test)

    task = subparsers.add_parser("task", help="Create, execute, or submit one governed SAGE task")
    task_actions = task.add_subparsers(dest="task_command", required=True)
    task_create = task_actions.add_parser("create", help="Create one immutable governed task")
    _add_task_create_arguments(task_create)
    task_create.set_defaults(handler=command_act_create)
    task_execute = task_actions.add_parser("execute", help="Run one immutable task through the selected SAGE LLM provider")
    task_execute.add_argument("--task", required=True, help="task-manifest.json path")
    task_execute.add_argument("--provider", choices=PROVIDER_IDS)
    task_execute.add_argument("--model")
    task_execute.add_argument("--reasoning", help="Operator-selected reasoning effort; validated against the live Codex catalog and SAGE policy")
    task_execute.add_argument("--policy-override", action="store_true", help="Permit an available but unqualified model or supported out-of-profile effort; the XHigh ceiling cannot be bypassed")
    task_execute.add_argument("--timeout", type=int, default=600)
    task_execute.add_argument("--dry-run", action="store_true", help="Validate and assemble the sealed request without calling a model")
    task_execute.set_defaults(handler=command_task_execute)
    task_submit = task_actions.add_parser("submit", help="Validate and finalize one completed ACT task")
    task_submit.add_argument("--task", required=True, help="task-manifest.json path")
    task_submit.set_defaults(handler=command_act_submit)
    task_aggregate = task_actions.add_parser("aggregate", help="Aggregate `FINALIZED` SAW work units")
    task_aggregate.add_argument("--plan", required=True, help="PARTITIONED SAW plan JSON path")
    task_aggregate.set_defaults(handler=command_act_aggregate)
    task_continue = task_actions.add_parser(
        "continue",
        help="Return the next sequential SAW work unit or aggregation action",
    )
    task_continue.add_argument("--plan", required=True, help="PARTITIONED SAW plan JSON path")
    task_continue.set_defaults(handler=command_act_continue)

    memory = subparsers.add_parser("memory", help="Review and govern individual BIC memory records")
    memory_actions = memory.add_subparsers(dest="memory_command", required=True)
    memory_list = memory_actions.add_parser("list", help="List governed BIC memory records")
    memory_list.add_argument("--state", choices=tuple(sorted(MEMORY_STATES)))
    memory_list.add_argument("--source", choices=("INSPECT", "LEXICON_IMPORT"))
    memory_list.set_defaults(handler=command_memory_list)
    memory_review = memory_actions.add_parser("review", help="Record optional review provenance after BIC INSPECT")
    memory_review.add_argument("--scope", required=True)
    memory_review.add_argument("--decision-id", required=True)
    memory_review.add_argument("--reviewer", required=True)
    memory_review.add_argument(
        "--decision",
        required=True,
        choices=("APPROVED_FOR_REWRITE", "RETURN_FOR_REVIEW", "REJECTED"),
    )
    memory_review.add_argument("--notes")
    memory_review.set_defaults(handler=command_memory_review)
    memory_transition = memory_actions.add_parser(
        "transition",
        help="Apply one stale-safe state transition to an individual BIC memory record",
    )
    memory_transition.add_argument("--record-id", required=True)
    memory_transition.add_argument(
        "--from",
        dest="expected_state",
        required=True,
        choices=tuple(sorted(MEMORY_STATES)),
        help="Required current state; prevents stale or accidental transitions",
    )
    memory_transition.add_argument(
        "--to",
        dest="new_state",
        required=True,
        choices=tuple(sorted(MEMORY_STATES)),
    )
    memory_transition.add_argument("--decision-id", required=True)
    memory_transition.add_argument("--operator", required=True)
    memory_transition.add_argument("--notes")
    memory_transition.set_defaults(handler=command_memory_transition)
    memory_import = memory_actions.add_parser(
        "import-lexicon",
        help="Import a governed lexicon document as PROPOSED BIC memory",
    )
    memory_import.add_argument("--file", required=True)
    memory_import.add_argument("--decision-id", required=True)
    memory_import.add_argument("--operator", required=True)
    memory_import.add_argument("--notes")
    memory_import.set_defaults(handler=command_memory_import_lexicon)
    memory_rollback = memory_actions.add_parser(
        "rollback-import",
        help="Deactivate every record from one committed lexicon import",
    )
    memory_rollback.add_argument("--import-id", required=True)
    memory_rollback.add_argument("--decision-id", required=True)
    memory_rollback.add_argument("--operator", required=True)
    memory_rollback.add_argument("--notes")
    memory_rollback.set_defaults(handler=command_memory_rollback_import)

    grammar = subparsers.add_parser("grammar", help="Review configured grammar profiles by exact content hash")
    grammar_actions = grammar.add_subparsers(dest="grammar_command", required=True)
    grammar_list = grammar_actions.add_parser("list", help="List declared and effective grammar-profile status")
    grammar_list.set_defaults(handler=command_grammar_list)
    grammar_review = grammar_actions.add_parser("review", help="Record one exact-hash grammar-profile decision")
    grammar_review.add_argument("--profile", required=True, help="Profile selector such as uk/wip")
    grammar_review.add_argument("--decision-id", required=True)
    grammar_review.add_argument("--operator", required=True)
    grammar_review.add_argument("--decision", choices=tuple(sorted(GRAMMAR_REVIEW_DECISIONS)), required=True)
    grammar_review.add_argument("--notes")
    grammar_review.set_defaults(handler=command_grammar_review)

    register_rwc_parser(subparsers)

    resource = subparsers.add_parser("resource", help="Manage Scripture resources, Paratext/PTLite mappings, and VRS roots")
    resource_actions = resource.add_subparsers(dest="resource_command", required=True)
    resource_list = resource_actions.add_parser("list", help="List Scripture resources and governed external mappings")
    resource_list.set_defaults(handler=command_resource_list)
    resource_map = resource_actions.add_parser("map", help="Map a Scripture resource to an external Paratext/PTLite project folder")
    resource_map.add_argument("--project", required=True, help="SAGE Scripture Project ID")
    resource_map.add_argument("--path", required=True, help="Absolute native project-folder path")
    resource_map.add_argument(
        "--access",
        choices=(READ_ONLY_SCRIPTURE, READ_WRITE_TARGET),
        default=READ_ONLY_SCRIPTURE,
        help="External access policy; writable mode is valid only for a BIC TARGET",
    )
    resource_map.set_defaults(handler=command_resource_map)
    resource_unmap = resource_actions.add_parser("unmap", help="Remove an external Scripture resource mapping")
    resource_unmap.add_argument("--project", required=True, help="SAGE Scripture Project ID")
    resource_unmap.set_defaults(handler=command_resource_unmap)
    resource_vrs_root = resource_actions.add_parser("vrs-root", help="Show, set, or clear the configurable base VRS root")
    resource_vrs_root.add_argument("--path", help="Absolute base VRS directory")
    resource_vrs_root.add_argument("--clear", action="store_true", help="Clear the machine-local base VRS root override")
    resource_vrs_root.set_defaults(handler=command_resource_vrs_root)
    resource_rights = resource_actions.add_parser(
        "validate-rights",
        help="Validate machine-readable provenance and rights metadata",
    )
    resource_rights.add_argument(
        "--metadata-root",
        default="auto",
        help="Metadata directory, its projects subdirectory, or auto-discovery in a handover pack",
    )
    resource_rights.set_defaults(handler=command_resource_validate_rights)

    evaluation = subparsers.add_parser("evaluation", help="Plan isolated sequential evaluation tasks")
    evaluation_actions = evaluation.add_subparsers(dest="evaluation_command", required=True)
    evaluation_plan = evaluation_actions.add_parser("plan", help="Validate and write a sequential multi-project queue")
    evaluation_plan.add_argument("--set", dest="set_id", required=True)
    evaluation_plan.add_argument("--scope", required=True)
    evaluation_plan.add_argument("--operation", choices=("rtc", "focused", "ol"), default="rtc")
    evaluation_plan.add_argument("--focus", help="One bounded question; required for focused and ol queues")
    evaluation_plan.add_argument("--type", dest="check_type", choices=tuple(sorted(SAW_CHECK_TYPES)))
    evaluation_plan.set_defaults(handler=command_evaluation_plan)

    transaction = subparsers.add_parser("transaction", help="List or recover journaled workflow transactions")
    transaction_actions = transaction.add_subparsers(dest="transaction_command", required=True)
    transaction_list = transaction_actions.add_parser("list", help="List incomplete transactions")
    transaction_list.add_argument("--workflow", dest="workflow_id", choices=("bic", "saw"), required=True)
    transaction_list.set_defaults(handler=_transaction_list)
    transaction_recover = transaction_actions.add_parser("recover", help="Rollback one incomplete transaction")
    transaction_recover.add_argument("--workflow", dest="workflow_id", choices=("bic", "saw"), required=True)
    transaction_recover.add_argument("--id", dest="transaction_id", required=True)
    transaction_recover.set_defaults(handler=_transaction_recover)

    generation = subparsers.add_parser("generation", help="Inspect immutable BIC TARGET generations")
    generation_actions = generation.add_subparsers(dest="generation_command", required=True)
    generation_publish = generation_actions.add_parser("publish", help="Validate and publish the current BIC generated TARGET immutably")
    generation_publish.add_argument("--project")
    generation_publish.add_argument(
        "--development-override",
        action="store_true",
        help="Allow infrastructure-only publication and record DEVELOPMENT_OVERRIDE",
    )
    generation_publish.set_defaults(handler=command_generation_publish)
    generation_list = generation_actions.add_parser("list", help="List immutable generations for one BIC-generated project")
    generation_list.add_argument("--project", required=True)
    generation_list.set_defaults(handler=command_generation_list)
    generation_verify = generation_actions.add_parser("verify", help="Verify one exact immutable generation and file inventory")
    generation_verify.add_argument("--project", required=True)
    generation_verify.add_argument("--selector", default="current")
    generation_verify.set_defaults(handler=command_generation_verify)

    maintenance = subparsers.add_parser("maintenance", help="Audit and safely migrate SAGE-owned persistent layout")
    maintenance_actions = maintenance.add_subparsers(dest="maintenance_command", required=True)
    maintenance_jobs = maintenance_actions.add_parser("jobs", help="Audit or migrate persistent Job folders")
    maintenance_job_actions = maintenance_jobs.add_subparsers(dest="maintenance_jobs_command", required=True)
    job_audit = maintenance_job_actions.add_parser("audit-layout", help="Read-only audit of canonical and legacy Job folders")
    job_audit.set_defaults(handler=command_job_layout_audit)
    job_migrate = maintenance_job_actions.add_parser("migrate-layout", help="Dry-run or apply one evidence-preserving legacy Job-layout migration")
    job_migrate.add_argument("--from-audit", required=True, help="Exact JOB-LAYOUT-AUDIT.json receipt")
    job_migrate.add_argument("--apply", action="store_true", help="Apply the reviewed migration; default is dry-run")
    job_migrate.set_defaults(handler=command_job_layout_migrate)
    job_verify = maintenance_job_actions.add_parser("verify-layout", help="Verify canonical Job layout without mutation")
    job_verify.set_defaults(handler=command_job_layout_verify)

    if include_internal:
        shortcut = subparsers.add_parser("shortcut", help="Internal launcher dispatch")
        shortcut.add_argument("--workflow", dest="workflow_id", choices=("bic", "saw"), required=True)
        shortcut.add_argument("shortcut_command")
        shortcut.add_argument("arguments", nargs=argparse.REMAINDER)
        shortcut.set_defaults(handler=command_shortcut)

        launcher_shortcut = subparsers.add_parser("launcher-shortcut", help="Raw Windows launcher dispatch")
        launcher_shortcut.add_argument("--workflow", dest="workflow_id", choices=("bic", "saw"), required=True)
        launcher_shortcut.add_argument("arguments", nargs=argparse.REMAINDER)
        launcher_shortcut.set_defaults(handler=command_launcher_shortcut)

    workflow = subparsers.add_parser("workflow", help="Inspect or plan one independent workflow")
    workflow_actions = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_status = workflow_actions.add_parser("status", help="Show one workflow's qualification and resource state")
    workflow_status.add_argument("--workflow", dest="workflow_id", choices=("bic", "saw"), required=True)
    workflow_status.set_defaults(handler=command_workflow_status)
    workflow_plan = workflow_actions.add_parser("plan", help="Build bounded section-preferred work units without analysis")
    _add_plan_arguments(workflow_plan)
    workflow_plan.set_defaults(handler=command_plan)
    workflow_reset = workflow_actions.add_parser(
        "reset-stage",
        help="Reset generated state for exactly one BIC or SAW stage",
    )
    workflow_reset.add_argument("--workflow", dest="workflow_id", choices=tuple(sorted(STAGES)), required=True)
    workflow_reset.add_argument(
        "--stage",
        choices=("inspect", "rewrite", "self-check", "rtc", "focused", "ol"),
        required=True,
    )
    workflow_reset.add_argument("--decision-id", required=True)
    workflow_reset.add_argument("--operator", required=True)
    workflow_reset.add_argument("--notes")
    workflow_reset.set_defaults(handler=command_workflow_reset_stage)

    return parser


def _operational_log_mode(args: argparse.Namespace) -> str | None:
    """Resolve one command-line log mode without changing configured defaults."""
    if getattr(args, "debug", False):
        return "debug"
    if getattr(args, "verbose", False):
        return "verbose"
    if getattr(args, "quiet", False):
        return "quiet"
    return None


def _operational_logger(args: argparse.Namespace | None, *, error_stream: bool = False) -> OperationalLogger | None:
    """Load the configured logger unless a read-only audit suppresses persistence."""
    if args is not None and getattr(args, "command", None) in {"guide", "help", "menu", "tui", "status"}:
        return None
    if (
        args is not None
        and getattr(args, "command", None) == "workspace"
        and getattr(args, "workspace_command", None) == "reset-state"
    ):
        # Reset-state must remain observably empty after completion; logging it would recreate runtime state.
        return None
    if os.environ.get("SAGE_DISABLE_OPERATIONAL_LOG", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    if args is None or not getattr(args, "settings", None):
        return None
    try:
        config = load_ecosystem(_settings_path(args.settings))
    except SageError:
        return None
    return OperationalLogger(
        root=config.root,
        spec=config.human_output,
        mode=_operational_log_mode(args),
        stream=sys.stderr if error_stream else sys.stdout,
    )


def _configure_console_streams(args: argparse.Namespace) -> None:
    """Localize recognized non-JSON report lines through the configured log/report channel."""
    if getattr(args, "command", None) in {"guide", "help", "menu", "tui"}:
        return
    if getattr(args, "json", False) or os.environ.get("SAGE_DISABLE_HUMAN_CONSOLE") == "1":
        return
    if isinstance(sys.stdout, LocalizedConsoleStream):
        return
    try:
        config = load_ecosystem(_settings_path(args.settings))
    except Exception:
        # Invalid settings still need canonical error output and guided remediation.
        return
    sys.stdout = LocalizedConsoleStream(sys.stdout, spec=config.human_output)
    sys.stderr = LocalizedConsoleStream(sys.stderr, spec=config.human_output)


def _command_context(args: argparse.Namespace) -> dict[str, Any]:
    """Return concise canonical context for one operational log entry."""
    return {
        "command": getattr(args, "command", None),
        "action": (
            getattr(args, "workspace_command", None)
            or getattr(args, "project_command", None)
            or getattr(args, "task_command", None)
            or getattr(args, "memory_command", None)
            or getattr(args, "grammar_command", None)
            or getattr(args, "resource_command", None)
            or getattr(args, "workflow_command", None)
            or getattr(args, "transaction_command", None)
            or getattr(args, "generation_command", None)
            or getattr(args, "evaluation_command", None)
            or getattr(args, "model_command", None)
            or getattr(args, "maintenance_jobs_command", None)
            or getattr(args, "maintenance_command", None)
            or getattr(args, "guide_topic", None)
        ),
    }


def main() -> None:
    """Run the CLI with guided remediation, operational logging, and deterministic exits."""
    args: argparse.Namespace | None = None
    logger: OperationalLogger | None = None
    try:
        _configure_utf8_standard_streams()
        if len(sys.argv) == 1:
            sys.argv.append("menu")
        _preconfigure_prompt_language(sys.argv[1:])
        parser = build_parser(include_internal=any(name in sys.argv[1:] for name in ("shortcut", "launcher-shortcut")))
        args = parse_args_with_guidance(parser)
        if getattr(args, "data_home", None):
            os.environ["SAGE_DATA_HOME"] = str(Path(args.data_home).expanduser())
        _prepare_runtime_inputs(args)
        _configure_console_streams(args)
        logger = _operational_logger(args)
        if logger is not None:
            logger.emit(
                "COMMAND_STARTED",
                severity="INFO",
                context=_command_context(args),
                console=not getattr(args, "json", False),
            )
        _print_corrections(args)
        exit_code = args.handler(args)
        if logger is not None:
            logger.emit(
                "COMMAND_COMPLETED",
                severity="SUCCESS" if exit_code == 0 else "WARNING",
                context={**_command_context(args), "exit_code": exit_code},
                console=not getattr(args, "json", False),
            )
    except SageError as exc:
        json_requested = bool(getattr(args, "json", False)) if args is not None else "--json" in sys.argv[1:]
        payload = exc.to_dict()
        logger = logger or _operational_logger(args, error_stream=True)
        if logger is not None:
            logger.emit(
                "COMMAND_FAILED",
                severity="ERROR",
                context={
                    **(_command_context(args) if args is not None else {}),
                    "reason_code": exc.code,
                    "status": payload.get("status", "ERROR"),
                },
                console=not json_requested,
            )
        if json_requested:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            display_root: Path | None = None
            try:
                settings_value = getattr(args, "settings", "ecosystem.yml") if args is not None else "ecosystem.yml"
                display_root = _app_root_for_settings(_settings_path(settings_value))
            except Exception:
                display_root = None
            display = (
                (lambda value: operator_text(display_root, str(value)))
                if display_root is not None
                else (lambda value: str(value))
            )
            print("SAGE ERROR", file=sys.stderr)
            print(f"Result: {payload.get('status', 'ERROR')}", file=sys.stderr)
            print(f"Reason code: {exc.code}", file=sys.stderr)
            print(f"Message: {display(exc.message)}", file=sys.stderr)
            if exc.affected_scope:
                print(f"Affected scope: {display(exc.affected_scope)}", file=sys.stderr)
            for suggestion in payload.get("suggestions", []):
                value = suggestion.get("value", suggestion)
                label = suggestion.get("label", value)
                print(f"Suggested alternative: {display(value)} ({display(label)})", file=sys.stderr)
            if exc.next_action:
                print(f"Next action: {display(exc.next_action)}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        if logger is not None:
            logger.emit(
                "COMMAND_FAILED",
                severity="WARNING",
                context={**(_command_context(args) if args is not None else {}), "status": "ABANDONED"},
                console=True,
            )
        print("SAGE CANCELLED\nResult: ABANDONED\nState preserved. Interrupted by operator.", file=sys.stderr)
        raise SystemExit(130)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
