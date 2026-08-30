"""Sequential SAW partition-plan continuation helper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, atomic_write_text
from .act_outputs import (
    aggregate_execution_routes,
    render_action_report,
    render_plain_text_from_markdown,
)
from .storage import resolve_persisted_path, storage_layout
from .errors import ValidationError
from .findings import (
    globalize_ol_review_request_ids,
    globalize_result_finding_ids,
    validate_global_finding_ids,
)
from .hashing import sha256_file
from .human_output import report_language_authority
from .consolidation import consolidate_result_documents
from .registry import EcosystemConfig, load_ecosystem
from .references import parse_scope
from .runtime_paths import plan_is_governed, task_is_governed
from .jobs import JobStore
from .platform_commands import render_sage_command
from .local_assistive import maybe_write_report_executive_summary
from .report_translation import ensure_secondary_saw_report_rendering
from .execution_events import events_for_run


def _report_scope_slug(scope: str) -> str:
    """Render one canonical Scripture scope without altering numeric book codes."""
    parsed = parse_scope(str(scope))
    parts = [parsed.book]
    if parsed.start_chapter is None:
        return parsed.book

    parts.append(f"{parsed.start_chapter:03d}")
    if parsed.start_verse is None:
        end_chapter = parsed.end_chapter or parsed.start_chapter
        if end_chapter != parsed.start_chapter:
            parts.append(f"{end_chapter:03d}")
        return "-".join(parts)

    parts.append(f"{parsed.start_verse:03d}")
    end_chapter = parsed.end_chapter or parsed.start_chapter
    end_verse = parsed.end_verse or parsed.start_verse
    if (end_chapter, end_verse) != (parsed.start_chapter, parsed.start_verse):
        if end_chapter != parsed.start_chapter:
            parts.append(f"{end_chapter:03d}")
        parts.append(f"{end_verse:03d}")
    return "-".join(parts)


def _report_book_code(scope: str) -> str:
    """Return the canonical uppercase book component used as a report subdirectory."""
    return parse_scope(str(scope)).book


def _job_root_from_plan(plan_path: Path) -> Path:
    """Resolve the owning Job directory from a canonical Run plan path."""
    run_root = plan_path.parent.parent
    if plan_path.parent.name != "plans" or run_root.parent.name != "runs":
        raise ValidationError("SAW report plan is not inside a canonical Job Run")
    job_root = run_root.parent.parent
    if job_root.parent.name != "saw" or job_root.parent.parent.name != "jobs":
        raise ValidationError("SAW report plan is not owned by a canonical SAW Job")
    return job_root


def _job_reports_root(plan_path: Path) -> Path:
    """Resolve the owning Job's polished Operator report catalog.

    Canonical Job paths live below ``localdata/work/jobs/<tool>/<job>``. Reports are a
    top-level Operator-owned collection below the same data root, so this resolution
    must not infer a Core checkout from the Job path. That also keeps custom
    ``SAGE_DATA_HOME`` locations portable.
    """
    job_root = _job_root_from_plan(plan_path)
    work_root = job_root.parent.parent.parent
    if work_root.name != "work":
        raise ValidationError("SAW Job is not inside the canonical localdata work root")
    data_root = work_root.parent
    return data_root / "reports" / job_root.name


def _report_paths_owned_by_other_plans(plan_path: Path) -> set[Path]:
    """Return report paths referenced by other finalized plans in the same Job."""
    job_root = _job_root_from_plan(plan_path)
    owned: set[Path] = set()
    for candidate in (job_root / "runs").glob("*/plans/*.json"):
        if candidate.resolve() == plan_path.resolve():
            continue
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("status") != "FINALIZED":
            continue
        for key in ("report_path", "operator_note_text_path", "consolidated_data_path"):
            raw = str(value.get(key) or "").strip()
            if raw:
                owned.add(Path(raw).expanduser().resolve())
        for key in ("report_paths", "operator_note_text_paths", "consolidated_data_paths"):
            for raw in value.get(key, []) if isinstance(value.get(key), list) else []:
                text = str(raw or "").strip()
                if text:
                    owned.add(Path(text).expanduser().resolve())
    return owned


def _report_scope_parts(scope: str) -> tuple[str, ...]:
    """Return the minimal directory parts for one canonical Operator report scope."""
    return (_report_book_code(scope),)


def _append_parts(root: Path, parts: tuple[str, ...]) -> Path:
    """Append governed path parts while rejecting adjacent duplicate directory names."""
    result = root
    previous = result.name.casefold() if result.name else ""
    for part in parts:
        value = str(part).strip()
        if not value:
            raise ValidationError("Generated path contains an empty directory segment")
        if value.casefold() == previous:
            continue
        result = result / value
        previous = value.casefold()
    return result


def _report_scope_root(plan_path: Path, scope: str) -> Path:
    """Return the polished report folder without repeated Book/scope directory segments."""
    return _append_parts(_job_reports_root(plan_path), _report_scope_parts(scope))


def _legacy_nested_scope_root(root: Path, scope: str) -> Path:
    """Return the pre-normalization Book/scope directory used by older report layouts."""
    return root / _report_book_code(scope) / _report_scope_slug(scope)


def _prune_empty_generated_directory(path: Path, *, stop: Path) -> None:
    """Remove empty generated directories up to but never including the governed stop root."""
    current = path
    stop_resolved = stop.resolve()
    while current.exists() and current.resolve() != stop_resolved:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _reference_chapter(value: str) -> int | None:
    """Return the first chapter encoded in one canonical Scripture reference."""
    try:
        return parse_scope(str(value)).start_chapter
    except ValidationError:
        return None


def _report_chapters(document: dict[str, Any], requested_scope: str) -> list[int]:
    """Return the ordered chapter inventory represented by a finalized SAW result."""
    chapters: set[int] = set()
    for value in list((document.get("coverage") or {}).get("reviewed_references", [])):
        chapter = _reference_chapter(str(value))
        if chapter is not None:
            chapters.add(chapter)
    for row in document.get("findings", []):
        if isinstance(row, dict):
            chapter = _reference_chapter(str(row.get("target_reference") or ""))
            if chapter is not None:
                chapters.add(chapter)
    parsed = parse_scope(requested_scope)
    if not chapters and parsed.start_chapter is not None:
        end = parsed.end_chapter or parsed.start_chapter
        chapters.update(range(parsed.start_chapter, end + 1))
    if not chapters:
        # Whole-book results should normally expose coordinate coverage. Keep a safe
        # single-chapter fallback for one-chapter books rather than omitting reports.
        chapters.add(1)
    return sorted(chapters)


def _row_in_chapter(row: dict[str, Any], chapter: int, *, field: str = "target_reference") -> bool:
    """Return whether one report row starts in the requested chapter."""
    return _reference_chapter(str(row.get(field) or "")) == chapter


def _chapter_document(document: dict[str, Any], *, book: str, chapter: int) -> dict[str, Any]:
    """Project one consolidated SAW document into one Operator-facing chapter document."""
    result = dict(document)
    findings = [
        dict(row) for row in document.get("findings", [])
        if isinstance(row, dict) and _row_in_chapter(row, chapter)
    ]
    coverage = [
        str(value) for value in list((document.get("coverage") or {}).get("reviewed_references", []))
        if _reference_chapter(str(value)) == chapter
    ]
    advisories = [
        dict(row) for row in document.get("versification_advisories", [])
        if isinstance(row, dict) and _reference_chapter(str(row.get("scope") or row.get("reference") or "")) == chapter
    ]
    events: list[dict[str, Any]] = []
    for row in document.get("execution_events", []):
        if not isinstance(row, dict):
            continue
        coordinate = str(row.get("work_unit_scope") or row.get("requested_scope") or "")
        event_chapter = _reference_chapter(coordinate)
        if event_chapter in {None, chapter}:
            events.append(dict(row))
    result["scope"] = f"{book} {chapter}"
    result["coverage"] = {"status": "COMPLETE", "reviewed_references": coverage}
    result["findings"] = findings
    result["finding_count"] = len(findings)
    chapter_finding_ids = {str(row.get("finding_id") or "") for row in findings}
    receipts: list[dict[str, Any]] = []
    for row in document.get("review_receipts", []):
        if not isinstance(row, dict):
            continue
        refs = [str(value) for value in row.get("reviewed_references", []) if _reference_chapter(str(value)) == chapter]
        if refs:
            item = dict(row)
            item["reviewed_references"] = refs
            receipts.append(item)
    result["review_receipts"] = receipts
    result["ol_review_requests"] = [
        dict(row) for row in document.get("ol_review_requests", [])
        if isinstance(row, dict) and _row_in_chapter(row, chapter)
    ]
    result["ol_resolutions"] = [
        dict(row) for row in document.get("ol_resolutions", [])
        if isinstance(row, dict) and _row_in_chapter(row, chapter)
    ]
    result["resolved_ol_request_ids"] = [
        str(row.get("request_id") or "") for row in result["ol_resolutions"]
        if str(row.get("request_id") or "").strip()
    ]
    result["structural_adjudications"] = [
        dict(row) for row in document.get("structural_adjudications", [])
        if isinstance(row, dict) and str(row.get("finding_id") or "") in chapter_finding_ids
    ]
    result["work_units"] = [
        dict(row) for row in document.get("work_units", [])
        if isinstance(row, dict) and _reference_chapter(str(row.get("scope") or "")) == chapter
    ]
    result["versification_advisories"] = advisories
    result["execution_events"] = events
    # Secondary renderings are regenerated per chapter so their finding inventory is exact.
    result.pop("report_renderings", None)
    return result


def _chapter_bundle_paths(
    plan_path: Path,
    *,
    book: str,
    chapter: int,
    report_id: str,
) -> tuple[Path, Path, Path]:
    """Return chapter paths that expose the SAW report/operation identity."""
    job_root = _job_root_from_plan(plan_path)
    reports_root = _append_parts(_job_reports_root(plan_path), (book,))
    report_data_root = _append_parts(job_root / "report_data", (book,))
    reports_root.mkdir(parents=True, exist_ok=True)
    report_data_root.mkdir(parents=True, exist_ok=True)
    operation = str(report_id or "").strip().upper()
    if operation not in {"RTC", "STC"}:
        raise ValidationError(f"Unsupported SAW report ID: {report_id!r}")
    base = f"{book}_{chapter:03d}_{operation}"
    return (
        reports_root / f"{base}_ACTION-REPORT.md",
        reports_root / f"{base}_OPERATOR-NOTE.txt",
        report_data_root / f"{base}_CONSOLIDATED.json",
    )


def _write_chapter_report_bundles(
    config: EcosystemConfig,
    plan_path: Path,
    documents: list[dict[str, Any]],
    source_paths: list[Path],
    *,
    requested_scope: str,
) -> dict[str, Any]:
    """Write reports by projecting raw result documents to one chapter before consolidation."""
    book = _report_book_code(requested_scope)
    chapters = sorted(
        {
            chapter
            for document in documents
            for chapter in _report_chapters(
                document, str(document.get("scope") or requested_scope)
            )
        }
    )
    report_paths: list[str] = []
    note_paths: list[str] = []
    data_paths: list[str] = []
    for chapter in chapters:
        chapter_pairs = [
            (document, source_path)
            for document, source_path in zip(documents, source_paths, strict=True)
            if chapter
            in _report_chapters(document, str(document.get("scope") or requested_scope))
        ]
        chapter_sources = [
            _chapter_document(document, book=book, chapter=chapter)
            for document, _ in chapter_pairs
        ]
        chapter_paths = [source_path for _, source_path in chapter_pairs]
        chapter_doc = consolidate_result_documents(chapter_sources, source_paths=chapter_paths)
        authority = report_language_authority(
            config.human_output.logs_and_reports,
            operator_language=config.human_output.operator_language,
        )
        if authority:
            chapter_doc["language_authority"] = authority
        report_path, note_path, data_path = _chapter_bundle_paths(
            plan_path,
            book=book,
            chapter=chapter,
            report_id=str(chapter_doc.get("operation") or ""),
        )
        chapter_doc = ensure_secondary_saw_report_rendering(config.root, report_path, chapter_doc)
        markdown = render_action_report(chapter_doc)
        atomic_write_text(report_path, markdown)
        atomic_write_text(note_path, render_plain_text_from_markdown(markdown))
        atomic_write_json(data_path, chapter_doc)
        report_paths.append(str(report_path))
        note_paths.append(str(note_path))
        data_paths.append(str(data_path))
    return {
        "report_directory": str(_append_parts(_job_reports_root(plan_path), (book,))),
        "report_paths": report_paths,
        "operator_note_text_paths": note_paths,
        "consolidated_data_paths": data_paths,
        "report_path": report_paths[0] if report_paths else None,
        "operator_note_text_path": note_paths[0] if note_paths else None,
        "consolidated_data_path": data_paths[0] if data_paths else None,
    }



def _chapter_result_documents(
    plan_path: Path,
    scope: str,
    *,
    current_path: Path | None = None,
    current_document: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Load every finalized raw result for the same Job and Scripture book."""
    job_root = _job_root_from_plan(plan_path)
    requested_book = parse_scope(scope).book
    rows: list[tuple[Path, dict[str, Any]]] = []
    current_resolved = current_path.resolve() if current_path is not None else None
    for candidate in sorted((job_root / "runs").glob("*/plans/*.json")):
        try:
            plan = _load_object(candidate, "finalized Job report plan")
        except ValidationError:
            continue
        if plan.get("plan_type") != "SAW_RTC_COMPOSITE":
            continue
        if plan.get("status") != "FINALIZED":
            continue
        try:
            candidate_book = parse_scope(str(plan.get("requested_scope") or "")).book
        except ValidationError:
            continue
        if candidate_book != requested_book:
            continue
        raw_path = Path(str(plan.get("aggregate_path", ""))).expanduser()
        if not raw_path.is_absolute():
            work_root = job_root.parent.parent.parent
            raw_path = (work_root.parent / raw_path).resolve()
        else:
            raw_path = raw_path.resolve()
        if not raw_path.is_file() or raw_path == current_resolved:
            continue
        rows.append((raw_path, _load_object(raw_path, "finalized Job result")))
    if current_path is not None and current_document is not None:
        rows.append((current_path.resolve(), dict(current_document)))
    if not rows:
        raise ValidationError("Chapter consolidation found no finalized Job result data")
    return [row[1] for row in rows], [row[0] for row in rows]


def _ensure_finalized_report_layout(
    config: EcosystemConfig,
    path: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Regenerate finalized human reports into the canonical per-chapter layout."""
    job_root = _job_root_from_plan(path)
    requested_scope = str(plan.get("requested_scope") or "SCOPE")
    aggregate_path = Path(str(plan.get("aggregate_path") or "")).expanduser()
    if not aggregate_path.is_absolute():
        aggregate_path = (config.root / aggregate_path).resolve()
    if not aggregate_path.is_file():
        raise ValidationError("Finalized composite RTC plan is missing its aggregate result")
    document = _load_object(aggregate_path, "composite RTC aggregate")
    documents, source_paths = _chapter_result_documents(
        path,
        requested_scope,
        current_path=aggregate_path,
        current_document=document,
    )
    bundle = _write_chapter_report_bundles(
        config, path, documents, source_paths, requested_scope=requested_scope
    )
    canonical = {Path(value).resolve() for key in ("report_paths", "operator_note_text_paths") for value in bundle.get(key, [])}
    other_owned = _report_paths_owned_by_other_plans(path)
    for key in ("report_path", "operator_note_text_path"):
        raw = str(plan.get(key) or "").strip()
        if not raw:
            continue
        legacy = Path(raw).expanduser()
        if not legacy.is_absolute():
            legacy = (config.root / legacy).resolve()
        if legacy.is_file() and legacy.resolve() not in canonical and legacy.resolve() not in other_owned:
            resolved = legacy.resolve()
            reports_root = _job_reports_root(path).resolve()
            plan_root = path.parent.resolve()
            if resolved.is_relative_to(reports_root):
                legacy.unlink()
                _prune_empty_generated_directory(legacy.parent, stop=reports_root)
            elif resolved.is_relative_to(plan_root):
                # Older builds wrote operator-facing artifacts beside the plan JSON.
                legacy.unlink()
    # Remove obsolete report-data files from older nested layouts after canonical regeneration.
    canonical_data = {Path(value).resolve() for value in bundle.get("consolidated_data_paths", [])}
    report_data_root = (job_root / "report_data").resolve()
    legacy_data_values: list[str] = []
    singular_data = str(plan.get("consolidated_data_path") or "").strip()
    if singular_data:
        legacy_data_values.append(singular_data)
    if isinstance(plan.get("consolidated_data_paths"), list):
        legacy_data_values.extend(str(value or "").strip() for value in plan["consolidated_data_paths"])
    for raw in dict.fromkeys(value for value in legacy_data_values if value):
        legacy = Path(raw).expanduser()
        if not legacy.is_absolute():
            legacy = (config.root / legacy).resolve()
        resolved = legacy.resolve()
        if not legacy.is_file() or resolved in canonical_data or resolved in other_owned:
            continue
        try:
            resolved.relative_to(report_data_root)
        except ValueError:
            continue
        legacy.unlink()
        _prune_empty_generated_directory(legacy.parent, stop=report_data_root)

    # Remove obsolete nested report_data directories only when emptied by canonical regeneration.
    report_data_book = job_root / "report_data" / _report_book_code(requested_scope)
    if report_data_book.is_dir():
        for child in sorted(report_data_book.iterdir()):
            if child.is_dir():
                _prune_empty_generated_directory(child, stop=report_data_book)
    plan.update(bundle)
    atomic_write_json(path, plan)
    return plan



def _load_object(path: Path, label: str) -> dict[str, Any]:
    """Load one JSON object with a bounded error surface."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must contain one JSON object")
    return dict(value)


def _continue_partitioned_plan(config: EcosystemConfig, plan_path: Path) -> dict[str, Any]:
    """Return the one next sequential SAW work unit, or the exact aggregation action."""
    path = plan_path.expanduser().resolve()
    if not plan_is_governed(config.workflow("saw"), path):
        raise ValidationError("SAW continuation plan must be inside the governed plans directory")
    plan = _load_object(path, "SAW continuation plan")
    if plan.get("workflow") != "saw":
        raise ValidationError("Only SAW plans can use the sequential continuation helper")
    if plan.get("status") == "FINALIZED":
        publication: dict[str, Any] = {}
        if str(plan.get("operation") or "").lower() == "stc":
            from .stc_reporting import publish_stc_plan_reports

            publication = publish_stc_plan_reports(config, path, plan)
            plan.update(publication)
            atomic_write_json(path, plan)
        return {
            "schema_version": "1.0",
            "status": "COMPLETE",
            "plan_id": plan.get("plan_id"),
            "plan_path": str(path),
            "aggregate_path": plan.get("aggregate_path"),
            **publication,
        }
    if plan.get("status") != "PARTITIONED":
        raise ValidationError("Only PARTITIONED or FINALIZED SAW plans can be continued")
    units = plan.get("work_units")
    if not isinstance(units, list) or not units or any(not isinstance(unit, dict) for unit in units):
        raise ValidationError("SAW plan work_units must be a nonempty list of objects")

    states: list[dict[str, Any]] = []
    first_unfinished: int | None = None
    finalized_after_gap: list[str] = []
    for index, unit in enumerate(units):
        manifest_path = resolve_persisted_path(
            config.root, str(unit.get("manifest_path", "")), "SAW work-unit manifest"
        )
        if not task_is_governed(config.workflow("saw"), manifest_path.parent):
            raise ValidationError("SAW work-unit manifest escapes the governed task root")
        submission_path = manifest_path.parent / "validation" / "submission.json"
        status = "CREATED"
        submission_sha256 = None
        if submission_path.is_file():
            submission = _load_object(submission_path, f"submission for {unit.get('unit_id')}")
            status = str(submission.get("status", "UNKNOWN"))
            submission_sha256 = sha256_file(submission_path)
        finalized = status == "FINALIZED"
        if not finalized and first_unfinished is None:
            first_unfinished = index
        elif finalized and first_unfinished is not None:
            finalized_after_gap.append(str(unit.get("unit_id")))
        states.append(
            {
                "index": index + 1,
                "unit_id": unit.get("unit_id"),
                "task_id": unit.get("task_id"),
                "scope": unit.get("scope"),
                "status": status,
                "manifest_path": str(manifest_path),
                "submission_sha256": submission_sha256,
            }
        )
    if finalized_after_gap:
        raise ValidationError(
            "SAW plan contains finalized work units after an unfinished predecessor",
            code="SAW_SEQUENTIAL_ORDER_VIOLATION",
            next_action="Resolve the earliest unfinished unit before continuing later units.",
            details={"out_of_order_units": finalized_after_gap},
        )
    if first_unfinished is None:
        return {
            "schema_version": "1.0",
            "status": "READY_TO_AGGREGATE",
            "plan_id": plan.get("plan_id"),
            "plan_path": str(path),
            "completed_units": len(states),
            "total_units": len(states),
            "aggregate_command": render_sage_command(["task", "aggregate", "--plan", path]),
            "work_units": states,
        }
    next_unit = states[first_unfinished]
    return {
        "schema_version": "1.0",
        "status": "NEXT_WORK_UNIT",
        "plan_id": plan.get("plan_id"),
        "plan_path": str(path),
        "completed_units": first_unfinished,
        "total_units": len(states),
        "next_unit": next_unit,
        "act_path": str(Path(next_unit["manifest_path"]).parent / "ACT.md"),
        "submit_command": render_sage_command(
            ["task", "submit", "--task", next_unit["manifest_path"]]
        ),
        "work_units": states,
    }


def _composite_stage_result(config: EcosystemConfig, stage: dict[str, Any]) -> tuple[str, str | None, dict[str, Any] | None]:
    """Return state, result path, and continuation details for one composite RTC stage."""
    if stage.get("kind") == "TASK":
        manifest = resolve_persisted_path(
            config.root, str(stage.get("manifest_path", "")), "composite stage manifest"
        )
        submission = manifest.parent / "validation" / "submission.json"
        normalized = manifest.parent / "validation" / "normalized-findings.json"
        if not submission.is_file():
            return "PENDING", None, {
                "schema_version": "1.0",
                "status": "NEXT_WORK_UNIT",
                "next_unit": {
                    "unit_id": stage.get("stage"),
                    "scope": None,
                    "manifest_path": str(manifest),
                },
                "act_path": str(manifest.parent / "ACT.md"),
                "submit_command": render_sage_command(["task", "submit", "--task", manifest]),
            }
        receipt = _load_object(submission, f"submission for {stage.get('stage')}")
        if receipt.get("status") != "FINALIZED" or not normalized.is_file():
            raise ValidationError(f"Composite RTC stage {stage.get('stage')} is not FINALIZED")
        return "FINALIZED", str(normalized), None
    if stage.get("kind") == "PARTITIONED_PLAN":
        child = resolve_persisted_path(
            config.root, str(stage.get("plan_path", "")), "composite stage plan"
        )
        child_plan = _load_object(child, f"partition plan for {stage.get('stage')}")
        if child_plan.get("status") == "FINALIZED":
            aggregate = child_plan.get("aggregate_path")
            if not aggregate:
                raise ValidationError("Finalized partition plan is missing aggregate_path")
            return "FINALIZED", str(aggregate), None
        continuation = _continue_partitioned_plan(config, child)
        if continuation.get("status") == "READY_TO_AGGREGATE":
            continuation["aggregate_plan_path"] = str(child)
        return "PENDING", None, continuation
    raise ValidationError(f"Unsupported composite RTC stage kind: {stage.get('kind')}")




def _run_versification_advisories(plan_path: Path) -> list[dict[str, Any]]:
    """Load non-blocking SAW VRS advisories captured before Run creation."""
    path = plan_path.parent.parent / "diagnostics" / "VERSIFICATION-ADVISORIES.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("advisories", []) if isinstance(payload, dict) else []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _finalize_composite_rtc(config: EcosystemConfig, path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Merge completed RTC stages and render deterministic Operator-facing outputs."""
    findings: list[dict[str, Any]] = []
    adjudications: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    coverage_refs: list[str] = []
    stage_results: list[dict[str, Any]] = []
    execution_sources: list[dict[str, Any]] = []
    ol_review_requests: list[dict[str, Any]] = []
    ol_resolutions: list[dict[str, Any]] = []
    resource_bindings: dict[str, Any] = {}
    resource_display_names: dict[str, Any] = {}
    for stage in plan.get("stages", []):
        state, result_path, _ = _composite_stage_result(config, stage)
        if state != "FINALIZED" or not result_path:
            raise ValidationError("Cannot finalize composite RTC before every created stage is FINALIZED")
        result = _load_object(Path(result_path), f"composite result for {stage.get('stage')}")
        execution_sources.append(result)
        stage_results.append({"stage": stage.get("stage"), "result_path": result_path})
        if not resource_bindings and isinstance(result.get("resource_bindings"), dict):
            resource_bindings = dict(result["resource_bindings"])
        if not resource_display_names and isinstance(result.get("resource_display_names"), dict):
            resource_display_names = dict(result["resource_display_names"])
        refs = list((result.get("coverage") or {}).get("reviewed_references", []))
        if stage.get("stage") == "REFERENCE_TEXT_COMPARISON":
            coverage_refs = refs
        globalized = globalize_result_finding_ids(
            result,
            unit_id=f"{plan['plan_id']}-{stage.get('stage')}",
            run_id=str(plan.get("run_id") or plan.get("plan_id") or "RUN"),
            prefix="SAW",
        )
        receipts.extend(globalized.get("review_receipts", []))
        adjudications.extend(globalized.get("structural_adjudications", []))
        ol_review_requests.extend(globalized.get("ol_review_requests", []))
        ol_resolutions.extend(globalized.get("ol_resolutions", []))
        findings.extend(globalized.get("findings", []))
    validate_global_finding_ids(findings)
    if not coverage_refs:
        raise ValidationError("Composite RTC finalization is missing meaning-stage coordinate coverage")
    document = {
        "schema_version": "2.0",
        "task_id": plan["plan_id"],
        "job_id": plan["job_id"],
        "run_id": plan["run_id"],
        "workflow": "saw",
        "operation": "rtc",
        "ol_referral_contract": plan.get("ol_referral_contract"),
        "resource_bindings": resource_bindings,
        "resource_display_names": resource_display_names,
        "stage": "COMPOSITE_FINALIZED",
        "scope": plan["requested_scope"],
        "focus": None,
        "check_type": None,
        "answer": "",
        "coverage": {"status": "COMPLETE", "reviewed_references": coverage_refs},
        "review_receipts": receipts,
        "structural_adjudications": adjudications,
        "ol_review_requests": ol_review_requests,
        "ol_resolutions": ol_resolutions,
        "resolved_ol_request_ids": [str(row.get("request_id", "")) for row in ol_resolutions],
        "findings": findings,
        "finding_count": len(findings),
        "versification_advisories": _run_versification_advisories(path),
        "execution_events": events_for_run(path.parent.parent),
        "execution_routes": aggregate_execution_routes(execution_sources),
    }
    authority = report_language_authority(
        config.human_output.logs_and_reports,
        operator_language=config.human_output.operator_language,
    )
    if authority:
        document["language_authority"] = authority
    final_path = path.with_name(f"{plan['plan_id']}-final.json")
    atomic_write_json(final_path, document)
    documents, source_paths = _chapter_result_documents(
        path,
        str(plan["requested_scope"]),
        current_path=final_path,
        current_document=document,
    )
    bundle = _write_chapter_report_bundles(
        config, path, documents, source_paths, requested_scope=str(plan["requested_scope"])
    )
    # Optional assistive executive summaries remain bounded to the first chapter report.
    if bundle.get("report_path") and bundle.get("consolidated_data_path"):
        first_chapter = _load_object(Path(str(bundle["consolidated_data_path"])), "chapter report data")
        maybe_write_report_executive_summary(config.root, Path(str(bundle["report_path"])), first_chapter)
    plan["status"] = "FINALIZED"
    plan["aggregate_path"] = str(final_path)
    plan.update(bundle)
    plan["stage_results"] = stage_results
    atomic_write_json(path, plan)
    return {
        "schema_version": "1.0",
        "status": "COMPLETE",
        "plan_id": plan["plan_id"],
        "plan_path": str(path),
        "aggregate_path": str(final_path),
        **bundle,
        "finding_count": len(findings),
        "consolidation_status": "CHAPTER_SCOPED",
    }


def _continue_saw_rtc_composite(config: EcosystemConfig, path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Advance one composite RTC plan by exactly one governed stage/action."""
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages or any(not isinstance(item, dict) for item in stages):
        raise ValidationError("Composite SAW RTC plan has no valid stage inventory")
    current = stages[-1]
    state, result_path, continuation = _composite_stage_result(config, current)
    if state != "FINALIZED":
        assert continuation is not None
        return {**continuation, "plan_id": plan.get("plan_id"), "plan_path": str(path), "composite_stage": current.get("stage")}

    stage_name = str(current.get("stage"))
    expected_requests: list[dict[str, Any]] = []
    stage_references: list[str] = []
    if stage_name == "STRUCTURAL_ADJUDICATION":
        next_stage = "REFERENCE_TEXT_COMPARISON"
        expected_ids: list[str] = []
        predecessor_files = [str(result_path)]
    elif stage_name == "REFERENCE_TEXT_COMPARISON":
        meaning = _load_object(Path(str(result_path)), "SAW RTC meaning-stage result")
        requests = globalize_ol_review_request_ids(
            list(meaning.get("ol_review_requests", [])),
            unit_id=f"{plan['plan_id']}-{stage_name}",
            run_id=str(plan.get("run_id") or plan["plan_id"]),
            prefix="SAW",
        )
        drift_state = str(
            dict((plan.get("rtc_policy") or {}).get("original_language") or {}).get(
                "source_text_drift_adjudication", "PROHIBITED"
            )
        ).upper()
        if requests and drift_state != "ENABLED":
            raise ValidationError(
                "Reference Text Comparison (RTC) emitted original-language review requests while source-text drift adjudication is prohibited",
                code="SAW_OL_REQUEST_PROHIBITED",
                next_action="Retry the same meaning-stage task; do not emit ol_review_requests unless the Run policy enables source-text drift adjudication.",
            )
        if not requests:
            return _finalize_composite_rtc(config, path, plan)
        next_stage = "SELECTIVE_OL_ADJUDICATION"
        expected_requests = [dict(item) for item in requests]
        expected_ids = [str(item.get("request_id", "")).upper() for item in requests]
        stage_references = [str(item.get("target_reference", "")).strip() for item in requests]
        predecessor_files = [
            str(value)
            for value in [
                *[
                    _composite_stage_result(config, row)[1]
                    for row in stages
                    if row.get("stage") == "STRUCTURAL_ADJUDICATION"
                ],
                result_path,
            ]
            if value
        ]
    elif stage_name == "SELECTIVE_OL_ADJUDICATION":
        return _finalize_composite_rtc(config, path, plan)
    else:
        raise ValidationError(f"Unsupported composite RTC stage: {stage_name}")

    from .act_tasks import _stage_record, create_act_task
    result = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id=str(plan["output_project"]),
        contemporary_source_id=str(plan["contemporary_source"]),
        scope_value=str(plan["requested_scope"]),
        grammar_override_id=plan.get("grammar_override_id"),
        auto_partition=True,
        parent_plan_id=str(plan["plan_id"]),
        job_id=str(plan.get("job_id") or plan["job_id"]),
        run_id=str(plan.get("run_id") or plan["run_id"]),
        rtc_stage=next_stage,
        rtc_predecessor_files=predecessor_files,
        expected_ol_request_ids=expected_ids,
        expected_ol_requests=expected_requests,
        rtc_stage_references=stage_references,
        ol_referral_contract=(
            str(plan.get("ol_referral_contract"))
            if plan.get("ol_referral_contract")
            else None
        ),
    )
    new_stage = _stage_record(result, next_stage)
    stages.append(new_stage)
    plan["stages"] = stages
    plan["updated_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(microsecond=0).isoformat()
    atomic_write_json(path, plan)
    new_state, _, new_continuation = _composite_stage_result(config, new_stage)
    if new_state == "FINALIZED":
        raise ValidationError("New composite RTC stage unexpectedly finalized before execution")
    assert new_continuation is not None
    return {**new_continuation, "plan_id": plan.get("plan_id"), "plan_path": str(path), "composite_stage": next_stage}


def continue_saw_plan(config: EcosystemConfig, plan_path: Path) -> dict[str, Any]:
    """Continue either a partitioned SAW plan or the staged composite RTC plan."""
    path = plan_path.expanduser().resolve()
    plan = _load_object(path, "SAW continuation plan")
    job_id = str(plan.get("job_id", "")).strip()
    if not job_id:
        raise ValidationError("SAW continuation plan is missing canonical Job identity")
    store = JobStore(config.root, config.settings_path)
    job = store.load_job(job_id, tool="saw")
    config = load_ecosystem(store.ensure_runtime_files(job))
    if not plan_is_governed(config.workflow("saw"), path):
        raise ValidationError("SAW continuation plan must be inside the governed plans directory")
    if plan.get("plan_type") == "SAW_RTC_COMPOSITE":
        if plan.get("status") == "FINALIZED":
            plan = _ensure_finalized_report_layout(config, path, plan)
            return {
                "schema_version": "1.0",
                "status": "COMPLETE",
                "plan_id": plan.get("plan_id"),
                "plan_path": str(path),
                "aggregate_path": plan.get("aggregate_path"),
                "report_path": plan.get("report_path"),
                "operator_note_text_path": plan.get("operator_note_text_path"),
                "consolidated_data_path": plan.get("consolidated_data_path"),
            }
        return _continue_saw_rtc_composite(config, path, plan)
    return _continue_partitioned_plan(config, path)
