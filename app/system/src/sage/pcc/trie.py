"""Token-sequence trie for phrase matching (standard library only).

Keys are tuples of normalized tokens. ``find_all`` reports every match, including nested and
overlapping ones, so the caller keeps nested phrases as separate evidence (AT21) and decides display
dedupe itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_END = object()


@dataclass(frozen=True)
class Match:
    """A phrase found at token positions ``[start, end)`` of the searched sequence."""

    start: int
    end: int
    key: tuple[str, ...]
    values: tuple[object, ...]


class TokenTrie:
    """Maps token tuples to one or more payloads."""

    def __init__(self) -> None:
        """Implement init."""
        self._root: dict[object, object] = {}
        self._size = 0

    def __len__(self) -> int:
        """Implement len."""
        return self._size

    def add(self, key: Sequence[str], value: object = None) -> None:
        """Register ``key`` (non-empty); the same key may carry several payloads."""
        if not key:
            raise ValueError("an empty phrase cannot be matched")
        node = self._root
        for token in key:
            node = node.setdefault(token, {})  # type: ignore[assignment]
        bucket = node.setdefault(_END, [])
        if not bucket:
            self._size += 1
        bucket.append(value)  # type: ignore[union-attr]

    def get(self, key: Sequence[str]) -> tuple[object, ...]:
        """The payloads stored for exactly ``key`` (empty when absent)."""
        node = self._root
        for token in key:
            node = node.get(token)  # type: ignore[assignment]
            if node is None:
                return ()
        return tuple(node.get(_END, ()))  # type: ignore[arg-type]

    def find_all(self, tokens: Sequence[str]) -> list[Match]:
        """Every stored phrase occurring in ``tokens``, ordered by start then length."""
        found: list[Match] = []
        for start in range(len(tokens)):
            node = self._root
            for end in range(start, len(tokens)):
                node = node.get(tokens[end])  # type: ignore[assignment]
                if node is None:
                    break
                bucket = node.get(_END)
                if bucket:
                    found.append(Match(start, end + 1, tuple(tokens[start:end + 1]), tuple(bucket)))
        return found

    @classmethod
    def from_items(cls, items: Iterable[tuple[Sequence[str], object]]) -> "TokenTrie":
        """Implement from items."""
        trie = cls()
        for key, value in items:
            trie.add(key, value)
        return trie
