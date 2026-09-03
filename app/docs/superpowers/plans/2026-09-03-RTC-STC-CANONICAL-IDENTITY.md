# RTC/STC Canonical Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RTC and STC canonical in all newly generated runtime artifacts and current-facing text, retain an isolated legacy SAW reader, and render staged RTC progress as one unambiguous live row.

**Architecture:** Extend `workflow_identity.py` into the single identity boundary: canonical writers receive `rtc` or `stc`, while legacy readers normalize stored `saw` plus its operation. The existing analysis engine remains shared, but configuration, task creation, continuation, reports, Skills, and UI consume canonical identity helpers instead of raw legacy strings. Compatibility branches remain explicit and read-only.

**Tech Stack:** Python 3.12, pytest, YAML/JSON schemas, Markdown Skills/ACT tasks, terminal `MenuIO` progress rendering.

**Spec:** `docs/superpowers/specs/2026-09-03-RTC-STC-CANONICAL-IDENTITY-DESIGN.md`

## Global Constraints

- New RTC/STC Jobs, Runs, plans, manifests, findings, reports, events, and ACT tasks must not serialize a legacy SAW identity.
- Existing sealed legacy artifacts must remain byte-for-byte unchanged and readable.
- `SAW` may appear only in explicit compatibility code, historical source material, frozen fixtures, and existing stored artifacts.
- TUI workflow actions remain paused; this migration changes only shared text/error rendering used by the current read-only TUI.
- RTC/STC evidence policy, versification behavior, bridge handling, and analytical conclusions do not change.
- Every production behavior change follows a witnessed red-green pytest cycle.
- Preserve all unrelated modifications already present in the dirty worktree.

---

### Task 1: Canonical identity and legacy normalization boundary

**Files:**
- Modify: `system/src/sage/workflow_identity.py`
- Modify: `system/src/sage/jobs.py`
- Test: `system/tests/test_primary_analysis_jobs.py`
- Test: `system/tests/test_storage_rtc_boundaries.py`

**Interfaces:**
- Produces: `is_analysis_workflow(value: str) -> bool`
- Produces: `canonical_analysis_workflow(workflow: str, operation: str | None = None) -> str`
- Produces: `analysis_operation_label(operation: str) -> str`
- Produces: `analysis_reason_code(code: str, operation: str) -> str`
- Produces: `legacy_saw_workflow(workflow: str) -> bool`
- Changes: `Job.runtime_tool` returns the canonical Job tool for RTC/STC; legacy Jobs continue returning `saw` only through the compatibility predicate.

- [ ] **Step 1: Write failing identity tests**

```python
def test_new_analysis_jobs_keep_canonical_runtime_identity() -> None:
    assert runtime_workflow_id("rtc") == "rtc"
    assert runtime_workflow_id("stc") == "stc"


def test_legacy_saw_identity_normalizes_from_operation() -> None:
    assert canonical_analysis_workflow("saw", "rtc") == "rtc"
    assert canonical_analysis_workflow("saw", "stc") == "stc"
```

- [ ] **Step 2: Run tests and witness the old adapter mapping fail**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_primary_analysis_jobs.py tests/test_storage_rtc_boundaries.py`

Expected: the RTC/STC runtime identity assertion fails because both currently return `saw`.

- [ ] **Step 3: Implement the identity boundary**

```python
ANALYSIS_WORKFLOWS = frozenset({"rtc", "stc"})
LEGACY_ANALYSIS_WORKFLOW = "saw"


def canonical_analysis_workflow(workflow: str, operation: str | None = None) -> str:
    value = str(workflow).strip().lower()
    if value in ANALYSIS_WORKFLOWS:
        return value
    if value == LEGACY_ANALYSIS_WORKFLOW and str(operation).strip().lower() in ANALYSIS_WORKFLOWS:
        return str(operation).strip().lower()
    raise ValidationError(f"Unsupported analysis workflow: {workflow!r}")
```

Route all new Job code through this helper; keep raw `saw` recognition in a clearly named compatibility function.

- [ ] **Step 4: Run the focused identity tests**

Run the Step 2 command and require zero failures.

- [ ] **Step 5: Review the diff for raw identity branches**

Run: `git diff --check && rg -n 'runtime_tool.*saw|return "saw"' app/system/src/sage/workflow_identity.py app/system/src/sage/jobs.py`

Expected: no ordinary RTC/STC writer maps back to `saw`; any match is documented legacy compatibility.

---

### Task 2: Canonical runtime configuration and artifact writers

**Files:**
- Create: `system/config/workflows/rtc/profile.yml`
- Create: `system/config/workflows/stc/profile.yml`
- Modify: `ecosystem.yml`
- Modify: `system/src/sage/registry.py`
- Modify: `system/src/sage/jobs.py`
- Modify: `system/src/sage/act_tasks.py`
- Modify: `system/src/sage/plan_continuation.py`
- Modify: `system/src/sage/stage_reset.py`
- Modify: `system/config/schemas/ecosystem.schema.yml`
- Modify: `system/config/schemas/workflow-profile.schema.yml`
- Test: `system/tests/test_registry_and_profiles.py`
- Test: `system/tests/test_primary_analysis_jobs.py`
- Test: `system/tests/test_stc_task.py`
- Test: `system/tests/test_storage_rtc_boundaries.py`

**Interfaces:**
- Consumes: canonical identity helpers from Task 1.
- Produces: new runtime settings containing `workflows.bic`, `workflows.rtc`, and `workflows.stc`.
- Produces: new task manifests with `workflow: rtc|stc`.
- Produces: `RTC_COMPOSITE`, `RTC-*`, and `STC-*` plan/task identities for new work.
- Preserves: legacy readers for `workflow: saw`, `SAW_RTC_COMPOSITE`, and legacy filenames.

- [ ] **Step 1: Write failing artifact tests**

```python
def test_new_rtc_manifest_and_plan_use_canonical_identity(...):
    result = create_act_task(config, workflow="rtc", operation="rtc", ...)
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["workflow"] == "rtc"
    assert manifest["task_id"].startswith("rtc-")
    assert "SAW" not in Path(result["act_path"]).read_text()


def test_new_stc_manifest_uses_canonical_identity(...):
    result = create_act_task(config, workflow="stc", operation="stc", ...)
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["workflow"] == "stc"
    assert manifest["task_id"].startswith("stc-")
```

- [ ] **Step 2: Run focused tests and witness unsupported canonical workflows**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_registry_and_profiles.py tests/test_primary_analysis_jobs.py tests/test_stc_task.py tests/test_storage_rtc_boundaries.py`

Expected: task creation or registry validation fails because only `saw` is registered internally.

- [ ] **Step 3: Add canonical profiles and registry support**

Register `rtc` and `stc` as current workflow IDs. Keep the old SAW profile resolvable only when a loaded settings document actually contains a legacy workflow. Give RTC only RTC policy and bindings; give STC only STC policy and bindings. Derived Job settings activate exactly the canonical Job workflow.

```yaml
workflows:
  rtc:
    profile: system/config/workflows/rtc/profile.yml
  stc:
    profile: system/config/workflows/stc/profile.yml
```

- [ ] **Step 4: Convert new task/plan writers**

Replace writer-side `workflow="saw"`, `SAW_RTC_COMPOSITE`, `SAW-RTC-*`, and `SAW-STC-*` values with the owning canonical workflow. Reader predicates accept both canonical and legacy values without rewriting loaded data.

```python
if plan.get("plan_type") in {"RTC_COMPOSITE", "SAW_RTC_COMPOSITE"}:
    return _continue_rtc_composite(config, path, plan)
```

- [ ] **Step 5: Run focused runtime/artifact tests**

Run the Step 2 command and require zero failures.

- [ ] **Step 6: Run schema tests**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_schema_validation.py tests/test_package.py::test_package_validation`

Expected: all selected tests pass.

---

### Task 3: Single-row staged progress and canonical operator errors

**Files:**
- Modify: `system/src/sage/menu.py`
- Modify: `system/src/sage/cli.py`
- Modify: `system/src/sage/evidence.py`
- Modify: `system/src/sage/execution_events.py`
- Modify: `system/src/sage/human_output.py`
- Test: `system/tests/test_operator_ux.py`
- Test: `system/tests/test_menu_projects.py`
- Test: `system/tests/test_cli_dev3.py`
- Test: `system/tests/test_primary_workflow_menus.py`

**Interfaces:**
- Consumes: `analysis_operation_label` and `analysis_reason_code` from Task 1.
- Produces: `_analysis_work_unit_status(...)` with one replaceable TTY status row.
- Produces: one non-interactive stage milestone per stage, not one line per work unit.
- Produces: RTC/STC-specific preflight, completion, aggregation, validation, and remediation text.

- [ ] **Step 1: Write failing progress tests**

```python
def test_captured_rtc_progress_does_not_stack_review_portions(...):
    center._continue_analysis_plan(project, run)
    rendered = output.getvalue()
    assert rendered.count("Current portion:") == 0
    assert rendered.count("Stage:") == 2
    assert "Review portion:" not in rendered


def test_tty_progress_names_stage_and_reuses_one_status_row(...):
    with center._analysis_work_unit_status(
        operation="rtc", composite_stage="REFERENCE_TEXT_COMPARISON",
        index=1, total=2, scope="1CH 5:1-6:19"
    ):
        pass
    assert "Stage:             Reference Text Comparison" in terminal.frames
    assert "Current portion:   1/2 — 1CH 5:1-6:19" in terminal.frames
```

- [ ] **Step 2: Run progress tests and witness accumulated `Review portion` lines**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_operator_ux.py tests/test_menu_projects.py`

Expected: the new assertions fail because `MenuIO.working` currently writes every non-TTY portion permanently.

- [ ] **Step 3: Implement stage-aware progress**

Track the last emitted non-TTY stage on the continuation call. TTY output updates one compound status string; non-TTY output writes only a stage transition. Rename generic helpers from `_saw_*` to `_analysis_*`, leaving thin legacy aliases only if old callers require them.

```python
stage_name = analysis_stage_label(composite_stage, operation)
if self.io.interactive:
    status_text = render_current_analysis_progress(...)
elif stage_name != previous_stage:
    self.io.write(f"{'Stage:':<18}{stage_name}")
```

- [ ] **Step 4: Write failing canonical error/menu tests**

Exercise an RTC route-limit error and an STC preflight failure through the real menu error renderer. Assert that operator messages and current reason codes use RTC/STC and contain no standalone SAW term. Exercise `build_parser().format_help()` and the current maintenance/resource menus with the same boundary.

- [ ] **Step 5: Run error/menu tests and witness stale labels**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_operator_ux.py tests/test_menu_projects.py tests/test_cli_dev3.py tests/test_primary_workflow_menus.py`

Expected: failures identify current `SAW` resource, completion, CLI, or error wording.

- [ ] **Step 6: Replace current-facing menu, CLI, and error terminology**

Use the owning Job/Run operation for labels. Remove the legacy public SAW menu; maintenance may list `Legacy RTC/STC compatibility data` without presenting SAW as a workflow. Keep legacy stored reason codes readable, but new failures receive RTC/STC/ANALYSIS prefixes.

- [ ] **Step 7: Run the Task 3 test set**

Run the Step 5 command and require zero failures.

---

### Task 4: Canonical reports, ACT tasks, provider prompts, and Skills

**Files:**
- Modify: `system/src/sage/act_tasks.py`
- Modify: `system/src/sage/act_outputs.py`
- Modify: `system/src/sage/llm_tasks.py`
- Modify: `system/src/sage/plan_continuation.py`
- Modify: `system/src/sage/stc_reporting.py`
- Create: `system/skills/rtc/SKILL.md`
- Create: `system/skills/rtc/agents/openai.yaml`
- Create: `system/skills/stc/SKILL.md`
- Create: `system/skills/stc/agents/openai.yaml`
- Modify: `system/config/skills.json`
- Modify: `system/config/skill-evaluation-contracts.json`
- Test: `system/tests/test_stc_registration.py`
- Test: `system/tests/test_llm_harness.py`
- Test: `system/tests/test_report_dynamic_naming.py`
- Test: `system/tests/test_model_evaluation.py`

**Interfaces:**
- Consumes: canonical workflow values and compatibility normalization.
- Produces: active Skill IDs `rtc` and `stc`; legacy `saw-rtc` and `saw-stc` hashes remain lookup-only aliases.
- Produces: RTC/STC ACT headings, instructions, validation labels, findings, action reports, aggregate reports, and versification advisories.

- [ ] **Step 1: Write failing generated-output tests**

Generate a real RTC ACT, STC ACT, RTC report, and STC report from fixtures. Assert their operation-specific titles and workflow identities, and assert no standalone SAW term in the generated text.

```python
assert "Reference Text Comparison (RTC)" in rtc_act
assert "Source Text Correspondence (STC)" in stc_act
assert not re.search(r"\bSAW\b", rtc_act + stc_act + rtc_report + stc_report)
```

- [ ] **Step 2: Run generated-output tests and witness stale task/report prose**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_stc_registration.py tests/test_llm_harness.py tests/test_report_dynamic_naming.py tests/test_model_evaluation.py`

Expected: failures identify SAW titles, instructions, validation descriptions, or report prose.

- [ ] **Step 3: Add active RTC/STC Skills and legacy aliases**

Copy only the governed RTC/STC rules into canonical Skill directories and remove SAW wording from active titles, descriptions, instructions, agent metadata, and references. Register the canonical IDs for new routing. Preserve old Skill files and hashes under an explicit `legacy_aliases` mapping so sealed tasks still validate without selecting those IDs for new work.

- [ ] **Step 4: Make ACT/provider/report rendering operation-aware**

Pass canonical workflow or operation into shared renderers. Replace generic fixed labels with `RTC`, `STC`, or neutral `analysis` text. Use canonical ID prefixes for new findings and reports; accept old prefixes only during legacy validation.

- [ ] **Step 5: Run the Task 4 test set**

Run the Step 2 command and require zero failures.

- [ ] **Step 6: Validate Skill hashes and routing**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_skill_routing_policy.py tests/test_schema_validation.py tests/test_package.py`

Expected: all selected tests pass with canonical new routing and legacy lookup intact.

---

### Task 5: Documentation, configuration prose, and terminology audit

**Files:**
- Modify: current files under `docs/`
- Modify: current prose under `system/config/`
- Modify: active Skill references under `system/skills/`
- Modify: `system/tools/deep_audit.py`
- Modify: `system/tests/test_documentation_contracts.py`
- Modify: `docs/advanced/release/VANILLA-INSTALL-MANIFEST.md`

**Interfaces:**
- Produces: a source audit that classifies current surfaces separately from explicit legacy/historical paths.
- Produces: current documentation that uses RTC/STC/Targeted Check/Original-Language Review terminology.
- Preserves: historical prompt originals, frozen evaluation fixtures, release archaeology, and legacy sealed data.

- [ ] **Step 1: Write a failing behavioral audit test**

Run the real deep-audit command on a copied distribution containing `SAW` in a current operator guide, active Skill, and ACT template; require failure. Place the same token in an allowlisted historical original prompt and require success.

```python
assert current_result.returncode == 2
assert "stale legacy analysis identity" in current_result.stdout.lower()
assert historical_result.returncode == 0
```

- [ ] **Step 2: Run the audit tests and witness missing terminology enforcement**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_documentation_contracts.py tests/test_package.py`

Expected: the new audit test fails because stale SAW terms are not yet classified.

- [ ] **Step 3: Implement current-versus-legacy audit routing**

Add explicit path categories. Current code strings, menus, docs, active Skills, config prose, and templates reject standalone `SAW`. Compatibility modules, original prompts, frozen fixtures, historical release records, and stored local data are allowlisted with narrow path rules.

- [ ] **Step 4: Update current documentation and configuration prose**

Replace current product wording contextually, update cross-links for canonical Skill/profile names, and label retained historical documents. Do not bulk-replace immutable fixtures or original source prompts.

- [ ] **Step 5: Run documentation and package tests**

Run the Step 2 command and require zero failures.

- [ ] **Step 6: Run the source audit directly**

Run: `cd app && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/deep_audit.py . --mode source`

Expected: JSON status `PASS` with no stale-current-surface errors.

---

### Task 6: Legacy fixture, regression, and release verification

**Files:**
- Test: `system/tests/test_storage_rtc_boundaries.py`
- Test: `system/tests/test_primary_analysis_jobs.py`
- Test: `system/tests/test_release_builder.py`
- Modify: `system/config/CHANGELOG.md`
- Modify: `system/config/DEVELOPMENT-STATUS.md`
- Modify: `system/config/project-management/IMPLEMENTED-UPDATES.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: evidence that new canonical work and legacy read-only compatibility coexist.

- [ ] **Step 1: Add a legacy read-only regression fixture**

Create a temporary legacy Job/Run in the test body with `tool: saw`, `workflow: saw`, and `plan_type: SAW_RTC_COMPOSITE`. Record hashes before loading/continuing, then assert the compatibility reader resolves RTC and leaves every sealed fixture hash unchanged.

- [ ] **Step 2: Run the legacy test and witness any compatibility gap**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_storage_rtc_boundaries.py tests/test_primary_analysis_jobs.py`

Expected: any writer-side assumption that rejects legacy data fails here before final verification.

- [ ] **Step 3: Fix only demonstrated compatibility gaps**

Confine each fix to the legacy reader/normalizer. Do not weaken canonical writer assertions or rewrite the legacy fixture.

- [ ] **Step 4: Update release status records**

Record the canonical RTC/STC identity migration, progress behavior, compatibility boundary, and verification commands in the current changelog/status documents.

- [ ] **Step 5: Run the complete test suite**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider`

Expected: all tests pass with zero failures.

- [ ] **Step 6: Run final packaging checks**

Run:

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/validate_schemas.py .
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/validate_package.py .
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m compileall -q system/src system/tools
```

Expected: schema and package validation report ready/pass, and compilation exits zero.

- [ ] **Step 7: Audit the final diff**

Run: `git diff --check && git status --short && git diff --stat`

Confirm only intended source, test, Skill, configuration, report, and documentation changes are present; preserve every unrelated pre-existing edit.
