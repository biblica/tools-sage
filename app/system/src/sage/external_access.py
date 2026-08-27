"""Filesystem policy for mapped Paratext/PTLite Scripture resources."""

from __future__ import annotations

from pathlib import Path

from .errors import ValidationError

READ_ONLY_SCRIPTURE = "READ_ONLY_SCRIPTURE"
# SAGE Project Inventory capability. Possession of this capability does not grant writes by itself.
READ_WRITE_SCRIPTURE = "READ_WRITE_SCRIPTURE"
# Effective/legacy mode used only inside a BIC Job runtime for its bound TARGET.
READ_WRITE_TARGET = "READ_WRITE_TARGET"
EXTERNAL_ACCESS_MODES = {READ_ONLY_SCRIPTURE, READ_WRITE_SCRIPTURE, READ_WRITE_TARGET}
READ_SUFFIXES = {".sfm", ".vrs"}
WRITE_SUFFIXES = {".sfm"}


def _inside(path: Path, root: Path) -> bool:
    """Return whether a resolved path remains inside one authorized root."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_external_file(
    path: Path,
    *,
    roots: tuple[Path, ...],
    write: bool = False,
) -> Path:
    """Resolve one external file and enforce root, symlink, and extension boundaries."""
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise ValidationError(f"Symbolic links are not accepted for external Scripture files: {candidate}", code="EXTERNAL_SYMLINK_PROHIBITED")
    resolved = candidate.resolve()
    allowed_roots = tuple(root.expanduser().resolve() for root in roots)
    if not any(_inside(resolved, root) for root in allowed_roots):
        raise ValidationError(f"External Scripture path escapes its authorized root: {candidate}", code="EXTERNAL_PATH_ESCAPE")
    suffix = resolved.suffix.casefold()
    allowed = WRITE_SUFFIXES if write else READ_SUFFIXES
    if suffix not in allowed:
        mode = "write" if write else "read"
        raise ValidationError(f"External Scripture {mode} is not allowed for {resolved.name}", code="EXTERNAL_FILE_TYPE_PROHIBITED")
    return resolved
