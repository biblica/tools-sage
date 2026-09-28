"""Explicit diagnostic-only NCA fixtures for branches without resource lookup."""
import pytest

from sage.numbers.models import ReferenceBundle, TargetUnit
from sage.vrs import VerseRef


def make_units(count: int) -> tuple[TargetUnit, ...]:
    """Build small target units for deterministic batch tests.

    Synthetic "MAT 5:v" identities beyond v=32 do not correspond to a real verse
    (Matthew 5 has 32 verses) -- batch-planning mechanics don't validate against
    real canon length, and tests needing genuine long-chapter coverage should
    measure against real compiled USJ instead (see test_batching.py's real-book
    measurement tests).
    """
    assert 1 <= count <= 256
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
