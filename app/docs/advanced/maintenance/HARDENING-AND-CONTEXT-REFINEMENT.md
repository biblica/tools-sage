# SAGE v0.02alpha1 hardening and context refinement

Version: `0.02alpha1`

`0.02alpha1` includes the current hardening/refinement baseline. It preserves the established project-cardinality grammar, BIC/SAW authority boundaries, provider architecture, and byte-pinned protected BIC linguistic contracts while tightening bounded TARGET safety, routed-SFM review-item budgeting, canonical linguistic-profile handoff, OL micro-scoping, SAW discourse segmentation, history ordering, and release validation.

## Bounded TARGET safety

- Missing verses are inserted only inside the intended existing chapter and never after the next `\c` marker.
- Every bounded merge is reparsed before write. The exact candidate scope must be recoverable at the intended coordinates and out-of-scope rendered content must remain byte-identical.
- TARGET history refuses a non-empty commit whose recorded `after_scope` is empty.
- Revert verifies the exact restored historical scope before transaction commit.
- Commit ordering includes a nanosecond ordering value so same-second commits have a total order independent of transaction-ID text.

## Routed-SFM review-item budget

SAGE sizes one actual analytical review item at a time. The hard analytical budget is:

```text
exact SFM Scripture routed to the review item
= governed slicing input
```

Controller JSON, microtransactions, prompts, output schemas, linguistic profiles, IDs, hashes, diagnostics, and local USJ projections do not enter token estimation or Scripture hard-byte sizing. Their serialized size may be retained as transport telemetry. This prevents controller growth or prompt wording from changing Scripture work-unit boundaries.

Every routed natural-language stream carries its complete canonical profile independently of sizing. The profile is mandatory governed context but has zero sizing contribution.

## BIC OL micro-scope

Conditional BIC OL clarification remains controller-derived and material-risk gated. When opened, each material challenge is processed separately. Raw SOURCE and original-language Scripture are released to the provider for one single-verse micro-scope only. A `VERB_CHOICE` referral asks only for the disputed verb's verbal sense/function. Surrounding Scripture is not added automatically.

This transport refinement does not modify the protected rewrite-detail or protected verb-selection contracts.

## SAW Reference Text Comparison (RTC) discourse units

Reference Text Comparison (RTC) preserves deterministic discourse units while balancing the WIP stream around a 6,000-token soft target. Clean WIP boundaries are preferred between 5,000 and 7,000; adjacent units are not greedily packed beyond the 7,000 preferred ceiling, and no WIP slice may be planned at 8,000 tokens or above. The complete required WIP+REFERENCE review item has its own routed-SFM hard guard; prompt/schema/controller overhead is not part of that guard. Focused review uses at most two intact units and standalone Original-Language Review one. OL clarification triggered by RTC is a separate finding-scoped package, not an expansion of the parent RTC slice.

- Prose: one body paragraph.
- Lists: `\lh` breaks list flow; each `\li1` starts a major unit; following subordinate `\li2+` paragraphs stay with that major unit; `\lf` breaks list flow.
- Poetry: an operational stanza is the maximal uninterrupted run of poetry-line paragraphs (`\q`/`\q#`, `\qm`/`\qm#`, `\qr`, `\qc`, `\qd`). Changes of indentation do not split the stanza and `\v` never splits it.
- Poetry breakers include `\b`, `\qa`, `\s*`, `\ms*`, Psalm chapter/associated `\cl`, `\d`, and transition to non-poetry.

This is an operational segmentation rule for model context, not a claim that every generated unit is a literary stanza. Partitioned tasks receive explicitly labeled adjacent context-only WIP and REFERENCE evidence, excluded from primary coverage and ordinary findings.

## Release gate

`system/tools/hardening.py` discovers every `system/tests/test_*.py` module and deterministically schedules each discovered module exactly once. Within that isolated module workspace it collects exact pytest node IDs and splits long modules into bounded groups of at most eight test nodes per pytest process; short modules remain single-process. Timed-out subprocess trees are explicitly terminated and never counted as passes. The hardening report records the exact governed source-tree SHA-256.

A production `build_release.py` invocation requires a complete hardening PASS whose source hash matches the exact staged tree before packaging. Test/internal recursion controls cannot enable a provider or alter runtime authority.
