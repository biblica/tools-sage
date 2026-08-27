"""Complete-package sizing for discourse-first SAW Reference Text Comparison plans."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Iterable

from .errors import ConfigurationError, EvidenceLimitError, ValidationError
from .evidence import EvidenceMeasurement, EvidencePolicy, RTCSizingPolicy, measure_evidence
from .work_units import EvidenceRecord, WorkUnit, build_evidence_packet, plan_work_units
from .vrs import VerseRef


RTC_PLANNER_VERSION = "SAGE_RTC_PACKAGE_PLANNER_V1"
RTC_HANDOFF_CONTRACT_VERSION = "SAGE_GOVERNED_TASK_V1"
RTC_PROMPT_SCHEMA_PROJECTION_VERSION = "SAW_RTC_REFERENCE_TEXT_COMPARISON_V1"
RTC_ESTIMATOR = "SAGE_MULTILINGUAL_HEURISTIC_1"


def rtc_slicing_policy(base: EvidencePolicy, sizing: RTCSizingPolicy) -> EvidencePolicy:
    """Derive the WIP-only boundary policy from the validated RTC sizing contract."""
    if sizing.estimator != RTC_ESTIMATOR:
        raise ConfigurationError(
            f"Unsupported SAW RTC estimator {sizing.estimator!r}; expected {RTC_ESTIMATOR}"
        )
    return EvidencePolicy(
        target_estimated_tokens=sizing.wip_target_min_tokens,
        hard_estimated_tokens=sizing.wip_hard_exclusive_tokens - 1,
        hard_serialized_bytes=min(
            base.hard_serialized_bytes,
            sizing.package_hard_serialized_bytes
            - sizing.minimum_overhead_serialized_bytes,
        ),
        minimum_target_tokens=max(1, sizing.wip_target_min_tokens - 1000),
        preferred_max_estimated_tokens=sizing.wip_target_max_tokens,
        maximum_primary_verse_units=min(base.maximum_primary_verse_units, 80),
        context_before_verses=base.context_before_verses,
        context_after_verses=base.context_after_verses,
        allow_cross_chapter_units=base.allow_cross_chapter_units,
        maximum_primary_discourse_units=base.maximum_primary_discourse_units,
        preferred_primary_discourse_units=base.preferred_primary_discourse_units,
    )


def _records_for_refs(
    records: Iterable[EvidenceRecord],
    refs: frozenset[VerseRef],
) -> tuple[EvidenceRecord, ...]:
    """Return ordered records intersecting an exact WIP-derived coordinate inventory."""
    return tuple(record for record in records if refs.intersection(record.refs))


def _component_packet(
    records: tuple[EvidenceRecord, ...],
    before: tuple[EvidenceRecord, ...],
    after: tuple[EvidenceRecord, ...],
    *,
    evidence_id: str,
) -> dict[str, Any]:
    """Build the deterministic component projection used for pre-run package sizing."""
    return {
        "projection": RTC_PLANNER_VERSION,
        "evidence_id": evidence_id,
        "primary": [
            {"reference": item.reference, "context_only": False, "evidence": item.payload}
            for item in records
        ],
        "context_before": [
            {"reference": item.reference, "context_only": True, "evidence": item.payload}
            for item in before
        ],
        "context_after": [
            {"reference": item.reference, "context_only": True, "evidence": item.payload}
            for item in after
        ],
    }


def _component(measurement: EvidenceMeasurement) -> dict[str, Any]:
    """Serialize one RTC component measurement for plan persistence and display."""
    return {
        "estimator": RTC_ESTIMATOR,
        "estimated_tokens": measurement.estimated_tokens,
        "serialized_bytes": measurement.serialized_bytes,
    }


def _measure_package(
    unit: WorkUnit,
    reference_records: tuple[EvidenceRecord, ...],
    sizing: RTCSizingPolicy,
) -> dict[str, Any]:
    """Measure WIP and correlated REF, then add the release-governed overhead reserve."""
    primary_refs = unit.primary_refs
    reference_primary = _records_for_refs(reference_records, primary_refs)
    covered_refs = frozenset(ref for record in reference_primary for ref in record.refs)
    missing = sorted(primary_refs - covered_refs)
    if missing:
        raise ValidationError(
            "SAW RTC REFERENCE does not cover the complete WIP slice: "
            + ", ".join(ref.label() for ref in missing),
            code="SAW_RTC_REFERENCE_RANGE_INCOMPLETE",
            affected_scope=unit.primary[0].reference if unit.primary else None,
            next_action="Correct the bound REFERENCE/VRS resource before rebuilding the RTC plan.",
        )
    before_refs = frozenset(ref for record in unit.context_before for ref in record.refs)
    after_refs = frozenset(ref for record in unit.context_after for ref in record.refs)
    reference_before = _records_for_refs(reference_records, before_refs)
    reference_after = _records_for_refs(reference_records, after_refs)

    # The WIP component deliberately excludes shared planning metadata. That metadata,
    # prompt, schema, indexes, grammar and serialization are represented by OH.
    wip_measurement = measure_evidence(build_evidence_packet(unit, {}))
    reference_measurement = measure_evidence(
        _component_packet(
            reference_primary,
            reference_before,
            reference_after,
            evidence_id="REFERENCE",
        )
    )
    overhead = {
        "estimator": RTC_ESTIMATOR,
        "estimated_tokens": sizing.minimum_overhead_reserve_tokens,
        "serialized_bytes": sizing.minimum_overhead_serialized_bytes,
        "basis": "RELEASE_GOVERNED_MINIMUM_RESERVE",
    }
    pack_tokens = (
        wip_measurement.estimated_tokens
        + reference_measurement.estimated_tokens
        + overhead["estimated_tokens"]
    )
    pack_bytes = (
        wip_measurement.serialized_bytes
        + reference_measurement.serialized_bytes
        + overhead["serialized_bytes"]
    )
    return {
        "projection": RTC_PLANNER_VERSION,
        "wip": _component(wip_measurement),
        "ref": _component(reference_measurement),
        "oh": overhead,
        "pack": {
            "estimator": RTC_ESTIMATOR,
            "estimated_tokens": pack_tokens,
            "serialized_bytes": pack_bytes,
        },
    }


def _package_failures(package: dict[str, Any], sizing: RTCSizingPolicy) -> list[str]:
    """Return every hard-limit violation in one completed planning projection."""
    wip_tokens = int(package["wip"]["estimated_tokens"])
    pack_tokens = int(package["pack"]["estimated_tokens"])
    pack_bytes = int(package["pack"]["serialized_bytes"])
    failures: list[str] = []
    if wip_tokens >= sizing.wip_hard_exclusive_tokens:
        failures.append(
            f"WIP {wip_tokens} >= {sizing.wip_hard_exclusive_tokens}"
        )
    if pack_tokens > sizing.package_hard_max_tokens:
        failures.append(f"PACK {pack_tokens} > {sizing.package_hard_max_tokens}")
    if pack_tokens > sizing.provider_handoff_max_tokens:
        failures.append(
            f"provider PACK {pack_tokens} > {sizing.provider_handoff_max_tokens}"
        )
    if pack_bytes > sizing.package_hard_serialized_bytes:
        failures.append(
            f"PACK bytes {pack_bytes} > {sizing.package_hard_serialized_bytes}"
        )
    return failures


def _smaller_policy(
    policy: EvidencePolicy,
    packages: tuple[dict[str, Any], ...],
    sizing: RTCSizingPolicy,
) -> EvidencePolicy:
    """Reduce the WIP ceiling deterministically when a correlated package is oversized."""
    ratios: list[float] = []
    for package in packages:
        pack = package["pack"]
        tokens = int(pack["estimated_tokens"])
        size = int(pack["serialized_bytes"])
        if tokens > sizing.package_hard_max_tokens:
            ratios.append(sizing.package_hard_max_tokens / tokens)
        if tokens > sizing.provider_handoff_max_tokens:
            ratios.append(sizing.provider_handoff_max_tokens / tokens)
        if size > sizing.package_hard_serialized_bytes:
            ratios.append(sizing.package_hard_serialized_bytes / size)
        if int(package["wip"]["estimated_tokens"]) >= sizing.wip_hard_exclusive_tokens:
            ratios.append(
                (sizing.wip_hard_exclusive_tokens - 1)
                / int(package["wip"]["estimated_tokens"])
            )
    ratio = min(ratios, default=0.8)
    new_hard = min(policy.hard_estimated_tokens - 1, math.floor(policy.hard_estimated_tokens * ratio * 0.92))
    if new_hard < 256:
        raise EvidenceLimitError(
            "SAW RTC cannot reslice the completed package within governed limits",
            code="SAW_RTC_UNSPLITTABLE_PACKAGE",
            next_action="Narrow the operator scope or correct an oversized single-verse WIP/REFERENCE record.",
            details={"packages": list(packages), "rtc_sizing": sizing.to_dict()},
        )
    new_target = min(sizing.wip_target_min_tokens, max(1, new_hard * 3 // 4))
    return replace(
        policy,
        target_estimated_tokens=new_target,
        hard_estimated_tokens=new_hard,
        minimum_target_tokens=min(policy.minimum_target_tokens, new_target),
        preferred_max_estimated_tokens=min(sizing.wip_target_max_tokens, new_hard),
    )


def plan_rtc_work_units(
    wip_records: Iterable[EvidenceRecord],
    base_policy: EvidencePolicy,
    sizing: RTCSizingPolicy,
    *,
    unit_prefix: str,
    shared: dict[str, Any],
    wip_context_pool: Iterable[EvidenceRecord],
    reference_records: Iterable[EvidenceRecord],
) -> tuple[tuple[WorkUnit, ...], tuple[dict[str, Any], ...], EvidencePolicy]:
    """Plan WIP boundaries, correlate REF, validate PACK, and reslice when required."""
    selected = tuple(wip_records)
    context = tuple(wip_context_pool)
    reference = tuple(reference_records)
    policy = rtc_slicing_policy(base_policy, sizing)
    for _attempt in range(12):
        try:
            units = plan_work_units(
                selected,
                policy,
                unit_prefix=unit_prefix,
                shared=shared,
                context_pool=context,
            )
        except EvidenceLimitError as exc:
            raise EvidenceLimitError(
                f"SAW RTC WIP cannot be split below its exclusive hard maximum: {exc.message}",
                code="SAW_RTC_UNSPLITTABLE_WIP",
                next_action="Narrow the scope or resolve the oversized single-verse record.",
            ) from exc
        packages = tuple(_measure_package(unit, reference, sizing) for unit in units)
        if not any(_package_failures(package, sizing) for package in packages):
            return units, packages, policy
        if all(len(unit.primary) == 1 for unit, package in zip(units, packages, strict=True) if _package_failures(package, sizing)):
            raise EvidenceLimitError(
                "A single-verse SAW RTC package exceeds governed WIP or complete-package limits",
                code="SAW_RTC_UNSPLITTABLE_PACKAGE",
                next_action="Narrow the scope or resolve the oversized WIP/REFERENCE verse record.",
                details={"packages": list(packages), "rtc_sizing": sizing.to_dict()},
            )
        policy = _smaller_policy(policy, packages, sizing)
    raise EvidenceLimitError(
        "SAW RTC package reslicing did not converge within the governed iteration limit",
        code="SAW_RTC_RESLICE_DID_NOT_CONVERGE",
        next_action="Narrow the operator scope and rebuild the RTC plan.",
    )


def package_summary(packages: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return component maxima for the operator plan and approval manifest."""
    values = tuple(packages)
    return {
        "largest_wip_estimated_tokens": max(
            (int(item["wip"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_ref_estimated_tokens": max(
            (int(item["ref"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_oh_estimated_tokens": max(
            (int(item["oh"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_pack_estimated_tokens": max(
            (int(item["pack"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_pack_serialized_bytes": max(
            (int(item["pack"]["serialized_bytes"]) for item in values), default=0
        ),
    }
