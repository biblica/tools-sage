# BIC, RTC, and STC authority boundaries — v0.01beta2

BIC, RTC, and STC are independent canonical workflows. None creates, converts, or hands work directly to another.

## Local evidence boundary

All three workflows enforce **Local Evidence, General Linguistic Competence**. Content evidence must be SAGE-local, owned by the Job, routed in the sealed task, and used only according to its `evidence_class`. Model recall, external Scripture/translations/lexicons/commentary, web sources, and unstated facts are not content evidence.

## BIC

```text
SOURCE + DONOR -> TARGET
```

- `CONTENT_SOURCE` is the sole content and translation authority.
- `LEXICAL_DONOR` supplies TARGET-language lexical evidence only.
- `GENERATED_TARGET` is the destination and is the only role that may receive governed external `.SFM` writes.
- INSPECT, REWRITE, and SELF-CHECK use one immutable evidence cohort.

## RTC

```text
WIP + REFERENCE -> findings
```

- `WIP` is the immutable translation under comparison.
- `REFERENCE` is the immutable authorized LWC Reference Project comparison.
- Ordinary RTC stages do not route original-language Scripture. A separately admitted selective stage may route the testament-appropriate primary GRK/HEB authority for one bounded source conflict.
- RTC reports structural and versification differences and never blocks solely because Project versifications differ.
- RTC cannot write Scripture or Paratext Notes XML.

## STC

```text
WIP + PRIMARY GRK/HEB -> findings
```

- `WIP` is the immutable translation under review.
- NT Books use PRIMARY `ORIGINAL_LANGUAGE_GREEK`; OT Books use PRIMARY `ORIGINAL_LANGUAGE_HEBREW`.
- STC never reads, requires, fingerprints, or uses a Reference Project or RTC findings.
- STC cannot write Scripture or Paratext Notes XML.

## No workflow handoff

There is no BIC TARGET -> RTC/STC WIP handoff, automatic generation handoff, role conversion, shared lifecycle, or dependency. An Operator may independently bind the same suitable SAGE Project to a later Job; that creates no authority link between the Jobs.

## Legacy compatibility

The retired shared-analysis identifier remains readable only for sealed historical Jobs, Runs, tasks, reports, and qualification receipts. New artifacts use BIC, RTC, or STC identity exclusively.
