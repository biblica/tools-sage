# Structure and work-unit planning

SAGE planning is deterministic preprocessing; it is not analytical completion.

```bash
./system/bin/sage workflow plan --workflow bic --operation inspect \
  --scope "PHP 1-4" --write-packets
```

The planner compiles strict USFM/USJ records, applies the governed structure policy, measures the serialized evidence packet, and divides the requested scope at preferred boundaries while preserving exact primary-coordinate coverage.

Planning first identifies intact spans at governed section markers. It then coalesces adjacent spans while the complete measured packet remains within every hard token, byte, verse, chapter, and discourse limit. If the scope must be divided, section markers are preferred split points. Only an individually oversized section is subdivided at a balanced natural discourse/paragraph boundary. This keeps a short book such as Jude in one work unit when it fits instead of turning each heading into a separate model task.

## Boundary preference

- major and ordinary section headings are strong candidates;
- Psalm `\cl`, `\qa`, and governed poetry breaks have book-specific weights;
- paragraph boundaries are preferred before arbitrary verse boundaries;
- chapter boundaries are weak fallbacks;
- `\m` continues a preceding body block but can begin a new block after a header or poetry break;
- `\s3` remains structural context but is not a split candidate;
- verse bridges are atomic and may not be cut.

## Evidence rules

Each requested coordinate occurs in exactly one primary unit. Adjacent context may be supplied for interpretation but is marked context-only and is not an ordinary finding location. Plan identity includes resources, VRS, structure policy, grammar contracts, compiler version, operation, and scope.

At SAW execution time, SAGE expands approved ranged labels and current WIP records to the same atomic
coordinate inventory before comparing them. An indivisible verse bridge remains one work-unit record,
but its covered coordinates reconcile exactly without requiring the Operator to rebuild an unchanged
approved plan.

Plans and packets remain inside the owning workflow output root and outside immutable publication folders.

## Normal SAW discourse units

The deterministic discourse layer sits inside a section-preferred planner. Normal SAW `TRANSLATION_AND_MEANING_QA` keeps complete `\s*`/`\ms*` sections intact, but coalesces adjacent sections whenever their combined measured packet fits. Section headings become split points only when a split is actually required. Four discourse units is a soft packing preference, not a hard ceiling. If an individual section is oversized, SAGE looks through its remainder and chooses balanced structural subdivisions rather than greedily filling one packet and leaving a tiny tail. Focused SAW review remains capped at two intact units and standalone OL Review at one; BIC INSPECT is capped at four. Hard projected-handoff token/byte/verse limits still apply, and a protected discourse unit is not split unless the unit itself cannot fit a hard limit.

- **Prose:** each ordinary body paragraph is one discourse unit.
- **Lists:** `\lh` breaks/heads list flow; each `\li1` starts a major unit; following subordinate `\li2+` paragraphs remain in that `\li1` unit; the next `\li1` starts another unit; `\lf` breaks/ends list flow.
- **Poetry:** one operational stanza is the maximal uninterrupted run of poetry-line paragraphs matched by the governed `poetry_lines` patterns (`q/q#`, `qm/qm#`, `qr`, `qc`, `qd`). Changing indentation/poetry-line marker does not split the unit. `\v` is a coordinate marker and never splits it.
- **Poetry breakers:** `\b`, `\qa`, section/major-section boundaries, Psalm chapter/associated `\cl`, `\d`, or a transition to a non-poetry body paragraph.

“Operational stanza” is a model-context boundary, not an inferred literary-stanza claim.

When a scope is partitioned, the controller routes the configured adjacent WIP and REFERENCE records into each child ACT as explicitly labeled context-only packets. Those coordinates may inform interpretation but are excluded from primary coverage, review receipts, and ordinary findings.
