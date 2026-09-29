#!/usr/bin/env python3
"""Measure the simplified NCA extraction-only pipeline with synthetic or live evidence.

Per the 2026-09-28 simplified-check rewrite, there is no longer a baseline/optimized
pipeline pair to compare against each other -- EXTRACTION is the only model phase,
and comparison against the indexed reference is local and deterministic
(numbers/compare.py). This tool measures the ONE remaining pipeline's real batch/call
counts, fault-injection resilience, and checkpoint-resume correctness against a
synthetic fixture (--mode synthetic), or validates and (if ever separately initiated)
runs it once against an existing sealed Run's reviewed-label corpus (--mode live).

The historical baseline-vs-optimized comparison numbers for the same MAT 5:1-32
scope (32 baseline extraction requests; 4 at the historical cap=8; 1 at the shipped
cap=220) are preserved as prior qualification evidence in
docs/advanced/release/NCA-OPTIMIZATION-QUALIFICATION.md -- they are not re-measured
here. This tool instead confirms the *simplified* pipeline reproduces the same batch
counts for the same fixture (batching is a pure function of unit count and routed-SFM
size via the unchanged plan_batches/EvidencePolicy sizer -- see
numbers/batching.py -- so it does not depend on the extraction response schema).
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
from dataclasses import asdict, replace
from fractions import Fraction
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from time import perf_counter_ns
from typing import Mapping, Sequence
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT / "system" / "src"))

from sage.executors import (  # noqa: E402
    ModelCapability,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ReasoningEffortOption,
)
from sage.jobs import JobStore  # noqa: E402
from sage.numbers.engine import evaluate_optimized_run  # noqa: E402
from sage.numbers.execution import ExecutionInputs, build_inventory, prepare_execution_inputs  # noqa: E402
from sage.numbers.model_tasks import NcaModelTasks  # noqa: E402
from sage.numbers.models import ProjectedUnit, ReferenceBundle, ReferenceRow, TargetUnit  # noqa: E402
from sage.numbers.policy import _plain as _plain_evidence, load_nca_run_snapshot, phase_contract_manifest  # noqa: E402
from sage.numbers.reference import load_reference  # noqa: E402
from sage.numbers.replay import PhaseStore  # noqa: E402
from sage.numbers.results import NCA_CAPABILITY_LIMITATION, group_findings  # noqa: E402
from sage.numbers.style import validate_style_profile  # noqa: E402
from sage.numbers.target import target_units  # noqa: E402
from sage.numbers.telemetry import summarize_calls  # noqa: E402
from sage.registry import load_ecosystem  # noqa: E402
from sage.usj import compile_usfm_text  # noqa: E402
from sage.vrs import VerseRef  # noqa: E402


_AREAS = ("digits", "bands", "grouping", "decimal", "ordinals", "fractions", "ranges", "qualifiers", "contexts", "units")


def _canonical_bytes(value: object) -> bytes:
    """Encode one JSON-compatible benchmark value with stable separators and ordering."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(payload: bytes) -> str:
    """Return the lowercase SHA-256 identity of exact benchmark bytes."""
    import hashlib
    return hashlib.sha256(payload).hexdigest()


def _reference(raw: str) -> VerseRef:
    """Parse one synthetic fixture coordinate through the production reference type."""
    book, coordinate = raw.split(" ", 1)
    chapter, verse = coordinate.split(":", 1)
    return VerseRef(book, int(chapter), int(verse))


def _load_cases(path: Path) -> tuple[bytes, tuple[Mapping[str, object], ...], Path]:
    """Read one closed synthetic case document and retain its exact fixture bytes."""
    payload = path.read_bytes()
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, Mapping) or document.get("schema_version") != "1.0":
        raise ValueError("NCA benchmark cases require schema version 1.0")
    reference_value = document.get("reference_package")
    if (not isinstance(reference_value, str) or not reference_value
            or Path(reference_value).is_absolute() or ".." in Path(reference_value).parts):
        raise ValueError("NCA benchmark reference_package must be a safe relative path")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("NCA benchmark cases must be a nonempty array")
    identifiers = []
    for case in cases:
        row = case.get("reference_row") if isinstance(case, Mapping) else None
        if (not isinstance(case, Mapping) or not isinstance(case.get("case_id"), str) or not case["case_id"]
                or not isinstance(case.get("language"), str) or not case["language"]
                or not isinstance(case.get("western_reference"), str)
                or not isinstance(case.get("body"), str)
                or not isinstance(row, Mapping) or not isinstance(row.get("values"), list)
                or not isinstance(case.get("extracted_values"), list)
                or not isinstance(case.get("expected_outcome"), str) or not case["expected_outcome"]):
            raise ValueError(f"Malformed NCA benchmark case: {case.get('case_id')!r}")
        identifiers.append(case["case_id"])
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("NCA benchmark case IDs must be unique")
    return payload, tuple(cases), (path.parent / reference_value).resolve()


def _build_reference_bundle(seed: ReferenceBundle, cases: Sequence[Mapping[str, object]]) -> ReferenceBundle:
    """Extend one genuinely qualified fixture package with the benchmark's synthetic rows."""
    rows: dict[VerseRef, ReferenceRow] = dict(seed.rows)
    for case in cases:
        ref = _reference(str(case["western_reference"]))
        row = case["reference_row"]
        values = tuple(Fraction(str(value)) for value in row["values"])
        rows[ref] = ReferenceRow(
            western_reference=ref, ol_reference=row["ol_reference"], language=str(row["language"]),
            ol_text=str(row["text"]), ol_values=values, niv_text=str(row["text"]), niv_values=values,
            metadata={"SOURCE_IDS": "SYNTHETIC-SOURCE"},
        )
    return ReferenceBundle(
        "nca-simplified-synthetic",
        _sha256(_canonical_bytes({"qualified_seed": seed.sha256, "synthetic_rows": [case["reference_row"] for case in cases]})),
        rows, dict(seed.variants), dict(seed.footnote_guidance), dict(seed.units),
        {**dict(seed.provenance), "SYNTHETIC-SOURCE": {"SOURCE_ID": "SYNTHETIC-SOURCE"}},
        "QUALIFIED",
    )


def _source_case(case: Mapping[str, object]) -> tuple[bytes, Mapping[str, object], ProjectedUnit]:
    """Build one production target projection and its exact synthetic SFM source."""
    ref = _reference(str(case["western_reference"]))
    sfm = f'\\id {ref.book}\n\\c {ref.chapter}\n\\v {ref.verse} {case["body"]}\n'
    document = compile_usfm_text(sfm)
    digest = _sha256(_canonical_bytes(document))
    target = replace(target_units(document, source_sha256=digest)[0], unit_id=str(case["case_id"]))
    projected = ProjectedUnit(target, (ref,), (ref,), "COORDINATE", "READY")
    return sfm.encode("utf-8"), document, projected


def _style_profile() -> dict[str, object]:
    """Return a fully explicit synthetic profile that makes no presentation claim."""
    return {
        "schema_version": "1.0",
        "profile": {
            "id": "nca-benchmark", "version": "1", "language": "en", "script": "Latn", "projects": ["*"],
            "source_guide": "Synthetic benchmark decisions", "recorded_by": "SAGE benchmark",
            "recorded_date": "2026-09-28", "status": "CONFIGURED",
        },
        "rules": {area: {"id": f"NCA-BENCHMARK-{area.upper()}", "status": "NOT_SPECIFIED"} for area in _AREAS},
    }


def _code_identity() -> tuple[str, dict[str, str]]:
    """Hash the exact implementation files that define this measurement."""
    paths = tuple(sorted(set(
        list((APP_ROOT / "system/src/sage").rglob("*.py"))
        + [APP_ROOT / "system/tools/benchmark_nca.py"]
        + list((APP_ROOT / "system/skills/nca-numbers").rglob("*.md"))
        + list((APP_ROOT / "system/config").rglob("*.yml"))
    )))
    files = {path.relative_to(APP_ROOT).as_posix(): _sha256(path.read_bytes()) for path in paths}
    aggregate = b"".join(name.encode("utf-8") + b"\0" + files[name].encode("ascii") + b"\n" for name in sorted(files))
    return _sha256(aggregate), files


class RecordedTransport:
    """Return fixture responses at the real provider boundary and inject bounded faults."""

    provider_id = "codex"

    def __init__(self, cases: Sequence[Mapping[str, object]], *, fault: str = "none") -> None:
        """Index literal case evidence and start an empty ProviderRequest ledger."""
        self._cases = {str(case["case_id"]): case for case in cases}
        self.owners: dict[str, str] = {}
        self.fault = fault
        self.requests: list[ProviderRequest] = []
        self.extraction_attempts = 0

    def status(self, *, model: str | None = None, reasoning_effort: str | None = None) -> ProviderStatus:
        """Expose one pinned recorded capability for normal production route resolution."""
        del model, reasoning_effort
        capability = ModelCapability(
            id="gpt-5.6-sol", model="gpt-5.6-sol", display_name="GPT-5.6 Sol",
            supported_reasoning_efforts=(ReasoningEffortOption("low"), ReasoningEffortOption("medium"), ReasoningEffortOption("high")),
            default_reasoning_effort="medium", is_default=True, identity_strength="PINNED", cost_class="STANDARD",
        )
        return ProviderStatus(provider="codex", available=True, ready=True, auth_mode="RECORDED_SYNTHETIC",
            version="nca-benchmark-1", model_capabilities=(capability,), diagnostic="recorded synthetic transport ready")

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Return a recorded EXTRACTION response, injecting the configured bounded fault once."""
        envelope = json.loads(request.prompt)
        payload = envelope["input"]
        if envelope["phase"] != "EXTRACTION":
            raise ValueError(f"Unsupported synthetic NCA phase: {envelope['phase']}")
        self.extraction_attempts += 1
        if self.fault == "transient" and self.extraction_attempts == 1:
            raise RuntimeError("Recorded transient provider failure")
        if self.fault == "malformed":
            self.requests.append(request)
            return ProviderResponse(provider="codex", model="gpt-5.6-sol", reasoning_effort="medium",
                content="{invalid", metadata={"request_id": f"recorded-{len(self.requests)}"})
        items = []
        for supplied in payload["work_units"]:
            case = self._cases[self.owners[supplied["input_id"]]]
            if self.fault in {"unsupported", "partial"}:
                items.append({"input_id": supplied["input_id"], "status": self.fault.upper(),
                    "limitations": ["Recorded language evidence limitation"], "values": []})
            else:
                items.append({"input_id": supplied["input_id"], "status": "COMPLETE", "limitations": [],
                    "values": list(case["extracted_values"])})
        raw = {"schema_version": "1.0", "phase": "EXTRACTION", "batch_id": payload["batch_id"], "work_units": items}
        content = json.dumps(raw, ensure_ascii=False, sort_keys=True)
        self.requests.append(request)
        return ProviderResponse(provider="codex", model="gpt-5.6-sol", reasoning_effort="medium",
            content=content, metadata={"request_id": f"recorded-{len(self.requests)}"})


def governance(tasks: NcaModelTasks) -> dict[str, object]:
    """Validate and fingerprint the single EXTRACTION phase contract independently of historical Runs."""
    manifest = phase_contract_manifest(tasks._config.root, tasks.route_snapshot)
    request_contracts = {}
    for attempt in tasks.attempts:
        envelope = json.loads(attempt.request["prompt"])
        if envelope["task_version"] != "nca-extraction-1.0":
            raise ValueError("Benchmark request used an unexpected task version")
        request_contracts[envelope["phase"]] = {
            "task_version": envelope["task_version"], "skill_sha256": _sha256(envelope["skill_contract"].encode()),
            "schema_sha256": _sha256(_canonical_bytes(_plain_evidence(attempt.request["schema"]))),
        }
    contract = {"phase_versions": {"EXTRACTION": "nca-extraction-1.0"}, "installed_manifest": manifest, "request_contracts": request_contracts}
    return {"status": "VALIDATED", "contract_sha256": _sha256(_canonical_bytes(contract)),
        "route_sha256": _sha256(_canonical_bytes(dict(tasks.route_snapshot))), **contract}


def input_identity(cases: Sequence[Mapping[str, object]], package_sha256: str, profile: Mapping[str, object],
                    checks: Mapping[str, object], mode: str) -> str:
    """Bind literal source bytes, projections, package, style, checks and comparison mode."""
    sources = []
    for case in cases:
        sfm, document, projected = _source_case(case)
        sources.append({"case": case, "sfm_sha256": _sha256(sfm), "usj_sha256": _sha256(_canonical_bytes(document)),
            "projection": {"status": projected.status, "precision": projected.precision,
                "target": [ref.label() for ref in projected.target.target_references],
                "western": [ref.label() for ref in projected.western_references]}})
    return _sha256(_canonical_bytes(_plain_evidence({"sources": sources, "package_sha256": package_sha256,
        "profile": profile, "checks": checks, "numeric_comparison_mode": mode})))


def run_synthetic(cases_path: Path, *, mode: str = "UNORDERED", fault: str = "none",
                   checkpoint_root: Path | None = None, resume_only: bool = False, max_units: int = 8) -> dict[str, object]:
    """Measure one qualified reference/style load and one complete-scope batched evaluation."""
    fixture_bytes, cases, reference_path = _load_cases(cases_path)
    started = perf_counter_ns()
    seed = load_reference(reference_path)
    reference_ms = (perf_counter_ns() - started) // 1_000_000
    bundle = _build_reference_bundle(seed, cases)
    started = perf_counter_ns()
    profile = validate_style_profile(_style_profile())
    profile_ms = (perf_counter_ns() - started) // 1_000_000
    documents: dict[str, Mapping[str, object]] = {}
    projected_units = []
    for case in cases:
        _sfm, document, projected = _source_case(case)
        documents[projected.target.source_sha256] = document
        projected_units.append(projected)
    projected_units = tuple(projected_units)
    transport = RecordedTransport(cases, fault=fault)
    checks = {"number_accuracy": True, "presentation_consistency": True, "footnote_review": False}
    if checkpoint_root is not None:
        checkpoint_root = checkpoint_root.resolve()
        if resume_only and not checkpoint_root.is_dir():
            raise ValueError("Cold resume requires an existing checkpoint directory")
        checkpoint_root.mkdir(parents=True, exist_ok=True)
    data_context = nullcontext(str(checkpoint_root)) if checkpoint_root is not None else tempfile.TemporaryDirectory(prefix="sage-nca-benchmark-")
    execution_started = perf_counter_ns()
    with data_context as data_home:
        with patch.dict(os.environ, {"SAGE_DATA_HOME": data_home}, clear=False):
            tasks = NcaModelTasks(type("BenchmarkConfig", (), {"root": APP_ROOT})(),
                settings={"selected_provider": "codex", "providers": {"codex": {"enabled": True}}}, transport=transport)
            tasks.phase_resume_only = resume_only
            route = dict(tasks.route_identity)
            contracts = phase_contract_manifest(APP_ROOT, tasks.route_snapshot)
            policy = {"schema_version": "2.0", "wip": {"language": "en", "script": "Latn"},
                "reference_package": {"diagnostics": []}, "model_route": dict(tasks.route_snapshot),
                "checks": checks, "numeric_comparison_mode": mode,
                "optimization": {"contract_version": "nca-optimization-2.0", "reuse_scope": "TASK",
                    "extraction_batch_max_units": max_units, "request_concurrency": 1, "transient_retries": 1}}
            inputs = ExecutionInputs(bundle, profile, policy, projected_units, (),
                tuple(x.target.unit_id for x in projected_units), tuple(x.western_references[0] for x in projected_units),
                documents, "MAT 5", _canonical_bytes(policy),
                {name: (APP_ROOT / name).read_bytes() for name in contracts["files"]})
            inventory = build_inventory(inputs)
            transport.owners.update({x.input_id: x.owner_unit_id for x in inventory.stream_inputs})
            task_root = Path(data_home) / "task"
            task_root.mkdir(exist_ok=True)
            fingerprint = _sha256(b"nca-simplified-benchmark")
            cold_started_ns = perf_counter_ns()
            result = evaluate_optimized_run(inputs, model_tasks=tasks, phase_store=PhaseStore(task_root, task_fingerprint=fingerprint), run_id="benchmark")
            cold_elapsed_ms = (perf_counter_ns() - cold_started_ns) // 1_000_000
            resumed_tasks = NcaModelTasks(type("BenchmarkConfig", (), {"root": APP_ROOT})(),
                settings={"selected_provider": "codex", "providers": {"codex": {"enabled": True}}}, transport=transport)
            resumed_tasks.phase_resume_only = True
            resume_started_ns = perf_counter_ns()
            resumed = evaluate_optimized_run(inputs, model_tasks=resumed_tasks, phase_store=PhaseStore(task_root, task_fingerprint=fingerprint), run_id="benchmark")
            resume_elapsed_ms = (perf_counter_ns() - resume_started_ns) // 1_000_000
            reuse_events = len(resumed_tasks.phase_session.reused)
            resume_equivalent = resumed.groups == result.groups and resumed.coverage == result.coverage
            outcomes = [{"case_id": group.projected.target.unit_id,
                "findings": [_plain_evidence(finding) for finding in group_findings(group)],
                "values": [str(value) for value in group.extraction.values], "outcome": group.comparison.outcome,
                "limitations": list(group.limitations), "coverage_status": result.coverage["coverage"]}
                for group in result.groups]
            calls = summarize_calls(tuple(attempt.measurement for attempt in tasks.attempts))
            governance_receipt = governance(tasks)
    driver_elapsed_ms = (perf_counter_ns() - execution_started) // 1_000_000
    expected_by_id = {str(case["case_id"]): case for case in cases}
    diffs = [{"case_id": item["case_id"], "expected_outcome": expected_by_id[item["case_id"]]["expected_outcome"],
        "observed_outcome": item["outcome"], "matches_expected": item["outcome"] == expected_by_id[item["case_id"]]["expected_outcome"]}
        for item in outcomes]
    code_sha256, code_files = _code_identity()
    return {
        "schema_version": "1.0", "benchmark_id": "nca-simplified-extraction-v1", "mode": "synthetic", "fault": fault,
        "case_count": len(cases), "extraction_batch_max_units": max_units, "numeric_comparison_mode": mode,
        "fixture_sha256": _sha256(fixture_bytes), "input_sha256": input_identity(cases, bundle.sha256, profile, checks, mode),
        "governance": governance_receipt,
        "resume": {"elapsed_ms": resume_elapsed_ms, "calls": summarize_calls(tuple(attempt.measurement for attempt in resumed_tasks.attempts)),
            "reuse_events": reuse_events, "equivalent_outcomes_and_coverage": resume_equivalent},
        "code_sha256": code_sha256, "code_files": code_files,
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(), "platform": platform.platform()},
        "transport_boundary": "sage.executors.ProviderRequest", "route": route, "calls": calls,
        "local_loads": {"reference_load_count": 1, "reference_load_elapsed_ms": reference_ms, "reference_package_sha256": seed.sha256,
            "profile_validation_count": 1, "profile_validation_elapsed_ms": profile_ms},
        "execution_elapsed_ms": cold_elapsed_ms, "driver_elapsed_ms": driver_elapsed_ms,
        "outcomes": outcomes, "outcome_diffs": diffs,
        "qualification_status": "PASS" if fault == "none" and all(item["matches_expected"] for item in diffs)
            and result.coverage["coverage"] in {"COMPLETE", "COMPLETE_WITH_RESTRICTIONS"} else "FAIL",
        "live_status": "LIVE_MODEL_BENCHMARK_NOT_RUN", "sqs_status": "NOT_APPLIED",
        "capability_limitations": NCA_CAPABILITY_LIMITATION,
    }


CRITICAL_CATEGORIES = frozenset({"omission", "extra_number", "referent"})


def live_input_identity(inputs: ExecutionInputs) -> str:
    """Bind exact sealed source, reference, mapping, style, scope, policy and projection identities."""
    value = {"policy_sha256": _sha256(inputs.policy_bytes), "source_files": dict(inputs.policy["wip"]["files"]),
        "package": inputs.policy["reference_package"], "style": inputs.policy["number_style"],
        "scope": inputs.requested_scope, "expected_ids": inputs.expected_unit_ids,
        "expected_references": [ref.label() for ref in inputs.expected_references],
        "projection": [{"unit_id": unit.target.unit_id, "source_sha256": unit.target.source_sha256,
            "status": unit.status, "precision": unit.precision,
            "target": [ref.label() for ref in unit.target.target_references],
            "western": [ref.label() for ref in unit.western_references]} for unit in inputs.projected_units]}
    return _sha256(_canonical_bytes(_plain_evidence(value)))


def reviewed_labels(path: Path, inputs: ExecutionInputs) -> tuple[dict[str, object], str]:
    """Require operator-reviewed exact ordered-value labels for every protected body unit."""
    content = path.read_bytes()
    labels = json.loads(content)
    if (not isinstance(labels, dict) or labels.get("schema_version") != "1.0"
            or not isinstance(labels.get("reviewed_by"), str) or not labels["reviewed_by"].strip()
            or not isinstance(labels.get("reviewed_at"), str) or not labels["reviewed_at"].strip()
            or labels.get("input_sha256") != live_input_identity(inputs)):
        raise ValueError("Reviewed labels must bind the exact current input identity")
    cases = labels.get("cases")
    if (not isinstance(cases, list) or len(cases) != len(inputs.expected_unit_ids)
            or {case.get("unit_id") for case in cases if isinstance(case, dict)} != set(inputs.expected_unit_ids)):
        raise ValueError("Reviewed labels must cover every selected unit exactly once")
    for case in cases:
        if (not isinstance(case.get("categories"), list) or not case["categories"]
                or any(not isinstance(item, str) or not item for item in case["categories"])
                or not isinstance(case.get("values"), list)
                or any(not isinstance(item, str) or not item for item in case["values"])
                or not isinstance(case.get("outcome"), str) or not case["outcome"]):
            raise ValueError("Reviewed labels lack typed extraction evidence")
    return labels, _sha256(content)


def case_metrics(group, label: Mapping[str, object]) -> dict[str, object]:
    """Compare exact ordered values and the comparison outcome against one reviewed label."""
    observed = [str(value) for value in group.extraction.values]
    expected = list(label["values"])
    known = group.extraction.status == "COMPLETE"
    critical = bool(set(label["categories"]) & CRITICAL_CATEGORIES)
    available = not critical or group.comparison.outcome != "NOT_ASSESSED"
    return {"unit_id": label["unit_id"], "categories": label["categories"], "extraction_status": group.extraction.status,
        "exact_values": observed == expected if known else None,
        "outcome_correct": (group.comparison.outcome == label["outcome"]) if available else None,
        "assessment_available": available, "outcome": group.comparison.outcome,
        "unresolved": not known or not available or group.comparison.outcome == "NEEDS_REVIEW"}


def run_live(args: argparse.Namespace) -> dict[str, object]:
    """Validate explicit selection before running once against an existing sealed Run."""
    required = ("settings", "job", "run", "project", "scope", "labels")
    if any(not getattr(args, name, None) for name in required):
        raise ValueError("Live benchmark requires settings, job, run, project, scope and reviewed labels")
    config = load_ecosystem(args.settings)
    destination = args.receipt.expanduser().resolve()
    runtime = (config.runtime_state_root / "nca-benchmarks").resolve()
    if not destination.is_relative_to(runtime) or destination.exists():
        raise ValueError("Live receipt requires a new path under runtime_state_root/nca-benchmarks")
    store = JobStore(config.root, config.settings_path)
    job = store.load_job(args.job, tool="nca")
    run = store.load_run(job, args.run)
    if job.bindings["wip"] != args.project or run.scope != args.scope:
        raise ValueError("Selected Project/scope differs from the explicit NCA Run")
    policy = load_nca_run_snapshot(run.root)
    inputs = prepare_execution_inputs(config, job, run, policy)
    labels, label_sha = reviewed_labels(args.labels, inputs)
    runtime.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="live-", dir=runtime))
    started = perf_counter_ns()
    tasks = NcaModelTasks(config, expected_route_id=policy["model_route"]["route_id"])
    if dict(tasks.route_snapshot) != dict(policy["model_route"]):
        raise ValueError("Current provider route differs from the selected sealed Run")
    result = evaluate_optimized_run(inputs, model_tasks=tasks, run_id="live-benchmark",
        phase_store=PhaseStore(session, task_fingerprint=live_input_identity(inputs)))
    raw = [{"measurement": asdict(attempt.measurement), "request": _plain_evidence(attempt.request),
        "raw_response": attempt.raw_response, "response_identity": _plain_evidence(attempt.response_identity)}
        for attempt in tasks.attempts]
    (session / "provider-evidence.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    by_id = {case["unit_id"]: case for case in labels["cases"]}
    metrics = [case_metrics(group, by_id[group.projected.target.unit_id]) for group in result.groups]
    categories = {item for case in labels["cases"] for item in case["categories"]}
    missing = sorted(CRITICAL_CATEGORIES - categories)
    unavailable = any(not item["assessment_available"] for item in metrics)
    accurate = all(item["exact_values"] is True and item["outcome_correct"] and not item["unresolved"] for item in metrics)
    code_sha256, code_files = _code_identity()
    return {"schema_version": "1.0", "mode": "live", "input_sha256": live_input_identity(inputs), "labels_sha256": label_sha,
        "project": args.project, "scope": args.scope, "job_id": job.job_id, "run_id": run.run_id,
        "style_sha256": policy["number_style"]["sha256"], "route": dict(policy["model_route"]),
        "governance": governance(tasks), "calls": summarize_calls(tuple(attempt.measurement for attempt in tasks.attempts)),
        "elapsed_ms": (perf_counter_ns() - started) // 1_000_000, "coverage": _plain_evidence(result.coverage), "cases": metrics,
        "qualification_status": "INCOMPLETE" if missing or unavailable else ("PASS_SELECTED_CASES" if accurate else "FAIL"),
        "missing_critical_categories": missing, "case_categories": {case["unit_id"]: case["categories"] for case in labels["cases"]},
        "code_sha256": code_sha256, "code_files": code_files, "session_id": session.name,
        "sqs_status": "NOT_APPLIED", "capability_limitations": NCA_CAPABILITY_LIMITATION,
        "qualification_limit": "Selected reviewed cases only; no broad model or language qualification."}


def _parser() -> argparse.ArgumentParser:
    """Expose the synthetic measurement and explicit existing-Run live comparison selectors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="synthetic", choices=("synthetic", "live"))
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--fault", choices=("none", "transient", "malformed", "unsupported", "partial"), default="none")
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--resume-only", action="store_true")
    parser.add_argument("--comparison-mode", choices=("ORDERED", "UNORDERED"), default="UNORDERED")
    parser.add_argument("--batch-cap", type=int, default=8, help="extraction_batch_max_units to exercise")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--job")
    parser.add_argument("--run")
    parser.add_argument("--project")
    parser.add_argument("--scope")
    parser.add_argument("--labels", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the selected benchmark scope and atomically publish its evidence receipt."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.fault != "none" and args.mode != "synthetic":
        parser.error("fault injection requires synthetic mode")
    if (args.checkpoint_root or args.resume_only) and (args.mode != "synthetic" or (args.resume_only and args.checkpoint_root is None)):
        parser.error("checkpoint flags require synthetic mode and a checkpoint root for resume")
    if args.mode == "live":
        receipt = run_live(args)
    elif args.cases is None:
        parser.error("synthetic mode requires --cases")
    else:
        receipt = run_synthetic(args.cases.resolve(), mode=args.comparison_mode, fault=args.fault,
            checkpoint_root=args.checkpoint_root, resume_only=args.resume_only, max_units=args.batch_cap)
    destination = args.receipt.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    staging.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(staging, destination)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 1 if receipt.get("qualification_status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
