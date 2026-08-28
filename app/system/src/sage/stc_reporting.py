"""Deterministic publication of finalized STC results for Operators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .act_outputs import render_plain_text_from_markdown
from .atomic import atomic_write_json, atomic_write_text
from .errors import ValidationError
from .human_output import (
    catalogue_text,
    render_report_language_authority,
    report_language_authority,
)
from .references import parse_scope
from .registry import EcosystemConfig
from .report_translation import ensure_secondary_saw_report_rendering
from .storage import resolve_persisted_path, storage_layout


def _load_object(path: Path, label: str) -> dict[str, Any]:
    """Load one JSON object with a report-specific validation boundary."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must contain one JSON object")
    return dict(value)


def _chapter(value: str) -> int | None:
    """Return the starting chapter for one canonical Scripture coordinate."""
    try:
        return parse_scope(str(value)).start_chapter
    except ValidationError:
        return None


def _finding_sort_key(row: Mapping[str, Any]) -> tuple[int, int, int, str]:
    """Sort STC findings in canonical chapter/verse order, then by stable identity."""
    try:
        scope = parse_scope(str(row.get("target_reference") or ""))
        return (
            scope.start_chapter or 0,
            scope.start_verse or 0,
            scope.end_verse or scope.start_verse or 0,
            str(row.get("finding_id") or ""),
        )
    except ValidationError:
        return (999, 999, 999, str(row.get("finding_id") or ""))


def _resource_names(
    bindings: Mapping[str, Any],
    declared_names: Mapping[str, Any],
) -> dict[str, str]:
    """Preserve sealed display names while retaining stable Project-ID fallbacks."""
    names: dict[str, str] = {}
    for role, raw_project_id in bindings.items():
        project_id = str(raw_project_id or "").strip()
        if not project_id:
            continue
        names[str(role)] = str(declared_names.get(role) or project_id)
    return names


def _stc_report_markdown(document: Mapping[str, Any]) -> str:
    """Render a human STC report without pretending STC findings are RTC actions."""
    authority = document.get("language_authority")
    primary = str(document.get("report_language") or "en").strip() or "en"
    secondary = ""
    if isinstance(authority, Mapping):
        primary = str(authority.get("primary_language") or primary).strip() or primary
        secondary = str(authority.get("secondary_language") or "").strip()
    renderings = document.get("report_renderings")
    secondary_rows: Mapping[str, Any] = {}
    rendering_status = ""
    if isinstance(renderings, Mapping):
        rendering_status = str(renderings.get("status") or "").upper()
        if isinstance(renderings.get("findings"), Mapping):
            secondary_rows = renderings["findings"]

    bindings = document.get("resource_bindings")
    bindings = bindings if isinstance(bindings, Mapping) else {}
    names = document.get("resource_display_names")
    names = names if isinstance(names, Mapping) else {}
    wip_id = str(bindings.get("WIP") or document.get("output_project") or "WIP")
    wip_name = str(names.get("WIP") or wip_id)
    ol_role = (
        "ORIGINAL_LANGUAGE_GREEK"
        if str(document.get("authority_family") or "").upper() == "GRK"
        else "ORIGINAL_LANGUAGE_HEBREW"
    )
    ol_id = str(bindings.get(ol_role) or document.get("primary_ol_authority") or document.get("authority_family") or "SRC")
    ol_name = str(names.get(ol_role) or ol_id)
    coverage = list(document.get("primary_coverage") or [])
    findings = [dict(row) for row in document.get("findings", []) if isinstance(row, Mapping)]
    findings.sort(key=_finding_sort_key)

    lines = [
        "# Source Text Correspondence (STC) Report",
        "",
        f"- Sources: `{wip_name}` checked against `{ol_name} OL`",
        f"- Scope: `{document.get('scope', '')}`",
        f"- Coverage: `COMPLETE` ({len(coverage)} coordinates)",
        f"- Report languages: `{primary}`" + (f"; `{secondary}`" if secondary else ""),
    ]
    notice = render_report_language_authority(authority if isinstance(authority, Mapping) else None, markdown=True)
    if notice:
        lines.extend(["", notice])
    if secondary and rendering_status == "DEGRADED":
        lines.extend(["", f"> **{catalogue_text(primary, 'message.secondary_rendering_unavailable')}**"])
        translated_notice = catalogue_text(secondary, "message.secondary_rendering_unavailable")
        if translated_notice != catalogue_text(primary, "message.secondary_rendering_unavailable"):
            lines.append(f"> **{translated_notice}**")
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("No governed STC findings were reported. All planned STC review items completed.")
    for position, finding in enumerate(findings):
        finding_id = str(finding.get("finding_id") or "STC finding")
        secondary_row = secondary_rows.get(finding_id) if secondary else None
        lines.extend([
            f"### {finding_id} — {finding.get('target_reference', '')}",
            "",
            f"- Category: `{finding.get('category', '')}`",
            f"- Authority: `{document.get('authority_family', '')} OL` (`PRIMARY`)",
            "",
            f"**Summary — {primary}**",
            "",
            str(finding.get("summary") or ""),
            "",
        ])
        if isinstance(secondary_row, Mapping) and str(secondary_row.get("issue") or "").strip():
            lines.extend([
                f"**Summary — {secondary}**",
                "",
                str(secondary_row.get("issue") or "").strip(),
                "",
            ])
        lines.extend([
            f"**{wip_id} evidence**",
            "",
            str(finding.get("wip_evidence") or ""),
            "",
            f"**{ol_id} OL evidence**",
            "",
            str(finding.get("ol_evidence") or ""),
            "",
        ])
        if position != len(findings) - 1:
            lines.extend(["---", ""])
    return "\n".join(lines).rstrip() + "\n"


def publish_stc_reports(
    config: EcosystemConfig,
    *,
    job_id: str,
    run_id: str,
    requested_scope: str,
    results: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Publish one separate STC report bundle per represented Scripture chapter."""
    documents = [dict(row) for row in results]
    if not documents or any(str(row.get("operation") or "").lower() != "stc" for row in documents):
        raise ValidationError("STC report publication requires finalized STC result documents")
    parsed_scope = parse_scope(requested_scope)
    book = parsed_scope.book
    identities = {
        (
            str(row.get("job_id") or ""),
            str(row.get("run_id") or ""),
            str(row.get("output_project") or ""),
            str(row.get("primary_ol_authority") or ""),
            str(row.get("authority_family") or "").upper(),
        )
        for row in documents
    }
    if len(identities) != 1:
        raise ValidationError("STC report results do not share one governed Job/Run/resource identity")
    result_job, result_run, output_project, ol_authority, family = next(iter(identities))
    if result_job != job_id or result_run != run_id or family not in {"GRK", "HEB"}:
        raise ValidationError("STC report identity differs from its governed publication request")

    coverage = [str(value) for row in documents for value in row.get("primary_coverage", [])]
    chapters = sorted({chapter for value in coverage if (chapter := _chapter(value)) is not None})
    if not chapters:
        raise ValidationError("STC report publication has no canonical chapter coverage")
    all_findings = [dict(value) for row in documents for value in row.get("findings", []) if isinstance(value, Mapping)]
    finding_ids = [str(row.get("finding_id") or "") for row in all_findings]
    if not all(finding_ids) or len(finding_ids) != len(set(finding_ids)):
        raise ValidationError("STC report publication received duplicate or missing finding identity")

    layout = storage_layout(config.root)
    report_root = layout.reports_root / job_id / book
    data_root = layout.jobs_root / "saw" / job_id / "report_data" / book
    report_root.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    authority = report_language_authority(
        config.human_output.logs_and_reports,
        operator_language=config.human_output.operator_language,
    )
    report_paths: list[str] = []
    note_paths: list[str] = []
    data_paths: list[str] = []
    for chapter in chapters:
        chapter_coverage = [value for value in coverage if _chapter(value) == chapter]
        chapter_findings = [row for row in all_findings if _chapter(str(row.get("target_reference") or "")) == chapter]
        first = next(row for row in documents if any(_chapter(str(value)) == chapter for value in row.get("primary_coverage", [])))
        bindings = dict(first.get("resource_bindings") or {})
        ol_role = "ORIGINAL_LANGUAGE_GREEK" if family == "GRK" else "ORIGINAL_LANGUAGE_HEBREW"
        bindings.setdefault("WIP", output_project)
        bindings.setdefault(ol_role, ol_authority)
        projected_findings = [
            {
                **row,
                "issue": str(row.get("summary") or ""),
                "required_action": "",
                "evidence_ids": ["WIP", ol_role],
            }
            for row in chapter_findings
        ]
        document: dict[str, Any] = {
            "schema_version": "1.0",
            "operation": "stc",
            "job_id": job_id,
            "run_id": run_id,
            "scope": f"{book} {chapter}",
            "output_project": output_project,
            "primary_ol_authority": ol_authority,
            "authority_family": family,
            "authority_role": "PRIMARY",
            "report_language": str(first.get("report_language") or config.human_output.operator_language),
            "resource_bindings": bindings,
            "resource_display_names": _resource_names(
                bindings,
                dict(first.get("resource_display_names") or {}),
            ),
            "primary_coverage": chapter_coverage,
            "finding_count": len(projected_findings),
            "findings": projected_findings,
        }
        if authority:
            document["language_authority"] = authority
        base = f"{book}_{chapter:03d}_STC"
        report_path = report_root / f"{base}-REPORT.md"
        note_path = report_root / f"{base}-OPERATOR-NOTE.txt"
        data_path = data_root / f"{base}-CONSOLIDATED.json"
        document = ensure_secondary_saw_report_rendering(config.root, report_path, document)
        markdown = _stc_report_markdown(document)
        atomic_write_text(report_path, markdown)
        atomic_write_text(note_path, render_plain_text_from_markdown(markdown))
        atomic_write_json(data_path, document)
        report_paths.append(str(report_path))
        note_paths.append(str(note_path))
        data_paths.append(str(data_path))
    return {
        "report_directory": str(report_root),
        "report_paths": report_paths,
        "operator_note_text_paths": note_paths,
        "consolidated_data_paths": data_paths,
        "report_path": report_paths[0],
        "operator_note_text_path": note_paths[0],
        "consolidated_data_path": data_paths[0],
    }


def publish_stc_task_reports(config: EcosystemConfig, manifest_path: Path) -> dict[str, Any]:
    """Publish or regenerate the report for an already-finalized standalone STC task."""
    manifest = _load_object(manifest_path, "STC task manifest")
    normalized = _load_object(manifest_path.parent / "validation" / "normalized-findings.json", "STC normalized findings")
    return publish_stc_reports(
        config,
        job_id=str(manifest.get("job_id") or ""),
        run_id=str(manifest.get("run_id") or ""),
        requested_scope=str(manifest.get("scope") or ""),
        results=[normalized],
    )


def publish_stc_plan_reports(
    config: EcosystemConfig,
    plan_path: Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish or regenerate reports for an already-finalized partitioned STC plan."""
    results: list[dict[str, Any]] = []
    for unit in plan.get("work_units", []):
        if not isinstance(unit, Mapping):
            raise ValidationError("STC report plan contains an invalid work unit")
        manifest = resolve_persisted_path(
            config.root,
            str(unit.get("manifest_path") or ""),
            "STC report work-unit manifest",
        )
        results.append(_load_object(manifest.parent / "validation" / "normalized-findings.json", "STC normalized findings"))
    return publish_stc_reports(
        config,
        job_id=str(plan.get("job_id") or ""),
        run_id=str(plan.get("run_id") or ""),
        requested_scope=str(plan.get("requested_scope") or ""),
        results=results,
    )
