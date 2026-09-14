"""Describe admitted WIP numeric expressions without inventing approved style rules."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
import unicodedata

from sage.errors import ValidationError


def validate_note_extractions(raw: object, projection: Mapping[str, object], *, enabled: bool) -> None:
    """Validate every retained note stream against its original text and exact identity."""
    from .results import _validate_expression

    def require(condition: bool) -> None:
        """Reject malformed or incomplete usage evidence with one stable diagnostic."""
        if not condition:
            raise ValidationError('NCA note usage evidence is invalid.', code='NCA_RESULT_EXPRESSION_INVALID')

    rows = projection.get('target_note_streams')
    require(isinstance(rows, list) and all(isinstance(row, Mapping)
        and set(row) == {'note_id', 'text'} and isinstance(row['note_id'], str)
        and row['note_id'] and isinstance(row['text'], str) for row in rows))
    notes = {row['note_id']: row['text'] for row in rows}
    require(len(notes) == len(rows))
    require(isinstance(raw, Mapping) and set(raw) == (set(notes) if enabled else set()))
    for note_id, extraction in raw.items():
        require(isinstance(extraction, Mapping) and set(extraction) == {'status', 'limitations', 'expressions'})
        require(extraction['status'] in {'COMPLETE', 'PARTIAL', 'UNSUPPORTED'})
        require(isinstance(extraction['limitations'], list)
                and all(isinstance(x, str) and x for x in extraction['limitations'])
                and (extraction['status'] == 'COMPLETE' or bool(extraction['limitations'])))
        require(isinstance(extraction['expressions'], list))
        ids, spans = [], []
        for expression in extraction['expressions']:
            identity, span = _validate_expression(expression, role_required=False,
                target_text=notes[note_id], expected_stream=note_id)
            ids.append(identity)
            spans.append(span)
        require(len(set(ids)) == len(ids) and not any(a < d and c < b
            for index, (a, b) in enumerate(spans) for c, d in spans[index + 1:]))


def _form(surface: str, representations: object) -> str:
    """Distinguish visible digit use without mistaking unit names for number words."""
    if representations:
        return 'MULTIPLE_REPRESENTATIONS'
    if any(unicodedata.category(char) in {'Nl', 'No'} for char in surface):
        return 'NUMERIC_SYMBOLS'
    return 'DIGITS' if any(char.isdecimal() for char in surface) else 'WORDS'


def number_usage(document: Mapping[str, object]) -> dict[str, object]:
    """Summarize validated parent/heading/note evidence once per original stream."""
    enabled = document['check_policy']['checks']['presentation_consistency']
    examples, unassessed = [], []
    coverage = Counter()
    groups = document.get('groups', document.get('units', ()))
    for group in groups:
        projection = group['projection']
        location = 'heading' if projection.get('precision') == 'STYLE_STREAM' else 'body'
        streams = [(None, location, projection['target_references'], group['extraction'])]
        metadata = {row['note_id']: row for row in projection.get('target_note_metadata', ())}
        for note in projection.get('target_note_streams', ()):
            note_id = note['note_id']
            # A historical report may contain note text but no accepted note extraction.
            extraction = group.get('note_extractions', {}).get(note_id)
            refs = metadata.get(note_id, {}).get('anchor_references', [])
            streams.append((note_id, 'footnote', refs, extraction))
        for note_id, location, refs, extraction in streams:
            identity = dict(unit_id=group['unit_id'], note_id=note_id, location=location,
                            target_references=list(refs))
            status = extraction['status'] if enabled and extraction is not None else 'NOT_ASSESSED'
            coverage[status] += 1
            if status != 'COMPLETE':
                limits = list(extraction.get('limitations', ())) if extraction is not None else ['NOTE_EXTRACTION_NOT_RECORDED']
                if not enabled:
                    limits = ['PRESENTATION_CHECK_DISABLED']
                unassessed.append(dict(identity, status=status, limitations=limits))
            if not enabled or extraction is None:
                continue
            for expression in extraction['expressions']:
                surface = expression['surface']
                punctuation = sorted({char for index, char in enumerate(surface)
                    if 0 < index < len(surface) - 1 and surface[index - 1].isdecimal()
                    and surface[index + 1].isdecimal() and not char.isdecimal()})
                digit_sets = sorted({unicodedata.name(char, 'UNKNOWN').rsplit(' DIGIT ', 1)[0]
                    if ' DIGIT ' in unicodedata.name(char, '') else 'ASCII'
                    for char in surface if char.isdecimal()})
                examples.append(dict(identity, expression_id=expression.get('expression_id'),
                    extraction_status=status, surface=surface, span=list(expression['span']),
                    values=list(expression['values']), kind=expression['kind'],
                    unit=expression.get('unit'), qualifier=expression.get('qualifier'),
                    form=_form(surface, expression.get('representations')), separators=punctuation,
                    digit_sets=digit_sets))
    buckets = defaultdict(list)
    for row in examples:
        key = (row['location'], tuple(row['values']), row['kind'], row['unit'], row['qualifier'])
        buckets[key].append(row)
    mixed = []
    for (location, values, kind, unit, qualifier), rows in buckets.items():
        forms = sorted({row['form'] for row in rows})
        separators = {tuple(row['separators']) for row in rows if row['form'] == 'DIGITS'}
        if len(forms) > 1 or len(separators) > 1:
            mixed.append(dict(location=location, values=list(values), kind=kind, unit=unit,
                qualifier=qualifier, forms=forms, examples=rows))
    return dict(expression_count=len(examples), forms=dict(Counter(row['form'] for row in examples)),
                coverage=dict(coverage), examples=examples, mixed_usage=mixed, unassessed=unassessed)


def render_number_usage(document: Mapping[str, object], text) -> list[str]:
    """Render descriptive counts and chapter examples with source text safely quoted."""
    from sage.nca_reporting import _exact
    from sage.references import BOOK_ORDER

    usage = number_usage(document)
    lines = ['', f"## {text('report.nca.usage_title')}", '', text('report.nca.usage_notice'), '',
             f"- {text('report.nca.expressions')}: {usage['expression_count']}",
             f"- {text('report.nca.usage_forms')}: `{_exact(usage['forms'])}`",
             f"- {text('report.nca.coverage')}: `{_exact(usage['coverage'])}`", '']
    if not document['provenance']['style_profile'].get('selector'):
        lines.extend([text('report.nca.no_stylesheet'), ''])
    sections = defaultdict(list)
    for row in usage['examples']:
        refs = row['target_references']
        # Protected cross-verse/chapter streams remain one example, under their first WIP chapter.
        chapter = refs[0].split(':')[0] if refs else 'UNLOCATED'
        sections[chapter].append(row)
    for chapter in sorted(sections, key=lambda value: (
            BOOK_ORDER.get(value.split()[0], 999), int(value.split()[1]) if ' ' in value else 0)):
        lines.extend([f'### {chapter}', '',
            f"| {text('report.nca.target_reference')} | {text('report.nca.usage_stream')} | {text('report.nca.exact_evidence')} | {text('report.nca.usage_form')} | {text('report.nca.usage_details')} |",
            '| --- | --- | --- | --- | --- |'])
        for row in sections[chapter]:
            detail = {key: row[key] for key in ('values', 'kind', 'unit', 'qualifier', 'separators', 'digit_sets', 'extraction_status')}
            cells = (', '.join(row['target_references']) or 'UNLOCATED',
                     row['location'] + (f" ({row['note_id']})" if row['note_id'] else ''),
                     row['surface'], row['form'], detail)
            lines.append('| ' + ' | '.join('`' + _exact(cell).replace('|', '\\u007c') + '`' for cell in cells) + ' |')
        lines.append('')
    lines.extend([f"### {text('report.nca.usage_mixed')}", '', text('report.nca.usage_mixed_notice'), ''])
    for item in usage['mixed_usage']:
        refs = list(dict.fromkeys(ref for row in item['examples'] for ref in row['target_references']))
        lines.append(f"- `{_exact(dict(values=item['values'], kind=item['kind'], unit=item['unit'], location=item['location'], forms=item['forms'], target_references=refs))}`")
    if not usage['mixed_usage']:
        lines.append(text('report.nca.usage_no_mixed'))
    if usage['unassessed']:
        lines.extend(['', f"### {text('report.nca.not_assessed')}", ''])
        lines.extend(f"- `{_exact(row)}`" for row in usage['unassessed'])
    lines.append('')
    return lines
