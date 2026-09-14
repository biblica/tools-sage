# NCA optimization qualification

The current measured implementation is `ec3e46fad44d0375ad7d33f948d28df4863632a0`. Initial final review returned **WITH_FIXES** at `04559e5a855d887a92342c379323c29112d0b09a`; the first scoped review returned **NOT_APPROVED** at `25c3fcc8af9cc630062291d02625625ee745af7d` because of residual F1. The bounded F1 correction is complete; residual verification is **PENDING**. Task base remains `1067c172c80e71f650b9d7b436e6f9fa5e1cabe4`. Core remains `0.02b1`; the user branch remains `0.02a2`. The original [NCA qualification](NCA-QUALIFICATION.md) and [reference qualification](NCA-REFERENCE-QUALIFICATION.json) are preserved byte-for-byte.

The separate [synthetic receipt](NCA-OPTIMIZATION-BENCHMARK.json) binds exact implementation files, fixtures, SFM/projection identities, package/style/check settings, route and strategy-specific benchmark contracts. It measures real `ProviderRequest` objects through the existing model-task boundary with recorded responses. It does not certify model interpretation.

## Deterministic qualification

The controlled fixture contains 32 small MAT 5:1–32 units, with explicit correct counts and complete omissions. Both strategies receive the same source, profile, checks, provider, model and reasoning selection. Baseline extraction uses its version-1 contract; optimized extraction uses version 2 and cap eight. Semantic and exact typed extraction labels remain independent of observed outcomes; finding labels include row attribution and multiplicity.

Required gates are four optimized extraction requests, at least 50% fewer extraction requests, lower aggregate request bytes, one measured bundle load/style validation, unchanged non-bridge goldens, correct labeled bridges and no additional requests when reopening valid checkpoints. Coverage retains explicit restrictions from unspecified presentation rules. No absent reference row is interpreted as an authoritative zero-number row.

The failure corpus covers one transient failure, malformed responses through every binary split, accepted PARTIAL, accepted UNSUPPORTED, and reopened durable checkpoints. With one retry per node, four complete failing eight-unit trees permit `2 × (2 × 32 − 4) = 120` extraction attempts. Failure evidence remains separate from admitted receipts. Timings are observations without CI thresholds; usage remains null when the recorded provider does not report it.

The numeric release suite covers the original acceptance examples, all 21 registered-reading rows/42 choices and 12 registered-unit pairs, plus typed bridge positives, omissions, extra numbers, referent mismatches, partial/unindexed/registered-absence rows, row-specific policies and immutable version-1 replay. Canonical import-to-report tests additionally validate two chapters with missing scope through the production v2 validator and check unique navigation ownership. PARTIAL component limitations preserve their original row-specific reason.

## Separately initiated live comparison

**LIVE_MODEL_BENCHMARK_NOT_RUN. SQS: NOT_APPLIED.** This delivery makes no model/language accuracy or speed qualification claim. Native Windows and native Python 3.10 execution were unavailable; the unchanged CI matrix retains Linux/macOS/Windows with Python 3.10/3.12. Actual local execution is recorded in the receipt.

A live comparison requires an explicit existing NCA Job and a current valid sealed version-2 Run. The selected Project and scope must match that Run exactly; its compatible Number Style Profile remains mandatory with presentation OFF. Current package, source, style and route checks must pass. Existing staleness checks remain active. The benchmark does not create, abandon, reseal or update Jobs or Runs.

```sh
python system/tools/benchmark_nca.py --mode live \
  --settings /absolute/path/ecosystem.yml \
  --job EXISTING_NCA_JOB --run EXISTING_NCA_RUN \
  --project EXISTING_WIP_PROJECT --scope 'MAT 5:1-32' \
  --labels /authorized/local/reviewed-labels.json \
  --repetitions 3 \
  --receipt /authorized/runtime_state_root/nca-benchmarks/comparison/receipt.json
```

The normal installed routing/readiness/authentication path selects the provider. There is no additional credential route. Each repetition uses a fresh benchmark-owned runtime subtree; order alternates between strategies. Full source requests, responses and checkpoint evidence remain in that local subtree. The shareable receipt contains input/response hashes, case metrics and canonical finding codes, not Scripture payloads. Receipt destinations must be new paths below the configured runtime state root's `nca-benchmarks` directory.

Operator labels use schema version `1.0`, nonempty `reviewed_by` and `reviewed_at`, `input_sha256`, and one `cases` entry per protected body/style unit. Obtain the input identity locally with `benchmark_nca_live.live_input_identity(inputs)` after normal `prepare_execution_inputs(config, job, run, load_nca_run_snapshot(run.root))`; this is a read-only preparation step. Labels require independent human review before live execution.

Each case contains `unit_id`, `categories`, exact `expressions`, expected `outcome`, `finding_codes` and `findings`. Expressions retain surface, span, rational value strings, kind, unit, qualifier, role and optional dual representations. Finding objects contain exactly `code`, `category`, `severity`, `target_references`, `western_references`, `ol_references`, `selected_reading`, `source_ids`, and `evidence_ids`. Empty expected arrays are explicit labels, including true omissions and number-free cases. Critical categories are `omission`, `extra_number`, `referent`, and `bridge`.

Labels must match the exact selected input fingerprint and every unit; malformed, mismatched or incomplete labels stop before provider execution. Missing critical categories produce **INCOMPLETE**, never an accuracy pass. Critical numeric cases also remain **INCOMPLETE** when numeric assessment is OFF or the actual numeric outcome is `NOT_ASSESSED`, even when reviewed labels expect that result. Their finding correctness is unavailable (`null`), with `CRITICAL_NUMERIC_ASSESSMENT_UNAVAILABLE` reported explicitly. Presentation-only Runs still execute with their selected checks, and their labels cannot qualify critical numeric coverage. Each repetition reports per-case extraction recall/precision, exact values/types/roles, finding correctness including row attribution, unresolved rate, measured timings and available provider usage. A selected-case pass requires complete critical coverage, correct optimized labels, no unresolved case and no critical regression; it makes no broad model/language qualification claim.

## Release evidence

The historical six-command sequence below passed on the corrected complete tracked release bundle. Its evidence remains attached to `1512e26`; the subsequent `6001294` amendment and first `93fe808` fixes and residual `ec3e46f` correction have separate qualification evidence. The first scoped verdict is NOT_APPROVED due to F1; residual verification remains pending.

The NCA capability limitation remains: model interpretation of language-specific numeric expressions, correspondence and note meaning requires independent qualification. SQS: NOT_APPLIED.


| Controlled MAT 5:1–32 measurement | Baseline | Optimized |
|---|---:|---:|
| Extraction requests | 32 | 4 |
| Total physical requests | 64 | 36 |
| Request bytes | 447133 | 287953 |
| Response bytes | 28063 | 28640 |
| Total transport bytes | 475196 | 316593 |
| Reference loads | 1 | 1 |
| Profile validations | 64 | 1 |
| Measured execution milliseconds | 56 | 443 |

Extraction requests decrease 87.5%; aggregate request bytes decrease about 35.6%. Timings describe recorded-provider/local persistence overhead only; they do not show a model speedup. The separate-process cold run took 1008ms; the resumed process took 639ms, requalified both resources once, reused 36 checkpoints and made zero calls. The transient workload records 37 calls including one failure; malformed responses reach the exact 120-attempt bound; accepted PARTIAL and UNSUPPORTED each make four calls with no pass outcome. All retain 32 outcome entries and explicit scope evidence.

| Required clean-source command | Result | Elapsed seconds |
|---|---|---:|
| `python -m pytest -p no:cacheprovider system/tests/numbers` | 815 passed in 142.01s (0:02:22) | 143.097 |
| `python system/tools/validate_schemas.py` | PASS | 0.261 |
| `python system/tools/validate_package.py` | READY | 0.915 |
| `python -m pytest -p no:cacheprovider system/tests` | 1926 passed in 632.09s (0:10:32) | 632.828 |
| `python system/tools/deep_audit.py . --mode source` | PASS | 7.204 |
| `python system/tools/validate_numbers_reference.py --package "$NCA_REFERENCE_DIR" --release --receipt "$NCA_RECEIPT_PATH"` | PASS | 26.678 |

The six-command sequence above qualified implementation `1512e260867ea2708d2b02c4cfb556906e72e7d0`. The bounded live-evidence correction in `6001294dc2360ede1cdab445e5df8aedb64771da` then passed all 32 benchmark tests and its full repository suite: 1929 passed in 592.60s (0:09:52). The original package, parser and qualification fixtures remain unchanged; the real-reference gate retains that exact evidence.

Current measured implementation code inventory SHA256: `37828dd7356d609a73224affefb5a1e97fa985638a477cbc5c0857edc52d3af7`. Controlled shared input SHA256: `697d2ccafd838cbb2f2ad3d228bca5577df53e9f78f1729b313ae0b7329c3b09`. Strategy contract and exact fixture hashes are retained separately in the receipt.

The retained original real-reference gate authenticates the package to `b04a08e7e51e405defeb1c1821a8fb3c63bf1af4f6bda7ce7c4fff268b19b202`; its 38-file complete inventory SHA256 is `770182f6bfaa967ba53ab52b6256520ffb52aa5865cda7fa34ed53a9236eda5d`. Its release acceptance passes all 15 original numeric examples, 42 registered-reading choices and 12 unit pairs. The original ZIP hash `f4b826a167c6f26f05799f121d9f279cd89db3cd5d7d9bca916fc3a9baf775b1` is previously verified provenance; that archive is no longer at the prior path and was not freshly rehashed. No package or original qualification file changed.

The initial app-only staging attempt omitted tracked bundle-root files and therefore failed ten launcher/documentation/release-builder tests. The corrected complete bundle passes them; no functional source change was needed. Schema IDs and Skill contracts were unchanged by Task 9, so no additional schema or Skill inventory entry was required. The vanilla manifest includes the two bounded benchmark helpers, new fixture and separate qualification artifacts.

Canonical capability limitation: Findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities. SQS confidence checks have not been applied. SQS: NOT_APPLIED. Initial final review: WITH_FIXES. First scoped review: NOT_APPROVED due to F1. Residual verification: PENDING.

## Consolidated final-review fixes

I1 is resolved in `93fe80837145af022b5c1e13e820afffc4992fba`. If interruption leaves staged output or receipt without a manifest, preparation first validates the current accepted checkpoints and controller-derived final objects. It then atomically moves the uncommitted staging directory to a unique `validation/nca-phases/abandoned-publications/<attempt-id>/` diagnostic directory and prepares current output and receipt. Retained bytes have no publication authority. Unexpected entries, symlinks, hard links, escaped destinations and canonical files without a manifest remain rejected. Committed manifests and their staged payloads remain immutable.

Canonical regression tests cover interruption after staged output, after staged receipt, after the manifest and after the first canonical write. They require zero repeated accepted-phase provider calls, exact canonical/staged output and receipt reconciliation, unchanged accepted checkpoint associations, and preserved physical failure history. Fresh pre-manifest execution may retry previously failed phases; those new physical attempts are also counted. Altered orphan bytes cannot override valid derived results or bypass corrupted checkpoint rejection. Retirement interrupted before or after its atomic rename also resumes with original diagnostic bytes retained.

M1 rejects nondefault `--fault` before dispatch unless `--mode synthetic --strategy optimized` is selected. Baseline, paired and live rejection tests accompany all four supported synthetic fault positives. M2 corrects `optimized_run_dispatch` to `activated` in the phase-ledger schema.

Historical first-fix qualification at `93fe808` passed: 1944 passed in 605.00s (0:10:04). Schema validation reports 52 schema IDs/PASS, package validation reports READY, and deep source audit reports PASS; all have no warnings. This is the single complete repository suite after I1/M1/M2, including all NCA tests; it predates F1 and is not claimed as a fresh run on the residual correction. The final metadata bundle receives separate schema/package/source-audit and documentation checks, with exact logs retained in the final-fix report. The covering regression run passed 189 tests, including 35 benchmark tests. Python 3.10 grammar and punctuated function/class docstrings pass for seven changed Python files; this is not native Python 3.10 execution. The controlled, labeled-corpus, fault and cold-process measurements were regenerated again for the current residual implementation identity. The 12-case labeled corpus still records 19 baseline versus 13 optimized calls and zero finding differences.

The original reference release command was not repeated: its implementation dependencies, all qualification fixtures, both original qualification documents, and the complete 38-file authorized unpacked package remain byte-identical. The existing 15-example/42-choice/12-unit gate is retained with its original log identity. The original archive hash remains prior verified provenance only. No new shipped file was added, so the vanilla installation manifest does not require a refresh.

| Historical functional fix gate at `93fe808` | Result | Elapsed seconds |
|---|---|---:|
| `python -m pytest -p no:cacheprovider system/tests` | 1944 passed in 605.00s (0:10:04) | 606.269 |
| `python system/tools/validate_schemas.py` | PASS, 52 schema IDs, no warnings | 0.266 |
| `python system/tools/validate_package.py` | READY, no warnings | 0.84 |
| `python system/tools/deep_audit.py . --mode source` | PASS, no warnings | 8.585 |

Exact first-fix gate log SHA256 identities are recorded in the benchmark receipt under `fix_gates`, bound to `fix_gate_implementation_commit`; historical `release_gates` and `amendment_gates` retain their original revision-specific evidence. The final metadata bundle checks and exact tracked-source inventories remain in the external final-fix report. First scoped review is NOT_APPROVED due to F1; residual verification is PENDING.

## F1 residual correction and bounded qualification

The first scoped review found that the new retirement helper rejected a legitimate temporary file left by `atomic_write_bytes` after process death before `os.replace`. F1 is corrected in `ec3e46fad44d0375ad7d33f948d28df4863632a0`: only full filenames matching `\.(?:output|receipt|manifest)\.json\.[A-Za-z0-9_-]+\.tmp` may join the existing uncommitted payload diagnostics. The nonempty token convention is explicitly governed and independent of private interpreter token lengths or alphabets. Neither the filename nor its bytes establish publication authority. Exact diagnostic write declarations cover these three destinations; model writes remain unchanged. Unknown names, symlinks, hard links, unsafe ancestors and unauthenticated canonical output remain rejected.

Portable subprocess tests actually terminate with `os._exit(73)` before the shared atomic rename for output, receipt and manifest. They verify canonical recovery, exact output/receipt reconciliation, zero repeated accepted-phase calls, preservation of accepted and failed physical history, altered temporary bytes retained only as diagnostics, and corrupted accepted evidence rejected without retirement. Filename lookalikes, unknown entries and linked temporary files remain negative cases. All earlier four-window and retirement regressions remain in the covering suite.

Current covering qualification passed **219 tests in 81.10s**, including **35 benchmark tests** and nine actual process-death cases. Five changed Python files pass Python 3.10 grammar, punctuated function/class docstrings and required long-function comments. Current provider-free measurement binds all 249 implementation hashes, four unchanged fixture hashes and ten strategy receipts to the residual revision. The 13 controlled gates pass; calls/payloads and labeled findings are unchanged. Native platform/provider limits remain as stated above.

The current schema/package/source checks below use the complete tracked bundle. Final metadata additionally receives schema/package/source-audit/documentation checks, with exact logs in the appended residual report. The prior 1,944-test full-suite evidence remains valid for `93fe808`; no second broad suite was run for this bounded recognizer/declaration change. Original qualification documents, reference interpretation dependencies, fixtures and all 38 authorized package files remain unchanged, so the original reference gate remains applicable.

| Current residual source gate at `ec3e46f` | Result | Elapsed seconds |
|---|---|---:|
| `python system/tools/validate_schemas.py` | PASS, 52 schema IDs, no warnings | 0.376 |
| `python system/tools/validate_package.py` | READY, no warnings | 0.949 |
| `python system/tools/deep_audit.py . --mode source` | PASS, no warnings | 8.371 |

Initial WITH_FIXES and first scoped NOT_APPROVED are historical verdicts. Residual verification remains PENDING until the controller records actual reviewer confirmation; this document does not approve integration.
