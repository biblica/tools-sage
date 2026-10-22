# Claude Code CLI provider — implementation plan

**Status:** Phase 1 implemented 2026-10-22 (`executors/claude_cli.py`, `executors/cli_process.py`,
`data/claude-catalog.json`, `tests/test_claude_cli_executor.py`); one live Haiku smoke call passed
with an API key present in the parent environment. Phase 2 implemented 2026-10-22 (see "Phase 2
as built"). Phases 3-5 open.

## Decisions (PO, 2026-10-22)

- Claude is reached through the **Claude Code CLI with the Operator's own subscription login**, exactly
  as Codex is reached through the Codex CLI with ChatGPT login. No API-key, auth-token, or
  service-account path is introduced; SAGE never reads, stores, or forwards a Claude credential.
- **One selected provider (Codex or Claude) serves all governed and hosted LLM work** in an
  installation: BIC/RTC/STC Skills, NCA, report translation, connectivity tests, and the local SQS
  qualification client. Every Run receipt records the provider.
- **Optional local Ollama stays as it is**: the capability-restricted administrative assistant,
  independent of the selected provider, never with workflow authority.
- Provisional default reasoning for Claude is `medium`, with `low` administrative-only (mirrors
  Codex); revisit after Phase 4 evidence.

## Why this is mostly de-hardcoding

`executors/base.py` already defines the `Executor` seam and `executors/__init__.py::make_executor` is
the registry. Every Codex call is a sealed one-shot (`codex exec --ephemeral --sandbox read-only`, empty
temp cwd, schema-constrained output, SAGE does all writes). No call relies on agentic editing,
threads, or resume, so a Claude adapter can satisfy every call site. The bulk of the work is ~40
`codex` literals across settings, menus, UI, CLI, policy, and workflow profiles.

`tools/qualify_nca.py::claude_judge` already calls the Claude CLI in the target shape (`-p`,
`--tools ""`, `--setting-sources ""`, `--strict-mcp-config`, `--json-schema`, `structured_output`).

## Phase 0 — Ground rules (no code)

1. Biblica legal confirms the Claude Code terms reading: running the **unmodified** binary where each
   end user signs in with their **own** subscription is permitted; collecting/storing/intermediating
   Claude.ai credentials is not. Consequence: SAGE never uses `claude setup-token` or sets
   `CLAUDE_CODE_OAUTH_TOKEN`. Sources: code.claude.com/docs/en/legal-and-compliance.
2. Out of scope: the SQS server-side worker (`services/sqs/.../openai_provider.py`, API-key based) and
   any remote deployment (see SQS remote-deploy security requirements).

## Phase 1 — `executors/claude_cli.py::ClaudeCLIExecutor`

1. **Invocation** (prompt on stdin — Windows argv limits rule out passing ACT-sized prompts as an
   argument; cwd = empty temp dir):

   ```text
   claude -p --output-format json --json-schema <schema> --model <id> --effort <level>
          --tools "" --restricted --setting-sources "" --strict-mcp-config
          --no-session-persistence --max-turns 1
   ```

   Never `--bare` (it ignores subscription login). Never `--fallback-model`.
2. **Environment:** reuse the Codex allowlist approach (`codex_cli.py` env builder). Explicitly drop
   `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, and
   `CLAUDE_CODE_USE_BEDROCK|VERTEX|FOUNDRY`. In `-p` mode an API key silently outranks the
   subscription.
3. **`status()`:** `claude --version` with a minimum-version gate (needs `--restricted`,
   `--json-schema`, `--effort`); `claude auth status` (JSON, exit 0/1) must report
   `authMethod == "claude.ai"` — the analogue of Codex's `account.type == "chatgpt"`.
4. **Response:** `structured_output` → `ProviderResponse.content` (absent → schema failure, same path
   as Codex). `modelUsage` keys → answering model, fed to `_validate_provider_response_route`.
   `usage` (input/output/cache tokens) → `metadata` — the first real token counts on the main path.
   `total_cost_usd` is a client-side estimate and is not recorded as spend.
5. **Limits/errors:** classify "session limit" / "weekly limit" / "Opus limit" alongside the Codex
   rate-limit regexes, same single short retry; "Not logged in" / "Login expired" → login guidance.
   Never-hard-block applies: a limit pauses or reports the Run. Before writing the classifier,
   **measure** the installed build's exit code and result `subtype` for usage limits and
   `--max-turns` exhaustion (undocumented).
6. **Catalog:** the Claude CLI has no `model/list`; a reviewed static catalog ships as package data
   `src/sage/data/claude-catalog.json` (executors receive no Core root). It lists ids and native
   efforts only; the `low` = administrative-only classification belongs to `model-policy.yml`
   (Phase 3). No model is classified Instant by name; unreviewed models stay `UNASSESSED`.

   **As built / observed (Claude Code 2.1.307):** failures exit 1 with a JSON result carrying
   `is_error: true`, `api_error_status`, and the message in `result` (`subtype` stays `success`).
   `USER` must be in the env allowlist or the macOS keychain login is not found. Governed calls
   replace Claude Code's system prompt (`--system-prompt`) and set `DISABLE_AUTOUPDATER=1`.
   Prompt input tokens arrive mostly as `cache_creation_input_tokens`; Phase 3 calibration must sum
   `input + cache_creation + cache_read`. The subscription usage-limit wording is still from the
   docs, not observed live.
7. **Tests:** fake-subprocess suite in the style of `test_llm_harness.py` /
   `test_codex_rate_limit_detection.py`: stripped env, non-subscription auth refused, missing
   `structured_output`, model mismatch, limit messages, stdin prompt.

## Phase 2 — Provider selection and de-hardcoding

1. `make_executor` gains `claude`; `build_policy.IMPLEMENTED_PROVIDER_IDS` gains `claude`
   (`ENABLED_AUTOMATED_PROVIDER_IDS` waits for Phase 4).
2. `llm_settings.py`: the selected provider is `codex | claude` (unknown still falls back to codex);
   per-provider allowed keys stay `enabled` only.
3. Replace `codex` literals with the selected provider: `model_service.py`, `model_policy.py`
   defaults, `llm_tasks.py` catalog cache, `numbers/model_tasks.py`, `cli.py`, `ui_services.py`
   (provider label), and the `menu.py` `list_models(...)` / `language_competency_status(...)` calls.
4. Receipt policy `"openai_api_keys": "PROHIBITED"` → provider-neutral `provider_api_keys`. Existing
   receipts are not migrated (LEGACY rule).
5. Setup menu: provider choice; install (native installer guidance), update (`claude update` +
   minimum-version gate; no release polling), login (hand the terminal to `claude auth login`, SAGE
   stays parent process).
6. Local SQS qualification client: `sqs_provider_coverage.py` / `sqs_provider_bridge.py` /
   `sqs_submission_flow.py` follow the selected provider; add a `claude_workspace` execution-channel
   descriptor beside `codex-workspace.yml` (`provider_family: anthropic`).

### Phase 2 as built

- `build_policy`: `IMPLEMENTED_PROVIDER_IDS = (codex, claude, ollama)`, new
  `GOVERNED_CLI_PROVIDER_IDS = (codex, claude)`; enablement is read at call time
  (`enabled_provider_ids()`), so Phase 4 is a one-line change. Claude stays disabled until then: a
  persisted Claude selection falls back to Codex, and signing in to Claude does not select it.
- `executors`: `cli_executor()`, `provider_labels()` (operator-facing names), and
  `receipt_transport_policy()`. Receipts now record `provider_api_keys: PROHIBITED` and
  `provider_catalog: LIVE | REVIEWED_STATIC` in place of `openai_api_keys` /
  `live_provider_catalog_required` (old receipts unchanged, LEGACY rule).
- `ModelService`: `selected_provider()`, `quick_provider_status / install_provider /
  update_provider / connect_provider` replace the Codex-named methods; route resolution probes only
  the selected provider.
- CLI: `sage model select-provider --provider codex|claude` (provider only, never a model); `connect/refresh/list/evaluate` default to the
  selected provider. Menu and setup labels come from `provider_labels()`; setup step codes are
  `INSTALL_PROVIDER_CLI` / `SIGN_IN_PROVIDER`; the governed-run gate raises
  `PROVIDER_EXECUTION_NOT_READY`. GitHub release polling stays Codex-only; Claude updates through
  `claude update`.
- SQS: `WorkspaceProviderAdapter` wraps the selected provider and passes Claude token usage
  through; `claude_workspace` descriptor (`provider_family: anthropic`) and mapping added.
  **Open (Phase 4 prerequisite):** the SQS service itself (`discovery.py`, `admin.py`, `worker.py`)
  still assumes `provider_family: openai`, so a Claude qualification cannot yet be approved there.

## Phase 3 — Routing, estimation, competency

1. `model-policy.yml`: Claude models in `release_preference`; provisional default reasoning for
   `claude`; `low` prohibited for Skills. Always pass effort explicitly (Opus 5.5's own default is
   `medium`).
2. Token estimator: `SAGE_MULTILINGUAL_HEURISTIC_2` is fitted to `o200k_base`. Fit a Claude variant
   from Phase 1 `usage` counts (no `count_tokens` — that needs an API key). Make
   `rtc_sizing.provider` in `rtc/profile.yml` and `saw/profile.yml` and
   `evidence.validate_active_provider` follow the selected provider.
3. `model-language-competency.yml`: `claude:<model>` seed entries.

## Phase 4 — Qualify, then enable

1. Run `model_evaluation.py` and the NCA release gate with Claude routes as system under test
   (deterministic plants + LLM-built labels only; no hand labelling).
2. **Judge independence:** the NCA gate judges are Claude Opus 5.5 / Sonnet 5.5. When the system
   under test is a Claude route, judge with Codex models or mark the receipt same-family-judged.
3. Record passing routes as qualification evidence; add `claude` to
   `ENABLED_AUTOMATED_PROVIDER_IDS`.

## Phase 5 — Documentation

`OPERATOR-GUIDE.md`, both cheat sheets, `windows/ERRORS.md`, `windows/RECOVERY.md`,
`macos-linux/ERRORS.md` (login, limits, the API-key environment trap), `KNOWN-LIMITATIONS.md`,
`ARCHITECTURE.md` §4, `models-and-ai/*`, `ADMINISTRATIVE-AI-ROUTING-DESIGN.md` (Claude effort
mapping), `THIRD-PARTY-NOTICES.md`, `VANILLA-INSTALL-MANIFEST.md`, `RELEASE-NOTES.md`, `CHANGELOG.md`.

Phases 1–3 are testable without spending subscription quota; Phase 4 needs live runs.
