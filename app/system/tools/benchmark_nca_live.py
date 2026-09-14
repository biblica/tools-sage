"""Run separately initiated paired NCA measurements on an existing governed WIP snapshot."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from time import perf_counter_ns

import benchmark_nca as baseline
from benchmark_nca_qualification import governance
from sage.jobs import JobStore
from sage.registry import load_ecosystem
from sage.numbers.engine import evaluate_prepared_run, evaluate_optimized_run, _unit_findings
from sage.numbers.execution import prepare_execution_inputs
from sage.numbers.model_tasks import NcaModelTasks
from sage.numbers.policy import _plain, load_nca_run_snapshot
from sage.numbers.replay import PhaseStore
from sage.numbers.results import NCA_CAPABILITY_LIMITATION
from sage.numbers.results_v2 import comparison_view, group_findings
from sage.numbers.telemetry import summarize_calls


FINDING_FIELDS = ('code', 'category', 'severity', 'target_references', 'western_references',
    'ol_references', 'selected_reading', 'source_ids', 'evidence_ids')


CRITICAL_CATEGORIES = frozenset({'omission', 'extra_number', 'referent', 'bridge'})


def live_input_identity(inputs):
    """Bind exact sealed source, reference, mapping, style, scope, policy and projection identities."""
    value = {'policy_sha256': baseline._sha256(inputs.policy_bytes),
        'source_files': dict(inputs.policy['wip']['files']),
        'package': inputs.policy['reference_package'], 'style': inputs.policy['number_style'],
        'scope': inputs.requested_scope, 'expected_ids': inputs.expected_unit_ids,
        'expected_references': [x.label() for x in inputs.expected_references],
        'projection': [{'unit_id': x.target.unit_id, 'source_sha256': x.target.source_sha256,
            'status': x.status, 'precision': x.precision, 'mapping': x.target_western_mapping,
            'target': [ref.label() for ref in x.target.target_references],
            'western': [ref.label() for ref in x.western_references],
            'canonical': [ref.label() for ref in x.canonical_references]} for x in inputs.projected_units]}
    return baseline._sha256(baseline._canonical_bytes(_plain(value)))


def reviewed_labels(path, inputs):
    """Require operator-reviewed exact labels for every protected body and style unit."""
    content = path.read_bytes()
    labels = json.loads(content)
    if (not isinstance(labels, dict) or labels.get('schema_version') != '1.0'
            or not isinstance(labels.get('reviewed_by'), str) or not labels['reviewed_by'].strip()
            or not isinstance(labels.get('reviewed_at'), str) or not labels['reviewed_at'].strip()
            or labels.get('input_sha256') != live_input_identity(inputs)):
        raise ValueError('Reviewed labels must bind the exact current input identity')
    cases = labels.get('cases')
    if (not isinstance(cases, list) or len(cases) != len(inputs.expected_unit_ids)
            or {x.get('unit_id') for x in cases if isinstance(x, dict)} != set(inputs.expected_unit_ids)):
        raise ValueError('Reviewed labels must cover every selected unit exactly once')
    targets = {x.target.unit_id: x.target for x in inputs.projected_units}
    targets.update({x.unit_id: x for x in inputs.style_units})
    for case in cases:
        if (not isinstance(case.get('categories'), list) or not case['categories']
                or any(not isinstance(x, str) or not x for x in case['categories'])
                or not isinstance(case.get('expressions'), list)
                or not isinstance(case.get('outcome'), str) or not case['outcome']
                or not isinstance(case.get('findings'), list)
                or not isinstance(case.get('finding_codes'), list)
                or any(not isinstance(x, str) or not x for x in case['finding_codes'])):
            raise ValueError('Reviewed labels lack typed extraction or finding evidence')
        for expression in case['expressions']:
            baseline._golden_expression(expression)
            typed = baseline._expression(expression, expression_id='label', stream_id='main')
            if targets[case['unit_id']].main_text[typed.span[0]:typed.span[1]] != typed.surface:
                raise ValueError('Reviewed labels differ from the exact selected source surface')
        if any(not isinstance(item, dict) or set(item) != set(FINDING_FIELDS) for item in case['findings']):
            raise ValueError('Reviewed labels require exact finding attribution fields')
        if sorted(item['code'] for item in case['findings']) != sorted(case['finding_codes']):
            raise ValueError('Reviewed labels contain inconsistent finding codes')
    return labels, baseline._sha256(content)


def case_metrics(view, found, label):
    """Compare exact typed values, roles and finding multiplicity without sharing source surfaces."""
    observed = [baseline._golden_expression(baseline._plain_expression(x)) for x in view.extraction.expressions]
    expected = [baseline._golden_expression(x) for x in label['expressions']]
    actual_counter = Counter(baseline._canonical_bytes(x) for x in observed)
    expected_counter = Counter(baseline._canonical_bytes(x) for x in expected)
    matched = sum((actual_counter & expected_counter).values())
    known = view.extraction.status == 'COMPLETE'
    codes = sorted(x['code'] for x in found)
    actual_findings = [_plain({field: item[field] for field in FINDING_FIELDS}) for item in found]
    matches_findings = Counter(baseline._canonical_bytes(x) for x in actual_findings) == Counter(
        baseline._canonical_bytes(x) for x in label['findings'])
    return {'unit_id': label['unit_id'], 'categories': label['categories'],
        'extraction_status': view.extraction.status,
        'extraction_recall': (matched / len(expected) if expected else 1.0) if known else None,
        'extraction_precision': (matched / len(observed) if observed else float(not expected)) if known else None,
        'exact_values_types_roles': observed == expected if known else None,
        'finding_correctness': matches_findings and view.final_outcome == label['outcome'],
        'outcome': view.final_outcome, 'finding_codes': codes,
        'unresolved': not known or view.final_outcome in {'INSUFFICIENT_EVIDENCE', 'REFERENCE_NOT_INDEXED'},
        'observed_findings_sha256': baseline._sha256(baseline._canonical_bytes(actual_findings)),
        'observed_extraction_sha256': baseline._sha256(baseline._canonical_bytes(observed)),
        'expected_extraction_sha256': baseline._sha256(baseline._canonical_bytes(expected))}


def run_strategy(config, inputs, labels, strategy, directory):
    """Use the ordinary authenticated route and real physical NCA phase boundary once."""
    started = perf_counter_ns()
    tasks = NcaModelTasks(config, expected_route_id=inputs.policy['model_route']['route_id'])
    if dict(tasks.route_snapshot) != dict(inputs.policy['model_route']):
        raise ValueError('Current provider route differs from the selected sealed Run')
    if strategy == 'baseline':
        result = evaluate_prepared_run(inputs, model_tasks=tasks, run_id='live-benchmark')
        units = [(x, _unit_findings(x, bundle=inputs.bundle, checks=inputs.policy['checks'])) for x in result.units]
    else:
        result = evaluate_optimized_run(inputs, model_tasks=tasks, run_id='live-benchmark',
            phase_store=PhaseStore(directory, task_fingerprint=live_input_identity(inputs)))
        units = [(comparison_view(x, checks=inputs.policy['checks']),
            group_findings(x, bundle=inputs.bundle, checks=inputs.policy['checks'])) for x in result.groups]
    # Raw requests/responses stay confined to this benchmark-owned local session.
    raw = [{'measurement': asdict(x.measurement), 'request': _plain(x.request),
        'raw_response': x.raw_response, 'response_identity': _plain(x.response_identity)} for x in tasks.attempts]
    (directory / 'provider-evidence.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2) + '\n')
    by_id = {x['unit_id']: x for x in labels['cases']}
    metrics = [case_metrics(view, found, by_id[view.projected.target.unit_id]) for view, found in units]
    return {'strategy': strategy, 'input_sha256': live_input_identity(inputs),
        'governance': governance(tasks, strategy), 'calls': summarize_calls(tuple(x.measurement for x in tasks.attempts)),
        'elapsed_ms': (perf_counter_ns() - started) // 1_000_000, 'coverage': _plain(result.coverage), 'cases': metrics,
        'unresolved_rate': sum(x['unresolved'] for x in metrics) / len(metrics) if metrics else None,
        'raw_response_sha256': [baseline._sha256(x.raw_response.encode()) if x.raw_response is not None else None for x in tasks.attempts]}


def run_live(args):
    """Validate explicit selection before creating a separate runtime-only paired session."""
    required = ('settings', 'job', 'run', 'project', 'scope', 'labels')
    if any(not getattr(args, name, None) for name in required) or args.repetitions < 3:
        raise ValueError('Live benchmark requires settings, job, run, project, scope, reviewed labels and at least three paired repetitions')
    config = load_ecosystem(args.settings)
    destination = args.receipt.expanduser().resolve()
    runtime = (config.runtime_state_root / 'nca-benchmarks').resolve()
    if not destination.is_relative_to(runtime) or destination.exists():
        raise ValueError('Live receipt requires a new path under runtime_state_root/nca-benchmarks')
    store = JobStore(config.root, config.settings_path)
    job = store.load_job(args.job, tool='nca')
    run = store.load_run(job, args.run)
    if job.bindings['wip'] != args.project or run.scope != args.scope:
        raise ValueError('Selected Project/scope differs from the explicit NCA Run')
    policy = load_nca_run_snapshot(run.root)
    if policy['schema_version'] != '2.0':
        raise ValueError('Live comparison requires a current valid sealed version-2 NCA Run')
    inputs = prepare_execution_inputs(config, job, run, policy)
    labels, label_sha = reviewed_labels(args.labels, inputs)
    runtime.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix='paired-', dir=runtime))
    pairs = []
    for repetition in range(args.repetitions):
        pair = {}
        # Alternate order to expose order effects while holding route and protected inputs fixed.
        for strategy in (('baseline', 'optimized') if repetition % 2 == 0 else ('optimized', 'baseline')):
            directory = session / str(repetition + 1) / strategy
            directory.mkdir(parents=True)
            pair[strategy] = run_strategy(config, inputs, labels, strategy, directory)
        pairs.append(pair)
    categories = {x for case in labels['cases'] for x in case['categories']}
    missing = sorted(CRITICAL_CATEGORIES - categories)
    complete = all(len(pair[strategy]['cases']) == len(labels['cases']) for pair in pairs for strategy in pair)
    observed = [case for pair in pairs for case in pair['optimized']['cases']]
    accurate = all(case['exact_values_types_roles'] is True and case['finding_correctness'] and not case['unresolved'] for case in observed)
    regressions = [after['unit_id'] for pair in pairs for before, after in zip(
        sorted(pair['baseline']['cases'], key=lambda x: x['unit_id']), sorted(pair['optimized']['cases'], key=lambda x: x['unit_id']))
        if set(after['categories']) & CRITICAL_CATEGORIES and any(
            before[field] is True and after[field] is not True for field in ('exact_values_types_roles', 'finding_correctness'))]
    code_sha, code_files = baseline._code_identity()
    return {'schema_version': '1.0', 'mode': 'live', 'strategy': 'paired', 'pairs': pairs,
        'qualification_status': 'INCOMPLETE' if missing or not complete else ('PASS_SELECTED_CASES' if accurate and not regressions else 'FAIL'),
        'input_sha256': live_input_identity(inputs), 'labels_sha256': label_sha,
        'project': args.project, 'scope': args.scope, 'job_id': job.job_id, 'run_id': run.run_id,
        'style_sha256': policy['number_style']['sha256'], 'route': dict(policy['model_route']),
        'missing_critical_categories': missing, 'critical_regressions': regressions,
        'case_categories': {x['unit_id']: x['categories'] for x in labels['cases']},
        'code_sha256': code_sha, 'code_files': code_files, 'session_id': session.name,
        'sqs_status': 'NOT_APPLIED', 'capability_limitations': NCA_CAPABILITY_LIMITATION,
        'qualification_limit': 'Selected reviewed cases only; no broad model or language qualification.'}
