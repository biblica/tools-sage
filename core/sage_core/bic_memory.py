"""BIC memory-state governance and transactional INSPECT submission primitives."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .errors import MemoryGovernanceError
from .references import parse_scope
from .vrs import VerseRef
from .hashing import sha256_bytes
from .locking import WorkspaceLock
from .state import utc_now
from .transactions import FileTransaction

MEMORY_STATES = {
    "PROPOSED",
    "REVIEWED",
    "APPROVED_FOR_USE",
    "REJECTED",
    "SUPERSEDED",
    "INACTIVE",
}
ALLOWED_TRANSITIONS = {
    "PROPOSED": {"REVIEWED", "REJECTED", "INACTIVE"},
    "REVIEWED": {"APPROVED_FOR_USE", "REJECTED", "INACTIVE"},
    "APPROVED_FOR_USE": {"SUPERSEDED", "INACTIVE"},
    "REJECTED": {"INACTIVE"},
    "SUPERSEDED": {"INACTIVE"},
    "INACTIVE": set(),
}
RECORD_TYPES = {
    "LEXICAL_ENTRY",
    "LEXICAL_FORM",
    "LEXICAL_SENSE",
    "SENSE_DESCRIPTION",
    "LANGUAGE_RENDERING",
    "OCCURRENCE",
    "LEXICAL_EXAMPLE",
    "SEMANTIC_DOMAIN_LINK",
    "LEXICAL_RELATION",
    "EXTERNAL_IDENTIFIER",
    "EXCHANGE_FIELD",
}
CHALLENGE_TYPES = {
    "LEXICAL",
    "GRAMMATICAL",
    "DISCOURSE",
    "CULTURAL",
    "TEXTUAL",
    "VERSIFICATION",
    "OTHER",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _required_string(value: Any, label: str, *, maximum: int = 4000) -> str:
    """Require one non-empty governance string and identify the invalid field precisely."""
    if not isinstance(value, str) or not value.strip():
        raise MemoryGovernanceError(f"{label} must be a nonempty string")
    result = value.strip()
    if len(result) > maximum:
        raise MemoryGovernanceError(f"{label} exceeds {maximum} characters")
    return result


def _stable_id(prefix: str, operation_id: str, submitted_id: str) -> str:
    """Build a deterministic governance ID from the supplied identity components."""
    digest = sha256_bytes(f"{operation_id}\0{submitted_id}".encode("utf-8"))[:16].upper()
    return f"{prefix}-{digest}"


def validate_inspect_submission(
    document: Mapping[str, Any],
    *,
    expected_scope: str | None = None,
) -> dict[str, Any]:
    """Validate model-produced INSPECT proposals without granting approval."""
    # Keep proposal validation separate from human approval; model output cannot authorise memory use.
    if document.get("schema_version") != "1.0":
        raise MemoryGovernanceError("INSPECT submission schema_version must be '1.0'")
    operation_id = _required_string(document.get("operation_id"), "operation_id", maximum=128)
    if not ID_RE.fullmatch(operation_id):
        raise MemoryGovernanceError("operation_id contains unsupported characters")
    scope = _required_string(document.get("scope"), "scope", maximum=200)
    parent_scope = parse_scope(expected_scope or scope)
    if scope != parent_scope.label():
        raise MemoryGovernanceError(
            "INSPECT scope does not match the governed task scope",
            code="INSPECT_SCOPE_MISMATCH",
            affected_scope=scope,
        )
    fingerprints = document.get("resource_fingerprints")
    if not isinstance(fingerprints, dict) or not fingerprints:
        raise MemoryGovernanceError("resource_fingerprints must be a nonempty mapping")
    normalized_fingerprints: dict[str, str] = {}
    for key, value in fingerprints.items():
        label = _required_string(key, "resource fingerprint key", maximum=80)
        digest = _required_string(value, f"resource_fingerprints.{label}", maximum=64).lower()
        if not SHA256_RE.fullmatch(digest):
            raise MemoryGovernanceError(
                f"resource_fingerprints.{label} must be a lowercase SHA-256 digest"
            )
        normalized_fingerprints[label] = digest

    proposals_raw = document.get("proposals", []) or []
    challenges_raw = document.get("challenges", []) or []
    if not isinstance(proposals_raw, list) or any(not isinstance(item, dict) for item in proposals_raw):
        raise MemoryGovernanceError("proposals must be a list of mappings")
    if not isinstance(challenges_raw, list) or any(not isinstance(item, dict) for item in challenges_raw):
        raise MemoryGovernanceError("challenges must be a list of mappings")
    proposals: list[dict[str, Any]] = []
    proposal_ids: set[str] = set()
    for index, item in enumerate(proposals_raw, start=1):
        submitted_id = _required_string(
            item.get("submitted_id", f"P{index:04d}"),
            f"proposals[{index}].submitted_id",
            maximum=128,
        )
        if submitted_id in proposal_ids:
            raise MemoryGovernanceError(f"Duplicate proposal submitted_id: {submitted_id}")
        proposal_ids.add(submitted_id)
        record_type = _required_string(
            item.get("record_type"),
            f"proposals[{index}].record_type",
            maximum=80,
        ).upper()
        if record_type not in RECORD_TYPES:
            raise MemoryGovernanceError(f"Unsupported INSPECT record_type: {record_type}")
        payload = item.get("payload")
        if not isinstance(payload, dict) or not payload:
            raise MemoryGovernanceError(f"proposals[{index}].payload must be a nonempty mapping")
        evidence_refs = item.get("evidence_refs", []) or []
        if not isinstance(evidence_refs, list) or any(
            not isinstance(value, str) or not value.strip() for value in evidence_refs
        ):
            raise MemoryGovernanceError(
                f"proposals[{index}].evidence_refs must be a string list"
            )
        proposals.append(
            {
                "proposal_id": _stable_id("MEM", operation_id, submitted_id),
                "submitted_id": submitted_id,
                "operation_id": operation_id,
                "scope": scope,
                "record_type": record_type,
                "payload": dict(payload),
                "evidence_refs": [value.strip() for value in evidence_refs],
                "memory_state": "PROPOSED",
                "operator_decision_id": "",
                "provenance": {
                    "resource_fingerprints": normalized_fingerprints,
                    "submission_source": "BIC_INSPECT",
                },
            }
        )

    challenges: list[dict[str, Any]] = []
    challenge_ids: set[str] = set()
    for index, item in enumerate(challenges_raw, start=1):
        submitted_id = _required_string(
            item.get("submitted_id", f"C{index:04d}"),
            f"challenges[{index}].submitted_id",
            maximum=128,
        )
        if submitted_id in challenge_ids:
            raise MemoryGovernanceError(f"Duplicate challenge submitted_id: {submitted_id}")
        challenge_ids.add(submitted_id)
        challenge_type = _required_string(
            item.get("challenge_type", "OTHER"),
            f"challenges[{index}].challenge_type",
            maximum=80,
        ).upper()
        if challenge_type not in CHALLENGE_TYPES:
            raise MemoryGovernanceError(f"Unsupported challenge_type: {challenge_type}")
        scripture_reference = _required_string(
            item.get("scripture_reference"),
            f"challenges[{index}].scripture_reference",
            maximum=120,
        )
        try:
            challenge_scope = parse_scope(scripture_reference)
        except Exception as exc:
            raise MemoryGovernanceError(
                f"challenges[{index}].scripture_reference is invalid: {scripture_reference}",
                code="INSPECT_REFERENCE_INVALID",
                affected_scope=scope,
            ) from exc
        points = []
        if challenge_scope.start_chapter is None:
            points = []
        elif challenge_scope.start_verse is None:
            points = [
                (challenge_scope.start_chapter, 1),
                (challenge_scope.start_chapter, 9999),
            ]
        else:
            points = [
                (challenge_scope.start_chapter, challenge_scope.start_verse),
                (challenge_scope.end_chapter or challenge_scope.start_chapter, challenge_scope.end_verse or challenge_scope.start_verse),
            ]
        if challenge_scope.book != parent_scope.book or (
            points and not all(parent_scope.contains(VerseRef(parent_scope.book, chapter, verse)) for chapter, verse in points)
        ):
            raise MemoryGovernanceError(
                f"INSPECT challenge reference is outside task scope: {scripture_reference}",
                code="INSPECT_REFERENCE_OUTSIDE_SCOPE",
                affected_scope=scope,
                details={"scripture_reference": scripture_reference},
            )
        challenges.append(
            {
                "challenge_id": _stable_id("CHL", operation_id, submitted_id),
                "submitted_id": submitted_id,
                "operation_id": operation_id,
                "scope": scope,
                "scripture_reference": scripture_reference,
                "challenge_type": challenge_type,
                "summary": _required_string(
                    item.get("summary"),
                    f"challenges[{index}].summary",
                    maximum=1200,
                ),
                "recommended_action": _required_string(
                    item.get("recommended_action"),
                    f"challenges[{index}].recommended_action",
                    maximum=1200,
                ),
                "review_state": "PROPOSED",
                "status": "OPEN",
                "operator_decision_id": "",
                "provenance": {
                    "resource_fingerprints": normalized_fingerprints,
                    "submission_source": "BIC_INSPECT",
                },
            }
        )
    if not proposals and not challenges:
        raise MemoryGovernanceError(
            "INSPECT submission must contain at least one proposal or challenge"
        )
    return {
        "schema_version": "1.0",
        "operation_id": operation_id,
        "scope": scope,
        "resource_fingerprints": normalized_fingerprints,
        "proposals": proposals,
        "challenges": challenges,
    }


def transition_memory_state(
    record: Mapping[str, Any],
    new_state: str,
    *,
    operator_decision_id: str,
) -> dict[str, Any]:
    """Apply one explicit Operator-governed memory-state transition."""
    current = str(record.get("memory_state", "")).upper()
    target = new_state.upper()
    if current not in MEMORY_STATES or target not in MEMORY_STATES:
        raise MemoryGovernanceError(f"Unsupported memory-state transition: {current} -> {target}")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise MemoryGovernanceError(f"Memory-state transition is not allowed: {current} -> {target}")
    decision = _required_string(operator_decision_id, "operator_decision_id", maximum=128)
    updated = dict(record)
    updated["memory_state"] = target
    updated["operator_decision_id"] = decision
    return updated


def eligible_memory_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Route only active Operator-approved memory into BIC generation evidence."""
    return [
        dict(record)
        for record in records
        if str(record.get("memory_state", "")).upper() == "APPROVED_FOR_USE"
        and str(record.get("status", "ACTIVE")).upper() == "ACTIVE"
    ]


def _read_list(path: Path) -> list[dict[str, Any]]:
    """Read a governance JSON list, returning an empty list only when the file is absent."""
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryGovernanceError(f"Invalid BIC memory file {path}: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise MemoryGovernanceError(f"BIC memory file must contain a list of mappings: {path}")
    return [dict(item) for item in value]


def _memory_record_id(record: Mapping[str, Any]) -> str:
    """Return the stable identity carried by one governed BIC memory record."""
    for key in ("proposal_id", "memory_id", "record_id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise MemoryGovernanceError("BIC memory record has no stable record identity")


def _memory_sources(memory_root: Path) -> tuple[tuple[str, Path], ...]:
    """Return the governed source lists that may contain individual memory records."""
    return (
        ("INSPECT", memory_root / "inspect-proposals.json"),
        ("LEXICON_IMPORT", memory_root / "lexicon-records.json"),
    )


def _materialized_approved_memory(memory_root: Path) -> list[dict[str, Any]]:
    """Build the exact approved-memory view from all governed source record lists."""
    approved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, path in _memory_sources(memory_root):
        for record in eligible_memory_records(_read_list(path)):
            record_id = _memory_record_id(record)
            if record_id in seen:
                raise MemoryGovernanceError(
                    f"Duplicate BIC memory identity across governed stores: {record_id}"
                )
            seen.add(record_id)
            approved.append(record)
    return sorted(approved, key=_memory_record_id)


def list_memory_records(
    memory_root: Path,
    *,
    state: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """List governed memory records without granting or changing any permission."""
    normalized_state = state.strip().upper() if isinstance(state, str) and state.strip() else None
    if normalized_state is not None and normalized_state not in MEMORY_STATES:
        raise MemoryGovernanceError(f"Unsupported memory state filter: {state}")
    normalized_source = source.strip().upper() if isinstance(source, str) and source.strip() else None
    allowed_sources = {label for label, _ in _memory_sources(memory_root)}
    if normalized_source is not None and normalized_source not in allowed_sources:
        raise MemoryGovernanceError(f"Unsupported memory source filter: {source}")
    records: list[dict[str, Any]] = []
    for source_label, path in _memory_sources(memory_root):
        if normalized_source is not None and source_label != normalized_source:
            continue
        for row in _read_list(path):
            row_state = str(row.get("memory_state", "")).upper()
            if normalized_state is not None and row_state != normalized_state:
                continue
            records.append(
                {
                    **row,
                    "record_id": _memory_record_id(row),
                    "record_source": source_label,
                }
            )
    return sorted(records, key=lambda row: (str(row["record_source"]), str(row["record_id"])))


def transition_memory_record_transactionally(
    *,
    memory_root: Path,
    transaction_root: Path,
    record_id: str,
    expected_state: str,
    new_state: str,
    operator_decision_id: str,
    operator: str,
    notes: str = "",
) -> dict[str, Any]:
    """Apply one stale-safe individual memory transition and refresh approved evidence."""
    normalized_id = _required_string(record_id, "record_id", maximum=128)
    normalized_expected = _required_string(expected_state, "expected_state", maximum=40).upper()
    normalized_target = _required_string(new_state, "new_state", maximum=40).upper()
    if normalized_expected not in MEMORY_STATES:
        raise MemoryGovernanceError(f"Unsupported expected memory state: {expected_state}")
    if normalized_target not in MEMORY_STATES:
        raise MemoryGovernanceError(f"Unsupported target memory state: {new_state}")
    decision_id = _required_string(operator_decision_id, "operator_decision_id", maximum=128)
    operator_id = _required_string(operator, "operator", maximum=160)
    recorded_utc = utc_now()
    lock_path = transaction_root.parent / "locks" / "memory-state-transition.lock"
    with WorkspaceLock(lock_path, "BIC_MEMORY_STATE_TRANSITION"):
        source_documents: dict[Path, list[dict[str, Any]]] = {}
        matches: list[tuple[str, Path, int, dict[str, Any]]] = []
        for source_label, path in _memory_sources(memory_root):
            rows = _read_list(path)
            source_documents[path] = rows
            for index, row in enumerate(rows):
                if _memory_record_id(row) == normalized_id:
                    matches.append((source_label, path, index, row))
        if not matches:
            raise MemoryGovernanceError(
                f"Unknown BIC memory record: {normalized_id}",
                code="MEMORY_RECORD_NOT_FOUND",
            )
        if len(matches) != 1:
            raise MemoryGovernanceError(
                f"BIC memory identity is not unique: {normalized_id}",
                code="MEMORY_RECORD_ID_COLLISION",
            )
        source_label, source_path, record_index, record = matches[0]
        current_state = str(record.get("memory_state", "")).upper()
        if current_state != normalized_expected:
            raise MemoryGovernanceError(
                f"BIC memory record {normalized_id} is {current_state}, not {normalized_expected}",
                code="MEMORY_STATE_CONFLICT",
                details={
                    "record_id": normalized_id,
                    "expected_state": normalized_expected,
                    "current_state": current_state,
                },
            )
        updated = transition_memory_state(
            record,
            normalized_target,
            operator_decision_id=decision_id,
        )
        transition_id = _stable_id(
            "MTR",
            decision_id,
            f"{normalized_id}:{current_state}->{normalized_target}",
        )
        updated["status"] = {
            "PROPOSED": "PENDING",
            "REVIEWED": "PENDING",
            "APPROVED_FOR_USE": "ACTIVE",
            "REJECTED": "REJECTED",
            "SUPERSEDED": "SUPERSEDED",
            "INACTIVE": "INACTIVE",
        }[normalized_target]
        updated["last_transition_id"] = transition_id
        updated["updated_utc"] = recorded_utc
        source_documents[source_path][record_index] = updated
        transitions_path = memory_root / "memory-state-transitions.json"
        transitions = _read_list(transitions_path)
        if any(str(row.get("transition_id")) == transition_id for row in transitions):
            raise MemoryGovernanceError(
                f"BIC memory transition is already recorded: {transition_id}",
                code="MEMORY_TRANSITION_ALREADY_RECORDED",
            )
        transition = {
            "schema_version": "1.0",
            "transition_id": transition_id,
            "record_id": normalized_id,
            "record_source": source_label,
            "from_state": current_state,
            "to_state": normalized_target,
            "operator_decision_id": decision_id,
            "operator": operator_id,
            "notes": notes.strip(),
            "recorded_utc": recorded_utc,
        }
        transitions.append(transition)
        transaction = FileTransaction(
            transaction_root,
            operation="BIC_MEMORY_STATE_TRANSITION",
            allowed_roots=(memory_root,),
        )
        transaction.stage_json(source_path, source_documents[source_path])
        transaction.stage_json(transitions_path, transitions)
        transaction.stage_json(
            memory_root / "approved-memory.json",
            _materialized_approved_memory_from_documents(source_documents),
        )
        transaction.commit()
    return {
        **transition,
        "status": "COMMITTED",
        "transaction_id": transaction.transaction_id,
        "record": updated,
    }


def _materialized_approved_memory_from_documents(
    source_documents: Mapping[Path, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Build approved memory from already locked source documents."""
    approved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rows in source_documents.values():
        for record in eligible_memory_records(rows):
            record_id = _memory_record_id(record)
            if record_id in seen:
                raise MemoryGovernanceError(
                    f"Duplicate BIC memory identity across governed stores: {record_id}"
                )
            seen.add(record_id)
            approved.append(record)
    return sorted(approved, key=_memory_record_id)


def validate_lexicon_import(
    document: Mapping[str, Any],
    *,
    source_sha256: str,
    operator: str,
    operator_decision_id: str,
) -> dict[str, Any]:
    """Validate one governed lexicon import without approving any imported record."""
    if document.get("schema_version") != "1.0":
        raise MemoryGovernanceError("Lexicon import schema_version must be '1.0'")
    import_id = _required_string(document.get("import_id"), "import_id", maximum=128)
    if not ID_RE.fullmatch(import_id):
        raise MemoryGovernanceError("import_id contains unsupported characters")
    digest = _required_string(source_sha256, "source_sha256", maximum=64).lower()
    if not SHA256_RE.fullmatch(digest):
        raise MemoryGovernanceError("source_sha256 must be a lowercase SHA-256 digest")
    source_raw = document.get("source")
    if not isinstance(source_raw, dict):
        raise MemoryGovernanceError("Lexicon import source must be a mapping")
    source = {
        "name": _required_string(source_raw.get("name"), "source.name", maximum=240),
        "version": _required_string(source_raw.get("version"), "source.version", maximum=120),
        "language": _required_string(source_raw.get("language"), "source.language", maximum=80),
        "authority_id": _required_string(
            source_raw.get("authority_id"),
            "source.authority_id",
            maximum=160,
        ),
    }
    entries_raw = document.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise MemoryGovernanceError("Lexicon import entries must be a nonempty list")
    if any(not isinstance(item, dict) for item in entries_raw):
        raise MemoryGovernanceError("Every lexicon import entry must be a mapping")
    normalized_entries: list[dict[str, Any]] = []
    submitted_ids: set[str] = set()
    for index, item in enumerate(entries_raw, start=1):
        submitted_id = _required_string(
            item.get("submitted_id", f"L{index:04d}"),
            f"entries[{index}].submitted_id",
            maximum=128,
        )
        if submitted_id in submitted_ids:
            raise MemoryGovernanceError(f"Duplicate lexicon submitted_id: {submitted_id}")
        submitted_ids.add(submitted_id)
        record_type = _required_string(
            item.get("record_type", "LEXICAL_ENTRY"),
            f"entries[{index}].record_type",
            maximum=80,
        ).upper()
        if record_type not in RECORD_TYPES:
            raise MemoryGovernanceError(f"Unsupported lexicon record_type: {record_type}")
        payload = item.get("payload")
        if not isinstance(payload, dict) or not payload:
            raise MemoryGovernanceError(f"entries[{index}].payload must be a nonempty mapping")
        evidence_refs = item.get("evidence_refs", []) or []
        if not isinstance(evidence_refs, list) or any(
            not isinstance(value, str) or not value.strip() for value in evidence_refs
        ):
            raise MemoryGovernanceError(
                f"entries[{index}].evidence_refs must be a string list"
            )
        record_id = _stable_id("LEX", import_id, submitted_id)
        normalized_entries.append(
            {
                "proposal_id": record_id,
                "submitted_id": submitted_id,
                "operation_id": import_id,
                "scope": str(item.get("scope", "GLOBAL")).strip() or "GLOBAL",
                "record_type": record_type,
                "payload": dict(payload),
                "evidence_refs": [value.strip() for value in evidence_refs],
                "memory_state": "PROPOSED",
                "status": "PENDING",
                "operator_decision_id": "",
                "provenance": {
                    "submission_source": "LEXICON_IMPORT",
                    "import_id": import_id,
                    "source": source,
                    "source_sha256": digest,
                },
            }
        )
    return {
        "schema_version": "1.0",
        "import_id": import_id,
        "source": source,
        "source_sha256": digest,
        "operator": _required_string(operator, "operator", maximum=160),
        "operator_decision_id": _required_string(
            operator_decision_id,
            "operator_decision_id",
            maximum=128,
        ),
        "entries": normalized_entries,
    }


def import_lexicon_transactionally(
    document: Mapping[str, Any],
    *,
    source_sha256: str,
    operator: str,
    operator_decision_id: str,
    notes: str,
    memory_root: Path,
    transaction_root: Path,
    bic_job_id: str | None = None,
) -> dict[str, Any]:
    """Import lexicon records as PROPOSED memory with full provenance and rollback identity."""
    normalized = validate_lexicon_import(
        document,
        source_sha256=source_sha256,
        operator=operator,
        operator_decision_id=operator_decision_id,
    )
    normalized_project = (
        _required_string(bic_job_id, "bic_job_id", maximum=128)
        if bic_job_id is not None
        else None
    )
    if normalized_project:
        for row in normalized["entries"]:
            row["bic_job_id"] = normalized_project
            provenance = dict(row.get("provenance", {}))
            provenance["bic_job_id"] = normalized_project
            row["provenance"] = provenance
    lock_path = transaction_root.parent / "locks" / "lexicon-import.lock"
    with WorkspaceLock(lock_path, "BIC_LEXICON_IMPORT"):
        lexicon_path = memory_root / "lexicon-records.json"
        imports_path = memory_root / "lexicon-imports.json"
        source_documents = {
            memory_root / "inspect-proposals.json": _read_list(memory_root / "inspect-proposals.json"),
            lexicon_path: _read_list(lexicon_path),
        }
        imports = _read_list(imports_path)
        if any(str(row.get("import_id")) == normalized["import_id"] for row in imports):
            raise MemoryGovernanceError(
                f"Lexicon import is already recorded: {normalized['import_id']}",
                code="LEXICON_IMPORT_ALREADY_RECORDED",
            )
        existing_ids = {
            _memory_record_id(row)
            for rows in source_documents.values()
            for row in rows
        }
        incoming_ids = {_memory_record_id(row) for row in normalized["entries"]}
        collisions = sorted(existing_ids.intersection(incoming_ids))
        if collisions:
            raise MemoryGovernanceError(
                "Lexicon import record ID collision: " + ", ".join(collisions),
                code="MEMORY_RECORD_ID_COLLISION",
            )
        source_documents[lexicon_path].extend(normalized["entries"])
        recorded_utc = utc_now()
        import_receipt = {
            "schema_version": "1.0",
            "import_id": normalized["import_id"],
            "source": normalized["source"],
            "source_sha256": normalized["source_sha256"],
            "operator": normalized["operator"],
            "operator_decision_id": normalized["operator_decision_id"],
            "notes": notes.strip(),
            "record_count": len(normalized["entries"]),
            "record_ids": [_memory_record_id(row) for row in normalized["entries"]],
            "status": "COMMITTED",
            "recorded_utc": recorded_utc,
        }
        if normalized_project:
            import_receipt["bic_job_id"] = normalized_project
        imports.append(import_receipt)
        transaction = FileTransaction(
            transaction_root,
            operation="BIC_LEXICON_IMPORT",
            allowed_roots=(memory_root,),
        )
        transaction.stage_json(lexicon_path, source_documents[lexicon_path])
        transaction.stage_json(imports_path, imports)
        transaction.stage_json(
            memory_root / "approved-memory.json",
            _materialized_approved_memory_from_documents(source_documents),
        )
        transaction.commit()
    return {
        **import_receipt,
        "transaction_id": transaction.transaction_id,
    }


def rollback_lexicon_import_transactionally(
    *,
    import_id: str,
    operator: str,
    operator_decision_id: str,
    notes: str,
    memory_root: Path,
    transaction_root: Path,
) -> dict[str, Any]:
    """Deactivate every record from one committed lexicon import and preserve its audit trail."""
    normalized_import_id = _required_string(import_id, "import_id", maximum=128)
    operator_id = _required_string(operator, "operator", maximum=160)
    decision_id = _required_string(operator_decision_id, "operator_decision_id", maximum=128)
    lock_path = transaction_root.parent / "locks" / "lexicon-import.lock"
    with WorkspaceLock(lock_path, "BIC_LEXICON_IMPORT_ROLLBACK"):
        lexicon_path = memory_root / "lexicon-records.json"
        imports_path = memory_root / "lexicon-imports.json"
        rollbacks_path = memory_root / "lexicon-import-rollbacks.json"
        lexicon = _read_list(lexicon_path)
        imports = _read_list(imports_path)
        rollbacks = _read_list(rollbacks_path)
        import_matches = [
            (index, row)
            for index, row in enumerate(imports)
            if str(row.get("import_id")) == normalized_import_id
        ]
        if not import_matches:
            raise MemoryGovernanceError(
                f"Unknown lexicon import: {normalized_import_id}",
                code="LEXICON_IMPORT_NOT_FOUND",
            )
        if len(import_matches) != 1:
            raise MemoryGovernanceError(
                f"Lexicon import identity is not unique: {normalized_import_id}",
                code="LEXICON_IMPORT_ID_COLLISION",
            )
        import_index, import_receipt = import_matches[0]
        if str(import_receipt.get("status")) == "ROLLED_BACK":
            raise MemoryGovernanceError(
                f"Lexicon import is already rolled back: {normalized_import_id}",
                code="LEXICON_IMPORT_ALREADY_ROLLED_BACK",
            )
        recorded_utc = utc_now()
        # Keep every imported row for auditability; rollback changes governed state rather than deleting provenance.
        affected: list[dict[str, str]] = []
        found_records = 0
        for index, record in enumerate(lexicon):
            provenance = record.get("provenance")
            if not isinstance(provenance, dict) or str(provenance.get("import_id")) != normalized_import_id:
                continue
            found_records += 1
            previous = str(record.get("memory_state", "")).upper()
            updated = dict(record)
            updated["memory_state"] = "INACTIVE"
            updated["status"] = "INACTIVE"
            updated["operator_decision_id"] = decision_id
            updated["last_transition_id"] = _stable_id(
                "MTR",
                decision_id,
                f"{_memory_record_id(record)}:{previous}->INACTIVE",
            )
            updated["updated_utc"] = recorded_utc
            lexicon[index] = updated
            affected.append(
                {
                    "record_id": _memory_record_id(record),
                    "from_state": previous,
                    "to_state": "INACTIVE",
                }
            )
        expected_count = int(import_receipt.get("record_count", 0))
        if found_records != expected_count:
            raise MemoryGovernanceError(
                f"Lexicon rollback found {found_records} of {expected_count} imported records",
                code="LEXICON_IMPORT_RECORD_MISMATCH",
            )
        rollback_id = _stable_id("LRB", decision_id, normalized_import_id)
        if any(str(row.get("rollback_id")) == rollback_id for row in rollbacks):
            raise MemoryGovernanceError(
                f"Lexicon rollback is already recorded: {rollback_id}",
                code="LEXICON_IMPORT_ALREADY_ROLLED_BACK",
            )
        rollback = {
            "schema_version": "1.0",
            "rollback_id": rollback_id,
            "import_id": normalized_import_id,
            "operator": operator_id,
            "operator_decision_id": decision_id,
            "notes": notes.strip(),
            "affected_records": affected,
            "status": "COMMITTED",
            "recorded_utc": recorded_utc,
        }
        rollbacks.append(rollback)
        imports[import_index] = {
            **import_receipt,
            "status": "ROLLED_BACK",
            "rollback_id": rollback_id,
            "rolled_back_utc": recorded_utc,
        }
        source_documents = {
            memory_root / "inspect-proposals.json": _read_list(memory_root / "inspect-proposals.json"),
            lexicon_path: lexicon,
        }
        transaction = FileTransaction(
            transaction_root,
            operation="BIC_LEXICON_IMPORT_ROLLBACK",
            allowed_roots=(memory_root,),
        )
        transaction.stage_json(lexicon_path, lexicon)
        transaction.stage_json(imports_path, imports)
        transaction.stage_json(rollbacks_path, rollbacks)
        transaction.stage_json(
            memory_root / "approved-memory.json",
            _materialized_approved_memory_from_documents(source_documents),
        )
        transaction.commit()
    return {
        **rollback,
        "transaction_id": transaction.transaction_id,
    }


def submit_inspect_transactionally(
    document: Mapping[str, Any],
    *,
    memory_root: Path,
    transaction_root: Path,
    bic_job_id: str | None = None,
) -> dict[str, Any]:
    """Commit INSPECT proposals and challenges under one lock and transaction."""
    normalized = validate_inspect_submission(document)
    normalized_project = (
        _required_string(bic_job_id, "bic_job_id", maximum=128)
        if bic_job_id is not None
        else None
    )
    if normalized_project:
        for collection in (normalized["proposals"], normalized["challenges"]):
            for row in collection:
                row["bic_job_id"] = normalized_project
                provenance = dict(row.get("provenance", {}))
                provenance["bic_job_id"] = normalized_project
                row["provenance"] = provenance
    proposals_path = memory_root / "inspect-proposals.json"
    challenges_path = memory_root / "translation-challenges.json"
    operations_path = memory_root / "inspect-operations.json"
    lock_path = transaction_root.parent / "locks" / "inspect-submit.lock"
    with WorkspaceLock(lock_path, "BIC_INSPECT_SUBMIT"):
        proposals = _read_list(proposals_path)
        challenges = _read_list(challenges_path)
        operations = _read_list(operations_path)
        existing_operations = {str(item.get("operation_id", "")) for item in operations}
        if normalized["operation_id"] in existing_operations:
            raise MemoryGovernanceError(
                f"INSPECT operation is already committed: {normalized['operation_id']}"
            )
        existing_proposals = {str(item.get("proposal_id", "")) for item in proposals}
        existing_challenges = {str(item.get("challenge_id", "")) for item in challenges}
        if existing_proposals.intersection(
            item["proposal_id"] for item in normalized["proposals"]
        ):
            raise MemoryGovernanceError("INSPECT proposal ID collision")
        if existing_challenges.intersection(
            item["challenge_id"] for item in normalized["challenges"]
        ):
            raise MemoryGovernanceError("INSPECT challenge ID collision")
        proposals.extend(normalized["proposals"])
        challenges.extend(normalized["challenges"])
        operation_record = {
                "operation_id": normalized["operation_id"],
                "scope": normalized["scope"],
                "state": "COMPLETE",
                "proposal_count": len(normalized["proposals"]),
                "challenge_count": len(normalized["challenges"]),
                "resource_fingerprints": normalized["resource_fingerprints"],
            }
        if normalized_project:
            operation_record["bic_job_id"] = normalized_project
        operations.append(operation_record)
        transaction = FileTransaction(
            transaction_root,
            operation="BIC_INSPECT_SUBMIT",
            allowed_roots=(memory_root,),
        )
        transaction.stage_json(proposals_path, proposals)
        transaction.stage_json(challenges_path, challenges)
        transaction.stage_json(operations_path, operations)
        transaction.commit()
    result = {
        "transaction_id": transaction.transaction_id,
        "operation_id": normalized["operation_id"],
        "state": "COMPLETE",
        "proposals_committed": len(normalized["proposals"]),
        "challenges_committed": len(normalized["challenges"]),
    }
    if normalized_project:
        result["bic_job_id"] = normalized_project
    return result


REVIEW_DECISIONS = {"APPROVED_FOR_REWRITE", "RETURN_FOR_REVIEW", "REJECTED"}


def record_human_memory_review(
    *,
    memory_root: Path,
    transaction_root: Path,
    scope: str,
    decision_id: str,
    reviewer: str,
    decision: str,
    notes: str = "",
) -> dict[str, Any]:
    """Record an explicit human review receipt for the latest INSPECT operation."""
    normalized_scope = parse_scope(scope).label()
    normalized_decision = decision.strip().upper()
    if normalized_decision not in REVIEW_DECISIONS:
        raise MemoryGovernanceError(
            f"Unsupported human memory review decision: {decision}",
            code="HUMAN_REVIEW_DECISION_INVALID",
            affected_scope=normalized_scope,
        )
    operations = _read_list(memory_root / "inspect-operations.json")
    matches = [
        row for row in operations
        if str(row.get("scope")) == normalized_scope and str(row.get("state")) == "COMPLETE"
    ]
    if not matches:
        raise MemoryGovernanceError(
            f"No committed INSPECT operation exists for {normalized_scope}",
            code="INSPECT_REQUIRED",
            affected_scope=normalized_scope,
        )
    operation = matches[-1]
    receipt = {
        "schema_version": "1.0",
        "review_id": _required_string(decision_id, "decision_id", maximum=128),
        "reviewer": _required_string(reviewer, "reviewer", maximum=160),
        "decision": normalized_decision,
        "scope": normalized_scope,
        "operation_id": str(operation["operation_id"]),
        "resource_fingerprints": dict(operation.get("resource_fingerprints", {})),
        "notes": notes.strip(),
    }
    receipts_path = memory_root / "human-review-receipts.json"
    receipts = _read_list(receipts_path)
    receipts = [row for row in receipts if str(row.get("operation_id")) != receipt["operation_id"]]
    receipts.append(receipt)
    lock_path = transaction_root.parent / "locks" / "human-memory-review.lock"
    with WorkspaceLock(lock_path, "BIC_HUMAN_MEMORY_REVIEW"):
        transaction = FileTransaction(
            transaction_root,
            operation="BIC_HUMAN_MEMORY_REVIEW",
            allowed_roots=(memory_root,),
        )
        transaction.stage_json(receipts_path, receipts)
        transaction.commit()
    return {**receipt, "transaction_id": transaction.transaction_id, "status": "RECORDED"}


def inspect_completion_and_review_status(
    memory_root: Path,
    scope: str,
    *,
    bic_job_id: str | None = None,
) -> dict[str, Any]:
    """Return committed INSPECT evidence for one scope and optional BIC project identity."""
    normalized_scope = parse_scope(scope).label()
    normalized_project = bic_job_id.strip() if isinstance(bic_job_id, str) and bic_job_id.strip() else None
    operations = _read_list(memory_root / "inspect-operations.json")
    matches = [
        row for row in operations
        if str(row.get("scope")) == normalized_scope
        and str(row.get("state")) == "COMPLETE"
        and (normalized_project is None or str(row.get("bic_job_id", "")) == normalized_project)
    ]
    if not matches:
        raise MemoryGovernanceError(
            f"BIC REWRITE requires a committed INSPECT operation for {normalized_scope}",
            code="INSPECT_REQUIRED",
            affected_scope=normalized_scope,
        )
    operation = dict(matches[-1])
    receipts = _read_list(memory_root / "human-review-receipts.json")
    receipt = next(
        (
            dict(row)
            for row in reversed(receipts)
            if str(row.get("operation_id")) == str(operation.get("operation_id"))
            and str(row.get("scope")) == normalized_scope
        ),
        None,
    )
    decision = str((receipt or {}).get("decision", "PENDING")).upper()
    attention_level = {
        "APPROVED_FOR_REWRITE": 0,
        "PENDING": 2,
        "RETURN_FOR_REVIEW": 3,
        "REJECTED": 4,
    }.get(decision, 2)
    return {
        "schema_version": "1.2",
        "scope": normalized_scope,
        "bic_job_id": operation.get("bic_job_id"),
        "operation_id": str(operation.get("operation_id")),
        "inspect_state": "COMPLETE",
        "resource_fingerprints": dict(operation.get("resource_fingerprints", {})),
        "review_status": decision,
        "review_receipt": receipt,
        "attention": {
            "level": attention_level,
            "classification": (
                "NONE" if attention_level == 0 else
                "REVIEW_RECOMMENDED" if attention_level == 2 else
                "URGENT" if attention_level == 3 else
                "CRITICAL"
            ),
            "next_stage_allowed": True,
            "prompt_required": False,
        },
    }


def require_human_memory_review(memory_root: Path, scope: str) -> dict[str, Any]:
    """Return non-blocking INSPECT and human-review status."""
    return inspect_completion_and_review_status(memory_root, scope)
