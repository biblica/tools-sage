"""Discourse-first SAW RTC planning from routed WIP+Reference SFM only."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .canon import PROTESTANT_66
from .errors import ConfigurationError, EvidenceLimitError, ValidationError
from .evidence import EvidenceMeasurement, EvidencePolicy, RTCSizingPolicy
from .references import expand_reference_atoms
from .sfm_slicer import SfmAnalysisRoute, SfmStream, measure_sfm_slice, plan_sfm_work_units
from .work_units import EvidenceRecord, WorkUnit
from .vrs import VerseRef


RTC_PLANNER_VERSION = "SAGE_RTC_SFM_ROUTE_PLANNER_V3"
RTC_HANDOFF_CONTRACT_VERSION = "SAGE_GOVERNED_TASK_V1"
RTC_PROMPT_SCHEMA_PROJECTION_VERSION = "SAW_RTC_REFERENCE_TEXT_COMPARISON_V1"
RTC_ESTIMATOR = "SAGE_MULTILINGUAL_HEURISTIC_1"


def vrs_source_equivalence_spans(
    effective_vrs: Mapping[str, Any],
    *,
    requested_book: str,
) -> tuple[tuple[VerseRef, ...], ...]:
    """Return in-scope local coordinate groups that an effective VRS keeps indivisible."""
    requested_book = str(requested_book).strip().upper()
    if len(requested_book) != 3 or requested_book not in PROTESTANT_66:
        raise ValidationError(
            "RTC planning requires a three-character Paratext/USFM book ID from "
            f"the Protestant 66-book canon; received {requested_book!r}",
            code="RTC_CANONICAL_BOOK_ID_REQUIRED",
            next_action="Use a canonical book ID such as JHN; extended-canon IDs are not supported.",
        )
    spans: list[tuple[VerseRef, ...]] = []
    for value in effective_vrs.get("mappings", []):
        if not isinstance(value, Mapping):
            continue
        local = str(value.get("local") or "").strip()
        if not local:
            continue
        local_book = local.split(maxsplit=1)[0].upper()
        if local_book != requested_book:
            continue
        refs = expand_reference_atoms(local)
        if len(refs) > 1:
            spans.append(refs)
    return tuple(spans)


def rtc_slicing_policy(base: EvidencePolicy, sizing: RTCSizingPolicy) -> EvidencePolicy:
    """Derive RTC soft WIP targets and hard routed-SFM review-item limits."""
    if sizing.estimator != RTC_ESTIMATOR:
        raise ConfigurationError(
            f"Unsupported SAW RTC estimator {sizing.estimator!r}; expected {RTC_ESTIMATOR}"
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


def _measure_review_item(
    unit: WorkUnit,
    reference_records: tuple[EvidenceRecord, ...],
) -> dict[str, Any]:
    """Persist WIP, Reference, and combined review-item SFM measurements for audit/UI."""
    reference_primary = _records_for_refs(reference_records, unit.primary_refs)
    covered = frozenset(ref for record in reference_primary for ref in record.refs)
    if covered != unit.primary_refs:
        missing = sorted(unit.primary_refs - covered)
        raise ValidationError(
            "SAW RTC REFERENCE does not cover the complete WIP slice: "
            + ", ".join(ref.label() for ref in missing),
            code="SAW_RTC_REFERENCE_RANGE_INCOMPLETE",
            affected_scope=unit.primary[0].reference if unit.primary else None,
            next_action="Correct the bound REFERENCE/VRS resource before rebuilding the RTC plan.",
        )
    wip_records = tuple(sorted(
        (*unit.context_before, *unit.primary, *unit.context_after),
        key=lambda item: (item.chapter, item.verse_start, item.verse_end),
    ))
    reference_slice = _unit_component(unit, reference_records)
    wip_measurement = measure_sfm_slice(wip_records)
    reference_measurement = measure_sfm_slice(reference_slice)
    return {
        "projection": RTC_PLANNER_VERSION,
        "sizing_basis": "ROUTED_SFM_ONLY",
        "analysis_route": "REFERENCE_TEXT_COMPARISON",
        "primary_coverage_atoms": [ref.label() for ref in sorted(unit.primary_refs)],
        "source_spans": {
            "WIP": [record.reference for record in unit.primary],
            "REFERENCE": [record.reference for record in reference_primary],
        },
        "wip": _component(wip_measurement),
        "ref": _component(reference_measurement),
        "route": _component(unit.measurement),
    }


def _required_spans(records: Iterable[EvidenceRecord]) -> tuple[tuple[VerseRef, ...], ...]:
    """Return bridged source spans that RTC boundaries must preserve intact."""
    return tuple(record.refs for record in records if len(record.refs) > 1)


def plan_rtc_work_units(
    wip_records: Iterable[EvidenceRecord],
    base_policy: EvidencePolicy,
    sizing: RTCSizingPolicy,
    *,
    unit_prefix: str,
    shared: dict[str, Any],
    wip_context_pool: Iterable[EvidenceRecord],
    reference_records: Iterable[EvidenceRecord],
    wip_equivalence_spans: Iterable[Iterable[VerseRef]] = (),
    reference_equivalence_spans: Iterable[Iterable[VerseRef]] = (),
) -> tuple[tuple[WorkUnit, ...], tuple[dict[str, Any], ...], EvidencePolicy]:
    """Plan RTC from actual WIP+Reference SFM while retaining WIP soft-target behavior."""
    del shared  # Controller metadata is deliberately absent from review-item sizing.
    selected = tuple(wip_records)
    context = tuple(wip_context_pool)
    reference = tuple(reference_records)
    policy = rtc_slicing_policy(base_policy, sizing)
    required_spans = (
        _required_spans(selected)
        + _required_spans(reference)
        + tuple(tuple(span) for span in wip_equivalence_spans)
        + tuple(tuple(span) for span in reference_equivalence_spans)
    )
    route = SfmAnalysisRoute(
        route_id="REFERENCE_TEXT_COMPARISON",
        streams=(
            SfmStream("WIP", context),
            SfmStream("REFERENCE", reference),
        ),
        target_stream_ids=("WIP",),
        stream_hard_token_limits=(("WIP", sizing.wip_hard_exclusive_tokens - 1),),
    )
    try:
        units = plan_sfm_work_units(
            selected,
            policy,
            unit_prefix=unit_prefix,
            route=route,
            context_pool=context,
            required_spans=required_spans,
        )
    except EvidenceLimitError as exc:
        code = "SAW_RTC_UNSPLITTABLE_BRIDGE" if exc.code == "WORK_UNIT_REQUIRED_SPAN_EXCEEDS_LIMIT" else "SAW_RTC_UNSPLITTABLE_WIP"
        raise EvidenceLimitError(
            "SAW RTC cannot preserve the routed WIP+REFERENCE SFM review item within governed limits",
            code=code,
            affected_scope=exc.affected_scope,
            next_action="Narrow the scope or correct the oversized indivisible Scripture span.",
            details=exc.details,
        ) from exc
    packages = tuple(_measure_review_item(unit, reference) for unit in units)
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
