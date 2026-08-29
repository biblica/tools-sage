# SAW Cheat Sheet — beta

SAW Jobs bind exactly one `WIP` and one authorized `REFERENCE`. Scripture Projects remain read-only. STC does not consume the bound REFERENCE; it routes WIP directly with the testament-appropriate PRIMARY OL authority.

**Authority:** REFERENCE is the normal authorized LWC Reference Project comparison for RTC and Targeted Check. STC uses configured PRIMARY GRK for NT or PRIMARY HEB for OT and is independent of REFERENCE and RTC findings. For an explicit Original-Language Review, the applicable configured GRK/HEB authority is primary for the bounded source-text question. WIP remains the subject under assessment.

## Menus

`SAW` is the Job setup menu: open/choose/add/manage a SAW Job. The management list marks the active row once as `[ACTIVE]`; **Choose active Job** changes that marker, and **Open active SAW Job** enters `SAW JOB - <id>`, the check-execution menu. `A. Back` from the Job returns to the calling SAW list/menu.

The Job menu exposes:

1. Continue active Run — only when a Run exists; context shows Job, check, task/stage, scope, and status.
2. Reference Text Comparison (RTC)
3. Source Text Correspondence (STC)
4. Targeted Check
5. Original-Language Review

The Job view also shows `AI Routing` and a compact `SKILL | PROVIDER | MODEL | REASONING | STATUS`
table. Idle rows are current recommendations. An active attempt uses its immutable execution receipt.
Normal Setup chooses a provider only; automatic routing selects an available qualified exact route for
`saw-rtc`, `saw-stc`, `saw-focused-check`, or `saw-original-language-review`. The optional advanced
override cannot bypass per-Skill qualification.

## Reference Text Comparison (RTC)

Broad systematic RTC over a selected scope. The Operator can enable/disable four standard check groups: structure/completeness, translation/meaning, language/readability, and consistency. Ordinary stages do not receive OL Scripture; a justified bounded issue may be routed internally to selective OL adjudication.

### Text policy

Marker context controls **finding elevation**, never finding severity:

- `NORMAL` — content is checked normally; marker context does not suppress findings.
- `MATERIAL_ONLY` — non-material wording/style detections are omitted; material semantic/consistency/structural issues are reported at their normal severity.
- `STRUCTURE_ONLY` — only marker/USFM structure is evaluated as a finding source.

Defaults: `\add` and `\nd` = `MATERIAL_ONLY`; `\f` and `\x` = `STRUCTURE_ONLY`. Quotations are checked normally and are not an Operator policy toggle. The effective policy is snapshotted into the Run.

## Source Text Correspondence (STC)

Independent systematic WIP-to-primary-OL correspondence review. NT routes bounded WIP + PRIMARY GRK; OT routes bounded WIP + PRIMARY HEB. STC does not read, require, fingerprint, or use REFERENCE Scripture or RTC findings as analytical evidence. Findings are limited to `OMISSION`, `ADDITION`, `VARIATION`, and `CONSISTENCY`; zero-finding work units still require analytical-completion proof.

## Targeted Check

One bounded WIP+REFERENCE question. No Greek/Hebrew Scripture is routed. If the question requires direct OL evidence, use Original-Language Review. The machine operation remains `focused` for compatibility.

## Original-Language Review

One explicit focus and a verse or short verse range. Exactly the applicable configured Greek or Hebrew resource is routed. Within that bounded source-text question, GRK/HEB is primary textual authority and REFERENCE is comparative translation evidence. Each adjudication item is sent as its own model request; unrelated items and conversation state are never combined.


## Natural-language entry

Natural-language entry may request Reference Text Comparison (RTC), Source Text Correspondence (STC), a Targeted Check, or an Original-Language Review. Recoverable missing or ambiguous Operator input returns `INPUT_REQUIRED`; reserve `BLOCKED` for a confirmed in-scope technical or integrity failure.

## Run state

A successful SAW Run progresses through governed tasks and becomes `FINALIZED` only after required findings, coverage, and report outputs pass their contracts. SAW never edits Scripture projects. Aggregation, coverage reconciliation, report composition, report naming, and publication are deterministic Python work with no LLM tokenization. Optional secondary-language rendering is one reported item per request and cannot change the canonical result.
