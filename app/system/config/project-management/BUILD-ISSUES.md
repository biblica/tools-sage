# Build Issues

Build-issue states are `OPEN`, `INVESTIGATING`, `BLOCKED`, `RESOLVED`, or `CLOSED`. New entries go
at the top of the active table. Resolution notes remain in this file after closure.

## Active issues

| ID | Opened | Version | Milestone | Priority | State | Summary |
|---|---|---|---|---|---|---|
| `BI-20260826-001` | 2026-08-26 | `0.01beta` | `MS-BETA-REQUALIFY` | HIGH | INVESTIGATING | External-data/Core-boundary refactor requires fresh exact-source qualification before ZIP promotion. |

### BI-20260826-001 — Refactored Core requires fresh exact-source qualification

- **Observed:** The 0.01beta refactor moved all persistent local/operator/runtime state out of Core
  into configurable `localdata`, removed the shipped virtual environment, and changed storage/runtime
  contracts across bootstrap, Jobs, reports, resources, tests, and release tooling.
- **Evidence:** Focused converted contract suites are passing, but release promotion remains blocked
  until the complete deterministic hardening, package validation, deep audit, cross-platform contract
  suite, and reproducible ZIP checks pass against the same frozen Core source.
- **Impact:** No pre-refactor qualification receipt can authorize the new package.
- **Required resolution:** Complete the exact-source qualification gates, record the frozen source
  SHA-256 and formal hardening receipt, build the deterministic Core-only ZIP, verify its SHA-256, and
  rerun package/audit checks against the extracted artifact.
- **Linked work:** `TODO-20260826-001`.

## Resolved issues

No build issues have been resolved since this ledger was introduced.
