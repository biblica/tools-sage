"""Validate one bridge adjudication and evaluate independently owned source rows."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from sage.errors import ValidationError
from .models import (Extraction, FootnoteDecision, ProjectedUnit, ReferenceBundle,
                     ReferenceRow, ReadingDecision, SemanticDecision, freeze)
from .models_v2 import ComponentResult
from .model_tasks import CorrespondenceEvidence, validate_correspondence_response


def _require(condition: bool, message: str) -> None:
    """Reject authority or ownership errors before any comparison policy executes."""
    if not condition:
        raise ValidationError(message, code='NCA_GROUP_EVIDENCE_INVALID')


def row_provenance(row: ReferenceRow | None, bundle: ReferenceBundle) -> Mapping[str, tuple[str, ...]]:
    """Retain original OL, registered guidance, and conversion sources as distinct authorities."""
    from .engine import _source_ids
    ref = row.western_reference if row is not None else None
    return {'ol_source_ids': _source_ids(row.metadata) if row is not None else (),
        'guidance_source_ids': _source_ids(bundle.footnote_guidance.get(ref, {})) if ref in bundle.variants else (),
        'unit_source_ids': _source_ids(bundle.units.get(ref, {}))}


@dataclass(frozen=True)
class ReferenceGroup:
    """One protected unit and its ordered immutable resolved or unindexed rows."""
    unit: ProjectedUnit
    rows: tuple[ReferenceRow | None, ...]
    registered_contexts: Mapping[str, Mapping[str, object]]

    def __post_init__(self) -> None:
        """Retain nullable source identity without inventing an empty authority row."""
        _require(isinstance(self.unit, ProjectedUnit) and isinstance(self.rows, tuple), 'Invalid reference group')
        _require(len(self.rows) == len(self.unit.western_references), 'Reference group row coverage differs')
        _require(all(row is None or isinstance(row, ReferenceRow) and row.western_reference == ref
            for ref, row in zip(self.unit.western_references, self.rows)), 'Reference group row identity differs')
        _require(isinstance(self.registered_contexts, Mapping) and set(self.registered_contexts) <=
            {row.western_reference.label() for row in self.rows if row is not None}, 'Foreign registered context')
        object.__setattr__(self, 'registered_contexts', freeze(self.registered_contexts))

    @classmethod
    def build(cls, unit: ProjectedUnit, *, bundle: ReferenceBundle) -> ReferenceGroup:
        """Collect qualified row authorities and bounded registered candidates once."""
        from .engine import _source_ids
        from .reference import parse_values
        from .units import parse_registered_quantity
        bundle.require_qualified()
        rows = tuple(bundle.lookup(ref) for ref in unit.western_references)
        contexts = {}
        for row in rows:
            if row is None:
                continue
            ref = row.western_reference
            variant, guidance, conversion = bundle.variants.get(ref), bundle.footnote_guidance.get(ref), bundle.units.get(ref)
            if variant and guidance:
                values = parse_values(str(variant.get('NIV_VALUE_RESEARCHED', '')))
                if values and values == parse_values(str(guidance.get('ALT_NIV_VALUES', ''))) and _source_ids(guidance):
                    contexts[ref.label()] = {'registry_id': ref.label(), 'reading_id': 'ALT', 'source_ids': _source_ids(guidance),
                        'text': row.niv_text, 'values': [str(x) for x in values],
                        'policy_outcome': str(guidance.get('VALIDATION_IF_TARGET_FOLLOWS_ALT', ''))}
            elif conversion and _source_ids(conversion):
                try:
                    quantities = parse_registered_quantity(str(conversion['NIV_QUANTITY']))
                except (KeyError, ValidationError):
                    continue
                contexts[ref.label()] = {'registry_id': ref.label(), 'reading_id': 'UNIT', 'source_ids': _source_ids(conversion),
                    'text': str(conversion['NIV_QUANTITY']), 'values': [str(v) for x in quantities for v in x.values],
                    'policy_outcome': 'PASS_UNIT_CONVERSION'}
        return cls(unit, rows, contexts)


@dataclass(frozen=True)
class GroupCorrespondence:
    """Validated per-row typed correspondence and exhaustive parent ownership."""
    rows: Mapping[str, CorrespondenceEvidence]
    assignments: Mapping[str, tuple[str, ...]]
    unmatched_target_ids: tuple[str, ...]
    unresolved_target_ids: tuple[str, ...]
    status: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        """Freeze evidence and reject malformed direct construction and duplicate owners."""
        _require(isinstance(self.rows, Mapping) and all(isinstance(k, str) and isinstance(v, CorrespondenceEvidence)
            for k, v in self.rows.items()), 'Invalid row correspondence')
        _require(isinstance(self.assignments, Mapping) and all(isinstance(k, str) and isinstance(v, tuple)
            and all(isinstance(eid, str) and eid for eid in v) for k, v in self.assignments.items()), 'Invalid ownership')
        for name in ('unmatched_target_ids', 'unresolved_target_ids', 'limitations'):
            value = getattr(self, name)
            _require(isinstance(value, tuple) and all(isinstance(x, str) and x for x in value)
                and len(value) == len(set(value)), 'Invalid group identifiers')
        ledger = [eid for ids in self.assignments.values() for eid in ids] + list(self.unmatched_target_ids) + list(self.unresolved_target_ids)
        _require(len(ledger) == len(set(ledger)), 'Overlapping expression ownership')
        _require(self.status in {'COMPLETE', 'PARTIAL', 'UNAVAILABLE'} and
            (self.status == 'COMPLETE' or bool(self.limitations)), 'Invalid group alignment')
        _require(self.status != 'COMPLETE' or not self.unresolved_target_ids, 'Complete alignment retains unresolved ownership')
        object.__setattr__(self, 'rows', freeze(self.rows))
        object.__setattr__(self, 'assignments', freeze(self.assignments))


def validate_group_correspondence(group: ReferenceGroup, extraction: Extraction,
                                 response: Mapping[str, object]) -> GroupCorrespondence:
    """Bind row-keyed source streams and exact role evidence to one exhaustive allocation."""
    _require(isinstance(group, ReferenceGroup) and isinstance(extraction, Extraction), 'Invalid group inputs')
    _require(isinstance(response, Mapping) and set(response) == {'schema_version', 'phase', 'unit_id', 'status',
        'limitations', 'rows', 'assignments', 'unmatched_target_ids', 'unresolved_target_ids'}, 'Invalid group response fields')
    _require(response['schema_version'] == '2.0' and response['phase'] == 'GROUP_CORRESPONDENCE'
        and response['unit_id'] == group.unit.target.unit_id, 'Invalid group response identity')
    refs = [ref.label() for ref in group.unit.western_references]
    assignments = response['assignments']
    raw_rows = response['rows']
    _require(isinstance(assignments, Mapping) and set(assignments) == set(refs), 'Invalid row ownership keys')
    _require(isinstance(raw_rows, Mapping) and set(raw_rows) == {ref for ref, row in zip(refs, group.rows) if row is not None},
        'Invalid source row coverage')
    for ids in assignments.values():
        _require(isinstance(ids, list) and all(isinstance(x, str) and x for x in ids), 'Invalid ownership IDs')
    for name in ('unmatched_target_ids', 'unresolved_target_ids', 'limitations'):
        _require(isinstance(response[name], list) and all(isinstance(x, str) and x for x in response[name]), 'Invalid group identifiers')
    ledger = [eid for ids in assignments.values() for eid in ids] + response['unmatched_target_ids'] + response['unresolved_target_ids']
    ids = [x.expression_id for x in extraction.expressions]
    _require(len(ids) == len(set(ids)) and len(ledger) == len(set(ledger)) and set(ledger) == set(ids),
        'Incomplete or overlapping expression ownership')
    _require(response['status'] in {'COMPLETE', 'PARTIAL', 'UNAVAILABLE'}, 'Invalid group alignment')
    _require(response['status'] != 'COMPLETE' or extraction.status == 'COMPLETE' and not response['unresolved_target_ids']
        and all(row is not None for row in group.rows), 'Incomplete complete alignment')
    evidence = {}
    from .policy import _plain
    for ref, row in zip(refs, group.rows):
        if row is None:
            _require(not assignments[ref], 'Unindexed row cannot own target expressions')
            continue
        target = replace(extraction, expressions=tuple(x for x in extraction.expressions if x.expression_id in assignments[ref]))
        raw = raw_rows[ref]
        _require(isinstance(raw, Mapping), 'Invalid row evidence')
        wrapped = dict(raw, schema_version='2.0', phase='CORRESPONDENCE', unit_id=group.unit.target.unit_id)
        _require(not {'schema_version', 'phase', 'unit_id'} & set(raw), 'Row cannot override group identity')
        evidence[ref] = validate_correspondence_response(group.unit.target, target, row, wrapped,
            reading_context=_plain(group.registered_contexts[ref]) if ref in group.registered_contexts else None, schema_version='2.0')
        _require(response['status'] != 'COMPLETE' or evidence[ref].status == 'COMPLETE', 'Complete alignment has partial source evidence')
    return GroupCorrespondence(evidence, {ref: tuple(eids) for ref, eids in assignments.items()},
        tuple(response['unmatched_target_ids']), tuple(response['unresolved_target_ids']), response['status'], tuple(response['limitations']))


def _bind_correspondence(group: ReferenceGroup, extraction: Extraction, evidence: GroupCorrespondence) -> GroupCorrespondence:
    """Revalidate directly constructed typed evidence against immutable parent and row inputs."""
    from .model_tasks import _expression_payload
    _require(isinstance(evidence, GroupCorrespondence), 'Invalid typed group correspondence')
    expected = {row.western_reference.label(): row for row in group.rows if row is not None}
    _require(set(evidence.rows) == set(expected), 'Foreign or missing source row evidence')
    target = {item.expression_id: item for item in extraction.expressions}
    raw_rows = {}
    text = group.unit.target.main_text
    for label, item in evidence.rows.items():
        assigned = evidence.assignments.get(label, ())
        represented = [x.expression_id for x in item.target_extraction.expressions]
        expected_ids = [x.expression_id for x in extraction.expressions if x.expression_id in assigned]
        _require(represented == expected_ids if item.status == 'COMPLETE' else
            represented == [eid for eid in expected_ids if eid in represented], 'Row target ownership differs')
        for expression in item.target_extraction.expressions:
            original = target[expression.expression_id]
            _require(replace(expression, role=original.role, role_spans=original.role_spans) == original,
                'Row expression differs from protected target')
        raw_rows[label] = {'status': item.status, 'limitations': list(item.limitations),
            'source_expressions': [_expression_payload(x, expected[label].ol_text) for x in item.source_expressions],
            'target_roles': [{'expression_id': x.expression_id, 'role': x.role,
                'role_spans': [{'start': a, 'end': b, 'surface': text[a:b]} for a, b in x.role_spans]}
                for x in item.target_extraction.expressions]}
        if label in group.registered_contexts:
            raw_rows[label].update(registered_status=item.registered_status, registered_limitations=list(item.registered_limitations),
                registered_expressions=[_expression_payload(x, group.registered_contexts[label]['text']) for x in item.registered_expressions])
        else:
            _require(not item.registered_expressions and item.registered_status == 'NOT_APPLICABLE'
                and not item.registered_limitations, 'Foreign registered row evidence')
    validated = validate_group_correspondence(group, extraction, {'schema_version': '2.0', 'phase': 'GROUP_CORRESPONDENCE',
        'unit_id': group.unit.target.unit_id, 'status': evidence.status, 'limitations': list(evidence.limitations),
        'assignments': {ref: list(ids) for ref, ids in evidence.assignments.items()}, 'rows': raw_rows,
        'unmatched_target_ids': list(evidence.unmatched_target_ids), 'unresolved_target_ids': list(evidence.unresolved_target_ids)})
    _require(validated == evidence, 'Typed correspondence differs from normalized evidence')
    return validated


def evaluate_group(reference_group: ReferenceGroup, extraction: Extraction, correspondence: GroupCorrespondence,
                   *, bundle: ReferenceBundle, checks: Mapping[str, bool]) -> tuple[ComponentResult, ...]:
    """Apply existing typed policies only after each row owns its complete target subset."""
    from .engine import _unsupported_reading, _identify_reading_from_evidence
    bundle.require_qualified()
    _require(reference_group == ReferenceGroup.build(reference_group.unit, bundle=bundle),
        'Group authority differs from the qualified bundle')
    correspondence = _bind_correspondence(reference_group, extraction, correspondence)
    components = []
    for ref, row in zip(reference_group.unit.western_references, reference_group.rows):
        label = ref.label()
        _require(bundle.lookup(ref) == row, 'Group row differs from qualified bundle')
        evidence = correspondence.rows.get(label)
        limits = correspondence.limitations
        source = () if evidence is None else evidence.source_expressions
        if row is None:
            reading = ReadingDecision('UNSUPPORTED', SemanticDecision('REFERENCE_NOT_INDEXED',
                reason_codes=('WESTERN_REFERENCE_NOT_INDEXED',)), 'NONE', None, ())
            limits += ('WESTERN_REFERENCE_NOT_INDEXED',)
        elif evidence is None or evidence.status != 'COMPLETE':
            reading = _unsupported_reading('CORRESPONDENCE_INCOMPLETE')
            limits += ('CORRESPONDENCE_INCOMPLETE',)
        else:
            reading, row_limits, source = _identify_reading_from_evidence(row, evidence.target_extraction, evidence, bundle=bundle)
            limits += row_limits
        footnote = FootnoteDecision(reading.footnote_action if checks['footnote_review'] else 'NONE', 'NOT_ASSESSED',
            'INSUFFICIENT_EVIDENCE' if checks['footnote_review'] else 'NONE')
        if checks['footnote_review'] and reading.selected in {'OL', 'ALT'} and reading.footnote_action == 'NONE':
            footnote = FootnoteDecision('NONE', 'NOT_REQUIRED', 'NONE')
        components.append(ComponentResult(ref, row.ol_reference if row is not None else None,
            correspondence.assignments[label], source, reading, footnote,
            reading.semantic.outcome if checks['number_accuracy'] else 'NOT_ASSESSED', tuple(dict.fromkeys(limits))))
    return tuple(components)


def build_group_payload(group: ReferenceGroup, extraction: Extraction) -> Mapping[str, object]:
    """Expose exact row authorities with the protected target text and extraction once."""
    from .model_tasks import _expression_payload
    from .policy import _plain
    rows = []
    for ref, row in zip(group.unit.western_references, group.rows):
        rows.append({'western_reference': ref.label(), 'status': 'UNINDEXED' if row is None else
            'REGISTERED_ABSENCE' if row.ol_reference is None else 'INDEXED',
            'authority': None if row is None else {'ol_reference': row.ol_reference, 'language': row.language,
                'ol_text': row.ol_text, 'ol_values': [str(x) for x in row.ol_values]},
            'reading_context': _plain(group.registered_contexts.get(ref.label()))})
    return {'schema_version': '2.0', 'phase': 'GROUP_CORRESPONDENCE', 'unit_id': group.unit.target.unit_id,
        'target': {'text': group.unit.target.main_text, 'status': extraction.status, 'limitations': list(extraction.limitations),
            'expressions': [_expression_payload(x, group.unit.target.main_text) for x in extraction.expressions]},
        'rows': rows, 'output_schema_id': 'sage-nca-extraction-2.0#group-correspondence'}


def group_response_schema(group: ReferenceGroup) -> Mapping[str, object]:
    """Build a closed row-keyed response schema from this bounded authoritative ledger."""
    from copy import deepcopy
    from .model_tasks import _SCHEMAS
    labels = [ref.label() for ref in group.unit.western_references]
    strings = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}
    row_schemas = {}
    for label, row in zip(labels, group.rows):
        if row is None:
            continue
        schema = deepcopy(_SCHEMAS['CORRESPONDENCE'])
        for field in ('schema_version', 'phase', 'unit_id'):
            schema['properties'].pop(field, None)
        schema['properties'].pop('confidence', None)
        if label not in group.registered_contexts:
            for field in ('registered_status', 'registered_limitations', 'registered_expressions'):
                schema['properties'].pop(field, None)
        schema['required'] = list(schema['properties'])
        row_schemas[label] = schema
    properties = {'schema_version': {'const': '2.0'}, 'phase': {'const': 'GROUP_CORRESPONDENCE'},
        'unit_id': {'const': group.unit.target.unit_id}, 'status': {'enum': ['COMPLETE', 'PARTIAL', 'UNAVAILABLE']},
        'limitations': strings, 'unmatched_target_ids': strings, 'unresolved_target_ids': strings,
        'assignments': {'type': 'object', 'additionalProperties': False, 'required': labels,
                        'properties': {label: strings for label in labels}},
        'rows': {'type': 'object', 'additionalProperties': False, 'required': list(row_schemas), 'properties': row_schemas}}
    return {'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties}


def attributed_notes(unit: ProjectedUnit, reference) -> tuple[tuple, bool]:
    """Admit original notes only when every anchor maps uniquely to this row."""
    eligible, ambiguous = [], False
    for note in unit.target.notes:
        mapped = [unit.target_western_mapping.get(anchor.label()) for anchor in note.anchor_references]
        if mapped and all(rows == (reference.label(),) for rows in mapped):
            eligible.append(note)
        elif not mapped or any(not rows or reference.label() in rows for rows in mapped):
            ambiguous = True
    return tuple(eligible), ambiguous


def assess_group_notes(reference_group: ReferenceGroup, components: tuple[ComponentResult, ...], *,
                       bundle: ReferenceBundle, checks: Mapping[str, bool], language: str,
                       model_tasks: object) -> tuple[ComponentResult, ...]:
    """Run separately governed disclosure phases over exclusively attributed original notes."""
    from .footnotes import assess_footnote
    assessed = []
    for component in components:
        reading = component.reading
        decision = component.footnote
        if checks['footnote_review']:
            notes, ambiguous = attributed_notes(reference_group.unit, component.western_reference)
            target = replace(reference_group.unit.target, notes=notes)
            if reading.footnote_action != 'NONE' and ambiguous and not notes:
                decision = FootnoteDecision(reading.footnote_action, 'NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE')
            else:
                decision = assess_footnote(reading, notes, bundle=bundle, language=language,
                                          unit=target, model_tasks=model_tasks)
                if ambiguous and decision.status in {'MISSING', 'INADEQUATE'}:
                    decision = FootnoteDecision(reading.footnote_action, 'NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE')
        final = reading.semantic.outcome if checks['number_accuracy'] else 'NOT_ASSESSED'
        if checks['footnote_review'] and decision.outcome == 'REVIEW_MISSING_FOOTNOTE':
            final = 'REVIEW_MISSING_FOOTNOTE'
        elif checks['number_accuracy'] and reading.selected == 'ALT' and reading.semantic.outcome == 'REGISTERED_ALTERNATE' and decision.status == 'ADEQUATE':
            final = reading.source_validation_outcome
        assessed.append(replace(component, footnote=decision, final_outcome=final))
    return tuple(assessed)
