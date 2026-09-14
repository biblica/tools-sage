# Bundled NCA reference validation — 2026-09-14

SAGE now includes its qualified NCA reference tables as Core resources. A clean installation can create an NCA Job without importing an archive. Additional qualified archives remain optional; existing Jobs retain their explicit reference identity. Jobs, Runs and tasks seal the selected Core or imported package through the same validation contract.

## Reference identity

- Core package: `SAGE_NUMBERS_REFERENCE_2026-09-09`.
- Core checksum inventory SHA-256: `51914b13d9cf63e9808eceb41671ea1b30f1f1400cf15db51fef75bbbe0ebf8d`.
- Original handover checksum inventory SHA-256: `b04a08e7e51e405defeb1c1821a8fb3c63bf1af4f6bda7ce7c4fff268b19b202`.
- All 12 runtime reference tables/text files are byte-identical to the authenticated September 9 handover. September 10–11 testing refined software interpretation and validation; the existing qualification evidence records unchanged reference bytes.
- The wrapper has its own identity and manifest. Original manifests, checksums, verification and distribution records remain under `provenance/`. Source ZIPs, the duplicate workbook and development documents are not part of the runtime reference package.

## Numeric and ambiguous-reading acceptance

The [fresh release receipt](NCA-BUNDLED-REFERENCE-VALIDATION.json) passes the current refined acceptance gate with `QUALIFIED_WITH_DIAGNOSTICS`:

| Check | Result |
| --- | --- |
| OL/NIV indexed coordinates | 6,244 paired rows |
| Numeric values | 6,800 OL; 8,442 NIV |
| Operator/canonical index agreement | PASS across all rows |
| Registered ambiguous readings | All 42 choices across 21 coordinates pass |
| Notes | All choices retain source IDs and nonempty guidance; missing required/recommended notes produce the registered review/advisory outcome |
| Numeric regression cases | 15 pass |
| Registered unit examples | 12 pass |
| Classified OL token audit | 341 rows retained |

The alternate reading at 1SA 6:19 retains its caution. NEH 7:68 remains a registered OL absence, rather than an ordinary numeric pass. The supplementary expression lineage remains incomplete at 47 rows (51 authoritative values beyond that supplementary audit); authoritative operator values remain unchanged. Three unit-display spacing differences and two OL coordinate-boundary exceptions remain explicit in the receipt.

From the application directory, reproduce the reference gate with the governed Python environment:

```sh
python system/tools/validate_numbers_reference.py --package system/resources/numbers/2026-09-09 --release --receipt /tmp/nca-reference-validation.json
```

## Local source-text readback

The [source-readback receipt](NCA-BUNDLED-SOURCE-READBACK.json) records a fresh comparison against the authenticated original GRK, HEB and NIV source archives (132 source files). Current SAGE USFM-to-USJ parsing supplied verse text; whitespace runs were normalized, OL coordinates followed the index mapping, and the PSA 60:0 title was read from its descriptive-title marker.

All 6,243 nonempty OL entries matched, with NEH 7:68 explicitly absent. NIV had 6,224 matches and 20 text differences: 12 whitespace-only differences and eight content/punctuation differences already documented in the original audit. The latter occur at GEN 7:20, 1SA 7:2, 1KI 5:11, NEH 7:73, PSA 119:72, PRO 8:22, EZK 42:16 and HAG 1:15.

Two omissions include continuation numbers: the NIV index omits “seventh month” at NEH 7:73 and “second year of King Darius” at HAG 1:15. These are known limits of the supplied NIV reference text. This validation does not establish complete numeric coverage of those source continuations, and they must not be interpreted as verified zero-number text. The original table bytes were retained, with these findings recorded separately.

This validates supplied indexes, their provenance, registered reading/note behavior and local source text. It is not an independent Hebrew/Greek numeric re-extraction, a new scholarly review, or a target-language model accuracy assessment. No live model calls or SQS checks were performed. Earlier handover and qualification receipts remain historical evidence and have not been replaced.
