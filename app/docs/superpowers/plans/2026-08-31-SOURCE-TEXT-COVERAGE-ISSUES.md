# Source Text Coverage Issues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make coordinate-only comparison-source gaps nonblocking and operator-visible in RTC and STC while preserving exact WIP coverage and structural safety gates.

**Architecture:** Use a shared deterministic source-coverage issue builder, configure only comparison streams as coverage-optional, and carry sealed issues through task packets, normalized results, aggregation, and reports. Permit header-only comparison packets for valid empty source selections; keep WIP packet construction strict.

**Tech Stack:** Python 3, pytest, SAGE USFM/USJ compiler, deterministic JSON/Markdown renderers.

**Spec:** `docs/superpowers/specs/2026-08-31-SOURCE-TEXT-COVERAGE-ISSUES.md`

## Global Constraints

- Keep `WIP` primary coverage exact and blocking.
- Use `SOURCE_PRIMARY_COVERAGE_MISMATCH` and `source_text_issues` for runtime gaps.
- Never synthesize missing Scripture wording.
- Preserve malformed-resource, missing-file/book, bridge-boundary, and plan/result drift blockers.
- Preserve unrelated changes in the existing dirty worktree.
- Do not create commits unless requested.

---

### Task 1: Shared source coverage contract

**Files:**
- Create: `system/src/sage/source_coverage.py`
- Modify: `system/src/sage/sfm_slicer.py`
- Test: `system/tests/test_sfm_slicer.py`

**Interfaces:**
- Produces `source_text_issues(expected_refs, covered_refs, *, workflow, source_stream, source_project_id, scope)`.
- Retains `SfmStream.require_primary_coverage=True` as the safe default.

- [x] Add planner regressions proving comparator gaps no longer raise.
- [x] Run them and observe `SFM_ROUTE_PRIMARY_COVERAGE_MISMATCH` before implementation.
- [x] Add deterministic issue construction and optional comparator coverage.
- [x] Verify focused planner tests pass.

### Task 2: RTC and STC planning

**Files:**
- Modify: `system/src/sage/rtc_planner.py`
- Modify: `system/src/sage/stc.py`
- Modify: `system/src/sage/act_tasks.py`
- Test: `system/tests/test_rtc_planner.py`
- Test: `system/tests/test_stc.py`

**Interfaces:**
- Produces `rtc_package["source_text_issues"]` and `stc_package["source_text_issues"]`.

- [x] Test literal missing REFERENCE and primary-OL coordinates.
- [x] Mark only RTC REFERENCE and STC primary-OL route streams coverage-optional.
- [x] Replace secondary equality blockers with report-only package issues.
- [x] Preserve complete WIP `primary_coverage_atoms`.

### Task 3: Truthful sealed task packets

**Files:**
- Modify: `system/src/sage/act_tasks.py`
- Test: `system/tests/test_stc_task.py`
- Test: `system/tests/test_storage_rtc_boundaries.py`

**Interfaces:**
- Produces packet metadata with actual source coordinates and manifest-level `source_text_issues`.

- [x] Add real workspace tests with a one-coordinate WIP scope absent from the source.
- [x] Observe failures at strict source selection and STC/RTC packet construction.
- [x] Add explicit `allow_empty` only to comparison packet calls.
- [x] Serialize `\\id` plus requested `\\c` for an empty comparison packet.
- [x] Seal issues into task identity and instruct the provider not to invent wording.

### Task 4: Submission, aggregation, and reports

**Files:**
- Modify: `system/src/sage/act_tasks.py`
- Modify: `system/src/sage/act_outputs.py`
- Modify: `system/src/sage/plan_continuation.py`
- Modify: `system/src/sage/consolidation.py`
- Modify: `system/src/sage/stc.py`
- Modify: `system/src/sage/stc_reporting.py`
- Test: `system/tests/test_human_output.py`
- Test: `system/tests/test_stc.py`
- Test: `system/tests/test_stc_task.py`
- Test: `system/tests/test_storage_rtc_boundaries.py`

**Interfaces:**
- Produces normalized and aggregate `source_text_issues`, `source_comparison_status`, and dedicated RTC/STC report sections.

- [x] Add failing renderer and finalizer tests using literal `JHN 5:4` data.
- [x] Copy sealed issues into normalized submissions.
- [x] Deduplicate issues across partitioned RTC and STC aggregation.
- [x] Chapter-filter issues during final report publication.
- [x] Render `COMPLETE_WITH_SOURCE_TEXT_ISSUES` without changing exact WIP completion.

### Task 5: GRK resource correction and verification

**Files:**
- Create: `system/resources/scripture/original-language/grk/custom.vrs`
- Modify: `docs/advanced/projects-and-resources/VERSIFICATION.md`
- Modify: `docs/advanced/release/VANILLA-INSTALL-MANIFEST.md`
- Test: `system/tests/test_vrs.py`

**Interfaces:**
- Produces the validated 16-coordinate GRK exclusion set and documents its authority.

- [x] Verify the 16 candidates absent from bundled GRK SFM are excluded.
- [x] Verify double-bracketed passages and the shorter `1JN 5:7-8` reading remain present.
- [x] Document the distinction between authoritative custom VRS data and runtime text issues.
- [ ] Run the complete suite with bytecode/cache generation disabled.
- [ ] Run `git diff --check` and direct composed-GRK VRS reconciliation.
