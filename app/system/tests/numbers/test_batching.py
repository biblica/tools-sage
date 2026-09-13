"""Protected NCA batches exercise the real routed-SFM planning boundary."""
from dataclasses import replace

import pytest
import yaml

from sage.errors import ValidationError
from sage.evidence import EvidencePolicy
from sage.sfm_slicer import render_sfm_slice
from sage.work_units import EvidenceRecord

from .conftest import make_units


@pytest.fixture
def evidence_policy(package_root):
    """Load the shipped NCA hard limits without replacing the shared planner."""
    raw = yaml.safe_load((package_root / 'system/config/workflows/nca/profile.yml').read_text())
    return EvidencePolicy.from_mapping(raw['evidence_policies']['default'])


@pytest.fixture
def stream_inputs():
    """Bind Task 1's exact 32 MAT units to small, real Scripture SFM slices."""
    from sage.numbers.transport import make_stream_input
    return tuple(make_stream_input(
        owner_unit_id=unit.unit_id, stream_id='main', purpose='BODY',
        target_references=unit.target_references, text=unit.main_text,
        records=(EvidenceRecord('MAT', 5, v, v, {'source_locator': dict(unit.source_locator)},
                                f'\\v {v} Three men.'),),
        source_sha256=unit.source_sha256, language='en', conventions={})
        for v, unit in enumerate(make_units(32), 1))


def test_eight_unit_batches_cover_the_scope_once(stream_inputs, evidence_policy):
    """Batching cannot lose or duplicate target streams."""
    from sage.numbers.batching import plan_batches
    plan = plan_batches(stream_inputs, policy=evidence_policy, max_units=8)
    assert len(plan.batches) == 4
    assert not plan.blocked
    assert [x.input_id for b in plan.batches for x in b.inputs] == [x.input_id for x in stream_inputs]
    assert plan == plan_batches(stream_inputs, policy=evidence_policy, max_units=8)


def test_wide_bridge_counts_as_one_input_but_keeps_atomic_hard_limit(stream_inputs, evidence_policy):
    """The input cap must never turn a ten-verse bridge into an eight-verse failure."""
    from sage.numbers.transport import make_stream_input
    from sage.numbers.batching import plan_batches
    record = EvidenceRecord('MAT', 5, 1, 10, {}, '\\v 1-10 Three men.')
    wide = make_stream_input(owner_unit_id='bridge', stream_id='main', purpose='BODY',
        target_references=record.refs, records=(record,), text='Three men.',
        source_sha256='0' * 64, language='en', conventions={})
    plan = plan_batches((wide,) + stream_inputs[10:17], policy=evidence_policy)
    assert len(plan.batches) == 1 and len(plan.batches[0].inputs) == 8
    limited = plan_batches((wide,), policy=replace(evidence_policy, maximum_primary_verse_units=9))
    assert not limited.batches and set(limited.blocked) == {wide.input_id}


def test_shared_hard_limit_splits_batches_and_blocks_only_oversized_input(stream_inputs, evidence_policy):
    """Every small input is planned; an indivisible oversized source is explicit."""
    from sage.numbers.batching import plan_batches
    from sage.numbers.transport import make_stream_input
    record = EvidenceRecord('MAT', 5, 9, 9, {}, '\\v 9 ' + 'Large ' * 1000)
    oversized = make_stream_input(owner_unit_id='large', stream_id='main', purpose='BODY',
        target_references=record.refs, records=(record,), text='Large ' * 1000,
        source_sha256='0' * 64, language='en', conventions={})
    candidates = stream_inputs[:8] + (oversized,)
    plan = plan_batches(candidates, policy=replace(evidence_policy, hard_serialized_bytes=130))
    assert len(plan.batches) > 1
    assert set(plan.blocked) == {oversized.input_id}
    assert all(len(batch.routed_sfm.encode()) <= 130 for batch in plan.batches)
    assert [item.input_id for batch in plan.batches for item in batch.inputs] == [x.input_id for x in stream_inputs[:8]]


def test_overlap_notes_and_heading_remain_separate_without_fake_coordinates(stream_inputs, evidence_policy):
    """Shared verse coordinates flush batches while preserving each independent stream."""
    from sage.numbers.batching import plan_batches
    from sage.numbers.transport import make_stream_input
    body = stream_inputs[0]
    siblings = tuple(make_stream_input(owner_unit_id=body.owner_unit_id, stream_id=str(i),
        purpose=purpose, target_references=body.target_references, records=body.records,
        text=text, source_sha256=body.source_sha256, language='en', conventions={})
        for i, (purpose, text) in enumerate([('NOTE_STYLE', 'Thirty.'), ('NOTE_STYLE', 'Forty.'), ('HEADING_STYLE', 'Section 3')]))
    values = (body,) + siblings + stream_inputs[1:]
    plan = plan_batches(values, policy=evidence_policy)
    assert not plan.blocked
    assert tuple(x for batch in plan.batches for x in batch.inputs) == values
    assert all(x.target_references == body.target_references for x in siblings)


def test_sized_sfm_matches_sent_context_and_metadata_never_enters_estimator(stream_inputs, evidence_policy, monkeypatch):
    """Observe actual shared sizing while making projection metadata far larger than SFM."""
    from sage.numbers.batching import plan_batches
    from sage import sfm_slicer
    actual = sfm_slicer.estimate_tokens
    seen = []

    def observe(text):
        """Record only actual SFM passed to the shared estimator."""
        assert text == '' or text.startswith('\\id MAT\n\\c 5\n\\v ')
        assert 'metadata-sentinel' not in text
        seen.append(text)
        return actual(text)

    monkeypatch.setattr(sfm_slicer, 'estimate_tokens', observe)
    from sage.numbers.transport import make_stream_input
    changed = tuple(make_stream_input(owner_unit_id=value.owner_unit_id, stream_id=value.stream_id,
        purpose=value.purpose, target_references=value.target_references, records=value.records,
        text=value.text, source_sha256=value.source_sha256, language=value.language,
        conventions={'profile-schema-metadata': 'metadata-sentinel' * 10000}) for value in stream_inputs[:8])
    plan = plan_batches(changed, policy=replace(evidence_policy, maximum_primary_verse_units=3))
    assert len(plan.batches) >= 3
    for batch in plan.batches:
        for part in batch.routed_sfm.split('\\id ')[1:]:
            assert '\\id ' + part in seen
        assert all(value.routed_sfm in batch.routed_sfm for value in batch.inputs)
    assert any(batch.routed_sfm != ''.join(x.routed_sfm for x in batch.inputs) for batch in plan.batches)


def test_split_bisects_membership_without_splitting_protected_inputs(stream_inputs, evidence_policy):
    """Binary fallback has a finite bound derived from original membership."""
    from sage.numbers.batching import plan_batches, split_batch
    batch = plan_batches(stream_inputs[:8], policy=evidence_policy).batches[0]
    children = split_batch(batch)
    assert [len(child.inputs) for child in children] == [4, 4]
    assert tuple(value for child in children for value in child.inputs) == batch.inputs
    assert children == split_batch(batch)
    pending, visited = [batch], []
    while pending:
        current = pending.pop()
        visited.append(current)
        pending.extend(split_batch(current))
    assert len(visited) == 2 * len(batch.inputs) - 1


@pytest.mark.parametrize('value', [True, 0, -1, 1.5, '8'])
def test_input_cap_requires_a_positive_exact_integer(stream_inputs, evidence_policy, value):
    """Invalid caps cannot silently change batch geometry."""
    from sage.numbers.batching import plan_batches
    with pytest.raises(ValidationError):
        plan_batches(stream_inputs, policy=evidence_policy, max_units=value)


def test_protected_multirecord_group_cannot_split_at_chapter_or_hard_limit(evidence_policy):
    """Shared required-spans closure protects a boundary group across separate records."""
    from sage.numbers.transport import streams_for_target
    from sage.numbers.projection import _combined
    from sage.numbers.target import target_units
    from sage.numbers.batching import plan_batches
    from sage.usj import compile_usfm_text
    source = compile_usfm_text('\\id 1SA Fixture\n\\c 20\n\\v 42 Two.\n\\c 21\n\\v 1 Continuation.\n')
    group = _combined(target_units(source, source_sha256='0' * 64))
    values = streams_for_target(group, source, language='en', conventions={})
    plan = plan_batches(values, policy=evidence_policy)
    assert len(plan.batches) == 1 and plan.batches[0].inputs == values
    blocked = plan_batches(values, policy=replace(evidence_policy, maximum_primary_verse_units=1))
    assert not blocked.batches and set(blocked.blocked) == {values[0].input_id}


@pytest.mark.parametrize('difference', ['purpose', 'language', 'conventions'])
def test_distinct_extraction_contracts_never_share_a_batch(stream_inputs, evidence_policy, difference):
    """Consecutive, nonoverlapping coordinates cannot mask distinct extraction contracts."""
    from sage.numbers.transport import make_stream_input
    from sage.numbers.batching import plan_batches
    first, second = stream_inputs[:2]
    fields = dict(owner_unit_id=second.owner_unit_id, stream_id=second.stream_id,
        purpose=second.purpose, target_references=second.target_references, records=second.records,
        text=second.text, source_sha256=second.source_sha256, language=second.language, conventions={})
    fields[difference] = {'purpose': 'NOTE_STYLE', 'language': 'fr', 'conventions': {'digits': 'different'}}[difference]
    changed = make_stream_input(**fields)
    plan = plan_batches((first, changed), policy=evidence_policy)
    assert len(plan.batches) == 2
    assert [batch.inputs for batch in plan.batches] == [(first,), (changed,)]


def test_chapter_boundary_is_preferred_between_complete_inputs(stream_inputs, evidence_policy):
    """Chapter preference changes packing only between protected inputs."""
    from sage.numbers.transport import make_stream_input
    from sage.numbers.batching import plan_batches
    record = EvidenceRecord('MAT', 6, 1, 1, {}, '\\v 1 Three men.')
    following = make_stream_input(owner_unit_id='next-chapter', stream_id='main', purpose='BODY',
        target_references=record.refs, records=(record,), text='Three men.',
        source_sha256='0' * 64, language='en', conventions={})
    assert len(plan_batches((stream_inputs[-1], following), policy=evidence_policy).batches) == 2


@pytest.mark.parametrize('damage', ['empty', 'list', 'untyped', 'duplicate', 'identity', 'version', 'sfm'])
def test_extraction_batch_rejects_invalid_direct_construction(stream_inputs, evidence_policy, damage):
    """Frozen transport containers cannot retain mutable membership or forged identity."""
    from sage.numbers.batching import plan_batches
    batch = plan_batches(stream_inputs[:2], policy=evidence_policy).batches[0]
    fields = {'empty': {'inputs': ()}, 'list': {'inputs': list(batch.inputs)},
        'untyped': {'inputs': ('invalid',)}, 'duplicate': {'inputs': batch.inputs * 2},
        'identity': {'batch_id': 'forged'}, 'version': {'contract_version': 'unknown'},
        'sfm': {'routed_sfm': ''}}[damage]
    with pytest.raises(ValidationError):
        replace(batch, **fields)
