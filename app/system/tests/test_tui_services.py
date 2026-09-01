"""Alpha TUI service-boundary regressions that do not require a terminal renderer."""

from __future__ import annotations

import yaml

from sage.storage import storage_layout
from sage.cli import build_parser, command_tui
from sage.jobs import JobStore
from sage.resource_mounts import set_project_root
from sage.runtime_status import RuntimeStatus
from sage.ui_services import OperatorUIService, context_help_lines, probe_workflow_ai


def test_tui_service_main_snapshot_uses_governed_release_and_runtime_ai(make_workspace) -> None:
    """Verify tui service main snapshot uses governed release and runtime ai."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    runtime = RuntimeStatus(interface_language="en-US")
    ai = probe_workflow_ai(root, runtime, refresh=True, dry_run_provider=True)
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml", runtime_status=runtime)

    snapshot = service.main_snapshot()

    assert snapshot["version"] == "0.01beta2"
    assert snapshot["release_status"] == "BETA"
    assert snapshot["feature_classifications"]["tui"] == "EXPERIMENTAL_UNSTABLE"
    assert snapshot["ai"] == ai
    assert snapshot["ai"]["model"] == "dry-run"
    assert snapshot["ai"]["reasoning_level"] == "NOT APPLICABLE"
    assert snapshot["interface_language"] == "en-US"


def test_tui_service_language_change_persists_through_existing_localization(make_workspace) -> None:
    """Verify tui service language change persists through existing localization."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")

    selected = service.set_interface_language("fr")
    refreshed = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")

    assert selected == "fr"
    assert refreshed.localizer.language == "fr"
    assert refreshed.localizer.text("Main Menu") != "Main Menu"


def test_tui_section_snapshots_are_read_only_and_bounded(make_workspace) -> None:
    """Verify tui section snapshots are read only and bounded."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")

    projects = service.section_snapshot("projects")
    bic = service.section_snapshot("bic")
    rtc = service.section_snapshot("rtc")
    stc = service.section_snapshot("stc")
    recovery = service.section_snapshot("recovery")

    assert set(projects) == {"projects_root", "catalog", "registered"}
    assert set(bic) == {"active_job", "jobs", "last_run"}
    assert set(rtc) == {"active_job", "jobs", "last_run"}
    assert set(stc) == {"active_job", "jobs", "last_run"}
    assert recovery["sage_home"] == str(root.resolve())


def test_context_help_is_shared_across_interactive_surfaces() -> None:
    """Verify context help is shared across interactive surfaces."""
    assert any("Quick Scan" in line for line in context_help_lines("SCRIPTURE PROJECTS"))
    assert any("SOURCE" in line for line in context_help_lines("BIC"))
    assert any("WIP" in line for line in context_help_lines("RTC"))
    assert any("does not use" in line for line in context_help_lines("STC"))
    assert any("classic menu" in line for line in context_help_lines("MAIN MENU"))


def test_cli_exposes_tui_without_importing_textual(make_workspace) -> None:
    """Verify cli exposes tui without importing textual."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    args = build_parser().parse_args([
        "--settings",
        str(root / "ecosystem.yml"),
        "tui",
        "--no-live-ai",
    ])

    assert args.command == "tui"
    assert args.handler is command_tui
    assert args.no_live_ai is True
    help_text = build_parser().format_help()
    assert "EXPERIMENTAL / UNSTABLE" in help_text
    assert "0.01beta2" in help_text


def test_startup_readiness_blocks_operational_surfaces_without_projects_root(make_workspace) -> None:
    """Verify shared startup readiness fails closed before workflow surfaces are opened."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    runtime = RuntimeStatus(interface_language="en-US")
    ai = probe_workflow_ai(root, runtime, refresh=True, dry_run_provider=True)
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml", runtime_status=runtime)

    snapshot = service.startup_readiness(ai)

    assert snapshot["status"] == "INCOMPLETE"
    assert snapshot["requires_setup"] is True
    assert snapshot["projects_root_status"] == "NOT_CONFIGURED"
    assert snapshot["next_step"] == "CONFIGURE_PROJECT_ROOT"


def test_invalid_active_job_is_action_needed_without_blocking_main_ui(make_workspace) -> None:
    """A Project-register mismatch stays configured and visible while the main UI remains available."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_project_root(root, project_root=storage_layout(root).projects_root)
    store = JobStore(root, root / "ecosystem.yml")
    saw = next(job for job in store.bootstrap_default_jobs() if job.tool == "saw")
    store.set_active_job("saw", saw.job_id)
    raw = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
    del raw["projects"]["usWIP"]
    del raw["projects"]["usNIVv2"]
    (root / "ecosystem.yml").write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    store.write_setup_state({"scripture_resources": {"status": "READY"}})
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")

    startup = service.startup_readiness({"available": True, "ready": True})
    section = service.section_snapshot("saw")

    assert startup["status"] == "READY"
    assert startup["requires_setup"] is False
    assert startup["next_step"] == "VALIDATE"
    assert startup["workflows"]["saw"] == (
        f"ACTION NEEDED - {saw.job_id} [PROJECT_BINDING_MISMATCH]"
    )
    assert section["active_job"] == saw.job_id
    assert section["jobs"] == [{
        "job_id": saw.job_id,
        "display_name": saw.display_name,
        "active": True,
        "archived": False,
        "action_needed": True,
        "reason_code": "PROJECT_BINDING_MISMATCH",
    }]


def test_project_snapshot_uses_inventory_display_name_and_language_code(make_workspace) -> None:
    """Verify TUI Project rows read the governed inventory schema rather than legacy fields."""
    import json

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    inventory = storage_layout(root).state_root / "project-inventory.json"
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "projects": {
                    "ABC123": {
                        "project_id": "ABC123",
                        "display_name": "Readable Project Name",
                        "language": {"code": "fr", "profile": "fr"},
                        "validation_status": "READY",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")

    rows = service.section_snapshot("projects")["registered"]

    assert rows == [
        {
            "project_id": "ABC123",
            "name": "Readable Project Name",
            "language": "fr",
            "status": "READY",
        }
    ]


def test_tui_service_configures_projects_root_and_quick_scans(make_workspace, tmp_path) -> None:
    """Verify TUI remediation uses the governed Projects-root and lightweight catalog services."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    paratext_root = tmp_path / "Paratext Projects"
    first = paratext_root / "ABC123"
    first.mkdir(parents=True)
    (first / "settings.xml").write_text("<ScriptureText/>", encoding="utf-8")
    service = OperatorUIService(root=root, settings_path=root / "ecosystem.yml")

    configured = service.configure_projects_root(paratext_root)

    assert configured["projects_root"] == str(paratext_root.resolve())
    assert configured["catalog"]["discovered"] == 1
    assert configured["catalog"]["pending"] == 1
    assert service.projects_root_status() == ("READY", paratext_root.resolve())

    second = paratext_root / "XYZ789"
    second.mkdir()
    (second / "settings.xml").write_text("<ScriptureText/>", encoding="utf-8")
    rescanned = service.scan_projects(full=False)

    assert rescanned["projects_root"] == str(paratext_root.resolve())
    assert set(rescanned["projects"]) == {"ABC123", "XYZ789"}
    assert all(row["detail_status"] == "PENDING" for row in rescanned["projects"].values())
