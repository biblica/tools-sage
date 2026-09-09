"""Resolve target-local NCA coverage using the immutable package's Western mapping."""
from dataclasses import replace
from pathlib import Path
import re

from sage.errors import ValidationError
from sage.references import ScriptureScope
from sage.vrs import VerseRef, VersificationSchema, parse_vrs_file

from .models import ProjectedUnit, ReferenceBundle, TargetUnit
from .projection import _BOUNDARIES, _same_schema, project_units


def _coordinates(schema: VersificationSchema, book: str) -> tuple[VerseRef, ...]:
    """Enumerate valid local coordinates independently of whether target text exists."""
    return tuple(VerseRef(book, chapter, verse)
        for chapter, limit in sorted(schema.chapter_max.get(book, {}).items())
        for verse in range(0 if book == 'PSA' else 1, limit + 1)
        if VerseRef(book, chapter, verse) not in schema.exclusions)


def _without_identity_rules(schema: VersificationSchema) -> VersificationSchema:
    """Canonicalize redundant identity rules without changing effective mapping meaning."""
    return replace(schema, mappings=[rule for rule in schema.mappings if rule.continuation or rule.local.refs() != rule.canonical.refs()])


def _continuation_coordinates(schema: VersificationSchema, book: str) -> set[VerseRef]:
    """Retain continuation flags while ignoring source labels and equivalent range spelling."""
    return {ref for rule in schema.mappings if rule.continuation
            for ref in rule.local.refs() if ref.book == book}


def _validate_scope(scope: ScriptureScope, schema: VersificationSchema) -> None:
    """Reject invalid endpoints instead of silently narrowing an operator's requested coverage."""
    chapters = schema.chapter_max.get(scope.book, {})
    valid = bool(chapters)
    if scope.start_chapter is not None:
        end_chapter = scope.end_chapter or scope.start_chapter
        valid = valid and all(chapter in chapters for chapter in range(scope.start_chapter, end_chapter + 1))
        if scope.start_verse is not None:
            minimum = 0 if scope.book == 'PSA' else 1
            valid = valid and minimum <= scope.start_verse <= chapters.get(scope.start_chapter, -1)
            valid = valid and minimum <= (scope.end_verse or scope.start_verse) <= chapters.get(end_chapter, -1)
    if not valid:
        raise ValidationError('The NCA scope is outside the effective WIP versification.',
            code='NCA_SCOPE_OUTSIDE_VRS', next_action='Choose a scope within the WIP Project\'s recorded verse boundaries.')


def project_scope(
    units: tuple[TargetUnit, ...], *, scope: ScriptureScope,
    target_schema: VersificationSchema, western_schema: VersificationSchema,
    bundle: ReferenceBundle, mapping_path: Path,
) -> tuple[tuple[ProjectedUnit, ...], tuple[VerseRef, ...]]:
    """Select expected Western rows from target-local scope and retain complete boundary groups.

    The caller supplies sealed book streams, including nearby material needed by
    registered equivalence groups. Unrelated streams remain outside coverage.
    """
    bundle.require_qualified()
    _validate_scope(scope, target_schema)
    package = parse_vrs_file(mapping_path, schema_id='nca-western', canonical_id=western_schema.canonical_id)
    continuation_difference = _continuation_coordinates(package, scope.book) ^ _continuation_coordinates(western_schema, scope.book)
    disagreement = tuple(ref.label() for ref in _coordinates(western_schema, scope.book)
        if ref in continuation_difference or package.local_to_canonical(ref) != western_schema.local_to_canonical(ref))
    if disagreement:
        raise ValidationError('The NCA package mapping disagrees with the configured Western baseline.',
            code='NCA_MAPPING_BASELINE_MISMATCH',
            details={'western_references': list(disagreement)},
            next_action='Resolve the configured ENG-to-ORG mapping discrepancy before creating this NCA task.')
    western = _without_identity_rules(replace(western_schema, mappings=package.mappings,
        source_files=western_schema.source_files + package.source_files))
    target = _without_identity_rules(target_schema)
    direct = _same_schema(target, western)
    selected_local = tuple(ref for ref in _coordinates(target, scope.book) if scope.contains(ref))
    selected_canonical = set(target.canonical_set(selected_local))

    def canonical_group(ref: VerseRef) -> set[VerseRef]:
        """Include the stored numeric-source portion of the two documented boundaries."""
        group = set(western.local_to_canonical(ref))
        row = bundle.lookup(ref)
        if ref in _BOUNDARIES and row is not None:
            match = re.fullmatch(r'([1-3]?[A-Z]{2,3}) ([0-9]+):([0-9]+)', row.ol_reference or '')
            if match:
                group.add(VerseRef(match[1], int(match[2]), int(match[3])))
        return group

    expected = []
    required_canonical = set(selected_canonical)
    for ref in _coordinates(western, scope.book):
        row = bundle.lookup(ref)
        if row is not None and row.ol_reference is None:
            if direct:
                selected = scope.contains(ref)
            else:
                # A registered absence has no canonical coordinate. A scope that
                # includes both neighbors can assess the omission without inventing one.
                neighbors = (VerseRef(ref.book, ref.chapter, ref.verse - 1), VerseRef(ref.book, ref.chapter, ref.verse + 1))
                selected = all(canonical_group(neighbor) & selected_canonical for neighbor in neighbors)
        else:
            selected = scope.contains(ref) if direct else bool(canonical_group(ref) & selected_canonical)
        if selected:
            expected.append(ref)
            if row is None or row.ol_reference is not None:
                required_canonical.update(canonical_group(ref))
    selected_units = tuple(unit for unit in units if any(scope.contains(ref) for ref in unit.target_references)
        or (not direct and bool(set(target.canonical_set(unit.target_references)) & required_canonical)))
    projected = project_units(selected_units, target_schema=target, western_schema=western,
        bundle=bundle, expected_western_references=tuple(expected))
    return projected, tuple(expected)
