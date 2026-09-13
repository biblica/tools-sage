"""Immutable target-only projections bound to the Scripture SFM actually routed."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import re

from sage.errors import ValidationError
from sage.evidence import serialize_evidence
from sage.hashing import sha256_bytes
from sage.sfm_slicer import render_sfm_slice
from sage.vrs import VerseRef
from sage.usj import visible_text
from sage.work_units import EvidenceRecord, _validate_records

from .models import TargetUnit, freeze
from .target import _notes
from .policy import _plain


def _digest(value: object) -> str:
    """Hash inert canonical binding data without invoking Scripture sizing."""
    return sha256_bytes(serialize_evidence(_plain(value)))


def _projection_binding(value: StreamInput) -> str:
    """Bind exact offsets and provenance, including all independently routed identity."""
    return _digest({name: getattr(value, name) for name in (
        'owner_unit_id', 'stream_id', 'purpose', 'text', 'routed_sfm',
        'source_sha256', 'language', 'conventions_sha256')} | {
        'target_references': [ref.label() for ref in value.target_references],
        'records': [{'references': [ref.label() for ref in record.refs],
                     'sfm': record.sfm, 'payload': record.payload} for record in value.records]})


@dataclass(frozen=True)
class StreamInput:
    """One protected offset stream, independent of expected reference numbers."""
    input_id: str
    owner_unit_id: str
    stream_id: str
    purpose: str
    target_references: tuple[VerseRef, ...]
    records: tuple[EvidenceRecord, ...]
    text: str
    routed_sfm: str
    source_sha256: str
    projection_sha256: str
    language: str
    conventions_sha256: str

    def __post_init__(self) -> None:
        """Reject invalid transport bindings and recursively own mutable record payloads."""
        if (any(not isinstance(value, str) or not value for value in (
                self.input_id, self.owner_unit_id, self.stream_id, self.language))
                or self.purpose not in {'BODY', 'NOTE_STYLE', 'HEADING_STYLE'}
                or not isinstance(self.text, str)
                or not isinstance(self.target_references, tuple)
                or any(not isinstance(ref, VerseRef) for ref in self.target_references)
                or len(set(self.target_references)) != len(self.target_references)
                or not isinstance(self.records, tuple) or not self.records
                or any(not isinstance(record, EvidenceRecord) or not record.sfm.strip()
                       or not isinstance(record.payload, Mapping) for record in self.records)
                or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                       for value in (self.source_sha256, self.projection_sha256, self.conventions_sha256))):
            raise ValidationError('NCA stream input is invalid', code='NCA_TRANSPORT_INVALID')
        _validate_records(self.records)
        object.__setattr__(self, 'records', tuple(replace(record, payload=freeze(record.payload),
            boundaries_before=tuple(freeze(item) for item in record.boundaries_before)) for record in self.records))
        if (self.routed_sfm != render_sfm_slice(self.records) or self.projection_sha256 != _projection_binding(self)
                or self.input_id != "input:" + self.projection_sha256):
            raise ValidationError('NCA stream binding differs from its evidence', code='NCA_TRANSPORT_INVALID')


def make_stream_input(*, owner_unit_id: str, stream_id: str, purpose: str,
                      target_references: tuple[VerseRef, ...], records: tuple[EvidenceRecord, ...],
                      text: str, source_sha256: str, language: str,
                      conventions: Mapping[str, object]) -> StreamInput:
    """Construct the same validated binding used at direct immutable model boundaries."""
    fields = dict(owner_unit_id=owner_unit_id, stream_id=stream_id, purpose=purpose,
        target_references=target_references, records=records, text=text,
        routed_sfm=render_sfm_slice(records), source_sha256=source_sha256,
        language=language, conventions_sha256=_digest(conventions))
    # A temporary namespace computes the binding before the dataclass verifies it.
    from types import SimpleNamespace
    digest = _projection_binding(SimpleNamespace(**fields))
    return StreamInput(input_id='input:' + digest, projection_sha256=digest, **fields)


def _bounded_node(node: Mapping[str, object]) -> Mapping[str, object]:
    """Stop a structural heading at its first verse milestone and keep source nodes."""
    children = []
    for child in node.get('content', ()):
        if isinstance(child, Mapping) and child.get('type') == 'verse':
            break
        children.append(child)
    return dict(node, content=children)


def _node_sfm(node: object) -> str:
    """Render compiler-owned structural nodes preserving wording and semantic markers."""
    if isinstance(node, str):
        return node
    if not isinstance(node, Mapping) or not isinstance(node.get('marker'), str):
        raise ValidationError('NCA structural source node is invalid', code='NCA_TRANSPORT_INVALID')
    marker = node['marker']
    content = ''.join(_node_sfm(child) for child in node.get('content', ()))
    closing = '\\' + marker + '*' if node.get('type') in {'char', 'note'} else ''
    return '\\' + marker + (' ' + content if content or node.get('type') == 'marker' else '') + closing


def _note_binding(note: object) -> dict[str, object]:
    """Keep exact note identity, anchors, and its original offset authority together."""
    return {'note_id': note.note_id, 'marker': note.marker, 'text': note.text,
            'anchors': [ref.label() for ref in note.anchor_references], 'spans': note.content_spans}


def _source_records(unit: TargetUnit, document: Mapping[str, object]) -> tuple[EvidenceRecord, ...]:
    """Resolve projected groups from the same raw verse or bounded structural source slices."""
    locator = unit.source_locator
    if 'component_0_start' in locator:
        parts = []
        index = 0
        offset = 0
        while f'component_{index}_start' in locator:
            prefix = f'component_{index}_'
            child_locator = {key[len(prefix):]: value for key, value in locator.items()
                             if key.startswith(prefix) and key[len(prefix):] not in {'start', 'end'}}
            child_records = _source_records(replace(unit, source_locator=child_locator), document)
            child_text = '\n'.join(record.payload['projection_text'] for record in child_records)
            if locator[prefix + 'start'] != offset or locator[prefix + 'end'] != offset + len(child_text):
                raise ValidationError('NCA component offsets differ from source', code='NCA_TRANSPORT_INVALID')
            offset += len(child_text) + 1
            parts.extend(child_records)
            index += 1
        return tuple(parts)
    if 'line_start' in locator:
        matches = [raw for raw in document['sage']['verse_records']
                   if raw['line_start'] == locator['line_start'] and raw['line_end'] == locator['line_end']]
        if len(matches) != 1 or not matches[0].get('raw_usfm'):
            raise ValidationError('NCA source locator does not resolve exactly', code='NCA_TRANSPORT_INVALID')
        raw = matches[0]
        book = str(document['sage']['book_code'])
        refs = tuple(VerseRef(book, raw['chapter'], verse) for verse in range(raw['verse_start'], raw['verse_end'] + 1))
        identity = f"{unit.source_sha256}:{book}:{raw['chapter']}:{raw['number']}"
        notes = _notes(_plain(raw['content']), refs, identity)
        return (EvidenceRecord(str(document['sage']['book_code']), raw['chapter'], raw['verse_start'], raw['verse_end'],
            {'source_locator': dict(locator), 'source_nodes': raw['content'],
             'projection_text': visible_text(_plain(raw['content'])),
             'note_bindings': [_note_binding(note) for note in notes]}, raw['raw_usfm']),)
    if 'content_index' in locator and unit.target_references:
        indexes = [value for key, value in locator.items() if re.fullmatch(r'paragraph_[0-9]+_content_index', key)]
        if not indexes:
            indexes = [locator['content_index']]
        nodes = tuple(_bounded_node(document['content'][index]) for index in indexes)
        book = str(document['sage']['book_code'])
        chapter = 0
        for node in document['content'][:indexes[0] + 1]:
            if isinstance(node, Mapping) and node.get('type') == 'chapter':
                chapter = int(node['number'])
        first = unit.target_references[0] if locator.get('heading') else VerseRef(book, chapter, 0)
        texts = [visible_text(_plain(node.get('content', ()))).strip() for node in nodes]
        notes = []
        for part, node in enumerate(nodes):
            identity = (f'{unit.source_sha256}:{book}:heading:{indexes[part]}' if locator.get('heading')
                        else f'{unit.source_sha256}:{book}:{chapter}:superscription:{part}')
            notes.extend(_notes(_plain(node.get('content', ())), (first,), identity))
        if not locator.get('heading'):
            offset = 0
            for part, text in enumerate(texts):
                if (locator.get(f'paragraph_{part}_start') != offset
                        or locator.get(f'paragraph_{part}_end') != offset + len(text)):
                    raise ValidationError('NCA title offsets differ from source', code='NCA_TRANSPORT_INVALID')
                offset += len(text) + 1
        # These are real anchor coordinates; the SFM retains its structural marker
        # rather than inventing a verse milestone for headings or Psalm titles.
        sfm = '\n'.join(_node_sfm(node).rstrip('\n') for node in nodes)
        return (EvidenceRecord(first.book, first.chapter, first.verse, first.verse,
            {'source_locator': dict(locator), 'source_nodes': nodes, 'projection_text': '\n'.join(texts),
             'note_bindings': [_note_binding(note) for note in notes]}, sfm),)
    raise ValidationError('NCA target has no bounded source locator', code='NCA_TRANSPORT_INVALID')


def streams_for_target(unit: TargetUnit, document: Mapping[str, object], *, language: str,
                       conventions: Mapping[str, object], heading: bool = False) -> tuple[StreamInput, ...]:
    """Keep body, each note, and headings in their original independent offset domains."""
    records = _source_records(unit, document)
    expected_notes = [note for record in records for note in record.payload['note_bindings']]
    if (unit.main_text != '\n'.join(record.payload['projection_text'] for record in records)
            or _digest([_note_binding(note) for note in unit.notes]) != _digest(expected_notes)
            or tuple(ref for record in records for ref in record.refs) != unit.target_references):
        raise ValidationError('NCA projection differs from its source slice', code='NCA_TRANSPORT_INVALID')
    values = [make_stream_input(owner_unit_id=unit.unit_id, stream_id='main',
        purpose='HEADING_STYLE' if heading else 'BODY', target_references=unit.target_references,
        records=records, text=unit.main_text, source_sha256=unit.source_sha256,
        language=language, conventions=conventions)]
    for note in unit.notes:
        # A note can anchor elsewhere (or ambiguously); route its physical source
        # coordinates and preserve its declared assessment anchors independently.
        values.append(make_stream_input(owner_unit_id=unit.unit_id, stream_id=note.note_id,
            purpose='NOTE_STYLE', target_references=note.anchor_references,
            records=tuple(replace(record, payload=dict(record.payload, note_id=note.note_id,
                note_content_spans=note.content_spans)) for record in records),
            text=note.text, source_sha256=unit.source_sha256, language=language, conventions=conventions))
    return tuple(values)
