"""Reading-specific disclosure assessment over anchored target notes."""
from __future__ import annotations

from typing import Mapping

from sage.errors import ValidationError
from .models import FootnoteDecision, ReadingDecision, ReferenceBundle, TargetNote, TargetUnit


def _missing(action: str, status: str = 'MISSING') -> FootnoteDecision:
    """Distinguish required disclosure failure from a recommendation advisory."""
    return FootnoteDecision(action, status, 'REVIEW_MISSING_FOOTNOTE' if action == 'REQUIRE' else 'ADVISORY')


def _guidance(reading: ReadingDecision, bundle: ReferenceBundle) -> Mapping[str, object] | None:
    """Select only registered guidance for the already identified whole reading."""
    for ref, record in bundle.footnote_guidance.items():
        if ref.label() != reading.registry_id:
            continue
        return {
            'guidance_id': ref.label(), 'registry_id': ref.label(),
            'action': reading.footnote_action, 'reading': reading.selected,
            'source_ids': list(reading.source_ids),
            'required_content': {
                'selected_reading': reading.selected,
                'ol_values': str(record.get('OL_VALUES', '')),
                'alternate_values': str(record.get('ALT_NIV_VALUES', '')),
                'classification': str(record.get('CLASS', '')),
                'scholarship_status': str(record.get('SCHOLARSHIP_STATUS', '')),
                'suggested_note': str(record.get(f'SUGGESTED_NOTE_IF_{reading.selected}_SELECTED', '')),
                'manuscript_evidence': str(record.get('MANUSCRIPT_EVIDENCE', '')),
                'scholarship_position': str(record.get('SCHOLARSHIP_POSITION', '')),
                'adequacy_rule': 'Disclose this numeric difference or its registered witness/reconstruction uncertainty. An unrelated number, locator or citation is insufficient.',
            },
        }
    return None


def assess_footnote(reading: ReadingDecision, notes: tuple[TargetNote, ...], *,
                    bundle: ReferenceBundle, language: str,
                    unit: TargetUnit | None = None, model_tasks: object | None = None) -> FootnoteDecision:
    """Assess anchored target disclosure through the existing routed model tasks.

    Missing-note classification needs only the selected immutable policy. Any
    content assessment also requires a qualified package, original target unit
    and routed model dependency. Missing interpretation remains unassessed.
    """
    action = reading.footnote_action
    if reading.selected not in {'OL', 'ALT'}:
        return FootnoteDecision(action, 'NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE')
    if action == 'NONE':
        return FootnoteDecision(action, 'NOT_REQUIRED', 'NONE')
    if not notes:
        return _missing(action)
    if unit is None:
        return FootnoteDecision(action, 'NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE')
    anchors = set(unit.target_references)
    if not anchors and reading.selected == 'OL' and reading.source_validation_outcome == 'NO_CONFIGURED_OL_READING':
        anchors.update(ref for ref, row in bundle.rows.items()
                       if ref.label() == reading.registry_id and row.ol_reference is None)
    eligible = tuple(note for note in notes if note in unit.notes
                     and note.marker in {'f', 'fe', 'ef', 'efe'} and note.text.strip()
                     and set(note.anchor_references).intersection(anchors)
                     and any(span.get('kind') == 'CONTENT' for span in note.content_spans))
    if not eligible:
        return _missing(action)
    bundle.require_qualified()
    guidance = _guidance(reading, bundle)
    if guidance is None or model_tasks is None or not language:
        return FootnoteDecision(action, 'NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE')
    unresolved = False
    for note in eligible:
        try:
            phase = model_tasks.assess_footnote(unit, note, guidance, required_action=action)
            decision = phase.value
        except ValidationError:
            unresolved = True
            continue
        if not isinstance(decision, FootnoteDecision) or decision.action != action:
            unresolved = True
            continue
        if decision.status == 'ADEQUATE':
            if not decision.evidence_spans or any(start < 0 or end <= start or end > len(note.text)
                                                  for start, end in decision.evidence_spans):
                unresolved = True
                continue
            return FootnoteDecision(action, 'ADEQUATE', 'NONE', decision.evidence_spans,
                                    tuple(note.note_id for _ in decision.evidence_spans))
        if decision.status != 'INADEQUATE':
            unresolved = True
    if unresolved:
        return FootnoteDecision(action, 'NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE')
    return _missing(action, 'INADEQUATE')


def footnote_recommendation(reading: ReadingDecision, decision: FootnoteDecision, *,
                            bundle: ReferenceBundle) -> Mapping[str, object] | None:
    """Recommend adding or revising disclosure only when registered policy calls for it."""
    if decision.action == 'NONE' or decision.status not in {'MISSING', 'INADEQUATE'}:
        return None
    guidance = _guidance(reading, bundle)
    if guidance is None:
        return None
    return {'action': 'ADD' if decision.status == 'MISSING' else 'REVISE',
            'required_action': decision.action, 'source_ids': tuple(reading.source_ids),
            'selected_reading': reading.selected, **guidance['required_content']}
