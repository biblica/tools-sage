# TODO Log

TODO states are `OPEN`, `READY`, `IN_PROGRESS`, `BLOCKED`, or `DONE`. `DONE` rows remain here for
traceability and must link to an entry in `IMPLEMENTED-UPDATES.md`.

## Current work

| ID | Added | Version | Milestone | Priority | State | Work item | Dependency |
|---|---|---|---|---|---|---|---|
| `TODO-20260826-001` | 2026-08-26 | `0.02alpha1` | `MS-ALPHA-QUALIFY` | HIGH | BLOCKED | Create a clean governed release staging tree and complete `RCLEAN-0.02alpha1-001`. | `BI-20260826-001` |
| `TODO-20260826-002` | 2026-08-26 | `0.02alpha1` | `MS-ALPHA-NATIVE` | HIGH | OPEN | Complete native Windows acceptance with a real Paratext Projects root and governed BIC/SAW cycles. | Clean Alpha staging tree |
| `TODO-20260826-003` | 2026-08-26 | `0.02alpha1` | `MS-ALPHA-NATIVE` | HIGH | OPEN | Complete native macOS acceptance from the exact release ZIP using a root path containing spaces. | Clean Alpha staging tree |
| `TODO-20260826-004` | 2026-08-26 | `0.02alpha1` | `MS-ALPHA-NATIVE` | HIGH | OPEN | Complete Linux release-host acceptance for fresh dependency installation and a real workflow. | Clean Alpha staging tree |
| `TODO-20260826-005` | 2026-08-26 | `0.02alpha1` | `MS-ALPHA-TUI` | MEDIUM | IN_PROGRESS | Finish action-capable TUI parity while retaining the classic menu and scriptable CLI. | UI-independent action services |

## Completion rule

A TODO becomes `DONE` only after implementation and proportionate verification. Its corresponding
Implemented Update must record the evidence, affected version, and milestone. Broader roadmap items
that are not yet accepted as actionable work remain in
`system/config/NEXT-DEVELOPMENT-WORK.md`.
