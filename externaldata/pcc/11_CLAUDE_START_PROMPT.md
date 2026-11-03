# 11 — Copy/paste prompt for Claude Code in VS Code

Open the actual SAGE repository in VS Code and place this handover folder somewhere Claude can read. Then use:

```text
You are implementing the SAGE Phrase Consistency Checker (PCC) — Stage 1.
Read all of this handover's README.md and CLAUDE.md, then the full docs/ series and contracts/. Treat these as requirements; example code paths and commands are only illustrative.

Nonnegotiable: local JSON/JSONL/Markdown/TXT only; no SQL, database, remote service or SQS; no OL dependency; no redistribution of restricted translation material. A recurring consistency obligation requires the same normalized controlling SOURCE wording AND the same contextual sense. Reverse TARGET findings are probable additions for review only. Linguistic variance uses approved rules and scoped contextual exceptions. No automatic model approval.

Before editing: inspect the actual SAGE repository and run its current tests. Produce PCC_REPO_FIT.md documenting actual integration points, existing commands, any contradictions, proposed file changes and milestone mapping. Show the M0 discovery results. Then implement milestones M1–M8 sequentially, respecting the existing SAGE architecture and checking tests at each milestone. Reuse current parsers, language profiles, translation brief contracts, semantic-review adapters and report conventions where present. Do not invent those interfaces.

Generate and execute unit, golden fixture, regression and performance tests. Verify that reference resources remain byte-identical, decisions are auditable and no unresolved occurrence is reported as consistent. At each milestone summarize changed files, tests actually run and remaining blockers. Never claim a test passes if it was not run. Record deviations and complete the acceptance checklist before declaring Stage 1 finished.
```

## If Claude encounters missing project assets
Do not fabricate actual REFERENCE corpora. Implement resource-loader and schema acceptance using the synthetic fixture, mark live index construction blocked on availability/licensing of authorized local data, and continue remaining reproducible components. Do not substitute internet texts or OL sources.
