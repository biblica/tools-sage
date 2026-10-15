# Third-Party Data Notices and Attribution

SAGE is built by Biblica, Inc. This page lists the third-party data that SAGE ships or quotes in its
reports, the license for each, and the attribution SAGE gives. It covers data only; Python dependencies
keep the licenses recorded in their own packages.

When a report quotes text from one of these sources, the report's **Sources and attribution** section
repeats that source's attribution line.

## MACULA Hebrew and MACULA Greek

[MACULA Hebrew Linguistic Datasets](https://github.com/Clear-Bible/macula-hebrew/) and
[MACULA Greek Linguistic Datasets](https://github.com/Clear-Bible/macula-greek/) © 2022–2024 by
[Biblica, Inc](https://biblica.com) are licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Required attribution, used verbatim in SAGE packages and reports:

- "MACULA Hebrew Linguistic Datasets, available at https://github.com/Clear-Bible/macula-hebrew/"
- "MACULA Greek Linguistic Datasets, available at https://github.com/Clear-Bible/macula-greek/"

**Pinned versions.** SAGE reads one exact commit of each dataset and refuses any other bytes:

| Dataset | Commit | File | SHA-256 |
|---|---|---|---|
| MACULA Hebrew (WLC) | `df1ea5d85c8cb194278a874d6c670cd1d8abd97f` | `WLC/tsv/macula-hebrew.tsv` | `965cb0599beed2fe31283b615bcc369178141c0e718a66d97518d94309cfc124` |
| MACULA Greek (SBLGNT) | `076282a3926625a5e670823b0738ce5f1e619528` | `SBLGNT/tsv/macula-greek-SBLGNT.tsv` | `7f71504fdee8659bdd9f85342e4103d645864c2851b8205915bb298f0c004cc5` |

**What SAGE uses and ships.** The NCA typed numbers package (`system/resources/numbers/2026-10-09/`,
package `SAGE_NUMBERS_TYPED_2026-10-09`) is built from these tables by
`system/tools/build_numbers_index.py`. It ships the original-language verse text and number words of
the verses that contain numbers, and MACULA word identifiers as source references. NCA reports quote
that verse text.

The original-language analysis package (`system/resources/ol-analysis/2026-10-15/`, package
`SAGE_OL_ANALYSIS_2026-10-15`, built by `system/tools/build_ol_analysis.py`) ships every MACULA word with its
text, lemma, Strong's number, morphology fields, and gloss. SAGE uses it to check the original-language
words a model cites in STC findings, RTC original-language adjudications, and BIC original-language checks,
and reports quote MACULA's lemma, parse, and gloss for those words.

**Changes made (CC BY 4.0 §3(a)(1)(B)).** SAGE reads only the identity, surface text, lemma, morphology,
Strong's and gloss columns; normalizes text to Unicode NFC; maps MACULA's Hebrew/Greek verse numbering to
English versification; and derives typed number values (cardinal, ordinal, fraction, date, and so on)
from the words. The typed values and review decisions are SAGE's own; they are not part of MACULA. The
analysis package keeps MACULA's values unchanged; it selects columns and normalizes text and lemmas to NFC.

**Data inside MACULA from other sources.** MACULA includes material under its own terms. SAGE ships
only the parts listed above:

| Source inside MACULA | Terms | SAGE use |
|---|---|---|
| Westminster Leningrad Codex (Hebrew text) | Public domain (tanach.us: "may be viewed or copied without restriction") | Verse text, number words, and analysis package |
| [Open Scriptures Hebrew Bible](https://github.com/openscriptures/morphhb) lemma and morphology | CC BY 4.0. Credit: "Open Scriptures Hebrew Bible Project" | Number typing; lemma and morphology in the analysis package |
| [SBL Greek New Testament](https://github.com/LogosBible/SBLGNT) | CC BY 4.0. "Copyright 2010 by the Society of Biblical Literature and Logos Bible Software" | Verse text, number words, and analysis package |
| Westminster Hebrew Syntax (J. Alan Groves Center) | CC BY 4.0 | Not used |
| Cherith Glosses for the Hebrew Old Testament (Andi Wu, © 2022 Cherith Analytics) | CC BY 4.0. Credit: "Cherith Glosses for the Hebrew Old Testament, by Andi Wu, Copyright (C) 2022 by Cherith Analytics" | Hebrew glosses in the analysis package |
| Berean Interlinear glosses (Greek `gloss`) | Public domain since 2023-04-30 | Greek glosses in the analysis package |
| UBS Semantic Dictionary of Biblical Hebrew (`sdbh`, `*domain`) and MARBLE / Louw-Nida (`ln`, `domain`) | © United Bible Societies, "used with permission" in MACULA; not covered by Biblica's CC BY grant | **Never read or shipped.** Any future use needs UBS terms first. |

## Other data SAGE ships or quotes

| Source | Terms | Attribution SAGE gives | Where |
|---|---|---|---|
| New International Version (NIV) | © 1973, 1978, 1984, 2011 by Biblica, Inc. | NIV numbers and references only; no NIV Scripture text is shipped or quoted | NCA package |
| Berean Standard Bible text and footnotes | Public domain since 2023-04-30 | "Berean Standard Bible, public domain (berean.bible; ebible.org engbsb)." | NCA package, NCA reports |
| SBLGNT apparatus | CC BY 4.0 | "SBLGNT apparatus, Society of Biblical Literature and Logos Bible Software (Faithlife/SBLGNT), CC BY 4.0." | NCA reports |
| OSHB ketiv/qere | CC BY 4.0 | "Open Scriptures Hebrew Bible (openscriptures/morphhb), CC BY 4.0." | NCA reports |
| NET Bible® text-critical notes | © 1996, 2019 Biblical Studies Press, L.L.C.; all rights reserved | Short excerpts quoted under fair use with the NET attribution line and a link | NCA reports |
| King James Version (1769), Brenton Septuagint (1851), Douay-Rheims (Challoner) | Public domain | One line each in the report | NCA reports |
| Standard versification schemas | MIT | `system/resources/scripture/standard-vrs.LICENSE.txt` | `system/resources/scripture/` |

## Bundled `@GRK` and `@HEB` Scripture

The bundled Greek and Hebrew SFM under `system/resources/scripture/original-language/` have no recorded
edition, copyright holder, or redistribution authority yet (`authority-profile.yml`:
`AMBIGUOUS_EDITION_LABELS` and `EDITION_UNRESOLVED`). Their provenance must be resolved before a public
release; see [Original-Language Resources](ORIGINAL-LANGUAGE-RESOURCES.md).

## Operator-supplied Projects

Operator Projects and their rights are governed per Project; see
[Resource Rights and Provenance](RESOURCE-RIGHTS-AND-PROVENANCE.md).
SAGE does not infer any permission from a file being present.
