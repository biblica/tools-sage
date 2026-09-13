"""Target-only batches independently validate protected stream evidence."""
from copy import deepcopy
from fractions import Fraction
import pytest
from sage.errors import ValidationError
from sage.numbers import extraction
from sage.numbers.batching import _batch
from sage.numbers.transport import make_stream_input
from sage.work_units import EvidenceRecord
from .test_extraction import expression


def batch_fixture(texts=('three men', 'four women'), stream_id='main'):
    """Bind hand-specified exact text to separate real source coordinates."""
    inputs = []
    for verse, text in enumerate(texts, 1):
        record = EvidenceRecord('MAT', 5, verse, verse, {}, f'\\v {verse} {text}')
        inputs.append(make_stream_input(owner_unit_id=f'MAT 5:{verse}', stream_id=stream_id,
            purpose='BODY' if stream_id == 'main' else 'NOTE_STYLE',
            target_references=record.refs, records=(record,), text=text,
            source_sha256='0' * 64, language='en', conventions={}))
    values = tuple(inputs)
    return _batch(values, ''.join(value.routed_sfm for value in values))


def batch_response(batch):
    """Produce literal recorded cardinal evidence with stream-local IDs."""
    return {'schema_version': '2.0', 'phase': 'EXTRACTION', 'batch_id': batch.batch_id,
        'work_units': [{'input_id': value.input_id, 'status': 'COMPLETE', 'limitations': [],
            'expressions': [expression('e1', value.text.split()[0], 0,
                len(value.text.split()[0]), '3' if value.text.startswith('three') else '4',
                stream_id=value.stream_id)]} for value in batch.inputs]}


def validate(batch, raw):
    """Expose absent API as an explicit behavior failure during the initial RED run."""
    assert hasattr(extraction, 'validate_batch_extraction_response'), 'batch validation is not implemented'
    return extraction.validate_batch_extraction_response(batch, raw)


def test_two_units_accept_out_of_order_and_freeze_controller_hashes():
    """A reordered response retains each exact input and immutable local item binding."""
    batch = batch_fixture()
    raw = batch_response(batch)
    raw['work_units'].reverse()
    result = validate(batch, raw)
    first, second = [value.input_id for value in batch.inputs]
    assert result.batch_id == batch.batch_id and not result.pending
    assert result.accepted[first].expressions[0].values == (Fraction(3),)
    assert result.accepted[second].expressions[0].values == (Fraction(4),)
    assert set(result.item_sha256) == {first, second}
    assert all(len(value) == 64 for value in result.item_sha256.values())
    raw['work_units'][0]['expressions'][0]['values'] = ['99']
    assert result.accepted[second].expressions[0].values == (Fraction(4),)
    with pytest.raises(TypeError):
        result.accepted[first] = result.accepted[second]


def test_absent_input_remains_pending_while_valid_sibling_commits():
    """Missing coverage never becomes an empty COMPLETE extraction."""
    batch = batch_fixture()
    raw = batch_response(batch)
    raw['work_units'].pop()
    result = validate(batch, raw)
    assert set(result.accepted) == {batch.inputs[0].input_id}
    assert result.pending == {batch.inputs[1].input_id: 'NCA_BATCH_INPUT_MISSING'}


@pytest.mark.parametrize('damage', ['duplicate', 'unknown', 'wrong_batch', 'unhashable', 'absent_id'])
def test_invalid_batch_identities_reject_entire_envelope(damage):
    """Coverage ambiguity blocks admission of every member under that parent receipt."""
    batch = batch_fixture()
    raw = batch_response(batch)
    if damage == 'duplicate':
        raw['work_units'].append(deepcopy(raw['work_units'][0]))
    elif damage == 'wrong_batch':
        raw['batch_id'] = 'invented'
    elif damage == 'absent_id':
        raw['work_units'][0].pop('input_id')
    else:
        raw['work_units'][0]['input_id'] = [] if damage == 'unhashable' else 'invented'
    with pytest.raises(ValidationError) as exc:
        validate(batch, raw)
    assert exc.value.code == 'NCA_BATCH_COVERAGE_INVALID'


@pytest.mark.parametrize('damage', ['surface', 'stream', 'offset', 'overlap', 'duplicate', 'unknown_field'])
def test_invalid_known_item_leaves_valid_sibling_accepted(damage):
    """Invented, overlapping, and foreign evidence cannot poison valid sibling work."""
    batch = batch_fixture()
    raw = batch_response(batch)
    item = raw['work_units'][0]
    expr = item['expressions'][0]
    if damage == 'surface':
        expr['surface'] = 'invented'
    elif damage == 'stream':
        expr['stream_id'] = 'another-note'
    elif damage == 'offset':
        expr['span']['start'] = 1
    elif damage == 'unknown_field':
        item['expected_values'] = ['3']
    else:
        other = deepcopy(expr)
        other['expression_id'] = 'e2'
        if damage == 'overlap':
            other.update(surface='hree', span={'start': 1, 'end': 5})
        item['expressions'].append(other)
    result = validate(batch, raw)
    assert set(result.accepted) == {batch.inputs[1].input_id}
    assert set(result.pending) == {batch.inputs[0].input_id}


@pytest.mark.parametrize('damage', ['contradiction', 'one_sided'])
def test_dual_form_evidence_cannot_disagree_or_omit_representation(damage):
    """Batch admission reuses the exact words-plus-digits semantic boundary."""
    batch = batch_fixture(('three (3) men',))
    raw = batch_response(batch)
    raw['work_units'][0]['expressions'] = [expression('e1', 'three (3)', 0, 9, '3',
        representations=[{'surface': 'three', 'span': {'start': 0, 'end': 5}, 'value': '3'},
            {'surface': '3', 'span': {'start': 7, 'end': 8}, 'value': '4' if damage == 'contradiction' else '3'}])]
    if damage == 'one_sided':
        raw['work_units'][0]['expressions'][0]['representations'].pop()
    result = validate(batch, raw)
    assert not result.accepted and set(result.pending) == {batch.inputs[0].input_id}


def test_duplicate_note_local_evidence_does_not_alias_another_note():
    """Repeated IDs across input scopes are legal but duplicate spans within a note fail."""
    batch = batch_fixture(stream_id='note-1')
    raw = batch_response(batch)
    raw['work_units'][0]['expressions'] *= 2
    result = validate(batch, raw)
    assert set(result.pending) == {batch.inputs[0].input_id}
    assert result.accepted[batch.inputs[1].input_id].expressions[0].stream_id == 'note-1'


@pytest.mark.parametrize('status', ['PARTIAL', 'UNSUPPORTED'])
def test_incomplete_interpretation_is_accepted_without_status_upgrade(status):
    """Semantic uncertainty is terminal evidence, never an automatic retry trigger."""
    batch = batch_fixture()
    raw = batch_response(batch)
    raw['work_units'][0].update(status=status, limitations=['ambiguous word'], expressions=[])
    result = validate(batch, raw)
    assert not result.pending
    assert result.accepted[batch.inputs[0].input_id].status == status


def test_batch_payload_filters_authority_and_requires_bound_conventions():
    """Reference hints and registry presence cannot enter the extraction request."""
    batch = batch_fixture()
    assert hasattr(extraction, 'build_batch_extraction_payload'), 'batch payload is not implemented'
    payload = extraction.build_batch_extraction_payload(batch, parsing_conventions={
        'ol_values': ['318'], 'niv_values': ['317'], 'registry_present': True})
    assert payload['parsing_conventions'] == {}
    assert payload['routed_sfm'] == batch.routed_sfm
    assert set(payload['work_units'][0]) == {'input_id', 'stream_id', 'text'}
    with pytest.raises(ValidationError) as exc:
        extraction.build_batch_extraction_payload(batch, parsing_conventions={'digits': {'preferred': '0123'}})
    assert exc.value.code == 'NCA_EXTRACTION_PAYLOAD_INVALID'
