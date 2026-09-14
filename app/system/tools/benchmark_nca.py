#!/usr/bin/env python3
"""Measure versioned NCA strategies with synthetic or separately initiated live evidence."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from fractions import Fraction
import hashlib
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
from sage.numbers import engine as engine_module  # noqa: E402
from sage.numbers import style as style_module  # noqa: E402
from sage.numbers.engine import evaluate_run  # noqa: E402
from sage.numbers.model_tasks import NcaModelTasks  # noqa: E402
from sage.numbers.models import (  # noqa: E402
    NumericExpression,
    ProjectedUnit,
    ReferenceBundle,
    ReferenceRow,
    TargetUnit,
)
from sage.numbers.policy import _plain as _plain_evidence
from sage.numbers.results import NCA_CAPABILITY_LIMITATION
from sage.numbers.reference import load_reference  # noqa: E402
from sage.numbers.telemetry import CallMeasurement, summarize_calls  # noqa: E402
from sage.vrs import VerseRef  # noqa: E402


_AREAS = (
    "digits",
    "bands",
    "grouping",
    "decimal",
    "ordinals",
    "fractions",
    "ranges",
    "qualifiers",
    "contexts",
    "units",
)


def _canonical_bytes(value: object) -> bytes:
    """Encode one JSON-compatible benchmark value with stable separators and ordering."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    """Return the lowercase SHA-256 identity of exact benchmark bytes."""
    return hashlib.sha256(payload).hexdigest()


def _reference(raw: str) -> VerseRef:
    """Parse one synthetic fixture coordinate through the production reference type."""
    book, coordinate = raw.split(" ", 1)
    chapter, verse = coordinate.split(":", 1)
    return VerseRef(book, int(chapter), int(verse))


def _expression(raw: Mapping[str, object], *, expression_id: str, stream_id: str) -> NumericExpression:
    """Construct one exact typed expression from a literal fixture golden."""
    representations = tuple(
        {
            "surface": item["surface"],
            "span": tuple(item["span"]),
            "value": item["value"],
        }
        for item in raw.get("representations", [])
    )
    return NumericExpression(
        values=tuple(Fraction(str(value)) for value in raw["values"]),
        kind=str(raw["kind"]),
        surface=str(raw["surface"]),
        span=tuple(raw["span"]),
        unit=raw["unit"],
        qualifier=str(raw["qualifier"]),
        role=str(raw["role"]),
        expression_id=expression_id,
        stream_id=stream_id,
        representations=representations,
    )


def _plain_expression(expression: NumericExpression) -> dict[str, object]:
    """Serialize a typed expression without losing exact rational values or spans."""
    return {
        "expression_id": expression.expression_id,
        "stream_id": expression.stream_id,
        "surface": expression.surface,
        "span": list(expression.span),
        "values": [str(value) for value in expression.values],
        "kind": expression.kind,
        "unit": expression.unit,
        "qualifier": expression.qualifier,
        "role": expression.role,
        "representations": [
            {
                "surface": item["surface"],
                "span": list(item["span"]),
                "value": item["value"],
            }
            for item in expression.representations
        ],
    }


def _golden_expression(expression: Mapping[str, object]) -> dict[str, object]:
    """Select the exact semantic and surface fields shared by fixture and observed evidence."""
    return {
        "surface": expression["surface"],
        "span": list(expression["span"]),
        "values": list(expression["values"]),
        "kind": expression["kind"],
        "unit": expression["unit"],
        "qualifier": expression["qualifier"],
        "role": expression["role"],
        "representations": [
            {
                "surface": item["surface"],
                "span": list(item["span"]),
                "value": item["value"],
            }
            for item in expression.get("representations", [])
        ],
    }


def _load_cases(
    path: Path,
) -> tuple[bytes, tuple[Mapping[str, object], ...], Path]:
    """Read one closed synthetic case document and retain its exact fixture bytes."""
    payload = path.read_bytes()
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, Mapping) or document.get("schema_version") != "1.0":
        raise ValueError("NCA benchmark cases require schema version 1.0")
    reference_value = document.get("reference_package")
    if (
        not isinstance(reference_value, str)
        or not reference_value
        or Path(reference_value).is_absolute()
        or ".." in Path(reference_value).parts
    ):
        raise ValueError("NCA benchmark reference_package must be a safe relative path")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("NCA benchmark cases must be a nonempty array")
    identifiers = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("Every NCA benchmark case must be an object")
        case_id = case.get("case_id")
        expected = case.get("expected")
        streams = case.get("streams")
        if (
            not isinstance(case_id, str)
            or not case_id
            or not isinstance(expected, Mapping)
            or not isinstance(streams, Mapping)
            or set(streams) != {"body", "notes", "headings"}
            or not isinstance(streams["body"], str)
            or not isinstance(streams["notes"], list)
            or not isinstance(streams["headings"], list)
        ):
            raise ValueError(f"Malformed NCA benchmark case: {case_id!r}")
        identifiers.append(case_id)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("NCA benchmark case IDs must be unique")
    return payload, tuple(cases), (path.parent / reference_value).resolve()


def _build_reference_bundle(
    seed: ReferenceBundle,
    cases: Sequence[Mapping[str, object]],
) -> ReferenceBundle:
    """Extend one genuinely qualified fixture package with the benchmark's synthetic rows."""
    rows: dict[VerseRef, ReferenceRow] = dict(seed.rows)
    variants: dict[VerseRef, Mapping[str, object]] = dict(seed.variants)
    guidance: dict[VerseRef, Mapping[str, object]] = dict(seed.footnote_guidance)
    for case in cases:
        for raw_row in case["reference_rows"]:
            ref = _reference(str(raw_row["western_reference"]))
            source = tuple(
                _expression(item, expression_id=f"ol-{ref.label()}-{index}", stream_id="ol")
                for index, item in enumerate(raw_row["expressions"], start=1)
            )
            values = tuple(value for expression in source for value in expression.values)
            registered_absence = raw_row.get("registered_absence") is True
            rows[ref] = ReferenceRow(
                western_reference=ref,
                ol_reference=raw_row["ol_reference"],
                language=str(raw_row["language"]),
                ol_text=str(raw_row["text"]),
                ol_values=values,
                niv_text=str(raw_row["text"]),
                niv_values=values,
                metadata={
                    "SOURCE_IDS": "SYNTHETIC-SOURCE",
                    "FOOTNOTE_IF_TARGET_FOLLOWS_OL": "NONE",
                },
            )
            if registered_absence:
                variants[ref] = {"NIV_VALUE_RESEARCHED": ""}
                guidance[ref] = {
                    "ALT_NIV_VALUES": "",
                    "SOURCE_IDS": "SYNTHETIC-SOURCE",
                    "FOOTNOTE_IF_TARGET_FOLLOWS_OL": "NONE",
                    "VALIDATION_IF_TARGET_FOLLOWS_OL": "NO_CONFIGURED_OL_READING",
                }
    return ReferenceBundle(
        "nca-optimization-synthetic",
        _sha256(
            _canonical_bytes(
                {
                    "qualified_seed": seed.sha256,
                    "synthetic_rows": [case["reference_rows"] for case in cases],
                }
            )
        ),
        rows,
        variants,
        guidance,
        dict(seed.units),
        {
            **dict(seed.provenance),
            "SYNTHETIC-SOURCE": {"SOURCE_ID": "SYNTHETIC-SOURCE"},
        },
        "QUALIFIED",
    )


def _target_case(case: Mapping[str, object]) -> ProjectedUnit:
    """Build one production target unit for validation of recorded provider evidence."""
    case_id = str(case["case_id"])
    references = tuple(_reference(value) for value in case["western_references"])
    text = str(case["streams"]["body"])
    target = TargetUnit(
        case_id,
        references,
        text,
        (),
        _sha256(text.encode("utf-8")),
        {"line_start": 1, "line_end": 1},
    )
    rows = tuple(case["reference_rows"])
    status = (
        "REGISTERED_ABSENCE"
        if len(rows) == 1 and rows[0].get("registered_absence") is True
        else "READY"
    )
    projected = ProjectedUnit(target, references, references, "COORDINATE", status)
    return projected


def _style_profile() -> dict[str, object]:
    """Return a fully explicit synthetic profile that makes no presentation claim."""
    return {
        "schema_version": "1.0",
        "profile": {
            "id": "nca-benchmark",
            "version": "1",
            "language": "en",
            "script": "Latn",
            "projects": ["*"],
            "source_guide": "Synthetic benchmark decisions",
            "recorded_by": "SAGE benchmark",
            "recorded_date": "2026-09-10",
            "status": "CONFIGURED",
        },
        "rules": {
            area: {"id": f"NCA-BENCHMARK-{area.upper()}", "status": "NOT_SPECIFIED"}
            for area in _AREAS
        },
    }


def _role_span(text: str, role: str) -> list[dict[str, object]]:
    """Return literal role evidence by locating the fixture's exact referent surface."""
    start = text.casefold().find(role.casefold())
    if start < 0:
        raise ValueError(f"Role {role!r} is not present in benchmark text {text!r}")
    end = start + len(role)
    return [{"start": start, "end": end, "surface": text[start:end]}]


def _response_expression(
    raw: Mapping[str, object],
    *,
    expression_id: str,
    stream_id: str,
    text: str,
) -> dict[str, object]:
    """Render one literal golden in the strict version-1 provider response shape."""
    role = str(raw["role"])
    return {
        "expression_id": expression_id,
        "stream_id": stream_id,
        "surface": raw["surface"],
        "span": {"start": raw["span"][0], "end": raw["span"][1]},
        "values": list(raw["values"]),
        "kind": raw["kind"],
        "unit": raw["unit"],
        "qualifier": raw["qualifier"],
        "role": role,
        "role_spans": _role_span(text, role),
        "representations": [
            {
                "surface": item["surface"],
                "span": {"start": item["span"][0], "end": item["span"][1]},
                "value": item["value"],
            }
            for item in raw.get("representations", [])
        ],
    }


class _RecordedTransport:
    """Return fixture responses at the real provider boundary and measure sealed requests."""

    # Literal fixture authorities stay separate from the model response and request ledger.
    provider_id = "codex"

    def __init__(self, cases: Sequence[Mapping[str, object]]) -> None:
        """Index literal case evidence and start an empty ProviderRequest ledger."""
        self._cases = {str(case["case_id"]): case for case in cases}
        self._rows = {
            str(_reference(str(row["western_reference"]))): row
            for case in cases
            for row in case["reference_rows"]
        }
        self.calls: list[CallMeasurement] = []
        self.requests: list[ProviderRequest] = []

    def status(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderStatus:
        """Expose one pinned recorded capability for normal production route resolution."""
        del model, reasoning_effort
        capability = ModelCapability(
            id="gpt-5.6-sol",
            model="gpt-5.6-sol",
            display_name="GPT-5.6 Sol",
            supported_reasoning_efforts=(
                ReasoningEffortOption("low"),
                ReasoningEffortOption("medium"),
                ReasoningEffortOption("high"),
            ),
            default_reasoning_effort="medium",
            is_default=True,
            identity_strength="PINNED",
            cost_class="STANDARD",
        )
        return ProviderStatus(
            provider="codex",
            available=True,
            ready=True,
            auth_mode="RECORDED_SYNTHETIC",
            version="nca-benchmark-1",
            model_capabilities=(capability,),
            diagnostic="recorded synthetic transport ready",
        )

    def _extraction_response(
        self, payload: Mapping[str, object]
    ) -> dict[str, object]:
        """Build one strict extraction response from the selected literal case."""
        work_unit = payload["work_units"][0]
        case_id = str(work_unit["unit_id"])
        case = self._cases[case_id]
        text = str(case["streams"]["body"])
        expressions = [
            _response_expression(
                item,
                expression_id=f"target-{case_id}-{index}",
                stream_id="main",
                text=text,
            )
            for index, item in enumerate(case["expected"]["expressions"], start=1)
        ]
        return {
            "schema_version": "1.0",
            "phase": "EXTRACTION",
            "work_units": [
                {
                    "unit_id": case_id,
                    "status": "COMPLETE",
                    "limitations": [],
                    "expressions": expressions,
                }
            ],
        }

    def _correspondence_response(
        self, payload: Mapping[str, object]
    ) -> dict[str, object]:
        """Build exact source and target-role evidence for one production row request."""
        case_id = str(payload["unit_id"])
        case = self._cases[case_id]
        target_text = str(case["streams"]["body"])
        reference_label = str(payload["authority"]["western_reference"])
        row = self._rows[reference_label]
        source_label = str(row["western_reference"])
        source_text = str(row["text"])
        source = [
            _response_expression(
                item,
                expression_id=f"ol-{source_label}-{index}",
                stream_id="ol",
                text=source_text,
            )
            for index, item in enumerate(row["expressions"], start=1)
        ]
        target_roles = [
            {
                "expression_id": expression["expression_id"],
                "role": expression["role"],
                "role_spans": _role_span(target_text, str(expression["role"])),
            }
            for expression in payload["target"]["expressions"]
        ]
        return {
            "schema_version": "1.0",
            "phase": "CORRESPONDENCE",
            "unit_id": case_id,
            "status": "COMPLETE",
            "limitations": [],
            "source_expressions": source,
            "target_roles": target_roles,
        }

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Return a recorded response and measure the actual sealed request contract."""
        started_ns = perf_counter_ns()
        envelope = json.loads(request.prompt)
        phase = str(envelope["phase"])
        payload = envelope["input"]
        if phase == "EXTRACTION":
            response = self._extraction_response(payload)
            unit_id = str(payload["work_units"][0]["unit_id"])
        elif phase == "CORRESPONDENCE":
            response = self._correspondence_response(payload)
            unit_id = str(payload["unit_id"])
        else:
            raise ValueError(f"Unsupported synthetic NCA phase: {phase}")
        content = json.dumps(response, ensure_ascii=False, sort_keys=True)
        self.requests.append(request)
        request_id = f"recorded-{len(self.requests)}"
        request_wire = {
            "prompt": request.prompt,
            "schema": request.schema,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "timeout_seconds": request.timeout_seconds,
        }
        self.calls.append(
            CallMeasurement(
                request_id=request_id,
                phase=phase,
                unit_ids=(unit_id,),
                elapsed_ms=(perf_counter_ns() - started_ns) // 1_000_000,
                request_bytes=len(_canonical_bytes(request_wire)),
                response_bytes=len(content.encode("utf-8")),
                input_tokens=None,
                output_tokens=None,
                status="SUCCESS",
                reused=False,
            )
        )
        return ProviderResponse(
            provider="codex",
            model="gpt-5.6-sol",
            content=content,
            metadata={"request_id": request_id},
            reasoning_effort="medium",
        )


def _code_identity() -> tuple[str, dict[str, str]]:
    """Hash the exact implementation files that define this baseline measurement."""
    paths = tuple(sorted(set(
        list((APP_ROOT / "system/src/sage").rglob("*.py"))
        + list((APP_ROOT / "system/tools").glob("benchmark_nca*.py"))
        + list((APP_ROOT / "system/skills/nca-numbers").rglob("*.md"))
        + list((APP_ROOT / "system/config").rglob("*.yml"))
    )))
    files = {
        path.relative_to(APP_ROOT).as_posix(): _sha256(path.read_bytes())
        for path in paths
    }
    aggregate = b"".join(
        name.encode("utf-8") + b"\0" + files[name].encode("ascii") + b"\n"
        for name in sorted(files)
    )
    return _sha256(aggregate), files


def run_synthetic_baseline(cases_path: Path) -> dict[str, object]:
    """Execute all literal cases through version-1 production evaluation APIs."""
    from benchmark_nca_qualification import source_case, input_identity, governance, finding_diffs
    fixture_bytes, cases, reference_path = _load_cases(cases_path)

    reference_loads: list[int] = []

    def measured_reference_load(path: Path) -> ReferenceBundle:
        """Count and time each completed call through the production package loader."""
        started = perf_counter_ns()
        loaded = load_reference(path)
        reference_loads.append((perf_counter_ns() - started) // 1_000_000)
        return loaded

    seed_bundle = measured_reference_load(reference_path)
    bundle = _build_reference_bundle(seed_bundle, cases)

    targets: dict[str, ProjectedUnit] = {
        str(case["case_id"]): source_case(case)[2] for case in cases
    }
    transport = _RecordedTransport(cases)
    policy = {
        "checks": {
            "number_accuracy": True,
            "presentation_consistency": True,
            "footnote_review": False,
        }
    }
    profile = _style_profile()
    profile_validation_count = 0
    profile_validation_elapsed_ns = 0
    original_validate = style_module.validate_style_profile

    def measured_validate(*args: object, **kwargs: object) -> Mapping[str, object]:
        """Measure each validation actually requested by engine and style production code."""
        nonlocal profile_validation_count, profile_validation_elapsed_ns
        started = perf_counter_ns()
        try:
            return original_validate(*args, **kwargs)
        finally:
            profile_validation_count += 1
            profile_validation_elapsed_ns += perf_counter_ns() - started

    outcomes = []
    execution_started = perf_counter_ns()
    # Retain the baseline algorithm's second, per-stream style validation. Each
    # fixture is a separate one-unit run; current public evaluate_run validates at
    # its run boundary, and this baseline-only adapter restores assess_style's
    # original strict traversal. Optimized measurements must not use this adapter.
    with tempfile.TemporaryDirectory(prefix="sage-nca-benchmark-") as data_home:
        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(os.environ, {"SAGE_DATA_HOME": data_home}, clear=False)
            )
            stack.enter_context(
                patch.object(engine_module, "validate_style_profile", measured_validate)
            )
            stack.enter_context(
                patch.object(style_module, "validate_style_profile", measured_validate)
            )
            stack.enter_context(
                patch.object(engine_module, "_assess_prepared_style", style_module.assess_style)
            )
            settings = {
                "selected_provider": "codex",
                "providers": {"codex": {"enabled": True}},
            }
            tasks = NcaModelTasks(
                type("BenchmarkConfig", (), {"root": APP_ROOT})(),
                settings=settings,
                transport=transport,
            )
            route_identity = dict(tasks.route_identity)
            for case in cases:
                case_id = str(case["case_id"])
                projected = targets[case_id]
                result = evaluate_run(
                    (projected,),
                    bundle=bundle,
                    language=str(case["language"]),
                    language_profile={"language": case["language"]},
                    style_profile=profile,
                    check_policy=policy,
                    run_id=f"benchmark-{case_id}",
                    expected_unit_ids=(case_id,),
                    model_tasks=tasks,
                )
                actual = result.units[0]
                outcomes.append(
                    {
                        "case_id": case_id,
                        "findings": _plain_evidence(result.findings),
                        "expressions": [
                            _plain_expression(item) for item in actual.extraction.expressions
                        ],
                        "outcome": actual.final_outcome,
                        "semantic_reason_codes": list(
                            actual.reading.semantic.reason_codes
                        ),
                        "limitations": list(actual.limitations),
                        "coverage_status": result.coverage["coverage"],
                    }
                )
    execution_elapsed_ms = (perf_counter_ns() - execution_started) // 1_000_000

    expected_by_id = {str(case["case_id"]): case["expected"] for case in cases}
    semantic_diffs = [
        {
            "case_id": item["case_id"],
            "expected_baseline": expected_by_id[item["case_id"]]["baseline_outcome"],
            "observed": item["outcome"],
            "matches_baseline": (
                item["outcome"]
                == expected_by_id[item["case_id"]]["baseline_outcome"]
            ),
            "observed_uncertainty": item["semantic_reason_codes"],
            "expected_baseline_uncertainty": expected_by_id[item["case_id"]][
                "baseline_uncertainty"
            ],
            "matches_uncertainty": (
                item["semantic_reason_codes"]
                == expected_by_id[item["case_id"]]["baseline_uncertainty"]
            ),
            "matches_expressions": (
                [
                    _golden_expression(expression)
                    for expression in item["expressions"]
                ]
                == [
                    _golden_expression(expression)
                    for expression in expected_by_id[item["case_id"]]["expressions"]
                ]
            ),
            "expected_optimized": expected_by_id[item["case_id"]]["optimized_outcome"],
            "expected_optimized_uncertainty": expected_by_id[item["case_id"]][
                "optimized_uncertainty"
            ],
            "bridge_result_new_behavior": expected_by_id[item["case_id"]][
                "bridge_result_new_behavior"
            ],
        }
        for item in outcomes
    ]
    code_sha256, code_files = _code_identity()
    return {
        "schema_version": "1.0",
        "benchmark_id": "nca-optimization-baseline-v1",
        "mode": "synthetic",
        "strategy": "baseline",
        "live_status": "LIVE_MODEL_BENCHMARK_NOT_RUN", "sqs_status": "NOT_APPLIED",
        "capability_limitations": NCA_CAPABILITY_LIMITATION,
        "case_count": len(cases),
        "input_sha256": input_identity(cases, bundle.sha256, profile, policy["checks"]),
        "governance": governance(tasks, "baseline"),
        "fixture_sha256": _sha256(fixture_bytes),
        "code_sha256": code_sha256,
        "code_files": code_files,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "transport_boundary": "sage.executors.ProviderRequest",
        "route": route_identity,
        "calls": summarize_calls(tuple(transport.calls)),
        "local_loads": {
            "reference_load_count": len(reference_loads),
            "reference_load_elapsed_ms": sum(reference_loads),
            "reference_package_sha256": seed_bundle.sha256,
            "profile_validation_count": profile_validation_count,
            "profile_validation_elapsed_ms": profile_validation_elapsed_ns // 1_000_000,
        },
        "execution_elapsed_ms": execution_elapsed_ms,
        "outcomes": outcomes,
        "semantic_outcome_diffs": semantic_diffs,
        "finding_diffs": finding_diffs(cases, outcomes, "baseline"),
    }


def _parser() -> argparse.ArgumentParser:
    """Expose synthetic strategies and explicit existing-snapshot live comparison selectors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="synthetic")
    parser.add_argument("--strategy", default="baseline")
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--fault", choices=("none", "transient", "malformed", "unsupported", "partial"), default="none")
    parser.add_argument('--checkpoint-root', type=Path)
    parser.add_argument('--resume-only', action='store_true')
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--job')
    parser.add_argument('--run')
    parser.add_argument('--project')
    parser.add_argument('--scope')
    parser.add_argument('--labels', type=Path)
    parser.add_argument('--repetitions', type=int, default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the selected benchmark scope and atomically publish its evidence receipt."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.mode not in {"synthetic", "live"}:
        parser.error(f"unsupported benchmark mode: {args.mode}")
    if args.strategy not in {"baseline", "optimized", "paired"}:
        parser.error(f"unsupported benchmark strategy: {args.strategy}")
    if args.fault != "none" and (args.mode != "synthetic" or args.strategy != "optimized"):
        parser.error("fault injection requires synthetic optimized mode")
    if (args.checkpoint_root or args.resume_only) and (args.mode != "synthetic" or args.strategy != "optimized" or args.resume_only and args.checkpoint_root is None):
        parser.error("checkpoint flags require synthetic optimized mode and a checkpoint root for resume")
    if args.mode == "live":
        from benchmark_nca_live import run_live
        receipt = run_live(args)
    elif args.cases is None:
        parser.error("synthetic mode requires --cases")
    elif args.strategy == "paired":
        from benchmark_nca_qualification import qualify_pair
        from benchmark_nca_optimized import run_synthetic_optimized
        receipt = qualify_pair(run_synthetic_baseline(args.cases.resolve()), run_synthetic_optimized(args.cases.resolve()))
    elif args.strategy == "optimized":
        from benchmark_nca_optimized import run_synthetic_optimized
        receipt = run_synthetic_optimized(args.cases.resolve(), fault=args.fault, checkpoint_root=args.checkpoint_root, resume_only=args.resume_only)
    else:
        receipt = run_synthetic_baseline(args.cases.resolve())
    destination = args.receipt.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    staging.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(staging, destination)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 1 if receipt.get('qualification_status') == 'FAIL' else 0


if __name__ == "__main__":
    raise SystemExit(main())
