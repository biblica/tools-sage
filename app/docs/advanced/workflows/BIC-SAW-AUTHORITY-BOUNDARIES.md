# BIC and SAW authority boundaries — v0.02alpha1

This is the current authority boundary for the two executable workflows. BIC and SAW are independent; neither creates, converts or hands work directly to the other.

## Local evidence boundary

Both workflows enforce **Local Evidence, General Linguistic Competence**. Content-bearing evidence must be SAGE-local, governed by the owning Job, routed in the sealed task, and used only according to its `evidence_class`. Model pretraining, recall, external Scripture/translations/lexicons/commentary, web sources, and unstated facts are not content evidence. General orthographic, morphological, grammatical, and syntactic competence may help interpret or express routed evidence; it may not add unsupported content.

Derived packs inherit the authority and restrictions of their verified provenance. Project indexes are `PROJECT_INDEX_EVIDENCE`, never independent Scripture or translation authority.


## BIC

```text
SOURCE + DONOR -> TARGET
```

| Role | Identifier | Authority |
|---|---|---|
| SOURCE | `CONTENT_SOURCE` | Sole BIC content and translation authority |
| DONOR | `LEXICAL_DONOR` | TARGET-language vocabulary/lexical evidence only |
| TARGET | `GENERATED_TARGET` | Destination only; optionally writable as external `.SFM` |

Invariants:

- Each BIC Job has one bound SOURCE resource, one bound DONOR resource, and one bound TARGET resource. The three are distinct and all three participate in BIC Job identity.
- The bound TARGET may use internal SAGE storage or one mapped Paratext/PTLite project folder; those are storage bindings for the same TARGET, never multiple targets.
- DONOR language must equal TARGET language.
- DONOR verse wording, order, syntax, propositions, participants, and discourse are not translation authority; only decontextualized lexical inventory is routed.
- Existing TARGET Scripture is never evidence for INSPECT or REWRITE.
- INSPECT -> REWRITE -> SELF-CHECK uses one immutable evidence cohort.
- If REWRITE uses conditional OL evidence, SELF-CHECK receives that exact inherited evidence; otherwise SELF-CHECK receives no OL.
- Protected rewrite-detail and verb-selection contracts are unchanged.

## SAW

```text
RTC/Targeted: WIP + REFERENCE -> findings\nSTC: WIP + PRIMARY GRK/HEB -> findings\nOL Review: bounded WIP + REFERENCE + applicable GRK/HEB -> findings
```

| Role | Identifier | Authority |
|---|---|---|
| WIP | `WIP` | Translation under analysis; never its own comparison authority |
| REFERENCE | `REFERENCE` | Authorized LWC Reference Project comparison |
| OL | `ORIGINAL_LANGUAGE_GREEK` / `ORIGINAL_LANGUAGE_HEBREW` | Original-language authority when routed |

Invariants:

- WIP lifecycle state is `UNDER_REVIEW`.
- SAW Scripture inputs are route-specific: RTC/Targeted use WIP+REFERENCE; STC uses WIP+testament-correct PRIMARY OL without REFERENCE; Original-Language Review uses its explicitly declared bounded WIP/REFERENCE/OL evidence.
- Reference Text Comparison (RTC) is composite: deterministic preflight/structural triage -> conditional structural adjudication -> required Reference Text Comparison (RTC) -> conditional selective OL adjudication -> deterministic finalization. STC is an independent WIP-to-primary-OL operation; Targeted Check and Original-Language Review remain separate bounded operations.
- SAW has no external Scripture write capability and never creates/modifies Paratext Notes XML; final note material is plain text for Operator copy/paste.
- Local indexes/semantic signals are `PROJECT_INDEX_EVIDENCE`: governed retrieval/triage evidence only, not autonomous findings, Scripture authority, or translation authority. RTC predecessor evidence must retain same-Job, same-Run, WIP, and REFERENCE lineage.

## No interface between workflows

There is no BIC TARGET -> SAW WIP handoff, automatic generation handoff, automatic role conversion, shared lifecycle, or dependency. An Operator may later configure any suitable Paratext/PTLite project independently for SAW; SAGE treats that as a separate SAW project configuration.


## Alpha bounded SAW OL authority

When original-language Scripture is explicitly routed to a bounded SAW task, the configured GRK/HEB resource is the primary textual authority for questions of source-text meaning within that task and scope. REFERENCE remains the authorized LWC Reference Project comparison, but it does not override contrary original-language evidence. Outside an OL-routed task, OL Scripture has no implicit authority and must not be read.
