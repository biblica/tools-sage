"""NCA handlers within the existing task and resource command families."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping

from sage.errors import ValidationError
from sage.numbers.resources import import_reference, resolve_reference_package
from sage.numbers.style import import_style_profile, load_style_profile


CHECK_LABELS = {
    'number_accuracy': 'Number accuracy',
    'presentation_consistency': 'Presentation consistency',
    'footnote_review': 'Footnote review and recommendations',
}


def validate_task_options(args: argparse.Namespace) -> None:
    """Reject options whose authority or policy belongs to another workflow."""
    if args.workflow_id == 'nca':
        invalid = ('contemporary_source', 'lexical_donor', 'focus', 'check_type', 'predecessor_task', 'grammar_override_id')
    else:
        invalid = ('numbers_package', 'number_style', *CHECK_LABELS)
    if any(getattr(args, key, None) is not None for key in invalid):
        raise ValidationError('NCA task options cannot be combined with another workflow\'s options.', code='NCA_TASK_OPTIONS_INVALID')


def check_overrides(args: argparse.Namespace) -> dict[str, bool]:
    """Preserve the distinction between an absent option and explicit OFF."""
    return {key: getattr(args, key) for key in CHECK_LABELS if getattr(args, key, None) is not None}


def add_nca_task_arguments(parser: argparse.ArgumentParser) -> None:
    """Register NCA selectors and booleans without adding provider overrides."""
    parser.add_argument('--numbers-package', help='Imported NCA reference package ID for a new Job')
    parser.add_argument('--number-style', help='Required configured NCA profile ID/version for a new Job')
    for key, label in CHECK_LABELS.items():
        parser.add_argument('--' + key.replace('_', '-'), action=argparse.BooleanOptionalAction,
                            default=None, help=label + '; omitted options use saved Job defaults')


def inspect_numbers_package(config, package_id: str) -> Mapping[str, object]:
    """Qualify a local reference package without invoking the selected model."""
    library = config.data_root / 'inputs' / 'resources' / 'numbers'
    path = library / package_id
    bundle = resolve_reference_package(config, package_id)
    return {'package_id': bundle.package_id, 'sha256': bundle.sha256,
            'qualification_status': bundle.qualification_status, 'rows': len(bundle.rows),
            'diagnostics': [_plain(item) for item in bundle.diagnostics], 'path': str(path)}


def _plain(value):
    """Convert immutable domain mappings to ordinary JSON-safe containers."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def command_nca_resource(args: argparse.Namespace) -> int:
    """Import or inspect NCA resources locally using standard CLI output handling."""
    from sage.cli import _load, _print_json
    config, _ = _load(args)
    if args.resource_command == 'numbers':
        if args.nca_resource_action == 'import':
            path = import_reference(config, Path(args.archive).expanduser())
            result = inspect_numbers_package(config, path.name)
        else:
            result = inspect_numbers_package(config, args.package)
    else:
        path = import_style_profile(config, Path(args.path).expanduser())
        profile = load_style_profile(path)
        result = {'status': 'CONFIGURED', 'selector': profile.selector, 'sha256': profile.sha256, 'path': str(path)}
    if args.json:
        _print_json(result)
    else:
        for key, value in result.items():
            print(f'{key}: {value}')
    return 0


def register_nca_resources(resource_actions) -> None:
    """Add immutable numbers and style imports under the existing resource family."""
    numbers = resource_actions.add_parser('numbers', help='Import or inspect immutable NCA reference packages')
    actions = numbers.add_subparsers(dest='nca_resource_action', required=True)
    imported = actions.add_parser('import', help='Qualify and import an unchanged operator archive')
    imported.add_argument('--archive', required=True)
    imported.set_defaults(handler=command_nca_resource)
    inspected = actions.add_parser('inspect', help='Inspect package qualification and diagnostics locally')
    inspected.add_argument('--package', required=True)
    inspected.set_defaults(handler=command_nca_resource)
    style = resource_actions.add_parser('number-style', help='Import a configured NCA Number Style Profile')
    styles = style.add_subparsers(dest='nca_resource_action', required=True)
    profile = styles.add_parser('import', help='Import an operator-configured copy of the standard profile template')
    profile.add_argument('--path', required=True)
    profile.set_defaults(handler=command_nca_resource)


def command_nca_create(args: argparse.Namespace, config) -> Mapping[str, object]:
    """Create NCA work through existing Job/Run ownership and governed task dispatch."""
    from sage.jobs import JobStore
    from sage.nca import create_nca_job, create_nca_run, create_nca_task
    if args.operation != 'numbers' or args.contemporary_source or args.lexical_donor:
        raise ValidationError('NCA requires operation numbers and one WIP Project.', code='NCA_TASK_BINDING_INVALID')
    store = JobStore(config.root, config.settings_path)
    if args.job_id:
        job = store.load_job(args.job_id, tool='nca')
        if args.output_project != job.bindings['wip']:
            raise ValidationError('NCA WIP differs from the bound Job.', code='NCA_TASK_BINDING_INVALID')
        if args.numbers_package or args.number_style:
            raise ValidationError('Resource selectors belong to Job setup; revise the Job before creating a new Run.', code='NCA_TASK_BINDING_INVALID')
    else:
        if not args.numbers_package or args.run_id:
            raise ValidationError('A new NCA Job requires --numbers-package; a Run ID requires --job-id.', code='NCA_JOB_BINDING_REQUIRED')
        job = create_nca_job(config, wip=args.output_project, package_id=args.numbers_package, style_selector=args.number_style)
    overrides = check_overrides(args)
    if args.run_id:
        if overrides:
            raise ValidationError('An existing NCA Run has immutable checks.', code='NCA_POLICY_IMMUTABLE')
        run = store.load_run(job, args.run_id)
    else:
        run = create_nca_run(config, job_id=job.job_id, scope_value=args.scope, checks=overrides or None)
    return create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value=args.scope)


def scoped_preflight(inputs) -> Mapping[str, object]:
    """Describe one prepared sealed scope without requalification or provider work."""
    from sage.references import parse_scope
    from sage.numbers.execution import build_inventory, plan_extraction, reference_restrictions
    from sage.numbers.results import NCA_CAPABILITY_LIMITATION

    inventory = build_inventory(inputs)
    scope = parse_scope(inputs.requested_scope)
    refs = inputs.expected_references
    indexed = [ref.label() for ref in refs if inputs.bundle.lookup(ref) is not None]
    # Historical v1 has no batch policy: never imply it used the optimized planner.
    streams, plan = plan_extraction(inputs, inventory) if inputs.policy['schema_version'] == '2.0' else ((), None)
    owners = {stream.owner_unit_id for stream in streams if stream.purpose != 'NOTE_STYLE'}
    return {'requested_scope': inputs.requested_scope,
        'language': inputs.policy['wip']['language'], 'script': inputs.policy['wip']['script'],
        'style_profile': _plain(inputs.policy['number_style']), 'checks': _plain(inputs.policy['checks']),
        'reference_expectations': indexed, 'indexed_coordinates': len(indexed),
        'unindexed_coordinates': len(refs) - len(indexed),
        'protected_group_ids': list(inputs.expected_unit_ids),
        'planned_extraction_calls': len(plan.batches) if plan is not None else None,
        'input_ids': [stream.input_id for stream in streams],
        'blocked': dict(plan.blocked) if plan is not None else {},
        'missing_owner_ids': [unit.target.unit_id for unit in inputs.projected_units
                              if unit.target.unit_id not in owners] if plan is not None else [],
        'scope_expansions': [{'unit_id': unit.target.unit_id,
            'included_target_references': [ref.label() for ref in unit.target.target_references if not scope.contains(ref)],
            'western_references': [ref.label() for ref in unit.western_references]}
            for unit in inputs.projected_units if any(not scope.contains(ref) for ref in unit.target.target_references)],
        'limitations': list(reference_restrictions(inputs.policy)),
        'capability': NCA_CAPABILITY_LIMITATION, 'sqs_confidence_checks_applied': False}
