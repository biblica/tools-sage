"""Multi-portion RTC and STC Runs (`1CH 5-6; 24`) end to end: plan, tasks, submission, and completion."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import yaml

from sage.act_tasks import aggregate_act_plan, create_act_task
from sage.jobs import JobStore
from sage.plan_continuation import continue_analysis_plan, continue_saw_plan
from sage.registry import load_ecosystem
from sage.storage import storage_layout

from .conftest import submit_with_receipt
from .test_rtc_stc_regressions import approve_planned_rtc_run
from .test_storage_rtc_boundaries import _initialize, _meaning_document

IMPORT_TIME = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
SCOPE = "1CH 5-6; 24"
CHAPTERS = (5, 6, 24)
VERSES = 2
EXPECTED = [f"1CH {chapter}:{verse}" for chapter in CHAPTERS for verse in range(1, VERSES + 1)]


def _chronicles_workspace(package_root: Path, make_workspace, *, wip_lacks: tuple[int, ...] = ()) -> Path:
    """Return an initialized workspace whose Projects also hold 1 Chronicles 5, 6, and 24.

    ``wip_lacks`` lists chapters the WIP Project leaves out while the versification still declares them.
    """
    root = make_workspace(configured=True, qualification_status="VALIDATED")

    def book(skip: tuple[int, ...]) -> str:
        """Return the 1 Chronicles SFM text with the ``skip`` chapters left out."""
        lines = ["\\id 1CH Fixture"]
        for chapter in (value for value in CHAPTERS if value not in skip):
            lines += [f"\\c {chapter}", "\\p"]
            lines += [f"\\v {verse} Chapter {chapter} verse {verse}." for verse in range(1, VERSES + 1)]
        return "\n".join(lines) + "\n"

    for project in storage_layout(root).projects_root.iterdir():
        if project.is_dir():
            (project / "13CH.SFM").write_text(book(wip_lacks if project.name == "usWIP" else ()), encoding="utf-8")
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
    return root


def _manifest(path: str | Path) -> dict:
    """Read one JSON plan, manifest, or aggregate."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_multi_portion_stc_run_reviews_exactly_the_selected_chapters(package_root: Path, make_workspace) -> None:
    """An STC Run over `1CH 5-6; 24` partitions, submits, and completes over only those six verses."""
    root = _chronicles_workspace(package_root, make_workspace)
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC multi-portion",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    run = store.create_run(job, operation="stc", scope=SCOPE)
    assert run.scope == "1CH 5-6; 1CH 24"
    config = load_ecosystem(store.ensure_runtime_files(job))

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

    assert plan["status"] == "PARTITIONED"
    manifests = [_manifest(unit["manifest_path"]) for unit in plan["work_units"]]
    assert [ref for manifest in manifests for ref in manifest["expected_references"]] == EXPECTED
    assert all(manifest["resource_bindings"].get("ORIGINAL_LANGUAGE_HEBREW") == "HEB" for manifest in manifests)
    assert not any("ORIGINAL_LANGUAGE_GREEK" in manifest["resource_bindings"] for manifest in manifests)

    for unit, manifest in zip(plan["work_units"], manifests, strict=True):
        manifest_path = Path(unit["manifest_path"])
        (manifest_path.parent / "output" / "findings.json").write_text(
            json.dumps({
                "review_summary": "The assigned primary coordinates were reviewed.",
                "report_language": manifest["narrative_language"]["tag"],
                "findings": [],
            }),
            encoding="utf-8",
        )
        assert submit_with_receipt(config, manifest_path)["status"] == "FINALIZED"

    assert continue_analysis_plan(config, Path(plan["plan_path"]))["status"] == "READY_TO_AGGREGATE"
    aggregate = aggregate_act_plan(config, Path(plan["plan_path"]))

    assert aggregate["status"] == "FINALIZED"
    assert aggregate["requested_scope"] == "1CH 5-6; 1CH 24"
    assert aggregate["primary_ol_authority"] == "HEB"
    assert aggregate["coverage"] == {"status": "COMPLETE", "reviewed_references": EXPECTED}
    assert sorted({Path(path).parent.name for path in aggregate["report_paths"]}) == ["005", "006", "024"]


def test_stc_portion_the_wip_lacks_is_not_assessed_and_the_rest_is_reviewed(package_root: Path, make_workspace) -> None:
    """A selected chapter the WIP has no text for is reported NOT_ASSESSED; the other portions still run."""
    root = _chronicles_workspace(package_root, make_workspace, wip_lacks=(24,))
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="stc",
        job_id="STC-usWIP_20260901",
        display_name="STC missing portion",
        bindings={"wip": "usWIP"},
        imported_at=IMPORT_TIME,
    )
    run = store.create_run(job, operation="stc", scope=SCOPE)
    config = load_ecosystem(store.ensure_runtime_files(job))

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

    assert [portion["scope"] for portion in plan["not_assessed_portions"]] == ["1CH 24"]
    manifests = [_manifest(unit["manifest_path"]) for unit in plan["work_units"]]
    reviewed = [ref for manifest in manifests for ref in manifest["expected_references"]]
    assert reviewed == [ref for ref in EXPECTED if not ref.startswith("1CH 24:")]
    for unit, manifest in zip(plan["work_units"], manifests, strict=True):
        manifest_path = Path(unit["manifest_path"])
        (manifest_path.parent / "output" / "findings.json").write_text(
            json.dumps({
                "review_summary": "The assigned primary coordinates were reviewed.",
                "report_language": manifest["narrative_language"]["tag"],
                "findings": [],
            }),
            encoding="utf-8",
        )
        assert submit_with_receipt(config, manifest_path)["status"] == "FINALIZED"

    aggregate = aggregate_act_plan(config, Path(plan["plan_path"]))

    assert aggregate["coverage"]["status"] != "COMPLETE"
    assert aggregate["coverage"]["not_assessed_references"] == ["1CH 24"]
    assert [row["code"] for row in aggregate["exceptions"]] == ["STC_WIP_PORTION_MISSING"]


def test_multi_portion_rtc_run_reviews_exactly_the_selected_chapters(package_root: Path, make_workspace) -> None:
    """An RTC Run over `1CH 5-6; 24` plans, creates meaning tasks, and completes over only those six verses."""
    root = _chronicles_workspace(package_root, make_workspace)
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="rtc",
        job_id="RTC-usWIP-usNIVv2_20260901",
        display_name="RTC multi-portion",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        imported_at=IMPORT_TIME,
    )
    run = store.create_run(job, operation="rtc", scope=SCOPE)
    approve_planned_rtc_run(package_root, store, job, run)
    config = load_ecosystem(store.ensure_runtime_files(job))

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

    assert composite["status"] == "COMPOSITE"
    assert composite["current_stage"] == "REFERENCE_TEXT_COMPARISON"
    stage_plan_path = Path(composite["stages"][0]["plan_path"])
    stage_plan = _manifest(stage_plan_path)
    units = stage_plan["work_units"]
    manifests = [_manifest(unit["manifest_path"]) for unit in units]
    assert [ref for manifest in manifests for ref in manifest["expected_references"]] == EXPECTED
    assert [manifest["review_portion_index"] for manifest in manifests] == list(range(1, len(units) + 1))

    for unit, manifest in zip(units, manifests, strict=True):
        manifest_path = Path(unit["manifest_path"])
        (manifest_path.parent / "output" / "findings.json").write_text(
            json.dumps(_meaning_document(manifest)), encoding="utf-8"
        )
        submit_with_receipt(config, manifest_path)

    assert continue_saw_plan(config, Path(composite["plan_path"]))["status"] == "READY_TO_AGGREGATE"
    stage_aggregate = aggregate_act_plan(config, stage_plan_path)
    assert stage_aggregate["coverage"]["reviewed_references"] == EXPECTED
    assert [unit["review_portion_scope"] for unit in stage_aggregate["work_units"]] == ["1CH 5:1-6:2", "1CH 24:1-2"]
    result = continue_saw_plan(config, Path(composite["plan_path"]))

    assert result["status"] == "COMPLETE", result
    assert result["consolidation_status"] == "CHAPTER_SCOPED"
    assert sorted({Path(path).parent.name for path in result["report_paths"]}) == ["005", "006", "024"]
    assert _manifest(result["aggregate_path"])["coverage"]["reviewed_references"] == EXPECTED
