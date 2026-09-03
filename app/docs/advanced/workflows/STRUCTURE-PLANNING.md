# Structure and work-unit planning

SAGE planning is deterministic preprocessing; it is not analytical completion.

```bash
./system/bin/sage workflow plan --workflow bic --operation inspect \
  --scope "PHP 1-4" --write-packets
```

The planner compiles strict structural records, applies the governed structure policy, measures only the SFM streams actually routed to the review item, and divides the requested scope at preferred boundaries while preserving exact primary-coordinate coverage. Controller USJ/provenance structures remain available for deterministic validation but do not participate in sizing.

Planning first identifies intact spans at governed section markers. For RTC, adjacent spans are packed toward the 6,000-token WIP soft target but normally stop at the 7,000-token preferred packing ceiling; a WIP slice must remain below the 8,000-token WIP hard limit and the complete routed WIP+REFERENCE review item must remain below its configured route hard limit. A complete protected discourse unit may use the WIP headroom rather than be split merely to hit the target. If a protected unit itself is too large, SAGE chooses a balanced natural discourse/paragraph boundary. STC uses the same general slicer with WIP+PRIMARY-OL as its route. Other workflows supply their own review-item stream profile and limits.

## Boundary preference

- major and ordinary section headings are strong candidates;
- Psalm `\cl`, `\qa`, and governed poetry breaks have book-specific weights;
- paragraph boundaries are preferred before arbitrary verse boundaries;
- chapter boundaries are weak fallbacks;
- `\m` continues a preceding body block but can begin a new block after a header or poetry break;
- `\s3` remains structural context but is not a split candidate;
- Actual multi-coordinate WIP and REFERENCE source records are indivisible verse-bridge spans and may not be cut.

## Evidence rules

Each requested coordinate occurs in exactly one primary unit. Adjacent context may be supplied for interpretation but is marked context-only and is not an ordinary finding location. Plan identity includes resources, VRS, structure policy, grammar contracts, compiler version, operation, and scope.

For RTC, the WIP stream supplies discourse/soft-target proposals, while the general slicer validates every proposed boundary against actual multi-coordinate source records in both active Scripture streams. A boundary crossing an actual WIP or REFERENCE verse bridge is moved through the far edge and checked again until stable; the completed routed WIP+REFERENCE SFM is then remeasured. A genuine source-record bridge that exceeds the hard limit blocks rather than being split. VRS mapping ranges are structural metadata, never boundary constraints: coordinate differences are retained as advisories or structural candidates, may cross approved review portions, and are reported without blocking RTC. STC additionally protects connected WIP-bridge and OL-correspondence spans and remeasures the complete WIP+PRIMARY-OL SFM route.

At RTC/STC execution and finalization time, SAGE expands approved ranged labels and current WIP records
to the same atomic coordinate inventory. Raw bridge labels remain source metadata;
`primary_coverage_atoms` are the immutable ownership keys. Existing partition plans created before
that field was introduced are expanded deterministically during aggregation, so a valid completed
Run can retry finalization without weakening exact coverage reconciliation.

Plans and packets remain inside the owning workflow output root and outside immutable publication folders.

## Normal RTC/STC discourse units

The deterministic discourse layer sits inside a section-preferred planner. RTC/STC `REFERENCE_TEXT_COMPARISON` targets about 6,000 estimated WIP tokens, searches for clean section/stanza/paragraph boundaries across the preferred 5,000–7,000 range, and hard-stops the original WIP packet below 8,000. Complete protected discourse units remain intact when they fit; oversized units are divided at balanced natural boundaries rather than greedily filling one packet and leaving a tiny tail. The Reference Project is then correlated to the exact same Scripture range. Focused RTC/STC review remains capped at two intact units and standalone OL Review at one; BIC INSPECT remains governed by its own profile.

- **Prose:** each ordinary body paragraph is one discourse unit.
- **Lists:** `\lh` breaks/heads list flow; each `\li1` starts a major unit; following subordinate `\li2+` paragraphs remain in that `\li1` unit; the next `\li1` starts another unit; `\lf` breaks/ends list flow.
- **Poetry:** one operational stanza is the maximal uninterrupted run of poetry-line paragraphs matched by the governed `poetry_lines` patterns (`q/q#`, `qm/qm#`, `qr`, `qc`, `qd`). Changing indentation/poetry-line marker does not split the unit. `\v` is a coordinate marker and never splits it.
- **Poetry breakers:** `\b`, `\qa`, section/major-section boundaries, Psalm chapter/associated `\cl`, `\d`, or a transition to a non-poetry body paragraph.

“Operational stanza” is a model-context boundary, not an inferred literary-stanza claim.

When a scope is partitioned, the controller routes the configured adjacent WIP and REFERENCE records into each child ACT as explicitly labeled context-only packets. Those coordinates may inform interpretation but are excluded from primary coverage, review receipts, and ordinary findings.
