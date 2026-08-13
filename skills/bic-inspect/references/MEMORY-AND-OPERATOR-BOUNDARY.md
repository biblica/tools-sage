# Memory and Operator boundary

BIC INSPECT may submit proposed memory records and translation challenges. Proposed records remain `PROPOSED`; AI output cannot approve or overwrite memory.

The controller stores governed memory under `workspace-data/bic/memory/`. Only records in `APPROVED_FOR_USE` state may be routed into REWRITE or SELF-CHECK. A human memory-review receipt may record review provenance for the committed INSPECT scope, but its absence or decision does not block REWRITE or SELF-CHECK.

The controls remain distinct:

- `APPROVED_FOR_USE` authorises one memory record for analytical use.
- `APPROVED_FOR_REWRITE`, `RETURN_FOR_REVIEW`, or `REJECTED` may be recorded as review attention for one INSPECT operation and scope.
- Any review attention is reported with urgency and `next_stage_allowed: true`.

Do not invent decision IDs, reviewers, approvals, or project evidence. Exclude unapproved memory from the routed packet, log pending review as an attention item, and continue from the committed INSPECT evidence.
