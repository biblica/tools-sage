"""Canonical NCA command arguments and local resource inspection."""
from argparse import Namespace

import pytest

from sage.cli import build_parser
from sage.errors import ValidationError
from sage.nca_cli import check_overrides, inspect_numbers_package


def test_task_create_accepts_independent_nca_policy_and_resource_selectors():
    """The existing task family carries NCA setup and explicit check switches."""
    args = build_parser().parse_args(['task', 'create', '--workflow', 'nca', '--operation', 'numbers', '--wip', 'usWIP', '--scope', 'MAT 1:1', '--numbers-package', 'fixture', '--number-style', 'fixture-en/1', '--no-presentation-consistency'])
    assert args.workflow_id == 'nca'
    assert args.operation == 'numbers'
    assert check_overrides(args) == {'presentation_consistency': False}
    assert args.numbers_package == 'fixture'


def test_numbers_import_and_inspection_use_existing_resource_family():
    """Operator resources have explicit local import and inspection commands."""
    imported = build_parser().parse_args(['resource', 'numbers', 'import', '--archive', '/tmp/example.zip'])
    inspected = build_parser().parse_args(['resource', 'numbers', 'inspect', '--package', 'fixture'])
    profile = build_parser().parse_args(['resource', 'number-style', 'import', '--path', '/tmp/profile.yml'])
    assert imported.archive == '/tmp/example.zip'
    assert inspected.package == 'fixture'
    assert profile.path == '/tmp/profile.yml'


def test_omitted_policy_does_not_override_saved_defaults():
    """CLI absence and explicit false remain distinct when creating a Run."""
    assert check_overrides(Namespace()) == {}
    assert check_overrides(Namespace(number_accuracy=True, presentation_consistency=None, footnote_review=False)) == {'number_accuracy': True, 'footnote_review': False}


def test_inspection_rejects_missing_and_escaping_packages(make_workspace):
    """Package selectors cannot escape the local immutable resource library."""
    from sage.registry import load_ecosystem
    config = load_ecosystem(make_workspace(configured=True) / 'ecosystem.yml')
    for package_id in ('missing', '../outside'):
        with pytest.raises(ValidationError):
            inspect_numbers_package(config, package_id)


@pytest.mark.parametrize('workflow,operation,extra', [
    ('rtc', 'rtc', ['--numbers-package', 'fixture']),
    ('stc', 'stc', ['--no-number-accuracy']),
    ('nca', 'numbers', ['--focus', 'unrelated']),
    ('nca', 'numbers', ['--predecessor-task', 'unrelated']),
    ('nca', 'numbers', ['--grammar-override-id', 'unrelated']),
])
def test_task_creation_rejects_cross_workflow_options(make_workspace, monkeypatch, workflow, operation, extra):
    """Accepted parser options cannot silently change meaning in another workflow."""
    from sage.cli import command_act_create
    from sage.registry import load_ecosystem
    config = load_ecosystem(make_workspace(configured=True) / 'ecosystem.yml')
    args = build_parser().parse_args(['task', 'create', '--workflow', workflow, '--operation', operation, '--wip', 'usWIP', '--scope', 'MAT 1'] + extra)
    monkeypatch.setattr('sage.cli._load', lambda _args: (config, None))
    with pytest.raises(ValidationError, match='NCA'):
        command_act_create(args)


@pytest.mark.parametrize('presentation,cap', [(False, 1), (True, 8)])
def test_scoped_preflight_reuses_actual_batches_without_provider(make_workspace, monkeypatch, presentation, cap):
    """Dry-run counts use sealed scope, enabled streams and the real SFM batch cap."""
    from pathlib import Path
    import yaml
    from sage.nca import create_nca_job, create_nca_run, create_nca_task, execute_nca_task
    from sage.numbers import resources, style
    from sage.numbers.execution import prepare_execution_inputs, build_inventory
    from sage.numbers.batching import plan_batches
    from sage.evidence import EvidencePolicy
    from sage.numbers.policy import load_nca_run_snapshot
    from .test_nca_jobs import _prepare_nca_workspace, _route
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    (config.project('usWIP').path / '41MAT.SFM').write_text(
        '\\id MAT Fixture\n\\c 1\n\\s Heading 8\n\\p\n\\v 1 3 men.\\f + \\ft Note 7.\\f*\n\\v 2 4 women.\n')
    profile = root / 'system/config/workflows/nca/profile.yml'
    raw = yaml.safe_load(profile.read_text())
    raw['optimization_policy']['extraction_batch_max_units'] = cap
    profile.write_text(yaml.safe_dump(raw))
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1', style_selector='fixture-style/1')
    run = create_nca_run(config, job_id=job.job_id, scope_value='MAT 1:1-2', checks={'presentation_consistency': presentation})
    created = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    inputs = prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))
    inventory = build_inventory(inputs)
    streams = tuple(x for x in inventory.stream_inputs if x.purpose == 'BODY' or presentation)
    expected = plan_batches(streams, policy=EvidencePolicy.from_mapping(inputs.evidence_policy), max_units=cap)
    counts = {'package': 0, 'style': 0}
    load, validate = resources.load_reference, style.validate_style_profile

    def counted_load(*args, **kwargs):
        """Observe fresh package qualification for this single attempt."""
        counts['package'] += 1
        return load(*args, **kwargs)

    def counted_style(*args, **kwargs):
        """Observe fresh style validation for this single attempt."""
        counts['style'] += 1
        return validate(*args, **kwargs)

    def forbidden(*args, **kwargs):
        """Planning must never construct a completion provider."""
        pytest.fail('provider constructed during preflight')

    monkeypatch.setattr(resources, 'load_reference', counted_load)
    monkeypatch.setattr(style, 'validate_style_profile', counted_style)
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', forbidden)
    result = execute_nca_task(config, Path(created['task_manifest_path']), dry_run=True)
    assert 'preflight' in result, 'scoped preflight is missing'
    plan = result['preflight']
    assert counts == {'package': 1, 'style': 1}
    assert plan['requested_scope'] == run.scope
    assert plan['planned_extraction_calls'] == len(expected.batches)
    assert plan['input_ids'] == [x.input_id for x in streams]
    assert plan['blocked'] == dict(expected.blocked)
    assert plan['indexed_coordinates'] == 1 and plan['unindexed_coordinates'] == 1
    assert plan['style_profile']['selector'] == 'fixture-style/1'
    assert plan['checks']['presentation_consistency'] is presentation
    assert not (Path(created['task_manifest_path']).parent / 'output/model-evidence.json').exists()


def test_completed_task_preflight_keeps_sealed_scope_without_new_provider(make_workspace, monkeypatch):
    """A completed-task dry-run still describes its own sealed scope and initial plan."""
    from pathlib import Path
    from .test_nca_tasks import _run, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    manifest = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    execute_nca_task(config, manifest)

    def forbidden(*args, **kwargs):
        """A completed dry-run cannot require provider construction."""
        pytest.fail('provider constructed during completed preflight')

    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', forbidden)
    result = execute_nca_task(config, manifest, dry_run=True)
    assert result['status'] == 'EXECUTED'
    assert 'preflight' in result, 'completed task omitted sealed preflight'
    assert result['preflight']['requested_scope'] == run.scope


def test_preflight_retains_blocked_streams_and_unlocated_missing_groups(make_workspace, monkeypatch):
    """An empty executable plan cannot hide oversized streams or absent WIP coverage."""
    from dataclasses import replace
    from .test_nca_tasks import _run
    from sage.numbers.execution import prepare_execution_inputs
    from sage.numbers.policy import load_nca_run_snapshot
    from sage.numbers.models import ProjectedUnit, TargetUnit
    from sage.vrs import VerseRef
    from sage.nca_cli import scoped_preflight
    _root, config, job, run = _run(make_workspace, monkeypatch)
    inputs = prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))
    ref = VerseRef('GEN', 10, 1)
    missing = ProjectedUnit(TargetUnit('missing:GEN 10:1', (), '', (), '0' * 64, {}),
                            (ref,), (ref,), 'COORDINATE', 'UNMAPPED')
    inputs = replace(inputs, projected_units=inputs.projected_units + (missing,),
        expected_unit_ids=inputs.expected_unit_ids + (missing.target.unit_id,),
        expected_references=inputs.expected_references + (ref,),
        evidence_policy=dict(inputs.evidence_policy, hard_serialized_bytes=1))
    plan = scoped_preflight(inputs)
    assert plan['planned_extraction_calls'] == 0
    assert set(plan['blocked']) == set(plan['input_ids']) and plan['blocked']
    assert 'missing:GEN 10:1' in plan['missing_owner_ids']
    assert 'missing:GEN 10:1' in plan['protected_group_ids']
