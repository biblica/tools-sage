"""Immutable typed records shared by the NCA domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from sage.errors import ValidationError
from sage.vrs import VerseRef


EXTRACTION_STATUSES = frozenset({"COMPLETE", "PARTIAL", "UNSUPPORTED"})
PROJECTION_STATUSES = frozenset({"READY", "AMBIGUOUS", "UNMAPPED", "REGISTERED_ABSENCE"})
QUALIFICATION_STATUSES = frozenset(
    {"QUALIFIED", "QUALIFIED_WITH_DIAGNOSTICS", "DIAGNOSTIC", "BLOCKED"}
)
COMPARISON_MODES = frozenset({"ORDERED", "UNORDERED"})
COMPARISON_OUTCOMES = frozenset({"PASS", "FAIL", "NEEDS_REVIEW", "NOT_ASSESSED"})


def _invalid(field_name: str, value: object) -> ValidationError:
    """Build a stable validation error for one malformed shared-model field."""
    return ValidationError(
        f"Invalid NCA {field_name}: {value!r}",
        code="NCA_MODEL_INVALID",
        details={"field": field_name, "value": repr(value)},
    )


def _enum(field_name: str, value: str, allowed: frozenset[str]) -> None:
    """Require one value to belong to its closed NCA vocabulary."""
    if value not in allowed:
        raise _invalid(field_name, value)


def _tuple(field_name: str, value: object) -> tuple[Any, ...]:
    """Require a tuple so callers cannot retain a mutable sequence alias."""
    if not isinstance(value, tuple):
        raise _invalid(field_name, value)
    return value


def freeze(value: Any) -> Any:
    """Recursively freeze JSON-like values while retaining scalar identities."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(item) for item in value)
    return value


def _freeze_mapping(field_name: str, value: Mapping[Any, Any]) -> Mapping[Any, Any]:
    """Validate and recursively freeze one mapping-valued model field."""
    if not isinstance(value, Mapping):
        raise _invalid(field_name, value)
    return MappingProxyType({key: freeze(item) for key, item in value.items()})


@dataclass(frozen=True)
class Extraction:
    """The ordered numeric values a model found in one WIP work unit.

    Deliberately minimal: no spans, kinds, qualifiers, roles, or representations.
    The comparison this feeds (numbers/compare.py) only needs values in reading
    order plus honest completeness -- see the 2026-09-28 simplified-check plan.
    """
    values: Tuple[Fraction, ...]
    status: str
    limitations: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate exact values and the closed completeness vocabulary."""
        values = _tuple("extraction values", self.values)
        if any(not isinstance(value, Fraction) for value in values):
            raise _invalid("extraction values", self.values)
        _enum("extraction status", self.status, EXTRACTION_STATUSES)
        if self.status != "COMPLETE" and not self.limitations:
            raise _invalid("extraction limitations", self.limitations)
        limitations = _tuple("extraction limitations", self.limitations)
        if any(not isinstance(value, str) for value in limitations):
            raise _invalid("extraction limitations", self.limitations)


@dataclass(frozen=True)
class ReferenceRow:
    """One authoritative Western-keyed OL-primary reference record."""
    western_reference: VerseRef
    ol_reference: Optional[str]
    language: str
    ol_text: str
    ol_values: Tuple[Fraction, ...]
    niv_text: str
    niv_values: Tuple[Fraction, ...]
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        """Validate typed authority fields and freeze retained raw metadata."""
        if not isinstance(self.western_reference, VerseRef):
            raise _invalid("reference row Western reference", self.western_reference)
        if self.ol_reference is not None and not isinstance(self.ol_reference, str):
            raise _invalid("reference row OL reference", self.ol_reference)
        for name, value in (("reference row OL values", self.ol_values), ("reference row NIV values", self.niv_values)):
            values = _tuple(name, value)
            if any(not isinstance(item, Fraction) for item in values):
                raise _invalid(name, value)
        if any(not isinstance(value, str) for value in (self.language, self.ol_text, self.niv_text)):
            raise _invalid("reference row text", (self.language, self.ol_text, self.niv_text))
        if not isinstance(self.metadata, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.metadata.items()
        ):
            raise _invalid("reference row metadata", self.metadata)
        object.__setattr__(self, "metadata", _freeze_mapping("reference row metadata", self.metadata))


@dataclass(frozen=True)
class ReferenceBundle:
    """One qualified immutable reference package and supporting registries."""
    package_id: str
    sha256: str
    rows: Mapping[VerseRef, ReferenceRow]
    variants: Mapping[Any, Mapping[str, object]]
    footnote_guidance: Mapping[Any, Mapping[str, object]]
    units: Mapping[Any, Mapping[str, object]]
    provenance: Mapping[str, Mapping[str, object]]
    qualification_status: str
    diagnostics: Tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        """Validate package identity and recursively freeze all nested records."""
        if not self.package_id or not isinstance(self.package_id, str):
            raise _invalid("reference package ID", self.package_id)
        if not isinstance(self.sha256, str) or len(self.sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.sha256
        ):
            raise _invalid("reference package SHA-256", self.sha256)
        _enum("reference qualification status", self.qualification_status, QUALIFICATION_STATUSES)
        for name in ("rows", "variants", "footnote_guidance", "units", "provenance"):
            object.__setattr__(self, name, _freeze_mapping(f"reference {name}", getattr(self, name)))
        diagnostics = _tuple("reference diagnostics", self.diagnostics)
        if any(not isinstance(item, Mapping) for item in diagnostics):
            raise _invalid("reference diagnostics", self.diagnostics)
        object.__setattr__(self, "diagnostics", tuple(freeze(item) for item in diagnostics))

    def lookup(self, ref: VerseRef) -> Optional[ReferenceRow]:
        """Return the authoritative Western row when the coordinate is indexed."""
        return self.rows.get(ref)

    def require_qualified(self) -> None:
        """Reject use of a bundle that did not pass authoritative qualification."""
        if self.qualification_status not in {"QUALIFIED", "QUALIFIED_WITH_DIAGNOSTICS"}:
            raise ValidationError(
                f"NCA reference package {self.package_id} is {self.qualification_status}",
                code="NCA_REFERENCE_NOT_QUALIFIED",
                details={"package_id": self.package_id, "qualification_status": self.qualification_status},
            )


@dataclass(frozen=True)
class TargetNote:
    """Target note text kept separate from locator and anchoring evidence."""
    note_id: str
    marker: str
    text: str
    anchor_references: Tuple[VerseRef, ...]
    content_spans: Tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        """Validate note anchors and recursively freeze provenance spans."""
        if any(not isinstance(value, str) for value in (self.note_id, self.marker, self.text)):
            raise _invalid("target note text", (self.note_id, self.marker, self.text))
        references = _tuple("target note anchor references", self.anchor_references)
        if any(not isinstance(value, VerseRef) for value in references):
            raise _invalid("target note anchor references", self.anchor_references)
        spans = _tuple("target note content spans", self.content_spans)
        if any(not isinstance(value, Mapping) for value in spans):
            raise _invalid("target note content spans", self.content_spans)
        object.__setattr__(self, "content_spans", tuple(freeze(value) for value in spans))


@dataclass(frozen=True)
class TargetUnit:
    """One target body stream with separate notes and immutable source identity."""
    unit_id: str
    target_references: Tuple[VerseRef, ...]
    main_text: str
    notes: Tuple[TargetNote, ...]
    source_sha256: str
    source_locator: Mapping[str, int]

    def __post_init__(self) -> None:
        """Validate target identities while permitting registered absent units."""
        if not isinstance(self.unit_id, str) or not self.unit_id:
            raise _invalid("target unit ID", self.unit_id)
        references = _tuple("target unit references", self.target_references)
        if any(not isinstance(value, VerseRef) for value in references):
            raise _invalid("target unit references", self.target_references)
        if not isinstance(self.main_text, str):
            raise _invalid("target unit main text", self.main_text)
        notes = _tuple("target unit notes", self.notes)
        if any(not isinstance(value, TargetNote) for value in notes):
            raise _invalid("target unit notes", self.notes)
        if not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.source_sha256
        ):
            raise _invalid("target source SHA-256", self.source_sha256)
        if not isinstance(self.source_locator, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, int)
            for key, value in self.source_locator.items()
        ):
            raise _invalid("target source locator", self.source_locator)
        object.__setattr__(self, "source_locator", _freeze_mapping("target source locator", self.source_locator))


@dataclass(frozen=True)
class ProjectedUnit:
    """A target unit projected into distinct Western and canonical identities."""
    target: TargetUnit
    western_references: Tuple[VerseRef, ...]
    canonical_references: Tuple[VerseRef, ...]
    precision: str
    status: str
    target_western_mapping: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate projected coordinates, precision label, and readiness state."""
        if not isinstance(self.target, TargetUnit):
            raise _invalid("projected target", self.target)
        for name, values in (("projected Western references", self.western_references), ("projected canonical references", self.canonical_references)):
            items = _tuple(name, values)
            if any(not isinstance(value, VerseRef) for value in items):
                raise _invalid(name, values)
        if not isinstance(self.precision, str) or not self.precision:
            raise _invalid("projection precision", self.precision)
        _enum("projection status", self.status, PROJECTION_STATUSES)
        mapping = self.target_western_mapping
        targets = {ref.label() for ref in self.target.target_references}
        western = {ref.label() for ref in self.western_references}
        if not isinstance(mapping, Mapping) or mapping and set(mapping) != targets or any(
            not isinstance(rows, tuple) or any(not isinstance(row, str) or row not in western for row in rows)
            or rows != tuple(ref.label() for ref in self.western_references if ref.label() in rows)
            for rows in mapping.values()
        ):
            raise _invalid("target Western mapping", mapping)
        object.__setattr__(self, "target_western_mapping", freeze(mapping))
