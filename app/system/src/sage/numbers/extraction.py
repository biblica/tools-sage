"""Build bounded NCA extraction requests and validate exact model evidence.

Contract 3.0: a work unit's response lists its numbers in reading order, each with its
exact text in the verse, its value (canonical rational string), its convention kind, what it
counts (target language and an English gloss), plus honest completeness. SAGE verifies each
text against the verse and reads digit numerals itself (numbers/numerals.py). Comparison
against the indexed expected values happens later, locally, in numbers/compare.py --
extraction never sees the expected values.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Any, Mapping

from sage.errors import ValidationError

from .batching import ExtractionBatch
from .transport import _digest
from .models import (
    freeze,
    MODEL_EXTRACTION_STATUSES,
    VALUE_KINDS,
    Extraction,
)


_RATIONAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$")
_PARSING_FIELDS: dict[str, frozenset[str]] = {
    "digits": frozenset({"preferred", "allowed"}),
    "grouping": frozenset({"style", "separator"}),
    "decimal": frozenset({"separator"}),
    "fractions": frozenset({"notation", "forms"}),
    "ranges": frozenset({"separator"}),
    "ordinals": frozenset({"form", "suffixes"}),
    "qualifiers": frozenset({"forms"}),
}
# Unit forms live per location in style profiles (rules.units.locations.<where>.forms).
_UNIT_LOCATIONS = ("body", "heading", "footnote")


def _error(message: str, *, code: str) -> ValidationError:
    """Build one stable NCA extraction validation error."""
    return ValidationError(message, code=code)


def _require_object(value: object, label: str, *, code: str) -> Mapping[str, Any]:
    """Require one string-keyed response mapping."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _error(f"{label} must be an object", code=code)
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
    code: str,
) -> None:
    """Reject missing and invented structured-response fields."""
    keys = set(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise _error(f"{label} has " + "; ".join(details), code=code)


def _require_list(value: object, label: str, *, code: str) -> list[Any]:
    """Require one JSON array without accepting tuple aliases."""
    if not isinstance(value, list):
        raise _error(f"{label} must be an array", code=code)
    return value


def _require_text(value: object, label: str, *, allow_empty: bool = False) -> str:
    """Require one response string and optionally reject blank evidence."""
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _error(f"{label} must be a non-empty string", code="NCA_EXTRACTION_SCHEMA_INVALID")
    return value


def _fraction(value: object, label: str) -> Fraction:
    """Parse one canonical reduced rational string without float conversion."""
    if not isinstance(value, str) or not _RATIONAL.fullmatch(value):
        raise _error(
            f"{label} must be a canonical rational string",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        )
    try:
        parsed = Fraction(value)
        canonical = str(parsed)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise _error(
            f"{label} cannot be represented as an exact rational",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        ) from exc
    if canonical != value:
        raise _error(
            f"{label} must be reduced and normalized",
            code="NCA_EXTRACTION_EVIDENCE_INVALID",
        )
    return parsed


def _safe_convention_value(value: object) -> object:
    """Copy only inert JSON-like convention data from an already validated profile."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_convention_value(item) for item in value]
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {str(key): _safe_convention_value(item) for key, item in value.items()}
    raise _error(
        "Style parsing conventions contain an unsupported value",
        code="NCA_EXTRACTION_PAYLOAD_INVALID",
    )


def _parsing_conventions(style_profile: Mapping[str, object]) -> dict[str, object]:
    """Select only fields that help interpret numeric surface notation."""
    rules = style_profile.get("rules", {})
    if not isinstance(rules, Mapping):
        return {}
    result: dict[str, object] = {}
    for area, allowed in _PARSING_FIELDS.items():
        raw = rules.get(area)
        if not isinstance(raw, Mapping) or raw.get("status") == "NOT_SPECIFIED":
            continue  # an unspecified rule says nothing about how this text writes numbers
        selected = {
            field: _safe_convention_value(raw[field])
            for field in sorted(allowed)
            if field in raw
        }
        if selected:
            result[area] = selected
    units = rules.get("units")
    locations = units.get("locations") if isinstance(units, Mapping) else None
    if isinstance(locations, Mapping):
        forms: dict[str, list[str]] = {}
        for where in _UNIT_LOCATIONS:
            location = locations.get(where)
            if isinstance(location, Mapping) and location.get("status") == "CONFIGURED":
                for unit, labels in (location.get("forms") or {}).items():
                    merged = forms.setdefault(str(unit), [])
                    merged.extend(label for label in _safe_convention_value(labels) if label not in merged)
        if forms:
            result["units"] = {"forms": {unit: forms[unit] for unit in sorted(forms)}}
    elif isinstance(units, Mapping) and isinstance(units.get("forms"), Mapping):
        # already-selected conventions (a second pass must reproduce the same selection)
        result["units"] = {"forms": _safe_convention_value(units["forms"])}
    return result


def _surface_at(text: str, surface: str, cursor: int, taken: list[tuple[int, int]]) -> int:
    """Where a number's text stands in its verse, or -1.

    The match must be a whole token (a "7" inside "17" or "seven" inside "seventy" is not the
    number) and must not overlap a number already placed; the first such match at or after the
    previous number wins, else the first anywhere (the model listed numbers out of order),
    else the very token of an earlier number (listed twice).
    """
    def whole(start: int) -> bool:
        """Whether the match at ``start`` is a whole token, not part of a longer word or numeral."""
        end = start + len(surface)
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        return not ((before.isalnum() and surface[0].isalnum()) or (after.isalnum() and surface[-1].isalnum())
                    or (before in ",." and start > 1 and text[start - 2].isdigit() and surface[0].isdigit())
                    or (after in ",." and end + 1 < len(text) and text[end + 1].isdigit() and surface[-1].isdigit()))

    spaces = {"\u00a0": " ", "\u202f": " ", "\u2009": " "}
    # same length, so offsets still hold
    text, surface = ("".join(spaces.get(char, char) for char in value) for value in (text, surface))
    found = [match.start() for match in re.finditer(re.escape(surface), text)]
    tokens = [start for start in found if whole(start)]
    free = [start for start in tokens
            if not any(start < end and begin < start + len(surface) for begin, end in taken)]
    # last resort: the same token again (the model listed it twice), never a partial overlap
    again = [start for start in tokens if (start, start + len(surface)) in taken]
    return next((start for start in free if start >= cursor), free[0] if free else again[0] if again else -1)


_NUMBER_FIELDS = frozenset({"text", "value", "kind", "counts", "counts_en"})


def _validated_extraction_item(raw: Mapping[str, Any], text: str = "",
                               conventions: Mapping[str, object] | None = None) -> Extraction:
    """Validate one work unit's numbers against its own text, then read its digit numerals locally.

    Each number's ``text`` must occur in the work unit at or after the previous number (reading
    order); a number whose text is not there is dropped with a limitation. A number that is a
    digit numeral takes SAGE's own reading (``NUMERAL_VALUE_DIFFERS`` when the model read it
    otherwise); a digit numeral the model did not return is added (origin ``LOCAL``); a numeral
    with no well-formed reading is a ``MALFORMED_NUMERAL`` issue.
    """
    from .numerals import find_numerals
    status = _require_text(raw["status"], "status")
    if status not in MODEL_EXTRACTION_STATUSES:
        raise _error("Extraction status is unsupported", code="NCA_EXTRACTION_SCHEMA_INVALID")
    limitations = list(
        _require_text(value, f"limitations[{index}]")
        for index, value in enumerate(
            _require_list(raw["limitations"], "limitations", code="NCA_EXTRACTION_SCHEMA_INVALID")
        )
    )
    if status != "COMPLETE" and not limitations:
        raise _error("Incomplete extraction must state a limitation", code="NCA_EXTRACTION_SCHEMA_INVALID")
    numbers = _require_list(raw["numbers"], "numbers", code="NCA_EXTRACTION_SCHEMA_INVALID")
    rows: list[dict[str, object]] = []
    cursor = 0
    for index, item in enumerate(numbers):
        item = _require_object(item, f"numbers[{index}]", code="NCA_EXTRACTION_SCHEMA_INVALID")
        _require_exact_keys(item, required=_NUMBER_FIELDS, label=f"numbers[{index}]",
                            code="NCA_EXTRACTION_SCHEMA_INVALID")
        if not isinstance(item["kind"], str) or item["kind"] not in VALUE_KINDS:
            raise _error("Extraction kinds must name one convention kind per value",
                         code="NCA_EXTRACTION_SCHEMA_INVALID")
        surface = _require_text(item["text"], f"numbers[{index}].text")
        counts = _require_text(item["counts"], f"numbers[{index}].counts", allow_empty=True)
        counts_en = _require_text(item["counts_en"], f"numbers[{index}].counts_en", allow_empty=True)
        try:
            value = _fraction(item["value"], f"numbers[{index}].value")
        except ValidationError:
            limitations.append(f"NCA_VALUE_MALFORMED: {item['value']!r}")
            status = "PARTIAL"
            continue
        start = _surface_at(text, surface, cursor, [row["span"] for row in rows]) if text else -1
        if text and start < 0:
            limitations.append(f"NCA_SURFACE_NOT_IN_TEXT: {surface!r}")
            status = "PARTIAL"
            continue
        if start >= 0:
            cursor = start + len(surface)
        rows.append({"value": value, "kind": item["kind"], "surface": surface,
                     "span": (start, start + len(surface)) if start >= 0 else (0, 0),
                     "counts": counts, "counts_en": counts_en, "origin": "MODEL"})
    issues: list[str] = []
    if text:
        for numeral in find_numerals(text, conventions):
            if numeral.malformed:
                issues.append(f"MALFORMED_NUMERAL:{numeral.text}")
            owner = next((row for row in rows if row["span"][0] <= numeral.start and numeral.end <= row["span"][1]),
                         None)
            if owner is None:
                if not numeral.malformed:
                    # a suffixed digit numeral ("2nd") is an ordinal: a convention edge case
                    rows.append({"value": numeral.readings[0], "kind": "ORDINAL" if numeral.suffixed else "CARDINAL",
                                 "surface": numeral.text,
                                 "span": (numeral.start, numeral.end), "counts": "", "counts_en": "",
                                 "origin": "LOCAL"})
                continue
            if owner["span"] == (numeral.start, numeral.end) and numeral.readings \
                    and owner["value"] not in numeral.readings:
                issues.append(f"NUMERAL_VALUE_DIFFERS:{numeral.text}:model={owner['value']}")
                owner["value"] = numeral.readings[0]
        rows.sort(key=lambda row: row["span"])
    return Extraction(
        values=tuple(row["value"] for row in rows), status=status, limitations=tuple(limitations),
        kinds=tuple(row["kind"] for row in rows), surfaces=tuple(row["surface"] for row in rows),
        spans=tuple(row["span"] for row in rows), counts=tuple(row["counts"] for row in rows),
        counts_en=tuple(row["counts_en"] for row in rows), origins=tuple(row["origin"] for row in rows),
        issues=tuple(issues))


@dataclass(frozen=True)
class BatchValidation:
    """Independently admitted members with controller-owned response item hashes."""

    accepted: Mapping[str, Extraction]
    pending: Mapping[str, str]
    batch_id: str
    item_sha256: Mapping[str, str]

    def __post_init__(self) -> None:
        """Own immutable results and require disjoint, fully hashed accepted membership."""
        if (not isinstance(self.batch_id, str) or not self.batch_id
                or not isinstance(self.accepted, Mapping) or not isinstance(self.pending, Mapping)
                or not isinstance(self.item_sha256, Mapping)
                or set(self.accepted).intersection(self.pending)
                or set(self.item_sha256) != set(self.accepted)
                or any(not isinstance(key, str) or not key for key in (*self.accepted, *self.pending))
                or any(not isinstance(value, Extraction) for value in self.accepted.values())
                or any(not isinstance(value, str) or not value for value in self.pending.values())
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in self.item_sha256.values())):
            raise _error("Invalid batch validation binding", code="NCA_BATCH_COVERAGE_INVALID")
        for field in ("accepted", "pending", "item_sha256"):
            object.__setattr__(self, field, freeze(getattr(self, field)))


def local_input_id(position: int) -> str:
    """Batch-local model-facing ID for the input at one 0-based batch position.

    Controller input IDs are 70-character hashes the model must echo; short positional IDs
    keep request and response size proportional to the verses, not to their identities.
    """
    return f"u{position + 1}"


def build_batch_extraction_payload(
    batch: ExtractionBatch, *, parsing_conventions: Mapping[str, object],
) -> Mapping[str, object]:
    """Send only the visible target text of each stream, with batch-local IDs and conventions.

    Raw routed SFM is not sent: it repeats each verse and carries verse numbers, note callers
    and cross-references the convention says never to count.
    """
    if not isinstance(batch, ExtractionBatch) or not isinstance(parsing_conventions, Mapping):
        raise _error("Invalid batch extraction input", code="NCA_EXTRACTION_PAYLOAD_INVALID")
    conventions = _parsing_conventions({"rules": parsing_conventions})
    if (any(value.conventions_sha256 != _digest(conventions) for value in batch.inputs)
            or len({(value.language, value.purpose) for value in batch.inputs}) != 1):
        raise _error("Batch extraction conventions differ", code="NCA_EXTRACTION_PAYLOAD_INVALID")
    return {
        "schema_version": "1.0", "phase": "EXTRACTION", "batch_id": batch.batch_id,
        "language": batch.inputs[0].language,
        "work_units": [{"input_id": local_input_id(position), "text": value.text}
                       for position, value in enumerate(batch.inputs)],
        "parsing_conventions": conventions,
        "output_schema_id": "sage-nca-extraction-3.0#extraction",
    }


def validate_batch_extraction_response(
    batch: ExtractionBatch, response: Mapping[str, object], *,
    parsing_conventions: Mapping[str, object] | None = None,
) -> BatchValidation:
    """Reconcile envelope identities first, then validate known members independently."""
    code = "NCA_EXTRACTION_SCHEMA_INVALID"
    coverage = "NCA_BATCH_COVERAGE_INVALID"
    if not isinstance(batch, ExtractionBatch):
        raise _error("Invalid extraction batch", code=coverage)
    root = _require_object(response, "response", code=code)
    _require_exact_keys(root, required=frozenset({"schema_version", "phase", "batch_id", "work_units"}),
                        label="response", code=code)
    if root["schema_version"] != "1.0" or root["phase"] != "EXTRACTION":
        raise _error("Extraction response identity is invalid", code=code)
    if root["batch_id"] != batch.batch_id:
        raise _error("Invalid batch identities", code=coverage)
    rows = _require_list(root["work_units"], "work_units", code=code)
    controller_ids = {local_input_id(position): value.input_id for position, value in enumerate(batch.inputs)}
    received = []
    for row in rows:
        item = _require_object(row, "work unit", code=coverage)
        if not isinstance(item.get("input_id"), str) or item["input_id"] not in controller_ids:
            raise _error("Invalid batch identities", code=coverage)
        received.append(controller_ids[item["input_id"]])
    expected = {item.input_id for item in batch.inputs}
    if len(received) != len(set(received)) or set(received) - expected:
        raise _error("Invalid batch identities", code=coverage)
    by_id = dict(zip(received, rows))
    accepted, pending, hashes = {}, {}, {}
    for value in batch.inputs:
        raw = by_id.get(value.input_id)
        if raw is None:
            pending[value.input_id] = "NCA_BATCH_INPUT_MISSING"
            continue
        try:
            _require_exact_keys(raw, required=frozenset({"input_id", "status", "limitations", "numbers"}),
                                label="work unit", code=code)
            accepted[value.input_id] = _validated_extraction_item(raw, value.text, parsing_conventions)
        except ValidationError as exc:
            pending[value.input_id] = str(exc.code)
            continue
        hashes[value.input_id] = _digest({"batch_id": batch.batch_id, "input_id": value.input_id,
                                         "projection_sha256": value.projection_sha256, "item": raw})
    return BatchValidation(accepted, pending, batch.batch_id, hashes)
