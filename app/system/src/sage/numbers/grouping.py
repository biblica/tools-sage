"""Classify, compare and annotate one projected NCA group against the reference index.

Kept apart from numbers/hybrid.py (model-phase execution) so comparison changes never
alter the sealed extraction contract or invalidate extraction checkpoints.
"""
from __future__ import annotations


def wip_covered_labels(projected_units) -> frozenset[str]:
    """Western coordinates owned by a group that has WIP text (e.g. inside a bridge).

    Western, not WIP-local, labels: under a different WIP versification a WIP label can name
    another Western verse (Hebrew NUM 17:1 is Western NUM 16:36), which must not excuse a gap.
    """
    return frozenset(ref.label() for unit in projected_units if unit.target.target_references
                     for ref in unit.western_references)


def alternate_readings(unit, inputs, refs) -> tuple:
    """Registered alternate readings (footnote guidance ALT values) the WIP may follow."""
    from .compare import AlternateReading
    from .reference import parse_values

    bundle = inputs.bundle
    readings = []
    for ref in refs:
        guidance = bundle.footnote_guidance.get(ref)
        alternate = parse_values(str(guidance.get('ALT_NIV_VALUES') or '')) if guidance else ()
        if not alternate:
            continue
        parts = []
        for western in unit.western_references:
            row = bundle.lookup(western)
            values = (row.ol_values or row.niv_values) if row is not None else ()
            parts.append((western, alternate if western == ref else values))
        if ref not in unit.western_references:
            parts.append((ref, alternate))
            parts.sort(key=lambda item: (item[0].chapter, item[0].verse))
        readings.append(AlternateReading(ref.label(), tuple(v for _ref, values in parts for v in values), {
            'classification': str(guidance.get('CLASS') or ''),
            'scholarship_status': str(guidance.get('SCHOLARSHIP_STATUS') or ''),
            'footnote_if_target_follows_alt': str(guidance.get('FOOTNOTE_IF_TARGET_FOLLOWS_ALT') or ''),
            'suggested_note': str(guidance.get('SUGGESTED_NOTE_IF_ALT_SELECTED') or ''),
            'niv_footnote': str(guidance.get('NIV_FOOTNOTE') or ''),
        }))
    return tuple(readings)


def evaluate_group(unit, *, inputs, by_owner, checks, mode, covered):
    """Classify, compare and annotate one projected group."""
    from .compare import ComparisonResult, compare_group, not_assessed
    from .numerals import find_numerals
    from .footnotes import noteworthy_note
    from .models import Extraction
    from .results import GroupResult

    bundle = inputs.bundle
    target = unit.target
    # Index, guidance and notes are keyed by Western coordinates; WIP-local labels stay out.
    refs = list(unit.western_references)

    def notes_for(coordinates):
        """Advisory text-critical notes for the coordinates this group owns."""
        if not checks['footnote_review']:
            return ()
        return tuple(note for ref in coordinates if (note := noteworthy_note(ref, bundle=bundle)) is not None)

    if not target.target_references:
        label = unit.western_references[0].label() if unit.western_references else ''
        if label in covered:
            # The WIP text for this coordinate lives in another group (a bridge); that group
            # owns its comparison and notes.
            return GroupResult(unit, Extraction((), 'NOT_REQUIRED', ('COVERED_BY_WIP_GROUP',)),
                               compare_group((), [], mode=mode), ('COVERED_BY_WIP_GROUP',), ())
        if unit.status == 'REGISTERED_ABSENCE':
            return GroupResult(unit, Extraction((), 'NOT_REQUIRED', ('REGISTERED_ABSENCE',)),
                               compare_group((), [], mode=mode), ('REGISTERED_ABSENCE',),
                               notes_for(unit.western_references))
        return GroupResult(unit, Extraction((), 'UNSUPPORTED', ('UNMAPPED_COORDINATE',)), not_assessed(mode),
                           ('UNMAPPED_COORDINATE',), notes_for(unit.western_references))
    if target.content_issues:
        # Damaged or repeated content is reported and never compared (never a false all-clear).
        return GroupResult(unit, Extraction((), 'NOT_REQUIRED', target.content_issues), not_assessed(mode),
                           tuple(dict.fromkeys(target.content_issues)), notes_for(refs))
    rows = [row for ref in unit.western_references if (row := bundle.lookup(ref)) is not None]
    if not rows:
        # "his 2nd son" is a rank, not a quantity; a malformed numeral is still reported
        numerals = [numeral for numeral in find_numerals(target.main_text) if not numeral.suffixed]
        if numerals and checks['number_accuracy']:
            # A digit numeral where the source has no number: almost always a typing slip.
            readable = [numeral for numeral in numerals if numeral.readings]
            values = tuple(numeral.readings[0] for numeral in readable)
            malformed = [numeral.text for numeral in numerals if numeral.malformed]
            return GroupResult(unit, Extraction(values, 'COMPLETE', ('NOT_INDEXED',),
                                                surfaces=tuple(numeral.text for numeral in readable)),
                               ComparisonResult('FAIL', mode, values, (), 'NONE',
                                                {'kind': 'MALFORMED_NUMERAL' if malformed else 'NUMBER_NOT_IN_SOURCE',
                                                 'numerals': malformed or [numeral.text for numeral in numerals],
                                                 'references': [ref.label() for ref in refs]}),
                               ('NOT_INDEXED',), notes_for(refs))
        return GroupResult(unit, Extraction((), 'NOT_REQUIRED', ('NOT_INDEXED',)),
                           compare_group((), [], mode=mode), ('NOT_INDEXED',), notes_for(refs))
    extraction = by_owner.get(target.unit_id, Extraction((), 'UNSUPPORTED', ('MISSING_WIP_OR_EXTRACTION',)))
    limits = list(extraction.limitations)
    if not checks['number_accuracy']:
        comparison = not_assessed(mode)
    elif extraction.status != 'COMPLETE' and not any(
            issue.startswith('MALFORMED_NUMERAL:') for issue in extraction.issues):
        comparison = not_assessed(mode)
        limits.append('NUMBER_ACCURACY_EXTRACTION_INCOMPLETE')
    else:
        # a malformed numeral is SAGE's own reading: reported even when the model read the verse partly
        if extraction.status != 'COMPLETE':
            limits.append('NUMBER_ACCURACY_EXTRACTION_INCOMPLETE')
        comparison = compare_group(extraction.values, rows, mode=mode,
                                   alternates=alternate_readings(unit, inputs, refs),
                                   wip_kinds=extraction.kinds, wip_counts_en=extraction.counts_en,
                                   wip_issues=extraction.issues)
    notes = list(notes_for(refs))
    critical = text_critical_note(rows, extraction, target, bundle)
    if critical is not None:
        notes.append(critical)
    if comparison.outcome == 'PASS' and comparison.review_context.get('note') == 'ORDER_DIFFERS_ITEMS_MATCH':
        notes.append({'kind': 'ORDER_NOTE', 'western_reference': ', '.join(ref.label() for ref in refs),
                      'pairings': list(comparison.review_context.get('pairings') or ())})
    return GroupResult(unit, extraction, comparison, tuple(dict.fromkeys(limits)), tuple(notes))


def text_critical_note(rows, extraction, target, bundle):
    """Where the original language and the NIV differ: which reading the WIP follows (operator list).

    These are editorial decisions that usually need a footnote; the note records both readings,
    the WIP choice, whether the WIP has a footnote at the verse, and any registered guidance.
    """
    from collections import Counter
    from .compare import apparatus_entries
    ol = [value for row in rows for value in row.ol_values]
    niv = [value for row in rows for value in row.niv_values]
    statuses = [row.metadata.get('TC_STATUS') for row in rows]
    if any(status is not None for status in statuses):
        # Typed packages with apparatus evidence: only a recorded number variant is a decision.
        if 'VARIANT_ATTESTED' not in statuses:
            return None
    elif Counter(ol) == Counter(niv):
        return None
    wip = Counter(extraction.values) if extraction.status == 'COMPLETE' else None
    follows = ('NOT_ASSESSED' if wip is None else 'OL' if wip == Counter(ol)
               else 'NIV' if wip == Counter(niv) else 'NEITHER')
    guidance = next((bundle.footnote_guidance.get(row.western_reference) for row in rows
                     if bundle.footnote_guidance.get(row.western_reference) is not None), None)
    return {
        'kind': 'TEXT_CRITICAL',
        'western_reference': ', '.join(row.western_reference.label() for row in rows),
        'ol_values': [str(value) for value in ol],
        'niv_values': [str(value) for value in niv],
        'wip_values': [str(value) for value in extraction.values],
        'follows': follows,
        'footnote_in_wip': bool(target.notes),
        'footnote_if_follows_ol': str((guidance or {}).get('FOOTNOTE_IF_TARGET_FOLLOWS_OL') or ''),
        'footnote_if_follows_alt': str((guidance or {}).get('FOOTNOTE_IF_TARGET_FOLLOWS_ALT') or ''),
        'suggested_note': str((guidance or {}).get('SUGGESTED_NOTE_IF_ALT_SELECTED' if follows == 'NIV'
                                                  else 'SUGGESTED_NOTE_IF_OL_SELECTED') or ''),
        'niv_footnote': str((guidance or {}).get('NIV_FOOTNOTE') or ''),
        'apparatus': apparatus_entries(rows),
    }
