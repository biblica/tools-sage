"""Read-only Job-layout audit and evidence-preserving legacy-layout migration."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .atomic import atomic_write_json, atomic_write_text
from .errors import ValidationError
from .hashing import sha256_bytes, sha256_file
from .storage import storage_layout

SCHEMA_VERSION = "1.0"
CANONICAL_JOB_DIRS = {
    "runs",
    "diagnostics",
    "exports",
}
CANONICAL_SAGE_DIRS = {"state", "locks", "transactions", "indexes", "cache"}
BIC_JOB_DIRS = {"memory", "generations", "target-history", "report_data"}
SAW_JOB_DIRS = {"report_data"}
CANONICAL_RUN_DIRS = {"tasks", "plans", "diagnostics"}
RESERVED_RUN_DIRS: set[str] = set()
UNUSED_JOB_DIRS = {"archive"}
UNUSED_SAGE_DIRS = {"workspace_data"}
UNUSED_RUN_DIRS = {"operator-note-text", "decisions", "findings"}
CURRENT_RUN_REPORT_NAMES = {"VERSIFICATION-ADVISORIES.json", "EXECUTION-EVENTS.jsonl", "BLOCK-REPORT.md"}


def _utc_now() -> str:
    """Return one stable audit/migration timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tree_stats(path: Path) -> tuple[int, int]:
    """Return file count and byte size below one path without following symlinks."""
    if not path.exists():
        return 0, 0
    if path.is_file():
        return 1, path.stat().st_size
    count = 0
    size = 0
    for candidate in path.rglob("*"):
        if candidate.is_symlink():
            continue
        if candidate.is_file():
            count += 1
            size += candidate.stat().st_size
    return count, size


def _entry(path: Path, root: Path, classification: str, action: str, *, owner: str, destination: str | None = None) -> dict[str, Any]:
    """Build one deterministic audit row."""
    files, bytes_size = _tree_stats(path)
    return {
        "path": path.relative_to(root).as_posix(),
        "classification": classification,
        "owner": owner,
        "file_count": files,
        "bytes": bytes_size,
        "proposed_action": action,
        "destination": destination,
    }


def _is_legacy_polished_report(path: Path) -> bool:
    """Return whether a Run-local report is a known old human-report artifact."""
    upper = path.name.upper()
    return path.is_file() and (
        upper.endswith("_ACTION-REPORT.MD")
        or upper.endswith("_OPERATOR-NOTE.TXT")
        or upper == "ACTION-REPORT.MD"
        or upper == "OPERATOR-NOTE-TEXT.TXT"
    )


def audit_job_layout(sage_root: Path) -> dict[str, Any]:
    """Inspect every Job/Run path without mutation and classify legacy/unknown content."""
    app_root = sage_root.expanduser().resolve()
    layout = storage_layout(app_root)
    root = layout.data_root
    jobs_root = layout.jobs_root
    rows: list[dict[str, Any]] = []
    job_count = 0
    run_count = 0
    for tool in ("bic", "saw"):
        tool_root = jobs_root / tool
        if not tool_root.is_dir():
            continue
        for job_root in sorted(path for path in tool_root.iterdir() if path.is_dir()):
            if not (job_root / "job.yml").is_file():
                rows.append(_entry(job_root, root, "UNKNOWN_PRESERVE", "PRESERVE", owner=f"{tool}:unknown"))
                continue
            job_count += 1
            allowed_job = CANONICAL_JOB_DIRS | (BIC_JOB_DIRS if tool == "bic" else SAW_JOB_DIRS)
            for child in sorted(job_root.iterdir(), key=lambda item: item.name.casefold()):
                if child.name in {"job.yml", "README.md"}:
                    continue
                if child.name in UNUSED_JOB_DIRS:
                    files, _ = _tree_stats(child)
                    cls = "UNUSED_EMPTY" if files == 0 else "UNKNOWN_PRESERVE"
                    action = "REMOVE_EMPTY" if files == 0 else "PRESERVE_REVIEW"
                    rows.append(_entry(child, root, cls, action, owner=job_root.name))
                elif child.name == ".sage":
                    for sage_child in sorted(child.iterdir(), key=lambda item: item.name.casefold()) if child.is_dir() else []:
                        if sage_child.name in UNUSED_SAGE_DIRS:
                            files, _ = _tree_stats(sage_child)
                            cls = "UNUSED_EMPTY" if files == 0 else "UNKNOWN_PRESERVE"
                            action = "REMOVE_EMPTY" if files == 0 else "PRESERVE_REVIEW"
                            rows.append(_entry(sage_child, root, cls, action, owner=job_root.name))
                        elif sage_child.name in CANONICAL_SAGE_DIRS or sage_child.name in {"runtime.yml", "profile.yml"}:
                            rows.append(_entry(sage_child, root, "CANONICAL", "KEEP", owner=job_root.name))
                        else:
                            rows.append(_entry(sage_child, root, "UNKNOWN_PRESERVE", "PRESERVE_REVIEW", owner=job_root.name))
                elif child.name == "runs" and child.is_dir():
                    rows.append(_entry(child, root, "CANONICAL", "KEEP", owner=job_root.name))
                    for run_root in sorted(path for path in child.iterdir() if path.is_dir()):
                        if not (run_root / "run.json").is_file():
                            rows.append(_entry(run_root, root, "UNKNOWN_PRESERVE", "PRESERVE_REVIEW", owner=job_root.name))
                            continue
                        run_count += 1
                        for run_child in sorted(run_root.iterdir(), key=lambda item: item.name.casefold()):
                            if run_child.name in {"run.json", "status.json"}:
                                continue
                            owner = f"{job_root.name}/{run_root.name}"
                            if run_child.name in UNUSED_RUN_DIRS:
                                files, _ = _tree_stats(run_child)
                                cls = "UNUSED_EMPTY" if files == 0 else "UNKNOWN_PRESERVE"
                                action = "REMOVE_EMPTY" if files == 0 else "PRESERVE_REVIEW"
                                rows.append(_entry(run_child, root, cls, action, owner=owner))
                            elif run_child.name in RESERVED_RUN_DIRS:
                                rows.append(_entry(run_child, root, "RESERVED_UNDER_REVIEW", "KEEP", owner=owner))
                            elif run_child.name == "reports" and run_child.is_dir():
                                for report in sorted(run_child.iterdir(), key=lambda item: item.name.casefold()):
                                    if report.name in CURRENT_RUN_REPORT_NAMES:
                                        destination = (run_child.parent / "diagnostics" / report.name).relative_to(root).as_posix()
                                        rows.append(_entry(report, root, "LEGACY_DIAGNOSTICS_MIGRATABLE", "MOVE_HASH_VERIFY", owner=owner, destination=destination))
                                    elif _is_legacy_polished_report(report):
                                        rows.append(_entry(report, root, "LEGACY_MIGRATABLE", "COPY_HASH_VERIFY_THEN_REMOVE", owner=owner))
                                    else:
                                        rows.append(_entry(report, root, "UNKNOWN_PRESERVE", "PRESERVE_REVIEW", owner=owner))
                                if not any(run_child.iterdir()):
                                    rows.append(_entry(run_child, root, "UNUSED_EMPTY", "REMOVE_EMPTY", owner=owner))
                            elif run_child.name in CANONICAL_RUN_DIRS:
                                rows.append(_entry(run_child, root, "CANONICAL", "KEEP", owner=owner))
                            else:
                                rows.append(_entry(run_child, root, "UNKNOWN_PRESERVE", "PRESERVE_REVIEW", owner=owner))
                elif child.name == "reports" and child.is_dir():
                    for report in sorted(child.iterdir(), key=lambda item: item.name.casefold()):
                        destination = (child.parent / "diagnostics" / report.name).relative_to(root).as_posix()
                        rows.append(_entry(report, root, "LEGACY_DIAGNOSTICS_MIGRATABLE", "MOVE_HASH_VERIFY", owner=job_root.name, destination=destination))
                    if not any(child.iterdir()):
                        rows.append(_entry(child, root, "UNUSED_EMPTY", "REMOVE_EMPTY", owner=job_root.name))
                elif child.name in allowed_job:
                    rows.append(_entry(child, root, "CANONICAL", "KEEP", owner=job_root.name))
                else:
                    rows.append(_entry(child, root, "UNKNOWN_PRESERVE", "PRESERVE_REVIEW", owner=job_root.name))
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY",
        "created_utc": _utc_now(),
        "jobs": job_count,
        "runs": run_count,
        "entries": rows,
        "summary": {
            key: sum(1 for row in rows if row["classification"] == key)
            for key in (
                "CANONICAL",
                "LEGACY_MIGRATABLE",
                "LEGACY_DIAGNOSTICS_MIGRATABLE",
                "UNUSED_EMPTY",
                "RESERVED_UNDER_REVIEW",
                "UNKNOWN_PRESERVE",
            )
        },
    }
    hash_basis = {key: value for key, value in audit.items() if key != "created_utc"}
    canonical = json.dumps(hash_basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    audit["audit_sha256"] = sha256_bytes(canonical.encode("utf-8"))
    return audit


def render_job_layout_audit(audit: dict[str, Any]) -> str:
    """Render one readable Job-layout audit report."""
    lines = [
        "# SAGE Job Layout Audit",
        "",
        f"- Status: `{audit.get('status', 'UNKNOWN')}`",
        f"- Jobs: `{audit.get('jobs', 0)}`",
        f"- Runs: `{audit.get('runs', 0)}`",
        f"- Audit hash: `{audit.get('audit_sha256', '')}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in sorted(dict(audit.get("summary") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Paths", ""])
    for row in audit.get("entries", []):
        lines.append(
            f"- `{row['classification']}` | `{row['path']}` | files={row['file_count']} | "
            f"bytes={row['bytes']} | action={row['proposed_action']}"
        )
    return "\n".join(lines).rstrip() + "\n"


def write_job_layout_audit(sage_root: Path) -> dict[str, Any]:
    """Write the read-only audit receipt under workspace diagnostics."""
    app_root = sage_root.expanduser().resolve()
    layout = storage_layout(app_root)
    audit = audit_job_layout(app_root)
    output = layout.diagnostics_root / "job-layout"
    atomic_write_json(output / "JOB-LAYOUT-AUDIT.json", audit)
    atomic_write_text(output / "JOB-LAYOUT-AUDIT.md", render_job_layout_audit(audit))
    return {**audit, "json_path": str(output / "JOB-LAYOUT-AUDIT.json"), "report_path": str(output / "JOB-LAYOUT-AUDIT.md")}


def _load_audit(path: Path) -> dict[str, Any]:
    """Load and validate one audit receipt."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid Job-layout audit: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("Unsupported Job-layout audit schema")
    expected = str(value.get("audit_sha256") or "")
    copy = dict(value)
    copy.pop("audit_sha256", None)
    copy.pop("created_utc", None)
    actual = sha256_bytes(json.dumps(copy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if expected != actual:
        raise ValidationError("Job-layout audit hash mismatch", code="JOB_LAYOUT_AUDIT_STALE")
    return value


def _legacy_destination(sage_root: Path, relative: Path) -> Path:
    """Return a diagnostics quarantine destination for obsolete polished reports."""
    safe = "__".join(relative.parts)
    return storage_layout(sage_root).diagnostics_root / "legacy-reports" / safe


def _diagnostic_destination(sage_root: Path, relative: Path, declared: str | None) -> Path:
    """Return the canonical diagnostics destination for one legacy technical report."""
    layout = storage_layout(sage_root)
    if declared:
        return layout.data_root / Path(declared)
    parts = list(relative.parts)
    if "reports" in parts:
        parts[parts.index("reports")] = "diagnostics"
    return layout.data_root / Path(*parts)


def migrate_job_layout(sage_root: Path, audit_path: Path, *, apply: bool = False) -> dict[str, Any]:
    """Apply only audit-authorized safe migrations; default is dry-run."""
    app_root = sage_root.expanduser().resolve()
    layout = storage_layout(app_root)
    root = layout.data_root
    audit_file = audit_path.expanduser().resolve()
    audit = _load_audit(audit_file)
    current = audit_job_layout(app_root)
    if current["audit_sha256"] != audit["audit_sha256"]:
        raise ValidationError(
            "Job layout changed since the selected audit; run a new audit before migration",
            code="JOB_LAYOUT_AUDIT_STALE",
        )
    actions: list[dict[str, Any]] = []
    for row in audit.get("entries", []):
        classification = row.get("classification")
        relative = Path(str(row.get("path") or ""))
        source = root / relative
        if classification == "UNUSED_EMPTY":
            actions.append({"action": "REMOVE_EMPTY", "source": relative.as_posix()})
            if apply and source.is_dir() and not any(source.iterdir()):
                source.rmdir()
        elif classification == "LEGACY_DIAGNOSTICS_MIGRATABLE" and source.is_file():
            destination = _diagnostic_destination(app_root, relative, str(row.get("destination") or "") or None)
            actions.append(
                {
                    "action": "MIGRATE_DIAGNOSTIC",
                    "source": relative.as_posix(),
                    "destination": destination.relative_to(root).as_posix(),
                    "sha256": sha256_file(source),
                }
            )
            if apply:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if sha256_file(destination) != sha256_file(source):
                    raise ValidationError("Diagnostic migration hash verification failed", code="JOB_LAYOUT_MIGRATION_HASH_MISMATCH")
                source.unlink()
        elif classification == "LEGACY_MIGRATABLE" and source.is_file():
            destination = _legacy_destination(app_root, relative)
            actions.append(
                {
                    "action": "MIGRATE_REPORT",
                    "source": relative.as_posix(),
                    "destination": destination.relative_to(root).as_posix(),
                    "sha256": sha256_file(source),
                }
            )
            if apply:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if sha256_file(destination) != sha256_file(source):
                    raise ValidationError("Legacy report hash verification failed", code="JOB_LAYOUT_MIGRATION_HASH_MISMATCH")
                source.unlink()
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "MIGRATED" if apply else "DRY_RUN",
        "created_utc": _utc_now(),
        "source_audit": str(audit_file),
        "source_audit_sha256": audit["audit_sha256"],
        "actions": actions,
    }
    output = layout.diagnostics_root / "job-layout"
    name = "JOB-LAYOUT-MIGRATION.json" if apply else "JOB-LAYOUT-MIGRATION-DRY-RUN.json"
    atomic_write_json(output / name, receipt)
    return {**receipt, "receipt_path": str(output / name)}


def verify_job_layout(sage_root: Path) -> dict[str, Any]:
    """Return post-migration layout status without mutating state."""
    audit = audit_job_layout(sage_root)
    blocking = [row for row in audit["entries"] if row["classification"] in {"LEGACY_MIGRATABLE", "LEGACY_DIAGNOSTICS_MIGRATABLE"}]
    unknown = [row for row in audit["entries"] if row["classification"] == "UNKNOWN_PRESERVE"]
    return {
        **audit,
        "status": "READY_WITH_ACTIONS" if blocking or unknown else "READY",
        "legacy_remaining": len(blocking),
        "unknown_preserved": len(unknown),
    }
