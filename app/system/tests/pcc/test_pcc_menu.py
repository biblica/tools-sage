"""PCC phase P1b: Main Menu entry and the PCC Job menu drive a sealed Run."""

from __future__ import annotations

import io

from sage.jobs import pcc_default_settings
from sage.menu import MenuIO, SageControlCenter, ScriptedInput


def _center(root, answers, output):
    """Build a control center with scripted operator input."""
    return SageControlCenter(
        sage_root=root, settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(answers), output=output), skip_setup=True, dry_run_provider=True,
    )


def test_main_menu_lists_pcc_before_maintenance(make_workspace) -> None:
    """Main Menu #6 is PCC and Maintenance moves to #7."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = _center(root, ["7"], output)
    assert center.main_menu() == "7"
    rendered = output.getvalue()
    assert "6. Phrase Consistency Checker (PCC)" in rendered and "7. SAGE Maintenance" in rendered
    assert "PCC active Job: NONE" in rendered


def test_job_menu_builds_terms_run_to_completion(make_workspace) -> None:
    """Choosing 'Build SOURCE terms list' creates, seals and executes a Run, then returns."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = _center(root, ["1", "", "a"], output)
    center._select_scripture_scope = lambda job, primary_binding: "MAT 1"
    job = center.store.create_job(
        tool="pcc", job_id="", display_name="PCC usNIVv2", bindings={"source": "usNIVv2"},
        defaults=pcc_default_settings("sw"),
    )
    from sage.pcc_menu import open_job
    open_job(center, job)
    rendered = output.getvalue()
    assert "Build SOURCE terms list" in rendered and "Check WIP against the glossary" in rendered
    assert "COMPLETE_WITH_EXCEPTIONS" in rendered
    assert center.store.active_run(center.store.load_job(job.job_id, tool="pcc")) is None


def test_check_without_wip_is_explained_not_crashed(make_workspace) -> None:
    """A Job with no WIP cannot be checked; the menu reports it and carries on."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = _center(root, ["2", "", "a"], output)
    job = center.store.create_job(
        tool="pcc", job_id="", display_name="PCC usNIVv2", bindings={"source": "usNIVv2"},
        defaults=pcc_default_settings("sw"),
    )
    from sage.pcc_menu import open_job
    open_job(center, job)
    assert "needs a WIP" in output.getvalue()


def _save_list(center, project_id="usNIVv2"):
    """Store one fabricated list version."""
    from sage.pcc.reflist import ReferenceListStore
    store = ReferenceListStore(center.store.storage.resources_root)
    store.save(rl_id="syn-list-0123abcd", title="Syn list",
               reference={"project_id": project_id, "edition": project_id, "language_tag": "en",
                          "content_sha256": "c" * 64, "versification_id": "eng"},
               license={"license_id": "SYNTHETIC", "local_only": True, "note": ""}, build={"mode": "SCRATCH"},
               entries=[], created_utc="2026-11-25T00:00:00Z")
    return store


def test_job_reference_list_pins_a_stored_list_and_manage_offers_wip_attach(make_workspace) -> None:
    """Job -> Reference list -> Pin clones the master into the Job's WIP list and pins it; WIP attach offered once."""
    from sage.pcc_menu import open_job

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = _center(root, ["4", "11", "1", "a", "5", "a", "a"], output)
    job = center.store.create_job(
        tool="pcc", job_id="", display_name="PCC usNIVv2", bindings={"source": "usNIVv2"},
        defaults=pcc_default_settings("sw"),
    )
    _save_list(center)
    open_job(center, job)
    rendered = output.getvalue()
    assert "Attach a WIP (once)" in rendered and "Syn list: syn-list-0123abcd v1" in rendered and "this SOURCE" in rendered
    pin = center.store.load_job(job.job_id, tool="pcc").defaults["reference_list"]
    assert pin["rl_id"] != "syn-list-0123abcd" and pin["version"] == 1, "the Job pins its own clone, not the master"
    assert f"Reference list: none -> {pin['rl_id']} v1" in rendered and "now has its own WIP list" in rendered


def test_glossary_menu_offers_findings_decisions_stale_review_and_revoke(make_workspace) -> None:
    """P7 actions are reachable and explain themselves when there is nothing to act on."""
    from sage.pcc_menu import glossary_menu

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = _center(root, ["10", "8", "a"], output)
    job = center.store.create_job(
        tool="pcc", job_id="", display_name="PCC usNIVv2", bindings={"source": "usNIVv2"},
        defaults=pcc_default_settings("sw"),
    )
    glossary_menu(center, job)
    rendered = output.getvalue()
    assert "Import decisions on check findings" in rendered and "Review stale rules" in rendered
    assert "Import Paratext Biblical Terms" not in rendered, "key terms belong to the reference list"
    assert "No approved renderings yet." in rendered and "Run a consistency check first" in rendered


def test_reference_lists_live_outside_jobs_and_export_with_numeric_keys(make_workspace) -> None:
    """PCC home -> Reference lists shows lists with the Jobs that pin them, and exports a workbook, with no Job."""
    from sage.pcc.pin import pin_for
    from sage.pcc_menu import pcc_home

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = _center(root, ["1", "1", "4", "1", "a", "a"], output)
    store = _save_list(center)
    job = center.store.create_job(tool="pcc", job_id="", display_name="PCC usNIVv2", bindings={"source": "usNIVv2"},
                                  defaults=pcc_default_settings("sw") | {"reference_list": pin_for(store, "syn-list-0123abcd")})
    pcc_home(center)
    rendered = output.getvalue()
    assert "1. Reference lists" in rendered and "10. Merge WIP-list changes into the master" in rendered
    assert "Pin a list to this JOB" not in rendered
    assert f"Pinned directly by: {job.job_id} (v1)" in rendered
    assert (center.store.storage.exports_root / "pcc" / "RL-syn-list-0123abcd-v1.xlsx").is_file()


def test_job_with_old_phrases_offers_the_move_into_its_list(make_workspace) -> None:
    """An older Job on a master: its phrases.txt moves into a new clone (the master stays as it was)."""
    from sage.pcc.pin import pin_for
    from sage.pcc_menu import reference_lists_menu

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = _center(root, ["12", "y", "y", "a"], output)
    store = _save_list(center, project_id="NOT-HERE")
    job = center.store.create_job(tool="pcc", job_id="", display_name="PCC usNIVv2", bindings={"source": "usNIVv2"},
                                  defaults=pcc_default_settings("sw") | {"reference_list": pin_for(store, "syn-list-0123abcd")})
    (job.root / "input").mkdir(parents=True, exist_ok=True)
    (job.root / "input" / "phrases.txt").write_text("bread of life\n", encoding="utf-8")
    reference_lists_menu(center, job)
    rendered = output.getvalue()
    assert "Move this JOB's own wordings into its list (1 in phrases.txt)" in rendered
    assert "phrases.moved-" in rendered and store.versions("syn-list-0123abcd") == [1], "the master is not changed"
    pin = center.store.load_job(job.job_id, tool="pcc").defaults["reference_list"]
    assert pin["rl_id"] != "syn-list-0123abcd" and pin["version"] == 2
    clone = store.load(pin["rl_id"], 2)[0]
    assert [c["label"] for c in clone["build"]["local"]] == ["bread of life"]


def test_merge_menu_merges_chosen_changes_then_updates_and_repins_the_job(make_workspace, tmp_path) -> None:
    """Job -> Reference list -> Merge -> Choose changes: master gets a new version, the Job's WIP list follows."""
    from sage.pcc import layers
    from sage.pcc.pin import pin_for
    from sage.pcc.reflist import ReferenceListStore
    from sage.pcc.reflist_xlsx import export_workbook, import_workbook
    from sage.pcc_menu import reference_lists_menu
    from .test_pcc_reflist_xlsx import _edit, _entry

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = _center(root, ["10", "2", "1", "y", "y", "a"], output)
    store = ReferenceListStore(center.store.storage.resources_root)
    store.save(rl_id="syn-list-0123abcd", title="Syn list",
               reference={"project_id": "usNIVv2", "edition": "usNIVv2", "language_tag": "en",
                          "content_sha256": "c" * 64, "versification_id": "eng"},
               license={"license_id": "SYNTHETIC", "local_only": True, "note": ""}, build={"mode": "SCRATCH"},
               entries=[_entry(["GRK:50"], "lamp"), _entry(["GRK:70"], "wall")], created_utc="2026-11-25T00:00:00Z")
    clone = layers.create_clone(store, "syn-list-0123abcd", None, title="Syn list - WIP", instance_id="t")
    path = export_workbook(store, clone["rl_id"], 1, tmp_path)
    _edit(path, {"wall": {"Status": "DROP"}})
    import_workbook(store, path, report_folder=tmp_path)
    job = center.store.create_job(tool="pcc", job_id="", display_name="PCC usNIVv2", bindings={"source": "usNIVv2"},
                                  defaults=pcc_default_settings("sw") | {"reference_list": pin_for(store, clone["rl_id"])})
    reference_lists_menu(center, job)
    rendered = output.getvalue()
    assert "1. Merge all changes into the master" in rendered and "left out: wall" in rendered
    assert "Master syn-list-0123abcd v2 written." in rendered
    master_wall = next(e for e in store.load("syn-list-0123abcd", 2)[1] if e["label"] == "wall")
    assert master_wall["status"] == "DROPPED"
    pin = center.store.load_job(job.job_id, tool="pcc").defaults["reference_list"]
    updated = store.load(clone["rl_id"], pin["version"])[0]
    assert pin["rl_id"] == clone["rl_id"] and updated["build"]["parent"]["version"] == 2 and updated["build"]["local"] == []
