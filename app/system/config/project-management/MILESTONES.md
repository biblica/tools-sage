# Project Milestones

Milestone states are `PLANNED`, `IN_PROGRESS`, `BLOCKED`, `COMPLETE`, or `SUPERSEDED`. The target
is a version, not an invented calendar commitment; a target date is added only when the project has
approved one. A `SUPERSEDED` milestone names the milestone or release that replaced it.

## Active milestones

| ID | Target | State | Outcome | Exit evidence |
|---|---|---|---|---|
| `MS-REVIEW-20261013` | `0.02a3` | PLANNED | Apply the 2026-10-13 code review: BIC protected contracts reach the model, BIC identity is controller-injected, every tool reports exceptions instead of hard-blocking, and the LLM, code, documentation, and grammar cleanups land. | `TODO-20261013-001` through `TODO-20261013-015` and `TODO-20261013-019` through `TODO-20261013-022` |
| `MS-REVIEW-20261014` | `0.02a3` | IN_PROGRESS | Apply the 2026-10-14 RTC/STC review: no unassessed work reported as complete, no Run stuck on content, deterministic checks before model calls, an in-process Run driver, and a decomposed task module. | `TODO-20261014-001` through `TODO-20261014-023` |
| `MS-REVIEW-20261022` | `0.02a3` | IN_PROGRESS | Apply the 2026-10-22 BIC Skill and prompt review: the model receives everything the Skills expect it to apply, the Skills stop describing reads the model never gets, and the protected-contract re-pin and existing-TARGET warning are decided. | Implemented: `IMP-20261022-002` (A1, A2), `IMP-20261022-003` (A3.1), `IMP-20261022-004` (A3.3). Open: `TODO-20261022-007` (A3.2, PO decision), `TODO-20261022-003` (B, PO decision), `TODO-20261022-004` (C1), `TODO-20261022-005` (C2, PO decision) |
| `MS-02A3` | `0.02a3` (non-release development branch) | IN_PROGRESS | Deliver the NCA runtime and the supporting workflow, menu, and language-data work, then qualify NCA with live models. | Implemented: `IMP-20260914-001`, `IMP-20260917-001`, `IMP-20260928-001`, `IMP-20261011-001`, `IMP-20261018-001` (NCA release gate: FAIL), `IMP-20261019-001` (NCA on Acts), `IMP-20261020-001` (NCA referents, nested association, unit conversions), `IMP-20261020-002` (NCA release gate schema 1.2), `IMP-20261020-003` (NCA restructured quantities). Open: `TODO-20261018-001`, `TODO-20261013-018`, `TODO-20261015-001` |
| `MS-SQS` | unscheduled | IN_PROGRESS | Recover the SQS service and integrate it into SAGE as qualification evidence, then deploy and accept it. | Implemented: `IMP-20260925-001`. Open: `TODO-20261013-017`, `TODO-20261015-002` |
| `MS-02B1-QUALIFY` | `0.02b1` | BLOCKED | Produce fresh exact-source qualification evidence from a clean governed staging tree. | Blocked by `BI-20260826-001`; requires `TODO-20260826-001` and `RCLEAN-0.02b1-001` |
| `MS-02B1-NATIVE` | `0.02b1` | IN_PROGRESS | Complete Windows, macOS, Linux, and real Operator workflow acceptance. | `TODO-20260826-002` through `TODO-20260826-004`, `TODO-20260829-002` |
| `MS-FUTURE-TUI` | a later release | PLANNED | Reach action-capable TUI parity without removing classic-menu or CLI support. | `TODO-20260826-005` |

## Closed milestones

| ID | Target | State | Outcome | Exit evidence |
|---|---|---|---|---|
| `MS-02B1-TUI` | `0.02b1` | SUPERSEDED | Reach action-capable TUI parity in `0.02b1`. The TUI baseline is frozen for `0.02b1` as **EXPERIMENTAL / UNSTABLE**; parity work moved to `MS-FUTURE-TUI`. | `IMP-20260826-008`; `MS-FUTURE-TUI` |
| `MS-BETA2-QUALIFY` | `0.01beta2` | SUPERSEDED | Qualify the `0.01beta2` integration of STC and Alpha hardening. The line was consolidated into `0.02b1` before release qualification; qualification now runs under `MS-02B1-QUALIFY`. | `IMP-20260830-BETA2` through `IMP-20260903-003`; `IMP-20260909-02B1` |
| `MS-BETA-PM` | `0.01beta` | COMPLETE | Establish internal PM tracking and versioning policy, reset the version baseline, and separate simple Operator documentation from advanced technical material. | `IMP-20260826-002` through `IMP-20260826-007` |
| `MS-BETA-UX` | `0.01beta` | COMPLETE | Converge current classic-menu operator grammar and navigation presentation. | `IMP-20260826-001`; focused UI tests pass |

## Milestone update rule

A milestone is `COMPLETE` only when every exit item is implemented and verified. A blocked milestone
must identify the blocking Build Issue. Completion should be reflected in Development Status and,
when release-significant, in Release Notes.
