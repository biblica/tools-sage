# SQS Codex-workspace qualification: admin-run local client — implementation plan

**Replanned per explicit direction, superseding the headless-server-worker design this document
originally held.** Closes the same gap Task 1 of
[2026-09-18-SQS-INTEGRATION-PLAN.md](2026-09-18-SQS-INTEGRATION-PLAN.md) flagged: no code path
can currently produce a truthful `execution_channel: codex_workspace` qualification. The
*shape* of the fix has changed; the gap it closes hasn't.

## The new model, stated plainly

- **SQS vetting/testing runs as a local client on an ADMIN's own machine — and that local
  client is SAGE itself**, not a new standalone binary and not a headless server process. An
  admin already has an authenticated Codex CLI session on their own machine for ordinary SAGE
  work; this reuses that session directly, the same way any other governed SAGE task does.
  **This eliminates the entire headless-authentication problem the original version of this
  plan researched in depth** (device-code flow, workspace-admin enablement, `$CODEX_HOME`
  systemd scoping, session-persistence cadence) -- there is no headless host in this design.
  That research isn't wasted (kept below as a deprioritized appendix, in case a true unattended
  drain loop is ever wanted later), but it is no longer on the critical path.
- **The client pulls a work queue from SQS** -- which (model, profile, capability) combinations
  still need testing -- rather than the admin picking blind.
- **The client uploads the resulting qualification data to the SQS service; other SAGE
  installations harvest it** through the exact publication path that already exists and is
  already fully built (`GET /bundle`, `sqs_client.py` + `sqs_cache.py`, Task 3/4). The
  *consumption* side of this integration needs no new work at all -- this plan is entirely
  about the *production* side, which has never existed.

## What's reused cleanly, and why this shape is better than the superseded one

- **SAGE's own `executors/codex_cli.py::CodexCLIExecutor` is used directly, in-process --
  zero duplication.** The superseded plan's entire `CliShellProviderAdapter` base class
  (subprocess plumbing, rate-limit classification, timeout/process-tree cleanup, re-implemented
  a second time inside `services/sqs`) is no longer needed. This client runs on a SAGE machine,
  as SAGE, so it's the *same* trust boundary SAGE's own governed tasks already run in --
  including Task 3a's just-built bounded rate-limit retry, reused as-is with no rework.
- **`services/sqs`'s evaluation logic is portable and reusable as a library, not just as a
  service.** Confirmed by reading it: `evaluation/runner.py::run_planned_test` and
  `evaluation/scoring.py::score_attempt` take plain dataclasses (`EvaluationPack`,
  `ProviderAdapter`, `ModelRecord`) with no database/repository coupling -- that coupling lives
  only in `Worker.run_once()`, which this design doesn't use. SAGE can depend on the
  `sage_sqs` package (already structured as an installable library --
  `src/tools_sage_sqs.egg-info` confirms it's already packaged that way) the same way it
  depends on any other pinned library, and call `run_planned_test`/`score_attempt` directly for
  the actual boundary-search and scoring logic, rather than re-deriving it.
- **The one real adapter piece still needed is small: a `ProviderAdapter`-shaped bridge over
  `CodexCLIExecutor`.** The two interfaces are close but not identical --
  `Executor.execute(request: ProviderRequest) -> ProviderResponse` (SAGE's shape, schema-aware)
  vs. `ProviderAdapter.execute(*, model_id, reasoning, prompt) -> ProviderResult` (SQS's shape,
  plain text) -- so a thin translation class is required, not a re-implementation of Codex
  execution itself.
- **Reporting reuses the existing outbound transport, per direction.** `sqs_client.py`'s
  endpoint-failover/loopback-HTTPS handling and `sqs_discovery.py`'s outbox-first pattern (Task
  4) already solve "queue locally, flush over HTTP with failover" for discovery data. The same
  mechanism extends to submitting qualification results rather than inventing a second
  transport stack.

## What's genuinely new and not yet built — the real scope of this plan

Confirmed directly against `services/sqs/src/sage_sqs/api.py`: today's HTTP surface is
**`GET /health`, `/profiles`, `/profiles/{id}`, `/models`, `/qualifications`, `/bundle`, and
`POST /discoveries`** -- read-only publication plus one write endpoint for low-trust discovery
metadata. Its own module docstring says exactly this: *"Public read-only SQS publication API
plus metadata-only discovery intake."* Two real gaps follow from that:

1. **No endpoint exists for a remote client to learn what needs testing -- confirmed:
   non-exclusive list, not a claim.** `Repository.claim_next_evaluation()` already exists and
   already backs the same "what's next" logic `Worker.run_once()` uses today -- but only for a
   caller with direct database access on the same host, and it's *exclusive* (built for a
   worker loop where concurrent workers must not duplicate the same test). This client isn't
   that: it's occasional and human-triggered, so exclusive-claim machinery (lock ownership,
   claim timeouts, releasing an abandoned claim if a client crashes mid-run) is real complexity
   this use case doesn't need -- two admins picking the same item at the same moment is rare,
   and if it happens the cost is just a redundant test run, not a correctness problem
   (`qualifications` are already keyed on `(provider_family, model_id, profile_id, capability)`,
   so a second submission for the same key is an ordinary update, not a conflict).
   **Confirmed: a plain `GET`-style list endpoint** (e.g. `GET /planned-evaluations`),
   read-only and stateless like the rest of the existing API (`/profiles`, `/models`,
   `/qualifications`) -- fitting the module's own "public read-only" framing rather than adding
   the first piece of server-side mutable session state. It still needs to expose the *real*
   planning logic behind `claim_next_evaluation()` (which reasoning level to start a
   boundary-search from, informed by `model_predecessors`/prior evidence) rather than have the
   client re-derive that client-side, which would duplicate logic that already exists on the
   server -- same reasoning already applied elsewhere in this plan to reusing `sage_sqs`'s
   evaluation package instead of reimplementing it.
2. **No endpoint exists for submitting a qualification result, and -- more importantly -- no
   authentication/authorization exists anywhere in this API at all.** Confirmed by reading the
   whole of `api.py`: no `Authorization` header handling, no API key, no bearer token, nothing
   -- `/discoveries` is genuinely open to anyone who can reach the server. A qualification
   *result* is a materially higher-trust write than a discovery: it becomes evidence other
   installations' routing decisions depend on once published. Submitting it as "ADMIN users"
   implies there needs to be an actual identity/trust concept for who's allowed to submit at
   all -- **this doesn't exist in the codebase today and is the single biggest new piece of
   scope this plan introduces**, bigger than the client itself. Two sub-questions, deliberately
   left open rather than assumed:
   - **Authentication mechanism -- credential location decided, per direction; transport
     mechanism now redirected to SSH, per direction, superseding the UN/PW-over-HTTP design
     this section held a turn ago (that design kept below, not deleted, since some of it --
     the credential-location and login-before-upload requirements -- still applies).** The
     admin's SQS submission credential is configured through SAGE's existing **SAGE
     MAINTENANCE** menu (`menu.py::system_configuration_menu`, currently `1. Configure AI,
     2. Configure languages, 3. Configure paths and storage, 4. Run system checks,
     5. Resource Status Report, 6. System actions`) -- a new item there, not a new top-level
     menu. Storage-wise, this fits the existing `app/system/config/sqs.yml`
     (`schema sage-sqs-1.0`) config file and its `SqsCache.from_config(...)`/
     `load_sqs_config()` loader (Task 4) -- that file already holds the *consumption*-side
     trust config (`trusted_authority_id`, `require_signature`, `trusted_signing_keys`); a
     submission credential is the natural *production*-side counterpart to add there.

     **Confirmed shape: SSH key-based auth, not a custom username/password system.** SSH
     authentication is a mature, already-trusted mechanism (`authorized_keys`, standard key
     management) that needs essentially none of the new code a password system would --  no
     password hashing, no login endpoint, no session/token issuance, no rate-limiting/lockout
     design, no HTTPS-vs-loopback question for a login exchange. The trust boundary becomes
     "does this admin's SSH key appear in the server's authorized set," which is exactly the
     kind of thing SSH already does well and this project doesn't need to reinvent. Concretely,
     two shapes were weighed:
     - **(a) SSH/SCP-SFTP as the actual submission transport**, bypassing the FastAPI app for
       this path entirely: the client pushes its qualification-result file directly onto the
       server (e.g. into a designated `incoming/` directory under `/var/lib/sage-sqs/`) over
       SFTP/SCP using the admin's SSH key; a new server-side ingest step (a small
       watcher/poller, or the existing `Worker`-style draining pattern adapted to pull from
       that directory instead of the DB's evaluation queue) validates and processes newly
       arrived files into `repo.save_qualification(...)`. `GET /bundle` and the other existing
       read-only endpoints are untouched; only the write path changes. This is the simpler
       shape and the one this plan currently leans toward.
     - **(b) SSH as a tunnel in front of the existing HTTP API**: the client opens an SSH
       connection (key-authenticated) to the server and tunnels the same `POST /qualifications`
       -style request through it, so the FastAPI app still handles the submission logic, just
       reachable only through an authenticated SSH tunnel rather than directly. Keeps the
       "everything is an HTTP endpoint" shape from the superseded design, at the cost of some
       tunnel-setup complexity on the client side that shape (a) doesn't need.
     - **Client requirement, per direction, unchanged regardless of (a) or (b): the SAGE-side
       client authenticates before it attempts to upload** -- SSH connection establishment
       itself is that auth step (you cannot transfer a file or reach the tunnel at all without
       a valid, authorized key), so this requirement is satisfied structurally rather than
       needing an explicit "login" call the way the password design did. A connection/auth
       failure (key not authorized, host unreachable) should still be raised as its own
       distinct, clearly reported error, same "fail with a specific, actionable reason"
       discipline used for Codex CLI failures.
     - **(a) vs (b) -- confirmed: (a), SCP/SFTP file-drop.** A tunnel (b) adds a second
       lifecycle the client has to manage and keep in sync (the tunnel process and the HTTP
       request riding it), for no benefit here since the server doesn't otherwise need the
       submission path to look like the other HTTP endpoints -- a single, well-defined SCP/SFTP
       transfer per submission is simpler to reason about, simpler to test, and fails in fewer,
       clearer ways. The one new piece this needs -- a small ingest step -- can be genuinely
       small: files land in `incoming/`, get validated, and get atomically moved to
       `processed/` or `rejected/` (mirroring the atomic-write discipline `sqs_cache.py`/
       `atomic_write_json` already use elsewhere in this integration, so a partially-written or
       double-processed file can't happen), polled on the same kind of cadence `Worker.run_once`
       already polls its DB queue on -- not a new architectural pattern, the same one reapplied
       to a directory instead of a table.
     - **Key provisioning -- confirmed: the SAGE MAINTENANCE menu item generates and manages
       a dedicated keypair, not the admin's personal one.** Purpose-scoped to SQS submission
       only, so it can be revoked/rotated without touching whatever else that admin uses SSH
       for -- better hygiene than pointing at an existing general-purpose key. `cryptography`
       (already pinned) can generate an Ed25519 keypair and serialize it to OpenSSH format
       directly, no new dependency. The menu stores the private key locally with the same
       restrictive permissions Codex CLI's own `auth.json` already uses (`0600`, confirmed
       during the earlier research above) and displays/exports the public key for the admin to
       hand to whoever operates the SQS server.
     - **Getting that public key onto the server -- still genuinely manual, and left that way
       deliberately.** An operator appending a line to a dedicated system user's
       `authorized_keys` (e.g. an `sqs-uploader` account scoped only to the `incoming/`
       directory, not general shell access) is standard, well-understood SSH administration --
       no new server-side code is required for this part at all. This mirrors the same
       one-time, low-frequency manual ceremony already accepted elsewhere in this plan (the
       ChatGPT workspace-admin device-code enablement, in the appendix below) -- consistent
       with not inventing new automation for something that happens rarely and needs a human's
       judgment anyway (deciding whether to trust a given admin with submission access at all).

     <details><summary>Superseded: username/password + HTTP login design (kept for reference,
     not the current direction)</summary>

     A new `admins`/`users` table in `db.py` storing a username and a **hashed** password
     (`cryptography==50.0.1`'s `Scrypt`/`PBKDF2HMAC`, already pinned, no new dependency); a
     `POST /auth/login` endpoint issuing a bearer token on success; the client calling
     `login → submit`. Dropped in favor of SSH because it duplicates trust machinery SSH
     already provides for free -- kept here only so it isn't silently lost if SSH turns out to
     be impractical for some deployment and this needs revisiting.
     </details>
   - **Trust/review model on submission -- confirmed: `REVIEW_REQUIRED`, not auto-publish.**
     Mirrors the pattern `catalog.py::sync_provider_catalog` already uses for model-metadata
     changes (`upsert_attention` + `REVIEW_REQUIRED` status, requiring explicit ADMIN approval
     before a changed/new model is trusted) -- nothing else in this codebase currently
     auto-trusts externally-submitted data, and this would be the first exception if it
     auto-published. Worth being explicit about *why* SSH-authenticating the submitter doesn't
     settle this on its own: the SSH key answers "is this admin allowed to submit at all," a
     question about *identity*; review answers "is what they submitted actually sound," a
     question about *content* -- even a fully trusted admin's run could reflect a stale
     evaluation pack, an uncaught transient issue, or a simple mis-selection, and those are
     exactly what a review step exists to catch. The two concerns are orthogonal, so resolving
     identity via SSH doesn't argue away the need for the existing content-review precedent.
     Given a published qualification becomes evidence every other SAGE installation's routing
     decisions can depend on, matching the codebase's existing, more conservative default here
     is the confirmed direction.

## Confirmed decisions and remaining build steps

- [x] **Confirmed, all four, per direction:** (a) SCP/SFTP file-drop into an `incoming/`
      directory, not an SSH tunnel in front of the HTTP API. SAGE MAINTENANCE menu generates
      and manages a dedicated (not personal) Ed25519 keypair via the already-pinned
      `cryptography` library; the admin hands the public key to whoever operates the SQS server
      to append to a dedicated system user's `authorized_keys` -- a deliberately manual,
      one-time step, no new server-side provisioning code needed for that part. Work-queue
      endpoint is a plain, stateless `GET /planned-evaluations` list, not an exclusive claim --
      exposing the same planning logic `claim_next_evaluation()` already has, just read-only.
      Trust/review model is `REVIEW_REQUIRED`, matching the existing `sync_provider_catalog`
      precedent -- not auto-publish. None of the open design questions remain; the plan is
      ready to move from design into building the contracts below.
- [x] Server side, built and test-first covered: `Repository.list_pending_evaluations()`
      (non-mutating sibling of `claim_next_evaluation()`) and its `GET /planned-evaluations`
      route; `sage_sqs.ingest` (`validate_submission`/`stage_submission`/
      `ingest_incoming_directory`) validates a dropped submission file against the new
      `contracts/qualification-submission-1.0.schema.json`, cross-checks it against the
      `evaluation_runs` row it claims to fulfil, and stages it as a `QUALIFICATION_SUBMISSION`
      attention item -- it never calls `save_qualification()` itself. Files move atomically
      (`os.replace`) from `incoming/` to `processed/` or `rejected/`. Packaged as the `sqs-ingest`
      console script plus `deploy/systemd/sqs-ingest.{service,timer}`, mirroring `sqs-worker`'s
      one-shot-drain-on-a-timer shape exactly. `AdminApp.review_qualification_submission()` is
      the explicit APPROVE/REJECT step: APPROVE reconstructs the `Qualification` from the staged
      payload, saves it, completes the run, and resolves the attention item; REJECT fails the
      run instead. Still open: the dedicated `sqs-uploader`-style system account (OS-level
      `authorized_keys` provisioning, scoped only to `incoming/`, no shell) is a deployment-time
      manual step, not code -- nothing to build there beyond documenting it when the server is
      actually provisioned.
- [x] Client side, built and test-first covered: `sage.sqs_submission_key` generates/rotates a
      dedicated Ed25519 keypair via the already-pinned `cryptography` library (private key
      written 0600, public key is a standard OpenSSH line the admin hands to whoever operates the
      SQS server); wired into `system_configuration_menu`'s **SAGE MAINTENANCE** menu as item 7,
      `_sqs_submission_key_menu()`, with an explicit typed `ROTATE` confirmation before replacing
      a live key. `sqs.yml`/`sqs.schema.yml` gained an optional `submission` section (`ssh_host`,
      `ssh_port`, `ssh_user`, `remote_incoming_dir`) for the non-secret SCP/SFTP target -- the
      private key itself never lives in that file, only in localdata's SQS state directory.
      Still open: the actual SCP/SFTP upload call (the "submits the result" half of the SAGE-side
      surface item below) and its own connection/auth-failure error code -- not yet built.
- [x] Contracts: `contracts/qualification-submission-1.0.schema.json` defines the incoming-result
      file's payload (`schema`, `run_id`, `submitted_by`, `submitted_at`, full `qualification`
      dict, `attempt` diagnostics), mirroring `contracts/discovery.schema.json`'s versioned-schema
      pattern; cross-checked against the Python validator in
      `tests/test_contract_schemas.py::test_qualification_submission_contract_matches_wire_vocabulary`.
      The work-queue read endpoint's contract is just `list_pending_evaluations()`'s plain dict
      shape (`id`, `provider_family`, `profile_id`, `model_id`, `capability`, `reasoning`,
      `scope`) -- no separate schema file was judged necessary for a GET response this shaped.
- [x] SAGE-side surface, built and test-first covered: `sage sqs list` (`GET /planned-evaluations`
      via the new `fetch_planned_evaluations` transport function, read-only) and
      `sage sqs submit --run-id <id>` (matching the `sage model sqs-sync` CLI precedent -- not
      wired into an interactive menu, since this is a scripted ADMIN power-user action, same as
      `sqs-sync` itself). `sage.sqs_submission_flow.prepare_submission` is the orchestration core:
      looks up the model/profile from the already-cached, already-validated local bundle
      (`SqsCache.load_current()` -- reusing Task 4's trust validation, no new network trust
      surface), loads the exact evaluation pack from the sibling `services/sqs/config/
      evaluation-packs/` checkout, runs it through `run_planned_test` with the Codex-workspace
      bridge, and synthesizes the qualification -- all pure/duck-typed against the bundle's public
      dict shape (`_BundleProfile`/`_BundleModel`), never reconstructing full `sage_sqs` domain
      objects. `write_submission_file` writes it atomically; `upload_submission_file` SCPs it with
      `BatchMode=yes` (fails fast/closed on auth or host-key failure rather than hanging on a
      prompt with no terminal to reach -- normal host-key verification still applies, deliberately
      not disabled). `sqs submit` fails closed with its own distinct `reason_code` at every
      prerequisite gap (no endpoint, no generated key, no cached bundle, unknown run id), verified
      by real subprocess CLI tests; the full run-through-Codex happy path is verified at the
      Python level with a `FakeProvider`, matching this project's established precedent for
      Codex-touching tests (a live, authenticated Codex CLI is not something a test suite can
      depend on).
- [x] `sage_sqs` as a dependency of SAGE, resolved by investigation, not by assumption: it is
      **not** a pip dependency. Its full package needs `fastapi`/`pydantic`/`uvicorn` (SQS's own
      HTTP server, irrelevant to SAGE), but the narrow slice the bridge actually needs --
      `sage_sqs.evaluation.runner`, `sage_sqs.qualification`, `sage_sqs.domain`,
      `sage_sqs.providers.base`/`openai_provider` -- was confirmed by a real import in an
      environment with none of those three packages installed to need only stdlib plus the
      already-pinned `PyYAML`. `sage.sqs_provider_bridge.ensure_sage_sqs_importable()` adds the
      sibling `services/sqs/src` checkout path to `sys.path` at runtime, the in-process analogue
      of the existing `system/src` sibling-path precedent in `menu.py`'s `controller()`. Real
      remaining caveat, not resolved here: this assumes `services/sqs` ships alongside `app/` on
      hosts that run SQS vetting -- not verified against a fully portable, code-signed SAGE Core
      bundle that might omit it.
- [x] `sage.sqs_provider_bridge.CodexWorkspaceProviderAdapter`, test-first covered: implements
      `sage_sqs`'s `ProviderAdapter.execute(*, model_id, reasoning, prompt)` over SAGE's own
      `CodexCLIExecutor.execute()` in-process (zero duplication, inherits Task 3a's bounded
      rate-limit retry for free), using a permissive `{"type": "object"}` output schema since
      `sage_sqs` validates response shape itself rather than needing provider-side schema
      constraint. Known, explicitly flagged gap (not fabricated): `CodexCLIExecutor` never runs
      `codex exec --json`, deliberately -- its rate-limit detection depends on plain-text
      stdout/stderr, and adding `--json` risks changing that on the failure path too (confirmed
      by `codex_cli.py`'s own module comment), so this bridge reports `input_tokens`/
      `output_tokens` as `None` rather than fabricating numbers; `sage_sqs.evaluation.runner`
      already treats `None` as zero cost/usage rather than raising. Capturing real Codex token
      usage safely is a separate, not-yet-scoped follow-up.
- [x] `system/requirements.txt` gained `cryptography==50.0.1`, `cffi==2.1.1`, `pycparser==3.0` --
      a real, pre-existing gap found during this work: `sqs_cache.py` (Task 4) already imported
      `cryptography` for Ed25519 bundle-signature verification, but it was never added to SAGE's
      pinned, `--no-deps` runtime manifest, so a fresh bootstrap install would have failed to
      import it. Fixed as part of adding the second real consumer (`sqs_submission_key.py`).

## Appendix: headless-server research, kept for reference, not currently on the critical path

The original version of this plan researched, in real depth, how a headless `sqs-worker`
systemd process could authenticate Codex CLI without a human present. That research is real,
sourced, and still potentially useful if an unattended server-side drain loop is ever wanted in
the future (e.g. if per-admin manual runs don't scale to the actual testing volume needed) --
but it does not apply to the admin-run local-client model above, so it's kept here rather than
in the main body:

- Device-code login (`codex login --device-auth`) is OpenAI's documented mechanism for headless
  auth, confirmed via `learn.chatgpt.com/docs/auth`, but requires explicit enablement by a
  ChatGPT **workspace admin** first (confirmed via the same docs and a real reported failure,
  [openai/codex#9253](https://github.com/openai/codex/issues/9253)) -- off by default,
  deliberately, for phishing-risk reasons.
- Token refresh is automatic during active use per OpenAI's own docs; exact outer refresh-token
  lifetime isn't officially documented (third-party figures suggest roughly 8-10 days,
  unconfirmed).
- Credential storage is `$CODEX_HOME` (default `~/.codex`), a real independent override
  confirmed by running `CODEX_HOME=/tmp/codex-home-test codex login status` locally --
  `auth.json` is written `0600` by the CLI itself. For a systemd deployment under
  `ProtectSystem=strict`, this would need scoping into the unit's own `ReadWritePaths` rather
  than relying on the service account's real `$HOME`.
- `codex login --with-access-token` (reads a token from stdin) is a real, documented,
  scriptable provisioning primitive distinct from the interactive device-code flow --
  confirmed via `codex login --help` -- though whether a token provisioned this way persists
  as a properly refreshable session or is itself short-lived was never confirmed before this
  plan's direction changed.
- `codex login status` is a clean, scriptable health-check primitive (confirmed real output:
  `"Not logged in"`, non-zero exit, when unauthenticated) that could support a proactive
  "session is dead" check rather than only reactive failure classification.

None of this blocks the current plan. It's preserved here so it doesn't need re-researching if
the architecture ever needs this shape again.
