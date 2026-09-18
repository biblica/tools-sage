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

## Task 1 — Provider/execution-channel onboarding contract (new; not in the original plan)

Implements spec decision 1 (two-field provider identity: `provider_family` = model vendor, stays `"openai"`; `execution_channel` = access mode, new). This finishes what `seed/openai-provider.yml`'s own unused `execution_provider_aliases` field and prose note already intended, rather than introducing a competing concept.

- [x] Add `services/sqs/contracts/execution-channel-descriptor.schema.json`: `{execution_channel, provider_family, display_name, provisioning_model, capability_classes[], reasoning_tier_taxonomy}` (+ reserved optional `availability_check` for Task 6a). `execution_channel` is an open string — not an enum of two, since new channels will appear, possibly to the same model vendor.
- [x] Add `services/sqs/seed/execution-channels/codex-workspace.yml` as the first descriptor: `execution_channel: codex_workspace`, `provider_family: openai`, `provisioning_model: workspace`. Left `seed/openai-provider.yml`'s model catalog as-is; replaced its dead `execution_provider_aliases: [codex]` field (never read by the loader) and stale prose note with a cross-reference to the new descriptor file.
- [x] Added `services/sqs/src/sage_sqs/execution_channels.py`: schema-validated loader (`load_execution_channel_descriptor`/`load_execution_channel_catalog`/`known_execution_channels`), fails closed on a duplicate `execution_channel` across seed files. `jsonschema` moved from a missing dev-only dependency to a core runtime dependency in `pyproject.toml` (this module needs it outside tests too) — also closes part of Task 2's dependency gap.
- [x] Added `execution_channel` (required) to `Qualification` in `domain.py` and to `qualifications[]` in `contracts/sqs-bundle.schema.json` (1.1). **Correction from an earlier draft of this plan**: `execution_channel` is provenance evidence (which channel produced this qualification's evidence), not part of the qualification's identity key — the key stays `(provider_family, model_id, profile_id, capability)` exactly as before, unchanged in `repository.py`'s `save_qualification`/`evaluation/lifecycle.py` (confirmed by grep — nothing elsewhere assumed a different key shape). Adding it to the key would contradict the entire reason for splitting the fields: a model qualifies once regardless of access channel.
- [x] `contracts/sqs-bundle-1.0.schema.json` stays `provider_family: const "openai"` (still correct under the two-field model) — no change made.
- [x] `synthesize_qualification` (`qualification.py`) now takes `execution_channel` and includes it in the evidence dict hashed into `evidence_sha256`; `Worker` (`worker.py`) requires an explicit `execution_channel` at construction (no default — fails closed) and threads it through; `drain()`'s CLI entrypoint reads `SQS_EXECUTION_CHANNEL`, raising if unset, mirroring the existing `OPENAI_API_KEY` fail-loud pattern. `ModelRecord.catalog_fingerprint` correctly stays unchanged (vendor/model identity only, no channel) — applying the same "no channel in key" reasoning.
- [x] Cross-catalog consistency test added (`tests/test_execution_channels.py`): a published bundle's `execution_channel` values must all exist in the seeded descriptor catalog; proven to actually catch drift, not just vacuously pass. The SAGE-side half of this check (Task 6) is not yet implemented — SAGE has no `sqs_client.py` to check from yet (Task 4).
- [x] Full suite re-verified green after every change: 93/93 (88 original + 5 new).
- [ ] **New finding while implementing this task, not yet fixed**: `worker.py`'s `drain()` default path (`provider is None`) constructs `OpenAIProvider(os.environ["OPENAI_API_KEY"])` — the only real, working provider adapter in this codebase is built around a raw API key, i.e. the `api_key` execution channel, not `codex_workspace`. There is no adapter that can actually execute a qualification test through a Codex workspace account. Recording `execution_channel: codex_workspace` on a qualification is now structurally possible, but no code path can yet *produce* one truthfully from a real run — only from hand-constructed evidence (as the tests do) or from a run actually made through the `api_key` channel mislabeled as `codex_workspace`. A `CodexWorkspaceProvider` adapter (however SAGE actually shells out to/authenticates with Codex) is required before any real qualification run can be trusted to carry that label. Tracked for Task 4/9, not solved here.

## Task 1b — Language onboarding contract (new; symmetric to Task 1)

Implements spec decision 5. Not hypothetical: SQS's 20 seeded languages vs. SAGE's 44 live grammar profiles already have a 27/5 mismatch (spec §5 item 7) — this task closes an existing gap, not just a future-proofing exercise.

- [x] Defined the onboarding action precisely, implemented as `services/sqs/config/language-coverage-status.yml`: a checked-in manifest recording every profile_id known to either catalog with an explicit status (`ONBOARDED`, `SAGE_ONLY_UNASSESSED`, `SQS_ONLY_PENDING_SAGE_PROFILE`). Adding a language to either side without updating this manifest now fails the consistency test below — that's what "one coordinated change" means in practice.
- [x] Reconciled the existing 27/5 mismatch as real, checked work — **without fabricating any language content**: this task builds the onboarding *mechanism*, not new evaluation packs or grammar profiles, which need real linguistic subject-matter review to author correctly. Checked each of the 5 SQS-only languages individually rather than assuming: none are tag mismatches with an existing SAGE profile — `es-ES` (European Spanish, distinct from SAGE's `es-419`/`es-MX` Latin-American variants), `pt-PT` (European Portuguese, distinct from `pt-419`), `sw-CD` (Congo Swahili/Kingwana, distinct from `sw-TZ`/`sw-KE`), and `pa-Arab-PK`/`pa-Guru-IN` (Punjabi in Arabic/Shahmukhi and Gurmukhi script respectively — SAGE has no Punjabi profile in either script). All 5 recorded `SQS_ONLY_PENDING_SAGE_PROFILE` with the reasoning above, kept rather than deleted (deleting real seed/evaluation-pack content someone deliberately authored is a bigger, harder-to-reverse call than flagging it pending). All 27 SAGE-only profiles recorded `SAGE_ONLY_UNASSESSED`. Whether to actually author the missing 5 SAGE profiles or the missing 27 SQS evaluation-pack sets is a product-prioritization and content-authoring decision, left open here.
- [x] Wrote the cross-catalog consistency test (`src/sage_sqs/language_coverage.py` + `tests/test_language_onboarding.py`): every SQS-seeded language and every SAGE grammar profile must have a manifest entry with a valid status for that catalog; `ONBOARDED` must be backed by a real entry on both sides (catches a profile silently removed from either side); a manifest entry matching neither catalog is flagged stale. Proven to actually catch drift (three dedicated tests construct broken states and assert the violation), not just pass vacuously on the current, already-consistent state (98/98 total, up from 93).
- [ ] **Noted fragility, not yet resolved**: `language_coverage.py` locates SAGE's grammar-profile directory via a relative filesystem path (`services/sqs` colocated with `app/` in this monorepo). Once the sibling-repo split (spec decision 4) happens, this check needs a different mechanism — SAGE exporting a checked-in profile-id list, or a live registry query — not a relative path assumption. Flagged in the module docstring; not solved now since the split itself is still deferred.
- [ ] Qualification testing itself keeps the existing monotonic boundary-search / single `minimum_reasoning` threshold design per spec decision 6 — this task is about which (model × language × capability) combinations get tested at all, not how each one is tested.

## Task 2 — Fix the defects found during recovery

- [x] Add `jsonschema` as a dependency (done as part of Task 1: it's a core runtime dependency now, not just `dev`, since `execution_channels.py` needs it outside tests).
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

- [ ] Extend `llm_settings.py`'s governed-provider allowlist to be validated against the same execution-channel descriptor catalog introduced in Task 1, rather than being an independent hardcoded list.
- [ ] Extend SAGE's language-profile loading (`registry.py`) to be checkable against SQS's language catalog from Task 1b, surfacing (not silently absorbing) any profile that's routable in SAGE but unqualified/unknown in SQS.
- [ ] Write the Task 1 and Task 1b cross-catalog consistency tests on the SAGE side too: a provider or language present in SQS's catalog but not SAGE's (or vice versa) fails closed with a clear error, never silently permits or silently drops it.
- [ ] Document both onboarding procedures (one short doc each, or one doc with two sections): what changes when a new provider is added, what changes when a new language is added, and where.

## Task 6a — Service availability / allowance checking (included allowance today, API credit later)

Distinct from Task 3a (reacting to a 429 mid-call): this is a proactive "is this connection currently usable" check, generalized per execution channel via the Task 1 descriptor catalog rather than special-cased to `codex_workspace`.

- [ ] Research, don't assume: does OpenAI's `chatgpt.com` web-session auth (what `codex_workspace`'s workspace/personal accounts both use) expose any queryable remaining-included-allowance signal today — a header, a status endpoint, anything — or is exhaustion only observable by hitting it (a 429)? Record the answer before designing around it.
- [ ] Add an `availability_check` field to the Task 1 execution-channel descriptor schema: how SAGE determines current usability for a given channel. Each channel gets its own check strategy — included-allowance and API-credit are different systems (session-based quota vs. an actual OpenAI platform billing/usage query), not one mechanism with two labels.
- [ ] Surface current availability per governed execution channel (e.g. via `sage model status` or existing model-service diagnostics) so an operator or task can know before committing to a run, not just discover it via a failed call.
- [ ] A future API-credit channel is a new execution-channel descriptor entry with its own `availability_check` (per Task 1's onboarding contract), added when that channel is actually enabled — not a special case bolted onto `codex_workspace` now. Enabling that channel itself stays out of scope here: `llm_settings.py`'s `openai_api_keys: PROHIBITED` is an explicit current policy and changing it is a separate decision, not implied by adding this check architecture.

## Task 7 — Acceptance gates

Reuse and adapt the recovered `05_ACCEPTANCE_TESTS/ACCEPTANCE_GATES.md` categories (current SAGE preservation, SQS source, publication trust/cache, transport/failover, discovery, routing authority, real local Mac socket test, packaging), re-verified against the actual integrated tree at completion — not assumed from the historical pack.

## Task 8 — Release/versioning

- [ ] Update `VERSIONING-POLICY.md` and `TODO.md` once SQS reaches a real milestone (e.g. Task 4 complete) — do not mark it done prematurely; both currently correctly say SQS is unimplemented.
- [ ] Decide, once `services/sqs/` is stable, whether to split it into `biblica/tools-sage-sqs` (spec decision 4 defers this, doesn't cancel it).

## Status

Task 0 in progress (baseline recovered and verified; commit pending). Tasks 1–8 not started.
