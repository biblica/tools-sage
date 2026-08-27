"""Journaled multi-file transactions with deterministic rollback and recovery."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from .atomic import atomic_write_bytes, atomic_write_json
from .errors import TransactionError
from .hashing import sha256_bytes, sha256_file
from .state import utc_now


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    """Return whether a candidate path remains inside the governed root."""
    for root in roots:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


class FileTransaction:
    """Stage and commit related files under an auditable recovery journal.

    Cross-directory replacement cannot be one filesystem-atomic operation. SAGE
    therefore combines per-file atomic replacement, a workspace lock, backups,
    and a durable journal that can deterministically roll back an interrupted
    commit.
    """
    # Keep staged writes isolated until prepare and commit establish one recoverable transaction boundary.

    def __init__(
        self,
        transaction_root: Path,
        operation: str,
        transaction_id: str | None = None,
        *,
        allowed_roots: Iterable[Path] | None = None,
    ):
        """Initialize the instance with the supplied governed state."""
        self.transaction_id = transaction_id or f"TX-{uuid.uuid4().hex.upper()}"
        self.operation = operation
        self.root = transaction_root.resolve() / self.transaction_id
        self.staged_root = self.root / "staged"
        self.backup_root = self.root / "backup"
        self.journal_path = self.root / "journal.json"
        self.operations: list[dict[str, Any]] = []
        self.state = "OPEN"
        self.created_utc = utc_now()
        self.allowed_roots = tuple(path.resolve() for path in (allowed_roots or ()))
        self.root.mkdir(parents=True, exist_ok=False)
        self._write_journal()

    def _write_journal(self, *, error: str = "") -> None:
        """Persist the transaction journal atomically after each recoverable state change."""
        atomic_write_json(
            self.journal_path,
            {
                "schema_version": "1.0",
                "transaction_id": self.transaction_id,
                "operation": self.operation,
                "state": self.state,
                "created_utc": self.created_utc,
                "updated_utc": utc_now(),
                "error": error,
                "operations": self.operations,
            },
        )

    def stage_bytes(self, target: Path, payload: bytes) -> None:
        """Stage one target replacement and preserve its previous content."""
        if self.state != "OPEN":
            raise TransactionError(f"Cannot stage files while transaction is {self.state}")
        target = target.resolve()
        if self.allowed_roots and not _inside(target, self.allowed_roots):
            raise TransactionError(f"Transaction target is outside its allowed roots: {target}")
        if any(Path(item["target"]) == target for item in self.operations):
            raise TransactionError(f"Transaction target is staged more than once: {target}")
        index = len(self.operations) + 1
        staged = self.staged_root / f"{index:04d}.new"
        backup = self.backup_root / f"{index:04d}.old"
        atomic_write_bytes(staged, payload)
        before_exists = target.exists()
        before_sha256 = ""
        if before_exists:
            if not target.is_file() or target.is_symlink():
                raise TransactionError(f"Transaction target is not a regular file: {target}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            before_sha256 = sha256_file(target)
        self.operations.append(
            {
                "target": str(target),
                "staged": str(staged),
                "backup": str(backup),
                "before_exists": before_exists,
                "before_sha256": before_sha256,
                "after_sha256": sha256_bytes(payload),
                "status": "STAGED",
            }
        )
        self._write_journal()

    def stage_text(self, target: Path, text: str) -> None:
        """Stage UTF-8 text for the pending atomic transaction."""
        self.stage_bytes(target, text.encode("utf-8"))

    def stage_json(self, target: Path, value: Any) -> None:
        """Stage deterministic UTF-8 JSON for the pending atomic transaction."""
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.stage_text(target, payload)

    def prepare(self) -> None:
        """Freeze the staged operation list before commit."""
        if self.state != "OPEN":
            raise TransactionError(f"Cannot prepare transaction while it is {self.state}")
        if not self.operations:
            raise TransactionError("Cannot prepare an empty transaction")
        self.state = "PREPARED"
        self._write_journal()

    def commit(self, *, failure_hook: Callable[[int], None] | None = None) -> None:
        """Commit all staged files, rolling back immediately on any failure."""
        if self.state == "OPEN":
            self.prepare()
        if self.state != "PREPARED":
            raise TransactionError(f"Cannot commit transaction while it is {self.state}")
        self.state = "COMMITTING"
        self._write_journal()
        try:
            for index, operation in enumerate(self.operations, start=1):
                target = Path(operation["target"])
                staged = Path(operation["staged"])
                before_exists = bool(operation["before_exists"])
                if before_exists:
                    if not target.is_file() or target.is_symlink() or sha256_file(target) != operation["before_sha256"]:
                        raise TransactionError(
                            f"Transaction target changed after staging and will not be overwritten: {target}"
                        )
                elif target.exists():
                    raise TransactionError(
                        f"Transaction target appeared after staging and will not be overwritten: {target}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, target)
                operation["status"] = "COMMITTED"
                self._write_journal()
                if failure_hook is not None:
                    failure_hook(index)
            self.state = "COMMITTED"
            self._write_journal()
        except Exception as exc:
            try:
                self.rollback(reason=str(exc))
            except Exception as rollback_exc:
                raise TransactionError(
                    f"Transaction {self.transaction_id} failed and rollback also failed: "
                    f"commit={exc}; rollback={rollback_exc}"
                ) from rollback_exc
            raise TransactionError(
                f"Transaction {self.transaction_id} failed and was rolled back: {exc}"
            ) from exc

    def rollback(self, *, reason: str = "") -> None:
        """Restore every committed target to its exact pre-transaction state."""
        for operation in reversed(self.operations):
            target = Path(operation["target"])
            backup = Path(operation["backup"])
            target_matches_after = (
                target.is_file() and sha256_file(target) == operation["after_sha256"]
            )
            if operation.get("status") == "COMMITTED" and not target_matches_after:
                raise TransactionError(
                    f"Rollback target changed after commit and will not be overwritten: {target}"
                )
            if operation.get("status") == "COMMITTED" or target_matches_after:
                if operation["before_exists"]:
                    if not backup.exists():
                        raise TransactionError(f"Backup is missing for rollback target {target}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, target)
                elif target.exists():
                    target.unlink()
                operation["status"] = "ROLLED_BACK"
        self.state = "ROLLED_BACK"
        self._write_journal(error=reason)


def load_transaction_journal(transaction_path: Path) -> dict[str, Any]:
    """Load and structurally validate one transaction journal."""
    journal_path = transaction_path / "journal.json"
    try:
        value = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransactionError(f"Invalid transaction journal {journal_path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("operations"), list):
        raise TransactionError(f"Invalid transaction journal structure: {journal_path}")
    return value


def recover_transaction(
    transaction_path: Path,
    *,
    mode: str = "rollback",
    allowed_roots: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Recover an interrupted transaction by conflict-safe deterministic rollback."""
    journal = load_transaction_journal(transaction_path)
    state = str(journal.get("state", ""))
    if state in {"COMMITTED", "ROLLED_BACK"}:
        return journal
    if mode != "rollback":
        raise TransactionError(f"Unsupported recovery mode: {mode}")
    roots = tuple(path.resolve() for path in (allowed_roots or ()))
    operations = list(journal["operations"])
    for operation in reversed(operations):
        target = Path(operation["target"]).resolve()
        if roots and not _inside(target, roots):
            raise TransactionError(f"Recovery target is outside its allowed roots: {target}")
        backup = Path(operation["backup"])
        target_matches_after = (
            target.is_file() and sha256_file(target) == operation.get("after_sha256", "")
        )
        if operation.get("status") == "COMMITTED" and not target_matches_after:
            raise TransactionError(
                f"Recovery target changed after the interrupted commit: {target}"
            )
        if operation.get("status") == "COMMITTED" or target_matches_after:
            if operation.get("before_exists"):
                if not backup.exists():
                    raise TransactionError(f"Backup is missing for recovery target {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
            elif target.exists():
                target.unlink()
            operation["status"] = "ROLLED_BACK"
    journal["state"] = "ROLLED_BACK"
    journal["updated_utc"] = utc_now()
    journal["error"] = "Recovered by deterministic rollback."
    journal["operations"] = operations
    atomic_write_json(transaction_path / "journal.json", journal)
    return journal


def incomplete_transactions(transaction_root: Path) -> list[Path]:
    """Return transaction directories that still require recovery."""
    if not transaction_root.exists():
        return []
    result: list[Path] = []
    for path in sorted(item for item in transaction_root.iterdir() if item.is_dir()):
        try:
            state = str(load_transaction_journal(path).get("state", ""))
        except TransactionError:
            result.append(path)
            continue
        if state not in {"COMMITTED", "ROLLED_BACK"}:
            result.append(path)
    return result
