# NCA — final reference-table audit

Date: 2026-09-09. **Conclusion: authoritative tables pass internal-contract audit, with documented limitations.**

Completed **22 audit checks: 18 PASS, 4 WARN, 0 FAIL**. This is a local reference-table audit, not a claim that NCA software is implemented or production-qualified.

The user has confirmed these indexes as authoritative: OL primary, NIV secondary, with the supplied uncertainty notes and provenance governing registered alternate readings. Nothing in this audit changes that authority or rewrites reference data.

[Machine audit receipt](2026-09-09-NCA-FINAL-REFERENCE-AUDIT.json) · [Updated design](2026-09-09-NCA-DESIGN.md) · [Updated implementation plan](../plans/2026-09-09-NCA-IMPLEMENTATION.md)

## Confirmed product contract

- NCA is an independent workflow at **Main Menu #5**, immediately after **STC #4**. SAGE Maintenance moves to #6.
- Check numeric accuracy against the authoritative indexes, with OL primary and NIV secondary.
- Check numeric presentation and consistency against the selected style guide, honoring context/location exceptions.
- For registered alternate or doubtful readings, assess the existing target footnote and recommend adding or revising it when disclosure is needed. Preserve adequate existing notes.
- Keep accuracy, style and footnote findings distinct; no automatic Scripture or footnote edits.

## What passed

| Area | Final evidence |
|---|---|
| Package | CRC valid; 37 listed checksums match; 36 manifest entries match bytes/hashes |
| Main index | 6,244 unique Western keys; exact numeric encodings valid |
| Authority agreement | Operator and canonical indexes agree on every OL/NIV numeric sequence and all common fields except 12 intentionally enriched unit-note cells |
| Registered uncertainty | All 21 variant records join correctly to their 21 footnote records and operator rows; values, classification, scholarship, note actions and source IDs agree |
| Unit rules | All 12 registered conversion quantities remain distinct from textual variants; classifications, source IDs and explanatory notes agree |
| Footnote policy | All 21 alternate choices require a note; OL choices require a note in 4 DIVIDED cases and recommend a note in the other 17 |
| Provenance | All referenced source IDs resolve to 38 records; expanded source URL fields match the source inventory; two OL local-source records legitimately have no web URL |
| Workbook | All 11 table exports match their workbook sheets; no formulas or error-typed cells across the 12 sheets |
| Mapping | Package and SAGE eng.vrs forward mappings agree at all 6,244 indexed keys |
| OL source text | All 6,243 nonempty OL_TEXT entries match the supplied corpus at stored OL_REF after whitespace normalization (4,675 HEB / 1,568 GRK) |
| OL corpus | All 39 HEB + 27 GRK SFM files are byte-identical to SAGE bundled sources |
| Token audit | All 341 token rows have recognized coverage classes |

No external source pages were fetched. URL checks establish inventory consistency and syntax, not link availability or independent scholarly verification. Numeric values were checked as authoritative data; this audit did not rebuild the Hebrew/Greek number extractor.

## Four recorded limitations and dispositions

### 1. Supplementary expression audit is incomplete

**Authoritative runtime:** 4,392 numeric rows / 6,800 values. **Supplementary audit:** 4,376 source coordinates / 6,749 expressions.

The 47 differing rows contain 51 additional authoritative values, including 16 rows absent from the expression audit. No supplementary-audit value is removed from the authoritative values. The operator and canonical indexes agree with each other. Matching normalization-override rows were not found for those 47 coordinates in the initial readback.

**Disposition:** use authoritative values unchanged; preserve `REFERENCE_LINEAGE_INCOMPLETE` and do not claim complete expression-span provenance at those rows. This is not a blanket block on using the indexes. The earlier planning document treated it as a mandatory reference-reconciliation gate; this final audit supersedes that interpretation based on the fuller cross-table checks and the user-confirmed authority.

### 2. Three unit-registry display copies omit spaces

| Verse | Unit-registry copy | Authoritative operator copy |
|---|---|---|
| LUK 13:21 | `poundsof` | `pounds of` |
| LUK 16:6 | `gallonsof` | `gallons of` |
| LUK 16:7 | `bushelsof` | `bushels of` |

**Disposition:** render the operator-index NIV_TEXT; consume the registered quantity/unit fields for conversions. Preserve source table bytes. The 12 unit notes present in the operator index but absent in the older canonical table are useful enrichment, not conflicts.

### 3. Two verse-boundary source attributions differ from shift-rule projection

| Western row | Stored authoritative OL_REF | Shift-rule projection |
|---|---|---|
| 1SA 20:42 | 1SA 20:42 | 1SA 21:1 |
| 1CH 12:4 | 1CH 12:4 | 1CH 12:5 |

Source readback confirms the numeric text at the stored OL_REF. The projected following source verses contain continuation material. Western verse text combines the boundary portions.

**Disposition:** preserve index OL_REF and Western lookup; do not replace the numeric source with the continuation. Add explicit attribution/grouping tests for non-Western targets. A mapping-only equality assertion would wrongly reject these index rows.

### 4. NIV source display/boundary readback is not identical everywhere

Of 6,244 indexed NIV entries, 6,235 match the existing SAGE verse parser after whitespace normalization. Eight ordinary verse entries differ; one canonical superscription is absent from the verse-only parser inventory.

| Reference | Observed difference | Required handling |
|---|---|---|
| GEN 7:20; 1KI 5:11; PRO 8:22; EZK 42:16 | Indexed display contains extra comma material | Preserve authoritative values; avoid treating punctuation remnants as numeric content |
| PSA 119:72 | Index appends the following `Yodh` heading | Keep editorial heading content out of verse numeric comparison |
| 1SA 7:2 | Source parser retains a following nonnumeric section continuation | Do not infer numeric disagreement from differing display extent |
| NEH 7:73 | Source continuation includes “seventh month,” absent from the indexed NIV_TEXT | Keep indexed NIV_VALUES authoritative; record incomplete source-continuation transcription |
| HAG 1:15 | Source continuation includes “second year,” absent from indexed NIV_TEXT (and not included in indexed HAG 2:1 text) | Keep indexed NIV_VALUES authoritative; do not silently append a 2 from source readback |
| PSA 60:0 | Canonical superscription has 12000; a verse-only parse has no verse 0 record | Extract the canonical superscription from structural content and assess its accuracy |

**Disposition:** retain the index as secondary numeric authority, with these explicit readback limits. This audit does not certify exhaustive transcription of all numeric NIV source continuations. Canonical superscriptions are not interchangeable with editorial headings.

## Preserve the actual reading-policy vocabulary

Two supplied outcomes are more specific than the generic handover examples:

- **1SA 6:19 alternate:** `CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE`. Retain minority-reading caution and require an adequate note; a generic accepted-variant summary must not erase the caution.
- **NEH 7:68 OL choice:** `NO_CONFIGURED_OL_READING`. This is an indexed absence with required disclosure, not a fabricated OL verse, a zero numeric value or an ordinary accuracy pass.

Both are valid source-policy states, not audit failures. Their raw policy strings, selected-reading identity and final footnote outcomes must survive into machine evidence.

## Complete registered uncertainty matrix

Values below are whole indexed numeric sequences. `∅` means no configured OL numeric reading at the registered omission row. RECOMMEND does not fail an OL accuracy match; REQUIRE means an inadequate/missing note must be reported.

| Western reference | OL primary | Registered alternate | Scholarship status | Note with OL | Note with alternate |
|---|---|---|---|---|---|
| JDG 14:15 | `7` | `4` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 1SA 1:24 | `3;1` | `3` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 1SA 6:19 | `70;50000` | `70` | OL_FAVORED | RECOMMEND | REQUIRE |
| 1SA 13:1 | `1;2` | `30;42` | RECONSTRUCTED_BUT_NOT_SECURE | RECOMMEND | REQUIRE |
| 1SA 13:5 | `30000;6000` | `3000;6000` | DIVIDED | REQUIRE | REQUIRE |
| 2SA 8:4 | `1700;20000;100` | `1000;7000;20000;100` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 2SA 15:7 | `40` | `4` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 2SA 24:13 | `7;3;3` | `3;3;3` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 1KI 4:26 | `40000;12000` | `4000;12000` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 1KI 5:11 | `20000;20` | `20000;20000` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 2KI 25:3 | `9` | `9;4` | NIV_FAVORED_RECONSTRUCTION | RECOMMEND | REQUIRE |
| 1CH 25:9 | `1;2;12` | `1;12;2;12` | STRUCTURAL_RECONSTRUCTION | RECOMMEND | REQUIRE |
| 2CH 3:4 | `20;120` | `20;20` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 2CH 22:2 | `42;1` | `22;1` | NIV_FAVORED | RECOMMEND | REQUIRE |
| 2CH 36:9 | `8;3;10` | `18;3;10` | NIV_FAVORED | RECOMMEND | REQUIRE |
| NEH 7:68 | `∅` | `736;245` | DIVIDED | REQUIRE | REQUIRE |
| EZK 26:1 | `11;1` | `11;12;1` | RECONSTRUCTED_BUT_NOT_SECURE | RECOMMEND | REQUIRE |
| EZK 40:49 | `20;11;1;1` | `20;12` | DIVIDED | REQUIRE | REQUIRE |
| EZK 42:4 | `10;1` | `10;100` | DIVIDED | REQUIRE | REQUIRE |
| EZK 45:1 | `25000;10000` | `25000;20000` | NIV_FAVORED | RECOMMEND | REQUIRE |
| EZK 45:5 | `25000;10000;20` | `25000;10000` | NIV_FAVORED | RECOMMEND | REQUIRE |

The machine receipt preserves source IDs and suggested wording for both selections at every row. Suggested wording is guidance; adequate disclosure need not use exactly those words.

## Reproducibility and remaining qualification

Archive SHA-256: `f4b826a167c6f26f05799f121d9f279cd89db3cd5d7d9bca916fc3a9baf775b1`.

Audit methods: standard-library ZIP CRC/SHA-256 checks, strict TSV field/number validation, keyed cross-table joins, openpyxl read-only cell comparison, existing SAGE VRS parsing/projection and USJ source-text readback. Original source text comparison ignores whitespace only; it does not normalize spelling, punctuation or numbers.

The supplementary audit remains a separate record. Neither the original package nor workbook gate cells were changed. `BASE_REGRESSION_GATE=PENDING_FINAL_RUN` remains the supplied historical status. NCA implementation, regression tests, accurate boundary/superscription handling, language capability validation and software release qualification still remain to be performed. Public-distribution source metadata remains as described by the handover.
