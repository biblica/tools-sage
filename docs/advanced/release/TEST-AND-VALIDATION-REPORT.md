# Test and Validation Report - SAGE v0.01beta

## Status

`0.01beta` is a pre-release group-testing build. Qualification applies only to the exact governed source used by the production release builder. Any source or governed-test change invalidates previous hardening receipts.

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

The current Beta qualification run collected **691 tests across 62 test modules**. Formal hardening recorded **689 passed**, **2 skipped**, and **0 failed/error outcomes**. The two skips are guarded optional Textual interaction cases; non-Textual TUI service/state coverage remains active.

Hardening was executed as four deterministic shards. The formal combine verified:

- 4/4 shard receipts PASS;
- 62 discovered test modules;
- 62 scheduled test modules;
- every test module scheduled exactly once;
- 691 collected test cases fully accounted for by passed/skipped outcomes;
- source hash identical across every shard and unchanged after testing;
- post-shard schema validation PASS;
- post-shard package validation PASS;
- post-shard source deep audit PASS;
- zero combine warnings/errors.

Schema validation covers **35 schemas / 35 IDs / 35 owner mappings**. Package validation reports **READY** with no warnings/errors. Source deep audit reports **PASS** with no warnings/errors.

## Deterministic distribution evidence

The production release builder stages only governed Core material, validates the supplied formal hardening receipt against the staged source hash, reruns source deep audit, emits deterministic ZIP member ordering/timestamps/permissions, and tests archive integrity before publication.

Qualification additionally builds the same release twice in independent output locations and requires byte-for-byte equality. The chosen release artifact is then extracted into a clean directory and revalidated. The extracted Core must:

- reproduce the frozen governed source hash;
- pass schema validation;
- report package status READY;
- pass source deep audit;
- contain no `SAGEdata`, `workspace_data`, top-level `jobs`, top-level `reports`, or `.venv` root;
- contain no nested archives or bytecode/cache artifacts from the release staging process.

The release ZIP checksum and formal hardening summary are emitted beside the artifact as `.sha256` and `.hardening.json` files.

## Cross-platform qualification boundary

Automated source tests exercise Windows, macOS, Linux, POSIX permissions, path-with-spaces handling, Unicode/custom data homes, launcher quoting, Windows CMD behavior, process-tree cleanup, deterministic bootstrap, clone/install, storage containment, and package construction.

GitHub CI is configured for `ubuntu-latest`, `windows-latest`, and `macos-latest` with Python 3.10 and 3.12. CI installs pinned qualification dependencies, validates schemas/package boundaries, runs the complete test inventory, runs the source deep audit, and verifies the Git checkout remains unchanged.

The local production artifact described by this report is built and qualified on a Linux host. Native group acceptance on real Windows and macOS hosts remains a Beta deployment requirement before production-release claims are made.

## Runtime/bootstrap boundary

The source ZIP does not contain a virtual environment. First launch resolves `SAGEdata` (default sibling of Core), creates the canonical data structure, and creates/repairs `SAGEdata/.system/runtime/venv` from exact version-controlled dependency manifests. A fresh dependency installation requires package access or an equivalent approved package source.

Core updates do not delete operator Projects, Jobs, reports, resources, plugins, local settings, or other SAGEdata. The explicit out-of-box reset is the only intentionally destructive local-reset surface and remains bounded to SAGEdata.

## Release-gate commands

Representative commands for the current qualification flow are:

```text
python system/tools/validate_schemas.py
python system/tools/validate_package.py
python system/tools/deep_audit.py . --mode source
python system/tools/hardening.py --shard-count 4 --shard-index 0 --output <receipt-0>
python system/tools/hardening.py --shard-count 4 --shard-index 1 --output <receipt-1>
python system/tools/hardening.py --shard-count 4 --shard-index 2 --output <receipt-2>
python system/tools/hardening.py --shard-count 4 --shard-index 3 --output <receipt-3>
python system/tools/hardening.py --combine <receipt-0> <receipt-1> <receipt-2> <receipt-3> --expected-source-sha256 <frozen-sha256> --output <combine-receipt>
python system/tools/build_release.py --root . --hardening-receipt <combine-receipt> --output SAGE-v0.01beta-Full-Distribution.zip
```

The hardening receipt, checksum, and extracted-artifact verification are release evidence; historical or differently hashed receipts do not qualify the current source.
