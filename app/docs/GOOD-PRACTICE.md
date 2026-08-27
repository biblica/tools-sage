# Good Practice

- Keep project selection, setup, recovery, approvals, and task state in SAGE.
- Use one immutable governed task per analytical operation/work unit.
- Use Codex with ChatGPT sign-in only for current governed automated execution; do not add API credentials.
- Treat Ollama as optional local-admin infrastructure only; it remains disabled
  for governed BIC/SAW work.
- Map Paratext/PTLite resources directly when appropriate; external reads are `.SFM`/`.VRS` only.
- Use `READ_ONLY_SCRIPTURE` for every SOURCE, DONOR, SAW WIP, SAW REFERENCE, and OL mapping.
- Use `READ_WRITE_TARGET` only for an explicitly chosen BIC TARGET; write `.SFM` only and never `.VRS`.
- Treat lifecycle state (`LOCKED`/`UNDER_REVIEW`) and filesystem permission as separate concepts.
- Keep BIC and SAW project configuration independent; do not create handoff or role-conversion conventions between them.
- Treat `ACT.md`, `task-manifest.json`, hashes, and `.sage` state as controller-owned.
- If task evidence becomes stale, recreate the task instead of patching it.
- Submit all model output through SAGE validation; provider output is not approval or commit.
- Keep BIC INSPECT -> REWRITE -> SELF-CHECK order.
- Keep SAW partition units separate and aggregate only after finalization.

Developer maintenance conventions: `PYTHON-MAINTENANCE.md`.
