"""NCA menu positioning, real dispatch and independent check selection."""
from ..test_primary_workflow_menus import _center
from types import SimpleNamespace
import pytest

from sage.nca_menu import choose_checks, choose_style


@pytest.mark.parametrize('status', ['CANCELLED', 'UNKNOWN', 'FAILED', 'BLOCKED', None])
def test_incomplete_execution_never_submits(make_workspace, status):
    """Only completed model execution may enter governed submission."""
    from sage.nca_menu import continue_run
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    center, _ = _center(root)
    calls = []

    def controller(_job, arguments):
        """Record control flow and return an incomplete execution outcome."""
        calls.append(arguments[1])
        return {'task_manifest_path': '/tmp/task.json'} if arguments[1] == 'create' else {'status': status}

    center.controller = controller
    center.dry_run_provider = False
    continue_run(center, SimpleNamespace(job_id='NCA-test', bindings={'wip': 'usWIP'}), SimpleNamespace(run_id='run', scope='MAT 1'))
    assert calls == ['create', 'execute']


def test_shared_nca_snapshot_and_frozen_tui_navigation(make_workspace):
    """Shared discovery serves NCA while the experimental TUI keeps its five entries."""
    from sage.ui_services import OperatorUIService
    from sage.tui import TOP_LEVEL_SECTIONS
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    service = OperatorUIService(root=root, settings_path=root / 'ecosystem.yml')
    assert service.section_snapshot('nca')['jobs'] == []
    assert 'nca_job' in service.main_snapshot()
    assert len(TOP_LEVEL_SECTIONS) == 5
    assert TOP_LEVEL_SECTIONS[-1].view_id == 'configure'


def test_run_preflight_shows_reference_and_language_capability(make_workspace, monkeypatch):
    """Readiness exposes package coverage and model limits alongside the input language."""
    from sage.nca_menu import show_preflight
    from .test_nca_jobs import _prepare_nca_workspace
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    _prepare_nca_workspace(root)
    center, output = _center(root)
    calls = []
    monkeypatch.setattr(center, '_write_job_ai_routing', lambda tool, run: calls.append((tool, run)))
    job = SimpleNamespace(bindings={'wip': 'usWIP'}, resources={'numbers_package': {'package_id': 'SYNTHETIC_NCA_REFERENCE_1'}})
    show_preflight(center, job)
    assert 'Input language: en; script: Latn' in output.getvalue()
    assert 'Numeric reference coverage:' in output.getvalue()
    assert 'unsupported evidence remains unassessed' in output.getvalue()
    assert calls == [('nca', None)]


def test_nca_reinitialization_uses_own_resource_contract(make_workspace, monkeypatch):
    """Recovery validates NCA prerequisites without entering another workflow initializer."""
    from sage.nca import create_nca_job
    from .test_nca_jobs import _prepare_nca_workspace
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1', style_selector='fixture-style/1')
    center, _ = _center(root)

    def unexpected(*_args, **_kwargs):
        """Fail if generic workspace initialization is dispatched for NCA."""
        pytest.fail('NCA recovery entered generic workspace initialization')

    monkeypatch.setattr(center, 'controller', unexpected)
    assert center.ensure_initialized(job, force=True)['state'] == 'READY'


def test_main_menu_places_nca_at_five_and_maintenance_at_six(make_workspace):
    """Existing workflow keys remain stable while NCA occupies its approved slot."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    center, output = _center(root, 'c')
    assert center.main_menu() == 'X'
    text = output.getvalue()
    assert '5. Number Consistency & Accuracy (NCA)' in text
    assert '6. SAGE Maintenance' in text
    assert 'NCA active Job:' in text
    assert '4. Source Text Correspondence (STC)' in text


def test_main_menu_dispatches_five_and_six_to_correct_workflows(make_workspace, monkeypatch):
    """Displayed numbering and executed menu destinations agree."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    center, output = _center(root)
    choices = iter(('5', '6', 'X'))
    calls = []
    monkeypatch.setattr(center, 'main_menu', lambda: next(choices))
    monkeypatch.setattr(center, '_setup_model_probe', lambda *args, **kwargs: {'ready': True})
    monkeypatch.setattr(center, '_render_startup_report', lambda *args: None)
    monkeypatch.setattr(center, 'nca_menu', lambda: calls.append('nca'), raising=False)
    monkeypatch.setattr(center, 'system_configuration_menu', lambda: calls.append('maintenance'))
    assert center.run() == 0
    assert calls == ['nca', 'maintenance']


def test_each_check_toggles_independently_and_saved_defaults_restore(make_workspace):
    """The presentation switch does not alter numeric or footnote assessment."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    job = SimpleNamespace(profiles={'number_style': 'fixture/1'}, defaults={})
    center, output = _center(root, '2', '7')
    assert choose_checks(center, job) == {'number_accuracy': True, 'presentation_consistency': False, 'footnote_review': True}
    assert 'Number Style Profile: fixture/1' in output.getvalue()
    center, output = _center(root, '1', '3', '4', '7')
    assert all(choose_checks(center, job).values())


def test_all_off_cannot_start_and_cancellation_is_honored(make_workspace):
    """The menu keeps an all-OFF policy pending until corrected or cancelled."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    job = SimpleNamespace(profiles={'number_style': 'fixture/1'}, defaults={})
    center, output = _center(root, '1', '2', '3', '7', 'a')
    assert choose_checks(center, job) is None
    assert 'Enable at least one NCA check.' in output.getvalue()


def test_nca_workflow_menu_can_cancel_before_creating_any_job(make_workspace):
    """Opening the new workflow and backing out has no lifecycle side effect."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    center, output = _center(root, 'a')
    center.nca_menu()
    assert 'Add NCA JOB <WIP PROJECT>' in output.getvalue()


def test_single_compatible_profile_is_reused_from_project_language_namespace(make_workspace, tmp_path):
    """Project script comes from its configured language namespace during guide choice."""
    import yaml
    from sage.registry import load_ecosystem
    from sage.numbers.style import import_style_profile
    from .test_style import configured_profile
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config = load_ecosystem(root / 'ecosystem.yml')
    project = config.project('usWIP')
    raw = configured_profile()
    raw['profile'].update(language=project.language_code, script=config.language_profile(project.language_profile).script)
    source = tmp_path / 'profile.yml'
    source.write_text(yaml.safe_dump(raw))
    import_style_profile(config, source)
    center, output = _center(root)
    assert choose_style(center, project) == 'fixture-en/1'
    assert 'Number Style Profile: fixture-en/1' in output.getvalue()
