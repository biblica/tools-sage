"""Transparent resolution and reporting for configuration values declared as auto."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canon import resolve_expected_books
from .human_output import paired_catalogue_text, resolved_languages
from .registry import EcosystemConfig
from .vrs import resolve_project_vrs_paths


def resolve_auto_settings(config: EcosystemConfig) -> list[dict[str, Any]]:
    """Return every known ``auto`` declaration with its resolved value and basis."""
    rows: list[dict[str, Any]] = []
    for project_id, project in sorted(config.projects.items()):
        if project.scope.expected_books == "auto":
            books = resolve_expected_books(project.scope)
            rows.append(
                {
                    "project_id": project_id,
                    "setting": f"projects.{project_id}.scope.expected_books",
                    "declared": "auto",
                    "resolved": list(books),
                    "resolved_summary": f"{len(books)} books ({project.scope.testament})",
                    "source": (
                        f"canon registry {project.scope.canon} filtered by "
                        f"testament {project.scope.testament}"
                    ),
                    "confidence": "AUTHORITATIVE",
                    "resolution_status": "ACCEPTED",
                    "override": f"projects.{project_id}.scope.expected_books",
                    "impact": "Changing the book set requires project and workflow revalidation.",
                }
            )
        if project.versification.custom_file.strip().lower() == "auto":
            _, custom_path = resolve_project_vrs_paths(config, project)
            resolved = str(custom_path) if custom_path else None
            rows.append(
                {
                    "project_id": project_id,
                    "setting": f"projects.{project_id}.versification.custom_file",
                    "declared": "auto",
                    "resolved": resolved,
                    "resolved_summary": (
                        Path(resolved).name if resolved else "No project-local custom VRS found"
                    ),
                    "source": (
                        f"project-local discovery using {config.custom_vrs_filename}"
                    ),
                    "confidence": "INFERRED",
                    "resolution_status": (
                        "REVIEW_RECOMMENDED" if custom_path else "ACCEPTED"
                    ),
                    "override": f"projects.{project_id}.versification.custom_file",
                    "impact": "Changing VRS selection requires full coordinate and cache revalidation.",
                }
            )
    return rows


def render_auto_resolution_report(
    config: EcosystemConfig, rows: list[dict[str, Any]]
) -> str:
    """Render a stable report in the configured logs-and-reports language pair."""
    channel = config.human_output.logs_and_reports

    def label(key: str) -> str:
        """Render one approved bilingual label for this report."""
        return paired_catalogue_text(
            channel,
            key,
            operator_language=config.human_output.operator_language,
        )

    languages = resolved_languages(
        channel, operator_language=config.human_output.operator_language
    )
    lines = [
        f"# {label('report.auto_resolution')}",
        "",
        label('report.auto_resolution_intro'),
        label('report.auto_resolution_edit'),
        "",
        (
            f"| {label('label.project')} | {label('label.setting')} | "
            f"{label('label.resolved_value')} | {label('label.source')} | "
            f"{label('label.confidence')} | {label('label.status')} | "
            f"{label('label.override')} |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    if not rows:
        lines.append(
            f"| — | — | {label('label.no_auto_settings')} | — | — | — | — |"
        )
    for row in rows:
        summary = str(row.get('resolved_summary', row.get('resolved'))).replace('|', '\\|')
        source = str(row['source']).replace('|', '\\|')
        lines.append(
            f"| {row['project_id']} | `{row['setting']}` | {summary} | {source} | "
            f"`{row['confidence']}` | `{row['resolution_status']}` | `{row['override']}` |"
        )
    lines.extend(["", f"## {label('label.impact_notes')}", ""])
    for row in rows:
        lines.append(f"- `{row['setting']}`: {row['impact']}")
    lines.extend(
        [
            "",
            f"_{label('label.report_languages')}: {', '.join(languages)}._",
            "",
        ]
    )
    return "\n".join(lines)
