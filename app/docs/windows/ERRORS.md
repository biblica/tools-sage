# SAGE Windows Error Cheat Sheet

| Cue / code | Action |
|---|---|
| `SAGE RUNTIME INSTALLATION REPORT` / `Result: BLOCKED` | Review the recorded runtime, Authenticode, download, SHA-256, archive, or dependency reason. Retry the SAGE-managed runtime, choose the offered WinGet Python 3.12 per-user installation when WinGet is available, or exit. SAGE runs WinGet only after explicit Operator approval. |
| TUI/Textual dependency unavailable | Run `.\sage.cmd` without `tui` to use the classic interface. TUI dependencies are supplemental and must not block the base CLI/menu. |
| `OLLAMA_DOWNLOAD_FAILED` with `CERTIFICATE_VERIFY_FAILED` | Restart SAGE once so its managed runtime installs the declared portable CA bundle, then retry. If an authorized proxy uses a private CA, run `set "SAGE_CA_BUNDLE=C:\path\to\ca-bundle.pem"` before `.\sage.cmd`. Do not disable TLS verification. |
| Codex TUI opens during setup | Exit Codex and rerun `.\sage.cmd` from the SAGE root in Command Prompt/PowerShell. SAGE must remain the parent process. |
| `CODEX_CLI_NOT_FOUND` | Run `.\sage.cmd` from the SAGE root; Setup offers Codex CLI installation. |
| `CODEX_INSTALL_FAILED` / installer says Windows only | Update to the current SAGE Windows bootstrap. SAGE must preserve `OS=Windows_NT` when launching the official non-interactive Codex installer. Retry Setup -> Install Codex CLI. |
| `CODEX_CHATGPT_AUTH_REQUIRED` | Main **4** -> **SAGE Maintenance** -> **Configure AI** -> OpenAI/ChatGPT connection. |
| `CODEX_APP_SERVER_*` | ChatGPT login may still be valid. Use Models -> Provider status/test; retry the live catalog query before reconnecting ChatGPT. |
| path with spaces rejected | Retry through the current mapper. Windows paths and matching surrounding quotes are normalized before validation. |
| Paratext/PTLite project not listed | Check the configured projects root, then **Scan / show detected projects**. A detected subfolder must contain `.SFM` or `.VRS`. |
| required project resource missing | In the BIC/SAW Project selector choose **Add another Project to SAGE**. SAGE opens Project administration temporarily, then returns to role selection. |
| `INPUT_REQUIRED` | Follow the guided prompt; SAGE records the Operator response without rewriting source settings. |
| stale/locked/incomplete task | Open the relevant **BIC/SAW > Recovery and diagnostics** menu; use governed recovery, not manual state edits. |
| workspace validation error | `.\sage.cmd workspace doctor`, then `.\sage.cmd workspace validate`. |

No Codex desktop app, Node/npm prerequisite, or OpenAI API key is required or supported.
