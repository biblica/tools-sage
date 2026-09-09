"""Immutable typed records shared by the NCA domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from sage.errors import ValidationError
from sage.vrs import VerseRef


NUMERIC_KINDS = frozenset({"CARDINAL", "ORDINAL", "FRACTION", "RANGE", "RATIO"})
NUMERIC_QUALIFIERS = frozenset({"EXACT", "ABOUT", "LESS_THAN", "MORE_THAN"})
EXTRACTION_STATUSES = frozenset({"COMPLETE", "PARTIAL", "UNSUPPORTED"})
SEMANTIC_OUTCOMES = frozenset(
    {
        "PASS_AUTHORITY1",
        "PASS_EQUIVALENT_NUMERIC_EXPRESSION",
        "PASS_UNIT_CONVERSION",
        "REGISTERED_ALTERNATE",
        "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
        "CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE",
        "NO_CONFIGURED_OL_READING",
        "REVIEW_MISSING_FOOTNOTE",
        "REVIEW_VALUE_DIFFERENCE",
        "REVIEW_NUMBER_MISSING",
        "REVIEW_NUMBER_ADDED",
        "INSUFFICIENT_EVIDENCE",
        "REFERENCE_NOT_INDEXED",
        "NOT_ASSESSED",
    }
)
FOOTNOTE_ACTIONS = frozenset({"NONE", "RECOMMEND", "REQUIRE"})
FOOTNOTE_STATUSES = frozenset(
    {"ADEQUATE", "MISSING", "INADEQUATE", "NOT_REQUIRED", "NOT_ASSESSED"}
)
FOOTNOTE_OUTCOMES = frozenset(
    {"NONE", "ADVISORY", "REVIEW_MISSING_FOOTNOTE", "INSUFFICIENT_EVIDENCE"}
)
PROJECTION_STATUSES = frozenset({"READY", "AMBIGUOUS", "UNMAPPED", "REGISTERED_ABSENCE"})
READING_SELECTIONS = frozenset({"OL", "ALT", "UNSUPPORTED", "UNASSESSED"})
SOURCE_VALIDATION_OUTCOMES = frozenset(
    {
        "PASS_AUTHORITY1",
        "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
        "CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE",
        "NO_CONFIGURED_OL_READING",
    }
)
QUALIFICATION_STATUSES = frozenset(
    {"QUALIFIED", "QUALIFIED_WITH_DIAGNOSTICS", "DIAGNOSTIC", "BLOCKED"}
)


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
class NumericExpression:
    """One exact numeric expression tied to its original text span."""
    values: Tuple[Fraction, ...]
    kind: str
    surface: str
    span: Tuple[int, int]
    unit: Optional[str] = None
    qualifier: str = "EXACT"
    role: Optional[str] = None
    expression_id: Optional[str] = None
    stream_id: str = "main"
    representations: Tuple[Mapping[str, object], ...] = ()
    role_spans: Tuple[Tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        """Validate exact values, closed vocabularies, and source span bounds."""
        values = _tuple("numeric expression values", self.values)
        if not values or any(not isinstance(value, Fraction) for value in values):
            raise _invalid("numeric expression values", self.values)
        _enum("numeric expression kind", self.kind, NUMERIC_KINDS)
        _enum("numeric expression qualifier", self.qualifier, NUMERIC_QUALIFIERS)
        span = _tuple("numeric expression span", self.span)
        if len(span) != 2 or any(not isinstance(value, int) for value in span) or span[0] < 0 or span[1] < span[0]:
            raise _invalid("numeric expression span", self.span)
        if not isinstance(self.surface, str):
            raise _invalid("numeric expression surface", self.surface)
        if self.unit is not None and not isinstance(self.unit, str):
            raise _invalid("numeric expression unit", self.unit)
        if self.role is not None and not isinstance(self.role, str):
            raise _invalid("numeric expression role", self.role)
        if self.expression_id is not None and (
            not isinstance(self.expression_id, str) or not self.expression_id
        ):
            raise _invalid("numeric expression ID", self.expression_id)
        if not isinstance(self.stream_id, str) or not self.stream_id:
            raise _invalid("numeric expression stream ID", self.stream_id)
        representations = _tuple(
            "numeric expression representations", self.representations
        )
        if any(not isinstance(value, Mapping) for value in representations):
            raise _invalid("numeric expression representations", self.representations)
        object.__setattr__(
            self,
            "representations",
            tuple(freeze(value) for value in representations),
        )
        role_spans = _tuple("numeric expression role spans", self.role_spans)
        for role_span in role_spans:
            values = _tuple("numeric expression role span", role_span)
            if (
                len(values) != 2
                or any(not isinstance(value, int) for value in values)
                or values[0] < 0
                or values[1] < values[0]
            ):
                raise _invalid("numeric expression role span", role_span)


@dataclass(frozen=True)
class Extraction:
    """A model extraction with explicit completeness limitations."""
    expressions: Tuple[NumericExpression, ...]
    status: str
    limitations: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate extraction members and its closed status vocabulary."""
        expressions = _tuple("extraction expressions", self.expressions)
        if any(not isinstance(value, NumericExpression) for value in expressions):
            raise _invalid("extraction expressions", self.expressions)
        _enum("extraction status", self.status, EXTRACTION_STATUSES)
        limitations = _tuple("extraction limitations", self.limitations)
        if any(not isinstance(value, str) for value in limitations):
            raise _invalid("extraction limitations", self.limitations)


@dataclass(frozen=True)
class SemanticDecision:
    """A deterministic semantic outcome with bounded evidence identifiers."""
    outcome: str
    evidence_ids: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the semantic outcome and immutable evidence identifiers."""
        _enum("semantic outcome", self.outcome, SEMANTIC_OUTCOMES)
        for name, value in (("semantic evidence IDs", self.evidence_ids), ("semantic reason codes", self.reason_codes)):
            items = _tuple(name, value)
            if any(not isinstance(item, str) or not item for item in items):
                raise _invalid(name, value)


@dataclass(frozen=True)
class FootnoteDecision:
    """A reading-dependent disclosure assessment and its exact note spans."""
    action: str
    status: str
    outcome: str
    evidence_spans: Tuple[Tuple[int, int], ...] = ()
    evidence_note_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate footnote policy vocabularies and evidence span bounds."""
        _enum("footnote action", self.action, FOOTNOTE_ACTIONS)
        _enum("footnote status", self.status, FOOTNOTE_STATUSES)
        _enum("footnote outcome", self.outcome, FOOTNOTE_OUTCOMES)
        spans = _tuple("footnote evidence spans", self.evidence_spans)
        for span in spans:
            values = _tuple("footnote evidence span", span)
            if len(values) != 2 or any(not isinstance(value, int) for value in values) or values[0] < 0 or values[1] < values[0]:
                raise _invalid("footnote evidence span", span)
        note_ids = _tuple("footnote evidence note IDs", self.evidence_note_ids)
        if any(not isinstance(note_id, str) or not note_id for note_id in note_ids):
            raise _invalid("footnote evidence note IDs", self.evidence_note_ids)
        if note_ids and len(note_ids) != len(spans):
            raise _invalid("footnote evidence note IDs", self.evidence_note_ids)


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


@dataclass(frozen=True)
class ReadingDecision:
    """The selected OL, alternate, or unsupported reading with raw policy state."""
    selected: str
    semantic: SemanticDecision
    footnote_action: str
    registry_id: Optional[str]
    source_ids: Tuple[str, ...]
    source_validation_outcome: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate selection, policy action, provenance, and source outcome."""
        _enum("reading selection", self.selected, READING_SELECTIONS)
        if not isinstance(self.semantic, SemanticDecision):
            raise _invalid("reading semantic decision", self.semantic)
        _enum("reading footnote action", self.footnote_action, FOOTNOTE_ACTIONS)
        if self.registry_id is not None and not isinstance(self.registry_id, str):
            raise _invalid("reading registry ID", self.registry_id)
        source_ids = _tuple("reading source IDs", self.source_ids)
        if any(not isinstance(value, str) or not value for value in source_ids):
            raise _invalid("reading source IDs", self.source_ids)
        if self.source_validation_outcome is not None:
            _enum(
                "reading source validation outcome",
                self.source_validation_outcome,
                SOURCE_VALIDATION_OUTCOMES,
            )


@dataclass(frozen=True)
class UnitResult:
    """A complete NCA unit result with separate semantic, note, and style state."""
    projected: ProjectedUnit
    extraction: Extraction
    reading: ReadingDecision
    footnote: FootnoteDecision
    final_outcome: str
    style_findings: Tuple[Mapping[str, object], ...] = ()
    limitations: Tuple[str, ...] = ()
    ol_references: Tuple[Optional[str], ...] = ()

    def __post_init__(self) -> None:
        """Validate result aggregates and freeze style evidence mappings."""
        if not isinstance(self.projected, ProjectedUnit):
            raise _invalid("unit result projection", self.projected)
        if not isinstance(self.extraction, Extraction):
            raise _invalid("unit result extraction", self.extraction)
        if not isinstance(self.reading, ReadingDecision):
            raise _invalid("unit result reading", self.reading)
        if not isinstance(self.footnote, FootnoteDecision):
            raise _invalid("unit result footnote", self.footnote)
        _enum("unit final outcome", self.final_outcome, SEMANTIC_OUTCOMES)
        findings = _tuple("unit style findings", self.style_findings)
        if any(not isinstance(value, Mapping) for value in findings):
            raise _invalid("unit style findings", self.style_findings)
        object.__setattr__(self, "style_findings", tuple(freeze(value) for value in findings))
        limitations = _tuple("unit limitations", self.limitations)
        if any(not isinstance(value, str) for value in limitations):
            raise _invalid("unit limitations", self.limitations)
        ol_references = _tuple("unit OL references", self.ol_references)
        if (
            len(ol_references) not in {0, len(self.projected.western_references)}
            or any(value is not None and (not isinstance(value, str) or not value) for value in ol_references)
            or any(value is None for value in ol_references)
            and self.projected.status != "REGISTERED_ABSENCE"
        ):
            raise _invalid("unit OL references", self.ol_references)


@dataclass(frozen=True)
class RunResult:
    """An immutable NCA run aggregate with findings, coverage, and summary."""
    units: Tuple[UnitResult, ...]
    findings: Tuple[Mapping[str, object], ...] = ()
    coverage: Mapping[str, object] = field(default_factory=dict)
    summary: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate unit membership and recursively freeze run-level mappings."""
        units = _tuple("run units", self.units)
        if any(not isinstance(value, UnitResult) for value in units):
            raise _invalid("run units", self.units)
        findings = _tuple("run findings", self.findings)
        if any(not isinstance(value, Mapping) for value in findings):
            raise _invalid("run findings", self.findings)
        object.__setattr__(self, "findings", tuple(freeze(value) for value in findings))
        object.__setattr__(self, "coverage", _freeze_mapping("run coverage", self.coverage))
        object.__setattr__(self, "summary", _freeze_mapping("run summary", self.summary))
