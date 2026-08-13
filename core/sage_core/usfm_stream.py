"""Logical USFM line segmentation for line-level markers outside notes."""

from __future__ import annotations

import re
from collections.abc import Iterator

MARKER_TOKEN_RE = re.compile(r"\\(\+?[A-Za-z0-9][A-Za-z0-9-]*)(\*)?")
NOTE_CONTAINERS = {"f", "fe", "ef", "efe", "x", "ex"}
LINE_LEVEL_MARKER_RE = re.compile(
    r"^(?:id|c|v|p|m|po|pr|cls|pmo|pm|pmc|pmr|pi\d*|mi\d*|nb|pc|ph\d*|"
    r"q\d*|qr|qc|qa|qm\d*|qd|lh|li\d*|lf|lim\d*|tr|tc\d*|th\d*|tcr\d*|"
    r"thr\d*|b|s\d*|ms\d*|mr|sr|r|d|sp|sd\d*|mt\d*|mte\d*|imt\d*|"
    r"imte\d*|is\d*|ip|ipi|im|imi|ipq|imq|ipr|iq\d*|ib|ili\d*|iot|"
    r"io\d*|iex|cl|cd|lit)$"
)


def _clean_marker(value: str) -> str:
    """Return the canonical marker name emitted by the streaming USFM parser."""
    return value.lstrip("+").casefold()


def iter_logical_usfm_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield line-level USFM fragments with their original physical line number.

    USFM projects normally place paragraph and verse markers on separate physical
    lines, but the format also permits sequences such as ``\\p \\v 1 ...``. This
    iterator splits line-level markers only when they are outside ``\\f``/``\\x``
    note containers. Inline character markers remain untouched.
    """
    note_stack: list[str] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        boundaries: list[int] = []
        for match in MARKER_TOKEN_RE.finditer(line):
            marker = _clean_marker(match.group(1))
            closing = bool(match.group(2))
            if note_stack:
                if closing and marker == note_stack[-1]:
                    note_stack.pop()
                elif not closing and marker in NOTE_CONTAINERS:
                    note_stack.append(marker)
                continue
            if not closing and marker in NOTE_CONTAINERS:
                note_stack.append(marker)
                continue
            if not closing and LINE_LEVEL_MARKER_RE.fullmatch(marker):
                boundaries.append(match.start())
        if not boundaries:
            yield line_number, line.strip()
            continue
        boundaries = sorted(set(boundaries))
        if boundaries[0] > 0 and line[: boundaries[0]].strip():
            yield line_number, line[: boundaries[0]].strip()
        for index, start in enumerate(boundaries):
            end = boundaries[index + 1] if index + 1 < len(boundaries) else len(line)
            fragment = line[start:end].strip()
            if fragment:
                yield line_number, fragment
