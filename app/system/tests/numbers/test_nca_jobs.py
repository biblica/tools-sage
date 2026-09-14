"""NCA Job identity, immutable bindings, snapshots, and Run lifecycle contracts."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import pytest
import yaml

from sage.errors import ConfigurationError, ValidationError
from sage.jobs import JobStore
from sage.nca import create_nca_job, create_nca_run
from sage.numbers.policy import load_nca_run_snapshot
from sage.project_inventory import register_project
from sage.registry import load_ecosystem
from sage.storage import storage_layout
import sage.workflow_identity as workflow_identity

REFERENCE_FIXTURE = Path(__file__).parent / "fixtures" / "reference" / "lineage"
IMPORT_TIME = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
CHECKS = {
    "number_accuracy": True,
    "presentation_consistency": True,
    "footnote_review": True,
}
ROUTE = {
    "route_id": "nca-route-fixture",
    "provider": "codex",
    "model": "gpt-test",
    "reasoning_effort": "high",
    "capability_fingerprint": "1" * 64,
    "qualification_status": "QUALIFIED",
    "qualification_evidence_sha256": "2" * 64,
    "routing_policy_version": "fixture-1",
}


def _configured_style(root: Path) -> bytes:
    """Install one complete compatible number-style profile in operator storage."""
    template = yaml.safe_load(
        (root / "system/config/profiles/numbers/number-style-template.yml").read_text(encoding="utf-8")
    )
    template["profile"].update(
        {
            "id": "fixture-style",
            "version": "1",
            "language": "en",
            "script": "Latn",
            "projects": ["usWIP"],
            "source_guide": "Fixture guide",
            "recorded_by": "Fixture owner",
            "recorded_date": "2026-09-01",
            "status": "CONFIGURED",
        }
    )
    payload = yaml.safe_dump(template, sort_keys=False, allow_unicode=True).encode("utf-8")
    destination = storage_layout(root).styleguides_root / "numbers/fixture-style/1.yml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return payload


def _prepare_nca_workspace(root: Path, *, content_state: str = "UNDER_REVIEW") -> tuple[object, bytes]:
    """Install qualified fixture resources and audited Project import identity."""
    profile_path = root / 'system/config/workflows/nca/profile.yml'
    profile = yaml.safe_load(profile_path.read_text())
    profile['optimization_policy'] = yaml.safe_load((Path(__file__).resolve().parents[2] / 'config/workflows/nca/profile.yml').read_text())['optimization_policy']
    profile_path.write_text(yaml.safe_dump(profile))
    source = Path(__file__).resolve().parents[2] / 'src/sage'
    destination = root / 'system/src/sage'
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('nca.py', 'nca_reporting.py'):
        shutil.copy2(source / name, destination / name)
    shutil.copytree(source / 'numbers', destination / 'numbers', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    package = storage_layout(root).resources_root / "numbers/SYNTHETIC_NCA_REFERENCE_1"
    package.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REFERENCE_FIXTURE, package)
    style_bytes = _configured_style(root)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")
    register_project(
        root,
        project_id="usWIP",
        project_path=project.path,
        language_code="en",
        language_profile="en",
        profile_variant="bol-target",
        base_vrs_file="eng.vrs",
        content_state=content_state,
        imported_at=IMPORT_TIME,
    )
    return load_ecosystem(root / "ecosystem.yml"), style_bytes


def _route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace provider readiness with one exact offline route identity."""
    monkeypatch.setattr("sage.nca._configured_nca_route", lambda _config: dict(ROUTE))


def test_invalid_nca_scope_is_rejected_before_route_selection(make_workspace, monkeypatch):
    """Direct NCA callers get a scope error before model probing or Run persistence."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1')

    def unexpected_route(_config):
        """Detect model readiness work attempted before rejecting malformed input."""
        pytest.fail('Invalid scope reached model route selection')

    monkeypatch.setattr('sage.nca._configured_nca_route', unexpected_route)
    with pytest.raises(ValidationError, match='Chapter must be positive'):
        create_nca_run(config, job_id=job.job_id, scope_value='MAT 0')
    assert JobStore(root, config.settings_path).active_run(job) is None
    assert list((job.root / 'runs').glob('*')) == []


@pytest.mark.parametrize('setup', ['existing_run', 'stale_receipt'])
@pytest.mark.parametrize('scope', ['MAT 1:1', 'mat', 'Matthew 1:1'])
def test_cli_creates_nca_task_without_generic_initialization(make_workspace, monkeypatch, capsys, setup, scope):
    """CLI remediation must allow NCA's sealed Job/Run prerequisites to govern creation."""
    from sage import cli
    from sage.state import ecosystem_state_path
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root, content_state='LOCKED')
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1')
    run = create_nca_run(config, job_id=job.job_id, scope_value=scope)
    expected = {'MAT 1:1': 'MAT 1:1', 'mat': 'MAT', 'Matthew 1:1': 'MAT 1:1'}[scope]
    assert run.scope == expected
    # Simulate a pre-normalization Run to retain real historical resume coverage.
    for name in ('run.json', 'status.json'):
        path = run.root / name
        metadata = json.loads(path.read_text())
        metadata['scope'] = scope
        path.write_text(json.dumps(metadata))
    config = load_ecosystem(job.runtime_settings_path)
    options = ['--job-id', job.job_id, '--run-id', run.run_id]
    receipt = ecosystem_state_path(config.runtime_state_root)
    if setup == 'stale_receipt':
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({'state': 'READY', 'settings_sha256': 'obsolete'}))
    else:
        receipt.unlink(missing_ok=True)
    original_receipt = receipt.read_bytes() if receipt.exists() else None
    monkeypatch.setattr('sys.argv', ['sage', '--settings', str(config.settings_path), '--json', '--no-prompt',
        'task', 'create', '--workflow', 'nca', '--operation', 'numbers',
        '--wip', 'usWIP', '--scope', scope, *options])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    payload = json.loads(capsys.readouterr().out)
    assert caught.value.code == 0, payload
    task = json.loads(Path(payload['task_manifest_path']).read_text())
    assert task['workflow'] == 'nca'
    assert task['scope'] == scope
    assert 'NUMBER_STYLE' not in task['resource_bindings']
    from .test_nca_tasks import _OfflineTasks
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    task_path = payload['task_manifest_path']
    for arguments, status in [
        (['execute', '--dry-run'], 'READY_TO_EXECUTE'),
        (['execute'], 'EXECUTED'),
        (['submit'], 'FINALIZED'),
    ]:
        monkeypatch.setattr('sys.argv', ['sage', '--settings', str(config.settings_path), '--json',
            '--no-prompt', 'task', *arguments, '--task', task_path])
        with pytest.raises(SystemExit) as caught:
            cli.main()
        payload = json.loads(capsys.readouterr().out)
        assert caught.value.code == 0, payload
        assert payload['status'] == status
    assert (receipt.read_bytes() if receipt.exists() else None) == original_receipt


@pytest.mark.parametrize('workflow', ['bic', 'rtc', 'stc'])
def test_other_workflows_still_require_workspace_initialization(make_workspace, workflow):
    """The NCA exception must not remove the initialization gate for other tasks."""
    import argparse
    from sage.cli import _ensure_workspace_initialized_input
    from sage.errors import InputRequiredError
    from sage.state import ecosystem_state_path
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config = load_ecosystem(root / 'ecosystem.yml')
    ecosystem_state_path(config.runtime_state_root).unlink(missing_ok=True)
    args = argparse.Namespace(command='task', task_command='create', workflow_id=workflow,
                              no_prompt=True, json=True)
    with pytest.raises(InputRequiredError) as caught:
        _ensure_workspace_initialized_input(args, config)
    assert caught.value.code == 'WORKSPACE_INITIALIZATION_INPUT_REQUIRED'


def test_role_neutral_locked_project_runs_as_nca_wip_without_global_changes(make_workspace, monkeypatch):
    """Selecting an imported Project grants only a read-only Job-local WIP role."""
    from sage.nca import create_nca_task, execute_nca_task, finalize_nca_run
    from sage.act_tasks import submit_act_task
    from sage.numbers.execution import prepare_execution_inputs
    from sage.project_inventory import project_registry_path
    from .test_nca_tasks import _OfflineTasks
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root, content_state='LOCKED')
    assert config.project('usWIP').content_state == 'LOCKED'
    source = config.project('usWIP').path / '41MAT.SFM'
    original_source = source.read_bytes()
    registry = project_registry_path(root)
    original_registry = registry.read_bytes()
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1')
    runtime = load_ecosystem(job.runtime_settings_path)
    assert runtime.project('usWIP').content_state == 'UNDER_REVIEW'
    assert yaml.safe_load(job.runtime_profile_path.read_text())['permissions']['may_write_projects'] == []
    run = create_nca_run(config, job_id=job.job_id, scope_value='MAT 1:1')
    policy = load_nca_run_snapshot(run.root)
    with pytest.raises(ValidationError) as caught:
        prepare_execution_inputs(config, job, run, policy)
    assert caught.value.code == 'NCA_WIP_SNAPSHOT_STALE'
    prepare_execution_inputs(runtime, job, run, policy)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    task_path = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    assert execute_nca_task(config, task_path)['status'] == 'EXECUTED'
    assert submit_act_task(config, task_path)['status'] == 'FINALIZED'
    assert finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)['status'] == 'COMPLETE'
    assert load_ecosystem(root / 'ecosystem.yml').project('usWIP').content_state == 'LOCKED'
    assert source.read_bytes() == original_source
    assert registry.read_bytes() == original_registry


def test_nca_identity_is_operator_workflow_but_not_analysis_workflow() -> None:
    """NCA shares snapshot lifecycle without inheriting RTC/STC authority semantics."""
    assert "nca" in workflow_identity.OPERATOR_WORKFLOWS
    assert "nca" not in workflow_identity.ANALYSIS_WORKFLOWS
    assert "nca" in workflow_identity.SNAPSHOT_WIP_WORKFLOWS
    assert workflow_identity.runtime_workflow_id("nca") == "nca"
    assert workflow_identity.is_analysis_workflow("nca") is False
    assert workflow_identity.canonical_nca_job_id("usWIP", "20260901") == "NCA-usWIP_20260901"


def test_create_nca_job_seals_wip_package_style_and_default_checks(make_workspace) -> None:
    """One NCA Job owns WIP snapshot identity and non-Scripture resource bindings."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)

    job = create_nca_job(
        config,
        wip="usWIP",
        package_id="SYNTHETIC_NCA_REFERENCE_1",
        style_selector="fixture-style/1",
        display_name="Fixture NCA",
    )

    assert job.job_id == "NCA-usWIP_20260901"
    assert job.bindings == {"wip": "usWIP"}
    assert job.profiles == {"number_style": "fixture-style/1"}
    assert job.resources["numbers_package"]["package_id"] == "SYNTHETIC_NCA_REFERENCE_1"
    assert len(job.resources["numbers_package"]["sha256"]) == 64
    assert job.defaults == {"checks": CHECKS}
    assert job.progress_quantifier["basis"] == "EXPECTED_NUMERIC_UNITS"
    assert job.wip_snapshot is not None
    assert set(job.wip_snapshot["files"]) == {"usj/MAT.json"}
    assert len(job.wip_snapshot["files"]["usj/MAT.json"]) == 64
    assert len(job.wip_snapshot["inventory_sha256"]) == 64
    runtime = yaml.safe_load(job.runtime_profile_path.read_text(encoding="utf-8"))
    assert runtime["bindings"] == {"WIP": "usWIP"}
    assert runtime["permissions"]["may_write_projects"] == []


def test_nca_job_rejects_reference_binding_and_explicit_invalid_style(make_workspace) -> None:
    """NCA cannot inherit REFERENCE authority or ignore an invalid selected style."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    store = JobStore(root, root / "ecosystem.yml")

    with pytest.raises(ValidationError, match="unsupported bindings"):
        store.create_job(
            tool="nca",
            job_id="NCA-usWIP_20260901",
            display_name="bad",
            bindings={"wip": "usWIP", "reference": "usNIVv2"},
            profiles={"number_style": "fixture-style/1"},
            resources={"numbers_package": {"package_id": "SYNTHETIC_NCA_REFERENCE_1", "sha256": "0" * 64}},
            imported_at=IMPORT_TIME,
        )
    with pytest.raises(ValidationError) as caught:
        create_nca_job(
            config,
            wip="usWIP",
            package_id="SYNTHETIC_NCA_REFERENCE_1",
            style_selector="missing/1",
        )
    assert caught.value.code == "NCA_STYLE_PROFILE_INVALID"


def test_create_nca_run_atomically_seals_policy_style_route_and_snapshot(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NCA Run publication includes every immutable input before active pointers change."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip="usWIP", package_id="SYNTHETIC_NCA_REFERENCE_1", style_selector="fixture-style/1")

    run = create_nca_run(
        config,
        job_id=job.job_id,
        scope_value="MAT 1",
        checks={"presentation_consistency": False},
    )

    assert run.operation == "numbers"
    assert (run.root / "snapshot/usj/MAT.json").is_file()
    policy = json.loads((run.root / "check-policy.json").read_text(encoding="utf-8"))
    assert policy["checks"] == {**CHECKS, "presentation_consistency": False}
    assert policy["reference_package"] == job.resources["numbers_package"] | {
        "parser_version": "1.0",
        "qualification_status": "QUALIFIED_WITH_DIAGNOSTICS",
        "diagnostics": policy["reference_package"]["diagnostics"],
        "files": policy["reference_package"]["files"],
        "inventory_sha256": policy["reference_package"]["inventory_sha256"],
    }
    assert policy["model_route"] == ROUTE
    assert policy["sqs_checks_applied"] is False
    assert policy["capability_limitation_code"] == "NCA_LLM_CAPABILITY_LIMITATION"
    assert (run.root / "profiles/number-style.yml").read_bytes() == style_bytes


def test_nca_snapshot_resume_ignores_live_sources_and_rejects_sealed_tamper(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resumed NCA work reads sealed bytes and fails if those bytes are changed."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip="usWIP", package_id="SYNTHETIC_NCA_REFERENCE_1", style_selector="fixture-style/1")
    run = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")
    sealed_before = (run.root / "snapshot/usj/MAT.json").read_bytes()
    (config.project("usWIP").path / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 changed\n", encoding="utf-8")
    assert (run.root / "snapshot/usj/MAT.json").read_bytes() == sealed_before

    (run.root / "snapshot/usj/MAT.json").write_bytes(sealed_before + b" ")
    with pytest.raises(ValidationError) as caught:
        load_nca_run_snapshot(run.root)
    assert caught.value.code == "NCA_WIP_SNAPSHOT_STALE"


def test_nca_job_load_rejects_package_manifest_tamper(make_workspace) -> None:
    """A Job cannot reopen when its content-addressed package no longer matches."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    job = create_nca_job(config, wip="usWIP", package_id="SYNTHETIC_NCA_REFERENCE_1", style_selector="fixture-style/1")
    package = storage_layout(root).resources_root / "numbers/SYNTHETIC_NCA_REFERENCE_1"
    target = package / "HANDOVER_VERIFICATION.json"
    target.write_bytes(target.read_bytes() + b"tamper")

    with pytest.raises(ConfigurationError):
        JobStore(root, root / "ecosystem.yml").load_job(job.job_id, tool="nca")


def test_restart_preserves_old_run_and_seals_current_job_defaults(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restart abandons immutable evidence and creates a fresh policy snapshot."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(
        config,
        wip="usWIP",
        package_id="SYNTHETIC_NCA_REFERENCE_1",
        style_selector="fixture-style/1",
    )
    old = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")
    old_policy = (old.root / "check-policy.json").read_bytes()
    store = JobStore(root, root / "ecosystem.yml")
    job = store.revise_job(
        job,
        defaults={
            "checks": {
                **CHECKS,
                "footnote_review": False,
            }
        },
    )

    replacement = store.restart_run(job, old)

    assert replacement.run_id != old.run_id
    assert store.load_run(job, old.run_id).status == "ABANDONED"
    assert (old.root / "check-policy.json").read_bytes() == old_policy
    assert load_nca_run_snapshot(replacement.root)["checks"]["footnote_review"] is False


def test_create_nca_run_rechecks_active_pointer_inside_creation_lock(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale pre-lock observation cannot publish a second active NCA Run."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(
        config,
        wip="usWIP",
        package_id="SYNTHETIC_NCA_REFERENCE_1",
        style_selector="fixture-style/1",
    )
    first = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")
    original = JobStore.active_run
    observations = 0

    def stale_then_current(store: JobStore, current_job):
        """Simulate a caller that observed no active Run before taking the lock."""
        nonlocal observations
        observations += 1
        if observations == 1:
            return None
        return original(store, current_job)

    monkeypatch.setattr(JobStore, "active_run", stale_then_current)

    with pytest.raises(ValidationError) as caught:
        create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")

    assert caught.value.code == "NCA_RUN_ALREADY_ACTIVE"
    store = JobStore(root, root / "ecosystem.yml")
    assert [run.run_id for run in store.list_runs(job)] == [first.run_id]


def test_provider_readiness_failure_publishes_no_run(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run creation fails before publication when no qualified model route resolves."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    job = create_nca_job(
        config,
        wip="usWIP",
        package_id="SYNTHETIC_NCA_REFERENCE_1",
        style_selector="fixture-style/1",
    )

    def unavailable(_config):
        """Expose the provider-readiness failure at the route snapshot boundary."""
        raise ValidationError(
            "No qualified NCA route is available",
            code="NCA_MODEL_PROVIDER_UNAVAILABLE",
            next_action="Configure a qualified nca-numbers route.",
        )

    monkeypatch.setattr("sage.nca._configured_nca_route", unavailable)

    with pytest.raises(ValidationError) as caught:
        create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")

    assert caught.value.code == "NCA_MODEL_PROVIDER_UNAVAILABLE"
    store = JobStore(root, root / "ecosystem.yml")
    assert store.list_runs(job) == []
    assert store.active_run(job) is None
