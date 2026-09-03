# Beta Operator UI Presentation

Beta standardizes the classic terminal interaction grammar.

## Interactive template

```text
╔══════════════════════════════════════════════════════════════════════╗
║ <SCREEN TITLE>: <optional context>                                   ║
╚══════════════════════════════════════════════════════════════════════╝

  1. Primary action
  2. Secondary/reset action

> <Section> — <Choose/change instruction>
────────────────────────────────────────────────────────────────────────

  3. <option>                           <state/value>
  4. <option>                           <state/value>

┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘

Choose:
```

Rules:

- Classic-menu navigation preserves terminal scrollback and never emits ANSI full-screen clear sequences.
- Interactive busy/progress output occupies one viewport-bounded terminal row, redraws in place,
  and is erased completely before permanent result or error output. Redirected output emits one
  static progress message per operation.
- A double-line `═` box marks the major title and start of each new form in continuous terminal history.
- A `> `-prefixed label with a full-width, unindented single `─` underline marks a minor section heading.
- A complete single-line `┌─┐ / │ / └─┘` box encloses the invariant footer.
- Leave one blank line before and after every major, minor, and footer block so adjacent panels remain distinct in scrollback.
- Routine action completion returns directly to the next menu. Do not add `Press Enter to continue...` acknowledgement prompts; reserve explicit confirmation prompts for consequential actions.
- Footer controls use two leading spaces before the semantic key (`  A.`, `  D.`), matching the numeric-menu indentation contract.
- Primary actions come before toggles/configuration.
- Menu headings and items use sentence case. A governed entity token after the opening word is
  displayed as `PROJECT`, `JOB`, `RUN`, or `TASK`; a sentence-initial token remains natural, as in
  `Project information`, so SAGE `JOB` cannot be confused with the Scripture book `Job`.
- Main separates the Project action, the BIC/RTC/STC workflow group, and `SAGE Maintenance` with blank section breaks.
- Numeric menu choices use one three-character right-aligned field before the period: `  1.`, ` 11.`, `111.`.
- The active terminal viewport is a hard width boundary (72 columns by default). Fit box borders,
  titles, headings, menu items, status text, and information blocks to it. Wrap long menu labels
  beneath the label start and long information values beneath the value-column start.
- Use fixed-width formatting for label/value columns; expand incoming tabs before measuring display
  width and do not emit literal `\t` for alignment. Measure terminal cells, not code-point count, so
  localized wide and combining characters remain inside the viewport.
- Optional file/text prompts use `[Enter to cancel]`; empty input cancels without an error.
- Lists omit repeated metadata. Put file paths and technical detail in drill-down views.
- Add compact differentiating metadata such as `[Arab]`, `[Latn]`, `[Cyrl]`, `[Ethi]`, or `[Deva]` where it helps selection.
- Job resource-assignment headings use `CHOOSE BIC <SOURCE>`, `CHOOSE BIC <DONOR>`, `CHOOSE BIC <TARGET>`, `CHOOSE RTC/STC <WIP>`, and `CHOOSE RTC/STC <REFERENCE>`. The angle brackets deliberately highlight the formal Job role and are not input placeholders in these headings. Every chooser routed through the centralized Project-assignment path must follow this convention.
- Secondary reporting recommends the audience Project language: RTC/STC uses the `<WIP>` language and BIC uses the `<TARGET>` language. The Operator may instead choose another language or no secondary language. A Project language already used as the primary report language cannot also be selected as secondary.

## Project maintenance action ledger

```text
╔══════════════════════════════════════════════════════════════════════╗
║ PROJECT ACTIONS                                                      ║
╚══════════════════════════════════════════════════════════════════════╝

  1. Project information
  2. Scripture books
  3. Versification
  4. Project location
  5. Refresh PROJECT
  6. Validate PROJECT
  7. Jobs using this PROJECT
  8. Advanced settings
  9. Remove PROJECT from SAGE
```

`Refresh PROJECT` rereads derived Project/catalog facts and preserves the Operator-confirmed scope
and import date. `Validate PROJECT` reports readiness separately. Removal uses negative-default
confirmation. If Jobs bind the Project, show every affected Job and state that confirmation removes
those Jobs and their Job-local data; also state that Paratext files and root-level published reports
remain unchanged.

Project onboarding renders the proposed and confirmed scope as viewport-fitted information rows,
not as a long inline prompt default. Accepted scope forms are `OT`, `NT`, `FB`, USFM IDs, inclusive
canonical ranges, and unions; `NT, PSA` and `LUK-ACT` are canonical examples.

## RTC/STC progress

```text
╔══════════════════════════════════════════════════════════════════════╗
║ RTC-paPCVv1_20260901                                                  ║
╚══════════════════════════════════════════════════════════════════════╝

paPCVv1 checked against usNIVv2
Check:            Reference Text Comparison (RTC)
Review range:     JHN 1:1-21:25
Using codex / gpt-5.6-terra / high [QUALIFIED]

Review portion:   4/19 — JHN 5:1-47
Source check:     2/5 — JHN 5:34      |
```

Only the live check line changes during normal execution. Review-portion numbering remains the immutable approved plan; structural/source counters are local to that portion. Machine work-unit IDs and detailed provider receipts remain stored for audit/debugging.
