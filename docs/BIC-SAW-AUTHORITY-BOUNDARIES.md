# BIC and SAW authority boundaries — RC7.04

This is the current authority boundary for the two executable workflows. BIC and SAW are independent; neither creates, converts or hands work directly to the other.

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
- DONOR verse wording, order, syntax, propositions, participants, and discourse are not translation authority; only decontextualised lexical inventory is routed.
- Existing TARGET Scripture is never evidence for INSPECT or REWRITE.
- INSPECT -> REWRITE -> SELF-CHECK uses one immutable evidence cohort.
- If REWRITE uses conditional OL evidence, SELF-CHECK receives that exact inherited evidence; otherwise SELF-CHECK receives no OL.
- Protected rewrite-detail and verb-selection contracts are unchanged.

## SAW

```text
WIP + REFERENCE (+ configured applicable GRK/HEB when routed) -> findings
```

| Role | Identifier | Authority |
|---|---|---|
| WIP | `WIP` | Translation under analysis; never its own benchmark |
| REFERENCE | `REFERENCE` | Authorised LWC comparison benchmark |
| OL | `ORIGINAL_LANGUAGE_GREEK` / `ORIGINAL_LANGUAGE_HEBREW` | Original-language authority when routed |

Invariants:

- WIP lifecycle state is `UNDER_REVIEW`.
- SAW Scripture inputs are WIP, REFERENCE, and only the configured applicable OL resource when OL is routed.
- Normal QA is composite: deterministic preflight/structural triage -> conditional structural adjudication -> required translation/meaning QA -> conditional selective OL adjudication -> deterministic finalisation. Focused Check and OL Review remain separate bounded operations.
- SAW has no external Scripture write capability and never creates/modifies Paratext Notes XML; final note material is plain text for Operator copy/paste.
- Local indexes/semantic signals are triage evidence, not autonomous findings or translation authority.

## No interface between workflows

There is no BIC TARGET -> SAW WIP handoff, automatic generation handoff, automatic role conversion, shared lifecycle, or dependency. An Operator may later configure any suitable Paratext/PTLite project independently for SAW; SAGE treats that as a separate SAW project configuration.
