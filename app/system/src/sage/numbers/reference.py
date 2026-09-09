"""Validate and load immutable NCA operator reference packages."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from sage.errors import ValidationError
from sage.references import BOOK_ORDER
from sage.vrs import VerseRef, parse_vrs_file

from .models import ReferenceBundle, ReferenceRow


REFERENCE_PARSER_VERSION = "1.0"
_VALUE_RE = re.compile(r"(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PRIMARY_FIELDS = frozenset(
    {"BK", "CH", "VS", "OL_REF", "LANG", "OL_TEXT", "OL_VALUES", "NIV_TEXT", "NIV_VALUES"}
)
_REQUIRED_COLUMNS: Mapping[str, frozenset[str]] = {
    "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv": _PRIMARY_FIELDS
    | frozenset(
        {
            "MATCH_STATUS",
            "VARIANT_CLASS",
            "SCHOLARSHIP_STATUS",
            "TARGET_DEFAULT",
            "TARGET_VALIDATION_RULE",
            "ALT_READING_STATUS",
            "FOOTNOTE_IF_TARGET_FOLLOWS_OL",
            "FOOTNOTE_IF_TARGET_FOLLOWS_ALT",
            "OPERATOR_GUIDANCE",
            "TEXTUAL_CRITICAL_NOTE",
            "SOURCE_IDS",
            "SOURCE_URLS",
        }
    ),
    "canonical_number_index.tsv": _PRIMARY_FIELDS
    | frozenset(
        {"AUTHORITY_BASIS", "MATCH_STATUS", "VARIANT_CLASS", "SCHOLARSHIP_STATUS", "TEXTUAL_CRITICAL_NOTE"}
    ),
    "textual_variant_registry.tsv": frozenset(
        {
            "BK", "CH", "VS", "OL_REF", "CLASS", "NIV_FOOTNOTE", "MANUSCRIPT_EVIDENCE",
            "CRITICAL_TEXT_POSITION", "MAJORITY_SCHOLARSHIP_POSITION", "SCHOLARSHIP_STATUS",
            "OL_VALUE_RESEARCHED", "NIV_VALUE_RESEARCHED", "APOLOGETIC_SUMMARY",
            "TEXTUAL_CRITICAL_NOTE", "SOURCE_IDS",
        }
    ),
    "footnote_guidance.tsv": frozenset(
        {
            "BK", "CH", "VS", "OL_REF", "OL_VALUES", "ALT_NIV_VALUES", "CLASS",
            "SCHOLARSHIP_STATUS", "FOOTNOTE_IF_TARGET_FOLLOWS_OL",
            "FOOTNOTE_IF_TARGET_FOLLOWS_ALT", "VALIDATION_IF_TARGET_FOLLOWS_OL",
            "VALIDATION_IF_TARGET_FOLLOWS_ALT", "SUGGESTED_NOTE_IF_OL_SELECTED",
            "SUGGESTED_NOTE_IF_ALT_SELECTED", "MANUSCRIPT_EVIDENCE", "SCHOLARSHIP_POSITION",
            "NIV_FOOTNOTE", "SOURCE_IDS", "SOURCE_URLS",
        }
    ),
    "unit_conversion_registry.tsv": frozenset(
        {
            "BK", "CH", "VS", "REF", "LANG", "OL_TEXT", "OL_QUANTITY", "NIV_TEXT",
            "NIV_QUANTITY", "CLASS", "SCHOLARSHIP_STATUS", "NOTE", "SOURCE_IDS",
        }
    ),
    "ol_expression_audit.tsv": frozenset(
        {"OL_REF", "LANG", "EXPR_NO", "TOKEN_POS", "SOURCE_EXPRESSION", "DIGIT_VALUE", "ORIGIN", "OL_TEXT"}
    ),
    "normalization_overrides.tsv": frozenset(
        {
            "LAYER", "BK", "CH", "VS", "OL_REF", "LANG", "ACTION", "EXPR_NO", "TOKEN_POS",
            "SOURCE_EXPRESSION", "ORIGINAL_VALUES", "FINAL_VALUES", "RULE_CLASS", "REASON", "REVIEW_STATUS",
        }
    ),
    "ol_token_coverage_audit.tsv": frozenset(
        {
            "BK", "CH", "VS", "OL_REF", "LANG", "TOKEN_NO", "TOKEN", "CANON_TOKEN", "ATOM_VALUE",
            "ATOM_TYPE", "STATUS", "REASON", "SEED_LEXEME_OCCURRENCES", "OL_TEXT", "COVERAGE_CLASS",
            "SEMANTIC_VALUE", "AUDIT_REASON",
        }
    ),
    "provenance_sources.tsv": frozenset(
        {"SOURCE_ID", "AUTHOR_OR_ORGANIZATION", "TITLE", "DATE_OR_EDITION", "URL", "ACCESS_NOTE", "EVIDENCE_USED"}
    ),
}
_COUNT_FIELDS = {
    "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv": "operator_index_rows",
    "textual_variant_registry.tsv": "critical_rows",
    "footnote_guidance.tsv": "footnote_guidance_rows",
    "unit_conversion_registry.tsv": "unit_conversion_rows",
    "ol_expression_audit.tsv": "ol_expression_rows",
    "normalization_overrides.tsv": "normalization_override_rows",
    "ol_token_coverage_audit.tsv": "ol_token_coverage_rows",
    "provenance_sources.tsv": "provenance_source_rows",
}
_NUMERIC_COLUMNS = {
    "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv": ("OL_VALUES", "NIV_VALUES"),
    "canonical_number_index.tsv": ("OL_VALUES", "NIV_VALUES"),
    "footnote_guidance.tsv": ("OL_VALUES", "ALT_NIV_VALUES"),
    "textual_variant_registry.tsv": ("OL_VALUE_RESEARCHED", "NIV_VALUE_RESEARCHED"),
    "ol_expression_audit.tsv": ("DIGIT_VALUE",),
}


def _reference_error(message: str, code: str, **details: object) -> ValidationError:
    """Build one stable reference-contract validation error."""
    return ValidationError(message, code=code, details=dict(details))


def parse_values(raw: str) -> tuple[Fraction, ...]:
    """Parse the package's canonical semicolon-separated reduced rational encoding."""
    if not isinstance(raw, str):
        raise _reference_error(
            "NCA numeric values must be encoded as text",
            "NCA_REFERENCE_ENCODING_INVALID",
            value=repr(raw),
        )
    if raw == "":
        return ()
    values: list[Fraction] = []
    for token in raw.split(";"):
        if not _VALUE_RE.fullmatch(token):
            raise _reference_error(
                f"Unsupported NCA numeric encoding: {token!r}",
                "NCA_REFERENCE_ENCODING_INVALID",
                value=raw,
            )
        value = Fraction(token)
        if str(value) != token:
            raise _reference_error(
                f"NCA numeric encoding is not reduced: {token!r}",
                "NCA_REFERENCE_ENCODING_INVALID",
                value=raw,
            )
        values.append(value)
    return tuple(values)


def normalize_footnote_action(raw: str) -> str:
    """Normalize literal no-action aliases while rejecting unknown policy actions."""
    aliases = {"NONE": "NONE", "NONE_TEXT_CRITICAL": "NONE", "N/A": "NONE"}
    if raw in aliases:
        return aliases[raw]
    if raw in {"RECOMMEND", "REQUIRE"}:
        return raw
    raise _reference_error(
        f"Unsupported NCA footnote action: {raw!r}",
        "NCA_REFERENCE_CONTRACT_CONFLICT",
        value=raw,
    )


def _safe_relative(raw: str) -> str:
    """Return a normalized package-relative POSIX path or reject it."""
    value = raw[2:] if raw.startswith("./") else raw
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise _reference_error(
            f"Unsafe NCA package path: {raw!r}",
            "NCA_REFERENCE_MANIFEST_INVALID",
            path=raw,
        )
    normalized = path.as_posix()
    if normalized in {".", ""}:
        raise _reference_error(
            f"Unsafe NCA package path: {raw!r}",
            "NCA_REFERENCE_MANIFEST_INVALID",
            path=raw,
        )
    return normalized


def _json_object(path: Path) -> dict[str, Any]:
    """Read one strict UTF-8 JSON object from the package."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _reference_error(
            f"Invalid NCA JSON file {path.name}: {exc}",
            "NCA_REFERENCE_MANIFEST_INVALID",
            path=str(path),
        ) from exc
    if not isinstance(raw, dict):
        raise _reference_error(
            f"NCA JSON file must contain an object: {path.name}",
            "NCA_REFERENCE_MANIFEST_INVALID",
            path=str(path),
        )
    return raw


def _verify_inventory(root: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Verify the complete checksum and file-manifest inventories before parsing data."""
    if not root.is_dir() or root.is_symlink():
        raise _reference_error(
            f"NCA reference root is unavailable or unsafe: {root}",
            "NCA_REFERENCE_MANIFEST_INVALID",
            path=str(root),
        )
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise _reference_error(
                f"NCA reference packages may not contain symbolic links: {path}",
                "NCA_REFERENCE_MANIFEST_INVALID",
                path=str(path),
            )
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    required = {"FILE_MANIFEST.json", "HANDOVER_VERIFICATION.json", "CHECKSUMS.sha256"}
    missing = sorted(required - actual)
    if missing:
        raise _reference_error(
            f"NCA package is missing required inventory files: {missing}",
            "NCA_REFERENCE_MANIFEST_INVALID",
            missing=missing,
        )

    checksum_rows: dict[str, str] = {}
    try:
        lines = (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise _reference_error(
            f"Invalid NCA checksum inventory: {exc}",
            "NCA_REFERENCE_MANIFEST_INVALID",
        ) from exc
    for line_number, line in enumerate(lines, start=1):
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not _SHA256_RE.fullmatch(parts[0]):
            raise _reference_error(
                f"Malformed NCA checksum line {line_number}",
                "NCA_REFERENCE_MANIFEST_INVALID",
                line=line_number,
            )
        relative = _safe_relative(parts[1].lstrip("*"))
        if relative in checksum_rows:
            raise _reference_error(
                f"Duplicate NCA checksum path: {relative}",
                "NCA_REFERENCE_MANIFEST_INVALID",
                path=relative,
            )
        checksum_rows[relative] = parts[0]
    expected_checksum_paths = actual - {"CHECKSUMS.sha256"}
    if set(checksum_rows) != expected_checksum_paths:
        raise _reference_error(
            "NCA checksum inventory does not exactly match package files",
            "NCA_REFERENCE_MANIFEST_INVALID",
            missing=sorted(expected_checksum_paths - set(checksum_rows)),
            unexpected=sorted(set(checksum_rows) - expected_checksum_paths),
        )
    for relative, expected in checksum_rows.items():
        observed = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if observed != expected:
            raise _reference_error(
                f"NCA checksum mismatch: {relative}",
                "NCA_REFERENCE_CHECKSUM_FAILED",
                path=relative,
                expected=expected,
                observed=observed,
            )

    manifest = _json_object(root / "FILE_MANIFEST.json")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise _reference_error(
            "NCA FILE_MANIFEST.json files must be a list",
            "NCA_REFERENCE_MANIFEST_INVALID",
        )
    manifest_rows: dict[str, dict[str, Any]] = {}
    for item in files:
        if not isinstance(item, dict):
            raise _reference_error("Invalid NCA file-manifest row", "NCA_REFERENCE_MANIFEST_INVALID")
        relative = _safe_relative(str(item.get("path") or ""))
        if relative in manifest_rows:
            raise _reference_error(
                f"Duplicate NCA manifest path: {relative}",
                "NCA_REFERENCE_MANIFEST_INVALID",
                path=relative,
            )
        manifest_rows[relative] = item
    expected_manifest_paths = actual - {"CHECKSUMS.sha256", "FILE_MANIFEST.json"}
    if set(manifest_rows) != expected_manifest_paths:
        raise _reference_error(
            "NCA file manifest does not exactly match package payload",
            "NCA_REFERENCE_MANIFEST_INVALID",
            missing=sorted(expected_manifest_paths - set(manifest_rows)),
            unexpected=sorted(set(manifest_rows) - expected_manifest_paths),
        )
    for relative, item in manifest_rows.items():
        payload = (root / relative).read_bytes()
        expected_hash = item.get("sha256")
        expected_bytes = item.get("bytes")
        if expected_hash != hashlib.sha256(payload).hexdigest() or expected_bytes != len(payload):
            raise _reference_error(
                f"NCA file manifest mismatch: {relative}",
                "NCA_REFERENCE_CHECKSUM_FAILED",
                path=relative,
            )
    verification = _json_object(root / "HANDOVER_VERIFICATION.json")
    if verification.get("status") != "PASS":
        raise _reference_error(
            "NCA package handover verification is not PASS",
            "NCA_REFERENCE_MANIFEST_INVALID",
            status=verification.get("status"),
        )
    package_sha256 = hashlib.sha256((root / "CHECKSUMS.sha256").read_bytes()).hexdigest()
    return manifest, verification, package_sha256


def _read_table(path: Path, required: frozenset[str]) -> list[dict[str, str]]:
    """Read a structurally strict UTF-8 TSV table with its original fields."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise _reference_error(
            f"NCA table is not valid UTF-8: {path.name}: {exc}",
            "NCA_REFERENCE_ENCODING_INVALID",
            path=str(path),
        ) from exc
    reader = csv.reader(text.splitlines(), delimiter="\t", strict=True)
    try:
        header = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise _reference_error(
            f"NCA table has no valid header: {path.name}",
            "NCA_REFERENCE_COLUMNS_MISSING",
            path=str(path),
        ) from exc
    if len(header) != len(set(header)) or any(not value for value in header):
        raise _reference_error(
            f"NCA table has duplicate or blank columns: {path.name}",
            "NCA_REFERENCE_COLUMNS_MISSING",
            path=str(path),
        )
    missing = sorted(required - set(header))
    if missing:
        raise _reference_error(
            f"NCA table {path.name} is missing columns: {missing}",
            "NCA_REFERENCE_COLUMNS_MISSING",
            path=str(path),
            missing=missing,
        )
    rows: list[dict[str, str]] = []
    try:
        for line_number, values in enumerate(reader, start=2):
            if len(values) != len(header):
                raise _reference_error(
                    f"NCA table {path.name} has a ragged row at line {line_number}",
                    "NCA_REFERENCE_COLUMNS_MISSING",
                    path=str(path),
                    line=line_number,
                )
            rows.append(dict(zip(header, values)))
    except csv.Error as exc:
        raise _reference_error(
            f"Malformed NCA TSV data in {path.name}: {exc}",
            "NCA_REFERENCE_ENCODING_INVALID",
            path=str(path),
        ) from exc
    return rows


def _western_key(row: Mapping[str, str], table: str) -> VerseRef:
    """Parse and validate one Western BK/CH/VS table key."""
    try:
        book = row["BK"]
        chapter = int(row["CH"])
        verse = int(row["VS"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _reference_error(
            f"Invalid Western reference in {table}",
            "NCA_REFERENCE_CONTRACT_CONFLICT",
            table=table,
        ) from exc
    if book not in BOOK_ORDER or str(chapter) != row["CH"] or str(verse) != row["VS"] or chapter < 1 or verse < 0:
        raise _reference_error(
            f"Invalid Western reference in {table}: {book} {row.get('CH')}:{row.get('VS')}",
            "NCA_REFERENCE_CONTRACT_CONFLICT",
            table=table,
        )
    return VerseRef(book, chapter, verse)


def _keyed(rows: Iterable[dict[str, str]], table: str) -> dict[VerseRef, dict[str, str]]:
    """Build a unique Western-key table index."""
    result: dict[VerseRef, dict[str, str]] = {}
    for row in rows:
        key = _western_key(row, table)
        if key in result:
            raise _reference_error(
                f"Duplicate Western key in {table}: {key.label()}",
                "NCA_REFERENCE_DUPLICATE_KEY",
                table=table,
                reference=key.label(),
            )
        result[key] = row
    return result


def _split_ids(raw: str) -> tuple[str, ...]:
    """Split the package's semicolon-delimited provenance identifiers."""
    return tuple(item.strip() for item in raw.split(";") if item.strip())


def _check_counts(tables: Mapping[str, list[dict[str, str]]], verification: Mapping[str, object]) -> None:
    """Enforce every table cardinality published by the package verification manifest."""
    for table, field in _COUNT_FIELDS.items():
        expected = verification.get(field)
        if field == "footnote_guidance_rows" and expected is None:
            expected = verification.get("critical_rows")
        if not isinstance(expected, int) or expected < 0:
            raise _reference_error(
                f"NCA handover verification lacks a valid {field}",
                "NCA_REFERENCE_MANIFEST_INVALID",
                field=field,
            )
        if len(tables[table]) != expected:
            raise _reference_error(
                f"NCA table cardinality differs from {field}: {table}",
                "NCA_REFERENCE_CARDINALITY_MISMATCH",
                table=table,
                expected=expected,
                observed=len(tables[table]),
            )
    main_count = verification.get("operator_index_rows")
    if len(tables["canonical_number_index.tsv"]) != main_count:
        raise _reference_error(
            "Canonical and operator index cardinalities differ",
            "NCA_REFERENCE_CARDINALITY_MISMATCH",
            expected=main_count,
            observed=len(tables["canonical_number_index.tsv"]),
        )


def _check_numeric_encodings(tables: Mapping[str, list[dict[str, str]]]) -> None:
    """Validate every governed rational-value cell using the canonical parser."""
    for table, columns in _NUMERIC_COLUMNS.items():
        for line_number, row in enumerate(tables[table], start=2):
            for column in columns:
                try:
                    parse_values(row[column])
                except ValidationError as exc:
                    exc.details.update({"table": table, "column": column, "line": line_number})
                    raise


def _check_authoritative_agreement(
    main: Mapping[VerseRef, dict[str, str]],
    canonical: Mapping[VerseRef, dict[str, str]],
) -> None:
    """Require both authoritative indexes to agree except documented note enrichment."""
    if set(main) != set(canonical):
        raise _reference_error(
            "Canonical and operator index key sets differ",
            "NCA_REFERENCE_CONTRACT_CONFLICT",
        )
    for key, operator in main.items():
        other = canonical[key]
        for field in set(operator) & set(other):
            if operator[field] == other[field]:
                continue
            if (
                field == "TEXTUAL_CRITICAL_NOTE"
                and operator["VARIANT_CLASS"] == "UNIT_CONVERSION_NOT_TEXTUAL_VARIANT"
                and other[field] == ""
            ):
                continue
            raise _reference_error(
                f"Authoritative index conflict at {key.label()} field {field}",
                "NCA_REFERENCE_CONTRACT_CONFLICT",
                reference=key.label(),
                field=field,
            )


def _check_registry_joins(
    main: Mapping[VerseRef, dict[str, str]],
    variants: Mapping[VerseRef, dict[str, str]],
    footnotes: Mapping[VerseRef, dict[str, str]],
    units: Mapping[VerseRef, dict[str, str]],
) -> list[str]:
    """Require authoritative registry policy joins and return display-only spacing differences."""
    if set(variants) != set(footnotes) or set(variants) & set(units):
        raise _reference_error(
            "NCA variant, footnote, and unit registry memberships conflict",
            "NCA_REFERENCE_CONTRACT_CONFLICT",
        )
    expected_variants = {key for key, row in main.items() if row["MATCH_STATUS"] == "TEXTUAL_VARIANT_RESEARCHED"}
    expected_units = {key for key, row in main.items() if row["MATCH_STATUS"] == "PASS_UNIT_CONVERSION"}
    if set(variants) != expected_variants or set(units) != expected_units:
        raise _reference_error(
            "NCA registry membership differs from the operator index",
            "NCA_REFERENCE_CONTRACT_CONFLICT",
        )
    for key, variant in variants.items():
        operator = main[key]
        footnote = footnotes[key]
        pairs = (
            (variant, operator, (("OL_REF", "OL_REF"), ("CLASS", "VARIANT_CLASS"), ("SCHOLARSHIP_STATUS", "SCHOLARSHIP_STATUS"),
                                 ("TEXTUAL_CRITICAL_NOTE", "TEXTUAL_CRITICAL_NOTE"), ("SOURCE_IDS", "SOURCE_IDS"),
                                 ("OL_VALUE_RESEARCHED", "OL_VALUES"), ("NIV_VALUE_RESEARCHED", "NIV_VALUES"))),
            (footnote, operator, (("OL_REF", "OL_REF"), ("CLASS", "VARIANT_CLASS"), ("SCHOLARSHIP_STATUS", "SCHOLARSHIP_STATUS"),
                                  ("SOURCE_IDS", "SOURCE_IDS"), ("SOURCE_URLS", "SOURCE_URLS"), ("OL_VALUES", "OL_VALUES"),
                                  ("ALT_NIV_VALUES", "NIV_VALUES"), ("FOOTNOTE_IF_TARGET_FOLLOWS_OL", "FOOTNOTE_IF_TARGET_FOLLOWS_OL"),
                                  ("FOOTNOTE_IF_TARGET_FOLLOWS_ALT", "FOOTNOTE_IF_TARGET_FOLLOWS_ALT"))),
        )
        for left, right, fields in pairs:
            for left_field, right_field in fields:
                if left[left_field] != right[right_field]:
                    raise _reference_error(
                        f"NCA registry conflict at {key.label()} field {left_field}",
                        "NCA_REFERENCE_CONTRACT_CONFLICT",
                        reference=key.label(),
                        field=left_field,
                    )
        if variant["MANUSCRIPT_EVIDENCE"] != footnote["MANUSCRIPT_EVIDENCE"] or variant["NIV_FOOTNOTE"] != footnote["NIV_FOOTNOTE"]:
            raise _reference_error(
                f"NCA variant evidence conflict at {key.label()}",
                "NCA_REFERENCE_CONTRACT_CONFLICT",
                reference=key.label(),
            )
        if variant["MAJORITY_SCHOLARSHIP_POSITION"] != footnote["SCHOLARSHIP_POSITION"]:
            raise _reference_error(
                f"NCA scholarship policy conflict at {key.label()}",
                "NCA_REFERENCE_CONTRACT_CONFLICT",
                reference=key.label(),
            )
        normalize_footnote_action(footnote["FOOTNOTE_IF_TARGET_FOLLOWS_OL"])
        normalize_footnote_action(footnote["FOOTNOTE_IF_TARGET_FOLLOWS_ALT"])
        allowed_ol = {"PASS_AUTHORITY1", "NO_CONFIGURED_OL_READING"}
        allowed_alt = {
            "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
            "CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE",
        }
        if footnote["VALIDATION_IF_TARGET_FOLLOWS_OL"] not in allowed_ol or footnote["VALIDATION_IF_TARGET_FOLLOWS_ALT"] not in allowed_alt:
            raise _reference_error(
                f"Unknown NCA reading policy at {key.label()}",
                "NCA_REFERENCE_CONTRACT_CONFLICT",
                reference=key.label(),
            )
    spacing: list[str] = []
    for key, unit in units.items():
        operator = main[key]
        for left_field, right_field in (
            ("CLASS", "VARIANT_CLASS"), ("SCHOLARSHIP_STATUS", "SCHOLARSHIP_STATUS"), ("OL_TEXT", "OL_TEXT"),
            ("NOTE", "TEXTUAL_CRITICAL_NOTE"), ("SOURCE_IDS", "SOURCE_IDS"),
        ):
            if unit[left_field] != operator[right_field]:
                raise _reference_error(
                    f"NCA unit registry conflict at {key.label()} field {left_field}",
                    "NCA_REFERENCE_CONTRACT_CONFLICT",
                    reference=key.label(),
                    field=left_field,
                )
        if unit["NIV_TEXT"] != operator["NIV_TEXT"]:
            if re.sub(r"\s+", "", unit["NIV_TEXT"]) == re.sub(r"\s+", "", operator["NIV_TEXT"]):
                spacing.append(key.label())
            else:
                raise _reference_error(
                    f"NCA unit display text conflict at {key.label()}",
                    "NCA_REFERENCE_CONTRACT_CONFLICT",
                    reference=key.label(),
                )
    return spacing


def _check_provenance(
    tables: Mapping[str, list[dict[str, str]]],
    provenance: Mapping[str, dict[str, str]],
) -> None:
    """Require every referenced source ID and expanded source URL to resolve exactly."""
    for table in (
        "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv",
        "textual_variant_registry.tsv",
        "footnote_guidance.tsv",
        "unit_conversion_registry.tsv",
    ):
        for line_number, row in enumerate(tables[table], start=2):
            source_ids = _split_ids(row["SOURCE_IDS"])
            missing = [source_id for source_id in source_ids if source_id not in provenance]
            if missing:
                raise _reference_error(
                    f"NCA source IDs do not resolve in {table}: {missing}",
                    "NCA_REFERENCE_PROVENANCE_MISSING",
                    table=table,
                    line=line_number,
                    source_ids=missing,
                )
            if "SOURCE_URLS" in row:
                expected = tuple(provenance[source_id]["URL"] for source_id in source_ids if provenance[source_id]["URL"])
                if _split_ids(row["SOURCE_URLS"]) != expected:
                    raise _reference_error(
                        f"NCA expanded source URLs conflict in {table} line {line_number}",
                        "NCA_REFERENCE_CONTRACT_CONFLICT",
                        table=table,
                        line=line_number,
                    )
    for source_id, row in provenance.items():
        url = row["URL"]
        parsed = urlparse(url)
        if url and (parsed.scheme not in {"http", "https"} or not parsed.netloc):
            raise _reference_error(
                f"Malformed NCA provenance URL for {source_id}",
                "NCA_REFERENCE_CONTRACT_CONFLICT",
                source_id=source_id,
            )


def _lineage_diagnostic(
    main: Mapping[VerseRef, dict[str, str]],
    expressions: Iterable[dict[str, str]],
) -> dict[str, object] | None:
    """Describe supplementary expression gaps without modifying authoritative values."""
    by_ol_ref: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in expressions:
        by_ol_ref[row["OL_REF"]].append(row)
    differing = 0
    additional = 0
    new_numeric = 0
    references: list[str] = []
    for key, row in main.items():
        ordered = sorted(by_ol_ref[row["OL_REF"]], key=lambda item: int(item["EXPR_NO"]))
        audit_values = [item["DIGIT_VALUE"] for item in ordered]
        authoritative = [str(value) for value in parse_values(row["OL_VALUES"])]
        if audit_values == authoritative:
            continue
        differing += 1
        references.append(key.label())
        additional += sum((Counter(authoritative) - Counter(audit_values)).values())
        if authoritative and not audit_values:
            new_numeric += 1
    if not differing:
        return None
    return {
        "code": "REFERENCE_LINEAGE_INCOMPLETE",
        "severity": "WARNING",
        "differing_rows": differing,
        "additional_authoritative_values": additional,
        "new_numeric_rows": new_numeric,
        "runtime_numeric_rows": sum(bool(row["OL_VALUES"]) for row in main.values()),
        "runtime_value_count": sum(len(parse_values(row["OL_VALUES"])) for row in main.values()),
        "supplementary_expression_count": sum(len(rows) for rows in by_ol_ref.values()),
        "references": tuple(references),
        "disposition": "Use authoritative operator values unchanged; supplementary expression lineage is incomplete.",
    }


def _boundary_diagnostic(root: Path, main: Mapping[VerseRef, dict[str, str]]) -> dict[str, object] | None:
    """Record stored OL references that intentionally differ from shift-rule projection."""
    schema = parse_vrs_file(
        root / "reference" / "eng_org_map_rules.txt",
        schema_id="eng",
        canonical_id="org",
    )
    exceptions: list[dict[str, object]] = []
    for key, row in main.items():
        ol_reference = row["OL_REF"]
        if not ol_reference:
            continue
        projected = tuple(sorted(ref.label() for ref in schema.local_to_canonical(key)))
        if ol_reference not in projected:
            exceptions.append(
                {
                    "western_reference": key.label(),
                    "stored_ol_reference": ol_reference,
                    "projected_ol_references": projected,
                }
            )
    if not exceptions:
        return None
    return {
        "code": "NCA_OL_REFERENCE_BOUNDARY_EXCEPTION",
        "severity": "WARNING",
        "count": len(exceptions),
        "exceptions": tuple(exceptions),
        "disposition": "Preserve the stored authoritative OL_REF and use boundary-group handling.",
    }


def _load_qualified(root: Path) -> ReferenceBundle:
    """Load one already-resolved package root after full deterministic qualification."""
    manifest, verification, package_sha256 = _verify_inventory(root)
    package_id = str(manifest.get("handover") or "").strip()
    if not package_id or package_id != str(verification.get("handover") or "").strip():
        raise _reference_error(
            "NCA package identity is absent or inconsistent",
            "NCA_REFERENCE_MANIFEST_INVALID",
        )
    reference_root = root / "reference"
    tables = {
        name: _read_table(reference_root / name, columns)
        for name, columns in _REQUIRED_COLUMNS.items()
    }
    main = _keyed(tables["SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv"], "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv")
    canonical = _keyed(tables["canonical_number_index.tsv"], "canonical_number_index.tsv")
    variants = _keyed(tables["textual_variant_registry.tsv"], "textual_variant_registry.tsv")
    footnotes = _keyed(tables["footnote_guidance.tsv"], "footnote_guidance.tsv")
    units = _keyed(tables["unit_conversion_registry.tsv"], "unit_conversion_registry.tsv")
    _check_counts(tables, verification)
    _check_numeric_encodings(tables)
    _check_authoritative_agreement(main, canonical)
    spacing = _check_registry_joins(main, variants, footnotes, units)

    provenance: dict[str, dict[str, str]] = {}
    for row in tables["provenance_sources.tsv"]:
        source_id = row["SOURCE_ID"]
        if not source_id or source_id in provenance:
            raise _reference_error(
                f"Duplicate or blank NCA provenance source ID: {source_id!r}",
                "NCA_REFERENCE_DUPLICATE_KEY",
                source_id=source_id,
            )
        provenance[source_id] = row
    _check_provenance(tables, provenance)

    rows: dict[VerseRef, ReferenceRow] = {}
    for key, row in main.items():
        registered_absence = not any(
            (row["LANG"], row["OL_REF"], row["OL_TEXT"], row["OL_VALUES"])
        )
        if row["LANG"] not in {"HEB", "GRK"} and not registered_absence:
            raise _reference_error(
                f"Unsupported NCA original-language code at {key.label()}: {row['LANG']!r}",
                "NCA_REFERENCE_CONTRACT_CONFLICT",
                reference=key.label(),
            )
        normalize_footnote_action(row["FOOTNOTE_IF_TARGET_FOLLOWS_OL"])
        normalize_footnote_action(row["FOOTNOTE_IF_TARGET_FOLLOWS_ALT"])
        rows[key] = ReferenceRow(
            western_reference=key,
            ol_reference=row["OL_REF"] or None,
            language=row["LANG"],
            ol_text=row["OL_TEXT"],
            ol_values=parse_values(row["OL_VALUES"]),
            niv_text=row["NIV_TEXT"],
            niv_values=parse_values(row["NIV_VALUES"]),
            metadata={field: value for field, value in row.items() if field not in _PRIMARY_FIELDS},
        )

    diagnostics: list[dict[str, object]] = []
    lineage = _lineage_diagnostic(main, tables["ol_expression_audit.tsv"])
    if lineage:
        diagnostics.append(lineage)
    if spacing:
        diagnostics.append(
            {
                "code": "NCA_UNIT_DISPLAY_SPACING_DIFFERENCE",
                "severity": "WARNING",
                "count": len(spacing),
                "references": tuple(spacing),
                "disposition": "Use authoritative operator NIV_TEXT for display and preserve registry bytes.",
            }
        )
    boundary = _boundary_diagnostic(root, main)
    if boundary:
        diagnostics.append(boundary)
    return ReferenceBundle(
        package_id=package_id,
        sha256=package_sha256,
        rows=rows,
        variants=variants,
        footnote_guidance=footnotes,
        units=units,
        provenance=provenance,
        qualification_status="QUALIFIED_WITH_DIAGNOSTICS" if diagnostics else "QUALIFIED",
        diagnostics=tuple(diagnostics),
    )


def load_reference(root: Path, *, qualification: str = "STRICT") -> ReferenceBundle:
    """Validate and load an NCA package in strict or diagnostic qualification mode."""
    if qualification not in {"STRICT", "DIAGNOSTIC"}:
        raise _reference_error(
            f"Unsupported NCA reference qualification mode: {qualification!r}",
            "NCA_REFERENCE_QUALIFICATION_INVALID",
            qualification=qualification,
        )
    resolved = Path(root).expanduser().resolve()
    try:
        return _load_qualified(resolved)
    except ValidationError as exc:
        if qualification == "STRICT":
            raise
        checksum_path = resolved / "CHECKSUMS.sha256"
        package_sha256 = (
            hashlib.sha256(checksum_path.read_bytes()).hexdigest()
            if checksum_path.is_file()
            else "0" * 64
        )
        return ReferenceBundle(
            package_id=resolved.name or "unknown-reference",
            sha256=package_sha256,
            rows={},
            variants={},
            footnote_guidance={},
            units={},
            provenance={},
            qualification_status="BLOCKED",
            diagnostics=(
                {
                    "code": exc.code,
                    "severity": "ERROR",
                    "message": exc.message,
                    "details": exc.details,
                },
            ),
        )
