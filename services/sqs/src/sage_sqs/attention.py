"""ADMIN attention aggregation facade."""
from __future__ import annotations

from typing import Any

from .repository import Repository


def attention_items(repo: Repository) -> list[dict[str, Any]]:
    return repo.list_attention(status="OPEN")
