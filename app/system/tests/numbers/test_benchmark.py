"""Deterministic NCA optimization benchmark and measurement contracts."""

from dataclasses import replace
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import perf_counter_ns

import pytest

from sage.llm_tasks import execute_task
from sage.numbers import execution as execution_module
from sage.nca import create_nca_task
from sage.numbers.telemetry import CallMeasurement, summarize_calls

from .test_nca_tasks import _OfflineTasks, _run


FIXTURE = Path(__file__).parent / "fixtures" / "optimization-cases.json"
TOOL = Path(__file__).parents[2] / "tools" / "benchmark_nca.py"


def test_reused_batch_receipt_is_not_another_provider_call():
    """Member count and reuse must not inflate usage."""
    call = CallMeasurement("r1", "EXTRACTION", ("a", "b"), 10,
                           100, 50, None, None, "VALIDATED", False)
    result = summarize_calls((call, replace(call, reused=True)))
    assert result["provider_calls"] == 1
    assert result["input_tokens"] is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"request_id": ""}, "request ID"),
        ({"phase": ""}, "phase"),
        ({"unit_ids": ["a"]}, "unit IDs"),
        ({"unit_ids": ("",)}, "unit IDs"),
        ({"elapsed_ms": -1}, "elapsed"),
        ({"request_bytes": True}, "request bytes"),
        ({"response_bytes": -1}, "response bytes"),
        ({"input_tokens": -1}, "input tokens"),
        ({"output_tokens": False}, "output tokens"),
        ({"status": ""}, "status"),
        ({"reused": 1}, "reused"),
    ],
)
def test_call_measurement_rejects_inexact_or_negative_fields(changes, message):
    """Telemetry cannot turn malformed or estimated values into exact counts."""
    fields = {
        "request_id": "r1",
        "phase": "EXTRACTION",
        "unit_ids": ("a",),
        "elapsed_ms": 10,
        "request_bytes": 100,
        "response_bytes": 50,
        "input_tokens": 20,
        "output_tokens": 5,
        "status": "VALIDATED",
        "reused": False,
    }
    fields.update(changes)
    with pytest.raises(ValueError, match=message):
        CallMeasurement(**fields)


def test_summary_rejects_conflicting_duplicate_request_evidence():
    """One provider request ID cannot authorize inconsistent transport evidence."""
    call = CallMeasurement(
        "r1", "EXTRACTION", ("a",), 10, 100, 50, 20, 5, "VALIDATED", False
    )
    with pytest.raises(ValueError, match="Inconsistent"):
        summarize_calls((call, replace(call, response_bytes=51)))


def test_summary_keeps_failures_reuse_and_phase_totals_separate():
    """Failed attempts remain visible while reused receipts add no transport usage."""
    successful = CallMeasurement(
        "r1", "EXTRACTION", ("a", "b"), 10, 100, 50, 20, 5, "VALIDATED", False
    )
    failed = CallMeasurement(
        "r2", "CORRESPONDENCE", ("a",), 7, 80, 0, 4, 0, "FAILED", False
    )
    result = summarize_calls((successful, replace(successful, reused=True), failed))
    assert result == {
        "provider_calls": 2,
        "reuse_events": 1,
        "failed_calls": 1,
        "phase_counts": {"CORRESPONDENCE": 1, "EXTRACTION": 1},
        "status_counts": {"FAILED": 1, "VALIDATED": 1},
        "elapsed_ms": 17,
        "request_bytes": 180,
        "response_bytes": 50,
        "input_tokens": 24,
        "output_tokens": 5,
        "failure_request_ids": ("r2",),
        "reused_request_ids": ("r1",),
    }


def test_optimization_fixture_has_exact_required_golden_semantics():
    """The benchmark corpus must cover every planned behavior with literal goldens."""
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = document["cases"]
    required = {
        "ordinary_numeric",
        "ordinary_number_free",
        "indexed_omission",
        "unindexed_numeric",
        "registered_absence",
        "mixed_word_digit",
        "unicode_digits",
        "repeated_values",
        "ratio_fraction_ordinal",
        "bridge_clear_roles",
        "bridge_repeated_values",
        "bridge_ambiguous",
    }
    assert {case["case_id"] for case in cases} == required
    for case in cases:
        assert set(case["streams"]) == {"body", "notes", "headings"}
        assert isinstance(case["streams"]["body"], str)
        assert isinstance(case["streams"]["notes"], list)
        assert isinstance(case["streams"]["headings"], list)
        assert case["language"]
        assert set(case["expected"]) == {
            "expressions",
            "baseline_outcome",
            "optimized_outcome",
            "baseline_uncertainty",
            "optimized_uncertainty",
            "bridge_result_new_behavior",
        }
        body = case["streams"]["body"]
        for expression in case["expected"]["expressions"]:
            assert body[expression["span"][0]:expression["span"][1]] == expression["surface"]
        for row in case["reference_rows"]:
            for expression in row["expressions"]:
                start, end = expression["span"]
                assert row["text"][start:end] == expression["surface"]
                assert expression["role"].casefold() in row["text"].casefold()
    bridges = [case for case in cases if len(case["western_references"]) > 1]
    assert len(bridges) == 3
    assert all(case["expected"]["bridge_result_new_behavior"] for case in bridges)
    assert all(
        not case["expected"]["bridge_result_new_behavior"]
        for case in cases
        if len(case["western_references"]) == 1
    )
    assert {
        case["case_id"]: (
            case["expected"]["baseline_uncertainty"],
            case["expected"]["optimized_uncertainty"],
        )
        for case in bridges
    } == {
        "bridge_clear_roles": (["MERGED_ALIGNMENT_UNAVAILABLE"], []),
        "bridge_repeated_values": (["MERGED_ALIGNMENT_UNAVAILABLE"], []),
        "bridge_ambiguous": (
            ["MERGED_ALIGNMENT_UNAVAILABLE"],
            ["AMBIGUOUS_BRIDGE_ASSIGNMENT"],
        ),
    }


def test_synthetic_baseline_records_observed_calls_loads_and_golden_outcomes(
    tmp_path: Path,
):
    """The provider-free baseline must measure real engine boundaries and literal outcomes."""
    receipt_path = tmp_path / "baseline-receipt.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--strategy",
            "baseline",
            "--cases",
            str(FIXTURE),
            "--receipt",
            str(receipt_path),
        ],
        check=False,
        cwd=TOOL.parents[2],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    case_count = len(json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"])
    assert receipt["mode"] == "synthetic"
    assert receipt["strategy"] == "baseline"
    assert receipt["case_count"] == case_count
    assert receipt["calls"]["provider_calls"] == sum(
        receipt["calls"]["phase_counts"].values()
    )
    assert receipt["calls"]["phase_counts"] == {
        "CORRESPONDENCE": 7,
        "EXTRACTION": 12,
    }
    assert receipt["calls"]["input_tokens"] is None
    assert receipt["calls"]["output_tokens"] is None
    assert receipt["transport_boundary"] == "sage.executors.ProviderRequest"
    assert receipt["calls"]["request_bytes"] > receipt["calls"]["response_bytes"]
    assert receipt["local_loads"]["reference_load_count"] == 1
    assert re.fullmatch(
        r"[0-9a-f]{64}", receipt["local_loads"]["reference_package_sha256"]
    )
    assert receipt["local_loads"]["profile_validation_count"] == 2 * case_count
    assert receipt["local_loads"]["reference_load_elapsed_ms"] >= 0
    assert receipt["local_loads"]["profile_validation_elapsed_ms"] >= 0
    assert all(diff["matches_baseline"] for diff in receipt["semantic_outcome_diffs"])
    assert all(diff["matches_expressions"] for diff in receipt["semantic_outcome_diffs"])
    assert all(diff["matches_uncertainty"] for diff in receipt["semantic_outcome_diffs"])
    assert {diff["case_id"] for diff in receipt["semantic_outcome_diffs"]} == {
        case["case_id"]
        for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    }
    for field in ("input_sha256", "fixture_sha256", "code_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", receipt[field])
    assert receipt["environment"]["python"]
    assert receipt["environment"]["platform"]


def test_baseline_detects_changed_uncertainty_with_other_goldens_unchanged(
    tmp_path: Path,
):
    """A reason-code regression must fail even when outcome and expressions still match."""
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["cases"][0]["expected"]["baseline_uncertainty"] = [
        "REGRESSION_SENTINEL"
    ]
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    shutil.copytree(
        FIXTURE.parent / document["reference_package"],
        fixture_dir / document["reference_package"],
    )
    changed_fixture = fixture_dir / FIXTURE.name
    changed_fixture.write_text(json.dumps(document), encoding="utf-8")
    receipt_path = tmp_path / "changed-uncertainty.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--strategy",
            "baseline",
            "--cases",
            str(changed_fixture),
            "--receipt",
            str(receipt_path),
        ],
        check=False,
        cwd=TOOL.parents[2],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    changed = next(
        diff
        for diff in receipt["semantic_outcome_diffs"]
        if diff["case_id"] == "ordinary_numeric"
    )
    assert changed["matches_baseline"] is True
    assert changed["matches_expressions"] is True
    assert changed["matches_uncertainty"] is False
    assert changed["observed_uncertainty"] == []
    assert changed["expected_baseline_uncertainty"] == ["REGRESSION_SENTINEL"]


def test_benchmark_rejects_an_unimplemented_strategy(tmp_path: Path):
    """Task 1 must not imply that the later optimized execution path exists."""
    receipt_path = tmp_path / "unsupported.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--mode",
            "synthetic",
            "--strategy",
            "future-unsupported",
            "--cases",
            str(FIXTURE),
            "--receipt",
            str(receipt_path),
        ],
        check=False,
        cwd=TOOL.parents[2],
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert not receipt_path.exists()


def test_canonical_execution_observes_one_reference_load(
    make_workspace, monkeypatch: pytest.MonkeyPatch
):
    """The governed task measures the actual attempt-owned package qualification boundary."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )
    manifest = Path(str(created["task_manifest_path"]))
    actual_bundle = execution_module.resolve_reference_package
    elapsed: list[int] = []

    def measured_bundle(*args, **kwargs):
        """Time each real package resolution reached by governed task execution."""
        started = perf_counter_ns()
        try:
            return actual_bundle(*args, **kwargs)
        finally:
            elapsed.append((perf_counter_ns() - started) // 1_000_000)

    monkeypatch.setattr(execution_module, "resolve_reference_package", measured_bundle)
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    execute_task(config, task_manifest=manifest)

    assert len(elapsed) == 1
    assert all(value >= 0 for value in elapsed)


def test_optimized_benchmark_preserves_nonbridge_goldens_and_reduces_local_work(tmp_path: Path):
    """Actual optimized batches keep golden semantics with one package/style qualification."""
    receipt_path = tmp_path / 'optimized.json'
    completed = subprocess.run([sys.executable, str(TOOL), '--strategy', 'optimized', '--cases', str(FIXTURE),
        '--receipt', str(receipt_path)], check=False, cwd=TOOL.parents[2], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(receipt_path.read_text())
    assert receipt['strategy'] == 'optimized'
    assert receipt['local_loads']['reference_load_count'] == 1
    assert receipt['local_loads']['profile_validation_count'] == 1
    assert receipt['calls']['phase_counts']['EXTRACTION'] < 12
    assert all(x['matches_baseline'] and x['matches_expressions'] and x['matches_uncertainty']
               for x in receipt['semantic_outcome_diffs'] if not x['bridge_result_new_behavior'])
    assert {x['case_id']: x['observed'] for x in receipt['semantic_outcome_diffs'] if x['bridge_result_new_behavior']} == {
        'bridge_clear_roles': 'PASS_AUTHORITY1', 'bridge_repeated_values': 'PASS_AUTHORITY1',
        'bridge_ambiguous': 'INSUFFICIENT_EVIDENCE'}
    assert all(x['observed'] == x['expected_optimized'] and x['observed_uncertainty'] == x['expected_optimized_uncertainty']
        for x in receipt['semantic_outcome_diffs'])
    assert receipt['calls']['phase_counts']['GROUP_CORRESPONDENCE'] == 3
    assert all(x['matches_labels'] for x in receipt['finding_diffs'])


def test_paired_qualification_uses_complete_equal_inputs_and_real_transport(tmp_path):
    """A changed scope, contract, golden or physical batch count invalidates qualification."""
    receipt_path = tmp_path / 'paired.json'
    completed = subprocess.run([sys.executable, str(TOOL), '--strategy', 'paired',
        '--cases', str(FIXTURE.with_name('optimization-mat5.json')), '--receipt', str(receipt_path)],
        capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(receipt_path.read_text())
    assert receipt['qualification_status'] == 'PASS'
    assert receipt['gates']['optimized_findings'] is True
    assert receipt['gates']['baseline_findings'] is True
    before, after = receipt['baseline'], receipt['optimized']
    assert before['input_sha256'] == after['input_sha256']
    assert before['governance']['status'] == after['governance']['status'] == 'VALIDATED'
    assert before['governance']['contract_sha256'] != after['governance']['contract_sha256']
    assert before['calls']['phase_counts']['EXTRACTION'] == 32
    assert after['calls']['phase_counts']['EXTRACTION'] == 4
    assert after['calls']['request_bytes'] < before['calls']['request_bytes']
    assert after['local_loads']['reference_load_count'] == after['local_loads']['profile_validation_count'] == 1
    assert after['resume']['calls']['provider_calls'] == 0
    assert after['resume']['reuse_events'] == after['calls']['provider_calls']
    assert all(x['coverage_status'] in {'COMPLETE', 'COMPLETE_WITH_RESTRICTIONS'} for x in after['outcomes'])
    assert receipt['live_status'] == 'LIVE_MODEL_BENCHMARK_NOT_RUN'
    assert receipt['sqs_status'] == 'NOT_APPLIED'


@pytest.mark.parametrize('fault', ['transient', 'malformed', 'unsupported', 'partial'])
def test_qualification_faults_remain_bounded_without_false_pass(tmp_path, fault):
    """Failed physical requests remain counted and accepted uncertainty is never retried to pass."""
    receipt_path = tmp_path / 'fault.json'
    completed = subprocess.run([sys.executable, str(TOOL), '--strategy', 'optimized', '--fault', fault,
        '--cases', str(FIXTURE.with_name('optimization-mat5.json')), '--receipt', str(receipt_path)],
        capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(receipt_path.read_text())
    assert receipt['calls']['phase_counts']['EXTRACTION'] <= 2 * (2 * 32 - 4)
    assert receipt['resume']['calls']['provider_calls'] == 0
    if fault in {'unsupported', 'partial'}:
        assert receipt['calls']['phase_counts']['EXTRACTION'] == 4
        assert not any(x['outcome'].startswith('PASS') for x in receipt['outcomes'])
    elif fault == 'transient':
        assert receipt['calls']['failed_calls'] == 1
        assert all(x['matches_expressions'] for x in receipt['semantic_outcome_diffs'])
    else:
        assert receipt['calls']['failed_calls'] > 0
        assert not any(x['outcome'].startswith('PASS') for x in receipt['outcomes'])


def test_live_entrypoint_requires_bound_reviewed_labels_and_runtime_output(make_workspace, monkeypatch, tmp_path):
    """A real live entrypoint uses sealed inputs and providers only after exact label validation."""
    import importlib
    from dataclasses import asdict
    from sage.numbers.policy import load_nca_run_snapshot
    from sage.numbers.execution import prepare_execution_inputs
    from sage.numbers.model_tasks import NcaModelTasks
    from .test_nca_tasks import _EmptyTransport
    sys.path.insert(0, str(TOOL.parent))
    live = importlib.import_module('benchmark_nca_live')
    _root, config, job, run = _run(make_workspace, monkeypatch)
    inputs = prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))
    class LiveRecordedTasks(_OfflineTasks):
        """Use real phase execution for both versions with only the external response recorded."""
        extract = NcaModelTasks.extract
        correspond = NcaModelTasks.correspond

        def __init__(self, *args, **kwargs):
            """Retain readiness fixture routing and count real ProviderRequest execution."""
            super().__init__(*args, **kwargs)
            self._executor = LiveRecordedTransport()

    class LiveRecordedTransport(_EmptyTransport):
        """Return empty evidence at the actual transport boundary for either extraction contract."""
        calls = []

        def execute(self, request):
            """Record every provider request without launching an external model."""
            from sage.executors import ProviderResponse
            self.calls.append(request)
            envelope = json.loads(request.prompt)
            if envelope['task_version'] == 'nca-extraction-1.0':
                raw = {'schema_version': '1.0', 'phase': 'EXTRACTION', 'work_units': [
                    {'unit_id': x['unit_id'], 'status': 'COMPLETE', 'limitations': [], 'expressions': []}
                    for x in envelope['input']['work_units']]}
                return ProviderResponse(provider='codex', model='gpt-test', reasoning_effort='high', content=json.dumps(raw), metadata={})
            return super().execute(request)

    monkeypatch.setattr(live, 'NcaModelTasks', LiveRecordedTasks)
    monkeypatch.setattr(live, 'load_ecosystem', lambda path: config)
    labels = {'schema_version': '1.0', 'reviewed_by': 'Fixture operator', 'reviewed_at': '2026-09-14',
        'input_sha256': live.live_input_identity(inputs), 'cases': [
            {'unit_id': x.target.unit_id, 'categories': ['ordinary'], 'expressions': [],
             'outcome': 'INSUFFICIENT_EVIDENCE', 'finding_codes': [], 'findings': []} for x in inputs.projected_units]}
    path = tmp_path / 'labels.json'
    path.write_text(json.dumps(labels))
    destination = config.runtime_state_root / 'nca-benchmarks/test/receipt.json'
    arguments = ['--mode', 'live', '--settings', str(config.settings_path), '--job', job.job_id,
        '--run', run.run_id, '--project', job.bindings['wip'], '--scope', run.scope,
        '--labels', str(path), '--receipt', str(destination), '--repetitions', '3']
    benchmark = importlib.import_module('benchmark_nca')
    before = {p.relative_to(run.root).as_posix(): p.read_bytes() for p in run.root.rglob('*') if p.is_file()}
    assert benchmark.main(arguments) == 0
    receipt = json.loads(destination.read_text())
    assert len(receipt['pairs']) == 3
    assert len(LiveRecordedTransport.calls) > 0
    assert receipt['qualification_status'] == 'INCOMPLETE'
    assert set(receipt['missing_critical_categories']) == {'omission', 'extra_number', 'referent', 'bridge'}
    assert {p.relative_to(run.root).as_posix(): p.read_bytes() for p in run.root.rglob('*') if p.is_file()} == before
    assert 'text' not in receipt and 'raw_response' not in receipt
    for pair in receipt['pairs']:
        assert pair['baseline']['input_sha256'] == pair['optimized']['input_sha256'] == labels['input_sha256']
        assert all('extraction_precision' in x and 'finding_correctness' in x for x in pair['optimized']['cases'])
    labels['input_sha256'] = '0' * 64
    path.write_text(json.dumps(labels))
    count = len(LiveRecordedTransport.calls)
    with pytest.raises(ValueError, match='labels'):
        benchmark.main(arguments[:-4] + ['--receipt', str(destination.with_name('changed.json')), '--repetitions', '3'])
    assert len(LiveRecordedTransport.calls) == count


def test_live_finding_accuracy_binds_row_attribution_and_not_only_codes():
    """A right finding code attached to the wrong Western row fails independent labels."""
    import importlib
    from types import SimpleNamespace
    from sage.numbers.models import Extraction
    sys.path.insert(0, str(TOOL.parent))
    live = importlib.import_module('benchmark_nca_live')
    view = SimpleNamespace(extraction=Extraction((), 'COMPLETE'), final_outcome='REVIEW_NUMBER_MISSING')
    expected = {'code': 'NCA_REVIEW_NUMBER_MISSING', 'category': 'ACCURACY', 'severity': 'REVIEW',
        'target_references': ['MAT 5:1', 'MAT 5:2'], 'western_references': ['MAT 5:1'],
        'ol_references': ['MAT 5:1'], 'selected_reading': 'OL', 'source_ids': ['SYNTHETIC-SOURCE'], 'evidence_ids': []}
    label = {'unit_id': 'bridge', 'categories': ['bridge', 'omission'], 'expressions': [],
        'outcome': view.final_outcome, 'finding_codes': [expected['code']], 'findings': [expected]}
    observed = dict(expected, western_references=['MAT 5:2'])
    assert live.case_metrics(view, [observed], label)['finding_correctness'] is False


def test_paired_command_fails_closed_when_independent_golden_changes(tmp_path):
    """A wrong operator label cannot leave an apparently successful qualification command."""
    fixture = FIXTURE.with_name('optimization-mat5.json')
    document = json.loads(fixture.read_text())
    document['cases'][0]['expected']['optimized_outcome'] = 'REVIEW_NUMBER_MISSING'
    shutil.copytree(FIXTURE.parent / document['reference_package'], tmp_path / document['reference_package'])
    changed = tmp_path / fixture.name
    changed.write_text(json.dumps(document))
    receipt_path = tmp_path / 'failed.json'
    completed = subprocess.run([sys.executable, str(TOOL), '--strategy', 'paired', '--cases', str(changed),
        '--receipt', str(receipt_path)], capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    receipt = json.loads(receipt_path.read_text())
    assert receipt['qualification_status'] == 'FAIL'
    assert receipt['gates']['optimized_goldens'] is False


def test_cold_process_requalifies_inputs_and_reuses_valid_checkpoints(tmp_path):
    """A fresh interpreter reconstructs input authority and emits zero calls for valid stored phases."""
    checkpoint_root = tmp_path / 'checkpoints'
    common = [sys.executable, str(TOOL), '--strategy', 'optimized', '--cases', str(FIXTURE.with_name('optimization-mat5.json')),
        '--checkpoint-root', str(checkpoint_root)]
    first, second = tmp_path / 'first.json', tmp_path / 'second.json'
    started = subprocess.run(common + ['--receipt', str(first)], capture_output=True, text=True, check=False)
    assert started.returncode == 0, started.stderr
    resumed = subprocess.run(common + ['--resume-only', '--receipt', str(second)], capture_output=True, text=True, check=False)
    assert resumed.returncode == 0, resumed.stderr
    before, after = json.loads(first.read_text()), json.loads(second.read_text())
    assert before['calls']['provider_calls'] == 36
    assert after['calls']['provider_calls'] == 0
    assert after['local_loads']['reference_load_count'] == after['local_loads']['profile_validation_count'] == 1
    assert before['outcomes'] == after['outcomes']
    assert before['input_sha256'] == after['input_sha256']
    assert after['checkpoint_reuse_events'] == 36
