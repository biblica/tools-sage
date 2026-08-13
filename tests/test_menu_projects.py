"""Control Center, Job isolation, and provider-neutral menu contracts."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from sage_core.cli import build_parser
from sage_core.menu import MenuIO, SageControlCenter, ScriptedInput
from sage_core.registry import load_ecosystem
from sage_core.runtime_paths import task_container
from sage_core.jobs import JobStore
from sage_core.bic_memory import submit_inspect_transactionally


def _bootstrap(root: Path) -> tuple[JobStore, list]:
    """Bootstrap canonical Jobs from the fixture bindings."""
    store = JobStore(root, root / "ecosystem.yml")
    projects = store.bootstrap_default_jobs()
    return store, projects


def test_menu_is_a_canonical_cli_domain() -> None:
    """Verify test menu is a canonical cli domain for the current Job-menu contract."""
    parser = build_parser()
    args = parser.parse_args(["menu", "--skip-setup", "--dry-run-provider"])
    assert args.command == "menu"
    assert args.skip_setup is True
    assert args.dry_run_provider is True


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

    assert before == {"bic": bic.job_id, "saw": saw.job_id}
    assert after == {"bic": None, "saw": saw.job_id}


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
    saw_run = store.create_run(saw, operation="qa", scope="MAT 1:1-2")

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
        io=MenuIO(input_func=ScriptedInput(["0"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    assert center.run() == 0
    rendered = output.getvalue()
    assert "SAGE v0.01-rc7.04" in rendered
    assert "BIC" in rendered
    assert "SAW" in rendered
    assert "System / Configuration" in rendered



def test_guided_first_run_setup_records_unresolved_provider_and_allows_main_menu(make_workspace, monkeypatch) -> None:
    """Verify first-run setup can decline installation, save state, and return to SAGE."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SAGE_CODEX_COMMAND", raising=False)
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(
            input_func=ScriptedInput(["n", "6", "0"]),
            output=output,
        ),
        dry_run_provider=True,
    )

    assert center.run() == 0
    receipt = json.loads((root / "state" / "setup-state.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["next_step"] == "INSTALL_CODEX"
    assert receipt["enabled_tools"] == []
    assert receipt["active_jobs"]["bic"] is None
    assert receipt["active_jobs"]["saw"] is None
    assert receipt["scripture_resources"]["status"] == "READY_EMPTY"
    rendered = output.getvalue()
    assert "SAGE SETUP" in rendered
    assert "SCRIPTURE RESOURCE CHECK" in rendered
    assert "Project inventory is empty by design for a clean RC start." in rendered
    assert "Install Codex CLI" in rendered
    assert "BIC:       NOT CONFIGURED" in rendered
    assert "SAW:       NOT CONFIGURED" in rendered
    assert "System / configuration" in rendered
    assert "Go to Main Menu - settings save automatically" in rendered
    assert "Exit SAGE" in rendered
    assert "SAGE v0.01-rc7.04" in rendered



def test_direct_setup_returns_without_opening_control_center(make_workspace, capsys, monkeypatch) -> None:
    """Verify the direct setup surface performs setup only and returns to its caller."""
    from sage_core.menu import run_setup

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SAGE_CODEX_COMMAND", raising=False)
    script = root / "setup-input.txt"
    script.write_text("n\n6\n", encoding="utf-8")
    assert run_setup(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        script_path=script,
    ) == 0
    receipt = json.loads((root / "state" / "setup-state.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["next_step"] == "INSTALL_CODEX"

def test_closed_menu_input_is_a_governed_cancellation() -> None:
    """Verify terminal EOF is converted to OperatorCancelledError rather than leaking a traceback."""
    from sage_core.errors import OperatorCancelledError

    io_surface = MenuIO(input_func=ScriptedInput([]), output=io.StringIO())
    try:
        io_surface.read("Select: ")
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
    (run.root / "reports" / "summary.md").write_text("# Summary\n", encoding="utf-8")

    project_export = store.export_job(project)
    first = project_export.read_bytes()
    project_export = store.export_job(project)
    assert project_export.read_bytes() == first
    with zipfile.ZipFile(project_export) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("EXPORT-MANIFEST.json"))
    assert manifest["job_id"] == project.job_id
    assert "job.yml" in names
    assert f"runs/{run.run_id}/run.yml" in names
    assert not any(name.startswith(".sage/cache/") for name in names)
    assert not any(name.startswith(".sage/workspace-data/") for name in names)

    run_export = store.export_run(project, run)
    with zipfile.ZipFile(run_export) as archive:
        manifest = json.loads(archive.read("EXPORT-MANIFEST.json"))
        names = set(archive.namelist())
    assert manifest["run_id"] == run.run_id
    assert "run.yml" in names
    assert "reports/summary.md" in names


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
