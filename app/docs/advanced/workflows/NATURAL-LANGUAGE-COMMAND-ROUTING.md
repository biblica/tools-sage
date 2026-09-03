# Natural-language command routing

SAGE accepts natural-language Operator requests through a governed command-construction layer. Natural language does not replace the canonical command grammar and does not create a second execution engine.

## Interaction surface

`./system/bin/sage request` is a terminal/CLI controller command, not an analytical model prompt. It may propose canonical controller actions but may not bypass confirmation or perform the routed analysis directly. After a confirmed command creates `ACT.md`, execute that task through the selected SAGE provider.

## Canonical route

```text
Natural-language request
        ↓
Deterministic intent and scope proposal
        ↓
Ranked registered SAGE commands
        ↓
Operator confirmation or correction
        ↓
Canonical SAGE parser and controller
        ↓
Normal INIT, validation, ACT, review, transaction, and write controls
```

Use:

```bash
./system/bin/sage request "Run RTC on Amos for NPU"
```

For a machine-readable proposal without execution:

```bash
./system/bin/sage --json --no-prompt request "Run RTC on Amos for NPU"
```

## Operator choices

When SAGE can recommend one complete command, it presents:

  1. Refine the request.
  2. Execute the suggested command.
  3. Edit the suggested command.
  4. Explain the suggested command.
  5. Show other related operations.
  6. Advisory response only — no project changes.
  7. Cancel.

Option 2 is always the strongest registered-command proposal. SAGE displays the resolved workflow, operation, projects, scope, confidence, corrections, defaults, and canonical command before execution.

When no command is safe to recommend, SAGE presents only:

  1. Refine the request.
  2. Show related supported operations.
  3. Advisory response only — no project changes.
  4. Cancel.

## Example: likely command with a book typo

Input:

```text
run rtc jun 10-11
```

Proposed interpretation:

```text
Workflow: RTC
Operation: RTC
Scope correction: JUN → JHN
WIP: ukrNPUv0
Authorized REFERENCE: usNIVv2
```

Canonical command:

```bash
./system/bin/sage task create --workflow rtc --operation rtc \
  --wip ukrNPUv0 \
  --reference usNIVv2 \
  --scope "JHN 10-11"
```

The correction and workflow defaults remain visible and require confirmation.

## Example: ambiguous request

Input:

```text
Review 3 John from KKH to BOL.
```

SAGE may rank:

  1. BIC INSPECT — `idKKHv0` SOURCE + configured DONOR -> `usBOLx1` TARGET, scope `3JN`.
  2. Reference Text Comparison (RTC) — review an independently configured RTC WIP Project, scope `3JN`.

SAGE must not silently decide that “review” means either source inspection or target RTC.

## Example: no safe execution match

Input:

```text
Make the translation better and fix everything.
```

This is too broad for safe execution. SAGE offers refinement, related operations, advisory-only handling, or cancellation. It does not offer freestyle execution.

## Interactive and automated behavior

### Interactive

The Operator reviews the interpretation and explicitly chooses the next action. An edited command is parsed again through the normal command grammar before execution.

### Non-interactive

`--json` and `--no-prompt` return the proposal and stop. Explicit execution requires `--execute`; a non-default ranked proposal can be selected with `--choice N`.

```bash
./system/bin/sage --json --no-prompt request "show BIC status" --execute
```

Scripts should prefer canonical commands directly. Natural-language execution is intended for governed human interaction, not unattended automation.

## Advisory-only boundary

Advisory-only handling may:

- explain the likely operation;
- compare related commands;
- recommend a safer scope;
- draft a canonical command;
- identify missing information.

It must not:

- create or submit tasks;
- change INIT settings;
- approve grammar or memory;
- reset or recover state;
- write or commit Scripture;
- publish BIC generation history.

## Audit record

Every routing decision is appended to:

```text
localdata/.system/logs/natural-language-requests.jsonl
```

The record contains the original request, interpretation status, Operator decision, selected command ID, canonical command, and confidence. Project resources and source settings are not changed by interpretation alone.
