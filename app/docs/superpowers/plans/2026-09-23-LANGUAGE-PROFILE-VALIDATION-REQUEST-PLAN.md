# Language profile validation request: user-initiated onboarding — implementation plan

## The problem, stated plainly

`services/sqs/config/language-coverage-status.yml` (Task 1b's coordination manifest) currently
lists **27 SAGE grammar profiles with zero SQS qualification coverage**
(`SAGE_ONLY_UNASSESSED`). Closing each one requires a human to author real linguistic content —
a `seed/languages/<tag>.yml` identity record and per-capability evaluation-pack test cases — and
today there is no signal telling ADMIN which of those 27 (or which future new profile) an actual
project actually needs *right now*. The only existing mechanism, `POST /discoveries` with
`kind: LANGUAGE_PROFILE`, is passive, automatic telemetry — it stages an attention item but never
creates a profile row, and it carries no notion of urgency or real demand.

This plan adds a deliberate, user-initiated request: a SAGE operator, seeing their project's
language show `UNASSESSED` competency, can explicitly ask for it to be validated and tested. That
request reaches ADMIN as a distinct, prioritized signal; ADMIN finalizes the profile (still by
hand — this does not, and cannot, automate linguistic authorship) and triggers model testing
through the pipeline that already exists; the requesting SAGE host can check on progress instead
of being left to guess.

## The one finding that shapes this plan

A recent commit (`ac34761`, Task 5) discovered that **SAGE's live task routing has no language
dimension at all** — `skill_routing.py` is keyed purely on model/skill/suite identity, with no
connection to SQS's per-language qualification data. So even after this plan is fully built and a
language is fully qualified, nothing in SAGE's routing decisions consumes that fact yet. That is
confirmed **out of scope for this plan** (a separate, later integration) — but it means the
existing `model_language_competency.py` registry (whose `TRUSTED_EVIDENCE_SOURCES` already
includes `MEASURED_EVALUATION` as a first-class evidence kind) is the eventual landing point for
this data, not something invented here.

## What's reused cleanly

- **Profile lifecycle**: `seed/languages/<tag>.yml` → `load_seed_profiles()` → `REVIEW_REQUIRED`
  row → `AdminApp.approve_profile()` → `ACTIVE`. Unchanged.
- **Evaluation-pack authorship and format**: unchanged, still 100% human-authored linguistic
  content; nothing here scaffolds test *cases*, only the profile identity stub (per confirmed
  decision below).
- **Testing pipeline**: `AdminApp.queue_evaluation()` → `evaluation_runs` (`PENDING`) → either the
  existing `sqs-worker` timer (`api_key` channel) or the just-built admin-run local client
  (`codex_workspace` channel, `sage sqs list`/`sage sqs submit`) → `save_qualification()` →
  publish. Zero new testing-execution code.
- **Discovery outbox/transport**: `sqs_discovery.py`'s queue-first, never-blocks-governed-work
  pattern, and `sqs_client.py`'s ordered-failover HTTP transport. The new request is just a new
  discovery `kind`, not a new transport.
- **Attention-item staging and review**: `upsert_attention`/`list_attention`/`resolve_attention`,
  the same mechanism the Codex-workspace plan's `QUALIFICATION_SUBMISSION` staging already reuses.
- **SSH-only ADMIN console precedent**: no new authentication surface; this is more `AdminApp`
  methods callable the same way `approve_profile`/`queue_evaluation` already are.

## What's genuinely new

1. **A distinct request signal**, `kind: LANGUAGE_VALIDATION_REQUEST`, metadata-only like every
   other discovery kind (`profile_id`, `language_code`, `script`, `region`, `capability`,
   `sage_version` — no project identity, no content, same `_PROHIBITED`-field discipline
   `discovery.py` already enforces). Staged under its own attention `category`
   (`LANGUAGE_VALIDATION_REQUEST`, not the generic `DISCOVERY` category), so ADMIN's review queue
   visibly separates *"a user is blocked on this right now"* from ambient telemetry. Repeated
   requests for the same `(profile_id, capability)` accumulate via the existing
   `observation_count` mechanism — a real, privacy-preserving demand signal (SQS never learns
   which project or host asked, only that N hosts have asked).
2. **Per-capability granularity**: a request names one exact `capability`
   (`GRAMMAR_ANALYSIS`/`SEMANTIC_REWRITE`), not "the whole profile" — so ADMIN is never implicitly
   committed to authoring evaluation-pack content for a capability nobody has asked for yet.
3. **Seed-profile scaffolding**, `AdminApp.draft_language_profile_seed()`: writes
   `seed/languages/<profile_id>.yml` pre-filled from the request's `observed` payload
   (`language_code`/`script`/`region`, `status: DRAFT`, `capabilities: [<requested>]`,
   `profile_build.evaluation_pack_state: BUILD_REQUIRED`) when no profile row exists yet for that
   `profile_id`. Filesystem-only; ADMIN still fills in `tier`/`cluster`/`iso_639_3`/`display_name`
   and, separately and by hand, the actual evaluation-pack test cases — this narrows *boilerplate*,
   never *linguistic content*.
4. **A minimal status read-back**, `GET /language-requests/{profile_id}?capability=<capability>`,
   a small new read-only endpoint (not served from the public bundle, since the bundle only ever
   contains `ACTIVE`+published state) returning one coarse, derived status:
   - `NOT_REQUESTED` — no open request, no profile row.
   - `REQUESTED` — an open `LANGUAGE_VALIDATION_REQUEST` attention item exists.
   - `PROFILE_IN_PROGRESS` — a profile row exists but is `DRAFT`/`REVIEW_REQUIRED`.
   - `TESTING_IN_PROGRESS` — profile `ACTIVE`; a `PENDING`/`RUNNING` `evaluation_runs` row exists
     for this `(profile_id, capability)`.
   - `QUALIFIED` / `NOT_QUALIFIED` — a published qualification exists for this exact
     `(profile_id, capability)`, positive or negative.
   Reveals nothing beyond what's already implied by the public bundle plus one coarse enum per
   profile/capability — no project or host identity, matching the existing trust boundary.
5. **Client-side trigger and surface**: a `build_language_validation_request()` discovery builder
   (mirrors the existing `build_language_profile_discovery` exactly) queued from
   `configure_languages_menu`'s existing "Check competency for configured languages" flow — when a
   language's competency comes back `UNASSESSED`, SAGE now offers "Request language validation for
   `<capability>`" right there, plus a `fetch_language_request_status()` transport call so the same
   flow can show "SQS validation: REQUESTED" / "TESTING_IN_PROGRESS" / etc. next to the competency
   row, live (not cached via the bundle sync).

## Confirmed decisions

- [x] **Scope**: request → review → finalize profile → test → publish only. Wiring qualification
      results into SAGE's actual task routing is an explicitly separate, later plan.
- [x] **Request signal**: a new, distinct `LANGUAGE_VALIDATION_REQUEST` discovery kind and
      attention category, not a reuse of the passive `LANGUAGE_PROFILE` discovery.
- [x] **Status visibility**: add the minimal `GET /language-requests/{profile_id}` read-back,
      rather than leaving the requester silent until publication.
- [x] **Scaffolding tooling**: generate the seed-profile YAML stub only. No evaluation-pack
      skeleton — that remains entirely hand-authored, including its file structure.
- [x] **Trigger point**: offered inline from the existing "Check competency for configured
      languages" action when a language shows `UNASSESSED`, not a separate standalone menu item.
- [x] **Request granularity**: per-capability, not whole-profile.

## Build status: complete

- [x] Server side: `discovery.py`'s `validate_discovery` accepts `LANGUAGE_VALIDATION_REQUEST`
      (`profile_id`, `language_code`, `script`, `region`, `capability`, the latter restricted to
      `GRAMMAR_ANALYSIS`/`SEMANTIC_REWRITE`); `contracts/discovery.schema.json` gained the matching
      `oneOf` branch. Covered by real unit tests plus a real jsonschema round-trip
      (`test_contract_schemas.py`) and real API-level POST tests (`test_discovery_contract.py`).
- [x] Server side: `accept_discovery` now stages `LANGUAGE_VALIDATION_REQUEST` under its own
      attention `category`/`MEDIUM` severity with a demand-specific summary, instead of the
      generic `DISCOVERY`/`INFO` used for passive telemetry -- repeated requests for the same
      `(profile_id, capability)` still accumulate one attention item's `observation_count`, exactly
      as before.
- [x] Server side: `AdminApp.draft_language_profile_seed(*, profile_id, language_code, script,
      region, requested_capability, seed_dir)` writes the seed YAML stub (identity fields only;
      `tier`/`cluster`/`iso_639_3` are explicit sentinel placeholders that make the stub fail
      `validate_profile()` until ADMIN sets them by hand -- verified directly against the real
      `profile_validation.validate_profile()`), refuses to overwrite an existing file, and is
      audited like every other `AdminApp` mutation.
- [x] Server side: `Repository.language_request_status(*, profile_id, capability)` derives one of
      `NOT_REQUESTED`/`REQUESTED`/`PROFILE_IN_PROGRESS`/`TESTING_IN_PROGRESS`/`QUALIFIED`/
      `NOT_QUALIFIED` by checking the published bundle first, then in-flight `evaluation_runs`, then
      the `profiles` table, then open attention items -- most-advanced-evidence-wins. `GET
      /language-requests/{profile_id}?capability=...` exposes it; covered end to end for all six
      states plus the missing-query-param 422 case.
- [x] Client side: `sage.sqs_discovery.build_language_validation_request()` (mirrors
      `build_language_profile_discovery` exactly), validated against the real, shared
      `discovery.schema.json` in `test_sqs_discovery.py`.
- [x] Client side: `sage.sqs_client.fetch_language_request_status()` (mirrors
      `fetch_planned_evaluations`'s plain-GET, ordered-failover style), tested against a real local
      HTTP server.
- [x] Client side: `configure_languages_menu`'s "Check competency for configured languages" now
      calls `_offer_sqs_language_validation()` afterward -- for each `UNASSESSED` competency row, it
      shows live per-capability SQS status (best-effort: silently skipped if no SQS endpoint is
      configured, shows `UNREACHABLE` per row rather than failing the whole competency check if a
      request errors) and, if any capability is `NOT_REQUESTED`, offers to queue a request to the
      existing discovery outbox for the next `sage model sqs-sync` to flush.
- [x] Contracts: `contracts/discovery.schema.json` extended; no new schema file needed for the
      status endpoint's plain derived-enum response, as anticipated.

Full test suites green: 132/132 SQS-side, 2200+/2200+ app-side (documentation-contract and
menu-localization contracts included -- the new `choose()` title and menu item both required
catalog entries across all six interface languages, caught and fixed by those same contracts).
