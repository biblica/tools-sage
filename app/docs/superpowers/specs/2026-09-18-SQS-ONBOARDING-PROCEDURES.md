# SQS provider and language onboarding procedures

Date: 2026-09-18.
Status: current. Companion to [2026-09-18-SQS-ARCHITECTURE-EVALUATION.md](2026-09-18-SQS-ARCHITECTURE-EVALUATION.md) and [2026-09-18-SQS-INTEGRATION-PLAN.md](../plans/2026-09-18-SQS-INTEGRATION-PLAN.md) (Task 6). Both procedures below exist because two independently-maintained catalogs (SAGE's and SQS's) will silently drift apart unless onboarding is one coordinated action, enforced by a test on each side.

## Provider onboarding

Adding a new governed provider to SAGE (or a new access channel to an existing one) requires touching all of the following in one change:

1. `services/sqs/contracts/execution-channel-descriptor.schema.json` — only if the new channel needs a genuinely new descriptor field; usually unchanged.
2. `services/sqs/seed/execution-channels/<channel>.yml` — a new descriptor: `execution_channel`, `provider_family` (the model vendor — may already exist, e.g. `openai`, if this is a second channel to a vendor SQS already knows), `display_name`, `provisioning_model` (`workspace` or `api_key`), `capability_classes`, `reasoning_tier_taxonomy`.
3. `app/system/src/sage/build_policy.py`'s `ENABLED_AUTOMATED_PROVIDER_IDS` — add the SAGE-side provider id (only once the provider is actually ready to be governed, not just described).
4. `app/system/src/sage/sqs_provider_coverage.py`'s `SAGE_PROVIDER_TO_EXECUTION_CHANNEL` — add the SAGE provider id → SQS execution_channel mapping. The two ids are allowed to differ (e.g. `codex` ↔ `codex_workspace`) because they name different things: SAGE's provider id, and SQS's access-channel id — see the architecture spec's two-field provider identity decision.

Verification: `pytest tests/test_sqs_provider_coverage.py` (SAGE side) and the equivalent cross-catalog test in `services/sqs/tests/test_execution_channels.py` (SQS side) both fail closed if any of the above is missed — a provider present on one side without the corresponding entry on the other is a hard error, not a warning.

Enabling API-key/API-credit access specifically (as opposed to a new workspace-style channel) additionally requires reversing `app/system/config/*` policy that currently prohibits it (`llm_settings.py`'s `openai_api_keys: PROHIBITED`) — that is a distinct governance decision, not implied by adding a descriptor.

## Language onboarding

Adding a new language profile requires touching all of the following in one change:

1. `app/system/config/profiles/grammar/<tag>/` — the new SAGE grammar profile (plus its registry entry, per SAGE's existing language-profile conventions — unrelated to SQS).
2. `services/sqs/seed/languages/<tag>.yml` — the new SQS language seed (identity, `tier`, `cluster` for SQS's own planner grouping — see the architecture spec's decision that SQS derives these from SAGE's authoritative data, not hand-authored duplicates, where practical).
3. `services/sqs/config/evaluation-packs/<tag>-grammar-analysis-r1.yml` and `<tag>-semantic-rewrite-r1.yml` — the actual qualification test content. **This step requires real linguistic subject-matter review, not fabrication** — it encodes ground truth about correct grammar/semantic-rewrite behavior for that language. Do not author placeholder or guessed content here.
4. `services/sqs/config/language-coverage-status.yml` — record the profile's status: `ONBOARDED` once steps 1–3 are all done, or `SAGE_ONLY_UNASSESSED` if step 1 landed but 2–3 haven't yet (a legitimate, tracked intermediate state — SAGE routing sees this as `UNASSESSED`, not silently missing).

Verification: `pytest tests/test_sqs_language_coverage.py` (SAGE side) and `services/sqs/tests/test_language_onboarding.py` (SQS side) both fail closed on a profile present in one catalog without a manifest entry, or a manifest entry whose status doesn't match reality.

As of this writing, 27 of SAGE's 44 grammar profiles are recorded `SAGE_ONLY_UNASSESSED` (step 3's content was never authored for them) and 5 SQS-seeded languages are recorded `SQS_ONLY_PENDING_SAGE_PROFILE` (distinct locales SAGE hasn't onboarded a profile for at all) — see the architecture spec §5 item 7 and §6 decision 5 for the full reconciliation and why each of the 5 isn't simply a tag mismatch.

## What this does not cover

Neither procedure connects onboarded evidence to live governed routing yet. Per the architecture spec §8 item 8 and the integration plan's Task 5, SAGE's routing identity (`skill_routing.py`) has no language dimension at all today, so even a fully `ONBOARDED` language/provider pair has no route to attach to until that separate, larger design decision is made.
