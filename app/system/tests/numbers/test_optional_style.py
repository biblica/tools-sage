"""Optional stylesheet choices remain explicit throughout the NCA lifecycle."""
import json
from pathlib import Path

import pytest
import yaml

from sage.errors import ValidationError
from sage.jobs import JobStore
from sage.nca import create_nca_job, create_nca_run, create_nca_task, execute_nca_task
from sage.numbers.execution import prepare_execution_inputs
from sage.numbers.policy import load_nca_run_snapshot
from sage.numbers.style import import_style_profile, resolve_style_profile, validate_style_profile
from sage.storage import storage_layout

from ..test_primary_workflow_menus import _center
from .test_nca_jobs import _prepare_nca_workspace, _route
from .test_nca_tasks import _OfflineTasks


def test_no_style_execution_rules_are_unassessed_and_cannot_be_imported(make_workspace, tmp_path):
    """An internal no-rules context must never become an approved library guide."""
    config, _ = _prepare_nca_workspace(make_workspace(configured=True, qualification_status='VALIDATED'))
    profile = validate_style_profile(None)
    assert profile['profile'] == {'status': 'NOT_CONFIGURED'}
    assert all(rule['status'] == 'NOT_SPECIFIED' for rule in profile['rules'].values())
    raw = {'profile': dict(profile['profile']), 'rules': {key: dict(value) for key, value in profile['rules'].items()}}
    path = tmp_path / 'not-a-guide.yml'
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError):
        import_style_profile(config, path)
    path.write_text('null\n')
    with pytest.raises(ValidationError):
        import_style_profile(config, path)


def test_omitted_style_selector_never_selects_installed_guide(make_workspace):
    """A newly installed guide cannot turn an omitted selector into approval."""
    config, _ = _prepare_nca_workspace(make_workspace(configured=True, qualification_status='VALIDATED'))
    assert resolve_style_profile(config, None, language='en', script='Latn') is None
    for selector in ('', 'missing/1', '../../profile'):
        with pytest.raises(ValidationError):
            resolve_style_profile(config, selector, language='en', script='Latn')


def test_no_style_run_and_task_keep_sealed_absence_after_later_import(make_workspace, monkeypatch):
    """Jobs without guides execute and resume without fabricated or late-bound rules."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, guide_bytes = _prepare_nca_workspace(root)
    (storage_layout(root).styleguides_root / 'numbers/fixture-style/1.yml').unlink()
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1')
    assert job.profiles == {}
    run = create_nca_run(config, job_id=job.job_id, scope_value='MAT 1')
    before = (run.root / 'check-policy.json').read_bytes()
    policy = load_nca_run_snapshot(run.root)
    assert policy['number_style'] == {'selector': None, 'sha256': None, 'profile_id': None,
                                       'version': None, 'language': 'en', 'script': 'Latn'}
    assert policy['checks']['presentation_consistency'] is True
    assert not (run.root / 'profiles/number-style.yml').exists()
    source = root / 'later-guide.yml'
    source.write_bytes(guide_bytes)
    import_style_profile(config, source)
    loaded = JobStore(root, config.settings_path).load_job(job.job_id, tool='nca')
    assert loaded.profiles == {}
    inputs = prepare_execution_inputs(config, loaded, run, policy)
    assert inputs.style_profile['profile']['status'] == 'NOT_CONFIGURED'
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    path = Path(task['task_manifest_path'])
    manifest = json.loads(path.read_text())
    assert 'NUMBER_STYLE' not in manifest['resource_bindings']
    assert 'number_style' not in manifest['packets']
    assert 'number_style' not in manifest['resource_fingerprints']
    assert not any(item['path'].endswith('profiles/number-style.yml') for item in manifest['allowed_reads'])
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    assert execute_nca_task(config, path, dry_run=True)['status'] == 'READY_TO_EXECUTE'
    assert execute_nca_task(config, path)['status'] == 'EXECUTED'
    assert execute_nca_task(config, path)['status'] == 'EXECUTED'
    assert (run.root / 'check-policy.json').read_bytes() == before


def test_no_guide_extraction_preserves_ambiguous_interpretation():
    """Absence supplies no separator convention and cannot upgrade partial model evidence."""
    from sage.numbers import extraction
    from .test_batch_extraction import batch_fixture
    batch = batch_fixture(('1,234 people',))
    payload = extraction.build_batch_extraction_payload(
        batch, parsing_conventions=extraction._parsing_conventions(validate_style_profile(None)))
    assert payload['parsing_conventions'] == {}
    interpreted = extraction._validated_extraction_item(
        {'status': 'PARTIAL', 'limitations': ['Grouping or decimal separator is unresolved'], 'values': []})
    assert interpreted.status == 'PARTIAL'
    assert interpreted.values == ()
    assert interpreted.limitations == ('Grouping or decimal separator is unresolved',)


def test_menu_can_remove_selected_guide_before_run(make_workspace):
    """Choosing no stylesheet clears the existing Job selection without disabling checks."""
    from sage.nca_menu import choose_checks
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1',
                         style_selector='fixture-style/1')
    center, _ = _center(root, '5', '3', '7')
    assert choose_checks(center, job) == {'number_accuracy': True, 'presentation_consistency': True,
                                         'footnote_review': True}
    assert center.store.load_job(job.job_id, tool='nca').profiles == {}


def test_menu_reinitialization_accepts_job_without_guide(make_workspace):
    """Reopening setup validates the NCA resources without requiring a style object."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1')
    center, _ = _center(root)
    state = center.ensure_initialized(job, force=True)
    assert state['state'] == 'READY'
    assert state['number_style'] is None


def test_menu_skip_creates_job_while_back_does_not(make_workspace, monkeypatch):
    """No stylesheet is a real setup choice, distinct from backing out of Job setup."""
    from sage.nca_menu import create_job
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    monkeypatch.setattr('sage.nca_menu.choose_package', lambda _center: 'SYNTHETIC_NCA_REFERENCE_1')
    for choice, expected in (('a', None), ('3', {})):
        center, _ = _center(root, choice)
        monkeypatch.setattr(center, 'choose_or_add_resource', lambda *_args: config.project('usWIP'))
        monkeypatch.setattr(center, '_write_job_ai_routing', lambda *_args: None)
        job = create_job(center)
        if expected is None:
            assert job is None
            assert center.store.active_job('nca') is None
        else:
            assert job.profiles == expected


def test_cli_omitted_guide_creates_task_with_no_style_binding(make_workspace, monkeypatch):
    """The canonical CLI can create a governed task with the stylesheet flag omitted."""
    from sage.cli import build_parser
    from sage.nca_cli import command_nca_create
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    _route(monkeypatch)
    args = build_parser().parse_args(['task', 'create', '--workflow', 'nca', '--operation', 'numbers',
        '--wip', 'usWIP', '--scope', 'MAT 1', '--numbers-package', 'SYNTHETIC_NCA_REFERENCE_1'])
    created = command_nca_create(args, config)
    raw = json.loads(Path(created['task_manifest_path']).read_text())
    assert 'NUMBER_STYLE' not in raw['resource_bindings']
    assert 'number_style' not in raw['packets']


def test_cli_existing_job_rejects_explicit_empty_style_selector(make_workspace, monkeypatch):
    """An explicitly supplied invalid selector cannot silently become omission on resume."""
    from sage.cli import build_parser
    from sage.nca_cli import command_nca_create
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1')
    args = build_parser().parse_args(['task', 'create', '--workflow', 'nca', '--operation', 'numbers',
        '--wip', 'usWIP', '--scope', 'MAT 1', '--job-id', job.job_id, '--number-style', ''])
    with pytest.raises(ValidationError) as caught:
        command_nca_create(args, config)
    assert caught.value.code == 'NCA_TASK_BINDING_INVALID'


@pytest.mark.parametrize('has_guide', [False, True])
def test_menu_explicitly_skips_style_and_back_cancels(make_workspace, has_guide):
    """Continue without stylesheet remains available even with one candidate."""
    from sage.nca_menu import choose_style
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    if not has_guide:
        (storage_layout(root).styleguides_root / 'numbers/fixture-style/1.yml').unlink()
    center, output = _center(root, '3' if has_guide else '2')
    assert choose_style(center, config.project('usWIP')) == ''
    assert 'Continue without stylesheet' in output.getvalue()
    center, _ = _center(root, 'a')
    assert choose_style(center, config.project('usWIP')) is None
