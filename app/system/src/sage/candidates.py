"""Deterministic candidates the model adjudicates (CONFIRM, REJECT, or UNSURE) in RTC and STC.

Code finds differences it cannot judge on its own: \\add and \\nd usage, digits that disagree with the
number index, numbers written in words, and (STC) verses far shorter or longer than their OL text. Each
becomes one candidate with a stable ID; the model returns one adjudication per candidate, and a CONFIRM
points at the finding that reports it.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

VERDICTS = ("CONFIRM", "REJECT", "UNSURE")


def _ref_key(reference: str) -> str:
    """Compact a reference for use inside a candidate ID."""
    return str(reference).replace(" ", "")


def candidate_inventory(
    *,
    markers: Iterable[Mapping[str, Any]] = (),
    numeric: Mapping[str, Any] | None = None,
    lengths: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build the task's candidate list with stable IDs from the deterministic checks."""
    rows: list[dict[str, Any]] = []
    for row in markers:
        reference = str(row.get("target_reference") or "")
        marker = str(row.get("marker") or "")
        rows.append(
            {
                "candidate_id": f"MC-{_ref_key(reference)}-{marker}",
                "kind": "MARKER",
                "target_reference": reference,
                "question": (
                    f"The WIP uses \\{marker} {row.get('wip_count')} time(s), the REFERENCE "
                    f"{row.get('reference_count')} time(s). Is the difference material?"
                ),
            }
        )
    for row in (numeric or {}).get("rows", []) if numeric else []:
        if row.get("status") == "MATCH":
            continue
        reference = str(row.get("reference") or "")
        rows.append(
            {
                "candidate_id": f"NC-{_ref_key(reference)}",
                "kind": "NUMBER",
                "target_reference": reference,
                "question": (
                    f"Number index values {', '.join(row.get('index_values') or []) or 'none'}; WIP digits "
                    f"{', '.join(row.get('wip_digit_values') or []) or 'none'} ({row.get('status')}). "
                    "Does the WIP render the numbers correctly?"
                ),
            }
        )
    for row in lengths:
        reference = str(row.get("wip_reference") or "")
        rows.append(
            {
                "candidate_id": f"LC-{_ref_key(reference)}",
                "kind": "LENGTH",
                "target_reference": reference,
                "question": (
                    f"The WIP verse is unusually {'short' if row.get('direction') == 'SHORT' else 'long'} "
                    f"for its original-language text ({row.get('relative_length')}x the book's usual ratio). "
                    "Is something omitted or added?"
                ),
            }
        )
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(row["candidate_id"], row)
    return list(unique.values())


def adjudication_schema(inventory: Sequence[Mapping[str, Any]], rationale: Mapping[str, Any]) -> dict[str, Any]:
    """Return the response schema for one adjudication per listed candidate."""
    ids = [str(row["candidate_id"]) for row in inventory]
    return {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["candidate_id", "verdict", "finding_id", "rationale"],
            "properties": {
                "candidate_id": {"type": "string", **({"enum": ids} if ids else {})},
                "verdict": {"type": "string", "enum": list(VERDICTS)},
                "finding_id": {
                    "type": ["string", "null"],
                    "description": "For CONFIRM, the finding_id of the finding that reports the issue; otherwise null.",
                },
                "rationale": dict(rationale),
            },
        },
    }


def reconcile_adjudications(
    raw: Any,
    inventory: Sequence[Mapping[str, Any]],
    finding_ids: Iterable[str],
    *,
    code_prefix: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return one adjudication per candidate plus records for every defect corrected on the way.

    Unknown or repeated candidate IDs are dropped, a CONFIRM without a reported finding becomes UNSURE,
    and a candidate the model did not adjudicate is recorded as UNSURE.
    """
    known = {str(row["candidate_id"]): row for row in inventory}
    findings = {str(value) for value in finding_ids}
    records: list[dict[str, Any]] = []
    result: dict[str, dict[str, Any]] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        if candidate_id not in known or candidate_id in result:
            records.append(
                {
                    "code": f"{code_prefix}_CANDIDATE_ADJUDICATION_DROPPED",
                    "coordinate": str(known.get(candidate_id, {}).get("target_reference") or ""),
                    "submitted_id": candidate_id,
                    "effect": "FLAGGED",
                    "message": f"Adjudication for unknown or repeated candidate {candidate_id or '(none)'} was dropped.",
                }
            )
            continue
        verdict = str(item.get("verdict") or "").upper()
        finding_id = str(item.get("finding_id") or "") or None
        if verdict not in VERDICTS:
            verdict = "UNSURE"
        if verdict == "CONFIRM" and finding_id not in findings:
            records.append(
                {
                    "code": f"{code_prefix}_CANDIDATE_CONFIRM_UNREPORTED",
                    "coordinate": str(known[candidate_id].get("target_reference") or ""),
                    "submitted_id": candidate_id,
                    "effect": "CORRECTED",
                    "message": f"Candidate {candidate_id} was confirmed without a reported finding; it is recorded as UNSURE.",
                }
            )
            verdict, finding_id = "UNSURE", None
        result[candidate_id] = {
            "candidate_id": candidate_id,
            "kind": known[candidate_id].get("kind"),
            "target_reference": known[candidate_id].get("target_reference"),
            "verdict": verdict,
            "finding_id": finding_id if verdict == "CONFIRM" else None,
            "rationale": str(item.get("rationale") or "").strip(),
        }
    for candidate_id, row in known.items():
        if candidate_id not in result:
            records.append(
                {
                    "code": f"{code_prefix}_CANDIDATE_NOT_ADJUDICATED",
                    "coordinate": str(row.get("target_reference") or ""),
                    "submitted_id": candidate_id,
                    "effect": "FLAGGED",
                    "message": f"Candidate {candidate_id} was not adjudicated; it is recorded as UNSURE for review.",
                }
            )
            result[candidate_id] = {
                "candidate_id": candidate_id,
                "kind": row.get("kind"),
                "target_reference": row.get("target_reference"),
                "verdict": "UNSURE",
                "finding_id": None,
                "rationale": "",
            }
    return [result[str(row["candidate_id"])] for row in inventory], records
