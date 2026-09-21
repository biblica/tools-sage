"""Complete-scope hybrid selection and durable execution integration."""
from dataclasses import replace
from fractions import Fraction

import pytest

from sage.numbers import engine
from sage.numbers.execution import ScopeInventory
from sage.numbers.models import Extraction, NumericExpression, ProjectedUnit, TargetUnit
from sage.vrs import VerseRef


def test_candidate_group_ids_is_exactly_the_indexed_scope_regardless_of_extraction():
    """Candidates are exactly the indexed units; unindexed units never become candidates.

    NCA finds incorrectly reported or missing numbers where a number is already known to be
    expected -- it does not scan unindexed coordinates for undiscovered numbers, so what an
    unindexed unit's extraction happened to contain (found, incomplete, or nothing) is
    irrelevant: it can never become a candidate, only indexed units can.
    """
    owners = tuple(ProjectedUnit(TargetUnit(name, (VerseRef('MAT', 1, verse),),
        '', (), 'a' * 64, {}), (VerseRef('MAT', 1, verse),), (), 'COORDINATE', 'READY')
        for verse, name in enumerate(('expected', 'unexpected', 'uncertain', 'empty'), 1))
    inventory = ScopeInventory(tuple(x.western_references[0] for x in owners), owners,
        frozenset({'expected'}), (), 'MAT 1:1-4')
    extractions = {'expected': Extraction((), 'COMPLETE'),
        'unexpected': Extraction((NumericExpression((Fraction(3),), 'CARDINAL', '3', (0, 1)),), 'COMPLETE'),
        'uncertain': Extraction((), 'UNSUPPORTED', ('unsupported language',)),
        'empty': Extraction((), 'COMPLETE')}
    assert hasattr(engine, 'candidate_group_ids'), 'complete-scope candidate union is missing'
    assert engine.candidate_group_ids(inventory, extractions) == frozenset({'expected'})
    assert len(inventory.projected_units) == 4
    assert engine.candidate_group_ids(inventory, {}) == frozenset({'expected'})


@pytest.mark.parametrize('field,value', [('request_concurrency', 2), ('transient_retries', 2), ('transient_retries', True)])
def test_optimized_policy_rejects_unimplemented_execution_modes(field, value):
    """A sealed setting cannot silently exceed supported concurrency or retry bounds."""
    from sage.errors import ValidationError
    from sage.numbers.policy import validate_optimization_policy
    policy = dict(contract_version='nca-optimization-2.0', reuse_scope='TASK',
        extraction_batch_max_units=8, request_concurrency=1, transient_retries=1)
    policy[field] = value
    with pytest.raises(ValidationError):
        validate_optimization_policy(policy)


def test_partial_checkpoint_resume_never_resubmits_accepted_members(package_root, tmp_path):
    """A durable partial envelope replays its accepted subset and retries only pending siblings."""
    import importlib.util
    assert importlib.util.find_spec('sage.numbers.hybrid') is not None, 'hybrid checkpoint integration is missing'
    from types import SimpleNamespace
    from sage.numbers.hybrid import PhaseSession
    from sage.numbers.replay import PhaseStore
    from sage.numbers.model_tasks import extract_batch_with_retries
    from .test_batch_extraction import batch_fixture, batch_response
    from .test_model_tasks import RecordedExecutor, model_tasks
    batch = batch_fixture()
    partial = batch_response(batch)
    partial['work_units'].pop()
    tasks = model_tasks(package_root, RecordedExecutor([partial]))
    store = PhaseStore(tmp_path, task_fingerprint='a' * 64)
    inputs = SimpleNamespace(policy_bytes=b'original sealed policy', contract_components={'contract': b'2.0'},
        policy={'model_route': dict(tasks.route_snapshot)})
    session = PhaseSession(inputs, tasks, store)
    tasks.configure_phase_execution(session.execute)
    first = tasks.extract_batch(batch, parsing_conventions={})
    assert len(first.value.accepted) == 1
    from sage.numbers.batching import _batch
    child = _batch(batch.inputs[1:], batch.inputs[1].routed_sfm)
    transport = RecordedExecutor([batch_response(child)])
    resumed = model_tasks(package_root, transport)
    replay = PhaseSession(inputs, resumed, store)
    resumed.configure_phase_execution(replay.execute)
    result = extract_batch_with_retries(resumed, batch, parsing_conventions={})
    assert len(result.accepted) == 2 and not result.pending
    assert len(resumed.attempts) == 1
    assert resumed.attempts[0].measurement.unit_ids == (batch.inputs[1].input_id,)
    assert len(replay.checkpoints) == 2 and len(replay.reused) == 1


def test_new_runs_seal_v2_phase_contracts_and_actual_route(make_workspace, monkeypatch):
    """Installed phase drift and unsupported execution settings cannot enter a new Run."""
    from .test_nca_tasks import _run
    from sage.numbers.policy import load_nca_run_snapshot
    root, _config, _job, run = _run(make_workspace, monkeypatch)
    policy = load_nca_run_snapshot(run.root)
    assert policy['schema_version'] == '2.0'
    assert policy['optimization']['request_concurrency'] == 1
    assert set(policy['phase_contracts']['phases']) == {'EXTRACTION', 'CORRESPONDENCE', 'FOOTNOTE', 'GROUP_CORRESPONDENCE'}
    assert policy['phase_contracts']['model_route'] == policy['model_route']
    assert policy['phase_contracts']['files']['system/src/sage/numbers/hybrid.py']


def test_prepared_comparison_consumes_validated_extraction_without_extracting(empty_bundle, monkeypatch):
    """Accuracy and presentation reuse one accepted inventory instead of running extraction again."""
    from .test_engine import style_profile
    from sage.numbers.models import ReferenceBundle
    from sage.numbers.engine import _evaluate_prepared_unit
    ref = VerseRef('MAT', 1, 1)
    unit = ProjectedUnit(TargetUnit('body', (ref,), '3', (), 'a' * 64, {}), (ref,), (ref,), 'COORDINATE', 'READY')
    bundle = replace(empty_bundle, qualification_status='QUALIFIED')
    evidence = Extraction((), 'UNSUPPORTED', ('no admitted body evidence',))
    def forbidden(*args, **kwargs):
        """Reject any repeated extraction at the prepared comparison boundary."""
        raise AssertionError('extraction repeated')
    monkeypatch.setattr(engine, '_extract', forbidden)
    assert 'extraction' in __import__('inspect').signature(_evaluate_prepared_unit).parameters, 'validated extraction injection is missing'
    result = _evaluate_prepared_unit(unit, bundle=bundle, language='en', language_profile={},
        style_profile=style_profile(), checks={'number_accuracy': True, 'presentation_consistency': False, 'footnote_review': False},
        model_tasks=None, extraction=evidence, note_extractions={})
    assert result.extraction is evidence
    # MAT 1:1 is unindexed in this empty bundle, so the supplied (unused) evidence is
    # irrelevant to the outcome: an unindexed single-row unit is always NOT_ASSESSED.
    assert result.final_outcome == 'NOT_ASSESSED'


def test_optimized_inventory_extracts_whole_scope_and_replays_without_calls(make_workspace, monkeypatch):
    """Complete no-number inputs remain in coverage and their accepted batches survive restart."""
    from .test_nca_tasks import _run
    from .test_model_tasks import RecordedExecutor, model_tasks
    from sage.numbers.execution import prepare_execution_inputs, build_inventory
    from sage.numbers.policy import load_nca_run_snapshot
    from sage.numbers.batching import plan_batches
    from sage.evidence import EvidencePolicy
    from sage.numbers.replay import PhaseStore
    from sage.nca import create_nca_task
    from pathlib import Path
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    inputs = prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))
    inventory = build_inventory(inputs)
    batches = plan_batches(inventory.stream_inputs, policy=EvidencePolicy.from_mapping(inputs.evidence_policy)).batches
    responses = [{'schema_version': '2.0', 'phase': 'EXTRACTION', 'batch_id': batch.batch_id,
        'work_units': [{'input_id': x.input_id, 'status': 'COMPLETE', 'limitations': [], 'expressions': []} for x in batch.inputs]} for batch in batches]
    tasks = model_tasks(config.root, RecordedExecutor(responses))
    inputs = replace(inputs, policy=dict(inputs.policy, model_route=tasks.route_snapshot))
    store = PhaseStore(Path(created['task_manifest_path']).parent, task_fingerprint=created['task_fingerprint'])
    assert hasattr(engine, 'evaluate_optimized_run'), 'optimized execution entry point is missing'
    result = engine.evaluate_optimized_run(inputs, model_tasks=tasks, phase_store=store, run_id=run.run_id)
    assert len(result.groups) == len(inputs.expected_unit_ids)
    assert result.metrics['accepted_phase_receipts'] == len(batches)
    # Only indexed body units (and unfiltered style/heading units) are actually planned for
    # extraction (build_inventory's indexed-only filter); an unindexed body unit is correctly
    # never attempted, so its extraction stays UNSUPPORTED rather than COMPLETE.
    assert all(g.extraction.status == 'COMPLETE' for g in result.groups
               if g.projected.precision == 'STYLE_STREAM'
               or g.projected.target.unit_id in inventory.expected_groups)
    assert all(g.extraction.status != 'COMPLETE' for g in result.groups
               if g.projected.precision != 'STYLE_STREAM'
               and g.projected.target.unit_id not in inventory.expected_groups)
    assert not any(c.final_outcome.startswith('PASS') for g in result.groups for c in g.components)
    resumed = model_tasks(config.root, RecordedExecutor([]))
    replay = engine.evaluate_optimized_run(inputs, model_tasks=resumed, phase_store=store, run_id=run.run_id)
    assert replay.groups == result.groups
    assert all(x.measurement.phase == "CORRESPONDENCE" for x in resumed.attempts)
    assert replay.metrics['checkpoint_reuse'] == len(batches)


def test_canonical_optimized_execution_publishes_v2_with_real_checkpoint_binding(make_workspace, monkeypatch):
    """Create, execute, submit, finalize, and reproduce the same receipt-bound grouped result."""
    import json
    from pathlib import Path
    from .test_nca_tasks import _run, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task, finalize_nca_run
    from sage.act_tasks import submit_act_task
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    path = Path(task['task_manifest_path'])
    receipt = execute_nca_task(config, path)
    document = json.loads((path.parent / 'output/model-evidence.json').read_text())
    assert document['schema_version'] == '2.0'
    assert document['metrics']['accepted_phase_receipts'] > 0
    assert receipt['task_fingerprint'] == task['task_fingerprint']
    submit_act_task(config, path)
    final = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    report = Path(final['report_path']).read_bytes()
    assert b'SQS: `NOT_APPLIED`' in report
    again = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    assert Path(again['report_path']).read_bytes() == report


def test_no_admitted_checkpoint_marks_run_failed_with_full_scope_diagnostics(make_workspace, monkeypatch):
    """Terminal provider failures cannot publish a false result or leave an apparently active Run."""
    from pathlib import Path
    import json
    from .test_nca_tasks import _run, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task
    from sage.jobs import JobStore
    from sage.errors import ValidationError
    class FailedTasks(_OfflineTasks):
        """Fail at the physical executor with no accepted phase evidence."""
        def _execute_physical(self, *args, **kwargs):
            """Exercise bounded terminal failures without a fabricated receipt."""
            raise ValidationError('recorded provider outage', code='NCA_MODEL_PROVIDER_FAILED')
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', FailedTasks)
    with pytest.raises(ValidationError):
        execute_nca_task(config, path)
    reopened = JobStore(config.root, config.settings_path).load_run(job, run.run_id)
    assert reopened.status == 'FAILED' and reopened.result == 'FAILED'
    failure = json.loads((path.parent / 'validation/nca-execution-failure.json').read_text())
    assert failure['expected_unit_ids'] == task['expected_unit_ids']
    assert failure['metrics']['accepted_phase_receipts'] == 0
    assert not (path.parent / 'output/model-evidence.json').exists()


@pytest.mark.parametrize('window', ['staged_output', 'staged_receipt', 'manifest', 'canonical_output'])
def test_canonical_publication_interruption_rebuilds_only_uncommitted_evidence(make_workspace, monkeypatch, window):
    """Every publication crash window reconciles canonical bytes without repeating accepted phases."""
    import hashlib
    import json
    from pathlib import Path
    from .test_nca_tasks import _run, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task
    from sage.numbers import replay
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    phase_root = path.parent / 'validation/nca-phases'
    publication = phase_root / 'publication'
    output = path.parent / 'output/model-evidence.json'
    receipt = path.parent / 'validation/llm-execution-receipt.json'
    target = {'staged_output': publication / 'output.json', 'staged_receipt': publication / 'receipt.json',
        'manifest': publication / 'manifest.json', 'canonical_output': output}[window]
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    original_bytes, original_json = replay.atomic_write_bytes, replay.atomic_write_json
    def interrupt_bytes(destination, payload):
        """Interrupt immediately after the selected durable payload write."""
        original_bytes(destination, payload)
        if destination == target:
            raise RuntimeError('publication interrupted')
    def interrupt_json(destination, payload):
        """Interrupt immediately after the manifest establishes publication authority."""
        original_json(destination, payload)
        if destination == target:
            raise RuntimeError('publication interrupted')
    monkeypatch.setattr(replay, 'atomic_write_bytes', interrupt_bytes)
    monkeypatch.setattr(replay, 'atomic_write_json', interrupt_json)
    with pytest.raises(RuntimeError, match='publication interrupted'):
        execute_nca_task(config, path)
    staged = {p.name: p.read_bytes() for p in publication.iterdir()}
    before = json.loads(staged['output.json'])
    attempts = {p.name: p.read_bytes() for p in (phase_root / 'attempts').iterdir()}
    ledger = json.loads((phase_root / 'ledger.json').read_text())
    assert ledger['failures'] and before['metrics']['failed_calls'] > 0
    monkeypatch.setattr(replay, 'atomic_write_bytes', original_bytes)
    monkeypatch.setattr(replay, 'atomic_write_json', original_json)
    committed = window in {'manifest', 'canonical_output'}
    class NoRepeatedAccepted(_OfflineTasks):
        """Permit only previously failed phases during an uncommitted fresh execution."""
        def _execute_physical(self, phase, *args, **kwargs):
            """Reject repeated accepted extraction and all post-manifest physical calls."""
            assert not committed and phase != 'EXTRACTION', 'accepted provider call repeated'
            return super()._execute_physical(phase, *args, **kwargs)
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', NoRepeatedAccepted)
    result = execute_nca_task(config, path)
    assert result['status'] == 'EXECUTED'
    after = json.loads(output.read_text())
    final_receipt = json.loads(receipt.read_text())
    assert output.read_bytes() == (publication / 'output.json').read_bytes()
    assert receipt.read_bytes() == (publication / 'receipt.json').read_bytes()
    assert final_receipt['output_sha256'] == {'output/model-evidence.json': hashlib.sha256(output.read_bytes()).hexdigest()}
    assert final_receipt['phase_count'] == after['metrics']['accepted_phase_receipts']
    assert final_receipt['provider_response_sha256'] == [row['response_sha256']
        for rows in after['model_receipts'].values() for row in rows]
    assert after['metrics']['checkpoints'] == before['metrics']['checkpoints']
    assert all(call in after['metrics']['calls'] for call in before['metrics']['calls'])
    assert all((phase_root / 'attempts' / name).read_bytes() == data for name, data in attempts.items())
    after_ledger = json.loads((phase_root / 'ledger.json').read_text())
    assert after_ledger['entries'] == ledger['entries']
    assert after_ledger['failures'][:len(ledger['failures'])] == ledger['failures']
    if committed:
        assert {p.name: p.read_bytes() for p in publication.iterdir()} == staged
        assert not (phase_root / 'abandoned-publications').exists()
    else:
        assert after['metrics']['checkpoint_reuse'] == before['metrics']['accepted_phase_receipts']
        retired = list((phase_root / 'abandoned-publications').iterdir())
        assert len(retired) == 1
        assert {p.name: p.read_bytes() for p in retired[0].iterdir()} == staged
    for field in ('groups', 'findings', 'coverage', 'summary', 'model_receipts'):
        assert after[field] == before[field]


@pytest.mark.parametrize('invalid_checkpoint', [False, True])
def test_altered_orphan_never_authorizes_canonical_evidence(make_workspace, monkeypatch, invalid_checkpoint):
    """Orphan bytes are retained as diagnostics and cannot override current checkpoint validation."""
    import json
    from pathlib import Path
    from .test_nca_tasks import _run, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task
    from sage.numbers import replay
    from sage.numbers.hybrid import CheckpointFailure
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    phases = path.parent / 'validation/nca-phases'
    orphan = phases / 'publication/output.json'
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    original = replay.atomic_write_bytes
    def interrupt(destination, payload):
        """Leave accepted checkpoints with no committed publication manifest."""
        original(destination, payload)
        if destination == orphan:
            raise RuntimeError('preparation interrupted')
    monkeypatch.setattr(replay, 'atomic_write_bytes', interrupt)
    with pytest.raises(RuntimeError, match='preparation interrupted'):
        execute_nca_task(config, path)
    monkeypatch.setattr(replay, 'atomic_write_bytes', original)
    forged = b'{"summary":{"passes":999},"untrusted":true}'
    orphan.write_bytes(forged)
    if invalid_checkpoint:
        ledger = json.loads((phases / 'ledger.json').read_text())
        row = next(iter(ledger['entries'].values()))
        attempt = phases / 'attempts' / (row['attempt_id'] + '.json')
        value = json.loads(attempt.read_text())
        value['artifact']['raw_response'] = '{}'
        attempt.write_text(json.dumps(value))
        with pytest.raises(CheckpointFailure):
            execute_nca_task(config, path)
        assert orphan.read_bytes() == forged
        assert not (phases / 'abandoned-publications').exists()
        assert not (path.parent / 'output/model-evidence.json').exists()
        assert not (path.parent / 'validation/llm-execution-receipt.json').exists()
    else:
        assert execute_nca_task(config, path)['status'] == 'EXECUTED'
        assert (path.parent / 'output/model-evidence.json').read_bytes() != forged
        retained = list((phases / 'abandoned-publications').glob('*/output.json'))
        assert len(retained) == 1 and retained[0].read_bytes() == forged


@pytest.mark.parametrize('destination', ['output.json', 'receipt.json', 'manifest.json'])
@pytest.mark.parametrize('damage', [None, 'temporary_bytes', 'checkpoint'])
def test_process_death_before_atomic_publication_replace_recovers(make_workspace, monkeypatch, destination, damage):
    """Actual process death leaves helper temporaries without allowing them to authorize evidence."""
    import hashlib
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    from .test_nca_tasks import _run, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task
    from sage.numbers.hybrid import CheckpointFailure
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    phases = path.parent / 'validation/nca-phases'
    publication = phases / 'publication'
    script = '''"""Exit without finally cleanup immediately before a publication temporary is installed."""
import os
from pathlib import Path
import sys
import pytest
from sage import atomic
from sage.nca import execute_nca_task
from sage.registry import load_ecosystem
from tests.numbers.test_nca_tasks import _OfflineTasks
from tests.numbers.test_nca_jobs import _route
manifest = Path(sys.argv[2])
target = manifest.parent / 'validation/nca-phases/publication' / sys.argv[3]
original = atomic.os.replace
def die(source, destination):
    """Leave the fully flushed atomic temporary and real dead-owner lock records."""
    if destination == target:
        os._exit(73)
    return original(source, destination)
with pytest.MonkeyPatch.context() as patch:
    _route(patch)
    patch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    patch.setattr(atomic.os, 'replace', die)
    execute_nca_task(load_ecosystem(Path(sys.argv[1])), manifest)
'''
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(Path(__file__).resolve().parents[2] / 'src'),
        str(Path(__file__).resolve().parents[2]))), PYTHONDONTWRITEBYTECODE='1', SAGE_DISABLE_OPERATIONAL_LOG='1')
    child = subprocess.run([sys.executable, '-c', script, str(config.settings_path), str(path), destination],
        env=env, capture_output=True, text=True, timeout=30, check=False)
    assert child.returncode == 73, child.stderr + child.stdout
    temporary, = publication.glob('.' + destination + '.*.tmp')
    assert not (publication / 'manifest.json').exists()
    before = json.loads((temporary if destination == 'output.json' else publication / 'output.json').read_text())
    ledger = json.loads((phases / 'ledger.json').read_text())
    attempts = {p.name: p.read_bytes() for p in (phases / 'attempts').iterdir()}
    assert ledger['failures'] and before['metrics']['failed_calls'] > 0
    if damage in {'temporary_bytes', 'checkpoint'}:
        temporary.write_bytes(b'altered temporary bytes are not authority')
    staged = {p.name: p.read_bytes() for p in publication.iterdir()}
    class NoRepeatedAccepted(_OfflineTasks):
        """Allow fresh failed-phase retries while rejecting every repeated accepted extraction."""
        def _execute_physical(self, phase, *args, **kwargs):
            """An accepted checkpoint must supply its result without another physical request."""
            assert phase != 'EXTRACTION', 'accepted provider call repeated'
            return super()._execute_physical(phase, *args, **kwargs)
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', NoRepeatedAccepted)
    if damage == 'checkpoint':
        row = next(iter(ledger['entries'].values()))
        attempt = phases / 'attempts' / (row['attempt_id'] + '.json')
        value = json.loads(attempt.read_text())
        value['artifact']['raw_response'] = '{}'
        attempt.write_text(json.dumps(value))
        with pytest.raises(CheckpointFailure):
            execute_nca_task(config, path)
        assert {p.name: p.read_bytes() for p in publication.iterdir()} == staged
        assert not (phases / 'abandoned-publications').exists()
        assert not (path.parent / 'output/model-evidence.json').exists()
        assert not (path.parent / 'validation/llm-execution-receipt.json').exists()
        return
    assert execute_nca_task(config, path)['status'] == 'EXECUTED'
    output = path.parent / 'output/model-evidence.json'
    receipt = path.parent / 'validation/llm-execution-receipt.json'
    after, final_receipt = json.loads(output.read_text()), json.loads(receipt.read_text())
    assert output.read_bytes() == (publication / 'output.json').read_bytes()
    assert receipt.read_bytes() == (publication / 'receipt.json').read_bytes()
    assert final_receipt['output_sha256'] == {'output/model-evidence.json': hashlib.sha256(output.read_bytes()).hexdigest()}
    assert final_receipt['phase_count'] == after['metrics']['accepted_phase_receipts']
    assert final_receipt['provider_response_sha256'] == [row['response_sha256']
        for rows in after['model_receipts'].values() for row in rows]
    assert after['metrics']['checkpoint_reuse'] == before['metrics']['accepted_phase_receipts']
    assert after['metrics']['checkpoints'] == before['metrics']['checkpoints']
    assert all(call in after['metrics']['calls'] for call in before['metrics']['calls'])
    assert all((phases / 'attempts' / name).read_bytes() == data for name, data in attempts.items())
    after_ledger = json.loads((phases / 'ledger.json').read_text())
    assert after_ledger['entries'] == ledger['entries']
    assert after_ledger['failures'][:len(ledger['failures'])] == ledger['failures']
    retired, = (phases / 'abandoned-publications').iterdir()
    assert {p.name: p.read_bytes() for p in retired.iterdir()} == staged
    for field in ('groups', 'findings', 'coverage', 'summary', 'model_receipts'):
        assert after[field] == before[field]


def test_failure_diagnostic_reader_authenticates_durable_membership(tmp_path):
    """Changing failure bytes cannot change reported physical attempts during publication replay."""
    import json
    from sage.numbers.replay import PhaseStore, PhaseKey
    from sage.errors import ValidationError
    store = PhaseStore(tmp_path, task_fingerprint='a' * 64)
    key = PhaseKey.build(phase='EXTRACTION', task_fingerprint='a' * 64, input_ids=('input-1',),
        input_components={'input': b'exact'}, policy_bytes=b'policy', route={}, contract_components={'contract': b'2'}, validator_version='2')
    store.record_failure(key, {'code': 'recorded', 'attempts': []})
    assert hasattr(store, 'failure_diagnostics'), 'authenticated failure replay is missing'
    assert store.failure_diagnostics()[0]['diagnostic']['code'] == 'recorded'
    file = next((tmp_path / 'validation/nca-phases/attempts').glob('*.json'))
    raw = json.loads(file.read_text())
    raw['artifact']['code'] = 'invented'
    file.write_text(json.dumps(raw))
    with pytest.raises(ValidationError):
        store.failure_diagnostics()


@pytest.mark.parametrize('damage', [
    'calls', 'request_id', 'members', 'key', 'planned_calls',
    'missing_planned_calls',
])
def test_publication_rejects_self_consistent_metrics_forgery(make_workspace, monkeypatch, damage):
    """Recomputed aggregate counters cannot authorize an invented physical request association."""
    from copy import deepcopy
    from pathlib import Path
    from .test_nca_tasks import _run_with_extra_indexed_verse, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task
    from sage.numbers.replay import PhaseStore
    from sage.numbers.telemetry import summarize_calls
    from sage.errors import ValidationError
    # MAT 1:1 (fixture default) and MAT 1:2 (added here) are both indexed and batch
    # together, so planned_extraction_calls (batch count) genuinely differs from
    # len(input_ids) (stream count) -- required for the 'planned_calls' forgery below
    # to actually change anything an honest recomputation would catch.
    _root, config, job, run = _run_with_extra_indexed_verse(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    original = PhaseStore.prepare_publication
    def forge(self, output, receipt, **kwargs):
        """Change only staged metrics and rehash them as an adversarial caller could."""
        from sage.hashing import sha256_bytes
        import json
        changed = deepcopy(output)
        metrics = changed['metrics']
        if damage == 'calls':
            metrics['calls'] = []
            metrics.update(summarize_calls(()))
        elif damage == 'request_id':
            metrics['checkpoints'][0]['request_id'] = 'fabricated-request'
        elif damage == 'planned_calls':
            metrics['planning']['planned_extraction_calls'] = len(metrics['planning']['input_ids'])
        elif damage == 'missing_planned_calls':
            del metrics['planning']['planned_extraction_calls']
        elif damage == 'members':
            metrics['batch_members'] -= len(metrics['checkpoints'][0]['accepted_input_ids'])
            metrics['checkpoints'][0]['accepted_input_ids'] = []
        else:
            metrics['checkpoints'][0]['key']['input_sha256'] = 'a' * 64
        payload = (json.dumps(changed, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
        receipt = dict(receipt, output_sha256={'output/model-evidence.json': sha256_bytes(payload)})
        return original(self, changed, receipt, **kwargs)
    monkeypatch.setattr(PhaseStore, 'prepare_publication', forge)
    with pytest.raises(ValidationError):
        execute_nca_task(config, path)
    assert not (path.parent / 'output/model-evidence.json').exists()


def _historical_run(make_workspace, monkeypatch):
    """Create an actual old-policy lifecycle fixture using the preserved v1 contracts."""
    from sage import nca
    from sage.hashing import sha256_file
    from .test_nca_tasks import _run
    build = nca.build_nca_run_snapshot
    def legacy(config, job, **kwargs):
        """Seal the exact original three-phase policy shape before simulating an upgrade."""
        policy = dict(build(config, job, **kwargs))
        policy['schema_version'] = '1.0'
        policy.pop('optimization')
        policy.pop('phase_contracts')
        policy['model_contract'] = dict(policy['model_contract'], prompt_task_contract_version='nca-model-phases-1.0',
            structured_response_schema_sha256=sha256_file(config.root / 'system/config/schemas/nca-extraction.schema.yml'))
        return policy
    monkeypatch.setattr(nca, 'build_nca_run_snapshot', legacy)
    return _run(make_workspace, monkeypatch)


def test_completed_v1_report_reproduction_preserves_historical_evidence_after_upgrade(make_workspace, monkeypatch):
    """Completed v1 control, submission, original evidence, and report survive installed contract drift."""
    import json
    from pathlib import Path
    from sage.nca import create_nca_task, execute_nca_task, finalize_nca_run
    from sage.act_tasks import submit_act_task
    from .test_nca_tasks import _OfflineTasks
    _root, config, job, run = _historical_run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    execute_nca_task(config, path)
    submit_act_task(config, path)
    final = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    output = path.parent / 'output/model-evidence.json'
    assert json.loads(output.read_text())['schema_version'] == '1.0'
    original = {p: p.read_bytes() for p in (output, path, path.parent / 'validation/submission.json',
        path.parent / 'validation/llm-execution-receipt.json', run.root / 'check-policy.json')}
    report = Path(final['report_path']).read_bytes()
    for relative in ('system/skills/nca-numbers/SKILL.md', 'system/config/schemas/nca-extraction.schema.yml'):
        installed = config.root / relative
        installed.write_bytes(installed.read_bytes() + b'\n# installed upgrade\n')
    Path(final['report_path']).unlink()
    regenerated = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    assert Path(regenerated['report_path']).read_bytes() == report
    assert all(p.read_bytes() == data for p, data in original.items())
    original_output = json.loads(output.read_text())
    original_output['summary']['passes'] += 1
    output.write_text(json.dumps(original_output))
    from sage.errors import ValidationError
    with pytest.raises(ValidationError):
        finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)


def test_unfinished_v1_execution_rejects_installed_contract_drift(make_workspace, monkeypatch):
    """Historical read eligibility never authorizes stale in-flight execution."""
    from pathlib import Path
    from sage.nca import create_nca_task, execute_nca_task
    from sage.errors import ValidationError
    _root, config, job, run = _historical_run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    contract = config.root / 'system/skills/nca-numbers/SKILL.md'
    contract.write_bytes(contract.read_bytes() + b'\n# installed upgrade\n')
    with pytest.raises(ValidationError):
        execute_nca_task(config, Path(task['task_manifest_path']))


def test_all_pending_envelope_retries_transport_and_retains_both_physical_attempts(package_root, tmp_path):
    """An all-pending validated envelope must not satisfy its own transient retry from cache."""
    from types import SimpleNamespace
    from sage.numbers.hybrid import PhaseSession
    from sage.numbers.replay import PhaseStore
    from sage.numbers.model_tasks import extract_batch_with_retries
    from .test_batch_extraction import batch_fixture, batch_response
    from .test_model_tasks import RecordedExecutor, model_tasks
    batch = batch_fixture()
    pending = dict(batch_response(batch), work_units=[])
    tasks = model_tasks(package_root, RecordedExecutor([pending, batch_response(batch)]))
    inputs = SimpleNamespace(policy_bytes=b'sealed', contract_components={'version': b'2'}, policy={'model_route': tasks.route_snapshot})
    session = PhaseSession(inputs, tasks, PhaseStore(tmp_path, task_fingerprint='a' * 64))
    tasks.configure_phase_execution(session.execute)
    result = extract_batch_with_retries(tasks, batch, parsing_conventions={})
    assert len(result.accepted) == 2 and not result.pending
    assert len(tasks.attempts) == 2 and len(session.durable_calls()) == 2
    assert len(session.checkpoints) == 1 and not session.reused


def test_checkpoint_commit_failure_propagates_without_retry_or_false_result(package_root, tmp_path, monkeypatch):
    """Persistence failure is distinct from model insufficiency and cannot be swallowed or retried."""
    from types import SimpleNamespace
    from sage.errors import ValidationError
    from sage.numbers.hybrid import PhaseSession, CheckpointFailure
    from sage.numbers.replay import PhaseStore
    from sage.numbers.model_tasks import extract_batch_with_retries
    from .test_batch_extraction import batch_fixture, batch_response
    from .test_model_tasks import RecordedExecutor, model_tasks
    batch = batch_fixture()
    tasks = model_tasks(package_root, RecordedExecutor([batch_response(batch)]))
    inputs = SimpleNamespace(policy_bytes=b'sealed', contract_components={'version': b'2'}, policy={'model_route': tasks.route_snapshot})
    store = PhaseStore(tmp_path, task_fingerprint='a' * 64)
    session = PhaseSession(inputs, tasks, store)
    tasks.configure_phase_execution(session.execute)
    def fail(*args, **kwargs):
        """Simulate controller admission failure after a valid physical response."""
        raise ValidationError('durable ledger failed', code='NCA_CHECKPOINT_INVALID')
    monkeypatch.setattr(store, 'commit', fail)
    with pytest.raises(CheckpointFailure):
        extract_batch_with_retries(tasks, batch, parsing_conventions={})
    assert len(tasks.attempts) == 1 and not session.checkpoints


@pytest.mark.skipif(not hasattr(__import__('os'), 'fork'), reason='POSIX real process-death test; Windows guard has dedicated platform tests')
def test_dead_canonical_executor_recovers_outer_lock_and_publication(make_workspace, monkeypatch):
    """Actual process death after canonical output must not strand the outer execution lock."""
    import os
    from pathlib import Path
    from .test_nca_tasks import _run, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task
    from sage.numbers import replay
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    child = os.fork()
    if child == 0:
        original = replay.atomic_write_bytes
        def die(destination, payload):
            """Leave real abandoned directory ownership after the first canonical publication write."""
            original(destination, payload)
            if destination == path.parent / 'output/model-evidence.json':
                os._exit(17)
        replay.atomic_write_bytes = die
        execute_nca_task(config, path)
        os._exit(99)
    _pid, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 17
    class NoCalls(_OfflineTasks):
        """Prove that fresh ownership recovery requires no repeated completion call."""
        def _execute_physical(self, *args, **kwargs):
            """A persisted publication's replay must never invoke the provider."""
            raise AssertionError('repeated provider call')
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', NoCalls)
    assert execute_nca_task(config, path)['status'] == 'EXECUTED'
    assert (path.parent / 'locks/execution.lock.guard').is_file()
    assert not (path.parent / 'locks/execution.lock').exists()


@pytest.mark.parametrize('presentation', [False, True])
def test_note_and_heading_numbers_never_become_body_accuracy_candidates(make_workspace, monkeypatch, presentation):
    """Separate note/heading extraction preserves coverage and obeys disabled presentation calls."""
    from sage.numbers.execution import ExecutionInputs, build_inventory, prepare_execution_inputs
    from sage.numbers.target import target_units, extract_heading_units
    from sage.usj import compile_usfm_text
    from sage.hashing import sha256_bytes
    from sage.numbers.policy import load_nca_run_snapshot
    from sage.numbers.batching import plan_batches
    from sage.evidence import EvidencePolicy
    from sage.numbers.replay import PhaseStore
    from .test_nca_tasks import _run
    from .test_model_tasks import RecordedExecutor, model_tasks
    from .test_extraction import expression
    import json
    _root, config, job, run = _run(make_workspace, monkeypatch)
    base = prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))
    document = compile_usfm_text('\\id MAT\n\\c 1\n\\s1 Heading 8\n\\p\n\\v 2 No numbers.\\f + \\ft Note 7\\f*\n')
    digest = sha256_bytes(json.dumps(document).encode())
    targets = target_units(document, source_sha256=digest)
    headings = extract_heading_units(document, source_sha256=digest)
    projected = tuple(ProjectedUnit(x, x.target_references, x.target_references, 'COORDINATE', 'READY') for x in targets)
    policy = dict(base.policy, checks={'number_accuracy': True, 'presentation_consistency': presentation, 'footnote_review': True})
    inputs = ExecutionInputs(base.bundle, base.style_profile, policy, projected, headings,
        tuple(x.unit_id for x in (*targets, *headings)), tuple(r for x in targets for r in x.target_references),
        {digest: document}, 'MAT 1:2', base.policy_bytes, base.contract_components, base.evidence_policy)
    streams = tuple(x for x in build_inventory(inputs).stream_inputs if x.purpose == 'BODY' or presentation)
    batches = plan_batches(streams, policy=EvidencePolicy.from_mapping(inputs.evidence_policy)).batches
    responses = []
    for batch in batches:
        items = []
        for stream in batch.inputs:
            digit = '7' if stream.purpose == 'NOTE_STYLE' else '8'
            expressions = [] if stream.purpose == 'BODY' else [expression('e1', digit, stream.text.index(digit), stream.text.index(digit) + 1, digit, stream_id=stream.stream_id)]
            items.append({'input_id': stream.input_id, 'status': 'COMPLETE', 'limitations': [], 'expressions': expressions})
        responses.append({'schema_version': '2.0', 'phase': 'EXTRACTION', 'batch_id': batch.batch_id, 'work_units': items})
    tasks = model_tasks(config.root, RecordedExecutor(responses))
    inputs = replace(inputs, policy=dict(inputs.policy, model_route=tasks.route_snapshot))
    result = engine.evaluate_optimized_run(inputs, model_tasks=tasks,
        phase_store=PhaseStore(run.root, task_fingerprint='a' * 64), run_id=run.run_id)
    assert len(result.groups) == len(targets) + len(headings) and headings
    assert result.coverage['candidate_group_ids'] == ()
    assert not any(x['category'] == 'ACCURACY' for x in result.findings)
    # MAT 1:2 is unindexed in this fixture, so its BODY/NOTE_STYLE streams are never planned
    # (build_inventory's indexed-only filter); only the (unfiltered) heading stream remains,
    # and only when presentation checks are enabled.
    assert len(tasks.attempts) == (1 if presentation else 0)
    heading = next(x for x in result.groups if x.projected.precision == 'STYLE_STREAM')
    assert heading.alignment_status == 'NOT_ASSESSED' and not heading.components
    if not presentation:
        assert heading.extraction.status == 'UNSUPPORTED'
        assert 'PRESENTATION_CHECK_DISABLED' in heading.limitations
    from sage.nca import _provenance
    from sage.numbers.results_v2 import numbers_result_document_v2
    from sage.numbers.results import validate_numbers_result
    receipts = {phase: [] for phase in ('EXTRACTION', 'CORRESPONDENCE', 'FOOTNOTE', 'GROUP_CORRESPONDENCE')}
    for checkpoint in result.metrics['checkpoints']:
        receipts[checkpoint['receipt']['phase']].append(checkpoint['receipt'])
    serialized = numbers_result_document_v2(result, provenance=_provenance(job, run, inputs.policy),
        check_policy=inputs.policy, model_receipts=receipts)
    assert validate_numbers_result(serialized, expected_unit_ids=inputs.expected_unit_ids,
        allowed_evidence_ids=tuple(inputs.bundle.provenance)) == serialized


def test_missing_wip_remains_unsupported_and_visible_in_final_scope(make_workspace, monkeypatch):
    """An expected missing target cannot be replaced by a COMPLETE empty extraction."""
    from sage.numbers.execution import prepare_execution_inputs
    from sage.numbers.policy import load_nca_run_snapshot
    from sage.numbers.replay import PhaseStore
    from .test_nca_tasks import _run, _OfflineTasks
    _root, config, job, run = _run(make_workspace, monkeypatch)
    inputs = prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))
    original = inputs.projected_units[0]
    ref = original.western_references[0]
    absent = replace(original, target=TargetUnit('missing:' + ref.label(), (), '', (), '0' * 64, {}), status='UNMAPPED', target_western_mapping={})
    projected = (absent,) + inputs.projected_units[1:]
    inputs = replace(inputs, projected_units=projected, expected_unit_ids=tuple(x.target.unit_id for x in projected))
    tasks = _OfflineTasks(config, expected_route_id='nca-route-fixture')
    result = engine.evaluate_optimized_run(inputs, model_tasks=tasks,
        phase_store=PhaseStore(run.root, task_fingerprint='a' * 64), run_id=run.run_id)
    missing = result.groups[0]
    assert missing.extraction.status == 'UNSUPPORTED' and not missing.extraction.expressions
    assert missing.components[0].final_outcome == 'INSUFFICIENT_EVIDENCE'
    assert missing.projected.target.unit_id in result.coverage['candidate_group_ids']
    assert result.coverage['coverage'] == 'PARTIAL'


def test_new_snapshot_uses_governed_batch_cap_and_rejects_unsupported_concurrency(make_workspace, monkeypatch):
    """Activation must honor the configured cap and reject a policy the executor cannot implement."""
    import yaml
    from .test_nca_tasks import _run
    from sage.numbers.policy import build_nca_run_snapshot, load_nca_run_snapshot
    from sage.errors import ValidationError
    _root, config, job, run = _run(make_workspace, monkeypatch)
    sealed = load_nca_run_snapshot(run.root)
    path = config.root / 'system/config/workflows/nca/profile.yml'
    profile = yaml.safe_load(path.read_text())
    profile['optimization_policy']['extraction_batch_max_units'] = 4
    path.write_text(yaml.safe_dump(profile))
    snapshot = build_nca_run_snapshot(config, job, checks=sealed['checks'], route=sealed['model_route'])
    assert snapshot['optimization']['extraction_batch_max_units'] == 4
    profile['optimization_policy']['request_concurrency'] = 2
    path.write_text(yaml.safe_dump(profile))
    with pytest.raises(ValidationError):
        build_nca_run_snapshot(config, job, checks=sealed['checks'], route=sealed['model_route'])


def test_mixed_terminal_invalid_batch_publication_replays_exact_failure_evidence(make_workspace, monkeypatch):
    """A mixed published result must preserve the terminal invalid member's reason after interruption."""
    import json
    from pathlib import Path
    from dataclasses import replace
    from .test_nca_tasks import _run_with_extra_indexed_verse, _OfflineTasks, _EmptyTransport
    from sage.nca import create_nca_task, execute_nca_task
    from sage.numbers import replay
    # MAT 1:1 (fixture default) and MAT 1:2 (added here) are both indexed and batch
    # together, giving this test a genuine valid sibling alongside the corrupted member.
    _root, config, job, run = _run_with_extra_indexed_verse(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    class InvalidMember(_EmptyTransport):
        """Return one persistently malformed member among valid empty extractions."""
        def execute(self, request):
            """Leave all accepted siblings intact while forcing bounded invalid singleton failure."""
            response = super().execute(request)
            payload = json.loads(request.prompt)['input']
            raw = json.loads(response.content)
            # MAT 1:1 and MAT 1:2 are the indexed verses in this fixture and batch together;
            # corrupt one while the other stays a valid sibling in the same batch.
            for supplied, result in zip(payload['work_units'], raw['work_units']):
                if 'Verse 1.' in supplied['text']:
                    result['expressions'] = [{'invented': True}]
            return replace(response, content=json.dumps(raw))
    class MixedTasks(_OfflineTasks):
        """Use the real batch validator and physical evidence recorder."""
        def __init__(self, *args, **kwargs):
            """Provide the recorded mixed-response transport."""
            super().__init__(*args, **kwargs)
            self._executor = InvalidMember()
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', MixedTasks)
    original = replay.atomic_write_bytes
    def interrupt(destination, payload):
        """Interrupt only after a fully validated mixed result is staged and first published."""
        original(destination, payload)
        if destination == path.parent / 'output/model-evidence.json':
            raise RuntimeError('mixed publication interrupted')
    monkeypatch.setattr(replay, 'atomic_write_bytes', interrupt)
    with pytest.raises(RuntimeError, match='mixed publication interrupted'):
        execute_nca_task(config, path)
    output = (path.parent / 'output/model-evidence.json').read_bytes()
    assert b'NCA_BATCH_SINGLETON_FAILED' in output
    monkeypatch.setattr(replay, 'atomic_write_bytes', original)
    class NoCalls(_OfflineTasks):
        """Deny new physical requests during staged failure-evidence reconstruction."""
        def _execute_physical(self, *args, **kwargs):
            """Recovered publication uses authenticated original failed and accepted attempts."""
            raise AssertionError('repeated completion')
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', NoCalls)
    assert execute_nca_task(config, path)['status'] == 'EXECUTED'
    assert (path.parent / 'output/model-evidence.json').read_bytes() == output
