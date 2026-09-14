"""Version-two grouped evidence, using strict shared field validation without rewriting v1."""
from __future__ import annotations

from collections.abc import Mapping
from .models import UnitResult, FootnoteDecision
from .models_v2 import GroupResult, OptimizedRunResult
from .results import _unit_document, _plain, _validate_policy, NCA_CAPABILITY_LIMITATION


def comparison_view(group: GroupResult, *, checks: Mapping[str, bool]) -> UnitResult:
    """Expose one parent for existing comparison counters, never duplicate its extraction."""
    from .engine import _unsupported_reading, _not_assessed_reading
    component = group.components[0] if group.components else None
    assessed = group.projected.precision != 'STYLE_STREAM' and (checks['number_accuracy'] or checks['footnote_review'])
    reading = component.reading if component else (_unsupported_reading('GROUP_ALIGNMENT_UNRESOLVED') if assessed else _not_assessed_reading())
    footnote = component.footnote if component else FootnoteDecision('NONE', 'NOT_ASSESSED', 'NONE')
    final = component.final_outcome if component else 'INSUFFICIENT_EVIDENCE' if assessed and checks['number_accuracy'] else 'NOT_ASSESSED'
    return UnitResult(group.projected, group.extraction, reading, footnote, final, group.style_findings, group.limitations,
        tuple(row['ol_reference'] for row in group.reference_rows if row['status'] != 'UNINDEXED'),
        component.source_expressions if component else (),
        group.reference_rows[0]['context'] if component else {},
        tuple({k: v for k, v in row.items() if k != 'context'} for row in group.reference_rows))


def group_document(group: GroupResult, *, checks: Mapping[str, bool]) -> dict[str, object]:
    """Serialize parent extraction once and keep component source and attribution separate."""
    unit = _unit_document(comparison_view(group, checks=checks))
    components = []
    for component in group.components:
        components.append({'western_reference': component.western_reference.label(), 'ol_reference': component.ol_reference,
            'owned_target_expression_ids': list(component.owned_target_expression_ids),
            'source_expressions': unit['source_evidence']['expressions'], 'reading': unit['reading'],
            'footnote': unit['footnote'], 'final_outcome': component.final_outcome, 'limitations': list(component.limitations)})
    return {'unit_id': unit['unit_id'], 'projection': unit['projection'], 'extraction': unit['extraction'],
        'reference_rows': _plain(group.reference_rows), 'components': components,
        'alignment_status': group.alignment_status, 'expression_ownership': dict(group.expression_ownership),
        'unmatched_target_ids': list(group.unmatched_target_ids), 'unresolved_target_ids': list(group.unresolved_target_ids),
        'style_findings': unit['style_findings'], 'limitations': list(group.limitations)}


def numbers_result_document_v2(result: OptimizedRunResult, *, provenance: Mapping[str, object],
    check_policy: Mapping[str, object], model_receipts: Mapping[str, object]) -> dict[str, object]:
    """Build exact v2 evidence with the original phase receipts and protected group identity."""
    from sage.errors import ValidationError
    if not isinstance(result, OptimizedRunResult):
        raise ValidationError('Optimized result required', code='NCA_RESULT_SCHEMA_INVALID')
    return {'schema_version': '2.0', 'workflow': 'nca', 'check_id': 'NUMBERS', 'provenance': _plain(provenance),
        'check_policy': _validate_policy(check_policy), 'model_receipts': _plain(model_receipts),
        'limitations': {'capability': NCA_CAPABILITY_LIMITATION, 'sqs_confidence_checks_applied': False},
        'groups': [group_document(g, checks=check_policy['checks']) for g in result.groups],
        'findings': _plain(result.findings), 'coverage': _plain(result.coverage),
        'summary': _plain(result.summary), 'metrics': _plain(result.metrics)}


def _require(condition: bool, message: str, code: str = 'NCA_RESULT_SCHEMA_INVALID') -> None:
    """Reject contradictory or unbounded v2 evidence with a stable machine diagnostic."""
    from sage.errors import ValidationError
    if not condition:
        raise ValidationError(message, code=code)


def _group_view(group: Mapping[str, object], checks: Mapping[str, bool]) -> dict[str, object]:
    """Validate group ownership then construct shared field-validation input once per parent."""
    from .results import _require_keys, _expression_document
    from .engine import _unsupported_reading, _not_assessed_reading
    _require_keys(group, {'unit_id', 'projection', 'extraction', 'reference_rows', 'components', 'alignment_status',
        'expression_ownership', 'unmatched_target_ids', 'unresolved_target_ids', 'style_findings', 'limitations'}, 'group')
    projection, rows, components = group['projection'], group['reference_rows'], group['components']
    _require(isinstance(projection, Mapping) and isinstance(rows, list) and isinstance(components, list), 'Invalid group structure')
    refs = projection['western_references']
    _require(group['alignment_status'] in {'COMPLETE', 'UNAVAILABLE', 'NOT_ASSESSED'}, 'Invalid alignment status')
    _require(len(rows) == len(refs), 'Reference row coverage differs', 'NCA_RESULT_REFERENCE_INVALID')
    for row, ref, index in zip(rows, refs, projection['reference_index']):
        _require(isinstance(row, Mapping) and set(row) == {'western_reference', 'ol_reference', 'status', 'context'}
            and row['western_reference'] == ref and {k: v for k, v in row.items() if k != 'context'} == index,
            'Reference row identity differs', 'NCA_RESULT_REFERENCE_INVALID')
    ids = [x['expression_id'] for x in group['extraction']['expressions']]
    ownership = group['expression_ownership']
    _require(isinstance(ownership, Mapping), 'Invalid expression ownership')
    owned = {}
    for component in components:
        _require(isinstance(component, Mapping), 'Invalid component')
        _require_keys(component, {'western_reference', 'ol_reference', 'owned_target_expression_ids', 'source_expressions',
            'reading', 'footnote', 'final_outcome', 'limitations'}, 'component')
        _require(isinstance(component['limitations'], list)
            and all(isinstance(x, str) and x for x in component['limitations']), 'Invalid component limitations')
        ref = component['western_reference']
        _require(ref in refs and component['ol_reference'] == rows[refs.index(ref)]['ol_reference'], 'Foreign component reference')
        _require(isinstance(component['owned_target_expression_ids'], list), 'Invalid component ownership')
        for eid in component['owned_target_expression_ids']:
            _require(isinstance(eid, str) and eid in ids and eid not in owned, 'Duplicate or foreign expression ownership')
            owned[eid] = ref
    component_refs = [x['western_reference'] for x in components]
    _require(len(set(component_refs)) == len(component_refs) and dict(ownership) == owned, 'Ownership ledger differs')
    for name in ('unmatched_target_ids', 'unresolved_target_ids'):
        _require(isinstance(group[name], list) and all(isinstance(x, str) for x in group[name]), 'Invalid attribution IDs')
    ledger = list(owned) + group['unmatched_target_ids'] + group['unresolved_target_ids']
    _require(len(ledger) == len(set(ledger)) and set(ledger) == set(ids), 'Incomplete attribution ledger')
    # Task 7 supplies multirow adjudication; no caller may claim that implementation early.
    _require(len(components) <= 1, 'Multirow component adjudication is unavailable')
    if group['alignment_status'] == 'COMPLETE':
        _require(len(refs) == 1 and component_refs == refs and not group['unresolved_target_ids'], 'Incomplete resolved group')
    elif group['alignment_status'] == 'NOT_ASSESSED':
        _require(not components and (projection['precision'] == 'STYLE_STREAM' or not (checks['number_accuracy'] or checks['footnote_review'])), 'Invalid unassessed group')
    else:
        _require(not components and bool(group['limitations']) and len(refs) != 1, 'Unresolved group cannot assert components')
    component = components[0] if components else None
    assessed = projection['precision'] != 'STYLE_STREAM' and (checks['number_accuracy'] or checks['footnote_review'])
    fallback = _unsupported_reading('GROUP_ALIGNMENT_UNRESOLVED') if assessed else _not_assessed_reading()
    reading = component['reading'] if component else {'selected': fallback.selected, 'footnote_action': fallback.footnote_action,
        'registry_id': None, 'source_ids': [], 'source_validation_outcome': None,
        'semantic': {'outcome': fallback.semantic.outcome, 'evidence_ids': [], 'reason_codes': list(fallback.semantic.reason_codes)}}
    return {'unit_id': group['unit_id'], 'projection': projection, 'extraction': group['extraction'],
        'source_evidence': {'expressions': component['source_expressions'] if component else [], 'context': rows[0]['context'] if component else {}},
        'reading': reading, 'footnote': component['footnote'] if component else {'action': 'NONE', 'status': 'NOT_ASSESSED', 'outcome': 'NONE', 'evidence_spans': [], 'evidence_note_ids': []},
        'final_outcome': component['final_outcome'] if component else 'INSUFFICIENT_EVIDENCE' if assessed and checks['number_accuracy'] else 'NOT_ASSESSED',
        'style_findings': group['style_findings'], 'limitations': group['limitations']}


def _validate_numbers_result_v2(document: Mapping[str, object], *, expected_unit_ids: tuple[str, ...],
                               allowed_evidence_ids: tuple[str, ...]) -> dict[str, object]:
    """Strictly validate parent evidence, component attribution, coverage, and physical metrics."""
    from .results import (_require_keys, _validate_provenance, _validate_unit, _validate_findings,
                          _validate_coverage, _summary_document, _RECEIPT_FIELDS, _validate_hash)
    from .policy import validate_optimization_policy
    from .replay import PhaseKey
    from .telemetry import CallMeasurement, summarize_calls
    from .model_tasks import ModelPhaseReceipt
    _require(isinstance(document, Mapping), 'Result must be an object')
    _require_keys(document, {'schema_version', 'workflow', 'check_id', 'provenance', 'check_policy', 'model_receipts',
        'limitations', 'groups', 'findings', 'coverage', 'summary', 'metrics'}, 'v2 result')
    _require(document['schema_version'] == '2.0' and document['workflow'] == 'nca' and document['check_id'] == 'NUMBERS', 'Invalid v2 result identity')
    _validate_provenance(document['provenance'])
    policy = _validate_policy(document['check_policy'])
    _require(policy.get('schema_version') == '2.0', 'V2 result requires a v2 sealed policy')
    validate_optimization_policy(policy.get('optimization'))
    _require(document['limitations'] == {'capability': NCA_CAPABILITY_LIMITATION, 'sqs_confidence_checks_applied': False}, 'Capability limitation is required')
    checks = policy['checks']
    groups = document['groups']
    _require(isinstance(groups, list) and all(isinstance(x, Mapping) for x in groups), 'Invalid groups')
    _require(len(set(allowed_evidence_ids)) == len(allowed_evidence_ids), 'Duplicate allowed evidence')
    unit_checks = {g['unit_id']: dict(checks, number_accuracy=False, footnote_review=False)
        if g['projection']['precision'] == 'STYLE_STREAM' else checks for g in groups}
    units = [_validate_unit(_group_view(g, checks), set(allowed_evidence_ids), unit_checks[g['unit_id']]) for g in groups]
    findings = _validate_findings(document['findings'], set(allowed_evidence_ids), units=units, checks=checks, unit_checks=unit_checks)
    complete = all((u['extraction']['status'] == 'COMPLETE' or 'PRESENTATION_CHECK_DISABLED' in u['limitations'])
        and g['alignment_status'] != 'UNAVAILABLE' and (u['projection']['precision'] == 'STYLE_STREAM'
            or (u['reading']['semantic']['outcome'] not in {'INSUFFICIENT_EVIDENCE', 'REFERENCE_NOT_INDEXED'}
                and u['footnote']['outcome'] != 'INSUFFICIENT_EVIDENCE')) for g, u in zip(groups, units))
    _validate_coverage(document['coverage'], expected_unit_ids, [u['unit_id'] for u in units],
                       findings_count=len(findings), required_evidence_complete=complete)
    _require(all(type(x) is int for x in document['summary'].values()) and document['summary'] == _summary_document(units, findings, checks), 'Summary differs from grouped evidence', 'NCA_RESULT_SUMMARY_INVALID')
    coverage = document['coverage']
    from sage.references import parse_scope
    scope = parse_scope(coverage['requested_scope'])
    from sage.vrs import VerseRef
    import re
    def reference(label):
        """Parse an exact Western or target coordinate without accepting arbitrary labels."""
        match = re.fullmatch(r'([1-3]?[A-Z]{2,3}) ([0-9]+):([0-9]+)', label)
        _require(match is not None, 'Malformed coordinate', 'NCA_RESULT_REFERENCE_INVALID')
        return VerseRef(match[1], int(match[2]), int(match[3]))
    expansions = []
    candidates = []
    for g in groups:
        refs = g['projection']['target_references']
        outside = [r for r in refs if not scope.contains(reference(r))]
        if outside:
            expansions.append({'unit_id': g['unit_id'], 'included_target_references': outside, 'western_references': g['projection']['western_references']})
        if g['projection']['precision'] != 'STYLE_STREAM' and (any(r['status'] != 'UNINDEXED' for r in g['reference_rows'])
                or g['extraction']['status'] != 'COMPLETE' or any(e['stream_id'] == 'main' for e in g['extraction']['expressions'])):
            candidates.append(g['unit_id'])
    _require(coverage['scope_expansions'] == expansions and coverage['candidate_group_ids'] == sorted(candidates), 'Scope ledger differs', 'NCA_RESULT_COVERAGE_INVALID')
    metrics, receipts = document['metrics'], document['model_receipts']
    phases = ('EXTRACTION', 'CORRESPONDENCE', 'FOOTNOTE', 'GROUP_CORRESPONDENCE')
    _require(isinstance(metrics, Mapping) and isinstance(receipts, Mapping) and set(receipts) == set(phases), 'Invalid phase evidence')
    _require_keys(metrics, set(summarize_calls(())) | {'accepted_phase_receipts', 'checkpoint_reuse',
        'reused_checkpoint_ids', 'batch_members', 'calls', 'checkpoints', 'planning'}, 'metrics')
    _require(isinstance(metrics['calls'], list), 'Physical calls must be an array')
    from dataclasses import fields
    for raw in metrics['calls']:
        _require(isinstance(raw, Mapping), 'Invalid physical call')
        _require_keys(raw, {field.name for field in fields(CallMeasurement)}, 'physical call')
        _require(isinstance(raw['unit_ids'], list) and len(set(raw['unit_ids'])) == len(raw['unit_ids']), 'Invalid call members')
    calls = tuple(CallMeasurement(**dict(x, unit_ids=tuple(x['unit_ids']))) for x in metrics['calls'])
    calls_by_id = {call.request_id: call for call in calls}
    _require(len(calls_by_id) == len(calls) and all(call.phase in phases and not call.reused for call in calls),
        'Physical calls must be unique original requests')
    derived = _plain(summarize_calls(calls))
    import json
    _require(json.dumps({k: metrics[k] for k in derived}, sort_keys=True) == json.dumps(derived, sort_keys=True), 'Physical call counters differ')
    for name in ('accepted_phase_receipts', 'checkpoint_reuse', 'batch_members'):
        _require(type(metrics[name]) is int and metrics[name] >= 0, 'Invalid exact phase counter')
    planning = metrics['planning']
    _require(isinstance(planning, Mapping), 'Invalid planning evidence')
    _require_keys(planning, {'input_ids', 'blocked', 'missing_owner_ids'}, 'planning')
    for name in ('input_ids', 'missing_owner_ids'):
        _require(isinstance(planning[name], list) and all(isinstance(x, str) and x for x in planning[name])
            and len(set(planning[name])) == len(planning[name]), 'Invalid planning identities')
    planned = set(planning['input_ids'])
    _require(all(re.fullmatch(r'input:[0-9a-f]{64}', x) for x in planned), 'Invalid planned input identity')
    blocked = planning['blocked']
    _require(isinstance(blocked, Mapping) and set(blocked) <= planned
        and all(isinstance(x, str) and x for x in blocked.values()), 'Invalid blocked inputs')
    _require(set(planning['missing_owner_ids']) <= set(expected_unit_ids), 'Foreign missing owner')
    for call in calls:
        _require(set(call.unit_ids) <= (planned if call.phase == 'EXTRACTION' else set(expected_unit_ids)), 'Foreign physical call inputs')
    checkpoints = metrics['checkpoints']
    _require(isinstance(checkpoints, list) and len({x['checkpoint_id'] for x in checkpoints}) == len(checkpoints), 'Duplicate checkpoints')
    actual_receipts = {phase: [] for phase in phases}
    accepted_members, checkpoint_requests, phase_keys, task_bindings = set(), set(), set(), set()
    for checkpoint in checkpoints:
        _require_keys(checkpoint, {'checkpoint_id', 'key', 'receipt', 'request_id', 'accepted_input_ids'}, 'checkpoint reference')
        key = PhaseKey.from_dict(checkpoint['key'])
        _require(isinstance(checkpoint['checkpoint_id'], str) and re.fullmatch(r'[0-9a-f]{32}', checkpoint['checkpoint_id']) is not None,
            'Invalid checkpoint identity')
        call = calls_by_id.get(checkpoint['request_id'])
        _require(call is not None and call.phase == key.phase and call.unit_ids == key.input_ids
            and call.status == 'VALIDATED', 'Checkpoint request does not bind an accepted physical call')
        _require(call.request_id not in checkpoint_requests and key.identity not in phase_keys, 'Repeated accepted request or phase key')
        checkpoint_requests.add(call.request_id)
        phase_keys.add(key.identity)
        task_bindings.add((key.task_fingerprint, key.policy_sha256, key.route_sha256))
        receipt = checkpoint['receipt']
        _require(set(receipt) == _RECEIPT_FIELDS and key.phase in phases and receipt['phase'] == key.phase
            and receipt['task_version'] == 'nca-' + key.phase.lower().replace('_', '-') + '-2.0', 'Invalid v2 receipt')
        ModelPhaseReceipt(**receipt)
        for field in ('prompt_sha256', 'input_sha256', 'response_sha256'):
            _validate_hash(receipt[field], field)
        _require(all(receipt[k] == policy['model_route'][k] for k in ('route_id', 'provider', 'model', 'reasoning_effort')), 'Receipt route differs')
        members = checkpoint['accepted_input_ids']
        _require(isinstance(members, list) and all(isinstance(x, str) for x in members)
            and len(set(members)) == len(members) and set(members) <= set(key.input_ids), 'Duplicate or foreign batch member')
        _require(bool(members) if key.phase == 'EXTRACTION' else not members, 'Invalid accepted phase membership')
        _require(not accepted_members.intersection(members), 'Repeated accepted extraction member')
        accepted_members.update(members)
        actual_receipts[key.phase].append(receipt)
    _require(len(task_bindings) <= 1, 'Checkpoint task or policy bindings differ')
    _require(not accepted_members.intersection(blocked) and accepted_members | set(blocked) == planned, 'Planning dispositions do not cover exact inputs')
    _require(actual_receipts == receipts, 'Receipt ledger differs')
    _require(metrics['accepted_phase_receipts'] == len(checkpoints) and metrics['batch_members'] == sum(len(x['accepted_input_ids']) for x in checkpoints), 'Receipt or member count differs')
    reused = metrics['reused_checkpoint_ids']
    _require(isinstance(reused, list) and all(isinstance(x, str) for x in reused)
        and len(set(reused)) == len(reused) and set(reused) <= {x['checkpoint_id'] for x in checkpoints}
        and metrics['checkpoint_reuse'] == len(reused), 'Checkpoint reuse differs')
    _require(not any(g['extraction']['status'] in {'COMPLETE', 'PARTIAL'} for g in groups) or bool(receipts['EXTRACTION']), 'Assessed extraction needs a receipt')
    if (checks['number_accuracy'] or checks['footnote_review']) and any(
            u['reading']['selected'] in {'OL', 'ALT'} or u['reading']['semantic']['outcome'] in
            {'REVIEW_NUMBER_MISSING', 'REVIEW_NUMBER_ADDED', 'REVIEW_VALUE_DIFFERENCE'} for u in units):
        _require(bool(receipts['CORRESPONDENCE']), 'Semantic adjudication needs a correspondence receipt')
    if checks['footnote_review'] and any(u['footnote']['status'] in {'ADEQUATE', 'INADEQUATE'} for u in units):
        _require(bool(receipts['FOOTNOTE']), 'Footnote assessment needs a receipt')
    return _plain(document)


def validate_numbers_result_v2(document: Mapping[str, object], *, expected_unit_ids: tuple[str, ...],
                               allowed_evidence_ids: tuple[str, ...]) -> dict[str, object]:
    """Normalize malformed public JSON failures into the version-specific validation boundary."""
    from sage.errors import ValidationError
    try:
        return _validate_numbers_result_v2(document, expected_unit_ids=expected_unit_ids, allowed_evidence_ids=allowed_evidence_ids)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationError('Malformed v2 result evidence', code='NCA_RESULT_SCHEMA_INVALID') from exc
