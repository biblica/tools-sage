# Model Handoff Optimization — v0.01beta2

## Purpose

`0.01beta2` retains the proven provider projections established during earlier development and adds conservative planning/focus optimizations without reducing the governed evidence available to SAGE. The controller remains authoritative for evidence admission, hashing, task identity, coverage, receipts, validation, and file materialization. Optimization occurs only after those local controls are established.

## 1. Governance inputs versus model reads

Immutable task inputs are split into two transport roles:

- `governance_inputs`: controller-consumed `PROCESS_CONTROL` files. SAGE re-hashes them at execution time, but their full bodies are not serialized to the provider.
- `allowed_reads`: evidence whose content the model must inspect. Every read still carries an explicit evidence class and is re-hashed before use.

The immutable `ACT.md` also remains a controller artifact. The provider receives only its deterministic `Process brief` capsule instead of the full ACT and repeated control sections.

## 2. Scripture transport and controller projections

Model-facing Scripture is routed as bounded SFM. SAGE may compile USJ/structural projections locally for deterministic validation, coordinate mapping, coverage reconciliation, and audit, but those controller projections are not Scripture sizing inputs and do not replace the exact SFM evidence sent to the provider. No Scripture wording is summarized or paraphrased.

Every routed natural-language stream also receives its complete canonical linguistic profile as a separate immutable model read. Project streams use `LANGUAGE_PROFILE`; GRK/HEB authorities use source-bound `OL_AUTHORITY_PROFILE`. Profiles are not Scripture evidence, are not sliced, and do not contribute to the SFM sizing budget.

## 3. RTC/STC semantic-only output

RTC/STC provider schemas are stage-specific. The model returns only semantic judgments relevant to that stage, such as findings, OL requests/resolutions, structural adjudications, and a concise review summary.

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

## 5. Routed-SFM sizing and transport telemetry

Every model review item records two deliberately separate measurement classes:

- `routed_sfm`: the exact SFM Scripture text routed to that review item. This is the only input to the Scripture token estimator and hard analysis-byte guard.
- transport/audit telemetry: serialized prompt, output schema, profiles, controller manifests, and other governed material. These bytes may be recorded for observability but contribute zero to Scripture slicing and cannot change a work-unit boundary.

A token estimator must never be called on controller JSON, microtransactions, prompts, schemas, profiles, IDs, hashes, diagnostics, or USJ projections.

## 6. Review-item planning and focus batching

Task creation records `context_budget.routed_sfm` with `planning_basis: ROUTED_SFM_ONLY`. New Jobs weight analytical progress by `ROUTED_SFM_ESTIMATED_TOKENS`; historical progress records may retain the legacy basis for read compatibility only.

The general SFM slicer owns deterministic Scripture planning for BIC, RTC, STC, Targeted Check, and Original-Language Review. Each operation/profile declares the streams for its actual review item. Current RTC geometry keeps a WIP target around 6,000 tokens, prefers WIP boundaries around 5,000–7,000, and rejects an individual WIP slice at 8,000 tokens or above; the complete required WIP+REFERENCE route is independently guarded by the configured routed-SFM hard limit. OL Scripture is not pre-reserved into the normal RTC route. A qualifying selective OL adjudication becomes a new bounded review item and sizes only the SFM routed to that item.

STC uses the same general slicer with a different route profile: WIP plus the testament-appropriate PRIMARY OL authority (GRK for NT, HEB for OT). BIC INSPECT partitions using its routed Scripture SFM; REWRITE and SELF-CHECK inherit approved scope.

Protected bridges, OL correspondence spans, discourse units, and exact primary coverage remain controller-owned constraints. Context SFM counts only when that context is actually sent to the model.

## 7. Task-scoped provider readiness and exact routing

Provider authentication and the live capability catalog are checked before task evidence is assembled.
SAGE then resolves an available route qualified for the manifest's exact registered `skill_id`. The
immutable execution receipt binds provider, model/capability identity, provider-native reasoning,
Skill/suite/policy hashes, qualification evidence, and automatic/override mode. An unavailable,
unassessed, stale, failed, or Skill-mismatched route is rejected before task evidence is sent.

The resulting task-scoped readiness snapshot may be reused for that task's first pass and authorized
BIC OL micro-adjudications, but every request remains independently bounded. SAGE does not reuse model
conversation state. Original-language adjudication sends exactly one item per evaluation. Secondary-
language report rendering sends exactly one reported item per evaluation, uses the originating item's
recorded route, and degrades to the canonical report if that route is not safely reusable.

## 8. Local semantic lookup efficiency

Semantic evidence retrieval now builds a local `record_id -> sense rows` lookup once per retrieval call instead of rescanning the complete sense table for each matched surface form. Original sense-document order is preserved. This changes local CPU work only; no evidence record, sense, authority field, or model-facing semantic decision is omitted.

## 9. Non-negotiable boundaries

Optimization must not:

- widen or change evidence authority;
- summarize Scripture content heuristically;
- substitute model recall for omitted evidence;
- drop material evidence because a local heuristic predicts irrelevance;
- let the provider generate controller-owned task identity, coverage, hashes, or receipts;
- permit an OL micro-task to broaden beyond its authorized single-verse challenge;
- count deterministic aggregation or report composition as an LLM handoff; or
- combine independent adjudication/rendering items merely to reduce provider calls.

Local slicing is deterministic, auditable, and derived from the same hashed governed inputs.
