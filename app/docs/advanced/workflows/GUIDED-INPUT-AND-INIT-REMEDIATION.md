# Guided input and INIT remediation

SAGE distinguishes recoverable Operator input from genuine execution blockers. Interactive commands ask the Operator to correct or confirm recoverable values. Non-interactive commands return the same alternatives as structured `INPUT_REQUIRED` data.

## State contract

| State | Meaning | Required response |
|---|---|---|
| `INPUT_REQUIRED` | A missing, unknown, mistyped, ambiguous, stale, or unconfirmed Operator value can be corrected safely. | Prompt, choose or enter a value, confirm it, revalidate, then continue. |
| `ABANDONED` | The Operator cancelled or closed the input stream. | Stop without applying a correction. |
| `READY_WITH_LIMITATIONS` | The requested scope can execute, but an optional resource or capability is unavailable. | Continue only within the reported limitation. |
| `READY_WITH_ACTIONS` | Execution may continue while recoverable settings or review attention remain. | Resolve through guided prompts or the action report. |
| `BLOCKED` | The corrected request is valid, but an in-scope safety, integrity, authority, resource, or workflow defect prevents execution. | Correct the reported defect; do not bypass it. |

`BLOCKED` is not the first response to a typo or omitted setting.

## Interactive correction

Interactive mode is the default when SAGE is attached to a terminal. SAGE:

1. validates the entered command and dynamic identifiers;
2. ranks up to three conservative alternatives;
3. asks the Operator to choose an alternative, enter another value, or cancel;
4. shows the resolved value;
5. requires confirmation before it affects execution;
6. revalidates the corrected value;
7. prints the canonical command and correction history.

Example (`JUN 10-11` is the invalid entered scope):

```text
Input: run qa jun 10-11

Scripture book 'JUN' was not recognized.
Possible corrections:
  1. JHN - John [high confidence]
  2. Enter another value
  3. Cancel

Resolved Scripture book: 'JUN' -> 'JHN'
Use this correction? [Y/n/edit]
```

The effective scope becomes `JHN 10-11` only after Operator confirmation.

SAGE never silently changes project IDs, book codes, paths, review decisions, grammar overrides, target projects, versification, or state-changing commands.

## Non-interactive operation

Use either option when prompts are not allowed:

```bash
./system/bin/sage --json ...
./system/bin/sage --no-prompt ...
```

The command exits with code `2` and returns a stable structure such as:

```json
{
  "status": "INPUT_REQUIRED",
  "reason_code": "UNKNOWN_BOOK_CODE",
  "received": "JUN",
  "suggestions": [
    {
      "value": "JHN",
      "label": "John",
      "confidence": "HIGH",
      "score": 0.99
    }
  ],
  "retryable": true
}
```

Automation must choose and resubmit explicitly. It must not apply a suggestion merely because the confidence is high.

## Inputs covered

Guided resolution applies to:

- command domains, actions, workflow names, and operation names;
- option-name typos;
- SAGE Project IDs;
- Scripture book codes and bounded scope syntax, including chapter ranges such as `JHN 10-11`;
- evaluation-set IDs;
- task, plan, predecessor, and governed-path selections;
- transaction IDs and generation selectors;
- required SAW focus questions;
- governed grammar-review decision IDs;
- selected INIT settings and automatic resolutions;
- stale effective-configuration sidecars;
- missing or stale workspace initialization before task creation.

## Guided INIT

`project init`, `workspace validate`, and `workspace initialize` use the same remediation model.

INIT may ask the Operator to:

- mark the effective ecosystem configured;
- enable a SAGE Project required by the requested workflow;
- accept a detected `auto` value as an explicit effective value;
- retain the source value as `auto`;
- enter a different compatible value;
- review project language/profile, scope, roles, `content_state`, and VRS settings;
- clear a stale override sidecar and restart from source settings.

Confirmed changes are written to:

```text
localdata/.system/config/operator-overrides.yml
```

The selected source settings file is never rewritten. The sidecar contains the source-settings SHA-256 and an Operator-resolution history. SAGE rejects the sidecar as stale when the source settings change.

The sidecar is governed effective configuration, so `workspace reset-state` preserves it. Clear it explicitly with:

```bash
./system/bin/sage --settings FILE.yml project init --clear-overrides
```

## Automatic settings

Every non-trivial `auto` result shows:

- setting path;
- proposed value;
- evidence source;
- confidence;
- effect on execution.

The Operator may accept the value explicitly, keep `auto`, edit it, or cancel. SAGE re-loads and validates the complete effective configuration before continuing. If the proposed combination is invalid, the prior sidecar is restored.

## Grammar profiles

When a routed profile is `PROJECT_REVIEW_REQUIRED`, SAGE records review attention and continues. `AI_DRAFTED` is an accepted operational state with explicit AI provenance, not human approval. A genuine review decision ID remains optional provenance where supported.

A supplied ID records provisional use. It does not promote the profile to `ACTIVE`, and SAGE must not invent an ID.

## Initialization before tasks

If an analytical task is requested before initialization, or after source/effective settings changed, interactive SAGE offers to run `workspace initialize` immediately. Non-interactive mode returns `WORKSPACE_INITIALIZATION_INPUT_REQUIRED`.

For a menu-owned BIC or SAW Run, readiness is checked against that active Job's runtime settings and Job-local initialization receipt. A root-workspace receipt is used only for direct root CLI/API compatibility when no Job-local receipt exists.

Task-triggered INIT reviews unresolved automatic settings only for the projects selected by that exact task. Unrelated project settings remain visible in ecosystem reports but are not presented as required input for the task. A direct `workspace initialize` or `project init` may review the complete configured ecosystem.

If initialization completes but reports a genuine in-scope defect, task creation remains `BLOCKED`.

## Immutable ACT boundary

Guided correction applies before ACT generation and during controller command validation. After `ACT.md` and `task-manifest.json` are generated, they are immutable.

The model provider must not repair a task typo, replace a routed project, broaden a scope, or alter a task hash. SAGE reports the task-input defect and requires the Operator to recreate the task through the controller.

## Good practice

- Use interactive mode for first setup and occasional operators.
- Use `--json` for automation and tests.
- Keep suggestions conservative and limited to three.
- Confirm every state-changing correction.
- Preserve the source settings file as the declared baseline.
- Review `operator-resolutions` in INIT reports before pilot execution.
- Treat a high-confidence suggestion as a proposal, not authority.
- Reserve `BLOCKED` for corrected requests that still cannot execute safely.

## Natural-language routing before command validation

Natural-language routing is an earlier guided layer. `sage request` maps the request to one or more registered canonical commands. The Operator then confirms, edits, refines, requests explanation, chooses advisory-only handling, or cancels. Only a confirmed canonical command enters ordinary command/INIT validation.

The strongest safe proposal is option 2. If no safe proposal exists, option 2 becomes “Show related supported operations”; no execution choice is shown. Natural-language interpretation never changes the immutable ACT boundary and never converts confidence into approval.
