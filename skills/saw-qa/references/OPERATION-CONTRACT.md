# Normal QA composite operation contract

The public operation is `SAW QA`, but SAGE routes one isolated model stage at a time after deterministic preflight. `ACT.md` and `task-manifest.json` state the current `qa_stage` and exact evidence boundary.

- Structural adjudication is conditional and receives only unresolved structural candidates; it has no OL Scripture.
- Translation/meaning QA is required and reviews the complete bounded WIP against the authorised REFERENCE. It has no OL Scripture and may emit bounded `ol_review_requests` only for questions that truly require original-language adjudication. Every request reserves one `deferred_finding_id`, and that deferred issue must not also be emitted as a final meaning-stage finding.
- Selective OL adjudication is conditional and receives only the exact inherited request objects, exact request-coordinate stage inventory, and appropriate bounded GRK/HEB evidence. It returns exactly one structured `ol_resolutions` object per inherited request.

Each stage must provide exact stage-coordinate coverage and review receipts for its declared checks. Submit only with the command printed in `ACT.md`. SAGE owns stage progression, merging, deduplication, coverage reconciliation, final validation, and rendering of the final action report and plain-text Operator note material.
