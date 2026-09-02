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
- A double-line `═` box marks the major title and start of each new form in continuous terminal history.
- A `> `-prefixed label with a full-width, unindented single `─` underline marks a minor section heading.
- A complete single-line `┌─┐ / │ / └─┘` box encloses the invariant footer.
- Leave one blank line before and after every major, minor, and footer block so adjacent panels remain distinct in scrollback.
- Routine action completion returns directly to the next menu. Do not add `Press Enter to continue...` acknowledgement prompts; reserve explicit confirmation prompts for consequential actions.
- Footer controls use two leading spaces before the semantic key (`  A.`, `  D.`), matching the numeric-menu indentation contract.
- Primary actions come before toggles/configuration.
- Main separates the Project action, the BIC/SAW workflow group, and `SAGE Maintenance` with blank section breaks.
- Numeric menu choices use one three-character right-aligned field before the period: `  1.`, ` 11.`, `111.`.
- Use fixed-width formatting for label/value columns; do not use literal `\t` for alignment.
- Optional file/text prompts use `[Enter to cancel]`; empty input cancels without an error.
- Lists omit repeated metadata. Put file paths and technical detail in drill-down views.
- Add compact differentiating metadata such as `[Arab]`, `[Latn]`, `[Cyrl]`, `[Ethi]`, or `[Deva]` where it helps selection.
- Job resource-assignment headings use `CHOOSE BIC <SOURCE>`, `CHOOSE BIC <DONOR>`, `CHOOSE BIC <TARGET>`, `CHOOSE SAW <WIP>`, and `CHOOSE SAW <REFERENCE>`. The angle brackets deliberately highlight the formal Job role and are not input placeholders in these headings. Every chooser routed through the centralized Project-assignment path must follow this convention.
- Secondary reporting recommends the audience Project language: SAW uses the `<WIP>` language and BIC uses the `<TARGET>` language. The Operator may instead choose another language or no secondary language. A Project language already used as the primary report language cannot also be selected as secondary.

## SAW progress

```text
╔══════════════════════════════════════════════════════════════════════╗
║ SAW_paPCVv1-usNIVv2                                                  ║
╚══════════════════════════════════════════════════════════════════════╝

paPCVv1 checked against usNIVv2
Check:            Reference Text Comparison (RTC)
Review range:     JHN 1:1-21:25
Using codex / gpt-5.6-terra / high [QUALIFIED]

Review portion:   4/19 — JHN 5:1-47
Source check:     2/5 — JHN 5:34      |
```

Only the live check line changes during normal execution. Review-portion numbering remains the immutable approved plan; structural/source counters are local to that portion. Machine work-unit IDs and detailed provider receipts remain stored for audit/debugging.
