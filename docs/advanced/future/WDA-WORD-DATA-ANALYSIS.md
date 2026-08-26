# WDA — Word Data Analysis (future work)

Status: **PARKED / NOT IMPLEMENTED**.

WDA is a proposed third SAGE tool for lexical and semantic-data analysis. It is deliberately separate from SAW.

## Proposed purpose

WDA would analyze word/sense relationships across RWC, FLEx, Combine, dictionaries, Scripture lexical evidence, semantic domains, key terms, and language/project clusters.

Typical future questions include lexical coverage gaps, semantic dispersion, cross-project sense differences, possible interference/borrowing, RWC/FLEx/Scripture disagreement, and cluster outliers.

## Authority invariant

WDA outputs would be evidence and hypotheses only. A WDA result would not by itself be:

- a BIC translation decision;
- a SAW finding;
- approved terminology;
- an approved FLEx sense; or
- translation authority.

## Architectural direction

A future WDA data layer may become the conceptual owner of shared lexical/semantic indexes. BIC and SAW would consume controlled projections appropriate to their own authority models. This direction is not implemented in the current Beta and must not be simulated by expanding SAW.

Most WDA computation should remain local/deterministic; AI would be reserved for bounded linguistic interpretation of ambiguous patterns.
