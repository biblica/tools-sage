"""Shared deterministic formatting for Operator-facing terminal surfaces."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


DEFAULT_VIEWPORT_COLUMNS = 72
_MENU_PROTOCOL_ENTITY_RE = re.compile(
    r"\b(?:Project|Projects|Job|Jobs|Run|Runs|Task|Tasks)\b",
    flags=re.IGNORECASE,
)


def sentence_case_menu_label(label: str) -> str:
    """Uppercase governed entity tokens only when they occur mid-sentence."""
    value = str(label)
    first_word = re.search(r"\b\w", value)
    first_index = first_word.start() if first_word is not None else -1

    def replace(match: re.Match[str]) -> str:
        """Keep sentence-initial display text natural and mark later protocol entities."""
        return match.group(0) if match.start() == first_index else match.group(0).upper()

    return _MENU_PROTOCOL_ENTITY_RE.sub(replace, value)


def display_width(value: str) -> int:
    """Return the number of terminal cells occupied by one plain-text value."""
    width = 0
    for character in str(value):
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
    return width


def _display_ljust(value: str, width: int) -> str:
    """Pad a value to a terminal-cell width without assuming one cell per code point."""
    return value + " " * max(0, width - display_width(value))


def _split_display_line(value: str, width: int) -> tuple[str, str]:
    """Split one non-empty line at a word boundary within the cell budget."""
    cells = 0
    end = 0
    for index, character in enumerate(value):
        character_width = display_width(character)
        if cells + character_width > width:
            break
        cells += character_width
        end = index + 1
    if end == len(value):
        return value.rstrip(), ""
    if end == 0:
        end = 1
    prefix = value[:end]
    word_break = max(prefix.rfind(" "), prefix.rfind("\t"))
    if word_break > 0:
        return prefix[:word_break].rstrip(), value[word_break + 1 :].lstrip()
    return prefix.rstrip(), value[end:].lstrip()


def wrap_display_text(
    value: str,
    width: int,
    *,
    initial_indent: str = "",
    subsequent_indent: str = "",
) -> tuple[str, ...]:
    """Wrap plain text to a terminal-cell width with optional hanging indentation."""
    width = max(1, int(width))
    rendered: list[str] = []
    physical_lines = str(value).split("\n")
    for physical_index, physical_line in enumerate(physical_lines):
        indent = initial_indent if physical_index == 0 else subsequent_indent
        leading = physical_line[: len(physical_line) - len(physical_line.lstrip())]
        if leading:
            indent += leading
        continuation_indent = subsequent_indent + leading
        remaining = physical_line.lstrip().rstrip()
        if not remaining:
            rendered.append(indent.rstrip())
            continue
        while remaining:
            available = max(1, width - display_width(indent))
            segment, remaining = _split_display_line(remaining, available)
            rendered.append(indent + segment)
            indent = continuation_indent
    return tuple(rendered)


def wrapped_menu_item(number: int | str, label: str, width: int) -> tuple[str, ...]:
    """Render one menu row with continuation text aligned beneath its label."""
    prefix = menu_item(number, "")
    return wrap_display_text(
        sentence_case_menu_label(label),
        width,
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
    )


def information_rows(
    rows: Iterable[tuple[str, object]],
    width: int,
    *,
    label_width: int = 20,
    indent: str = "",
) -> tuple[str, ...]:
    """Render aligned label/value rows with wrapped values under one value column."""
    width = max(1, int(width))
    indent = str(indent).expandtabs(4)
    indent_width = display_width(indent)
    label_width = max(
        2,
        min(int(label_width), max(2, width - indent_width - 1)),
    )
    rendered: list[str] = []
    for label, raw_value in rows:
        value = ("—" if raw_value in (None, "") else str(raw_value)).expandtabs(4)
        label_text = str(label).expandtabs(4)
        prefix = indent + _display_ljust(label_text, label_width)
        if display_width(prefix) >= width:
            rendered.extend(
                wrap_display_text(
                    label_text,
                    width,
                    initial_indent=indent,
                    subsequent_indent=indent,
                )
            )
            prefix = indent + " " * min(
                label_width,
                max(0, width - indent_width - 1),
            )
        rendered.extend(
            wrap_display_text(
                value,
                width,
                initial_indent=prefix,
                subsequent_indent=" " * display_width(prefix),
            )
        )
    return tuple(rendered)


def menu_item(number: int | str, label: str) -> str:
    """Render one numeric menu row using the global three-column number contract."""
    value = int(number)
    if value < 0 or value > 999:
        raise ValueError("Numeric menu choices must be between 0 and 999")
    return f"{value:>3}. {sentence_case_menu_label(label)}"
