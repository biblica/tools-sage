"""PCC operator flow: Main Menu #6 home, Job creation and the two Run operations.

PCC has two functions on one Job (plan section 1): build a SOURCE terms list, and check a WIP against
the project glossary. Both are local and deterministic; this module only collects choices and hands
sealed Runs to ``sage.pcc.run``.
"""
from __future__ import annotations

from sage.errors import SageError, ValidationError
from sage.jobs import PCC_RUN_OPERATIONS, pcc_default_settings
from pathlib import Path

import json

from sage.pcc import decisions, glossary, reflist_xlsx, transfer
from sage.pcc.pin import repin
from sage.pcc.reflist import ReferenceListStore
from sage.pcc.rlservice import build_reference_list_for, reference_context
from sage.pcc.run import OUTPUT_DIRECTORY, execute_pcc_run, load_run_snapshot, project_identity, run_initializer
from sage.registry import load_ecosystem
from sage.vrs import load_project_vrs

ACTOR = "operator"

TITLE = "PHRASE CONSISTENCY CHECKER (PCC)"
OPERATION_LABELS = {"terms": "Build SOURCE terms list", "check": "Check WIP against the glossary"}


def _binding_lines(job) -> list[str]:
    """Show the Job's bindings with the role names the Operator sees."""
    lines = [f"PCC JOB                      {job.job_id}", f"SOURCE                       {job.bindings['source']}"]
    if job.bindings.get("secondary_source"):
        lines.append(f"Secondary SOURCE             {job.bindings['secondary_source']}")
    lines.append(f"WIP                          {job.bindings.get('wip') or 'NONE (terms list only)'}")
    lines.append(f"Target language              {job.defaults.get('target_language')}")
    pin = job.defaults.get("reference_list")
    lines.append(f"Reference list               {pin['rl_id']} v{pin['version']}" if pin
                 else "Reference list               NONE (terms list discovers wordings)")
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
        center.io.write(f"Target language: {target_language} (from the WIP).")
    else:
        center.io.write("You can attach a WIP to this Job once, later (Manage PCC JOB).")
        target_language = center.io.text("TARGET language tag for the terms list (for example sw)").strip()
    job = center.store.create_job(
        tool="pcc", job_id="", display_name=f"PCC {bindings['source']}",
        bindings=bindings, defaults=pcc_default_settings(target_language),
    )
    center.store.set_active_job("pcc", job.job_id)
    try:
        reference_list_menu(center, job)
    except SageError as exc:
        center.show_error(exc)
    return center.store.load_job(job.job_id, tool="pcc")


def create_run(center, job, operation: str):
    """Seal one Run for ``operation`` after the Operator chooses a scope."""
    if operation not in PCC_RUN_OPERATIONS:
        raise ValidationError(f"Unknown PCC operation: {operation}", code="JOB_OPERATION_MISMATCH")
    if operation == "check" and not job.bindings.get("wip"):
        raise ValidationError(
            "Checking consistency needs a WIP, and this Job has none.",
            code="PCC_WIP_REQUIRED",
            next_action="Attach a WIP once under Manage PCC JOB, or create a new PCC Job with the WIP.",
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
    if run.operation == "check":
        found = ", ".join(f"{code} {n}" for code, n in summary.get("findings_by_code", {}).items()) or "none"
        center.io.write(f"Groups compared: {summary.get('evaluated_groups', 0)}; findings: {found}; "
                        f"issues: {summary.get('issue_clusters', 0)}.")
        center.io.write(f"Reports: {center.store.storage.reports_root / job.job_id / 'PCC-CHECK.md'} and PCC-FINDINGS.xlsx")
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


def _latest_terms(center, job):
    """Return (run, snapshot, rows, left-out summary) of the newest finished terms Run, or None."""
    for run in center.store.list_runs(job, include_archived=False):
        if run.operation == "terms" and run.status in {"COMPLETE", "COMPLETE_WITH_EXCEPTIONS"}:
            output = run.root / "validation" / OUTPUT_DIRECTORY
            if (output / "expressions.jsonl").is_file():
                summary: dict = {}
                rows = glossary.terms_rows(output, summary=summary, key_terms=glossary.current_key_terms(job.root))
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
                   ("8", "Import my own terms list (CSV, TXT or XLSX)"),
                   ("9", "Import decisions on check findings (PCC-FINDINGS.xlsx)"),
                   ("10", "Review stale rules"), ("11", "Revoke an approved rendering"), ("B", "Back")]
        choice = center.io.choose(f"PCC terms list {job.job_id}", options, context=tuple(context))
        if choice == "B":
            return
        try:
            if choice in ("9", "10", "11"):
                _rules_and_decisions(center, job, {"9": "D", "10": "S", "11": "R"}[choice])
                center.io.pause()
                continue
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
                    target_language=snapshot["target_language"], path=target)
                center.io.write(f"Bundle written to {target}: {counts['entries']} wordings, {counts['rules']} approved renderings, "
                                f"{counts['key_terms']} key terms.")
            elif choice == "7":
                path = _ask_path(center, "Path of the terms bundle .json (blank to cancel)")
                if path:
                    report = transfer.import_bundle(
                        job, path, rows, lock_path=_lock(job), source_corpus_sha256=snapshot["source"]["content_sha256"],
                        target_language=snapshot["target_language"])
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
            elif choice == "4":
                _review_proposals(center, job, snapshot["source"]["content_sha256"])
        except SageError as exc:
            center.show_error(exc)
        center.io.pause()


def _latest_check(center, job):
    """(run, snapshot, output folder) of the newest finished check Run, or None."""
    for run in center.store.list_runs(job, include_archived=False):
        if run.operation == "check" and run.status in {"COMPLETE", "COMPLETE_WITH_EXCEPTIONS"}:
            output = run.root / "validation" / OUTPUT_DIRECTORY
            if (output / decisions.DETAIL_FILE).is_file():
                return run, load_run_snapshot(run.root), output
    return None


def _rules_and_decisions(center, job, choice: str) -> None:
    """Findings decisions (D), stale rules (S) and revoking a rule (R) — P7."""
    latest = _latest_check(center, job)
    config = load_ecosystem(job.runtime_settings_path)
    sha = latest[1]["source"]["content_sha256"] if latest else project_identity(config, job.bindings["source"])["content_sha256"]
    rules = glossary.current_rules(job.root)
    if choice == "D":
        if latest is None:
            center.io.write("Run a consistency check first; its PCC-FINDINGS.xlsx is what you decide on.")
            return
        path = _ask_path(center, "Path of the filled PCC-FINDINGS.xlsx (blank to cancel)")
        if path:
            report = decisions.import_finding_decisions(job, path, latest[2], lock_path=_lock(job), source_corpus_sha256=sha,
                                                        target_language=job.defaults["target_language"], actor=ACTOR)
            center.io.write(f"Recorded {report.imported} decision(s); {report.unchanged} already recorded. Run the check "
                            "again to see their effect.")
            for line in report.problems[:30]:
                center.io.write(f"- {line}")
        return
    if choice == "S":
        reported = json.loads((latest[2] / "stale-rules.json").read_text(encoding="utf-8")) if latest else {}
        pending = [rid for rid in sorted(reported) if rules.get(rid, {}).get("state") == "APPROVED"]
        marked = sorted(rid for rid, r in rules.items() if r["state"] == "STALE")
        center.io.write(f"{len(marked)} rule(s) already marked STALE; {len(pending)} reported by the last check as bound "
                        "to text that changed.")
        for rid in pending:
            rule = rules[rid]
            answer = center.io.choose(f"'{rule['target_form']}' ({rule['effect'].lower()}, {rule['scope']['level']}) at "
                                      f"{', '.join(reported[rid][:5])}",
                                      (("1", "Mark STALE (kept, never applied; decide again on the next findings)"),
                                       ("2", "Revoke"), ("S", "Skip"), ("B", "Stop")))
            if answer == "B":
                break
            if answer in ("1", "2"):
                glossary.change_rule_state(job, rid, "STALE" if answer == "1" else "REVOKED", lock_path=_lock(job),
                                           source_corpus_sha256=sha, reason="Reviewed: its text changed.", actor=ACTOR)
        return
    approved = sorted((r for r in rules.values() if r["state"] == "APPROVED"),
                      key=lambda r: (r["target_form"].casefold(), r["rule_id"]))
    if not approved:
        center.io.write("No approved renderings yet.")
        return
    for n, rule in enumerate(approved[:60], 1):
        center.io.write(f"{n:3}. {rule['target_form']}  ({rule['effect'].lower()}, {rule['scope']['level']})")
    text = center.io.text("Number of the rendering to revoke (blank to cancel)").strip()
    if text.isdigit() and 1 <= int(text) <= min(len(approved), 60):
        rule = approved[int(text) - 1]
        glossary.change_rule_state(job, rule["rule_id"], "REVOKED", lock_path=_lock(job), source_corpus_sha256=sha,
                                   reason="Revoked by the Operator.", actor=ACTOR)
        center.io.write(f"Revoked '{rule['target_form']}'. It stays in the journal and is never applied again.")


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
    """Delete or inspect one Job, pin its reference list, attach a WIP once; True once deleted."""
    options = [("1", "Delete PCC JOB"), ("2", "Recovery and diagnostics"), ("3", "Reference list (pin or re-pin)")]
    if not job.bindings.get("wip"):
        options.append(("4", "Attach a WIP (once)"))
    options.append(("B", "Back"))
    choice = center.io.choose(f"Manage PCC {job.job_id}", tuple(options), context=tuple(_binding_lines(job)))
    if choice == "1":
        return bool(center._delete_job(job))
    try:
        if choice == "2":
            center.recovery_menu(job)
        elif choice == "3":
            reference_list_menu(center, job)
        elif choice == "4":
            wip = center.choose_or_add_resource("PCC <WIP PROJECT>", "WIP")
            if wip is not None and center.io.confirm(
                    f"Attach {wip.project_id} to {job.job_id}? This cannot be changed later.", default=False):
                center.store.attach_pcc_wip(job, wip.project_id)
                center.io.write(f"WIP {wip.project_id} attached; the Job ID stays {job.job_id}.")
                center.io.pause()
    except SageError as exc:
        center.show_error(exc)
    return False


def _rl_store(center) -> ReferenceListStore:
    """The Operator's reference lists."""
    return ReferenceListStore(center.store.storage.resources_root)


def reference_list_menu(center, job) -> None:
    """Pin (or re-pin) a reference list for the Job's SOURCE: choose a stored one, build one, or keep none."""
    store = _rl_store(center)
    source = job.bindings["source"]
    lists = store.lists()
    lists.sort(key=lambda m: (m["reference"]["project_id"] != source, m["title"].casefold(), m["rl_id"]))
    options = []
    for n, manifest in enumerate(lists, 1):
        mark = " (this SOURCE)" if manifest["reference"]["project_id"] == source else ""
        options.append((str(n), f"{manifest['title']}: {manifest['rl_id']} v{manifest['version']}, "
                                 f"{manifest['counts']['entries']} concepts, built on {manifest['reference']['project_id']}{mark}"))
    build_key = str(len(lists) + 1)
    options += [(build_key, f"Build a new reference list from {source} now")]
    pin = job.defaults.get("reference_list")
    export_key, import_key = str(len(lists) + 2), str(len(lists) + 3)
    if pin:
        options += [(export_key, "Export the pinned list as a workbook (edit KEEP / DROP / NEW)"),
                    (import_key, "Import an edited workbook (writes a new version)")]
    options += [("B", "Keep the current setting")]
    context = (f"Pinned now                   {pin['rl_id']} v{pin['version']}" if pin else "Pinned now                   none",
               "A reference list holds the key concepts and their senses for one reference text. Glossary",
               "decisions carry over to a new version by concept and sense; rules whose concept is gone become STALE.")
    choice = center.io.choose(f"Reference list for {job.job_id}", tuple(options), context=context)
    if choice == "B":
        return
    if pin and choice == export_key:
        path = reflist_xlsx.export_workbook(store, pin["rl_id"], pin["version"], center.store.storage.exports_root / "pcc")
        center.io.write(f"Workbook written to {path}. Edit it, then import it here; pinning the new version is your choice.")
        center.io.pause()
        return
    if pin and choice == import_key:
        path = _ask_path(center, "Path of the edited reference-list workbook (blank to cancel)")
        if path is None:
            return
        context = None
        pinned, _ = store.load(pin["rl_id"], pin["version"])
        if pinned["reference"]["project_id"] == source:
            config = load_ecosystem(job.runtime_settings_path)
            project = config.project(source)
            center.io.write("Reading the reference text to locate NEW rows (uses the cached alignment).")
            context = reference_context(app_root=config.root, cache_root=config.cache_root,
                                        reference_path=Path(project.path), schema=load_project_vrs(config, project),
                                        settings=pinned["build"].get("settings"))
        result = reflist_xlsx.import_workbook(store, path, report_folder=center.store.storage.reports_root / job.job_id,
                                              context=context)
        for line in result.lines()[:30]:
            center.io.write(line)
        center.io.write(f"Changes: {result.diff_path}")
        if not (result.manifest and center.io.confirm(f"Pin {result.manifest['rl_id']} v{result.manifest['version']} "
                                                      "to this Job now?", default=True)):
            center.io.pause()
            return
        rl_id, version = result.manifest["rl_id"], result.manifest["version"]
    elif choice == build_key:
        manifest = _build_list(center, job)
        if manifest is None:
            return
        rl_id, version = manifest["rl_id"], manifest["version"]
    else:
        chosen = lists[int(choice) - 1]
        rl_id, version = chosen["rl_id"], chosen["version"]
    config = load_ecosystem(job.runtime_settings_path)
    report = repin(center.store, job, store, rl_id, version, actor=ACTOR, lock_path=_lock(job),
                   source_corpus_sha256=project_identity(config, source)["content_sha256"],
                   reports_root=center.store.storage.reports_root)
    for line in report.lines():
        center.io.write(line)
    center.io.write(f"Report: {report.report_path}")
    center.io.pause()


def _build_list(center, job):
    """Build a reference list from the Job's SOURCE (whole text) and return its manifest, or None."""
    config = load_ecosystem(job.runtime_settings_path)
    project = config.project(job.bindings["source"])
    terms = Path(project.path) / "BiblicalTerms.xml"
    biblical_terms = None
    if terms.is_file() and center.io.confirm(f"Use the Paratext Biblical Terms list of {project.project_id} "
                                             "(read only, kept local)?", default=True):
        biblical_terms = terms
    elif not terms.is_file():
        biblical_terms = _ask_path(center, "Path of a Paratext BiblicalTerms.xml (blank: none; the list then holds "
                                           "only your declared phrases)")
    phrases = job.root / "input" / "phrases.txt"
    title = center.io.text(f"Title for the list (blank: {project.project_id} reference list)").strip() \
        or f"{project.project_id} reference list"
    schema = load_project_vrs(config, project)
    center.io.write("Aligning the SOURCE with the original language. The first time takes a few minutes; "
                    "later builds and terms Runs reuse the alignment.")
    outcome = build_reference_list_for(
        app_root=config.root, store=_rl_store(center), cache_root=config.cache_root, reference_path=Path(project.path),
        project_id=project.project_id, title=title, language_tag=project.language_code,
        schema=schema, versification_id=schema.schema_id, biblical_terms=biblical_terms,
        phrases=phrases if phrases.is_file() else None, instance_id=str(center.store.storage.data_root),
        progress=lambda stage, detail: center.io.write(f"  {stage}: {detail}") if stage != "index" else None)
    left = outcome.result.left_out
    center.io.write(f"Built {outcome.manifest['rl_id']} v{outcome.manifest['version']}: "
                    f"{outcome.manifest['counts']['entries']} concepts. Left out: {left['NOT_IN_REFERENCE']} not in "
                    f"the text, {left['BELOW_RECURRENCE']} not recurring, {left['NO_REALIZATION'] + left['FUNCTION_ONLY']} "
                    "not rendered by a wording.")
    for problem in outcome.result.declared_problems[:20]:
        center.io.write(f"- phrases.txt {problem}")
    return outcome.manifest


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
