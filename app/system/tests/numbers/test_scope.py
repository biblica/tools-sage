"""Runtime NCA scope preserves target-local selection and package Western authority."""
import pytest

from sage.errors import ValidationError
from sage.numbers.scope import project_scope
from sage.references import parse_scope
from sage.vrs import VerseRef

from .test_projection import bundle, schema, unit


def test_target_scope_selects_shifted_western_reference_even_without_target_text(tmp_path):
    """A missing target verse cannot make expected coverage use Western verse numbers as local ones."""
    target = schema(tmp_path, 'org.vrs', '1KI 4:20 5:32\n')
    western = schema(tmp_path, 'eng.vrs', '1KI 4:34 5:18\n1KI 4:21-34 = 1KI 5:1-14\n1KI 5:1-18 = 1KI 5:15-32\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('1KI 4:21-34 = 1KI 5:1-14\n1KI 5:1-18 = 1KI 5:15-32\n')
    correct, unrelated = VerseRef('1KI', 4, 21), VerseRef('1KI', 5, 1)
    projected, expected = project_scope((), scope=parse_scope('1KI 5:1'), target_schema=target,
        western_schema=western, bundle=bundle((correct, '1KI 5:1'), (unrelated, '1KI 5:15')), mapping_path=mapping)
    assert expected == (correct,)
    assert len(projected) == 1 and projected[0].western_references == (correct,)
    assert projected[0].status == 'UNMAPPED'


def test_scoped_boundary_loads_its_complete_numeric_source_group(tmp_path):
    """A selected source boundary pulls in its required continuation without broadening unrelated coverage."""
    target = schema(tmp_path, 'org.vrs', '1SA 20:42 21:16\n')
    western = schema(tmp_path, 'eng.vrs', '1SA 20:42 21:15\n1SA 20:42 = 1SA 21:1\n1SA 21:1-15 = 1SA 21:2-16\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('1SA 20:42 = 1SA 21:1\n1SA 21:1-15 = 1SA 21:2-16\n')
    ref = VerseRef('1SA', 20, 42)
    projected, expected = project_scope((unit('1SA', 20, 42, 'Two.'), unit('1SA', 21, 1, 'Continuation.'), unit('1SA', 21, 2, 'Unrelated.')),
        scope=parse_scope('1SA 20:42'), target_schema=target, western_schema=western,
        bundle=bundle((ref, '1SA 20:42')), mapping_path=mapping)
    assert expected == (ref,)
    assert len(projected) == 1 and projected[0].status == 'READY'
    assert projected[0].target.main_text == 'Two.\nContinuation.'


def test_package_mapping_disagreement_fails_explicitly(tmp_path):
    """A configured baseline cannot silently replace the mapping supplied with reference authority."""
    target = schema(tmp_path, 'org.vrs', 'MAT 1:3\n')
    western = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:2\n')
    with pytest.raises(ValidationError) as caught:
        project_scope((unit('MAT', 1, 1),), scope=parse_scope('MAT 1'), target_schema=target,
            western_schema=western, bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:2')), mapping_path=mapping)
    assert caught.value.code == 'NCA_MAPPING_BASELINE_MISMATCH'


def test_scope_keeps_unindexed_target_streams_and_direct_registered_absence(tmp_path):
    """Complete target screening includes added numbers and explicit Western registered omissions."""
    target = schema(tmp_path, 'eng.vrs', 'NEH 7:73\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('NEH 7:1 = NEH 7:1\n')
    absence = VerseRef('NEH', 7, 68)
    projected, expected = project_scope((unit('NEH', 7, 67),), scope=parse_scope('NEH 7'),
        target_schema=target, western_schema=target, bundle=bundle((absence, None)), mapping_path=mapping)
    assert absence in expected and len(expected) == 73
    assert (VerseRef('NEH', 7, 67),) in {item.western_references for item in projected}
    assert next(item for item in projected if item.western_references == (absence,)).status == 'REGISTERED_ABSENCE'


def test_equal_forward_mapping_does_not_hide_continuation_disagreement(tmp_path):
    """Continuation semantics belong to the mapping contract even when coordinate sets agree."""
    target = schema(tmp_path, 'org.vrs', 'MAT 1:3\n')
    western = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n&MAT 1:1 = MAT 1:2\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:2\n')
    with pytest.raises(ValidationError) as caught:
        project_scope((), scope=parse_scope('MAT 1'), target_schema=target, western_schema=western,
            bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:2')), mapping_path=mapping)
    assert caught.value.code == 'NCA_MAPPING_BASELINE_MISMATCH'


def test_missing_unindexed_target_coordinate_cannot_disappear_from_coverage(tmp_path):
    """A selected but absent WIP verse is not equivalent to a screened empty numeric extraction."""
    target = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:1\n')
    projected, expected = project_scope((unit('MAT', 1, 1),), scope=parse_scope('MAT 1'),
        target_schema=target, western_schema=target, bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:1')), mapping_path=mapping)
    assert len(expected) == len(projected) == 3
    assert all(item.status == 'UNMAPPED' for item in projected if item.target.unit_id.startswith('missing:'))


@pytest.mark.parametrize('label', ['MAT 2', 'MAT 1:9', 'MAT 1:1-9'])
def test_invalid_target_scope_is_rejected_instead_of_narrowed(tmp_path, label):
    """Unknown or partially out-of-bounds scopes cannot become empty all-clear Runs."""
    target = schema(tmp_path, 'eng.vrs', 'MAT 1:3\n')
    mapping = tmp_path / 'mapping.txt'
    mapping.write_text('MAT 1:1 = MAT 1:1\n')
    with pytest.raises(ValidationError) as caught:
        project_scope((), scope=parse_scope(label), target_schema=target, western_schema=target,
            bundle=bundle((VerseRef('MAT', 1, 1), 'MAT 1:1')), mapping_path=mapping)
    assert caught.value.code == 'NCA_SCOPE_OUTSIDE_VRS'
