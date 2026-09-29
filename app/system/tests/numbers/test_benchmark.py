"""Deterministic NCA simplified-pipeline benchmark and measurement contracts.

Per the 2026-09-28 simplified-check rewrite, there is no more baseline/optimized
pipeline pair to compare -- EXTRACTION is the only model phase. The historical
baseline-vs-optimized batch-count numbers for the same MAT 5:1-32 scope (32
baseline requests; 4 at cap=8; 1 at cap=220) are preserved as prior qualification
evidence in docs/advanced/release/NCA-OPTIMIZATION-QUALIFICATION.md and are not
re-measured here. This file instead confirms the simplified pipeline reproduces
those same batch counts (batching is a pure function of unit count and routed-SFM
size -- see numbers/batching.py -- so it does not depend on the response schema),
plus fault-injection resilience and checkpoint-resume correctness.
"""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sage.numbers.telemetry import CallMeasurement, summarize_calls


FIXTURE = Path(__file__).parent / "fixtures" / "nca-simplified-mat5.json"
TOOL = Path(__file__).parents[2] / "tools" / "benchmark_nca.py"


def test_reused_batch_receipt_is_not_another_provider_call():
    """Member count and reuse must not inflate usage."""
    call = CallMeasurement("r1", "EXTRACTION", ("a", "b"), 10, 100, 50, None, None, "VALIDATED", False)
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
        "request_id": "r1", "phase": "EXTRACTION", "unit_ids": ("a",), "elapsed_ms": 10,
        "request_bytes": 100, "response_bytes": 50, "input_tokens": 20, "output_tokens": 5,
        "status": "VALIDATED", "reused": False,
    }
    fields.update(changes)
    with pytest.raises(ValueError, match=message):
        CallMeasurement(**fields)


def test_summary_rejects_conflicting_duplicate_request_evidence():
    """One provider request ID cannot authorize inconsistent transport evidence."""
    call = CallMeasurement("r1", "EXTRACTION", ("a",), 10, 100, 50, 20, 5, "VALIDATED", False)
    with pytest.raises(ValueError, match="Inconsistent"):
        summarize_calls((call, replace(call, response_bytes=51)))


def test_summary_keeps_failures_reuse_and_phase_totals_separate():
    """Failed attempts remain visible while reused receipts add no transport usage."""
    successful = CallMeasurement("r1", "EXTRACTION", ("a", "b"), 10, 100, 50, 20, 5, "VALIDATED", False)
    failed = CallMeasurement("r2", "EXTRACTION", ("a",), 7, 80, 0, 4, 0, "FAILED", False)
    result = summarize_calls((successful, replace(successful, reused=True), failed))
    assert result == {
        "provider_calls": 2, "reuse_events": 1, "failed_calls": 1,
        "phase_counts": {"EXTRACTION": 2}, "status_counts": {"FAILED": 1, "VALIDATED": 1},
        "elapsed_ms": 17, "request_bytes": 180, "response_bytes": 50,
        "input_tokens": 24, "output_tokens": 5,
        "failure_request_ids": ("r2",), "reused_request_ids": ("r1",),
    }


def test_simplified_fixture_has_the_historical_32_unit_coverage():
    """The benchmark corpus must retain the historical MAT 5:1-32 shape used for cap qualification."""
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = document["cases"]
    assert len(cases) == 32
    assert {case["case_id"] for case in cases} == {f"mat-5-{n}" for n in range(1, 33)}
    passes = [case for case in cases if case["expected_outcome"] == "PASS"]
    fails = [case for case in cases if case["expected_outcome"] == "FAIL"]
    assert len(passes) == 24 and len(fails) == 8
    for case in cases:
        assert case["reference_row"]["values"]
        assert isinstance(case["extracted_values"], list)


def _run_tool(receipt_path: Path, *extra: str) -> dict[str, object]:
    """Invoke the real benchmark CLI as a subprocess and load its published receipt."""
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--cases", str(FIXTURE), "--receipt", str(receipt_path), *extra],
        check=False, cwd=TOOL.parents[2], capture_output=True, text=True,
    )
    assert completed.returncode in (0, 1), completed.stderr
    return json.loads(receipt_path.read_text(encoding="utf-8"))


def test_synthetic_measurement_reproduces_the_historical_batch_count_at_cap_8(tmp_path: Path):
    """The simplified pipeline must issue exactly 4 extraction requests at the historical cap of 8.

    This is the same MAT 5:1-32 scope and the same shipped plan_batches/EvidencePolicy sizer
    the historical baseline-vs-optimized measurement used (see
    docs/advanced/release/NCA-OPTIMIZATION-QUALIFICATION.md); batching depends only on unit
    count and routed-SFM size, not on the extraction response schema, so this reproduces --
    rather than re-derives -- that number.
    """
    receipt = _run_tool(tmp_path / "cap8.json", "--batch-cap", "8")
    assert receipt["qualification_status"] == "PASS"
    assert receipt["case_count"] == 32
    assert receipt["calls"]["phase_counts"] == {"EXTRACTION": 4}
    assert receipt["calls"]["provider_calls"] == 4
    assert all(item["matches_expected"] for item in receipt["outcome_diffs"])
    assert receipt["resume"]["calls"]["provider_calls"] == 0
    assert receipt["resume"]["reuse_events"] == 4
    assert receipt["resume"]["equivalent_outcomes_and_coverage"] is True
    assert receipt["local_loads"]["reference_load_count"] == 1
    assert receipt["local_loads"]["profile_validation_count"] == 1
    for field in ("input_sha256", "fixture_sha256", "code_sha256"):
        assert len(receipt[field]) == 64


def test_synthetic_measurement_collapses_to_one_batch_at_the_shipped_cap_220(tmp_path: Path):
    """The shipped production cap (220) must collapse the same 32-unit scope to one request."""
    receipt = _run_tool(tmp_path / "cap220.json", "--batch-cap", "220")
    assert receipt["qualification_status"] == "PASS"
    assert receipt["calls"]["phase_counts"] == {"EXTRACTION": 1}


def test_outcome_changes_when_a_case_no_longer_reports_its_reference_number(tmp_path: Path):
    """A regressed extraction must be visibly detected, not silently pass."""
    import shutil
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["cases"][0]["extracted_values"] = []
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    shutil.copytree(FIXTURE.parent / document["reference_package"], fixture_dir / document["reference_package"])
    changed_fixture = fixture_dir / FIXTURE.name
    changed_fixture.write_text(json.dumps(document), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--cases", str(changed_fixture), "--batch-cap", "8",
         "--receipt", str(tmp_path / "changed-receipt.json")],
        check=False, cwd=TOOL.parents[2], capture_output=True, text=True,
    )
    assert completed.returncode == 1, completed.stderr
    receipt = json.loads((tmp_path / "changed-receipt.json").read_text(encoding="utf-8"))
    assert receipt["qualification_status"] == "FAIL"
    changed_diff = next(item for item in receipt["outcome_diffs"] if item["case_id"] == "mat-5-1")
    assert changed_diff["matches_expected"] is False
    assert changed_diff["observed_outcome"] == "FAIL"
    assert all(item["matches_expected"] for item in receipt["outcome_diffs"] if item["case_id"] != "mat-5-1")


@pytest.mark.parametrize("fault", ["transient", "malformed", "unsupported", "partial"])
def test_qualification_faults_remain_bounded_without_a_false_pass(tmp_path: Path, fault):
    """Every fault mode terminates with a bounded call count and never reports PASS."""
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--cases", str(FIXTURE), "--batch-cap", "8",
         "--fault", fault, "--receipt", str(tmp_path / f"{fault}.json")],
        check=False, cwd=TOOL.parents[2], capture_output=True, text=True,
    )
    assert completed.returncode == 1, completed.stderr
    receipt = json.loads((tmp_path / f"{fault}.json").read_text(encoding="utf-8"))
    assert receipt["qualification_status"] == "FAIL"
    bound = 2 * (2 * receipt["case_count"] - 4)
    assert receipt["calls"]["provider_calls"] <= bound
    if fault == "malformed":
        assert receipt["calls"]["provider_calls"] == bound
        assert receipt["calls"]["failed_calls"] == bound
    elif fault == "transient":
        assert receipt["calls"]["failed_calls"] == 1


def test_cold_process_requalifies_inputs_and_reuses_valid_checkpoints(tmp_path: Path):
    """A fresh resume-only process must requalify inputs once and issue zero provider calls."""
    checkpoint_root = tmp_path / "checkpoint"
    cold = _run_tool(tmp_path / "cold.json", "--batch-cap", "8", "--checkpoint-root", str(checkpoint_root))
    assert cold["calls"]["provider_calls"] == 4
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--cases", str(FIXTURE), "--batch-cap", "8",
         "--checkpoint-root", str(checkpoint_root), "--resume-only", "--receipt", str(tmp_path / "resume.json")],
        check=False, cwd=TOOL.parents[2], capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    resumed = json.loads((tmp_path / "resume.json").read_text(encoding="utf-8"))
    assert resumed["qualification_status"] == "PASS"
    assert resumed["calls"]["provider_calls"] == 0
    assert resumed["local_loads"]["reference_load_count"] == 1
    assert resumed["local_loads"]["profile_validation_count"] == 1


def test_fault_cli_rejects_unsupported_dispatch_before_work(tmp_path: Path):
    """Fault injection and checkpoint flags require synthetic mode; live requires its own args."""
    receipt_path = tmp_path / "rejected.json"
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--mode", "live", "--fault", "transient", "--receipt", str(receipt_path)],
        check=False, cwd=TOOL.parents[2], capture_output=True, text=True,
    )
    assert completed.returncode == 2
    assert "fault injection requires synthetic mode" in completed.stderr
    assert not receipt_path.exists()


def test_live_entrypoint_requires_bound_reviewed_labels_and_runtime_output(make_workspace, monkeypatch, tmp_path):
    """Live comparison never proceeds without an existing Run, matching scope and reviewed labels.

    No live provider call is ever made in this test; only the fail-closed argument and
    identity validation before any provider construction is exercised.
    """
    import argparse
    sys.path.insert(0, str(TOOL.parent))
    import benchmark_nca as tool
    from .test_nca_jobs import _prepare_nca_workspace, _route
    from sage.nca import create_nca_job, create_nca_run

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip="usWIP", package_id="SYNTHETIC_NCA_REFERENCE_1", style_selector="fixture-style/1")
    run = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")

    runtime = (config.runtime_state_root / "nca-benchmarks").resolve()
    args = argparse.Namespace(settings=config.settings_path, job=job.job_id, run=run.run_id,
        project="usWIP", scope="MAT 1", labels=None, receipt=runtime / "live-1.json")
    with pytest.raises(ValueError, match="reviewed labels"):
        tool.run_live(args)

    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps({"schema_version": "1.0", "reviewed_by": "Reviewer",
        "reviewed_at": "2026-09-29", "input_sha256": "0" * 64, "cases": []}), encoding="utf-8")
    args = replace_namespace(args, labels=labels_path, scope="MAT 2", receipt=runtime / "live-2.json")
    with pytest.raises(ValueError, match="Project/scope"):
        tool.run_live(args)


def replace_namespace(namespace, **changes):
    """Return a copy of one argparse.Namespace with the given attributes replaced."""
    import argparse
    return argparse.Namespace(**{**vars(namespace), **changes})
