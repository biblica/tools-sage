"""Release qualification requires real supplied reference evidence, never a skip."""
import importlib.util
from pathlib import Path

import pytest

from sage.errors import ValidationError
from .test_reference import FIXTURE


def qualification_tool():
    """Load the standalone qualification command without executing its CLI."""
    path = Path(__file__).resolve().parents[2] / 'tools/validate_numbers_reference.py'
    spec = importlib.util.spec_from_file_location('validate_numbers_reference', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_reference_is_usable_but_not_real_release_evidence():
    """The CI fixture can pass integrity while failing the real-package release gate."""
    tool = qualification_tool()
    assert tool.qualify(FIXTURE, release=False)['status'] == 'PASS'
    with pytest.raises(ValidationError):
        tool.qualify(FIXTURE, release=True)


def test_release_mode_fails_when_authorized_package_is_absent(tmp_path):
    """Missing authorized evidence is a blocking outcome, not xfail or skipped work."""
    with pytest.raises(ValidationError):
        qualification_tool().qualify(tmp_path / 'missing', release=True)
