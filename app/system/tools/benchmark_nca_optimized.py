"""Small synthetic optimized driver reusing the recorded baseline's literal evidence."""
from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from dataclasses import replace
import json
import os
from pathlib import Path
import platform
import tempfile
from time import perf_counter_ns
from unittest.mock import patch

import benchmark_nca as baseline
from sage.executors.base import ProviderResponse
from benchmark_nca_qualification import source_case, input_identity, governance, finding_diffs
from sage.numbers.engine import evaluate_optimized_run
from sage.numbers.execution import ExecutionInputs, build_inventory
from sage.numbers.model_tasks import NcaModelTasks
from sage.numbers.policy import phase_contract_manifest
from sage.numbers.replay import PhaseStore
from sage.numbers.results_v2 import comparison_view, group_findings
from sage.numbers.style import validate_style_profile
from sage.numbers.target import target_units
from sage.numbers.telemetry import summarize_calls
from sage.usj import compile_usfm_text


class RecordedBatchTransport(baseline._RecordedTransport):
    """Map protected input identities to literal fixture responses at the real provider boundary."""

    def __init__(self, cases, fault="none"):
        """Reuse the baseline authority rows and retain explicit controller input bindings."""
        super().__init__(cases)
        self.owners = {}
        self.fault = fault
        self.extraction_attempts = 0

    def execute(self, request):
        """Return v2 batch or singleton correspondence JSON without making a live model call."""
        envelope = json.loads(request.prompt)
        payload = envelope['input']
        if envelope['phase'] == 'EXTRACTION':
            self.extraction_attempts += 1
            if self.fault == 'transient' and self.extraction_attempts == 1:
                raise RuntimeError('Recorded transient provider failure')
            if self.fault == 'malformed':
                return ProviderResponse(provider='codex', model='gpt-5.6-sol', reasoning_effort='medium', content='{invalid', metadata={})
            items = []
            for supplied in payload['work_units']:
                case_id = self.owners[supplied['input_id']]
                legacy = self._extraction_response({'work_units': [{'unit_id': case_id}]})['work_units'][0]
                if self.fault in {'unsupported', 'partial'}:
                    legacy.update(status=self.fault.upper(), limitations=['Recorded language evidence limitation'], expressions=[])
                items.append({'input_id': supplied['input_id'], 'status': legacy['status'],
                    'limitations': legacy['limitations'], 'expressions': legacy['expressions']})
            raw = {'schema_version': '2.0', 'phase': 'EXTRACTION', 'batch_id': payload['batch_id'], 'work_units': items}
        elif envelope['phase'] == 'GROUP_CORRESPONDENCE':
            raw = self._group_response(payload)
        else:
            raw = dict(self._correspondence_response(payload), schema_version='2.0')
        self.requests.append(request)
        return ProviderResponse(provider='codex', model='gpt-5.6-sol', reasoning_effort='medium',
            content=json.dumps(raw, ensure_ascii=False, sort_keys=True), metadata={'request_id': f'recorded-{len(self.requests)}'})

    def _group_response(self, payload):
        """Render literal row allocations, including an explicitly unresolved bridge."""
        case = self._cases[payload['unit_id']]
        evidence = case['group_evidence']
        target = payload['target']['expressions']
        assignments = {ref: [target[index - 1]['expression_id'] for index in indexes]
            for ref, indexes in evidence['assignments'].items()}
        rows = {}
        for row in case['reference_rows']:
            ref = row['western_reference']
            source = [baseline._response_expression(item, expression_id=f'ol-{ref}-{index}',
                stream_id='ol', text=row['text']) for index, item in enumerate(row['expressions'], 1)]
            rows[ref] = {'status': evidence['status'], 'limitations': evidence['limitations'],
                'source_expressions': source, 'target_roles': [{'expression_id': item['expression_id'],
                    'role': item['role'], 'role_spans': baseline._role_span(case['streams']['body'], item['role'])}
                    for item in target if item['expression_id'] in assignments[ref]]}
        return {'schema_version': '2.0', 'phase': 'GROUP_CORRESPONDENCE', 'unit_id': payload['unit_id'],
            'status': evidence['status'], 'limitations': evidence['limitations'], 'rows': rows, 'assignments': assignments,
            'unmatched_target_ids': [], 'unresolved_target_ids': [target[index - 1]['expression_id'] for index in evidence['unresolved']]}


def _run_synthetic_optimized(cases_path: Path, *, fault="none", checkpoint_root=None, resume_only=False) -> dict[str, object]:
    """Measure one qualified reference/style load and complete-scope batched production evaluation."""
    fixture_bytes, cases, reference_path = baseline._load_cases(cases_path)
    started = perf_counter_ns()
    seed = baseline.load_reference(reference_path)
    reference_ms = (perf_counter_ns() - started) // 1_000_000
    bundle = baseline._build_reference_bundle(seed, cases)
    started = perf_counter_ns()
    profile = validate_style_profile(baseline._style_profile())
    profile_ms = (perf_counter_ns() - started) // 1_000_000
    by_language = defaultdict(list)
    documents = {}
    for case in cases:
        sfm, document, projected = source_case(case)
        documents[projected.target.source_sha256] = document
        by_language[case['language']].append(projected)
    transport = RecordedBatchTransport(cases, fault=fault)
    outcomes = []
    resume_calls = []
    reuse_events = 0
    checkpoint_reuse_events = 0
    resume_equivalent = True
    cold_elapsed_ns = 0
    resume_elapsed_ns = 0
    coverage_ledgers = []
    started = perf_counter_ns()
    if checkpoint_root is not None:
        checkpoint_root = checkpoint_root.resolve()
        if resume_only and not checkpoint_root.is_dir():
            raise ValueError('Cold resume requires an existing checkpoint directory')
        checkpoint_root.mkdir(parents=True, exist_ok=True)
    data_context = nullcontext(str(checkpoint_root)) if checkpoint_root is not None else tempfile.TemporaryDirectory(prefix='sage-nca-optimized-benchmark-')
    with data_context as data_home:
        with patch.dict(os.environ, {'SAGE_DATA_HOME': data_home}, clear=False):
            tasks = NcaModelTasks(type('BenchmarkConfig', (), {'root': baseline.APP_ROOT})(),
                settings={'selected_provider': 'codex', 'providers': {'codex': {'enabled': True}}}, transport=transport)
            tasks.phase_resume_only = resume_only
            route = dict(tasks.route_identity)
            contracts = phase_contract_manifest(baseline.APP_ROOT, tasks.route_snapshot)
            for language, projected in by_language.items():
                policy = {'schema_version': '2.0', 'wip': {'language': language, 'script': 'Latn'},
                    'reference_package': {'diagnostics': []}, 'model_route': dict(tasks.route_snapshot),
                    'checks': {'number_accuracy': True, 'presentation_consistency': True, 'footnote_review': False},
                    'optimization': {'contract_version': 'nca-optimization-2.0', 'reuse_scope': 'TASK',
                        'extraction_batch_max_units': 8, 'request_concurrency': 1, 'transient_retries': 1}}
                inputs = ExecutionInputs(bundle, profile, policy, tuple(projected), (),
                    tuple(x.target.unit_id for x in projected), tuple(r for x in projected for r in x.western_references),
                    documents, 'MAT 5', baseline._canonical_bytes(policy),
                    {name: (baseline.APP_ROOT / name).read_bytes() for name in contracts['files']})
                inventory = build_inventory(inputs)
                transport.owners.update({x.input_id: x.owner_unit_id for x in inventory.stream_inputs})
                task_root = Path(data_home) / language
                task_root.mkdir(exist_ok=True)
                cold_started_ns = perf_counter_ns()
                result = evaluate_optimized_run(inputs, model_tasks=tasks,
                    phase_store=PhaseStore(task_root, task_fingerprint=baseline._sha256(language.encode())), run_id='benchmark')
                checkpoint_reuse_events += len(tasks.phase_session.reused)
                cold_elapsed_ns += perf_counter_ns() - cold_started_ns
                resume_started_ns = perf_counter_ns()
                # A new task object and store read the cold durable state without shared in-memory caches.
                resumed_tasks = NcaModelTasks(type('BenchmarkConfig', (), {'root': baseline.APP_ROOT})(),
                    settings={'selected_provider': 'codex', 'providers': {'codex': {'enabled': True}}}, transport=transport)
                resumed_tasks.phase_resume_only = True
                resumed = evaluate_optimized_run(inputs, model_tasks=resumed_tasks,
                    phase_store=PhaseStore(task_root, task_fingerprint=baseline._sha256(language.encode())), run_id='benchmark')
                resume_elapsed_ns += perf_counter_ns() - resume_started_ns
                resume_calls.extend(x.measurement for x in resumed_tasks.attempts)
                reuse_events += len(resumed_tasks.phase_session.reused)
                resume_equivalent = resume_equivalent and resumed.groups == result.groups and resumed.coverage == result.coverage
                coverage_ledgers.append(baseline._plain_evidence(result.coverage))
                for group in result.groups:
                    view = comparison_view(group, checks=policy['checks'])
                    outcomes.append({'case_id': group.projected.target.unit_id,
                        'findings': group_findings(group, bundle=bundle, checks=policy['checks']),
                        'expressions': [baseline._plain_expression(x) for x in group.extraction.expressions],
                        'outcome': view.final_outcome, 'semantic_reason_codes': list(view.reading.semantic.reason_codes),
                        'limitations': list(group.limitations), 'coverage_status': result.coverage['coverage']})
            calls = summarize_calls(tuple(x.measurement for x in tasks.attempts))
    elapsed_ms = (perf_counter_ns() - started) // 1_000_000
    expected = {x['case_id']: x['expected'] for x in cases}
    diffs = []
    for item in outcomes:
        golden = expected[item['case_id']]
        diffs.append({'case_id': item['case_id'], 'expected_baseline': golden['baseline_outcome'],
            'observed': item['outcome'], 'matches_baseline': item['outcome'] == golden['baseline_outcome'],
            'observed_uncertainty': item['semantic_reason_codes'], 'expected_baseline_uncertainty': golden['baseline_uncertainty'],
            'matches_uncertainty': item['semantic_reason_codes'] == golden['baseline_uncertainty'],
            'matches_expressions': [baseline._golden_expression(x) for x in item['expressions']] == [baseline._golden_expression(x) for x in golden['expressions']],
            'expected_optimized': golden['optimized_outcome'], 'expected_optimized_uncertainty': golden['optimized_uncertainty'],
            'bridge_result_new_behavior': golden['bridge_result_new_behavior']})
    code_sha, code_files = baseline._code_identity()
    return {'schema_version': '2.0', 'benchmark_id': 'nca-optimization-hybrid-v2', 'mode': 'synthetic', 'strategy': 'optimized',
        'case_count': len(cases), 'fixture_sha256': baseline._sha256(fixture_bytes),
        'input_sha256': input_identity(cases, bundle.sha256, profile, policy['checks']),
        'governance': governance(tasks, 'optimized'),
        'resume': {'elapsed_ms': resume_elapsed_ns // 1_000_000, 'calls': summarize_calls(tuple(resume_calls)), 'reuse_events': reuse_events, 'equivalent_outcomes_and_coverage': resume_equivalent},
        'coverage_ledgers': coverage_ledgers, 'checkpoint_reuse_events': checkpoint_reuse_events,
        'code_sha256': code_sha, 'code_files': code_files, 'environment': {'python': platform.python_version(),
            'implementation': platform.python_implementation(), 'platform': platform.platform()},
        'transport_boundary': 'sage.executors.ProviderRequest', 'route': route, 'calls': calls,
        'local_loads': {'reference_load_count': 1, 'reference_load_elapsed_ms': reference_ms, 'reference_package_sha256': seed.sha256,
            'profile_validation_count': 1, 'profile_validation_elapsed_ms': profile_ms},
        'execution_elapsed_ms': cold_elapsed_ns // 1_000_000, 'driver_elapsed_ms': elapsed_ms, 'outcomes': outcomes, 'semantic_outcome_diffs': diffs,
        'finding_diffs': finding_diffs(cases, outcomes, 'optimized'),
        'limitations': ['LIVE_MODEL_BENCHMARK_NOT_RUN', 'SQS: NOT_APPLIED'],
        'capability_limitations': baseline.NCA_CAPABILITY_LIMITATION}


def run_synthetic_optimized(cases_path: Path, *, fault="none", checkpoint_root=None, resume_only=False):
    """Observe every package/style qualification call across execution and checkpoint replay."""
    from contextlib import ExitStack
    counts = {'reference_load_count': 0, 'profile_validation_count': 0}
    original_reference = baseline.load_reference
    original_style = validate_style_profile

    def measured_reference(*args, **kwargs):
        """Count the actual reference loader including any future accidental repeated load."""
        counts['reference_load_count'] += 1
        return original_reference(*args, **kwargs)

    def measured_style(*args, **kwargs):
        """Count the complete profile validator at each existing production import boundary."""
        counts['profile_validation_count'] += 1
        return original_style(*args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(baseline, 'load_reference', measured_reference))
        stack.enter_context(patch(__name__ + '.validate_style_profile', measured_style))
        stack.enter_context(patch.object(baseline.engine_module, 'validate_style_profile', measured_style))
        stack.enter_context(patch.object(baseline.style_module, 'validate_style_profile', measured_style))
        receipt = _run_synthetic_optimized(cases_path, fault=fault, checkpoint_root=checkpoint_root, resume_only=resume_only)
    receipt['local_loads'].update(counts)
    return receipt
