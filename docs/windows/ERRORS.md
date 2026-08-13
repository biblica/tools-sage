# SAGE Windows Error Cheat Sheet

| Cue / code | Action |
|---|---|
| `.venv` missing / Python dependency missing | Run `sage.cmd`; approve **Create/Repair SAGE Python environment**. Manual fallback: `py -3 -m venv .venv` then `.venv\Scripts\python.exe -m pip install -r requirements.txt`. |
| Codex TUI opens during setup | Exit Codex and rerun `sage.cmd` from Command Prompt/PowerShell. SAGE must remain the parent process. |
| `CODEX_CLI_NOT_FOUND` | Run `sage.cmd`; Setup offers Codex CLI installation. |
| `CODEX_CHATGPT_AUTH_REQUIRED` | Main **5** -> System/configuration -> OpenAI/Codex connection. |
| `CODEX_APP_SERVER_*` | ChatGPT login may still be valid. Use Models -> Provider status/test; retry the live catalogue query before reconnecting ChatGPT. |
| path with spaces rejected | Retry through the current mapper. Windows paths and matching surrounding quotes are normalised before validation. |
| Paratext/PTLite project not listed | Check the configured projects root, then **Scan / show detected projects**. A detected subfolder must contain `.SFM` or `.VRS`. |
| required project resource missing | In the BIC/SAW Project selector choose **Add another Project to SAGE**. SAGE opens Project administration temporarily, then returns to role selection. |
| `INPUT_REQUIRED` | Follow the guided prompt; SAGE records the operator response without rewriting source settings. |
| stale/locked/incomplete task | Main **6**; use governed recovery, not manual state edits. |
| workspace validation error | `sage.cmd workspace doctor`, then `sage.cmd workspace validate`. |

No Codex desktop app, Node/npm prerequisite, or OpenAI API key is required or supported.
