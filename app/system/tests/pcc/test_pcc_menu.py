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
