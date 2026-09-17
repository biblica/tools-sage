# NCA integration with SQS confidence checks

Date: 2026-09-09.
Status: current behavior finalized by the user; shared SQS confidence checks are future functionality. No NCA runtime implementation is claimed.

## Confirmed direction

The user initially identified the LLM confidence checks planned for SQS, then explicitly deferred them to future functionality. Current NCA uses the configured LLM and states its capability limitations in every report. This supersedes the English-pilot, deterministic-only launch proposal. NCA remains an independent workflow at Main Menu #5, after STC. Language understanding is provided through the configured model; it is not restricted by an NCA-specific list of hand-written number-word parsers.

The authoritative reference tables, required Number Style Profile, three pre-Run toggles, and immutable Job/Run evidence remain part of the design. SQS confidence checks do not gate the current implementation. When implemented later, they should be shared infrastructure, not an independently invented NCA scoring system.

## Division of responsibility

| Component | Responsibility |
|---|---|
| Existing Scripture and VRS infrastructure | Supply immutable target text, separate footnotes, source locations, and correct reference mapping |
| LLM | Identify numeric expressions in the target language, their values, kinds, qualifiers, units and referents; interpret relevant footnote disclosure |
| Future shared SQS confidence checks | Assess model-derived evidence under the future shared policy; not performed in the current version |
| Deterministic NCA rules | Validate returned evidence, compare exact values, apply registered alternates/unit policies, enforce style rules and reconcile coverage |
| Operator | Review uncertain cases and suggested notes; approve any later changes to Scripture outside this check |

The model cannot replace OL values with NIV, invent a textual variant, change a style rule, or claim a note satisfies a requirement without supporting target evidence. The existing general model/language competency registry can supply relevant context, but it does not establish that an individual numeric extraction or footnote assessment is correct.

## Evidence required from model work

Each extracted expression must identify its original target span and text stream, exact normalized value, cardinal/ordinal/fraction/range/ratio kind, and any unit, approximation or quantity-to-referent relationship needed by comparison. Main text and footnote content are separate inputs and outputs. Note locator numbers and cross-references cannot become numeric disclosure evidence.

Target extraction should occur before supplying expected OL/NIV values to that extraction operation. This reduces the chance of copying the expected answer instead of reading the target. Later correspondence and footnote assessment may use the specific authoritative row and its registered explanatory evidence.

Validate source spans, schema, exact numeric encodings, multiplicity and complete work-unit coverage independently of model confidence. A high confidence claim cannot repair an invalid span or contradictory evidence. Repeated model agreement is not, by itself, proof of correctness.

Currently retain the model release, task/prompt identity, language and input hashes with the associated NCA evidence. In future, retain the SQS assessment and policy provenance when the shared contract exists. Model-reported confidence may be retained as evidence if SQS permits it; it must not become an invented NCA pass threshold or substitute for measured qualification.

## Result handling

- Usable evidence proceeds to exact numeric comparison and reading-dependent footnote policy.
- Reported uncertainty, disagreement, unsupported context or incomplete extraction remains visible as insufficient evidence or operator review. It cannot produce an all-clear result.
- A registered alternate is acceptable only under its registered policy and any required, adequately assessed note.
- A missing footnote and an existing note whose meaning cannot be assessed remain different outcomes.
- A run may finish processing while retaining unresolved results. Reports must distinguish execution completion from assessment completeness.

Do not invent a confidence cutoff, model self-rating gate, independent-review threshold or SQS status for the current version. Future SQS retry, review, escalation and confidence aggregation must follow its eventual shared specification. Existing provider execution/retry mechanics remain available.

## Job setup and execution

Require one WIP Project, the authoritative numbers package, the Project language identity, exactly one compatible Number Style Profile, and a configured model route using existing SAGE provider requirements. Snapshot the current model/task identities alongside the reference and style hashes so resumed Runs preserve their evidence contract.

Keep the three user-facing switches: number accuracy; presentation consistency; footnote review and recommendations. At least one must be ON. Disabled checks are not assessed. The mandatory report limitation applies to any model work needed by the enabled checks. A presentation-only run cannot claim OL accuracy.

Profile setup and reference inspection can be local operations. Model-dependent execution requires provider readiness; do not remove those prerequisites on the basis of the superseded deterministic-only proposal.

## Acceptance additions

Tests must cover invented/misaligned spans, numeric words versus digits, ordinal/partitive ambiguity, swapped quantity referents, dropped approximation, unrelated matching numbers in notes, incomplete output coverage, explicit model uncertainty, conflicting evidence, changed model/task identities on resume, and missing provider prerequisites. Future SQS tests must be added when that functionality is implemented. The handover's existing numeric, variant, unit, VRS and immutability fixtures remain mandatory.

Use synthetic recorded model responses for deterministic CI; they test evidence handling without claiming live model competence. Current output must not claim SQS qualification. A later implementation must use the actual SQS protocol before making such a claim.

## Mandatory current report disclosure

Every human report and export, including zero-finding and incomplete reports, must contain this meaning in the Job's reporting language:

> Findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities. SQS confidence checks have not been applied.

Machine results must carry an explicit limitation and record that SQS checks were not applied, together with the actual provider/model. Do not expose a percentage or certification badge that suggests measured SQS confidence. A report with no findings is not proof that the model found every numeric issue.

## Future functionality

Record shared SQS confidence checks in the NCA roadmap. Obtain its actual specification when implementing that future feature, then map its service interface, assessment states, threshold ownership, review/retry policy and versioning. No SQS specification is required to complete the current NCA design or proceed with its implementation.

The inspected repository contains `model_language_competency.py`, a general evidence registry. It is not a substitute for the future SQS per-task checks. The current version uses capability disclosure rather than inventing that missing service.

## Related: Language Profile capture (2026-09-17)

Captured here alongside SQS as another piece of forward-looking, currently-unimplemented capability work tracked in the same "future functionality" spirit.

Current state: `app/system/config/schemas/language-profile-registry.schema.yml` already requires only `script` (ISO 15924, four-letter code) and the canonical BCP-47 language tag itself (which already carries region, e.g. `pt-BR`, `fr-011`, `ti-ER`) per profile namespace. Everything else about a language (display name, spoken regions/countries) is not hand-authored per profile — it is already sourced from the bundled `app/system/data/iso-639-3.json` and `iso-3166-1.json` reference snapshots and resolved at render time via `iso_language()`/`resolve_country()` in `act_outputs.py`.

Open question raised: should "sourced from official online repos" mean a periodically-refreshed bundled snapshot (consistent with the existing iso-639-3/iso-3166-1 approach, and with this project's deterministic, offline-capable design — no-network installs, reproducible reports), or live runtime queries against IANA/CLDR/Ethnologue? The former preserves determinism; the latter would introduce a network dependency and non-determinism risk that conflicts with how the rest of SAGE is built. Recommendation: keep the bundled-snapshot approach — capture only script + BCP-47 tag per project language, derive the rest from a periodically-refreshed local reference bundle, refreshed at release-build time rather than queried live.

Not yet resolved: how many languages/profiles the "build language profile list" TODO actually needs to cover (sizing not yet done).
