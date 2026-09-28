"""Version-two grouped evidence, using strict shared field validation without rewriting v1."""
from __future__ import annotations

from collections.abc import Mapping
from .models import UnitResult, FootnoteDecision
from .models_v2 import GroupResult, OptimizedRunResult
from .results import _unit_document, _expression_document, _plain, _validate_policy, NCA_CAPABILITY_LIMITATION


def component_views(group: GroupResult) -> tuple[UnitResult, ...]:
    """Expose row-owned evidence for existing policies and coordinate-specific findings."""
    from dataclasses import replace
    rows = {row['western_reference']: row for row in group.reference_rows}
    views = []
    for component in group.components:
        row = rows[component.western_reference.label()]
        projected = replace(group.projected, western_references=(component.western_reference,),
            status='REGISTERED_ABSENCE' if row['status'] == 'REGISTERED_ABSENCE' else group.projected.status,
            target_western_mapping={})
        extraction = replace(group.extraction, expressions=tuple(x for x in group.extraction.expressions
            if x.expression_id in component.owned_target_expression_ids))
        views.append(UnitResult(projected, extraction, component.reading, component.footnote,
            component.final_outcome, (), component.limitations,
            (component.ol_reference,) if row['status'] != 'UNINDEXED' else (),
            component.source_expressions, row['context'], ({k: v for k, v in row.items() if k not in {'context', 'provenance'}},)))
    return tuple(views)


def comparison_view(group: GroupResult, *, checks: Mapping[str, bool]) -> UnitResult:
    """Summarize the parent once while retaining all row outcomes in component views."""
    from .engine import _unsupported_reading, _not_assessed_reading
    from .models import ReadingDecision, SemanticDecision
    component = group.components[0] if group.components else None
    assessed = group.projected.precision != 'STYLE_STREAM' and (checks['number_accuracy'] or checks['footnote_review'])
    if len(group.components) > 1:
        severity = ('REFERENCE_NOT_INDEXED', 'INSUFFICIENT_EVIDENCE', 'REVIEW_MISSING_FOOTNOTE',
            'REVIEW_VALUE_DIFFERENCE', 'REVIEW_NUMBER_MISSING', 'REVIEW_NUMBER_ADDED', 'REGISTERED_ALTERNATE')
        component = min(group.components, key=lambda c: severity.index(c.final_outcome) if c.final_outcome in severity else len(severity))
    reading = component.reading if component else (_unsupported_reading('GROUP_ALIGNMENT_UNRESOLVED') if assessed else _not_assessed_reading())
    footnote = component.footnote if component else FootnoteDecision('NONE', 'NOT_ASSESSED', 'NONE')
    final = component.final_outcome if component else 'INSUFFICIENT_EVIDENCE' if assessed and checks['number_accuracy'] else 'NOT_ASSESSED'
    if assessed and group.alignment_status in {'PARTIAL', 'UNAVAILABLE'}:
        reading = _unsupported_reading(group.limitations[0] if group.alignment_status == 'PARTIAL' and group.limitations else 'GROUP_ALIGNMENT_UNRESOLVED')
        final = 'INSUFFICIENT_EVIDENCE' if checks['number_accuracy'] else 'NOT_ASSESSED'
        footnote = FootnoteDecision('NONE', 'NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE' if checks['footnote_review'] else 'NONE')
    elif assessed and group.unmatched_target_ids:
        reading = ReadingDecision('UNSUPPORTED', SemanticDecision('REVIEW_NUMBER_ADDED', reason_codes=('UNMATCHED_TARGET_EXPRESSIONS',)), 'NONE', None, ())
        final = 'REVIEW_NUMBER_ADDED' if checks['number_accuracy'] else 'NOT_ASSESSED'
        footnote = FootnoteDecision('NONE', 'NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE' if checks['footnote_review'] else 'NONE')
    return UnitResult(group.projected, group.extraction, reading, footnote, final, group.style_findings, group.limitations,
        tuple(row['ol_reference'] for row in group.reference_rows if row['status'] != 'UNINDEXED'),
        component.source_expressions if component and len(group.components) == 1 else (),
        group.reference_rows[0]['context'] if component and len(group.components) == 1 else {},
        tuple({k: v for k, v in row.items() if k not in {'context', 'provenance'}} for row in group.reference_rows))


def group_findings(group: GroupResult, *, bundle, checks: Mapping[str, bool]) -> list[dict[str, object]]:
    """Emit attributed row findings plus one parent presentation and allocation assessment."""
    from .engine import _unit_findings
    parent = comparison_view(group, checks=checks)
    if not group.components:
        return _unit_findings(parent, bundle=bundle, checks=checks)
    found = [item for view in component_views(group) for item in _unit_findings(view, bundle=bundle,
        checks=dict(checks, presentation_consistency=False))]
    parent_checks = dict(checks, number_accuracy=checks['number_accuracy'] and bool(group.unmatched_target_ids or group.unresolved_target_ids), footnote_review=False)
    found.extend(_unit_findings(parent, bundle=bundle, checks=parent_checks))
    return found


def group_summary(groups: tuple[GroupResult, ...], *, checks: Mapping[str, bool], findings_count: int) -> dict[str, int]:
    """Count extraction parents once and numeric assessments at their owning coordinates."""
    from .engine import summarize
    summary = dict(summarize(tuple(comparison_view(g, checks=checks) for g in groups), checks=checks))
    row_counts = summarize(tuple(view for g in groups for view in (component_views(g) or (comparison_view(g, checks=checks),))), checks=checks)
    for key in ('ol_expressions_checked', 'passes', 'unit_conversions', 'value_differences', 'missing_numbers',
                'added_numbers', 'known_variants', 'reference_not_indexed'):
        summary[key] = row_counts[key]
    summary['added_numbers'] += sum(bool(g.components and g.unmatched_target_ids and g.alignment_status == 'COMPLETE') for g in groups) if checks['number_accuracy'] else 0
    summary['insufficient_evidence'] = sum('PRESENTATION_CHECK_DISABLED' not in g.limitations and (
        g.extraction.status != 'COMPLETE' or g.alignment_status in {'PARTIAL', 'UNAVAILABLE'}
        or any(c.reading.semantic.outcome == 'INSUFFICIENT_EVIDENCE' or c.footnote.outcome == 'INSUFFICIENT_EVIDENCE'
            for c in g.components)) for g in groups)
    summary['findings'] = findings_count
    return summary


def group_document(group: GroupResult, *, checks: Mapping[str, bool]) -> dict[str, object]:
    """Serialize each component's exact evidence and retain projection metadata only in v2."""
    unit = _unit_document(comparison_view(group, checks=checks))
    components = []
    for component, view in zip(group.components, component_views(group)):
        row = _unit_document(view)
        components.append({'western_reference': component.western_reference.label(), 'ol_reference': component.ol_reference,
            'owned_target_expression_ids': list(component.owned_target_expression_ids),
            'source_expressions': row['source_evidence']['expressions'], 'reading': row['reading'],
            'footnote': row['footnote'], 'final_outcome': component.final_outcome, 'limitations': list(component.limitations)})
    unit['projection']['target_western_mapping'] = _plain(group.projected.target_western_mapping)
    unit['projection']['target_note_metadata'] = [{'note_id': note.note_id, 'marker': note.marker,
        'anchor_references': [ref.label() for ref in note.anchor_references], 'content_spans': _plain(note.content_spans)}
        for note in group.projected.target.notes]
    return {'unit_id': unit['unit_id'], 'projection': unit['projection'], 'extraction': unit['extraction'],
        'reference_rows': _plain(group.reference_rows), 'components': components,
        'alignment_status': group.alignment_status, 'expression_ownership': dict(group.expression_ownership),
        'unmatched_target_ids': list(group.unmatched_target_ids), 'unresolved_target_ids': list(group.unresolved_target_ids),
        'style_findings': unit['style_findings'], 'limitations': list(group.limitations),
        **({'note_extractions': {key: {'status': value.status, 'limitations': list(value.limitations),
            'expressions': [_expression_document(item) for item in value.expressions]}
            for key, value in group.note_extractions.items()}} if group.note_extractions is not None else {})}


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
    from .results import _require_keys
    from .usage import validate_note_extractions
    from .engine import _unsupported_reading, _not_assessed_reading
    _require_keys(group, {'unit_id', 'projection', 'extraction', 'reference_rows', 'components', 'alignment_status',
        'expression_ownership', 'unmatched_target_ids', 'unresolved_target_ids', 'style_findings', 'limitations'}
        | ({'note_extractions'} if 'note_extractions' in group else set()), 'group')
    projection, rows, components = group['projection'], group['reference_rows'], group['components']
    _require(isinstance(projection, Mapping) and isinstance(rows, list) and isinstance(components, list), 'Invalid group structure')
    if 'note_extractions' in group:
        validate_note_extractions(group['note_extractions'], projection, enabled=checks['presentation_consistency'])
    refs = projection['western_references']
    _require(group['alignment_status'] in {'COMPLETE', 'PARTIAL', 'UNAVAILABLE', 'NOT_ASSESSED'}, 'Invalid alignment status')
    _require(len(rows) == len(refs), 'Reference row coverage differs', 'NCA_RESULT_REFERENCE_INVALID')
    for row, ref, index in zip(rows, refs, projection['reference_index']):
        _require(isinstance(row, Mapping) and set(row) == {'western_reference', 'ol_reference', 'status', 'context', 'provenance'}
            and row['western_reference'] == ref and {k: v for k, v in row.items() if k not in {'context', 'provenance'}} == index,
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
    if group['alignment_status'] == 'COMPLETE':
        _require(component_refs == refs and not group['unresolved_target_ids'], 'Incomplete resolved group')
    elif group['alignment_status'] == 'NOT_ASSESSED':
        _require(not components and (projection['precision'] == 'STYLE_STREAM' or not (checks['number_accuracy'] or checks['footnote_review'])), 'Invalid unassessed group')
    elif group['alignment_status'] == 'PARTIAL':
        _require(component_refs == refs and bool(group['limitations']), 'Partial group must retain its row ledger')
    else:
        _require(not components and bool(group['limitations']), 'Unavailable group cannot assert components')
    component = components[0] if len(components) == 1 else None
    assessed = projection['precision'] != 'STYLE_STREAM' and (checks['number_accuracy'] or checks['footnote_review'])
    fallback = _unsupported_reading('GROUP_ALIGNMENT_UNRESOLVED') if assessed else _not_assessed_reading()
    reading = component['reading'] if component else {'selected': fallback.selected, 'footnote_action': fallback.footnote_action,
        'registry_id': None, 'source_ids': [], 'source_validation_outcome': None,
        'semantic': {'outcome': fallback.semantic.outcome, 'evidence_ids': [], 'reason_codes': list(fallback.semantic.reason_codes)}}
    projection = {k: v for k, v in projection.items() if k not in {'target_western_mapping', 'target_note_metadata'}}
    if any(row['status'] == 'REGISTERED_ABSENCE' for row in rows):
        projection = dict(projection, status='REGISTERED_ABSENCE')
    return {'unit_id': group['unit_id'], 'projection': projection, 'extraction': group['extraction'],
        'source_evidence': {'expressions': component['source_expressions'] if component else [], 'context': rows[0]['context'] if component else {}},
        'reading': reading, 'footnote': component['footnote'] if component else {'action': 'NONE', 'status': 'NOT_ASSESSED', 'outcome': 'NONE', 'evidence_spans': [], 'evidence_note_ids': []},
        'final_outcome': component['final_outcome'] if component else 'INSUFFICIENT_EVIDENCE' if assessed and checks['number_accuracy'] else 'NOT_ASSESSED',
        'style_findings': group['style_findings'], 'limitations': group['limitations']}


def _typed_group(raw: Mapping[str, object]) -> GroupResult:
    """Reconstruct immutable evidence only after checking exact v2 projection metadata."""
    from fractions import Fraction
    import re
    from sage.vrs import VerseRef
    from .models import (TargetUnit, TargetNote, ProjectedUnit, Extraction, NumericExpression,
                         ReadingDecision, SemanticDecision)
    from .models_v2 import ComponentResult
    def reference(label):
        """Parse a coordinate without identity fallback or permissive scope parsing."""
        match = re.fullmatch(r'([1-3]?[A-Z]{2,3}) ([0-9]+):([0-9]+)', label)
        _require(match is not None, 'Invalid projection coordinate')
        return VerseRef(match[1], int(match[2]), int(match[3]))
    def expression(item):
        """Restore exact rational values and immutable evidence spans."""
        return NumericExpression(tuple(Fraction(x) for x in item['values']), item['kind'], item['surface'],
            tuple(item['span']), item['unit'], item['qualifier'], item['role'],
            expression_id=item['expression_id'], stream_id=item['stream_id'],
            representations=tuple(item['representations']), role_spans=tuple(tuple(x) for x in item['role_spans']))
    projection = raw['projection']
    mapping = projection['target_western_mapping']
    _require(isinstance(mapping, Mapping) and all(isinstance(v, list) for v in mapping.values()), 'Invalid target Western mapping')
    metadata = projection['target_note_metadata']
    streams = projection['target_note_streams']
    _require(isinstance(metadata, list) and len(metadata) == len(streams), 'Incomplete note metadata')
    notes = []
    for item, stream in zip(metadata, streams):
        _require(isinstance(item, Mapping) and set(item) == {'note_id', 'marker', 'anchor_references', 'content_spans'}
            and item['note_id'] == stream['note_id'] and isinstance(item['marker'], str)
            and isinstance(item['anchor_references'], list) and isinstance(item['content_spans'], list), 'Invalid note metadata')
        for span in item['content_spans']:
            _require(isinstance(span, Mapping), 'Invalid note content span')
            if span.get('kind') == 'CONTENT':
                _require(set(span) == {'kind', 'start', 'end', 'text'} and type(span['start']) is int
                    and type(span['end']) is int and 0 <= span['start'] < span['end'] <= len(stream['text'])
                    and stream['text'][span['start']:span['end']] == span['text'], 'Invalid exact note content')
            else:
                _require(set(span) == {'kind', 'marker', 'text'} and span['kind'] == 'LOCATOR'
                    and span['marker'] in {'fr', 'fv'} and isinstance(span['text'], str), 'Invalid note locator')
        notes.append(TargetNote(item['note_id'], item['marker'], stream['text'],
            tuple(reference(x) for x in item['anchor_references']), tuple(item['content_spans'])))
    target = TargetUnit(raw['unit_id'], tuple(reference(x) for x in projection['target_references']),
        projection['target_text'], tuple(notes), projection['source_sha256'], projection['source_locator'])
    unit = ProjectedUnit(target, tuple(reference(x) for x in projection['western_references']),
        tuple(reference(x) for x in projection['canonical_references']), projection['precision'], projection['status'],
        {k: tuple(v) for k, v in mapping.items()})
    extraction = Extraction(tuple(expression(x) for x in raw['extraction']['expressions']),
        raw['extraction']['status'], tuple(raw['extraction']['limitations']))
    components = []
    for item in raw['components']:
        reading, footnote = item['reading'], item['footnote']
        semantic = reading['semantic']
        components.append(ComponentResult(reference(item['western_reference']), item['ol_reference'],
            tuple(item['owned_target_expression_ids']), tuple(expression(x) for x in item['source_expressions']),
            ReadingDecision(reading['selected'], SemanticDecision(semantic['outcome'], tuple(semantic['evidence_ids']),
                tuple(semantic['reason_codes'])), reading['footnote_action'], reading['registry_id'],
                tuple(reading['source_ids']), reading['source_validation_outcome']),
            FootnoteDecision(footnote['action'], footnote['status'], footnote['outcome'],
                tuple(tuple(x) for x in footnote['evidence_spans']), tuple(footnote['evidence_note_ids'])),
            item['final_outcome'], tuple(item['limitations'])))
    return GroupResult(unit, extraction, tuple(raw['reference_rows']), tuple(components), raw['alignment_status'],
        raw['expression_ownership'], tuple(raw['unmatched_target_ids']), tuple(raw['unresolved_target_ids']),
        tuple(raw['style_findings']), tuple(raw['limitations']),
        {key: Extraction(tuple(expression(item) for item in value['expressions']), value['status'], tuple(value['limitations']))
         for key, value in raw['note_extractions'].items()} if 'note_extractions' in raw else None)


def _component_document(group: Mapping[str, object], component: Mapping[str, object]) -> dict[str, object]:
    """Select one original serialized row without normalizing numeric or decision fields."""
    row = next(row for row in group['reference_rows'] if row['western_reference'] == component['western_reference'])
    projection = {k: v for k, v in group['projection'].items() if k not in {'target_western_mapping', 'target_note_metadata'}}
    projection.update(western_references=[row['western_reference']],
        ol_references=[row['ol_reference']] if row['status'] != 'UNINDEXED' else [],
        reference_index=[{k: v for k, v in row.items() if k not in {'context', 'provenance'}}])
    if row['status'] == 'REGISTERED_ABSENCE':
        projection['status'] = 'REGISTERED_ABSENCE'
    return {'unit_id': group['unit_id'], 'projection': projection,
        'extraction': dict(group['extraction'], expressions=[x for x in group['extraction']['expressions']
            if x['expression_id'] in component['owned_target_expression_ids']]),
        'source_evidence': {'expressions': component['source_expressions'], 'context': row['context']},
        **{key: component[key] for key in ('reading', 'footnote', 'final_outcome', 'limitations')}, 'style_findings': []}


def _validate_component_document(raw: Mapping[str, object], *, allowed: set[str], checks: Mapping[str, bool]) -> None:
    """Validate original v2 source fields before applying unchanged v1 decision-field rules."""
    from .results import _validate_expression, _validate_unit
    source = raw['source_evidence']
    unresolved = raw['reading']['semantic']['outcome'] in {'INSUFFICIENT_EVIDENCE', 'REFERENCE_NOT_INDEXED', 'NOT_ASSESSED'}
    if unresolved:
        for expression in source['expressions']:
            _validate_expression(expression, role_required=False, target_text=source['context']['ol_text'], expected_stream='ol')
        # GroupResult checks the original full sequence. Only the legacy decision validator
        # sees a subset with resolved roles; every original partial field stays in the v2 document.
        raw = dict(raw, source_evidence=dict(source, expressions=[x for x in source['expressions'] if x['role'] and x['role_spans']]))
    _validate_unit(raw, allowed, checks)


def _validate_component_view(view: UnitResult, *, allowed: set[str], checks: Mapping[str, bool]) -> None:
    """Apply the same component-field checks to an already validated typed row view."""
    _validate_component_document(_unit_document(view), allowed=allowed, checks=checks)


def _validate_group_findings(findings, groups, *, allowed, checks):
    """Match each finding to its exact owning row or parent presentation assessment."""
    from .results import _validate_findings
    remaining = list(findings)
    for group in groups:
        parent = comparison_view(group, checks=checks)
        local_checks = dict(checks, number_accuracy=False, footnote_review=False) if group.projected.precision == 'STYLE_STREAM' else checks
        views = [(view, dict(local_checks, presentation_consistency=False)) for view in component_views(group)]
        parent_checks = dict(local_checks, number_accuracy=local_checks['number_accuracy'] and bool(group.unmatched_target_ids or group.unresolved_target_ids),
            footnote_review=False) if group.components else local_checks
        views.append((parent, parent_checks))
        for view, selected_checks in views:
            western = [ref.label() for ref in view.projected.western_references]
            selected = [row for row in remaining if row.get('work_unit_id') == view.projected.target.unit_id
                and row.get('western_references') == western and ((row.get('category') == 'STYLE' and selected_checks['presentation_consistency'])
                    or (row.get('category') == 'FOOTNOTE' and selected_checks['footnote_review'])
                    or (row.get('category') in {'ACCURACY', 'EVIDENCE'} and selected_checks['number_accuracy']))]
            _validate_findings(selected, allowed, units=[_unit_document(view)], checks=selected_checks)
            for item in selected:
                remaining.remove(item)
    _require(not remaining, 'Finding lacks attributed decision', 'NCA_RESULT_FINDING_INVALID')
    _require(len({row['finding_id'] for row in findings}) == len(findings), 'Duplicate finding IDs')
    return findings


def _validate_numbers_result_v2(document: Mapping[str, object], *, expected_unit_ids: tuple[str, ...],
                               allowed_evidence_ids: tuple[str, ...]) -> dict[str, object]:
    """Strictly validate parent evidence, component attribution, coverage, and physical metrics."""
    from .results import (_require_keys, _validate_provenance, _validate_unit,
                          _validate_coverage, _RECEIPT_FIELDS, _validate_hash)
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
    # Validate original fields before typed normalization, findings, parent coverage, or counters.
    for group in groups:
        for component in group['components']:
            _validate_component_document(_component_document(group, component), allowed=set(allowed_evidence_ids), checks=checks)
    typed = tuple(_typed_group(g) for g in groups)
    for group in typed:
        for row in group.reference_rows:
            provenance = row['provenance']
            _require(isinstance(provenance, Mapping) and set(provenance) == {'ol_source_ids', 'guidance_source_ids', 'unit_source_ids'},
                'Invalid retained row provenance')
            _require(all(isinstance(ids, tuple) and len(ids) == len(set(ids)) and all(isinstance(x, str) and x in allowed_evidence_ids for x in ids)
                for ids in provenance.values()), 'Row provenance exceeds allowed source IDs')
    findings = _validate_group_findings(document['findings'], typed, allowed=set(allowed_evidence_ids), checks=checks)
    complete = all((g.extraction.status == 'COMPLETE' or 'PRESENTATION_CHECK_DISABLED' in g.limitations)
        and g.alignment_status not in {'PARTIAL', 'UNAVAILABLE'}
        and all(c.reading.semantic.outcome not in {'INSUFFICIENT_EVIDENCE', 'REFERENCE_NOT_INDEXED'}
            and c.footnote.outcome != 'INSUFFICIENT_EVIDENCE' for c in g.components) for g in typed)
    _validate_coverage(document['coverage'], expected_unit_ids, [u['unit_id'] for u in units],
                       findings_count=len(findings), required_evidence_complete=complete)
    _require(all(type(x) is int for x in document['summary'].values()) and document['summary'] ==
        group_summary(typed, checks=checks, findings_count=len(findings)),
        'Summary differs from grouped evidence', 'NCA_RESULT_SUMMARY_INVALID')
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
        # A wholly unindexed unit is never planned for extraction (build_inventory's
        # indexed-only filter), so its incomplete/absent extraction is the deliberate
        # no-data-scan outcome, not a coverage gap -- only an at-least-partially indexed
        # unit can become a candidate.
        if (g['projection']['precision'] != 'STYLE_STREAM'
                and any(r['status'] != 'UNINDEXED' for r in g['reference_rows'])):
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
    # Missing initial counts remain readable in historical v2 evidence. New
    # publication compares this entire ledger with the freshly computed plan.
    fields = {'input_ids', 'blocked', 'missing_owner_ids'}
    _require(set(planning) in (fields, fields | {'planned_extraction_calls'}), 'Invalid planning fields')
    for name in ('input_ids', 'missing_owner_ids'):
        _require(isinstance(planning[name], list) and all(isinstance(x, str) and x for x in planning[name])
            and len(set(planning[name])) == len(planning[name]), 'Invalid planning identities')
    planned = set(planning['input_ids'])
    if 'planned_extraction_calls' in planning:
        count = planning['planned_extraction_calls']
        _require(type(count) is int and 0 <= count <= len(planned), 'Invalid initial extraction call count')
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
    phase_owners = {phase: {owner for checkpoint in checkpoints if checkpoint['key']['phase'] == phase
        for owner in checkpoint['key']['input_ids']} for phase in phases}
    for group in typed:
        owner = group.projected.target.unit_id
        if len(group.reference_rows) > 1 and group.components:
            _require(owner in phase_owners['GROUP_CORRESPONDENCE'], 'Attributed bridge needs its group correspondence receipt')
        elif any(component.reading.selected in {'OL', 'ALT'} or component.reading.semantic.outcome in
            {'REVIEW_NUMBER_MISSING', 'REVIEW_NUMBER_ADDED', 'REVIEW_VALUE_DIFFERENCE'} for component in group.components):
            _require(owner in phase_owners['CORRESPONDENCE'], 'Semantic adjudication needs its correspondence receipt')
        if any(component.footnote.status in {'ADEQUATE', 'INADEQUATE'} for component in group.components):
            _require(owner in phase_owners['FOOTNOTE'], 'Footnote assessment needs its owning receipt')
    return _plain(document)


def validate_numbers_result_v2(document: Mapping[str, object], *, expected_unit_ids: tuple[str, ...],
                               allowed_evidence_ids: tuple[str, ...]) -> dict[str, object]:
    """Normalize malformed public JSON failures into the version-specific validation boundary."""
    from sage.errors import ValidationError
    try:
        return _validate_numbers_result_v2(document, expected_unit_ids=expected_unit_ids, allowed_evidence_ids=allowed_evidence_ids)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationError('Malformed v2 result evidence', code='NCA_RESULT_SCHEMA_INVALID') from exc
