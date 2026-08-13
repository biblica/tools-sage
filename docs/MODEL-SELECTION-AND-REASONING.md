# SAGE model selection and provider build policy

## RC7.04 execution policy

Provider architecture and release execution permission are separate controls.

| Provider | Adapter/configuration | RC7.04 automated execution |
|---|---|---|
| Codex | Implemented | **Enabled** |
| Ollama | Implemented/provisionable | **Disabled** |
| LM Studio | Implemented/provisionable | **Disabled** |
| Grok | Future adapter slot | Not implemented |
| Gemini | Future adapter slot | Not implemented |

`build_policy.allowed_automated_providers` is effectively `[CODEX]` in RC7.04. A configured or provisioned provider is not automatically executable.

No OpenAI API-key, access-token, service-account, direct API, or API-fallback route is supported. Codex uses the locally installed official CLI with ChatGPT-managed authentication.
The normal Operator connection path is `Models > Connect OpenAI / ChatGPT`; direct CLI equivalents are `./sage model connect` on macOS/Linux and `sage.cmd model connect` on Windows. SAGE runs Codex CLI sign-in directly; the Codex desktop app is not required.

## Codex availability, qualification, recommendation

SAGE separates:

1. **Available** — currently exposed to the Operator's signed-in Codex/ChatGPT workspace.
2. **SAGE-qualified** — allowed by `meta/model-policy.yml` for the task profile.
3. **Recommended** — selected from currently available qualified models for the exact workflow/operation.

SAGE queries the locally installed `codex app-server` over stdio. `account/read` must establish ChatGPT-managed authentication; `model/list` supplies the current workspace catalogue and advertised reasoning levels.

The supported SAGE reasoning ceiling is **XHigh**. Higher or unrecognised provider effort levels are not routable.

```sh
./sage model refresh --provider codex
./sage model list --provider codex
./sage model recommend --workflow bic --operation rewrite
./sage model use --provider codex --auto
./sage model use --provider codex --model MODEL_ID --reasoning high
./sage model test --provider codex
```

## Provisioned disabled local providers

Ollama and LM Studio configuration is retained so the provider abstraction can be exercised and future builds can enable local execution without redesigning workflow contracts.

```sh
./sage model provision --provider ollama --model MODEL_ID [--endpoint http://127.0.0.1:11434]
./sage model provision --provider lmstudio --model MODEL_ID [--endpoint http://127.0.0.1:1234]
```

Provisioning records model/endpoint configuration only. `model use`, task execution, and provider testing through these providers fail closed under RC7.04 build policy. Local endpoints remain restricted to loopback when those adapters are used by a future enabled build.

## Future providers

Grok, Gemini, and other providers should enter through the same provider request/response/status abstractions. RC7.04 contains no credentials, implementation, or execution path for them.

## Task execution boundary

The resolved provider/model/reasoning choice is recorded in execution receipts. Provider choice never changes task scope, authorised reads/writes, authority roles, evidence hashes, or workflow state ownership.

## Exact provider-handoff budget

Model selection does not bypass context limits. Immediately before every provider execution SAGE serialises the exact prompt and output schema, records the byte count and `SAGE_MULTILINGUAL_HEURISTIC_1` token estimate, and compares the combined handoff with the workflow operation's hard limits. Conditional OL phases are remeasured after previous-phase outputs are embedded. An oversized final handoff fails closed with `LLM_HANDOFF_CONTEXT_LIMIT_EXCEEDED`; earlier ACT/work-unit budgeting remains the partitioning layer.
