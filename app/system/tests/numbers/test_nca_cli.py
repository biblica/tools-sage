"""Canonical NCA command arguments and local resource inspection."""
from argparse import Namespace

import pytest

from sage.cli import build_parser
from sage.errors import ValidationError
from sage.nca_cli import check_overrides, inspect_numbers_package


def test_task_create_accepts_independent_nca_policy_and_resource_selectors():
    """The existing task family carries NCA setup and explicit check switches."""
    args = build_parser().parse_args(['task', 'create', '--workflow', 'nca', '--operation', 'numbers', '--wip', 'usWIP', '--scope', 'MAT 1:1', '--numbers-package', 'fixture', '--number-style', 'fixture-en/1', '--no-presentation-consistency'])
    assert args.workflow_id == 'nca'
    assert args.operation == 'numbers'
    assert check_overrides(args) == {'presentation_consistency': False}
    assert args.numbers_package == 'fixture'


def test_numbers_import_and_inspection_use_existing_resource_family():
    """Operator resources have explicit local import and inspection commands."""
    imported = build_parser().parse_args(['resource', 'numbers', 'import', '--archive', '/tmp/example.zip'])
    inspected = build_parser().parse_args(['resource', 'numbers', 'inspect', '--package', 'fixture'])
    profile = build_parser().parse_args(['resource', 'number-style', 'import', '--path', '/tmp/profile.yml'])
    assert imported.archive == '/tmp/example.zip'
    assert inspected.package == 'fixture'
    assert profile.path == '/tmp/profile.yml'


def test_omitted_policy_does_not_override_saved_defaults():
    """CLI absence and explicit false remain distinct when creating a Run."""
    assert check_overrides(Namespace()) == {}
    assert check_overrides(Namespace(number_accuracy=True, presentation_consistency=None, footnote_review=False)) == {'number_accuracy': True, 'footnote_review': False}


def test_inspection_rejects_missing_and_escaping_packages(make_workspace):
    """Package selectors cannot escape the local immutable resource library."""
    from sage.registry import load_ecosystem
    config = load_ecosystem(make_workspace(configured=True) / 'ecosystem.yml')
    for package_id in ('missing', '../outside'):
        with pytest.raises(ValidationError):
            inspect_numbers_package(config, package_id)


@pytest.mark.parametrize('workflow,operation,extra', [
    ('rtc', 'rtc', ['--numbers-package', 'fixture']),
    ('stc', 'stc', ['--no-number-accuracy']),
    ('nca', 'numbers', ['--focus', 'unrelated']),
    ('nca', 'numbers', ['--predecessor-task', 'unrelated']),
    ('nca', 'numbers', ['--grammar-override-id', 'unrelated']),
])
def test_task_creation_rejects_cross_workflow_options(make_workspace, monkeypatch, workflow, operation, extra):
    """Accepted parser options cannot silently change meaning in another workflow."""
    from sage.cli import command_act_create
    from sage.registry import load_ecosystem
    config = load_ecosystem(make_workspace(configured=True) / 'ecosystem.yml')
    args = build_parser().parse_args(['task', 'create', '--workflow', workflow, '--operation', operation, '--wip', 'usWIP', '--scope', 'MAT 1'] + extra)
    monkeypatch.setattr('sage.cli._load', lambda _args: (config, None))
    with pytest.raises(ValidationError, match='NCA'):
        command_act_create(args)
