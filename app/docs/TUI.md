# SAGE TUI — EXPERIMENTAL / UNSTABLE in v0.01beta2

## Status

The Textual TUI is **EXPERIMENTAL / UNSTABLE** in `v0.01beta2`. It may change incompatibly, includes incomplete and read-only workflows, and is not qualified as an authoritative Operator surface. The classic menu and scriptable CLI remain authoritative.

Launch it explicitly:

```text
sage tui
```

The root `./sage` / `sage.cmd` launchers still enter the classic menu by default while TUI parity is incomplete.

## Implemented through 0.01beta2

- full-screen Textual application shell targeting `100 x 30` during the current layout iteration;
- keyboard and mouse navigation with numeric `1`-`4` functional shortcuts;
- top-level **Main Menu / Scripture Projects / BIC / SAW / SAGE Maintenance** views;
- compact `1`-`4` mouse-capable functional menu row plus the global `A`-`F` footer row;
- persistent dashboard blocks for **System Status**, **Active AI**, **Project**, and the single **Active Job**;
- persistent view history with `A`/`Esc` Back and `B`/`Home` Main Menu;
- `C`/`Ctrl+Q` exit;
- `D` interface-language chooser using the existing governed localization source;
- `E`/`?` context Help as a modal overlay;
- `F` Status as a live `90 x 24` modal overlay, with `F`/`Esc` close and `R` refresh;
- Help/Status overlays return to the exact invoking TUI view;
- two-row mouse-capable footer matching the classic semantic controls;
- canonical sequential Job progress reporting using sealed ACT token estimates, advancing only when governed task submission is finalized;
- a 10-cell progress bar where each visual cell represents 10%, while the aligned numeric field retains conservative integer-percent precision, for example `SAW_UK-ENG [████░░░░░░]  43%`;
- active-task reporting derived from the current ACT operation and registered Skill rather than a parallel task vocabulary;
- terminal Run results are separate from active execution phases: `DONE`, `FAILED`, `BLOCKED`, and `CANCELLED`; `BLOCKED` requires a machine-readable reason and preserves the current progress bar for later remediation/resume;
- read-only Project, Job, report, setup, and recovery summaries;
- shared UI-independent status/help/dashboard service consumed by both classic and TUI code;
- shared workflow-AI startup probe service;
- canonical startup-readiness view covering configuration, Projects root, Project catalog, Scripture-resource state, BIC/SAW Job initialization, and workflow AI;
- workflow surfaces are gated while startup is incomplete, while Scripture Projects and SAGE Maintenance remain reachable for remediation;
- live workflow-AI probing starts only after the TUI has mounted; blocking readiness I/O is kept off the Textual UI event loop;
- persisted unfinished Run state feeds the TUI session header rather than relying only on in-process task state;
- native `P` / mouse Projects-root configuration with an absolute-path modal;
- native `Q` / mouse tree-only Quick Scan using the same Paratext catalog service as the classic menu;
- native `R` / mouse AI retest and startup-readiness refresh;
- Projects-root/scan readiness I/O is isolated from AI-probe I/O so one UI operation cannot cancel the other. These UI workers do **not** introduce parallel Job execution; governed Job/Run execution remains strictly sequential.

## 100 x 30 dashboard contract

The initial layout target is `100 x 30`. The persistent information hierarchy is:

```text
SYSTEM STATUS | ACTIVE AI | PROJECT
ACTIVE JOB: <job-id> [████░░░░░░]  43%
ACT / SKILL / active phase
current view/content
1 Projects | 2 BIC | 3 SAW | 4 SAGE Maintenance
A Back | B Main | C Exit | D Language | E Help | F Status
```

`F Status` is a centered `90 x 24` live overlay. It is not a navigation destination and does not enter Back history.

## Progress contract

SAGE remains sequential in this development slice: exactly one execution is presented as the active Job/Run. New Jobs record the quantification policy (`ROUTED_SFM_ESTIMATED_TOKENS`, finalized-task advancement, 10 visual cells); historical Jobs that explicitly record `ACT_ESTIMATED_TOKENS` retain that legacy basis. The Run percentage is derived rather than persisted, so the displayed percent cannot drift from sealed task evidence. Detailed token totals remain internal; normal TUI surfaces show only the compact progress line and ACT/Skill activity.

The dashboard treats `DONE` and `CANCELLED` as idle. `FAILED` and `BLOCKED` remain visible because they require Operator attention. A blocked Run is terminated for that execution attempt but remains resumable from governed state after its reason is remediated.

## Deliberate migration boundary

Only the bounded startup-remediation actions listed above are enabled. Use `sage menu` or the scriptable CLI for Project registration/removal, Job changes, Run creation/continuation, AI login/configuration, report actions, and recovery writes. Reports and Job recovery are owned by the relevant BIC/SAW workflow; system recovery is owned by SAGE Maintenance.

This boundary prevents the experimental TUI from duplicating governed workflow logic before service extraction and parity tests are complete.

## Dependency and portability

Textual is a **supplemental TUI dependency**, not a base runtime prerequisite. `system/requirements.txt` contains the classic CLI/menu dependencies; `system/requirements-tui.txt` contains:

```text
textual>=8.2,<9
```

The root launchers detect an explicit `tui` command and ask the bootstrapper to validate/install that supplemental profile. A Textual installation failure therefore does not invalidate the base classic CLI/menu environment.

Textual is selected because the framework supports terminal keyboard/mouse interaction across Windows, macOS, and Linux. Native-host acceptance remains required before the TUI can become the default launcher.

## Development order

1. Add native Scripture-resource validation, AI login guidance, workflow/Job configuration, and active-Job validation.
2. Add Project registration/selection/validation actions behind the shared Project services.
3. Replace remaining read-only Job/Run/report/recovery panels one governed operation at a time.
4. Add headless Textual keyboard/mouse regression tests for every migrated action.
5. Run native Windows/macOS/Linux acceptance, including terminals with limited dimensions and paths containing spaces.
6. Keep `sage menu` as fallback until action parity and recovery behavior pass release gates.
7. Only then consider making the TUI the default no-argument interface.

## Experimental Beta parity rule

The Textual TUI uses the same information architecture and labels as the authoritative text UI: SAW two-level Job/check flow, Reference Text Comparison (RTC)/Source Text Correspondence (STC)/Targeted Check/Original-Language Review, Configure AI, Configure Languages, diagnostics/report ownership, and configured Project names in Operator-facing context. TUI controls may replace numeric choices with buttons/switches/links, but they must map to the same governed operations. Mouse and keyboard activation must invoke the same action. Until a write surface reaches parity, the TUI shows the state read-only and directs writes to the text UI rather than inventing an alternate workflow.
