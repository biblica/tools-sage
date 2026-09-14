"""NCA operator flow using the existing Control Center and Job store."""
from __future__ import annotations

from pathlib import Path

from sage.errors import ValidationError
from sage.registry import load_ecosystem
from sage.references import validate_scripture_scope
from sage.nca_cli import CHECK_LABELS, inspect_numbers_package
from sage.numbers.resources import import_reference, reference_package_candidates
from sage.numbers.style import import_style_profile, style_profile_candidates


def choose_style(center, project) -> str | None:
    """Choose a guide, return empty text for no stylesheet, or None for cancellation."""
    while True:
        config = load_ecosystem(center.store.settings_path)
        script = config.language_profile(project.language_profile).script
        candidates = style_profile_candidates(config, language=project.language_code, script=script, project=project.project_id)
        options = [(str(index), item.selector) for index, item in enumerate(candidates, 1)]
        import_key = str(len(options) + 1)
        skip_key = str(len(options) + 2)
        options.extend(((import_key, 'Import configured Number Style Profile'),
                        (skip_key, 'Continue without stylesheet'), ('B', 'Back')))
        center.io.write('An optional Number Style Profile adds approved rule checks to the Number Usage Report.')
        center.io.write('Template: system/config/profiles/numbers/number-style-template.yml')
        choice = center.io.choose('NCA Number Style Profile', options)
        if choice == 'B':
            return None
        if choice == skip_key:
            return ''
        if choice == import_key:
            raw = center.io.text('Configured profile path', required=False).strip()
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
        center.io.write(f"NCA reference package: {package_id}")
        center.io.write(f"Reference qualification: {status['qualification_status']}")
        center.io.write(f"Numeric reference coverage: {status['rows']} indexed rows")
        for diagnostic in status['diagnostics']:
            center.io.write(str(diagnostic))
        return package_id


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


def choose_checks(center, job) -> dict[str, bool] | None:
    """Offer independent pre-Run switches and an optional approved stylesheet."""
    defaults = {key: True for key in CHECK_LABELS}
    defaults.update(job.defaults.get('checks', {}))
    checks = dict(defaults)
    while True:
        center.io.write(f"Number Style Profile: {job.profiles.get('number_style', 'NOT CONFIGURED')}")
        choices = [(str(index), f"{center.localizer.text(label)}: {'ON' if checks[key] else 'OFF'}") for index, (key, label) in enumerate(CHECK_LABELS.items(), 1)]
        choices.extend((('4', 'Restore saved check defaults'), ('5', 'Change Number Style Profile'),
                        ('6', 'Save check defaults'), ('7', 'Continue with selected checks'), ('B', 'Back')))
        choice = center.io.choose('NCA Run checks', choices)
        if choice == 'B':
            return None
        if choice in {'1', '2', '3'}:
            key = tuple(CHECK_LABELS)[int(choice) - 1]
            checks[key] = not checks[key]
        elif choice == '4':
            checks = dict(defaults)
        elif choice == '5':
            config = load_ecosystem(center.store.settings_path)
            selector = choose_style(center, config.project(job.bindings['wip']))
            if selector is not None:
                job = center.store.revise_job(job, profiles={'number_style': selector} if selector else {})
        elif not any(checks.values()):
            center.io.write('Enable at least one NCA check.')
        elif choice == '6':
            job = center.store.revise_job(job, defaults={**job.defaults, 'checks': checks})
            defaults = dict(checks)
        elif choice == '7':
            return checks


def start_run(center, job) -> None:
    """Create and execute the same governed task used by the canonical CLI."""
    from sage.nca import create_nca_run
    checks = choose_checks(center, job)
    if checks is None:
        return
    scope = center.io.text('Scripture scope', required=False,
                          validator=lambda value: validate_scripture_scope(value, workflow='nca').label()).strip()
    if not scope:
        return
    config = load_ecosystem(center.store.settings_path)
    run = create_nca_run(config, job_id=job.job_id, scope_value=scope, checks=checks)
    continue_run(center, job, run)


def continue_run(center, job, run) -> None:
    """Resume sealed NCA inputs and checks without consulting mutable Job defaults."""
    scope = run.scope
    task = center.controller(job, ['task', 'create', '--workflow', 'nca', '--operation', 'numbers',
                                  '--wip', job.bindings['wip'], '--scope', scope,
                                  '--job-id', job.job_id, '--run-id', run.run_id])
    manifest = str(task.get('task_manifest') or task.get('task_manifest_path') or '')
    if not manifest:
        raise ValidationError('NCA task creation did not return its manifest.', code='NCA_TASK_MANIFEST_MISSING')
    arguments = ['task', 'execute', '--task', manifest]
    preflight = center.controller(job, arguments + ['--dry-run'])
    show_preflight(center, job, preflight)
    result = preflight
    if not center.dry_run_provider and preflight.get('status') == 'READY_TO_EXECUTE':
        result = center.controller(job, arguments)
    center.io.write(f"NCA execution: {result.get('status', 'UNKNOWN')}")
    if not center.dry_run_provider and result.get('status') == 'EXECUTED':
        finalized = center.controller(job, ['task', 'submit', '--task', manifest])
        center.io.write(f"NCA report: {finalized.get('report_path') or finalized.get('status', 'UNKNOWN')}")
    center.io.pause()


def show_preflight(center, job, result) -> None:
    """Display controller-derived sealed scope estimates without reloading Job resources."""
    from sage.nca_reporting import _exact
    from sage.human_output import catalogue_text

    text = lambda key: catalogue_text(center.localizer.language, key)
    plan = result.get('preflight', {})
    center.io.write(text('report.nca.preflight'))
    if plan:
        values = (
            ('input_language', f"{plan.get('language')}; {plan.get('script')}"),
            ('requested_scope', plan.get('requested_scope')),
            ('mandatory_profile', plan.get('style_profile', {}).get('selector')),
            ('checks', plan.get('checks')),
            ('reference_expectations', plan.get('reference_expectations')),
            ('indexed_coordinates', plan.get('indexed_coordinates')),
            ('unindexed_coordinates', plan.get('unindexed_coordinates')),
            ('protected_groups', plan.get('protected_group_ids')),
            ('planned_extraction_calls', plan.get('planned_extraction_calls')),
            ('planned_inputs', len(plan.get('input_ids', ()))),
            ('blocked_inputs', plan.get('blocked')),
            ('missing_owners', plan.get('missing_owner_ids')),
            ('scope_expansion', plan.get('scope_expansions')),
            ('limitations', plan.get('limitations')),
        )
        for key, value in values:
            center.io.write(f"{text('report.nca.' + key)}: {_exact(value)}")
    center.io.write(f"{text('report.nca.model_identity')}: {result.get('provider', 'NOT RECORDED')}/{result.get('model', 'NOT RECORDED')}")
    center.io.write(text('report.nca.planning_notice'))
    center.io.write(text('report.nca.capability_limitation'))
    center.io.write('SQS: NOT_APPLIED')


def job_menu(center, job) -> None:
    """Operate one NCA Job without entering RTC or STC execution branches."""
    while True:
        job = center.store.load_job(job.job_id, tool='nca')
        run = center.store.active_run(job)
        choice = center.io.choose('NUMBER CONSISTENCY & ACCURACY (NCA)',
                                  (('1', 'Run SAGE NUMBERS CHECK'), ('2', 'Reports and history'),
                                   ('3', 'NCA check defaults and profile'), ('4', 'Recovery and diagnostics'),
                                   ('5', 'Manage Job'), ('B', 'Back')),
                                  context=(f'Job: {job.job_id}', f"WIP Project: {job.bindings['wip']}", f"Number Style Profile: {job.profiles.get('number_style', 'NOT CONFIGURED')}"))
        if choice == 'B':
            return
        if choice == '1':
            if run is None:
                start_run(center, job)
            else:
                center.io.write(f'Resuming NCA Run: {run.run_id}')
                continue_run(center, job, run)
        elif choice == '2':
            center.reports_menu(job)
        elif choice == '3':
            choose_checks(center, job)
        elif choice == '4':
            center.recovery_menu(job)
        elif choice == '5':
            if center._job_settings_menu(job):
                return


def workflow_menu(center) -> None:
    """Create, select and operate independent NCA Jobs using shared discovery."""
    while True:
        choice = center.io.choose('NUMBER CONSISTENCY & ACCURACY (NCA)',
                                  (('1', 'Open active NCA job'), ('2', 'Choose active NCA job'),
                                   ('3', 'Add NCA job <WIP PROJECT>'), ('4', 'NCA reference packages'), ('B', 'Back')))
        if choice == 'B':
            return
        try:
            if choice == '4':
                choose_package(center, manage=True)
                continue
            if choice == '3':
                job = create_job(center)
            elif choice == '2':
                job = center.choose_job('nca')
            else:
                job = center.store.active_job('nca') or center.choose_job('nca')
            if job is not None:
                job_menu(center, job)
        except ValidationError as exc:
            center.io.write(str(exc))
            if exc.next_action:
                center.io.write(exc.next_action)
            center.io.pause()
