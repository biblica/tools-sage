# Standard QA composite operation contract

The public operation is `SAW QA`, but SAGE routes one isolated model stage at a time after deterministic preflight. `ACT.md` and `task-manifest.json` state the current `qa_stage` and exact evidence boundary.

- Structural adjudication is conditional and receives only unresolved structural candidates; it has no OL Scripture.
- Translation/meaning QA is required and reviews the complete bounded WIP against the configured Reference Project. It has no OL Scripture. When the sealed Standard-QA `source_text_drift_adjudication` policy is `ENABLED`, it defers every material content-bearing WIP–Reference variance whose correctness depends on the source text. Grammar, readability, punctuation, spelling, USFM/structure, style, and ordinary consistency remain direct QA findings. Every request reserves one `deferred_finding_id`, and that deferred issue must not also be emitted as a final meaning-stage finding.
- Selective OL adjudication is conditional and automatically receives only those exact inherited variance requests, the exact request-coordinate stage inventory, and the testament-correct Job-bound source (OT Hebrew, NT Greek). It returns one structured resolution and comparison decision per request. SAGE deterministically injects evidence IDs and materializes any resulting QA finding. This is not the separate, explicit-focus, detailed Original-Language Review operation.

Each stage must semantically review every assigned primary coordinate and return a concise `review_summary`. SAGE owns task identity, check inventories, exact coverage, review receipts, stage progression, merging, deduplication, final validation, and rendering of the final action report and plain-text Operator note material.
