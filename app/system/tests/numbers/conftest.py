"""Explicit diagnostic-only NCA fixtures for branches without resource lookup."""
import pytest

from sage.numbers.models import ReferenceBundle, TargetUnit
from sage.vrs import VerseRef


def make_units(count: int) -> tuple[TargetUnit, ...]:
    """Build small target units for deterministic batch tests."""
    assert 1 <= count <= 32
    return tuple(
        TargetUnit(f"MAT 5:{v}", (VerseRef("MAT", 5, v),),
                   "Three men.", (), "0" * 64,
                   {"line_start": v, "line_end": v})
        for v in range(1, count + 1)
    )


@pytest.fixture
def empty_bundle():
    """Provide no authority for tests that only apply an already selected policy."""
    return ReferenceBundle('empty-diagnostic', '0' * 64, {}, {}, {}, {}, {}, 'DIAGNOSTIC')
