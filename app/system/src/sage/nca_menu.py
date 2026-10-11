"""NCA operator flow using the existing Control Center and Job store."""
from __future__ import annotations

from pathlib import Path

from sage.errors import ValidationError
from sage.registry import load_ecosystem
from sage.nca_cli import CHECK_LABELS, inspect_numbers_package
from sage.numbers.resources import import_reference, reference_package_candidates
from sage.numbers.style import import_style_profile, style_profile_candidates

# Data-integrity violations detected while executing a sealed NCA task (a
# corrupted or tampered checkpoint, an output that no longer matches its
# execution receipt). These must remain hard failures -- a soft, resumable
# framing (the default for provider/transient failures) would misrepresent
# a detected integrity breach as an ordinary retryable hiccup.
NCA_INTEGRITY_FAILURE_CODES = frozenset({
    'LLM_TASK_OUTPUT_NOT_EMPTY',
    'NCA_PHASE_CHECKPOINT_INVALID',
    'EXECUTION_RECEIPT_OUTPUT_MISMATCH',
})


def choose_style(center, project) -> str | None:
    """Choose a guide, return empty text for no stylesheet, or None for cancellation."""
    while True:
        config = load_ecosystem(center.store.settings_path)
        script = config.language_profile(project.language_profile).script
        candidates = style_profile_candidates(config, language=project.language_code, script=script, project=project.project_id)
        options = [(str(index), item.selector) for index, item in enumerate(candidates, 1)]
        skip_key = str(len(options) + 1)
        import_key = str(len(options) + 2)
        options.extend(((skip_key, 'Use standard language profile data'),
                        (import_key, 'Upload style data from template'), ('B', 'Back')))
        center.io.write('A Number Style Profile is optional. Without one, NCA uses the standard language profile '
                        'data and reconstructs the translation\'s own number style from the text.')
        center.io.write('Template: system/config/profiles/numbers/number-style-template.yml')
        choice = center.io.choose('NCA Number Style Profile', options)
        if choice == 'B':
            return None
        if choice == skip_key:
            return ''
        if choice == import_key:
            raw = center.io.text('Style data file (filled-in template)', required=False).strip()
            if not raw:
                return None
            import_style_profile(config, Path(raw).expanduser())
        else:
            selector = candidates[int(choice) - 1].selector
            center.io.write(f'Number Style Profile: {selector}')
            return selector


def choose_package(center, *, manage: bool = False) -> str | None:
    """Show qualification diagnostics before binding an immutable package."""
    while True:
        config = load_ecosystem(center.store.settings_path)
        candidates = reference_package_candidates(config)
        if len(candidates) == 1 and not manage:
            package_id = candidates[0][1].package_id
        else:
            options = [(str(index), f'{bundle.package_id} [{bundle.qualification_status}]') for index, (_, bundle) in enumerate(candidates, 1)]
            import_key = str(len(options) + 1)
            options.extend(((import_key, 'Import additional NCA reference archive'), ('B', 'Back')))
            choice = center.io.choose('NCA reference package', options)
            if choice == 'B':
                return None
            if choice == import_key:
                raw = center.io.text('NCA reference archive path', required=False).strip()
                if not raw:
                    return None
                path = import_reference(config, Path(raw).expanduser())
                package_id = path.name
            else:
                package_id = candidates[int(choice) - 1][1].package_id
        status = inspect_numbers_package(config, package_id)
        shown = center.__dict__.setdefault('_nca_packages_shown', set())
        if manage or (package_id, status['sha256']) not in shown:
            # once per package per session; package management always shows it
            shown.add((package_id, status['sha256']))
            center.io.write(f"NCA reference package: {package_id}")
            center.io.write(f"Reference qualification: {status['qualification_status']}")
            center.io.write(f"Numeric reference coverage: {status['rows']} indexed rows")
            for diagnostic in status['diagnostics']:
                center.io.write(_diagnostic_line(diagnostic))
        return package_id


def _diagnostic_line(diagnostic) -> str:
    """One readable line for a package diagnostic (the full record stays in the package report)."""
    count = diagnostic.get('count', diagnostic.get('differing_rows'))
    detail = diagnostic.get('disposition') or diagnostic.get('message') or ''
    return (f"- {diagnostic.get('severity', 'NOTE')} {diagnostic.get('code', 'DIAGNOSTIC')}"
            + (f" ({count} verses)" if count is not None else "") + (f": {detail}" if detail else ""))


def create_job(center):
    """Resolve one WIP, qualified package and optional profile before persistence."""
    from sage.nca import create_nca_job
    project = center.choose_or_add_resource('Start new NCA review <WIP PROJECT>', 'WIP')
    if project is None:
        return None
    package_id = choose_package(center)
    if package_id is None:
        return None
    selector = choose_style(center, project)
    if selector is None:
        return None
    config = load_ecosystem(center.store.settings_path)
    center.io.write(f'Input language: {project.language_code}; script: {config.language_profile(project.language_profile).script}')
    center.io.write('Numeric interpretation depends on the selected model; unsupported evidence remains unassessed.')
    center._write_job_ai_routing('nca', None)
    job = create_nca_job(load_ecosystem(center.store.settings_path), wip=project.project_id, package_id=package_id, style_selector=selector or None)
    center.store.set_active_job('nca', job.job_id)
    return job


def saved_checks(job) -> dict[str, bool]:
    """Return the Job's saved NCA check defaults, with every unsaved check ON."""
    checks = {key: True for key in CHECK_LABELS}
    checks.update({key: value for key, value in job.defaults.get('checks', {}).items() if key in checks})
    return checks


def choose_checks(center, job, *, for_run: bool = True) -> dict[str, bool] | None:
    """Offer independent check switches and an optional approved stylesheet.

    ``for_run=False`` is the NCA defaults setting screen: it saves defaults and returns,
    without the "Continue with selected checks" Run action.
    """
    defaults = saved_checks(job)
    checks = dict(defaults)
    while True:
        center.io.write(f"Number Style Profile: {job.profiles.get('number_style', 'NOT CONFIGURED')}")
        names = tuple(CHECK_LABELS)
        restore, style, save, proceed = (str(len(names) + offset) for offset in range(1, 5))
        choices = [(str(index), f"{center.localizer.text(label)}: {'ON' if checks[key] else 'OFF'}")
                   for index, (key, label) in enumerate(CHECK_LABELS.items(), 1)]
        choices.extend(((restore, 'Restore saved check defaults'), (style, 'Change Number Style Profile'),
                        (save, 'Save check defaults')))
        if for_run:
            choices.append((proceed, 'Continue with selected checks'))
        choices.append(('B', 'Back'))
        choice = center.io.choose('NCA Run checks' if for_run else 'NCA defaults setting', choices)
        if choice == 'B':
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            key = names[int(choice) - 1]
            checks[key] = not checks[key]
        elif choice == restore:
            checks = dict(defaults)
        elif choice == style:
            config = load_ecosystem(center.store.settings_path)
            selector = choose_style(center, config.project(job.bindings['wip']))
            if selector is not None:
                job = center.store.revise_job(job, profiles={'number_style': selector} if selector else {})
        elif not any(checks.values()):
            center.io.write('Enable at least one NCA check.')
        elif choice == save:
            job = center.store.revise_job(job, defaults={**job.defaults, 'checks': checks})
            defaults = dict(checks)
            if not for_run:
                center.io.write('NCA defaults saved. They apply to every later Run of this Job.')
        elif choice == proceed:
            return checks


def start_run(center, job, *, checks: dict[str, bool] | None = None) -> None:
    """Create and execute the same governed task used by the canonical CLI.

    Supplied ``checks`` (the Job's saved defaults) skip the per-Run check screen.
    """
    from sage.nca import create_nca_run
    if checks is None:
        checks = choose_checks(center, job)
    if checks is None:
        return
    if not any(checks.values()):
        center.io.write('Enable at least one NCA check in NCA defaults setting.')
        center.io.pause()
        return
    scope = center._select_scripture_scope(job, primary_binding='wip')
    if scope is None:
        return
    config = load_ecosystem(center.store.settings_path)
    run = create_nca_run(config, job_id=job.job_id, scope_value=scope, checks=checks)
    center.continue_run(job, run)


def continue_run(center, job, run):
    """Resume the sealed NCA task through the same governed helpers BIC/RTC/STC use."""
    tasks = center._tasks_by_operation(run)
    numbers_tasks = tasks.get('numbers', [])
    if not numbers_tasks:
        run, result = center._create_task(job, run, 'numbers', scope=run.scope)
        if result.get('status') in {'PARTITIONED', 'COMPOSITE'}:
            raise ValidationError(
                'NCA does not support partitioned or composite task creation.',
                code='NCA_TASK_PARTITIONING_UNSUPPORTED',
            )
        manifest = str(result.get('manifest_path') or '')
        if not manifest:
            raise ValidationError('NCA task creation did not return its manifest.', code='NCA_TASK_MANIFEST_MISSING')
        manifest_path = center._manifest_path(manifest)
    else:
        manifest_path, _manifest, state = numbers_tasks[-1]
        if state == 'FINALIZED':
            center.io.write('NCA Run is already complete.')
            center.io.pause()
            return center.store.update_run(run, status='COMPLETE', current_stage='COMPLETE')

    def preview(preflight: dict) -> bool:
        """Show the sealed preflight and gate real execution on its readiness."""
        show_preflight(center, job, preflight)
        return preflight.get('status') == 'READY_TO_EXECUTE'

    # NCA's execute step is itself idempotent (it recognizes and safely resumes
    # partially-published output), so unlike BIC/RTC/STC it must always be tried
    # rather than gated on _task_state's generic "output file already exists"
    # shortcut, which would otherwise skip straight to submission and never let a
    # partially-published run finish publishing.
    executed = center._launch_task(
        job, run, manifest_path, preview=preview, raise_codes=NCA_INTEGRITY_FAILURE_CODES,
    )
    if executed and center._task_state(manifest_path)[0] == 'OUTPUT_READY':
        run = center._submit_task(job, run, manifest_path)
        run = center.store.update_run(run, status='COMPLETE', current_stage='COMPLETE')
    return run


_PREFLIGHT_SCREEN_LIMIT = 5


def _bounded_preflight_value(value):
    """Cap a list/dict preflight field for the screen; the file always keeps the full value."""
    if isinstance(value, list) and len(value) > _PREFLIGHT_SCREEN_LIMIT:
        return [*value[:_PREFLIGHT_SCREEN_LIMIT], f"... and {len(value) - _PREFLIGHT_SCREEN_LIMIT} more"], True
    if isinstance(value, dict) and len(value) > _PREFLIGHT_SCREEN_LIMIT:
        head = dict(list(value.items())[:_PREFLIGHT_SCREEN_LIMIT])
        head[f"... and {len(value) - _PREFLIGHT_SCREEN_LIMIT} more"] = "SEE FULL PREFLIGHT FILE"
        return head, True
    return value, False


def show_preflight(center, job, result) -> None:
    """Display a screen-bounded preflight summary; the unbounded detail is written to a file."""
    from sage.atomic import atomic_write_json
    from sage.nca_reporting import _exact
    from sage.human_output import catalogue_text

    text = lambda key: catalogue_text(center.localizer.language, key)
    plan = result.get('preflight', {})
    center.io.write(text('report.nca.preflight'))
    if plan:
        plan_path = job.controller_state_root / "last-preflight.json"
        atomic_write_json(plan_path, plan)
        # The screen shows what the operator confirms; batching, coverage counters and group ids
        # stay in the preflight file. Inputs that cannot be extracted are shown only when present.
        values = (
            ('input_language', f"{plan.get('language')}; {plan.get('script')}"),
            ('requested_scope', plan.get('requested_scope')),
            ('mandatory_profile', plan.get('style_profile', {}).get('selector')),
            ('checks', plan.get('checks')),
            ('blocked_inputs', plan.get('blocked') or None),
            ('missing_owners', plan.get('missing_owner_ids') or None),
            ('limitations', plan.get('limitations')),
        )
        for key, value in values:
            if value is None and key in {'blocked_inputs', 'missing_owners'}:
                continue
            bounded, _ = _bounded_preflight_value(value)
            center.io.write(f"{text('report.nca.' + key)}: {_exact(bounded)}")
        center.io.write(f"Full preflight detail: {plan_path}")
    center.io.write(f"{text('report.nca.model_identity')}: {result.get('provider', 'NOT RECORDED')}/{result.get('model', 'NOT RECORDED')}")
    center.io.write(text('report.nca.planning_notice'))
    center.io.write(text('report.nca.capability_limitation'))
    center.io.write('SQS: NOT_APPLIED')


def job_menu(center, job) -> None:
    """Operate one NCA Job in the standard [ NCA <WIP> ] Job menu shape."""
    from sage.job_menus import open_job
    open_job(center, job)


def workflow_menu(center) -> None:
    """Open the NCA Job home in the standard Job menu shape."""
    from sage.job_menus import job_home
    job_home(center, 'nca')
