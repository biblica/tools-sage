# Number Consistency & Accuracy (NCA)

**SAGE NUMBERS CHECK** compares the numbers in one read-only WIP Project with SAGE's own number index of the original-language text, reports the formatting consistency of those numbers, and lists the text-critical decisions an operator must make. Open **Main Menu → 5. Number Consistency & Accuracy (NCA)**. SAGE Maintenance is option **6**.

## Reference index

SAGE ships one typed reference package, `SAGE_NUMBERS_TYPED_2026-10-09` (format `sage-numbers-typed-1.1`) under `system/resources/numbers/2026-10-09`, pinned by `system/config/numbers-reference.json`. No archive import is required. It indexes 3,814 verses with 5,345 original-language values and 5,021 NIV values, and records what each number counts.

- The original-language layer is built in SAGE from MACULA Hebrew (WLC) and MACULA Greek (SBLGNT) word data. It is Authority 1 and the only basis for a FAIL against the source. MACULA is © Biblica, Inc. under CC BY 4.0; licenses and attribution for every source are in [Third-Party Data Notices](advanced/projects-and-resources/THIRD-PARTY-NOTICES.md).
- The NIV layer (Biblica) is secondary evidence. It never silently replaces an original-language value.
- Every index review item has been decided; the package has no provisional rows. Build and review records are in the [index rebuild summary](advanced/release/nca-index-rebuild/SUMMARY.md), [NIV layer summary](advanced/release/nca-index-rebuild/NIV-SUMMARY.md) and [apparatus summary](advanced/release/nca-index-rebuild/APPARATUS-SUMMARY.md).
- The earlier `SAGE_NUMBERS_REFERENCE_2026-09-09` package remains in Core for comparison only; its text-critical registries (variants, footnote guidance, unit conversions) are carried into the typed package.

The package diagnostics block is shown once per package per session, as short readable lines.

## What counts as a number

The index and the model use one shared [counting convention, version 2.0](../system/skills/nca-numbers/references/COUNTING-CONVENTION.md): NCA checks **numbers that state a quantity or a date** (twelve men, half a hin, the fourteenth day of the first month). It does not count implied numbers ("tithe", "twice"), frequency ("seven times"), pronoun or idiom "one", rank ordinals ("the first one"), "both", "a pair", indefinite plurals ("thousands"), or numbers inside names. A difference NCA reports is therefore a translation question, not a difference in counting rules.

Extraction follows [contract 3.0](../system/skills/nca-numbers/references/TARGET-EXTRACTION-CONTRACT.md): the model returns each number's exact text in the verse, its value, kind and the item it counts (with an English gloss). SAGE verifies that each text occurs in the verse, drops invented ones, reads every digit numeral itself, corrects and flags a numeral the model read otherwise, and adds numerals the model missed.

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

Each finding is **FAIL** or **NEEDS_REVIEW**, with the WIP and original-language evidence, the quoted Berean Standard Bible (BSB) text, the NIV numbers as **Also see — NIV**, and a copy-paste translator note. No NIV Scripture text is shipped or quoted (NIV fair use allows at most 500 verses).

- **FAIL** is reserved for clear translation errors: `VALUE_DIFFERENCE` (the WIP has a number that matches neither the original language nor the NIV), `WRONG_ASSOCIATION` (the same numbers as the source, attached to different items, such as "1 000 gold dishes" for "30 gold dishes"), `MALFORMED_NUMERAL` (for example `10,0000`), and `NUMBER_NOT_IN_SOURCE` (a digit numeral in a verse whose source has no number).
- **NEEDS_REVIEW** covers cases the index cannot settle alone: the WIP follows the NIV where it differs from the original language, NIV-only or mixed authority, an attested variant reading, an order difference that cannot be verified, convention edge cases, `ONE_ONLY_DIFFERENCE` (the WIP differs only by an added or missing "one", such as "one talent" for "a talent"), `VALUE_OMITTED` (the WIP leaves out a source number and adds none, such as a repeated number stated once; check that the style is deliberate and consistent), and `UNIT_CONVERSION` (category `CONSISTENCY`: the WIP states a source value in another unit, such as the 11th hour as 5 in the afternoon or talents as coins; the report shows the WIP value with the original-language value and unit, and asks you to confirm the conversion style is applied consistently). A mismatch at a verse where the textual apparatus records a number variant is `APPARATUS_VARIANT` review, never FAIL.
- **Association check**: each WIP number's counted item is matched against the item the index records. A faithful reordering passes and appears under **Notes (no action needed)**.

**Text-critical decisions (operator)** lists the verses where the original language and NIV differ and the textual apparatus records a number variant. These are editorial decisions, not errors: NCA states both readings, which one the WIP follows, whether a footnote is present, and a suggested footnote basis when there is none. Each entry cites its evidence: NET Bible text-critical notes (short excerpts quoted with attribution and a link), the SBLGNT apparatus, OSHB ketiv/qere, Brenton's Septuagint, the Douay-Rheims Vulgate, the KJV, Berean Standard Bible footnotes, and synoptic parallel passages checked against SAGE's own index. The BSB reading itself is cited as a modern rendering reference with **Also see** (MT or Greek NT, NIV, LXX, Vulgate, KJV); it never decides a variant. Every report ends with **Sources and attribution** for each quoted source.

NCA never stops a Run on Scripture content. A verse with markup errors, a repeated verse number, or a comparison group split across files is not sent for extraction; it reports **NOT_ASSESSED** with its issue codes, and every other verse is still compared. Unreadable books become Run-level advisories. Only integrity guards (hashes, package, checkpoints) stop a Run. Unindexed coordinates, partial extraction, and missing coverage remain visible and never count as a pass.

## Reports

Reports are published under `localdata/reports/<job>/`:

- `<BOOK>/<CCC>/<run>_<BOOK>-<CCC>_ACTION-REPORT.md` and its `_OPERATOR-NOTE.txt`, one bundle per chapter, in the RTC/STC template;
- `JOB-SUMMARY.md` at the Job report root;
- `<run>_NUMBER-STYLE.md`: the formatting consistency report. Every number NCA reads (body numbers from extraction, footnote numerals read locally) is classified by form (digits, words, mixed), digit script, grouping and decimal mark. With a style profile, every variance is reported. Without one, NCA reconstructs the dominant style per area and location, reports the minority uses as grouped patterns (count and example verses), and writes `<run>_NUMBER-STYLE-PROFILE-RECONSTRUCTED.yml`, which you can review and import as the Number Style Profile.

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
