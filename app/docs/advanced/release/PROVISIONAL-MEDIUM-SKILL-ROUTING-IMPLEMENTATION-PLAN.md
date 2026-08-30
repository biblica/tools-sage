# Provisional Medium Skill Routing Implementation Plan

> **For agentic workers:** Execute this plan test-first and preserve the immutable Run/task retry contracts.

**Goal:** Make every release state execute governed Skills through a truthful Medium provisional route when, and only when, no current qualification evidence exists, while preserving qualified-route precedence and adverse/stale evidence blocking.

**Architecture:** Extend the deterministic Python route resolver with an explicit no-data state and a release-state-independent policy branch. Keep exact qualification and manual override logic separate from provisional routing. Project the selected basis into CLI/menu displays, execution receipts, reports, and a pre-`Working` SAW preflight so `CONTINUE RUN` can retry the same sealed task.

**Tech stack:** Python 3.12, YAML/JSON policy schemas, pytest, existing SAGE model-service, skill-routing, LLM-task, ACT-output, CLI, and menu modules.

**Specification:** [Provisional Medium Skill Routing Design](PROVISIONAL-MEDIUM-SKILL-ROUTING-DESIGN.md)

## Global constraints

- Historical implementation began on `alpha/0.02alpha1`; the current universal policy is integrated into `0.01beta2`.
- Use one manual state plus two automatic substates: `USER_OVERRIDE`, `AUTOMATIC / DATA`, and `AUTOMATIC / NO DATA`.
- Default to provider-native `medium` only in a true no-data state.
- Exact current `QUALIFIED` or `RECOMMENDED` evidence always outranks provisional routing.
- Current `FAILED`/`UNRELIABLE` evidence and stale evidence block instead of falling back.
- The qualified global override remains qualification-only.
- Provisional routing is enabled for every release state; no release-state gate is permitted.
- Receipts must never represent provisional policy as qualification evidence.
- Preflight must happen before the UI prints `Working on ...`.
- Existing blocked Runs and sealed tasks remain resumable; do not recreate the JOS Run.

## Task 1: Add the universal no-data policy contract

**Files:**

- Modify: `app/system/config/model-policy.yml`
- Modify: `app/system/config/schemas/model-policy.schema.yml`
- Modify: `app/system/src/sage/model_policy.py`
- Test: `app/system/tests/test_skill_routing_policy.py`

1. Add failing tests for the universal provisional policy and implicit Codex Medium default.
2. Run the focused tests and confirm the new cases fail for missing behavior.
3. Add `provisional_routing` to the shipped policy and schema, including status label, provider default, prohibited native settings, and block effects; prohibit a release-state gate.
4. Validate the policy fields and values in `load_model_policy()`.
5. Keep the existing audited Advanced routing override as the only manual model/reasoning control.
6. Run the focused tests until green.

## Task 2: Implement qualification-first, no-data provisional resolution

**Files:**

- Modify: `app/system/src/sage/skill_routing.py`
- Modify: `app/system/src/sage/routing_override.py`
- Test: `app/system/tests/test_skill_routing_policy.py`

1. Add failing resolver tests for:
   - no evidence selects the deterministic available model at Medium with `PROVISIONAL_UNQUALIFIED`;
   - exact qualified evidence changes automatic routing from Medium to the evidence-selected reasoning;
   - known failed or unreliable evidence blocks;
   - stale evidence blocks;
   - Alpha, Beta, RC, and final builds all permit provisional execution in true no-data;
   - unavailable/hidden/unsupported models are not provisional candidates;
   - the exact global override cannot select a provisional route.
2. Confirm those tests fail against the current fail-closed resolver.
3. Add an explicit candidate-evidence state so the resolver can distinguish true absence, adverse current data, stale data, positive data, and unavailable candidates.
4. Extend `SkillRoute` with nullable qualification evidence, explicit `selection_mode`, and nullable provisional routing-basis hash.
5. Preserve `qualified_skill_routes()` and `resolve_specific_skill_route()` as qualification-only APIs.
6. Make `resolve_skill_route()` apply the approved precedence and construct a deterministic provisional route in every true no-data state.
7. Run the focused tests until green.

## Task 3: Expose truthful service, CLI, and menu state

**Files:**

- Modify: `app/system/src/sage/model_service.py`
- Modify: `app/system/src/sage/cli.py`
- Modify: `app/system/src/sage/menu.py`
- Test: `app/system/tests/test_command_contract.py`
- Test: `app/system/tests/test_operator_ux.py`
- Test: `app/system/tests/test_menu_projects.py`

1. Add failing tests for route/recommendation output that labels provisional selection without calling it qualified or recommended.
2. Separate provisional route output from `qualified_skill_routes` and give aggregate availability a distinct provisional-ready state.
3. Display the automatic no-data Medium default beside the existing audited Advanced routing override.
4. Record `USER_OVERRIDE`, `EXACT_SKILL_QUALIFICATION`, or `PROVISIONAL_PROVIDER_DEFAULT` as the exact selection source.
5. Normalize the Job/Run route display to include provider, model, native reasoning, and `PROVISIONAL_UNQUALIFIED`.
6. Run the focused UI/command tests until green.

## Task 4: Record provisional provenance in receipts and reports

**Files:**

- Modify: `app/system/config/schemas/llm-execution-receipt.schema.yml`
- Modify: `app/system/src/sage/llm_tasks.py`
- Modify: `app/system/src/sage/act_outputs.py`
- Test: `app/system/tests/test_llm_harness.py`
- Test: `app/system/tests/test_report_dynamic_naming.py`

1. Add failing tests proving qualified receipts require qualification evidence, while provisional receipts omit that evidence and require a policy routing-basis hash and provisional selection mode.
2. Update receipt generation to use the route's actual selection mode and conditional provenance.
3. Update schema validation and report projection without weakening historical schema 2.0 receipt readability.
4. Confirm reports expose the exact provisional status and do not invent qualification evidence.
5. Run the focused tests until green.

## Task 5: Resolve before visible SAW work and preserve retry

**Files:**

- Modify: `app/system/src/sage/menu.py`
- Modify: `app/system/src/sage/llm_tasks.py` only if a reusable read-only preflight entry point is needed
- Test: `app/system/tests/test_operator_ux.py`

1. Add failing tests that route resolution and its display occur before `Working on ...`, and that a blocked sealed task is retried without changing Run or task identity.
2. Add a read-only route preflight immediately before task creation/continuation and visible work status. Keep just-in-time resolution inside execution as the final authority check.
3. Reuse the preflight result for the header/display, but never trust it as a substitute for attempt-time validation.
4. Run the focused SAW tests until green.

## Task 6: Update Operator and release documentation

**Files:**

- Modify: `app/docs/INDEX.md`
- Modify: relevant Operator model-routing and release documents discovered by reference search
- Modify: `app/docs/advanced/release/PROVISIONAL-MEDIUM-SKILL-ROUTING-DESIGN.md`
- Test: `app/system/tests/test_documentation_contracts.py`

1. Document Medium as a universal no-data fallback, not a qualified recommendation.
2. Document the Operator preference, its precedence, block cases, receipt labels, and `CONTINUE RUN` behavior.
3. Mark the design implemented only after verification succeeds.
4. Run documentation contract tests.

## Task 7: Harden, validate the preserved JOS Run, and commit

1. Run all focused policy, resolver, settings, receipt, CLI/menu, and SAW tests.
2. Run package/schema validation and the complete test suite with bytecode and cache generation disabled.
3. Dry-run route resolution against the preserved JOS RTC task manifest. Verify it selects Codex Medium provisionally and does not create an attempt, receipt, task, or replacement Run.
4. Inspect the existing JOS Run/task identity before and after the dry run to confirm immutability.
5. Review the diff for accidental qualification claims, hidden fallback paths, unrelated localdata changes, and generated artifacts.
6. Commit the verified implementation on the approved release branch. Do not push or merge unless the Operator requests it.
