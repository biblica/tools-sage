# Structure and work-unit planning

SAGE planning is deterministic preprocessing; it is not analytical completion.

```bash
./sage workflow plan --workflow bic --operation inspect \
  --scope "PHP 1-4" --write-packets
```

The planner compiles strict USFM/USJ records, applies the governed structure policy, measures the serialised evidence packet, and divides the requested scope at preferred boundaries while preserving exact primary-coordinate coverage.

If a hard limit would otherwise leave a very small final unit, the planner rebalances the final pair at a discourse boundary. It merges the tail when the combined unit fits; otherwise it maximises the smaller side without splitting a discourse unit.

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

Plans and packets remain inside the owning workflow output root and outside immutable publication folders.

## Normal SAW discourse units

The deterministic discourse layer sits above the split-score planner. Normal SAW `TRANSLATION_AND_MEANING_QA` keeps each natural unit intact, but coalesces adjacent units toward the configured minimum and target token sizes. `maximum_primary_discourse_units: 0` means there is no competing one-unit ceiling; hard token, byte, and verse limits still apply.

- **Prose:** each ordinary body paragraph is one discourse unit.
- **Lists:** `\lh` breaks/heads list flow; each `\li1` starts a major unit; following subordinate `\li2+` paragraphs remain in that `\li1` unit; the next `\li1` starts another unit; `\lf` breaks/ends list flow.
- **Poetry:** one operational stanza is the maximal uninterrupted run of poetry-line paragraphs matched by the governed `poetry_lines` patterns (`q/q#`, `qm/qm#`, `qr`, `qc`, `qd`). Changing indentation/poetry-line marker does not split the unit. `\v` is a coordinate marker and never splits it.
- **Poetry breakers:** `\b`, `\qa`, section/major-section boundaries, Psalm chapter/associated `\cl`, `\d`, or a transition to a non-poetry body paragraph.

“Operational stanza” is a model-context boundary, not an inferred literary-stanza claim.

When a scope is partitioned, the controller routes the configured adjacent WIP and REFERENCE records into each child ACT as explicitly labelled context-only packets. Those coordinates may inform interpretation but are excluded from primary coverage, review receipts, and ordinary findings.
