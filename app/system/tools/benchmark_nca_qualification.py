"""Bind deterministic NCA benchmark inputs, contracts and paired acceptance evidence."""
from __future__ import annotations

from dataclasses import replace
from collections import Counter
import json

import benchmark_nca as baseline
from sage.numbers.policy import _plain, phase_contract_manifest
from sage.numbers.results import NCA_CAPABILITY_LIMITATION
from sage.numbers.target import target_units
from sage.usj import compile_usfm_text


def source_case(case):
    """Build the same exact synthetic SFM and production projection for both strategies."""
    projected = baseline._target_case(case)
    refs = projected.target.target_references
    verse = str(refs[0].verse) if len(refs) == 1 else f'{refs[0].verse}-{refs[-1].verse}'
    sfm = f'\\id {refs[0].book}\n\\c {refs[0].chapter}\n\\v {verse} {case["streams"]["body"]}\n'
    document = compile_usfm_text(sfm)
    digest = baseline._sha256(baseline._canonical_bytes(document))
    target = replace(target_units(document, source_sha256=digest)[0], unit_id=case['case_id'])
    return sfm.encode(), document, replace(projected, target=target)


def input_identity(cases, package_sha256, profile, checks):
    """Bind literal labels, source bytes, projections, package, style and all check settings."""
    sources = []
    for case in cases:
        sfm, document, projected = source_case(case)
        sources.append({'case': case, 'sfm_sha256': baseline._sha256(sfm),
            'usj_sha256': baseline._sha256(baseline._canonical_bytes(document)),
            'projection': {'status': projected.status, 'mapping_kind': projected.precision,
                'target': [ref.label() for ref in projected.target.target_references],
                'western': [ref.label() for ref in projected.western_references],
                'canonical': [ref.label() for ref in projected.canonical_references]}})
    return baseline._sha256(baseline._canonical_bytes(_plain({'sources': sources,
        'package_sha256': package_sha256, 'profile': profile, 'checks': checks})))


def governance(tasks, strategy):
    """Validate and fingerprint each benchmark contract independently of historical Runs."""
    manifest = phase_contract_manifest(tasks._config.root, tasks.route_snapshot)
    versions = {'EXTRACTION': f'nca-extraction-{ "1.0" if strategy == "baseline" else "2.0"}',
        'CORRESPONDENCE': f'nca-correspondence-{ "1.0" if strategy == "baseline" else "2.0"}'}
    if strategy == 'optimized':
        versions['GROUP_CORRESPONDENCE'] = 'nca-group-correspondence-2.0'
    manifest = dict(manifest, version='nca-benchmark-contracts-' + ('1.0' if strategy == 'baseline' else '2.0'),
        phases=versions, schema_ids=['sage-nca-extraction-' + ('1.0' if strategy == 'baseline' else '2.0')], scope='BENCHMARK_ONLY')
    request_contracts = {}
    for attempt in tasks.attempts:
        envelope = json.loads(attempt.request['prompt'])
        phase = envelope['phase']
        if phase in versions and envelope['task_version'] != versions[phase]:
            raise ValueError('Benchmark request used another versioned phase contract')
        request_contracts[phase] = {'task_version': envelope['task_version'],
            'skill_sha256': baseline._sha256(envelope['skill_contract'].encode()),
            'schema_sha256': baseline._sha256(baseline._canonical_bytes(_plain(attempt.request['schema'])))}
    contract = {'strategy': strategy, 'phase_versions': versions, 'installed_manifest': manifest,
        'request_contracts': request_contracts}
    return {'status': 'VALIDATED', 'contract_sha256': baseline._sha256(baseline._canonical_bytes(contract)),
        'route_sha256': baseline._sha256(baseline._canonical_bytes(dict(tasks.route_snapshot))), **contract}


def qualify_pair(before, after):
    """Fail closed on physical efficiency, exact labelled semantics and complete scope."""
    semantic = all(x['matches_expressions'] and x['observed'] == x['expected_optimized']
        and x['observed_uncertainty'] == x['expected_optimized_uncertainty'] for x in after['semantic_outcome_diffs'])
    before_ok = all(x['matches_expressions'] and x['matches_baseline'] and x['matches_uncertainty']
        for x in before['semantic_outcome_diffs'])
    initial = before['calls']['phase_counts'].get('EXTRACTION', 0)
    optimized = after['calls']['phase_counts'].get('EXTRACTION', 0)
    gates = {'identical_inputs': before['input_sha256'] == after['input_sha256'],
        'identical_route': before['governance']['route_sha256'] == after['governance']['route_sha256'],
        'baseline_goldens': before_ok, 'optimized_goldens': semantic,
        'baseline_findings': all(x['matches_labels'] for x in before['finding_diffs']),
        'optimized_findings': all(x['matches_labels'] for x in after['finding_diffs']),
        'complete_scope': len(before['outcomes']) == len(after['outcomes']) == before['case_count']
            and all(x['coverage_status'] in {'COMPLETE', 'COMPLETE_WITH_RESTRICTIONS'} for x in before['outcomes'] + after['outcomes']),
        'extraction_call_reduction': optimized * 2 <= initial,
        'lower_request_bytes': after['calls']['request_bytes'] < before['calls']['request_bytes'],
        'one_qualification': after['local_loads']['reference_load_count'] == after['local_loads']['profile_validation_count'] == 1,
        'zero_resume_calls': after['resume']['calls']['provider_calls'] == 0,
        'identical_resume_semantics': after['resume']['equivalent_outcomes_and_coverage']}
    if before['case_count'] == 32:
        gates['four_batches'] = optimized == 4
    return {'schema_version': '1.0', 'mode': 'synthetic', 'strategy': 'paired',
        'qualification_status': 'PASS' if all(gates.values()) else 'FAIL', 'gates': gates,
        'baseline': before, 'optimized': after, 'live_status': 'LIVE_MODEL_BENCHMARK_NOT_RUN',
        'sqs_status': 'NOT_APPLIED', 'capability_limitations': NCA_CAPABILITY_LIMITATION}


def finding_diffs(cases, outcomes, strategy):
    """Compare literal independently labeled finding codes and row ownership with multiplicity."""
    labels = {case['case_id']: case.get('finding_labels', {}).get(strategy) for case in cases}
    differences = []
    for outcome in outcomes:
        observed = [_plain({key: item[key] for key in ('code', 'category', 'western_references')})
            for item in outcome['findings']]
        expected = labels[outcome['case_id']]
        differences.append({'case_id': outcome['case_id'], 'expected': expected, 'observed': observed,
            'matches_labels': expected is not None and Counter(baseline._canonical_bytes(x) for x in expected)
                == Counter(baseline._canonical_bytes(x) for x in observed)})
    return differences
