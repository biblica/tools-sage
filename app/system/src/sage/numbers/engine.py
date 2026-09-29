"""Compose bounded NCA evidence into the indexed-scope numeric-accuracy result.

Simplified per the 2026-09-28 rewrite: the old per-unit reading/correspondence/
footnote/style adjudication pipeline (exact-span extraction, OL correspondence,
registered-unit conversion, presentation-style checking) has no successor here
-- comparison is local/deterministic (numbers/compare.py) and the noteworthy-
info advisory is a local lookup (numbers/footnotes.py). This module now only
owns the indexed-only scope restriction and the entry point into the batched
extraction + local comparison orchestrator (numbers/hybrid.py).
"""

from __future__ import annotations

from collections.abc import Mapping

from sage.errors import ValidationError

from .execution import ExecutionInputs, ScopeInventory
from .models import Extraction
from .replay import PhaseStore


def candidate_group_ids(inventory: ScopeInventory, extractions: Mapping[str, Extraction]) -> frozenset[str]:
    """Return the indexed units NCA actually evaluates, unaffected by their extraction outcome.

    Unindexed units are never planned for extraction (see build_inventory's indexed-only
    filter), so a missing or incomplete extraction there is the deliberate no-data-scan
    outcome, not a coverage gap -- only indexed units (`inventory.expected_groups`) can ever
    become candidates. `extractions` is accepted for interface stability with callers that
    still pass it, but no longer changes this result.
    """
    return frozenset(inventory.expected_groups)


def evaluate_optimized_run(inputs: ExecutionInputs, *, model_tasks: object, phase_store: PhaseStore, run_id: str) -> object:
    """Execute complete indexed scope through bounded extraction and local comparison."""
    from .hybrid import evaluate
    if not isinstance(inputs, ExecutionInputs):
        raise ValidationError('NCA execution context is required', code='NCA_ENGINE_INPUT_INVALID')
    return evaluate(inputs, model_tasks=model_tasks, phase_store=phase_store, run_id=run_id)
