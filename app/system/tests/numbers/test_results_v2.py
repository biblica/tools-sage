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
