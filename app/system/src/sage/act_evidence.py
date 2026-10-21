"""ACT task evidence: bounded USJ/SFM packets, grammar and VRS contracts, RTC preflight, structural triage, and budget checks.

Split from act_tasks.py, which re-exports every name defined here.
"""

from __future__ import annotations

from .act_outputs import marker_sequence
from .atomic import atomic_write_bytes
from .atomic import atomic_write_json
from .atomic import atomic_write_text
from .bic_memory import eligible_memory_records
from .config import load_yaml
from .errors import EvidenceLimitError
from .errors import ValidationError
from .evidence import EvidencePolicy
from .external_access import validate_external_companion_file
from .grammar import GrammarProfile
from .grammar import load_grammar_profile
from .grammar_governance import active_grammar_review
from .grammar_governance import grammar_profile_is_approved
from .hashing import sha256_bytes
from .hashing import sha256_file
from .linguistic_profiles import complete_language_profile_contract
from .llm_settings import load_llm_settings
from .marker_checks import load_verse_content
from .marker_checks import marker_review
from .marker_checks import packet_marker_candidates
from .numeric_candidates import numeric_candidates
from .numeric_candidates import packet_verses
from .original_language_resources import OL_AUTHORITY_PROFILE_FILE
from .profiles import load_workflow_profile
from .references import AnalysisScope
from .references import ScriptureScope
from .references import ScriptureScopeSet
from .references import expand_reference_atoms
from .references import parse_scope
from .references import parse_scope_set
from .registry import EcosystemConfig
from .registry import ProjectSpec
from .scripture import compile_project
from .scripture import parser_errors_for_chapters
from .sfm_slicer import measure_sfm_text
from .source_coverage import source_text_issues
from .storage import StorageError
from .storage import resolve_declared_path
from .text_coverage import gap_findings
from .text_coverage import omission_rows
from .text_coverage import psalm_title_chapters
from .usj import compile_usfm_text
from .usj import parse_usj_units
from .verse_alignment import ProjectVerseIndex
from .verse_alignment import align_records
from .verse_alignment import missing_by_local_ref
from .verse_alignment import project_coordinates
from .versification_service import VersificationService
from .vrs import VerseRef
from .vrs import resolve_project_vrs_paths
from .work_units import EvidenceRecord
from .work_units import records_from_project_result
from .work_units import select_records_for_scope
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Mapping
from typing import Sequence
import json
import re
from .act_common import (
    READY_RESOURCE_STATES,
    _analysis_identity,
    _assert_initialized_and_ready,
    _assert_project_scope,
    _load_list,
    _memory_root,
    _one_book_file,
    _relative,
    _resolve_bic_lexical_donor,
    _validate_task_projects,
    _vrs_provenance_reference,
)



def validate_act_request_readiness(
    config: EcosystemConfig,
    *,
    workflow: str,
    output_project_id: str,
    contemporary_source_id: str,
    lexical_donor_id: str | None = None,
    scope_value: str,
) -> dict[str, Any]:
    """Validate initialization and task-specific project readiness without creating a task."""
    scope = parse_scope(scope_value)
    output, source, ol_role, ol_project = _validate_task_projects(
        config, workflow, output_project_id, contemporary_source_id, scope, job_id=None
    )
    donor = (
        _resolve_bic_lexical_donor(
            config, donor_project_id=lexical_donor_id, output=output, source=source, scope=scope
        )
        if workflow == "bic"
        else None
    )
    readiness_projects: list[tuple[str, ProjectSpec]] = [
        (
            "BIC SOURCE"
            if workflow == "bic"
            else f"{_analysis_identity(workflow)} comparison source",
            source,
        ),
    ]
    if workflow != "bic":
        readiness_projects.insert(0, (f"{_analysis_identity(workflow)} WIP", output))
    if donor is not None:
        readiness_projects.append(("BIC DONOR", donor))
    if workflow == "bic":
        compiled, bic_alignment = _prepare_bic_project_alignment(
            config,
            source=source,
            target=output,
            source_scope=scope,
            source_readiness_projects=readiness_projects,
        )
    else:
        compiled = _assert_initialized_and_ready(
            config, workflow, readiness_projects, scope
        )
        bic_alignment = None
    return {
        "workflow": workflow,
        "output_project": output.project_id,
        "contemporary_source": source.project_id,
        "lexical_donor": donor.project_id if donor is not None else None,
        "original_language": {
            "role": ol_role,
            "project": ol_project.project_id if ol_project else None,
            "availability": "AVAILABLE" if ol_project else "UNAVAILABLE_OPTIONAL",
        },
        "scope": scope.label(),
        "target_scope": (
            bic_alignment["target_scope"] if bic_alignment is not None else None
        ),
        "project_statuses": {key: value.get("status") for key, value in compiled.items()},
    }


def _scope_chapters(scopes: Iterable[AnalysisScope]) -> set[int] | None:
    """Return the chapters the scopes touch, or None when any scope is a whole book."""
    chapters: set[int] = set()
    flat = [
        portion
        for scope in scopes
        for portion in (scope.portions if isinstance(scope, ScriptureScopeSet) else (scope,))
    ]
    for scope in flat:
        if scope.start_chapter is None:
            return None
        chapters.update(range(scope.start_chapter, (scope.end_chapter or scope.start_chapter) + 1))
    return chapters


def _parser_errors_in_scope(text: str, name: str, usj: Mapping[str, Any], chapters: set[int] | None) -> list[str]:
    """Return parser errors that affect the requested chapters; errors elsewhere in the book do not block."""
    errors = list(dict(usj.get("sage") or {}).get("errors", []))
    if not errors or not chapters:
        return errors
    return parser_errors_for_chapters(text, name, chapters)


def _scope_units(
    path: Path,
    scope: ScriptureScope,
    *,
    allow_empty: bool = False,
) -> tuple[list[dict[str, Any]], set[VerseRef], str]:
    """Select authorized USJ units from one atomic read and return its exact byte hash."""
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        if "\ufffd" in text:
            raise UnicodeError(f"Literal Unicode replacement character U+FFFD is not approved in {path}")
        usj = compile_usfm_text(text, path.name)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValidationError(f"Cannot compile task input {path}: {exc}") from exc
    parser_errors = _parser_errors_in_scope(text, path.name, usj, _scope_chapters((scope,)))
    if parser_errors:
        raise ValidationError(f"Task input {path.name} has parser errors: {', '.join(parser_errors[:8])}")
    units = parse_usj_units(usj)
    selected: list[dict[str, Any]] = []
    refs: set[VerseRef] = set()
    for unit in units:
        unit_refs = {
            VerseRef(scope.book, int(unit["chapter"]), verse)
            for verse in range(int(unit["verse_start"]), int(unit["verse_end"]) + 1)
        }
        intersection = {ref for ref in unit_refs if scope.contains(ref)}
        if not intersection:
            continue
        if intersection != unit_refs:
            raise ValidationError(
                f"Scope {scope.label()} cuts through a verse bridge in {path.name}; use the complete bridge"
            )
        selected.append(unit)
        refs.update(unit_refs)
    if not selected and not allow_empty:
        raise ValidationError(f"Scope {scope.label()} is absent from {path.name}")
    return selected, refs, sha256_bytes(raw)


def _comparison_usj(
    bounded_usfm: str,
    *,
    source: Path,
    source_sha256: str,
    scope: ScriptureScope,
    refs: set[VerseRef],
) -> dict[str, Any]:
    """Compile one bounded comparison packet to compact, provenance-bound USJ."""
    usj = compile_usfm_text(bounded_usfm, source.name)
    parser_errors = list(usj.get("sage", {}).get("errors", []))
    if parser_errors:
        raise ValidationError(
            f"Bounded comparison packet has parser errors: {', '.join(parser_errors[:8])}"
        )
    sage = dict(usj.get("sage", {}))
    records: list[dict[str, Any]] = []
    for value in sage.get("verse_records", []):
        if not isinstance(value, dict):
            continue
        record = dict(value)
        for duplicate in (
            "lines",
            "raw_usfm",
            "body_text",
            "body_text_exact",
            "body_text_normalized",
        ):
            record.pop(duplicate, None)
        records.append(record)
    sage.update(
        {
            "verse_records": records,
            "source_format": "USFM",
            "comparison_format": "USJ",
            "source_file": source.name,
            "source_sha256": source_sha256,
            "scope": scope.label(),
            "atomic_references": [ref.label() for ref in sorted(refs)],
            "authority_rule": (
                "The hashed USFM/SFM file is the immutable source of record. This bounded USJ is "
                "a deterministic comparison representation and is never written back as authority."
            ),
        }
    )
    usj["sage"] = sage
    return usj


def _write_scope_usj_packet(
    source: Path,
    scope: ScriptureScope,
    destination: Path,
    *,
    allow_empty: bool = False,
) -> tuple[dict[str, Any], str]:
    """Write bounded comparison evidence as USJ and return private USFM for validation/indexing."""
    units, refs, source_sha256 = _scope_units(source, scope, allow_empty=allow_empty)
    lines = [f"\\id {scope.book} SAGE bounded comparison evidence"]
    if not units and scope.start_chapter is not None:
        lines.append(f"\\c {scope.start_chapter}")
    current_chapter: int | None = None
    for unit in units:
        chapter = int(unit["chapter"])
        if chapter != current_chapter:
            lines.append(f"\\c {chapter}")
            current_chapter = chapter
        raw_lines = list(unit.get("lines", []))
        if not raw_lines:
            raise ValidationError(f"Compiled unit in {source.name} has no retained USFM lines")
        lines.extend(str(line) for line in raw_lines)
    bounded_usfm = "\n".join(lines).rstrip() + "\n"
    atomic_write_json(
        destination,
        _comparison_usj(
            bounded_usfm,
            source=source,
            source_sha256=source_sha256,
            scope=scope,
            refs=refs,
        ),
    )
    return (
        {
            "path": destination.name,
            "source_file": source.name,
            "source_format": "USFM",
            "comparison_format": "USJ",
            "source_sha256": source_sha256,
            "packet_sha256": sha256_file(destination),
            "scope": scope.label(),
            "atomic_references": [ref.label() for ref in sorted(refs)],
            "marker_sequence": list(marker_sequence(bounded_usfm)),
        },
        bounded_usfm,
    )


def _write_bic_donor_vocabulary(
    source: Path,
    scope: ScriptureScope,
    destination: Path,
) -> dict[str, Any]:
    """Harvest decontextualized DONOR vocabulary without routing donor Scripture wording."""
    units, _, source_sha256 = _scope_units(source, scope)
    displays: dict[str, set[str]] = {}
    for unit in units:
        for token in re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", str(unit.get("text", "")), flags=re.UNICODE):
            key = token.casefold()
            displays.setdefault(key, set()).add(token)
    forms = [
        {
            "form": key,
            "attested_forms": sorted(displays.get(key, {key})),
        }
        for key in sorted(displays)
    ]
    packet = {
        "schema_version": "1.0",
        "role": "LEXICAL_DONOR",
        "scope": scope.label(),
        "source_project_file_sha256": source_sha256,
        "form_count": len(forms),
        "forms": forms,
        "authority_rule": (
            "Vocabulary evidence only. This packet deliberately omits donor verse text, sequence, "
            "frequency, syntax, propositions, participant structure, and verse-level wording. CONTENT_SOURCE "
            "remains the sole BIC content and translation authority."
        ),
    }
    atomic_write_json(destination, packet)
    return {
        "path": destination.name,
        "source_sha256": source_sha256,
        "packet_sha256": sha256_file(destination),
        "scope": scope.label(),
        "form_count": len(forms),
        "evidence_id": "DONOR_VOCABULARY",
        "authority": "VOCABULARY_ONLY",
    }


def _write_reference_inventory_usj_packet(
    source: Path,
    reference_values: Sequence[str],
    destination: Path,
    *,
    parent_scope: ScriptureScope,
    allow_empty: bool = False,
    text_filter: Callable[[str], str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Write exact composite-RTC coordinates as deterministic bounded comparison USJ.

    `text_filter` is applied to the bounded SFM after coordinate selection (e.g. Hebrew cantillation removal).
    """
    raw = source.read_bytes()
    text = raw.decode("utf-8-sig")
    usj = compile_usfm_text(text, source.name)
    requested_scopes = [scope for value in reference_values for scope in parse_scope_set(value)]
    parser_errors = _parser_errors_in_scope(
        text, source.name, usj, _scope_chapters([parent_scope, *requested_scopes])
    )
    if parser_errors:
        raise ValidationError(f"Task input {source.name} has parser errors: {', '.join(parser_errors[:8])}")
    if not requested_scopes and not allow_empty:
        raise ValidationError("Composite RTC stage reference inventory must not be empty")
    selected: list[dict[str, Any]] = []
    refs: set[VerseRef] = set()
    for unit in parse_usj_units(usj):
        unit_refs = {
            VerseRef(parent_scope.book, int(unit["chapter"]), verse)
            for verse in range(int(unit["verse_start"]), int(unit["verse_end"]) + 1)
        }
        intersection = {
            ref for ref in unit_refs if any(requested.contains(ref) for requested in requested_scopes)
        }
        if not intersection:
            continue
        if intersection != unit_refs:
            raise ValidationError(
                f"Composite RTC stage inventory cuts through a verse bridge in {source.name}; include the complete bridge"
            )
        selected.append(unit)
        refs.update(unit_refs)
    if not selected and not allow_empty:
        raise ValidationError("Composite RTC stage references are absent from the routed Scripture resource")
    lines = [f"\\id {parent_scope.book} SAGE bounded stage comparison evidence"]
    if not selected:
        lines.extend(
            f"\\c {chapter}"
            for chapter in sorted({scope.start_chapter for scope in requested_scopes if scope.start_chapter is not None})
        )
    current_chapter: int | None = None
    for unit in selected:
        chapter = int(unit["chapter"])
        if chapter != current_chapter:
            lines.append(f"\\c {chapter}")
            current_chapter = chapter
        lines.extend(str(line) for line in unit.get("lines", []))
    bounded_usfm = "\n".join(lines).rstrip() + "\n"
    if text_filter is not None:
        bounded_usfm = text_filter(bounded_usfm)
    atomic_write_json(
        destination,
        _comparison_usj(
            bounded_usfm,
            source=source,
            source_sha256=sha256_bytes(raw),
            scope=parent_scope,
            refs=refs,
        ),
    )
    return (
        {
            "path": destination.name,
            "source_file": source.name,
            "source_format": "USFM",
            "comparison_format": "USJ",
            "source_sha256": sha256_bytes(raw),
            "packet_sha256": sha256_file(destination),
            "scope": parent_scope.label(),
            "stage_references": [ref.label() for ref in sorted(refs)],
            "atomic_references": [ref.label() for ref in sorted(refs)],
            "marker_sequence": list(marker_sequence(bounded_usfm)),
        },
        bounded_usfm,
    )


def _records_intersecting_reference_values(
    records: Sequence[EvidenceRecord],
    reference_values: Sequence[str],
) -> tuple[EvidenceRecord, ...]:
    """Select complete physical records intersecting an explicit local inventory."""
    atoms = {
        ref
        for value in reference_values
        if str(value).strip()
        for ref in expand_reference_atoms(str(value))
    }
    return tuple(record for record in records if atoms.intersection(record.refs))


def _rtc_canonical_packet_route(
    config: EcosystemConfig,
    *,
    output: ProjectSpec,
    reference: ProjectSpec,
    compiled: Mapping[str, dict[str, Any]],
    scope: ScriptureScope,
    primary_reference_values: Sequence[str],
    context_reference_values: Sequence[str],
) -> dict[str, Any]:
    """Resolve RTC WIP-local packet inventories through both effective Project VRSs."""
    wip_records = records_from_project_result(
        output.project_id,
        compiled[output.project_id],
        resource_role="WIP",
    )
    reference_records = records_from_project_result(
        reference.project_id,
        compiled[reference.project_id],
        resource_role="REFERENCE",
    )
    selected_wip = (
        _records_intersecting_reference_values(wip_records, primary_reference_values)
        if primary_reference_values
        else select_records_for_scope(wip_records, scope)
    )
    context_wip = _records_intersecting_reference_values(
        wip_records,
        context_reference_values,
    )
    service = VersificationService(config)
    wip_index = ProjectVerseIndex.cached(
        output.project_id,
        wip_records,
        service.project_schema(output),
    )
    reference_index = ProjectVerseIndex.cached(
        reference.project_id,
        reference_records,
        service.project_schema(reference),
    )
    primary_alignment = align_records(selected_wip, wip_index, reference_index)
    context_alignment = align_records(context_wip, wip_index, reference_index)
    issues = _canonical_gap_source_issues(
        selected_wip,
        wip_index,
        primary_alignment.missing_canonical_refs,
        workflow="RTC",
        source_stream="REFERENCE",
        source_project_id=reference.project_id,
        wip_project_id=output.project_id,
        scope=scope.label(),
    )
    return {
        "reference_references": [
            record.reference for record in primary_alignment.authority_records
        ],
        "context_reference_references": [
            record.reference for record in context_alignment.authority_records
        ],
        "alignment": {
            "primary_local_atoms": [
                ref.label() for ref in sorted(primary_alignment.primary_local_refs)
            ],
            "canonical_atoms": [
                ref.label() for ref in sorted(primary_alignment.canonical_refs)
            ],
            "reference_local_spans": [
                record.reference for record in primary_alignment.authority_records
            ],
            "missing_canonical_atoms": [
                ref.label() for ref in sorted(primary_alignment.missing_canonical_refs)
            ],
        },
        "source_text_issues": issues,
    }


def _projected_scope_for_refs(
    refs: Iterable[VerseRef],
    *,
    schema,
) -> ScriptureScope | None:
    """Return one exact contiguous TARGET-local scope, or ``None`` when unsafe."""
    ordered = tuple(sorted(frozenset(refs)))
    if not ordered or len({ref.book for ref in ordered}) != 1:
        return None
    for previous, current in zip(ordered, ordered[1:]):
        if previous.book != current.book:
            return None
        if previous.chapter == current.chapter:
            if current.verse != previous.verse + 1:
                return None
            continue
        chapter_limit = schema.chapter_limit(previous.book, previous.chapter)
        if (
            current.chapter != previous.chapter + 1
            or current.verse != 1
            or chapter_limit != previous.verse
        ):
            return None
    first = ordered[0]
    last = ordered[-1]
    return ScriptureScope(
        book=first.book,
        start_chapter=first.chapter,
        start_verse=first.verse,
        end_chapter=last.chapter,
        end_verse=last.verse,
    )


def _scope_envelope_for_refs(refs: Iterable[VerseRef]) -> ScriptureScope | None:
    """Return the narrowest one-book scope containing every projected coordinate."""
    ordered = tuple(sorted(frozenset(refs)))
    if not ordered or len({ref.book for ref in ordered}) != 1:
        return None
    first = ordered[0]
    last = ordered[-1]
    return ScriptureScope(
        book=first.book,
        start_chapter=first.chapter,
        start_verse=first.verse,
        end_chapter=last.chapter,
        end_verse=last.verse,
    )


def _bic_canonical_projection(
    config: EcosystemConfig,
    *,
    source: ProjectSpec,
    target: ProjectSpec,
    compiled: Mapping[str, dict[str, Any]],
    scope: ScriptureScope,
) -> dict[str, Any]:
    """Project BIC SOURCE-local coverage into deterministic TARGET coordinates."""
    source_records = records_from_project_result(
        source.project_id,
        compiled[source.project_id],
        resource_role="CONTENT_SOURCE",
    )
    target_result = compiled.get(target.project_id)
    target_records = (
        records_from_project_result(
            target.project_id,
            dict(target_result),
            resource_role="GENERATED_TARGET",
        )
        if target_result is not None
        and str(target_result.get("status")) in READY_RESOURCE_STATES
        else ()
    )
    selected_source = select_records_for_scope(source_records, scope)
    service = VersificationService(config)
    source_schema = service.project_schema(source)
    target_schema = service.project_schema(target)
    source_index = ProjectVerseIndex.build(
        source.project_id,
        source_records,
        source_schema,
    )
    target_index = ProjectVerseIndex.build(
        target.project_id,
        target_records,
        target_schema,
    )
    source_refs = frozenset(ref for record in selected_source for ref in record.refs)
    projection = project_coordinates(source_refs, source_index, target_index)
    target_scope = _projected_scope_for_refs(
        projection.target_local_refs,
        schema=target_schema,
    )
    target_shapes: list[list[int]] = []
    record_shapes_are_precise = True
    for record in selected_source:
        record_projection = project_coordinates(record.refs, source_index, target_index)
        record_scope = _projected_scope_for_refs(
            record_projection.target_local_refs,
            schema=target_schema,
        )
        if (
            not record_projection.is_deterministic
            or record_scope is None
            or record_scope.start_chapter != record_scope.end_chapter
        ):
            record_shapes_are_precise = False
            continue
        assert record_scope.start_chapter is not None
        assert record_scope.start_verse is not None
        assert record_scope.end_verse is not None
        target_shapes.append(
            [
                record_scope.start_chapter,
                record_scope.start_verse,
                record_scope.end_verse,
            ]
        )
    target_existing_records = target_index.records_for_canonical(
        projection.canonical_refs
    )
    target_existing_refs = frozenset(
        ref for record in target_existing_records for ref in record.refs
    )
    # Protected marker validation is positional, so a moved chapter break must
    # remain inspect-only even when every individual coordinate maps precisely.
    source_breaks: list[int] = []
    target_breaks: list[int] = []
    previous_source_chapter: int | None = None
    previous_target_chapter: int | None = None
    if len(target_shapes) == len(selected_source):
        for index, (record, target_shape) in enumerate(
            zip(selected_source, target_shapes)
        ):
            if record.chapter != previous_source_chapter:
                source_breaks.append(index)
                previous_source_chapter = record.chapter
            target_chapter = target_shape[0]
            if target_chapter != previous_target_chapter:
                target_breaks.append(index)
                previous_target_chapter = target_chapter
    chapter_topology_is_compatible = (
        len(target_shapes) == len(selected_source)
        and source_breaks == target_breaks
    )
    writable = (
        projection.is_deterministic
        and target_scope is not None
        and record_shapes_are_precise
        and len(target_shapes) == len(selected_source)
        and chapter_topology_is_compatible
    )
    advisory = None
    if not writable:
        advisory = {
            "code": "BIC_TARGET_VRS_ALIGNMENT_REQUIRED",
            "classification": "STRUCTURE_ADVISORY",
            "message": (
                "BIC SOURCE coverage does not project to one coordinate-precise, "
                "contiguous, marker-compatible TARGET-local span. INSPECT may "
                "continue, but writable stages require human versification alignment."
            ),
            "next_stage_allowed": False,
        }
    return {
        "primary_stream": "SOURCE",
        "target_stream": "TARGET",
        "source_primary_references": [ref.label() for ref in sorted(source_refs)],
        "canonical_references": [
            ref.label() for ref in sorted(projection.canonical_refs)
        ],
        "target_local_references": [
            ref.label() for ref in sorted(projection.target_local_refs)
        ],
        "target_existing_references": [
            ref.label() for ref in sorted(target_existing_refs)
        ],
        "target_shapes": target_shapes,
        "chapter_topology": {
            "source_break_before_record_indexes": source_breaks,
            "target_break_before_record_indexes": target_breaks,
            "is_compatible": chapter_topology_is_compatible,
        },
        "precision": projection.precision,
        "is_deterministic": projection.is_deterministic,
        "is_writable": writable,
        "source_effective_vrs_sha256": service.effective_fingerprint(source),
        "target_effective_vrs_sha256": service.effective_fingerprint(target),
        "target_scope": target_scope.label() if target_scope is not None else None,
        "advisory": advisory,
    }


def _prepare_bic_project_alignment(
    config: EcosystemConfig,
    *,
    source: ProjectSpec,
    target: ProjectSpec,
    source_scope: ScriptureScope,
    source_readiness_projects: Sequence[tuple[str, ProjectSpec]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile SOURCE-side inputs, project coordinates, then compile TARGET scope."""
    compiled = _assert_initialized_and_ready(
        config,
        "bic",
        source_readiness_projects,
        source_scope,
    )
    provisional = _bic_canonical_projection(
        config,
        source=source,
        target=target,
        compiled=compiled,
        scope=source_scope,
    )
    target_validation_scope = _scope_envelope_for_refs(
        VerseRef(
            value.split()[0],
            int(value.split()[1].split(":")[0]),
            int(value.split(":")[1]),
        )
        for value in provisional["target_local_references"]
    )
    if target_validation_scope is None:
        # An inspect-only projection may have no one-book TARGET envelope. Compile
        # the declared TARGET inventory for sealed identity/fingerprint purposes;
        # the writable-stage guard below remains authoritative.
        compiled[target.project_id] = compile_project(config, target)
    else:
        _assert_project_scope(target, target_validation_scope, "BIC TARGET")
        compiled.update(
            _assert_initialized_and_ready(
                config,
                "bic",
                (("BIC TARGET", target),),
                target_validation_scope,
            )
        )
    alignment = _bic_canonical_projection(
        config,
        source=source,
        target=target,
        compiled=compiled,
        scope=source_scope,
    )
    alignment["target_validation_scope"] = (
        target_validation_scope.label()
        if target_validation_scope is not None
        else None
    )
    return compiled, alignment


def _canonical_gap_source_issues(
    primary_records: Sequence[EvidenceRecord],
    primary_index: ProjectVerseIndex,
    missing_canonical: frozenset[VerseRef],
    *,
    workflow: str,
    source_stream: str,
    source_project_id: str,
    wip_project_id: str,
    scope: str,
) -> list[dict[str, Any]]:
    """Render canonical Authority gaps at their corresponding WIP-local coordinates."""
    canonical_by_local: dict[VerseRef, set[VerseRef]] = {}
    missing_local: set[VerseRef] = set()
    for record in primary_records:
        for local_ref, record_missing in missing_by_local_ref(record, primary_index, missing_canonical).items():
            missing_local.add(local_ref)
            canonical_by_local.setdefault(local_ref, set()).update(record_missing)
    issues = list(source_text_issues(
        missing_local,
        (),
        workflow=workflow,
        source_stream=source_stream,
        source_project_id=source_project_id,
        wip_project_id=wip_project_id,
        scope=scope,
    ))
    for issue in issues:
        local_ref = next(
            ref for ref in missing_local if ref.label() == issue["reference"]
        )
        issue["canonical_references"] = [
            ref.label() for ref in sorted(canonical_by_local[local_ref])
        ]
    return issues


def _bic_evidence_cohort(
    *,
    job_id: str | None,
    source: ProjectSpec,
    donor: ProjectSpec,
    target: ProjectSpec,
    scope: ScriptureScope,
    project_fingerprints: Mapping[str, str],
    source_packet: Path,
    donor_packet: Path,
    source_grammar_path: Path,
    target_grammar_sha256: str,
    vrs_packets: Sequence[Path],
    semantic_packets: Sequence[Path],
) -> dict[str, Any]:
    """Build the immutable evidence identity shared by BIC INSPECT, REWRITE, and SELF-CHECK."""
    components = {
        "schema_version": "1.0",
        "job_id": job_id,
        "scope": scope.label(),
        "source_project": source.project_id,
        "donor_project": donor.project_id,
        "target_project": target.project_id,
        "source_project_fingerprint": project_fingerprints[source.project_id],
        "donor_project_fingerprint": project_fingerprints[donor.project_id],
        "source_packet_sha256": sha256_file(source_packet),
        "donor_packet_sha256": sha256_file(donor_packet),
        "source_grammar_sha256": sha256_file(source_grammar_path),
        "target_grammar_sha256": target_grammar_sha256,
        "vrs_packets": {path.name: sha256_file(path) for path in sorted(vrs_packets)},
        "semantic_packets": {path.name: sha256_file(path) for path in sorted(semantic_packets)},
    }
    digest = sha256_bytes(
        json.dumps(components, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return {"sha256": digest, "components": components}


def _write_bic_governance_packets(
    config: EcosystemConfig, packet_root: Path, scope: ScriptureScope, *, job_id: str
) -> list[Path]:
    """Write same-Job BIC derived evidence into the task packet.

    Only INSPECT proposals with verified SOURCE-derived provenance may materialize as
    content-bearing memory. Generic lexicon imports are reviewable governance data,
    never BIC content authority.
    """
    memory_root = _memory_root(config)
    approved = [
        row
        for row in eligible_memory_records(_load_list(memory_root / "approved-memory.json"))
        if str(row.get("bic_job_id", "")) == job_id
        and str((row.get("provenance") or {}).get("submission_source", "")).upper() == "BIC_INSPECT"
    ]
    challenges = [
        row
        for row in _load_list(memory_root / "translation-challenges.json")
        if str(row.get("bic_job_id", "")) == job_id
        and (
            str(row.get("scope", "")) == scope.label()
            or str(row.get("scripture_reference", "")).startswith(scope.book)
        )
    ]
    approved_path = packet_root / "approved-memory.json"
    challenges_path = packet_root / "translation-challenges.json"
    atomic_write_json(approved_path, approved)
    atomic_write_json(challenges_path, challenges)
    return [approved_path, challenges_path]


def _project_grammar_profile(
    config: EcosystemConfig, project: ProjectSpec
) -> GrammarProfile | None:
    """Resolve the role-specific grammar profile selected by one project binding."""
    if not project.profile_variant:
        return None
    namespace = config.language_profile(project.language_profile)
    spec = namespace.variants[project.profile_variant]
    return load_grammar_profile(
        spec.path,
        expected_profile_id=project.profile_variant,
        expected_language=namespace.profile_language,
        expected_role=spec.role,
    )


def _grammar_profile_from_binding(config: EcosystemConfig, selector: str) -> GrammarProfile:
    """Load one Job-bound canonical linguistic profile selector (language/variant)."""
    value = str(selector or "").strip()
    if "/" not in value:
        raise ValidationError(
            f"Canonical linguistic profile selector is invalid: {value or '<missing>'}",
            code="LINGUISTIC_PROFILE_MISSING",
        )
    language, variant_id = value.split("/", 1)
    namespace = config.language_profile(language)
    spec = namespace.variants.get(variant_id)
    if spec is None:
        raise ValidationError(
            f"Canonical linguistic profile is not configured: {value}",
            code="LINGUISTIC_PROFILE_MISSING",
        )
    return load_grammar_profile(
        spec.path,
        expected_profile_id=variant_id,
        expected_language=namespace.profile_language,
        expected_role=spec.role,
    )


def _write_bound_grammar_contract(
    config: EcosystemConfig,
    selector: str,
    packet_root: Path,
    label: str,
) -> tuple[Path, GrammarProfile]:
    """Write the complete immutable Job-bound profile for one routed language stream."""
    profile = _grammar_profile_from_binding(config, selector)
    path = packet_root / f"{label}-grammar-contract.json"
    review = active_grammar_review(config, profile)
    contract = profile.contract()
    contract["governance_review"] = review
    contract["effective_status"] = (
        "ACTIVE" if grammar_profile_is_approved(config, profile) else profile.status
    )
    atomic_write_json(path, contract)
    return path, profile


def _write_report_language_contract(
    config: EcosystemConfig,
    language_tag: str,
    packet_root: Path,
    label: str,
) -> tuple[Path, GrammarProfile]:
    """Materialize one complete canonical LANGUAGE_PROFILE for generated report prose."""
    profile, contract = complete_language_profile_contract(config, language_tag)
    path = packet_root / f"{label}-language-profile.json"
    atomic_write_json(path, contract)
    return path, profile


def _write_grammar_contract(
    config: EcosystemConfig,
    project: ProjectSpec,
    packet_root: Path,
    label: str,
) -> tuple[Path | None, GrammarProfile | None]:
    """Compile and write one content-addressed grammar contract into the task evidence."""
    profile = _project_grammar_profile(config, project)
    if profile is None:
        return None, None
    path = packet_root / f"{label}-grammar-contract.json"
    review = active_grammar_review(config, profile)
    contract = profile.contract()
    contract["governance_review"] = review
    contract["effective_status"] = (
        "ACTIVE" if grammar_profile_is_approved(config, profile) else profile.status
    )
    atomic_write_json(path, contract)
    return path, profile


def _vrs_record(
    config: EcosystemConfig,
    project: ProjectSpec,
    scope: ScriptureScope,
    *,
    service: VersificationService,
) -> dict[str, Any]:
    """Return compact, scope-bounded VRS evidence and provenance."""
    base_path, custom_path = resolve_project_vrs_paths(config, project)
    schema = service.project_schema(project)
    relevant_mappings = []
    for mapping in schema.mappings:
        local_refs = mapping.local.refs()
        canonical_refs = mapping.canonical.refs()
        if any(scope.contains(ref) for ref in local_refs) or any(
            ref.book == scope.book and scope.contains(ref) for ref in canonical_refs
        ):
            relevant_mappings.append({
                "local": mapping.local.label(),
                "canonical": mapping.canonical.label(),
                "continuation": mapping.continuation,
            })
    exclusions = [ref.label() for ref in sorted(schema.exclusions) if scope.contains(ref)]
    chapter_max = {
        str(chapter): maximum
        for chapter, maximum in sorted(schema.chapter_max.get(scope.book, {}).items())
        if scope.start_chapter is None
        or (
            chapter >= scope.start_chapter
            and chapter <= (scope.end_chapter or scope.start_chapter)
        )
    }
    return {
        "project_id": project.project_id,
        "schema_id": schema.schema_id,
        "canonical_id": schema.canonical_id,
        "scope": scope.label(),
        "source_provenance": {
            "base_file": _vrs_provenance_reference(
                config, project, base_path, custom=False
            ),
            "base_sha256": sha256_file(base_path),
            "custom_file": (
                _vrs_provenance_reference(config, project, custom_path, custom=True)
                if custom_path
                else None
            ),
            "custom_sha256": sha256_file(custom_path) if custom_path else None,
        },
        "chapter_max": chapter_max,
        "mappings": relevant_mappings,
        "exclusions": exclusions,
    }


def _write_vrs_evidence(
    config: EcosystemConfig,
    packet_root: Path,
    output: ProjectSpec,
    source: ProjectSpec,
    ol_project: ProjectSpec | None,
    scope: ScriptureScope,
    *,
    output_scope: ScriptureScope | None = None,
) -> tuple[list[Path], dict[str, Any]]:
    """Write only the bounded versification evidence needed to interpret the task scope."""
    service = VersificationService(config)
    effective_output_scope = output_scope or scope
    resources: dict[str, Any] = {
        "output_project": _vrs_record(
            config,
            output,
            effective_output_scope,
            service=service,
        ),
        "contemporary_source": _vrs_record(config, source, scope, service=service),
    }
    if ol_project is not None:
        resources["original_language"] = _vrs_record(
            config, ol_project, scope, service=service
        )
    packet = {"schema_version": "1.1", "scope": scope.label(), "resources": resources}
    path = packet_root / "vrs-evidence.json"
    atomic_write_json(path, packet)
    return [path], packet


def _structural_candidates(
    config: EcosystemConfig,
    project: ProjectSpec,
    scope: AnalysisScope,
) -> list[dict[str, Any]]:
    """Derive structural RTC candidates that require explicit adjudication."""
    schema = VersificationService(config).project_schema(project)
    candidates: list[dict[str, Any]] = []
    for mapping in schema.mappings:
        local_refs = mapping.local.refs()
        if not any(scope.contains(ref) for ref in local_refs):
            continue
        canonical_refs = mapping.canonical.refs()
        if len(local_refs) == len(canonical_refs) == 1 and local_refs[0] == canonical_refs[0]:
            continue
        if len(local_refs) > len(canonical_refs):
            state = "MERGED"
        elif len(local_refs) < len(canonical_refs):
            state = "SPLIT"
        else:
            state = "MAPPED"
        # Derived from the mapping itself so IDs stay unique across every work unit of a plan.
        candidate_id = "VRS-" + sha256_bytes(
            f"{mapping.source}:{mapping.line_number}:{mapping.local.label()}:{mapping.canonical.label()}".encode("utf-8")
        )[:10].upper()
        candidates.append(
            {
                "candidate_id": candidate_id,
                "type": "VERSIFICATION_EQUIVALENCE",
                "state": state,
                "local": mapping.local.label(),
                "canonical": mapping.canonical.label(),
                "source": mapping.source,
                "line_number": mapping.line_number,
                "evidence_ids": ["WIP", "VRS-WIP"],
                "references": [ref.label() for ref in local_refs if scope.contains(ref)],
            }
        )
    return candidates


def _rtc_alignment_inputs(
    config: EcosystemConfig,
    workflow: str,
    output: ProjectSpec,
    source: ProjectSpec,
    scope: AnalysisScope,
) -> tuple[tuple[EvidenceRecord, ...], ProjectVerseIndex, tuple[EvidenceRecord, ...], ProjectVerseIndex, dict[str, Any]]:
    """Compile WIP and REFERENCE once and index both through their effective VRS schemas."""
    compiled = _assert_initialized_and_ready(
        config, workflow, [("RTC WIP", output), ("RTC REFERENCE", source)], scope
    )
    wip_records = records_from_project_result(output.project_id, compiled[output.project_id], resource_role="WIP")
    reference_records = records_from_project_result(
        source.project_id, compiled[source.project_id], resource_role="REFERENCE"
    )
    service = VersificationService(config)
    wip_index = ProjectVerseIndex.cached(output.project_id, wip_records, service.project_schema(output))
    reference_index = ProjectVerseIndex.cached(
        source.project_id, reference_records, service.project_schema(source)
    )
    return wip_records, wip_index, reference_records, reference_index, compiled


def _rtc_omission_rows(
    inputs: tuple[Any, ...],
    output: ProjectSpec,
    source: ProjectSpec,
    scope: AnalysisScope,
) -> list[dict[str, Any]]:
    """Return REFERENCE text the WIP lacks anywhere in the requested RTC scope."""
    wip_records, wip_index, reference_records, reference_index, _ = inputs
    wip_file = _one_book_file(output, scope.book)
    return omission_rows(
        wip_records,
        wip_index,
        reference_records,
        reference_index,
        scope,
        workflow="RTC",
        authority_stream="REFERENCE",
        authority_project_id=source.project_id,
        wip_project_id=output.project_id,
        title_chapters=(
            psalm_title_chapters(wip_file.read_text(encoding="utf-8-sig"))
            if wip_file is not None and scope.book == "PSA"
            else ()
        ),
    )


def _rtc_marker_review(
    inputs: tuple[Any, ...],
    output: ProjectSpec,
    source: ProjectSpec,
    scope: AnalysisScope,
) -> dict[str, list[dict[str, Any]]]:
    """Run the deterministic cross-reference and footnote checks over the WIP verses of the scope."""
    wip_records, wip_index, _reference_records, reference_index, compiled = inputs
    return marker_review(
        [record for record in wip_records if any(scope.contains(ref) for ref in record.refs)],
        load_verse_content(compiled[output.project_id]),
        wip_index,
        reference_index,
        load_verse_content(compiled[source.project_id]),
        wip_project_id=output.project_id,
        reference_project_id=source.project_id,
    )


def _structural_triage(
    config: EcosystemConfig,
    workflow: str,
    output: ProjectSpec,
    source: ProjectSpec,
    scope: AnalysisScope,
    candidates: Sequence[Mapping[str, Any]],
    inputs: tuple[Any, ...] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Decide WIP VRS mapping candidates in code from the WIP↔REFERENCE alignment.

    Identity, shift, merge, or split with text on both sides is no finding. Text missing on one side is a
    deterministic STRUCTURE finding. Only an equivalence group whose sides do not both carry text goes to
    the model. Returns ``model`` (candidates to adjudicate), ``findings``, and ``resolved`` rows.
    """
    triage: dict[str, list[dict[str, Any]]] = {"model": [], "findings": [], "resolved": []}
    if not candidates:
        return triage
    wip_records, wip_index, reference_records, reference_index, _ = inputs or _rtc_alignment_inputs(
        config, workflow, output, source, scope
    )
    for candidate in candidates:
        local = {atom for value in candidate.get("references", []) for atom in expand_reference_atoms(str(value))}
        wip_selected = tuple(record for record in wip_records if local.intersection(record.refs))
        wip_covered = {ref for record in wip_selected for ref in record.refs}
        wip_has_text = local <= wip_covered and all(
            str(record.payload.get("body_text") or "").strip() for record in wip_selected
        )
        alignment = align_records(wip_selected, wip_index, reference_index) if wip_selected else None
        canonical = set(alignment.canonical_refs) if alignment else set()
        reference_selected = alignment.authority_records if alignment else ()
        reference_has_text = bool(canonical) and not alignment.missing_canonical_refs and all(
            str(record.payload.get("body_text") or "").strip() for record in reference_selected
        )
        row = {
            "candidate_id": candidate["candidate_id"],
            "local": candidate.get("local"),
            "canonical": candidate.get("canonical"),
            "state": candidate.get("state"),
            "references": list(candidate.get("references", [])),
            "reference_spans": [record.reference for record in reference_selected],
        }
        if wip_has_text and reference_has_text:
            triage["resolved"].append({**row, "outcome": "NO_FINDING"})
        elif alignment is not None and alignment.mapping_precision == "EQUIVALENCE_GROUP":
            triage["model"].append(dict(candidate))
        else:
            missing_side = "WIP" if not wip_has_text else "REFERENCE"
            present = source.project_id if missing_side == "WIP" else output.project_id
            absent = output.project_id if missing_side == "WIP" else source.project_id
            triage["findings"].append(
                {
                    "finding_id": f"D-{candidate['candidate_id']}",
                    "target_reference": "; ".join(row["references"]),
                    "category": "STRUCTURE",
                    "issue": (
                        f"{output.project_id} {candidate.get('local')} maps to {candidate.get('canonical')}, "
                        f"which has text in {present} but none in {absent}."
                    ),
                    "required_action": f"Check whether text is missing from {absent} at this coordinate.",
                    "action_level": "REVIEW",
                    "confidence": "HIGH",
                    "evidence_ids": ["WIP", "REFERENCE"],
                    "grammar_rule_ids": [],
                    "original_language_evidence": "",
                    "detection": "DETERMINISTIC",
                }
            )
            triage["resolved"].append({**row, "outcome": "FINDING", "missing_side": missing_side})
    return triage


def _rtc_task_source_issue_rows(
    rtc_packet_route: Mapping[str, Any] | None,
    packet_records: Mapping[str, Any],
    source: ProjectSpec,
    output: ProjectSpec,
    scope: AnalysisScope,
) -> list[dict[str, Any]]:
    """Return the REFERENCE coverage gaps of one RTC task's WIP coordinates."""
    if rtc_packet_route is not None:
        return list(rtc_packet_route["source_text_issues"])
    return list(source_text_issues(
        (
            ref
            for value in packet_records["output_project"]["atomic_references"]
            for ref in expand_reference_atoms(str(value))
        ),
        (
            ref
            for value in packet_records["contemporary_source"]["atomic_references"]
            for ref in expand_reference_atoms(str(value))
        ),
        workflow="RTC",
        source_stream="REFERENCE",
        source_project_id=source.project_id,
        wip_project_id=output.project_id,
        scope=scope.label(),
    ))


def _write_analysis_preflight(
    config: EcosystemConfig,
    packet_root: Path,
    workflow: str,
    output: ProjectSpec,
    source: ProjectSpec,
    ol_project: ProjectSpec | None,
    ol_role: str,
    scope: ScriptureScope,
    packet_records: dict[str, Any],
    *,
    structural_stage: bool = False,
    source_issue_rows: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[Path], dict[str, Any]]:
    """Write deterministic RTC/legacy preflight evidence and coverage targets."""
    vrs_inputs, _ = _write_vrs_evidence(
        config, packet_root, output, source, ol_project, scope
    )
    candidates = _structural_candidates(config, output, scope)
    if structural_stage and candidates:
        # The structural model stage sees only the equivalence groups code could not decide.
        candidates = _structural_triage(config, workflow, output, source, scope, candidates)["model"]
    expected_refs = list(packet_records["output_project"]["atomic_references"])
    direct_findings = gap_findings(source_issue_rows)
    # Numbers the index settles need no model finding; the rest are candidates (NCA checks them in full).
    numeric = numeric_candidates(config, packet_verses(packet_root / str(packet_records["output_project"]["path"])))
    marker_candidates = (
        packet_marker_candidates(
            packet_root / str(packet_records["output_project"]["path"]),
            packet_root / str(packet_records["contemporary_source"]["path"]),
        )
        if packet_records.get("contemporary_source", {}).get("path")
        else []
    )
    # Each status reflects what the controller actually established for this task.
    mechanical_checks = [
        {
            # Task creation already refused parser errors in the requested chapters.
            "check_id": "BOUNDED_USFM_PARSE_AND_COORDINATE_INVENTORY",
            "status": "PASS",
            "reviewed_reference_count": len(expected_refs),
        },
        {
            "check_id": "REFERENCE_TEXT_COVERAGE",
            "status": "GAPS_REPORTED" if direct_findings else "PASS",
            "gap_count": len(direct_findings),
            "reference_coordinate_count": len(packet_records["contemporary_source"].get("atomic_references", [])),
        },
        {
            "check_id": "VERSIFICATION_MAPPING_SCAN",
            "status": "PASS_WITH_CANDIDATES" if candidates else "PASS",
            "candidate_count": len(candidates),
        },
        {
            "check_id": "EVIDENCE_ROLE_ALLOWLIST",
            "status": "PASS",
        },
    ]
    preflight = {
        "schema_version": "1.0",
        "scope": scope.label(),
        "status": "PREFLIGHT_PASS_WITH_RESTRICTIONS" if candidates else "PREFLIGHT_PASS",
        # Already reported by SAGE; the model must not restate these text gaps.
        "direct_findings": direct_findings,
        # The add and nd marker counts differ from the REFERENCE here; the model reports only material differences.
        "marker_candidates": marker_candidates,
        "numeric_candidates": numeric,
        "structural_candidates": candidates,
        "controller_checks": mechanical_checks,
        "controller_owned_outputs": [
            "task_identity",
            "coverage",
            "checks_performed",
            "review_receipt_identity",
            "final_ledgers",
            "report_rendering",
        ],
        "model_owned_outputs": ["review_summary", "semantic_findings", "stage_adjudications"],
        "stage_1": "REQUIRES_ADJUDICATION" if candidates else "AUTO_PASS",
        "stage_2": "REFERENCE_TEXT_COMPARISON",
        "finalize": "PYTHON_VALIDATION_MERGE_COVERAGE_AND_RENDER",
        "expected_references": expected_refs,
        "evidence_ids": [
            "WIP",
            "REFERENCE",
            "VRS-WIP",
            "VRS-REFERENCE",
            "PROJECT-GRAMMAR",
            *(
                [ol_role, "VRS-ORIGINAL_LANGUAGE"]
                if ol_project is not None
                else []
            ),
        ],
    }
    preflight_path = packet_root / (
        "saw-preflight.json" if workflow == "saw" else f"{workflow}-preflight.json"
    )
    atomic_write_json(preflight_path, preflight)
    return [preflight_path, *vrs_inputs], preflight


def _context_measurement(
    root: Path,
    allowed_reads: list[dict[str, str]],
    act_text: str,
    manifest_without_budget: dict[str, Any],
) -> dict[str, Any]:
    """Inventory controller-routed bytes without treating them as model tokens."""
    contributors: list[dict[str, Any]] = []
    total_bytes = 0
    for item in allowed_reads:
        try:
            path = resolve_declared_path(root, item["path"], "context measurement read")
        except StorageError as exc:
            raise ValidationError(str(exc), code="EXTERNAL_PATH_ESCAPE") from exc
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        size = len(text.encode("utf-8"))
        contributors.append({"path": item["path"], "bytes": size})
        total_bytes += size
    generated = {
        "ACT.md": act_text,
        "task-manifest.json": json.dumps(
            manifest_without_budget, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    }
    for label, text in generated.items():
        size = len(text.encode("utf-8"))
        contributors.append({"path": label, "bytes": size})
        total_bytes += size
    contributors.sort(key=lambda item: item["bytes"], reverse=True)
    return {
        "measurement_scope": "controller_inventory_only",
        "serialized_bytes": total_bytes,
        "top_contributors": contributors[:8],
    }


def _enforce_context_budget(
    telemetry: dict[str, Any],
    policy: EvidencePolicy,
    *,
    operation: str,
    scope: ScriptureScope,
    primary_verse_units: int,
) -> None:
    """Reject a task whose routed analysis SFM or primary scope exceeds configured hard limits."""
    failures: list[str] = []
    if telemetry["serialized_bytes"] > policy.hard_serialized_bytes:
        failures.append(
            f"serialized bytes {telemetry['serialized_bytes']} > {policy.hard_serialized_bytes}"
        )
    if telemetry["estimated_tokens"] > policy.hard_estimated_tokens:
        failures.append(
            f"estimated tokens {telemetry['estimated_tokens']} > {policy.hard_estimated_tokens}"
        )
    if primary_verse_units > policy.maximum_primary_verse_units:
        failures.append(
            f"primary verse units {primary_verse_units} > {policy.maximum_primary_verse_units}"
        )
    if failures:
        raise EvidenceLimitError(
            f"{operation} routed analysis SFM exceeds governed limits: " + "; ".join(failures),
            affected_scope=scope.label(),
            next_action="Use the automatically generated bounded work-unit plan or narrow the scope.",
            details={"context_budget": telemetry, "policy": policy.to_dict()},
        )


def _enforce_rtc_sizing(
    config: EcosystemConfig,
    measurement: Mapping[str, Any],
    *,
    workflow: str,
    operation: str,
    rtc_stage: str | None,
    scope: ScriptureScope,
) -> None:
    """Apply component-aware RTC limits to the exact task-creation projection."""
    if (
        workflow not in {"rtc", "saw"}
        or operation != "rtc"
        or rtc_stage != "REFERENCE_TEXT_COMPARISON"
    ):
        return
    sizing = load_workflow_profile(config, config.workflow(workflow)).require_rtc_sizing()
    sizing.validate_active_provider(
        str(load_llm_settings(config.root).get("selected_provider") or "")
    )
    sizing.enforce_route(measurement, scope=scope.label(), workflow=workflow)


def _bounded_sfm_packet(
    source: Path,
    primary_scope: ScriptureScope,
    destination: Path,
    *,
    primary_references: Sequence[str] | None = None,
    context_references: Sequence[str] = (),
    allow_empty: bool = False,
    text_filter: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Write only bounded Scripture SFM selected by primary scope plus explicit context.

    `text_filter` is applied after coordinate selection (e.g. Hebrew cantillation removal).
    """
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8-sig")
        usj = compile_usfm_text(text, source.name)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValidationError(f"Cannot compile STC Scripture input {source}: {exc}") from exc
    parser_errors = _parser_errors_in_scope(
        text,
        source.name,
        usj,
        _scope_chapters(
            [
                primary_scope,
                *(scope for value in (*(primary_references or ()), *context_references) for scope in parse_scope_set(value)),
            ]
        ),
    )
    if parser_errors:
        raise ValidationError(f"STC input {source.name} has parser errors: {', '.join(parser_errors[:8])}")
    requested_primary = (
        tuple(
            requested
            for value in primary_references
            for requested in parse_scope_set(value)
        )
        if primary_references is not None
        else (primary_scope,)
    )
    requested_context = tuple(
        requested
        for value in context_references
        for requested in parse_scope_set(value)
    )
    requested = (*requested_primary, *requested_context)
    selected: list[dict[str, Any]] = []
    refs: set[VerseRef] = set()
    for unit in parse_usj_units(usj):
        unit_refs = {
            VerseRef(primary_scope.book, int(unit["chapter"]), verse)
            for verse in range(int(unit["verse_start"]), int(unit["verse_end"]) + 1)
        }
        intersection = {ref for ref in unit_refs if any(scope.contains(ref) for scope in requested)}
        if not intersection:
            continue
        if intersection != unit_refs:
            raise ValidationError(
                f"STC bounded evidence cuts through a protected verse bridge in {source.name}",
                code="OL_CORRESPONDENCE_BOUNDARY_SPLIT",
                affected_scope=primary_scope.label(),
            )
        selected.append(unit)
        refs.update(unit_refs)
    if not selected and not allow_empty:
        raise ValidationError(f"STC scope {primary_scope.label()} is absent from {source.name}")
    lines = [f"\\id {primary_scope.book}"]
    if not selected and primary_scope.start_chapter is not None:
        lines.append(f"\\c {primary_scope.start_chapter}")
    current_chapter: int | None = None
    for unit in selected:
        chapter = int(unit["chapter"])
        if chapter != current_chapter:
            current_chapter = chapter
            lines.append(f"\\c {chapter}")
        raw_lines = list(unit.get("lines", []))
        if not raw_lines:
            raise ValidationError(f"Compiled STC unit in {source.name} has no retained SFM lines")
        lines.extend(str(line) for line in raw_lines)
    bounded = "\n".join(lines).rstrip() + "\n"
    if text_filter is not None:
        bounded = text_filter(bounded)
    atomic_write_text(destination, bounded)
    primary_atoms = [
        ref.label()
        for ref in sorted(refs)
        if any(requested.contains(ref) for requested in requested_primary)
    ]
    return {
        "path": destination.name,
        "source_file": source.name,
        "source_sha256": sha256_bytes(raw),
        "packet_sha256": sha256_file(destination),
        "source_format": "SFM",
        "comparison_format": "SFM",
        "scope": primary_scope.label(),
        "primary_references": primary_atoms,
        "routed_references": [ref.label() for ref in sorted(refs)],
        "serialized_bytes": measure_sfm_text(bounded).serialized_bytes,
        "estimated_tokens": measure_sfm_text(bounded).estimated_tokens,
    }


def _copy_ol_authority_profile(
    ol_project: ProjectSpec,
    family: str,
    destination: Path,
) -> dict[str, Any]:
    """Validate and copy the complete source-bound OL authority profile into one task."""
    source = ol_project.path / OL_AUTHORITY_PROFILE_FILE
    if ol_project.external and source.is_file():
        source = validate_external_companion_file(
            source,
            roots=(ol_project.path,),
            allowed_filenames=(OL_AUTHORITY_PROFILE_FILE,),
        )
    if not source.is_file():
        raise ValidationError(
            f"Original-language authority {ol_project.project_id} has no authority-profile.yml",
            code="OL_AUTHORITY_PROFILE_MISSING",
            next_action="Bind a governed OL authority profile to the exact GRK/HEB resource before model handoff.",
        )
    raw = load_yaml(source)
    profile = raw.get("profile") if isinstance(raw, dict) else None
    language_identity = raw.get("language_identity") if isinstance(raw, dict) else None
    if not isinstance(profile, dict) or str(profile.get("type", "")).upper() != "OL_AUTHORITY_PROFILE":
        raise ValidationError("OL authority profile has invalid profile.type", code="OL_AUTHORITY_PROFILE_INVALID")
    if str(profile.get("authority_family", "")).upper() != family:
        raise ValidationError("OL authority profile family does not match routed Scripture", code="OL_AUTHORITY_PROFILE_INVALID")
    if not isinstance(language_identity, dict) or not str(language_identity.get("historical_register", "")).strip():
        raise ValidationError("OL authority profile lacks historical language/register specificity", code="OL_AUTHORITY_PROFILE_INVALID")
    exclusion = language_identity.get("modern_language_exclusion")
    if not isinstance(exclusion, dict) or not str(exclusion.get("instruction", "")).strip():
        raise ValidationError("OL authority profile lacks the modern-language exclusion rule", code="OL_AUTHORITY_PROFILE_INVALID")
    atomic_write_bytes(destination, source.read_bytes())
    return {
        "profile_class": "OL_AUTHORITY_PROFILE",
        "authority_family": family,
        "authority_id": str(profile.get("authority_id") or family),
        "authority_role": str(profile.get("applies_to_role") or "PRIMARY"),
        "language": str(language_identity.get("canonical_name") or ""),
        "historical_register": str(language_identity.get("historical_register") or ""),
        "path": _relative(destination.parents[3] if False else destination.parent, destination) if False else destination.name,
        "sha256": sha256_file(destination),
    }

