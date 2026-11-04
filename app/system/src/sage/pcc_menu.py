"""PCC operator flow: Main Menu #6 home, Job creation and the two Run operations.

PCC has two functions on one Job (plan section 1): build a SOURCE terms list, and check a WIP against
the project glossary. Both are local and deterministic; this module only collects choices and hands
sealed Runs to ``sage.pcc.run``.
"""
from __future__ import annotations

from sage.errors import SageError, ValidationError
from sage.jobs import PCC_RUN_OPERATIONS, pcc_default_settings
from pathlib import Path

from sage.pcc import glossary, overlay, transfer
from sage.pcc.run import OUTPUT_DIRECTORY, execute_pcc_run, load_run_snapshot, run_initializer
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


def _overlay_folder(center) -> Path:
    """Return the Operator's local PCC data folder (core-list verdicts live here, shared by all Jobs)."""
    return center.store.storage.inputs_root / "pcc"


def _latest_terms(center, job):
    """Return (run, snapshot, rows, left-out summary) of the newest finished terms Run, or None."""
    for run in center.store.list_runs(job, include_archived=False):
        if run.operation == "terms" and run.status in {"COMPLETE", "COMPLETE_WITH_EXCEPTIONS"}:
            output = run.root / "validation" / OUTPUT_DIRECTORY
            if (output / "expressions.jsonl").is_file():
                summary: dict = {}
                rows = glossary.terms_rows(output, summary=summary, key_terms=glossary.current_key_terms(job.root),
                                          verdicts=overlay.verdict_map(_overlay_folder(center)))
                return run, load_run_snapshot(run.root), rows, summary
    return None


def _lock(job) -> Path:
    """Return the Job's journal lock path."""
    return job.controller_root / "locks" / "pcc-journal.lock"


def _ask_path(center, prompt: str) -> Path | None:
    """Ask for an existing file path; blank cancels."""
    text = center.io.text(prompt).strip().strip("'\"")
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_file():
        center.io.write(f"No file at {path}.")
        return None
    return path


def terms_menu(center, job) -> None:
    """Terms list sub-option: export, import the filled sheet, Paratext proposals, review proposals."""
    while True:
        job = center.store.load_job(job.job_id, tool="pcc")
        latest = _latest_terms(center, job)
        rules = glossary.current_rules(job.root)
        approved = sum(1 for r in rules.values() if r["state"] == "APPROVED")
        proposed = len(glossary.proposed_rules(job.root))
        context = [f"Terms list                   {latest[0].run_id if latest else 'none yet: build the SOURCE terms list first'}",
                   f"Glossary rules               {approved} approved, {proposed} waiting for your decision"]
        options = [("1", "Export the terms list (Markdown and XLSX)"), ("2", "Import the filled terms list"),
                   ("3", "Import Paratext TermRenderings (read-only proposals)"),
                   ("4", "Review proposed renderings"),
                   ("5", "Import Paratext Biblical Terms (key theological terms, always listed)"),
                   ("6", "Export a terms bundle (to use in another WIP)"), ("7", "Import a terms bundle from another WIP"),
                   ("8", "Import my own terms list (CSV, TXT or XLSX)"), ("9", "Review core lists (senses and key terms)"),
                   ("B", "Back")]
        choice = center.io.choose(f"PCC terms list {job.job_id}", options, context=tuple(context))
        if choice == "B":
            return
        try:
            if choice == "5":
                path = _ask_path(center, "Path of Paratext BiblicalTerms.xml (blank to cancel)")
                if path:
                    center.io.write(f"{glossary.import_key_terms(job.root, path)} key terms stored; export the terms list again.")
                continue
            if latest is None:
                center.io.write("Build the SOURCE terms list first (a terms Run).")
                continue
            run, snapshot, rows, left_out = latest
            if choice == "1":
                folder = center.store.storage.reports_root / job.job_id
                digest = glossary.write_terms_list(
                    rows, job_id=job.job_id, run_id=run.run_id, target_language=snapshot["target_language"],
                    markdown=folder / "TERMS-LIST.md", xlsx=folder / "TERMS-LIST.xlsx", summary=left_out)
                center.io.write(f"Terms list {digest[:16]} written to {folder} ({len(rows)} rows).")
            elif choice == "2":
                path = _ask_path(center, "Path of the filled TERMS-LIST.xlsx (blank to cancel)")
                if path:
                    report = glossary.import_filled_list(
                        job, path, rows, lock_path=_lock(job), source_corpus_sha256=snapshot["source"]["content_sha256"],
                        target_language=snapshot["target_language"])
                    for line in report.as_lines():
                        center.io.write(line)
            elif choice == "3":
                path = _ask_path(center, "Path of Paratext TermRenderings.xml (blank to cancel)")
                if path:
                    report = glossary.propose_from_paratext(
                        job, path, rows, lock_path=_lock(job), source_corpus_sha256=snapshot["source"]["content_sha256"],
                        target_language=snapshot["target_language"])
                    center.io.write(f"Proposed {report.imported} rendering(s); {report.unchanged} already known.")
                    for line in report.problems[:20]:
                        center.io.write(f"- {line}")
            elif choice == "6":
                folder = center.store.storage.exports_root / "pcc"
                target = folder / f"{job.job_id}-terms-bundle.json"
                counts = transfer.export_bundle(
                    job, rows, source_project=job.bindings["source"], source_sha256=snapshot["source"]["content_sha256"],
                    target_language=snapshot["target_language"], verdict_folder=_overlay_folder(center), path=target)
                center.io.write(f"Bundle written to {target}: {counts['entries']} wordings, {counts['rules']} approved renderings, "
                                f"{counts['key_terms']} key terms, {counts['verdicts']} review verdicts.")
            elif choice == "7":
                path = _ask_path(center, "Path of the terms bundle .json (blank to cancel)")
                if path:
                    report = transfer.import_bundle(
                        job, path, rows, lock_path=_lock(job), source_corpus_sha256=snapshot["source"]["content_sha256"],
                        target_language=snapshot["target_language"], verdict_folder=_overlay_folder(center))
                    center.io.write(f"Proposed {report.imported} rendering(s); {report.unchanged} already known. Review them under option 4.")
                    for line in report.problems[:20]:
                        center.io.write(f"- {line}")
            elif choice == "8":
                path = _ask_path(center, "Path of your list: wording[, rendering(s)[, note]] (blank to cancel)")
                if path:
                    report = transfer.import_operator_list(
                        job, path, rows, lock_path=_lock(job), source_corpus_sha256=snapshot["source"]["content_sha256"],
                        target_language=snapshot["target_language"])
                    center.io.write(f"Proposed {report.imported} rendering(s); {report.unchanged} already known.")
                    for line in report.problems[:20]:
                        center.io.write(f"- {line}")
            elif choice == "9":
                _review_core(center, job, rows)
            elif choice == "4":
                _review_proposals(center, job, snapshot["source"]["content_sha256"])
        except SageError as exc:
            center.show_error(exc)
        center.io.pause()


def _review_core(center, job, rows) -> None:
    """Operator review of the core lists: sense evidence (MACULA/OL) and Paratext key terms."""
    folder = _overlay_folder(center)
    while True:
        standing = overlay.verdict_map(folder)
        senses = [r for r in rows if r["lemma"]]
        pending = [r for r in senses if ("OL_SENSE", f"{r['normalized']}|{r['lemma']}") not in standing]
        key_terms = glossary.current_key_terms(job.root)
        choice = center.io.choose(
            "Review core lists",
            (("1", f"Review original-language senses ({len(pending)} not yet reviewed of {len(senses)})"),
             ("2", f"Review key terms ({len(key_terms)} from Paratext Biblical Terms)"),
             ("3", f"Show or withdraw my verdicts ({len(standing)})"), ("B", "Back")),
            context=("Your verdicts are a local overlay on the shipped lists; the lists themselves never change.",))
        if choice == "B":
            return
        if choice == "1":
            for row in pending:
                key = f"{row['normalized']}|{row['lemma']}"
                answer = center.io.choose(f"'{row['wording']}' = {row['sense']}  ({row['verses']} verses, e.g. {row['examples']})",
                                          (("1", "Accept this sense"), ("2", "Reject (hide it from the list)"),
                                           ("S", "Skip"), ("B", "Stop")))
                if answer == "B":
                    break
                if answer in {"1", "2"}:
                    overlay.record_verdict(folder, "OL_SENSE", key, "ACCEPT" if answer == "1" else "REJECT")
        elif choice == "2":
            for lemma, gloss in sorted(key_terms.items()):
                if ("KEY_TERM", lemma) in standing:
                    continue
                answer = center.io.choose(f"Key term {lemma}  ({gloss or 'no gloss'})",
                                          (("1", "Keep as a key term"), ("2", "Not a key term for this work"),
                                           ("S", "Skip"), ("B", "Stop")))
                if answer == "B":
                    break
                if answer in {"1", "2"}:
                    overlay.record_verdict(folder, "KEY_TERM", lemma, "ACCEPT" if answer == "1" else "REJECT")
        elif choice == "3":
            for (name, key), verdict in sorted(standing.items()):
                answer = center.io.choose(f"{name}  {key}: {verdict}", (("1", "Withdraw this verdict"), ("S", "Keep"), ("B", "Stop")))
                if answer == "B":
                    break
                if answer == "1":
                    overlay.record_verdict(folder, name, key, "CLEAR")


def _review_proposals(center, job, source_sha: str) -> None:
    """Approve or decline proposed renderings, all at once or one by one."""
    proposals = glossary.proposed_rules(job.root)
    if not proposals:
        center.io.write("Nothing is waiting for a decision.")
        return
    mode = center.io.choose(f"{len(proposals)} proposed rendering(s)",
                            (("1", "Approve all"), ("2", "Decide one by one"), ("B", "Back")))
    if mode == "1":
        count = glossary.decide_proposals(job, [r["rule_id"] for r in proposals], approve=True,
                                          lock_path=_lock(job), source_corpus_sha256=source_sha)
        center.io.write(f"Approved {count} rendering(s).")
    elif mode == "2":
        for rule in proposals:
            answer = center.io.choose(f"{rule['target_form']}  ({rule['rationale']})",
                                      (("1", "Approve"), ("2", "Decline"), ("S", "Skip"), ("B", "Stop")))
            if answer == "B":
                break
            if answer in {"1", "2"}:
                glossary.decide_proposals(job, [rule["rule_id"]], approve=answer == "1",
                                          lock_path=_lock(job), source_corpus_sha256=source_sha)


def open_job(center, job) -> None:
    """Operate one PCC Job: terms list, consistency check, or Job management."""
    while True:
        job = center.store.load_job(job.job_id, tool="pcc")
        run = center.store.active_run(job)
        context = _binding_lines(job)
        if run is not None:
            context += ["", f"Active Run                   {run.run_id} ({run.operation}, {run.scope}, {run.status})"]
        if run is not None:
            options = [("1", f"Continue PCC Run {run.run_id}"), ("2", "Terms list and glossary"),
                       ("3", "Manage PCC JOB"), ("B", "Back")]
        else:
            options = [("1", OPERATION_LABELS["terms"]), ("2", OPERATION_LABELS["check"]),
                       ("3", "Terms list and glossary"), ("4", "Manage PCC JOB"), ("B", "Back")]
        choice = center.io.choose(f"PCC {job.job_id}", options, context=tuple(context))
        if choice == "B":
            return
        if choice == options[-2][0]:
            if _manage(center, job):
                return
        elif options[int(choice) - 1][1] == "Terms list and glossary":
            terms_menu(center, job)
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
