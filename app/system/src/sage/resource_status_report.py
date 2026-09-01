"""Read-only inventory and structural status report for SAGE Scripture resources."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .errors import SageError
from .jobs import Job, JobStore
from .original_language_resources import active_ol_provenance
from .project_inventory import registered_project_records
from .registry import load_ecosystem
from .scripture import discover_book_ids
from .storage import StorageError, resolve_persisted_path, storage_layout

_VERSE_RE = re.compile(rb"(?m)^\\v[ \t]+")


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, dict) else None


def _project_fingerprint(path: Path) -> str | None:
    """Fingerprint readable top-level USFM without writing caches or resource state."""
    if not path.is_dir():
        return None
    digest = hashlib.sha256()
    found = False
    try:
        entries = sorted(path.iterdir(), key=lambda value: value.name.casefold())
    except OSError:
        return None
    for source in entries:
        if not source.is_file() or source.suffix.casefold() != ".sfm":
            continue
        try:
            payload = source.read_bytes()
        except OSError:
            continue
        found = True
        digest.update(source.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest() if found else None


def _coverage(path: Path) -> dict[str, Any]:
    try:
        books = discover_book_ids(path) if path.is_dir() else {}
    except OSError:
        books = {}
    coordinates = 0
    for source in books.values():
        try:
            coordinates += len(_VERSE_RE.findall(source.read_bytes()))
        except OSError:
            continue
    return {
        "books": sorted(books),
        "book_count": len(books),
        "verse_markers": coordinates,
    }


def _active_analysis_jobs(store: JobStore) -> tuple[list[Job], list[dict[str, Any]]]:
    jobs: list[Job] = []
    issues: list[dict[str, Any]] = []
    active = store.active_jobs()
    for tool in ("rtc", "stc"):
        report = store.discover_report(tool, include_archived=False)
        issues.extend(
            {
                "job_id": item.job_id,
                "tool": item.tool.upper(),
                "status": "ACTION_NEEDED",
                "code": item.code,
                "message": item.message,
                "next_action": item.next_action,
            }
            for item in report.issues
        )
        selected = active.get(tool)
        if selected:
            jobs.extend(job for job in report.jobs if job.job_id == selected)
    return jobs, issues


def _job_roles(jobs: list[Job]) -> tuple[dict[str, list[str]], dict[str, list[dict[str, Any]]]]:
    roles: dict[str, list[str]] = {}
    snapshots: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        wip = str(job.bindings.get("wip") or "")
        if wip:
            roles.setdefault(wip, []).append(f"{job.tool.upper()} WIP")
            snapshot = dict(job.wip_snapshot or {})
            snapshots.setdefault(wip, []).append(
                {
                    "job_id": job.job_id,
                    "snapshot_date": snapshot.get("snapshot_date"),
                    "fingerprint": snapshot.get("content_fingerprint"),
                    "source_location": snapshot.get("source_location"),
                }
            )
        reference = str(job.bindings.get("reference") or "")
        if reference:
            roles.setdefault(reference, []).append(f"{job.tool.upper()} REFERENCE")
        if job.tool == "stc":
            roles.setdefault("GRK", []).append("STC ORIGINAL-LANGUAGE AUTHORITY")
            roles.setdefault("HEB", []).append("STC ORIGINAL-LANGUAGE AUTHORITY")
    return roles, snapshots


def _run_structure_issues(store: JobStore, jobs: list[Job]) -> dict[str, list[dict[str, Any]]]:
    by_project: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        for run in store.list_runs(job, include_archived=True):
            diagnostic = _read_object(
                run.root / "diagnostics" / "VERSIFICATION-ADVISORIES.json"
            )
            candidates: list[Mapping[str, Any]] = []
            if diagnostic and isinstance(diagnostic.get("advisories"), list):
                candidates.extend(
                    row for row in diagnostic["advisories"] if isinstance(row, Mapping)
                )
            for manifest_value in run.task_manifests:
                try:
                    manifest = resolve_persisted_path(
                        store.sage_root,
                        manifest_value,
                        "resource report task manifest",
                    )
                except (OSError, SageError, StorageError):
                    continue
                normalized = _read_object(
                    manifest.parent / "validation" / "normalized-findings.json"
                )
                if not normalized:
                    continue
                raw_rows = normalized.get(
                    "structural_issues", normalized.get("source_text_issues", [])
                )
                if isinstance(raw_rows, list):
                    candidates.extend(row for row in raw_rows if isinstance(row, Mapping))
            for candidate in candidates:
                row = dict(candidate)
                project_id = str(
                    row.get("project_id")
                    or row.get("source_project_id")
                    or row.get("wip_project_id")
                    or job.bindings.get("wip")
                    or ""
                )
                if project_id:
                    row.setdefault("run_id", run.run_id)
                    by_project.setdefault(project_id, []).append(row)
    return by_project


def build_resource_status_report(
    root: Path,
    *,
    settings_path: Path | None = None,
) -> dict[str, Any]:
    """Build a non-mutating resource inventory; isolate each expected resource defect."""
    sage_root = root.expanduser().resolve()
    settings = (settings_path or sage_root / "ecosystem.yml").expanduser().resolve()
    config = load_ecosystem(settings)
    layout = storage_layout(sage_root)
    store = JobStore(sage_root, settings)
    jobs, job_issues = _active_analysis_jobs(store)
    roles, snapshots = _job_roles(jobs)
    structural = _run_structure_issues(store, jobs)
    inventory = registered_project_records(sage_root)
    raw_projects = config.raw.get("projects", {})
    raw_projects = raw_projects if isinstance(raw_projects, Mapping) else {}
    ol = active_ol_provenance(sage_root)

    project_ids = set(config.projects) | set(inventory) | {"GRK", "HEB"}
    resources: list[dict[str, Any]] = []
    for project_id in sorted(project_ids):
        project = config.projects.get(project_id)
        record = dict(inventory.get(project_id) or {})
        raw = raw_projects.get(project_id)
        raw = dict(raw) if isinstance(raw, Mapping) else {}
        ol_row = dict(ol.get(project_id) or {})
        if project is not None:
            source_location = project.path
            content_state = project.content_state
            versification = {
                "base": project.versification.base,
                "custom": project.versification.custom,
            }
            configured_roles = list(project.scope.roles)
            allow_empty = project.allow_empty
        else:
            external = record.get("external_path") or ol_row.get("path")
            source_location = (
                Path(str(external)).expanduser()
                if external
                else layout.projects_root / str(record.get("path") or project_id)
            )
            content_state = str(record.get("content_state") or "LOCKED")
            vrs = record.get("versification")
            vrs = dict(vrs) if isinstance(vrs, Mapping) else {}
            versification = {
                "base": vrs.get("base_file") or "org.vrs" if project_id in {"GRK", "HEB"} else vrs.get("base_file"),
                "custom": vrs.get("custom_file") or "auto",
            }
            scope = record.get("scope")
            scope = dict(scope) if isinstance(scope, Mapping) else {}
            configured_roles = list(scope.get("roles") or [])
            allow_empty = bool(record.get("allow_empty", False))
        source_location = source_location.expanduser().resolve()
        coverage = _coverage(source_location)
        row_issues = list(structural.get(project_id, []))
        next_action = ""
        if not source_location.is_dir():
            status = "ACTION_NEEDED"
            next_action = "Restore or correct this Project/resource source location."
        elif not coverage["books"] and not allow_empty:
            status = "ACTION_NEEDED"
            next_action = "Add readable canonical USFM Books or correct the Project mapping."
        elif row_issues:
            status = "READY_WITH_STRUCTURE_PROBLEMS"
            next_action = "Review the listed structural coordinates in the authoritative Project."
        else:
            status = "READY"
        authority = None
        if project_id in {"GRK", "HEB"}:
            authority = {
                "identity": project_id,
                "role": "PRIMARY",
                "fingerprint": _project_fingerprint(source_location),
                "provenance": ol_row,
            }
        display_name = str(
            record.get("display_name")
            or raw.get("display_name")
            or ol_row.get("display_name")
            or project_id
        )
        resources.append(
            {
                "project_id": project_id,
                "display_name": display_name,
                "source_location": str(source_location),
                "roles": sorted(set(roles.get(project_id, []) or configured_roles)) or ["UNBOUND"],
                "content_state": content_state,
                "books": coverage["books"],
                "coverage": coverage,
                "versification": versification,
                "snapshot": snapshots.get(project_id, []),
                "authority": authority,
                "structural_issues": row_issues,
                "status": status,
                "next_action": next_action,
            }
        )

    statuses = {row["status"] for row in resources}
    overall = (
        "ACTION_NEEDED"
        if job_issues or "ACTION_NEEDED" in statuses
        else "READY_WITH_STRUCTURE_PROBLEMS"
        if "READY_WITH_STRUCTURE_PROBLEMS" in statuses
        else "READY"
    )
    return {
        "schema_version": "1.0",
        "status": overall,
        "active_jobs": [job.job_id for job in jobs],
        "job_issues": job_issues,
        "resources": resources,
    }


def render_resource_status_report(report: Mapping[str, Any]) -> str:
    """Render a compact, actionable Operator view of the resource inventory."""
    lines = [
        "SAGE RESOURCE STATUS REPORT",
        "=" * 72,
        f"Status: {report.get('status', 'ACTION_NEEDED')}",
        "",
    ]
    for row in report.get("resources", []):
        if not isinstance(row, Mapping):
            continue
        lines.extend(
            [
                f"{row.get('project_id')} — {row.get('display_name')}",
                f"  Status: {row.get('status')}",
                f"  Roles: {', '.join(str(value) for value in row.get('roles', []))}",
                f"  Source: {row.get('source_location')}",
                f"  Content state: {row.get('content_state')}",
                f"  Books: {', '.join(str(value) for value in row.get('books', [])) or 'NONE'}",
                f"  Versification: {dict(row.get('versification') or {}).get('base')}; custom={dict(row.get('versification') or {}).get('custom')}",
            ]
        )
        for snapshot in row.get("snapshot", []):
            lines.append(
                f"  Snapshot: {snapshot.get('job_id')} | {snapshot.get('snapshot_date')} | {snapshot.get('fingerprint')}"
            )
        authority = row.get("authority")
        if isinstance(authority, Mapping):
            lines.append(
                f"  Authority: {authority.get('identity')} ({authority.get('role')}) | {authority.get('fingerprint') or 'NOT RECORDED'}"
            )
        for issue in row.get("structural_issues", []):
            lines.append(
                f"  Structure: {issue.get('reference') or issue.get('scope') or 'UNSCOPED'} | "
                f"{issue.get('code') or issue.get('structure_status') or 'STRUCTURE_PROBLEM'} — "
                f"{issue.get('message') or ''}"
            )
        if row.get("next_action"):
            lines.append(f"  Next action: {row.get('next_action')}")
        lines.append("")
    for issue in report.get("job_issues", []):
        lines.extend(
            [
                f"Job {issue.get('job_id')} — ACTION_NEEDED",
                f"  {issue.get('code')}: {issue.get('message')}",
                f"  Next action: {issue.get('next_action') or 'Manage the Job bindings.'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
