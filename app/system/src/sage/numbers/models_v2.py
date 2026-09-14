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
        _require(isinstance(self.components, tuple) and all(isinstance(x, ComponentResult) for x in self.components), 'Invalid components')
        for name in ('unmatched_target_ids', 'unresolved_target_ids', 'limitations'):
            _require(_strings(getattr(self, name)), 'Invalid group identifiers')
        refs = [ref.label() for ref in self.projected.western_references]
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
