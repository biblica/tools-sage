"""Per-attempt qualification and immutable sealed NCA execution inputs."""
import json
from pathlib import Path
from dataclasses import replace

import pytest

from sage.errors import ConfigurationError, ValidationError
from sage.nca import create_nca_task, execute_nca_task, finalize_nca_run
from sage.act_tasks import submit_act_task
from sage.numbers import engine, resources, style
from sage.storage import storage_layout
from sage.jobs import JobStore
from sage.numbers.policy import load_nca_run_snapshot
from sage.numbers.models import ProjectedUnit, TargetUnit
from sage.vrs import VerseRef

from .test_nca_tasks import _OfflineTasks, _run


def test_execution_qualifies_package_and_style_once_per_attempt(make_workspace, monkeypatch):
    """Many units and output resume must each use one freshly validated context."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    assert len(created["expected_unit_ids"]) > 1
    counts = {"package": 0, "style": 0}
    actual_load, actual_style = resources.load_reference, style.validate_style_profile

    def load(*args, **kwargs):
        """Observe full qualification rather than a cached status assertion."""
        counts["package"] += 1
        return actual_load(*args, **kwargs)

    def validate(*args, **kwargs):
        """Observe both loader and engine aliases of the actual style validator."""
        counts["style"] += 1
        return actual_style(*args, **kwargs)

    monkeypatch.setattr(resources, "load_reference", load)
    monkeypatch.setattr(style, "validate_style_profile", validate)
    monkeypatch.setattr(engine, "validate_style_profile", validate)
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    manifest = Path(created["task_manifest_path"])
    for dry_run, status in ((True, "READY_TO_EXECUTE"), (False, "EXECUTED"), (False, "EXECUTED"), (True, "EXECUTED")):
        counts.update(package=0, style=0)
        assert execute_nca_task(config, manifest, dry_run=dry_run)["status"] == status
        assert counts == {"package": 1, "style": 1}


@pytest.mark.parametrize("damage", ["package", "style", "wip"])
@pytest.mark.parametrize("resume", [False, True])
def test_fresh_attempt_rejects_changed_sealed_inputs_before_provider(
    make_workspace, monkeypatch, damage, resume
):
    """Tampering between lock acquisitions cannot reuse prior trust or construct a provider."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    manifest = Path(created["task_manifest_path"])
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    if resume:
        execute_nca_task(config, manifest)
    if damage == "package":
        path = storage_layout(config.root).resources_root / "numbers/SYNTHETIC_NCA_REFERENCE_1/extra.txt"
        path.write_text("unsealed file", encoding="utf-8")
    elif damage == "style":
        path = run.root / "profiles/number-style.yml"
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
    else:
        policy = json.loads((run.root / "check-policy.json").read_text(encoding="utf-8"))
        path = run.root / "snapshot" / next(iter(policy["wip"]["files"]))
        path.write_bytes(path.read_bytes() + b" ")

    def forbidden(*args, **kwargs):
        """Fail if validation reaches provider construction with stale evidence."""
        pytest.fail("provider constructed before sealed input rejection")

    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", forbidden)
    with pytest.raises((ConfigurationError, ValidationError)):
        execute_nca_task(config, manifest)


def test_prepared_context_freezes_sources_and_rejects_coverage_drift(make_workspace, monkeypatch):
    """Prepared evidence keeps raw source content and concrete references without mutable aliases."""
    from sage.numbers.execution import prepare_execution_inputs

    _root, config, job, run = _run(make_workspace, monkeypatch)
    policy = load_nca_run_snapshot(run.root)
    inputs = prepare_execution_inputs(config, job, run, policy)
    assert all(isinstance(ref, VerseRef) for ref in inputs.expected_references)
    assert inputs.source_documents
    digest, document = next(iter(inputs.source_documents.items()))
    assert len(digest) == 64
    assert document["sage"]["verse_records"]
    with pytest.raises(TypeError):
        document["sage"]["verse_records"][0]["text"] = "changed"
    with pytest.raises(TypeError):
        inputs.style_profile["profile"]["id"] = "changed"
    policy["checks"]["footnote_review"] = False
    assert inputs.policy["checks"]["footnote_review"] is True
    with pytest.raises(ValidationError):
        replace(inputs, expected_unit_ids=inputs.expected_unit_ids + inputs.expected_unit_ids[:1])
    with pytest.raises(ValidationError):
        replace(inputs, expected_references=("MAT 1:1",))
    with pytest.raises(ValidationError):
        replace(inputs, source_documents={})
    with pytest.raises(ValidationError):
        prepare_execution_inputs(config, job, run, policy)


def test_context_preserves_explicit_missing_wip_placeholder(make_workspace, monkeypatch):
    """Zero-SHA absence evidence remains a coverage gap while actual text requires a source."""
    from sage.numbers.execution import prepare_execution_inputs

    _root, config, job, run = _run(make_workspace, monkeypatch)
    inputs = prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))
    ref = VerseRef("MAT", 1, 1)
    missing = ProjectedUnit(TargetUnit("missing:MAT 1:1", (), "", (), "0" * 64, {}),
                            (ref,), (ref,), "COORDINATE", "UNMAPPED")
    absent = replace(inputs, projected_units=(missing,), style_units=(), expected_unit_ids=(missing.target.unit_id,))
    result = engine.evaluate_prepared_run(absent, model_tasks=None, run_id=run.run_id)
    assert result.units[0].projected.status == "UNMAPPED"
    assert result.coverage["coverage"] != "COMPLETE"
    with pytest.raises(ValidationError):
        replace(absent, projected_units=(replace(missing, target=replace(missing.target, main_text="3 men")),))


def test_context_uses_sealed_checks_after_job_defaults_change(make_workspace, monkeypatch):
    """Current editable defaults and imported profiles cannot replace sealed Run inputs."""
    from sage.numbers.execution import prepare_execution_inputs

    _root, config, job, run = _run(make_workspace, monkeypatch)
    revised = JobStore(config.root, config.settings_path).revise_job(
        job, defaults={"checks": {"number_accuracy": True, "presentation_consistency": False, "footnote_review": False}}
    )
    live_style = storage_layout(config.root).styleguides_root / "numbers/fixture-style/1.yml"
    live_style.unlink()
    inputs = prepare_execution_inputs(config, revised, run, load_nca_run_snapshot(run.root))
    assert inputs.policy["checks"] == {"number_accuracy": True, "presentation_consistency": True, "footnote_review": True}


def test_creation_and_finalization_each_qualify_once(make_workspace, monkeypatch):
    """Structural Job reopening cannot hide loads during creation or completed finalization."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    actual_load = resources.load_reference
    loads = []

    def load(*args, **kwargs):
        """Retain actual qualification evidence for each separate controller attempt."""
        loads.append(args[0])
        return actual_load(*args, **kwargs)

    monkeypatch.setattr(resources, "load_reference", load)
    created = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    assert len(loads) == 1
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    manifest = Path(created["task_manifest_path"])
    execute_nca_task(config, manifest)
    submit_act_task(config, manifest)
    loads.clear()
    assert finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)["status"] == "COMPLETE"
    assert len(loads) == 1


@pytest.mark.parametrize("stage", ["create", "finalize"])
def test_creation_and_finalization_reject_package_inventory_drift(make_workspace, monkeypatch, stage):
    """An unlisted package file is rejected even though all allowlisted bytes still match."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    if stage == "finalize":
        created = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
        monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
        manifest = Path(created["task_manifest_path"])
        execute_nca_task(config, manifest)
        submit_act_task(config, manifest)
    extra = storage_layout(config.root).resources_root / "numbers/SYNTHETIC_NCA_REFERENCE_1/extra.txt"
    extra.write_text("unsealed", encoding="utf-8")
    with pytest.raises(ValidationError):
        if stage == "create":
            create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
        else:
            finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)


@pytest.mark.parametrize("api", ["unit", "run"])
@pytest.mark.parametrize("damage", ["bundle", "style", "checks"])
def test_public_evaluators_reject_unvalidated_inputs(api, damage):
    """Both public boundaries remain strict with no prepared-input escape hatch."""
    from .test_engine import check_policy, projected, reference_bundle, style_profile

    ref = VerseRef("MAT", 1, 1)
    unit = projected(ref, "3 men")
    bundle = reference_bundle(ref)
    profile = style_profile()
    policy = check_policy()
    if damage == "bundle":
        bundle = replace(bundle, qualification_status="BLOCKED")
    elif damage == "style":
        profile["rules"] = {}
    else:
        policy["checks"] = {"number_accuracy": False, "presentation_consistency": False, "footnote_review": False}
    kwargs = dict(bundle=bundle, language="en", language_profile={}, style_profile=profile, check_policy=policy)
    with pytest.raises(ValidationError):
        if api == "unit":
            engine.evaluate_unit(unit, **kwargs)
        else:
            engine.evaluate_run((unit,), run_id="strict", expected_unit_ids=(unit.target.unit_id,), **kwargs)
