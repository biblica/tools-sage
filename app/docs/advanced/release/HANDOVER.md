# SAGE v0.02alpha1 Handover

## Current continuation state

- Version: `0.02alpha1`
- Status: **Alpha; pre-release; not an RC and not FINAL.**
- Prior-release promotion-baseline qualification is historical reference evidence only.
- The version reset and subsequent governed edits invalidate earlier qualification receipts. Fresh exact-source qualification is required before the first real RC.
- Current implementation carries section-preferred SAW slicing that coalesces adjacent fitting sections, with bounded lookahead and balanced oversized-section partitioning; scope-projected predecessor/selective-OL evidence; chapter-first report compilation; actual WIP/Reference Project names in reports; three-column numeric menu alignment; non-generative Configure AI readiness, and explicit connection testing.
- Release feature classification: the Textual TUI is `EXPERIMENTAL_UNSTABLE`, displayed exactly as `EXPERIMENTAL / UNSTABLE`; it remains non-authoritative independently of the product's Alpha/Beta/RC phase.
- Current UI presentation contract: `docs/advanced/maintenance/UI-PRESENTATION.md`.
- ALPHA1 finalization includes the approved provider-neutral, per-Skill routing design in `docs/advanced/models-and-ai/SKILL-ROUTING-AND-MODEL-QUALIFICATION.md` and its test-first execution sequence in `docs/advanced/release/SKILL-ROUTING-IMPLEMENTATION-PLAN.md`; implementation, fresh route qualification, and Operator acceptance remain outstanding.
- Machine-local runtime state, caches, `localdata/.system/runtime/python`, `runtime/venv`, and `host-capability.json` must not ship in the vanilla Core distribution.


0.01beta remains the mainline baseline. 0.02alpha1 is developed on the parallel Alpha branch; all qualification and release artifacts described below are Alpha-branch evidence only.

## Qualification rule

Freeze one exact governed source hash and run all deterministic hardening shards from zero. Require every shard PASS and formal combine PASS with every discovered test module scheduled exactly once, identical source hashes, no governed-source mutation, schema validation PASS, package validation PASS, deep source audit PASS, and zero release-gate warnings/errors.

After formal hardening, build the full distribution, verify ZIP integrity/hash, extract cleanly, run startup smoke, verify BASIC/STANDARD/ADVANCED/failure-fallback host capability behavior, confirm runtime-local files are absent from the vanilla ZIP, and perform final version/name/content audits.

Any governed source or test change after qualification begins invalidates all receipts and requires a new exact source hash.

## Operator-testing focus

- Validate section-preferred SAW Reference Text Comparison (RTC) slicing on real books, especially adjacent short sections and oversized sections.
- Validate later RTC stages remain bounded to each child scope and do not inherit unrelated whole-book evidence.
- Validate chapter-scoped final reports contain only that chapter's findings/evidence and use actual configured Project names.
- Validate Configure AI entry readiness, toggle behavior without implicit rechecks, and explicit connection testing.
- After Skill routing implementation, validate provider-only normal Setup, the guarded global override, fail-closed per-Skill qualification, and exact route metadata in Job menus and Run reports.
- Validate that deterministic task phases remain Python-owned, local-model work remains non-authoritative and evidence-restricted, and deterministic handoff reduction never combines isolated OL or secondary-rendering items.
- Validate numeric menu alignment at one-, two-, and three-digit option numbers.
- Continue macOS/Windows first-run and clean-install testing.

## Release status

The clean `0.02alpha1` source/package gates are qualified for group testing when accompanied by the matching exact-source hardening and checksum receipts. Native Windows/macOS acceptance remains required before any production-release promotion.
