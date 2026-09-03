# Skill-qualified model routing implementation plan

> Historical implementation record: examples using `saw-*` identify the original sealed Skill suites. Current RTC/STC work routes through the canonical `rtc` and `stc` Skills; legacy suites remain readable for sealed Jobs.

> **Required implementation skill:** Use `superpowers:test-driven-development` for every runtime change and `superpowers:verification-before-completion` before reporting any task complete.

**Goal:** Replace global model/reasoning selection with provider-neutral, deterministic routing to an available route qualified for the exact registered Skill, while preserving Python ownership, item isolation, auditable overrides, truthful receipts, and Operator-visible execution metadata.

**Architecture:** Core policy classifies execution ownership before routing. `skill_routing.py` reconciles registered Skill identity, live provider capability, qualification evidence, and an optional audited override into one immutable `SkillRoute`. `model_evaluation.py` runs sealed synthetic cases three times and lets existing deterministic validators—not a model—decide qualification. Runtime tasks consume only a resolved route; submission and reporting project the actual execution receipt without recomputing or inventing it.

**Technology:** Python 3.12, dataclasses, JSON/YAML schemas, existing provider adapters, pytest, existing atomic storage and hardening tools.

**Branch boundary:** Perform all work on `alpha/0.02alpha1`. Do not merge or commit to `main` without explicit Operator approval after live Alpha testing.

## Non-negotiable contracts

- The routing key is the exact `skill_id` from `system/config/skills.json`, never a reconstructed workflow/operation string.
- Python planning, parsing, scope projection, token measurement, validation, aggregation, report composition, naming, and state transition never enter model routing and never receive an LLM token budget.
- Provider-native reasoning IDs and order are retained. SAGE does not invent a universal low/medium/high scale.
- New or changed model identity, capability fingerprint, Skill hash, suite hash, or policy version is `UNASSESSED` or `STALE`; no model can qualify itself.
- Operational tasks accept only `RECOMMENDED` or `QUALIFIED` exact routes. The evaluation harness is the only path allowed to exercise unqualified candidates.
- An advanced global override is an exact provider/model/reasoning route, still checked against the current Skill. It never enables an unqualified route and never silently falls back.
- Original-language adjudication is exactly one item per model request. Secondary-language rendering is exactly one reported item per request, inherits the originating item route, remains `ASSISTIVE_TRANSLATION_ONLY`, and degrades safely.
- Historical receipts remain readable. New reports state only routes proved by execution receipts.

## Task 1: Freeze execution ownership and provider-neutral policy schemas

**Files:**

- Create `system/config/execution-ownership.yml`.
- Create `system/config/schemas/execution-ownership.schema.yml`.
- Create `system/config/schemas/model-policy.schema.yml`.
- Modify `system/config/model-policy.yml` to schema `2.0`.
- Modify `system/src/sage/schema_validation.py`.
- Modify `system/src/sage/validation.py`.
- Create `system/tests/test_skill_routing_policy.py`.

**Step 1: Write failing schema and ownership tests.**

Assert that every registered Skill is classified `GOVERNED_SKILL`; controller operations are explicitly enumerated as `DETERMINISTIC_PYTHON`; Local AI capabilities are `LOCAL_ASSISTIVE`; no deterministic class has a token policy or route profile; policy keys exactly equal the registered Skill IDs.

The ownership registry must explicitly list at least planning, scripture parsing, SFM slicing, coverage, identity, aggregation, report composition, report naming, validation, finalization, and token measurement as Python-owned. It must list report secondary rendering as an item-isolated governed subtask of its originating Skill, not as a new analytical Skill.

Run:

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_skill_routing_policy.py
```

Expected: FAIL because the schemas and policy do not exist.

**Step 2: Implement schema `2.0`.**

Replace Codex-only `qualification` and `task_profiles` with these provider-neutral sections:

```yaml
schema_version: '2.0'
qualification_policy_version: alpha1-1
unknown_route_status: UNASSESSED
accepted_operational_statuses: [RECOMMENDED, QUALIFIED]
recommendation_order:
  - hard_contracts
  - cost_class
  - provider_native_reasoning_order
  - material_semantic_score
  - release_preference
skill_routes:
  bic-inspect: {suite_id: alpha1-bic-inspect, execution_class: GOVERNED_SKILL}
```

All seven registered Skills must appear exactly once. Do not encode a release preference as qualification evidence.

**Step 3: Register schema owners and distribution paths.**

Add explicit schema ownership and package-validation entries so missing, extra, or malformed routing files fail the existing schema/package gates.

**Step 4: Run the focused tests and commit.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_skill_routing_policy.py system/tests/test_schema_validation.py system/tests/test_provider_and_boundary_policy.py
git add app/system/config app/system/src/sage/schema_validation.py app/system/src/sage/validation.py app/system/tests/test_skill_routing_policy.py
git commit -m "feat: govern execution ownership and skill routes"
```

## Task 2: Implement exact route identity and deterministic resolution

**Files:**

- Create `system/src/sage/skill_routing.py`.
- Modify `system/src/sage/executors/base.py`.
- Modify `system/src/sage/model_policy.py` into a compatibility facade over Skill routing.
- Modify `system/src/sage/model_service.py`.
- Extend `system/tests/test_skill_routing_policy.py`.
- Modify `system/tests/test_llm_harness.py`.

**Step 1: Write failing resolver tests.**

Use fake Codex, Claude-like, and no-reasoning-control catalogs. Cover:

- exact Skill, adapted Skill hash, suite hash, model ID, capability fingerprint, and native reasoning match;
- `UNASSESSED` for an unseen model or reasoning setting;
- `STALE` for any bound hash/fingerprint change;
- unavailable qualified route rejection;
- stable recommendation ordering;
- `provider-default` for a provider without reasoning controls;
- no universal effort-rank assumption across providers;
- the existing Codex catalog mapping through the same neutral interface.

Expected public interfaces:

```python
@dataclass(frozen=True)
class RouteIdentity:
    provider: str
    model_id: str
    capability_fingerprint: str
    reasoning_id: str
    skill_id: str
    skill_sha256: str
    suite_id: str
    suite_sha256: str
    policy_version: str

@dataclass(frozen=True)
class SkillRoute:
    identity: RouteIdentity
    availability: str
    qualification: str
    routing_mode: str
    evidence_sha256: str
    provider_runtime_version: str | None

def resolve_skill_route(root: Path, skill_id: str, statuses: Sequence[ProviderStatus]) -> SkillRoute: ...
```

**Step 2: Add provider identity primitives.**

Extend `ModelCapability` with explicit `identity_strength` (`IMMUTABLE` or `ALIASED`) and a deterministic canonical capability fingerprint. Retain provider-advertised reasoning order exactly. Adapters may declare cost class and stable preference metadata, but those fields must not imply qualification.

**Step 3: Implement fail-closed resolution.**

Load Core seed evidence plus reconciled machine-local receipts. Filter by exact route identity and accepted status before applying stable recommendation order. Emit `NO_QUALIFIED_SKILL_ROUTE`, `SKILL_ROUTE_EVIDENCE_STALE`, or `PROVIDER_ROUTE_UNAVAILABLE` before any task evidence is sent.

Keep legacy `recommend_model()` only as a deprecated adapter that obtains the registered Skill ID and calls the new resolver. No new code may use workflow/profile lookup.

**Step 4: Expose read-only service views.**

Add `ModelService.skill_routes()`, `ModelService.recommendation_for_skill(skill_id)`, and provider-neutral catalog qualification rows. Provider status remains separate from Skill readiness.

**Step 5: Verify and commit.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_skill_routing_policy.py system/tests/test_llm_harness.py system/tests/test_provider_and_boundary_policy.py
git add app/system/src/sage app/system/tests
git commit -m "feat: resolve exact qualified skill routes"
```

## Task 3: Migrate provider settings and add the audited override

**Files:**

- Modify `system/src/sage/llm_settings.py`.
- Create `system/src/sage/routing_override.py`.
- Create `system/config/schemas/model-routing-override.schema.yml`.
- Create `system/config/schemas/model-routing-override-receipt.schema.yml`.
- Modify `system/src/sage/schema_validation.py`.
- Modify `system/src/sage/model_service.py`.
- Create `system/tests/test_routing_override.py`.
- Modify `system/tests/test_provider_and_boundary_policy.py` and `system/tests/test_operator_ux.py`.

**Step 1: Write migration and override failures first.**

Test that schema `1.2` settings preserve connection and Local AI provisioning fields but discard old global Codex model/reasoning/selection as operational choices. Loading legacy state must not silently create an override.

Test exact override create/change/clear receipts, prior mode, UTC time, route identity, qualification coverage such as `5/7`, atomic persistence, unavailable route rejection, and per-Skill fail-closed behavior.

**Step 2: Implement provider-only settings schema `2.0`.**

Normal settings retain enabled provider/connection state and Ollama assistive configuration. Move override state to:

```text
localdata/.system/config/model-routing-override.json
localdata/.system/state/model-routing-overrides/<utc>-<action>.json
```

Do not store credentials. Do not import a legacy global choice into the override.

**Step 3: Implement exact override validation.**

`set_global_override(route_identity)` accepts only an available route qualified for at least one registered Skill. Runtime resolution still rejects it for every Skill outside that qualified set with `GLOBAL_OVERRIDE_NOT_QUALIFIED_FOR_SKILL`. `clear_global_override()` restores `AUTOMATIC` in one audited action.

**Step 4: Verify and commit.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_routing_override.py system/tests/test_provider_and_boundary_policy.py system/tests/test_operator_ux.py
git add app/system/src/sage app/system/config/schemas app/system/tests
git commit -m "feat: migrate provider settings and audit route overrides"
```

## Task 4: Build sealed per-Skill evaluation contracts and harness

**Files:**

- Create `system/config/skill-evaluation-contracts.json`.
- Create `system/config/model-qualification-seeds.json` with an initially empty evidence inventory.
- Create `system/config/schemas/skill-evaluation-contracts.schema.yml`.
- Create `system/config/schemas/model-qualification-receipt.schema.yml`.
- Create `system/config/schemas/model-qualification-seeds.schema.yml`.
- Create `system/evaluations/model-routing-alpha1/` with generated synthetic case bundles.
- Create `system/tools/build_model_evaluation_cases.py`.
- Create `system/src/sage/model_evaluation.py`.
- Modify `system/src/sage/schema_validation.py` and `system/src/sage/validation.py`.
- Create `system/tests/test_model_evaluation.py`.

**Step 1: Write failing inventory and reconciliation tests.**

Require an explicit sealed case inventory per Skill and exactly three independent attempts per case. The initial inventory used three cases per Skill; later RTC referral hardening adds two RTC-only semantic boundary cases.

| Skill | Positive | Zero finding | Adversarial |
|---|---|---|---|
| `bic-inspect` | `seeded-material-issue` | `clean-source` | `forged-evidence` |
| `bic-rewrite` | `authorized-challenges` | `no-change-required` | `scope-expansion` |
| `bic-self-check` | `detect-regression` | `approve-clean` | `blocking-regression` |
| `saw-rtc` | `seeded-variance` | `aligned-pair` | `false-ol-referral` |
| `saw-stc` | `seeded-correspondence` | `complete-no-finding` | `reference-contamination` |
| `saw-focused-check` | `bounded-answer` | `bounded-zero-result` | `question-expansion` |
| `saw-original-language-review` | `greek-single-item` | `hebrew-no-change` | `multi-item-contamination` |

All fixtures use synthetic, redistributable SFM/USFM text and canonical three-digit book IDs. No external Project, copyrighted translation text, credentials, or network state may enter the bundle.

**Step 2: Build and verify sealed fixtures deterministically.**

`build_model_evaluation_cases.py --build` uses existing task factories and writes complete `task-manifest.json`, `ACT.md`, packets, and `expected.json`. `--verify` regenerates in a temporary directory and compares complete file inventories and SHA-256 values. Package validation runs `--verify`.

Each `expected.json` declares exact finding/category/coverage assertions, allowed narrative equivalence IDs, prohibited outputs, and the existing submission/finalization validator invoked. OL cases permit one and only one request identity. No expectation is generated by the candidate model.

**Step 3: Implement an evaluation-only execution path.**

```python
def evaluate_candidate(
    root: Path,
    *,
    skill_id: str,
    provider: str,
    model_id: str,
    reasoning_id: str,
    repetitions: int = 3,
) -> QualificationReceipt: ...
```

The runner copies a sealed case into a fresh temporary localdata root for every repetition, invokes the real provider transport, validates through the production output/submission boundary, and stores machine-local evidence under `localdata/.system/state/model-qualification/`. It stops native-reasoning progression at the first fully qualified setting unless comparison mode is explicitly requested.

Status rules are deterministic: any hard governance failure is `FAILED`; mixed repetitions are `UNRELIABLE`; all case/repetition assertions passing is `QUALIFIED`. The reconciler marks mismatched evidence `STALE` and never edits old receipts.

Pytest uses fake provider responses only. It must prove all status transitions, tamper detection, suite hashing, one-item OL isolation, and absence of provider calls during schema/package/hardening validation.

**Step 4: Add controlled seed promotion.**

`model_evaluation.py promote-receipts` accepts only fully reconciled `QUALIFIED` local receipts and writes a deterministic candidate seed file. Promotion requires an explicit destination argument; it never overwrites Core policy automatically. Review and add the accepted seed change in a later source-freeze task.

**Step 5: Verify and commit.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/build_model_evaluation_cases.py --verify
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_model_evaluation.py system/tests/test_skill_routing_policy.py system/tests/test_schema_validation.py system/tests/test_package.py
git add app/system/config app/system/evaluations app/system/tools/build_model_evaluation_cases.py app/system/src/sage app/system/tests
git commit -m "feat: add sealed skill route qualification harness"
```

## Task 5: Route every governed runtime attempt by manifest Skill

**Files:**

- Modify `system/src/sage/llm_tasks.py`.
- Modify `system/config/schemas/llm-execution-receipt.schema.yml`.
- Modify `system/src/sage/schema_validation.py`.
- Modify `system/src/sage/report_translation.py`.
- Modify `system/src/sage/task_retry.py` if receipt preservation needs the new fields.
- Modify `system/tests/test_llm_harness.py`.
- Modify `system/tests/test_report_translation.py`.
- Modify `system/tests/test_rc_block_and_job_cleanup.py`.

**Step 1: Write failing operational-route tests.**

Cover automatic routing by exact `manifest["skill_id"]`; missing/mismatched Skill identity; stale/unavailable/unqualified routes rejected before prompt execution; exact override acceptance/rejection; dry-run route resolution without evidence transmission; attempt-specific receipts; and no direct `--provider`, `--model`, `--reasoning`, or `--policy-override` bypass.

**Step 2: Replace runtime selection.**

`execute_task()` loads and verifies the registered Skill before assembling the provider prompt, probes enabled providers without task evidence, and calls `resolve_skill_route()`. Provider flags are removed from ordinary operational commands; the evaluation command is the only unqualified path.

Bump the receipt schema and add:

```json
{
  "skill_id": "saw-rtc",
  "route_id": "<canonical-route-sha256>",
  "routing_mode": "AUTOMATIC",
  "qualification_status": "RECOMMENDED",
  "qualification_evidence_sha256": "...",
  "routing_policy_version": "alpha1-1",
  "provider_runtime_version": "...",
  "model_identity_strength": "ALIASED",
  "capability_fingerprint": "..."
}
```

Retain legacy receipt reading and the existing phase-level reasoning list. Each retry writes its own route evidence.

**Step 3: Route secondary rendering from source receipts.**

Project the originating item route into report data. `report_translation.py` uses that exact route for one finding/event only, preserves `ASSISTIVE_TRANSLATION_ONLY`, and includes the route in its cache key/receipt. If the route is absent, stale, or unavailable, emit the existing degraded canonical report without choosing another route. Never combine items or reuse provider conversation state.

**Step 4: Verify and commit.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_llm_harness.py system/tests/test_report_translation.py system/tests/test_rc_block_and_job_cleanup.py
git add app/system/src/sage app/system/config/schemas app/system/tests
git commit -m "feat: bind governed task attempts to qualified skill routes"
```

## Task 6: Carry actual route evidence through submission, aggregation, and reports

**Files:**

- Modify `system/src/sage/act_tasks.py`.
- Modify `system/src/sage/plan_continuation.py`.
- Modify `system/src/sage/act_outputs.py`.
- Modify `system/src/sage/stc_reporting.py`.
- Modify `system/src/sage/rewrite_risk.py` so `render_rewrite_challenge_report()` uses the shared execution renderer.
- Modify the BIC validation/publication branches in `system/src/sage/act_tasks.py` so inspect, rewrite, and self-check submission data retain the same execution projection.
- Modify `system/tests/test_report_dynamic_naming.py`.
- Modify `system/tests/test_stc.py` and `system/tests/test_stc_task.py`.
- Modify `system/tests/test_project_grammar_convergence.py`.
- Add focused route-provenance cases to the BIC/SAW report tests.

**Step 1: Write failing provenance tests.**

Require submission to load the sibling `validation/llm-execution-receipt.json`, verify its task/output hashes, and copy a normalized immutable `execution_route` projection. Reject a receipt for another task or output. Aggregation must group distinct routes by exact identity and count tasks without losing attempt or override information.

**Step 2: Implement one shared projection and renderer.**

Add helpers in `act_outputs.py` (or a focused `execution_reporting.py` if imports would cycle):

```python
def execution_route_from_receipt(task_root: Path, *, task_id: str, output_hashes: Mapping[str, str]) -> dict[str, Any]: ...
def aggregate_execution_routes(results: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]: ...
def render_execution_section(routes: Sequence[Mapping[str, Any]]) -> list[str]: ...
```

Single-route reports use aligned fields; multi-route reports use `SKILL | PROVIDER | MODEL | REASONING | MODE | TASKS`. Machine JSON retains receipt path, phase reasoning, provider version, qualification evidence, route ID, and attempt identity.

Report composition remains deterministic Python and is excluded from handoff/token measurement. Preserve existing RTC/STC report IDs and names such as `JUD_001_RTC_ACTION-REPORT.md` and `JUD_001_STC_ACTION-REPORT.md`.

**Step 3: Verify and commit.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_report_dynamic_naming.py system/tests/test_stc.py system/tests/test_stc_task.py system/tests/test_project_grammar_convergence.py system/tests/test_dev8_governance.py
git add app/system/src/sage app/system/tests
git commit -m "feat: report exact skill execution routes"
```

## Task 7: Replace normal model selection UI with provider and Skill routing views

**Files:**

- Modify `system/src/sage/model_service.py`.
- Modify `system/src/sage/cli.py`.
- Modify `system/src/sage/menu.py`.
- Modify `system/src/sage/tui.py` only where it exposes the same configuration/status data.
- Modify `system/src/sage/human_output.py` and menu catalog files used by localization.
- Modify `system/tests/test_menu_projects.py`.
- Modify `system/tests/test_operator_ux.py`.
- Modify `system/tests/test_menu_localization.py`.
- Modify `system/tests/test_command_contract.py`.

**Step 1: Write failing menu/CLI contract tests.**

Assert that normal Configure AI offers provider connections, available provider models, Skill routing recommendations, Advanced routing override, Local AI, and connection check. Costly route evaluation remains maintainer CLI tooling. The menu must not offer ordinary `Change model` or `Change reasoning` actions.

Assert compact Job displays:

```text
SAW JOB - SAW_ukrNPUv1-usNASB
WIP                          ukrNPUv1
REFERENCE                    usNASB
Active Run                   NONE
AI Routing                   AUTOMATIC

SKILL   PROVIDER   MODEL         REASONING   STATUS
RTC     CODEX      gpt-5.6-sol   medium      RECOMMENDED
```

For active Runs, display actual current-attempt receipt data when present; otherwise label it `Current recommendation`. BIC displays Inspect/Rewrite/Self-check rows. Keep existing menu grouping and no redundant headings.

**Step 2: Implement provider-only configuration.**

Available Models is informational. Skill Recommendations shows independent Availability and Qualification. Advanced Override requires confirmation and displays qualified Skill coverage. Evaluate Model runs only sealed cases and clearly warns that Job data is not used.

Replace ordinary CLI selection with `model override set|clear|status` and `model evaluate`; retain provider connect/status/refresh/catalog. Legacy selection flags return a migration error explaining the advanced override.

**Step 3: Verify localization and commit.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_menu_projects.py system/tests/test_operator_ux.py system/tests/test_menu_localization.py system/tests/test_command_contract.py
git add app/system/src/sage app/system/tests
git commit -m "feat: show provider and skill routing in operator UI"
```

## Task 8: Reconcile Core documentation and packaging

**Files:**

- Modify `docs/OPERATOR-GUIDE.md`.
- Modify `docs/BIC-CHEAT-SHEET.md` and `docs/SAW-CHEAT-SHEET.md`.
- Modify `docs/advanced/models-and-ai/MODEL-SELECTION-AND-REASONING.md`.
- Modify `docs/advanced/models-and-ai/MODEL-HANDOFF-OPTIMIZATION.md`.
- Modify `docs/advanced/models-and-ai/SKILL-ROUTING-AND-MODEL-QUALIFICATION.md` from proposed design to implemented contract.
- Modify `docs/advanced/release/HANDOVER.md`, `IMPLEMENTATION-REPORT.md`, `TEST-AND-VALIDATION-REPORT.md`, `RELEASE-GATES.md`, and `VANILLA-INSTALL-MANIFEST.md`.
- Modify `docs/advanced/architecture/PROJECT-TREE.md` and `FILE-NAMING-AND-SERIALIZATION.md`.
- Modify documentation-contract tests where exact inventory text is intentionally changed.

**Step 1: Update docs after behavior is green.**

Document provider-only Setup, exact Skill routing, native reasoning labels, advanced override, live evaluation, new state paths, route failure codes, report fields, settings migration, and the fact that deterministic Python work has no model tokenization.

Mark Codex as the only enabled governed provider in Alpha1 while retaining the provider-neutral adapter boundary. Keep Ollama `ASSISTIVE_ONLY`.

**Step 2: Verify clean distribution contracts.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider system/tests/test_documentation_contracts.py system/tests/test_package.py system/tests/test_schema_validation.py
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/validate_package.py .
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/deep_audit.py . --mode source
git add app/docs app/system/tests
git commit -m "docs: document automatic skill-qualified routing"
```

## Task 9: Automated regression and fresh exact-source hardening

**Step 1: Run the complete deterministic suite from the test runtime.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider
```

Expected: every discovered module scheduled normally; zero failures. Provider qualification calls are forbidden in pytest.

**Step 2: Run schema, package, deep-audit, and cleanliness checks.**

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/validate_schemas.py .
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/validate_package.py .
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/deep_audit.py . --mode source
git status --short
```

Remove only generated test caches allowed by the repository maintenance contract; do not delete Operator inputs, Jobs, reports, or work data.

**Step 3: Run four isolated hardening shards and formal combine.**

Use `env -u SAGE_DATA_HOME` with the test runtime, a new qualification directory, the exact current governed source hash, four shards, and the existing formal-combine command. Require:

- all shards PASS;
- every discovered test module scheduled exactly once;
- zero errors and zero warnings;
- schema/package/deep audit PASS;
- identical source hash before and after.

```bash
cd app
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/hardening.py --shard-count 4 --shard-index 0 --output skill-routing-alpha1-final/hardening-shard-00.json
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/hardening.py --shard-count 4 --shard-index 1 --output skill-routing-alpha1-final/hardening-shard-01.json
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/hardening.py --shard-count 4 --shard-index 2 --output skill-routing-alpha1-final/hardening-shard-02.json
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/hardening.py --shard-count 4 --shard-index 3 --output skill-routing-alpha1-final/hardening-shard-03.json
PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/hardening.py --combine ../localdata/.system/diagnostics/qualification/skill-routing-alpha1-final/hardening-shard-00.json ../localdata/.system/diagnostics/qualification/skill-routing-alpha1-final/hardening-shard-01.json ../localdata/.system/diagnostics/qualification/skill-routing-alpha1-final/hardening-shard-02.json ../localdata/.system/diagnostics/qualification/skill-routing-alpha1-final/hardening-shard-03.json --output skill-routing-alpha1-final/hardening-combined.json
```

Record the combined receipt path and SHA-256. This supersedes the pre-implementation hardening receipt.

## Task 10: Controlled live qualification, seed freeze, and Operator handoff

**Step 1: Run controlled live evaluation—never pytest—against enabled Alpha providers.**

For each available Codex model and each of the seven Skills, query current native reasoning options, evaluate lowest to highest with three repetitions of every case in that Skill's sealed inventory, and stop at the first qualifying setting unless comparison was explicitly requested. Preserve every local receipt, including `FAILED` and `UNRELIABLE` outcomes.

Do not use live Job/Project data. Do not run multiple OL items or secondary rendering items in one request.

**Step 2: Review and promote exact accepted receipts.**

Generate a candidate `model-qualification-seeds.json`, inspect the exact Skill/suite/capability/policy hashes, confirm one deterministic recommendation or a visible blocked state for each Skill, then commit only reviewed evidence:

```bash
git add app/system/config/model-qualification-seeds.json
git commit -m "chore: seed alpha1 qualified skill routes"
```

Because this changes governed source, rerun Task 9 hardening against the new exact hash.

**Step 3: Hand off for Operator testing.**

Operator acceptance must cover:

- provider-only Setup and live catalog refresh;
- Skill recommendation table and unavailable/unassessed states;
- automatic RTC, STC, Targeted Check, OL, and BIC routes;
- continue-run/retry with per-attempt route receipts;
- exact one-item OL and secondary-render isolation;
- audited override coverage, fail-closed mismatch, and restore-to-automatic;
- truthful active Job route display and final report Execution section;
- legacy settings migration without historical-receipt changes;
- macOS and Windows clean-install behavior.

Record defects on `alpha/0.02alpha1`, fix test-first, and repeat exact-source hardening after every governed change. Do not merge `main` until the Operator explicitly accepts the Alpha result.

## Plan self-review checklist

- Every current global-selection consumer is covered: `llm_settings.py`, `model_service.py`, `llm_tasks.py`, `report_translation.py`, CLI, menu, and TUI.
- Every registered analytical Skill has one exact policy key and an explicit sealed case inventory.
- Qualification uses production validators and fake-provider tests; models never judge themselves.
- Runtime cannot bypass qualification through direct flags or override state.
- Receipt provenance reaches both BIC and SAW reports without changing deterministic composition ownership.
- Migration preserves provider provisioning and history but not the old global selection.
- No step authorizes destructive localdata cleanup or a merge to `main`.
