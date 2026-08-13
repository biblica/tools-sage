# Release Notes — SAGE v0.01-rc7.04

RC7.04 separates **SAGE Project administration** from **BIC/SAW Job role assignment**, fixes cross-workflow runtime validation, and makes the operator story consistent from Project discovery through execution.

## Canonical Project and Job workflow

The operator lifecycle is now:

```text
Scan → Discover → Add to SAGE → Configure → Validate
     → Assign role → Create Job → Select scope → Preview work
     → Run → Review results
```

- A discovered Paratext Project becomes a **SAGE Project** only through **Add Project to SAGE**.
- Adding a Project is role-neutral. SOURCE / DONOR / TARGET / WIP / REFERENCE exist only as **Job bindings**.
- The persistent collection is the **SAGE Project Inventory** (`state/project-inventory.json`).
- BIC and SAW Project selectors show SAGE Projects only. `A. Add another Project to SAGE` enters Project administration temporarily, then returns to the Job selector.
- **Remove Project from SAGE** removes only SAGE's inventory record. It never deletes or modifies the Paratext Project and is blocked while a Job still uses that Project.
- BIC and SAW Job menus support both **Add Job** and **Remove Job**. Removing a Job deletes Job-owned state only and leaves all SAGE/Paratext Projects unchanged.

## BIC / SAW runtime isolation

- A SAW Job no longer fails because the inactive BIC workflow template has no SOURCE / DONOR / TARGET bindings.
- A BIC Job likewise does not require an inactive SAW template to be configured.
- Runtime validation requires bindings only for the active Job's tool.
- Job runtime files derive role-specific grammar and access from the Job binding while the SAGE Project Inventory remains role-neutral.
- Run continuation and ACT creation use the active Job's own initialization receipt, with root initialization retained only as a compatibility fallback for direct root CLI/API task creation.
- BIC TARGET remains the only ordinary Project role that can receive governed external Scripture writes; SAW remains read-only.

## Project language handling

- Project addition no longer requires a pre-existing SAGE language grammar/profile namespace.
- Valid Paratext ISO language metadata is accepted into the SAGE Project Inventory even when language-specific analysis has not yet been configured.
- SAGE includes an offline ISO-639 lookup used to validate declared codes and to suggest candidates for missing/invalid metadata.
- The Paratext folder prefix is secondary evidence only. It can corroborate a language identity, but ambiguous candidates are never silently substituted.
- Language grammar/profile requirements are enforced later when a Job operation actually needs them.

## Paratext catalogue and VRS handling

- Paratext catalogue scans provide a simple rotating status line (`| / - \\`) and, where available, completed/total counts.
- The configured Paratext Projects root is also the default **Base VRS root**.
- An explicit Base VRS override survives later Paratext-root changes; clearing the override returns to the Paratext-root default.
- Governed external base/custom VRS files are validated at their configured roots and copied into bounded task evidence by hash; task manifests record logical `@BASE_VRS` / `@PROJECT` provenance rather than authorising direct external reads.
- Catalogue discovery remains limited to direct child folders with valid `settings.xml`, with cached metadata for Project selection.

## Operator menus and scope preview

- Main-menu BIC/SAW access no longer depends on a separate manual **SAVE** step; setup state is persisted as it changes.
- Startup reconciles the saved Setup summary with each active Job's current initialisation receipt; a ready configured workflow proceeds to the Main Menu instead of reopening Setup because of an obsolete `VALIDATE` step.
- Project administration is under **Scripture Projects**; role assignment is under BIC/SAW Job setup.
- Project detail screens use the standard section grammar: `# Details`, `# Project Settings`, `# Maintenance`, and `# Advanced`.
- Scripture scope entry now has a guided **SELECT SCRIPTURE SCOPE** flow plus direct expert entry at the selection prompt. `GEN` means the whole book and `GEN 1` means the whole chapter.
- Evidence preview evaluates readiness for that exact scope; defects in other chapters or books remain reported but do not block the requested plan.
- Before a Run is created, SAGE shows the planned bounded work/token sections and permits **Run**, **Change scope**, or **Cancel**.
- Normal QA may create a staged composite whose current stage is itself partitioned into several governed tasks. After the operator chooses **Run** or **Continue active Run**, SAGE advances every ready unit through execution, submission, stage aggregation, and completion without returning to the Job menu between tasks or creating a duplicate Run.
- Blocking Run phases display a rotating one-line heartbeat, while composite continuation prints durable progress such as `SAW work unit 1/10: GEN 1:1-2` before provider execution.
- Unexpected implementation errors during continuation return a bounded `RUN_CONTINUATION_FAILED` diagnostic while preserving the saved Run instead of terminating SAGE with a traceback.
- Errors present what happened, why it matters, and the operator's next action rather than exposing only an internal reason code.

## Preserved boundaries

- CODEX remains the only enabled automated provider; no OpenAI API-key/direct-API path exists.
- External Scripture reads remain limited to `.SFM` and `.VRS`.
- Governed `@GRK` / `@HEB` resources remain separate from ordinary SAGE Projects.
- Protected BIC rewrite-detail and verb-selection contracts remain unchanged.
