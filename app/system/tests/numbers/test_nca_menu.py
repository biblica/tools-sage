"""NCA menu positioning, real dispatch and independent check selection."""
from ..test_primary_workflow_menus import _center
from types import SimpleNamespace
import pytest

from sage.nca_menu import choose_checks, choose_style


def test_nca_scope_prompt_retries_invalid_input_before_creating_run(make_workspace, monkeypatch):
    """A scope typo is corrected in the prompt and only the valid request is sealed."""
    from sage.nca import create_nca_job
    from sage.nca_menu import start_run
    from .test_nca_jobs import _prepare_nca_workspace, _route
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, _ = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip='usWIP', package_id='SYNTHETIC_NCA_REFERENCE_1')
    center, output = _center(root, '7', 'MAT 0', 'matthew 01')
    # This test stops at the execution boundary; CLI lifecycle is covered separately.
    monkeypatch.setattr('sage.nca_menu.continue_run', lambda *_args: None)
    start_run(center, job)
    run = center.store.active_run(job)
    assert run.scope == 'MAT 1'
    assert run.run_id.endswith('-001')
    assert 'Chapter must be positive' in output.getvalue()


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


def test_run_preflight_shows_reference_and_language_capability(make_workspace):
    """Readiness reports scoped evidence without traversing a whole reference package."""
    from sage.nca_menu import show_preflight
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    center, output = _center(root)
    show_preflight(center, SimpleNamespace(), {'preflight': {
        'language': 'en', 'script': 'Latn', 'indexed_coordinates': 1,
        'reference_expectations': ['MAT 1:1'], 'requested_scope': 'MAT 1:1'}})
    assert 'en; Latn' in output.getvalue()
    assert 'Indexed coordinates: 1' in output.getvalue()
    assert 'SQS: NOT_APPLIED' in output.getvalue()


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


def test_single_compatible_profile_is_selected_from_project_language_namespace(make_workspace, tmp_path):
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
    center, output = _center(root, '1')
    assert choose_style(center, project) == 'fixture-en/1'
    assert 'Number Style Profile: fixture-en/1' in output.getvalue()


def test_resume_preflight_uses_one_task_before_execution(make_workspace):
    """Resume displays the sealed plan and executes the same task without another prompt."""
    from sage.nca_menu import continue_run
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    center, output = _center(root)
    center.dry_run_provider = False
    calls = []

    def controller(_job, arguments):
        """Record task identity and expose the dry-run sealed scope plan."""
        calls.append(arguments)
        if arguments[1] == 'create':
            return {'task_manifest_path': '/tmp/sealed-task.json'}
        if '--dry-run' in arguments:
            return {'status': 'READY_TO_EXECUTE', 'provider': 'sealed-provider', 'model': 'sealed-model',
                'preflight': {'requested_scope': 'MAT 2:1', 'planned_extraction_calls': 2,
                    'input_ids': ['one', 'two'], 'blocked': {'two': 'OVERSIZED'},
                    'missing_owner_ids': ['missing:MAT 2:2'], 'protected_group_ids': ['bridge'],
                    'indexed_coordinates': 1, 'unindexed_coordinates': 1,
                    'reference_expectations': ['MAT 1:1'], 'scope_expansions': [],
                    'style_profile': {'selector': 'sealed-style/1'}, 'checks': {'number_accuracy': True},
                    'language': 'en', 'script': 'Latn', 'limitations': ['REFERENCE_GAP']}}
        return {'status': 'FAILED'}

    center.controller = controller
    continue_run(center, SimpleNamespace(job_id='JOB', bindings={'wip': 'usWIP'}),
                 SimpleNamespace(run_id='RUN', scope='MAT 2:1'))
    assert [args[1] for args in calls] == ['create', 'execute', 'execute']
    assert '--dry-run' in calls[1] and '--dry-run' not in calls[2]
    assert calls[1][3] == calls[2][3] == '/tmp/sealed-task.json'
    for value in ('MAT 2:1', 'sealed-style/1', 'sealed-provider', 'OVERSIZED', 'REFERENCE_GAP',
                  'missing:MAT 2:2', 'Planning estimates', 'SQS: NOT_APPLIED'):
        assert value in output.getvalue()


@pytest.mark.parametrize('remaining', ['output', 'receipt'])
@pytest.mark.parametrize('damage', [None, 'unbacked', 'tampered'])
def test_menu_resume_recovers_partial_publication_only_through_authenticated_execution(
    make_workspace, monkeypatch, remaining, damage
):
    """Read-only preflight permits recoverable copies while execution authenticates publication."""
    from pathlib import Path
    from sage.cli import build_parser
    from sage.errors import ValidationError
    from sage.nca import create_nca_task, execute_nca_task
    from sage.nca_menu import continue_run
    from sage.numbers import replay
    from .test_nca_tasks import _run, _OfflineTasks

    root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope)
    manifest = Path(task['task_manifest_path'])
    output = manifest.parent / 'output/model-evidence.json'
    receipt = manifest.parent / 'validation/llm-execution-receipt.json'
    publication = manifest.parent / 'validation/nca-phases/publication'
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _OfflineTasks)
    write_bytes = replay.atomic_write_bytes

    def interrupt(destination, payload):
        """Leave the actual staged publication after its first canonical write."""
        write_bytes(destination, payload)
        if destination == output:
            raise RuntimeError('publication interrupted')

    monkeypatch.setattr(replay, 'atomic_write_bytes', interrupt)
    with pytest.raises(RuntimeError, match='publication interrupted'):
        execute_nca_task(config, manifest)
    monkeypatch.setattr(replay, 'atomic_write_bytes', write_bytes)
    before = (publication / 'output.json').read_bytes()
    if remaining == 'receipt':
        # The same authenticated publication can restore either missing final copy.
        receipt.write_bytes((publication / 'receipt.json').read_bytes())
        output.unlink()
    if damage == 'unbacked':
        (publication / 'manifest.json').unlink()
    elif damage == 'tampered':
        (publication / 'output.json').write_bytes(before + b' ')

    class NoCalls(_OfflineTasks):
        """Replay admitted phases without repeating any completion request."""

        def _execute_physical(self, *args, **kwargs):
            """Reject any physical call while recovering a prepared publication."""
            pytest.fail('unexpected recovery completion')

    def forbidden(*args, **kwargs):
        """Preflight cannot construct a provider even when recovery is pending."""
        pytest.fail('provider constructed during recovery preflight')

    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', NoCalls)
    center, displayed = _center(root)
    center.dry_run_provider = False
    commands, results = [], []
    monkeypatch.setattr('sage.cli._print_json', results.append)

    def controller(_job, arguments):
        """Run actual CLI handlers in-process so offline transport remains observable."""
        commands.append(arguments)
        args = build_parser().parse_args(['--settings', str(root / 'ecosystem.yml'), '--json', *arguments])
        with monkeypatch.context() as attempt:
            if '--dry-run' in arguments:
                attempt.setattr('sage.numbers.model_tasks.NcaModelTasks', forbidden)
            assert args.handler(args) == 0
        if '--dry-run' in arguments:
            assert not (receipt if remaining == 'output' else output).exists()
        return results[-1]

    center.controller = controller
    if damage:
        with pytest.raises(ValidationError) as rejected:
            continue_run(center, job, run)
        if damage == 'unbacked':
            assert rejected.value.code == 'LLM_TASK_OUTPUT_NOT_EMPTY'
        else:
            assert 'Staged final bytes differ' in str(rejected.value)
        assert not (receipt if remaining == 'output' else output).exists()
        assert [args[1] for args in commands] == (['create', 'execute'] if damage == 'unbacked'
                                                  else ['create', 'execute', 'execute'])
    else:
        continue_run(center, job, run)
        assert output.read_bytes() == before
        assert receipt.is_file()
        assert 'NCA execution: EXECUTED' in displayed.getvalue()
        assert [args[1] for args in commands] == ['create', 'execute', 'execute', 'submit']
        assert commands[1][3] == commands[2][3] == commands[3][3] == str(manifest)
