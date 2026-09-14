"""Bundled NCA references work without an Operator archive import."""
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from sage.errors import ValidationError
from sage.numbers.reference import load_reference
from sage.numbers.resources import reference_package_candidates, resolve_reference_package
from .test_reference import FIXTURE


def install_fixture_bundle(root: Path):
    """Install a pinned synthetic Core package separately from external localdata."""
    path = root / 'system/resources/numbers/test-bundle'
    shutil.copytree(FIXTURE, path)
    bundle = load_reference(path)
    pin = root / 'system/config/numbers-reference.json'
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text(json.dumps({'schema_version': '1.0', 'package_id': bundle.package_id,
                              'path': path.relative_to(root).as_posix(), 'sha256': bundle.sha256}))
    return path, bundle


def test_clean_install_resolves_default_without_import(tmp_path):
    """Default resolution and discovery use Core without creating localdata."""
    root = tmp_path / 'app'
    path, expected = install_fixture_bundle(root)
    config = SimpleNamespace(root=root, data_root=tmp_path / 'external-data')
    assert resolve_reference_package(config).sha256 == expected.sha256
    assert reference_package_candidates(config) == ((path.resolve(), expected),)
    assert not config.data_root.exists()


@pytest.mark.parametrize('damage', ['table', 'pin', 'escape', 'missing'])
def test_bundled_reference_fails_closed(tmp_path, damage):
    """Corruption cannot silently turn the bundled authority into an imported substitute."""
    root = tmp_path / 'app'
    path, expected = install_fixture_bundle(root)
    config = SimpleNamespace(root=root, data_root=tmp_path / 'external-data')
    assert resolve_reference_package(config, expected.package_id).sha256 == expected.sha256
    pin_path = root / 'system/config/numbers-reference.json'
    pin = json.loads(pin_path.read_text())
    if damage == 'table':
        with (path / 'reference/canonical_number_index.tsv').open('a') as output:
            output.write('corrupt\n')
    elif damage == 'pin':
        pin['sha256'] = '0' * 64
    elif damage == 'escape':
        pin['path'] = '../outside'
    else:
        shutil.rmtree(path)
    pin_path.write_text(json.dumps(pin))
    with pytest.raises(ValidationError):
        resolve_reference_package(config, expected.package_id)


def test_shipped_reference_preserves_original_table_bytes(package_root):
    """The runtime package retains tested authoritative data and original provenance."""
    pin = json.loads((package_root / 'system/config/numbers-reference.json').read_text())
    path = package_root / pin['path']
    source_manifest = json.loads((path / 'provenance/ORIGINAL_FILE_MANIFEST.json').read_text())
    original = {item['path']: item['sha256'] for item in source_manifest['files']}
    for table in (path / 'reference').iterdir():
        assert hashlib.sha256(table.read_bytes()).hexdigest() == original[table.relative_to(path).as_posix()]
    bundle = resolve_reference_package(SimpleNamespace(root=package_root))
    assert len(bundle.rows) == 6244
    assert sum(len(row.ol_values) for row in bundle.rows.values()) == 6800
    assert not list(path.rglob('*.zip'))


def test_menu_uses_only_bundled_package_without_import_prompt(make_workspace):
    """A standard one-package installation proceeds directly to profile setup."""
    from sage.nca_menu import choose_package
    from ..test_primary_workflow_menus import _center
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    _, expected = install_fixture_bundle(root)
    center, output = _center(root)

    def unexpected(*_args, **_kwargs):
        """Reject any package-choice or archive-path prompt for the bundled default."""
        pytest.fail('Bundled NCA setup requested an archive or package selection')

    center.io.choose = unexpected
    center.io.text = unexpected
    assert choose_package(center) == expected.package_id
    assert 'Reference qualification:' in output.getvalue()


def test_default_job_run_and_task_seal_core_reference(make_workspace, monkeypatch):
    """Default Job creation seals Core evidence through the normal Run/task lifecycle."""
    from sage.nca import create_nca_job, create_nca_run, create_nca_task
    from sage.numbers.execution import package_root
    from .test_nca_jobs import _prepare_nca_workspace, _route
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    path, expected = install_fixture_bundle(root)
    shutil.rmtree(config.data_root / 'inputs/resources/numbers')
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', style_selector='fixture-style/1')
    assert job.resources['numbers_package']['sha256'] == expected.sha256
    assert package_root(config, expected.package_id) == path.resolve()
    run = create_nca_run(config, job_id=job.job_id, scope_value='MAT 1:1')
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    assert Path(task['task_manifest_path']).is_file()
    assert not (config.data_root / 'inputs/resources/numbers').exists()


def test_reference_management_keeps_additional_import_accessible(make_workspace):
    """Management exposes archive import even with just the bundled package."""
    from sage.nca_menu import workflow_menu
    from ..test_primary_workflow_menus import _center
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    install_fixture_bundle(root)
    center, _ = _center(root)
    prompts = []

    def choose(title, options):
        """Open package management, then leave both menus."""
        prompts.append((title, dict(options)))
        return '4' if len(prompts) == 1 else 'B'

    center.io.choose = choose
    workflow_menu(center)
    assert prompts[1][0] == 'NCA reference package'
    assert 'Import additional NCA reference archive' in prompts[1][1].values()


def test_import_rejects_bundled_identity_conflict_before_publication(tmp_path):
    """A qualified archive cannot poison discovery by reusing the Core identity."""
    from sage.numbers.resources import import_reference
    from .test_reference import _archive_tree, _refresh_inventory
    root = tmp_path / 'app'
    _, expected = install_fixture_bundle(root)
    config = SimpleNamespace(root=root, data_root=tmp_path / 'external-data')
    changed = tmp_path / 'changed'
    shutil.copytree(FIXTURE, changed)
    manifest_path = changed / 'FILE_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['description'] = 'Conflicting distribution metadata'
    manifest_path.write_text(json.dumps(manifest))
    _refresh_inventory(changed)
    assert load_reference(changed).sha256 != expected.sha256
    archive = tmp_path / 'changed.zip'
    _archive_tree(changed, archive)
    with pytest.raises(ValidationError) as caught:
        import_reference(config, archive)
    assert caught.value.code == 'NCA_REFERENCE_PUBLICATION_CONFLICT'
    assert not (config.data_root / 'inputs/resources/numbers' / expected.package_id).exists()
    assert not (config.data_root / '.system/state/numbers/qualification').exists()
    assert len(reference_package_candidates(config)) == 1
