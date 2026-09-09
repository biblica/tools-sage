"""Exact numeric correspondence over validated, typed expression evidence."""
from __future__ import annotations

from collections import Counter

from .models import Extraction, NumericExpression, SemanticDecision


def _meaning(expression: NumericExpression) -> tuple[object, ...]:
    """Keep every semantic attribute, including internal range/ratio order."""
    return (expression.values, expression.kind, expression.unit,
            expression.qualifier, expression.role)


def compare_expressions(
    ol: tuple[NumericExpression, ...], target: Extraction, *, allow_reordering: bool = False,
) -> SemanticDecision:
    """Compare typed meanings; surface presentation never changes authority.

    Callers must validate the source correspondence evidence before constructing
    the OL expressions. A flat index value does not supply kinds or referents.
    """
    if target.status != "COMPLETE":
        return SemanticDecision("INSUFFICIENT_EVIDENCE", reason_codes=("TARGET_EXTRACTION_INCOMPLETE",))
    if any(not expression.role or not expression.role.strip() for expression in ol):
        return SemanticDecision("INSUFFICIENT_EVIDENCE", reason_codes=("SOURCE_CORRESPONDENCE_UNSUPPORTED",))
    if any(not expression.role or not expression.role.strip() for expression in target.expressions):
        return SemanticDecision("INSUFFICIENT_EVIDENCE", reason_codes=("TARGET_CORRESPONDENCE_UNSUPPORTED",))
    if len(target.expressions) < len(ol):
        return SemanticDecision("REVIEW_NUMBER_MISSING", reason_codes=("TARGET_QUANTITY_MISSING",))
    if len(target.expressions) > len(ol):
        return SemanticDecision("REVIEW_NUMBER_ADDED", reason_codes=("TARGET_QUANTITY_ADDED",))
    source = tuple(_meaning(expression) for expression in ol)
    actual = tuple(_meaning(expression) for expression in target.expressions)
    if source == actual:
        return SemanticDecision("PASS_AUTHORITY1")
    if allow_reordering and Counter(source) == Counter(actual):
        return SemanticDecision("PASS_EQUIVALENT_NUMERIC_EXPRESSION", reason_codes=("CORRESPONDING_ROLES_REORDERED",))
    return SemanticDecision("REVIEW_VALUE_DIFFERENCE", reason_codes=("NUMERIC_MEANING_DIFFERENT",))
