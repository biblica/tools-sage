# Provisional Medium Skill Routing Design

**Status:** approved design awaiting implementation planning  
**Target:** SAGE v0.02alpha1 Operator testing  
**Date:** 2026-08-29

## Purpose

SAGE must let an Alpha Operator begin governed BIC/SAW testing when no model-qualification data has
yet been published or measured. In that exact no-data state, SAGE uses a provider-native balanced
reasoning setting—`medium` for the current Codex provider—as a provisional default. When current
qualification data becomes available, exact per-Skill qualification determines the default instead.

The provisional route is operational but never described as tested, qualified, recommended, or
production-ready. Every attempt remains subject to the existing sealed task, evidence, schema,
coverage, authority, write, and finalization validators.

## Goals

1. Remove `NO_QUALIFIED_SKILL_ROUTE` as the ordinary first-run outcome when a Skill has no current
   qualification evidence at all.
2. Use native `medium` as the current Codex no-data reasoning default.
3. Allow the Operator to change the no-data reasoning preference explicitly.
4. Automatically replace the provisional preference with an exact qualified per-Skill route when
   usable evidence becomes available.
5. Preserve known negative and stale evidence: it must block rather than be bypassed by a provisional
   route.
6. Record the true provisional status in every Operator surface and execution receipt.
7. Resolve route readiness before a Run enters the visible `Working` state.
8. Keep the change provider-neutral without inventing a universal reasoning scale.

## Non-goals

- Medium is not implicitly qualified.
- Higher reasoning is not assumed to be more accurate or safer.
- A candidate model cannot qualify or recommend itself.
- Provisional execution does not weaken task evidence, output, validation, or authority contracts.
- Failed, unreliable, stale, unavailable, or policy-prohibited routes are not made executable.
- Normal Setup does not become a required model-selection wizard.
- No model benchmark runs during Setup, startup, pytest, package validation, or a normal Job.
- This design does not publish qualification evidence or implement the future hosted registry.

## Terminology

### Current qualification data

Evidence returned by the qualification-evidence repository that reconciles to the current provider,
model capability fingerprint, native reasoning ID, registered Skill hash, evaluation-suite hash, and
policy version. Stale evidence remains diagnostically significant but is not current qualification
data.

### No-data state

No current qualification record exists for any available candidate route for the exact Skill, and no
stale evidence indicates that a previously known Skill route changed. An empty Core seed inventory and
no matching machine-local receipt produce this state.

### Provisional route

An enabled and available exact provider/model/native-reasoning route selected only because the Skill is
in the no-data state. Its qualification status is `PROVISIONAL_UNQUALIFIED`. It is permitted for Alpha
Operator testing but carries no qualification claim.

### Bootstrap reasoning preference

The provider-specific native reasoning setting used only for provisional routing. Its default is
`medium` when the provider advertises that exact setting. An Operator may change it explicitly; the
preference never overrides usable positive qualification evidence.

## Routing precedence

For every governed task attempt, Python resolves the route in this order:

1. **Qualified advanced override:** Use the existing exact global override when it is currently
   qualified for the task's Skill. The override remains unable to bypass qualification.
2. **Qualified automatic recommendation:** If one or more current `QUALIFIED` or `RECOMMENDED` routes
   exist, apply the existing deterministic per-Skill recommendation order.
3. **Known adverse or stale evidence:** If the Skill has current `FAILED` or `UNRELIABLE` evidence but
   no passing route, block with the existing specific failure state. If only stale evidence is
   observed, block with `SKILL_ROUTE_EVIDENCE_STALE`.
4. **Operator bootstrap preference:** In a true no-data state, use the Operator's valid provider-native
   bootstrap reasoning preference when one has been explicitly set.
5. **Medium bootstrap default:** Otherwise use provider-native `medium` on the deterministically
   selected available model.
6. **Provider adapter bootstrap default:** If the provider does not advertise an exact `medium`, use
   the adapter's reviewed governed-eligible balanced/default native setting. If no such mapping exists,
   block with `NO_PROVISIONAL_SKILL_ROUTE`.

The same inputs always produce the same route. The model is not prompted to choose its model or
reasoning. Installing a positive exact qualification receipt causes the next attempt to move from
steps 4–6 to step 2 automatically. Removing or invalidating evidence does not rewrite prior receipts.

## Model selection in the no-data state

The bootstrap preference selects reasoning, not the model. Model selection continues to use the
release-governed enabled-provider and model preference order already present in `model-policy.yml`.
The resolver selects the first available capability that:

- is enabled by build policy;
- has a provider-advertised exact identity and capability fingerprint;
- supports the requested bootstrap reasoning setting, or the adapter's allowed bootstrap default;
- is not prohibited for governed Skills;
- is considered only after the Skill satisfies the no-data definition above; and
- can be represented by the provider execution adapter.

Availability, release preference, and a reasoning label do not become qualification evidence. They
only make a no-data provisional candidate deterministic.

For the current Alpha Codex catalog, `medium` is the exact bootstrap reasoning ID. Future provider
adapters retain native identities. They must declare an exact bootstrap mapping when they do not offer
`medium`; SAGE must not guess an equivalent from a display label, pricing, latency, or model response.

## Operator preference

`Configure AI` gains an advanced **Provisional reasoning** action. It is separate from provider
connection and from the qualified global route override.

- Default: `medium` for Codex.
- Allowed values: provider-advertised reasoning settings eligible for governed provisional execution.
- Prohibited values: administrative-only settings or service modes, including native `low` and
  provider-declared Instant variants under the administrative routing policy.
- Scope: the selected provider's no-data fallback only.
- Reset: restore provider bootstrap default.
- Effect: subsequent attempts only; completed attempt receipts remain unchanged.

The preference is stored as a provider-native ID in non-secret Operator settings. Loading a preference
that is no longer advertised or allowed does not silently substitute another value: SAGE reports it
as unavailable and uses the reviewed provider bootstrap default if permitted.

Positive exact qualification data outranks this preference. The Operator can force an exact qualified
route only through the existing advanced global override. A provisional preference cannot force SAGE
to ignore qualification evidence.

## Alpha authority boundary

Provisional execution is permitted only while the build identifies itself as a pre-release Alpha
Operator-testing build. Before an RC or public-production claim, release policy must either:

- ship or obtain current exact qualification evidence for every executable governed Skill; or
- explicitly approve a later release policy that retains provisional execution.

The Alpha receipt and report labels are evidence that the result came from an unqualified route. They
do not change Scripture or source authority, and they do not exempt the result from deterministic
validation. Operator test data remains disposable evidence for proving and improving the workflow.

## Data and schema changes

The model policy gains explicit bootstrap configuration rather than interpreting absence of seeds as
an error:

```yaml
provisional_routing:
  enabled_release_states: [ALPHA]
  no_data_qualification_status: PROVISIONAL_UNQUALIFIED
  default_reasoning_by_provider:
    codex: medium
  known_negative_effect: BLOCK
  stale_evidence_effect: BLOCK
```

Provider settings gain only the optional native preference:

```json
{
  "providers": {
    "codex": {
      "enabled": true,
      "provisional_reasoning_effort": "medium"
    }
  }
}
```

The default may be computed without persisting a file. SAGE persists the field only after an explicit
Operator change. Reset removes the field and restores the implicit provider bootstrap default. Legacy
provider connection settings migrate to the implicit `medium` default and do not create an advanced
route override.

`SkillRoute` and the execution receipt must distinguish qualification evidence from provisional policy
basis. A provisional receipt includes:

- `qualification_status: PROVISIONAL_UNQUALIFIED`;
- `routing_mode: AUTOMATIC`;
- `selection_mode: PROVISIONAL_OPERATOR_PREFERENCE` or `PROVISIONAL_PROVIDER_DEFAULT`;
- exact provider, model, capability fingerprint, and native reasoning ID;
- no qualification-evidence hash;
- the provisional policy version/hash as the routing basis;
- whether the default was implicit or explicitly changed by the Operator.

The receipt schema must require qualification evidence for `RECOMMENDED` and `QUALIFIED`, and require
the provisional policy basis instead for `PROVISIONAL_UNQUALIFIED`. Historical schema 2.0 receipts
remain readable and immutable.

## Runtime and retry flow

Before creating or continuing visible work, SAGE preflights the exact Skill route:

1. determine the Skill from the planned operation;
2. obtain one provider capability snapshot;
3. reconcile qualification and stale evidence;
4. resolve qualified, provisional, or blocked status using the precedence above;
5. display the exact route and status;
6. only then enter `Working on ...` and execute the sealed task.

For multi-Skill plans, preflight every Skill that is unconditionally required before the Run begins.
Conditionally created Skills are checked when their trigger becomes true and before their task is
created or executed.

A previously blocked task remains resumable. With no evidence, **Continue Run** may select the new
provisional route and retry the same sealed task. If qualification data was installed after the block,
Continue instead uses the exact qualified recommendation. It never restarts the Run or rewrites a
prior attempt.

## Operator display

Provisional status must be visible wherever a route is shown:

```text
SKILL       PROVIDER   MODEL          REASONING   STATUS
STC         CODEX      gpt-5.6-sol    medium      PROVISIONAL (NO TEST DATA)
```

The Run header uses the same truthful wording:

```text
Using CODEX / gpt-5.6-sol / medium [PROVISIONAL_UNQUALIFIED]
```

When qualification arrives, the next unexecuted attempt might show:

```text
Using CODEX / gpt-5.6-sol / high [RECOMMENDED]
```

The UI must not call Medium `RECOMMENDED` unless qualification evidence actually recommends it.
Status and diagnostic output distinguish:

- `PROVISIONAL_UNQUALIFIED`: no current test data; Alpha fallback is executable;
- `UNASSESSED`: shown for catalog candidates, not the selected executable fallback;
- `FAILED` or `UNRELIABLE`: tested adverse result; execution blocked without another passing route;
- `STALE`: prior evidence no longer matches; execution blocked;
- `RECOMMENDED` or `QUALIFIED`: exact current passing evidence.

## Failure behavior

| Reason/status | Meaning | Effect |
|---|---|---|
| `PROVISIONAL_UNQUALIFIED` | No current qualification data; governed Alpha fallback selected | Execute and receipt truthfully |
| `NO_PROVISIONAL_SKILL_ROUTE` | No enabled available model exposes an allowed bootstrap setting | Block before `Working` |
| `MODEL_QUALIFICATION_FAILED` | Current data records a hard failure and no route passes | Block; do not fall back |
| `MODEL_QUALIFICATION_UNRELIABLE` | Current repeated results are inconsistent and no route passes | Block; do not fall back |
| `SKILL_ROUTE_EVIDENCE_STALE` | Prior evidence no longer matches the route/Skill/suite/policy | Block; do not fall back |
| `PROVIDER_ROUTE_UNAVAILABLE` | A qualified or selected provider route is unavailable | Re-resolve; use another exact passing route, or provisional only if the Skill truly returns to no-data state |

A provider execution or output-validation failure on a provisional route follows the normal retry and
BLOCK semantics. SAGE never changes reasoning automatically during a retry merely because an attempt
failed; only qualification evidence, an explicit Operator preference change, or provider availability
can change the next route.

## Testing and hardening

Implementation uses test-driven changes with fake provider catalogs and transports. Required tests:

1. Empty Core seeds plus no local receipts select current Codex `medium` with
   `PROVISIONAL_UNQUALIFIED`.
2. An exact `QUALIFIED` route at `high` supersedes provisional Medium for that Skill.
3. A `QUALIFIED` route at `medium` is reported as qualified, not provisional.
4. Current `FAILED` or `UNRELIABLE` evidence with no passing route blocks and never falls back.
5. Stale evidence blocks and does not silently become no-data.
6. An explicit allowed Operator preference changes only the provisional reasoning ID.
7. Positive qualification data supersedes the Operator provisional preference.
8. Reset restores the provider's reviewed bootstrap default.
9. A provider without native `medium` uses only its explicit adapter bootstrap mapping.
10. A provider with neither native Medium nor a reviewed mapping fails with
    `NO_PROVISIONAL_SKILL_ROUTE`.
11. Low, Instant, unavailable, hidden, and policy-prohibited candidates cannot become governed
    provisional routes.
12. The provisional execution receipt contains exact route and policy basis without inventing a
    qualification-evidence hash.
13. Existing qualified and global-override routes retain their current behavior.
14. A blocked SAW task resumes through **Continue Run** without Run recreation after provisional or
    qualified route resolution becomes possible.
15. Route preflight occurs before the visible work-unit status and before Scripture evidence is sent.
16. RC/non-Alpha release policy rejects provisional execution.
17. No live provider evaluation runs from automated tests, normal startup, Setup, or Job execution.

Hardening must cover direct task execution, menu/CLI/TUI parity, legacy settings, corrupted settings,
retry, report provenance, schema validation, package cleanliness, and source deep audit. The full suite
must continue to prove that Python owns task creation, validation, report composition, and state
transition.

## Documentation changes

Implementation must update:

- Skill routing and model qualification policy;
- Model selection and reasoning policy;
- Operator Guide and BIC/SAW cheat sheets;
- Configure AI, Status, Job, Run, retry, and error help;
- release gates, test report, release notes, and handover.

The documentation must state plainly that Medium is an unqualified Alpha bootstrap route when there is
no data, qualification evidence automatically supersedes it, and known negative/stale evidence blocks.
It must not describe provisional results as recommended or production-qualified.

## Implementation boundary

This is one implementation-plan scope: provisional policy/configuration, provider-native bootstrap
mapping, resolver precedence, Operator preference, receipt/schema migration, preflight timing,
Continue Run behavior, UI/docs, regression tests, and hardening. Model evaluation suites and the future
hosted qualification-registry service remain separate systems and are not redesigned here.
