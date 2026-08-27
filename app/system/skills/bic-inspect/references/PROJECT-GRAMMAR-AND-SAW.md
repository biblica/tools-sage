# Project grammar and SAW

Project grammar is selected from the language profile bound to each resource in the governed Job. SAGE validates the complete profile, compiles a content-addressed grammar contract, and routes only the contracts required by the current model stage:

- BIC INSPECT: SOURCE-language contract only;
- BIC REWRITE and SELF-CHECK: SOURCE- and TARGET-language contracts;
- SAW structural adjudication: WIP contract when applicable;
- SAW translation/meaning QA and Targeted Check: WIP contract;
- SAW selective or standalone original-language review: WIP contract plus only the bounded OL evidence explicitly routed for that stage.

`ACTIVE`, `PROJECT_REVIEW_REQUIRED`, and `AI_DRAFTED` are accepted operational states. `AI_DRAFTED` identifies a profile based on an LLM's general knowledge of the target language and does not imply Team/project approval or known provenance to specific model-training sources. `PROJECT_REVIEW_REQUIRED` remains usable with review attention unless an exact governed review decision changes its effective status. `INACTIVE`, corrupt, role-incompatible, or structurally incomplete profiles are execution defects.

A supplied `--grammar-override-id` must resolve to a real active exact-hash grammar-review receipt for a grammar contract routed to the task. Grammar findings must cite applicable rule IDs. Analytical tasks must never alter language-profile YAML, `project_decisions`, or `approved_exceptions`.
