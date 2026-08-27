# Local Evidence and General Linguistic Competence

This contract defines the evidence boundary for every governed SAGE model task.

## Canonical rule

**Local Evidence, General Linguistic Competence.**

All content-bearing evidence used to determine, analyze, interpret, compare, validate, or generate content must originate from governed SAGE-local resources authorized for the owning Job and routed in the sealed task.

The language model may contribute only general orthographic, morphological, grammatical, and syntactic competence from its training. Model pretraining, recall, memory, or unstated world knowledge is never authorized content evidence.

> Linguistic competence may determine how locally supported content is expressed; it may not determine what the content is.

## Canonical prompt form

```text
CONTENT EVIDENCE: SAGE-LOCAL ONLY.
Use only the evidence routed in this Job.
Do not use pretrained knowledge, model memory, external Scripture,
translations, lexicons, commentary, web sources, or unstated facts
as content evidence.
You may use general orthographic, morphological, grammatical, and
syntactic competence only to understand and express the supplied evidence.
It must not introduce unsupported content.
```

## Read classes

Every file exposed to a model task has one explicit `evidence_class`. Unclassified reads fail closed.

| Class | Permitted use |
|---|---|
| `AUTHORIZED_CONTENT_EVIDENCE` | Content judgments only within the exact Job role and bounded scope. |
| `AUTHORIZED_LEXICAL_EVIDENCE` | Lexical choice only; never verse wording, syntax, propositions, participant structure, sequence, or discourse. |
| `PROJECT_INDEX_EVIDENCE` | Retrieval, classification, lexical triage, or occurrence evidence according to provenance; never independent Scripture or translation authority. |
| `DERIVED_EVIDENCE` | Only claims inherited from verified authorized local provenance; never a new authority class. |
| `STRUCTURAL_EVIDENCE` | Versification, coverage, coordinate, segmentation, and routing judgments only. |
| `SUBJECT_TEXT` | Text being analyzed or generated; not independent authority for what its content should be. |
| `LINGUISTIC_COMPETENCE_RULES` | Governed orthographic, morphological, grammatical, and syntactic constraints; never independent content or lexical meaning. |
| `PROCESS_CONTROL` | Execution, schema, Skill, validation, and workflow control only; not content evidence. |

## BIC authority

- `SOURCE` / `CONTENT_SOURCE`: sole BIC content and translation authority.
- `DONOR` / `LEXICAL_DONOR`: lexical evidence only.
- `TARGET` / `GENERATED_TARGET`: subject/output destination only. Existing TARGET Scripture is not evidence during INSPECT or REWRITE.
- Original-language content may be used only when the governed task explicitly routes the configured local OL resource under the bounded OL policy.
- BIC memory may become content-bearing derived evidence only when it originates in same-Job INSPECT, retains verified SOURCE-resource fingerprints, and is explicitly approved for use.
- Generic lexicon imports are reviewable governance records only and cannot be promoted into BIC content evidence.

## SAW authority

- `WIP`: subject under analysis, never its own comparison authority.
- `REFERENCE`: configured LWC Reference Project comparison. In an explicitly OL-routed bounded source-text question, the configured routed GRK/HEB packet is primary textual authority for that question; REFERENCE does not override contrary OL evidence.
- Original-language content is conditional bounded evidence only when the configured local GRK/HEB resource is explicitly routed.
- RTC predecessor material must preserve same-Job, same-Run, WIP, and REFERENCE lineage.

## Project indexes

RWC, semantic-domain, FLEx/Combine, frequency, occurrence, and similar index material may be used only after it has been explicitly imported or merged into governed SAGE-local project resources and selected for the relevant project namespace. Locality alone does not establish authority.

Project indexes are classified `PROJECT_INDEX_EVIDENCE`. Their provenance controls what they may support. They never become independent Scripture, translation, commentary, or theological authority.

A specialized external biblical workbook or other external canonical-Scripture-derived semantic source must not be consulted by a Job simply because an importer exists. The runtime does not provide an external Greek biblical-term workbook import path.

## Derived packs

A generated packet, approved-memory view, challenge ledger, semantic signal file, preflight packet, predecessor packet, or other derived artifact inherits the authority and restrictions of its verified local provenance. Derivation never upgrades authority.

## Forbidden external content evidence

The following are never authorized as content evidence unless the content is itself present in a governed routed SAGE-local resource with the correct role and provenance:

- model recall or pretrained Scripture knowledge;
- unrouted canonical Scripture or translations;
- unrouted lexicons, corpora, semantic databases, commentaries, theological material, or study resources;
- historical or cultural facts recalled by the model;
- web search, external APIs, provider workspace browsing, plugins, or external file tools;
- familiar wording, remembered interpretations, or unstated facts.

## Fail-closed behavior

- Model reads are exact-path, exact-hash, SAGE-root-bounded, and explicitly classified.
- The task embeds the canonical evidence policy; submission and model execution reject a missing or altered policy.
- Conditional OL reads remain sealed until the governed material-risk trigger opens the exact micro-scope.
- Any conflict between content evidence and general model knowledge is resolved in favor of routed local evidence; unsupported model knowledge is discarded.
