"""Same-task checkpoints admit only current, receipt-bound physical evidence."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import importlib
import json
from pathlib import Path
import shutil

import pytest

from sage.errors import ValidationError
from sage.numbers.extraction import validate_batch_extraction_response
from .test_batch_extraction import batch_fixture, batch_response
from .test_model_tasks import RecordedExecutor, model_tasks


def replay_module():
    """Make the missing implementation an explicit initial behavioral failure."""
    spec = importlib.util.find_spec('sage.numbers.replay')
    assert spec is not None, 'verified phase checkpoint storage is not implemented'
    return importlib.import_module('sage.numbers.replay')


def plain(value):
    """Copy immutable evidence containers while preserving the raw response string."""
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


@pytest.fixture
def recorded(tmp_path, package_root):
    """Execute Task 4's two-unit response entirely inside a disposable app fixture."""
    root = tmp_path / 'app'
    for name in ('config', 'skills'):
        shutil.copytree(package_root / 'system' / name, root / 'system' / name)
    batch = batch_fixture()
    tasks = model_tasks(root, RecordedExecutor([batch_response(batch)]))
    result = tasks.extract_batch(batch, parsing_conventions={})
    return root, batch, tasks, result


@pytest.fixture
def phase_key(recorded):
    """Hash actual sealed stream, contract, and routed request evidence."""
    root, batch, tasks, result = recorded
    module = replay_module()
    return module.PhaseKey.build(phase='EXTRACTION', task_fingerprint='a' * 64,
        input_ids=tuple(value.input_id for value in batch.inputs),
        input_components={'source': batch.routed_sfm.encode(), 'package': b'qualified fixture',
                          'mapping': b'MAT 5:1-2', 'profile': b'configured number style'},
        policy_bytes=b'sealed policy', route=plain(tasks.route_snapshot),
        contract_components={'schema': (root / 'system/config/schemas/nca-extraction-v2.schema.yml').read_bytes(),
            'skill': (root / 'system/skills/nca-numbers/references/TARGET-EXTRACTION-CONTRACT.md').read_bytes(),
            'phase': result.receipt.task_version.encode()}, validator_version='nca-extraction-2.0')


@pytest.fixture
def artifact(recorded):
    """Retain exact bytes and the uniquely associated physical attempt."""
    _, _, tasks, result = recorded
    attempt = next(value for value in tasks.attempts if value.measurement.request_id == result.request_id)
    return {'receipt': result.receipt.to_dict(), 'raw_response': result.raw_response,
        'request_id': result.request_id, 'route_snapshot': plain(tasks.route_snapshot),
        'attempt': {'measurement': plain(asdict(attempt.measurement)), 'request': plain(attempt.request),
                    'raw_response': attempt.raw_response, 'response_identity': plain(attempt.response_identity)},
        'item_sha256': dict(result.value.item_sha256)}


@pytest.fixture
def validator(recorded):
    """Revalidate protected batch evidence with the actual current phase validator."""
    _, batch, _, _ = recorded
    def validate(value):
        """Reconcile exact surfaces, identities, coverage, and local item hashes."""
        result = validate_batch_extraction_response(batch, json.loads(value['raw_response']))
        assert dict(result.item_sha256) == value['item_sha256']
        return result
    return validate


@pytest.fixture
def phase_store(tmp_path):
    """Open a fresh confined task directory with one governed identity."""
    root = tmp_path / 'task'
    root.mkdir()
    return replay_module().PhaseStore(root, task_fingerprint='a' * 64)


def test_changed_phase_identity_cannot_reuse_evidence(phase_store, phase_key, artifact, validator):
    """A valid earlier response is not authority for different source inputs."""
    phase_store.commit(phase_key, artifact, validate=validator)
    assert phase_store.lookup(phase_key, validate=validator) is not None
    changed = replace(phase_key, input_sha256='f' * 64)
    assert phase_store.lookup(changed, validate=validator) is None


def test_checkpoint_api_is_available():
    """The replay boundary must expose a concrete store before phases can persist."""
    assert replay_module().PhaseStore is not None


@pytest.mark.parametrize('field', ['route_sha256', 'policy_sha256', 'contract_sha256', 'validator_version', 'input_ids'])
def test_other_identity_changes_miss(phase_store, phase_key, artifact, validator, field):
    """Route, policy, contracts, validator, and ordered inputs independently fence reuse."""
    phase_store.commit(phase_key, artifact, validate=validator)
    replacement = tuple(reversed(phase_key.input_ids)) if field == 'input_ids' else ('future' if field == 'validator_version' else 'f' * 64)
    assert phase_store.lookup(replace(phase_key, **{field: replacement}), validate=validator) is None


def test_restart_after_accepted_extraction_reuses_without_call(phase_store, phase_key, artifact, validator, recorded):
    """A fresh store revalidates prior accepted evidence without a provider completion."""
    phase_store.commit(phase_key, artifact, validate=validator)
    resumed = replay_module().PhaseStore(phase_store.task_root, task_fingerprint=phase_key.task_fingerprint)
    result = resumed.lookup(phase_key, validate=validator)
    assert len(result.accepted) == 2 and not result.pending
    assert len(recorded[2].attempts) == 1


def test_changed_job_defaults_do_not_override_sealed_inputs(phase_store, phase_key, artifact, validator, tmp_path):
    """Replay keys depend on sealed bytes rather than mutable Job defaults."""
    defaults = tmp_path / 'job-defaults.json'
    defaults.write_text('{"checks": "on", "profile": "first"}')
    phase_store.commit(phase_key, artifact, validate=validator)
    defaults.write_text('{"checks": "off", "profile": "second"}')
    assert len(phase_store.lookup(phase_key, validate=validator).accepted) == 2


@pytest.mark.parametrize('damage', ['raw', 'extra', 'version', 'owner', 'hash', 'path'])
def test_corrupt_published_evidence_is_rejected(phase_store, phase_key, artifact, validator, damage):
    """Ledger membership never excuses damaged content, identity, or path escapes."""
    checkpoint = phase_store.commit(phase_key, artifact, validate=validator)
    path = phase_store.task_root / 'validation/nca-phases/attempts' / f'{checkpoint}.json'
    ledger_path = phase_store.task_root / 'validation/nca-phases/ledger.json'
    value = json.loads(path.read_text())
    if damage == 'raw':
        value['artifact']['raw_response'] += ' '
    elif damage == 'extra':
        value['injected'] = True
    elif damage == 'version':
        value['schema_version'] = 'future'
    elif damage == 'owner':
        value['task_fingerprint'] = 'b' * 64
    else:
        ledger = json.loads(ledger_path.read_text())
        row = next(iter(ledger['entries'].values()))
        row['artifact_sha256' if damage == 'hash' else 'attempt_id'] = '0' * 64 if damage == 'hash' else '../../outside'
        ledger_path.write_text(json.dumps(ledger))
    if damage not in {'hash', 'path'}:
        path.write_text(json.dumps(value))
    with pytest.raises(ValidationError):
        phase_store.lookup(phase_key, validate=validator)


def test_wrong_task_is_rejected(phase_store, phase_key, artifact, validator):
    """A key and existing ledger cannot cross task ownership."""
    with pytest.raises(ValidationError):
        phase_store.commit(replace(phase_key, task_fingerprint='b' * 64), artifact, validate=validator)
    phase_store.commit(phase_key, artifact, validate=validator)
    foreign = replay_module().PhaseStore(phase_store.task_root, task_fingerprint='b' * 64)
    with pytest.raises(ValidationError):
        foreign.lookup(replace(phase_key, task_fingerprint='b' * 64), validate=validator)


@pytest.mark.parametrize('damage', ['raw', 'request_id', 'request', 'route', 'item', 'receipt_extra', 'measurement'])
def test_physical_attempt_must_match_receipt(phase_store, phase_key, artifact, validator, damage):
    """Different requests and reserialized response bytes cannot borrow a receipt."""
    changed = deepcopy(artifact)
    if damage == 'raw':
        changed['raw_response'] = json.dumps(json.loads(changed['raw_response']), indent=2)
    elif damage == 'request_id':
        changed['attempt']['measurement']['request_id'] = 'other-physical-call'
    elif damage == 'request':
        changed['attempt']['request']['prompt'] += ' '
    elif damage == 'route':
        changed['route_snapshot']['model'] = 'different'
    elif damage == 'item':
        changed['item_sha256'][phase_key.input_ids[0]] = '0' * 64
    elif damage == 'receipt_extra':
        changed['receipt']['extra'] = True
    else:
        changed['attempt']['measurement']['reused'] = True
    with pytest.raises((ValidationError, AssertionError)):
        phase_store.commit(phase_key, changed, validate=validator)
    assert phase_store.lookup(phase_key, validate=validator) is None


def test_validation_failure_keeps_orphan_out_of_ledger(phase_store, phase_key, artifact, validator):
    """An interrupted or invalid attempt remains immutable and never gains membership."""
    def interrupted(value):
        """Crash at validation after the raw attempt has reached disk."""
        raise RuntimeError('crash before ledger publication')
    with pytest.raises(RuntimeError):
        phase_store.commit(phase_key, artifact, validate=interrupted)
    attempts = list((phase_store.task_root / 'validation/nca-phases/attempts').glob('*.json'))
    assert len(attempts) == 1
    before = attempts[0].read_bytes()
    assert phase_store.lookup(phase_key, validate=validator) is None
    checkpoint = phase_store.commit(phase_key, artifact, validate=validator)
    assert attempts[0].read_bytes() == before and checkpoint != attempts[0].stem


def test_failure_diagnostic_does_not_erase_acceptance(phase_store, phase_key, artifact, validator):
    """Independent failed physical attempts preserve already accepted phase evidence."""
    checkpoint = phase_store.commit(phase_key, artifact, validate=validator)
    path = phase_store.task_root / 'validation/nca-phases/attempts' / f'{checkpoint}.json'
    before = path.read_bytes()
    phase_store.record_failure(phase_key, {'code': 'transport_failed', 'request_id': 'new-call'})
    assert len(phase_store.lookup(phase_key, validate=validator).accepted) == 2
    assert path.read_bytes() == before
    assert len(list(path.parent.glob('*.json'))) == 2


def test_current_validator_runs_on_every_lookup(phase_store, phase_key, artifact, validator):
    """A prior acceptance cannot bypass newly enforced semantic evidence rules."""
    phase_store.commit(phase_key, artifact, validate=validator)
    def reject(value):
        """Represent a current validator rejecting the previously admitted evidence."""
        raise ValidationError('current evidence rejected', code='NCA_TEST_CURRENT')
    with pytest.raises(ValidationError, match='current evidence rejected'):
        phase_store.lookup(phase_key, validate=reject)


@pytest.mark.parametrize('relative', ['validation', 'validation/nca-phases', 'validation/nca-phases/attempts', 'locks', 'locks/nca-phases.lock'])
def test_symlink_ancestor_is_rejected_before_lock_write(phase_store, phase_key, artifact, validator, tmp_path, relative):
    """No governed storage or lock creation may traverse a task descendant symlink."""
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = phase_store.task_root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError):
        phase_store.commit(phase_key, artifact, validate=validator)
    assert list(outside.iterdir()) == []


def test_concurrent_writer_is_excluded_without_ledger_damage(phase_store, phase_key, artifact, validator):
    """A real competing store cannot enter the ledger while another writer validates."""
    from concurrent.futures import ThreadPoolExecutor
    from sage.errors import LockError
    competitor = replay_module().PhaseStore(phase_store.task_root, task_fingerprint=phase_key.task_fingerprint)
    def validating(value):
        """Attempt a competing physical commit while the first writer holds its lock."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(competitor.commit, phase_key, artifact, validate=validator)
            with pytest.raises(LockError):
                future.result(timeout=5)
        return validator(value)
    phase_store.commit(phase_key, artifact, validate=validating)
    assert len(phase_store.lookup(phase_key, validate=validator).accepted) == 2


def test_supported_and_unsupported_dispositions_survive(phase_store, phase_key, artifact, validator, recorded):
    """Valid UNSUPPORTED evidence remains uncertainty after reuse, never an empty pass."""
    root, batch, _, _ = recorded
    response = batch_response(batch)
    response['work_units'][0].update(status='UNSUPPORTED', limitations=['uninterpretable'], expressions=[])
    tasks = model_tasks(root, RecordedExecutor([response]))
    result = tasks.extract_batch(batch, parsing_conventions={})
    attempt = tasks.attempts[0]
    value = deepcopy(artifact)
    value.update(receipt=result.receipt.to_dict(), raw_response=result.raw_response, request_id=result.request_id,
        item_sha256=dict(result.value.item_sha256), attempt={'measurement': plain(asdict(attempt.measurement)),
        'request': plain(attempt.request), 'raw_response': attempt.raw_response, 'response_identity': plain(attempt.response_identity)})
    phase_store.commit(phase_key, value, validate=validator)
    recovered = phase_store.lookup(phase_key, validate=validator)
    assert recovered.accepted[batch.inputs[0].input_id].status == 'UNSUPPORTED'


def publication_fixture(phase_store, phase_key, artifact, validator):
    """Build independently reproducible final content from revalidated checkpoints."""
    checkpoint = phase_store.commit(phase_key, artifact, validate=validator)
    checkpoints = {checkpoint: phase_key}
    output = {'accepted': list(phase_key.input_ids)}
    output_bytes = (json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    receipt = {'task_fingerprint': phase_key.task_fingerprint,
        'output_sha256': {'output/model-evidence.json': hashlib.sha256(output_bytes).hexdigest()}}
    def validate_final(document, execution, evidence):
        """Require final evidence to be exactly derived from validated phase artifacts."""
        assert set(evidence) == {checkpoint}
        assert document == {'accepted': list(evidence[checkpoint].accepted)}
        assert execution['task_fingerprint'] == phase_key.task_fingerprint
        return document
    return checkpoints, output, receipt, validate_final


def test_final_publication_recovers_after_one_canonical_file(phase_store, phase_key, artifact, validator, monkeypatch):
    """A crash between final files resumes only their manifest-bound exact bytes."""
    checkpoints, output, receipt, validate_final = publication_fixture(phase_store, phase_key, artifact, validator)
    module = replay_module()
    phase_store.prepare_publication(output, receipt, checkpoints=checkpoints,
        validate_phase=lambda key, value: validator(value), validate_final=validate_final)
    original = module.atomic_write_bytes
    def crash(path, payload):
        """Interrupt the second canonical write while retaining staged authority."""
        if path.name == 'llm-execution-receipt.json':
            raise RuntimeError('power loss')
        original(path, payload)
    monkeypatch.setattr(module, 'atomic_write_bytes', crash)
    with pytest.raises(RuntimeError):
        phase_store.recover_publication(checkpoints=checkpoints, validate_phase=lambda key, value: validator(value), validate_final=validate_final)
    assert (phase_store.task_root / 'output/model-evidence.json').is_file()
    assert not (phase_store.task_root / 'validation/llm-execution-receipt.json').exists()
    monkeypatch.setattr(module, 'atomic_write_bytes', original)
    assert phase_store.recover_publication(checkpoints=checkpoints, validate_phase=lambda key, value: validator(value), validate_final=validate_final) == output
    assert json.loads((phase_store.task_root / 'validation/llm-execution-receipt.json').read_text()) == receipt


def test_arbitrary_partial_output_is_not_recovery_authority(phase_store, phase_key, artifact, validator):
    """A lone output without a verified publication manifest never becomes accepted."""
    path = phase_store.task_root / 'output/model-evidence.json'
    path.parent.mkdir()
    path.write_text('{"accepted": []}')
    with pytest.raises(ValidationError):
        phase_store.recover_publication(checkpoints={}, validate_phase=lambda key, value: validator(value), validate_final=lambda *args: None)


@pytest.mark.parametrize('damage', ['output', 'receipt', 'checkpoint', 'semantic', 'destination'])
def test_publication_rejects_tampering(phase_store, phase_key, artifact, validator, damage):
    """Final files require unchanged checkpoint authority and current controller derivation."""
    checkpoints, output, receipt, validate_final = publication_fixture(phase_store, phase_key, artifact, validator)
    phase_store.prepare_publication(output, receipt, checkpoints=checkpoints,
        validate_phase=lambda key, value: validator(value), validate_final=validate_final)
    directory = phase_store.task_root / 'validation/nca-phases/publication'
    if damage in {'output', 'receipt'}:
        (directory / f'{damage}.json').write_text('{}')
    elif damage == 'checkpoint':
        checkpoint = next(iter(checkpoints))
        (directory.parent / 'attempts' / f'{checkpoint}.json').write_text('{}')
    elif damage == 'destination':
        path = phase_store.task_root / 'output/model-evidence.json'
        path.parent.mkdir()
        path.write_text('{}')
    else:
        def validate_final(*args):
            """Reject a staged document under changed controller requirements."""
            raise ValidationError('cannot derive staged content', code='NCA_TEST_FINAL')
    with pytest.raises((ValidationError, AssertionError)):
        phase_store.recover_publication(checkpoints=checkpoints,
            validate_phase=lambda key, value: validator(value), validate_final=validate_final)
    assert not (phase_store.task_root / 'validation/llm-execution-receipt.json').exists()


def test_preparation_crash_after_one_staged_file_can_finish_from_checkpoints(phase_store, phase_key, artifact, validator, monkeypatch):
    """A lone staged file can finish preparation only by reproducing validated finals."""
    checkpoints, output, receipt, validate_final = publication_fixture(phase_store, phase_key, artifact, validator)
    module = replay_module()
    original = module.atomic_write_bytes
    def crash(path, payload):
        """Interrupt durable staging immediately after the first staged payload."""
        if path.name == 'receipt.json':
            raise RuntimeError('stage interrupted')
        original(path, payload)
    monkeypatch.setattr(module, 'atomic_write_bytes', crash)
    with pytest.raises(RuntimeError):
        phase_store.prepare_publication(output, receipt, checkpoints=checkpoints,
            validate_phase=lambda key, value: validator(value), validate_final=validate_final)
    directory = phase_store.task_root / 'validation/nca-phases/publication'
    assert (directory / 'output.json').is_file() and not (directory / 'manifest.json').exists()
    assert phase_store.recover_publication(checkpoints=checkpoints,
        validate_phase=lambda key, value: validator(value), validate_final=validate_final) is None
    monkeypatch.setattr(module, 'atomic_write_bytes', original)
    phase_store.prepare_publication(output, receipt, checkpoints=checkpoints,
        validate_phase=lambda key, value: validator(value), validate_final=validate_final)
    assert phase_store.recover_publication(checkpoints=checkpoints,
        validate_phase=lambda key, value: validator(value), validate_final=validate_final) == output


def test_accepted_attempt_cannot_be_replaced(phase_store, phase_key, artifact, validator):
    """A second valid but different physical attempt cannot replace accepted membership."""
    checkpoint = phase_store.commit(phase_key, artifact, validate=validator)
    before = (phase_store.task_root / 'validation/nca-phases/ledger.json').read_bytes()
    changed = deepcopy(artifact)
    changed['request_id'] = changed['attempt']['measurement']['request_id'] = 'different-call'
    with pytest.raises(ValidationError):
        phase_store.commit(phase_key, changed, validate=validator)
    assert (phase_store.task_root / 'validation/nca-phases/ledger.json').read_bytes() == before
    assert phase_store.commit(phase_key, artifact, validate=validator) == checkpoint


@pytest.mark.parametrize('component', ['source', 'package', 'mapping', 'profile'])
def test_every_applicable_input_byte_component_affects_identity(phase_key, artifact, component):
    """Each applicable sealed component and ordered stream identity fences evidence reuse."""
    arguments = dict(phase=phase_key.phase, task_fingerprint=phase_key.task_fingerprint,
        input_ids=phase_key.input_ids, input_components={'source': b'source', 'package': b'package',
        'mapping': b'mapping', 'profile': b'profile'}, policy_bytes=b'policy', route=artifact['route_snapshot'],
        contract_components={'schema': b'schema', 'skill': b'skill', 'phase': b'2.0'}, validator_version='2.0')
    original = replay_module().PhaseKey.build(**arguments)
    arguments['input_components'][component] += b' changed'
    assert replay_module().PhaseKey.build(**arguments).input_sha256 != original.input_sha256


@pytest.mark.parametrize('relative', ['validation/nca-phases/ledger.json', 'validation/nca-phases/publication', 'output'])
def test_publication_and_ledger_symlinks_are_rejected(phase_store, phase_key, artifact, validator, tmp_path, relative):
    """Final destinations and existing ledger files cannot redirect controller writes."""
    checkpoints, output, receipt, validate_final = publication_fixture(phase_store, phase_key, artifact, validator)
    outside = tmp_path / 'outside'
    outside.mkdir()
    path = phase_store.task_root / relative
    if path.is_file():
        path.unlink()
    path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError):
        phase_store.prepare_publication(output, receipt, checkpoints=checkpoints,
            validate_phase=lambda key, value: validator(value), validate_final=validate_final)
        phase_store.recover_publication(checkpoints=checkpoints,
            validate_phase=lambda key, value: validator(value), validate_final=validate_final)
    assert list(outside.iterdir()) == []


def test_resume_exposes_verified_checkpoint_id_for_publication(phase_store, phase_key, artifact, validator):
    """A resumed controller obtains the store ID with the same freshly validated evidence."""
    checkpoint = phase_store.commit(phase_key, artifact, validate=validator)
    resumed = replay_module().PhaseStore(phase_store.task_root, task_fingerprint=phase_key.task_fingerprint)
    assert hasattr(resumed, 'lookup_checkpoint'), 'resume cannot recover publication checkpoint IDs'
    identifier, result = resumed.lookup_checkpoint(phase_key, validate=validator)
    assert identifier == checkpoint and len(result.accepted) == 2
    assert resumed.lookup_checkpoint(replace(phase_key, input_sha256='f' * 64), validate=validator) is None


@pytest.mark.parametrize('unreported', [None, ''])
def test_admitted_response_with_unreported_optional_identity_can_checkpoint(phase_store, phase_key, validator, recorded, unreported):
    """An admitted response retains missing optional metadata without inventing identity."""
    from sage.executors.base import ProviderResponse
    root, batch, _, _ = recorded
    raw = ' \n' + json.dumps(batch_response(batch), indent=2) + '\n'
    response = ProviderResponse(provider='codex', model=unreported, reasoning_effort=unreported,
                                content=raw, metadata={})
    tasks = model_tasks(root, RecordedExecutor([response]))
    result = tasks.extract_batch(batch, parsing_conventions={})
    attempt = tasks.attempts[0]
    artifact = {'receipt': result.receipt.to_dict(), 'raw_response': result.raw_response,
        'request_id': result.request_id, 'route_snapshot': plain(tasks.route_snapshot),
        'item_sha256': dict(result.value.item_sha256), 'attempt': {
            'measurement': plain(asdict(attempt.measurement)), 'request': plain(attempt.request),
            'raw_response': attempt.raw_response, 'response_identity': plain(attempt.response_identity)}}
    checkpoint = phase_store.commit(phase_key, artifact, validate=validator)
    assert len(phase_store.lookup(phase_key, validate=validator).accepted) == 2
    stored = json.loads((phase_store.task_root / 'validation/nca-phases/attempts' / f'{checkpoint}.json').read_text())
    assert stored['artifact']['attempt']['response_identity']['model'] is unreported
    assert stored['artifact']['raw_response'] == raw


@pytest.mark.parametrize('field', ['provider_metadata', 'phase', 'task_version'])
def test_malformed_receipt_field_types_raise_checkpoint_validation(phase_store, phase_key, artifact, validator, field):
    """Malformed persisted receipts fail closed with a domain error rather than a crash."""
    changed = deepcopy(artifact)
    changed['receipt'][field] = []
    with pytest.raises(ValidationError):
        phase_store.commit(phase_key, changed, validate=validator)
    assert phase_store.lookup(phase_key, validate=validator) is None


@pytest.mark.parametrize('field', ['provider', 'model', 'reasoning_effort'])
def test_explicit_response_route_conflicts_cannot_checkpoint(phase_store, phase_key, artifact, validator, field):
    """Missing optional metadata is admissible, but contradictory response identity is not."""
    changed = deepcopy(artifact)
    changed['attempt']['response_identity'][field] = 'contradictory'
    with pytest.raises(ValidationError):
        phase_store.commit(phase_key, changed, validate=validator)
    assert phase_store.lookup(phase_key, validate=validator) is None
