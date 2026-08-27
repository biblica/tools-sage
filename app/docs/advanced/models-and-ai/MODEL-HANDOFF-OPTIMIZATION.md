# Model Handoff Optimization — v0.01beta

## Purpose

`0.01beta` retains the proven provider projections established during earlier development and adds conservative planning/focus optimizations without reducing the governed evidence available to SAGE. The controller remains authoritative for evidence admission, hashing, task identity, coverage, receipts, validation, and file materialization. Optimization occurs only after those local controls are established.

## 1. Governance inputs versus model reads

Immutable task inputs are split into two transport roles:

- `governance_inputs`: controller-consumed `PROCESS_CONTROL` files. SAGE re-hashes them at execution time, but their full bodies are not serialized to the provider.
- `allowed_reads`: evidence whose content the model must inspect. Every read still carries an explicit evidence class and is re-hashed before use.

The immutable `ACT.md` also remains a controller artifact. The provider receives only its deterministic `Process brief` capsule instead of the full ACT and repeated control sections.

## 2. Scripture projection

Model-facing USJ uses `SAGE_SCRIPTURE_SLICE_V1`. SAGE retains the full USJ packet and its hash locally, but the provider projection contains only:

- projection identifier;
- evidence class;
- book code and bounded scope;
- original source SHA-256;
- exact USJ `content` required for the bounded task.

Duplicated `sage.verse_records`, parser line offsets, internal paragraph identifiers, parser diagnostics, and other local implementation metadata are not repeated to the model. No Scripture wording is summarized or paraphrased by this projection.

## 3. SAW semantic-only output

SAW provider schemas are stage-specific. The model returns only semantic judgments relevant to that stage, such as findings, OL requests/resolutions, structural adjudications, and a concise review summary.

SAGE materializes deterministic fields locally before canonical validation, including:

- task identity;
- stage/scope/focus/check type;
- expected coordinate coverage;
- work-unit identity and task fingerprint;
- review receipt identity and required checks.

This removes token-expensive model echo fields while preserving the existing canonical findings contract after local materialization.

## 4. BIC conditional OL micro-adjudication

A material BIC OL challenge no longer triggers regeneration of all REWRITE outputs. Each authorized challenge becomes one micro-task containing only:

- one inherited challenge/question;
- the current bounded candidate verse;
- one locally sliced SOURCE verse;
- one locally sliced applicable OL verse;
- relevant authorized non-Scripture evidence;
- the first-pass candidate inventory required to adjudicate the existing choice.

The micro-response may select only an existing first-pass candidate, state after-OL risk and evidence, report newly introduced project-grammar issues, and optionally return one bounded replacement verse. SAGE merges that delta into the existing rewrite and challenge ledger locally. Prior grammar/risk evidence is retained conservatively and cannot be silently cleared by the micro-call.

The former conditional prompt path that re-sent the complete phase-one output set has been removed.

## 5. Handoff telemetry

Every execution phase records exact prompt/schema handoff measurements and deterministic projection telemetry. Receipts include:

- prompt, schema, and total serialized bytes;
- estimated prompt, schema, and total tokens;
- raw routed evidence bytes/tokens;
- model-facing evidence bytes/tokens;
- saved bytes/tokens and estimated reduction percentage;
- projected-read count;
- evidence-class breakdown.

Hard handoff limits continue to apply to the actual serialized provider prompt plus schema. Projection statistics are diagnostic and cannot override a context-limit failure.

## 6. Quality-first planning and focus batching

Task creation now records two independent measurements:

- `context_budget.governance_context`: the complete controller-routed local context, including controller-only governance inputs, conditional reads, full ACT text, and task manifest. This is retained for audit and legacy comparison.
- `context_budget.provider_handoff`: the exact projected first provider prompt plus output schema built with the same projection path used at execution time. This is the planning/progress workload basis.

The exact handoff is reconstructed and hard-gated again immediately before provider execution. A planning estimate therefore cannot authorize an oversized provider request. Historical Jobs that explicitly record the legacy `ACT_ESTIMATED_TOKENS` progress basis remain readable; new Jobs use `PROJECTED_HANDOFF_ESTIMATED_TOKENS`.

RTC batching is discourse-first and governed from the original WIP contribution rather than by filling the complete model context. The shipped RTC geometry is:

- WIP target: about 6,000 estimated tokens;
- preferred discourse packing range: 5,000–7,000 estimated WIP tokens;
- hard WIP packet limit: strictly below 8,000 estimated tokens;
- complete WIP+REFERENCE provider handoff target: below 28,000 estimated tokens;
- complete RTC provider handoff hard guard: 32,000 estimated tokens.

The WIP establishes the canonical Scripture range and the configured Reference Project follows exactly that range. OL Scripture is not budgeted into the normal RTC package. If RTC identifies a qualifying material WIP–Reference source-text discrepancy, SAGE creates a new finding-scoped OL clarification task containing only the affected WIP/REFERENCE coordinate(s), the applicable Job-bound GRK/HEB evidence, provenance, and the exact question. The parent RTC package is not enlarged or rerun.

A prose paragraph, major list unit, or operational poetry stanza remains indivisible merely to meet the 6k target when it still fits below the hard WIP slice limit. Targeted Check remains capped at two intact primary discourse units, standalone SAW OL review at one, and BIC INSPECT at four. BIC REWRITE and SELF_CHECK continue to follow approved bounded INSPECT lineage.

## 7. Task-scoped provider readiness

Codex authentication/catalog/model readiness is verified once for a governed task. The resulting immutable readiness snapshot is reused for that task's first pass and any authorized BIC OL micro-adjudications. Each micro-request is still checked against the verified model/reasoning capabilities, and any execution failure remains fail-closed. SAGE does not reuse model conversation state.

## 8. Local semantic lookup efficiency

Semantic evidence retrieval now builds a local `record_id -> sense rows` lookup once per retrieval call instead of rescanning the complete sense table for each matched surface form. Original sense-document order is preserved. This changes local CPU work only; no evidence record, sense, authority field, or model-facing semantic decision is omitted.

## 9. Non-negotiable boundaries

Optimization must not:

- widen or change evidence authority;
- summarize Scripture content heuristically;
- substitute model recall for omitted evidence;
- drop material evidence because a local heuristic predicts irrelevance;
- let the provider generate controller-owned task identity, coverage, hashes, or receipts;
- permit an OL micro-task to broaden beyond its authorized single-verse challenge.

Local slicing is deterministic, auditable, and derived from the same hashed governed inputs.
