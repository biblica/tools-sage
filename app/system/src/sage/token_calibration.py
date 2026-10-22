"""Work-unit size presets and the self-correcting factor of the unified token estimator.

SAGE sizes every work unit with one estimator (`evidence.estimate_tokens`) whose weight table follows
the selected provider's tokenizer. Two operator-visible adjustments sit on top of the profile budgets:

* the work-unit size (S/M/L, an AI setting) scales token and byte budgets by 0.5 / 1 / 2;
* the token correction is learned from governed calls whose provider reports real usage: the
  median ratio of real prompt tokens to the estimate, per provider and model. It only ever shrinks
  planning targets (bounded to 1.0-1.5x) and never touches hard limits, so a unit planned under an
  older correction is never rejected at task creation.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .evidence import TOKEN_ESTIMATOR, WORK_UNIT_SIZES, estimate_tokens, set_token_table, token_table_for
from .state import append_event
from .storage import storage_layout

DEFAULT_WORK_UNIT_SIZE = "M"
# A prompt this small is dominated by fixed instructions, so its ratio says little about Scripture.
MIN_OBSERVED_ESTIMATE = 2000
MIN_OBSERVATIONS = 20
RECENT_OBSERVATIONS = 200
CORRECTION_BOUNDS = (1.0, 1.5)


@dataclass(frozen=True)
class SizingAdjustment:
    """The work-unit size and learned token correction applied to one planning pass."""

    work_unit_size: str = DEFAULT_WORK_UNIT_SIZE
    size_multiplier: float = 1.0
    provider: str = ""
    token_correction: float = 1.0
    token_table: str = "o200k-2026-10-15"

    @property
    def target_scale(self) -> float:
        """Scale for soft planning targets: the size, shrunk by the learned correction."""
        return self.size_multiplier / self.token_correction

    def to_dict(self) -> dict[str, Any]:
        """Render the adjustment for plans, receipts, and diagnostics."""
        return asdict(self)


def observations_path(root: Path) -> Path:
    """Return the append-only log of estimated-versus-real prompt tokens."""
    return storage_layout(root).state_root / "token-observations.jsonl"


def record_observation(root: Path, *, provider: str, model: str | None, estimated: int, actual: int | None) -> None:
    """Record one governed call's estimated and real prompt tokens when both are meaningful."""
    if not model or actual is None or actual <= 0 or estimated < MIN_OBSERVED_ESTIMATE:
        return
    append_event(
        observations_path(root),
        {
            "estimator": TOKEN_ESTIMATOR,
            "token_table": token_table_for(provider, model),
            "provider": provider,
            "model": model,
            "estimated": int(estimated),
            "actual": int(actual),
        },
    )


def observe_response(root: Path, request: Any, response: Any) -> None:
    """Record one governed call's estimated prompt tokens against the usage its provider reported."""
    usage = (getattr(response, "metadata", None) or {}).get("usage")
    if not isinstance(usage, dict) or usage.get("input_tokens") is None:
        return
    actual = sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    provider = str(response.provider)
    estimated = estimate_tokens(request.prompt, token_table_for(provider, response.model))
    record_observation(root, provider=provider, model=response.model, estimated=estimated, actual=actual)


def _ratios(root: Path, provider: str) -> dict[str, list[float]]:
    """Return recent real/estimated ratios per model of one provider under the current estimator."""
    path = observations_path(root)
    if not path.is_file():
        return {}
    by_model: dict[str, list[float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            row.get("estimator") != TOKEN_ESTIMATOR
            or row.get("provider") != provider
            or row.get("token_table") != token_table_for(provider, row.get("model"))
        ):
            continue
        by_model.setdefault(str(row.get("model")), []).append(int(row["actual"]) / int(row["estimated"]))
    return {model: values[-RECENT_OBSERVATIONS:] for model, values in by_model.items()}


def token_correction(root: Path, provider: str) -> float:
    """Return the bounded correction for one provider: the highest per-model median with enough data."""
    medians = [statistics.median(values) for values in _ratios(root, provider).values() if len(values) >= MIN_OBSERVATIONS]
    if not medians:
        return 1.0
    low, high = CORRECTION_BOUNDS
    return round(min(max(max(medians), low), high), 3)


def correction_status(root: Path, provider: str) -> dict[str, Any]:
    """Return per-model observation counts and medians for the AI settings screen."""
    models = {
        model: {"observations": len(values), "median_ratio": round(statistics.median(values), 3)}
        for model, values in sorted(_ratios(root, provider).items())
    }
    return {"provider": provider, "token_correction": token_correction(root, provider), "models": models,
            "minimum_observations": MIN_OBSERVATIONS}


def sizing_adjustment(root: Path) -> SizingAdjustment:
    """Return the adjustment for the selected provider and the persisted work-unit size."""
    from .llm_settings import load_llm_settings

    settings = load_llm_settings(root)
    size = str(settings.get("work_unit_size") or DEFAULT_WORK_UNIT_SIZE)
    provider = str(settings["selected_provider"])
    table = token_table_for(provider)
    # Every routed-SFM measurement after this point counts in the selected provider's tokens.
    set_token_table(table)
    return SizingAdjustment(
        work_unit_size=size,
        size_multiplier=WORK_UNIT_SIZES[size],
        provider=provider,
        token_correction=token_correction(root, provider),
        token_table=table,
    )
