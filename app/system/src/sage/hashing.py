"""Hashing helpers for immutable resources, derived caches, and provenance."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


def sha256_bytes(payload: bytes) -> str:
    """Return the hexadecimal SHA-256 digest for bytes."""
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash one file without loading it entirely into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_paths(paths: Iterable[Path], *, relative_to: Path | None = None) -> str:
    """Hash path names and contents in a deterministic order."""
    digest = hashlib.sha256()
    base = relative_to.resolve() if relative_to else None
    for path in sorted((item.resolve() for item in paths), key=str):
        label = str(path.relative_to(base)) if base else str(path)
        digest.update(label.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()
