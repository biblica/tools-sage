# SAGE v0.01beta hardening and context refinement

Version: `0.01beta`

`0.01beta` includes the current hardening/refinement baseline. It preserves the established project-cardinality grammar, BIC/SAW authority boundaries, provider architecture, and byte-pinned protected BIC linguistic contracts while tightening bounded TARGET safety, provider handoff budgeting, OL micro-scoping, SAW discourse segmentation, history ordering, and release validation.

## Bounded TARGET safety

- Missing verses are inserted only inside the intended existing chapter and never after the next `\c` marker.
- Every bounded merge is reparsed before write. The exact candidate scope must be recoverable at the intended coordinates and out-of-scope rendered content must remain byte-identical.
- TARGET history refuses a non-empty commit whose recorded `after_scope` is empty.
- Revert verifies the exact restored historical scope before transaction commit.
- Commit ordering includes a nanosecond ordering value so same-second commits have a total order independent of transaction-ID text.

## Provider handoff budget

SAGE now measures and enforces the exact provider request immediately before every provider execution:

```text
provider prompt
+ output schema
= governed LLM handoff
```

The receipt records prompt bytes, schema bytes, total bytes, component token estimates, total estimated input tokens, estimator identity, and the applicable workflow hard limits. Conditional second/next passes are remeasured after Phase-1/previous outputs are embedded.

## BIC OL micro-scope

Conditional BIC OL clarification remains controller-derived and material-risk gated. When opened, each material challenge is processed separately. Raw SOURCE and original-language Scripture are released to the provider for one single-verse micro-scope only. A `VERB_CHOICE` referral asks only for the disputed verb's verbal sense/function. Surrounding Scripture is not added automatically.

This transport refinement does not modify the protected rewrite-detail or protected verb-selection contracts.

## SAW Reference Text Comparison (RTC) discourse units

Reference Text Comparison (RTC) preserves deterministic discourse units while balancing the original WIP packet around 6,000 estimated tokens. Clean boundaries are preferred between 5,000 and 7,000; adjacent units are not greedily packed beyond the 7,000 preferred ceiling, and no WIP packet may be planned at 8,000 tokens or above. Focused review uses at most two intact units and standalone Original-Language Review one. OL clarification triggered by RTC is a separate finding-scoped package, not an expansion of the parent RTC slice.

- Prose: one body paragraph.
- Lists: `\lh` breaks list flow; each `\li1` starts a major unit; following subordinate `\li2+` paragraphs stay with that major unit; `\lf` breaks list flow.
- Poetry: an operational stanza is the maximal uninterrupted run of poetry-line paragraphs (`\q`/`\q#`, `\qm`/`\qm#`, `\qr`, `\qc`, `\qd`). Changes of indentation do not split the stanza and `\v` never splits it.
- Poetry breakers include `\b`, `\qa`, `\s*`, `\ms*`, Psalm chapter/associated `\cl`, `\d`, and transition to non-poetry.

This is an operational segmentation rule for model context, not a claim that every generated unit is a literary stanza. Partitioned tasks receive explicitly labeled adjacent context-only WIP and REFERENCE evidence, excluded from primary coverage and ordinary findings.

## Release gate

`system/tools/hardening.py` discovers every `system/tests/test_*.py` module and automatically schedules any module not present in the curated batches. Timed-out subprocess trees are explicitly terminated. The hardening report records the exact governed source-tree SHA-256.

A production `build_release.py` invocation requires a complete hardening PASS whose source hash matches the exact staged tree before packaging. Test/internal recursion controls cannot enable a provider or alter runtime authority.
