"""Parse ``input/phrases.txt``: literal SOURCE wording the team wants on the terms list (handover doc 13).

One phrase per line. Blank lines and lines starting with ``#`` are ignored. A line with no letters is a
malformed row: it is reported with its line number and never silently skipped; the rest still loads
(never hard-block). Text is literal SOURCE only: no TARGET synonyms or meanings are read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .segment import nfc, tokenize
from .traits import WipTraits

PHRASES_FILE = "phrases.txt"


@dataclass(frozen=True)
class PhraseLine:
    """One accepted phrase: its line, surface and comparison tokens."""

    line: int
    surface: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class PhraseProblem:
    """One line that could not be used, with the reason."""

    line: int
    text: str
    reason: str


def parse_phrases(text: str, traits: WipTraits) -> tuple[list[PhraseLine], list[PhraseProblem]]:
    """Return accepted phrases and per-line problems. Duplicates (same tokens) are reported, first wins."""
    phrases: list[PhraseLine] = []
    problems: list[PhraseProblem] = []
    seen: dict[tuple[str, ...], int] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = nfc(raw.lstrip("﻿")).strip()
        if not line or line.startswith("#"):
            continue
        tokens = tuple(t.norm for t in tokenize(
            line, cased=traits.cased, letter_marks=traits.letter_marks, unspaced=traits.unspaced))
        if not tokens:
            problems.append(PhraseProblem(number, line, "NO_LETTERS"))
        elif tokens in seen:
            problems.append(PhraseProblem(number, line, f"DUPLICATE_OF_LINE_{seen[tokens]}"))
        else:
            seen[tokens] = number
            phrases.append(PhraseLine(number, line, tokens))
    return phrases, problems


def read_phrases(path: Path, traits: WipTraits) -> tuple[list[PhraseLine], list[PhraseProblem]]:
    """Read a phrases file (absent file: no phrases). Invalid UTF-8 is a reported problem, not a stop."""
    if not path.is_file():
        return [], []
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return [], [PhraseProblem(0, path.name, f"NOT_UTF8:{exc.reason}")]
    return parse_phrases(text, traits)
