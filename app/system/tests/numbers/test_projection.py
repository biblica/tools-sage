"""NCA Western lookup preserves equivalence groups and absent coverage."""
from pathlib import Path

import pytest

from sage.numbers.models import ReferenceBundle, ReferenceRow, TargetUnit
from sage.numbers.projection import project_units
from sage.vrs import VerseRef, parse_vrs_file


def schema(tmp_path, name, text):
    """Parse one synthetic VRS fixture through the production parser."""
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return parse_vrs_file(path, schema_id=name, canonical_id='org.vrs')


def unit(book, chapter, verse, text='Three.', end=None):
    """Build a locatable synthetic target record without parsing assumptions."""
    return TargetUnit(f'{book}:{chapter}:{verse}', tuple(VerseRef(book, chapter, v) for v in range(verse, (end or verse) + 1)), text, (), '0' * 64, {'line_start': verse, 'line_end': end or verse})


def bundle(*rows):
    """Supply immutable synthetic reference rows for projection tests."""
    return ReferenceBundle('projection-fixture', '0' * 64,
                           {ref: ReferenceRow(ref, ol, 'HEB', '', (), '', (), {})
                            for ref, ol in rows}, {}, {}, {}, {}, 'QUALIFIED')


def test_bridge_is_one_comparison_group(tmp_path):
    """Bridge is one comparison group."""
    eng = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    projected, = project_units((unit('MAT', 1, 1, end=2),), target_schema=eng, western_schema=eng)
    assert projected.western_references == (VerseRef('MAT', 1, 1), VerseRef('MAT', 1, 2))
    assert projected.target.main_text == 'Three.'
    assert projected.status == 'READY'
    assert projected.precision == 'EQUIVALENCE_GROUP'


def test_repeated_psalm_mapping_preserves_all_canonical_atoms(tmp_path):
    """Repeated psalm mapping preserves all canonical atoms."""
    eng = schema(tmp_path, 'eng.vrs', 'PSA 51:19\nPSA 51:0 = PSA 51:1\nPSA 51:0 = PSA 51:2\nPSA 51:1-19 = PSA 51:3-21\n')
    projected, = project_units((unit('PSA', 51, 0),), target_schema=eng, western_schema=eng)
    assert projected.western_references == (VerseRef('PSA', 51, 0),)
    assert projected.canonical_references == (VerseRef('PSA', 51, 1), VerseRef('PSA', 51, 2))


def test_nonwestern_parts_are_grouped_once(tmp_path):
    """Nonwestern parts are grouped once."""
    eng = schema(tmp_path, 'eng.vrs', 'MAT 1:2\nMAT 1:1 = MAT 1:1-2\nMAT 1:2 = MAT 1:3\n')
    org = schema(tmp_path, 'org.vrs', 'MAT 1:3\n')
    projected, = project_units((unit('MAT', 1, 1, 'Three.'), unit('MAT', 1, 2, 'Four.')), target_schema=org, western_schema=eng)
    assert projected.western_references == (VerseRef('MAT', 1, 1),)
    assert projected.target.main_text == 'Three.\nFour.'
    assert projected.target.target_references == (VerseRef('MAT', 1, 1), VerseRef('MAT', 1, 2))
    assert projected.status == 'READY'


def test_missing_part_of_equivalence_group_is_ambiguous(tmp_path):
    """Missing part of equivalence group is ambiguous."""
    eng = schema(tmp_path, 'eng.vrs', 'MAT 1:1\nMAT 1:1 = MAT 1:1-2\n')
    org = schema(tmp_path, 'org.vrs', 'MAT 1:2\n')
    projected, = project_units((unit('MAT', 1, 2),), target_schema=org, western_schema=eng)
    assert projected.status == 'AMBIGUOUS'


def test_invalid_target_and_excluded_coordinate_are_unmapped(tmp_path):
    """Invalid target and excluded coordinate are unmapped."""
    eng = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    wip = schema(tmp_path, 'custom.vrs', 'MAT 1:3\n#! -MAT 1:2\n')
    records = project_units((unit('MAT', 1, 2), unit('MAT', 1, 4)), target_schema=wip, western_schema=eng)
    assert [record.status for record in records] == ['UNMAPPED', 'UNMAPPED']


def test_expected_missing_verse_is_not_silently_skipped(tmp_path):
    """Expected missing verse is not silently skipped."""
    eng = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    records = project_units((unit('MAT', 1, 1),), target_schema=eng, western_schema=eng, expected_western_references=(VerseRef('MAT', 1, 1), VerseRef('MAT', 1, 2)))
    missing = records[1]
    assert missing.western_references == (VerseRef('MAT', 1, 2),)
    assert missing.target.target_references == ()
    assert missing.target.main_text == ''
    assert missing.status == 'UNMAPPED'


def test_registered_ol_absence_never_uses_identity_fallback(tmp_path):
    """Registered ol absence never uses identity fallback."""
    eng = schema(tmp_path, 'eng.vrs', 'NEH 7:73\nNEH 7:69-73 = NEH 7:68-72\n')
    org = schema(tmp_path, 'org.vrs', 'NEH 7:72\n')
    absent = VerseRef('NEH', 7, 68)
    records = project_units((unit('NEH', 7, 68, 'Other verse.'),), target_schema=org, western_schema=eng, bundle=bundle((absent, None)), expected_western_references=(absent,))
    omitted = next(record for record in records if record.western_references == (absent,))
    assert omitted.status == 'REGISTERED_ABSENCE'
    assert omitted.canonical_references == ()
    assert omitted.target.main_text == ''
    assert records[0].western_references == (VerseRef('NEH', 7, 69),)


def test_boundary_group_includes_numeric_source_and_continuation(tmp_path):
    """Boundary group includes numeric source and continuation."""
    eng = schema(tmp_path, 'eng.vrs', '1SA 20:42 21:15\n1SA 20:42 = 1SA 21:1\n1SA 21:1-15 = 1SA 21:2-16\n')
    org = schema(tmp_path, 'org.vrs', '1SA 20:42 21:16\n')
    western = VerseRef('1SA', 20, 42)
    records = project_units((unit('1SA', 20, 42, 'Three.'), unit('1SA', 21, 1, 'Continuation.')), target_schema=org, western_schema=eng, bundle=bundle((western, '1SA 20:42')))
    combined, = records
    assert combined.western_references == (western,)
    assert combined.canonical_references == (VerseRef('1SA', 20, 42), VerseRef('1SA', 21, 1))
    assert combined.target.main_text == 'Three.\nContinuation.'
    assert combined.status == 'READY'


def test_continuation_alone_cannot_pass_boundary_accuracy(tmp_path):
    """Continuation alone cannot pass boundary accuracy."""
    eng = schema(tmp_path, 'eng.vrs', '1CH 12:40\n1CH 12:4 = 1CH 12:5\n')
    org = schema(tmp_path, 'org.vrs', '1CH 12:41\n')
    ref = VerseRef('1CH', 12, 4)
    record, = project_units((unit('1CH', 12, 5, 'Continuation.'),), target_schema=org, western_schema=eng, bundle=bundle((ref, '1CH 12:4')))
    assert record.status == 'AMBIGUOUS'


def test_actual_western_shifts_preserve_numeric_source_identity():
    """Actual western shifts preserve numeric source identity."""
    root = Path(__file__).resolve().parents[3]
    paths = list((root / 'system').rglob('eng.vrs'))
    eng = parse_vrs_file(paths[0], schema_id='eng.vrs', canonical_id='org.vrs')
    cases = [(unit('1KI', 4, 26), VerseRef('1KI', 5, 6)), (unit('1KI', 5, 11), VerseRef('1KI', 5, 25)), (unit('PSA', 60, 0), VerseRef('PSA', 60, 2))]
    for target, canonical in cases:
        projected, = project_units((target,), target_schema=eng, western_schema=eng)
        assert canonical in projected.canonical_references
        assert projected.western_references == target.target_references


def test_missing_western_verse_uses_only_explicitly_anchored_notes(tmp_path):
    """Missing western verse uses only explicitly anchored notes."""
    from sage.numbers.target import target_units
    from sage.usj import compile_usfm_text

    eng = schema(tmp_path, 'eng.vrs', 'NEH 7:73\n')
    absent = VerseRef('NEH', 7, 68)
    for anchor, expected_notes in [('7:68', 1), ('7:69', 0), ('7:68, 69', 0)]:
        usj = compile_usfm_text(f'\\id NEH Fixture\n\\c 7\n\\v 69 Text.\\f + \\fr {anchor} \\ft Other reading.\\f*\n')
        targets = target_units(usj, source_sha256='0' * 64)
        records = project_units(targets, target_schema=eng, western_schema=eng, bundle=bundle((absent, None)), expected_western_references=(absent,))
        omitted = records[-1]
        assert omitted.status == 'REGISTERED_ABSENCE'
        assert len(omitted.target.notes) == expected_notes


def test_direct_western_boundary_preserves_stored_source_attribution(tmp_path):
    """Direct western boundary preserves stored source attribution."""
    eng = schema(tmp_path, 'eng.vrs', '1CH 12:40\n1CH 12:4 = 1CH 12:5\n')
    ref = VerseRef('1CH', 12, 4)
    reference = bundle((ref, '1CH 12:4'))
    record, = project_units((unit('1CH', 12, 4),), target_schema=eng, western_schema=eng, bundle=reference)
    assert record.status == 'READY'
    assert record.western_references == (ref,)
    assert reference.lookup(ref).ol_reference == '1CH 12:4'
    assert set(record.canonical_references) == {ref, VerseRef('1CH', 12, 5)}


def test_boundary_continuation_without_reference_context_is_not_ready(tmp_path):
    """Boundary continuation without reference context is not ready."""
    eng = schema(tmp_path, 'eng.vrs', '1CH 12:40\n1CH 12:4 = 1CH 12:5\n')
    org = schema(tmp_path, 'org.vrs', '1CH 12:41\n')
    record, = project_units((unit('1CH', 12, 5),), target_schema=org, western_schema=eng)
    assert record.status == 'AMBIGUOUS'


def test_projection_rejects_unqualified_reference_bundle(tmp_path):
    """Projection rejects unqualified reference bundle."""
    from dataclasses import replace
    import pytest
    from sage.errors import ValidationError

    eng = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    reference = replace(bundle((VerseRef('MAT', 1, 1), 'MAT 1:1')), qualification_status='DIAGNOSTIC')
    with pytest.raises(ValidationError) as exc:
        project_units((unit('MAT', 1, 1),), target_schema=eng, western_schema=eng, bundle=reference)
    assert exc.value.code == 'NCA_REFERENCE_NOT_QUALIFIED'


@pytest.mark.parametrize(('mapping', 'expected'), [
    ('MAT 1:1 = MAT 1:9-10\n', (VerseRef('MAT', 1, 9), VerseRef('MAT', 1, 10))),
    ('MAT 1:1 = MAT 9:1\nMAT 1:1 = MAT 10:1\n', (VerseRef('MAT', 9, 1), VerseRef('MAT', 10, 1))),
])
def test_target_mapping_retains_numeric_western_order(tmp_path, mapping, expected):
    """One target mapping orders two-digit verses and chapters by their coordinates."""
    eng = schema(tmp_path, 'eng.vrs', 'MAT 1:10 9:1 10:1\n')
    target = schema(tmp_path, 'custom.vrs', 'MAT 1:1\n' + mapping)
    projected, = project_units((unit('MAT', 1, 1),), target_schema=target, western_schema=eng)
    assert projected.western_references == expected
    assert projected.target_western_mapping == {'MAT 1:1': tuple(ref.label() for ref in expected)}
    assert projected.status == 'READY'
