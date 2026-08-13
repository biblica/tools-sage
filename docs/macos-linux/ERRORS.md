# SAGE macOS/Linux Error Cheat Sheet

| Cue / code | Action |
|---|---|
| `.venv` missing / Python dependency missing | Run `./sage`; approve **Create/Repair SAGE Python environment**. Manual fallback: `python3 -m venv .venv` then `./.venv/bin/python -m pip install -r requirements.txt`. |
| Codex TUI opens during setup | Exit Codex and rerun `./sage` from the normal shell. SAGE must remain the parent process. |
| `CODEX_CLI_NOT_FOUND` | Run `./sage`; Setup offers Codex CLI installation. |
| `CODEX_CHATGPT_AUTH_REQUIRED` | Main **5** -> System/configuration -> OpenAI/Codex connection. |
| `CODEX_APP_SERVER_*` | ChatGPT login may still be valid. Use Models -> Provider status/test; retry the live catalogue query before reconnecting ChatGPT. |
| quoted/space-containing path rejected | Retry through the current mapper. It accepts unquoted, `'quoted'`, `"quoted"`, and Unix `\ ` space escapes. |
| Paratext/PTLite project not listed | Check the configured projects root, then **Scan / show detected projects**. A detected subfolder must contain `.SFM` or `.VRS`. |
| required project resource missing | In the BIC/SAW Project selector choose **Add another Project to SAGE**. SAGE opens Project administration temporarily, then returns to role selection. |
| `INPUT_REQUIRED` | Follow the guided prompt; SAGE records the operator response without rewriting source settings. |
| stale/locked/incomplete task | Main **6**; use governed recovery, not manual state edits. |
| workspace validation error | `./sage workspace doctor`, then `./sage workspace validate`. |

No Codex desktop app or OpenAI API key is required or supported.
