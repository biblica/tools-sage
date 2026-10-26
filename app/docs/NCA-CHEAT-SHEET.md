# Number Consistency & Accuracy (NCA)

**SAGE NUMBERS CHECK** compares the numbers in one read-only WIP Project with SAGE's own number index of the original-language text, reports the formatting consistency of those numbers, and lists the text-critical decisions an operator must make. Open **Main Menu → 5. Number Consistency & Accuracy (NCA)**. SAGE Maintenance is option **6**.

## Reference and counting rules

NCA checks against SAGE's bundled number index (original language first, NIV second), built from MACULA and shipped with the app; no import is needed. It counts **numbers that state a quantity or a date**, using one shared [counting convention](../system/skills/nca-numbers/references/COUNTING-CONVENTION.md), so a difference NCA reports is a translation question, not a difference in counting rules. Details, sources and licences: [NCA reference package and rules](advanced/workflows/NCA-REFERENCE-AND-RULES.md). The package diagnostics block is shown once per package per session.

## Set up a Job

1. Choose an onboarded WIP Project. Its language, script, recorded import date, and versification identify the input.
2. Choose the number style:
   - **1. Use standard language profile data**: NCA reconstructs the translation's own number style from the text.
   - **2. Upload style data from template**: import a filled-in copy of `system/config/profiles/numbers/number-style-template.yml`. Record all questionnaire areas, using `NOT_SPECIFIED` when the guide supplies no rule.
   Compatible profiles already installed are listed first, and these two options follow them.
3. Review the package diagnostics and model routing. The independent Job is named `NCA-<Project>_<YYYYMMDD>`.

Profiles use resolved localdata `inputs/styleguides/numbers`; additional imported packages use `inputs/resources/numbers`. The bundled reference remains read-only under Core `system/resources/numbers`.

## Choose Run checks

Two independent switches are initially ON:

- **Number accuracy** compares the WIP numbers with the index.
- **Footnote review and recommendations** adds the registered text-critical guidance notes for each checked verse.

At least one check must be ON. OFF means **NOT ASSESSED**, never passed. The number formatting report is always produced from the extraction evidence. Save or restore Job defaults before starting. Each Run seals its checks, style selection or explicit absence, package, target snapshot, mapping, and model/task identities. Resuming uses sealed evidence; revised defaults apply to new Runs.

After checks and scope, the menu seals the Run and shows a short preflight: language and script, requested scope, style profile, checks, limitations, inputs that cannot be extracted (only when present), model identity, and the SQS notice. Counters, batching and group IDs are written to `last-preflight.json` in the Job's controller state, whose path is shown.

## Read results

Each finding is a **Variance** or a **Consistency check** (stored as `FAIL` and `NEEDS_REVIEW` in the Run's results and diagnostics), with the WIP and original-language evidence, the quoted Berean Standard Bible (BSB) text, the NIV numbers as **Also see — NIV**, and a copy-paste translator note. Every variance is reported as a statement of what differs; no note asks the Operator for input. A Variance note says what to correct; a Consistency check note starts with "Check consistency:" and names the difference. No NIV Scripture text is shipped or quoted (NIV fair use allows at most 500 verses).

- **Variance** (`FAIL`) is reserved for clear translation errors: `VALUE_DIFFERENCE` (the WIP has a number that matches neither the original language nor the NIV, ; a substituted value is always a Variance, and when the unit it counts differs from the source's or is not determined, the report adds both units without converting), `WRONG_ASSOCIATION` (the same numbers as the source, attached to different items, such as "1 000 gold dishes" for "30 gold dishes"), `MALFORMED_NUMERAL` (for example `10,0000`), and `NUMBER_NOT_IN_SOURCE` (a digit numeral in a verse whose source has no number).
- **Consistency check** (`NEEDS_REVIEW`) is a difference NCA reports without deciding it (PO decision 2026-10-26: NCA reports number mismatches for the consultant; it does not explain or harmonize them, and grammar and wording are RTC/STC work). The reasons are:
  - `NUMBERS_DIFFER`: the WIP leaves out or adds numbers and substitutes none (a repeated number stated once, an explicit "one", a number made explicit from context, an extra ordinal). The report names the numbers not in the translation and the numbers not in the source.
  - `INDEX_UNSETTLED`: the index cannot settle the verse: it has no numbers there, only the NIV gives one, bridged verses mix original-language and NIV readings, the original-language numbers were adjusted by the index, or the index value is not yet reviewed. The report shows the values with the original-language and BSB text.
  - `MATCHES_SECONDARY_AUTHORITY`: the WIP follows the NIV where it differs from the original language.
  - `ATTESTED_VARIANT_READING` and `APPARATUS_VARIANT`: the WIP follows an attested alternate reading, or a mismatch sits at a verse where the textual apparatus records a number variant.
  - `ORDER_DIFFERENCE`: the same numbers in a different order that cannot be verified item by item.
- **Association check**: each WIP number's counted item is matched against the item the index records. A faithful reordering passes and appears under **Notes (no action needed)**.

**Text-critical variants** lists the verses where the original language and NIV differ and the textual apparatus records a number variant. These are editorial decisions, not errors: NCA states both readings, which one the WIP follows, whether a footnote is present, and a suggested footnote basis when there is none. Evidence and sources: [NCA reference package and rules](advanced/workflows/NCA-REFERENCE-AND-RULES.md).

Verses with no issue, verses without numbers in the source or the index, and verses that were not checked (with the reason) are summarized at the end of each report, under **Summary: no issue and not checked**, before the attribution and limitations.

NCA never stops a Run on Scripture content. A Variance is a report finding to correct before publication; it never stops the Run. A verse with markup errors, a repeated verse number, or a comparison group split across files is not sent for extraction; it reports **NOT_ASSESSED** with its issue codes, and every other verse is still compared. Unreadable books become Run-level advisories. Only integrity guards (hashes, package, checkpoints) stop a Run. Unindexed coordinates, partial extraction, and missing coverage remain visible and never count as a pass.

## Reports

Reports are published under `localdata/reports/<job>/`:

- `<BOOK>/<CCC>/<run>_<BOOK>-<CCC>_ACTION-REPORT.md` and its `_OPERATOR-NOTE.txt`, one bundle per chapter, in the RTC/STC template;
- `JOB-SUMMARY.md` at the Job report root;
- `<run>_NUMBER-STYLE.md`: the formatting consistency report. Every number NCA reads (body numbers from extraction, footnote numerals read locally) is classified by form (digits, words, mixed), digit script, grouping and decimal mark. Body numbers are also classified by the measure system of the unit they count (ancient: cubits, baths, talents; modern: metres, litres, kilograms). This is a word-list lookup per language (`numbers/measures.py`; Ukrainian, Spanish and English today) on the text of what each number counts, which the Run's existing extraction already returns. It makes no model call. The report shows the dominant system and lists every use of the other, or both uses when neither dominates. Nothing is converted. A WIP language with no list is reported as not checked. Number-style areas other than digits, bands, grouping, decimal mark and measure system (ordinals, fractions, ranges, qualifiers, contexts, units) are accepted in a profile but not yet assessed. With a style profile, every variance is reported. Without one, NCA reconstructs the dominant style per area and location, reports the minority uses as grouped patterns (count and example verses), and writes `<run>_NUMBER-STYLE-PROFILE-RECONSTRUCTED.yml`, which you can review and import as the Number Style Profile.

The full technical projection is written to the Run diagnostics, not the operator report.

**Findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities. SQS confidence checks have not been applied.** This limitation appears in every report and in machine output. SQS is future functionality, not a setup prerequisite.

## Canonical CLI

Run from the application directory with the managed Python environment. Global `--settings` and `--json` options precede the domain.

```sh
python -m sage.cli resource numbers inspect
python -m sage.cli task create --workflow nca --operation numbers --wip PROJECT_ID --scope "MAT 1:1-17"
python -m sage.cli task execute --task /path/to/task-manifest.json --dry-run
python -m sage.cli task execute --task /path/to/task-manifest.json
python -m sage.cli task submit --task /path/to/task-manifest.json
```

Use `--job-id` for an existing Job and `--run-id` for a sealed Run. New-Run switches are `--number-accuracy` / `--no-number-accuracy` and `--footnote-review` / `--no-footnote-review`. Omitted switches use Job defaults. Omit `--number-style` to run without a style profile; otherwise import one with `resource number-style import --path /path/to/configured-profile.yml` and pass `--number-style PROFILE/VERSION` when creating the Job. The `--numbers-package` selector is optional; omission selects the bundled Core reference. Use `resource numbers import --archive ...` only to add another qualified package.

Resource inspection is local. Model-dependent execution requires the configured NCA route and provider readiness. `task execute --dry-run` validates the request and returns scoped `preflight` metadata without contacting a completion provider. NCA never edits Scripture or Paratext Notes XML. The experimental TUI retains its documented execution limitations; use the Control Center or CLI for NCA.

## Qualification

Provider-free tests establish software behavior; they do not establish actual-model language accuracy, cost, or performance. The typed package [failed its release gate](advanced/release/NCA-RELEASE-GATE.md) on 2026-10-18 (FAIL precision 60%; the bar is 90%), so every FAIL needs a reviewer's judgment. The [bundled-reference validation](advanced/release/NCA-BUNDLED-REFERENCE-VALIDATION.md) and [NCA qualification](advanced/release/NCA-QUALIFICATION.md) records describe the earlier 2026-09-09 package and pipeline. See [Known Limitations](KNOWN-LIMITATIONS.md).
