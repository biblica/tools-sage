"""PCC operator flow: Main Menu #6 home, Job creation and the two Run operations.

PCC has two functions on one Job (plan section 1): build a SOURCE terms list, and check a WIP against
the project glossary. Both are local and deterministic; this module only collects choices and hands
sealed Runs to ``sage.pcc.run``.
"""
from __future__ import annotations

from sage.errors import SageError, ValidationError
from sage.jobs import PCC_RUN_OPERATIONS, pcc_default_settings
from sage.pcc.run import execute_pcc_run, run_initializer
from sage.registry import load_ecosystem

TITLE = "PHRASE CONSISTENCY CHECKER (PCC)"
OPERATION_LABELS = {"terms": "Build SOURCE terms list", "check": "Check WIP against the glossary"}


def _binding_lines(job) -> list[str]:
    """Show the Job's bindings with the role names the Operator sees."""
    lines = [f"PCC JOB                      {job.job_id}", f"SOURCE                       {job.bindings['source']}"]
    if job.bindings.get("secondary_source"):
        lines.append(f"Secondary SOURCE             {job.bindings['secondary_source']}")
    lines.append(f"WIP                          {job.bindings.get('wip') or 'NONE (terms list only)'}")
    lines.append(f"Target language              {job.defaults.get('target_language')}")
    return lines


def create_job(center):
    """Resolve SOURCE, optional secondary SOURCE and optional WIP before anything is persisted."""
    source = center.choose_or_add_resource("Start new PCC <SOURCE>", "REFERENCE")
    if source is None:
        return None
    bindings = {"source": source.project_id}
    if center.io.confirm("Add a secondary SOURCE (another edition)?", default=False):
        secondary = center.choose_or_add_resource("PCC <SECONDARY SOURCE>", "REFERENCE")
        if secondary is None:
            return None
        bindings["secondary_source"] = secondary.project_id
    wip = None
    if center.io.confirm("Bind a translation work in progress (WIP) now? (needed to check consistency)", default=True):
        wip = center.choose_or_add_resource("PCC <WIP PROJECT>", "WIP")
        if wip is None:
            return None
        bindings["wip"] = wip.project_id
        target_language = wip.language_code
        center.io.write(f"Target language: {target_language} (from the WIP). A WIP cannot be added to a Job later.")
    else:
        target_language = center.io.text("TARGET language tag for the terms list (for example sw)").strip()
    job = center.store.create_job(
        tool="pcc", job_id="", display_name=f"PCC {bindings['source']}",
        bindings=bindings, defaults=pcc_default_settings(target_language),
    )
    center.store.set_active_job("pcc", job.job_id)
    return job


def create_run(center, job, operation: str):
    """Seal one Run for ``operation`` after the Operator chooses a scope."""
    if operation not in PCC_RUN_OPERATIONS:
        raise ValidationError(f"Unknown PCC operation: {operation}", code="JOB_OPERATION_MISMATCH")
    if operation == "check" and not job.bindings.get("wip"):
        raise ValidationError(
            "Checking consistency needs a WIP, and this Job has none.",
            code="PCC_WIP_REQUIRED",
            next_action="Create a new PCC Job that binds the WIP; a WIP cannot be added to an existing Job.",
        )
    scope = center._select_scripture_scope(job, primary_binding="wip" if operation == "check" else "source")
    if scope is None:
        return None
    config = load_ecosystem(job.runtime_settings_path)
    return center.store.create_run(
        job, operation=operation, scope=scope,
        initialize_run=run_initializer(config, job, operation=operation, scope=scope),
    )


def continue_run(center, job, run):
    """Execute a sealed PCC Run; integrity stops surface as normal SAGE errors."""
    config = load_ecosystem(job.runtime_settings_path)
    summary = execute_pcc_run(center.store, config, job, run)
    run = center.store.load_run(job, run.run_id)
    center.io.write(f"PCC Run {run.run_id}: {run.status}")
    for limitation in summary.get("limitations", []):
        center.io.write(f"- {limitation}")
    center.io.pause()
    return run


def _start(center, job, operation: str) -> None:
    """Create and drive one Run, reporting content problems instead of crashing the menu."""
    try:
        run = create_run(center, job, operation)
        if run is not None:
            center.continue_run(job, run)
    except SageError as exc:
        center.show_error(exc)


def open_job(center, job) -> None:
    """Operate one PCC Job: terms list, consistency check, or Job management."""
    while True:
        job = center.store.load_job(job.job_id, tool="pcc")
        run = center.store.active_run(job)
        context = _binding_lines(job)
        if run is not None:
            context += ["", f"Active Run                   {run.run_id} ({run.operation}, {run.scope}, {run.status})"]
        if run is not None:
            options = [("1", f"Continue PCC Run {run.run_id}"), ("2", "Manage PCC JOB"), ("B", "Back")]
        else:
            options = [("1", OPERATION_LABELS["terms"]), ("2", OPERATION_LABELS["check"]),
                       ("3", "Manage PCC JOB"), ("B", "Back")]
        choice = center.io.choose(f"PCC {job.job_id}", options, context=tuple(context))
        if choice == "B":
            return
        if choice == options[-2][0]:
            if _manage(center, job):
                return
        elif run is not None:
            center.continue_run(job, run)
        else:
            _start(center, job, "terms" if choice == "1" else "check")


def _manage(center, job) -> bool:
    """Delete or inspect one Job; True once deleted."""
    choice = center.io.choose(
        f"Manage PCC {job.job_id}",
        (("1", "Delete PCC JOB"), ("2", "Recovery and diagnostics"), ("B", "Back")),
        context=tuple(_binding_lines(job)),
    )
    if choice == "1":
        return bool(center._delete_job(job))
    if choice == "2":
        center.recovery_menu(job)
    return False


def pcc_home(center) -> None:
    """Main Menu #6: add the first Job, or open/choose among existing ones."""
    while True:
        report = center.store.discover_report("pcc", include_archived=True)
        if not (report.jobs or report.issues):
            job = center.create_job_wizard("pcc")
            if job is None:
                return
            open_job(center, job)
            continue
        active_id = center.store.active_jobs().get("pcc")
        context = (f"Active PCC JOB               {active_id or 'NONE'}",)
        choice = center.io.choose(
            TITLE,
            (("1", "Open active PCC JOB"), ("2", "Set active PCC JOB"), ("3", "Add new PCC JOB"), ("B", "Back")),
            context=context,
        )
        if choice == "B":
            return
        if choice == "3":
            job = center.create_job_wizard("pcc")
        elif choice == "2" or not active_id:
            job = center.choose_job("pcc")
        else:
            job = center.store.load_job(active_id, tool="pcc")
        if job is not None:
            open_job(center, job)
