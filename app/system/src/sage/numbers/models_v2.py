"""Immutable parent groups and independently owned Western component evidence."""
from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Mapping

from sage.errors import ValidationError
from sage.vrs import VerseRef
from .models import (Extraction, FootnoteDecision, NumericExpression, ProjectedUnit,
                     ReadingDecision, SEMANTIC_OUTCOMES, freeze)


def _require(condition: bool, message: str) -> None:
    """Reject malformed typed ownership before serialization can obscure its origin."""
    if not condition:
        raise ValidationError(message, code='NCA_MODEL_INVALID')


def _strings(value: object) -> bool:
    """Recognize an immutable unique collection of nonempty evidence identifiers."""
    return isinstance(value, tuple) and all(isinstance(x, str) and x for x in value) and len(set(value)) == len(value)


@dataclass(frozen=True)
class ComponentResult:
    """One Western row's decisions, referring to expressions held by its parent."""
    western_reference: VerseRef
    ol_reference: str | None
    owned_target_expression_ids: tuple[str, ...]
    source_expressions: tuple[NumericExpression, ...]
    reading: ReadingDecision
    footnote: FootnoteDecision
    final_outcome: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require exact references, immutable evidence, and closed decision vocabularies."""
        _require(isinstance(self.western_reference, VerseRef), 'Invalid component Western reference')
        _require(self.ol_reference is None or isinstance(self.ol_reference, str) and re.fullmatch(r'[1-3]?[A-Z]{2,3} [0-9]+:[0-9]+', self.ol_reference) is not None, 'Invalid stored OL reference')
        _require(_strings(self.owned_target_expression_ids) and _strings(self.limitations), 'Invalid component identifiers')
        _require(isinstance(self.source_expressions, tuple) and all(isinstance(x, NumericExpression) for x in self.source_expressions), 'Invalid source expressions')
        _require(isinstance(self.reading, ReadingDecision) and isinstance(self.footnote, FootnoteDecision)
                 and self.final_outcome in SEMANTIC_OUTCOMES, 'Invalid component decisions')


@dataclass(frozen=True)
class GroupResult:
    """The single extracted parent and complete, disjoint component attribution ledger."""
    projected: ProjectedUnit
    extraction: Extraction
    reference_rows: tuple[Mapping[str, object], ...]
    components: tuple[ComponentResult, ...]
    alignment_status: str
    expression_ownership: Mapping[str, str]
    unmatched_target_ids: tuple[str, ...]
    unresolved_target_ids: tuple[str, ...]
    style_findings: tuple[Mapping[str, object], ...]
    limitations: tuple[str, ...]
    note_extractions: Mapping[str, Extraction] | None = None

    def __post_init__(self) -> None:
        """Freeze nested evidence and reject duplicate, missing, or foreign attribution."""
        _require(isinstance(self.projected, ProjectedUnit) and isinstance(self.extraction, Extraction), 'Invalid group evidence')
        _require(self.alignment_status in {'COMPLETE', 'PARTIAL', 'UNAVAILABLE', 'NOT_ASSESSED'}, 'Invalid alignment status')
        for name in ('reference_rows', 'style_findings'):
            value = getattr(self, name)
            _require(isinstance(value, tuple) and all(isinstance(x, Mapping) for x in value), 'Invalid group mappings')
            object.__setattr__(self, name, freeze(value))
        _require(isinstance(self.expression_ownership, Mapping), 'Invalid ownership mapping')
        object.__setattr__(self, 'expression_ownership', freeze(self.expression_ownership))
        if self.note_extractions is not None:
            _require(isinstance(self.note_extractions, Mapping)
                and set(self.note_extractions) <= {note.note_id for note in self.projected.target.notes}
                and all(isinstance(value, Extraction) for value in self.note_extractions.values()), 'Invalid note extractions')
            object.__setattr__(self, 'note_extractions', freeze(self.note_extractions))
        _require(isinstance(self.components, tuple) and all(isinstance(x, ComponentResult) for x in self.components), 'Invalid components')
        for name in ('unmatched_target_ids', 'unresolved_target_ids', 'limitations'):
            _require(_strings(getattr(self, name)), 'Invalid group identifiers')
        refs = [ref.label() for ref in self.projected.western_references]
        _require(len(refs) == len(set(refs)), 'Duplicate Western ledger coordinates')
        _require(all(set(row) == {'western_reference', 'ol_reference', 'status', 'context', 'provenance'} for row in self.reference_rows), 'Invalid reference row fields')
        _require([row.get('western_reference') for row in self.reference_rows] == refs, 'Incomplete reference rows')
        component_refs = [x.western_reference.label() for x in self.components]
        _require(len(set(component_refs)) == len(component_refs) and set(component_refs) <= set(refs), 'Duplicate or foreign components')
        rows = {row['western_reference']: row for row in self.reference_rows}
        _require(all(rows[x.western_reference.label()]['ol_reference'] == x.ol_reference for x in self.components), 'Component OL reference differs')
        ids = [x.expression_id for x in self.extraction.expressions]
        _require(all(isinstance(x, str) and x for x in ids) and len(set(ids)) == len(ids), 'Invalid parent expression IDs')
        owned = {eid: c.western_reference.label() for c in self.components for eid in c.owned_target_expression_ids}
        count = sum(len(c.owned_target_expression_ids) for c in self.components)
        _require(count == len(owned) and dict(self.expression_ownership) == owned, 'Contradictory expression ownership')
        ledger = list(owned) + list(self.unmatched_target_ids) + list(self.unresolved_target_ids)
        _require(len(ledger) == len(set(ledger)) and set(ledger) == set(ids), 'Incomplete or overlapping attribution')
        _require(self.alignment_status != 'UNAVAILABLE' or not self.components and bool(self.limitations), 'Unresolved alignment needs explicit limits')
        _require(self.alignment_status != 'COMPLETE' or component_refs == refs and not self.unresolved_target_ids, 'Resolved alignment must cover every row')
        _require(self.alignment_status != 'NOT_ASSESSED' or not self.components and not self.expression_ownership
            and not self.unresolved_target_ids, 'Unassessed alignment cannot claim numeric ownership')
        _require(self.alignment_status != 'PARTIAL' or component_refs == refs and bool(self.limitations), 'Partial alignment needs rows and limits')
        if len(refs) > 1 and self.alignment_status == 'COMPLETE':
            _require(self.extraction.status == 'COMPLETE' and all(row['status'] != 'UNINDEXED' for row in self.reference_rows),
                'Complete alignment lacks complete extraction or authority')
        _validate_group_evidence(self)


def _note_content_covers(note, span: tuple[int, int]) -> bool:
    """Allow one disclosure span across adjacent original content fields without admitting gaps."""
    cursor = span[0]
    parts = sorted((part['start'], part['end']) for part in note.content_spans if part.get('kind') == 'CONTENT')
    for start, end in parts:
        if start > cursor:
            break
        cursor = max(cursor, end)
        if cursor >= span[1]:
            return True
    return False


def _validate_group_evidence(group: GroupResult) -> None:
    """Bind typed evidence to exact streams and prevent cross-row policy or note authority."""
    from .results import _expression_document, _validate_expression, _is_ordered_subsequence, _validate_fraction
    from fractions import Fraction
    from .groups import attributed_notes
    rows = {row['western_reference']: row for row in group.reference_rows}
    for row in group.reference_rows:
        provenance = row['provenance']
        _require(isinstance(provenance, Mapping) and set(provenance) == {'ol_source_ids', 'guidance_source_ids', 'unit_source_ids'}
            and all(_strings(value) for value in provenance.values()), 'Invalid row source provenance')
        _require(row['status'] in {'INDEXED', 'REGISTERED_ABSENCE', 'UNINDEXED'}, 'Invalid row status')
        _require((row['status'] == 'INDEXED') == (row['ol_reference'] is not None), 'Row source nullability differs from ledger state')
        _require(row['status'] != 'UNINDEXED' or not any(provenance.values()) and not row['context'], 'Unindexed row has invented authority')
        if row['status'] != 'UNINDEXED':
            context = row['context']
            _require(isinstance(context, Mapping) and set(context) == {'language', 'ol_text', 'ol_values', 'variant_class', 'scholarship_status'}
                and isinstance(context['language'], str) and isinstance(context['ol_text'], str)
                and isinstance(context['ol_values'], tuple) and all(context[name] is None or isinstance(context[name], str)
                    and bool(context[name]) for name in ('variant_class', 'scholarship_status')), 'Invalid original row source context')
            for value in context['ol_values']:
                _validate_fraction(str(value) if isinstance(value, Fraction) else value)
    resolved_rows = {component.western_reference for component in group.components
        if (len(group.reference_rows) > 1 and group.alignment_status == 'COMPLETE')
        or component.reading.semantic.outcome not in {'INSUFFICIENT_EVIDENCE', 'REFERENCE_NOT_INDEXED', 'NOT_ASSESSED'}}
    required_target_ids = {eid for component in group.components if component.western_reference in resolved_rows
        for eid in component.owned_target_expression_ids}
    note_pairs = set()
    target_spans = []
    for expression in group.extraction.expressions:
        _eid, span = _validate_expression(_expression_document(expression),
            role_required=expression.expression_id in required_target_ids,
            target_text=group.projected.target.main_text, expected_stream='main')
        _require(not any(a < span[1] and span[0] < b for a, b in target_spans), 'Overlapping target evidence')
        target_spans.append(span)
    for component in group.components:
        row = rows[component.western_reference.label()]
        _require(row['status'] in {'INDEXED', 'REGISTERED_ABSENCE', 'UNINDEXED'}, 'Invalid row status')
        _require(component.reading.registry_id in {None, component.western_reference.label()}, 'Foreign row policy registry')
        provenance = row['provenance']
        _require(component.reading.registry_id is None or bool(provenance['guidance_source_ids']), 'Registered reading lacks row guidance provenance')
        selected = provenance['guidance_source_ids'] if component.reading.registry_id is not None else provenance['ol_source_ids']
        if component.reading.selected in {'OL', 'ALT'}:
            _require(component.reading.source_ids == selected, 'Reading source IDs differ from owning row policy')
        if component.reading.semantic.outcome == 'PASS_UNIT_CONVERSION':
            _require(bool(provenance['unit_source_ids']) and component.reading.semantic.evidence_ids == provenance['unit_source_ids'],
                'Unit source IDs differ from owning conversion policy')
        else:
            _require(set(component.reading.semantic.evidence_ids) <= set(selected), 'Semantic sources differ from owning row policy')
        if row['status'] == 'UNINDEXED':
            _require(not any(provenance.values()) and not row['context'] and not component.source_expressions
                and (len(group.reference_rows) == 1 or not component.owned_target_expression_ids) and component.reading.selected in {'UNSUPPORTED', 'UNASSESSED'},
                'Unindexed row cannot own authoritative evidence')
            continue
        context = row['context']
        _require(bool(context), 'Indexed component lacks exact source context')
        resolved = component.western_reference in resolved_rows
        source_ids, spans = set(), []
        for expression in component.source_expressions:
            eid, span = _validate_expression(_expression_document(expression), role_required=resolved,
                target_text=context['ol_text'], expected_stream='ol')
            _require(eid not in source_ids and not any(a < span[1] and span[0] < b for a, b in spans), 'Repeated source evidence')
            source_ids.add(eid)
            spans.append(span)
        values = [str(value) for expression in component.source_expressions for value in expression.values]
        _require(values == [str(value) for value in context['ol_values']] if resolved else _is_ordered_subsequence(values, [str(value) for value in context['ol_values']]),
            'Source sequence differs from owning authority')
        if len(group.reference_rows) > 1:
            eligible, _ambiguous = attributed_notes(group.projected, component.western_reference)
            notes = {note.note_id: note for note in eligible}
            for note_id, span in zip(component.footnote.evidence_note_ids, component.footnote.evidence_spans):
                _require(note_id in notes and notes[note_id].marker in {'f', 'fe', 'ef', 'efe'}
                    and span[1] <= len(notes[note_id].text)
                    and _note_content_covers(notes[note_id], span), 'Footnote evidence lacks unique row attribution')
                _require((note_id, span) not in note_pairs, 'Repeated note evidence ownership')
                note_pairs.add((note_id, span))


@dataclass(frozen=True)
class OptimizedRunResult:
    """Complete scope, component findings, and independently derived physical metrics."""
    groups: tuple[GroupResult, ...]
    findings: tuple[Mapping[str, object], ...]
    coverage: Mapping[str, object]
    summary: Mapping[str, object]
    metrics: Mapping[str, object]

    def __post_init__(self) -> None:
        """Own immutable nested evidence and reconcile every expected parent exactly once."""
        _require(isinstance(self.groups, tuple) and all(isinstance(x, GroupResult) for x in self.groups), 'Invalid result groups')
        _require(isinstance(self.findings, tuple) and all(isinstance(x, Mapping) for x in self.findings), 'Invalid findings')
        for name in ('coverage', 'summary', 'metrics'):
            _require(isinstance(getattr(self, name), Mapping), 'Invalid result mapping')
        for name in ('findings', 'coverage', 'summary', 'metrics'):
            object.__setattr__(self, name, freeze(getattr(self, name)))
        ids = tuple(x.projected.target.unit_id for x in self.groups)
        expected = tuple(self.coverage.get('expected_unit_ids', ()))
        _require(len(ids) == len(set(ids)) and len(expected) == len(set(expected)) and set(ids) == set(expected), 'Incomplete result coverage')
