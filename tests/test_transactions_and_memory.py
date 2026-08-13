"""Journaled rollback, recovery, and BIC memory-governance tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sage_core.atomic import atomic_write_json
from sage_core.bic_memory import (
    eligible_memory_records,
    submit_inspect_transactionally,
    transition_memory_state,
)
from sage_core.errors import MemoryGovernanceError, TransactionError
from sage_core.transactions import FileTransaction, recover_transaction


def test_multi_file_commit_failure_rolls_back_exactly(tmp_path: Path) -> None:
    """Verify that multi file commit failure rolls back exactly."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text("old-first", encoding="utf-8")
    second.write_text("old-second", encoding="utf-8")
    transaction = FileTransaction(tmp_path / "transactions", "TEST")
    transaction.stage_text(first, "new-first")
    transaction.stage_text(second, "new-second")

    def fail_after_first(index: int) -> None:
        """Raise after the first write to simulate an interrupted transaction."""
        if index == 1:
            raise RuntimeError("simulated interruption")

    with pytest.raises(TransactionError, match="rolled back"):
        transaction.commit(failure_hook=fail_after_first)
    assert first.read_text(encoding="utf-8") == "old-first"
    assert second.read_text(encoding="utf-8") == "old-second"
    journal = json.loads(transaction.journal_path.read_text(encoding="utf-8"))
    assert journal["state"] == "ROLLED_BACK"


def test_interrupted_transaction_can_be_recovered(tmp_path: Path) -> None:
    """Verify that interrupted transaction can be recovered."""
    target = tmp_path / "target.txt"
    target.write_text("before", encoding="utf-8")
    transaction = FileTransaction(tmp_path / "transactions", "TEST_RECOVERY")
    transaction.stage_text(target, "after")
    transaction.prepare()
    operation = transaction.operations[0]
    os.replace(operation["staged"], operation["target"])
    operation["status"] = "COMMITTED"
    transaction.state = "COMMITTING"
    transaction._write_journal()  # Test-only simulation of process death.
    recovered = recover_transaction(transaction.root)
    assert recovered["state"] == "ROLLED_BACK"
    assert target.read_text(encoding="utf-8") == "before"


def test_inspect_submission_commits_only_proposed_memory(tmp_path: Path) -> None:
    """Verify that inspect submission commits only proposed memory."""
    document = {
        "schema_version": "1.0",
        "operation_id": "INSPECT-MAT-001",
        "scope": "MAT 1:1-3",
        "resource_fingerprints": {"idKKHv0": "a" * 64, "usNIRVv2": "b" * 64},
        "proposals": [
            {
                "submitted_id": "P-1",
                "record_type": "LEXICAL_SENSE",
                "payload": {"lemma": "fixture", "sense": "example"},
                "evidence_refs": ["MAT 1:1"],
            }
        ],
        "challenges": [
            {
                "submitted_id": "C-1",
                "scripture_reference": "MAT 1:2",
                "challenge_type": "LEXICAL",
                "summary": "A lexical decision is unresolved.",
                "recommended_action": "Review with the Operator.",
            }
        ],
    }
    result = submit_inspect_transactionally(
        document,
        memory_root=tmp_path / "memory",
        transaction_root=tmp_path / "transactions",
    )
    assert result["state"] == "COMPLETE"
    proposals = json.loads((tmp_path / "memory" / "inspect-proposals.json").read_text())
    assert proposals[0]["memory_state"] == "PROPOSED"
    assert eligible_memory_records(proposals) == []
    reviewed = transition_memory_state(
        proposals[0],
        "REVIEWED",
        operator_decision_id="DEC-1",
    )
    approved = transition_memory_state(
        reviewed,
        "APPROVED_FOR_USE",
        operator_decision_id="DEC-2",
    )
    approved["status"] = "ACTIVE"
    assert eligible_memory_records([approved]) == [approved]
    with pytest.raises(MemoryGovernanceError, match="already committed"):
        submit_inspect_transactionally(
            document,
            memory_root=tmp_path / "memory",
            transaction_root=tmp_path / "transactions",
        )
