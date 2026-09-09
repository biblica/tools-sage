"""Offline acceptance through canonical import, task, Run and report interfaces."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import zipfile

import pytest

from sage.cli import build_parser
from sage.jobs import JobStore
from sage.numbers.model_tasks import CorrespondenceEvidence
from sage.numbers.models import Extraction, NumericExpression
from sage.numbers.results import NCA_CAPABILITY_LIMITATION
from sage.storage import storage_layout

from .test_nca_jobs import REFERENCE_FIXTURE, _prepare_nca_workspace, _route
from .test_nca_tasks import _OfflineTasks, _Receipt


def _inventory(root: Path) -> dict[str, str]:
    """Capture exact source bytes for the no-input-writes acceptance contract."""
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


class _NumericTasks(_OfflineTasks):
    """Supply validated synthetic phase evidence at the provider boundary."""

    calls = 0
    unsupported = False

    def extract(self, unit, *, language, style_profile):
        """Interpret only target content, without any expected OL or NIV values."""
        type(self).calls += 1
        assert language == 'en' and style_profile
        if self.unsupported:
            value = Extraction((), 'UNSUPPORTED', ('Fixture language understanding unavailable',))
        else:
            expressions = tuple(NumericExpression((Fraction(number),), 'CARDINAL', str(number),
                (unit.main_text.index(str(number)), unit.main_text.index(str(number)) + 1), role=role,
                expression_id=f'target-{number}', role_spans=((0, len(unit.main_text)),))
                for number, role in ((3, 'men'), (4, 'women')))
            value = Extraction(expressions, 'COMPLETE')
        return SimpleNamespace(value=value, receipt=_Receipt('EXTRACTION'))

    def correspond(self, unit, target, reference, *, reading_context=None):
        """Bind independently typed OL expressions to the target referents."""
        assert reference.ol_text == 'three and four'
        source = tuple(NumericExpression((Fraction(number),), 'CARDINAL', surface,
            (reference.ol_text.index(surface), reference.ol_text.index(surface) + len(surface)),
            role=role, expression_id=f'ol-{number}', stream_id='ol', role_spans=((0, len(reference.ol_text)),))
            for number, surface, role in ((3, 'three', 'men'), (4, 'four', 'women')))
        return SimpleNamespace(value=CorrespondenceEvidence(source, target, 'COMPLETE'), receipt=_Receipt('CORRESPONDENCE'))


@pytest.mark.parametrize('unsupported', [False, True])
def test_import_to_report_is_read_only_reproducible_and_explicit_about_limits(make_workspace, monkeypatch, tmp_path, unsupported):
    """A full canonical operator flow seals evidence and reports limited assessment honestly."""
    root = make_workspace(configured=True, qualification_status='VALIDATED')
    config, style_bytes = _prepare_nca_workspace(root)
    scripture = config.project('usWIP').path / '41MAT.SFM'
    scripture.write_text('\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 3 men and 4 women.\n', encoding='utf-8')
    source_before = _inventory(config.project('usWIP').path)
    library = storage_layout(root).resources_root / 'numbers'
    shutil.rmtree(library / 'SYNTHETIC_NCA_REFERENCE_1')
    archive = tmp_path / 'reference.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        for path in REFERENCE_FIXTURE.rglob('*'):
            if path.is_file():
                output.write(path, 'SYNTHETIC_NCA_REFERENCE_1/' + path.relative_to(REFERENCE_FIXTURE).as_posix())
    profile_source = tmp_path / 'configured.yml'
    profile_source.write_bytes(style_bytes)
    style_path = storage_layout(root).styleguides_root / 'numbers/fixture-style/1.yml'
    style_path.unlink()
    outputs = []
    monkeypatch.setattr('sage.cli._print_json', lambda value: outputs.append(value))
    _route(monkeypatch)
    _NumericTasks.calls = 0
    _NumericTasks.unsupported = unsupported
    monkeypatch.setattr('sage.numbers.model_tasks.NcaModelTasks', _NumericTasks)

    def command(*arguments):
        """Execute real canonical handlers using the isolated operator configuration."""
        args = build_parser().parse_args(['--settings', str(root / 'ecosystem.yml'), '--json', *arguments])
        assert args.handler(args) == 0
        return outputs[-1]

    imported = command('resource', 'numbers', 'import', '--archive', str(archive))
    inspected = command('resource', 'numbers', 'inspect', '--package', imported['package_id'])
    assert inspected['qualification_status'] == 'QUALIFIED_WITH_DIAGNOSTICS'
    assert inspected['rows'] == 3 and inspected['diagnostics']
    package_before = _inventory(library)
    command('resource', 'number-style', 'import', '--path', str(profile_source))
    created = command('task', 'create', '--workflow', 'nca', '--operation', 'numbers', '--wip', 'usWIP',
                      '--scope', 'MAT 1:1', '--numbers-package', imported['package_id'], '--number-style', 'fixture-style/1')
    manifest = created['task_manifest_path']
    assert command('task', 'execute', '--task', manifest)['status'] == 'EXECUTED'
    completed = command('task', 'submit', '--task', manifest)
    report = Path(completed['report_path'])
    result = Path(completed['result_path'])
    report_bytes, result_bytes = report.read_bytes(), result.read_bytes()
    document = json.loads(result_bytes)
    assert document['limitations']['capability'] == NCA_CAPABILITY_LIMITATION
    assert NCA_CAPABILITY_LIMITATION in report.read_text(encoding='utf-8')
    assert document['limitations']['sqs_confidence_checks_applied'] is False
    assert len(document['units']) == 1
    unit = document['units'][0]
    assert unit['final_outcome'] == ('INSUFFICIENT_EVIDENCE' if unsupported else 'PASS_AUTHORITY1')
    assert unit['footnote']['status'] == ('NOT_ASSESSED' if unsupported else 'NOT_REQUIRED')
    assert document['model_receipts']['EXTRACTION']
    store = JobStore(root, root / 'ecosystem.yml')
    job = store.load_job(document['provenance']['job_id'], tool='nca')
    run = store.load_run(job, document['provenance']['run_id'])
    assert run.status == 'COMPLETE'
    # Mutable operator defaults cannot rewrite a completed Run or trigger repeat model work.
    store.revise_job(job, defaults={'checks': {'number_accuracy': False, 'presentation_consistency': True, 'footnote_review': False}})
    calls = _NumericTasks.calls
    command('task', 'execute', '--task', manifest)
    from sage.nca import finalize_nca_run
    finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    assert _NumericTasks.calls == calls
    assert (report.read_bytes(), result.read_bytes()) == (report_bytes, result_bytes)
    assert _inventory(config.project('usWIP').path) == source_before
    assert _inventory(library) == package_before
