# Windows and Codex Execution Audit — SAGE v0.01beta

## Scope

This audit covers every Windows launcher and every SAGE runtime boundary that can start Python, Codex CLI, PowerShell, `cmd.exe`, `taskkill.exe`, Git/pip/bootstrap helpers, or another managed executable. The goal is deterministic argv handling, explicit environment ownership, bounded child-process cleanup, and no accidental Codex TUI or API-key path.

## Windows launchers

| Surface | Beta disposition |
|---|---|
| `sage.cmd` | Thin forwarding wrapper; untouched argv; no `SHIFT`. |
| `system/bin/sage.cmd` | Resolves the application root, delegates to PowerShell, installs/verifies pinned Windows CPython under `localdata/.system/runtime/python`, repairs `venv`, then executes `python -m sage.cli`. Paths are quoted. |
| `system/bin/bic.cmd` | **Beta fix:** no batch parsing/`SHIFT`. Passes untouched argv to Python `launcher-shortcut`, which owns global-option and workflow-argument parsing. |
| `system/bin/saw.cmd` | **Beta fix:** same as BIC; no `%*` replay after `SHIFT`. |
| `system/tools/clone_and_install.cmd` | Delegates to `sage-python.cmd`; no system Python selection or installation is required. |

No SAGE runtime Python call uses `shell=True`. Legacy `codex.cmd`/`.bat` is supported only through an explicit `%COMSPEC% /d /s /c` argv generated with `subprocess.list2cmdline`; the preferred Windows command is the official standalone `codex.exe`.

## Codex command inventory

SAGE invokes only these Codex CLI surfaces:

1. `codex --version` — bounded presence/version check.
2. `codex login status` — local ChatGPT-login state check.
3. `codex login` or `codex login --device-auth` — explicit interactive account connection requested by the Operator.
4. `codex app-server --stdio` — bounded account/model-catalog request/response exchange.
5. `codex exec ... -` — governed task execution with sealed prompt on stdin and JSON Schema-constrained final output.

The current OpenAI Codex source exposes `login status`, `--device-auth`, `app-server --stdio`, `exec --skip-git-repo-check`, `--output-schema`, and `--output-last-message`. Beta therefore does not depend on undocumented shell aliases.

## Governed `codex exec` contract

Beta executes governed tasks with:

- `--ephemeral` — no reusable Codex session is required for SAGE task continuity;
- `--ignore-user-config` — ChatGPT auth still comes from `CODEX_HOME`, while unrelated user `config.toml` cannot redirect the governed model-provider/task policy;
- `--ignore-rules` — user/project exec-policy rules cannot alter the sealed SAGE task contract;
- `--color never` — deterministic diagnostics;
- `--sandbox read-only` — provider subprocess cannot write the task workspace;
- `--skip-git-repo-check` — SAGE task temp directories are intentionally not Git repositories;
- `--output-schema <schema>` — machine response contract;
- `--output-last-message <file>` — deterministic response handoff;
- explicit `--model` when selected;
- explicit `--config model_reasoning_effort=...` when selected;
- `-` — sealed prompt read from stdin.

Stdout/stderr are file-backed for governed execution instead of inherited pipes. On timeout or cleanup SAGE terminates the Windows process tree via `%SYSTEMROOT%\\System32\\taskkill.exe /PID ... /T /F`, then falls back to direct process termination.

## Windows Codex installation

- PowerShell is invoked by absolute/discovered executable argv, never by `shell=True`.
- SAGE supplies `OS=Windows_NT` and `CODEX_NON_INTERACTIVE=1` in the minimized installer environment.
- `LOCALAPPDATA`, `USERPROFILE`, `SYSTEMROOT`, `COMSPEC`, proxy variables, and custom CA variables are retained.
- API/access-token variables are not passed by SAGE.
- After installation, SAGE prefers `%LOCALAPPDATA%\\Programs\\OpenAI\\Codex\\bin\\codex.exe` before a legacy npm `codex.cmd` on PATH.
- Installation success is verified by the resulting binary, not by PATH refresh alone.

## Connectivity and authentication separation

`codex login status` proves stored login mode, not successful model sampling. SAGE therefore separately probes execution transport before governed work and reports connection failure as a retryable task interruption rather than waiting for the task execution ceiling and calling it a Run block.

## Other subprocess boundaries

- Menu/controller bridge: `sys.executable -m sage.cli` with list argv, controlled `PYTHONPATH`, no shell.
- Runtime bootstrap: Python/venv/pip calls use list argv and explicit working roots.
- Clone/install tooling: Git/Python/pip use list argv and checked return codes.
- Ollama administration is independent from Codex and remains assistive-only; it is not a governed BIC/RTC/STC fallback.
- Deep-audit Windows launcher checks use `cmd.exe /d /c <launcher> --help` only in qualification tooling.

## Beta acceptance requirements

Beta is acceptable only if:

- Windows launcher/static portability tests pass;
- no launcher mixes `SHIFT` with later `%*` replay;
- standalone `codex.exe` wins over an npm `codex.cmd` when both exist unless `SAGE_CODEX_COMMAND` explicitly overrides it;
- API credentials are absent from the Codex subprocess environment;
- proxy/custom-CA settings survive environment minimization;
- login, model-catalog, app-server, execution, timeout, and process-tree cleanup tests pass;
- source deep audit reports zero errors/warnings.

## Beta Windows `.CMD` shim correction

The previous release candidate could pre-render a quoted `.CMD`/`.BAT` Codex command and then pass that rendered string as one `cmd.exe /s /c` argument. On Windows, the nested CreateProcess escaping could reach `cmd.exe` as literal `\"...\"` quoting, producing `'"C:\\...\\codex.CMD"' is not recognized`. Beta normalizes accidental outer quotes and invokes batch shims as `cmd.exe /d /c call <shim> <args...>`. Native `codex.exe` remains direct execution. The shared command builder covers login, device-code login, version/status, model catalog/app-server, execution connectivity probes, and governed `codex exec`.

The current official standalone installer exposes `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`; Beta also tolerates older/alternate `%LOCALAPPDATA%\Programs\Codex\bin\codex.cmd` / `.exe` locations without treating a batch shim as a native executable.
