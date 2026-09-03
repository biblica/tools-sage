# SAW review portions and OL referral admission design

> Historical record: this document preserves the pre-RTC workflow identity used when the design was implemented. Current operator and runtime terminology is RTC/STC; `SAW` names below refer only to sealed legacy artifacts.

Status: implemented and regression-verified on `alpha/0.02alpha1`; Operator field acceptance remains pending.

## Purpose

Separate the stable portions of an Operator-approved SAW review range from
stage-specific check cases, and prevent Reference Text Comparison (RTC) from
creating excessive original-language (OL) referrals for ordinary translation
differences.

The design preserves the existing deterministic planner, immutable Run/task
boundaries, and one-request-per-selective-OL-task isolation. It changes the
Operator vocabulary and introduces a structured, fail-closed referral admission
contract for newly planned RTC Runs.

## Problems

### Ambiguous progress units

The pre-Run screen counts deterministic scope-covering work units. Composite
RTC stages later reuse `work unit n/m` for structural cases and selective OL
cases. The denominator therefore changes meaning during one Run. An approved
19-part review can later display `20/97` without explaining that 97 is a count
of stage cases rather than approved review partitions.

### Excessive OL referrals

The meaning-stage prompt currently asks the provider to defer every material
source-dependent variance. Python validates request identity, scope, and routed
evidence, but does not require a narrow fundamental-conflict classification or
structured proof that non-OL evidence cannot resolve the question. A model can
therefore produce many technically valid but analytically unnecessary
referrals.

## Canonical boundaries and vocabulary

The following boundaries are distinct:

| Boundary | Meaning | Stability | Operator label |
|---|---|---|---|
| Run scope | One contiguous scope, or ordered non-overlapping semicolon-separated portions from one book | Immutable for the Run | `Review range` |
| Approved plan unit | One deterministic scope-covering partition approved before Run creation | Immutable for the Run | `Review portion` |
| Stage case | One structural, meaning, or selective-source task within a stage | May differ by stage | `<Stage> check` |
| Machine work unit | Existing internal task/coverage identity | Stable machine contract | Not shown as the default Operator label |

`parse_scope()` remains the contiguous processing-range parser.
`parse_analysis_scope()` validates RTC/STC Run input and accepts same-book
semicolon-separated portions such as `1CH 5-6; 24`. After parsing, the controller expands each portion
to canonical atomic coordinates and partitions those coordinates into approved
review portions exactly as it does now.

Each stage case receives a deterministic parent review-portion identity from
the controller. Provider output never chooses or changes that parent.

Approved-plan entries expose `review_portion_index` and
`review_portion_total`. Stage-plan entries and continuation responses expose
`parent_review_portion_id`, `stage_case_index`, and `stage_case_total`. A stage
case must be wholly contained in one approved review portion; otherwise the
controller blocks with `SAW_STAGE_CASE_PORTION_MISMATCH` before model
execution. A VRS structural candidate is report-only metadata rather than one
indivisible stage case: when its atomic coordinates cross approved portions,
the controller projects those coordinates into separate contained structural
cases under their existing parents. This never changes the approved RTC
boundaries.

Normal progress is nested:

```text
Review range:     JHN 1:1-21:25
Review portion:   4/19 — JHN 5:1-47
Source check:     2/5 — JHN 5:34
```

The approved review-portion denominator remains `19` for the complete Run.
Structural and source-check numbering resets within the parent review portion.
Machine manifests and receipts may retain `work_unit_id` for compatibility and
auditability.

## Enforcement decision

Three enforcement approaches were considered:

1. Prompt-only guidance was rejected because it cannot prevent a technically
   valid referral flood.
2. A structured, fail-closed controller gate was selected. The provider makes
   the semantic assessment, while Python enforces the closed classes, required
   assertions, provenance, scope, and uniqueness.
3. A separate model call for every referral candidate was rejected because it
   would add substantial task volume and latency before the already isolated OL
   adjudications.

## OL referral admission rule

An RTC meaning-stage candidate becomes an OL referral only when every rule
below passes:

1. **Fundamental meaning conflict.** The difference changes the core
   proposition, not merely nuance, intensity, style, register, or preference.
2. **Incompatible meanings.** WIP and REFERENCE cannot both communicate the
   same intended meaning.
3. **Approved conflict class.** The request declares exactly one class from the
   closed list below.
4. **Source-dependent.** Correctness genuinely requires the applicable
   original-language text.
5. **Unresolved by RTC evidence.** Routed WIP, REFERENCE, grammar, and other
   authorized non-OL evidence cannot settle the issue.
6. **One issue per referral.** The request asks one question at the smallest
   necessary Scripture scope.
7. **Unique issue.** The same normalized conflict may appear only once in the
   parent meaning-stage result.

If any rule fails, no OL request is created. The issue remains an RTC finding
or no-finding as appropriate.

## Approved conflict classes

`NEGATION_OR_POLARITY_CONFLICT`
: One rendering affirms, permits, requires, or favors what the other denies,
  prohibits, or opposes. This is semantic polarity, not a search for a token
  such as `not`. Negative concord, morphological negation, double negatives,
  rhetorical questions, and equivalent positive/negative constructions must
  be interpreted by meaning.

`PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT`
: A core subject/agent, object/patient, recipient, beneficiary, speaker,
  addressee, possessor, or referent is different, missing, added, or assigned a
  different semantic role. Reversal is one subtype, not a requirement. Active
  versus passive voice or different word order is not a conflict when the
  participant identities and roles remain equivalent.

`CORE_EVENT_OR_STATE_CONFLICT`
: The renderings assert fundamentally incompatible actions, events, states,
  quantities, times, locations, permissions, obligations, or prohibitions.
  The distinction must change the truth conditions or required response of the
  core proposition.

`CORE_PROPOSITION_OMISSION_OR_ADDITION`
: One rendering contains an essential proposition that the other lacks. Minor
  explicitation, recoverable implication, discourse smoothing, or stylistic
  expansion does not qualify.

The closed list deliberately excludes lexical intensity. For example,
`dislike` versus `hate` remains RTC; `love` versus `hate` may qualify as a
polarity conflict when the other admission rules also pass.

## Structured provider contract

Every `ol_review_requests` item created under the new contract retains its
existing identity, scope, question, reason, and evidence fields and adds:

```json
{
  "conflict_class": "NEGATION_OR_POLARITY_CONFLICT",
  "wip_proposition": "The WIP proposition in canonical report language.",
  "reference_proposition": "The REFERENCE proposition in canonical report language.",
  "fundamental_impact": "How the difference changes the core proposition.",
  "source_dependency": "UNRESOLVED_REQUIRES_ORIGINAL_LANGUAGE"
}
```

All narrative fields use the existing Job-owned canonical report language.
They summarize the competing propositions; they do not introduce external
Scripture or commentary.

The prompt states that an OL request may be emitted if and only if every
admission rule passes. It explicitly lists non-referral cases: lexical nuance
or intensity, style, register, readability, grammar, spelling, punctuation,
USFM structure, ordinary consistency, equivalent paraphrase, and any issue
resolvable from routed non-OL evidence.

## Deterministic controller gate

Python validates the complete meaning-stage output before any selective OL task
is created. For each request it requires:

- one allowed `conflict_class` value;
- nonempty and distinct normalized WIP and REFERENCE propositions;
- nonempty `fundamental_impact`;
- exact `source_dependency` value
  `UNRESOLVED_REQUIRES_ORIGINAL_LANGUAGE`;
- a target reference wholly inside the sealed meaning-task scope;
- only evidence IDs routed to that task;
- unique request and deferred-finding identities;
- no overlap between a final RTC finding and its deferred OL issue; and
- no duplicate normalized conflict key.

The controller derives the conflict key from the canonical target reference,
conflict class, whitespace/case-normalized WIP proposition, and
whitespace/case-normalized REFERENCE proposition. The provider does not supply
the key. Validation writes the derived `conflict_key` into the normalized
meaning-stage result, selective task inheritance, aggregate referral ledger,
and canonical report data.

Python cannot independently prove multilingual semantic equivalence. The
qualified RTC provider makes the semantic classification; the deterministic
gate enforces the closed contract and provenance. Model qualification and
regression fixtures test semantic boundary cases. No second referral-triage
model call is introduced.

No arbitrary numeric referral cap is introduced. Legitimate fundamental
conflicts must not be suppressed because a passage contains several of them.
Volume is reduced by the closed admission classes, required structured
justification, and duplicate rejection.

## Failure and retry behavior

One invalid request rejects the complete meaning-stage output with a specific
`SAW_OL_REFERRAL_*` reason code. The rejected output is preserved, and the same
sealed task remains ready for another provider attempt. SAGE creates no OL
tasks from a partially valid request list.

At minimum, diagnostics distinguish:

- missing referral fields: `SAW_OL_REFERRAL_FIELDS_MISSING`;
- unsupported conflict class: `SAW_OL_REFERRAL_CLASS_INVALID`;
- missing or invalid admission assertions:
  `SAW_OL_REFERRAL_ADMISSION_INVALID`;
- out-of-scope reference: `SAW_OL_REFERRAL_SCOPE_INVALID`;
- prohibited evidence: `SAW_OL_REFERRAL_EVIDENCE_INVALID`;
- duplicate referral: `SAW_OL_REFERRAL_DUPLICATE`; and
- final-finding/deferred-request overlap:
  `SAW_OL_REFERRAL_FINDING_OVERLAP`.

## Selective OL execution

After admission, existing isolation remains mandatory:

- one admitted referral produces one sealed selective OL task;
- one task contains one inherited request and its smallest governed scope;
- the OL evaluation receives no unrelated referral;
- the result resolves exactly that inherited request ID; and
- deterministic aggregation reconciles one resolution per admitted request.

## Compatibility

New RTC composite plans and task manifests declare
`ol_referral_contract: SAW_OL_REFERRAL_ADMISSION_V1`. Absence of that field
identifies a sealed legacy contract. Existing sealed tasks and plans are never
rewritten or reinterpreted, so Continue Run remains possible. Operators must
start or restart a Run to adopt the stricter referral gate and complete nested
progress metadata throughout that Run.

This is an Alpha contract change. Machine identifiers such as `work_unit_id`,
`ol_review_requests`, and `SELECTIVE_OL_ADJUDICATION` remain stable.

## Verification

Implementation is test-driven and must cover:

- each allowed conflict class with one valid referral;
- positive/negative semantic polarity without raw-token assumptions;
- different subject or object identity without reversal;
- equivalent active/passive participant roles producing no referral;
- lexical intensity such as `dislike` versus `hate` producing no referral;
- `love` versus `hate` as a qualifying polarity candidate;
- missing fields, unsupported classes, equal propositions, and invalid
  unresolved status;
- exact duplicate referral rejection;
- one-request-per-selective-task partitioning and exact aggregation;
- preservation of sealed legacy task behavior;
- a 19-portion Run whose later stage cases never display a changing
  `work unit` denominator; and
- full documentation, schema, package, and regression suites.

Qualification fixtures for `saw-rtc` must include valid fundamental conflicts
and false-referral cases for lexical intensity, equivalent paraphrase,
active/passive equivalence, and ordinary grammar/style differences.

## Out of scope

- A second model call to approve each referral.
- Arbitrary per-verse, per-portion, or per-Run referral caps.
- Changes to original-language authority bindings.
- Combining several admitted OL questions into one provider evaluation.
