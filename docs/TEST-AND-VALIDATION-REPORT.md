# Test and Validation Report — SAGE RC7.04

## Regression inventory

The complete discovered source inventory contains **396 tests across 41 test modules**. **396/396 passed** in isolated/bounded module execution after the RC7.04 changes. Process-spawning modules are executed separately with file-backed output to avoid descendant-pipe lifetime affecting the test result. `scripts/hardening.py` applies the same per-module isolation from a clean temporary source copy and records source-tree/test-inventory provenance for release environments that can run the complete gate in one process lifetime.

RC7.04-specific coverage includes:

- SAW/BIC active-runtime isolation so an empty inactive workflow template cannot block the active Job;
- role-neutral SAGE Project Inventory with Job-only SOURCE/DONOR/TARGET/WIP/REFERENCE assignment;
- valid ISO Project addition without a preconfigured SAGE language profile, plus offline ISO suggestions for missing/invalid metadata;
- Paratext scan heartbeat/progress and Paratext-root-as-default Base VRS with sticky explicit override;
- Add Job / Remove Job and safe Remove Project from SAGE boundaries;
- auto-persisted setup with no manual SAVE prerequisite;
- guided Scripture scope selection and pre-Run work/token preview with Change scope;
- clean RC-state boundary and empty shipped translation-Project inventory;
- first-run packaged VRS + SAGE Project Inventory validation (`READY_EMPTY` is valid);
- persistent `settings.xml`-gated Paratext Project catalogue built when the Projects root is selected;
- `settings.xml` metadata normalisation including `LanguageIsoCode` values such as `en:::`;
- `canons.xml` included-book discovery, `.SFM` inventory comparison, and FB/NT/Portions classification;
- descriptive `custom.vrs` name/base parsing without inventing missing base metadata;
- Scope + Language catalogue filters, quick/full rescan, and `<Other location>` refresh;
- Project-centric inventory/maintenance and rejection of the obsolete Resources mapping menu surface;
- per-Project bilingual reporting overrides flowing to BIC TARGET and SAW WIP runtime configuration while UI language remains English;
- governed `@GRK` / `@HEB` separation from the ordinary SAGE Project Inventory;
- explicit local/Paratext OL override validation and runtime provenance under stable GRK/HEB binding IDs;
- absence of fabricated OL Scripture payload from the source distribution;
- quoted/escaped cross-platform path normalisation and parent Projects-root resolution;
- Python 3.10+, `venv`, pip, requirement-specifier, and `pip check` preflight;
- package/release-builder inclusion of governed OL resource slots;
- previous-RC filename rejection in package validation;
- protected BIC rewrite-detail and verb-selection contract hashes unchanged.

Existing authority, cardinality, bounded-write, VRS, semantic-index, Run, transaction, storage, segmentation, generation, routing, and workflow regression modules remain in the same complete inventory under capability-based filenames.

## Release gates

Before packaging:

```text
python scripts/validate_package.py .
python scripts/deep_audit.py . --mode source
```

The release builder validates and audits the exact staged source tree. Runtime `.venv`, caches, operator state, Scripture payloads, nested archives, symlinks, and previous-RC named artefacts are excluded or rejected. The handover pack includes the test inventory/results and exact package/source hashes used for this RC7.04 development handoff.
