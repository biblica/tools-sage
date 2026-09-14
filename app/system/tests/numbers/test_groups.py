"""Bridge ownership retains typed meaning and exact row authority."""
from dataclasses import replace
from fractions import Fraction
import pytest

from sage.errors import ValidationError
from sage.numbers import groups
from sage.numbers.models import Extraction
from sage.numbers.model_tasks import _expression_payload
from sage.vrs import VerseRef
from .test_engine import expression_at, projected, reference_bundle, check_policy


def bridge_case(*, repeated=False):
    """Build two exact source streams and one protected bridge target."""
    refs = (VerseRef('MAT', 5, 1), VerseRef('MAT', 5, 2))
    text = '3 men and 3 women' if repeated else '3 men and 4 women'
    unit = projected(refs[0], text, end=2, western=refs)
    bundle = reference_bundle(refs[0])
    second = replace(reference_bundle(refs[1], ol=3 if repeated else 4).rows[refs[1]],
                     ol_text='3 women' if repeated else '4 women')
    bundle = replace(bundle, rows={**bundle.rows, refs[1]: second})
    target = tuple(expression_at(text, surface, value, role=role, expression_id=eid, stream_id='main')
                   for surface, value, role, eid in [('3', 3, 'men', 't1'),
                   ('3 women' if repeated else '4', 3 if repeated else 4, 'women', 't2')])
    if repeated:
        target = (target[0], replace(target[1], surface='3', span=(10, 11)))
    extraction = Extraction(target, 'COMPLETE')
    group = groups.ReferenceGroup.build(unit, bundle=bundle)
    response = {'schema_version': '2.0', 'phase': 'GROUP_CORRESPONDENCE', 'unit_id': unit.target.unit_id,
        'status': 'COMPLETE', 'limitations': [], 'assignments': {refs[0].label(): ['t1'], refs[1].label(): ['t2']},
        'unmatched_target_ids': [], 'unresolved_target_ids': [], 'rows': {}}
    for ref, role, eid in zip(refs, ('men', 'women'), ('t1', 't2')):
        row = bundle.rows[ref]
        source = expression_at(row.ol_text, str(row.ol_values[0]), row.ol_values[0], role=role,
                               expression_id='s1', stream_id='ol')
        item = next(x for x in target if x.expression_id == eid)
        response['rows'][ref.label()] = {'status': 'COMPLETE', 'limitations': [],
            'source_expressions': [_expression_payload(source, row.ol_text)],
            'target_roles': [{'expression_id': eid, 'role': role,
                'role_spans': [{'start': a, 'end': b, 'surface': text[a:b]} for a, b in item.role_spans]}]}
    return group, extraction, response, bundle


def test_clear_bridge_has_two_attributed_passes():
    """Each source row compares only its own target expression."""
    group, extraction, response, bundle = bridge_case()
    evidence = groups.validate_group_correspondence(group, extraction, response)
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
    assert [x.final_outcome for x in components] == ['PASS_AUTHORITY1', 'PASS_AUTHORITY1']
    assert [x.owned_target_expression_ids for x in components] == [('t1',), ('t2',)]


def test_two_reference_rows_cannot_consume_one_target_expression():
    """A bridge must retain multiplicity and one owner per target expression."""
    group, extraction, response, _ = bridge_case(repeated=True)
    extraction = replace(extraction, expressions=extraction.expressions[:1])
    response['assignments'] = {'MAT 5:1': ['t1'], 'MAT 5:2': ['t1']}
    response['rows']['MAT 5:2']['target_roles'] = response['rows']['MAT 5:1']['target_roles']
    with pytest.raises(ValidationError, match='ownership'):
        groups.validate_group_correspondence(group, extraction, response)


@pytest.mark.parametrize('mutation', ['source_value', 'source_surface', 'foreign_row', 'unaccounted', 'overlap', 'unresolved_complete'])
def test_group_rejects_mutated_authority_or_accounting(mutation):
    """Exact row streams and exhaustive disjoint expression ownership are mandatory."""
    group, extraction, response, _ = bridge_case()
    if mutation == 'source_value':
        response['rows']['MAT 5:1']['source_expressions'][0]['values'] = ['4']
    elif mutation == 'source_surface':
        response['rows']['MAT 5:1']['source_expressions'][0]['surface'] = '4'
    elif mutation == 'foreign_row':
        response['assignments']['MAT 5:3'] = []
    elif mutation == 'unaccounted':
        response['assignments']['MAT 5:2'] = []
    elif mutation == 'overlap':
        response['unmatched_target_ids'] = ['t2']
    else:
        response['assignments']['MAT 5:2'] = []
        response['unresolved_target_ids'] = ['t2']
    with pytest.raises(ValidationError):
        groups.validate_group_correspondence(group, extraction, response)


def test_swapped_roles_cannot_pass_pooled_equal_values():
    """Equal pooled values cannot authorize quantities allocated to wrong referents."""
    group, extraction, response, bundle = bridge_case(repeated=True)
    response['assignments'] = {'MAT 5:1': ['t2'], 'MAT 5:2': ['t1']}
    a, b = response['rows'].values()
    a['target_roles'], b['target_roles'] = b['target_roles'], a['target_roles']
    evidence = groups.validate_group_correspondence(group, extraction, response)
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
    assert [x.final_outcome for x in components] == ['REVIEW_VALUE_DIFFERENCE'] * 2


def test_group_phase_is_one_real_checkpointed_request(package_root, tmp_path):
    """A bridge's physical receipt survives replay without per-row provider calls."""
    from types import SimpleNamespace
    from sage.numbers.hybrid import PhaseSession
    from sage.numbers.replay import PhaseStore
    from .test_model_tasks import RecordedExecutor, model_tasks
    group, extraction, response, _ = bridge_case()
    transport = RecordedExecutor([response])
    tasks = model_tasks(package_root, transport)
    assert hasattr(tasks, 'correspond_group'), 'group physical phase is missing'
    inputs = SimpleNamespace(policy_bytes=b'group policy', contract_components={'contract': b'2.0'},
                             policy={'model_route': dict(tasks.route_snapshot)})
    session = PhaseSession(inputs, tasks, PhaseStore(tmp_path, task_fingerprint='a' * 64))
    tasks.configure_phase_execution(session.execute)
    result = tasks.correspond_group(group.unit, extraction, group)
    replay = tasks.correspond_group(group.unit, extraction, group)
    assert result.receipt == replay.receipt
    assert result.receipt.phase == 'GROUP_CORRESPONDENCE'
    assert result.receipt.task_version == 'nca-group-correspondence-2.0'
    assert len(transport.requests) == len(session.durable_calls()) == 1
    assert len(session.reused) == 1


def test_partial_group_retains_resolved_row_and_unresolved_ids():
    """Ambiguous allocation preserves useful rows without an overall completion claim."""
    group, extraction, response, bundle = bridge_case()
    response.update(status='PARTIAL', limitations=['AMBIGUOUS_ALLOCATION'], unresolved_target_ids=['t2'])
    response['assignments']['MAT 5:2'] = []
    response['rows']['MAT 5:2'].update(status='PARTIAL', limitations=['AMBIGUOUS_ALLOCATION'], target_roles=[])
    evidence = groups.validate_group_correspondence(group, extraction, response)
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
    assert evidence.status == 'PARTIAL' and evidence.unresolved_target_ids == ('t2',)
    assert [x.final_outcome for x in components] == ['PASS_AUTHORITY1', 'INSUFFICIENT_EVIDENCE']


def test_missing_quantity_does_not_duplicate_the_other_row_target():
    """Complete correspondence can prove one missing quantity from an empty row allocation."""
    group, extraction, response, bundle = bridge_case()
    extraction = replace(extraction, expressions=extraction.expressions[:1])
    response['assignments']['MAT 5:2'] = []
    response['rows']['MAT 5:2']['target_roles'] = []
    evidence = groups.validate_group_correspondence(group, extraction, response)
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
    assert [x.final_outcome for x in components] == ['PASS_AUTHORITY1', 'REVIEW_NUMBER_MISSING']


def test_group_document_serializes_each_rows_own_evidence():
    """Multirow serialization cannot copy the first source or decision to its neighbors."""
    from sage.numbers.models_v2 import GroupResult
    from sage.numbers.results_v2 import group_document, _group_view
    from sage.numbers.engine import _result_reference_context
    group, extraction, response, bundle = bridge_case()
    evidence = groups.validate_group_correspondence(group, extraction, response)
    checks = check_policy(footnotes=False)['checks']
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=checks)
    rows = tuple({'western_reference': row.western_reference.label(), 'ol_reference': row.ol_reference,
                  'status': 'INDEXED', 'context': _result_reference_context(row, bundle), 'provenance': groups.row_provenance(row, bundle)} for row in group.rows)
    result = GroupResult(group.unit, extraction, rows, components, 'COMPLETE',
                         {'t1': 'MAT 5:1', 't2': 'MAT 5:2'}, (), (), (), ())
    document = group_document(result, checks=checks)
    assert [c['source_expressions'][0]['values'] for c in document['components']] == [['3'], ['4']]
    assert _group_view(document, checks)['unit_id'] == group.unit.target.unit_id


def test_shifted_anchor_mapping_is_retained_and_used_for_notes(tmp_path):
    """A shifted WIP anchor proves its row through explicit mapping rather than label equality."""
    from sage.numbers.projection import project_units
    from .test_projection import schema
    from sage.numbers.models import TargetNote, TargetUnit
    from sage.vrs import VerseRef
    ref = VerseRef('MAT', 5, 1)
    group, _extraction, _response, bundle = bridge_case()
    local = VerseRef('MAT', 5, 3)
    note = TargetNote('n1', 'f', 'witness has three', (local,), ({'kind': 'CONTENT', 'start': 0, 'end': 17, 'text': 'witness has three'},))
    target = TargetUnit('shifted', (local,), '3 men', (note,), 'a' * 64, {})
    western = schema(tmp_path, 'western', 'MAT 1:10 2:10 3:10 4:10 5:10\n')
    shifted = schema(tmp_path, 'shifted', 'MAT 1:10 2:10 3:10 4:10 5:10\nMAT 5:3 = MAT 5:1\n')
    projected_units = project_units((target,), target_schema=shifted, western_schema=western, bundle=bundle)
    assert projected_units[0].target_western_mapping[local.label()] == (ref.label(),)
    assert groups.attributed_notes(projected_units[0], ref) == ((note,), False)


@pytest.mark.parametrize(('presentation_only', 'unmatched'), [(False, False), (True, False), (False, True)])
def test_optimized_bridge_uses_one_group_phase(package_root, tmp_path, presentation_only, unmatched):
    """Production orchestration extracts one bridge and attributes both coordinates."""
    from sage.numbers.execution import ExecutionInputs, build_inventory
    from sage.numbers.hybrid import evaluate
    from sage.numbers.replay import PhaseStore
    from sage.usj import compile_usfm_text
    from sage.numbers.target import target_units
    from .test_engine import style_profile
    from .test_model_tasks import RecordedExecutor, model_tasks
    group, extraction, response, bundle = bridge_case()
    text = '3 men and 4 women' + (' and 5' if unmatched else '')
    if unmatched:
        extra = replace(expression_at(text, '5', 5, role='5', expression_id='t3', stream_id='main'), role=None, role_spans=())
        extraction = replace(extraction, expressions=(*extraction.expressions, extra))
        response['unmatched_target_ids'] = ['t3']
    document = compile_usfm_text('\\id MAT\n\\c 5\n\\v 1-2 ' + text + '\n')
    target = replace(target_units(document, source_sha256='a' * 64)[0], unit_id=group.unit.target.unit_id)
    unit = replace(group.unit, target=target)
    policy = dict(check_policy(accuracy=not presentation_only, footnotes=False), schema_version='2.0', wip={'language': 'en'},
        reference_package={'diagnostics': []}, optimization={'contract_version': 'nca-optimization-2.0',
        'reuse_scope': 'TASK', 'extraction_batch_max_units': 8, 'request_concurrency': 1, 'transient_retries': 1})
    inputs = ExecutionInputs(bundle, style_profile(), policy, (unit,), (), (target.unit_id,),
        unit.western_references, {'a' * 64: document}, 'MAT 5:1-2', b'policy', {'contract': b'2.0'})
    from sage.numbers.batching import plan_batches
    from sage.evidence import EvidencePolicy
    inventory = build_inventory(inputs)
    batch = plan_batches(inventory.stream_inputs, policy=EvidencePolicy.from_mapping(inputs.evidence_policy)).batches[0]
    raw = {'schema_version': '2.0', 'phase': 'EXTRACTION', 'batch_id': batch.batch_id,
        'work_units': [{'input_id': batch.inputs[0].input_id, 'status': 'COMPLETE', 'limitations': [],
            'expressions': [_expression_payload(x, target.main_text) for x in extraction.expressions]}]}
    transport = RecordedExecutor([raw, response])
    tasks = model_tasks(package_root, transport)
    inputs = replace(inputs, policy=dict(policy, model_route=tasks.route_snapshot))
    result = evaluate(inputs, model_tasks=tasks, phase_store=PhaseStore(tmp_path, task_fingerprint='a' * 64), run_id='bridge')
    if presentation_only:
        assert result.groups[0].alignment_status == 'NOT_ASSESSED'
        assert not result.groups[0].components and not result.groups[0].expression_ownership
        assert len(transport.requests) == 1
        return
    assert result.groups[0].alignment_status == 'COMPLETE'
    assert [c.final_outcome for c in result.groups[0].components] == ['PASS_AUTHORITY1'] * 2
    assert result.summary['units'] == 1 and result.summary['passes'] == result.summary['indexed_coordinates'] == 2
    assert result.metrics['accepted_phase_receipts'] == 2 and len(transport.requests) == 2
    if unmatched:
        from sage.numbers.results_v2 import numbers_result_document_v2
        from sage.numbers.results import validate_numbers_result
        from .test_results import provenance
        receipts = {phase: [] for phase in ('EXTRACTION', 'CORRESPONDENCE', 'FOOTNOTE', 'GROUP_CORRESPONDENCE')}
        for checkpoint in result.metrics['checkpoints']:
            receipts[checkpoint['receipt']['phase']].append(checkpoint['receipt'])
        raw = numbers_result_document_v2(result, provenance=provenance(), check_policy=inputs.policy, model_receipts=receipts)
        assert validate_numbers_result(raw, expected_unit_ids=inputs.expected_unit_ids, allowed_evidence_ids=('SRC-1',)) == raw
        assert raw['groups'][0]['unmatched_target_ids'] == ['t3']
        assert raw['groups'][0]['extraction']['expressions'][-1]['role'] is None
        assert raw['summary']['added_numbers'] == 1


def result_case():
    """Construct a complete bridge result for typed and serialized mutation checks."""
    from sage.numbers.models_v2 import GroupResult
    from sage.numbers.engine import _result_reference_context
    group, extraction, response, bundle = bridge_case()
    evidence = groups.validate_group_correspondence(group, extraction, response)
    checks = check_policy(footnotes=False)['checks']
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=checks)
    rows = tuple({'western_reference': row.western_reference.label(), 'ol_reference': row.ol_reference,
        'status': 'INDEXED', 'context': _result_reference_context(row, bundle), 'provenance': groups.row_provenance(row, bundle)} for row in group.rows)
    return GroupResult(group.unit, extraction, rows, components, 'COMPLETE',
        {'t1': 'MAT 5:1', 't2': 'MAT 5:2'}, (), (), (), ()), checks


@pytest.mark.parametrize('damage', ['source_sequence', 'source_surface', 'registry', 'incomplete', 'unindexed', 'not_assessed'])
def test_typed_group_rejects_row_evidence_mutations(damage):
    """Direct typed construction enforces source authority and explicit alignment states."""
    result, _checks = result_case()
    component = result.components[1]
    with pytest.raises(ValidationError):
        if damage == 'source_sequence':
            component = replace(component, source_expressions=(replace(component.source_expressions[0], values=(Fraction(3),)),))
        elif damage == 'source_surface':
            component = replace(component, source_expressions=(replace(component.source_expressions[0], surface='3'),))
        elif damage == 'registry':
            component = replace(component, reading=replace(component.reading, registry_id='MAT 5:1'))
        elif damage == 'incomplete':
            replace(result, extraction=replace(result.extraction, status='PARTIAL', limitations=('ambiguous',)))
        elif damage == 'unindexed':
            replace(result, reference_rows=(result.reference_rows[0], dict(result.reference_rows[1], status='UNINDEXED', ol_reference=None, context={}, provenance=groups.row_provenance(None, bridge_case()[3]))),
                components=(result.components[0], replace(component, ol_reference=None)))
        else:
            replace(result, alignment_status='NOT_ASSESSED')
        if damage in {'source_sequence', 'source_surface', 'registry'}:
            replace(result, components=(result.components[0], component))


@pytest.mark.parametrize('missing', ['role', 'role_spans'])
def test_complete_typed_group_requires_target_role_evidence(missing):
    """Complete bridge passes cannot retain a target with unresolved role evidence."""
    result, _checks = result_case()
    target = result.extraction.expressions[0]
    target = replace(target, role=None, role_spans=()) if missing == 'role' else replace(target, role_spans=())
    with pytest.raises(ValidationError):
        replace(result, extraction=replace(result.extraction,
            expressions=(target, result.extraction.expressions[1])))


def test_one_to_many_note_anchor_cannot_satisfy_disclosure():
    """A broad anchor preserves unknown note attribution rather than authorizing both rows."""
    from sage.numbers.models import TargetNote
    result, _checks = result_case()
    ref = result.projected.target.target_references[0]
    note = TargetNote('n1', 'f', 'witness differs', (ref,), ({'kind': 'CONTENT', 'start': 0, 'end': 15, 'text': 'witness differs'},))
    mapping = {x.label(): tuple(y.label() for y in result.projected.western_references) for x in result.projected.target.target_references}
    unit = replace(result.projected, target=replace(result.projected.target, notes=(note,)), target_western_mapping=mapping)
    assert groups.attributed_notes(unit, unit.western_references[0]) == ((), True)
    assert groups.attributed_notes(unit, unit.western_references[1]) == ((), True)


@pytest.mark.parametrize('kind', ['RANGE', 'RATIO'])
def test_group_range_and_ratio_are_owned_as_one_expression(kind):
    """Ordered range and ratio values remain attached to a single owning expression."""
    from sage.numbers.models import NumericExpression
    group, extraction, response, bundle = bridge_case()
    text = '3-4 men and 4 women' if kind == 'RANGE' else '3:4 men and 4 women'
    target = (NumericExpression((Fraction(3), Fraction(4)), kind, text[:3], (0, 3), role='men',
        expression_id='t1', role_spans=((4, 7),)), expression_at(text, '4 women', 4, role='women', expression_id='t2', stream_id='main'))
    target = (target[0], replace(target[1], surface='4', span=(12, 13)))
    first = replace(group.rows[0], ol_text=text[:7], ol_values=(Fraction(3), Fraction(4)))
    bundle = replace(bundle, rows={**bundle.rows, first.western_reference: first})
    group = groups.ReferenceGroup.build(replace(group.unit, target=replace(group.unit.target, main_text=text)), bundle=bundle)
    extraction = Extraction(target, 'COMPLETE')
    response['rows']['MAT 5:1']['source_expressions'] = [_expression_payload(replace(target[0], expression_id='s1', stream_id='ol'), first.ol_text)]
    for label, expression in zip(response['rows'], target):
        response['rows'][label]['target_roles'] = [{'expression_id': expression.expression_id, 'role': expression.role,
            'role_spans': [{'start': a, 'end': b, 'surface': text[a:b]} for a, b in expression.role_spans]}]
    evidence = groups.validate_group_correspondence(group, extraction, response)
    assert [c.final_outcome for c in groups.evaluate_group(group, extraction, evidence, bundle=bundle,
        checks=check_policy(footnotes=False)['checks'])] == ['PASS_AUTHORITY1'] * 2


def test_canonical_bridge_publication_replays_row_evidence_and_mapping(make_workspace, monkeypatch):
    """Canonical publication keeps an indexed bridge row and rejects tampered retained mapping."""
    import json
    from pathlib import Path
    from sage.executors.base import ProviderResponse
    from sage.nca import create_nca_job, create_nca_run, create_nca_task, execute_nca_task, finalize_nca_run
    from sage.act_tasks import submit_act_task
    from sage.numbers.results import validate_numbers_result
    from .test_nca_jobs import _prepare_nca_workspace, _route
    from .test_nca_tasks import _OfflineTasks
    class BridgeTransport:
        """Return literal bridge evidence through the actual physical execution boundary."""
        def execute(self, request):
            """Extract two original expressions and assign them only to their indexed row."""
            payload = json.loads(request.prompt)['input']
            if payload['phase'] == 'EXTRACTION':
                text = payload['work_units'][0]['text']
                expressions = [expression_at(text, digit, int(digit), role=digit, expression_id=f't{index}',
                    stream_id='main') for index, digit in enumerate(('3', '4'), 1)]
                expressions = [replace(x, role='quantity', role_spans=(x.span,)) for x in expressions]
                raw = {'schema_version': '2.0', 'phase': 'EXTRACTION', 'batch_id': payload['batch_id'],
                    'work_units': [{'input_id': payload['work_units'][0]['input_id'], 'status': 'COMPLETE', 'limitations': [],
                        'expressions': [_expression_payload(x, text) for x in expressions]}]}
            else:
                assert payload['phase'] == 'GROUP_CORRESPONDENCE'
                text = payload['rows'][0]['authority']['ol_text']
                source = [expression_at(text, surface, value, role=surface, expression_id=f's{index}', stream_id='ol')
                    for index, (surface, value) in enumerate((('three', 3), ('four', 4)), 1)]
                source = [replace(x, role='quantity', role_spans=(x.span,)) for x in source]
                raw = {'schema_version': '2.0', 'phase': 'GROUP_CORRESPONDENCE', 'unit_id': payload['unit_id'],
                    'status': 'PARTIAL', 'limitations': ['REFERENCE_NOT_INDEXED'], 'unmatched_target_ids': [],
                    'unresolved_target_ids': [], 'assignments': {'MAT 1:1': ['t1', 't2'], 'MAT 1:2': []},
                    'rows': {'MAT 1:1': {'status': 'COMPLETE', 'limitations': [],
                        'source_expressions': [_expression_payload(x, text) for x in source],
                        'target_roles': [{'expression_id': x['expression_id'], 'role': x['role'], 'role_spans': x['role_spans']}
                            for x in payload['target']['expressions']]}}}
            return ProviderResponse(provider='codex', model='gpt-test', reasoning_effort='high',
                content=json.dumps(raw), metadata={'request_id': 'bridge-' + payload['phase']})
    class BridgeTasks(_OfflineTasks):
        """Keep real builders and checkpoint hooks while substituting literal transport."""
        def __init__(self, *args, **kwargs):
            """Attach the provider-free bridge responder to the sealed fixture route."""
            super().__init__(*args, **kwargs)
            self._executor = BridgeTransport()
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _style = _prepare_nca_workspace(root)
    (config.project('usWIP').path / '41MAT.SFM').write_text('\\id MAT\n\\c 1\n\\v 1-2 3 and 4\n')
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1', style_selector='fixture-style/1')
    run = create_nca_run(config, job_id=job.job_id, scope_value='MAT 1:1-2',
        checks={'presentation_consistency': False, 'footnote_review': False})
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', BridgeTasks)
    assert execute_nca_task(config, path)['status'] == 'EXECUTED'
    output = path.parent / 'output/model-evidence.json'
    document = json.loads(output.read_text())
    assert document['groups'][0]['alignment_status'] == 'PARTIAL'
    assert [c['final_outcome'] for c in document['groups'][0]['components']] == ['PASS_AUTHORITY1', 'REFERENCE_NOT_INDEXED']
    assert document['summary']['units'] == document['summary']['passes'] == 1
    assert document['summary']['indexed_coordinates'] == document['summary']['unindexed_coordinates'] == 1
    assert document['coverage']['result'] == 'INSUFFICIENT_DATA'
    manifest = json.loads(path.read_text())
    validate_numbers_result(document, expected_unit_ids=tuple(manifest['expected_unit_ids']), allowed_evidence_ids=tuple(manifest['allowed_evidence_ids']))
    from copy import deepcopy
    forged = deepcopy(document)
    forged['model_receipts']['GROUP_CORRESPONDENCE'] = []
    forged['metrics']['checkpoints'] = [c for c in forged['metrics']['checkpoints'] if c['key']['phase'] != 'GROUP_CORRESPONDENCE']
    forged['metrics']['accepted_phase_receipts'] -= 1
    with pytest.raises(ValidationError):
        validate_numbers_result(forged, expected_unit_ids=tuple(manifest['expected_unit_ids']), allowed_evidence_ids=tuple(manifest['allowed_evidence_ids']))
    invalid_number = deepcopy(document)
    invalid_number['groups'][0]['components'][0]['source_expressions'][0]['values'] = ['1/0']
    with pytest.raises(ValidationError):
        validate_numbers_result(invalid_number, expected_unit_ids=tuple(manifest['expected_unit_ids']), allowed_evidence_ids=tuple(manifest['allowed_evidence_ids']))
    assert submit_act_task(config, path)['status'] == 'FINALIZED'
    final = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    assert 'SQS: `NOT_APPLIED`' in Path(final['report_path']).read_text()
    before = output.read_bytes()
    document['groups'][0]['projection']['target_western_mapping']['MAT 1:1'] = ['MAT 1:2']
    output.write_text(json.dumps(document))
    with pytest.raises(ValidationError):
        execute_nca_task(config, path)
    output.write_bytes(before)


def alternate_case(*, ambiguous=False):
    """Build a registered alternate with a neighboring equal quantity and exact note anchors."""
    from sage.numbers.models import TargetNote
    group, extraction, response, _bundle = bridge_case()
    first, second = group.unit.western_references
    bundle = reference_bundle(first, niv=4, registered=True)
    bundle = replace(bundle, rows={**bundle.rows, second: group.rows[1]})
    text = '4 men and 4 women'
    target = tuple(replace(x, values=(Fraction(4),), surface='4') for x in extraction.expressions)
    note_text = 'Other witnesses read three.'
    note = TargetNote('n1', 'f', note_text, (first,), ({'kind': 'CONTENT', 'start': 0, 'end': len(note_text), 'text': note_text},))
    unit = replace(group.unit, target=replace(group.unit.target, main_text=text, notes=(note,)),
        target_western_mapping={first.label(): (first.label(), second.label()) if ambiguous else (first.label(),),
                                second.label(): (second.label(),)})
    group = groups.ReferenceGroup.build(unit, bundle=bundle)
    candidate = expression_at('4 men', '4', 4, role='men', expression_id='r1', stream_id='registered')
    response['rows'][first.label()].update(registered_status='COMPLETE', registered_limitations=[],
        registered_expressions=[_expression_payload(candidate, '4 men')])
    return group, Extraction(target, 'COMPLETE'), response, bundle


@pytest.mark.parametrize('ambiguous', [False, True])
@pytest.mark.parametrize('shifted', [False, True])
def test_registered_bridge_note_is_separate_and_uniquely_attributed(package_root, tmp_path, ambiguous, shifted):
    """Required disclosure uses one governed note phase only after unique anchor ownership."""
    from types import SimpleNamespace
    from sage.numbers.hybrid import PhaseSession
    from sage.numbers.replay import PhaseStore
    from .test_model_tasks import RecordedExecutor, model_tasks
    group, extraction, response, bundle = alternate_case(ambiguous=ambiguous)
    if shifted:
        local = (VerseRef('MAT', 5, 3), VerseRef('MAT', 5, 4))
        note = replace(group.unit.target.notes[0], anchor_references=(local[0],))
        target = replace(group.unit.target, target_references=local, notes=(note,))
        mapping = {new.label(): group.unit.target_western_mapping[old.label()]
            for new, old in zip(local, group.unit.target.target_references)}
        group = replace(group, unit=replace(group.unit, target=target, target_western_mapping=mapping))
    note = group.unit.target.notes[0]
    raw = {'schema_version': '2.0', 'phase': 'FOOTNOTE', 'unit_id': group.unit.target.unit_id,
        'note_id': note.note_id, 'action': 'REQUIRE', 'status': 'ADEQUATE', 'outcome': 'NONE', 'limitations': [],
        'evidence': [{'note_id': note.note_id, 'surface': note.text, 'span': {'start': 0, 'end': len(note.text)}}]}
    transport = RecordedExecutor([response] + ([] if ambiguous else [raw]))
    tasks = model_tasks(package_root, transport)
    session = PhaseSession(SimpleNamespace(policy_bytes=b'notes', contract_components={'contract': b'2.0'},
        policy={'model_route': dict(tasks.route_snapshot)}), tasks, PhaseStore(tmp_path, task_fingerprint='b' * 64))
    tasks.configure_phase_execution(session.execute)
    evidence = tasks.correspond_group(group.unit, extraction, group).value
    checks = check_policy()['checks']
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=checks)
    assert components[0].reading.selected == 'ALT' and components[0].footnote.status == 'NOT_ASSESSED'
    assessed = groups.assess_group_notes(group, components, bundle=bundle, checks=checks, language='en', model_tasks=tasks)
    assert assessed[0].footnote.status == ('NOT_ASSESSED' if ambiguous else 'ADEQUATE')
    assert assessed[0].final_outcome == ('REGISTERED_ALTERNATE' if ambiguous else 'ACCEPTABLE_VARIANT_WITH_FOOTNOTE')
    assert assessed[1].reading.selected == 'OL' and assessed[1].footnote.status == 'NOT_REQUIRED'
    assert sorted(call.phase for call in session.durable_calls()) == (['GROUP_CORRESPONDENCE'] if ambiguous else ['FOOTNOTE', 'GROUP_CORRESPONDENCE'])


def test_registered_neighbor_cannot_authorize_changed_ordinary_row():
    """A registered alternate applies exclusively to its own Western row."""
    group, extraction, response, bundle = alternate_case()
    second = group.unit.western_references[1]
    source = replace(bundle.rows[second], ol_values=(Fraction(3),), ol_text='3 women')
    bundle = replace(bundle, rows={**bundle.rows, second: source})
    group = groups.ReferenceGroup.build(group.unit, bundle=bundle)
    response['rows'][second.label()]['source_expressions'] = [_expression_payload(
        expression_at('3 women', '3', 3, role='women', expression_id='s1', stream_id='ol'), '3 women')]
    evidence = groups.validate_group_correspondence(group, extraction, response)
    decisions = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
    assert decisions[0].reading.selected == 'ALT'
    assert decisions[1].reading.selected == 'UNSUPPORTED' and decisions[1].final_outcome == 'REVIEW_VALUE_DIFFERENCE'


@pytest.mark.parametrize('wrong_residual', [False, True])
def test_group_conversion_keeps_unrelated_typed_residual(wrong_residual):
    """One coordinate's registered unit pair cannot authorize an unrelated changed referent."""
    from sage.numbers.models import NumericExpression
    first, second = VerseRef('LUK', 16, 7), VerseRef('LUK', 16, 8)
    record = {'OL_QUANTITY': '3 sata', 'NIV_QUANTITY': '60 gallons', 'SOURCE_IDS': 'UNIT-SOURCE'}
    bundle = reference_bundle(first, ol=3, niv=60, unit_record=record)
    bundle = replace(bundle, provenance={**bundle.provenance, 'UNIT-SOURCE': {'SOURCE_ID': 'UNIT-SOURCE'}})
    row = replace(bundle.rows[first], ol_text='3 sata and 2 debts', ol_values=(Fraction(3), Fraction(2)))
    neighbor = replace(reference_bundle(second, ol=4).rows[second], ol_text='4 women')
    bundle = replace(bundle, rows={first: row, second: neighbor})
    text = '60 gallons and 2 debts and 4 women'
    unit = projected(first, text, end=8, western=(first, second))
    def numeric(stream, surface, value, role_surface, role, eid, stream_id, unit=None):
        """Build exact unit and residual evidence with independently located referents."""
        return replace(expression_at(stream, surface, value, role=role_surface, expression_id=eid, stream_id=stream_id), role=role, unit=unit)
    target = (numeric(text, '60', 60, 'gallons', 'measure', 't1', 'main', 'gallon'),
        numeric(text, '2', 2, 'women' if wrong_residual else 'debts', 'women' if wrong_residual else 'debts', 't2', 'main'),
        numeric(text, '4', 4, 'women', 'women', 't3', 'main'))
    source = (numeric(row.ol_text, '3', 3, 'sata', 'measure', 's1', 'ol', 'saton'),
        numeric(row.ol_text, '2', 2, 'debts', 'debts', 's2', 'ol'))
    other = numeric(neighbor.ol_text, '4', 4, 'women', 'women', 's1', 'ol')
    candidate = numeric('60 gallons', '60', 60, 'gallons', 'measure', 'r1', 'registered', 'gallon')
    group = groups.ReferenceGroup.build(unit, bundle=bundle)
    response = {'schema_version': '2.0', 'phase': 'GROUP_CORRESPONDENCE', 'unit_id': unit.target.unit_id,
        'status': 'COMPLETE', 'limitations': [], 'assignments': {first.label(): ['t1', 't2'], second.label(): ['t3']},
        'unmatched_target_ids': [], 'unresolved_target_ids': [], 'rows': {}}
    for row_ref, row_source, assigned in ((first, source, target[:2]), (second, (other,), target[2:])):
        source_text = bundle.rows[row_ref].ol_text
        response['rows'][row_ref.label()] = {'status': 'COMPLETE', 'limitations': [],
            'source_expressions': [_expression_payload(x, source_text) for x in row_source],
            'target_roles': [{'expression_id': x.expression_id, 'role': x.role,
                'role_spans': [{'start': a, 'end': b, 'surface': text[a:b]} for a, b in x.role_spans]} for x in assigned]}
    response['rows'][first.label()].update(registered_status='COMPLETE', registered_limitations=[],
        registered_expressions=[_expression_payload(candidate, '60 gallons')])
    evidence = groups.validate_group_correspondence(group, Extraction(target, 'COMPLETE'), response)
    results = groups.evaluate_group(group, Extraction(target, 'COMPLETE'), evidence, bundle=bundle, checks=check_policy(footnotes=False)['checks'])
    assert results[0].final_outcome == ('REVIEW_VALUE_DIFFERENCE' if wrong_residual else 'PASS_UNIT_CONVERSION')
    assert results[1].final_outcome == 'PASS_AUTHORITY1'
    from sage.numbers.models_v2 import GroupResult
    from sage.numbers.engine import _result_reference_context
    from sage.numbers.results_v2 import group_document, _typed_group
    rows = tuple({'western_reference': row.western_reference.label(), 'ol_reference': row.ol_reference,
        'status': 'INDEXED', 'context': _result_reference_context(row, bundle), 'provenance': groups.row_provenance(row, bundle)} for row in group.rows)
    result = GroupResult(unit, Extraction(target, 'COMPLETE'), rows, results, 'COMPLETE',
        {'t1': first.label(), 't2': first.label(), 't3': second.label()}, (), (), (), ())
    raw = group_document(result, checks=check_policy(footnotes=False)['checks'])
    assert raw['reference_rows'][0]['provenance'] == {'ol_source_ids': ['SRC-1'], 'guidance_source_ids': [], 'unit_source_ids': ['UNIT-SOURCE']}
    assert _typed_group(raw).components == results
    if not wrong_residual:
        raw['reference_rows'][0]['provenance']['unit_source_ids'] = ['SRC-1']
        with pytest.raises(ValidationError):
            _typed_group(raw)


def test_neh_registered_absence_is_distinct_from_unindexed_neighbor():
    """NEH 7:68 preserves its nullable authorized reading and unresolved disclosure."""
    from .test_variants import READINGS, reference_case
    row, bundle = reference_case(next(x for x in READINGS if x['BK'] == 'NEH'))
    first, second = row.western_reference, VerseRef('NEH', 7, 69)
    unit = projected(first, '', end=69, western=(first, second))
    group = groups.ReferenceGroup.build(unit, bundle=bundle)
    response = {'schema_version': '2.0', 'phase': 'GROUP_CORRESPONDENCE', 'unit_id': unit.target.unit_id,
        'status': 'PARTIAL', 'limitations': ['UNINDEXED_NEIGHBOR'], 'assignments': {first.label(): [], second.label(): []},
        'unmatched_target_ids': [], 'unresolved_target_ids': [], 'rows': {first.label(): {
            'status': 'COMPLETE', 'limitations': [], 'source_expressions': [], 'target_roles': [],
            'registered_status': 'UNSUPPORTED', 'registered_limitations': ['ALTERNATE_NOT_ASSESSED'], 'registered_expressions': []}}}
    extraction = Extraction((), 'COMPLETE')
    evidence = groups.validate_group_correspondence(group, extraction, response)
    results = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
    assert results[0].ol_reference is None and results[0].reading.semantic.outcome == 'NO_CONFIGURED_OL_READING'
    assert results[0].footnote.action == 'REQUIRE' and results[0].footnote.status == 'NOT_ASSESSED'
    assert results[1].reading.semantic.outcome == 'REFERENCE_NOT_INDEXED'


@pytest.mark.parametrize('damage', ['target_value', 'source_value', 'foreign_row'])
def test_evaluate_group_rebinds_direct_typed_correspondence(damage):
    """Constructed typed correspondence cannot bypass the protected extraction or source authority."""
    group, extraction, response, bundle = bridge_case()
    evidence = groups.validate_group_correspondence(group, extraction, response)
    rows = dict(evidence.rows)
    row = rows['MAT 5:1']
    if damage == 'target_value':
        rows['MAT 5:1'] = replace(row, target_extraction=replace(row.target_extraction,
            expressions=(replace(row.target_extraction.expressions[0], values=(Fraction(9),)),)))
    elif damage == 'source_value':
        rows['MAT 5:1'] = replace(row, source_expressions=(replace(row.source_expressions[0], values=(Fraction(9),)),))
    else:
        rows['MAT 5:3'] = rows.pop('MAT 5:1')
    evidence = replace(evidence, rows=rows)
    with pytest.raises(ValidationError):
        groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])


def test_unmatched_quantity_is_a_parent_addition_without_inventing_a_row():
    """An extra target is counted once while both source rows retain their own passes."""
    from sage.numbers.results_v2 import comparison_view, group_summary, group_findings, group_document, _typed_group
    result, checks = result_case()
    text = result.projected.target.main_text + ' and 5 children'
    extra = replace(expression_at(text, '5', 5, role='children', expression_id='t3', stream_id='main'), role=None, role_spans=())
    result = replace(result, projected=replace(result.projected, target=replace(result.projected.target, main_text=text)),
        extraction=replace(result.extraction, expressions=(*result.extraction.expressions, extra)), unmatched_target_ids=('t3',))
    result = _typed_group(group_document(result, checks=checks))
    assert result.unmatched_target_ids == ('t3',) and result.extraction.expressions[-1].role is None
    assert comparison_view(result, checks=checks).final_outcome == 'REVIEW_NUMBER_ADDED'
    counts = group_summary((result,), checks=checks, findings_count=1)
    assert counts['passes'] == 2 and counts['added_numbers'] == counts['units'] == 1 and counts['expressions'] == 3
    bundle = bridge_case()[3]
    findings = group_findings(result, bundle=bundle, checks=checks)
    assert len(findings) == 1 and findings[0]['western_references'] == ['MAT 5:1', 'MAT 5:2']


@pytest.mark.parametrize('damage', ['source_copy', 'duplicate_source', 'missing_role', 'mapping_foreign', 'unknown_projection', 'unknown_component'])
def test_v2_bridge_replay_rejects_mutated_row_fields(damage):
    """Serialized bridge evidence crosses the same exact row and ownership boundaries."""
    from sage.numbers.results_v2 import group_document, _group_view, _typed_group, component_views
    from sage.numbers.results import _validate_unit, _unit_document
    result, checks = result_case()
    raw = group_document(result, checks=checks)
    if damage == 'source_copy':
        raw['components'][1]['source_expressions'] = raw['components'][0]['source_expressions']
    elif damage == 'duplicate_source':
        raw['components'][0]['source_expressions'] *= 2
    elif damage == 'missing_role':
        raw['extraction']['expressions'][1]['role_spans'] = []
    elif damage == 'mapping_foreign':
        raw['projection']['target_western_mapping'] = {'MAT 5:1': ['MAT 5:99'], 'MAT 5:2': ['MAT 5:2']}
    elif damage == 'unknown_projection':
        raw['projection']['invented'] = True
    else:
        raw['components'][1]['invented'] = True
    with pytest.raises(ValidationError):
        _validate_unit(_group_view(raw, checks), {'SRC-1'}, checks)
        typed = _typed_group(raw)
        for view in component_views(typed):
            _validate_unit(_unit_document(view), {'SRC-1'}, checks)


def test_typed_complete_bridge_requires_exact_source_even_when_reading_unresolved():
    """Complete alignment cannot retain an unaccounted partial source sequence."""
    from sage.numbers.engine import _unsupported_reading
    result, _checks = result_case()
    component = replace(result.components[1], source_expressions=(), reading=_unsupported_reading('CORRESPONDENCE_INCOMPLETE'),
        final_outcome='INSUFFICIENT_EVIDENCE', limitations=('CORRESPONDENCE_INCOMPLETE',))
    with pytest.raises(ValidationError):
        replace(result, components=(result.components[0], component))


@pytest.mark.parametrize('damage', ['anchor', 'marker', 'content', 'one_to_many', 'duplicate_pair', 'neighbor_pair'])
def test_v2_note_metadata_and_evidence_keep_unique_row_ownership(damage):
    """Replayed disclosure cannot change original anchors, exact content, marker, or owner."""
    from sage.numbers.models_v2 import GroupResult
    from sage.numbers.engine import _result_reference_context
    from sage.numbers.results_v2 import group_document, _typed_group
    from .test_footnotes import NoteTasks
    group, extraction, response, bundle = alternate_case()
    checks = check_policy()['checks']
    evidence = groups.validate_group_correspondence(group, extraction, response)
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=checks)
    components = groups.assess_group_notes(group, components, bundle=bundle, checks=checks, language='en', model_tasks=NoteTasks())
    rows = tuple({'western_reference': row.western_reference.label(), 'ol_reference': row.ol_reference,
        'status': 'INDEXED', 'context': _result_reference_context(row, bundle), 'provenance': groups.row_provenance(row, bundle)} for row in group.rows)
    result = GroupResult(group.unit, extraction, rows, components, 'COMPLETE',
        {'t1': 'MAT 5:1', 't2': 'MAT 5:2'}, (), (), (), ())
    raw = group_document(result, checks=checks)
    assert _typed_group(raw).components == result.components
    if damage == 'anchor':
        raw['projection']['target_note_metadata'][0]['anchor_references'] = ['MAT 5:2']
    elif damage == 'marker':
        raw['projection']['target_note_metadata'][0]['marker'] = 'x'
    elif damage == 'content':
        raw['projection']['target_note_metadata'][0]['content_spans'][0]['text'] = 'changed'
    elif damage == 'one_to_many':
        raw['projection']['target_western_mapping']['MAT 5:1'] = ['MAT 5:1', 'MAT 5:2']
    elif damage == 'duplicate_pair':
        raw['components'][0]['footnote']['evidence_note_ids'] *= 2
        raw['components'][0]['footnote']['evidence_spans'] *= 2
    else:
        raw['components'][1]['footnote'] = raw['components'][0]['footnote']
    with pytest.raises(ValidationError):
        _typed_group(raw)


def test_v2_retains_original_row_provenance_and_rejects_neighbor_source():
    """A globally allowed source ID still needs the owning row's original provenance."""
    from sage.numbers.results_v2 import group_document, _typed_group
    result, checks = result_case()
    raw = group_document(result, checks=checks)
    assert raw['reference_rows'][0]['provenance']['ol_source_ids'] == ['SRC-1']
    raw['components'][0]['reading']['source_ids'] = ['NEIGHBOR-SOURCE']
    with pytest.raises(ValidationError):
        _typed_group(raw)


@pytest.mark.parametrize('damage', ['reading', 'provenance', 'registry'])
def test_registered_provenance_remains_separate_from_original_ol_sources(damage):
    """A registered reading cites its owning guidance while retaining original OL provenance."""
    from sage.numbers.models_v2 import GroupResult
    from sage.numbers.engine import _result_reference_context
    from sage.numbers.results_v2 import group_document, _typed_group
    group, extraction, response, bundle = alternate_case()
    ref = group.unit.western_references[0]
    bundle = replace(bundle, footnote_guidance={ref: dict(bundle.footnote_guidance[ref], SOURCE_IDS='GUIDANCE-SOURCE')},
        provenance={**bundle.provenance, 'GUIDANCE-SOURCE': {'SOURCE_ID': 'GUIDANCE-SOURCE'}})
    group = groups.ReferenceGroup.build(group.unit, bundle=bundle)
    evidence = groups.validate_group_correspondence(group, extraction, response)
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
    rows = tuple({'western_reference': row.western_reference.label(), 'ol_reference': row.ol_reference,
        'status': 'INDEXED', 'context': _result_reference_context(row, bundle), 'provenance': groups.row_provenance(row, bundle)} for row in group.rows)
    result = GroupResult(group.unit, extraction, rows, components, 'COMPLETE',
        {'t1': 'MAT 5:1', 't2': 'MAT 5:2'}, (), (), (), ())
    raw = group_document(result, checks=check_policy()['checks'])
    assert raw['reference_rows'][0]['provenance']['ol_source_ids'] == ['SRC-1']
    assert raw['reference_rows'][0]['provenance']['guidance_source_ids'] == ['GUIDANCE-SOURCE']
    assert raw['components'][0]['reading']['source_ids'] == ['GUIDANCE-SOURCE']
    assert _typed_group(raw).components == components
    if damage == 'reading':
        raw['components'][0]['reading']['source_ids'] = ['SRC-1']
    elif damage == 'provenance':
        raw['reference_rows'][0]['provenance']['guidance_source_ids'] = ['SRC-1']
    else:
        raw['components'][0]['reading']['registry_id'] = 'MAT 5:2'
    with pytest.raises(ValidationError):
        _typed_group(raw)


def test_disclosure_span_can_cross_adjacent_original_content_fields():
    """Inline formatting does not split a supported note's contiguous disclosure evidence."""
    from sage.numbers.models_v2 import GroupResult
    from sage.numbers.engine import _result_reference_context
    from .test_footnotes import NoteTasks
    group, extraction, response, bundle = alternate_case()
    note = group.unit.target.notes[0]
    note = replace(note, content_spans=({'kind': 'CONTENT', 'start': 0, 'end': 6, 'text': note.text[:6]},
        {'kind': 'CONTENT', 'start': 6, 'end': len(note.text), 'text': note.text[6:]}))
    group = replace(group, unit=replace(group.unit, target=replace(group.unit.target, notes=(note,))))
    evidence = groups.validate_group_correspondence(group, extraction, response)
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
    components = groups.assess_group_notes(group, components, bundle=bundle, checks=check_policy()['checks'], language='en', model_tasks=NoteTasks())
    rows = tuple({'western_reference': row.western_reference.label(), 'ol_reference': row.ol_reference,
        'status': 'INDEXED', 'context': _result_reference_context(row, bundle), 'provenance': groups.row_provenance(row, bundle)} for row in group.rows)
    result = GroupResult(group.unit, extraction, rows, components, 'COMPLETE',
        {'t1': 'MAT 5:1', 't2': 'MAT 5:2'}, (), (), (), ())
    assert result.components[0].footnote.status == 'ADEQUATE'


def test_parent_insufficiency_counter_includes_every_required_row_note():
    """A neighboring numeric review cannot hide another row's unresolved disclosure."""
    from sage.numbers.models_v2 import GroupResult
    from sage.numbers.engine import _result_reference_context
    from sage.numbers.results_v2 import group_summary
    group, extraction, response, bundle = alternate_case()
    response['rows']['MAT 5:2']['target_roles'] = [{'expression_id': 't2', 'role': 'men',
        'role_spans': [{'start': 2, 'end': 5, 'surface': 'men'}]}]
    evidence = groups.validate_group_correspondence(group, extraction, response)
    checks = check_policy()['checks']
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=checks)
    extraction = replace(extraction, expressions=tuple(x for row in evidence.rows.values() for x in row.target_extraction.expressions))
    rows = tuple({'western_reference': row.western_reference.label(), 'ol_reference': row.ol_reference,
        'status': 'INDEXED', 'context': _result_reference_context(row, bundle), 'provenance': groups.row_provenance(row, bundle)} for row in group.rows)
    result = GroupResult(group.unit, extraction, rows, components, 'COMPLETE',
        {'t1': 'MAT 5:1', 't2': 'MAT 5:2'}, (), (), (), ())
    assert group_summary((result,), checks=checks, findings_count=2)['insufficient_evidence'] == 1


def test_partial_row_keeps_owned_expression_with_unresolved_roles():
    """Partial role interpretation retains exact evidence and cannot discard a resolved neighbor."""
    from sage.numbers.models_v2 import GroupResult
    from sage.numbers.engine import _result_reference_context
    from sage.numbers.results_v2 import group_document, _typed_group
    group, extraction, response, bundle = bridge_case()
    extraction = replace(extraction, expressions=(extraction.expressions[0],
        replace(extraction.expressions[1], role=None, role_spans=())))
    response.update(status='PARTIAL', limitations=['UNRESOLVED_ROLE'])
    response['rows']['MAT 5:2'].update(status='PARTIAL', limitations=['UNRESOLVED_ROLE'], target_roles=[])
    response['rows']['MAT 5:2']['source_expressions'][0].update(role=None, role_spans=[])
    evidence = groups.validate_group_correspondence(group, extraction, response)
    checks = check_policy(footnotes=False)['checks']
    components = groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=checks)
    rows = tuple({'western_reference': row.western_reference.label(), 'ol_reference': row.ol_reference,
        'status': 'INDEXED', 'context': _result_reference_context(row, bundle), 'provenance': groups.row_provenance(row, bundle)} for row in group.rows)
    result = GroupResult(group.unit, extraction, rows, components, 'PARTIAL',
        {'t1': 'MAT 5:1', 't2': 'MAT 5:2'}, (), (), (), ('UNRESOLVED_ROLE',))
    raw = group_document(result, checks=checks)
    assert [c.final_outcome for c in _typed_group(raw).components] == ['PASS_AUTHORITY1', 'INSUFFICIENT_EVIDENCE']
    from sage.numbers.results_v2 import _validate_component_view, component_views
    for view in component_views(result):
        _validate_component_view(view, allowed={'SRC-1'}, checks=checks)
    with pytest.raises(ValidationError):
        replace(result, extraction=replace(result.extraction, expressions=(
            replace(result.extraction.expressions[0], role=None, role_spans=()), result.extraction.expressions[1])))


def test_unassessed_group_still_validates_retained_reference_context():
    """Disabling numeric assessment cannot turn retained source metadata into unchecked fields."""
    result, _checks = result_case()
    row = dict(result.reference_rows[0], context=dict(result.reference_rows[0]['context'], ol_values=(True,)))
    with pytest.raises(ValidationError):
        replace(result, reference_rows=(row, result.reference_rows[1]), components=(), alignment_status='NOT_ASSESSED',
            expression_ownership={}, unmatched_target_ids=('t1', 't2'))


def test_direct_reference_group_cannot_replace_registered_context_authority():
    """A caller-created group must retain the qualified bundle's exact registered context."""
    group, extraction, response, bundle = alternate_case()
    contexts = {key: dict(value, text=value['text'] + ' extra') for key, value in group.registered_contexts.items()}
    group = replace(group, registered_contexts=contexts)
    evidence = groups.validate_group_correspondence(group, extraction, response)
    with pytest.raises(ValidationError):
        groups.evaluate_group(group, extraction, evidence, bundle=bundle, checks=check_policy()['checks'])
