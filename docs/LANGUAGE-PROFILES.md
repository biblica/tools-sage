# Language profiles and project grammar

Language namespaces use canonical tags such as `en`, `id`, `uk`, `fa`, `grc`, and `hbo`. A project declares its namespace and optional role variant:

```yaml
language:
  code: uk
  profile: uk
  variant: wip
```

## Active variants

| Use | Profile |
|---|---|
| Indonesian BIC SOURCE | `profiles/languages/id/source.yml` |
| English BIC TARGET | `profiles/languages/en/bol-target.yml` |
| Ukrainian SAW WIP | `profiles/languages/uk/wip.yml` |
| Persian SAW WIP | `profiles/languages/fa/wip.yml` |

Greek and Hebrew are OL resources and do not currently use target-grammar variants.

## Status governance

- `ACTIVE`: accepted for governed use.
- `PROJECT_REVIEW_REQUIRED`: usable with review attention. A supplied `--grammar-override-id` must resolve to a genuine active exact-hash grammar-review receipt.
- `AI_DRAFTED`: accepted operational starting state whose provenance basis is an LLM's general knowledge of the target language. It is **not** Team/project approval and must not claim provenance to specific model-training sources.
- `INACTIVE`: unavailable for normal analytical use.

AI output cannot promote a profile to human approval or invent an approval/override receipt.

## Operation-specific routing

- BIC INSPECT receives SOURCE grammar.
- BIC REWRITE and SELF-CHECK receive SOURCE and TARGET grammar contracts.
- SAW Normal QA routes the WIP grammar contract to the internal stage that requires it; Focused and standalone OL Review receive the WIP contract for their bounded operation.

BIC REWRITE and SELF-CHECK grammar assessments bind every required rule to the exact candidate hash. SAW grammar findings cite routed rule IDs.
