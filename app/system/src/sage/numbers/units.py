"""Exact adapters for registered verse-specific unit examples."""
from __future__ import annotations

from collections import Counter
import re
from fractions import Fraction

from sage.errors import ValidationError
from .models import Extraction, NumericExpression, ReferenceBundle, ReferenceRow, SemanticDecision


_UNITS = {
    'sata': 'saton', 'saton': 'saton', 'baths': 'bath', 'bath': 'bath',
    'cors': 'cor', 'cor': 'cor', 'stadia': 'stadion', 'stadion': 'stadion',
    'metretes': 'metretes', 'litras': 'litra', 'litra': 'litra',
    'cubits': 'cubit', 'cubit': 'cubit', 'fathoms': 'fathom', 'fathom': 'fathom',
    'choinix': 'choinix', 'choinikes': 'choinix', 'talent-weight': 'talent-weight',
    'pounds': 'pound', 'pound': 'pound', 'gallons': 'gallon', 'gallon': 'gallon',
    'bushels': 'bushel', 'bushel': 'bushel', 'miles': 'mile', 'mile': 'mile',
    'yards': 'yard', 'yard': 'yard', 'feet': 'foot', 'foot': 'foot',
}
_NUMBER = r'(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|0|[1-9][0-9]*)(?:/[1-9][0-9]*)?'
_QUANTITY = re.compile(rf'(?:(about|less than|more than) )?({_NUMBER})(?:-({_NUMBER}))? ([a-z-]+)')
_QUALIFIERS = {None: 'EXACT', 'about': 'ABOUT', 'less than': 'LESS_THAN', 'more than': 'MORE_THAN'}


def parse_registered_quantity(raw: str) -> tuple[NumericExpression, ...]:
    """Parse the bounded English registry notation, never target-language text."""
    expressions = []
    offset = 0
    for part in raw.split(';'):
        surface = part.strip()
        match = _QUANTITY.fullmatch(surface)
        if match is None or match[4] not in _UNITS:
            raise ValidationError('Unsupported registered NCA quantity.', code='NCA_UNIT_EXAMPLE_UNSUPPORTED')
        values = tuple(Fraction(value.replace(',', '')) for value in (match[2], match[3]) if value is not None)
        start = offset + len(part) - len(part.lstrip())
        kind = 'RANGE' if len(values) == 2 else ('FRACTION' if values[0].denominator != 1 else 'CARDINAL')
        expressions.append(NumericExpression(values, kind, surface, (start, start + len(surface)),
                                             unit=_UNITS[match[4]], qualifier=_QUALIFIERS[match[1]]))
        offset += len(part) + 1
    return tuple(expressions)


def _unit_meaning(expression: NumericExpression) -> tuple[object, ...]:
    """Compare unit presentation only through exact registered semantic attributes."""
    return (expression.values, expression.kind, _UNITS.get(expression.unit, expression.unit), expression.qualifier)


def compare_registered_units(row: ReferenceRow, target: Extraction, *, bundle: ReferenceBundle) -> SemanticDecision:
    """Check the registered pair and preserve every unrelated indexed source value.

    This adapter supplies conversion evidence, not whole-verse role alignment.
    The engine must independently validate the full typed residual correspondence,
    including every referent, kind, unit, qualifier, and permitted reordering,
    before it can return an overall pass.
    An implicit singular unit in the original registry may supply a quantity of
    one absent from the flat index; no other missing source value is inferred.
    """
    bundle.require_qualified()
    if bundle.lookup(row.western_reference) != row:
        raise ValidationError('NCA unit row is outside the bound reference.', code='NCA_REFERENCE_CONTRACT_CONFLICT')
    record = bundle.units.get(row.western_reference)
    if record is None:
        return SemanticDecision('INSUFFICIENT_EVIDENCE', reason_codes=('UNIT_CONVERSION_NOT_REGISTERED',))
    if target.status != 'COMPLETE' or any(not item.role or not item.role.strip() for item in target.expressions):
        return SemanticDecision('INSUFFICIENT_EVIDENCE', reason_codes=('UNIT_CORRESPONDENCE_UNSUPPORTED',))
    try:
        source = parse_registered_quantity(str(record['OL_QUANTITY']))
        expected = parse_registered_quantity(str(record['NIV_QUANTITY']))
    except (ValidationError, KeyError):
        return SemanticDecision('INSUFFICIENT_EVIDENCE', reason_codes=('UNIT_EXAMPLE_UNSUPPORTED',))
    remaining = list(row.ol_values)
    for expression in source:
        for value in expression.values:
            if value in remaining:
                remaining.remove(value)
            elif value != 1:
                return SemanticDecision('INSUFFICIENT_EVIDENCE', reason_codes=('UNIT_SOURCE_INDEX_CONFLICT',))
    converted = tuple(item for item in target.expressions if item.unit is not None)
    retained = tuple(item for item in target.expressions if item.unit is None)
    retained_values = tuple(value for item in retained for value in item.values)
    if (tuple(_unit_meaning(item) for item in converted) != tuple(_unit_meaning(item) for item in expected)
            or Counter(retained_values) != Counter(remaining)):
        return SemanticDecision('REVIEW_VALUE_DIFFERENCE', reason_codes=('REGISTERED_UNIT_PAIR_DIFFERENT',))
    source_ids = tuple(part.strip() for part in str(record.get('SOURCE_IDS', '')).split(';') if part.strip())
    return SemanticDecision('PASS_UNIT_CONVERSION', source_ids, ('REGISTERED_UNIT_EXAMPLE', 'UNRELATED_VALUES_PRESERVED'))
