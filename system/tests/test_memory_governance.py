"""Individual memory transition and governed lexicon import tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage.bic_memory import (
    import_lexicon_transactionally,
    list_memory_records,
    rollback_lexicon_import_transactionally,
    submit_inspect_transactionally,
    transition_memory_record_transactionally,
)
from sage.errors import MemoryGovernanceError


def _inspect_document() -> dict[str, object]:
    """Return one valid INSPECT document with one proposed memory record."""
    return {
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
        "challenges": [],
    }


def _lexicon_document() -> dict[str, object]:
    """Return one governed lexicon import fixture."""
    return {
        "schema_version": "1.0",
        "import_id": "LEXICON-ID-001",
        "source": {
            "name": "Fixture lexicon",
            "version": "2026.08",
            "language": "id",
            "authority_id": "AUTH-LEX-001",
        },
        "entries": [
            {
                "submitted_id": "ENTRY-001",
                "record_type": "LEXICAL_ENTRY",
                "payload": {"lemma": "contoh", "gloss": "example"},
                "evidence_refs": ["MAT 1:1"],
            },
            {
                "submitted_id": "ENTRY-002",
                "record_type": "LANGUAGE_RENDERING",
                "payload": {"source": "fixture", "rendering": "contoh"},
                "evidence_refs": ["MAT 1:2"],
            },
        ],
    }


def test_individual_transition_is_stale_safe_and_materializes_approved_memory(
    tmp_path: Path,
) -> None:
    """Require expected state and synchronize only active approved records."""
    memory_root = tmp_path / "memory"
    transaction_root = tmp_path / "transactions"
    submit_inspect_transactionally(
        _inspect_document(),
        memory_root=memory_root,
        transaction_root=transaction_root,
        bic_job_id="BIC-fixture",
    )
    record_id = json.loads((memory_root / "inspect-proposals.json").read_text())[0][
        "proposal_id"
    ]

    reviewed = transition_memory_record_transactionally(
        memory_root=memory_root,
        transaction_root=transaction_root,
        record_id=record_id,
        expected_state="PROPOSED",
        new_state="REVIEWED",
        operator_decision_id="DEC-REVIEW-001",
        operator="operator-1",
        notes="Reviewed against project evidence.",
    )
    assert reviewed["from_state"] == "PROPOSED"
    assert reviewed["to_state"] == "REVIEWED"
    assert json.loads((memory_root / "approved-memory.json").read_text()) == []

    with pytest.raises(MemoryGovernanceError) as conflict:
        transition_memory_record_transactionally(
            memory_root=memory_root,
            transaction_root=transaction_root,
            record_id=record_id,
            expected_state="PROPOSED",
            new_state="REJECTED",
            operator_decision_id="DEC-STALE-001",
            operator="operator-2",
        )
    assert conflict.value.code == "MEMORY_STATE_CONFLICT"

    approved = transition_memory_record_transactionally(
        memory_root=memory_root,
        transaction_root=transaction_root,
        record_id=record_id,
        expected_state="REVIEWED",
        new_state="APPROVED_FOR_USE",
        operator_decision_id="DEC-APPROVE-001",
        operator="operator-2",
    )
    assert approved["record"]["status"] == "ACTIVE"
    materialized = json.loads((memory_root / "approved-memory.json").read_text())
    assert [row["proposal_id"] for row in materialized] == [record_id]
    transitions = json.loads((memory_root / "memory-state-transitions.json").read_text())
    assert [row["to_state"] for row in transitions] == ["REVIEWED", "APPROVED_FOR_USE"]
    assert transitions[-1]["operator"] == "operator-2"


def test_lexicon_import_requires_individual_approval_and_supports_rollback(
    tmp_path: Path,
) -> None:
    """Import proposed records with provenance, then deactivate all records on rollback."""
    memory_root = tmp_path / "memory"
    transaction_root = tmp_path / "transactions"
    result = import_lexicon_transactionally(
        _lexicon_document(),
        source_sha256="c" * 64,
        operator="operator-1",
        operator_decision_id="DEC-IMPORT-001",
        notes="Approved for governed ingestion, not use.",
        memory_root=memory_root,
        transaction_root=transaction_root,
    )
    assert result["record_count"] == 2
    imported = list_memory_records(memory_root, source="LEXICON_IMPORT")
    assert {row["memory_state"] for row in imported} == {"PROPOSED"}
    assert {row["status"] for row in imported} == {"PENDING"}
    assert all(row["provenance"]["source_sha256"] == "c" * 64 for row in imported)
    assert json.loads((memory_root / "approved-memory.json").read_text()) == []

    first_id = imported[0]["record_id"]
    transition_memory_record_transactionally(
        memory_root=memory_root,
        transaction_root=transaction_root,
        record_id=first_id,
        expected_state="PROPOSED",
        new_state="REVIEWED",
        operator_decision_id="DEC-LEX-REVIEW-001",
        operator="operator-2",
    )
    with pytest.raises(MemoryGovernanceError) as prohibited:
        transition_memory_record_transactionally(
            memory_root=memory_root,
            transaction_root=transaction_root,
            record_id=first_id,
            expected_state="REVIEWED",
            new_state="APPROVED_FOR_USE",
            operator_decision_id="DEC-LEX-APPROVE-001",
            operator="operator-2",
        )
    assert prohibited.value.code == "LEXICON_IMPORT_CONTENT_AUTHORITY_PROHIBITED"
    approved = json.loads((memory_root / "approved-memory.json").read_text())
    assert approved == []
    imported_after_review = list_memory_records(memory_root, source="LEXICON_IMPORT")
    assert all(row["provenance"]["content_authority"] == "PROHIBITED" for row in imported_after_review)

    rollback = rollback_lexicon_import_transactionally(
        import_id="LEXICON-ID-001",
        operator="operator-3",
        operator_decision_id="DEC-ROLLBACK-001",
        notes="Source authority withdrawn.",
        memory_root=memory_root,
        transaction_root=transaction_root,
    )
    assert len(rollback["affected_records"]) == 2
    assert {row["to_state"] for row in rollback["affected_records"]} == {"INACTIVE"}
    assert json.loads((memory_root / "approved-memory.json").read_text()) == []
    imports = json.loads((memory_root / "lexicon-imports.json").read_text())
    assert imports[0]["status"] == "ROLLED_BACK"
    assert imports[0]["rollback_id"] == rollback["rollback_id"]

    with pytest.raises(MemoryGovernanceError) as repeated:
        rollback_lexicon_import_transactionally(
            import_id="LEXICON-ID-001",
            operator="operator-3",
            operator_decision_id="DEC-ROLLBACK-002",
            notes="Repeated rollback must not alter state.",
            memory_root=memory_root,
            transaction_root=transaction_root,
        )
    assert repeated.value.code == "LEXICON_IMPORT_ALREADY_ROLLED_BACK"


def test_lexicon_import_identity_is_idempotency_boundary(tmp_path: Path) -> None:
    """Reject a repeated import identity instead of duplicating records."""
    memory_root = tmp_path / "memory"
    transaction_root = tmp_path / "transactions"
    kwargs = {
        "source_sha256": "d" * 64,
        "operator": "operator-1",
        "operator_decision_id": "DEC-IMPORT-001",
        "notes": "",
        "memory_root": memory_root,
        "transaction_root": transaction_root,
    }
    import_lexicon_transactionally(_lexicon_document(), **kwargs)
    with pytest.raises(MemoryGovernanceError) as repeated:
        import_lexicon_transactionally(_lexicon_document(), **kwargs)
    assert repeated.value.code == "LEXICON_IMPORT_ALREADY_RECORDED"
