# NCA NIV (secondary authority) number layer

> **Status 2026-10-09.** The runtime package is `SAGE_NUMBERS_TYPED_2026-10-09` (`sage-numbers-typed-1.1`). All open review items were resolved by the NIV number rule (eac267d, REVIEWER `RULE-2026-10-08`), and the package has no provisional rows. Current package counts: 3,814 verses, 5,345 original-language values, 5,021 NIV values. The generated figures below predate that resolution. No NIV Scripture text is shipped: the package quotes the public-domain BSB and cites the NIV by its numbers.

Typed NIV values counted with `system/tools/build_numbers_index.py niv-build` from the local
`usNIVv2` Paratext project by the shared counting convention, and compared verse by verse with
the rebuilt original-language layer (`TYPED-NUMBERS.tsv`). Original language stays the only
BLOCKING authority; NIV is secondary evidence (see `docs/advanced/future/AUTHORITY-POLICY.md`).

Typed NIV values: 5022 in 3485 verses (APPROX 66, CARDINAL 4323, FRACTION 49, ORDINAL 584).
Evidence rows (NIV text SHA-256 + count of number-bearing footnotes; no NIV text is shipped): 6244.

## OL / NIV agreement (typed, per Western verse)

| MATCH_STATUS | Verses |
|---|---:|
| DIFFERENT_NUMERIC_EXPRESSION | 475 |
| NIV_EXPLICIT_OL_NONEXPLICIT | 334 |
| OL_EXPLICIT_NIV_NONEXPLICIT | 330 |
| PASS_EQUIVALENT_REORDERED | 46 |
| PASS_EXACT | 2630 |

## Differences from the 2026-09-09 package NIV_VALUES

2888 verses differ. `NIV-REVIEW-DECISIONS.tsv` has one row each with a reason class; a
`SUGGESTED_DECISION` of `REBUILT` marks classes the counting convention decides on its own.

| Reason | Verses |
|---|---:|
| SCOPE: PRONOUN_ONE | 1749 |
| SCOPE: RANK_ORDINAL | 426 |
| SCOPE: BOTH | 250 |
| SCOPE: FRACTION_NO_MEASURE | 123 |
| OTHER | 79 |
| SCOPE: FREQUENCY | 72 |
| SCOPE: IMPLICIT_NUMBER | 34 |
| SCOPE: INDEFINITE_PLURAL | 31 |
| SCOPE: PRONOUN_ONE;RANK_ORDINAL | 29 |
| SCOPE: BOTH;PRONOUN_ONE | 29 |
| SCOPE: FREQUENCY;PRONOUN_ONE | 10 |
| SCOPE: FRACTION_NO_MEASURE;PRONOUN_ONE | 9 |
| SCOPE: PAIR | 8 |
| SCOPE: FRACTION_NO_MEASURE;RANK_ORDINAL | 8 |
| SCOPE: BOTH;RANK_ORDINAL | 5 |
| SCOPE: PAIR;RANK_ORDINAL | 4 |
| SCOPE: IMPLICIT_NUMBER;RANK_ORDINAL | 3 |
| SCOPE: BOTH;IMPLICIT_NUMBER | 3 |
| SCOPE: FREQUENCY;IMPLICIT_NUMBER | 3 |
| SCOPE: PAIR;PRONOUN_ONE | 2 |
| SCOPE: PART_NOUN | 2 |
| SCOPE: FRACTION_NO_MEASURE;PART_NOUN | 1 |
| SCOPE: BOTH;IMPLICIT_NUMBER;PRONOUN_ONE | 1 |
| SCOPE: INDEFINITE_PLURAL;RANK_ORDINAL | 1 |
| SCOPE: BOTH;FRACTION_NO_MEASURE | 1 |
| SCOPE: FREQUENCY;IMPLICIT_NUMBER;RANK_ORDINAL | 1 |
| SCOPE: INDEFINITE_PLURAL;PRONOUN_ONE;RANK_ORDINAL | 1 |
| SCOPE: FRACTION_NO_MEASURE;IMPLICIT_NUMBER | 1 |
| SCOPE: FRACTION_NO_MEASURE;FREQUENCY | 1 |
| SCOPE: NAME | 1 |

## Source

- New International Version (NIV) 2011, Biblica, Inc.; Copyright © 1973, 1978, 1984, 2011 by Biblica, Inc.
- Local Paratext project read at build time; combined sha256 `add35fb810a3162eeb8634ccd68982322a5ea68ffe9911efce62e1b02df5cfd2` (per-book
  digests in `NIV-BUILD-MANIFEST.json`). No NIV Scripture text is shipped (NIV fair use allows at most
  500 verses): verse text is quoted from the public-domain Berean Standard Bible and the NIV is cited
  by reference and its numbers ("also see").
