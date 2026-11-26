"""PCC operator flow: Main Menu #6 home, reference lists, PCC Jobs and their WIP lists and Runs.

PCC has two separate functions (PO 2026-11-26):

1. **Reference lists** are master SOURCE lists built from complete REFERENCE texts. They live outside every Job,
   in ``localdata/inputs/resources/reference-lists``, and are reused by any number of Jobs. A list can be built
   from a text, or from another list (usNIV curated list -> Spanish NVI base list). Every change is a new version.
2. **PCC Jobs** maintain one WIP. When a Job pins a master list it **clones** it into the Job's own **WIP list**
   (``sage.pcc.layers``). Everything the team changes while working on the WIP (added wordings, left-out
   concepts, notes) goes to the WIP list. The Operator may merge those additions and omissions into the master,
   through a menu action (all or chosen changes) or by editing a changes workbook. The Job also holds the WIP's
   TARGET renderings (glossary), its terms and check Runs and the decisions on findings.

This module only collects choices; the work is done in ``sage.pcc``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sage.errors import SageError, ValidationError
from sage.jobs import PCC_RUN_OPERATIONS, pcc_default_settings
from sage.pcc import decisions, glossary, layers, reflist_xlsx, rlexchange, transfer
from sage.pcc.phrases import job_phrase_lines, retire_job_phrases
from sage.pcc.pin import repin
from sage.pcc.reflist import ReferenceListStore
from sage.pcc.rlservice import add_biblical_terms, build_reference_list_for, reference_context
from sage.pcc.source_text import books_label, present_books, source_content_sha256
from sage.pcc.run import OUTPUT_DIRECTORY, execute_pcc_run, load_run_snapshot, project_identity, run_initializer
from sage.registry import load_ecosystem
from sage.vrs import load_project_vrs

ACTOR = "operator"

TITLE = "PHRASE CONSISTENCY CHECKER (PCC)"
OPERATION_LABELS = {"terms": "Build SOURCE terms list", "check": "Check WIP against the glossary"}
RL_REPORTS = "pcc-reference-lists"
MODE_LABELS = {"SCRATCH": "built from the text", "INHERIT": "built from another list", "MERGE": "edited",
               "IMPORT": "imported", "LOCAL": "WIP list"}


# --- shared helpers -------------------------------------------------------------------------------------


def _config(center, job=None):
    """The Job's runtime settings, or SAGE's own settings outside a Job."""
    return load_ecosystem(job.runtime_settings_path if job is not None else center.store.settings_path)


def _rl_store(center) -> ReferenceListStore:
    """The Operator's reference lists (shared by every Job)."""
    return ReferenceListStore(center.store.storage.resources_root)


def _rl_reports(center) -> Path:
    """Reports about reference lists (they belong to no Job)."""
    return center.store.storage.reports_root / RL_REPORTS


def _lock(job) -> Path:
    """Return the Job's journal lock path."""
    return job.controller_root / "locks" / "pcc-journal.lock"


def _ask_path(center, prompt: str) -> Path | None:
    """Ask for an existing file path; blank cancels."""
    text = center.io.text(prompt, required=False).strip().strip("'\"")
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_file():
        center.io.write(f"No file at {path}.")
        return None
    return path


def _pcc_jobs(center) -> list:
    """Every readable PCC Job."""
    return list(center.store.discover_report("pcc", include_archived=False).jobs)


def _jobs_on(center, rl_id: str) -> list[tuple[str, int]]:
    """(Job ID, pinned version) of every Job that pins ``rl_id``."""
    found = []
    for job in _pcc_jobs(center):
        pin = job.defaults.get("reference_list")
        if pin and pin["rl_id"] == rl_id:
            found.append((job.job_id, int(pin["version"])))
    return sorted(found)


def _list_label(manifest: dict[str, Any], pinned: dict[str, Any] | None = None, source: str | None = None) -> str:
    """One line naming a list's newest version."""
    marks = []
    parent = manifest["build"].get("parent")
    if parent:
        marks.append(f"WIP list of {parent['rl_id']} v{parent['version']}, "
                     f"{len(manifest['build'].get('local', []))} change(s)")
    if pinned and pinned["rl_id"] == manifest["rl_id"]:
        marks.append(f"this JOB's list: v{pinned['version']}")
    if source and manifest["reference"]["project_id"] == source:
        marks.append("this SOURCE")
    counts = manifest["counts"]
    return (f"{manifest['title']}: {manifest['rl_id']} v{manifest['version']}, {counts['entries']} concepts "
            f"({counts.get('proposed', 0)} to review), built on {manifest['reference']['project_id']}"
            + (f" ({'; '.join(marks)})" if marks else ""))


def _choose_list(center, title: str, job=None, kind: str = "any"):
    """Choose one stored list (``kind``: any, master or wip); returns its newest manifest or None."""
    lists = _rl_store(center).lists()
    if kind == "master":
        lists = [m for m in lists if not layers.is_clone(m)]
    elif kind == "wip":
        lists = [m for m in lists if layers.is_clone(m)]
    if not lists:
        center.io.write({"master": "No master list is stored yet. Build one first (Reference lists).",
                         "wip": "No WIP list exists yet: a Job makes one when it pins a master list."}.get(
            kind, "No reference list is stored yet. Build one first (Build a new list from a reference text)."))
        return None
    pin = job.defaults.get("reference_list") if job is not None else None
    source = job.bindings.get("source") if job is not None else None
    lists.sort(key=lambda m: (not (pin and m["rl_id"] == pin["rl_id"]), m["reference"]["project_id"] != source,
                              layers.is_clone(m), m["title"].casefold(), m["rl_id"]))
    options = [(str(n), _list_label(m, pin, source)) for n, m in enumerate(lists, 1)] + [("B", "Back")]
    choice = center.io.choose(title, tuple(options))
    return None if choice == "B" else lists[int(choice) - 1]


def _choose_version(center, rl_id: str, title: str, default: int | None = None) -> int | None:
    """Choose one version of a list (newest first)."""
    versions = _rl_store(center).versions(rl_id)
    if len(versions) == 1:
        return versions[0]
    options = []
    for n, version in enumerate(reversed(versions), 1):
        manifest, _ = _rl_store(center).load(rl_id, version)
        build = manifest["build"]
        origin = MODE_LABELS.get(build["mode"], build["mode"])
        if build.get("derived_from") and build["mode"] == "INHERIT":
            origin += f" ({build['derived_from']['rl_id']} v{build['derived_from']['version']})"
        mark = " (default)" if version == default else ""
        options.append((str(n), f"v{version}: {manifest['counts']['entries']} concepts, {origin}, "
                                f"{manifest['created_utc'][:10]}{mark}"))
    choice = center.io.choose(title, tuple(options + [("B", "Back")]))
    return None if choice == "B" else list(reversed(versions))[int(choice) - 1]


def _list_context(center, manifest: dict[str, Any], job=None):
    """The alignment context of a list's own reference text, or None (with a message) when it is not available."""
    config = _config(center, job)
    project_id = manifest["reference"]["project_id"]
    try:
        project = config.project(project_id)
    except SageError:
        center.io.write(f"The reference text {project_id} is not in this SAGE instance: wordings are kept on the list "
                        "without senses until the list is rebuilt on a SAGE that has the text.")
        return None
    center.io.write(f"Reading {project_id} to locate the wordings (uses the cached alignment).")
    return reference_context(app_root=config.root, cache_root=config.cache_root, reference_path=Path(project.path),
                             schema=load_project_vrs(config, project), settings=manifest["build"].get("settings"))


def _show_import(center, result) -> None:
    """Report a list change and where its report is."""
    for line in result.lines()[:40]:
        center.io.write(line)
    path = getattr(result, "diff_path", None) or getattr(result, "report_path", None)
    if path:
        center.io.write(f"Report: {path}")


def _after_new_version(center, manifest: dict[str, Any] | None, job=None) -> None:
    """After a new list version: re-pin the Job's own list, otherwise name the Jobs still on older versions."""
    if manifest is None:
        return
    rl_id, version = manifest["rl_id"], manifest["version"]
    if job is not None:
        job = center.store.load_job(job.job_id, tool="pcc")
        pin = job.defaults.get("reference_list")
        if pin and pin["rl_id"] == rl_id and center.io.confirm(f"Pin {rl_id} v{version} to {job.job_id} now?",
                                                                 default=True):
            _repin(center, job, rl_id, version)
            return
    older = [f"{job_id} (v{v})" for job_id, v in _jobs_on(center, rl_id) if v < version]
    if older:
        center.io.write(f"Jobs on an older version of this list: {', '.join(older)}. Each Job moves to v{version} only "
                        "when you re-pin it.")
    wip_lists = [m for m in _rl_store(center).lists()
                 if layers.is_clone(m) and m["build"]["parent"]["rl_id"] == rl_id
                 and m["build"]["parent"]["version"] < version]
    if wip_lists and not layers.is_clone(manifest):
        center.io.write(f"WIP lists on an older version of this master: {', '.join(m['rl_id'] for m in wip_lists)}. "
                        "Update them from the master (Reference lists -> Update a WIP list from its master).")


def _repin(center, job, rl_id: str, version: int) -> None:
    """Pin a list version to the Job and show the carry-over report."""
    config = _config(center, job)
    job = center.store.load_job(job.job_id, tool="pcc")
    report = repin(center.store, job, _rl_store(center), rl_id, version, actor=ACTOR, lock_path=_lock(job),
                   source_corpus_sha256=project_identity(config, job.bindings["source"])["content_sha256"],
                   reports_root=center.store.storage.reports_root)
    for line in report.lines():
        center.io.write(line)
    center.io.write(f"Report: {report.report_path}")


def _biblical_terms_path(center, project) -> Path | None:
    """The text's own Paratext Biblical Terms list (on confirmation), or a path the Operator gives, or None."""
    terms = Path(project.path) / "BiblicalTerms.xml"
    if terms.is_file():
        if center.io.confirm(f"Use the Paratext Biblical Terms list of {project.project_id} (read only, kept local)?",
                             default=True):
            return terms
        return None
    return _ask_path(center, "Path of a Paratext BiblicalTerms.xml (blank: none)")


def _clone_for_job(center, job, master_id: str, version: int | None) -> dict[str, Any]:
    """Clone a master list version into this Job's WIP list and pin it."""
    master = _rl_store(center).load(master_id, version)[0]
    wip = job.bindings.get("wip") or job.job_id
    clone = layers.create_clone(_rl_store(center), master_id, master["version"], title=f"{master['title']} - {wip}",
                                instance_id=str(center.store.storage.data_root))
    center.io.write(f"{job.job_id} now has its own WIP list {clone['rl_id']} (a clone of {master_id} "
                    f"v{master['version']}). Changes made in this Job go to it; merge them into the master when you "
                    "choose.")
    _repin(center, job, clone["rl_id"], clone["version"])
    return clone


def _job_list(center, job) -> dict[str, Any] | None:
    """The Job's own WIP list (newest version). An older Job pinned to a master is offered a clone first."""
    pin = job.defaults.get("reference_list")
    if not pin:
        center.io.write("This JOB has no reference list yet: pin a master list first (it is cloned for this WIP).")
        return None
    manifest = _rl_store(center).load(pin["rl_id"], None)[0]
    if layers.is_clone(manifest):
        return manifest
    if not center.io.confirm(f"This JOB uses the master list {pin['rl_id']} directly. Clone it into this JOB's own WIP "
                             "list first? (Changes then stay with this WIP until you merge them.)", default=True):
        return manifest
    return _clone_for_job(center, job, pin["rl_id"], pin["version"])


# --- function 1: reference lists ------------------------------------------------------------------------


def reference_lists_menu(center, job=None) -> None:
    """Master lists and WIP lists outside a Job; inside a Job the Job's WIP list, pinning and merging."""
    while True:
        if job is not None:
            job = center.store.load_job(job.job_id, tool="pcc")
        lists = _rl_store(center).lists()
        masters = sum(1 for m in lists if not layers.is_clone(m))
        context = [f"Master lists                 {masters}",
                   f"WIP lists                    {len(lists) - masters}",
                   "A master list holds the key concepts of one complete reference text. Each Job clones it into",
                   "its own WIP list; merge a WIP list's changes into the master when you choose."]
        options = [("1", "Show lists and versions"),
                   ("2", "Build a new list from a reference text"),
                   ("3", "Build a new list from an existing list (another text, or a rebuild)"),
                   ("4", "Export a list for curation (workbook: KEEP / DROP / NEW)"),
                   ("5", "Import a curated workbook (new version)"),
                   ("6", "Add my own SOURCE wordings (CSV, TXT or XLSX; new version)"),
                   ("7", "Add Paratext Biblical Terms (new version)"),
                   ("8", "Compare two versions of a list"),
                   ("9", "Update a WIP list from its master"),
                   ("10", "Merge WIP-list changes into the master"),
                   ("11", "Export a list to share with another SAGE (.sagerl.zip)"),
                   ("12", "Import a shared list (.sagerl.zip)")]
        title = "PCC REFERENCE LISTS"
        moved = []
        if job is not None:
            pin = job.defaults.get("reference_list")
            context = [f"PCC JOB                      {job.job_id}",
                       f"This JOB's list              {pin['rl_id']} v{pin['version']}" if pin else
                       "This JOB's list              none"] + context
            options.append(("13", "Pin a master list to this JOB (cloned into this JOB's WIP list)"))
            moved = job_phrase_lines(job.root)
            if moved:
                options.append(("14", f"Move this JOB's own wordings into its list ({len(moved)} in phrases.txt)"))
            title = f"Reference list for {job.job_id}"
        choice = center.io.choose(title, tuple(options + [("B", "Back")]), context=tuple(context))
        if choice == "B":
            return
        try:
            _reference_list_action(center, choice, job, moved)
        except SageError as exc:
            center.show_error(exc)
        center.io.pause()


def _target_list(center, job, title: str):
    """Inside a Job: the Job's WIP list. Outside: any list the Operator chooses."""
    return _job_list(center, job) if job is not None else _choose_list(center, title)


def _reference_list_action(center, choice: str, job, moved: list[tuple[int, str]]) -> None:
    """Run one reference-list action."""
    store = _rl_store(center)
    if choice == "1":
        _show_lists(center)
    elif choice == "2":
        _after_build(center, _build_from_text(center, job), job)
    elif choice == "3":
        _after_build(center, _build_from_list(center, job), job)
    elif choice == "4":
        manifest = _target_list(center, job, "Export which list?")
        if manifest:
            path = reflist_xlsx.export_workbook(store, manifest["rl_id"], manifest["version"],
                                                center.store.storage.exports_root / "pcc")
            center.io.write(f"Workbook of {manifest['rl_id']} v{manifest['version']} written to {path}. Set Status to "
                            "KEEP, DROP or leave it blank; add NEW rows with a wording; then import it here.")
    elif choice == "5":
        path = _ask_path(center, "Path of the edited reference-list workbook (blank to cancel)")
        if path:
            about = reflist_xlsx._rows(path)[0]
            rl_id = str(about.get("rl_id") or "")
            manifest = store.load(rl_id, None)[0] if store.versions(rl_id) else None
            context = _list_context(center, manifest, job) if manifest else None
            result = reflist_xlsx.import_workbook(store, path, report_folder=_rl_reports(center), context=context)
            _show_import(center, result)
            _after_new_version(center, result.manifest, job)
    elif choice == "6":
        manifest = _target_list(center, job, "Add wordings to which list?")
        path = _ask_path(center, "Path of your list (first column: SOURCE wording; blank to cancel)") if manifest else None
        if path:
            items = [(n, cells[0].strip()) for n, cells in transfer._operator_lines(path)
                     if cells and cells[0].strip() and not cells[0].strip().startswith("#")
                     and not (n == 1 and cells[0].strip().casefold() in transfer._HEADER_WORDS)]
            _add_wordings(center, manifest, items, path.name, job)
    elif choice == "7":
        _add_terms(center, job)
    elif choice == "8":
        manifest = _choose_list(center, "Compare versions of which list?", job)
        if manifest:
            versions = store.versions(manifest["rl_id"])
            if len(versions) < 2:
                center.io.write("This list has one version only.")
                return
            new = _choose_version(center, manifest["rl_id"], "Newer version", default=versions[-1])
            old = _choose_version(center, manifest["rl_id"], "Older version", default=versions[-2]) if new else None
            if new and old:
                result, path = reflist_xlsx.compare_versions(store, manifest["rl_id"], min(old, new), max(old, new),
                                                             report_folder=_rl_reports(center))
                center.io.write(f"Added {len(result.added)}, removed {len(result.problems)}, dropped "
                                f"{len(result.dropped)}, status changed {len(result.kept)}, other changes "
                                f"{len(result.changed)}. Report: {path}")
    elif choice == "9":
        clone = _job_list(center, job) if job is not None else _choose_list(center, "Update which WIP list?", kind="wip")
        if clone and layers.is_clone(clone):
            _update_clone(center, clone, job)
    elif choice == "10":
        clone = _job_list(center, job) if job is not None else _choose_list(center, "Merge which WIP list?", kind="wip")
        if clone and layers.is_clone(clone):
            merge_menu(center, clone, job)
    elif choice == "11":
        _export_shared(center, job)
    elif choice == "12":
        _import_shared(center, job)
    elif choice == "13" and job is not None:
        pin = job.defaults.get("reference_list")
        if pin and layers.is_clone(store.load(pin["rl_id"], None)[0]):
            changes = len(store.load(pin["rl_id"], None)[0]["build"].get("local", []))
            center.io.write(f"This JOB already has its WIP list {pin['rl_id']} ({changes} change(s)). To follow a newer "
                            "master, use Update a WIP list from its master. Pinning another master replaces it; "
                            "merge its changes first if the master should keep them.")
            if not center.io.confirm("Pin another master list anyway?", default=False):
                return
        manifest = _choose_list(center, f"Pin which master list to {job.job_id}?", job, kind="master")
        if manifest:
            version = _choose_version(center, manifest["rl_id"], "Pin which version?", default=manifest["version"])
            if version:
                _clone_for_job(center, job, manifest["rl_id"], version)
    elif choice == "14" and job is not None and moved:
        manifest = _job_list(center, job)
        if manifest is None:
            return
        if _add_wordings(center, manifest, moved, "phrases.txt", job) is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            kept = retire_job_phrases(job.root, stamp)
            center.io.write(f"phrases.txt is now on the list; the file was kept as {kept.name}.")


def _export_shared(center, job=None) -> None:
    """Export one list (a WIP list together with its master version) as a .sagerl.zip."""
    manifest = _target_list(center, job, "Export which list?")
    if manifest is None:
        return
    if manifest["license"].get("local_only") and not center.io.confirm(
            f"{manifest['rl_id']} is marked local only (built from licensed text or Paratext Biblical Terms). Share it "
            "only within your organization's license. Export it?", default=False):
        return
    path, index = rlexchange.export_list(_rl_store(center), manifest["rl_id"], manifest["version"],
                                         center.store.storage.exports_root / "pcc")
    what = "WIP list with its master version" if index["kind"] == "WIP_LIST" else "master list"
    center.io.write(f"Package written to {path} ({what}). Import it on the other SAGE under Reference lists -> 12.")


def _import_shared(center, job=None) -> None:
    """Import a .sagerl.zip; inside a Job offer to pin what came in."""
    path = _ask_path(center, f"Path of the {rlexchange.SUFFIX} package (blank to cancel)")
    if path is None:
        return
    result = rlexchange.import_list(_rl_store(center), path)
    for line in result.lines():
        center.io.write(line)
    main = result.main
    if job is None or main is None:
        return
    if layers.is_clone(main):
        if center.io.confirm(f"Pin WIP list {main['rl_id']} v{main['version']} to {job.job_id} (it becomes this JOB's "
                             "WIP list)?", default=False):
            _repin(center, job, main["rl_id"], main["version"])
    elif center.io.confirm(f"Pin master {main['rl_id']} v{main['version']} to {job.job_id} (cloned into this JOB's WIP "
                           "list)?", default=False):
        _clone_for_job(center, job, main["rl_id"], main["version"])


def _after_build(center, manifest, job) -> None:
    """A newly built master: inside a Job offer to clone it for this WIP; outside name nothing more."""
    if manifest is None:
        return
    if job is not None and center.io.confirm(f"Pin {manifest['rl_id']} to {job.job_id} (cloned into this JOB's WIP "
                                             "list)?", default=True):
        _clone_for_job(center, job, manifest["rl_id"], manifest["version"])
        return
    _after_new_version(center, manifest, job)


def _update_clone(center, clone: dict[str, Any], job=None) -> None:
    """Re-apply a WIP list's changes to the newest master version."""
    result = layers.update_clone(_rl_store(center), clone["rl_id"], report_folder=_rl_reports(center))
    _show_import(center, result)
    _after_new_version(center, result.manifest, job)


def merge_menu(center, clone: dict[str, Any], job=None) -> None:
    """Merge a WIP list's additions and omissions into its master: all, chosen, or through the changes workbook."""
    store = _rl_store(center)
    changes = clone["build"].get("local", [])
    parent = clone["build"]["parent"]
    master_entries = {e["concept_key"]: e for e in store.load(parent["rl_id"], parent["version"])[1]}
    context = [f"WIP list                     {clone['rl_id']} v{clone['version']}",
               f"Master                       {parent['rl_id']} v{parent['version']}",
               f"Changes in this WIP list     {len(changes)}"]
    options = (("1", "Merge all changes into the master"), ("2", "Choose changes to merge"),
               ("3", "Export the changes for manual edit (workbook)"), ("4", "Import an edited changes workbook"),
               ("B", "Back"))
    choice = center.io.choose(f"Merge {clone['rl_id']} into its master", options, context=tuple(context))
    if choice == "B":
        return
    if choice in ("1", "2") and not changes:
        center.io.write("This WIP list has no changes against its master.")
        return
    chosen, edits = None, None
    if choice == "2":
        for n, change in enumerate(changes, 1):
            center.io.write(f"{n:3}. {layers.describe(change, master_entries.get(change['concept_key']))}")
        text = center.io.text("Numbers to merge (for example 1,3,5-7; blank to cancel)", required=False).strip()
        picked = _parse_numbers(text, len(changes))
        if not picked:
            return
        chosen = [changes[i - 1]["change_id"] for i in picked]
    elif choice == "3":
        path = layers.export_changes(store, clone["rl_id"], center.store.storage.exports_root / "pcc")
        center.io.write(f"Changes workbook written to {path}. Set Merge to YES for the changes the master should get; "
                        "edit Category or Notes if needed; then import it here (option 4).")
        return
    elif choice == "4":
        path = _ask_path(center, "Path of the edited RL-CHANGES workbook (blank to cancel)")
        if path is None:
            return
        clone_id, chosen, edits, problems = layers.read_changes(path)
        for line in problems:
            center.io.write(f"- {line}")
        if clone_id != clone["rl_id"]:
            center.io.write(f"That workbook belongs to WIP list {clone_id or '?'}, not {clone['rl_id']}.")
            return
        if not chosen:
            center.io.write("No row has Merge set to YES.")
            return
    result = layers.merge_to_master(store, clone["rl_id"], chosen, report_folder=_rl_reports(center), edits=edits)
    _show_import(center, result)
    if result.master is None:
        return
    jobs = [j for j, _ in _jobs_on(center, result.master["rl_id"])]
    if jobs:
        center.io.write(f"Jobs that pin the master directly: {', '.join(jobs)}.")
    if center.io.confirm(f"Update {clone['rl_id']} from master v{result.master['version']} now?", default=True):
        _update_clone(center, store.load(clone["rl_id"], None)[0], job)


def _parse_numbers(text: str, limit: int) -> list[int]:
    """'1,3,5-7' -> [1, 3, 5, 6, 7] within 1..limit; anything else is ignored."""
    picked: set[int] = set()
    for part in text.replace(" ", "").split(","):
        if "-" in part:
            a, _, b = part.partition("-")
            if a.isdigit() and b.isdigit():
                picked.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            picked.add(int(part))
    return sorted(n for n in picked if 1 <= n <= limit)


def _coverage(center, manifest: dict[str, Any]) -> tuple[str, list[str]]:
    """(coverage line, warnings) of a list against its reference text as it is now in this SAGE."""
    books = manifest["build"].get("settings", {}).get("books")
    line = f"Built on {books_label(books)}" if isinstance(books, list) else "Built on: not recorded"
    try:
        project = _config(center).project(manifest["reference"]["project_id"])
    except SageError:
        return line + " (the reference text is not in this SAGE)", []
    warnings = []
    present = present_books(Path(project.path))
    if isinstance(books, list) and set(present) - set(books):
        warnings.append(f"The text now has {books_label(present)}: widen the list (Build a new list from an existing "
                        "list, with the same text). Every decision is kept.")
    elif source_content_sha256(Path(project.path)) != manifest["reference"]["content_sha256"]:
        warnings.append("The text changed since this version was built: rebuild it on the same text to locate the "
                        "concepts again (every decision is kept).")
    return line, warnings


def _show_lists(center) -> None:
    """Every master list with its versions, its WIP lists and the Jobs that pin them."""
    store = _rl_store(center)
    lists = store.lists()
    if not lists:
        center.io.write("No reference list is stored yet.")
        return
    clones: dict[str, list[dict[str, Any]]] = {}
    for manifest in lists:
        if layers.is_clone(manifest):
            clones.setdefault(manifest["build"]["parent"]["rl_id"], []).append(manifest)
    masters = [m for m in lists if not layers.is_clone(m)]
    known = {m["rl_id"] for m in masters}
    for manifest in masters:
        ref = manifest["reference"]
        center.io.write(f"{manifest['title']}  ({manifest['rl_id']}, master)")
        center.io.write(f"  Reference text: {ref['project_id']} [{ref['language_tag']}]")
        coverage, warnings = _coverage(center, manifest)
        center.io.write(f"  {coverage} (newest version)")
        for warning in warnings:
            center.io.write(f"  ! {warning}")
        for version in reversed(store.versions(manifest["rl_id"])):
            try:
                m, _ = store.load(manifest["rl_id"], version)
            except SageError:
                center.io.write(f"  v{version}: unreadable (failed its checksum)")
                continue
            build, counts = m["build"], m["counts"]
            origin = MODE_LABELS.get(build["mode"], build["mode"])
            if build.get("derived_from") and build["mode"] == "INHERIT":
                origin += f" {build['derived_from']['rl_id']} v{build['derived_from']['version']}"
            if build.get("summary", {}).get("merged_from_wip_list") and build["mode"] == "MERGE":
                origin += f", merged from {build['summary']['merged_from_wip_list']['rl_id']}"
            center.io.write(f"  v{version} {m['created_utc'][:10]}: {counts['entries']} concepts ({counts.get('active', 0)} "
                            f"kept, {counts.get('proposed', 0)} to review, {counts.get('dropped', 0)} dropped); {origin}")
        jobs = _jobs_on(center, manifest["rl_id"])
        if jobs:
            center.io.write("  Pinned directly by: " + ", ".join(f"{j} (v{v})" for j, v in jobs))
        for clone in clones.get(manifest["rl_id"], []):
            _show_clone(center, clone)
        center.io.write("")
    for parent_id, orphans in sorted(clones.items()):
        if parent_id not in known:
            for clone in orphans:
                center.io.write(f"(master {parent_id} is not in this SAGE)")
                _show_clone(center, clone)


def _show_clone(center, clone: dict[str, Any]) -> None:
    """One WIP list under its master."""
    changes = clone["build"].get("local", [])
    adds = sum(1 for c in changes if c["op"] == "ADD")
    left = sum(1 for c in changes if c["op"] == "SET" and c["fields"].get("status") == "DROPPED")
    jobs = _jobs_on(center, clone["rl_id"])
    center.io.write(f"  - WIP list {clone['title']} ({clone['rl_id']}) v{clone['version']} on master "
                    f"v{clone['build']['parent']['version']}: {adds} added, {left} left out, "
                    f"{len(changes) - adds - left} other change(s); "
                    + ("pinned by " + ", ".join(f"{j} (v{v})" for j, v in jobs) if jobs else "no Job"))


def _build_from_text(center, job=None):
    """Build a new master list from a complete reference text; returns the new manifest or None."""
    config = _config(center, job)
    project = center.choose_or_add_resource("Build a reference list from which <REFERENCE TEXT>?", "REFERENCE")
    if project is None:
        return None
    project = config.project(project.project_id)
    biblical_terms = _biblical_terms_path(center, project)
    title = center.io.text(f"Title for the list (blank: {project.project_id} reference list)", required=False).strip() \
        or f"{project.project_id} reference list"
    return _run_build(center, config, project, title, biblical_terms, None)


def _build_from_list(center, job=None):
    """Build a master list for another text from an existing master (or rebuild one text); returns the manifest."""
    config = _config(center, job)
    base = _choose_list(center, "Use which master list as the base?", job, kind="master")
    if base is None:
        return None
    version = _choose_version(center, base["rl_id"], "Use which version as the base?", default=base["version"])
    if version is None:
        return None
    project = center.choose_or_add_resource("Build the new list for which <REFERENCE TEXT>?", "REFERENCE")
    if project is None:
        return None
    project = config.project(project.project_id)
    same = project.project_id == base["reference"]["project_id"]
    if same:
        books = base["build"].get("settings", {}).get("books")
        present = present_books(Path(project.path))
        was = f" (the list covered {books_label(books)})" if isinstance(books, list) and books != present else ""
        center.io.write(f"Same text as the base: this rebuilds {base['rl_id']} on all {books_label(present)} of "
                        f"{project.project_id}{was} as its next version. Every decision is kept: KEEP, DROP, notes "
                        "and added wordings.")
        title = base["title"]
    else:
        center.io.write(f"The concepts of {base['rl_id']} v{version} are carried over by original-language key and "
                        f"located in {project.project_id}. They arrive as PROPOSED: review them in the new list's "
                        "workbook (KEEP / DROP). Concepts the team dropped stay out.")
        title = center.io.text(f"Title for the new list (blank: {project.project_id} reference list)",
                               required=False).strip() or f"{project.project_id} reference list"
    biblical_terms = _biblical_terms_path(center, project)
    return _run_build(center, config, project, title, biblical_terms, (base["rl_id"], version))


def _run_build(center, config, project, title: str, biblical_terms: Path | None, base):
    """Align and build; report what was kept, left out and not carried."""
    schema = load_project_vrs(config, project)
    center.io.write("Aligning the text with the original language. The first time takes a few minutes; later "
                    "builds and terms Runs reuse the alignment.")
    outcome = build_reference_list_for(
        app_root=config.root, store=_rl_store(center), cache_root=config.cache_root, reference_path=Path(project.path),
        project_id=project.project_id, title=title, language_tag=project.language_code, schema=schema,
        versification_id=schema.schema_id, biblical_terms=biblical_terms, base=base,
        instance_id=str(center.store.storage.data_root),
        progress=lambda stage, detail: center.io.write(f"  {stage}: {detail}") if stage != "index" else None)
    manifest, left = outcome.manifest, outcome.result.left_out
    center.io.write(f"Built {manifest['rl_id']} v{manifest['version']}: {manifest['counts']['entries']} concepts "
                    f"({manifest['counts'].get('proposed', 0)} to review). Left out: {left['NOT_IN_REFERENCE']} not in "
                    f"the text, {left['BELOW_RECURRENCE']} not recurring, "
                    f"{left['NO_REALIZATION'] + left['FUNCTION_ONLY']} not rendered by a wording.")
    carried = outcome.report.get("inherited") or {}
    if carried:
        center.io.write(f"From the base list: {carried['concepts']} concept(s) carried, {carried['dropped']} dropped "
                        "decision(s) kept.")
        if "drops_kept" in carried:
            center.io.write(f"{carried['drops_kept']} DROP decision(s) kept.")
        unchanged = carried.get("kept_unchanged") or []
        if unchanged:
            center.io.write(f"{len(unchanged)} concept(s) could not be located again and were kept as they were: "
                            f"{', '.join(unchanged[:15])}{' ...' if len(unchanged) > 15 else ''}.")
        other = carried.get("wordings_other_language") or []
        if other:
            center.io.write(f"{len(other)} wording(s) the team added to the base list are in another language and were "
                            f"not carried: {', '.join(other[:15])}{' ...' if len(other) > 15 else ''}. Add them in "
                            "this list's language (Add my own SOURCE wordings).")
    for problem in outcome.result.declared_problems[:20]:
        center.io.write(f"- {problem}")
    return manifest


def _add_wordings(center, manifest: dict[str, Any], items: list[tuple[int, str]], origin: str, job=None):
    """Add (line, wording) pairs to the newest version of a list; returns the import result or None."""
    if not items:
        center.io.write("No wordings to add.")
        return None
    context = _list_context(center, manifest, job)
    result = reflist_xlsx.add_wordings(_rl_store(center), manifest["rl_id"], None, items,
                                       report_folder=_rl_reports(center), context=context, origin=origin)
    _show_import(center, result)
    _after_new_version(center, result.manifest, job)
    return result


def _add_terms(center, job=None) -> None:
    """Add Paratext Biblical Terms to the newest version of a list."""
    manifest = _target_list(center, job, "Add Biblical Terms to which list?")
    if manifest is None:
        return
    config = _config(center, job)
    try:
        project = config.project(manifest["reference"]["project_id"])
    except SageError:
        center.io.write(f"The reference text {manifest['reference']['project_id']} is not in this SAGE instance; "
                        "Biblical Terms are located in the text, so they cannot be added here.")
        return
    path = _biblical_terms_path(center, project)
    if path is None:
        return
    center.io.write(f"Locating the terms in {project.project_id} (uses the cached alignment).")
    result, _ = add_biblical_terms(app_root=config.root, store=_rl_store(center), cache_root=config.cache_root,
                                   rl_id=manifest["rl_id"], version=None, reference_path=Path(project.path),
                                   schema=load_project_vrs(config, project), biblical_terms=path,
                                   report_folder=_rl_reports(center))
    _show_import(center, result)
    _after_new_version(center, result.manifest, job)


# --- function 2: PCC Jobs (WIP lists) -------------------------------------------------------------------


def _binding_lines(job) -> list[str]:
    """Show the Job's bindings with the role names the Operator sees."""
    lines = [f"PCC JOB                      {job.job_id}", f"SOURCE                       {job.bindings['source']}"]
    if job.bindings.get("secondary_source"):
        lines.append(f"Secondary SOURCE             {job.bindings['secondary_source']}")
    lines.append(f"WIP                          {job.bindings.get('wip') or 'NONE (terms list only)'}")
    lines.append(f"Target language              {job.defaults.get('target_language')}")
    pin = job.defaults.get("reference_list")
    lines.append(f"Reference list               {pin['rl_id']} v{pin['version']}" if pin
                 else "Reference list               NONE (pin a master list under Reference list)")
    return lines


def create_job(center):
    """Resolve SOURCE, optional secondary SOURCE and optional WIP before anything is persisted; then pin a list."""
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
        _pin_at_creation(center, job)
    except SageError as exc:
        center.show_error(exc)
    return center.store.load_job(job.job_id, tool="pcc")


def _pin_at_creation(center, job) -> None:
    """A new Job pins a master list (stored or built now); it is cloned into the Job's own WIP list."""
    masters = [m for m in _rl_store(center).lists() if not layers.is_clone(m)]
    options = [("1", f"Pin a stored master list ({len(masters)} stored)")] if masters else []
    options += [(str(len(options) + 1), f"Build a new master list from {job.bindings['source']} now"),
                (str(len(options) + 2), "Build a new master list from an existing list"), ("B", "No list for now")]
    choice = center.io.choose(f"Reference list for {job.job_id}", tuple(options),
                              context=("A Job checks its WIP against the concepts of a master reference list.",
                                       "The master is cloned into this Job's own WIP list: changes made for this WIP",
                                       "stay there until you merge them into the master."))
    label = dict(options).get(choice, "")
    manifest = None
    if label.startswith("Pin a stored master list"):
        manifest = _choose_list(center, f"Pin which master list to {job.job_id}?", job, kind="master")
    elif label.startswith("Build a new master list from an existing"):
        manifest = _build_from_list(center, job)
    elif label.startswith("Build a new master list from"):
        config = _config(center, job)
        project = config.project(job.bindings["source"])
        title = center.io.text(f"Title for the list (blank: {project.project_id} reference list)",
                               required=False).strip() or f"{project.project_id} reference list"
        manifest = _run_build(center, config, project, title, _biblical_terms_path(center, project), None)
    if manifest:
        _clone_for_job(center, job, manifest["rl_id"], manifest["version"])


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


def _offer_missing_wordings(center, job, report) -> None:
    """SOURCE wordings of an import that are not on the terms list go to the pinned reference list, not the Job."""
    missing = report.missing_wordings
    if not missing:
        return
    shown = ", ".join(w for _, w in missing[:10]) + (" ..." if len(missing) > 10 else "")
    center.io.write(f"{len(missing)} SOURCE wording(s) are not on this Job's terms list: {shown}.")
    if not job.defaults.get("reference_list"):
        center.io.write("Pin a master list to this JOB (Reference list) to add them to this JOB's WIP list.")
        return
    if not center.io.confirm("Add them to this JOB's WIP list (a new version; merge them into the master later if "
                             "other WIPs need them)?", default=True):
        return
    manifest = _job_list(center, job)
    if manifest is not None:
        if _add_wordings(center, manifest, list(missing), "import", job) is not None:
            center.io.write("Build the SOURCE terms list again, then import the same file again to propose their "
                            "renderings.")


def glossary_menu(center, job) -> None:
    """The WIP's TARGET renderings: fill-in sheet, Paratext and bundle proposals, review, findings decisions."""
    while True:
        job = center.store.load_job(job.job_id, tool="pcc")
        latest = _latest_terms(center, job)
        rules = glossary.current_rules(job.root)
        approved = sum(1 for r in rules.values() if r["state"] == "APPROVED")
        proposed = len(glossary.proposed_rules(job.root))
        context = [f"Terms list                   {latest[0].run_id if latest else 'none yet: build the SOURCE terms list first'}",
                   f"Renderings                   {approved} approved, {proposed} waiting for a decision"]
        options = [("1", "Export the terms list to fill in renderings (Markdown and XLSX)"),
                   ("2", "Import the filled terms list"),
                   ("3", "Import Paratext TermRenderings (read-only proposals)"),
                   ("4", "Review proposed renderings"),
                   ("5", "Export a glossary bundle (renderings, for another WIP of this language)"),
                   ("6", "Import a glossary bundle from another WIP"),
                   ("7", "Import my own renderings list (wording, rendering(s)[, note])"),
                   ("8", "Import decisions on check findings (PCC-FINDINGS.xlsx)"),
                   ("9", "Review stale rules"), ("10", "Revoke an approved rendering"), ("B", "Back")]
        choice = center.io.choose(f"PCC glossary {job.job_id}", options, context=tuple(context))
        if choice == "B":
            return
        try:
            _glossary_action(center, job, choice, latest)
        except SageError as exc:
            center.show_error(exc)
        center.io.pause()


def _glossary_action(center, job, choice: str, latest) -> None:
    """Run one glossary action."""
    if choice in ("8", "9", "10"):
        _rules_and_decisions(center, job, {"8": "D", "9": "S", "10": "R"}[choice])
        return
    if latest is None:
        center.io.write("Build the SOURCE terms list first (a terms Run).")
        return
    run, snapshot, rows, left_out = latest
    sha, language = snapshot["source"]["content_sha256"], snapshot["target_language"]
    if choice == "1":
        folder = center.store.storage.reports_root / job.job_id
        digest = glossary.write_terms_list(
            rows, job_id=job.job_id, run_id=run.run_id, target_language=language,
            markdown=folder / "TERMS-LIST.md", xlsx=folder / "TERMS-LIST.xlsx", summary=left_out)
        center.io.write(f"Terms list {digest[:16]} written to {folder} ({len(rows)} rows).")
    elif choice == "2":
        path = _ask_path(center, "Path of the filled TERMS-LIST.xlsx (blank to cancel)")
        if path:
            report = glossary.import_filled_list(job, path, rows, lock_path=_lock(job), source_corpus_sha256=sha,
                                                 target_language=language)
            for line in report.as_lines():
                center.io.write(line)
    elif choice == "3":
        path = _ask_path(center, "Path of Paratext TermRenderings.xml (blank to cancel)")
        if path:
            report = glossary.propose_from_paratext(job, path, rows, lock_path=_lock(job), source_corpus_sha256=sha,
                                                    target_language=language)
            center.io.write(f"Proposed {report.imported} rendering(s); {report.unchanged} already known.")
            for line in report.problems[:20]:
                center.io.write(f"- {line}")
    elif choice == "4":
        _review_proposals(center, job, sha)
    elif choice == "5":
        target = center.store.storage.exports_root / "pcc" / f"{job.job_id}-glossary-bundle.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        counts = transfer.export_bundle(job, rows, source_project=job.bindings["source"], source_sha256=sha,
                                        target_language=language, path=target)
        center.io.write(f"Bundle written to {target}: {counts['rules']} approved renderings for {counts['entries']} "
                        "wordings.")
    elif choice in ("6", "7"):
        path = _ask_path(center, "Path of the glossary bundle .json (blank to cancel)" if choice == "6" else
                         "Path of your list: wording[, rendering(s)[, note]] (blank to cancel)")
        if path:
            importer = transfer.import_bundle if choice == "6" else transfer.import_operator_list
            report = importer(job, path, rows, lock_path=_lock(job), source_corpus_sha256=sha, target_language=language)
            center.io.write(f"Proposed {report.imported} rendering(s); {report.unchanged} already known. Review them "
                            "under option 4.")
            for line in report.problems[:20]:
                center.io.write(f"- {line}")
            _offer_missing_wordings(center, job, report)


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
                                       ("2", "Revoke"), ("3", "Skip"), ("B", "Stop")))
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
    text = center.io.text("Number of the rendering to revoke (blank to cancel)", required=False).strip()
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
                                      (("1", "Approve"), ("2", "Decline"), ("3", "Skip"), ("B", "Stop")))
            if answer == "B":
                break
            if answer in {"1", "2"}:
                glossary.decide_proposals(job, [rule["rule_id"]], approve=answer == "1",
                                          lock_path=_lock(job), source_corpus_sha256=source_sha)


def open_job(center, job) -> None:
    """Operate one PCC Job (a WIP list): terms Run, check Run, glossary, reference list, management."""
    while True:
        job = center.store.load_job(job.job_id, tool="pcc")
        run = center.store.active_run(job)
        context = _binding_lines(job)
        if run is not None:
            context += ["", f"Active Run                   {run.run_id} ({run.operation}, {run.scope}, {run.status})"]
            options = [("1", f"Continue PCC Run {run.run_id}")]
        else:
            options = [("1", OPERATION_LABELS["terms"] + " (from the pinned reference list)"),
                       ("2", OPERATION_LABELS["check"])]
        n = len(options)
        options += [(str(n + 1), "Glossary (TARGET renderings and decisions)"),
                    (str(n + 2), "Reference list (this JOB's WIP list, pin, merge into the master)"),
                    (str(n + 3), "Manage PCC JOB"), ("B", "Back")]
        choice = center.io.choose(f"PCC {job.job_id}", options, context=tuple(context))
        if choice == "B":
            return
        label = dict(options)[choice]
        if label == "Manage PCC JOB":
            if _manage(center, job):
                return
        elif label.startswith("Glossary"):
            glossary_menu(center, job)
        elif label.startswith("Reference list"):
            reference_lists_menu(center, job)
        elif run is not None:
            center.continue_run(job, run)
        else:
            _start(center, job, "terms" if choice == "1" else "check")


def _manage(center, job) -> bool:
    """Delete or inspect one Job, attach a WIP once; True once deleted."""
    options = [("1", "Delete PCC JOB"), ("2", "Recovery and diagnostics")]
    if not job.bindings.get("wip"):
        options.append(("3", "Attach a WIP (once)"))
    options.append(("B", "Back"))
    choice = center.io.choose(f"Manage PCC {job.job_id}", tuple(options), context=tuple(_binding_lines(job)))
    if choice == "1":
        return bool(center._delete_job(job))
    try:
        if choice == "2":
            center.recovery_menu(job)
        elif choice == "3":
            wip = center.choose_or_add_resource("PCC <WIP PROJECT>", "WIP")
            if wip is not None and center.io.confirm(
                    f"Attach {wip.project_id} to {job.job_id}? This cannot be changed later.", default=False):
                center.store.attach_pcc_wip(job, wip.project_id)
                center.io.write(f"WIP {wip.project_id} attached; the Job ID stays {job.job_id}.")
                center.io.pause()
    except SageError as exc:
        center.show_error(exc)
    return False


def pcc_home(center) -> None:
    """Main Menu #6: reference lists (function 1) and PCC Jobs (function 2)."""
    while True:
        active_id = center.store.active_jobs().get("pcc")
        lists = _rl_store(center).lists()
        context = (f"Reference lists              {len(lists)} stored",
                   f"Active PCC JOB               {active_id or 'NONE'}")
        choice = center.io.choose(
            TITLE,
            (("1", "Reference lists (SOURCE lists from reference texts)"), ("2", "Open active PCC JOB"),
             ("3", "Set active PCC JOB"), ("4", "Add new PCC JOB (a WIP and its reference list)"), ("B", "Back")),
            context=context,
        )
        if choice == "B":
            return
        if choice == "1":
            reference_lists_menu(center)
            continue
        if choice == "4":
            job = center.create_job_wizard("pcc")
        elif choice == "3" or not active_id:
            if not _pcc_jobs(center):
                center.io.write("No PCC Job yet: add one (Add new PCC JOB).")
                continue
            job = center.choose_job("pcc")
        else:
            job = center.store.load_job(active_id, tool="pcc")
        if job is not None:
            open_job(center, job)
