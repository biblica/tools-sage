# SQS integration implementation plan

**Goal:** Bring SQS (SAGE Qualification Service) from recovered-but-uncommitted source into a working, tested, extensible sibling service under version control, then layer it into SAGE's existing model-routing policy as the evidence source, without disturbing SAGE's current, tested behavior.

**Spec:** [2026-09-18-SQS-ARCHITECTURE-EVALUATION.md](../specs/2026-09-18-SQS-ARCHITECTURE-EVALUATION.md) (read first — it records the gap analysis and locked decisions this plan implements) and [2026-09-09-NCA-SQS-INTEGRATION.md](../specs/2026-09-09-NCA-SQS-INTEGRATION.md) (NCA's own SQS consumption stays future/deferred, unaffected by this plan).

**Tech stack:** `services/sqs/` is an independent Python 3.12+ package (`tools-sage-sqs`: fastapi, pydantic, PyYAML, uvicorn, cryptography) with its own venv, versioned separately from the SAGE app. SAGE-side integration uses SAGE's existing Python runtime plus a new direct `cryptography` dependency.

## Global constraints

- Do not weaken SAGE's current routing/harness/versification/provenance test baseline at any step.
- Do not restore "legacy" behavior (hand-seeded qualification, single hardcoded provider) to make old tests pass; migrate the tests instead.
- Provider identity is an open catalog (spec §6.1) — never hardcode a second, independently-maintained provider list.
- Every hardening-ledger item (rollback protection, negative tombstones, Ed25519, outbox-first discovery, endpoint failover) must be implemented test-first; none of it survived as code from the prior effort, so there is nothing to "port" for these items specifically.
- Governed SAGE task execution must never make a synchronous SQS network call; only explicit `sage model sqs-sync` talks to SQS over the network.

## Task 0 — Recover a durable, verified baseline (done)

- [x] Copy `recoverable_v11_source/` into `services/sqs/` in this repository, unmodified.
- [x] Stand up a local venv, install deps (+ `jsonschema`, missing from the `dev` extra), confirm 88/88 tests pass with `SQS_DB_PATH`/`SQS_CONFIG_ROOT` pointed at writable local paths.
- [x] Record the real defects found (`pyproject.toml` missing `jsonschema`, `runtime.py` import-time side effect against hardcoded FHS paths, unpinned deps) in the spec rather than silently fixing them as part of "just recovering."
- [ ] Commit this checkpoint before any modification, so "unmodified recovered baseline, 88/88" is a real, inspectable git commit.

## Task 1 — Provider onboarding contract (new; not in the original plan)

Implements spec decision 1 (extensible provider identity).

- [ ] Add `services/sqs/contracts/provider-descriptor.schema.json`: `{provider_family, display_name, access_mode, provisioning_model, capability_classes[], reasoning_tier_taxonomy}`. `access_mode` is an open string (e.g. `openai_codex_workspace` for `codex`, `api_key` for a future direct-API provider) — not an enum of two, since new access modes will appear. `provisioning_model` distinguishes org-managed seat provisioning (`workspace`, e.g. every staff member draws on the org's OpenAI Codex workspace entitlement — the confirmed first binding) from per-integration credentials (`api_key`) — this affects how a new provider's capability/tier assumptions can be trusted to hold uniformly across all staff versus needing per-credential verification.
- [ ] Add `services/sqs/seed/providers/codex.yml` as the first descriptor: `provider_family: codex`, `access_mode: openai_codex_workspace`, `provisioning_model: workspace`. This replaces the assumption baked into `seed/openai-provider.yml` (which assumed a direct OpenAI API-key integration SAGE does not use). Keep `openai-provider.yml` only if a real direct-OpenAI-API provider is ever separately onboarded; otherwise remove it rather than leave a stale, unused seed.
- [ ] Loosen `contracts/sqs-bundle-1.0.schema.json`'s `provider_family` (still `const:"openai"`) to match 1.1's free string, or drop 1.0 entirely if nothing depends on it — confirm via `git grep` on the SAGE side before removing.
- [ ] Write a cross-catalog consistency test: any `provider_family` appearing in a published bundle must exist in the provider-descriptor catalog, and (once Task 6 exists) in SAGE's governed-provider allowlist. Fail closed — an unregistered provider in a bundle is a hard error, not a warning.
- [ ] Update `evaluation/planner.py`/`domain.py` fingerprint canonicalization if it assumed `"openai"` anywhere literal (grep first; report findings before changing).

## Task 1b — Language onboarding contract (new; symmetric to Task 1)

Implements spec decision 5. Not hypothetical: SQS's 20 seeded languages vs. SAGE's 44 live grammar profiles already have a 27/5 mismatch (spec §5 item 7) — this task closes an existing gap, not just a future-proofing exercise.

- [ ] Define the onboarding action precisely: adding a language to SAGE (a new `config/profiles/grammar/<tag>/` directory + registry entry) and adding it to SQS (a `seed/languages/<tag>.yml` + `config/evaluation-packs/<tag>-{grammar-analysis,semantic-rewrite}-r1.yml` pair) are one coordinated change, not two independently-timed ones.
- [ ] Reconcile the existing 27/5 mismatch as real work: for the 27 uncovered SAGE profiles, either onboard them into SQS (seed + evaluation packs) or explicitly record them as intentionally not-yet-qualified (`UNASSESSED`, consistent with SAGE's existing policy vocabulary — not silently missing). For the 5 SQS languages with no matching SAGE profile (`es-ES`, `pa-Arab-PK`, `pa-Guru-IN`, `pt-PT`, `sw-CD`), confirm whether each should map onto an existing SAGE profile under a different tag, be added as a new SAGE profile, or be retired from SQS's seed set as stale — don't assume; check each one.
- [ ] Write a cross-catalog consistency test analogous to Task 1's: a language profile referenced in an SQS bundle qualification must exist in SAGE's registry (by the same identity — profile_id/BCP-47 tag), and vice versa for any SAGE profile expected to be governed-routable. Fail closed on drift, don't silently degrade to provisional routing without recording why.
- [ ] Qualification testing itself keeps the existing monotonic boundary-search / single `minimum_reasoning` threshold design per spec decision 6 — this task is about which (model × language × capability) combinations get tested at all, not how each one is tested.

## Task 2 — Fix the defects found during recovery

- [ ] Add `jsonschema` to `pyproject.toml`'s `dev` extra.
- [ ] Change `runtime.py` so opening the database is an explicit call inside `create_runtime_app`/a real entrypoint function, not a module-level global executed on import. Keep the `SQS_DB_PATH`/`SQS_CONFIG_ROOT` env vars as the configuration mechanism, but only read/act on them when the app is actually being constructed (uvicorn entrypoint, test fixture), not whenever the module is imported.
- [ ] Pin dependency versions in `pyproject.toml` (or a lockfile) against what's actually verified working in this session, per the hardening ledger's "dependency set is locked for deterministic Mac setup" requirement.
- [ ] Re-run the full suite after each fix; each must independently stay green.

## Task 3 — Reapply post-snapshot hardening (test-first; real implementation, not porting)

One sub-task per hardening-ledger item, each as its own failing-test-then-implementation cycle:

- [ ] Publication digest + Ed25519 signature verification on the bundle consumer side.
- [ ] Monotonic authority/epoch/revision enforcement; rollback rejection.
- [ ] Current + previous known-good cache generation rotation; missing metadata must not lower the rollback floor.
- [ ] Torn bundle/metadata pair rejection (identity-pair validation).
- [ ] Durable negative-evidence tombstones, independent of normal cache staleness; crash-between-writes fails closed.
- [ ] Ordered endpoint failover (`SAGE_SQS_URLS` list, `SAGE_SQS_URL` single-endpoint compatibility override): failover on connection/5xx only, never on 4xx/contract/signature rejection.
- [ ] Loopback-only HTTP exception (`127.0.0.1`, `localhost`, loopback IPv6) with explicit proxy bypass; non-loopback endpoints require HTTPS.
- [ ] Outbox-first discovery: SAGE queues metadata locally and never blocks task execution on delivery; explicit sync flushes and SQS deduplicates.

## Task 3a — Provider rate-limit handling (independent gap, surfaced by this evaluation)

Not an SQS transport concern (that's Task 3's endpoint failover, for SAGE↔SQS traffic). This is the existing, pre-dating SAGE↔`codex` provider call path, which currently has **no** 429/`Retry-After` handling at all (confirmed empty grep across `executors/http.py`, `llm_tasks.py`, `model_service.py`). Usage allowance is confirmed to differ between workspace and personal `codex` accounts (both authenticate identically via `chatgpt.com` web sign-in, so SAGE cannot distinguish which kind a session is at auth time); a rate-limited session fails a governed task outright today. Not required to unblock SQS integration itself, but should land before real qualification runs are exercised (Task 7's local socket test, Task 9's server runtime) against live accounts.

- [ ] Add typed handling for 429/`Retry-After` in the provider call layer, distinct from a hard transport failure.
- [ ] Decide and implement a bounded backoff/retry policy for rate-limit responses specifically (not for other error classes — that stays as today's fail-fast behavior per SAGE's existing design).
- [ ] Do not attempt to detect workspace-vs-personal account type — the shared `chatgpt.com` auth flow gives no signal to distinguish them; handle by response code, not by inferred account type.

## Task 4 — SAGE-side integration units (self-contained, test-first)

- [ ] `app/system/config/sqs.yml`, `app/system/config/schemas/sqs.schema.yml`, `app/system/config/contracts/sqs-bundle-1.1.schema.json` (mirroring the corrected SQS-side schema from Task 1/2).
- [ ] `app/system/src/sage/sqs_client.py`, `sqs_discovery.py`, `sqs_qualification.py` — new, independent of current routing until their own tests pass. Use the *tested* discovery contract (uppercase `kind`, no `execution_provider`), not the stale `openapi.yaml`.
- [ ] Add direct `cryptography==<pinned version from Task 2>` to SAGE's runtime dependencies (not inherited from a shared SQS venv).
- [ ] `sage model sqs-sync` CLI command: flush queued discoveries, refresh/validate publication, rotate local known-good cache, report `REMOTE`/`CACHE`/failure — without opening any synchronous network path from normal task execution.

## Task 5 — Layer SQS into existing SAGE routing (spec decision 2: evidence source, not replacement)

- [ ] Extend `model_policy.py`/`model_evaluation.py` to accept SQS bundle qualifications as an additional evidence input alongside (then, once trusted, instead of) `model-qualification-seeds.json`. Preserve `accepted_operational_statuses`, `provisional_routing`, `known_negative_effect`, `stale_evidence_effect` semantics exactly.
- [ ] Map SQS's canonical reasoning bands (`low/medium/high`) and native tiers onto SAGE's existing `reasoning_effort` concept; confirm with a real example whether these are the same concept under different names or need an explicit conversion table (open question — resolve with evidence, not assumption, before writing the mapping).
- [ ] Exact positive SQS evidence resolves a route; exact `NOT_QUALIFIED` blocks it; unknown routes follow existing provisional policy; no governed route ever calls SQS transport directly.
- [ ] Include SQS publication/tier provenance in existing execution receipts.
- [ ] Migrate (don't delete) legacy tests that mutate local qualification seeds to instead construct SQS positive/negative publication fixtures.

## Task 6 — Provider and language onboarding in practice

- [ ] Extend `llm_settings.py`'s governed-provider allowlist to be validated against the same provider-descriptor catalog introduced in Task 1, rather than being an independent hardcoded list.
- [ ] Extend SAGE's language-profile loading (`registry.py`) to be checkable against SQS's language catalog from Task 1b, surfacing (not silently absorbing) any profile that's routable in SAGE but unqualified/unknown in SQS.
- [ ] Write the Task 1 and Task 1b cross-catalog consistency tests on the SAGE side too: a provider or language present in SQS's catalog but not SAGE's (or vice versa) fails closed with a clear error, never silently permits or silently drops it.
- [ ] Document both onboarding procedures (one short doc each, or one doc with two sections): what changes when a new provider is added, what changes when a new language is added, and where.

## Task 6a — Service availability / allowance checking (included allowance today, API credit later)

Distinct from Task 3a (reacting to a 429 mid-call): this is a proactive "is this connection currently usable" check, generalized per access mode via the Task 1 provider-descriptor catalog rather than special-cased to `codex`.

- [ ] Research, don't assume: does OpenAI's `chatgpt.com` web-session auth (what `codex`'s workspace/personal accounts both use) expose any queryable remaining-included-allowance signal today — a header, a status endpoint, anything — or is exhaustion only observable by hitting it (a 429)? Record the answer before designing around it.
- [ ] Add an `availability_check` field to the Task 1 provider-descriptor schema: how SAGE determines current usability for a given provider + access mode. Each access mode gets its own check strategy — included-allowance and API-credit are different systems (session-based quota vs. an actual OpenAI platform billing/usage query), not one mechanism with two labels.
- [ ] Surface current availability per governed provider (e.g. via `sage model status` or existing model-service diagnostics) so an operator or task can know before committing to a run, not just discover it via a failed call.
- [ ] A future API-credit access mode is a new provider-descriptor entry with its own `availability_check` (per Task 1's onboarding contract), added when that mode is actually enabled — not a special case bolted onto `codex` now. Enabling API-key/API-credit access itself stays out of scope here: `llm_settings.py`'s `openai_api_keys: PROHIBITED` is an explicit current policy and changing it is a separate decision, not implied by adding this check architecture.

## Task 7 — Acceptance gates

Reuse and adapt the recovered `05_ACCEPTANCE_TESTS/ACCEPTANCE_GATES.md` categories (current SAGE preservation, SQS source, publication trust/cache, transport/failover, discovery, routing authority, real local Mac socket test, packaging), re-verified against the actual integrated tree at completion — not assumed from the historical pack.

## Task 8 — Release/versioning

- [ ] Update `VERSIONING-POLICY.md` and `TODO.md` once SQS reaches a real milestone (e.g. Task 4 complete) — do not mark it done prematurely; both currently correctly say SQS is unimplemented.
- [ ] Decide, once `services/sqs/` is stable, whether to split it into `biblica/tools-sage-sqs` (spec decision 4 defers this, doesn't cancel it).

## Status

Task 0 in progress (baseline recovered and verified; commit pending). Tasks 1–8 not started.
