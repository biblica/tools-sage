"""Typed v2 group ownership and externally bounded serialized evidence."""
from dataclasses import replace
import importlib.util

import pytest

from sage.errors import ValidationError
from .test_results import complete_run_result


def test_group_parent_extraction_is_owned_once_and_nested_rows_are_frozen():
    """A target expression cannot be counted twice or attributed outside its parent group."""
    assert importlib.util.find_spec('sage.numbers.models_v2') is not None, 'typed group result is missing'
    from sage.numbers.models_v2 import ComponentResult, GroupResult
    old = complete_run_result().units[0]
    row = dict(old.reference_index[0], context=old.reference_context)
    component = ComponentResult(old.projected.western_references[0], old.ol_references[0],
        ('target-1',), old.source_expressions, old.reading, old.footnote,
        old.final_outcome, old.limitations)
    group = GroupResult(old.projected, old.extraction, (row,), (component,), 'COMPLETE',
        {'target-1': 'MAT 1:1'}, (), (), old.style_findings, old.limitations)
    row['status'] = 'UNINDEXED'
    assert group.reference_rows[0]['status'] == 'INDEXED'
    with pytest.raises(TypeError):
        group.expression_ownership['target-1'] = 'MAT 1:2'
    with pytest.raises(ValidationError):
        replace(group, components=(component, component))
    with pytest.raises(ValidationError):
        replace(group, expression_ownership={'target-1': 'MAT 1:2'})
    with pytest.raises(ValidationError):
        replace(group, alignment_status='PASS')


@pytest.fixture
def canonical_document(make_workspace, monkeypatch):
    """Read the actual controller-published v2 artifact for mutation/replay tests."""
    import json
    from pathlib import Path
    from .test_nca_tasks import _run, _OfflineTasks
    from sage.nca import create_nca_task, execute_nca_task
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    execute_nca_task(config, path)
    manifest = json.loads(path.read_text())
    return json.loads((path.parent / 'output/model-evidence.json').read_text()), tuple(manifest['expected_unit_ids']), tuple(manifest['allowed_evidence_ids'])


def test_v2_dispatcher_preserves_exact_parent_and_component_evidence(canonical_document):
    """The shared entry point uses v2 validation while preserving every serialized evidence field."""
    from sage.numbers.results import validate_numbers_result
    document, expected, allowed = canonical_document
    normalized = validate_numbers_result(document, expected_unit_ids=expected, allowed_evidence_ids=allowed)
    assert normalized == document and 'units' not in normalized
    assert all(len(g['components']) == 1 for g in normalized['groups'])
    assert normalized['limitations']['sqs_confidence_checks_applied'] is False


@pytest.mark.parametrize('damage', ['missing_group', 'duplicate_group', 'extra_field', 'alignment', 'ol_reference',
    'component_ownership', 'unsupported_pass', 'summary_bool', 'receipt_version', 'call_count', 'scope_expansion'])
def test_v2_rejects_fabricated_group_or_execution_claims(canonical_document, damage):
    """A self-reported parent, decision, reference, or counter cannot escape external evidence bounds."""
    from copy import deepcopy
    from sage.numbers.results import validate_numbers_result
    document, expected, allowed = canonical_document
    document = deepcopy(document)
    group = document['groups'][0]
    if damage == 'missing_group':
        document['groups'].pop()
    elif damage == 'duplicate_group':
        document['groups'].append(deepcopy(group))
    elif damage == 'extra_field':
        group['source_evidence'] = {}
    elif damage == 'alignment':
        group['alignment_status'] = 'PASS'
    elif damage == 'ol_reference':
        group['components'][0]['ol_reference'] = 'MAT 99:99'
    elif damage == 'component_ownership':
        group['components'][0]['owned_target_expression_ids'] = ['foreign']
    elif damage == 'unsupported_pass':
        group['extraction']['status'] = 'UNSUPPORTED'
        group['components'][0]['final_outcome'] = 'PASS_AUTHORITY1'
    elif damage == 'summary_bool':
        document['summary']['findings'] = True
    elif damage == 'receipt_version':
        document['model_receipts']['EXTRACTION'][0]['task_version'] = 'nca-extraction-1.0'
    elif damage == 'call_count':
        document['metrics']['provider_calls'] += 1
    else:
        document['coverage']['scope_expansions'] = [{'invented': True}]
    with pytest.raises(ValidationError):
        validate_numbers_result(document, expected_unit_ids=expected, allowed_evidence_ids=allowed)


@pytest.mark.parametrize('damage', ['component_limits', 'missing_planning', 'extra_metrics', 'extra_planning',
    'foreign_plan_input', 'foreign_blocked', 'foreign_missing_owner', 'duplicate_call', 'foreign_request',
    'wrong_call_phase', 'wrong_call_members', 'failed_checkpoint_call', 'duplicate_accepted_member', 'boolean_counter'])
def test_v2_rejects_malformed_new_fields_and_physical_associations(canonical_document, damage):
    """Public replay rejects fields hidden by the legacy view and unbound checkpoint requests."""
    from sage.numbers.results import validate_numbers_result
    document, expected, allowed = canonical_document
    metrics = document['metrics']
    checkpoint = metrics['checkpoints'][0]
    call = next(x for x in metrics['calls'] if x['request_id'] == checkpoint['request_id'])
    if damage == 'component_limits':
        document['groups'][0]['components'][0]['limitations'] = {'invented': True}
    elif damage == 'missing_planning':
        del metrics['planning']
    elif damage == 'extra_metrics':
        metrics['invented'] = 1
    elif damage == 'extra_planning':
        metrics['planning']['invented'] = 1
    elif damage == 'foreign_plan_input':
        metrics['planning']['input_ids'].append('foreign')
    elif damage == 'foreign_blocked':
        metrics['planning']['blocked']['foreign'] = 'blocked'
    elif damage == 'foreign_missing_owner':
        metrics['planning']['missing_owner_ids'].append('foreign')
    elif damage == 'duplicate_call':
        metrics['calls'].append(dict(call))
    elif damage == 'foreign_request':
        checkpoint['request_id'] = 'not-in-calls'
    elif damage == 'wrong_call_phase':
        call['phase'] = 'FOOTNOTE'
    elif damage == 'wrong_call_members':
        call['unit_ids'] = ['foreign']
    elif damage == 'failed_checkpoint_call':
        call['status'] = 'NCA_MODEL_PROVIDER_FAILED'
    elif damage == 'duplicate_accepted_member':
        checkpoint['accepted_input_ids'].append(checkpoint['accepted_input_ids'][0])
        metrics['batch_members'] += 1
    else:
        metrics['accepted_phase_receipts'] = True
    # Keep aggregate counters self-consistent so assertions exercise the public binding boundary.
    from sage.numbers.telemetry import CallMeasurement, summarize_calls
    from sage.numbers.policy import _plain
    metrics.update(_plain(summarize_calls(tuple(CallMeasurement(**dict(x, unit_ids=tuple(x['unit_ids']))) for x in metrics['calls']))))
    with pytest.raises(ValidationError):
        validate_numbers_result(document, expected_unit_ids=expected, allowed_evidence_ids=allowed)


@pytest.mark.parametrize('presentation', [False, True])
def test_heading_result_finalizes_without_suppressing_enabled_body_findings(make_workspace, monkeypatch, presentation):
    """Heading-only policy reaches canonical finalization while body evidence findings stay mandatory."""
    import json
    from pathlib import Path
    from sage.nca import create_nca_job, create_nca_run, create_nca_task, execute_nca_task, finalize_nca_run
    from sage.act_tasks import submit_act_task
    from sage.numbers.results import validate_numbers_result
    from .test_nca_jobs import _prepare_nca_workspace, _route
    from .test_nca_tasks import _OfflineTasks, _EmptyTransport
    from .test_extraction import expression
    class HeadingTransport(_EmptyTransport):
        """Keep body empty while returning literal numbers only from their note or heading stream."""
        def execute(self, request):
            """Preserve production transport accounting and exact stream-bounded numeric responses."""
            response = super().execute(request)
            payload = json.loads(request.prompt)['input']
            raw = json.loads(response.content)
            for stream, item in zip(payload['work_units'], raw['work_units']):
                for digit in ('7', '8'):
                    if digit in stream['text']:
                        start = stream['text'].index(digit)
                        item['expressions'].append(expression('e1', digit, start, start + 1, digit, stream_id=stream['stream_id']))
            return replace(response, content=json.dumps(raw))
    class HeadingTasks(_OfflineTasks):
        """Use the literal heading transport with real builders, validators, and checkpoints."""
        def __init__(self, *args, **kwargs):
            """Override only the external provider transport."""
            super().__init__(*args, **kwargs)
            self._executor = HeadingTransport()
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _style = _prepare_nca_workspace(root)
    (config.project('usWIP').path / '41MAT.SFM').write_text(
        '\\id MAT\n\\c 1\n\\s1 Heading 8\n\\p\n\\v 1 No numbers.\\f + \\ft Note 7\\f*\n', encoding='utf-8')
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1', style_selector='fixture-style/1')
    run = create_nca_run(config, job_id=job.job_id, scope_value='MAT 1:1', checks={'presentation_consistency': presentation})
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', HeadingTasks)
    assert execute_nca_task(config, path)['status'] == 'EXECUTED'
    assert submit_act_task(config, path)['status'] == 'FINALIZED'
    finalized = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    document = json.loads(Path(finalized['result_path']).read_text())
    manifest = json.loads(path.read_text())
    heading = next(g for g in document['groups'] if g['projection']['precision'] == 'STYLE_STREAM')
    assert heading['alignment_status'] == 'NOT_ASSESSED'
    assert not any(f['work_unit_id'] == heading['unit_id'] and f['category'] != 'STYLE' for f in document['findings'])
    assert any(f['category'] == 'EVIDENCE' for f in document['findings'])
    assert Path(finalized['report_path']).is_file()
    document['findings'] = [f for f in document['findings'] if f['category'] != 'EVIDENCE']
    with pytest.raises(ValidationError) as caught:
        validate_numbers_result(document, expected_unit_ids=tuple(manifest['expected_unit_ids']),
            allowed_evidence_ids=tuple(manifest['allowed_evidence_ids']))
    assert caught.value.code == 'NCA_RESULT_FINDING_INVALID'
