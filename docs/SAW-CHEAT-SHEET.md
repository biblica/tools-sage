# SAW cheat sheet

Use SAW to analyse one bounded LWC WIP against one authorised LWC REFERENCE. SAW is read-only for every external Scripture resource and never edits Paratext Notes XML.

```text
WIP + REFERENCE (+ configured applicable GRK/HEB only when routed) -> findings
```

## Natural-language entry

```bash
./sage --settings FILE.yml request "Run QA on Amos for NPU"
```

Confirm the SAW Job, WIP, REFERENCE, scope, and canonical command. The request resolves through the same persisted Project -> Job -> Run -> Task grammar as the Control Center.

## Preparation

```bash
./sage --settings FILE.yml status
./saw --settings FILE.yml status
```

If a semantic binding exists, confirm its index is `CURRENT`. Semantic signals are triage-only.

## Normal QA

```bash
./saw --settings FILE.yml qa \
  --wip ukrNPUv0 \
  --reference usNIVv2 \
  --scope "AMO 1:1-9:15"
```

One QA request creates/continues a composite QA Run:

```text
DETERMINISTIC PREFLIGHT
 -> STRUCTURAL ADJUDICATION          only if needed
 -> TRANSLATION / MEANING QA         required
 -> SELECTIVE OL ADJUDICATION        only if meaning QA emits bounded OL requests
 -> DETERMINISTIC FINALISATION
```

Only the selective OL stage receives GRK/HEB. SAGE owns stage progression and any deterministic partitioning. **Continue active Run** advances all ready work units and stages through execution, governed submission, aggregation, and completion in one operator action. It stops when validation fails or a task needs operator attention. The Run dashboard retains separate expert controls for execution and submission.

Meaning QA preserves deterministic natural units—one prose paragraph, one `\li1` major list unit with its subordinate `\li2+` items, or one operational poetry stanza—then coalesces adjacent units toward the governed minimum and target token sizes. Poetry stanza means an uninterrupted run of `\q`/`\q#`, `\qm`/`\qm#`, `\qr`, `\qc`, or `\qd`; it breaks at `\b`, `\qa`, section/major-section boundaries, Psalm chapter/`\cl`, `\d`, or transition to non-poetry. `\v` does not break a poetry unit. Partitioned child tasks also receive labelled adjacent WIP and REFERENCE context; context-only coordinates cannot become coverage or ordinary findings.

## Focused Check

```bash
./saw --settings FILE.yml focused \
  --wip faTMNv0 \
  --reference usNIVv2 \
  --scope "JHN 1:1-5" \
  --focus "Is the participant reference clear in verse 3?" \
  --type PARTICIPANT_REFERENCE
```

Focused Check has no OL Scripture. If the question requires OL adjudication, use the separate OL Review operation.

## Original-language Review

```bash
./saw --settings FILE.yml ol \
  --wip faTMNv0 \
  --reference usNIVv2 \
  --scope "JHN 1:1-5" \
  --focus "Does the WIP preserve the grammatical relationship in verse 3?"
```

A SAW Job may configure one Greek resource and/or one Hebrew resource. The OL resource is resolved from the applicable configured SAW Job binding, not from a global role search. Focused Check and the OL-free Normal QA stages do not require an OL binding.

## Outputs

A successful SAW finalisation first validates every Task or work unit in the bounded Run, then deterministically batches their findings and review receipts into one final Job-level report set. Task outputs, submission receipts, stage aggregates, and machine plan JSON remain under the owning Run for traceability. They are not the final Operator report catalogue.

Final human-facing reports are written to the owning Job's main report folder, grouped by Scripture book:

```text
jobs/saw/<job-id>/reports/<BOOK>/
```

For a `GEN 1` QA scope, for example:

```text
jobs/saw/<job-id>/reports/GEN/GEN-001_2026-08-13_001_ACTION-REPORT.md
jobs/saw/<job-id>/reports/GEN/GEN-001_2026-08-13_001_OPERATOR-NOTE.txt
```

The `<job-id>` segment identifies the owning SAW Job, not the WIP Project. The filename order is `<SCOPE>_<YYYY-MM-DD>_<SERIAL>_<REPORT-TYPE>`. Book codes are uppercase, numeric scope components are three digits, and the serial increases within that Job/book/date catalogue. The completion screen prints both exact final paths.

Open the Operator-note text in Notepad++, TextEdit, VS Code, or another basic editor and copy/paste selected material into Paratext Notes manually. SAGE does not generate or write Paratext Notes XML. SAGE reports never go into the Paratext Project folder.

## State rules

- Every model task/unit must become `FINALIZED` before its dependent stage proceeds.
- SAW never edits Scripture projects.
- Recreate an invalid task instead of editing `ACT.md` or `task-manifest.json`.
- If a sealed task reports `ACT_INPUT_STALE` after configuration changes, choose **Reset / restart active Run with current configuration** from the SAW Job menu. SAGE preserves the superseded Run and all its outputs as `ABANDONED`, then creates an active replacement with the same operation, scope, focus, and check type.
- Recoverable missing/ambiguous Operator input is `INPUT_REQUIRED`. Reserve `BLOCKED` for confirmed technical/integrity failure.
