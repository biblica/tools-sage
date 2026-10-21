"""Chapters with compile defects are left out and reported NOT_ASSESSED; the rest of the scope still runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

from sage.act_tasks import aggregate_act_plan, create_act_task
from sage.effective_scope import SCOPE_CHAPTER_COMPILE_DEFECT, decide_effective_scope
from sage.jobs import JobStore
from sage.plan_continuation import continue_analysis_plan, continue_saw_plan
from sage.references import parse_analysis_scope
from sage.registry import load_ecosystem
from sage.scripture import compile_project_scope, issue_chapters
from sage.storage import storage_layout

from .conftest import submit_with_receipt
from .test_storage_rtc_boundaries import _initialize, _meaning_document

IMPORT_TIME = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
SCOPE = "1CH 5-6; 24"
CHAPTERS = (5, 6, 24)
VERSES = 2
REVIEWED = [f"1CH {chapter}:{verse}" for chapter in (5, 24) for verse in range(1, VERSES + 1)]


def _book(defect: str) -> str:
    """Return the 1 Chronicles SFM text with an unclosed ``\\wj`` in a 1CH 6 verse or heading, in the header, or nowhere."""
    header = "\\h 1 Chronicles \\wj open" if defect == "header" else "\\h 1 Chronicles"
    lines = ["\\id 1CH Fixture", header]
    for chapter in CHAPTERS:
        lines += [f"\\c {chapter}"]
        if defect == "heading" and chapter == 6:
            lines.append("\\s Heading \\wj open")
        lines.append("\\p")
        for verse in range(1, VERSES + 1):
            text = f"Chapter {chapter} verse {verse}."
            if defect == "chapter" and chapter == 6 and verse == 1:
                text = f"Chapter {chapter} \\wj verse {verse}."
            lines.append(f"\\v {verse} {text}")
    return "\n".join(lines) + "\n"


def _plant(root: Path, defect: str = "chapter") -> None:
    """Write the defect into the live WIP, as a translator's later edit would."""
    (storage_layout(root).projects_root / "usWIP" / "13CH.SFM").write_text(_book(defect), encoding="utf-8")


def _workspace(package_root: Path, make_workspace, *, defect: str = "chapter") -> Path:
    """Return an initialized workspace whose Projects hold 1CH 5, 6, and 24, the WIP with ``defect``."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    for project in storage_layout(root).projects_root.iterdir():
        if project.is_dir():
            (project / "13CH.SFM").write_text(_book("none"), encoding="utf-8")
    vrs = " ".join(f"{chapter}:{VERSES}" for chapter in CHAPTERS)
    for name in ("eng.vrs", "org.vrs"):
        path = root / "system" / "resources" / "scripture" / name
        path.write_text(f"1CH {vrs}\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    settings_path = root / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    for project in settings["projects"].values():
        project["scope"]["expected_books"] = ["1CH", *project["scope"]["expected_books"]]
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)
    if defect != "none":
        _plant(root, defect)
    return root


def _plan(package_root: Path, runtime_settings: Path, tool: str, operation: str, scope: str, output: Path):
    """Run the public plan command the menu uses for its preview."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable, "-m", "sage.cli", "--settings", str(runtime_settings), "--json",
            "workflow", "plan", "--workflow", tool, "--operation", operation, "--scope", scope,
            "--output", str(output),
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=60,
    )


def _manifest(path: str | Path) -> dict:
    """Read one JSON plan, manifest, or aggregate."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _findings(manifest_path: Path, document: dict) -> None:
    """Write one model output for a sealed task."""
    (manifest_path.parent / "output" / "findings.json").write_text(json.dumps(document), encoding="utf-8")


def test_parser_error_is_filed_under_its_chapter(package_root: Path, make_workspace) -> None:
    """An unclosed marker in 1CH 6 blocks 1CH 6 only; other chapters of the book compile READY."""
    root = _workspace(package_root, make_workspace)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")

    blocked = compile_project_scope(config, project, parse_analysis_scope("1CH 6"))
    assert blocked["status"] == "BLOCKED"
    assert {issue["reference"] for issue in blocked["issues"]} == {"1CH 6"}
    assert issue_chapters(blocked["issues"][0], "1CH") == frozenset({6})
    assert compile_project_scope(config, project, parse_analysis_scope("1CH 5"))["status"] != "BLOCKED"
    assert compile_project_scope(config, project, parse_analysis_scope("1CH 24"))["status"] != "BLOCKED"


def test_parser_error_outside_any_verse_is_filed_under_its_chapter(package_root: Path, make_workspace) -> None:
    """A heading-level error carries no verse coordinate; compile files it under the chapter that reproduces it."""
    root = _workspace(package_root, make_workspace, defect="heading")
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")

    blocked = compile_project_scope(config, project, parse_analysis_scope("1CH 6"))
    assert [issue["reference"] for issue in blocked["issues"]] == ["1CH 6"]
    assert compile_project_scope(config, project, parse_analysis_scope("1CH 5"))["status"] != "BLOCKED"


def test_header_parser_error_still_blocks_the_whole_book(package_root: Path, make_workspace) -> None:
    """A defect in the book header cannot be tied to a chapter, so the scope stays refused."""
    root = _workspace(package_root, make_workspace, defect="header")
    config = load_ecosystem(root / "ecosystem.yml")

    decision = decide_effective_scope(config, [("WIP", config.project("usWIP"))], parse_analysis_scope(SCOPE))
    assert decision.blocked
    assert decision.unlocalized and decision.unlocalized[0]["reference"] == "1CH"


def test_decision_leaves_out_the_defective_chapter(package_root: Path, make_workspace) -> None:
    """The requested scope loses only 1CH 6; whole-book and cross-chapter scopes are split at chapter ends."""
    root = _workspace(package_root, make_workspace)
    config = load_ecosystem(root / "ecosystem.yml")
    projects = [("WIP", config.project("usWIP")), ("REFERENCE", config.project("usNIVv2"))]

    decision = decide_effective_scope(config, projects, parse_analysis_scope(SCOPE))
    assert decision.narrowed
    assert decision.effective.label() == "1CH 5; 1CH 24"
    assert [row["scope"] for row in decision.excluded] == ["1CH 6"]
    assert decision.excluded[0]["code"] == SCOPE_CHAPTER_COMPILE_DEFECT
    assert decision.excluded[0]["issues"][0]["project_id"] == "usWIP"

    assert decide_effective_scope(config, projects, parse_analysis_scope("1CH")).effective.label() == "1CH 1-5; 1CH 7-24"
    crossing = decide_effective_scope(config, projects, parse_analysis_scope("1CH 5:2-24:1"))
    assert crossing.effective.label() == "1CH 5:2; 1CH 7:1-24:1"
    assert decide_effective_scope(config, projects, parse_analysis_scope("1CH 6")).blocked
    clean = decide_effective_scope(config, projects, parse_analysis_scope("1CH 5"))
    assert not clean.narrowed and not clean.blocked and clean.effective.label() == "1CH 5"


def test_rtc_run_reviews_the_rest_and_reports_the_left_out_chapter(package_root: Path, make_workspace) -> None:
    """An RTC Run planned over a scope with a defective chapter runs the rest and reports that chapter."""
    root = _workspace(package_root, make_workspace, defect="none")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP_20260901",
        display_name="RTC effective scope",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=IMPORT_TIME,
    )
    _plant(root)
    runtime_settings = store.ensure_runtime_files(job)
    planned = _plan(package_root, runtime_settings, job.tool, "rtc", SCOPE, Path("plans/PREVIEW.manifest.json"))
    assert planned.returncode == 0, planned.stderr + planned.stdout
    preview = json.loads(planned.stdout)
    assert preview["operator_scope"] == "1CH 5; 1CH 24"
    assert preview["requested_scope"] == "1CH 5-6; 1CH 24"
    assert [row["scope"] for row in preview["excluded_portions"]] == ["1CH 6"]

    # The menu creates the Run with the effective scope and stores the preview as the approved plan.
    run = store.create_run(job, operation="rtc", scope=preview["operator_scope"])
    preview.update({
        "approval_status": "OPERATOR_APPROVED",
        "approved_job_id": job.job_id,
        "approved_run_id": run.run_id,
    })
    approved_path = run.root / "plans" / "APPROVED-WORK-UNITS.json"
    approved_path.write_text(json.dumps(preview), encoding="utf-8")
    run = store.update_run(run, approved_work_plan_path=str(approved_path))
    config = load_ecosystem(runtime_settings)

    composite = create_act_task(
        config,
        workflow="rtc",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value=run.scope,
        job_id=job.job_id,
        run_id=run.run_id,
    )
    stage_plan_path = Path(composite["stages"][0]["plan_path"])
    stage_plan = _manifest(stage_plan_path)
    assert [row["scope"] for row in stage_plan["not_assessed_portions"]] == ["1CH 6"]
    for unit in stage_plan["work_units"]:
        manifest_path = Path(unit["manifest_path"])
        _findings(manifest_path, _meaning_document(_manifest(manifest_path)))
        submit_with_receipt(config, manifest_path)

    assert continue_saw_plan(config, Path(composite["plan_path"]))["status"] == "READY_TO_AGGREGATE"
    stage_aggregate = aggregate_act_plan(config, stage_plan_path)
    assert stage_aggregate["coverage"]["reviewed_references"] == REVIEWED
    assert stage_aggregate["coverage"]["not_assessed_references"] == ["1CH 6"]
    assert [row["code"] for row in stage_aggregate["exceptions"]] == [SCOPE_CHAPTER_COMPILE_DEFECT]

    result = continue_saw_plan(config, Path(composite["plan_path"]))
    assert result["status"] == "COMPLETE", result
    final = _manifest(result["aggregate_path"])
    assert final["coverage"]["reviewed_references"] == REVIEWED
    assert "1CH 6" in final["coverage"]["not_assessed_references"]
    reports = "\n".join(Path(path).read_text(encoding="utf-8") for path in result["report_paths"])
    assert "1CH 6" in reports and SCOPE_CHAPTER_COMPILE_DEFECT in reports


def test_stc_run_reviews_the_rest_and_reports_the_left_out_chapter(package_root: Path, make_workspace) -> None:
    """An STC Run with the effective scope reports the left-out chapter with its other not-assessed scope."""
    root = _workspace(package_root, make_workspace, defect="none")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC effective scope",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    _plant(root)
    runtime_settings = store.ensure_runtime_files(job)
    planned = _plan(package_root, runtime_settings, job.tool, "stc", SCOPE, Path("plans/PREVIEW.manifest.json"))
    assert planned.returncode == 0, planned.stderr + planned.stdout
    preview = json.loads(planned.stdout)
    assert preview["operator_scope"] == "1CH 5; 1CH 24"

    run = store.create_run(job, operation="stc", scope=preview["operator_scope"])
    approved_path = run.root / "plans" / "APPROVED-WORK-UNITS.json"
    approved_path.write_text(json.dumps(preview), encoding="utf-8")
    run = store.update_run(run, approved_work_plan_path=str(approved_path))
    config = load_ecosystem(runtime_settings)

    plan = create_act_task(
        config,
        workflow="stc",
        operation="stc",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value=run.scope,
        job_id=job.job_id,
        run_id=run.run_id,
    )
    assert [row["scope"] for row in plan["not_assessed_portions"]] == ["1CH 6"]
    for unit in plan["work_units"]:
        manifest_path = Path(unit["manifest_path"])
        manifest = _manifest(manifest_path)
        _findings(manifest_path, {
            "review_summary": "The assigned primary coordinates were reviewed.",
            "report_language": manifest["narrative_language"]["tag"],
            "findings": [],
        })
        assert submit_with_receipt(config, manifest_path)["status"] == "FINALIZED"

    assert continue_analysis_plan(config, Path(plan["plan_path"]))["status"] == "READY_TO_AGGREGATE"
    aggregate = aggregate_act_plan(config, Path(plan["plan_path"]))
    assert aggregate["coverage"]["reviewed_references"] == REVIEWED
    assert aggregate["coverage"]["not_assessed_references"] == ["1CH 6"]
    assert [row["code"] for row in aggregate["exceptions"]] == [SCOPE_CHAPTER_COMPILE_DEFECT]


def _rtc_with_ol_request(package_root: Path, make_workspace, *, book: str, request_ref: str, defect: tuple[int, int]):
    """Run the RTC meaning stage with one OL request, then put an unclosed marker into one OL verse."""
    if book == "MAT":
        root = make_workspace(qualification_status="VALIDATED", verse_max=3)
        _initialize(package_root, root)
        scope, ol_dir, ol_file = "MAT 1:1-3", "GRK", "41MAT.SFM"
    else:
        root = _workspace(package_root, make_workspace, defect="none")
        scope, ol_dir, ol_file = "1CH 5-6", "HEB", "13CH.SFM"
    profile_path = root / "system" / "config" / "workflows" / "saw" / "profile.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["check_policy"]["rtc"]["original_language"]["source_text_drift_adjudication"] = "ENABLED"
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    plan = create_act_task(
        config, workflow="saw", operation="rtc", output_project_id="usWIP",
        contemporary_source_id="usNIVv2", scope_value=scope,
    )
    meaning_path = Path(plan["manifest_path"])
    _findings(meaning_path, _meaning_document(_manifest(meaning_path), request_ref=request_ref))
    submit_with_receipt(config, meaning_path)
    ol_path = storage_layout(root).projects_root / ol_dir / ol_file
    lines = ol_path.read_text(encoding="utf-8").splitlines(keepends=True)
    chapter = None
    for index, line in enumerate(lines):
        if line.startswith("\\c "):
            chapter = int(line.split()[1])
        if chapter == defect[0] and line.startswith(f"\\v {defect[1]} "):
            lines[index] = line.replace(f"\\v {defect[1]} ", f"\\v {defect[1]} \\wj ", 1)
            break
    else:
        raise AssertionError(f"verse {defect} not found in {ol_file}")
    ol_path.write_text("".join(lines), encoding="utf-8")
    return config, plan


def test_ol_defect_in_the_requested_chapter_is_reported_instead_of_stopping(package_root: Path, make_workspace) -> None:
    """RTC finishes without the OL stage; the request's verse is reported not assessed with the OL defect."""
    config, plan = _rtc_with_ol_request(package_root, make_workspace, book="MAT", request_ref="MAT 1:2", defect=(1, 3))
    final = continue_saw_plan(config, Path(plan["plan_path"]))

    assert final["status"] == "COMPLETE", final
    composite = _manifest(plan["plan_path"])
    assert [stage["stage"] for stage in composite["stages"]][-1] == "REFERENCE_TEXT_COMPARISON"
    aggregate = _manifest(final["aggregate_path"])
    assert "MAT 1:2" in aggregate["coverage"]["not_assessed_references"]
    rows = [row for row in aggregate["exceptions"] if row["code"] == "SAW_OL_TEXT_UNAVAILABLE"]
    assert len(rows) == 1 and rows[0]["coordinates"] == ["MAT 1:2"]
    assert "GRK" in rows[0]["message"]


def test_ol_defect_in_another_chapter_does_not_stop_the_ol_stage(package_root: Path, make_workspace) -> None:
    """An OL defect in 1CH 6 no longer blocks the OL stage for a request in 1CH 5."""
    config, plan = _rtc_with_ol_request(package_root, make_workspace, book="1CH", request_ref="1CH 5:1", defect=(6, 1))
    next_stage = continue_saw_plan(config, Path(plan["plan_path"]))

    ol = _manifest(next_stage["next_unit"]["manifest_path"])
    assert ol["rtc_stage"] == "SELECTIVE_OL_ADJUDICATION"
    assert ol["expected_references"] == ["1CH 5:1"]
