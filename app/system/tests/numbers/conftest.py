"""Explicit diagnostic-only NCA fixtures for branches without resource lookup."""
import pytest

from sage.numbers.models import ReferenceBundle


@pytest.fixture
def empty_bundle():
    """Provide no authority for tests that only apply an already selected policy."""
    return ReferenceBundle('empty-diagnostic', '0' * 64, {}, {}, {}, {}, {}, 'DIAGNOSTIC')
