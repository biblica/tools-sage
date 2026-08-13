# Language profiles

Profiles are stored under canonical language tags and selected by each project. Role variants contain project-facing spelling, punctuation, syntax, grammar, discourse, and review guidance. Workflows derive the profile from the bound project; independent workflow grammar bindings are prohibited.

Current variants:

- `id/source.yml`
- `en/bol-target.yml`
- `uk/wip.yml`
- `fa/wip.yml`

Greek (`grc`) and Hebrew (`hbo`) are routed as original-language resources and do not currently require target-grammar variants.

## Status semantics

- `ACTIVE`: approved for governed use.
- `PROJECT_REVIEW_REQUIRED`: usable provisionally with attention reporting; `--grammar-override-id` is optional provenance.
- `AI_DRAFTED` is an accepted operational state with explicit AI provenance; it is not human approval. `INACTIVE` remains unavailable.

A grammar override records responsibility for using a provisional profile; it does not convert that profile to `ACTIVE` or imply linguistic approval.
