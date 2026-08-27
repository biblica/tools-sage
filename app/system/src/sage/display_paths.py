"""Display-only shortening for paths beneath the active SAGE checkout."""

from __future__ import annotations

from pathlib import Path


def sage_checkout_root(app_root: Path) -> Path:
    """Return the repository root when the configured application root is ``app``."""
    resolved = app_root.expanduser().resolve()
    if resolved.name == "app":
        return resolved.parent
    return resolved


def operator_path(app_root: Path, value: str | Path) -> str:
    """Shorten a SAGE-internal path without changing its persisted filesystem value."""
    path = Path(value).expanduser().resolve()
    root = sage_checkout_root(app_root)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    return "SAGE" if not relative.parts else f"SAGE/{relative.as_posix()}"


def operator_text(app_root: Path, value: str) -> str:
    """Shorten embedded absolute SAGE paths in one human-facing diagnostic string."""
    root = sage_checkout_root(app_root)
    prefix = str(root)
    return value.replace(prefix + "/", "SAGE/").replace(prefix + "\\", "SAGE/")
