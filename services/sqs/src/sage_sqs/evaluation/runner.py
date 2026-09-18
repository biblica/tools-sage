"""Execute deterministic reasoning-boundary evaluations against exact packs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..domain import ModelRecord
from ..providers.base import ProviderAdapter
from .packs import EvaluationCase, EvaluationPack
from .scoring import AttemptScore, aggregate_quality, reasoning_level_can_still_pass, score_attempt


@dataclass(frozen=True)
class BoundaryDecision:
    minimum_reasoning: str | None


@dataclass(frozen=True)
class ReasoningRun:
    reasoning: str
    passed: bool
    quality_score: float
    scores: tuple[AttemptScore, ...]
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class PlannedRunResult:
    minimum_reasoning: str | None
    quality_score: float
    reliability_score: float
    scope: str
    required_repeats_met: bool
    total_input_tokens: int
    total_output_tokens: int
    estimated_unit_cost_usd: float
    reasoning_runs: tuple[ReasoningRun, ...]
    decisive_critical_failure: bool = False


def evaluate_boundary(*, medium_pass: bool, branch_pass: bool) -> BoundaryDecision:
    if medium_pass:
        return BoundaryDecision("low" if branch_pass else "medium")
    return BoundaryDecision("high" if branch_pass else None)


def estimated_cost_usd(input_tokens: int, output_tokens: int, input_per_mtok: float, output_per_mtok: float) -> float:
    return (input_tokens / 1_000_000) * input_per_mtok + (output_tokens / 1_000_000) * output_per_mtok


def _cases_for_scope(pack: EvaluationPack, scope: str) -> tuple[EvaluationCase, ...]:
    if scope == "CONFIRMATION":
        rows = pack.confirmation_cases()
        if not rows:
            raise ValueError(f"Pack {pack.pack_id} has no exact confirmation cases")
        return rows
    if scope != "FULL":
        raise ValueError(f"Unsupported evaluation scope: {scope}")
    return pack.ordered_cases()


def _run_reasoning(*, pack: EvaluationPack, provider: ProviderAdapter, model: ModelRecord,
                   reasoning: str, scope: str) -> ReasoningRun:
    scores: list[AttemptScore] = []
    input_tokens = 0
    output_tokens = 0
    for case in _cases_for_scope(pack, scope):
        result = provider.execute(model_id=model.model_id, reasoning=reasoning, prompt=case.provider_prompt())
        input_tokens += int(result.input_tokens or 0)
        output_tokens += int(result.output_tokens or 0)
        score = score_attempt(case, result.text)
        scores.append(score)
        if not reasoning_level_can_still_pass(pack, scores):
            break
    quality = aggregate_quality(scores)
    critical_ok = all(score.passed for score in scores if score.critical)
    # A full/confirmation run is only a pass after all selected cases have run;
    # fail-fast therefore cannot accidentally convert partial evidence into success.
    expected_count = len(_cases_for_scope(pack, scope))
    complete = len(scores) == expected_count
    passed = complete and critical_ok and quality >= pack.minimum_quality
    return ReasoningRun(reasoning, passed, quality, tuple(scores), input_tokens, output_tokens)


def _search_sequence(starting_reasoning: str) -> tuple[str, ...]:
    if starting_reasoning == "medium":
        return ("medium",)
    if starting_reasoning == "low":
        return ("low", "medium", "high")
    if starting_reasoning == "high":
        return ("high", "medium", "low")
    raise ValueError(f"Unsupported routine reasoning level: {starting_reasoning}")


def _boundary_search(*, pack: EvaluationPack, provider: ProviderAdapter, model: ModelRecord,
                     starting_reasoning: str, scope: str) -> tuple[str | None, list[ReasoningRun]]:
    runs: list[ReasoningRun] = []
    if starting_reasoning == "medium":
        medium = _run_reasoning(pack=pack, provider=provider, model=model, reasoning="medium", scope=scope)
        runs.append(medium)
        branch_reasoning = "low" if medium.passed else "high"
        branch = _run_reasoning(pack=pack, provider=provider, model=model, reasoning=branch_reasoning, scope=scope)
        runs.append(branch)
        return evaluate_boundary(medium_pass=medium.passed, branch_pass=branch.passed).minimum_reasoning, runs

    # Predecessor-boundary starts are an optimization prior only. Measure outward
    # from that exact starting level until the minimum routine boundary is known.
    for reasoning in _search_sequence(starting_reasoning):
        run = _run_reasoning(pack=pack, provider=provider, model=model, reasoning=reasoning, scope=scope)
        runs.append(run)
        if starting_reasoning == "low":
            if run.passed:
                return reasoning, runs
        else:  # high start
            if reasoning == "high" and not run.passed:
                return None, runs
            if reasoning == "medium" and not run.passed:
                return "high", runs
            if reasoning == "low":
                return "low" if run.passed else "medium", runs
    return None, runs


def _repeat_confirmation(*, pack: EvaluationPack, provider: ProviderAdapter, model: ModelRecord,
                         reasoning: str, repeats: int) -> tuple[float, bool, int, int]:
    if repeats <= 0:
        return 1.0, True, 0, 0
    if not pack.confirmation_cases():
        return 0.0, False, 0, 0
    passed = 0
    input_tokens = 0
    output_tokens = 0
    for _ in range(repeats):
        run = _run_reasoning(pack=pack, provider=provider, model=model, reasoning=reasoning, scope="CONFIRMATION")
        input_tokens += run.input_tokens
        output_tokens += run.output_tokens
        if run.passed:
            passed += 1
    reliability = passed / repeats
    return reliability, passed == repeats, input_tokens, output_tokens


def run_planned_test(*, pack: EvaluationPack, provider: ProviderAdapter, model: ModelRecord,
                     starting_reasoning: str = "medium", scope: str = "FULL") -> PlannedRunResult:
    minimum_reasoning, runs = _boundary_search(
        pack=pack, provider=provider, model=model, starting_reasoning=starting_reasoning, scope=scope,
    )
    selected = next((run for run in reversed(runs) if run.reasoning == minimum_reasoning), None)
    if selected is None and minimum_reasoning is not None:
        selected = next(run for run in runs if run.reasoning == minimum_reasoning)
    quality = selected.quality_score if selected else max((run.quality_score for run in runs), default=0.0)

    reliability = 1.0
    repeats_met = True
    repeat_in = repeat_out = 0
    if minimum_reasoning is not None:
        reliability, repeats_met, repeat_in, repeat_out = _repeat_confirmation(
            pack=pack, provider=provider, model=model, reasoning=minimum_reasoning,
            repeats=pack.repeat_confirmation_cases,
        )

    total_input = sum(run.input_tokens for run in runs) + repeat_in
    total_output = sum(run.output_tokens for run in runs) + repeat_out
    selected_input = (selected.input_tokens if selected else 0) + repeat_in
    selected_output = (selected.output_tokens if selected else 0) + repeat_out
    cost = estimated_cost_usd(
        selected_input, selected_output, model.input_usd_per_mtok, model.output_usd_per_mtok,
    )
    decisive_failure = minimum_reasoning is None and any(
        score.critical and not score.passed for run in runs for score in run.scores
    )
    return PlannedRunResult(
        minimum_reasoning=minimum_reasoning,
        quality_score=quality,
        reliability_score=reliability if minimum_reasoning is not None else 1.0 if decisive_failure else 0.0,
        scope=scope,
        required_repeats_met=repeats_met if minimum_reasoning is not None else decisive_failure,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        estimated_unit_cost_usd=cost,
        reasoning_runs=tuple(runs),
        decisive_critical_failure=decisive_failure,
    )
