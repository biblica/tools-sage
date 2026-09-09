"""Discourse-first RTC planning from routed WIP+Reference SFM only."""

from __future__ import annotations

from typing import Any, Iterable

from .canon import PROTESTANT_66
from .errors import ConfigurationError, EvidenceLimitError, ValidationError
from .evidence import EvidenceMeasurement, EvidencePolicy, RTCSizingPolicy
from .sfm_slicer import SfmAnalysisRoute, SfmStream, measure_sfm_slice, plan_sfm_work_units
from .source_coverage import source_text_issues
from .verse_alignment import ProjectVerseIndex
from .work_units import EvidenceRecord, WorkUnit
from .vrs import VerseRef


RTC_PLANNER_VERSION = "SAGE_RTC_SFM_ROUTE_PLANNER_V5"
LEGACY_RTC_PLANNER_VERSION = "SAGE_RTC_SFM_ROUTE_PLANNER_V4"
RTC_HANDOFF_CONTRACT_VERSION = "SAGE_GOVERNED_TASK_V1"
RTC_PROMPT_SCHEMA_PROJECTION_VERSION = "RTC_REFERENCE_TEXT_COMPARISON_V1"
LEGACY_RTC_PROMPT_SCHEMA_PROJECTION_VERSION = "SAW_RTC_REFERENCE_TEXT_COMPARISON_V1"
RTC_ESTIMATOR = "SAGE_MULTILINGUAL_HEURISTIC_1"


def rtc_prompt_schema_projection_version(workflow: str) -> str:
    """Return the current projection version or its sealed legacy identity."""
    return (
        LEGACY_RTC_PROMPT_SCHEMA_PROJECTION_VERSION
        if str(workflow).strip().lower() == "saw"
        else RTC_PROMPT_SCHEMA_PROJECTION_VERSION
    )


def _validate_rtc_book(records: tuple[EvidenceRecord, ...]) -> None:
    """Require RTC primary evidence from one Protestant-canon Paratext book."""
    books = {record.book.strip().upper() for record in records}
    if len(books) != 1 or next(iter(books), "") not in PROTESTANT_66:
        rendered = ", ".join(sorted(books)) or "NONE"
        raise ValidationError(
            "RTC planning requires a three-character Paratext/USFM book ID from "
            f"the Protestant 66-book canon; received {rendered!r}",
            code="RTC_CANONICAL_BOOK_ID_REQUIRED",
            next_action="Use a canonical book ID such as JHN; extended-canon IDs are not supported.",
        )


def rtc_slicing_policy(base: EvidencePolicy, sizing: RTCSizingPolicy) -> EvidencePolicy:
    """Derive RTC soft WIP targets and hard routed-SFM review-item limits."""
    if sizing.estimator != RTC_ESTIMATOR:
        raise ConfigurationError(
            f"Unsupported RTC estimator {sizing.estimator!r}; expected {RTC_ESTIMATOR}"
        )
    route_hard = min(base.hard_estimated_tokens, sizing.route_hard_max_tokens)
    target = min(sizing.wip_target_min_tokens, max(1, route_hard - 1))
    preferred = min(sizing.wip_target_max_tokens, route_hard)
    return EvidencePolicy(
        target_estimated_tokens=target,
        hard_estimated_tokens=route_hard,
        hard_serialized_bytes=min(base.hard_serialized_bytes, sizing.route_hard_serialized_bytes),
        minimum_target_tokens=min(max(1, sizing.wip_target_min_tokens - 1000), target),
        preferred_max_estimated_tokens=max(target, preferred),
        maximum_primary_verse_units=min(base.maximum_primary_verse_units, 80),
        context_before_verses=base.context_before_verses,
        context_after_verses=base.context_after_verses,
        allow_cross_chapter_units=base.allow_cross_chapter_units,
        maximum_primary_discourse_units=base.maximum_primary_discourse_units,
        preferred_primary_discourse_units=base.preferred_primary_discourse_units,
    )


def _records_for_refs(
    records: Iterable[EvidenceRecord], refs: frozenset[VerseRef]
) -> tuple[EvidenceRecord, ...]:
    """Select source records intersecting the requested canonical coordinate set."""
    return tuple(record for record in records if refs.intersection(record.refs))


def _component(measurement: EvidenceMeasurement) -> dict[str, Any]:
    """Render one routed-SFM measurement component for RTC audit and operator display."""
    return {
        "estimator": RTC_ESTIMATOR,
        "estimated_tokens": measurement.estimated_tokens,
        "serialized_bytes": measurement.serialized_bytes,
        "basis": "ROUTED_SFM_ONLY",
    }


def _unit_component(unit: WorkUnit, records: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
    """Select all primary and routed-context records belonging to one RTC work unit."""
    refs = frozenset((*unit.primary_refs, *unit.context_refs))
    return _records_for_refs(records, refs)


def _indexed_records_for_canonical(
    records: tuple[EvidenceRecord, ...],
    index: ProjectVerseIndex,
    refs: frozenset[VerseRef],
) -> tuple[EvidenceRecord, ...]:
    """Select canonical matches without expanding beyond the routed record inventory."""
    return tuple(
        record
        for record in index.records_for_canonical(refs)
        if record in records
    )


def _rtc_planner_version(
    requested: str | None,
    wip_index: ProjectVerseIndex | None,
    reference_index: ProjectVerseIndex | None,
) -> str:
    """Resolve current indexed planning or the exact sealed V4 compatibility path."""
    version = str(requested or "").strip()
    if not version:
        version = (
            RTC_PLANNER_VERSION
            if wip_index is not None and reference_index is not None
            else LEGACY_RTC_PLANNER_VERSION
        )
    if version not in {RTC_PLANNER_VERSION, LEGACY_RTC_PLANNER_VERSION}:
        raise ValidationError(
            f"Unsupported RTC planner version: {version}",
            code="RTC_PLANNER_VERSION_UNSUPPORTED",
        )
    if version == RTC_PLANNER_VERSION and (
        wip_index is None or reference_index is None
    ):
        raise ValidationError(
            "RTC V5 planning requires WIP and REFERENCE Project verse indexes",
            code="RTC_VRS_INDEX_REQUIRED",
        )
    return version


def _canonical_source_text_issues(
    unit: WorkUnit,
    wip_index: ProjectVerseIndex,
    missing_canonical: frozenset[VerseRef],
) -> list[dict[str, Any]]:
    """Attach canonical gaps to the corresponding WIP-local completion coordinates."""
    missing_local: set[VerseRef] = set()
    canonical_by_local: dict[VerseRef, set[VerseRef]] = {}
    for record in unit.primary:
        record_canonical = wip_index.canonical_refs_for_records((record,))
        record_missing = record_canonical.intersection(missing_canonical)
        if not record_missing:
            continue
        for local_ref in record.refs:
            missing_local.add(local_ref)
            canonical_by_local.setdefault(local_ref, set()).update(record_missing)
    issues = list(source_text_issues(
        missing_local,
        (),
        workflow="RTC",
        source_stream="REFERENCE",
        scope=str(unit.to_dict()["primary_scope"]),
    ))
    for issue in issues:
        local_ref = next(
            ref for ref in missing_local if ref.label() == issue["reference"]
        )
        issue["canonical_references"] = [
            ref.label() for ref in sorted(canonical_by_local[local_ref])
        ]
    return issues


def _measure_review_item(
    unit: WorkUnit,
    reference_records: tuple[EvidenceRecord, ...],
    *,
    planner_version: str,
    wip_index: ProjectVerseIndex | None,
    reference_index: ProjectVerseIndex | None,
) -> dict[str, Any]:
    """Persist WIP, Reference, and combined review-item SFM measurements for audit/UI."""
    primary_scope = str(unit.to_dict()["primary_scope"])
    wip_records = tuple(sorted(
        (*unit.context_before, *unit.primary, *unit.context_after),
        key=lambda item: (item.chapter, item.verse_start, item.verse_end),
    ))
    if planner_version == RTC_PLANNER_VERSION:
        assert wip_index is not None and reference_index is not None
        primary_canonical = wip_index.canonical_refs_for_records(unit.primary)
        routed_canonical = wip_index.canonical_refs_for_records(wip_records)
        reference_primary = _indexed_records_for_canonical(
            reference_records,
            reference_index,
            primary_canonical,
        )
        reference_slice = _indexed_records_for_canonical(
            reference_records,
            reference_index,
            routed_canonical,
        )
        covered = reference_index.canonical_refs_for_records(reference_primary)
        missing_canonical = primary_canonical.difference(covered)
        issues = _canonical_source_text_issues(
            unit,
            wip_index,
            missing_canonical,
        )
    else:
        reference_primary = _records_for_refs(reference_records, unit.primary_refs)
        reference_slice = _unit_component(unit, reference_records)
        covered = frozenset(ref for record in reference_primary for ref in record.refs)
        primary_canonical = frozenset(unit.primary_refs)
        missing_canonical = primary_canonical.difference(covered)
        issues = list(source_text_issues(
            unit.primary_refs,
            covered,
            workflow="RTC",
            source_stream="REFERENCE",
            scope=primary_scope,
        ))
    wip_measurement = measure_sfm_slice(wip_records)
    reference_measurement = measure_sfm_slice(reference_slice)
    package = {
        "projection": planner_version,
        "sizing_basis": "ROUTED_SFM_ONLY",
        "analysis_route": "REFERENCE_TEXT_COMPARISON",
        "primary_coverage_atoms": [ref.label() for ref in sorted(unit.primary_refs)],
        "source_spans": {
            "WIP": [record.reference for record in unit.primary],
            "REFERENCE": [record.reference for record in reference_primary],
        },
        "source_text_issues": issues,
        "wip": _component(wip_measurement),
        "ref": _component(reference_measurement),
        "route": _component(unit.measurement),
    }
    if planner_version == RTC_PLANNER_VERSION:
        package["alignment"] = {
            "primary_local_atoms": [ref.label() for ref in sorted(unit.primary_refs)],
            "canonical_atoms": [ref.label() for ref in sorted(primary_canonical)],
            "reference_local_spans": [record.reference for record in reference_primary],
            "missing_canonical_atoms": [
                ref.label() for ref in sorted(missing_canonical)
            ],
        }
    return package


def plan_rtc_work_units(
    wip_records: Iterable[EvidenceRecord],
    base_policy: EvidencePolicy,
    sizing: RTCSizingPolicy,
    *,
    unit_prefix: str,
    shared: dict[str, Any],
    wip_context_pool: Iterable[EvidenceRecord],
    reference_records: Iterable[EvidenceRecord],
    wip_index: ProjectVerseIndex | None = None,
    reference_index: ProjectVerseIndex | None = None,
    workflow: str = "rtc",
    planner_version: str | None = None,
) -> tuple[tuple[WorkUnit, ...], tuple[dict[str, Any], ...], EvidencePolicy]:
    """Plan RTC from actual WIP+Reference SFM while retaining WIP soft-target behavior."""
    del shared  # Controller metadata is deliberately absent from review-item sizing.
    selected = tuple(wip_records)
    context = tuple(wip_context_pool)
    reference = tuple(reference_records)
    version = _rtc_planner_version(planner_version, wip_index, reference_index)
    _validate_rtc_book(selected)
    policy = rtc_slicing_policy(base_policy, sizing)
    indexed = version == RTC_PLANNER_VERSION
    route = SfmAnalysisRoute(
        route_id="REFERENCE_TEXT_COMPARISON",
        streams=(
            SfmStream("WIP", context, verse_index=wip_index if indexed else None),
            SfmStream(
                "REFERENCE",
                reference,
                require_primary_coverage=False,
                verse_index=reference_index if indexed else None,
            ),
        ),
        target_stream_ids=("WIP",),
        stream_hard_token_limits=(("WIP", sizing.wip_hard_exclusive_tokens - 1),),
        primary_stream_id="WIP" if indexed else None,
        primary_index=wip_index if indexed else None,
    )
    try:
        units = plan_sfm_work_units(
            selected,
            policy,
            unit_prefix=unit_prefix,
            route=route,
            context_pool=context,
        )
    except EvidenceLimitError as exc:
        prefix = "SAW_RTC" if str(workflow).strip().lower() == "saw" else "RTC"
        code = (
            f"{prefix}_UNSPLITTABLE_BRIDGE"
            if exc.code == "WORK_UNIT_REQUIRED_SPAN_EXCEEDS_LIMIT"
            else f"{prefix}_UNSPLITTABLE_WIP"
        )
        raise EvidenceLimitError(
            "RTC cannot preserve the routed WIP+REFERENCE SFM review item within governed limits",
            code=code,
            affected_scope=exc.affected_scope,
            next_action="Narrow the scope or correct the oversized indivisible Scripture span.",
            details=exc.details,
        ) from exc
    packages = tuple(
        _measure_review_item(
            unit,
            reference,
            planner_version=version,
            wip_index=wip_index,
            reference_index=reference_index,
        )
        for unit in units
    )
    return units, packages, policy


def package_summary(packages: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return review-item SFM maxima for operator plan display."""
    values = tuple(packages)
    return {
        "largest_wip_estimated_tokens": max((int(item["wip"]["estimated_tokens"]) for item in values), default=0),
        "largest_ref_estimated_tokens": max((int(item["ref"]["estimated_tokens"]) for item in values), default=0),
        "largest_route_estimated_tokens": max((int(item["route"]["estimated_tokens"]) for item in values), default=0),
        "largest_route_serialized_bytes": max((int(item["route"]["serialized_bytes"]) for item in values), default=0),
        "sizing_basis": "ROUTED_SFM_ONLY",
    }
