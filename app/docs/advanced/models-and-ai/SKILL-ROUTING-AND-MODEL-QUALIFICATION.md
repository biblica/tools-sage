# Skill routing and model qualification

## Status and purpose

This document defines the implemented `v0.02alpha1` contract for selecting an AI execution route.
It replaces the normal Operator-owned global model/reasoning choice with deterministic SAGE
routing by registered analytical Skill. It also retains one guarded global override for controlled
diagnostics and Alpha testing.

The design applies to all seven registered analytical Skills:

- `bic-inspect`
- `bic-rewrite`
- `bic-self-check`
- `saw-rtc`
- `saw-stc`
- `saw-focused-check`
- `saw-original-language-review`

Controller-only planning, validation, aggregation, report composition, and finalization remain
deterministic Python work. They are not model Skills and do not receive model routes.

## Execution-owner assessment

SAGE classifies the owner of a task or subtask before it evaluates any model route. The classifier
is deterministic policy; no model decides whether work should be sent to a model.

| Execution class | Use | Governing rule |
|---|---|---|
| `DETERMINISTIC_PYTHON` | Parsing, validation, slicing, coverage, identity, aggregation, report composition, file naming, token measurement, and state transition | Required whenever Python can produce the reliable result without linguistic or semantic judgment |
| `LOCAL_ASSISTIVE` | Bounded disposable phrasing or administrative assistance | Non-authoritative, safe to omit, no canonical state mutation, and no raw Scripture/OL evidence |
| `GOVERNED_SKILL` | A semantic or linguistic decision that affects a finding, rewrite, adjudication, or other governed result | Requires an available route qualified for the exact registered `skill_id` |

The decision order is:

1. If the result can be computed reliably and verified locally, Python must own it.
2. Python deterministically projects the smallest exact evidence set needed for any residual
   semantic decision; unrelated packets, reports, controller data, and prior items are excluded.
3. If the residual result is non-authoritative, safely disposable, bounded, and contains no
   prohibited evidence, a locally provisioned model may own it under `LOCAL_ASSISTIVE` policy.
4. All remaining semantic work becomes an isolated `GOVERNED_SKILL` task and receives only the
   exact reduced projection.

Handoff reduction must preserve exact authoritative evidence. An unqualified local model cannot
summarize, select, or transform evidence before a governed model receives it. Independent
work units are never combined merely to reduce calls. Original-language adjudication remains exactly
one item per evaluation, and secondary-language report rendering remains exactly one reported item
per evaluation. SAGE does not reuse provider conversation state.

The current Ollama capability remains `ASSISTIVE_ONLY`; it cannot execute BIC/SAW analytical Skills.
A future local model can become a governed route only through the same adapter, authorization, and
per-Skill qualification process as a hosted provider.

Deterministic Python work has no LLM token budget because it has no model handoff. For local or
hosted model work, sizing and transport controls apply only to the material actually routed to that
specific request. Report composition and other locally derived artifacts are never counted as
Scripture handoff merely because their inputs originated in model output.

## Final operator contract

Normal Setup owns provider connection and enablement only. It does not ask the Operator to choose a
model or reasoning level. SAGE discovers the enabled provider's current model catalog and resolves
an available, qualified provider/model/native-reasoning route for the exact `skill_id` when a
governed task is executed.

The normal mode is `AUTOMATIC`. `Configure AI` exposes five distinct concerns:

1. Provider connections
2. Available provider models
3. Skill routing recommendations
4. Advanced routing override
5. Evaluate new or changed models

The available-model view is informational. It shows provider-reported model identity, native
reasoning settings, availability, and per-Skill qualification evidence. It is not a normal model
selection menu.

Provider readiness and Skill readiness are separate. A connected provider can be ready while one
or more Skills have no executable route. Startup may continue when the provider connection is
ready; execution of an unroutable Skill fails closed with `NO_QUALIFIED_SKILL_ROUTE`.

## Route identity

One route is identified by:

- provider ID;
- exact provider-reported model ID or model-version ID;
- provider capability fingerprint;
- provider-native reasoning setting, or `provider-default` when no setting exists;
- registered `skill_id` and adapted Skill SHA-256;
- evaluation-suite ID, version, and SHA-256;
- qualification-policy version.

SAGE does not convert provider controls into a supposedly universal LOW/MEDIUM/HIGH scale.
Operator surfaces display the provider's native reasoning label. An adapter supplies the native
ordering needed to test lower settings before higher settings. A provider that offers no reasoning
control exposes one `provider-default` candidate.

When a provider exposes only a model alias rather than an immutable backend revision, SAGE records
that limitation as `ALIASED`. It uses the provider-reported ID plus the capability fingerprint as
the strongest observable identity and does not invent a hidden version.

## Governed data separation

The routing design separates policy, live state, and evidence:

| Data | Owner | Persistence |
|---|---|---|
| Registered Skill identity and hashes | SAGE Core | `system/config/skills.json` |
| Skill success criteria and route-selection rules | SAGE Core | versioned routing policy and schema |
| Provider adapter capabilities | SAGE Core code | provider-neutral adapter interface |
| Release qualification seeds | SAGE Core | exact hash-bound qualification registry |
| Live provider catalog | machine-local state | `localdata/.system/state/model-catalog/` |
| Measured evaluation receipts | machine-local evidence | `localdata/.system/state/model-qualification/` |
| Provider connection/enablement | Operator setup | `localdata/.system/state/llm-settings.json` |
| Advanced global override | Operator setup | separate auditable local routing override |
| Actual route used | governed task evidence | `llm-execution-receipt.json` and final reports |

Local state cannot weaken Core success criteria. A local evaluation receipt is accepted only when
its Skill hash, suite hash, policy version, route identity, case inventory, and deterministic
validator results all reconcile.

## Skill success contracts

Each registered Skill owns a versioned evaluation contract. The contract names its curated sealed
case suite, exact input authority, expected semantic decisions, deterministic validators, prohibited
behavior, ranking measurements, execution class, evidence projection, and required isolation.
Each Alpha1 suite contains at least:

- one ordinary positive-finding case;
- one valid zero-finding case;
- one adversarial case testing scope, authority, or output-discipline boundaries.

The Alpha1 success boundaries are:

| Skill | Required semantic success | Disqualifying behavior |
|---|---|---|
| `bic-inspect` | Identify every seeded material issue with the expected evidence and severity relationship | Rewrite TARGET, invent evidence, or miss a seeded blocking issue |
| `bic-rewrite` | Resolve every authorized challenge while preserving protected Scripture, markers, and unrelated text | Unauthorized scope change, unresolved approved challenge, or new seeded regression |
| `bic-self-check` | Detect every seeded rewrite regression and return the expected commit/block decision | Approve a seeded blocking regression or alter Scripture |
| `saw-rtc` | Complete exact WIP/REFERENCE coverage, report seeded variances, and defer only qualifying source-text disputes | Missing/extra coverage, ordinary issue wrongly sent to OL, or source-text dispute finalized without required adjudication |
| `saw-stc` | Evaluate every planned WIP/primary-SOURCE coordinate and return the expected correspondence result | Use a REFERENCE dependency, omit analytical completion, or treat non-primary evidence as SOURCE authority |
| `saw-focused-check` | Answer only the sealed focused question with the expected bounded evidence | Expand the question/scope, use OL Scripture, or perform general RTC |
| `saw-original-language-review` | Resolve exactly one sealed OL item against the correct GRK/HEB authority and expected semantic decision | Combine items, use the wrong testament authority, or import unrelated context into the decision |

Each case enumerates its expected finding IDs/categories, allowed equivalence set for narrative
conclusions, required zero-finding state where applicable, and prohibited outputs. A route cannot
compensate for a hard-contract failure with a higher aggregate semantic score.

Every candidate route is run three independent times per case. A route qualifies only when all
three runs of every case:

- produce schema-valid output;
- preserve exact task identity and required coverage;
- use only authorized evidence and writes;
- avoid every Skill-specific prohibited action;
- satisfy the case's expected semantic assertions;
- pass the existing deterministic submission/finalization validators.

A hard governance, authority, schema, identity, or coverage failure produces `FAILED`. A candidate
that passes some repetitions but not all produces `UNRELIABLE`. Semantic thresholds are explicit
per Skill and cannot be supplied or changed by the candidate model. A model may explain its output
inside a test response, but it cannot rate, qualify, or recommend itself.

Evaluation proceeds through each model's provider-native reasoning settings from lowest to highest.
Testing for that model/Skill stops at the first setting that fully qualifies unless an explicit
comparison evaluation is requested. This finds the least reasoning that satisfies the Skill rather
than assuming that greater reasoning is automatically better.

## Qualification and availability state

Availability and qualification are independent dimensions:

| Dimension | Values |
|---|---|
| Availability | `AVAILABLE`, `UNAVAILABLE` |
| Qualification | `RECOMMENDED`, `QUALIFIED`, `UNRELIABLE`, `FAILED`, `UNASSESSED`, `STALE` |
| Routing mode | `AUTOMATIC`, `GLOBAL_OVERRIDE` |

`UNASSESSED` is mandatory for a new model identity, reasoning setting, Skill hash, or evaluation
suite. Older evidence is never inherited. Evidence becomes `STALE` when any bound identity or hash
changes. Exactly one available qualified route is `RECOMMENDED` for each Skill. Other passing routes
remain `QUALIFIED`.

The deterministic recommendation order is:

1. reject unavailable, unqualified, stale, or policy-prohibited candidates;
2. retain only candidates that meet every hard and semantic success criterion;
3. prefer the lowest declared monetary-cost class when provider cost evidence is available;
4. prefer the lowest qualifying provider-native reasoning setting;
5. prefer the higher measured semantic score only when the Skill contract declares the difference
   material;
6. break remaining ties with the release-governed provider/model preference order and stable route
   identity.

The same inputs must always produce the same recommendation. A provider's marketing recommendation
or a model's self-assessment is advisory metadata only and never enters qualification or routing.

## Runtime flow

Each immutable task manifest already carries `skill_id`. Before a provider call, SAGE:

1. loads the registered Skill and verifies its hash;
2. reads the enabled provider set and any active global override;
3. obtains the current provider capability snapshot without asking a model to choose;
4. resolves the route deterministically for that `skill_id`;
5. rejects an unavailable, unqualified, stale, or unsupported route before sending task evidence;
6. executes the sealed task with the resolved model and provider-native reasoning setting;
7. records the exact route, policy/evidence basis, and routing mode in the execution receipt;
8. projects the actual receipt data into Job/Run status and finalized reports.

No route changes task scope, evidence authority, allowed reads/writes, token measurement, output
schema, validation, or finalization. Python remains authoritative wherever deterministic work is
possible.

A retry may create a new provider attempt, but every attempt records its own exact route. SAGE never
rewrites an earlier receipt or describes a later route as though it produced earlier output.

## Advanced global override

The global override is retained under `Configure AI > Advanced routing override`. It is not part of
guided Setup and is never the default.

The Operator selects one exact provider/model/native-reasoning combination. Before confirmation,
SAGE displays the number and identities of registered Skills for which that route is currently
qualified, for example `Qualified Skills 5/7`. The override applies to subsequent provider attempts
only. Already completed attempts and reports remain unchanged.

At task execution, the pinned route must still be available and qualified for the task's exact
`skill_id`. Otherwise SAGE fails closed with `GLOBAL_OVERRIDE_NOT_QUALIFIED_FOR_SKILL`; it does not
silently fall back to automatic routing. Unassessed or failed routes may be exercised only by the
sealed evaluation harness, never on live Job data.

Enabling, changing, or clearing the override creates an auditable local receipt containing the
Operator action, UTC time, exact route, policy version, qualification coverage, and prior mode. One
action restores `AUTOMATIC` routing.

## Operator displays

The SAW Job menu must not place one model in the Job title because different Skills can use different
routes. Its idle state shows current recommendations:

```text
SAW JOB - SAW_ukrNPUv1-usNASB
------------------------------------------------------------------------
WIP                          ukrNPUv1
REFERENCE                    usNASB
Active Run                   NONE
AI Routing                   AUTOMATIC

SKILL       PROVIDER   MODEL          REASONING   STATUS
RTC         CODEX      gpt-5.6-sol    medium      RECOMMENDED
STC         CODEX      gpt-5.6-sol    high        RECOMMENDED
```

The actual native labels come from current qualification evidence; the example does not prescribe
those particular routes. During an active Run, the menu adds the route for the current task or labels
an unresolved route as a current recommendation:

```text
Active Run                   SAW_ukrNPUv1-usNASB-20260829-001
Current Skill                RTC
Execution Route              CODEX | gpt-5.6-sol | medium
Routing Mode                 AUTOMATIC
```

Every final Run report contains an `Execution` section derived from execution receipts. A
single-route report uses aligned fields. A Run with multiple Skills, phases, attempts, or routes uses
a table:

```text
SKILL       PROVIDER   MODEL          REASONING   MODE              TASKS
RTC         CODEX      gpt-5.6-sol    medium      AUTOMATIC         19
STC         CODEX      gpt-5.6-sol    high        GLOBAL_OVERRIDE   1
```

The machine report data retains exact route identity, phase-level reasoning, attempt identity,
qualification status, policy version, evaluation-evidence hash, provider runtime version, and
receipt path. The human report may use compact labels but must never omit that an override was used.

## Migration and compatibility

The Alpha1 settings migration preserves provider connection and non-secret provisioning fields. It
normalizes the old global `model`, `reasoning_effort`, and `selection_mode` fields to automatic Skill
routing unless the Operator explicitly creates a new advanced override. Historical task receipts
remain valid and continue to display their recorded legacy selection mode.

The CLI follows the same boundary:

- provider connect, status, refresh, catalog, recommendations, and evaluation remain available;
- ordinary model/reasoning selection becomes automatic Skill routing;
- an explicit global override moves to an advanced command and creates the same audit receipt as the
  menu;
- direct task flags cannot bypass Skill qualification; qualification experiments use the evaluation
  command and sealed evaluation data.

Future Claude, Grok, Gemini, or other providers implement the same provider-neutral catalog,
capability, execution, and receipt interfaces. Adding an adapter does not enable governed execution.
A provider is routable only after build-policy enablement and exact route qualification for a Skill.

## Failure behavior

Routing failures are explicit and recoverable:

| Reason code | Meaning | Operator action |
|---|---|---|
| `NO_QUALIFIED_SKILL_ROUTE` | No enabled, available route qualifies for the Skill | Connect/evaluate a provider or wait for an available qualified route |
| `SKILL_ROUTE_EVIDENCE_STALE` | Skill, suite, model capability, or policy identity changed | Re-evaluate the route |
| `GLOBAL_OVERRIDE_NOT_QUALIFIED_FOR_SKILL` | The pinned route cannot execute this Skill | Clear/change the override or qualify the route |
| `PROVIDER_ROUTE_UNAVAILABLE` | The previously recommended or pinned route is no longer in the live catalog | Refresh the catalog and resolve again |
| `MODEL_QUALIFICATION_FAILED` | Evaluation hit a hard contract failure | Inspect the evaluation receipt; do not use the route operationally |
| `MODEL_QUALIFICATION_UNRELIABLE` | Repeated evaluation results were inconsistent | Retest after correction/provider change; do not use the route operationally |

Failure to resolve a route occurs before Scripture evidence is sent. Existing retry, BLOCK, and
diagnostic-report semantics remain authoritative after task creation.

## ALPHA1 finalization boundary

The deterministic source implementation covers the contracts below. Alpha1 finalization is complete
only when live exact-route qualification, fresh exact-source hardening, and Operator acceptance also
confirm them:

- every workflow task/subtask has one deterministic execution-owner classification and an explicit
  justification for any model handoff;
- deterministic Python work cannot enter provider routing or token accounting;
- `LOCAL_ASSISTIVE` work is non-authoritative, safely disposable, evidence-restricted, and unable to
  mutate canonical Job/Run/Project state;
- deterministic projection reduces every governed handoff to exact required evidence without
  model-generated preprocessing, while OL adjudication and secondary-language rendering retain
  their required one-item isolation;
- the routing policy is keyed by registered `skill_id`, not ad hoc workflow strings;
- normal Setup manages providers without global model/reasoning choices;
- current Codex catalog discovery maps into the provider-neutral capability contract;
- all seven Skills have versioned evaluation contracts and sealed Alpha1 cases;
- exact model/reasoning/Skill qualification receipts can be generated and reconciled;
- a deterministic recommended route exists for each executable Alpha1 Skill, or the Skill is visibly
  blocked;
- the advanced global override is audited and fails closed per Skill;
- task execution receipts record exact automatic or override routing evidence;
- SAW and BIC Job menus, status surfaces, and final reports display truthful route metadata;
- legacy local settings migrate without changing historical receipts;
- schemas, package validation, deep audit, complete automated tests, and native platform acceptance
  pass from one frozen exact source hash.

Qualification provider calls are not part of the deterministic unit-test suite. Unit tests use fake
provider catalogs and sealed responses. Before source freeze, controlled live qualification creates
the release evidence used to seed the Alpha1 route matrix. Any subsequent Skill, suite, policy, or
governed-source change invalidates that evidence and requires a fresh qualification run.

## Out of scope

Alpha1 does not enable a second governed workflow provider, normalize different providers into a
fictional universal reasoning scale, accept model self-qualification, route deterministic report
composition through an LLM, or allow unqualified routes to process live Job data.
