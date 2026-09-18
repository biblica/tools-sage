"""Deterministic structured scoring and fail-fast evaluation helpers."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from .packs import EvaluationCase, EvaluationPack


@dataclass(frozen=True)
class AttemptScore:
    case_id: str
    passed: bool
    quality: float
    critical: bool
    contract_failure: bool = False
    detail: str = ""


def _lookup(payload: dict[str, Any], dotted_path: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def score_attempt(case: EvaluationCase, text: str) -> AttemptScore:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return AttemptScore(case.case_id, False, 0.0, case.critical, True, "INVALID_JSON")
    if not isinstance(payload, dict):
        return AttemptScore(case.case_id, False, 0.0, case.critical, True, "JSON_OBJECT_REQUIRED")
    if not case.expected:
        return AttemptScore(case.case_id, False, 0.0, case.critical, True, "NO_MACHINE_EXPECTATION")

    matched = 0
    missing = 0
    for path, expected in case.expected.items():
        present, actual = _lookup(payload, path)
        if not present:
            missing += 1
            continue
        if actual == expected:
            matched += 1
    quality = matched / len(case.expected)
    contract_failure = missing > 0
    return AttemptScore(
        case_id=case.case_id,
        passed=(quality == 1.0 and not contract_failure),
        quality=quality,
        critical=case.critical,
        contract_failure=contract_failure,
        detail="MISSING_OUTPUT_FIELD" if contract_failure else "",
    )


def reasoning_level_can_still_pass(pack: EvaluationPack, scores: list[AttemptScore]) -> bool:
    if pack.critical_case_failure == "FAIL_REASONING_LEVEL":
        if any(score.critical and not score.passed for score in scores):
            return False
    return True


def run_pack_cases(pack: EvaluationPack, execute: Callable[[EvaluationCase], str]) -> list[AttemptScore]:
    scores: list[AttemptScore] = []
    for case in pack.ordered_cases():
        score = score_attempt(case, execute(case))
        scores.append(score)
        if not reasoning_level_can_still_pass(pack, scores):
            break
    return scores


def aggregate_quality(scores: list[AttemptScore]) -> float:
    if not scores:
        return 0.0
    return sum(score.quality for score in scores) / len(scores)
