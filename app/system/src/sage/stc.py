"""Source Text Correspondence (STC) planning, validation, and exact finalization."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .atomic import atomic_write_json, atomic_write_text
from .candidates import reconcile_adjudications
from .canon import NT_27, OT_39
from .errors import ValidationError
from .evidence import TOKEN_ESTIMATOR, EvidenceMeasurement, EvidencePolicy
from .exception_reports import NOT_ASSESSED, coverage_document, render_exceptions_section
from .hashing import sha256_bytes
from .references import expand_reference_atoms, parse_scope
from .sfm_slicer import (
    SfmAnalysisRoute,
    SfmStream,
    measure_sfm_slice,
    measure_sfm_text,
    plan_sfm_work_units,
    render_sfm_slice,
)
from .source_coverage import source_text_issues
from .source_coverage import source_comparison_status, unique_source_text_issues
from .structural_issues import normalize_structure_problem
from .verse_alignment import ProjectVerseIndex
from .work_units import EvidenceRecord, WorkUnit
from .vrs import VerseRef

STC_FINDING_CATEGORIES = {"OMISSION", "ADDITION", "VARIATION", "CONSISTENCY"}
STC_ANALYSIS_ROUTE = "STC_CORRESPONDENCE"
STC_RESULT_VERSION = "1.0"
STC_ESTIMATOR = TOKEN_ESTIMATOR
STC_PLANNER_VERSION = "SAGE_STC_SFM_ROUTE_PLANNER_V2"
LEGACY_STC_PLANNER_VERSION = "SAGE_STC_SFM_ROUTE_PLANNER_V1"


# Hebrew cantillation accents (U+0591-U+05AF) are chant and prosody marks. Routed Hebrew evidence drops
# them and keeps consonants, vowel points, maqaf, and sof pasuq: about 22% fewer model tokens per Hebrew
# verse, and STC's verbatim-quote check already matches quotes with or without accents.
HEBREW_CANTILLATION_RE = re.compile("[\u0591-\u05AF]")


def strip_hebrew_cantillation(text: str) -> str:
    """Remove Hebrew cantillation accents, keeping every letter, vowel point, and punctuation mark."""
    return HEBREW_CANTILLATION_RE.sub("", text)


def routed_ol_text_filter(family: str) -> Callable[[str], str] | None:
    """Return the text filter for original-language evidence routed to a model, if any."""
    return strip_hebrew_cantillation if str(family).strip().upper() == "HEB" else None


def routed_ol_text_filter_for_book(book: str) -> Callable[[str], str] | None:
    """Return the routed original-language text filter for one book; Hebrew Old Testament books only."""
    return strip_hebrew_cantillation if str(book).strip().upper() in OT_39 else None


def _routed_ol(text: str, family: str) -> str:
    """Apply the routed original-language text filter for one family."""
    text_filter = routed_ol_text_filter(family)
    return text_filter(text) if text_filter is not None else text


def stc_authority_family(book: str) -> str:
    """Return the testament-governed primary OL authority family for one canonical book."""
    code = str(book).strip().upper()
    if code in NT_27:
        return "GRK"
    if code in OT_39:
        return "HEB"
    raise ValidationError(
        f"STC does not support original-language routing for book {book!r}",
        code="STC_CANONICAL_BOOK_REQUIRED",
    )


def plan_stc_work_units(
    wip_records: Iterable[EvidenceRecord],
    ol_records: Iterable[EvidenceRecord],
    policy: EvidencePolicy,
    *,
    unit_prefix: str,
    wip_index: ProjectVerseIndex | None = None,
    ol_index: ProjectVerseIndex | None = None,
    context_pool: Iterable[EvidenceRecord] | None = None,
    planner_version: str | None = None,
) -> tuple[WorkUnit, ...]:
    """Plan bounded WIP+primary-OL work units with exact canonical coverage."""
    selected = tuple(wip_records)
    if not selected:
        raise ValidationError("STC planning requires WIP Scripture records", code="STC_WIP_MISSING")
    ol = tuple(ol_records)
    family = stc_authority_family(selected[0].book)
    version = _stc_planner_version(planner_version, wip_index, ol_index)
    indexed = version == STC_PLANNER_VERSION
    route = SfmAnalysisRoute(
        route_id=STC_ANALYSIS_ROUTE,
        streams=(
            SfmStream(
                "WIP",
                tuple(context_pool) if context_pool is not None else selected,
                verse_index=wip_index if indexed else None,
            ),
            SfmStream(
                f"{family}:PRIMARY",
                ol,
                require_primary_coverage=False,
                verse_index=ol_index if indexed else None,
                text_filter=routed_ol_text_filter(family),
            ),
        ),
        primary_stream_id="WIP" if indexed else None,
        primary_index=wip_index if indexed else None,
    )
    return plan_sfm_work_units(
        selected,
        policy,
        unit_prefix=unit_prefix,
        route=route,
        context_pool=tuple(context_pool) if context_pool is not None else selected,
    )


def _records_for_refs(
    records: Iterable[EvidenceRecord], refs: frozenset[VerseRef]
) -> tuple[EvidenceRecord, ...]:
    """Select source records intersecting the requested canonical coordinates."""
    return tuple(record for record in records if refs.intersection(record.refs))


def _stc_planner_version(
    requested: str | None,
    wip_index: ProjectVerseIndex | None,
    ol_index: ProjectVerseIndex | None,
) -> str:
    """Resolve indexed V2 planning or the exact sealed V1 compatibility path."""
    version = str(requested or "").strip()
    if not version:
        version = (
            STC_PLANNER_VERSION
            if wip_index is not None and ol_index is not None
            else LEGACY_STC_PLANNER_VERSION
        )
    if version not in {STC_PLANNER_VERSION, LEGACY_STC_PLANNER_VERSION}:
        raise ValidationError(
            f"Unsupported STC planner version: {version}",
            code="STC_PLANNER_VERSION_UNSUPPORTED",
        )
    if version == STC_PLANNER_VERSION and (wip_index is None or ol_index is None):
        raise ValidationError(
            "STC V2 planning requires WIP and primary-OL Project verse indexes",
            code="STC_VRS_INDEX_REQUIRED",
        )
    return version


def _indexed_records_for_canonical(
    records: tuple[EvidenceRecord, ...],
    index: ProjectVerseIndex,
    refs: frozenset[VerseRef],
) -> tuple[EvidenceRecord, ...]:
    """Select canonical matches without expanding beyond routed OL evidence."""
    return tuple(record for record in index.records_for_canonical(refs) if record in records)


def _canonical_source_text_issues(
    unit: WorkUnit,
    wip_index: ProjectVerseIndex,
    missing_canonical: frozenset[VerseRef],
    *,
    authority_stream: str,
) -> list[dict[str, Any]]:
    """Attach missing canonical OL coverage to corresponding WIP-local coordinates."""
    missing_local: set[VerseRef] = set()
    canonical_by_local: dict[VerseRef, set[VerseRef]] = {}
    for record in unit.primary:
        record_missing = wip_index.canonical_refs_for_records((record,)).intersection(
            missing_canonical
        )
        if not record_missing:
            continue
        for local_ref in record.refs:
            missing_local.add(local_ref)
            canonical_by_local.setdefault(local_ref, set()).update(record_missing)
    issues = list(source_text_issues(
        missing_local,
        (),
        workflow="STC",
        source_stream=authority_stream,
        scope=str(unit.to_dict()["primary_scope"]),
    ))
    for issue in issues:
        local_ref = next(
            ref for ref in missing_local if ref.label() == issue["reference"]
        )
        issue["canonical_references"] = [
            ref.label() for ref in sorted(canonical_by_local[local_ref])
        ]
    return issues


def _component(measurement: EvidenceMeasurement) -> dict[str, Any]:
    """Render one routed-SFM measurement component for STC audit and display."""
    return {
        "estimator": STC_ESTIMATOR,
        "estimated_tokens": measurement.estimated_tokens,
        "serialized_bytes": measurement.serialized_bytes,
        "basis": "ROUTED_SFM_ONLY",
    }


def stc_package_measurements(
    units: Iterable[WorkUnit],
    ol_records: Iterable[EvidenceRecord],
    *,
    wip_index: ProjectVerseIndex | None = None,
    ol_index: ProjectVerseIndex | None = None,
    planner_version: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Measure WIP, primary OL, and combined STC routed-SFM review items."""
    original_language = tuple(ol_records)
    version = _stc_planner_version(planner_version, wip_index, ol_index)
    packages: list[dict[str, Any]] = []
    for unit in units:
        wip_slice = tuple(sorted(
            (*unit.context_before, *unit.primary, *unit.context_after),
            key=lambda item: (item.chapter, item.verse_start, item.verse_end),
        ))
        family = stc_authority_family(unit.primary[0].book)
        authority_stream = f"{family}:PRIMARY"
        if version == STC_PLANNER_VERSION:
            assert wip_index is not None and ol_index is not None
            primary_canonical = wip_index.canonical_refs_for_records(unit.primary)
            routed_canonical = wip_index.canonical_refs_for_records(wip_slice)
            ol_primary = _indexed_records_for_canonical(
                original_language,
                ol_index,
                primary_canonical,
            )
            ol_slice = _indexed_records_for_canonical(
                original_language,
                ol_index,
                routed_canonical,
            )
            covered = ol_index.canonical_refs_for_records(ol_primary)
            missing_canonical = primary_canonical.difference(covered)
            issues = _canonical_source_text_issues(
                unit,
                wip_index,
                missing_canonical,
                authority_stream=authority_stream,
            )
        else:
            ol_primary = _records_for_refs(original_language, unit.primary_refs)
            ol_slice = ol_primary
            covered = frozenset(ref for record in ol_primary for ref in record.refs)
            primary_canonical = frozenset(unit.primary_refs)
            missing_canonical = primary_canonical.difference(covered)
            issues = list(source_text_issues(
                unit.primary_refs,
                covered,
                workflow="STC",
                source_stream=authority_stream,
                scope=str(unit.to_dict()["primary_scope"]),
            ))
        primary_scope = str(unit.to_dict()["primary_scope"])
        package = {
            "sizing_basis": "ROUTED_SFM_ONLY",
            "analysis_route": STC_ANALYSIS_ROUTE,
            "primary_coverage_atoms": [ref.label() for ref in sorted(unit.primary_refs)],
            "structural_issues": issues,
            "source_text_issues": issues,
            "wip": _component(measure_sfm_slice(wip_slice)),
            "ol": _component(measure_sfm_text(_routed_ol(render_sfm_slice(ol_slice), family))),
            "route": _component(unit.measurement),
        }
        if version == STC_PLANNER_VERSION:
            package.update({
                "projection": version,
                "source_spans": {
                    "WIP": [record.reference for record in unit.primary],
                    authority_stream: [record.reference for record in ol_primary],
                },
                "alignment": {
                    "primary_local_atoms": [
                        ref.label() for ref in sorted(unit.primary_refs)
                    ],
                    "canonical_atoms": [
                        ref.label() for ref in sorted(primary_canonical)
                    ],
                    "authority_stream": authority_stream,
                    "authority_local_spans": [
                        record.reference for record in ol_primary
                    ],
                    "missing_canonical_atoms": [
                        ref.label() for ref in sorted(missing_canonical)
                    ],
                },
            })
        packages.append(package)
    return tuple(packages)


def stc_package_summary(packages: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return STC routed-SFM maxima for operator plan display."""
    values = tuple(packages)
    return {
        "largest_wip_estimated_tokens": max(
            (int(item["wip"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_ol_estimated_tokens": max(
            (int(item["ol"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_route_estimated_tokens": max(
            (int(item["route"]["estimated_tokens"]) for item in values), default=0
        ),
        "largest_route_serialized_bytes": max(
            (int(item["route"]["serialized_bytes"]) for item in values), default=0
        ),
        "sizing_basis": "ROUTED_SFM_ONLY",
    }


def _stable_finding_id(work_unit_id: str, finding: Mapping[str, Any]) -> str:
    """Derive a deterministic STC finding identity from governed evidence coordinates."""
    seed = {
        "work_unit_id": work_unit_id,
        "category": str(finding.get("category") or "").upper(),
        "target_reference": str(finding.get("target_reference") or ""),
        "wip_evidence": str(finding.get("wip_evidence") or ""),
        "ol_evidence": str(finding.get("ol_evidence") or ""),
        "summary": str(finding.get("summary") or ""),
    }
    digest = sha256_bytes(json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))[:16].upper()
    return f"STC-F-{digest}"


# A verse is a length outlier when its WIP/OL length ratio is this far from the book's median ratio.
LENGTH_OUTLIER_LOW = 0.4
LENGTH_OUTLIER_HIGH = 2.5
_MIN_OL_CHARS = 20


def length_outliers(
    primary_records: Sequence[Any],
    book_records: Sequence[Any],
    wip_index: Any,
    ol_index: Any,
) -> list[dict[str, Any]]:
    """Return WIP verses much shorter or longer than their OL text, relative to the book's median ratio.

    These are candidates for the model to check for omissions or additions, never findings by themselves.
    """

    def ratio(record: Any) -> tuple[float, int] | None:
        """Return the WIP/OL character ratio of one WIP record and its OL length."""
        ol_records = ol_index.records_for_canonical(wip_index.canonical_refs_for_records((record,)))
        ol_chars = sum(len(str(item.payload.get("body_text") or "").strip()) for item in ol_records)
        wip_chars = len(str(record.payload.get("body_text") or "").strip())
        if ol_chars < _MIN_OL_CHARS or not wip_chars:
            return None
        return wip_chars / ol_chars, ol_chars

    book_ratios = sorted(value[0] for record in book_records if (value := ratio(record)) is not None)
    if len(book_ratios) < 5:
        return []
    median = book_ratios[len(book_ratios) // 2]
    rows: list[dict[str, Any]] = []
    for record in primary_records:
        value = ratio(record)
        if value is None:
            continue
        relative = value[0] / median
        if relative < LENGTH_OUTLIER_LOW or relative > LENGTH_OUTLIER_HIGH:
            rows.append(
                {
                    "wip_reference": record.reference,
                    "direction": "SHORT" if relative < 1 else "LONG",
                    "relative_length": round(relative, 2),
                }
            )
    return rows


def stc_gap_findings(
    rows: Iterable[Mapping[str, Any]],
    *,
    work_unit_id: str,
    authority_family: str,
) -> list[dict[str, Any]]:
    """Promote OMISSION and ADDITION coverage gaps to deterministic STC findings."""
    findings: list[dict[str, Any]] = []
    for row in rows:
        relation = str(row.get("text_relation") or "").upper()
        if relation not in {"OMISSION", "ADDITION"}:
            continue
        normalized = {
            "category": relation,
            "target_reference": str(row.get("reference") or ""),
            "summary": str(row.get("message") or ""),
            "wip_evidence": "" if relation == "OMISSION" else "WIP text present",
            "ol_evidence": "Original-language text present" if relation == "OMISSION" else "",
            "authority_family": authority_family,
            "authority_role": "PRIMARY",
            "detection": "DETERMINISTIC",
        }
        normalized["finding_id"] = _stable_finding_id(work_unit_id, normalized)
        findings.append(normalized)
    return findings


_MARKER_RE = re.compile(r"\\[A-Za-z0-9]+\*?")
_ELLIPSIS_RE = re.compile(r"\s*(?:\.\.\.|…)\s*")


def _evidence_plain(text: str, *, fold_diacritics: bool = False) -> str:
    """Reduce SFM or a quotation to comparable plain text: NFC, no markers, no ketiv/qere asterisks."""
    value = unicodedata.normalize("NFC", _MARKER_RE.sub(" ", str(text))).replace("*", "")
    if fold_diacritics:
        value = unicodedata.normalize(
            "NFC",
            "".join(char for char in unicodedata.normalize("NFD", value) if not unicodedata.combining(char)),
        )
    return " ".join(value.split()).casefold()


def evidence_is_verbatim(quote: str, source_text: str) -> bool:
    """Return whether every ellipsis-separated part of a quotation occurs in the routed text.

    Comparison ignores USFM markers, whitespace, and case, and falls back to ignoring diacritics
    (vowel points and accents) when the exact comparison fails.
    """
    parts = [part for part in _ELLIPSIS_RE.split(str(quote)) if part.strip()]
    if not parts:
        return False
    for fold in (False, True):
        haystack = _evidence_plain(source_text, fold_diacritics=fold)
        if all(_evidence_plain(part, fold_diacritics=fold) in haystack for part in parts):
            return True
    return False


def validate_stc_submission(
    path: Path,
    *,
    task_id: str,
    work_unit_id: str,
    scope_value: str,
    expected_references: Iterable[str],
    authority_family: str,
    task_fingerprint: str,
    narrative_language: str,
    wip_text: str | None = None,
    ol_text: str | None = None,
    expected_candidates: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Validate provider STC semantics and materialize deterministic identity/coverage.

    With the routed ``wip_text`` and ``ol_text``, each finding's quotations are checked against them; a
    quotation that cannot be found keeps its finding but marks it ``evidence_verified: false``.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid STC findings output: {exc}", code="STC_OUTPUT_INVALID") from exc
    if not isinstance(raw, dict):
        raise ValidationError("STC findings output must be a JSON object", code="STC_OUTPUT_INVALID")
    summary = str(raw.get("review_summary") or "").strip()
    if not summary:
        raise ValidationError("STC output requires review_summary", code="STC_OUTPUT_INVALID")
    salvage_records: list[dict[str, Any]] = []
    report_language = str(raw.get("report_language") or "").strip()
    if report_language != narrative_language:
        # The narrative is kept but reported as unverified rather than discarding the whole unit.
        salvage_records.append(
            {
                "code": "STC_REPORT_LANGUAGE_UNVERIFIED",
                "coordinate": scope_value,
                "effect": "FLAGGED",
                "message": (
                    f"The STC narrative declares {report_language or 'no language'} instead of "
                    f"{narrative_language}; its wording is unverified."
                ),
            }
        )
    expected = tuple(str(value) for value in expected_references)
    expected_set = set(expected)
    # Exact verse atoms: a prefix test would accept MAT 1:2 because MAT 1:20 is planned.
    expected_atoms = {atom for label in expected for atom in expand_reference_atoms(label)}
    scope = parse_scope(scope_value)
    findings_raw = raw.get("findings", [])
    if not isinstance(findings_raw, list):
        raise ValidationError("STC findings must be a list", code="STC_OUTPUT_INVALID")
    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for value in findings_raw:
        if not isinstance(value, dict):
            raise ValidationError("Each STC finding must be an object", code="STC_OUTPUT_INVALID")
        category = str(value.get("category") or "").strip().upper()
        reference = str(value.get("target_reference") or "").strip()
        wip_evidence = str(value.get("wip_evidence") or "").strip()
        ol_evidence = str(value.get("ol_evidence") or "").strip()
        finding_summary = str(value.get("summary") or "").strip()
        defect = ""
        if category not in STC_FINDING_CATEGORIES:
            defect = f"uses an unsupported category {category or '(none)'}"
        else:
            try:
                reference_atoms = expand_reference_atoms(reference) if reference else ()
            except ValidationError:
                reference_atoms = ()
            if not reference_atoms or not all(scope.contains(ref) for ref in reference_atoms):
                defect = "cites a reference outside the governed scope"
            elif reference not in expected_set and not set(reference_atoms) <= expected_atoms:
                defect = "cites a reference outside the planned WIP verses"
            elif not wip_evidence or not ol_evidence or not finding_summary:
                defect = "lacks WIP evidence, OL evidence, or a summary"
        normalized = {
            "category": category,
            "target_reference": reference,
            "summary": finding_summary,
            "wip_evidence": wip_evidence,
            "ol_evidence": ol_evidence,
            "authority_family": authority_family,
            "authority_role": "PRIMARY",
        }
        if not defect:
            normalized["finding_id"] = _stable_finding_id(work_unit_id, normalized)
            if normalized["finding_id"] in seen_ids:
                defect = "duplicates another finding"
        if defect:
            salvage_records.append(
                {
                    "code": "STC_FINDING_DROPPED",
                    "coordinate": reference or scope_value,
                    "effect": "FLAGGED",
                    "message": f"An STC finding was dropped: it {defect}."
                    + (f" Finding text: {finding_summary[:600]}" if finding_summary else ""),
                }
            )
            continue
        seen_ids.add(normalized["finding_id"])
        unverified = [
            label
            for label, quote, source_text in (("WIP", wip_evidence, wip_text), ("OL", ol_evidence, ol_text))
            if source_text is not None and not evidence_is_verbatim(quote, source_text)
        ]
        if unverified:
            normalized["evidence_verified"] = False
            salvage_records.append(
                {
                    "code": "STC_EVIDENCE_UNVERIFIED",
                    "coordinate": reference,
                    "effect": "FLAGGED",
                    "message": (
                        f"The {' and '.join(unverified)} quotation of finding {normalized['finding_id']} was not "
                        "found in the routed text; the finding is kept and marked unverified."
                    ),
                }
            )
        findings.append(normalized)
    inventory = list(expected_candidates)
    candidate_adjudications: list[dict[str, Any]] = []
    if inventory or raw.get("candidate_adjudications"):
        candidate_adjudications, candidate_records = reconcile_adjudications(
            raw.get("candidate_adjudications"),
            inventory,
            seen_ids,
            code_prefix="STC",
        )
        salvage_records.extend(candidate_records)
    return {
        "schema_version": STC_RESULT_VERSION,
        "operation": "stc",
        "task_id": task_id,
        "work_unit_id": work_unit_id,
        "task_fingerprint": task_fingerprint,
        "scope": scope_value,
        "analysis_route": STC_ANALYSIS_ROUTE,
        "authority_family": authority_family,
        "authority_role": "PRIMARY",
        "report_language": narrative_language,
        "review_summary": summary,
        "primary_coverage": list(expected),
        "analytical_completion": {
            "status": "COMPLETE",
            "review_item": STC_ANALYSIS_ROUTE,
            "reviewed_primary_coordinates": list(expected),
        },
        "finding_count": len(findings),
        "findings": findings,
        **({"candidate_adjudications": candidate_adjudications} if candidate_adjudications else {}),
        **({"salvage_records": salvage_records} if salvage_records else {}),
    }


def finalize_stc_run(
    *,
    run_id: str,
    planned_units: Iterable[Mapping[str, Any]],
    accepted_results: Iterable[Mapping[str, Any]],
    output_root: Path,
    exceptions: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Path]:
    """Fail closed on exact STC work-unit/coverage reconciliation and write canonical artifacts."""
    plans = [dict(row) for row in planned_units]
    results = [dict(row) for row in accepted_results]
    # Units sealed NOT_ASSESSED never reach this function as results; their exceptions are only reported here.
    exceptions_list = [dict(row) for row in exceptions]
    plan_by_id = {str(row.get("work_unit_id") or row.get("unit_id") or ""): row for row in plans}
    if not plan_by_id or len(plan_by_id) != len(plans) or "" in plan_by_id:
        raise ValidationError("STC immutable work-unit plan is invalid", code="STC_WORK_UNIT_PLAN_INVALID")
    result_by_id: dict[str, dict[str, Any]] = {}
    for result in results:
        unit_id = str(result.get("work_unit_id") or "")
        if unit_id in result_by_id:
            raise ValidationError("Duplicate STC terminal work-unit result", code="DUPLICATE_WORK_UNIT_RESULT")
        result_by_id[unit_id] = result
    missing = sorted(set(plan_by_id) - set(result_by_id))
    extra = sorted(set(result_by_id) - set(plan_by_id))
    if missing:
        raise ValidationError("Missing STC terminal work-unit result", code="MISSING_WORK_UNIT_RESULT", details={"work_unit_ids": missing})
    if extra:
        raise ValidationError("Unexpected STC terminal work-unit result", code="RESULT_COVERAGE_DRIFT", details={"work_unit_ids": extra})
    planned_atoms: list[str] = []
    observed_atoms: list[str] = []
    findings: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    source_issue_rows: list[dict[str, Any]] = []
    for unit_id, plan in plan_by_id.items():
        planned = list(plan.get("primary_coverage") or plan.get("primary_coverage_atoms") or [])
        observed = list(result_by_id[unit_id].get("primary_coverage") or [])
        if planned != observed:
            raise ValidationError("STC result primary coverage differs from immutable plan", code="RESULT_COVERAGE_DRIFT", details={"work_unit_id": unit_id})
        planned_atoms.extend(planned)
        observed_atoms.extend(observed)
        findings.extend(dict(row) for row in result_by_id[unit_id].get("findings", []) if isinstance(row, Mapping))
        receipts.append(dict(result_by_id[unit_id].get("analytical_completion") or {}))
        raw_structure = result_by_id[unit_id].get("structural_issues")
        if raw_structure is None:
            raw_structure = result_by_id[unit_id].get("source_text_issues", [])
        source_issue_rows.extend(
            normalize_structure_problem(dict(row))
            for row in raw_structure
            if isinstance(row, Mapping)
        )
    if len(planned_atoms) != len(set(planned_atoms)):
        raise ValidationError("STC plan has duplicate primary ownership", code="AGGREGATE_COVERAGE_MISMATCH")
    if observed_atoms != planned_atoms:
        raise ValidationError("STC aggregate coverage differs from planned coverage", code="AGGREGATE_COVERAGE_MISMATCH")
    finding_ids = [str(row.get("finding_id") or "") for row in findings]
    if len(finding_ids) != len(set(finding_ids)):
        raise ValidationError("STC aggregate contains duplicate finding identity", code="DUPLICATE_STC_FINDING")
    source_issue_rows = unique_source_text_issues(source_issue_rows)
    comparison_status = source_comparison_status(source_issue_rows)
    output_root.mkdir(parents=True, exist_ok=True)
    run_path = output_root / "STC_RUN_RESULT.json"
    findings_path = output_root / "STC_FINDINGS.json"
    report_path = output_root / "STC_REPORT.md"
    not_assessed_atoms = list(
        dict.fromkeys(
            str(value)
            for row in exceptions_list
            if row.get("effect") == NOT_ASSESSED
            for value in row.get("coordinates") or []
        )
    )
    coverage = coverage_document(planned_atoms, not_assessed_atoms, findings_present=bool(findings))
    run_document = {
        "schema_version": STC_RESULT_VERSION,
        "run_id": run_id,
        "operation": "stc",
        # Lost units outrank the source-comparison status: a Run with NOT_ASSESSED units is not COMPLETE.
        "status": coverage["status"] if not_assessed_atoms else comparison_status,
        "coverage": coverage,
        "structure_status": (
            "VERSIFICATION_MISMATCH" if source_issue_rows else "READY"
        ),
        "source_comparison_status": comparison_status,
        "structural_issues": source_issue_rows,
        "source_text_issues": source_issue_rows,
        "planned_work_units": plans,
        "accepted_work_unit_count": len(results),
        "planned_primary_coverage": planned_atoms,
        "analytical_completion_receipts": receipts,
        "finding_count": len(findings),
        "exceptions": exceptions_list,
    }
    findings_document = {
        "schema_version": STC_RESULT_VERSION,
        "run_id": run_id,
        "operation": "stc",
        "finding_count": len(findings),
        "source_comparison_status": comparison_status,
        "structural_issues": source_issue_rows,
        "source_text_issues": source_issue_rows,
        "findings": findings,
    }
    atomic_write_json(run_path, run_document)
    atomic_write_json(findings_path, findings_document)
    lines = ["# STC Report", "", f"Run: `{run_id}`", f"Findings: {len(findings)}", ""]
    if source_issue_rows:
        lines.extend([
            "## Structural issues",
            "",
            "These coordinate or versification differences did not block STC execution.",
            "",
            *[
                f"- `{row.get('reference', '')}` | `{row.get('source_project_id', '')}` | "
                f"`{row.get('code', 'SOURCE_TEXT_ISSUE')}` — {row.get('message', '')}"
                for row in source_issue_rows
            ],
            "",
        ])
    exception_section = render_exceptions_section(exceptions_list)
    if exception_section:
        lines.extend([*exception_section])
    if not findings:
        lines.append(
            "No governed STC findings were reported for the assessed coordinates."
            if exception_section
            else "No governed STC findings were reported. All planned STC review items completed."
        )
    else:
        for finding in findings:
            lines.extend([
                f"## {finding.get('finding_id', 'STC finding')} — {finding.get('category', '')}",
                "",
                f"- Reference: {finding.get('target_reference', '')}",
                f"- Summary: {finding.get('summary', '')}",
                f"- WIP: {finding.get('wip_evidence', '')}",
                f"- OL: {finding.get('ol_evidence', '')}",
                "",
            ])
    atomic_write_text(report_path, "\n".join(lines).rstrip() + "\n")
    return {"run_result": run_path, "findings": findings_path, "report": report_path}
