"""Control Center, Job isolation, and provider-neutral menu contracts."""

from __future__ import annotations

import ast
import io
import json
import re
import zipfile
from pathlib import Path

import yaml

from sage.storage import storage_layout
from sage.cli import build_parser
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.registry import load_ecosystem
from sage.runtime_paths import task_container
from sage.jobs import JobStore
from sage.llm_settings import load_llm_settings
from sage.bic_memory import submit_inspect_transactionally
from sage.canon import NT_27
from sage.project_inventory import register_project, registered_project_records
from sage.resource_mounts import load_resource_mounts, set_resource_mount


def _bootstrap(root: Path) -> tuple[JobStore, list]:
    """Bootstrap canonical Jobs from the fixture bindings."""
    store = JobStore(root, root / "ecosystem.yml")
    projects = store.bootstrap_default_jobs()
    return store, projects


def test_menu_is_a_canonical_cli_domain() -> None:
    """Verify CLI registration and the canonical menu-key contract."""
    parser = build_parser()
    args = parser.parse_args(["menu", "--skip-setup", "--dry-run-provider"])
    assert args.command == "menu"
    assert args.skip_setup is True
    assert args.dry_run_provider is True

    source = (Path(__file__).parents[1] / "src" / "sage" / "menu.py").read_text(encoding="utf-8")
    assert re.search(r"\(\s*['\"]0['\"]\s*,", source) is None
    assert "reserved footer controls are A-F" in source
    assert '("1", "Configure AI")' in source
    assert '("2", "Configure languages")' in source

    tree = ast.parse(source)
    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "choose"
            and len(call.args) > 1
            and isinstance(call.args[1], (ast.Tuple, ast.List))
        ):
            continue
        keys = [
            item.elts[0].value
            for item in call.args[1].elts
            if isinstance(item, (ast.Tuple, ast.List))
            and item.elts
            and isinstance(item.elts[0], ast.Constant)
            and isinstance(item.elts[0].value, str)
        ]
        labels = [
            item.elts[1].value
            for item in call.args[1].elts
            if isinstance(item, (ast.Tuple, ast.List))
            and len(item.elts) > 1
            and isinstance(item.elts[1], ast.Constant)
            and isinstance(item.elts[1].value, str)
        ]
        normalized_labels = [
            label.replace(" (BIC)", "").replace(" (RTC)", "").replace(" (STC)", "")
            for label in labels
        ]
        assert all("(" not in label and ")" not in label for label in normalized_labels)
        numbers = [int(key) for key in keys if key.isdecimal()]
        if numbers:
            assert numbers == list(range(1, max(numbers) + 1))


def test_scripture_projects_menu_exposes_projects_root_and_scan_separately(make_workspace) -> None:
    """Show the required Paratext root status and its maintenance action on the main Project menu."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.resource_menu()

    rendered = output.getvalue()
    assert "Paratext Projects root: NOT CONFIGURED" in rendered
    assert "3. Remove PROJECT from SAGE" in rendered
    assert "6. Paratext PROJECTS root" in rendered
    assert "7. Scan Paratext PROJECTS" in rendered


def test_direct_remove_project_action_preserves_paratext_files(make_workspace) -> None:
    """Remove SAGE inventory/mapping state from the visible Project menu without deleting Scripture."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project_id = "usFREEv1"
    project_path = storage_layout(root).projects_root / project_id
    project_path.mkdir()
    scripture = project_path / "41MAT.SFM"
    scripture.write_text("\\id MAT\n\\c 1\n\\v 1 Test.\n", encoding="utf-8")
    register_project(
        root,
        project_id=project_id,
        project_path=project_path,
        language_code="en",
        base_vrs_file="eng.vrs",
        display_name="Disposable Project",
    )
    set_resource_mount(root, project_id=project_id, external_path=project_path)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["3", "1", "yes", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.resource_menu()

    assert project_id not in registered_project_records(root)
    assert project_id not in load_resource_mounts(root)
    assert scripture.read_text(encoding="utf-8").startswith("\\id MAT")
    rendered = output.getvalue()
    assert "This removes the selected PROJECT inventory and mapping from SAGE." in rendered
    assert "Bound SAGE JOBS are listed and require explicit confirmation before removal." in rendered
    assert "Paratext Project folders and Scripture files are never deleted or modified." in rendered
    assert f"Removed {project_id} from SAGE. Paratext files were unchanged." in rendered


def test_direct_remove_project_action_can_remove_job_bound_project(make_workspace) -> None:
    """A bound Project can remove its dependent Jobs only after explicit confirmation."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project_id = "usWIP"
    project_path = storage_layout(root).projects_root / project_id
    register_project(
        root,
        project_id=project_id,
        project_path=project_path,
        language_code="en",
        profile_variant="bol-target",
        base_vrs_file="eng.vrs",
        display_name="Bound WIP",
    )
    set_resource_mount(root, project_id=project_id, external_path=project_path)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["3", "1", "yes", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.store.bootstrap_default_jobs()

    center.resource_menu()

    assert project_id not in registered_project_records(root)
    assert project_id not in load_resource_mounts(root)
    assert not any(project_id in job.bindings.values() for job in center.store.discover(include_archived=True))
    assert project_path.is_dir()
    rendered = output.getvalue()
    assert "Jobs currently using this Project:" in rendered
    assert "RTC/STC WIP" in rendered
    assert "Removing this PROJECT also removes the listed SAGE JOBS and their JOB-local data." in rendered
    assert f"Removed {project_id} from SAGE." in rendered


def test_bound_project_removal_can_be_cancelled_without_changes(make_workspace) -> None:
    """Declining cascade removal preserves the Project, mount, and bound Jobs."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project_id = "usWIP"
    project_path = storage_layout(root).projects_root / project_id
    register_project(
        root,
        project_id=project_id,
        project_path=project_path,
        language_code="en",
        profile_variant="bol-target",
        base_vrs_file="eng.vrs",
        display_name="Bound WIP",
    )
    set_resource_mount(root, project_id=project_id, external_path=project_path)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["3", "1", "no", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.store.bootstrap_default_jobs()

    center.resource_menu()

    assert project_id in registered_project_records(root)
    assert project_id in load_resource_mounts(root)
    assert any(project_id in job.bindings.values() for job in center.store.discover(include_archived=True))


def test_project_actions_expose_separate_refresh_and_validation(make_workspace, monkeypatch) -> None:
    """Refresh rescans Project facts while validation remains a separate action."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    register_project(
        root,
        project_id="usWIP",
        project_path=storage_layout(root).projects_root / "usWIP",
        language_code="en",
        base_vrs_file="eng.vrs",
    )
    events: list[str] = []
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["5", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    record = registered_project_records(root)["usWIP"]
    monkeypatch.setattr(
        center,
        "_refresh_registered_from_catalog",
        lambda project_id: events.append("refresh") or record,
    )
    monkeypatch.setattr(
        center,
        "_setup_scripture_resource_status",
        lambda **kwargs: events.append("validate") or {},
    )

    center.registered_project_detail("usWIP")

    assert events == ["refresh"]
    rendered = output.getvalue()
    assert "5. Refresh PROJECT" in rendered
    assert "6. Validate PROJECT" in rendered
    assert "9. Remove PROJECT from SAGE" in rendered


def test_bic_and_saw_active_jobs_are_independent(make_workspace) -> None:
    """Verify test bic and saw active Jobs are independent for the current Job-menu contract."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    bic = next(project for project in projects if project.tool == "bic")
    saw = next(project for project in projects if project.tool == "saw")

    store.set_active_job("bic", bic.job_id)
    store.set_active_job("saw", saw.job_id)
    before = store.active_jobs()
    store.set_active_job("bic", None)
    after = store.active_jobs()

    assert before == {"bic": bic.job_id, "rtc": None, "stc": None, "saw": saw.job_id}
    assert after == {"bic": None, "rtc": None, "stc": None, "saw": saw.job_id}


def test_runtime_roots_are_job_scoped(make_workspace) -> None:
    """Verify test runtime roots are Job scoped for the current Job-menu contract."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    bic = next(project for project in projects if project.tool == "bic")
    saw = next(project for project in projects if project.tool == "saw")
    bic_config = load_ecosystem(store.write_runtime_files(bic))
    saw_config = load_ecosystem(store.write_runtime_files(saw))

    bic_workflow = bic_config.workflow("bic")
    saw_workflow = saw_config.workflow("saw")
    assert bic_workflow.output_root == bic.root
    assert bic_workflow.memory_root == bic.root / "memory"
    assert bic_workflow.publication_root == bic.root / "generations"
    assert saw_workflow.output_root == saw.root
    assert not hasattr(saw_workflow, "pin_root")
    assert bic.root != saw.root


def test_runs_and_tasks_remain_inside_their_own_job(make_workspace) -> None:
    """Verify test Runs and tasks remain inside their own Job for the current Job-menu contract."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    bic = next(project for project in projects if project.tool == "bic")
    saw = next(project for project in projects if project.tool == "saw")
    bic_run = store.create_run(bic, operation="bic", scope="MAT 1:1-2")
    saw_run = store.create_run(saw, operation="rtc", scope="MAT 1:1-2")

    bic_config = load_ecosystem(bic.runtime_settings_path)
    saw_config = load_ecosystem(saw.runtime_settings_path)
    assert task_container(bic_config.workflow("bic"), bic_run.run_id) == bic_run.root / "tasks"
    assert task_container(saw_config.workflow("saw"), saw_run.run_id) == saw_run.root / "tasks"
    assert bic_run.root.is_relative_to(bic.root)
    assert saw_run.root.is_relative_to(saw.root)
    assert not bic_run.root.is_relative_to(saw.root)


def test_scripted_control_center_can_open_and_exit(make_workspace) -> None:
    """Verify test scripted control center can open and exit for the current Job-menu contract."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _bootstrap(root)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["c"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    assert center.run() == 0
    rendered = output.getvalue()
    assert "SAGE v0.01beta2" in rendered
    assert "BETA - PRE-RELEASE" in rendered
    assert "BIC" in rendered
    assert "Reference Text Comparison (RTC)" in rendered
    assert "Source Text Correspondence (STC)" in rendered
    assert "\n  3. SAW\n" not in rendered
    assert "SAGE Maintenance" in rendered


def test_operator_and_job_language_menus_persist_separate_ownership(make_workspace) -> None:
    """The menus store the new-Job default and Job languages in their proper manifests."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    global_center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", "id", "", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    global_center.operator_language_menu()
    config = load_ecosystem(root / "ecosystem.yml")
    assert config.human_output.operator_language == "id"
    assert config.human_output.logs_and_reports.primary_language == "OPERATOR_LANGUAGE"
    assert config.human_output.logs_and_reports.secondary_language is None

    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Menu language ownership",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    job_center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", "2", "uk", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    job_center._job_settings_menu(job)
    updated = store.load_job(job.job_id, tool="saw")
    assert updated.secondary_report_language == "uk"
    assert "WIP language: en [RECOMMENDED]" in output.getvalue()
    assert "Use WIP language [Recommended]" in output.getvalue()
    assert load_ecosystem(updated.runtime_settings_path).human_output.logs_and_reports.primary_language == "id"
    assert load_ecosystem(updated.runtime_settings_path).human_output.logs_and_reports.secondary_language == "uk"


def test_operator_language_menu_hides_pilot_only_until_manual_promotion(make_workspace) -> None:
    """Normal selection rejects a pilot tag that an advanced Operator has not promoted."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", "sw", "", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.operator_language_menu()

    rendered = output.getvalue()
    assert "OPERATOR_LANGUAGE_NOT_CANDIDATE" in rendered
    assert "add the canonical tag" in rendered
    assert load_ecosystem(root / "ecosystem.yml").human_output.operator_language == "en"



def test_guided_first_run_setup_records_missing_project_root_with_ready_test_ai(make_workspace) -> None:
    """A ready test provider may enter Main while unrelated setup remains incomplete."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["7", "c"]),
            output=output,
        ),
        dry_run_provider=True,
    )

    assert center.run() == 0
    receipt = json.loads((storage_layout(root).state_root / "setup-state.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["next_step"] == "CONFIGURE_PROJECT_ROOT"
    assert receipt["enabled_tools"] == []
    assert receipt["active_jobs"]["bic"] is None
    assert receipt["active_jobs"]["saw"] is None
    assert receipt["scripture_resources"]["status"] == "READY_EMPTY"
    rendered = output.getvalue()
    assert "SAGE STARTUP" in rendered
    assert "SCRIPTURE RESOURCE CHECK" in rendered
    assert "Project inventory is empty. Add a Paratext Project to SAGE when required." in rendered
    assert "Status:              No SAGE Projects added yet" in rendered
    assert "AI connection            READY" in rendered
    assert "Model                    dry-run" in rendered
    assert "Reasoning level          NOT APPLICABLE" in rendered
    assert "BIC:       NOT CONFIGURED" in rendered
    assert "RTC:       NOT CONFIGURED" in rendered
    assert "STC:       NOT CONFIGURED" in rendered
    assert "MANAGE JOBS" in rendered
    assert "4. Manage active JOBS" in rendered
    assert "Setup options" not in rendered
    assert "SAGE Maintenance" in rendered
    assert "B. Main menu   C. Exit SAGE" in rendered
    assert "D. Language   E. Help   F. Status" in rendered
    assert "SAGE v0.01beta2" in rendered
    assert "BETA - PRE-RELEASE" in rendered


def test_global_footer_is_rendered_for_main_bic_and_saw(make_workspace) -> None:
    """The common horizontal navigation footer is present across workflow menus."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.bic_menu()
    center.saw_menu()

    rendered = output.getvalue()
    assert "BIC JOBS" in rendered
    assert "LEGACY ANALYSIS" in rendered
    assert rendered.count("A. Back   B. Main menu   C. Exit SAGE") == 2
    assert rendered.count("D. Language   E. Help   F. Status") == 2


def test_active_job_marker_is_rendered_once_in_management_list(make_workspace) -> None:
    """Mark the selected Job once without repeating its lifecycle status."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")
    store.set_active_job("saw", saw.job_id)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.job_management_menu("saw")

    rendered = output.getvalue()
    assert f"{saw.job_id} - {saw.display_name} [ACTIVE]" in rendered
    assert "[ACTIVE] [ACTIVE]" not in rendered


def test_job_management_can_open_the_active_saw_job(make_workspace) -> None:
    """Changing the active marker must lead to an explicit operational entry action."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")
    store.set_active_job("saw", None)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["2", "1", "1", "a", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.job_management_menu("saw")

    rendered = output.getvalue()
    assert "Open active LEGACY ANALYSIS JOB" in rendered
    assert f"{saw.job_id} - {saw.display_name} [ACTIVE]" in rendered
    assert f"LEGACY ANALYSIS JOB - {saw.job_id}" in rendered
    assert "Run Reference Text Comparison (RTC)" in rendered


def test_job_management_uses_the_same_open_active_grammar_for_bic(make_workspace) -> None:
    """BIC management must expose the same choose-then-open navigation contract."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    bic = next(project for project in projects if project.tool == "bic")
    store.set_active_job("bic", bic.job_id)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", "a", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.job_management_menu("bic")

    rendered = output.getvalue()
    assert "Open active BIC JOB" in rendered
    assert f"{bic.job_id} - {bic.display_name} [ACTIVE]" in rendered
    assert f"BIC JOB - {bic.job_id}" in rendered
    assert "Run BIC check" in rendered


def test_open_job_reports_missing_projects_and_offers_guided_onboarding(make_workspace) -> None:
    """Opening an invalid active Job reports corrective action without aborting Job management."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")
    store.set_active_job("saw", saw.job_id)
    raw = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
    del raw["projects"]["usWIP"]
    del raw["projects"]["usNIVv2"]
    (root / "ecosystem.yml").write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    prompts: list[str] = []
    responses = iter(("1", "no", "a"))

    def respond(prompt: str) -> str:
        """Record each prompt while supplying the bounded operator responses."""
        prompts.append(prompt)
        return next(responses)

    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=respond, output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.job_management_menu("saw")

    rendered = output.getvalue()
    assert f"{saw.job_id} - {saw.display_name} [ACTIVE, ACTION NEEDED]" in rendered
    assert "JOB ACTION NEEDED" in rendered
    assert "Reason code: PROJECT_BINDING_MISMATCH" in rendered
    assert "Missing onboarded Projects:" in rendered
    assert "- WIP: usWIP" in rendered
    assert "- REFERENCE: usNIVv2" in rendered
    assert "Job and Project data were not changed." in rendered
    assert "SAGE ERROR" not in rendered
    assert any("Open Add Projects to SAGE now?" in prompt for prompt in prompts)
    assert store.active_jobs()["saw"] == saw.job_id


def test_open_job_reports_same_project_role_conflict_before_rtc(make_workspace) -> None:
    """Keep a legacy SAW self-comparison visible but prevent it from reaching runtime validation."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    default = next(project for project in projects if project.tool == "saw")
    raw = yaml.safe_load(default.manifest_path.read_text(encoding="utf-8"))
    job_id = "SAW_usNIRVv2-usNIRVv2"
    raw["job_id"] = job_id
    raw["display_name"] = "usNIRVv2 analyzed against usNIRVv2"
    raw["bindings"]["wip"] = "usNIRVv2"
    raw["bindings"]["reference"] = "usNIRVv2"
    manifest = store.job_root("saw", job_id) / "job.yml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    store.active_jobs_path.write_text(
        json.dumps({"schema_version": "1.0", "bic": None, "saw": job_id}),
        encoding="utf-8",
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(("1", "a", "a")), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.job_management_menu("saw")

    rendered = output.getvalue()
    assert job_id in rendered
    assert "[ACTIVE, ACTION NEEDED]" in rendered
    assert "Reason code: PROJECT_BINDING_ROLE_CONFLICT" in rendered
    assert "WIP and REFERENCE both bind usNIRVv2" in rendered
    assert "different SAGE Projects" in rendered
    assert "SAW JOB - SAW_usNIVv2-usNIVv2" not in rendered
    assert "SAGE ERROR" not in rendered


def test_bic_and_saw_entry_menus_preserve_invalid_active_job_as_action_needed(make_workspace) -> None:
    """Workflow entry must check the raw active pointer instead of disguising it as no active Job."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    for job in projects:
        store.set_active_job(job.tool, job.job_id)
    raw = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
    for project_id in ("idKKHv0", "usNIVv2", "usBOLx1", "usWIP"):
        del raw["projects"][project_id]
    (root / "ecosystem.yml").write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    for tool in ("bic", "saw"):
        job = next(project for project in projects if project.tool == tool)
        output = io.StringIO()
        center = SageControlCenter(
            sage_root=root,
            settings_path=root / "ecosystem.yml",
            io=MenuIO(input_func=ScriptedInput(("1", "no", "a")), output=output),
            skip_setup=True,
            dry_run_provider=True,
        )

        (center.bic_menu if tool == "bic" else center.saw_menu)()

        rendered = output.getvalue()
        assert job.job_id in rendered
        assert "ACTION NEEDED" in rendered
        assert "JOB ACTION NEEDED" in rendered
        assert "SAGE ERROR" not in rendered


def test_home_and_exit_footer_keys_unwind_nested_workflow_menu(make_workspace) -> None:
    """Home returns from BIC to Main and Exit terminates SAGE from Main."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["2", "b", "c"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    assert center.run() == 0

    rendered = output.getvalue()
    assert "BIC JOBS" in rendered
    assert rendered.count("║ Main menu") == 2
    assert rendered.count("B. Main menu   C. Exit SAGE") >= 3
    assert rendered.count("D. Language   E. Help   F. Status") >= 3



def test_direct_setup_returns_without_opening_control_center(make_workspace, capsys, monkeypatch) -> None:
    """Verify the direct setup surface performs setup only and returns to its caller."""
    from sage.menu import run_setup

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SAGE_CODEX_COMMAND", raising=False)
    script = root / "setup-input.txt"
    script.write_text("n\nc\n", encoding="utf-8")
    assert run_setup(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        script_path=script,
    ) == 0
    receipt = json.loads((storage_layout(root).state_root / "setup-state.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["next_step"] == "INSTALL_CODEX"

def test_closed_menu_input_is_a_governed_cancellation() -> None:
    """Verify terminal EOF is converted to OperatorCancelledError rather than leaking a traceback."""
    from sage.errors import OperatorCancelledError

    io_surface = MenuIO(input_func=ScriptedInput([]), output=io.StringIO())
    try:
        io_surface.read("Choose: ")
    except OperatorCancelledError as exc:
        assert exc.code == "OPERATOR_CANCELLED"
        assert "Interactive input closed" in exc.message
    else:
        raise AssertionError("Expected OperatorCancelledError")

def test_job_and_run_exports_are_isolated_and_deterministic(make_workspace) -> None:
    """Verify test Job and Run exports are isolated and deterministic for the current Job-menu contract."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    project = next(item for item in projects if item.tool == "bic")
    run = store.create_run(project, operation="bic", scope="MAT 1:1-2")
    (run.root / "diagnostics" / "summary.md").write_text("# Summary\n", encoding="utf-8")

    project_export = store.export_job(project)
    first = project_export.read_bytes()
    project_export = store.export_job(project)
    assert project_export.read_bytes() == first
    with zipfile.ZipFile(project_export) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("EXPORT-MANIFEST.json"))
    assert manifest["job_id"] == project.job_id
    assert "job.yml" in names
    assert f"runs/{run.run_id}/run.json" in names
    assert not any(name.startswith(".sage/cache/") for name in names)
    assert not any(name.startswith(".sage/workspace_data/") for name in names)

    run_export = store.export_run(project, run)
    with zipfile.ZipFile(run_export) as archive:
        manifest = json.loads(archive.read("EXPORT-MANIFEST.json"))
        names = set(archive.namelist())
    assert manifest["run_id"] == run.run_id
    assert "run.json" in names
    assert "diagnostics/summary.md" in names


def test_bic_memory_records_include_job_identity(make_workspace) -> None:
    """Verify test BIC memory records include Job identity for the current Job-menu contract."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    project = next(item for item in projects if item.tool == "bic")
    document = {
        "schema_version": "1.0",
        "operation_id": "OP-1",
        "scope": "MAT 1:1-2",
        "resource_fingerprints": {"content": "a" * 64},
        "proposals": [
            {
                "submitted_id": "P1",
                "record_type": "LEXICAL_ENTRY",
                "payload": {"lemma": "demo"},
                "evidence_refs": ["MAT 1:1"],
            }
        ],
        "challenges": [],
    }
    result = submit_inspect_transactionally(
        document,
        memory_root=project.root / "memory",
        transaction_root=project.root / ".sage" / "transactions",
        bic_job_id=project.job_id,
    )
    rows = json.loads((project.root / "memory" / "inspect-proposals.json").read_text(encoding="utf-8"))
    assert result["bic_job_id"] == project.job_id
    assert rows[0]["bic_job_id"] == project.job_id
    assert rows[0]["provenance"]["bic_job_id"] == project.job_id


def test_bic_and_saw_job_manifests_have_no_handoff_semantics(make_workspace) -> None:
    """Verify BIC and SAW Jobs remain independent and carry no handoff configuration."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    bic = next(item for item in projects if item.tool == "bic")
    saw = next(item for item in projects if item.tool == "saw")
    assert bic.bindings["generated_target"] == "usBOLx1"
    assert saw.bindings["wip"] == "usWIP"
    assert bic.bindings["generated_target"] != saw.bindings["wip"]
    assert "source_bic_job_id" not in saw.defaults
    assert "target_generation" not in saw.defaults
    config = load_ecosystem(saw.runtime_settings_path)
    assert not hasattr(config.workflow("saw"), "pin_root")


def test_help_and_status_return_to_the_invoking_menu(make_workspace) -> None:
    """Global Help and Status are non-destructive overlays over the active menu invocation."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["e", "", "f", "", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.bic_menu()

    rendered = output.getvalue()
    assert "HELP - BIC JOBS" in rendered
    assert "SAGE STATUS" in rendered
    assert rendered.count("BIC JOBS") >= 3


def test_saw_flow_selects_job_then_exposes_checks_and_back_is_hierarchical(make_workspace) -> None:
    """SAW navigation is setup/select -> selected Job checks -> Back -> SAW setup/select."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")
    store.set_active_job("saw", None)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", "1", "a", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.saw_menu()

    rendered = output.getvalue()
    assert "LEGACY ANALYSIS" in rendered
    assert "Choose active JOB [LEGACY ANALYSIS]" in rendered
    assert f"LEGACY ANALYSIS JOB - {saw.job_id}" in rendered
    assert "Active Run                   NONE" in rendered
    assert "Run Reference Text Comparison (RTC)" in rendered
    assert "Run Targeted Check" in rendered
    assert "Run Original-Language Review" in rendered
    assert "LEGACY ANALYSIS RUN OPTIONS" not in rendered
    assert rendered.count("A. Back") >= 2


def test_completed_saw_run_is_history_not_an_active_menu_run(make_workspace) -> None:
    """A completed SAW Run must not expose the Continue active Run action."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")
    run = store.create_run(saw, operation="rtc", scope="EXO 1-2")
    completed = store.update_run(run, status="COMPLETE", current_stage="COMPLETE")
    pointer = saw.controller_state_root / "active-run.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps({"schema_version": "1.0", "run_id": completed.run_id}),
        encoding="utf-8",
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center._saw_job_menu(saw)

    rendered = output.getvalue()
    assert "Active Run                   NONE" in rendered
    assert "Continue active Run" not in rendered
    assert "Run Reference Text Comparison (RTC)" in rendered
    assert not pointer.exists()


def test_saw_job_menu_visually_separates_work_from_administration(make_workspace) -> None:
    """Use the shared blank-line convention without adding section headings."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center._saw_job_menu(saw)

    rendered = output.getvalue()
    assert "  4. Run Original-Language Review\n\n  5. Reports and exports" in rendered

    store.create_run(saw, operation="rtc", scope="JHN 1")
    output.seek(0)
    output.truncate(0)
    center.io.input_func = ScriptedInput(["a"])

    center._saw_job_menu(saw)

    rendered = output.getvalue()
    assert "  5. Run Original-Language Review\n\n  6. Reports and exports" in rendered
    assert "WORK\n" not in rendered
    assert "ADMINISTRATION\n" not in rendered


def test_saw_job_menu_displays_current_skill_model_and_reasoning_route(
    make_workspace, monkeypatch
) -> None:
    """The Job view identifies routing mode and the exact recommended Skill route."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")

    class Service:
        """Return deterministic route status without a live provider dependency."""

        def __init__(self, _root):
            """Accept the normal workspace root."""

        def routing_override_status(self):
            """Report normal automatic routing."""
            return {"routing_mode": "AUTOMATIC", "override": None}

        def skill_routes(self):
            """Return one recommended SAW route."""
            return {
                "routing_mode": "AUTOMATIC",
                "skills": [{
                    "skill_id": "saw-rtc",
                    "provider": "codex",
                    "model_id": "gpt-5.6-sol",
                    "reasoning_id": "medium",
                    "qualification": "RECOMMENDED",
                    "availability": "AVAILABLE",
                }],
            }

    monkeypatch.setattr("sage.menu.ModelService", Service)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=False,
    )
    center._saw_job_menu(saw)
    rendered = output.getvalue()
    assert "AI Routing                   AUTOMATIC" in rendered
    assert "Current recommendation" in rendered
    assert "SKILL" in rendered and "MODEL" in rendered and "REASONING" in rendered
    assert "RTC" in rendered and "gpt-5.6-sol" in rendered and "medium" in rendered


def test_active_job_route_comes_from_current_attempt_receipt(
    make_workspace, monkeypatch
) -> None:
    """An active attempt displays its receipt route without resolving a new recommendation."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")
    run = store.create_run(saw, operation="rtc", scope="JUD 1")
    task = run.root / "tasks" / "saw-rtc-jud-001"
    task.mkdir(parents=True)
    manifest = task / "task-manifest.json"
    manifest.write_text(json.dumps({"task_id": "saw-rtc-jud-001"}), encoding="utf-8")
    validation = task / "validation"
    validation.mkdir()
    (validation / "llm-execution-receipt.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "task_id": "saw-rtc-jud-001",
                "skill_id": "saw-rtc",
                "provider": "codex",
                "model": "gpt-actual",
                "reasoning_effort": "high",
                "qualification_status": "QUALIFIED",
            }
        ),
        encoding="utf-8",
    )
    run = store.update_run(run, task_manifests=[str(manifest)])

    class Service:
        """Permit local mode lookup but prohibit recommendation substitution."""

        def __init__(self, _root):
            """Accept the workspace root."""

        def routing_override_status(self):
            """Report normal automatic routing."""
            return {"routing_mode": "AUTOMATIC", "override": None}

        def skill_routes(self):
            """Fail if the receipt path is incorrectly replaced by a live route lookup."""
            raise AssertionError("current attempt must use its execution receipt")

    monkeypatch.setattr("sage.menu.ModelService", Service)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([]), output=output),
        skip_setup=True,
    )

    center._write_job_ai_routing("saw", run)

    rendered = output.getvalue()
    assert "Current attempt receipt" in rendered
    assert "gpt-actual" in rendered
    assert "high" in rendered
    assert "QUALIFIED" in rendered


def test_active_job_route_rejects_receipt_for_another_task(make_workspace) -> None:
    """Job status must not attribute another task's route to the current attempt."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store, projects = _bootstrap(root)
    saw = next(project for project in projects if project.tool == "saw")
    run = store.create_run(saw, operation="rtc", scope="JUD 1")
    task = run.root / "tasks" / "saw-rtc-jud-001"
    task.mkdir(parents=True)
    manifest = task / "task-manifest.json"
    manifest.write_text(json.dumps({"task_id": "saw-rtc-jud-001"}), encoding="utf-8")
    validation = task / "validation"
    validation.mkdir()
    (validation / "llm-execution-receipt.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "task_id": "another-task",
                "skill_id": "saw-rtc",
                "provider": "codex",
                "model": "gpt-wrong",
                "reasoning_effort": "high",
                "qualification_status": "QUALIFIED",
            }
        ),
        encoding="utf-8",
    )
    run = store.update_run(run, task_manifests=[str(manifest)])
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([]), output=io.StringIO()),
        skip_setup=True,
    )

    assert center._active_run_route_row(run) is None



def test_main_menu_separates_scripture_project_management_from_workflows(make_workspace) -> None:
    """Project administration is explicit and separated from BIC/RTC/STC."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["c"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    try:
        center.main_menu()
    except Exception as exc:
        from sage.menu import MenuExitRequested
        assert isinstance(exc, MenuExitRequested)
    rendered = output.getvalue()
    assert "1. Manage SAGE Scripture PROJECTS" in rendered
    assert "Manage SAGE Scripture PROJECTS\n\n  2. Bible Index & Context (BIC)" in rendered
    assert "3. Reference Text Comparison (RTC)" in rendered
    assert "4. Source Text Correspondence (STC)\n\n  5. SAGE Maintenance" in rendered
    assert "\n  3. SAW\n" not in rendered
    assert "5. SAGE Maintenance" in rendered
    assert "4. Reports" not in rendered
    assert "6. Recovery" not in rendered
    assert "Scripture Projects >>" not in rendered


def test_reports_and_recovery_are_owned_by_workflow_or_sage_maintenance(make_workspace) -> None:
    """Keep report/Job recovery under BIC/SAW and system recovery under SAGE Maintenance."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.bic_menu()
    center.io.input_func = ScriptedInput(["a"])
    center.saw_menu()
    center.io.input_func = ScriptedInput(["a"])
    assert center.system_configuration_menu() == "BACK"
    center.io.input_func = ScriptedInput(["a"])
    center.system_actions_menu()

    rendered = output.getvalue()
    assert rendered.count("Reports and history") >= 2
    assert rendered.count("Recovery and diagnostics") >= 2
    assert rendered.count("Maintain JOB storage") == 2
    assert "SAGE Maintenance" in rendered
    assert "6. System actions" in rendered
    assert "System information, recovery and diagnostics" not in rendered
    assert "Wipe all JOB data" in rendered
    assert "Change interface language" not in rendered
    assert "Open system information" not in rendered
    assert "System information" in rendered
    assert "System actions" in rendered
    assert "Reset SAGE to out-of-box state" in rendered
    assert rendered.index("║ System actions") < rendered.index("\nSystem information\n")
    assert rendered.index("\nSystem information\n") < rendered.index("> System actions")
    assert "SAGE data folders" in rendered
    assert "Project inventory" in rendered
    assert "Resource mappings" in rendered
    assert "Show SAGE data folders" not in rendered
    assert rendered.index("System information") < rendered.index("SAGE data folders")
    assert rendered.index("SAGE data folders") < rendered.index("> System actions")
    assert rendered.index("> System actions") < rendered.index("1. Export global diagnostics")
    assert "\n> System actions\n" + "─" * 72 + "\n\n" in rendered


def test_workflow_storage_rebuilds_job_configuration_without_project_attribute_crash(
    make_workspace,
) -> None:
    """Rebuild each workflow's Jobs by Job ID from its BIC/SAW storage menu."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    _store, jobs = _bootstrap(root)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.job_storage_maintenance_menu("bic")
    center.io.input_func = ScriptedInput(["1", "a"])
    center.job_storage_maintenance_menu("saw")

    rendered = output.getvalue()
    for job in jobs:
        assert f"Rebuilt: {job.job_id}" in rendered
        assert job.runtime_settings_path.is_file()
    assert "BIC JOB storage" in rendered
    assert "LEGACY ANALYSIS JOB storage" in rendered


def test_system_actions_exclude_job_configuration_rebuild(make_workspace) -> None:
    """Keep Job configuration under BIC/SAW storage maintenance, not System actions."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.system_actions_menu()

    assert "Rebuild Job configuration" not in output.getvalue()


def test_project_registration_does_not_display_or_lookup_global_competency(
    make_workspace,
    monkeypatch,
) -> None:
    """Adding one Project must not trigger the explicit language-competency evidence action."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    monkeypatch.setattr(center, "_project_language_identification_menu", lambda row: True)
    monkeypatch.setattr(center.io, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "sage.menu.register_catalogued_scripture_project",
        lambda settings_path, catalogue_row: "faTEST",
    )

    class ForbiddenModelService:
        """Fail if Project registration attempts any model-competency operation."""

        def __init__(self, root):
            """Reject construction because the explicit competency action was not selected."""
            raise AssertionError("Project registration must not construct ModelService for competency")

    monkeypatch.setattr("sage.menu.ModelService", ForbiddenModelService)
    created = center._register_catalogue_row({
        "project_code": "faTEST",
        "detail_status": "VALIDATED",
        "full_name": "Persian test Project",
        "language_name": "Persian",
        "language_iso": "fa-IR",
        "scope": "PORTIONS",
        "book_count": 1,
        "books": ["MAT"],
        "sfm_books": ["MAT"],
        "versification": {},
        "code_metadata": {"parse_status": "VALID"},
        "status": "READY",
        "warnings": [],
    })

    assert created == "faTEST"
    rendered = output.getvalue()
    assert "PROJECT ADDED TO SAGE" in rendered
    assert "LANGUAGE COMPETENCY" not in rendered
    assert "competency evidence" not in rendered.casefold()


def test_project_registration_accepts_scope_presets_unions_and_ranges(
    make_workspace,
    monkeypatch,
) -> None:
    """The onboarding scope becomes the exact declared Project book set."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["NT, PSA"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    monkeypatch.setattr(center, "_project_language_identification_menu", lambda row: True)
    monkeypatch.setattr(center.io, "confirm", lambda *args, **kwargs: True)
    captured: dict[str, object] = {}

    def register(_settings_path, *, catalogue_row):
        """Capture the normalized catalog row passed to Project registration."""
        captured.update(catalogue_row)
        return "idTEST"

    monkeypatch.setattr("sage.menu.register_catalogued_scripture_project", register)
    created = center._register_catalogue_row({
        "project_code": "idTEST",
        "detail_status": "VALIDATED",
        "full_name": "Scope fixture",
        "language_name": "Indonesian",
        "language_iso": "id-ID",
        "scope": "PORTIONS",
        "book_count": 2,
        "books": ["MAT", "PSA"],
        "sfm_books": ["MAT", "PSA"],
        "versification": {},
        "code_metadata": {"parse_status": "VALID"},
        "status": "READY",
        "warnings": [],
    })

    assert created == "idTEST"
    assert captured["books"] == ["PSA", *NT_27]
    assert captured["scope"] == "PORTIONS"
    assert captured["book_count"] == 28
    assert "USFM IDs/ranges" in output.getvalue()


def test_ai_menu_probes_on_open_and_exposes_skill_routing_actions(make_workspace) -> None:
    """Configure AI exposes provider setup and route governance without normal model selection."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.model_menu()

    rendered = output.getvalue()
    assert "Loading LLM state..." in rendered
    assert "LLM status" not in rendered
    assert "Connection                  READY" in rendered
    assert rendered.index("Configure Hosted AI") < rendered.index("Connection                  READY")
    assert "AI settings" in rendered
    assert "1. Change provider" in rendered
    assert "2. Available provider models" in rendered
    assert "3. Skill routing recommendations" in rendered
    assert "4. Advanced routing override" in rendered
    assert "Evaluate model for Skill" not in rendered
    assert "Change model" not in rendered
    assert "Change reasoning" not in rendered
    assert "Change provider         Codex" not in rendered
    assert "Change model            gpt-" not in rendered
    assert "Provider management" in rendered
    assert "5. Connect OpenAI and ChatGPT" in rendered
    assert "6. Configure Local AI" in rendered
    assert "7. Check LLM connection" in rendered
    assert "Check competency for configured languages" not in rendered


def test_available_model_view_labels_provisional_skills_separately(make_workspace) -> None:
    """Hiding provisional rows behind 'Qualified Skills: none' must mislead the Operator."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    class FakeService:
        """Expose one catalog row with only a provisional Skill route."""

        def list_models(self, _provider):
            """Return a truthful no-data catalog fixture."""
            return {
                "models": [
                    {
                        "model": "gpt-5.6-sol",
                        "display_name": "GPT-5.6 Sol",
                        "reasoning_efforts": ["medium", "high"],
                        "qualified_skill_routes": [],
                        "provisional_skill_routes": [
                            {
                                "skill_id": "saw-rtc",
                                "reasoning_id": "medium",
                                "qualification": "PROVISIONAL_UNQUALIFIED",
                            }
                        ],
                    }
                ]
            }

    center._model_show_codex_catalog(FakeService())

    rendered = output.getvalue()
    assert "Qualified Skills: none" in rendered
    assert "Provisional Skills: saw-rtc:medium" in rendered


def test_rtc_policy_menu_omits_mandatory_cross_reference_toggle(make_workspace) -> None:
    """Keep cross-reference review always on and reuse item 10 for the OL policy."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["10", "1"]),
            output=output,
            viewport_columns=40,
        ),
        skip_setup=True,
        dry_run_provider=True,
    )

    policy = center._rtc_policy_menu("JHN 1:1")

    assert policy is not None
    assert policy["usfm_contexts"]["x"] == "NORMAL"
    assert policy["original_language"]["source_text_drift_adjudication"] == "ENABLED"
    rendered = output.getvalue()
    assert "Check cross-references" not in rendered
    assert "10. Adjudicate WIP-Reference variance" in rendered
    assert "11. Adjudicate WIP-Reference variance" not in rendered
    assert "\n     ON\n" in rendered


def test_sage_maintenance_submenus_put_relevant_state_before_actions(
    make_workspace,
    monkeypatch,
) -> None:
    """Keep Paths and Checks scoped, informative, and non-probing until an action is chosen."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    center.paths_and_workspace_menu()
    paths = output.getvalue()
    assert paths.index("Paths and workspace locations") < paths.index("Paratext Projects root")
    assert paths.index("Resource mappings") < paths.index("Path actions")
    assert "Show SAGE data folders" not in paths

    monkeypatch.setattr(
        center,
        "_setup_model_probe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("opening System Checks must not test AI")
        ),
    )
    output.seek(0)
    output.truncate(0)
    center.io.input_func = ScriptedInput(["a"])
    center.system_diagnostics_menu()
    checks = output.getvalue()
    assert checks.index("System checks") < checks.index("Current system state [last known]")
    assert checks.index("Last AI check") < checks.index("Check actions")
    assert "Configured paths" not in checks
    assert "6. Complete system check" in checks


def test_ai_menu_checks_connection_only_on_entry_and_explicit_check(make_workspace, monkeypatch) -> None:
    """Read-only routing UI does not add hidden provider connection tests."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["7", "", "a"]), output=output),
        skip_setup=True,
    )
    readiness_calls: list[bool] = []
    connection_calls: list[int] = []
    catalog_calls: list[str] = []

    class FakeService:
        """Expose one loaded catalog and count only explicit structured connection checks."""

        def __init__(self, service_root):
            """Retain the fixture root used by persisted selection helpers."""
            self.root = service_root

        def settings(self):
            """Read the current persisted selection without a provider probe."""
            return load_llm_settings(self.root)

        def routing_override_status(self):
            """Return local automatic routing without a provider probe."""
            return {"routing_mode": "AUTOMATIC", "override": None}

        def policy(self):
            """Return the release-owned no-data default without probing a provider."""
            return {
                "provisional_routing": {
                    "default_reasoning_by_provider": {"codex": "medium"}
                }
            }

        def quick_codex_status(self):
            """Report a ready authenticated runtime for each requested connection refresh."""
            return {
                "available": True,
                "ready": True,
                "auth_mode": "CHATGPT",
                "version": "codex-cli test",
                "diagnostic": "ready",
            }

        def connectivity_test(self, *, timeout_seconds: int):
            """Count only the explicit end-to-end connection test."""
            connection_calls.append(timeout_seconds)
            settings = self.settings()
            selected = dict(settings["providers"]["codex"])
            return {
                "provider": "codex",
                "model": selected.get("model") or "gpt-a",
                "reasoning_effort": selected.get("reasoning_effort") or "medium",
            }

        def readiness_check(self):
            """Load the selected configuration without model generation."""
            readiness_calls.append(True)
            settings = self.settings()
            selected = dict(settings["providers"]["codex"])
            return {
                "provider": "codex",
                "model": selected.get("model") or "gpt-a",
                "reasoning_effort": selected.get("reasoning_effort") or "medium",
            }

        def list_models(self, provider: str):
            """Return capabilities loaded only beside the entry/explicit refresh."""
            catalog_calls.append(provider)
            return {
                "provider": provider,
                "models": [
                    {"model": "gpt-a", "reasoning_efforts": ["low", "high"]},
                    {"model": "gpt-b", "reasoning_efforts": ["medium", "high"]},
                ],
            }

    monkeypatch.setattr("sage.menu.ModelService", FakeService)

    center.model_menu()

    settings = load_llm_settings(root)
    assert readiness_calls == [True]
    assert connection_calls == [120]
    assert catalog_calls == ["codex", "codex"]
    assert "model" not in settings["providers"]["codex"]
    assert "reasoning_effort" not in settings["providers"]["codex"]
    rendered = output.getvalue()
    assert rendered.count("Loading LLM state...") == 1
    assert rendered.count("Checking LLM connection...") == 1
    assert "Connection                  READY" in rendered
    assert "NOT CHECKED FOR CURRENT SELECTION" not in rendered
    assert "MODEL_SELECTION_REQUIRED" not in rendered
    assert "\nModel: gpt-a\n" not in rendered
    assert "\nReasoning: Low\n" not in rendered


def test_language_competency_update_renders_evidence_once_not_repeated_messages(make_workspace) -> None:
    """A competency update shows actual rows and one disclaimer, never repeated boilerplate."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center._write_language_competency_evidence({
        "status": "REGISTRY_EVIDENCE_READY",
        "model": "gpt-test",
        "model_version": "gpt-test",
        "provider_runtime_version": "0.147.0",
        "assessments": [
            {
                "canonical_tag": "uk-UA",
                "language": "Ukrainian",
                "tier": "GOOD",
                "confidence": "MEDIUM",
                "limitations": ["Verify grammar-sensitive output"],
                "operator_message": "Versioned registry evidence.",
            },
            {
                "canonical_tag": "fa-IR",
                "language": "Persian",
                "tier": "FAIR",
                "confidence": "LOW",
                "limitations": [],
                "operator_message": "Versioned registry evidence.",
            },
        ],
    })
    rendered = output.getvalue()
    assert "Ukrainian" in rendered and "uk-UA" in rendered and "GOOD" in rendered and "MEDIUM" in rendered
    assert "Persian" in rendered and "fa-IR" in rendered and "FAIR" in rendered and "LOW" in rendered
    assert "Verify grammar-sensitive output" in rendered
    assert rendered.count("Registry/evaluation evidence only") == 1


def test_global_numeric_menu_alignment_contract() -> None:
    """Every numeric menu row uses one three-column right-aligned number field."""
    from sage.ui_format import menu_item

    assert menu_item(1, "One") == "  1. One"
    assert menu_item(11, "Eleven") == " 11. Eleven"
    assert menu_item(111, "One hundred eleven") == "111. One hundred eleven"
    source_root = Path(__file__).resolve().parents[1] / "src" / "sage"
    for name in ("menu.py", "cli.py", "guided_input.py"):
        source = (source_root / name).read_text(encoding="utf-8")
        assert 'f"  {index}. ' not in source
