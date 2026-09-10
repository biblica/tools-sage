"""Deterministic NCA optimization benchmark and measurement contracts."""

from dataclasses import replace
import json
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter_ns

import pytest

from sage.llm_tasks import execute_task
import sage.nca as nca_module
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
            "uncertainty",
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
    assert {diff["case_id"] for diff in receipt["semantic_outcome_diffs"]} == {
        case["case_id"]
        for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    }
    for field in ("input_sha256", "fixture_sha256", "code_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", receipt[field])
    assert receipt["environment"]["python"]
    assert receipt["environment"]["platform"]


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
            "optimized",
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


def test_canonical_baseline_observes_three_execution_reference_loads(
    make_workspace, monkeypatch: pytest.MonkeyPatch
):
    """The governed version-1 task must expose every actual execution-time package load."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )
    manifest = Path(str(created["task_manifest_path"]))
    actual_bundle = nca_module._bundle
    elapsed: list[int] = []

    def measured_bundle(*args, **kwargs):
        """Time each real package resolution reached by governed task execution."""
        started = perf_counter_ns()
        try:
            return actual_bundle(*args, **kwargs)
        finally:
            elapsed.append((perf_counter_ns() - started) // 1_000_000)

    monkeypatch.setattr(nca_module, "_bundle", measured_bundle)
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    execute_task(config, task_manifest=manifest)

    assert len(elapsed) == 3
    assert all(value >= 0 for value in elapsed)
