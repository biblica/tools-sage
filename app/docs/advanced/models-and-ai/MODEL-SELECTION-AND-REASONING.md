# SAGE provider and Skill routing policy

## v0.02b1 execution policy

Provider architecture, provider connection, and permission to execute a governed Skill are separate
controls.

| Provider | Adapter/configuration | v0.02b1 governed execution |
|---|---|---|
| Codex | Implemented | Exact qualified routes, plus truthful Medium fallback in every true no-data state |
| Ollama | Optional local admin assistant | Disabled for BIC/RTC/STC |
| Grok | Future adapter slot | Not implemented |
| Gemini | Future adapter slot | Not implemented |

`build_policy.allowed_automated_providers` is effectively `[CODEX]` in v0.02b1. A connected,
available, or provisioned provider is not automatically qualified for a Skill.

No OpenAI API-key, access-token, service-account, direct API, or API-fallback route is supported.
Codex uses the locally installed official CLI with ChatGPT-managed authentication. The normal
connection path is **SAGE Maintenance > Configure AI > Connect OpenAI and ChatGPT**. Direct CLI
equivalents are `./system/bin/sage model connect` on macOS/Linux and
`.\system\bin\sage.cmd model connect` on Windows. The Codex desktop application is not required.

## Provider-only setup

Normal Setup records provider connection and enablement only. It does not ask the Operator to choose
one global model or reasoning level. **Configure AI** exposes:

1. Change provider
2. Available provider models
3. Skill routing recommendations
4. Advanced routing override
5. Evaluate new or changed models
6. Connect OpenAI and ChatGPT
7. Configure Local AI
8. Check LLM connection

Available models are informational. Skill recommendations show availability and qualification
independently for every registered Skill. **Check LLM connection** is the explicit minimal generation
test. Merely opening a Job, reading a recommendation, or changing an override does not submit Job
evidence to a model.

Startup verifies provider installation and authentication without generating analytical output. A
ready provider does not imply that every Skill is ready. In every release state, a true no-data Skill
uses the governed Medium fallback, or the Operator's pinned no-data default when one is set (see
[Operator-pinned no-data default](#operator-pinned-no-data-default)); stale, failed, unreliable,
unsupported, or unavailable states still fail closed before Scripture evidence is sent.

## Exact per-Skill routing

Every governed task manifest carries one registered `skill_id`. SAGE deterministically resolves the
exact route for that Skill. A route binds:

- provider ID;
- provider-reported model ID and capability fingerprint;
- provider-native reasoning ID, or `provider-default` where no control exists;
- Skill ID and adapted Skill SHA-256;
- sealed evaluation-suite ID and SHA-256;
- qualification-policy version.

SAGE does not invent a universal LOW/MEDIUM/HIGH reasoning scale or a cross-provider XHigh ceiling.
Provider-native labels and order are retained. A model, model alias, capability fingerprint,
reasoning option, Skill, suite, or policy change produces `UNASSESSED` or `STALE` evidence until that
exact route is evaluated again.

Automatic routing uses current `RECOMMENDED` or `QUALIFIED` evidence when it exists. In a true
no-data state, the universal policy selects Codex native `medium` and labels it
`PROVISIONAL_UNQUALIFIED`, unless the Operator has pinned a different no-data default (see
[Operator-pinned no-data default](#operator-pinned-no-data-default)); either way the model is not
thereby tested or qualified. The model cannot qualify or
recommend itself: sealed synthetic responses pass through deterministic production validators. Every Skill has
an explicit positive, zero-finding, and adversarial inventory, extended where a Skill has additional semantic boundary criteria; each case is repeated three times. Any hard
contract failure is `FAILED`; inconsistent repetitions are `UNRELIABLE`; all required assertions and
validators passing is `QUALIFIED`.

```sh
./system/bin/sage model refresh --provider codex
./system/bin/sage model list --provider codex
./system/bin/sage model routes
./system/bin/sage model recommend --skill rtc
./system/bin/sage model evaluate --skill rtc --provider codex --model MODEL_ID
./system/bin/sage model evaluate --all-skills --provider codex --all-models
./system/bin/sage model evaluate --skill rtc --provider codex --model MODEL_ID --comparison
./system/bin/sage model test --provider codex
```

Evaluation uses only packaged synthetic cases. For every selected model/Skill, SAGE tests the
provider's advertised reasoning settings in provider order and stops at the first `QUALIFIED`
setting. Most tested settings perform nine isolated attempts. RTC performs fifteen because its five-case suite adds fundamental polarity and participant-identity referral boundaries. `--comparison` explicitly continues through every advertised setting. A provider without a
reasoning control is evaluated once as `provider-default`.

Evaluation must not use Operator Jobs, Projects, reports, or Scripture. It is never run by pytest,
package validation, startup, or a normal Job. Because a full catalog benchmark can take hours and
makes real provider calls, `model evaluate` requires an explicit confirmation naming that cost either
way it is invoked: as maintainer/release CLI tooling, or as the Operator-triggered **Configure AI >
Evaluate new or changed models** menu action, which wraps the same `evaluate_catalog_routes`/
`evaluate_skill_route` machinery. Neither surface is required before a normal Job runs; a true
no-data state still routes through the governed Medium fallback (or the Operator's pinned no-data
default) until qualification evidence exists.
Local receipts become immediately eligible for deterministic routing only while every bound identity
still reconciles. Building a possible Core seed is a separate, explicit review action:

```sh
./system/bin/sage model promote --receipt RECEIPT.json --destination CANDIDATE-SEEDS.json
```

The destination must not already exist. This command accepts only reconciled `QUALIFIED` receipts
and never overwrites `system/config/model-qualification-seeds.json`; human review and a later governed
source change are required for Core promotion.

## Routing precedence

SAGE has two manual override states and two automatic substates:

| State | Selection |
|---|---|
| `USER_OVERRIDE` | Use the existing audited exact override when it remains available and qualified for the Skill |
| `AUTOMATIC / DATA` | Use the deterministic recommendation from current exact qualification data |
| `AUTOMATIC / NO DATA` | Use the Operator's pinned `PROVISIONAL_OVERRIDE` no-data default when one is set and still live, otherwise the release policy's provider-native default (`medium` unless changed) |

Current failed, unreliable, stale, unavailable, hidden, or prohibited routes do not become no-data
fallback candidates, whether the candidate comes from the release policy default or an Operator-pinned
`PROVISIONAL_OVERRIDE`. `USER_OVERRIDE` still takes precedence over both: it requires qualification
evidence and is unaffected by the no-data pin, since the no-data pin only ever applies in a true
no-data state.

## Advanced global override

The optional global override is a diagnostic/pre-release control, not a normal Setup default. It pins one
exact provider/model/capability/reasoning combination. SAGE records an audit receipt when the override
is set, changed, or cleared and displays how many registered Skills currently qualify for that route.

The override never weakens per-Skill qualification. If it is not currently available and qualified
for the task's exact Skill, execution fails with `GLOBAL_OVERRIDE_NOT_QUALIFIED_FOR_SKILL`; SAGE does
not silently fall back.

```sh
./system/bin/sage model override status
./system/bin/sage model override set --provider codex --model MODEL_ID \
  --capability-fingerprint SHA256 --reasoning PROVIDER_REASONING_ID
./system/bin/sage model override clear
```

Legacy normal model/reasoning selection is not an execution surface. Direct `task execute` model,
provider, reasoning, and policy-bypass flags are prohibited.

## Operator-pinned no-data default

The exact global override above only ever helps once qualification evidence exists for that route;
on a fresh install, or before evaluation has run, every Skill resolves through the true no-data state
instead. **Configure AI > Advanced routing override > Set no-data default model/reasoning**
interrogates the live provider catalog -- whatever models and native reasoning levels the provider
currently reports, not a hardcoded model ID -- and lets the Operator pin the pair used by that no-data
fallback for every Skill, replacing the release policy's static `medium` default.

This pin needs no qualification evidence: it only requires the chosen model/reasoning to be live right
now, since it is exactly the fallback used when nothing is qualified. Every resolution re-validates the
pin against the current provider catalog; if the pinned model or reasoning is no longer live, routing
fails closed with `PROVISIONAL_OVERRIDE_NOT_AVAILABLE` rather than silently reverting to the release
default. **Clear no-data default** in the same menu removes the pin and restores the release policy
default. Setting or clearing the pin records an audit receipt, mirroring the exact override's audit
trail.

The no-data pin and the exact `USER_OVERRIDE` above are independent: clearing one never affects the
other, and the exact override always takes precedence once its qualification evidence exists.

```
Configure AI > Advanced routing override
  3. Set no-data default model/reasoning   -- pick a live model, then its native reasoning
  4. Clear no-data default                 -- restore the release policy default
```

## Deterministic ownership and token boundary

Python owns planning, parsing, SFM slicing, scope/coverage projection, token measurement, validation,
aggregation, report composition, report naming, and state transition. These operations are not sent
to an LLM and have no LLM token budget. Only the exact evidence routed to one governed semantic item
is measured against that request's handoff limits.

Original-language adjudication is one item per request. Secondary-language report rendering sends
exactly one reported item per request and inherits the originating item's exact route. SAGE does not combine
items or reuse provider conversation state to reduce calls.

Every new execution receipt records the exact route and selection source. Qualified receipts carry
qualification evidence; provisional receipts carry the policy routing-basis hash and no
qualification-evidence claim. Job/Run displays and
final reports use actual receipt data when available; they never rewrite history using a later
recommendation.

## Local admin assistant

**Configure Local AI** manages the optional Ollama assistant on this workstation. It is
`ASSISTIVE_ONLY`, non-authoritative, safely omittable, evidence-restricted, and cannot execute BIC/RTC/STC
analytical Skills or mutate canonical Job/Run/Project state.

The supported local model and runtime controls remain defined by the governed Ollama policy. A future
local or hosted provider becomes a governed route only after an adapter is enabled and the exact
model/reasoning route qualifies independently for each Skill.

## State and evidence

| Data | Location |
|---|---|
| Provider connection/enablement | `localdata/.system/state/llm-settings.json` |
| Audited exact override | `localdata/.system/config/model-routing-override.json` |
| Exact override receipts | `localdata/.system/state/model-routing-overrides/` |
| Audited no-data default override | `localdata/.system/config/model-provisional-override.json` |
| No-data override receipts | `localdata/.system/state/model-provisional-overrides/` |
| Local qualification receipts | `localdata/.system/state/model-qualification/` |
| Actual task route | task `validation/llm-execution-receipt.json` |
| Core Skill criteria and seeds | `system/config/skill-evaluation-contracts.json`, `model-qualification-seeds.json` |

Historical receipts remain readable. Legacy provider settings preserve connection/provisioning state
but do not silently become an advanced route override.

## Model-release language competency

Language-competency evidence remains separate from Skill qualification. A concrete model release or
language without trusted versioned evidence remains `UNASSESSED`; SAGE never asks a model to rate
itself. See `MODEL-LANGUAGE-COMPETENCY.md`.
