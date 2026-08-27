"""Shared deterministic formatting for Operator-facing numeric menus."""

from __future__ import annotations


def menu_item(number: int | str, label: str) -> str:
    """Render one numeric menu row using the global three-column number contract."""
    value = int(number)
    if value < 0 or value > 999:
        raise ValueError("Numeric menu choices must be between 0 and 999")
    return f"{value:>3}. {label}"
