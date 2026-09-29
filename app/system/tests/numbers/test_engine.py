"""NCA engine composition: indexed-scope candidates and the optimized entry point.

Per the 2026-09-28 simplified-check rewrite, engine.py only owns indexed-scope
restriction and delegation into the batched extraction + local comparison
orchestrator (numbers/hybrid.py::evaluate). hybrid.py's actual behavior
(extraction, comparison, coverage, checkpoints) is exercised end-to-end in
test_hybrid_execution.py; this file covers only what remains in engine.py
itself.
"""
import pytest

from sage.errors import ValidationError
from sage.numbers import engine
from sage.numbers.execution import ScopeInventory
from sage.numbers.models import Extraction, ProjectedUnit, TargetUnit
from sage.vrs import VerseRef


def test_candidate_group_ids_is_exactly_the_indexed_scope_regardless_of_extraction():
    """Candidates are exactly the indexed units; unindexed units never become candidates.

    NCA finds incorrectly reported or missing numbers where a number is already known to be
    expected -- it does not scan unindexed coordinates for undiscovered numbers, so what an
    unindexed unit's extraction happened to contain (found, incomplete, or nothing) is
    irrelevant: it can never become a candidate, only indexed units can.
    """
    from fractions import Fraction
    owners = tuple(ProjectedUnit(TargetUnit(name, (VerseRef('MAT', 1, verse),),
        '', (), 'a' * 64, {}), (VerseRef('MAT', 1, verse),), (), 'COORDINATE', 'READY')
        for verse, name in enumerate(('expected', 'unexpected', 'uncertain', 'empty'), 1))
    inventory = ScopeInventory(tuple(x.western_references[0] for x in owners), owners,
        frozenset({'expected'}), (), 'MAT 1:1-4')
    extractions = {'expected': Extraction((), 'COMPLETE'),
        'unexpected': Extraction((Fraction(3),), 'COMPLETE'),
        'uncertain': Extraction((), 'UNSUPPORTED', ('unsupported language',)),
        'empty': Extraction((), 'COMPLETE')}
    assert engine.candidate_group_ids(inventory, extractions) == frozenset({'expected'})
    assert len(inventory.projected_units) == 4
    assert engine.candidate_group_ids(inventory, {}) == frozenset({'expected'})


def test_evaluate_optimized_run_requires_a_real_execution_context():
    """The entry point cannot silently proceed with an unvalidated or absent context."""
    with pytest.raises(ValidationError) as exc:
        engine.evaluate_optimized_run(object(), model_tasks=None, phase_store=None, run_id='RUN-1')
    assert exc.value.code == 'NCA_ENGINE_INPUT_INVALID'


def test_evaluate_optimized_run_delegates_to_hybrid_evaluate(monkeypatch):
    """The engine's public entry point is a thin, verifiable delegation into hybrid.evaluate."""
    from sage.numbers.execution import ExecutionInputs
    from sage.numbers import hybrid

    calls = []

    def fake_evaluate(inputs, *, model_tasks, phase_store, run_id):
        """Record the exact arguments the engine forwarded, unchanged."""
        calls.append((inputs, model_tasks, phase_store, run_id))
        return 'RESULT'

    monkeypatch.setattr(hybrid, 'evaluate', fake_evaluate)
    inputs = object.__new__(ExecutionInputs)  # bypass __post_init__: only identity matters here

    result = engine.evaluate_optimized_run(inputs, model_tasks='tasks', phase_store='store', run_id='RUN-1')

    assert result == 'RESULT'
    assert calls == [(inputs, 'tasks', 'store', 'RUN-1')]
