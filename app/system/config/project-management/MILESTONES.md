# Project Milestones

Milestone states are `PLANNED`, `IN_PROGRESS`, `BLOCKED`, or `COMPLETE`. The target is a version,
not an invented calendar commitment; a target date is added only when the project has approved one.

## Milestone register

| ID | Target | State | Outcome | Exit evidence |
|---|---|---|---|---|
| `MS-BETA-PM` | `0.01beta` | COMPLETE | Establish internal PM tracking and versioning policy, reset the version baseline, and separate simple Operator documentation from advanced technical material. | `IMP-20260826-002` through `IMP-20260826-007` |
| `MS-BETA-UX` | `0.01beta` | COMPLETE | Converge current classic-menu operator grammar and navigation presentation. | `IMP-20260826-001`; focused UI tests pass |
| `MS-ALPHA-QUALIFY` | `0.02alpha1` | BLOCKED | Produce fresh exact-source qualification evidence from a clean governed staging tree. | Blocked by `BI-20260826-001`; requires `TODO-20260826-001` and `RCLEAN-0.02alpha1-001` |
| `MS-ALPHA-NATIVE` | `0.02alpha1` | IN_PROGRESS | Complete Windows, macOS, Linux, and real Operator workflow acceptance. | `TODO-20260826-002` through `TODO-20260826-004` |
| `MS-ALPHA-TUI` | `0.02alpha1` | IN_PROGRESS | Reach action-capable TUI parity without removing classic-menu or CLI support. | `TODO-20260826-005` |

## Milestone update rule

A milestone is `COMPLETE` only when every exit item is implemented and verified. A blocked milestone
must identify the blocking Build Issue. Completion should be reflected in Development Status and,
when release-significant, in Release Notes.
