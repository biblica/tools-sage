# Administrative AI Routing Design

**Status:** approved design awaiting implementation planning  
**Target:** SAGE v0.02alpha1 finalization  
**Date:** 2026-08-29

## Purpose

SAGE must use deterministic Python whenever the required result can be produced reliably without
model judgment. When an administrative presentation task genuinely benefits from a model, SAGE
should prefer a qualified Local AI route and use a qualified hosted administrative route only when
the Operator has explicitly enabled that fallback.

This design refines the existing `local_assistive` boundary. It does not create a second workflow
engine and does not weaken the governed BIC/RTC/STC Skill boundary. It also formalizes the rule that
latency-optimized **Instant** models or modes and provider-native **low** reasoning settings are
administrative-only and can never execute a SAGE Job Skill.

## Goals

1. Keep Python authoritative for all computable results, validation, writes, and state changes.
2. Permit narrowly scoped AI assistance for administrative presentation without granting workflow
   authority.
3. Prefer qualified Local AI for eligible administrative assistance.
4. Allow hosted administrative fallback only by explicit Operator opt-in.
5. Prohibit every Instant model/mode and provider-native low reasoning setting from governed BIC/RTC/STC
   execution.
6. Reuse the provider-neutral catalog, qualification-evidence repository, and receipt architecture.
7. Let normal Operators begin work within minutes without running a local model benchmark.
8. Keep the qualification-evidence source modular so a signed hosted registry can later replace or
   supplement local reviewed evidence through the existing repository boundary.

## Non-goals

- No new BIC, RTC, or STC analytical Skill is introduced.
- No Local AI model is promoted to governed Scripture authority.
- No universal LOW/MEDIUM/HIGH reasoning scale is invented.
- No route is qualified by asking a model to rate itself.
- No normal startup, Setup, Job, pytest, or package-validation flow runs a live catalog benchmark.
- No AI response may directly update canonical Project, Job, Run, report, or Scripture state.
- No direct API-key or service-account provider path is introduced.

## Terms

### Administrative assistance

A non-authoritative transformation of a typed, controller-produced administrative fact view. Its
output may improve wording or summarization, but it cannot determine facts, approve recovery, make a
workflow judgment, or change state.

### Governed Skill

A registered BIC/RTC/STC Skill whose model result is part of governed Job execution. It requires an exact
qualified provider/model/capability/reasoning route and the full existing task, evidence, submission,
and validation boundaries.

### Instant

An entire provider model or service mode that the provider explicitly presents as primarily
optimized for minimum response latency, with reduced deliberation or consistency relative to its
standard service. SAGE treats such a route as `ADMINISTRATIVE_ONLY`.

SAGE must not infer Instant status from marketing adjectives, model size, price, speed observed by
SAGE, or substrings such as `fast`, `mini`, or `instant`. The provider adapter must derive the status
from provider metadata or a reviewed Core mapping. An unknown model or mode remains `UNASSESSED`.

### Low reasoning

An exact provider-native reasoning setting that the provider adapter classifies as
`ADMINISTRATIVE_ONLY`. The label is not normalized across providers. For the Codex adapter, the exact
native `low` setting is administrative-only. Other providers require their own explicit reviewed
mapping; SAGE must not classify a setting by approximate name matching.

## Authority model

The current execution ownership classes remain the authority source:

| Execution area | Authority | Permitted result |
|---|---|---|
| `deterministic_python` | Authoritative controller | Facts, validation, rendering, writes, and state transitions |
| `local_assistive` deterministic template | Non-authoritative presentation | Reproducible explanation or compact summary derived from typed facts |
| Qualified Local AI administrative route | Non-authoritative presentation | Optional wording or summarization of the same typed facts |
| Qualified hosted administrative route | Non-authoritative presentation | Explicitly enabled fallback wording or summarization |
| `governed_skills` | Governed semantic execution | Exact qualified BIC/RTC/STC Skill output subject to production validators |

Administrative AI cannot:

- execute or substitute for a governed Skill;
- decide whether a Run, task, recovery action, or report is valid;
- create facts, diagnoses, action choices, findings, or Scripture interpretations;
- mutate canonical data or become an input to canonical state transition;
- qualify itself or another route;
- silently escalate from Local AI to a hosted provider.

## Deterministic-first decision flow

Every administrative capability starts from a typed fact view produced and validated by Python.
Python then applies this decision in order:

1. **Deterministic sufficiency:** If a deterministic template fully satisfies the capability contract,
   return it and make no model call.
2. **Qualified Local AI:** If the capability contract explicitly permits model presentation and the
   deterministic result is intentionally only a fallback, use an enabled, available, exact qualified
   Local AI route.
3. **Qualified hosted administration:** If Local AI is unavailable or not qualified, use a qualified
   hosted administrative route only when the Operator has enabled hosted administrative fallback.
4. **Omit assistance:** If no permitted AI route succeeds, retain the deterministic result or omit the
   optional AI presentation. The governing operation continues unchanged.

This is a policy decision, not a free-form model-routing prompt. Capability policy declares whether
deterministic output is sufficient and whether optional model presentation is allowed. The model
does not choose its route or decide whether it is needed.

The initial capability policy is:

| Administrative capability | Deterministic result | Optional AI presentation | Canonical effect |
|---|---|---|---|
| `status-explanation` | Required and sufficient | Prohibited initially | None |
| `approved-action-explanation` | Required and sufficient | Prohibited initially | None |
| `diagnostic-explanation` | Required fallback | Local preferred; hosted opt-in fallback | None |
| `report-executive-summary` | Required compact fallback | Local preferred; hosted opt-in fallback | Separate assistive artifact only |

Adding AI presentation to another administrative capability requires an explicit policy and test
change. Generic administrative prompting is prohibited.

## Route metadata and provider adapters

Provider adapters expose eligibility as data. Core policy consumes it; runtime code must not infer it
from display names.

Each model/service capability exposes:

```yaml
route_eligibility:
  administrative_assistive: true
  governed_skills: false
restriction_reason: PROVIDER_LATENCY_OPTIMIZED_VARIANT
restriction_source: PROVIDER_DECLARED
```

Each provider-native reasoning option exposes equivalent eligibility. A standard model may therefore
allow governed execution at one exact qualified native reasoning setting while its low setting remains
administrative-only. An entire Instant model/mode has `governed_skills: false` for every reasoning
setting.

Allowed restriction sources are:

- `PROVIDER_DECLARED`: stable provider catalog metadata;
- `CORE_REVIEWED_ADAPTER`: a reviewed provider-specific mapping shipped by SAGE.

Absence of either source yields `UNASSESSED`; it never yields governed eligibility. Provider adapters
for Codex, Claude, Grok, or later providers implement the same interface but retain their native model
and reasoning identities.

After authority and exact qualification filtering, SAGE chooses an administrative recommendation
deterministically: Local AI before hosted administration, `RECOMMENDED` before `QUALIFIED`, then the
adapter's reviewed stable preference order, followed by exact route ID as the final tie-break. Cost or
observed speed may inform a reviewed adapter preference but can never outrank correctness or create
eligibility. A provider/model response cannot modify this order.

The advanced global governed-route override remains separate. It cannot convert an administrative
route into a governed route, bypass a restriction, or enable hosted administrative fallback.

## Administrative Skill qualification

Administrative capabilities use their own lightweight, sealed success contracts. They do not reuse
or dilute governed Skill qualification. An exact administrative route binds:

- provider and provider-reported model identity;
- capability fingerprint;
- provider-native reasoning or service-mode identity;
- administrative capability ID and contract hash;
- evaluation-suite hash and policy version;
- qualification verdict and evidence hash.

The deterministic evaluator, never the candidate model, assigns the verdict. Every administrative
case must prove:

1. controller facts, identifiers, coordinates, and action tokens are preserved exactly;
2. no diagnosis, fact, action, recommendation, or status is invented;
3. the response satisfies the capability schema and output bound;
4. prohibited evidence never crosses the request boundary;
5. the request is stateless and independent of previous model conversation;
6. failure produces no canonical effect;
7. observed latency is recorded but never compensates for a correctness failure.

The verdict vocabulary remains `RECOMMENDED`, `QUALIFIED`, `UNASSESSED`, `FAILED`, `UNRELIABLE`, and
`STALE`. Runtime accepts only exact reconciled `RECOMMENDED` or `QUALIFIED` administrative evidence.

Normal Operators do not run this suite. Reviewed Core seeds and, later, locally verified signed
registry records provide immediately usable recommendations. Maintainers may run explicit evaluation
for new, changed, unavailable, or disputed routes. If a Local AI route has no trusted evidence, SAGE
uses the deterministic fallback rather than delaying Setup.

## Evidence boundary

All administrative routes, local or hosted, receive the same capability-specific typed projection.
The boundary rejects:

- raw Scripture, USFM, USJ, or original-language text;
- ACT content, Skill bodies, governed evidence packets, or unrestricted Job/report content;
- canonical candidate forms or evidence prose;
- credentials, authentication material, secrets, or tokens;
- arbitrary filesystem paths;
- fields outside the capability allowlist.

Identifiers, Scripture coordinates, controller reason codes, approved action tokens, bounded risk or
status labels, and compact canonical report metadata may be allowed when the capability contract
requires them. The request contains one capability item and has no provider conversation history.

## Output, receipts, and failure handling

Python validates every administrative response before display or artifact creation. A valid response
is labeled `NON_AUTHORITATIVE_ASSISTIVE` and records:

- administrative capability ID;
- route type: deterministic, local AI, or hosted administration;
- exact provider/model/native reasoning or service mode when AI was used;
- qualification-evidence identity;
- normalized input-view SHA-256 and output SHA-256;
- UTC time and validation verdict;
- whether hosted fallback was enabled and used.

Receipts remain administrative state under `localdata/.system/state/local-ai-receipts/`. The receipt
schema records the route type and provider-neutral route identity even though the compatibility path
retains its existing name. They do not modify canonical reports.

`report-executive-summary` writes only a separate `*_ASSISTIVE-SUMMARY.json` artifact bound to the
canonical report SHA-256. Diagnostic and status assistance is display-only unless an explicitly
defined administrative receipt is required.

Provider timeout, malformed output, missing qualification, prohibited evidence, unavailable Local AI,
or declined hosted fallback produces `OMIT_ASSISTANCE`. SAGE shows the deterministic fallback where one
exists, records a concise administrative reason, and leaves the governing Job/Run result unchanged.

## Operator controls and presentation

Normal Setup remains provider-only and must not ask the Operator to select one universal model or
reasoning level. Administrative controls are separate:

- enable or disable Local AI;
- show the fixed or recommended qualified local administrative route;
- enable or disable hosted administrative fallback, default `OFF`;
- show the exact route and `LOCAL`, `HOSTED`, or `DETERMINISTIC` provenance when assistance is used.

Enabling hosted fallback is durable consent for automatic use on the two allowlisted administrative
capabilities. It is never implied by connecting a hosted governed provider. SAGE must display the
setting in Configure AI and Status, and every use must be receipted. Turning it off takes effect before
the next administrative request.

Governed Job and Run displays continue to show actual Skill execution receipts. An Instant or low
administrative route must never appear as the executor of a governed Job task. Assistive model metadata
belongs only on the assistive display/artifact and its receipt.

## Modular service boundary

Administrative routing consumes qualification through a repository protocol rather than reading one
storage format directly. The initial implementation may use reviewed Core seeds and machine-local
receipts. A future hosted qualification-registry client can implement the same interface and return
signed immutable records.

SAGE verifies registry signatures, exact identities, hashes, expiry/review state, and policy version
locally. It caches an approved last-known registry for offline use and fails closed on mismatch. The
external service supplies evidence records only; it never receives Job data or controls runtime route
selection.

## Configuration evolution

`execution-ownership.yml` remains the policy root. The implementation will extend the existing
`local_assistive` records with explicit deterministic sufficiency, AI-presentation permission, route
preference, and failure effect. Provider catalog schemas will gain explicit route-eligibility and
restriction-source fields.

New configuration defaults must preserve current behavior:

- deterministic administrative output remains available;
- Local AI does not become required;
- hosted administrative fallback is `OFF`;
- existing governed routes and qualification receipts remain separate;
- an unknown or legacy model capability is not silently made eligible.

Schema migration is deterministic and atomic. Legacy settings may preserve Local AI enablement but
cannot imply hosted fallback consent.

## Testing and release gates

Implementation must use test-driven changes and fake provider transports. Automated tests must cover:

- deterministic-first routing and zero provider calls for sufficient capabilities;
- Local AI preference for each AI-permitted administrative capability;
- explicit hosted-fallback consent and no silent escalation;
- `OMIT_ASSISTANCE` behavior for unavailable, failed, invalid, or unqualified routes;
- strict evidence-field allowlists and one-item stateless requests;
- exact fact, ID, coordinate, and action-token preservation;
- separate assistive artifacts and unchanged canonical report bytes;
- receipt accuracy for deterministic, local, and hosted outcomes;
- Codex native `low` rejected for every governed Skill;
- every declared Instant model/mode rejected for every governed Skill;
- standard exact routes remaining eligible only through existing governed qualification;
- unknown provider metadata yielding `UNASSESSED`;
- provider-neutral fake catalogs representing Codex, Claude-like, Grok-like, and no-reasoning-control
  providers;
- no live model or registry calls from pytest, startup, package validation, or normal Job execution.

Release hardening must prove that no route-classification bypass exists through CLI flags, advanced
override state, legacy settings, task retry, or receipt loading. Operator acceptance must confirm that
a clean installation reaches usable deterministic operation within minutes without local benchmarking.

## Documentation deliverables

Implementation must update the Operator Guide, model-routing policy, Local AI guide, Help/status text,
and install documentation. Installation documentation must distinguish Operator and developer needs:

| Item | Operator release ZIP | Git-based Operator install | Developer/test workstation |
|---|---|---|---|
| Git | Not required | Required to clone/update | Required |
| System Python | Not required; SAGE installs its managed pinned runtime | Not required | CPython 3.12 recommended for development tooling |
| VS Code | Optional | Optional | Recommended, not required |
| Internet | Required for first bootstrap/provider sign-in unless artifacts are pre-provisioned | Required to clone and normally bootstrap/sign in | Required for clone and provider-dependent work |
| ChatGPT sign-in | Required before governed Codex work | Required before governed Codex work | Required only for live Codex work |
| Paratext/PTLite Projects root | Required for real Project workflows, not launcher bootstrap | Same | Required only for real Project integration tests |

The docs must not state that a separate system Python installation is an Operator prerequisite. The
managed-runtime bootstrap remains part of the product contract.

## Implementation boundary

This specification is one implementation-plan scope: policy/schema changes, provider metadata,
administrative route resolution, validation/receipts, UI/docs, migration, and hardening. The hosted
qualification-registry service itself remains future work; this scope only preserves and tests the
replaceable repository interface needed to adopt it later.
