# Local AI Assistive Mode

SAGE retains the Local AI compatibility switch, but its administrative explanations and executive summaries are now deterministic controller functions. Ollama does not participate in those paths and never becomes a governed BIC/SAW provider.

## Authority and configuration

- Governed automated provider: **CODEX only**.
- Local provider: Ollama, fixed model `sage-gemma4-e2b:q5_k_m`.
- Local authority: `ASSISTIVE_ONLY`.
- Compatibility switch: `providers.ollama.admin_assistant_enabled`.
- Enabling Local AI does not scan, block, or alter Jobs with secondary reporting configured.
- Creating or revising a Job may configure a secondary reporting language while Local AI is enabled.
- Basic primary-language work remains available. If that specific Job reaches secondary rendering while Local AI is enabled, the Hosted-AI-dependent rendering is rejected with `LOCAL_AI_EXTERNAL_RENDERING_REQUIRED`; the governing primary report remains available with an explicit degraded secondary-rendering status.

## Deterministic compatibility capabilities

The compatibility surface exposes these typed controller transforms:

1. status explanation;
2. diagnostic explanation;
3. explanation of controller-approved actions;
4. optional executive summary of a compact canonical report view.

There is no generic free-form workflow prompt API. Controller facts, reason codes, action tokens, IDs, coordinates, administrative explanations, and executive report summaries are computed deterministically without an AI call.

## Input boundary

The deterministic renderer receives only typed administrative or compact report facts. The boundary rejects fields or values that expose or request:

- raw Scripture or USFM/USJ payloads;
- Greek/Hebrew or other original-language Scripture;
- ACT or Skill bodies;
- arbitrary filesystem paths;
- credentials, secrets, tokens, or authorization data;
- fields outside the capability-specific whitelist.

Report-summary projection retains identifiers, coordinates/references, categories, risk/urgency/confidence, status, approved recommendation metadata, and candidate IDs. It does not expose canonical candidate forms or evidence prose and makes no model call.

## Preservation

The renderer preserves the exact controller-supplied action-token and referenced-ID arrays. Its output is reproducible from the same normalized fact view. There is no Ollama or CODEX fallback because no AI call is attempted.

Assistive provenance receipts are stored under `SAGEdata/.system/state/local-ai-receipts/`. They are administrative state and do not mutate Job, Run, Project Scripture, or canonical report state.

## Status surfaces

Classic status, CLI status data, and Textual status use the same normalized Local AI policy fields:

- ON/OFF;
- fixed model;
- authority `ASSISTIVE_ONLY`;
- readiness;
- reporting mode;
- secondary-language configuration availability;
- any Job-scoped external-rendering reason.

Classic and Textual status may render a deterministic assistive note from the same normalized facts without invoking Ollama.

## Report summaries

A canonical BIC/SAW report is written first and remains unchanged. When the compatibility switch is enabled, SAGE writes a separate deterministic `*_ASSISTIVE-SUMMARY.json` artifact carrying:

- `NON_AUTHORITATIVE_ASSISTIVE` label;
- source canonical-report SHA-256;
- canonical item IDs;
- unresolved critical item IDs;
- the optional local summary and its receipt.

Summary generation never changes the canonical report bytes.

## Qualification boundary

This development build keeps the existing configuration and artifact contracts while rendering the full administrative/summary surface in Python. Ollama installation and its explicit administration test remain separate operator tools, not dependencies of these transforms.
