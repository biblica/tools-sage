# Release gates

A package may include handover data only after all applicable gates pass.

## Clean build

- every discovered `system/tests/test_*.py` module is scheduled by hardening and the complete automated suite passes in a fresh isolated source copy;
- state is reset before and after formal tests;
- pytest cache generation is disabled and residual ephemeral state does not alter package validation;
- source package validation passes before and after testing;
- source deep audit passes with no errors or warnings before and after testing;
- no operator/Job/Project Scripture payloads, nested archives, runtime data, cache, bytecode, editor files, or platform artifacts are present; only the governed bundled `@GRK`/`@HEB` `.SFM` resources are permitted;
- ZIP integrity and SHA-256 verification pass;
- deterministic rebuild produces the same SHA-256;
- production packaging has a hardening PASS receipt whose governed source-tree SHA-256 exactly matches the staged tree.

## With-all-resources handover

- workspace static validation passes;
- workspace deep audit passes;
- INIT and initialization reports are generated where required;
- required SAGE Projects and governed resource sources are included;
- every file is represented in the handover manifest;
- included ZIPs pass integrity and artifact scans;
- resource restrictions are reported without being reclassified as successes;
- executable permissions for POSIX launchers are preserved in the archive.

## Analytical governance

- all seven registered analytical Skill files have valid frontmatter and internally consistent identifiers; deterministic controller functions such as consolidation are not registered as AI Skills;
- all seven registered Skill bindings and their original/adapted hashes verify;
- routed Skill references contain only current paths, commands, filenames, and workflow claims;
- ACT mutation, traversal, output grammar, bounded scope, scope-aware readiness, review evidence, and resubmission regressions pass;
- BIC and SAW process-flow tests pass;
- only the SFM Scripture streams routed to that review item contribute to governed token/hard-byte sizing; prompt, schema, profile, controller, provenance, diagnostic, and transport material cannot alter slicing or hard-budget decisions;
- command, help, cheat-sheet, and documentation consistency tests pass;
- local documentation links resolve.

## Interface localization

- changed canonical `en-US` menu text is rebuilt into
  `system/config/localization/menu-localization.json` before the source freeze;
- stable semantic keys are retained only when meaning is unchanged; a meaning change receives an
  appropriate new or deliberately revised semantic entry;
- every current static and governed dynamic menu phrase appears exactly once;
- every entry has a reviewed nonblank rendering for `en-US`, `en-GB`, `id`, `fr`, `ru`, and
  `pt-BR`; missing translations may not silently fall back to canonical English for release;
- `python -m pytest system/tests/test_menu_localization.py` passes against the frozen source.

Human platform acceptance, linguistic approval, corpus authority, and distribution rights remain separate approval gates.
