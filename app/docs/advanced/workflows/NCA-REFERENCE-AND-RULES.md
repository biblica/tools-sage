# NCA reference package and rules (advanced)

Background for the [NCA Cheat Sheet](../../NCA-CHEAT-SHEET.md): what the bundled reference package is, what NCA
counts, and how text-critical variants are evidenced. Operators do not need this to run a check.

## Reference index

SAGE ships one typed reference package, `SAGE_NUMBERS_TYPED_2026-10-09` (format `sage-numbers-typed-1.1`) under `system/resources/numbers/2026-10-09`, pinned by `system/config/numbers-reference.json`. No archive import is required. It indexes 3,814 verses with 5,345 original-language values and 5,021 NIV values, and records what each number counts.

- The original-language layer is built in SAGE from MACULA Hebrew (WLC) and MACULA Greek (SBLGNT) word data. It is Authority 1 and the only basis for a FAIL against the source. MACULA is © Biblica, Inc. under CC BY 4.0; licenses and attribution for every source are in [Third-Party Data Notices](../projects-and-resources/THIRD-PARTY-NOTICES.md).
- The NIV layer (Biblica) is secondary evidence. It never silently replaces an original-language value.
- Every index review item has been decided; the package has no provisional rows. Build and review records are in the [index rebuild summary](../release/nca-index-rebuild/SUMMARY.md), [NIV layer summary](../release/nca-index-rebuild/NIV-SUMMARY.md) and [apparatus summary](../release/nca-index-rebuild/APPARATUS-SUMMARY.md).
- The earlier `SAGE_NUMBERS_REFERENCE_2026-09-09` package remains in Core for comparison only; its text-critical registries (variants, footnote guidance, unit conversions) are carried into the typed package.

The package diagnostics block is shown once per package per session, as short readable lines.

## What counts as a number

The index and the model use one shared [counting convention, version 2.0](../../../system/skills/nca-numbers/references/COUNTING-CONVENTION.md): NCA checks **numbers that state a quantity or a date** (twelve men, half a hin, the fourteenth day of the first month). It does not count implied numbers ("tithe", "twice"), frequency ("seven times"), pronoun or idiom "one", rank ordinals ("the first one"), "both", "a pair", indefinite plurals ("thousands"), or numbers inside names. A difference NCA reports is therefore a translation question, not a difference in counting rules.

Extraction follows [contract 3.0](../../../system/skills/nca-numbers/references/TARGET-EXTRACTION-CONTRACT.md): the model returns each number's exact text in the verse, its value, kind and the item it counts (with an English gloss). SAGE verifies that each text occurs in the verse, drops invented ones, reads every digit numeral itself, corrects and flags a numeral the model read otherwise, and adds numerals the model missed.

## Text-critical evidence

**Text-critical variants** lists the verses where the original language and NIV differ and the textual apparatus records a number variant. These are editorial decisions, not errors: NCA states both readings, which one the WIP follows, whether a footnote is present, and a suggested footnote basis when there is none. Each entry cites its evidence: NET Bible text-critical notes (short excerpts quoted with attribution and a link), the SBLGNT apparatus, OSHB ketiv/qere, Brenton's Septuagint, the Douay-Rheims Vulgate, the KJV, Berean Standard Bible footnotes, and synoptic parallel passages checked against SAGE's own index. The BSB reading itself is cited as a modern rendering reference with **Also see** (MT or Greek NT, NIV, LXX, Vulgate, KJV); it never decides a variant. Every report ends with **Sources and attribution** for each quoted source.
