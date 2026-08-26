"""SAW finding identity, lookup, context, and VRS-aware reference controls."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping

from .errors import ValidationError
from .references import parse_scope_set
from .vrs import VerseRef, VersificationSchema

_ID_PART_RE = re.compile(r"[^A-Z0-9]+")


def _id_part(value: str, *, maximum: int = 24) -> str:
    """Return a compact deterministic token without truncation collisions."""
    raw = value.strip()
    normalized = _ID_PART_RE.sub("-", raw.upper()).strip("-") or "X"
    if len(normalized) <= maximum:
        return normalized
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8].upper()
    if maximum <= len(digest):
        return digest[:maximum]
    prefix_length = maximum - len(digest) - 1
    return f"{normalized[:prefix_length]}-{digest}"


def _without_redundant_prefix(value: str, prefix: str) -> str:
    """Remove one repeated top-level workflow prefix from a derived ID component."""
    raw = value.strip()
    marker = prefix.strip().upper()
    upper = raw.upper()
    for separator in ("_", "-"):
        token = f"{marker}{separator}"
        if upper.startswith(token):
            return raw[len(token):]
    return raw


def assign_global_finding_ids(
    findings_by_unit: Mapping[str, Iterable[dict[str, Any]]],
    *,
    run_id: str,
    prefix: str = "TR",
) -> list[dict[str, Any]]:
    """Assign deterministic run-global IDs without trusting model-local IDs.

    Composite ITEM identifiers use underscore between hierarchy levels and hyphen
    inside compact components. Repeated workflow prefixes already present in Run
    or work-unit identifiers are removed before assembly.
    """
    result: list[dict[str, Any]] = []
    prefix_key = _id_part(prefix, maximum=8)
    run_key = _id_part(_without_redundant_prefix(run_id, prefix_key), maximum=18)
    for unit_id in sorted(findings_by_unit):
        unit_key = _id_part(
            _without_redundant_prefix(unit_id, prefix_key),
            maximum=18,
        )
        for sequence, submitted in enumerate(findings_by_unit[unit_id], start=1):
            if not isinstance(submitted, dict):
                raise ValidationError(f"Finding in {unit_id} is not a mapping")
            row = dict(submitted)
            if row.get("finding_id") and not row.get("submitted_id"):
                row["submitted_id"] = str(row.pop("finding_id"))
            row["finding_id"] = (
                f"{prefix_key}_{run_key}_{unit_key}_{sequence:04d}"
            )
            row["work_unit_id"] = unit_id
            result.append(row)
    validate_global_finding_ids(result)
    return result



def globalize_result_finding_ids(
    result: Mapping[str, Any],
    *,
    unit_id: str,
    run_id: str,
    prefix: str = "TR",
) -> dict[str, Any]:
    """Assign run-global finding IDs to one task/stage result and remap local references.

    Provider finding IDs are task-local handles. They may repeat across work units (for
    example, every unit may legitimately return ``F001``). At an aggregation boundary
    SAGE owns identity: findings receive deterministic run-global IDs while the original
    provider handle is retained as ``submitted_id``. Any structured references to a
    finding inside the same result are rewritten to the same global ID.
    """
    value = dict(result)
    raw_findings = value.get("findings", [])
    if not isinstance(raw_findings, list) or any(not isinstance(row, dict) for row in raw_findings):
        raise ValidationError("Result findings must be a list of mappings")
    current_ids = [str(row.get("finding_id", "")).strip() for row in raw_findings]
    if any(not finding_id for finding_id in current_ids):
        raise ValidationError("Result finding is missing its local finding_id")
    if len(current_ids) != len(set(current_ids)):
        raise ValidationError("Duplicate local finding_id inside one work unit")

    assigned = assign_global_finding_ids(
        {unit_id: [dict(row) for row in raw_findings]},
        run_id=run_id,
        prefix=prefix,
    )
    remap = {old: str(new["finding_id"]) for old, new in zip(current_ids, assigned)}

    def _remap_rows(field: str) -> list[dict[str, Any]]:
        """Remap one structured finding-reference ledger to run-global IDs."""
        raw_rows = value.get(field, [])
        if not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows):
            raise ValidationError(f"Result {field} must be a list of mappings")
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            row = dict(raw)
            raw_id = row.get("finding_id")
            local_id = str(raw_id).strip() if raw_id not in (None, "") else ""
            if local_id:
                if local_id not in remap:
                    raise ValidationError(
                        f"{field} refers to finding_id not present in the same result: {local_id}"
                    )
                row["finding_id"] = remap[local_id]
            rows.append(row)
        return rows

    value["findings"] = assigned
    value["finding_count"] = len(assigned)
    value["structural_adjudications"] = _remap_rows("structural_adjudications")
    value["ol_resolutions"] = _remap_rows("ol_resolutions")
    return value

def validate_global_finding_ids(findings: Iterable[dict[str, Any]]) -> None:
    """Require one nonempty unique global ID for every normalized finding."""
    seen: set[str] = set()
    for row in findings:
        finding_id = str(row.get("finding_id", "")).strip()
        if not finding_id:
            raise ValidationError("Finding is missing its global finding_id")
        if finding_id in seen:
            raise ValidationError(f"Duplicate global finding ID: {finding_id}")
        seen.add(finding_id)


def resolve_finding(
    findings: Iterable[dict[str, Any]],
    identifier: str,
    *,
    parent_scope: str | None = None,
) -> dict[str, Any]:
    """Resolve exactly one global or submitted ID and block ambiguous lookups."""
    rows = list(findings)
    exact = [row for row in rows if str(row.get("finding_id", "")) == identifier]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValidationError(f"AMBIGUOUS_FINDING_ID: {identifier}")
    submitted = [row for row in rows if str(row.get("submitted_id", "")) == identifier]
    if parent_scope is not None:
        submitted = [
            row for row in submitted if str(row.get("parent_scope", "")) == parent_scope
        ]
    if len(submitted) == 1:
        return submitted[0]
    if len(submitted) > 1:
        raise ValidationError(f"AMBIGUOUS_FINDING_ID: {identifier}")
    raise ValidationError(f"FINDING_ID_NOT_FOUND: {identifier}")


def _local_refs(value: str, schema: VersificationSchema) -> frozenset[VerseRef]:
    """Expand one or more submitted local citation portions under a resource VRS schema."""
    refs: set[VerseRef] = set()
    for scope in parse_scope_set(value):
        chapters = schema.chapter_max.get(scope.book, {})
        for chapter, maximum in sorted(chapters.items()):
            for verse in range(1, maximum + 1):
                ref = VerseRef(scope.book, chapter, verse)
                if scope.contains(ref):
                    refs.add(ref)
    if not refs:
        raise ValidationError(
            f"Reference {value!r} is empty under VRS schema {schema.schema_id}"
        )
    return frozenset(refs)


def reference_is_authorized(
    local_reference: str,
    *,
    schema: VersificationSchema,
    authorized_canonical: frozenset[VerseRef],
) -> bool:
    """Authorize a resource-local citation through its effective VRS schema."""
    local_refs = _local_refs(local_reference, schema)
    canonical = schema.canonical_set(local_refs)
    return bool(canonical) and canonical.issubset(authorized_canonical)


def validate_finding_references(
    finding: Mapping[str, Any],
    *,
    target_schema: VersificationSchema,
    resource_schemas: Mapping[str, VersificationSchema],
    primary_target_refs: frozenset[VerseRef],
    context_target_refs: frozenset[VerseRef] = frozenset(),
) -> None:
    """Validate TARGET and non-TARGET references against one equivalence group."""
    target_reference = str(finding.get("target_reference", "")).strip()
    if not target_reference:
        raise ValidationError("Finding target_reference is required")
    target_local = _local_refs(target_reference, target_schema)
    if not target_local.issubset(primary_target_refs):
        if target_local.intersection(context_target_refs):
            raise ValidationError(
                "Finding may not target a CONTEXT_ONLY coordinate without a primary boundary finding"
            )
        raise ValidationError("Finding target_reference is outside the primary TARGET scope")
    # Non-TARGET citations must belong to this finding's own TARGET equivalence
    # span, not merely somewhere else in the same work unit.
    authorized_canonical = target_schema.canonical_set(target_local)
    field_roles = {
        "reference_reference": "REFERENCE",
        "greek_reference": "ORIGINAL_LANGUAGE_GREEK",
        "hebrew_reference": "ORIGINAL_LANGUAGE_HEBREW",
    }
    for field, role in field_roles.items():
        value = str(finding.get(field, "")).strip()
        if not value:
            continue
        try:
            schema = resource_schemas[role]
        except KeyError as exc:
            raise ValidationError(f"No VRS schema is available for role {role}") from exc
        if not reference_is_authorized(
            value,
            schema=schema,
            authorized_canonical=authorized_canonical,
        ):
            raise ValidationError(
                f"{field} is not authorized by the primary canonical equivalence group"
            )
