"""Cross-platform directory locks for mutually exclusive SAGE operations."""

from __future__ import annotations

import json
import os
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .errors import LockError


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _process_exists(pid: int) -> bool:
    """Return whether the recorded process still exists on the current host."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


@dataclass
class WorkspaceLock:
    """Acquire one lock directory and remove it only if this process owns it."""

    path: Path
    operation: str
    break_stale: bool = False

    def __post_init__(self) -> None:
        """Validate and normalize fields after dataclass initialization."""
        self.owner_file = self.path / "owner.json"
        self.owner: dict[str, Any] = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "operation": self.operation,
            "acquired_utc": utc_now(),
        }
        self.acquired = False

    def _existing_owner(self) -> dict[str, Any]:
        """Read the lock owner receipt, returning no owner when the receipt is absent or invalid."""
        if not self.owner_file.exists():
            return {}
        try:
            return json.loads(self.owner_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _is_stale(self, owner: dict[str, Any]) -> bool:
        """Return whether the lock receipt is old enough and its owner is no longer active."""
        if not owner:
            return True
        if owner.get("host") != socket.gethostname():
            return False
        try:
            pid = int(owner.get("pid", 0))
        except (TypeError, ValueError):
            return True
        return not _process_exists(pid)

    def acquire(self) -> "WorkspaceLock":
        """Acquire the lock atomically, recovering only a provably stale same-host owner."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.mkdir()
        except FileExistsError as exc:
            existing = self._existing_owner()
            if self.break_stale and self._is_stale(existing):
                shutil.rmtree(self.path)
                self.path.mkdir()
            else:
                detail = json.dumps(existing, ensure_ascii=False, sort_keys=True) if existing else "unknown owner"
                raise LockError(f"Workspace is locked by {detail}") from exc
        atomic_write_json(self.owner_file, self.owner)
        self.acquired = True
        return self

    def release(self) -> None:
        """Remove the lock only when the current process still owns its receipt."""
        if not self.acquired or not self.path.exists():
            return
        existing = self._existing_owner()
        if existing.get("pid") != self.owner.get("pid") or existing.get("host") != self.owner.get("host"):
            raise LockError(f"Refusing to release a lock now owned by another process: {self.path}")
        shutil.rmtree(self.path)
        self.acquired = False

    def __enter__(self) -> "WorkspaceLock":
        """Acquire the managed resource and return the context value."""
        return self.acquire()

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Release the managed resource without suppressing exceptions."""
        self.release()
