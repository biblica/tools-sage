"""Evaluation-pack records and deterministic YAML loading."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    diagnostic_class: str
    critical: bool
    priority: int
    prompt: str
    expected: dict[str, Any]
    expected_constraints: tuple[str, ...]
    estimated_input_tokens: int
    estimated_output_tokens: int
    confirmation: bool = False

    def provider_prompt(self) -> str:
        """Return provider-visible material only; hidden expectations never cross the boundary."""
        return (
            f"{self.prompt.rstrip()}\n\n"
            "Return one JSON object only. Do not include markdown fences or explanatory text."
        )


@dataclass(frozen=True)
class EvaluationPack:
    pack_id: str
    profile_id: str
    capability: str
    revision: int
    cases: tuple[EvaluationCase, ...]
    critical_case_failure: str = "FAIL_REASONING_LEVEL"
    repeat_confirmation_cases: int = 2
    minimum_quality: float = 1.0
    review_state: str = "REVIEW_REQUIRED"

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError("Evaluation pack requires at least one case")
        if not any(case.critical for case in self.cases):
            raise ValueError("Evaluation pack requires at least one critical case")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Evaluation pack case_id values must be unique")
        if not (0.0 <= self.minimum_quality <= 1.0):
            raise ValueError("minimum_quality must be between 0 and 1")

    def ordered_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(sorted(self.cases, key=lambda case: (-case.priority, case.case_id)))

    def confirmation_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(case for case in self.ordered_cases() if case.confirmation)


def _load_case(raw: dict[str, Any]) -> EvaluationCase:
    expected = raw.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError("case expected must be an object keyed by dotted output paths")
    return EvaluationCase(
        case_id=str(raw["case_id"]),
        diagnostic_class=str(raw["diagnostic_class"]),
        critical=bool(raw.get("critical", False)),
        priority=int(raw.get("priority", 0)),
        prompt=str(raw.get("prompt", raw.get("input", ""))),
        expected=dict(expected),
        expected_constraints=tuple(str(value) for value in raw.get("expected_constraints") or ()),
        estimated_input_tokens=int(raw.get("estimated_input_tokens", 0)),
        estimated_output_tokens=int(raw.get("estimated_output_tokens", 0)),
        confirmation=bool(raw.get("confirmation", False)),
    )


def load_pack(path: str | Path) -> EvaluationPack:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    policy = raw.get("policy") or {}
    return EvaluationPack(
        pack_id=str(raw["pack_id"]),
        profile_id=str(raw["profile_id"]),
        capability=str(raw["capability"]),
        revision=int(raw.get("revision", 1)),
        cases=tuple(_load_case(case) for case in raw.get("cases") or ()),
        critical_case_failure=str(policy.get("critical_case_failure", "FAIL_REASONING_LEVEL")),
        repeat_confirmation_cases=int(policy.get("repeat_confirmation_cases", 2)),
        minimum_quality=float(policy.get("minimum_quality", 1.0)),
        review_state=str(raw.get("review_state", "REVIEW_REQUIRED")),
    )


def load_pack_catalog(path: str | Path) -> dict[tuple[str, str], EvaluationPack]:
    catalog: dict[tuple[str, str], EvaluationPack] = {}
    for file in sorted(Path(path).glob("*.yml")):
        pack = load_pack(file)
        key = (pack.profile_id, pack.capability)
        if key in catalog:
            raise ValueError(f"Duplicate exact evaluation pack for {key[0]}/{key[1]}")
        catalog[key] = pack
    return catalog
