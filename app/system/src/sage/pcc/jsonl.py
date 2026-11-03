"""Strict UTF-8 JSON and JSONL storage for PCC (handover doc 03 "Consistency/atomicity").

Reads fail closed with the file and line of the first problem: invalid UTF-8, a malformed line, a
duplicate key, a non-object line, or a contract violation. Writes are sorted, LF-terminated and
atomic (temporary file, fsync, rename) through SAGE's ``atomic`` helpers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_text
from ..errors import ValidationError
from .contracts import validate_record
from .ids import canonical_json


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object and refuse a repeated key instead of keeping the last value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _decode(path: Path) -> str:
    """Return the file text, failing closed on invalid UTF-8."""
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"{path.name} is not valid UTF-8 at byte {exc.start}",
            code="PCC_FILE_ENCODING_INVALID",
            details={"path": str(path), "byte": exc.start},
        ) from exc


def parse_json_text(text: str) -> Any:
    """Parse one JSON document, rejecting duplicate keys and non-finite numbers."""
    def no_constants(name: str) -> Any:
        """Refuse NaN and Infinity, which JSON does not define."""
        raise ValueError(f"non-finite number {name}")

    return json.loads(text, object_pairs_hook=_reject_duplicates, parse_constant=no_constants)


def read_json(path: Path, *, kind: str | None = None) -> Any:
    """Read one strict JSON document and, when ``kind`` is given, validate it."""
    text = _decode(path)
    try:
        value = parse_json_text(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"{path.name} is not valid JSON: {exc}",
            code="PCC_FILE_MALFORMED",
            details={"path": str(path)},
        ) from exc
    if kind is not None:
        validate_record(kind, value, where=path.name)
    return value


def read_jsonl(path: Path, *, kind: str | None = None) -> list[dict[str, Any]]:
    """Read every record of a strict JSONL file; blank lines are allowed, nothing is skipped."""
    records: list[dict[str, Any]] = []
    for number, line in enumerate(_decode(path).splitlines(), 1):
        if not line.strip():
            continue
        where = f"{path.name} line {number}"
        try:
            value = parse_json_text(line)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValidationError(
                f"{where} is not valid JSON: {exc}",
                code="PCC_FILE_MALFORMED",
                details={"path": str(path), "line": number},
            ) from exc
        if not isinstance(value, dict):
            raise ValidationError(
                f"{where} must be one JSON object",
                code="PCC_FILE_MALFORMED",
                details={"path": str(path), "line": number},
            )
        if kind is not None:
            validate_record(kind, value, where=where)
        records.append(value)
    return records


def write_json(path: Path, value: Mapping[str, Any], *, kind: str | None = None) -> None:
    """Validate (when ``kind`` is given) and atomically write one sorted JSON document."""
    if kind is not None:
        validate_record(kind, value, where=path.name)
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def write_jsonl(
    path: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    kind: str | None = None,
    sort_key: str | None = None,
) -> None:
    """Validate and atomically write JSONL, one canonical record per line, in deterministic order."""
    rows = [dict(record) for record in records]
    for index, record in enumerate(rows, 1):
        if kind is not None:
            validate_record(kind, record, where=f"{path.name} record {index}")
    if sort_key is not None:
        rows.sort(key=lambda record: str(record[sort_key]))
    atomic_write_text(path, "".join(canonical_json(record) + "\n" for record in rows))
