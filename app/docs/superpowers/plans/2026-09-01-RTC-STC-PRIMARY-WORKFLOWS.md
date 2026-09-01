# RTC and STC Primary Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Replace operator-facing SAW with independent RTC and STC Jobs, snapshot-based Run identities, explicit authority reports, non-failing structural deficiencies, resource inspection, and a governed Job-data wipe.

**Architecture:** Keep the proven SAW analytical engine as an internal runtime adapter while introducing RTC/STC as the persisted and operator-facing workflow identities. Add focused snapshot, structural-status, resource-report, and reset modules; adapt JobStore and report publishers to use those contracts without migrating legacy SAW data.

**Tech Stack:** Python 3.11+, PyYAML, pytest, JSON/YAML manifests, USFM-to-USJ compiler, and existing SAGE atomic storage/menu utilities.

**Spec:** docs/superpowers/specs/2026-09-01-RTC-STC-PRIMARY-WORKFLOWS-DESIGN.md

## Global Constraints

- Paratext remains authoritative; SAGE analyzes a static imported USJ snapshot.
- RTC binds distinct WIP Project plus REFERENCE Project.
- STC binds only WIP Project and uses GRK or HEB.
- Main Menu exposes BIC, RTC, and STC, never SAW.
- Targeted Check and standalone Original-Language Review stay importable but absent from menus.
- RTC option #10 remains the only advanced original-language toggle in RTC.
- Job names are RTC-<WIP>_YYYYMMDD or STC-<WIP>_YYYYMMDD; Runs append one monotonic -NNN serial.
- Reports identify the actual Project and exact authority below Job/Book/chapter paths.
- Versification and comparison-source deficiencies complete as COMPLETE_WITH_STRUCTURE_PROBLEMS.
- Missing Project bindings remain ACTION_NEEDED and never abort surrounding discovery.
- No legacy SAW data migration is implemented.
- Wipe all Job data preserves Project/resource/environment configuration and the managed virtual environment.
- Preserve and separately commit the existing uncommitted Job-recovery changes.

---

### Task 1: Checkpoint tolerant Job discovery

**Files:**
- Modify: system/src/sage/jobs.py
- Modify: system/src/sage/menu.py
- Modify: system/src/sage/ui_services.py
- Test: system/tests/test_menu_projects.py
- Test: system/tests/test_storage_rtc_boundaries.py
- Test: system/tests/test_tui_services.py

**Interfaces:**
- Consumes: SageError, JobStore.load_job(), Project Inventory, and Paratext catalog discovery.
- Produces: JobLoadIssue, JobDiscoveryReport, JobStore.discover_report(), and PROJECT_BINDING_ROLE_CONFLICT behavior used by RTC/STC management.

- [ ] **Step 1: Verify the existing recovery tests**

    ./sage-python -m pytest \
      system/tests/test_storage_rtc_boundaries.py::test_same_project_saw_bindings_leave_no_persisted_job \
      system/tests/test_storage_rtc_boundaries.py::test_job_discovery_reports_all_missing_saw_projects_and_keeps_valid_jobs \
      system/tests/test_menu_projects.py::test_open_job_reports_missing_projects_and_offers_guided_onboarding \
      system/tests/test_tui_services.py::test_invalid_active_job_is_action_needed_without_blocking_main_ui -q

Expected: four tests pass and no top-level SAGE ERROR appears.

- [ ] **Step 2: Verify diff quality**

    git diff --check -- \
      system/src/sage/jobs.py system/src/sage/menu.py system/src/sage/ui_services.py \
      system/tests/test_menu_projects.py system/tests/test_storage_rtc_boundaries.py \
      system/tests/test_tui_services.py

Expected: exit 0.

- [ ] **Step 3: Commit the recovery foundation**

    git add system/src/sage/jobs.py system/src/sage/menu.py system/src/sage/ui_services.py \
      system/tests/test_menu_projects.py system/tests/test_storage_rtc_boundaries.py \
      system/tests/test_tui_services.py
    git commit -m "fix: report actionable Job binding problems"

### Task 2: Add workflow identity and WIP snapshots

**Files:**
- Create: system/src/sage/workflow_identity.py
- Create: system/src/sage/job_snapshots.py
- Create: system/tests/test_job_snapshots.py
- Modify: system/src/sage/jobs.py

**Interfaces:**
- Consumes: compile_project(), project_validation_fingerprint(), atomic_write_json(), and canonical Project IDs.
- Produces: OPERATOR_WORKFLOWS, SUPPORTED_JOB_TOOLS, runtime_workflow_id(), canonical_analysis_job_id(), capture_wip_snapshot(), and seal_run_snapshot().

- [ ] **Step 1: Write failing identity tests**

    from sage.workflow_identity import canonical_analysis_job_id, runtime_workflow_id

    def test_analysis_identity_uses_snapshot_date_and_internal_adapter():
        assert canonical_analysis_job_id("rtc", "ukrNPUv1", "20260901") == "RTC-ukrNPUv1_20260901"
        assert canonical_analysis_job_id("stc", "ukrNPUv1", "20260901") == "STC-ukrNPUv1_20260901"
        assert runtime_workflow_id("rtc") == "saw"
        assert runtime_workflow_id("stc") == "saw"

- [ ] **Step 2: Write failing snapshot test**

    from datetime import datetime, timezone
    import json
    from sage.job_snapshots import capture_wip_snapshot, seal_run_snapshot

    def test_capture_and_seal_wip_snapshot(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        imported_at = datetime(2026, 9, 1, 10, 30, tzinfo=timezone.utc)
        snapshot = root.parent / "snapshot-fixture"
        receipt = capture_wip_snapshot(
            root,
            settings_path=root / "ecosystem.yml",
            project_id="usWIP",
            destination=snapshot,
            imported_at=imported_at,
        )
        assert receipt["project_id"] == "usWIP"
        assert receipt["snapshot_date"] == "20260901"
        assert len(receipt["content_fingerprint"]) == 64
        assert receipt["books"]
        sealed_root = root.parent / "run-snapshot"
        sealed = seal_run_snapshot(snapshot, sealed_root, run_id="RTC-usWIP_20260901-001")
        assert sealed["content_fingerprint"] == receipt["content_fingerprint"]
        assert json.loads((sealed_root / "SNAPSHOT.json").read_text())["run_id"] == "RTC-usWIP_20260901-001"

- [ ] **Step 3: Run tests and verify RED**

    ./sage-python -m pytest system/tests/test_job_snapshots.py -q

Expected: collection fails because both new modules are absent.

- [ ] **Step 4: Implement workflow identity**

    OPERATOR_WORKFLOWS = ("bic", "rtc", "stc")
    SUPPORTED_JOB_TOOLS = ("bic", "rtc", "stc", "saw")
    ANALYSIS_WORKFLOWS = frozenset({"rtc", "stc"})

    def validate_project_code(value: str) -> str:
        code = str(value).strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", code):
            raise ValidationError(
                f"Project code is not cross-platform safe: {value}",
                code="PROJECT_ID_INVALID",
            )
        return code

    def runtime_workflow_id(tool: str) -> str:
        normalized = tool.strip().lower()
        if normalized not in SUPPORTED_JOB_TOOLS:
            raise ValidationError(f"Unsupported tool: {tool}")
        return "saw" if normalized in ANALYSIS_WORKFLOWS else normalized

    def canonical_analysis_job_id(tool: str, wip_project: str, snapshot_date: str) -> str:
        normalized = tool.strip().lower()
        if normalized not in ANALYSIS_WORKFLOWS:
            raise ValidationError(f"Analysis Job requires RTC or STC, not {tool}")
        project = validate_project_code(wip_project)
        if not re.fullmatch(r"\d{8}", snapshot_date):
            raise ValidationError("WIP snapshot date must be YYYYMMDD", code="SNAPSHOT_DATE_INVALID")
        return f"{normalized.upper()}-{project}_{snapshot_date}"

- [ ] **Step 5: Implement capture_wip_snapshot()**

Compile the enabled WIP Project to USJ, reject malformed/corrupt WIP evidence, copy each Book cache to snapshot/usj/<BOOK>.json, and atomically persist:

    receipt = {
        "schema_version": "1.0",
        "project_id": project_id,
        "imported_utc": imported_at.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "snapshot_date": imported_at.astimezone().strftime("%Y%m%d"),
        "content_fingerprint": project_validation_fingerprint(compiled),
        "resource_sha256": compiled["resource_sha256"],
        "compiled_files_sha256": compiled["compiled_files_sha256"],
        "books": list(compiled["summary"]["books"]),
        "atomic_coordinates": int(compiled["summary"]["atomic_coordinates"]),
        "source_location": str(project.path),
    }

seal_run_snapshot() copies the immutable Job snapshot into the new Run snapshot directory and writes the Run ID into its receipt.

- [ ] **Step 6: Run tests and verify GREEN**

    ./sage-python -m pytest system/tests/test_job_snapshots.py -q

Expected: all tests pass.

- [ ] **Step 7: Commit snapshot identity**

    git add system/src/sage/workflow_identity.py system/src/sage/job_snapshots.py \
      system/src/sage/jobs.py system/tests/test_job_snapshots.py
    git commit -m "feat: add analysis Job snapshot identity"

### Task 3: Implement independent RTC and STC Job storage

**Files:**
- Modify: system/src/sage/jobs.py
- Modify: system/src/sage/workflow_identity.py
- Create: system/tests/test_primary_analysis_jobs.py
- Test: system/tests/test_storage_rtc_boundaries.py

**Interfaces:**
- Consumes: Task 2 identity/snapshot functions and internal workflows.saw.
- Produces: RTC bindings {wip, reference}, STC bindings {wip}, Job.wip_snapshot, fixed-operation Runs, JobStore.refresh_job_snapshot(), and legacy SAW readability.

- [ ] **Step 1: Write failing Job contract test**

    from datetime import datetime, timezone
    import pytest
    from sage.errors import ValidationError
    from sage.jobs import JobStore

    IMPORT_TIME = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)

    def test_rtc_and_stc_use_independent_bindings(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        store = JobStore(root, root / "ecosystem.yml")
        rtc = store.create_job(
            tool="rtc", job_id="RTC-usWIP_20260901", display_name="RTC fixture",
            bindings={"wip": "usWIP", "reference": "usNIVv2"}, imported_at=IMPORT_TIME,
        )
        stc = store.create_job(
            tool="stc", job_id="STC-usWIP_20260901", display_name="STC fixture",
            bindings={"wip": "usWIP"}, imported_at=IMPORT_TIME,
        )
        assert rtc.bindings == {"wip": "usWIP", "reference": "usNIVv2"}
        assert stc.bindings == {"wip": "usWIP"}
        assert rtc.wip_snapshot["snapshot_date"] == "20260901"
        assert stc.wip_snapshot["snapshot_date"] == "20260901"

    def test_rtc_rejects_self_comparison_and_stc_rejects_reference(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        store = JobStore(root, root / "ecosystem.yml")
        with pytest.raises(ValidationError, match="different"):
            store.create_job(
                tool="rtc", job_id="RTC-usWIP_20260901", display_name="bad",
                bindings={"wip": "usWIP", "reference": "usWIP"}, imported_at=IMPORT_TIME,
            )
        with pytest.raises(ValidationError, match="unsupported bindings"):
            store.create_job(
                tool="stc", job_id="STC-usWIP_20260901", display_name="bad",
                bindings={"wip": "usWIP", "reference": "usNIVv2"}, imported_at=IMPORT_TIME,
            )

- [ ] **Step 2: Write failing Run identity test**

    def test_run_identity_uses_snapshot_job_and_serial_only(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        store = JobStore(root, root / "ecosystem.yml")
        job = store.create_job(
            tool="stc", job_id="STC-usWIP_20260901", display_name="STC fixture",
            bindings={"wip": "usWIP"}, imported_at=IMPORT_TIME,
        )
        first = store.create_run(job, operation="stc", scope="MAT 1")
        second = store.create_run(job, operation="stc", scope="MAT 2")
        assert first.run_id == "STC-usWIP_20260901-001"
        assert second.run_id == "STC-usWIP_20260901-002"
        assert (first.root / "snapshot" / "SNAPSHOT.json").is_file()
        sealed_before = (first.root / "snapshot" / "SNAPSHOT.json").read_bytes()
        current = job.root / "snapshot" / "SNAPSHOT.json"
        current.write_text(current.read_text().replace(
            job.wip_snapshot["content_fingerprint"], "f" * 64
        ))
        assert (first.root / "snapshot" / "SNAPSHOT.json").read_bytes() == sealed_before

- [ ] **Step 3: Run tests and verify RED**

    ./sage-python -m pytest system/tests/test_primary_analysis_jobs.py -q

Expected: RTC/STC are unsupported and Job lacks wip_snapshot.

- [ ] **Step 4: Extend JobStore binding rules**

    required_bindings = {
        "bic": {"content_source", "lexical_donor", "generated_target"},
        "rtc": {"wip", "reference"},
        "stc": {"wip"},
        "saw": {"wip", "reference"},
    }[job_tool]

For RTC/STC, load the profile from workflows.saw and inject usable GRK/HEB aliases only into derived runtime configuration. Do not persist those aliases as RTC/STC Job bindings.

- [ ] **Step 5: Persist Job snapshot receipt**

Add wip_snapshot: dict[str, Any] | None to Job. RTC/STC manifests require wip_snapshot copied from snapshot/SNAPSHOT.json; BIC and legacy SAW load with None.

- [ ] **Step 6: Enforce fixed operation and serial Run IDs**

    expected_operation = {"rtc": "rtc", "stc": "stc"}.get(project.tool)
    if expected_operation and operation.strip().lower() != expected_operation:
        raise ValidationError(
            f"{project.tool.upper()} Job can create only {expected_operation.upper()} Runs",
            code="JOB_OPERATION_MISMATCH",
        )
    run_id = f"{project.job_id}-{next_serial:03d}"

Create the Run root under an atomic lock, seal the Job snapshot before run.json publication, and never derive the ID from execution date.

- [ ] **Step 7: Preserve the internal adapter**

Add Job.runtime_tool returning runtime_workflow_id(self.tool). Derived runtime settings continue to expose workflows.saw, but runtime_context.tool, Job paths, Run paths, and active pointers remain rtc or stc.

- [ ] **Step 8: Implement governed snapshot refresh**

JobStore.refresh_job_snapshot(job, imported_at=None) refuses refresh while a non-closed Run exists. It captures into a staging directory, replaces the current same-day snapshot atomically, and increments configuration_revision. If the date changes, it creates the new snapshot-dated Job root and controller root, marks the old evidence container ARCHIVED, removes the superseded Job-level USJ snapshot from that old container, and atomically updates the active pointer. Sealed Run snapshots and published report roots retain their original IDs and bytes.

- [ ] **Step 9: Run storage regressions**

    ./sage-python -m pytest system/tests/test_primary_analysis_jobs.py \
      system/tests/test_storage_rtc_boundaries.py \
      system/tests/test_project_inventory_and_job_isolation.py -q

Expected: all pass and legacy SAW fixtures remain readable.

- [ ] **Step 10: Commit independent storage**

    git add system/src/sage/jobs.py system/src/sage/workflow_identity.py \
      system/tests/test_primary_analysis_jobs.py system/tests/test_storage_rtc_boundaries.py
    git commit -m "feat: split RTC and STC Job storage"

### Task 4: Replace SAW menus with fixed RTC and STC flows

**Files:**
- Modify: system/src/sage/menu.py
- Modify: system/src/sage/ui_services.py
- Modify: system/src/sage/tui.py
- Create: system/tests/test_primary_workflow_menus.py
- Test: system/tests/test_menu_projects.py
- Test: system/tests/test_tui_services.py

**Interfaces:**
- Consumes: RTC/STC JobStore and internal start_saw_run() adapter.
- Produces: BIC/RTC/STC Main Menu, analysis_menu(), analysis_job_menu(), and workflow-valid create/manage forms.

- [ ] **Step 1: Write failing Main Menu test**

    import io
    from datetime import datetime, timezone
    from sage.menu import MenuIO, SageControlCenter, ScriptedInput

    def test_main_menu_exposes_rtc_and_stc_without_saw(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        output = io.StringIO()
        center = SageControlCenter(
            sage_root=root, settings_path=root / "ecosystem.yml",
            io=MenuIO(input_func=ScriptedInput(("x",)), output=output),
            skip_setup=True, dry_run_provider=True,
        )
        assert center.main_menu() == "X"
        rendered = output.getvalue()
        assert "BIC active Job:" in rendered
        assert "RTC active Job:" in rendered
        assert "STC active Job:" in rendered
        assert "\n3. SAW\n" not in rendered

- [ ] **Step 2: Write failing STC menu test**

    def test_stc_menu_has_no_reference_or_parked_checks(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        output = io.StringIO()
        center = SageControlCenter(
            sage_root=root, settings_path=root / "ecosystem.yml",
            io=MenuIO(input_func=ScriptedInput(("b",)), output=output),
            skip_setup=True, dry_run_provider=True,
        )
        job = center.store.create_job(
            tool="stc", job_id="STC-usWIP_20260901", display_name="STC fixture",
            bindings={"wip": "usWIP"},
            imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
        )
        center.analysis_job_menu(job)
        rendered = output.getvalue()
        assert "WIP Project                  usWIP" in rendered
        assert "REFERENCE" not in rendered
        assert "Run Source Text Correspondence (STC)" in rendered
        assert "Targeted Check" not in rendered
        assert "Original-Language Review" not in rendered

- [ ] **Step 3: Run tests and verify RED**

    ./sage-python -m pytest system/tests/test_primary_workflow_menus.py -q

Expected: SAW remains visible and analysis_job_menu() is absent.

- [ ] **Step 4: Implement Main Menu routing**

    (
        ("1", "Manage SAGE Scripture Projects"),
        ("2", "BIC"),
        ("3", "Reference Text Comparison (RTC)"),
        ("4", "Source Text Correspondence (STC)"),
        ("5", "SAGE Maintenance"),
        ("X", "Exit SAGE"),
    )

Keep saw_menu() and _saw_job_menu() callable for compatibility/support only; no operator path invokes them.

- [ ] **Step 5: Implement fixed analysis menus**

analysis_menu("rtc") and analysis_menu("stc") expose Job selection, creation, Manage Job, reports, recovery, and storage. analysis_job_menu() displays the snapshot receipt and exactly one Run action:

    operation_label = {
        "rtc": "Run Reference Text Comparison (RTC)",
        "stc": "Run Source Text Correspondence (STC)",
    }[project.tool]

The adapter calls start_saw_run(project, project.tool). Controller arguments replace project.tool with project.runtime_tool only where the internal CLI expects workflow saw.

- [ ] **Step 6: Split creation and Manage Job**

RTC selects WIP then a different REFERENCE. STC selects WIP only. Manage Job supports WIP update, RTC REFERENCE update, WIP snapshot refresh, report languages, and manifest display. Validation returns to the menu.

- [ ] **Step 7: Retain only RTC option #10**

Keep _rtc_policy_menu() entry 10 and change stale “Option 11” copy to “RTC option #10”. Remove Targeted Check and standalone OL review from RTC, STC, New Task, setup, and TUI navigation.

- [ ] **Step 8: Run UI regressions**

    ./sage-python -m pytest system/tests/test_primary_workflow_menus.py \
      system/tests/test_menu_projects.py system/tests/test_tui_services.py \
      system/tests/test_parent_runtime.py -q

Expected: all pass with primary BIC/RTC/STC navigation.

- [ ] **Step 9: Commit menu split**

    git add system/src/sage/menu.py system/src/sage/ui_services.py system/src/sage/tui.py \
      system/tests/test_primary_workflow_menus.py system/tests/test_menu_projects.py \
      system/tests/test_tui_services.py system/tests/test_parent_runtime.py
    git commit -m "feat: expose RTC and STC primary flows"

### Task 5: Normalize structural deficiencies

**Files:**
- Create: system/src/sage/structural_issues.py
- Create: system/tests/test_structural_issues.py
- Modify: system/src/sage/source_coverage.py
- Modify: system/src/sage/stc.py
- Modify: system/src/sage/act_tasks.py
- Modify: system/src/sage/menu.py
- Test: system/tests/test_stc.py
- Test: system/tests/test_storage_rtc_boundaries.py

**Interfaces:**
- Consumes: source-text issues, VRS advisories, binding issues, and deterministic results.
- Produces: STRUCTURE_PROBLEM, VERSIFICATION_MISMATCH, READY_WITH_STRUCTURE_PROBLEMS, and COMPLETE_WITH_STRUCTURE_PROBLEMS.

- [ ] **Step 1: Write failing classification tests**

    from sage.structural_issues import classify_text_relation, completion_status, readiness_status

    def test_text_relation_is_relative_to_wip():
        assert classify_text_relation(wip_has_text=False, authority_has_text=True) == "OMISSION"
        assert classify_text_relation(wip_has_text=True, authority_has_text=False) == "ADDITION"
        assert classify_text_relation(
            wip_has_text=True, authority_has_text=True, wording_matches=False
        ) == "VARIATION"

    def test_structural_issue_completes_without_failure():
        issues = [{"classification": "STRUCTURE_PROBLEM", "code": "VERSIFICATION_MISMATCH"}]
        assert readiness_status(issues) == "READY_WITH_STRUCTURE_PROBLEMS"
        assert completion_status(issues) == "COMPLETE_WITH_STRUCTURE_PROBLEMS"

- [ ] **Step 2: Run tests and verify RED**

    ./sage-python -m pytest system/tests/test_structural_issues.py -q

Expected: module is absent.

- [ ] **Step 3: Implement normalization**

    def normalize_structure_problem(row: Mapping[str, Any]) -> dict[str, Any]:
        code = str(row.get("code") or "STRUCTURE_PROBLEM").upper()
        return {
            **dict(row),
            "classification": "STRUCTURE_PROBLEM",
            "status": "REPORT_ONLY",
            "structure_status": (
                "VERSIFICATION_MISMATCH"
                if "VRS" in code or "VERSIFICATION" in code
                else "STRUCTURE_PROBLEM"
            ),
        }

readiness_status() returns ACTION_NEEDED only when evidence cannot be loaded; otherwise a non-empty issue set is READY_WITH_STRUCTURE_PROBLEMS. completion_status() returns COMPLETE_WITH_STRUCTURE_PROBLEMS after completed analysis.

- [ ] **Step 4: Carry structural issues through RTC/STC**

Convert comparison-source coordinate gaps and VRS advisories into structural_issues while retaining source_text_issues as a backward-readable field. Use structural status in STC run documents, RTC aggregates, and Job/Run UI.

- [ ] **Step 5: Preserve true failure boundaries**

Do not downgrade malformed USFM/USJ, unsafe paths, immutable drift, prohibited writes, or incomplete WIP analytical coverage. Missing bindings remain ACTION_NEEDED before a Run exists.

- [ ] **Step 6: Run analytical regressions**

    ./sage-python -m pytest system/tests/test_structural_issues.py \
      system/tests/test_stc.py system/tests/test_storage_rtc_boundaries.py \
      system/tests/test_rtc_planner.py -q

Expected: gaps/VRS produce structural completion and immutable drift still raises.

- [ ] **Step 7: Commit structural reporting**

    git add system/src/sage/structural_issues.py system/src/sage/source_coverage.py \
      system/src/sage/stc.py system/src/sage/act_tasks.py system/src/sage/menu.py \
      system/tests/test_structural_issues.py system/tests/test_stc.py \
      system/tests/test_storage_rtc_boundaries.py
    git commit -m "feat: report structural deficiencies without failing runs"

### Task 6: Publish authority-explicit Book/chapter reports

**Files:**
- Create: system/src/sage/report_authority.py
- Create: system/tests/test_report_authority.py
- Modify: system/src/sage/stc_reporting.py
- Modify: system/src/sage/plan_continuation.py
- Modify: system/src/sage/act_outputs.py
- Test: system/tests/test_project_grammar_convergence.py
- Test: system/tests/test_stc.py
- Test: system/tests/test_operator_ux.py

**Interfaces:**
- Consumes: Job/Run snapshot receipts and resource fingerprints.
- Produces: authority_header(), chapter_report_path(), canonical report stems, and Job summaries.

- [ ] **Step 1: Write failing authority tests**

    from datetime import datetime, timezone
    from sage.jobs import JobStore
    from sage.report_authority import authority_header, chapter_report_path

    def stc_job_and_run(root):
        store = JobStore(root, root / "ecosystem.yml")
        job = store.create_job(
            tool="stc", job_id="STC-usWIP_20260901", display_name="STC fixture",
            bindings={"wip": "usWIP"},
            imported_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
        )
        return job, store.create_run(job, operation="stc", scope="JHN 5")

    def test_stc_header_names_project_and_grk(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        stc_job, stc_run = stc_job_and_run(root)
        lines = authority_header(
            stc_job, stc_run, family="GRK", fingerprints={"GRK": "a" * 64}
        )
        rendered = "\n".join(lines)
        assert "Analysis                     STC" in rendered
        assert "WIP Project                  usWIP" in rendered
        assert "Original-language authority  GRK" in rendered
        assert "REFERENCE Project            NOT USED" in rendered
        assert "GRK:PRIMARY" not in rendered

    def test_chapter_report_path_uses_job_run_book_and_chapter(make_workspace, tmp_path):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        stc_job, stc_run = stc_job_and_run(root)
        path = chapter_report_path(tmp_path, stc_job, stc_run, "JHN", 5)
        assert path == (
            tmp_path / stc_job.job_id / "JHN" / "005"
            / f"{stc_run.run_id}_JHN-005_ACTION-REPORT.md"
        )

- [ ] **Step 2: Run tests and verify RED**

    ./sage-python -m pytest system/tests/test_report_authority.py -q

Expected: module is absent.

- [ ] **Step 3: Implement shared headers**

RTC names WIP Project, snapshot date/fingerprint, REFERENCE Project/fingerprint, and NOT USED or option-#10 GRK/HEB. STC names WIP Project, snapshot date/fingerprint, exact GRK/HEB and fingerprint, plus REFERENCE Project NOT USED.

- [ ] **Step 4: Implement canonical report paths**

    chapter_root = layout.reports_root / job.job_id / book / f"{chapter:03d}"
    stem = f"{run.run_id}_{book}-{chapter:03d}"
    report_path = chapter_root / f"{stem}_ACTION-REPORT.md"
    note_path = chapter_root / f"{stem}_OPERATOR-NOTE.txt"
    data_path = (
        job.root / "report_data" / book / f"{chapter:03d}"
        / f"{stem}_CONSOLIDATED.json"
    )

Partition cross-chapter findings/structural issues and write JOB-SUMMARY.md at the Job report root.

- [ ] **Step 5: Correct STC prose**

Use: “Project usWIP contains an OMISSION at JHN 5:4 relative to GRK.” Evidence headings name usWIP and GRK/HEB. Do not expose WIP, SRC, OL, GRK:PRIMARY, or HEB:PRIMARY as unidentified report authorities.

- [ ] **Step 6: Run reporting regressions**

    ./sage-python -m pytest system/tests/test_report_authority.py \
      system/tests/test_project_grammar_convergence.py system/tests/test_stc.py \
      system/tests/test_operator_ux.py -q

Expected: all pass with Job/Book/chapter paths and explicit headers.

- [ ] **Step 7: Commit report changes**

    git add system/src/sage/report_authority.py system/src/sage/stc_reporting.py \
      system/src/sage/plan_continuation.py system/src/sage/act_outputs.py \
      system/tests/test_report_authority.py system/tests/test_project_grammar_convergence.py \
      system/tests/test_stc.py system/tests/test_operator_ux.py
    git commit -m "feat: identify project and authority in RTC STC reports"

### Task 7: Add Resource Status Report and Job-data wipe

**Files:**
- Create: system/src/sage/resource_status_report.py
- Create: system/src/sage/job_data_reset.py
- Create: system/tests/test_resource_status_report.py
- Create: system/tests/test_job_data_reset.py
- Modify: system/src/sage/menu.py
- Test: system/tests/test_out_of_box_reset.py

**Interfaces:**
- Consumes: Project Inventory, active RTC/STC Jobs, snapshot receipts, OL provenance, and safe storage boundaries.
- Produces: build_resource_status_report(), render_resource_status_report(), wipe_all_job_data(), and Maintenance actions.

- [ ] **Step 1: Write failing read-only report test**

    from copy import deepcopy
    from sage.project_inventory import load_project_registry
    from sage.resource_status_report import (
        build_resource_status_report,
        render_resource_status_report,
    )

    def test_resource_report_names_projects_and_authorities_without_mutation(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        before = deepcopy(load_project_registry(root))
        report = build_resource_status_report(root, settings_path=root / "ecosystem.yml")
        text = render_resource_status_report(report)
        assert "usWIP" in text
        assert "GRK" in text
        assert "HEB" in text
        assert report["status"] in {
            "READY", "READY_WITH_STRUCTURE_PROBLEMS", "ACTION_NEEDED"
        }
        assert load_project_registry(root) == before

- [ ] **Step 2: Write failing wipe test**

    from pathlib import Path
    from sage.job_data_reset import wipe_all_job_data
    from sage.storage import storage_layout

    def test_job_wipe_preserves_environment_projects_and_resources(make_workspace):
        root = make_workspace(configured=True, qualification_status="VALIDATED")
        layout = storage_layout(root, create=True)
        keep = layout.venv_root / "keep.txt"
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_text("managed", encoding="utf-8")
        registry = layout.state_root / "project-inventory.json"
        before = registry.read_bytes()
        (layout.jobs_root / "rtc" / "RTC-fixture_20260901").mkdir(parents=True)
        (layout.reports_root / "RTC-fixture_20260901").mkdir(parents=True)
        result = wipe_all_job_data(root)
        assert result["status"] == "JOB_DATA_WIPED"
        assert keep.read_text(encoding="utf-8") == "managed"
        assert registry.read_bytes() == before
        assert not any(layout.jobs_root.iterdir())
        assert not any(layout.reports_root.iterdir())
        assert Path(result["receipt_path"]).is_file()

- [ ] **Step 3: Run tests and verify RED**

    ./sage-python -m pytest system/tests/test_resource_status_report.py \
      system/tests/test_job_data_reset.py -q

Expected: both modules are absent.

- [ ] **Step 4: Implement Resource Status Report**

Each row has project_id, display_name, source_location, roles, content_state, books, coverage, versification, snapshot, authority, structural_issues, status, and next_action. Add GRK and HEB rows from active_ol_provenance(). Catch each resource SageError into ACTION_NEEDED so one defect never aborts the report.

- [ ] **Step 5: Implement bounded deletion**

    targets = (
        layout.jobs_root,
        layout.reports_root,
        layout.exports_root,
        layout.system_root / "jobs",
        layout.workflow_root,
        layout.locks_root,
        layout.transactions_root,
        layout.state_root / "active-jobs.json",
        layout.state_root / "last-run.json",
        layout.state_root / "operator-cues.jsonl",
        layout.state_root / "setup-state.json",
    )

Require every target below layout.data_root, delete without following symlinks, recreate empty layout roots, and write .system/state/job-data-wipe.json. Preserve Project Inventory, resource mounts, OL selection, inputs/resources, indexes, config, runtime/venv, and Core.

- [ ] **Step 6: Add Maintenance actions**

Add Resource Status Report and Wipe all Job data. Wipe defaults to no and requires exact WIPE JOB DATA. Keep Out-of-Box reset separate with RESET SAGE.

- [ ] **Step 7: Run maintenance regressions**

    ./sage-python -m pytest system/tests/test_resource_status_report.py \
      system/tests/test_job_data_reset.py system/tests/test_out_of_box_reset.py \
      system/tests/test_menu_projects.py -q

Expected: all pass; Job wipe retains environment/resources and OOB retains only runtime/Core.

- [ ] **Step 8: Commit maintenance features**

    git add system/src/sage/resource_status_report.py system/src/sage/job_data_reset.py \
      system/src/sage/menu.py system/tests/test_resource_status_report.py \
      system/tests/test_job_data_reset.py system/tests/test_out_of_box_reset.py \
      system/tests/test_menu_projects.py
    git commit -m "feat: add resource report and Job data wipe"

### Task 8: Align documentation and verify the release

**Files:**
- Modify: docs/OPERATOR-GUIDE.md
- Modify: docs/macos-linux/CHEAT-SHEET.md
- Modify: docs/macos-linux/RECOVERY.md
- Modify: docs/macos-linux/ERRORS.md
- Modify: docs/windows/CHEAT-SHEET.md
- Modify: docs/windows/RECOVERY.md
- Modify: docs/windows/ERRORS.md
- Modify: docs/advanced/workflows/FULL-PROCESS-FLOW.md
- Modify: docs/advanced/workflows/JOB-STORAGE-MAINTENANCE.md
- Modify: docs/advanced/workflows/SAW-CHECK-POLICY.md
- Modify: docs/advanced/projects-and-resources/PROJECT-INVENTORY.md
- Modify: docs/advanced/projects-and-resources/VERSIFICATION.md
- Modify: system/tests/test_documentation_contracts.py

**Interfaces:**
- Consumes: all implemented workflow/storage/status/report/maintenance contracts.
- Produces: executable documentation assertions matching shipped menus and paths.

- [ ] **Step 1: Write failing documentation assertion**

    def test_primary_workflow_documentation_contracts():
        guide = (ROOT / "docs/OPERATOR-GUIDE.md").read_text(encoding="utf-8")
        assert "Reference Text Comparison (RTC)" in guide
        assert "Source Text Correspondence (STC)" in guide
        assert "RTC-ukrNPUv1_20260901-001" in guide
        assert "STC never uses a REFERENCE Project" in guide
        assert "Wipe all Job data" in guide
        assert "COMPLETE_WITH_STRUCTURE_PROBLEMS" in guide

- [ ] **Step 2: Run the documentation test and verify RED**

    ./sage-python -m pytest \
      system/tests/test_documentation_contracts.py::test_primary_workflow_documentation_contracts -q

Expected: the first stale/absent contract fails.

- [ ] **Step 3: Update documentation**

Document BIC/RTC/STC menu order, separate bindings, snapshot/serial names, Book/chapter report paths, authority headers, structural completion, Resource Status Report, Job-data wipe, and separate OOB reset. Mark Targeted Check and standalone OL Review as parked without menu instructions.

- [ ] **Step 4: Run focused suites**

    ./sage-python -m pytest \
      system/tests/test_primary_analysis_jobs.py \
      system/tests/test_primary_workflow_menus.py \
      system/tests/test_job_snapshots.py \
      system/tests/test_structural_issues.py \
      system/tests/test_report_authority.py \
      system/tests/test_resource_status_report.py \
      system/tests/test_job_data_reset.py \
      system/tests/test_documentation_contracts.py -q

Expected: zero failures.

- [ ] **Step 5: Run static validation and full suite**

    ./sage-python -m sage.cli --settings ecosystem.yml --json validate
    ./sage-python -m pytest system/tests -q

Expected: validation exits 0 and pytest has zero failures with no new warnings.

- [ ] **Step 6: Inspect repository state**

    git diff --check
    git status --short
    git log --oneline -10

Expected: no whitespace errors and only intended documentation changes remain.

- [ ] **Step 7: Commit documentation**

    git add docs system/tests/test_documentation_contracts.py
    git commit -m "docs: document RTC and STC primary workflows"

- [ ] **Step 8: Re-run verification from committed state**

    ./sage-python -m sage.cli --settings ecosystem.yml --json validate
    ./sage-python -m pytest system/tests -q
    git status --short

Expected: validation/tests exit 0 and the working tree is clean.
