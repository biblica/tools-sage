# SAGE model selection and provider build policy

## v0.02alpha1 execution policy

Provider architecture and release execution permission are separate controls.

| Provider | Adapter/configuration | v0.02alpha1 automated execution |
|---|---|---|
| Codex | Implemented | **Enabled** |
| Ollama | Optional local admin assistant | **Disabled for BIC/SAW** |
| Grok | Future adapter slot | Not implemented |
| Gemini | Future adapter slot | Not implemented |

`build_policy.allowed_automated_providers` is effectively `[CODEX]` in v0.02alpha1. A configured or provisioned provider is not automatically executable.

No OpenAI API-key, access-token, service-account, direct API, or API-fallback route is supported. Codex uses the locally installed official CLI with ChatGPT-managed authentication.
The normal Operator connection path is `SAGE Maintenance > Configure AI > Connect OpenAI and ChatGPT`; direct CLI equivalents are `./system/bin/sage model connect` on macOS/Linux and `.\system\bin\sage.cmd model connect` on Windows. SAGE runs Codex CLI sign-in directly; the Codex desktop app is not required.

## Startup prerequisite and canonical AI status

Normal interactive startup performs one non-generative workflow-AI readiness check before SAGE is considered ready. The resulting canonical status records **Connection**, **Provider**, selected **Model**, effective **Reasoning level**, prerequisite state, last-check timestamp, and bounded diagnostic/reason code. A failed installation/authentication/model readiness check leaves setup `INCOMPLETE` and blocks normal Main Menu entry.

`SAGE Maintenance > Configure AI` loads that canonical state once on entry. Model and reasoning toggles update the loaded selection without implicit connection checks. **Check LLM connection** is the explicit minimal generation test and refreshes the status; if a provider cannot report a reasoning level, SAGE reports it as unavailable/provider-default rather than inventing one.

## Codex availability, qualification, recommendation

SAGE separates:

1. **Available** — currently exposed to the Operator's signed-in Codex/ChatGPT workspace.
2. **SAGE-qualified** — allowed by `system/config/model-policy.yml` for the task profile.
3. **Recommended** — selected from currently available qualified models for the exact workflow/operation.

SAGE queries the locally installed `codex app-server` over stdio. `account/read` must establish ChatGPT-managed authentication; `model/list` supplies the current workspace catalog and advertised reasoning levels.

The supported SAGE reasoning ceiling is **XHigh**. Higher or unrecognised provider effort levels are not routable.

```sh
./system/bin/sage model refresh --provider codex
./system/bin/sage model list --provider codex
./system/bin/sage model recommend --workflow bic --operation rewrite
./system/bin/sage model use --provider codex --auto
./system/bin/sage model use --provider codex --model MODEL_ID --reasoning high
./system/bin/sage model test --provider codex
```

## Local admin assistant

**Configure Hosted AI** manages externally hosted Codex/OpenAI/ChatGPT execution. **Configure
Local AI** manages the optional Ollama assistant on this workstation. `F. Status` reports both
states without duplicating Local AI status inside the Hosted AI panel.

The optional local admin assistant uses Ollama but has no authority to execute
governed BIC/SAW tasks. Open it through **SAGE Maintenance > Configure AI >
Configure Local AI**.

SAGE detects an existing host installation before offering an installer. The
same menu installs Ollama through the official macOS, Linux, or Windows route;
starts and stops a SAGE-owned `ollama serve` process; and reports an externally
owned Ollama service without terminating it.

The only supported local model is the instruction-tuned Gemma 4 E2B
importance-matrix `Q5_K_M` GGUF, imported under the stable local alias
`sage-gemma4-e2b:q5_k_m`. The source is
`bartowski/google_gemma-4-E2B-it-GGUF`; setup verifies SHA-256
`53c8e1a5bf3f9c83074f6ed8a737e8d17ac70e90904078dc3e010739d1152c6a`
before import and records the resulting Ollama digest. The raw download is about
3.66 GB and setup requires 10 GiB temporary free space.

SAGE caps context at 16K, disables thinking for the bounded admin response,
permits one request at a time, and sends `keep_alive: 0` so the model unloads
after every response. Hosts below 16 GiB total RAM may install the model but
cannot enable it.

The local assistant remains separate from governed BIC and SAW task execution.
Codex remains the only enabled automated workflow provider.

## Future providers

Grok, Gemini, and other providers should enter through the same provider request/response/status abstractions. v0.02alpha1 contains no credentials, implementation, or execution path for them.

## Task execution boundary

The resolved provider/model/reasoning choice is recorded in execution receipts. Provider choice never changes task scope, authorized reads/writes, authority roles, evidence hashes, or workflow state ownership.

## Routed-SFM execution budget

Model selection does not bypass review-item limits. Immediately before provider execution SAGE measures only the exact SFM Scripture streams routed to that review item and enforces the operation's routed-SFM hard limits. Prompt, output schema, linguistic profiles, controller manifests, prior microtransaction records, IDs, hashes, and diagnostics are transport/governance material rather than Scripture slicing inputs; their byte size may be recorded as telemetry. Conditional OL phases are separate review items and size only the SFM actually routed to those phases. Oversized routed Scripture fails closed before provider execution.


## Model-release language competency

SAGE maintains language-competency estimates separately for each concrete provider/model release. Selecting or encountering a model ID without an existing competency record triggers a governed re-evaluation of known languages. The provider CLI/runtime version is recorded separately from the model release key. See `MODEL-LANGUAGE-COMPETENCY.md`.
