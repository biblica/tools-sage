# macOS / Linux Path and Execution Report - SAGE v0.01beta

## Result

- Linux path/runtime execution: PASS in the current Linux validation host.
- macOS path/runtime contract: PASS by static and platform-mocked validation; native macOS acceptance remains required.
- POSIX release permissions: corrected and release-gated.

## Path contract

The shipped tree has no non-ASCII pathnames, no case-insensitive/Unicode-normalized path collisions, and no path component approaching common POSIX filesystem component limits. Runtime path construction uses `pathlib`; shell entrypoints quote their resolved SAGE root and forward arguments without word splitting. A root containing spaces was exercised through `./sage`, BIC, and RTC/STC.

## POSIX launchers

The only executable files in the source/release contract are:

- `sage`
- `system/bin/sage`
- `system/bin/bic`
- `system/bin/saw`
- `system/tools/clone_and_install.sh`

Bundled Scripture `.SFM` and XML data are mode `0644`; they are no longer accidentally executable. Release ZIP metadata is explicitly emitted as Unix metadata (`create_system = 3`) with deterministic `0755`/`0644` modes, independent of whether the release ZIP is built on Windows, macOS, or Linux.

## Linux execution

A disposable SAGE copy under a root containing spaces was run using the managed runtime outside Core at `localdata/.system/runtime/venv`, containing only declared pinned dependencies. The real launchers produced:

- `./sage status` -> Python environment READY, Setup `NOT_RUN`, Workspace `NOT_INITIALISED`;
- `./sage workspace validate` -> expected fail-closed `INIT_INPUT_REQUIRED`;
- `./system/bin/bic --help` -> exit 0;
- `./system/bin/saw --help` -> exit 0; and
- schema validation -> PASS.

Fresh dependency download remains network-dependent and was not exercised because the validation container has no outbound package access.

## macOS-specific execution contract

- `/bin/sh`-compatible launchers are syntax checked.
- `localdata/.system/runtime/venv/bin/python` is the default managed-interpreter path when localdata uses the sibling location.
- Ollama executable discovery covers Apple Silicon Homebrew, Intel Homebrew, and the Ollama application bundle.
- Ollama installation uses the downloaded macOS DMG and the native `open` command.
- macOS physical-memory detection uses `sysctl -n hw.memsize`; available-memory estimation uses `vm_stat`.
- Codex uses the POSIX standalone installer path and preserves `HOME`, `PATH`, locale, temporary-directory, proxy, and TLS environment variables required by the host.

## Remaining native acceptance

Before production qualification, run on a physical/virtual macOS host:

1. extract the exact ZIP and verify `./sage` executes without manual chmod;
2. run from an SAGE root containing spaces;
3. create a fresh `localdata/.system/runtime/venv` with governed dependency installation;
4. exercise a real Paratext Projects root and an external Project location;
5. verify Codex ChatGPT login;
6. verify Ollama detection/install/start/model status if that optional local assistant is enabled; and
7. run one governed BIC and RTC/STC cycle.
