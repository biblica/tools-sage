"""Runtime NCA scope preserves target-local selection and package Western authority."""
import pytest

from sage.errors import ValidationError
from sage.numbers.scope import project_scope
from sage.references import parse_scope
from sage.vrs import VerseRef

from .test_projection import bundle, schema, unit


def test_target_scope_selects_shifted_western_reference_even_without_target_text(tmp_path):
    """A missing target verse cannot make expected coverage use Western verse numbers as local ones."""
    target = schema(tmp_path, 'org.vrs', '1KI 4:20 5:32\n')
    western = schema(tmp_path, 'eng.vrs', '1KI 4:34 5:18\n1KI 4:21-34 = 1KI 5:1-14\n1KI 5:1-18 = 1KI 5:15-32\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('1KI 4:21-34 = 1KI 5:1-14\n1KI 5:1-18 = 1KI 5:15-32\n')
    correct, unrelated = VerseRef('1KI', 4, 21), VerseRef('1KI', 5, 1)
    projected, expected = project_scope((), scope=parse_scope('1KI 5:1'), target_schema=target,
        western_schema=western, bundle=bundle((correct, '1KI 5:1'), (unrelated, '1KI 5:15')), mapping_path=mapping)
    assert expected == (correct,)
    assert len(projected) == 1 and projected[0].western_references == (correct,)
    assert projected[0].status == 'UNMAPPED'


def test_scoped_boundary_loads_its_complete_numeric_source_group(tmp_path):
    """A selected source boundary pulls in its required continuation without broadening unrelated coverage."""
    target = schema(tmp_path, 'org.vrs', '1SA 20:42 21:16\n')
    western = schema(tmp_path, 'eng.vrs', '1SA 20:42 21:15\n1SA 20:42 = 1SA 21:1\n1SA 21:1-15 = 1SA 21:2-16\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('1SA 20:42 = 1SA 21:1\n1SA 21:1-15 = 1SA 21:2-16\n')
    ref = VerseRef('1SA', 20, 42)
    projected, expected = project_scope((unit('1SA', 20, 42, 'Two.'), unit('1SA', 21, 1, 'Continuation.'), unit('1SA', 21, 2, 'Unrelated.')),
        scope=parse_scope('1SA 20:42'), target_schema=target, western_schema=western,
        bundle=bundle((ref, '1SA 20:42')), mapping_path=mapping)
    assert expected == (ref,)
    assert len(projected) == 1 and projected[0].status == 'READY'
    assert projected[0].target.main_text == 'Two.\nContinuation.'


def test_package_mapping_disagreement_fails_explicitly(tmp_path):
    """A configured baseline cannot silently replace the mapping supplied with reference authority."""
    target = schema(tmp_path, 'org.vrs', 'MAT 1:3\n')
    western = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:2\n')
    with pytest.raises(ValidationError) as caught:
        project_scope((unit('MAT', 1, 1),), scope=parse_scope('MAT 1'), target_schema=target,
            western_schema=western, bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:2')), mapping_path=mapping)
    assert caught.value.code == 'NCA_MAPPING_BASELINE_MISMATCH'


def test_scope_keeps_unindexed_target_streams_and_direct_registered_absence(tmp_path):
    """Complete target screening includes added numbers and explicit Western registered omissions."""
    target = schema(tmp_path, 'eng.vrs', 'NEH 7:73\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('NEH 7:1 = NEH 7:1\n')
    absence = VerseRef('NEH', 7, 68)
    projected, expected = project_scope((unit('NEH', 7, 67),), scope=parse_scope('NEH 7'),
        target_schema=target, western_schema=target, bundle=bundle((absence, None)), mapping_path=mapping)
    assert absence in expected and len(expected) == 73
    assert (VerseRef('NEH', 7, 67),) in {item.western_references for item in projected}
    assert next(item for item in projected if item.western_references == (absence,)).status == 'REGISTERED_ABSENCE'


def test_equal_forward_mapping_does_not_hide_continuation_disagreement(tmp_path):
    """Continuation semantics belong to the mapping contract even when coordinate sets agree."""
    target = schema(tmp_path, 'org.vrs', 'MAT 1:3\n')
    western = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n&MAT 1:1 = MAT 1:2\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:2\n')
    with pytest.raises(ValidationError) as caught:
        project_scope((), scope=parse_scope('MAT 1'), target_schema=target, western_schema=western,
            bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:2')), mapping_path=mapping)
    assert caught.value.code == 'NCA_MAPPING_BASELINE_MISMATCH'


def test_missing_unindexed_target_coordinate_cannot_disappear_from_coverage(tmp_path):
    """A selected but absent WIP verse is not equivalent to a screened empty numeric extraction."""
    target = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:1\n')
    projected, expected = project_scope((unit('MAT', 1, 1),), scope=parse_scope('MAT 1'),
        target_schema=target, western_schema=target, bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:1')), mapping_path=mapping)
    assert len(expected) == len(projected) == 3
    assert all(item.status == 'UNMAPPED' for item in projected if item.target.unit_id.startswith('missing:'))


@pytest.mark.parametrize('label', ['MAT 2', 'MAT 1:9', 'MAT 1:1-9'])
def test_invalid_target_scope_is_rejected_instead_of_narrowed(tmp_path, label):
    """Unknown or partially out-of-bounds scopes cannot become empty all-clear Runs."""
    target = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:1\n')
    with pytest.raises(ValidationError) as caught:
        project_scope((), scope=parse_scope(label), target_schema=target, western_schema=target,
            bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:1')), mapping_path=mapping)
    assert caught.value.code == 'NCA_SCOPE_OUTSIDE_VRS'


def test_fully_excluded_scope_cannot_become_empty_all_clear(tmp_path):
    """A valid-looking selector must still contain an assessable coordinate under effective VRS."""
    target = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n-MAT 1:2\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:1\n')
    with pytest.raises(ValidationError) as caught:
        project_scope((), scope=parse_scope('MAT 1:2'), target_schema=target, western_schema=target,
            bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:1')), mapping_path=mapping)
    assert caught.value.code == 'NCA_SCOPE_OUTSIDE_VRS'


def test_inventory_keeps_full_expected_ledger_and_missing_unindexed_scope(tmp_path):
    """Scope inventory comes from projection coverage, never detected or indexed numbers."""
    from sage.numbers.execution import ExecutionInputs, build_inventory
    from sage.numbers.target import target_units
    from sage.usj import compile_usfm_text
    source = compile_usfm_text('\\id MAT Fixture\n\\c 1\n\\v 1 Three.\n\\v 2 No numeral.\n')
    target = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:1\n')
    reference = bundle((VerseRef('MAT', 1, 1), 'MAT 1:1'))
    projected, expected = project_scope(target_units(source, source_sha256='0' * 64),
        scope=parse_scope('MAT 1'), target_schema=target, western_schema=target,
        bundle=reference, mapping_path=mapping)
    prepared = ExecutionInputs(reference, {}, {'wip': {'language': 'en'}}, projected, (),
        tuple(value.target.unit_id for value in projected), expected, {'0' * 64: source}, 'MAT 1')
    inventory = build_inventory(prepared)
    assert inventory.requested_scope == 'MAT 1'
    assert inventory.expected_references == tuple(VerseRef('MAT', 1, verse) for verse in range(1, 4))
    assert inventory.projected_units == prepared.projected_units
    assert inventory.expected_groups == frozenset({projected[0].target.unit_id})
    assert {value.owner_unit_id for value in inventory.stream_inputs if value.purpose == 'BODY'} == {
        unit.target.unit_id for unit in projected if unit.target.target_references}
    assert len(inventory.stream_inputs) == 2
    assert projected[-1].target.unit_id == 'missing:MAT 1:3'
    assert projected[-1].status == 'UNMAPPED'


def test_prepared_inventory_retains_actual_requested_scope(make_workspace, monkeypatch):
    """The real preparation boundary carries Run-local scope without adding sealed policy fields."""
    from sage.numbers.execution import prepare_execution_inputs, build_inventory
    from sage.numbers.policy import load_nca_run_snapshot
    from .test_nca_tasks import _run
    _root, config, job, run = _run(make_workspace, monkeypatch)
    prepared = prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))
    inventory = build_inventory(prepared)
    assert prepared.requested_scope == inventory.requested_scope == run.scope
    assert 'scope' not in prepared.policy
    assert inventory.expected_references == prepared.expected_references
    assert inventory.stream_inputs


def test_inventory_preserves_boundary_expansion_in_wip_coordinates(tmp_path):
    """Western expected refs must never replace the original WIP-local selection."""
    from sage.numbers.execution import ExecutionInputs, build_inventory
    from sage.numbers.target import target_units
    from sage.usj import compile_usfm_text
    source = compile_usfm_text('\\id 1SA Fixture\n\\c 20\n\\v 42 Two.\n\\c 21\n\\v 1 Continuation.\n\\v 2 Unrelated.\n')
    target = schema(tmp_path, 'org.vrs', '1SA 20:42 21:16\n')
    western = schema(tmp_path, 'eng.vrs', '1SA 20:42 21:15\n1SA 20:42 = 1SA 21:1\n1SA 21:1-15 = 1SA 21:2-16\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('1SA 20:42 = 1SA 21:1\n1SA 21:1-15 = 1SA 21:2-16\n')
    reference = bundle((VerseRef('1SA', 20, 42), '1SA 20:42'))
    scope_value = '1SA 21:1'
    projected, expected = project_scope(target_units(source, source_sha256='0' * 64),
        scope=parse_scope(scope_value), target_schema=target, western_schema=western,
        bundle=reference, mapping_path=mapping)
    prepared = ExecutionInputs(reference, {}, {'wip': {'language': 'en'}}, projected, (),
        tuple(value.target.unit_id for value in projected), expected, {'0' * 64: source}, scope_value)
    inventory = build_inventory(prepared)
    assert inventory.requested_scope == '1SA 21:1'
    assert inventory.expected_references == (VerseRef('1SA', 20, 42),)
    value, = inventory.stream_inputs
    assert value.text == 'Two.\nContinuation.'
    assert value.target_references == (VerseRef('1SA', 20, 42), VerseRef('1SA', 21, 1))
    assert len(value.records) == 2


def test_registered_missing_inventory_keeps_notes_once_at_their_physical_source(tmp_path):
    """Registered absence keeps its case ledger while a transferred note is extracted once."""
    from sage.numbers.execution import ExecutionInputs, build_inventory
    from sage.numbers.target import target_units
    from sage.usj import compile_usfm_text
    source = compile_usfm_text('\\id NEH Fixture\n\\c 7\n\\v 69 Other text.'
        '\\f + \\fr 7:68 \\ft Thirty animals.\\f*\n')
    target = schema(tmp_path, 'eng.vrs', 'NEH 7:73\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('NEH 7:1 = NEH 7:1\n')
    absence = VerseRef('NEH', 7, 68)
    reference = bundle((absence, None))
    projected, expected = project_scope(target_units(source, source_sha256='0' * 64),
        scope=parse_scope('NEH 7:68-69'), target_schema=target, western_schema=target,
        bundle=reference, mapping_path=mapping)
    prepared = ExecutionInputs(reference, {}, {'wip': {'language': 'en'}}, projected, (),
        tuple(value.target.unit_id for value in projected), expected, {'0' * 64: source}, 'NEH 7:68-69')
    inventory = build_inventory(prepared)
    missing = next(value for value in inventory.projected_units if not value.target.target_references)
    assert missing.status == 'REGISTERED_ABSENCE' and missing.target.notes
    assert inventory.expected_groups == frozenset({missing.target.unit_id})
    assert [value.purpose for value in inventory.stream_inputs] == ['BODY', 'NOTE_STYLE']
    note = inventory.stream_inputs[1]
    assert note.target_references == (absence,)
    assert note.records[0].refs == (VerseRef('NEH', 7, 69),)


def test_inventory_groups_offset_purposes_for_bounded_note_batching(tmp_path):
    """Notes on every verse must not prevent eligible body and note inputs from batching."""
    from sage.numbers.execution import ExecutionInputs, build_inventory
    from sage.numbers.target import target_units
    from sage.numbers.batching import plan_batches
    from sage.evidence import EvidencePolicy
    from sage.usj import compile_usfm_text
    source = compile_usfm_text('\\id MAT Fixture\n\\c 1\n' + ''.join(
        f'\\v {verse} Three.\\f + \\ft Thirty.\\f*\n' for verse in range(1, 9)))
    target = schema(tmp_path, 'eng.vrs', 'MAT 1:8\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:1\n')
    reference = bundle((VerseRef('MAT', 1, 1), 'MAT 1:1'))
    projected, expected = project_scope(target_units(source, source_sha256='0' * 64),
        scope=parse_scope('MAT 1'), target_schema=target, western_schema=target,
        bundle=reference, mapping_path=mapping)
    prepared = ExecutionInputs(reference, {}, {'wip': {'language': 'en'}}, projected, (),
        tuple(value.target.unit_id for value in projected), expected, {'0' * 64: source}, 'MAT 1')
    inventory = build_inventory(prepared)
    assert [value.purpose for value in inventory.stream_inputs] == ['BODY'] * 8 + ['NOTE_STYLE'] * 8
    plan = plan_batches(inventory.stream_inputs, policy=EvidencePolicy())
    assert len(plan.batches) == 2
    assert tuple(value for batch in plan.batches for value in batch.inputs) == inventory.stream_inputs
