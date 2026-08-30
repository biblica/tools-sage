# Test and Validation Report - SAGE v0.01beta2

## Status

`0.01beta2` is a pre-release group-testing build. Qualification applies only to the exact governed source used by the production release builder. Any source or governed-test change invalidates previous hardening receipts.

## Current qualification model

The release process uses one frozen governed source hash and requires all of the following against that same source:

- schema validation PASS;
- package validation READY with zero warnings/errors;
- source deep audit PASS with zero warnings/errors;
- deterministic isolated hardening shards;
- formal combine proving every discovered test module was scheduled exactly once;
- zero failed/error test outcomes;
- governed source unchanged before/after every isolated test workspace;
- deterministic release staging and ZIP construction;
- archive integrity verification;
- a second independent build with byte-identical ZIP output;
- SHA-256 checksum and hardening sidecars;
- clean extraction followed by schema/package/deep-audit verification.

## Current automated evidence

Working-source validation on 2026-08-30 collected **884 outcomes**. The direct managed-runtime suite
recorded **882 passed**, **2 skipped**, and **0 failed/error outcomes** under
SAGE-managed CPython 3.12.14. The two skips are guarded optional Textual interaction cases;
non-Textual TUI service/state coverage remains active.

Schema validation covers **42 schemas / 42 IDs / 42 owner mappings** and reports PASS with no
warnings/errors. Package validation reports READY with no warnings/errors. Source deep audit covers
620 governed files and **3,042 / 3,042 documented Python procedures** and reports PASS with no
warnings/errors. Sealed model-evaluation regeneration verifies **7 Skills / 23 cases / 93 files**.

This is development evidence, not a production-release claim. Formal exact-source hardening receipts
remain machine-local evidence and must be regenerated after any governed-source change. Deterministic
release construction, two byte-identical builds, clean extraction, and native host acceptance remain
separate gates before the first RC.

## Skill-routing implementation evidence

The Beta 2 source now includes provider-neutral exact-Skill resolution, provider-only settings
migration, an audited exact-route override, sealed synthetic qualification cases, schema 2.0 execution
receipts, receipt-bound report provenance, provider-native automatic qualification progression, and
provider-only UI/CLI controls. Focused deterministic
tests have exercised resolver and policy contracts, settings/override state, evaluation reconciliation,
runtime pre-handoff rejection, per-item secondary rendering, BIC/SAW report propagation, localization,
and menu/command surfaces using fake provider responses only.

No unit, schema, package, or hardening command is permitted to run a live provider qualification.
Controlled live qualification for current Codex catalog routes remains a separate Beta handoff gate.
Accepted receipts must be reviewed and promoted to the Core seed registry before an executable route
is claimed for every Skill. Any later model/capability/Skill/suite/policy change invalidates that exact
evidence.

## Deterministic distribution evidence

The production release builder stages only governed Core material, validates the supplied formal hardening receipt against the staged source hash, reruns source deep audit, emits deterministic ZIP member ordering/timestamps/permissions, and tests archive integrity before publication.

Qualification additionally builds the same release twice in independent output locations and requires byte-for-byte equality. The chosen release artifact is then extracted into a clean directory and revalidated. The extracted Core must:

- reproduce the frozen governed source hash;
- pass schema validation;
- report package status READY;
- pass source deep audit;
- contain no `localdata`, `workspace_data`, top-level `jobs`, top-level `reports`, or `.venv` root;
- contain no nested archives or bytecode/cache artifacts from the release staging process.

The release ZIP checksum and formal hardening summary are emitted beside the artifact as `.sha256` and `.hardening.json` files.

## Cross-platform qualification boundary

Automated source tests exercise Windows, macOS, Linux, POSIX permissions, path-with-spaces handling, Unicode/custom data homes, launcher quoting, Windows CMD behavior, process-tree cleanup, deterministic bootstrap, clone/install, storage containment, and package construction.

GitHub CI is configured for `ubuntu-latest`, `windows-latest`, and `macos-latest` with Python 3.10 and 3.12. CI installs pinned qualification dependencies, validates schemas/package boundaries, runs the complete test inventory, runs the source deep audit, and verifies the Git checkout remains unchanged.

No current exact-source production artifact is claimed by this report. Native group acceptance on
Windows, macOS Intel, and Linux release hosts remains a Beta deployment requirement before
production-release claims are made.

## Runtime/bootstrap boundary

The source ZIP contains neither Python nor a virtual environment. First launch resolves `localdata` (default `<bundle>/localdata`, beside `app/`), accepts a validated approved host CPython 3.12 when available, or installs the exact OS/CPU CPython archive after SHA-256 verification. Every provider creates/repairs `localdata/.system/runtime/venv` from exact version-controlled dependency manifests. A fresh runtime/dependency installation requires the applicable Python.org, Homebrew, WinGet, GitHub, and Python-package access or equivalent approved sources. The macOS ARM64 paths have been exercised natively; Windows, macOS Intel, and Linux paths remain native release-host acceptance gates.

Core updates do not delete operator Projects, Jobs, reports, resources, plugins, local settings, or other localdata. The explicit out-of-box reset is the only intentionally destructive local-reset surface and remains bounded to localdata.

## Release-gate commands

Representative commands for the current qualification flow are:

```text
./sage-python system/tools/validate_schemas.py
./sage-python system/tools/validate_package.py
./sage-python system/tools/deep_audit.py . --mode source
./sage-python system/tools/hardening.py --shard-count 4 --shard-index 0 --output <receipt-0>
./sage-python system/tools/hardening.py --shard-count 4 --shard-index 1 --output <receipt-1>
./sage-python system/tools/hardening.py --shard-count 4 --shard-index 2 --output <receipt-2>
./sage-python system/tools/hardening.py --shard-count 4 --shard-index 3 --output <receipt-3>
./sage-python system/tools/hardening.py --combine <receipt-0> <receipt-1> <receipt-2> <receipt-3> --expected-source-sha256 <frozen-sha256> --output <combine-receipt>
./sage-python system/tools/build_release.py --root . --hardening-receipt <combine-receipt> --output SAGE-v0.01beta2-Full-Distribution.zip
```

The hardening receipt, checksum, and extracted-artifact verification are release evidence; historical or differently hashed receipts do not qualify the current source.
