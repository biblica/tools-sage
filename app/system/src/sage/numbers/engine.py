"""Compose bounded NCA evidence into independent accuracy, note, and style results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from sage.coverage import assess_coverage
from sage.errors import ValidationError
from sage.findings import assign_global_finding_ids

from .compare import compare_expressions
from .footnotes import assess_footnote, footnote_recommendation
from .model_tasks import CorrespondenceEvidence
from .models import (
    Extraction,
    FootnoteDecision,
    NumericExpression,
    ProjectedUnit,
    ReadingDecision,
    ReferenceBundle,
    ReferenceRow,
    RunResult,
    SemanticDecision,
    TargetUnit,
    UnitResult,
)
from .reference import parse_values
from .style import _assess_prepared_style, validate_style_profile
from .execution import ExecutionInputs, reference_restrictions
from .units import compare_registered_units, parse_registered_quantity
from .variants import select_reading


_CHECKS = frozenset(
    {"number_accuracy", "presentation_consistency", "footnote_review"}
)
_PASS_OUTCOMES = frozenset(
    {
        "PASS_AUTHORITY1",
        "PASS_EQUIVALENT_NUMERIC_EXPRESSION",
        "PASS_UNIT_CONVERSION",
        "NO_CONFIGURED_OL_READING",
    }
)


def _checks(policy: Mapping[str, object]) -> Mapping[str, bool]:
    """Return the exact enabled-check snapshot or reject an ambiguous policy."""
    checks = policy.get("checks") if isinstance(policy, Mapping) else None
    if (
        not isinstance(checks, Mapping)
        or set(checks) != _CHECKS
        or any(type(checks[name]) is not bool for name in _CHECKS)
        or not any(checks.values())
    ):
        raise ValidationError(
            "NCA requires the exact three-check policy with at least one enabled check.",
            code="NCA_CHECK_POLICY_INVALID",
        )
    return checks


def _unsupported_reading(reason: str) -> ReadingDecision:
    """Build an explicit unsupported reading without inventing interpretation evidence."""
    return ReadingDecision(
        "UNSUPPORTED",
        SemanticDecision("INSUFFICIENT_EVIDENCE", reason_codes=(reason,)),
        "NONE",
        None,
        (),
    )


def _not_assessed_reading() -> ReadingDecision:
    """Build the neutral state used when only presentation was selected."""
    return ReadingDecision(
        "UNASSESSED", SemanticDecision("NOT_ASSESSED"), "NONE", None, ()
    )


def _style_location(unit: ProjectedUnit) -> str:
    """Distinguish a Task 2 heading stream from an ordinary target body stream."""
    return "heading" if unit.target.source_locator.get("heading") == 1 else "body"


def _flat_values(extraction: Extraction) -> tuple[object, ...]:
    """Flatten exact target values while preserving expression and range order."""
    return tuple(value for item in extraction.expressions for value in item.values)


def _source_ids(record: Mapping[str, object]) -> list[str]:
    """Read the registry's semicolon-delimited evidence identifiers exactly once."""
    return [part.strip() for part in str(record.get("SOURCE_IDS", "")).split(";") if part.strip()]


def _reading_context(
    row: ReferenceRow,
    extraction: Extraction,
    bundle: ReferenceBundle,
) -> tuple[Mapping[str, object] | None, str | None]:
    """Authorize only an exact registered alternate or unit example for interpretation."""
    values = _flat_values(extraction)
    if values == row.ol_values:
        return None, None
    variant = bundle.variants.get(row.western_reference)
    guidance = bundle.footnote_guidance.get(row.western_reference)
    if variant is not None and guidance is not None:
        expected = parse_values(str(variant.get("NIV_VALUE_RESEARCHED", "")))
        guided = parse_values(str(guidance.get("ALT_NIV_VALUES", "")))
        if values == expected == guided:
            source_ids = _source_ids(guidance)
            if source_ids:
                return {
                    "registry_id": row.western_reference.label(),
                    "reading_id": "ALT",
                    "source_ids": source_ids,
                    "text": row.niv_text,
                    "values": [str(value) for value in expected],
                    "policy_outcome": str(
                        guidance.get("VALIDATION_IF_TARGET_FOLLOWS_ALT", "")
                    ),
                }, "ALT"
    record = bundle.units.get(row.western_reference)
    if record is not None:
        try:
            registered = parse_registered_quantity(str(record["NIV_QUANTITY"]))
        except (KeyError, ValidationError):
            registered = ()
        registered_values = tuple(
            value for item in registered for value in item.values
        )
        target_unit_values = tuple(
            value
            for item in extraction.expressions
            if item.unit is not None
            for value in item.values
        )
        source_ids = _source_ids(record)
        if registered and target_unit_values == registered_values and source_ids:
            return {
                "registry_id": row.western_reference.label(),
                "reading_id": "UNIT",
                "source_ids": source_ids,
                "text": str(record["NIV_QUANTITY"]),
                "values": [str(value) for value in registered_values],
                "policy_outcome": "PASS_UNIT_CONVERSION",
            }, "UNIT"
    return None, None


def _result_reference_context(
    row: ReferenceRow, bundle: ReferenceBundle
) -> Mapping[str, object]:
    """Retain exact OL stream and bounded variant metadata for result evidence."""
    guidance = bundle.footnote_guidance.get(row.western_reference, {})
    return {
        "language": row.language,
        "ol_text": row.ol_text,
        "ol_values": tuple(row.ol_values),
        "variant_class": row.metadata.get("VARIANT_CLASS") or guidance.get("CLASS"),
        "scholarship_status": row.metadata.get("SCHOLARSHIP_STATUS")
        or guidance.get("SCHOLARSHIP_STATUS"),
    }


def _extract(
    unit: ProjectedUnit,
    *,
    language: str,
    style_profile: Mapping[str, object],
    model_tasks: object | None,
) -> Extraction:
    """Run target extraction once or expose the absent model dependency."""
    if model_tasks is None:
        return Extraction((), "UNSUPPORTED", ("MODEL_INTERPRETATION_UNAVAILABLE",))
    try:
        phase = model_tasks.extract(
            unit.target, language=language, style_profile=style_profile
        )
        extraction = phase.value
    except (AttributeError, TypeError, ValidationError):
        return Extraction((), "UNSUPPORTED", ("TARGET_EXTRACTION_UNAVAILABLE",))
    if not isinstance(extraction, Extraction):
        return Extraction((), "UNSUPPORTED", ("TARGET_EXTRACTION_INVALID",))
    return extraction


def _correspond(
    unit: ProjectedUnit,
    extraction: Extraction,
    row: ReferenceRow,
    *,
    context: Mapping[str, object] | None,
    model_tasks: object | None,
) -> CorrespondenceEvidence | None:
    """Run one whole-unit correspondence phase and reject malformed evidence."""
    if model_tasks is None or extraction.status != "COMPLETE":
        return None
    try:
        phase = model_tasks.correspond(
            unit.target, extraction, row, reading_context=context
        )
        evidence = phase.value
    except (AttributeError, TypeError, ValidationError):
        return None
    return evidence if isinstance(evidence, CorrespondenceEvidence) else None


def _identify_reading(
    unit: ProjectedUnit,
    extraction: Extraction,
    row: ReferenceRow,
    *,
    bundle: ReferenceBundle,
    model_tasks: object | None,
) -> tuple[ReadingDecision, tuple[str, ...], tuple[NumericExpression, ...]]:
    """Select a reading only from complete OL and registered correspondence evidence."""
    context, context_kind = _reading_context(row, extraction, bundle)
    evidence = _correspond(
        unit, extraction, row, context=context, model_tasks=model_tasks
    )
    if evidence is None or evidence.status != "COMPLETE":
        limitations = extraction.limitations
        if evidence is not None:
            limitations += evidence.limitations
        return (
            _unsupported_reading("CORRESPONDENCE_INCOMPLETE"),
            limitations,
            evidence.source_expressions if evidence is not None else (),
        )

    target = evidence.target_extraction
    target_values = _flat_values(target)
    if context_kind is None:
        semantic = compare_expressions(
            evidence.source_expressions, target, allow_reordering=True
        )
        reading = select_reading(
            row,
            row.ol_values if semantic.outcome in _PASS_OUTCOMES else target_values,
            bundle=bundle,
            semantic=semantic,
        )
        if semantic.outcome in {"REVIEW_NUMBER_MISSING", "REVIEW_NUMBER_ADDED"}:
            reading = ReadingDecision(
                "UNSUPPORTED",
                semantic,
                "NONE",
                None,
                (),
            )
        return reading, tuple(evidence.limitations), evidence.source_expressions

    if evidence.registered_status != "COMPLETE":
        return (
            _unsupported_reading("REGISTERED_CORRESPONDENCE_INCOMPLETE"),
            tuple(evidence.limitations + evidence.registered_limitations),
            evidence.source_expressions,
        )
    candidate = compare_expressions(evidence.registered_expressions, target)
    if context_kind == "ALT":
        return (
            select_reading(row, target_values, bundle=bundle, semantic=candidate),
            tuple(evidence.limitations + evidence.registered_limitations),
            evidence.source_expressions,
        )

    target_units = Extraction(
        tuple(item for item in target.expressions if item.unit is not None),
        target.status,
        target.limitations,
    )
    candidate = compare_expressions(evidence.registered_expressions, target_units)
    conversion = compare_registered_units(row, target, bundle=bundle)
    residual = _compare_unit_residual(row, evidence.source_expressions, target, bundle)
    for decision in (candidate, conversion, residual):
        if decision.outcome not in _PASS_OUTCOMES:
            conversion = decision
            break
    reading = select_reading(
        row, row.ol_values, bundle=bundle, semantic=conversion
    )
    return (
        reading,
        tuple(evidence.limitations + evidence.registered_limitations),
        evidence.source_expressions,
    )


def _unit_signature(expression: object) -> tuple[object, ...]:
    """Return the registered unit attributes used only to partition OL evidence."""
    return (
        expression.values,
        expression.kind,
        expression.unit,
        expression.qualifier,
    )


def _compare_unit_residual(
    row: ReferenceRow,
    source: tuple[object, ...],
    target: Extraction,
    bundle: ReferenceBundle,
) -> SemanticDecision:
    """Compare every non-converted quantity with full typed OL correspondence."""
    record = bundle.units.get(row.western_reference)
    if record is None:
        return SemanticDecision(
            "INSUFFICIENT_EVIDENCE", reason_codes=("UNIT_CONVERSION_NOT_REGISTERED",)
        )
    try:
        registered_source = parse_registered_quantity(str(record["OL_QUANTITY"]))
    except (KeyError, ValidationError):
        return SemanticDecision(
            "INSUFFICIENT_EVIDENCE", reason_codes=("UNIT_SOURCE_EXAMPLE_UNSUPPORTED",)
        )
    remaining = list(source)
    for expected in registered_source:
        match = next(
            (
                index
                for index, expression in enumerate(remaining)
                if _unit_signature(expression) == _unit_signature(expected)
            ),
            None,
        )
        if match is not None:
            remaining.pop(match)
            continue
        implicit_one = (
            expected.values == (1,)
            and 1 not in row.ol_values
        )
        if not implicit_one:
            return SemanticDecision(
                "INSUFFICIENT_EVIDENCE",
                reason_codes=("UNIT_SOURCE_CORRESPONDENCE_UNSUPPORTED",),
            )
    target_residual = Extraction(
        tuple(item for item in target.expressions if item.unit is None),
        target.status,
        target.limitations,
    )
    return compare_expressions(
        tuple(remaining), target_residual, allow_reordering=True
    )


def evaluate_unit(
    unit: ProjectedUnit,
    *,
    bundle: ReferenceBundle,
    language: str,
    language_profile: Mapping[str, object],
    style_profile: Mapping[str, object],
    check_policy: Mapping[str, object],
    model_tasks: object | None = None,
) -> UnitResult:
    """Evaluate one projected stream once under three independently enabled checks."""
    if (not isinstance(unit, ProjectedUnit) or not isinstance(bundle, ReferenceBundle)
            or not isinstance(language_profile, Mapping)):
        raise ValidationError("NCA unit inputs are malformed.", code="NCA_ENGINE_INPUT_INVALID")
    checks = _checks(check_policy)
    bundle.require_qualified()
    validated_style = validate_style_profile(style_profile)
    return _evaluate_prepared_unit(
        unit, bundle=bundle, language=language, language_profile=language_profile,
        style_profile=validated_style, checks=checks, model_tasks=model_tasks,
    )


def _evaluate_prepared_unit(
    unit: ProjectedUnit, *, bundle: ReferenceBundle, language: str,
    language_profile: Mapping[str, object], style_profile: Mapping[str, object],
    checks: Mapping[str, bool], model_tasks: object | None,
) -> UnitResult:
    """Evaluate one stream using only boundary-validated resources and switches."""
    validated_style = style_profile
    resolved_rows = tuple(bundle.lookup(ref) for ref in unit.western_references)
    ol_references = tuple(
        row.ol_reference for row in resolved_rows if row is not None
    )
    reference_index = tuple(
        {
            "western_reference": ref.label(),
            "status": "UNINDEXED" if row is None else (
                "REGISTERED_ABSENCE" if row.ol_reference is None else "INDEXED"
            ),
            "ol_reference": None if row is None else row.ol_reference,
        }
        for ref, row in zip(unit.western_references, resolved_rows)
    )
    extraction = _extract(
        unit, language=language, style_profile=validated_style, model_tasks=model_tasks
    )
    limitations = list(extraction.limitations)
    source_expressions: tuple[NumericExpression, ...] = ()
    reference_context: Mapping[str, object] = {}

    # Reading identification is shared evidence, but only enabled checks may publish claims from it.
    reading = _not_assessed_reading()
    if checks["number_accuracy"] or checks["footnote_review"]:
        if unit.status not in {"READY", "REGISTERED_ABSENCE"}:
            reading = _unsupported_reading("PROJECTION_NOT_READY")
            limitations.append(f"Projection is {unit.status}.")
        else:
            rows = tuple(
                bundle.lookup(ref)
                for ref in unit.western_references
                if bundle.lookup(ref) is not None
            )
            if len(unit.western_references) != 1 or len(rows) > 1:
                reading = _unsupported_reading("MERGED_ALIGNMENT_UNAVAILABLE")
                limitations.append("Merged Western alignment is unavailable.")
            elif not rows:
                if extraction.status == "COMPLETE" and extraction.expressions:
                    reading = ReadingDecision(
                        "UNSUPPORTED",
                        SemanticDecision(
                            "REFERENCE_NOT_INDEXED",
                            reason_codes=("WESTERN_REFERENCE_NOT_INDEXED",),
                        ),
                        "NONE",
                        None,
                        (),
                    )
                elif extraction.status == "COMPLETE":
                    reading = ReadingDecision(
                        "UNASSESSED",
                        SemanticDecision(
                            "NOT_ASSESSED",
                            reason_codes=("NO_NUMERIC_CONTENT_REFERENCE_NOT_REQUIRED",),
                        ),
                        "NONE",
                        None,
                        (),
                    )
                else:
                    reading = _unsupported_reading("REFERENCE_OR_EXTRACTION_UNAVAILABLE")
            else:
                reference_context = _result_reference_context(rows[0], bundle)
                reading, correspondence_limitations, source_expressions = _identify_reading(
                    unit,
                    extraction,
                    rows[0],
                    bundle=bundle,
                    model_tasks=model_tasks,
                )
                limitations.extend(correspondence_limitations)

    footnote = FootnoteDecision("NONE", "NOT_ASSESSED", "NONE")
    if checks["footnote_review"]:
        if "NO_NUMERIC_CONTENT_REFERENCE_NOT_REQUIRED" in reading.semantic.reason_codes:
            footnote = FootnoteDecision("NONE", "NOT_REQUIRED", "NONE")
        else:
            footnote = assess_footnote(
                reading,
                unit.target.notes,
                bundle=bundle,
                language=language,
                unit=unit.target,
                model_tasks=model_tasks,
            )

    style_findings: tuple[Mapping[str, object], ...] = ()
    if checks["presentation_consistency"]:
        context = (
            language_profile.get("number_context")
            if isinstance(language_profile.get("number_context"), str)
            else None
        )
        assessed_styles = list(
            _assess_prepared_style(
                extraction,
                profile=validated_style,
                location=_style_location(unit),
                context=context,
            )
        )
        for note in unit.target.notes:
            note_target = replace(
                unit.target,
                unit_id=f"{unit.target.unit_id}:note:{note.note_id}",
                target_references=note.anchor_references,
                main_text=note.text,
                notes=(),
            )
            note_unit = replace(
                unit,
                target=note_target,
                canonical_references=note.anchor_references,
            )
            note_extraction = _extract(
                note_unit,
                language=language,
                style_profile=validated_style,
                model_tasks=model_tasks,
            )
            limitations.extend(
                f"Note {note.note_id}: {item}" for item in note_extraction.limitations
            )
            assessed_styles.extend(
                {
                    **item,
                    "stream_id": f"note:{note.note_id}",
                    "note_id": note.note_id,
                }
                for item in _assess_prepared_style(
                    note_extraction,
                    profile=validated_style,
                    location="footnote",
                    context=context,
                )
            )
        style_findings = tuple(assessed_styles)

    if checks["number_accuracy"]:
        final = reading.semantic.outcome
        if (
            reading.selected == "ALT"
            and reading.semantic.outcome == "REGISTERED_ALTERNATE"
            and footnote.status == "ADEQUATE"
            and reading.source_validation_outcome is not None
        ):
            final = reading.source_validation_outcome
        elif footnote.outcome == "REVIEW_MISSING_FOOTNOTE":
            final = "REVIEW_MISSING_FOOTNOTE"
    elif checks["footnote_review"] and footnote.outcome == "REVIEW_MISSING_FOOTNOTE":
        final = "REVIEW_MISSING_FOOTNOTE"
    else:
        final = "NOT_ASSESSED"

    return UnitResult(
        unit,
        extraction,
        reading,
        footnote,
        final,
        style_findings,
        tuple(dict.fromkeys(limitations)),
        ol_references,
        source_expressions,
        reference_context,
        reference_index,
    )


def _finding_base(result: UnitResult) -> dict[str, object]:
    """Return the exact target, Western, OL, selection, and evidence context."""
    target_refs = [ref.label() for ref in result.projected.target.target_references]
    western_refs = [ref.label() for ref in result.projected.western_references]
    ol_references = list(result.ol_references)
    return {
        "target_reference": target_refs[0] if target_refs else None,
        "target_references": target_refs,
        "western_references": western_refs,
        "ol_reference": ol_references[0] if len(ol_references) == 1 else None,
        "ol_references": ol_references,
        "selected_reading": result.reading.selected,
        "source_ids": list(result.reading.source_ids),
        "evidence_ids": list(result.reading.semantic.evidence_ids),
    }


def _unit_findings(
    result: UnitResult,
    *,
    bundle: ReferenceBundle,
    checks: Mapping[str, bool],
) -> list[dict[str, object]]:
    """Create NUMBERS-only findings without claims from disabled assessments."""
    base = _finding_base(result)
    findings: list[dict[str, object]] = []
    semantic = result.reading.semantic.outcome
    screened = "NO_NUMERIC_CONTENT_REFERENCE_NOT_REQUIRED" in result.reading.semantic.reason_codes
    if checks["number_accuracy"] and not screened and semantic not in _PASS_OUTCOMES | {
        "REGISTERED_ALTERNATE"
    }:
        category = (
            "EVIDENCE"
            if semantic in {"INSUFFICIENT_EVIDENCE", "REFERENCE_NOT_INDEXED"}
            else "ACCURACY"
        )
        findings.append(
            {
                **base,
                "category": category,
                "code": f"NCA_{semantic}",
                "severity": "REVIEW",
                "message": f"Numeric assessment requires review: {semantic}.",
            }
        )
    if checks["footnote_review"] and result.footnote.outcome in {
        "ADVISORY",
        "REVIEW_MISSING_FOOTNOTE",
        "INSUFFICIENT_EVIDENCE",
    }:
        recommendation = footnote_recommendation(
            result.reading, result.footnote, bundle=bundle
        )
        findings.append(
            {
                **base,
                "category": "FOOTNOTE",
                "code": f"NCA_FOOTNOTE_{result.footnote.outcome}",
                "severity": "REVIEW"
                if result.footnote.outcome != "ADVISORY"
                else "ADVISORY",
                "footnote_action": result.footnote.action,
                "footnote_status": result.footnote.status,
                "suggested_note": recommendation.get("suggested_note")
                if recommendation
                else None,
                "message": "Review the reading-specific target footnote.",
            }
        )
    if checks["presentation_consistency"]:
        for style in result.style_findings:
            if style.get("status") != "REVIEW":
                continue
            findings.append(
                {
                    **base,
                    "category": "STYLE",
                    "code": str(style["code"]),
                    "severity": "REVIEW",
                    "rule_id": style.get("rule_id"),
                    "span": list(style["span"]) if "span" in style else None,
                    "message": "Review numeric presentation against the bound style rule.",
                }
            )
    return findings


def summarize(
    results: tuple[UnitResult, ...],
    *,
    checks: Mapping[str, bool] | None = None,
) -> Mapping[str, int]:
    """Derive handover, parser, reference, and assessment-state counters."""
    enabled = dict(checks) if checks is not None else {
        "number_accuracy": True,
        "presentation_consistency": True,
        "footnote_review": True,
    }
    accuracy = enabled["number_accuracy"]
    presentation = enabled["presentation_consistency"]
    semantic = tuple(result.reading.semantic.outcome for result in results)
    return {
        "units": len(results),
        "expressions": sum(len(result.extraction.expressions) for result in results),
        "target_expressions": sum(len(result.extraction.expressions) for result in results),
        "ol_expressions_checked": (
            sum(len(result.source_expressions) for result in results) if accuracy else 0
        ),
        "passes": sum(
            outcome in {
                "PASS_AUTHORITY1", "PASS_EQUIVALENT_NUMERIC_EXPRESSION",
                "PASS_UNIT_CONVERSION",
            }
            for outcome in semantic
        ) if accuracy else 0,
        "unit_conversions": semantic.count("PASS_UNIT_CONVERSION") if accuracy else 0,
        "value_differences": semantic.count("REVIEW_VALUE_DIFFERENCE") if accuracy else 0,
        "missing_numbers": semantic.count("REVIEW_NUMBER_MISSING") if accuracy else 0,
        "added_numbers": semantic.count("REVIEW_NUMBER_ADDED") if accuracy else 0,
        "known_variants": sum(
            result.reading.selected == "ALT" for result in results
        ) if accuracy else 0,
        "style_findings": sum(
            item.get("status") == "REVIEW"
            for result in results
            for item in result.style_findings
        ) if presentation else 0,
        "indexed_coordinates": sum(
            item.get("status") != "UNINDEXED"
            for result in results
            for item in result.reference_index
        ),
        "unindexed_coordinates": sum(
            item.get("status") == "UNINDEXED"
            for result in results
            for item in result.reference_index
        ),
        "findings": 0,
        "insufficient_evidence": sum(
            "PRESENTATION_CHECK_DISABLED" not in result.limitations
            and (
                result.extraction.status != "COMPLETE"
                or result.reading.semantic.outcome == "INSUFFICIENT_EVIDENCE"
                or result.footnote.outcome == "INSUFFICIENT_EVIDENCE"
            )
            for result in results
        ),
        "reference_not_indexed": sum(
            result.final_outcome == "REFERENCE_NOT_INDEXED" for result in results
        ),
        "not_assessed": sum(
            result.final_outcome == "NOT_ASSESSED" for result in results
        ),
        "extraction_complete": sum(
            result.extraction.status == "COMPLETE" for result in results
        ),
        "extraction_partial": sum(
            result.extraction.status == "PARTIAL" for result in results
        ),
        "extraction_unsupported": sum(
            result.extraction.status == "UNSUPPORTED" for result in results
        ),
    }


def evaluate_run(
    units: Sequence[ProjectedUnit],
    *,
    bundle: ReferenceBundle,
    language: str,
    language_profile: Mapping[str, object],
    style_profile: Mapping[str, object],
    check_policy: Mapping[str, object],
    run_id: str,
    expected_unit_ids: tuple[str, ...],
    model_tasks: object | None = None,
    coverage_restrictions: Sequence[str] = (),
    style_units: Sequence[TargetUnit] = (),
) -> RunResult:
    """Evaluate an exact run scope once and derive findings, coverage, and summary."""
    checks = _checks(check_policy)
    if not isinstance(bundle, ReferenceBundle) or not isinstance(language_profile, Mapping):
        raise ValidationError("NCA run inputs are malformed.", code="NCA_ENGINE_INPUT_INVALID")
    bundle.require_qualified()
    validated_style = validate_style_profile(style_profile)
    return _evaluate_prepared_units(
        units, bundle=bundle, language=language, language_profile=language_profile,
        style_profile=validated_style, checks=checks, run_id=run_id,
        expected_unit_ids=expected_unit_ids, model_tasks=model_tasks,
        coverage_restrictions=coverage_restrictions, style_units=style_units,
    )


def evaluate_prepared_run(inputs: ExecutionInputs, *, model_tasks: object, run_id: str) -> RunResult:
    """Evaluate a controller-owned context without reopening or revalidating resources."""
    if not isinstance(inputs, ExecutionInputs):
        raise ValidationError("NCA execution context is required.", code="NCA_ENGINE_INPUT_INVALID")
    wip = inputs.policy["wip"]
    return _evaluate_prepared_units(
        inputs.projected_units, bundle=inputs.bundle, language=str(wip["language"]),
        language_profile={"language": wip["language"], "script": wip["script"]},
        style_profile=inputs.style_profile, checks=inputs.policy["checks"],
        run_id=run_id, expected_unit_ids=inputs.expected_unit_ids, model_tasks=model_tasks,
        coverage_restrictions=reference_restrictions(inputs.policy), style_units=inputs.style_units,
    )


def _evaluate_prepared_units(
    units: Sequence[ProjectedUnit], *, bundle: ReferenceBundle, language: str,
    language_profile: Mapping[str, object], style_profile: Mapping[str, object],
    checks: Mapping[str, bool], run_id: str, expected_unit_ids: tuple[str, ...],
    model_tasks: object | None, coverage_restrictions: Sequence[str],
    style_units: Sequence[TargetUnit],
) -> RunResult:
    """Reconcile exact coverage and evaluate separately owned body and style streams."""
    unit_values = tuple(units)
    if any(not isinstance(unit, ProjectedUnit) for unit in unit_values) or any(
        not isinstance(unit, TargetUnit) for unit in style_units
    ):
        raise ValidationError(
            "NCA style streams must be TargetUnit values.", code="NCA_ENGINE_INPUT_INVALID"
        )
    projected_styles = tuple(
        ProjectedUnit(
            target,
            (),
            target.target_references,
            "STYLE_STREAM",
            "READY",
        )
        for target in style_units
    )
    all_units = unit_values + projected_styles
    actual_ids = tuple(unit.target.unit_id for unit in all_units)
    if (
        len(actual_ids) != len(set(actual_ids))
        or len(expected_unit_ids) != len(set(expected_unit_ids))
        or set(actual_ids) != set(expected_unit_ids)
    ):
        raise ValidationError(
            "Expected NCA units must reconcile exactly once.",
            code="NCA_RESULT_COVERAGE_INVALID",
        )
    main_results = tuple(
        _evaluate_prepared_unit(
            unit,
            bundle=bundle,
            language=language,
            language_profile=language_profile,
            style_profile=style_profile,
            checks=checks,
            model_tasks=model_tasks,
        )
        for unit in unit_values
    )
    # Heading streams enter coverage as units while remaining presentation-only evidence.
    if checks["presentation_consistency"]:
        style_policy = {
            "checks": {
                "number_accuracy": False,
                "presentation_consistency": True,
                "footnote_review": False,
            }
        }
        style_results = tuple(
            _evaluate_prepared_unit(
                unit,
                bundle=bundle,
                language=language,
                language_profile=language_profile,
                style_profile=style_profile,
                checks=style_policy["checks"],
                model_tasks=model_tasks,
            )
            for unit in projected_styles
        )
    else:
        style_results = tuple(
            UnitResult(
                unit,
                Extraction((), "UNSUPPORTED", ("PRESENTATION_CHECK_DISABLED",)),
                _not_assessed_reading(),
                FootnoteDecision("NONE", "NOT_ASSESSED", "NONE"),
                "NOT_ASSESSED",
                (),
                ("PRESENTATION_CHECK_DISABLED",),
            )
            for unit in projected_styles
        )
    results = main_results + style_results
    style_ids = {unit.target.unit_id for unit in projected_styles}
    style_only_checks = {
        "number_accuracy": False,
        "presentation_consistency": checks["presentation_consistency"],
        "footnote_review": False,
    }
    local = {
        result.projected.target.unit_id: _unit_findings(
            result,
            bundle=bundle,
            checks=style_only_checks
            if result.projected.target.unit_id in style_ids
            else checks,
        )
        for result in results
    }
    findings = tuple(assign_global_finding_ids(local, run_id=run_id, prefix="NUMBERS"))
    restrictions = list(coverage_restrictions)
    restrictions.extend(
        limitation for result in results for limitation in result.limitations
    )
    if checks["presentation_consistency"]:
        restrictions.extend(
            str(item.get("code"))
            for result in results
            for item in result.style_findings
            if item.get("status") == "NOT_ASSESSED"
        )
    skipped = tuple(sorted(name for name, enabled in checks.items() if not enabled))
    required_complete = all(
        (
            result.extraction.status == "COMPLETE"
            or (
                result.projected.target.unit_id in style_ids
                and not checks["presentation_consistency"]
            )
        )
        and (
            not (checks["number_accuracy"] or checks["footnote_review"])
            or result.reading.semantic.outcome
            not in {"INSUFFICIENT_EVIDENCE", "REFERENCE_NOT_INDEXED"}
        )
        and (
            not checks["footnote_review"]
            or result.footnote.outcome != "INSUFFICIENT_EVIDENCE"
        )
        for result in results
    )
    assessed = bool(results) and any(checks.values())
    coverage = assess_coverage(
        findings_present=bool(findings),
        required_evidence_complete=required_complete,
        restrictions=restrictions,
        skipped_checks=skipped,
        assessed=assessed,
    ).to_dict()
    coverage.update(
        expected_unit_ids=list(expected_unit_ids), assessed_unit_ids=list(actual_ids)
    )
    summary = dict(summarize(results, checks=checks))
    summary["findings"] = len(findings)
    return RunResult(results, findings, coverage, summary)
