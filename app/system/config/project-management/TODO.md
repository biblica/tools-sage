# TODO Log

TODO states are `OPEN`, `READY`, `IN_PROGRESS`, `BLOCKED`, or `DONE`. `DONE` rows remain here for
traceability and must link to an entry in `IMPLEMENTED-UPDATES.md`.

## Current work

| ID | Added | Version | Milestone | Priority | State | Work item | Dependency |
|---|---|---|---|---|---|---|---|
| `TODO-20260826-001` | 2026-08-26 | `0.01beta2` | `MS-BETA2-QUALIFY` | HIGH | BLOCKED | Create a clean governed release staging tree and complete `RCLEAN-0.01beta2-001`. | `BI-20260826-001` |
| `TODO-20260826-002` | 2026-08-26 | `0.01beta2` | `MS-BETA2-NATIVE` | HIGH | OPEN | Complete native Windows acceptance with a real Paratext Projects root and governed BIC, RTC, and STC cycles. | Clean Beta 2 staging tree |
| `TODO-20260826-003` | 2026-08-26 | `0.01beta2` | `MS-BETA2-NATIVE` | HIGH | OPEN | Complete native macOS acceptance from the exact release ZIP using a root path containing spaces. | Clean Beta 2 staging tree |
| `TODO-20260826-004` | 2026-08-26 | `0.01beta2` | `MS-BETA2-NATIVE` | HIGH | OPEN | Complete Linux release-host acceptance for fresh dependency installation and a real workflow. | Clean Beta 2 staging tree |
| `TODO-20260826-005` | 2026-08-26 | `0.02beta` | `MS-0.02BETA-TUI` | MEDIUM | OPEN | Resume action-capable TUI parity after the frozen `0.01beta2` baseline; retain the classic menu and scriptable CLI. | Begin 0.02beta development |
| `TODO-20260828-001` | 2026-08-28 | `0.01beta2` | `MS-BETA2-QUALIFY` | HIGH | OPEN | Test and harden the parked Targeted Check and standalone Original-Language Review compatibility paths, including planning, task contracts, validation, continuation, aggregation, and report publication. | Complete current STC/RTC stabilization |
| `TODO-20260829-001` | 2026-08-29 | `0.01beta2` | `MS-BETA2-QUALIFY` | HIGH | IN_PROGRESS | Complete exact-source automated hardening for provider-neutral per-Skill routing, then run controlled live synthetic qualification and review/promote accepted route seeds. | Routing implementation and documentation complete |
| `TODO-20260829-002` | 2026-08-29 | `0.01beta2` | `MS-BETA2-NATIVE` | HIGH | OPEN | Operator-test provider-only Setup, automatic/override routes, continue/retry receipts, Job/Run/report route display, and one-item isolation on macOS and Windows before any RC promotion. | Live qualified route seeds and exact-source hardening |

## Completion rule

A TODO becomes `DONE` only after implementation and proportionate verification. Its corresponding
Implemented Update must record the evidence, affected version, and milestone. Broader roadmap items
that are not yet accepted as actionable work remain in
`system/config/NEXT-DEVELOPMENT-WORK.md`.
