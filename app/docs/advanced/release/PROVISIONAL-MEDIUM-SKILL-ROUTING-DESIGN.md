# Provisional Medium Skill Routing Design

**Status:** implemented for Alpha Operator testing on `alpha/0.02alpha1`
**Date:** 2026-08-30

## Purpose

SAGE must let an Alpha Operator begin governed BIC/SAW testing when no current model-qualification
data exists. In that exact state, deterministic Python selects provider-native `medium` for the
current Codex provider and labels the route `PROVISIONAL_UNQUALIFIED`. When current exact
qualification data becomes available, automatic routing uses that data instead.

Medium is a bootstrap default, not a qualification claim. The sealed task, evidence, schema,
coverage, authority, write, and finalization validators remain unchanged.

## One manual state plus two automatic substates

Routing follows this state machine:

| State | Selection source | Result |
|---|---|---|
| `USER_OVERRIDE` | Existing audited exact global override | Use the Operator-selected route when it remains available and qualified for the exact Skill |
| `AUTOMATIC / DATA` | Current reconciled exact qualification evidence | Use the deterministic qualified recommendation |
| `AUTOMATIC / NO DATA` | Alpha provisional policy | Use provider-native `medium` and label it `PROVISIONAL_UNQUALIFIED` |

The existing Advanced routing override is the single manual control. SAGE does not create a second
automatic-mode Operator preference. The override remains qualification-only and fails closed for a
Skill it does not cover.

Within automatic routing, current positive data outranks the no-data fallback. Current `FAILED` or
`UNRELIABLE` evidence blocks when no passing route exists. Stale evidence blocks with
`SKILL_ROUTE_EVIDENCE_STALE`; it is not treated as absence. An unavailable qualified route blocks
with `PROVIDER_ROUTE_UNAVAILABLE`.

## True no-data state

No-data means that the exact Skill has no current qualification record for the live capability
snapshot and no stale record indicates changed route identity. An empty reviewed seed inventory and
no matching machine-local qualification receipt produce this state.

An unknown, malformed, stale, failed, unreliable, hidden, unavailable, or policy-prohibited route is
not a no-data candidate.

## Deterministic provisional selection

The no-data model is selected through the release-governed provider/model preference order in
`model-policy.yml`. The capability must be enabled, available, ready, visible, exactly fingerprinted,
and advertise the policy's provider-native default. Current Codex policy maps its no-data default to
the exact native ID `medium` and prohibits administrative-only `none`, `minimal`, and `low` settings.

Future provider adapters must declare their own reviewed provider-native balanced/default mapping.
SAGE never guesses equivalence from labels, cost, latency, marketing metadata, or a model response.

## Alpha boundary

Provisional routing is enabled only when `sage-standard.json` reports release state `ALPHA`. A later
release must ship current qualification evidence or approve a new explicit release policy. The Alpha
fallback does not imply RC or public-production readiness.

## Policy and receipt contract

The release policy declares:

```yaml
provisional_routing:
  enabled_release_states: [ALPHA]
  no_data_qualification_status: PROVISIONAL_UNQUALIFIED
  default_reasoning_by_provider:
    codex: medium
  prohibited_reasoning_by_provider:
    codex: [none, minimal, low]
  known_negative_effect: BLOCK
  stale_evidence_effect: BLOCK
```

Every route records an explicit selection mode:

- `USER_OVERRIDE` for the audited global override;
- `EXACT_SKILL_QUALIFICATION` for automatic/data routing;
- `PROVISIONAL_PROVIDER_DEFAULT` for automatic/no-data routing.

Qualified receipts require `qualification_evidence_sha256`. Provisional receipts must omit that
claim and instead require `routing_basis_sha256`, the exact provider/model/capability/reasoning
identity, `qualification_status: PROVISIONAL_UNQUALIFIED`, and
`selection_mode: PROVISIONAL_PROVIDER_DEFAULT`. Historical schema 2.0 receipts remain readable.

## Runtime and retry flow

Before an RTC/STC Run enters visible `Review portion ...` output, SAGE resolves the exact
current Skill route. A blocking preflight propagates without adding or launching another task. The
attempt boundary resolves the route again immediately before model execution.

A previously blocked Run remains resumable. `CONTINUE RUN` retries the same sealed task selected by
the immutable plan. It does not restart the Run or rewrite a previous attempt. With no current data,
the retry uses Medium provisionally; with newly installed positive data, it uses the qualified route.

## Operator display

Automatic/no-data is displayed truthfully:

```text
SKILL       PROVIDER   MODEL          REASONING   STATUS
RTC         CODEX      gpt-5.6-sol    medium      PROVISIONAL_UNQUALIFIED

Using codex / gpt-5.6-sol / medium [PROVISIONAL_UNQUALIFIED]
```

Automatic/data may display `RECOMMENDED`; a manual route displays routing/selection mode
`USER_OVERRIDE`. SAGE never calls the Medium fallback recommended or qualified without evidence.

## Acceptance criteria

- Empty qualification inventory selects Codex Medium only in Alpha.
- Positive exact data replaces Medium in automatic mode.
- The audited exact Operator override remains the highest-precedence route state.
- Failed, unreliable, stale, unavailable, hidden, and prohibited candidates cannot trigger fallback.
- Receipts and reports use conditional, truthful provenance.
- Route blocks occur before visible SAW work and before task mutation.
- A preserved blocked Run can be dry-run and resumed without creating a replacement Run or task.
