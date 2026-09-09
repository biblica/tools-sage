"""Western NCA lookup through existing VRS, with explicit coverage gaps."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import re
from typing import Optional

from sage.errors import ValidationError
from sage.vrs import VerseRef, VersificationSchema

from .models import ProjectedUnit, ReferenceBundle, TargetUnit

_BOUNDARIES = frozenset({VerseRef("1SA", 20, 42), VerseRef("1CH", 12, 4)})


def _valid(ref: VerseRef, schema: VersificationSchema) -> bool:
    """Require a real local coordinate; Psalm titles may use verse zero."""
    limit = schema.chapter_limit(ref.book, ref.chapter)
    return (limit is not None and (0 if ref.book == "PSA" else 1) <= ref.verse <= limit
            and ref not in schema.exclusions)


def _same_schema(left: VersificationSchema, right: VersificationSchema) -> bool:
    """Compare effective mapping semantics, not filenames or mutable identities."""
    def rules(schema: VersificationSchema) -> set[tuple[object, ...]]:
        """Ignore source-file labels when comparing effective VRS rules."""
        return {(m.local, m.canonical, m.continuation) for m in schema.mappings}

    return (left.canonical_id == right.canonical_id and left.chapter_max == right.chapter_max
            and left.exclusions == right.exclusions and left.verse_segments == right.verse_segments
            and rules(left) == rules(right))


def _combined(units: tuple[TargetUnit, ...]) -> TargetUnit:
    """Create one named comparison stream while preserving component offsets."""
    if len(units) == 1:
        return units[0]
    ordered = tuple(sorted(units, key=lambda unit: unit.target_references))
    if len({unit.source_sha256 for unit in ordered}) != 1:
        raise ValidationError("NCA cannot combine target units from different source files.",
                              code="NCA_PROJECTION_SOURCE_CONFLICT")
    identity = sha256("\n".join(unit.unit_id for unit in ordered).encode()).hexdigest()
    locator: dict[str, int] = {}
    offset = 0
    for index, unit in enumerate(ordered):
        locator[f"component_{index}_start"] = offset
        locator[f"component_{index}_end"] = offset + len(unit.main_text)
        for key, value in unit.source_locator.items():
            locator[f"component_{index}_{key}"] = value
        offset += len(unit.main_text) + 1
    return TargetUnit(f"group:{identity}",
                      tuple(sorted({ref for unit in ordered for ref in unit.target_references})),
                      "\n".join(unit.main_text for unit in ordered),
                      tuple(note for unit in ordered for note in unit.notes),
                      ordered[0].source_sha256, locator)


def project_units(
    units: tuple[TargetUnit, ...], *, target_schema: VersificationSchema,
    western_schema: VersificationSchema, bundle: Optional[ReferenceBundle] = None,
    expected_western_references: tuple[VerseRef, ...] = (),
) -> tuple[ProjectedUnit, ...]:
    """Group WIP evidence once and reconcile explicitly expected Western scope.

    ``bundle`` adds the documented numeric-source boundary groups and registered
    source absences. Expected scope must be supplied by the caller; missing WIP
    text cannot define its own complete coverage.
    """
    if target_schema.canonical_id != western_schema.canonical_id:
        raise ValidationError("NCA projection schemas use different canonical identities.",
                              code="NCA_PROJECTION_CANONICAL_MISMATCH")
    if len({unit.unit_id for unit in units}) != len(units):
        raise ValidationError("NCA target unit IDs must be unique.", code="NCA_PROJECTION_DUPLICATE_UNIT")
    direct = _same_schema(target_schema, western_schema)
    if bundle is not None:
        bundle.require_qualified()
    rows = bundle.rows if bundle is not None else {}
    absences = {ref for ref, row in rows.items() if row.ol_reference is None}
    boundary: dict[VerseRef, set[VerseRef]] = {}
    for ref in _BOUNDARIES.intersection(rows):
        raw = rows[ref].ol_reference
        match = re.fullmatch(r"([1-3]?[A-Z]{2,3}) ([0-9]+):([0-9]+)", raw or "")
        if match:
            source = VerseRef(match[1], int(match[2]), int(match[3]))
            boundary[ref] = set(western_schema.local_to_canonical(ref)) | {source}

    def canonical_for(ref: VerseRef) -> set[VerseRef]:
        """Preserve registered absence instead of VRS identity fallback."""
        if ref in absences:
            return set()
        return boundary.get(ref, set(western_schema.local_to_canonical(ref)))

    def western_for(ref: VerseRef) -> set[VerseRef]:
        """Validate reverse candidates by their forward correspondence."""
        candidates = set(western_schema.canonical_to_local(ref))
        candidates.update(key for key, values in boundary.items() if ref in values)
        return {key for key in candidates
                if _valid(key, western_schema) and key not in absences and ref in canonical_for(key)}

    local_refs = [ref for unit in units for ref in unit.target_references]
    if len(set(local_refs)) != len(local_refs):
        raise ValidationError("NCA target units overlap before projection.", code="NCA_PROJECTION_DUPLICATE_REFERENCE")
    western_sets: list[set[VerseRef]] = []
    canonical_sets: list[set[VerseRef]] = []
    invalid: set[int] = set()
    for index, unit in enumerate(units):
        if not unit.target_references or any(not _valid(ref, target_schema) for ref in unit.target_references):
            invalid.add(index)
            western_sets.append(set())
            canonical_sets.append(set())
            continue
        if direct:
            western = set(unit.target_references)
            canonical = set().union(*(canonical_for(ref) for ref in western))
        else:
            canonical = set(target_schema.canonical_set(unit.target_references))
            western = set().union(*(western_for(ref) for ref in canonical))
        western_sets.append(western)
        canonical_sets.append(canonical)

    # Connected components avoid duplicating target expressions across a bridge.
    parents = list(range(len(units)))

    def find(index: int) -> int:
        """Resolve and compress a comparison-component parent."""
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    owners: dict[VerseRef, int] = {}
    for index, refs in enumerate(western_sets):
        for ref in refs:
            if ref in owners:
                parents[find(index)] = find(owners[ref])
            else:
                owners[ref] = index
    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(units)):
        groups[find(index)].append(index)
    results: list[ProjectedUnit] = []
    covered: set[VerseRef] = set()
    for indexes in groups.values():
        target = _combined(tuple(units[index] for index in indexes))
        western = set().union(*(western_sets[index] for index in indexes))
        canonical = set().union(*(canonical_sets[index] for index in indexes))
        required = set().union(*(canonical_for(ref) for ref in western)) if western else set()
        precision = "COORDINATE"
        if (len(target.target_references) > 1 or len(western) > 1 or len(canonical) > 1
                or target_schema.mapping_precision(target.target_references) != "COORDINATE"):
            precision = "EQUIVALENCE_GROUP"
        if not western or any(index in invalid for index in indexes):
            status = "UNMAPPED"
        elif western <= absences:
            status = "REGISTERED_ABSENCE"
        elif not direct and (_BOUNDARIES.intersection(western) - boundary.keys()):
            status = "AMBIGUOUS"
        elif not direct and (required != canonical):
            status = "AMBIGUOUS"
        else:
            status = "READY"
        results.append(ProjectedUnit(target, tuple(sorted(western)), tuple(sorted(canonical)), precision, status))
        covered.update(western)
    for ref in sorted(set(expected_western_references) - covered):
        # An adjacent note only transfers if its explicit anchor is this Western
        # coordinate in a Western WIP. Non-Western source omission has no local
        # identity to invent.
        notes = tuple(note for unit in units for note in unit.notes
                      if direct and note.anchor_references == (ref,))
        target = TargetUnit(f"missing:{ref.label()}", (), "", notes,
                            units[0].source_sha256 if units else "0" * 64, {})
        results.append(ProjectedUnit(target, (ref,), tuple(sorted(canonical_for(ref))),
                                     "COORDINATE", "REGISTERED_ABSENCE" if ref in absences else "UNMAPPED"))
    return tuple(results)
