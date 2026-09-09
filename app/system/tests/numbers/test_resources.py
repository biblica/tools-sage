"""Local NCA package selection never silently substitutes another identity."""
import shutil
from types import SimpleNamespace

import pytest

from sage.errors import ValidationError
from sage.numbers.reference import load_reference
from sage.numbers.resources import reference_package_candidates, resolve_reference_package
from .test_reference import FIXTURE


def test_package_selection_validates_identity_and_bytes(tmp_path):
    """An imported package is requalified and a corrupt published sibling is visible."""
    config = SimpleNamespace(data_root=tmp_path)
    package_id = load_reference(FIXTURE).package_id
    library = tmp_path / 'inputs/resources/numbers'
    path = library / package_id
    shutil.copytree(FIXTURE, path)
    assert resolve_reference_package(config, package_id).package_id == package_id
    assert reference_package_candidates(config)[0][0] == path
    (library / '.staging').mkdir()
    assert len(reference_package_candidates(config)) == 1
    (path / 'FILE_MANIFEST.json').write_text('{}')
    with pytest.raises(ValidationError):
        reference_package_candidates(config)


@pytest.mark.parametrize('selector', ['missing', '../outside', '/absolute'])
def test_package_selector_cannot_escape_or_select_missing_resources(tmp_path, selector):
    """Selection requires a real safe imported package directory."""
    with pytest.raises(ValidationError):
        resolve_reference_package(SimpleNamespace(data_root=tmp_path), selector)


def test_visible_non_directory_publication_is_reported_as_invalid(tmp_path):
    """A damaged visible publication is an error instead of disappearing from selection."""
    library = tmp_path / 'inputs/resources/numbers'
    library.mkdir(parents=True)
    (library / 'damaged-package').write_text('not a package directory')
    with pytest.raises(ValidationError):
        reference_package_candidates(SimpleNamespace(data_root=tmp_path))
