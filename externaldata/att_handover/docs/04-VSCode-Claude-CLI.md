# VS Code + Claude CLI Development Notes

## Recommended workflow
1. Open the SAGE repository in VS Code.
2. Create a feature branch for ATT.
3. Copy this handover package into a temporary planning folder or keep it beside the repo.
4. Start Claude CLI from the repository root.
5. Provide `prompts/CLAUDE-CLI-HANDOVER.md` as the governing implementation brief.
6. Ask Claude to inspect the existing SAGE architecture before changing code.
7. Require it to reuse existing Translation Brief, input-folder, reporting, test and resource-loading conventions where present.
8. Implement in small commits with tests after each layer.

## Strong implementation constraints
- Do not introduce SQS runtime dependencies in Phase 1.
- Do not modify existing OL authority semantics.
- Do not route ATT findings into RTC/STC logic.
- Do not mutate shipped canonical indexes.
- Do not infer source authority outside the Translation Brief.
- Prefer existing SAGE conventions over new parallel infrastructure.

## Suggested implementation sequence
1. Config/Translation Brief schema integration.
2. Reference package loader and validator.
3. Static lexical/phrase index contracts.
4. Local `input/att/` reader and resolver.
5. TARGET dynamic indexing adapter.
6. Lexical recurrence analyzer.
7. Phrase recurrence analyzer.
8. Dual-reference correlation/reconciliation.
9. Report model and output.
10. Tests and fixtures.
11. Documentation.

## Stop conditions for Claude
Claude should stop and report rather than invent behavior if:
- existing SAGE source/reference semantics conflict with this handover;
- the repository already contains an ATT-like subsystem with incompatible contracts;
- license-sensitive text would need to be embedded in test fixtures;
- existing Translation Brief keys are named differently and migration would be breaking.

In those cases, preserve existing architecture and propose the smallest compatible adaptation.
