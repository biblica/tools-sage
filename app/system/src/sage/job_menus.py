"""Canonical Operator menu structure shared by every WIP-bound SAGE Job type.

Tester feedback 0.02a3 fixed one shape for RTC, STC and NCA so an Operator
learns it once:

    [ JOB NAME (XXX) ]              1. Open active XXX JOB
                                    2. Set active XXX JOB
                                    3. Manage XXX JOBs
    [ XXX <WIP> ]                   1. Run XXX on <WIP> with defaults
                                    2. XXX defaults setting
                                    3. Manage XXX <WIP>
    [ Manage XXX <WIP> ]            1. Manage reporting languages
                                    2. Refresh XXX JOB source
                                    3. Delete XXX JOB
                                    4. <WIP> Job reports and history
                                    5. Recovery and diagnostics
    [ Manage XXX JOBs ]             1. Add new XXX JOB
                                    2. Refresh XXX JOB source
                                    3. Delete XXX JOB

With no Jobs the home goes straight to Add new; with Jobs but none active it
goes straight to Set active. Tool-specific behavior (what "defaults" are, how
a Run starts) lives in the small per-tool adapters at the bottom.
"""

from __future__ import annotations

from typing import Any

from .errors import SageError, ValidationError
from .jobs import Job, JobLoadIssue
from .rtc_policy import default_rtc_policy, validate_rtc_policy

STANDARD_JOB_TOOLS = frozenset({"rtc", "stc", "nca"})
JOB_TITLES = {
    "rtc": "REFERENCE TEXT COMPARISON (RTC)",
    "stc": "SOURCE TEXT CORRESPONDENCE (STC)",
    "nca": "NUMBER CONSISTENCY & ACCURACY (NCA)",
}


def _label(tool: str) -> str:
    """Return the Operator-facing Job acronym."""
    return tool.upper()


def _require_standard(tool: str) -> str:
    """Reject tools that do not follow the WIP-bound standard Job shape."""
    normalized = tool.strip().lower()
    if normalized not in STANDARD_JOB_TOOLS:
        raise ValidationError(f"Standard Job menu requires RTC, STC or NCA, not {tool}")
    return normalized


def _binding_lines(job: Job) -> list[str]:
    """Show the fixed Project bindings and snapshot every Job screen leads with."""
    lines = [f"WIP Project                  {job.bindings['wip']}"]
    if job.tool == "rtc":
        lines.append(f"REFERENCE Project            {job.bindings['reference']}")
    snapshot = dict(job.wip_snapshot or {})
    lines.append(f"WIP snapshot date            {snapshot.get('snapshot_date') or 'UNKNOWN'}")
    exception_line = snapshot_exception_summary(snapshot)
    if exception_line:
        lines.append(f"WIP snapshot exceptions      {exception_line}")
    return lines


def snapshot_exception_summary(snapshot: dict) -> str:
    """Name what the WIP snapshot left out or will report not assessed; empty when nothing was."""
    rows = [row for row in snapshot.get("exceptions") or () if isinstance(row, dict)]
    books = sorted({str(row.get("book")) for row in rows if row.get("effect") == "BOOK_LEFT_OUT"})
    chapters = sorted(
        {f"{row.get('book')} {chapter}" for row in rows if row.get("effect") == "CHAPTER_NOT_ASSESSED"
         for chapter in row.get("chapters") or ()},
        key=lambda label: (label.split(" ")[0], int(label.split(" ")[1])),
    )
    parts = []
    if books:
        parts.append("books left out: " + ", ".join(book or "unnamed file" for book in books))
    if chapters:
        parts.append("chapters not assessed: " + ", ".join(chapters))
    return "; ".join(parts)


# ---------- [ JOB NAME (XXX) ] ----------

def job_home(center, tool: str) -> None:
    """Open one Job type's home, redirecting to Add new or Set active when needed."""
    tool = _require_standard(tool)
    label = _label(tool)
    redirect = True
    while True:
        report = center.store.discover_report(tool, include_archived=True)
        active, issue = center._active_job_from_report(report, center.store.active_jobs().get(tool))
        if redirect:
            redirect = False
            if not (report.jobs or report.issues):
                job = add_job(center, tool)
                if job is None:
                    return
                open_job(center, job)
                continue
            if active is None and issue is None:
                job = set_active_job(center, tool)
                if job is not None:
                    open_job(center, job)
                continue
        active_label = active.job_id if active else f"{issue.job_id} [ACTION NEEDED]" if issue else "NONE"
        context = [f"Active {label} JOB               {active_label}"]
        if active is not None:
            context.extend(_binding_lines(active))
        choice = center.io.choose(
            JOB_TITLES[tool],
            (
                ("1", f"Open active {label} JOB"),
                ("2", f"Set active {label} JOB"),
                ("3", f"Manage {label} JOBs"),
                ("B", "Back"),
            ),
            context=tuple(context),
        )
        if choice == "B":
            return
        if choice == "1":
            job = _resolve_active(center, tool, active, issue)
        elif choice == "2":
            job = set_active_job(center, tool)
        else:
            manage_jobs(center, tool)
            continue
        if job is not None:
            open_job(center, job)


def _resolve_active(center, tool: str, active: Job | None, issue: JobLoadIssue | None) -> Job | None:
    """Return the usable active Job, repairing or choosing one when it is missing."""
    if issue is not None:
        repaired = center._present_job_action_needed(issue, offer_onboarding=True)
        if repaired is not None:
            center.store.set_active_job(tool, repaired.job_id)
            return repaired
    return active or set_active_job(center, tool)


def set_active_job(center, tool: str) -> Job | None:
    """List loaded Jobs, a blank line, then Add new; the chosen Job becomes active."""
    return center.choose_job(tool)


def add_job(center, tool: str) -> Job | None:
    """Create one Job with the tool's wizard and make it the active Job."""
    try:
        job = center.create_job_wizard(tool)
    except ValidationError as exc:
        center.show_error(exc)
        return None
    if not isinstance(job, Job):
        return None
    center.store.set_active_job(tool, job.job_id)
    return job


# ---------- [ Manage XXX JOBs ] ----------

def manage_jobs(center, tool: str) -> None:
    """Add, refresh or delete any Job of one type, plus the tool's storage upkeep."""
    label = _label(tool)
    while True:
        report = center.store.discover_report(tool, include_archived=True)
        active_id = center.store.active_jobs().get(tool)
        entries = sorted([*report.jobs, *report.issues], key=lambda item: item.job_id.casefold())
        context = [
            f"  - {item.job_id}" + (" [ACTIVE]" if item.job_id == active_id else "")
            + (f" [{_issue_label(item)}]" if isinstance(item, JobLoadIssue) else "")
            for item in entries
        ] or [f"No {label} JOBs exist."]
        options = [
            ("1", f"Add new {label} JOB"),
            ("2", f"Refresh {label} JOB source"),
            ("3", f"Delete {label} JOB"),
            ("4", f"Archive {label} JOB"),
            ("5", f"Maintain {label} job storage"),
        ]
        if tool == "nca":
            options.append(("6", "NCA reference packages"))
        options.append(("B", "Back"))
        choice = center.io.choose(f"Manage {label} JOBs", tuple(options), context=tuple(context), blank_before=("4",))
        if choice == "B":
            return
        if choice == "1":
            add_job(center, tool)
        elif choice == "5":
            center.job_storage_maintenance_menu(tool)
        elif choice == "6":
            from .nca_menu import choose_package
            choose_package(center, manage=True)
        else:
            target = _pick_job(center, tool, {"2": "Refresh", "3": "Delete", "4": "Archive"}[choice])
            if target is None:
                continue
            if choice == "2":
                refresh_source(center, target)
            elif choice == "3":
                center._delete_job(target)
            elif center.io.confirm(f"Archive Job {target.job_id}?", default=False):
                center.store.revise_job(target, status="ARCHIVED")
                if active_id == target.job_id:
                    center.store.set_active_job(tool, None)
                center.io.write("Job archived. Data was not deleted.")
                center.io.pause()


def _issue_label(issue: JobLoadIssue) -> str:
    """Short list tag for a Job that cannot load: LEGACY when its contract is retired."""
    return "LEGACY - cannot run" if issue.code == "NCA_JOB_LEGACY_PACKAGE" else "ACTION NEEDED"


def _pick_job(center, tool: str, verb: str) -> Job | None:
    """Choose one existing Job of this type for a management action.

    Delete and Archive also offer Jobs that cannot load (LEGACY or action-needed), so a retired
    Job can always be removed; Refresh offers only loadable Jobs.
    """
    label = _label(tool)
    unloadable_allowed = verb in {"Delete", "Archive"}
    candidates = center.store.discover(tool, include_archived=True, include_unloadable=unloadable_allowed)
    if not candidates:
        center.io.write(f"No {label} JOBs exist.")
        center.io.pause()
        return None
    issues = {
        issue.job_id: issue
        for issue in center.store.discover_report(tool, include_archived=True).issues
    } if unloadable_allowed else {}
    choice = center.io.choose(
        f"{verb.upper()} {label} JOB",
        [
            (str(index), f"{job.job_id}: {job.display_name}"
             + (f" [{_issue_label(issues[job.job_id])}]" if job.job_id in issues else ""))
            for index, job in enumerate(candidates, 1)
        ]
        + [("B", "Back")],
    )
    return None if choice == "B" else candidates[int(choice) - 1]


def refresh_source(center, job: Job) -> Job:
    """Re-snapshot the WIP Project into the Job; Project bindings stay fixed."""
    try:
        job = center.store.refresh_job_snapshot(
            job, imported_at=center._required_project_imported_at(job.bindings["wip"]))
        snapshot = dict(job.wip_snapshot or {})
        center.io.write(f"WIP snapshot refreshed: {snapshot.get('snapshot_date')}")
        exception_line = snapshot_exception_summary(snapshot)
        if exception_line:
            center.io.write(f"WIP snapshot exceptions: {exception_line}")
    except SageError as exc:
        center.show_error(exc)
    center.io.pause()
    return job


# ---------- [ XXX <WIP> ] ----------

def open_job(center, job: Job) -> None:
    """Operate one Job: run with its saved defaults, edit them, or manage the Job."""
    tool = _require_standard(job.tool)
    label = _label(tool)
    while True:
        job = center.store.load_job(job.job_id, tool=tool)
        run = center.store.active_run(job)
        wip = job.bindings["wip"]
        context = [*_binding_lines(job), "", *_defaults_lines(center, job)]
        if run is not None:
            context.extend(["", "Active Run",
                            f"  Run                        {run.run_id}",
                            f"  Scope                      {run.scope}",
                            f"  Status                     {run.status}"])
        center._write_job_ai_routing(tool, run)
        run_label = (f"Continue {label} Run {run.run_id} on {wip}" if run is not None
                     else f"Run {label} on {wip} with defaults")
        choice = center.io.choose(
            f"{label} {wip}",
            (
                ("1", run_label),
                ("2", f"{label} defaults setting"),
                ("3", f"Manage {label} {wip}"),
                ("B", "Back"),
            ),
            context=tuple(context),
        )
        if choice == "B":
            return
        if choice == "1":
            if run is not None:
                center.continue_run(job, run)
            else:
                _run_with_defaults(center, job)
        elif choice == "2":
            _edit_defaults(center, job)
        elif manage_job(center, job):
            return


# ---------- [ Manage XXX <WIP> ] ----------

def manage_job(center, job: Job) -> bool:
    """Manage one Job's languages, source, reports and recovery; True once deleted."""
    label = _label(job.tool)
    while True:
        job = center.store.load_job(job.job_id, tool=job.tool)
        wip = job.bindings["wip"]
        context = (
            *_binding_lines(job),
            f"Primary report language      {job.primary_report_language}",
            f"Secondary report language    {job.secondary_report_language or 'NONE'}",
        )
        choice = center.io.choose(
            f"Manage {label} {wip}",
            (
                ("1", "Manage reporting languages"),
                ("2", f"Refresh {label} JOB source"),
                ("3", f"Delete {label} JOB"),
                ("4", f"{wip} Job reports and history"),
                ("5", "Recovery and diagnostics"),
                ("B", "Back"),
            ),
            context=context,
        )
        if choice == "B":
            return False
        if choice == "1":
            center._reporting_languages_menu(job)
        elif choice == "2":
            refresh_source(center, job)
        elif choice == "3":
            if center._delete_job(job):
                return True
        elif choice == "4":
            reports_and_history(center, job)
        else:
            center.recovery_menu(job)


def reports_and_history(center, job: Job) -> None:
    """Published reports first, then Run history and the Job's raw data locations."""
    from .storage import storage_layout
    wip = job.bindings["wip"]
    while True:
        choice = center.io.choose(
            f"{wip} Job reports and history",
            (
                ("1", "Published Job reports"),
                ("2", "Runs and task history"),
                ("3", "Run report data"),
                ("4", "Exports"),
                ("5", "Job data folder"),
                ("B", "Back"),
            ),
        )
        if choice == "B":
            return
        if choice == "1":
            center.list_files(storage_layout(center.root).reports_root / job.job_id, patterns=("*.md", "*.txt"))
        elif choice == "2":
            center.runs_menu(job)
        elif choice == "3":
            center.list_files(job.root / "runs", patterns=("*.md", "*.json", "*.txt", "*.tsv"))
        elif choice == "4":
            center.list_files(job.root / "exports", patterns=("*",))
        else:
            center.io.write(str(job.root))
            center.io.pause()


# ---------- Per-tool defaults and Run adapters ----------

def rtc_defaults(center, job: Job) -> tuple[dict[str, Any], str]:
    """Return the RTC policy a default Run uses and whether it is JOB-saved or governed."""
    stored = job.defaults.get("rtc_policy")
    if stored:
        return validate_rtc_policy(stored, workflow=job.runtime_tool), "SAVED JOB DEFAULTS"
    profile_path = center.root / "system" / "config" / "workflows" / job.runtime_tool / "profile.yml"
    return default_rtc_policy(profile_path), "GOVERNED DEFAULTS"


def _on_off(value: object) -> str:
    """Render one check switch."""
    return "ON" if value else "OFF"


def _defaults_lines(center, job: Job) -> list[str]:
    """Describe exactly what "Run with defaults" will use, under the menu banner."""
    if job.tool == "rtc":
        policy, source = rtc_defaults(center, job)
        checks, contexts = policy["checks"], policy["usfm_contexts"]
        drift = policy["original_language"]["source_text_drift_adjudication"]
        return [
            f"Defaults                     {source}",
            "  Checks                     "
            f"structure {_on_off(checks['structure_completeness'])} · meaning {_on_off(checks['translation_meaning'])}"
            f" · readability {_on_off(checks['language_readability'])} · consistency {_on_off(checks['consistency'])}",
            "  Text policy                "
            + " · ".join(f"\\{key} {contexts[key].replace('_', ' ')}" for key in ("add", "nd", "f")),
            f"  WIP-Reference variance     {drift}",
        ]
    if job.tool == "nca":
        from .nca_menu import CHECK_LABELS, saved_checks
        checks = saved_checks(job)
        package = dict(job.resources.get("numbers_package") or {}).get("package_id") or "NOT CONFIGURED"
        rows = [(center.localizer.text(text), _on_off(checks[key])) for key, text in CHECK_LABELS.items()]
        rows += [("Number Style Profile", job.profiles.get("number_style", "NOT CONFIGURED")),
                 ("Reference package", package)]
        width = max(27, *(len(name) + 2 for name, _value in rows))
        return ["Defaults", *(f"  {name:<{width}}{value}" for name, value in rows)]
    return ["Defaults                     GOVERNED STC CHECK (no configurable run defaults)"]


def _run_with_defaults(center, job: Job) -> None:
    """Start a Run using the saved defaults, asking only for the Scripture scope."""
    if job.tool == "rtc":
        center.start_saw_run(job, "rtc", policy=rtc_defaults(center, job)[0])
    elif job.tool == "stc":
        center.start_saw_run(job, "stc")
    else:
        from .nca_menu import saved_checks, start_run
        try:
            start_run(center, job, checks=saved_checks(job))
        except ValidationError as exc:
            center.show_error(exc)


def _edit_defaults(center, job: Job) -> None:
    """Edit the per-Job defaults every later "Run with defaults" uses."""
    if job.tool == "rtc" and center.store.open_run_ids(job):
        center.io.write("RTC defaults cannot change while a Run is open. Finish or abandon that Run first.")
        center.io.pause()
        return
    if job.tool == "rtc":
        current, _source = rtc_defaults(center, job)
        policy = center._rtc_policy_menu(
            "JOB defaults", workflow=job.runtime_tool, initial=current, action_label="Save RTC defaults")
        if policy is not None:
            center.store.revise_job(job, defaults={
                **job.defaults, "rtc_policy": validate_rtc_policy(policy, workflow=job.runtime_tool)})
            center.io.write("RTC defaults saved. They apply to every later Run of this Job.")
            center.io.pause()
    elif job.tool == "nca":
        from .nca_menu import choose_checks
        choose_checks(center, job, for_run=False)
    else:
        center.io.write("STC has no configurable run defaults; every STC Run uses the governed STC check.")
        center.io.pause()
