"""Canonical authority identity, paths, and indexes for RTC/STC reports."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .atomic import atomic_write_text
from .errors import ValidationError
from .jobs import Job, Run

_BOOK_RE = re.compile(r"^[A-Z0-9]{3}$")


def _field(label: str, value: object) -> str:
    return f"{label:<29}{value}"


def _fingerprint(
    fingerprints: Mapping[str, Any],
    project_id: str,
    *roles: str,
) -> str:
    """Resolve common sealed fingerprint key forms without inventing identity."""
    candidates = (
        project_id,
        f"project.{project_id}",
        *roles,
        *(role.upper() for role in roles),
    )
    for key in candidates:
        value = str(fingerprints.get(key) or "").strip()
        if value:
            return value
    return "NOT RECORDED"


def _snapshot_date(value: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw or "NOT RECORDED"


def authority_header(
    job: Job,
    run: Run,
    *,
    family: str | None = None,
    fingerprints: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Render explicit Project/snapshot/comparison authority for one analysis Run."""
    if job.tool not in {"rtc", "stc", "saw"}:
        raise ValidationError("Authority headers are available only for RTC/STC analysis")
    operation = str(run.operation or job.tool).strip().upper()
    if operation not in {"RTC", "STC"}:
        raise ValidationError(f"Unsupported analysis report operation: {operation}")
    values = dict(fingerprints or {})
    snapshot = dict(job.wip_snapshot or {})
    wip_id = str(job.bindings.get("wip") or snapshot.get("project_id") or "NOT RECORDED")
    wip_fingerprint = str(snapshot.get("content_fingerprint") or "").strip()
    if not wip_fingerprint:
        wip_fingerprint = _fingerprint(values, wip_id, "WIP")
    lines = [
        _field("Analysis", operation),
        _field("Job", job.job_id),
        _field("Run", run.run_id),
        _field("WIP Project", wip_id),
        _field("WIP snapshot date", _snapshot_date(str(snapshot.get("snapshot_date") or ""))),
        _field("WIP fingerprint", wip_fingerprint or "NOT RECORDED"),
    ]
    normalized_family = str(family or "").strip().upper()
    if normalized_family and normalized_family not in {"GRK", "HEB"}:
        raise ValidationError(f"Unsupported original-language authority: {family}")
    if operation == "RTC":
        reference = str(job.bindings.get("reference") or "NOT RECORDED")
        lines.extend(
            [
                _field("REFERENCE Project", reference),
                _field("Comparison authority", reference),
                _field(
                    "REFERENCE fingerprint",
                    _fingerprint(values, reference, "REFERENCE"),
                ),
                _field("Original-language authority", normalized_family or "NOT USED"),
            ]
        )
        if normalized_family:
            lines.append(
                _field(
                    "Authority fingerprint",
                    _fingerprint(values, normalized_family, "ORIGINAL_LANGUAGE"),
                )
            )
    else:
        if not normalized_family:
            raise ValidationError("STC report requires exact GRK or HEB authority identity")
        lines.extend(
            [
                _field("Original-language authority", normalized_family),
                _field(
                    "Authority fingerprint",
                    _fingerprint(values, normalized_family, "ORIGINAL_LANGUAGE"),
                ),
                _field("REFERENCE Project", "NOT USED"),
            ]
        )
    return tuple(lines)


def authority_markdown(lines: Sequence[str]) -> list[str]:
    """Wrap a shared authority header for an Operator-facing Markdown report."""
    return ["## Authority and analyzed snapshot", "", "```text", *lines, "```"]


def _chapter_root(reports_root: Path, job: Job, book: str, chapter: int) -> Path:
    code = str(book).strip().upper()
    if not _BOOK_RE.fullmatch(code):
        raise ValidationError(f"Invalid canonical report Book code: {book!r}")
    if not isinstance(chapter, int) or chapter < 1 or chapter > 999:
        raise ValidationError(f"Invalid canonical report chapter: {chapter!r}")
    return reports_root / job.job_id / code / f"{chapter:03d}"


def report_stem(run: Run, book: str, chapter: int) -> str:
    """Return the canonical Run/Book/chapter report stem."""
    code = str(book).strip().upper()
    if not _BOOK_RE.fullmatch(code) or chapter < 1 or chapter > 999:
        raise ValidationError("Invalid canonical report coordinate")
    return f"{run.run_id}_{code}-{chapter:03d}"


def chapter_report_path(
    reports_root: Path,
    job: Job,
    run: Run,
    book: str,
    chapter: int,
) -> Path:
    root = _chapter_root(reports_root, job, book, chapter)
    return root / f"{report_stem(run, book, chapter)}_ACTION-REPORT.md"


def chapter_note_path(
    reports_root: Path,
    job: Job,
    run: Run,
    book: str,
    chapter: int,
) -> Path:
    root = _chapter_root(reports_root, job, book, chapter)
    return root / f"{report_stem(run, book, chapter)}_OPERATOR-NOTE.txt"


def chapter_data_path(job: Job, run: Run, book: str, chapter: int) -> Path:
    code = str(book).strip().upper()
    return (
        job.root
        / "report_data"
        / code
        / f"{chapter:03d}"
        / f"{report_stem(run, code, chapter)}_CONSOLIDATED.json"
    )


def write_job_summary(
    reports_root: Path,
    job: Job,
    *,
    report_paths: Sequence[Path] = (),
) -> Path:
    """Refresh the Job-level report index from every published chapter report."""
    job_report_root = reports_root / job.job_id
    job_report_root.mkdir(parents=True, exist_ok=True)
    known = {
        path.resolve()
        for path in job_report_root.glob("*/*/*_ACTION-REPORT.md")
        if path.is_file()
    }
    known.update(Path(path).resolve() for path in report_paths)
    snapshot = dict(job.wip_snapshot or {})
    lines = [
        f"# {job.tool.upper()} Job Report Summary — {job.job_id}",
        "",
        f"- WIP Project: `{job.bindings.get('wip', 'NOT RECORDED')}`",
        f"- WIP snapshot date: `{_snapshot_date(str(snapshot.get('snapshot_date') or ''))}`",
        f"- Paratext/source location: `{snapshot.get('source_location') or 'NOT RECORDED'}`",
        "",
        "## Chapter reports",
        "",
    ]
    if not known:
        lines.append("No chapter reports have been published.")
    else:
        for path in sorted(known):
            relative = path.relative_to(job_report_root.resolve())
            lines.append(f"- [{path.name}]({relative.as_posix()})")
    summary = job_report_root / "JOB-SUMMARY.md"
    atomic_write_text(summary, "\n".join(lines).rstrip() + "\n")
    return summary
