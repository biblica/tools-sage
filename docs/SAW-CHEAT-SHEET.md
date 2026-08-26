# SAW Cheat Sheet — beta

SAW binds exactly one `WIP` and one authorized `REFERENCE`. Scripture Projects remain read-only.

**Authority:** REFERENCE is the normal authorized LWC Reference Project comparison. For an explicitly OL-routed bounded question, configured GRK/HEB becomes the primary textual authority for the source-text question in that task only. WIP remains the subject under assessment.

## Menus

`SAW` is the Job setup menu: open/choose/add/manage a SAW Job. The management list marks the active row once as `[ACTIVE]`; **Choose active Job** changes that marker, and **Open active SAW Job** enters `SAW JOB - <id>`, the check-execution menu. `A. Back` from the Job returns to the calling SAW list/menu.

The Job menu exposes:

1. Continue active Run — only when a Run exists; context shows Job, check, task/stage, scope, and status.
2. Standard QA
3. Targeted Check
4. Original-Language Review

## Standard QA

Broad systematic QA over a selected scope. The Operator can enable/disable four standard check groups: structure/completeness, translation/meaning, language/readability, and consistency. Ordinary stages do not receive OL Scripture; a justified bounded issue may be routed internally to selective OL adjudication.

### Text policy

Marker context controls **finding elevation**, never finding severity:

- `NORMAL` — content is checked normally; marker context does not suppress findings.
- `MATERIAL_ONLY` — non-material wording/style detections are omitted; material semantic/consistency/structural issues are reported at their normal severity.
- `STRUCTURE_ONLY` — only marker/USFM structure is evaluated as a finding source.

Defaults: `\add` and `\nd` = `MATERIAL_ONLY`; `\f` and `\x` = `STRUCTURE_ONLY`. Quotations are checked normally and are not an Operator policy toggle. The effective policy is snapshotted into the Run.

## Targeted Check

One bounded WIP+REFERENCE question. No Greek/Hebrew Scripture is routed. If the question requires direct OL evidence, use Original-Language Review. The machine operation remains `focused` for compatibility.

## Original-Language Review

One explicit focus and a verse or short verse range. Exactly the applicable configured Greek or Hebrew resource is routed. Within that bounded source-text question, GRK/HEB is primary textual authority and REFERENCE is comparative translation evidence.


## Natural-language entry

Natural-language entry may request Standard QA, a Targeted Check, or an Original-Language Review. Recoverable missing or ambiguous Operator input returns `INPUT_REQUIRED`; reserve `BLOCKED` for a confirmed in-scope technical or integrity failure.

## Run state

A successful SAW Run progresses through governed tasks and becomes `FINALIZED` only after required findings, coverage, and report outputs pass their contracts. SAW never edits Scripture projects.
