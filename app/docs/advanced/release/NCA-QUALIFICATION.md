# NCA qualification record

This record separates reference integrity, deterministic acceptance, and model language capability. The NCA implementation is on development branch `0.02a2`. SQS confidence checks are not implemented.

## Environment and baseline

Qualification uses an isolated environment with the existing pinned application, development, and TUI requirements. The local interpreter is Python 3.12.4 on macOS 26.6.2, ARM64. Recorded packages include PyYAML 6.0.3, pytest 9.0.2, and openpyxl 3.1.5.

The clean starting source at `b7c6a65` passed **1,103 tests in 365.63 seconds**. Existing working-directory `.DS_Store`, `__pycache__`, and nested OL archive artifacts were kept separate from source qualification. Final source gates run on a clean staged copy, preserving those workspace artifacts.

## Authorized reference evidence

The original ZIP SHA-256 is:

```text
f4b826a167c6f26f05799f121d9f279cd89db3cd5d7d9bca916fc3a9baf775b1
```

The qualified package identity hash is:

```text
b04a08e7e51e405defeb1c1821a8fb3c63bf1af4f6bda7ce7c4fff268b19b202
```

A fresh isolated extraction of that archive passed the real-reference gate with 6,244 rows; 4,392 numeric OL rows; 6,800 OL values; 21 variants and guidance rows; 12 unit examples; 341 classified tokens; and 38 provenance sources. The gate exercises both selections for all 21 registered readings, every registered unit pair with explicitly retained unrelated quantities, and 15 handover numeric examples. It confirms that DAN 1:10 remains unindexed. NIV residual changes at LUK 16:7 and JHN 19:39 remain review cases because the unit registry does not authorize unrelated additions or omissions.

`REFERENCE_LINEAGE_INCOMPLETE` remains a nonblocking warning: 47 differing rows, 51 additional authoritative values, 16 additional numeric rows, and 6,749 supplementary expressions. Three unit display-spacing differences and two registered OL coordinate-boundary exceptions remain documented diagnostics. The minority-reading caution at 1SA 6:19 and registered OL absence at NEH 7:68 are retained.

The first measured full-package integrity and domain acceptance run took **25.8466 seconds** with Python allocation tracing enabled; peak traced allocation was **36,635,309 bytes**. On the final reviewed implementation, the expanded gate passed in **26.9817 seconds**, with **36,600,562 bytes** of peak traced allocation. These are observed local measurements, not throughput guarantees or total process memory measurements. The separate [reference qualification receipt](NCA-REFERENCE-QUALIFICATION.json) records all outcomes.

An existing extracted handover directory failed the checksum for `docs/SAGE_NUMBER_STYLE_PROFILE.txt`. Qualification used a fresh extraction of the original ZIP instead. Neither existing source was repaired or overwritten. The inherited workbook/source `PENDING_FINAL_RUN` gate remains unchanged.

## Repeatable gates

From `app/`, use the isolated pinned interpreter:

```sh
python -m pytest -q system/tests/numbers
python system/tools/validate_schemas.py
python system/tools/validate_package.py
python -m pytest -p no:cacheprovider system/tests
python system/tools/deep_audit.py . --mode source
python system/tools/validate_numbers_reference.py --package /path/to/unchanged/package --release --receipt /path/outside/package/nca-reference-qualification.json
```

Synthetic CI tests require no operator archive or paid model calls. The explicit `--release` gate requires the unchanged authorized package and the complete source acceptance fixtures. Missing evidence, corruption, contradictory policy, or failed golden cases produce a nonzero exit status. Qualification receipts are separate from immutable source resources.

## Acceptance traceability

The synthetic tests under `system/tests/numbers/` cover the complete implementation plan:

| Contract | Evidence |
|---|---|
| Immutable import, exact values, joined registries, provenance, and qualification | `test_reference.py`, `test_reference_release.py`, and the separate real-reference receipt |
| Target/note separation, Western mappings, canonical Psalm titles, boundary groups, and missing coordinates | `test_target.py`, `test_projection.py`, `test_scope.py` |
| Routed model identity, exact spans, structured numeric types, uncertainty, and semantic correspondence | `test_extraction.py`, `test_model_tasks.py`, `test_compare.py` |
| Whole registered readings, exact unit pairs, required/recommended disclosure, and no duplicate note advice | `test_variants.py`, `test_units.py`, `test_footnotes.py` |
| Mandatory configured profiles, three independent checks, and disabled assessments | `test_style.py`, `test_policy.py`, `test_nca_jobs.py` |
| Source evidence, counters, coverage, localized reports, sealed lifecycle, concurrency, and canonical operator routes | `test_engine.py`, `test_results.py`, `test_reporting.py`, `test_nca_tasks.py`, `test_nca_cli.py`, `test_nca_menu.py`, `test_acceptance.py` |

The end-to-end acceptance test imports reference and style resources, creates a Job and Run through canonical CLI handlers, executes controlled provider responses, submits and finalizes, and verifies deterministic reports. It also checks unsupported interpretation, immutable input bytes, and replay after changed Job defaults. Existing repository tests cover the integration with other workflows and source distribution.

## Capability and distribution limits

Deterministic/reference acceptance does not measure the selected model's performance in a target language. Structured model tests use controlled provider responses to verify evidence, routing, failure handling, and orchestration; they are not measured SQS confidence qualification. No live paid model call is part of CI qualification.

Findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities. SQS confidence checks have not been applied.

No supplied Scripture archive or full-text index is added to Core or published by these gates. Distribution remains subject to the existing resource-rights metadata and governance. Local qualification does not establish that every supported operating system/Python combination has been exercised; the repository CI matrix remains the authority for those runs. That unchanged matrix covers Ubuntu, Windows, and macOS on Python 3.10 and 3.12; its existing full-suite command automatically includes the NCA synthetic tests.

## Final implementation gates

All eleven implementation-plan tasks are complete on branch `0.02a2`. Final review approved the implementation through `1ea6980` with no unresolved blockers and 199 passing focused review tests.

The clean source at `1ea6980` passed **1,530 tests in 391.28 seconds**, including all **427 NCA tests**. Schema validation passed with 48 schemas, 48 owners, and 11 source-instance groups. Package validation returned `READY`; the source deep audit returned `PASS` with no errors or warnings and all ten registered Skills. The real-reference release gate also passed on this reviewed source; its exact results and measurements are recorded above and in the separate receipt.

The final documentation and Core workflow qualification metadata are checked again with the documentation/profile tests and schema, package, and source-audit gates. Core NCA is marked `VALIDATED` for these deterministic workflow and reference contracts. This does not change the inherited workbook/source `PENDING_FINAL_RUN`, qualify live model language accuracy, or apply SQS confidence checks.
