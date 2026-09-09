"""Select only whole registered readings without changing OL authority."""
from __future__ import annotations

from fractions import Fraction

from sage.errors import ValidationError
from .models import ReadingDecision, ReferenceBundle, ReferenceRow, SemanticDecision
from .reference import normalize_footnote_action, parse_values


_PROVEN_MATCHES = frozenset({'PASS_AUTHORITY1', 'PASS_EQUIVALENT_NUMERIC_EXPRESSION'})


def select_reading(row: ReferenceRow, target_values: tuple[Fraction, ...], *,
                   bundle: ReferenceBundle, semantic: SemanticDecision) -> ReadingDecision:
    """Identify a numeric reading, preserving independent correspondence evidence.

    The incoming semantic decision must describe correspondence against the
    selected candidate's supported evidence. Value lookup alone does not prove
    numeric roles, units or qualifiers, nor does it assess target footnotes.
    """
    bundle.require_qualified()
    if bundle.lookup(row.western_reference) != row:
        raise ValidationError('NCA reading row does not belong to the bound reference bundle.', code='NCA_REFERENCE_CONTRACT_CONFLICT')
    ref = row.western_reference
    variant = bundle.variants.get(ref)
    guidance = bundle.footnote_guidance.get(ref)
    registered = variant is not None and guidance is not None
    selected = 'UNSUPPORTED'
    if target_values == row.ol_values:
        selected = 'OL'
    elif registered and target_values == parse_values(str(variant['NIV_VALUE_RESEARCHED'])) == parse_values(str(guidance['ALT_NIV_VALUES'])):
        selected = 'ALT'
    if selected == 'UNSUPPORTED':
        outcome = semantic if semantic.outcome in {'INSUFFICIENT_EVIDENCE', 'NOT_ASSESSED'} else SemanticDecision('REVIEW_VALUE_DIFFERENCE', semantic.evidence_ids, ('UNREGISTERED_NUMERIC_READING',))
        return ReadingDecision(selected, outcome, 'NONE', None, ())
    if registered:
        source_ids = tuple(part.strip() for part in str(guidance['SOURCE_IDS']).split(';') if part.strip())
        action = normalize_footnote_action(str(guidance[f'FOOTNOTE_IF_TARGET_FOLLOWS_{selected}']))
        source_policy = str(guidance[f'VALIDATION_IF_TARGET_FOLLOWS_{selected}'])
        outcome = semantic
        if selected == 'ALT' and semantic.outcome in _PROVEN_MATCHES:
            outcome = SemanticDecision('REGISTERED_ALTERNATE', semantic.evidence_ids, semantic.reason_codes)
        elif selected == 'OL' and row.ol_reference is None:
            if source_policy != 'NO_CONFIGURED_OL_READING':
                raise ValidationError('NCA source absence is not registered.', code='NCA_REFERENCE_CONTRACT_CONFLICT')
            if semantic.outcome in _PROVEN_MATCHES:
                outcome = SemanticDecision('NO_CONFIGURED_OL_READING', semantic.evidence_ids, semantic.reason_codes)
        return ReadingDecision(selected, outcome, action, ref.label(), source_ids, source_policy)
    if row.ol_reference is None:
        raise ValidationError('NCA cannot select an unregistered source absence.', code='NCA_REFERENCE_CONTRACT_CONFLICT')
    source_ids = tuple(part.strip() for part in row.metadata.get('SOURCE_IDS', '').split(';') if part.strip())
    action = normalize_footnote_action(row.metadata.get('FOOTNOTE_IF_TARGET_FOLLOWS_OL', 'NONE'))
    return ReadingDecision('OL', semantic, action, None, source_ids)
