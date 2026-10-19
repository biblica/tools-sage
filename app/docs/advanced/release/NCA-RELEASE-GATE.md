# NCA release gate: typed package `SAGE_NUMBERS_TYPED_2026-10-09`

**Result, 2026-10-18: FAIL.** FAIL precision is 60%, below the 90% bar. Extraction recall and
planted-error detection pass. NCA stays `PROVISIONAL_UNQUALIFIED`; every FAIL in a report still needs
a reviewer's judgment.

Receipts: [development set](NCA-RELEASE-GATE-2026-10-18-DEVELOPMENT.json) (FAIL) and
[held-out set](NCA-RELEASE-GATE-2026-10-18-HELDOUT.json) (`INCOMPLETE`: the Spanish half did not run
because the codex workspace ran out of credits). Tool: `system/tools/qualify_nca.py`.

## What the gate measures

No hand labelling. Labels are built by code or by LLMs:

| Step | How |
|---|---|
| Gold set | A seeded selection of indexed verses, stratified over twelve hard classes taken from the typed package: apparatus variants, fractions, NIV-only and OL-only rows, dates, numbers of 1,000 or more, measures, compound numbers, lists of four or more values, "one", durations, and plain counts. |
| System under test | The production NCA route (codex `gpt-5.6-sol`, reasoning `medium`) runs over the selected verses of each WIP. It uses the same projection, batching, extraction and local comparison as a Run. |
| Expected values | Two judge models, `claude-opus-5-5` and `claude-sonnet-5-5`, independent of the model under test, read each WIP verse with counting convention 2.0. A verse has gold values only when both judges agree. Disputed verses are counted and left out. |
| FAIL verdict | Both judges see the WIP verse, the original-language verse, the BSB, the expected values and the values read. Each answers `GENUINE` (the WIP states a different quantity) or `FALSE_ALARM`. A FAIL is genuine only when both judges say so. A split verdict counts against precision. |
| Planted errors | Each verse that passes is compared again against its index row with one expected value changed by one. Provisional and apparatus rows are skipped. The comparison must return FAIL. |
| Thresholds | FAIL precision at least 90%, extraction recall at least 95%, planted-error detection at least 95%, at least two WIP languages. |

WIPs: `ukrNPUv1` (Ukrainian) and `spaNVIv3` (Spanish NVI). `spaNVIv3` is read directly from its
Paratext folder through a temporary settings copy, so SAGE state is not changed. Receipts hold coordinates,
values and verdict labels only. WIP text, judge reasons and raw responses stay under
`localdata/.system/nca-benchmarks/`.

## Results

| Set | Verses | FAILs | FAIL precision | Extraction recall | Planted errors | Status |
|---|---:|---:|---:|---:|---:|---|
| Development (seed `nca-gate-1`), as found | 312 | 32 | 4/32 (12.5%) | 295/305 (96.7%) | 156/156 | FAIL |
| Development, after the four changes below | 312 | 5 | 3/5 (60%) | 295/305 (96.7%) | 161/161 | FAIL |
| Held-out (seed `nca-gate-2`, no shared verse), Ukrainian, as found | 167 | 6 | 0/6 (0%) | 152/158 (96.2%) | 90/90 | INCOMPLETE |
| Held-out, Ukrainian, after the changes | 167 | 0 | no evidence | 152/158 (96.2%) | 91/91 | INCOMPLETE |

Rescoring after a comparison change made no model calls: the sealed extraction phases were replayed. The
nine held-out Ukrainian verses that ran out of provider credits are left out of every measure.

## Changes made from the measurement

1. **Association check: one gloss on different values.** When one gloss landed different WIP numbers on
   the same source item ("12 bulls … 3 [bulls] facing north", 1KI 7:25), the check reported a swap and a
   correct verse became a BLOCKING `WRONG_ASSOCIATION` FAIL. Those numbers now stay undecided; a real swap
   ("1,000 gold dishes") still fails.
2. **Association check: unglossed source items.** When a source item has no distinguishing words, a gloss
   cannot rule it out ("righteous people 50" against an unglossed 50, GEN 18:28). A mismatch then stays
   undecided. This case came from the held-out set, which therefore no longer measures this class blind.
3. **`ONE_ONLY_DIFFERENCE` review.** A WIP that differs from the source only by added or missing values of
   one is NEEDS_REVIEW, not FAIL. The judges called 14 of the 16 such development FAILs false alarms: an
   implied singular made explicit ("one talent" for "a talent"), a repeated "one" left out, or "year-old"
   read as 1. One verdict was split; the one genuine case (1SA 6:17) is still reported, for review.
4. **`VALUE_OMITTED` review (PO decision, 2026-10-18).** A WIP that leaves out some source numbers and adds
   none is NEEDS_REVIEW, not FAIL. Stating a repeated number once ("twenty cubits long and wide"), an
   idiom, or "each" or "both" is often a style choice. The translator note asks whether the omission is
   deliberate and consistent with the rest of the translation. No genuine FAIL measured was a pure
   omission.

## Remaining FAILs (development set)

| Verse | WIP | Verdict |
|---|---|---|
| 2CH 35:8 (uk) | 300 rendered as 3,000 | GENUINE |
| EZK 45:12 (es) | 20 + 25 + 15 shekels rewritten as one total of 60 | GENUINE |
| MRK 6:37 (es) | 200 denarii rendered as six months' wages | GENUINE |
| 1CH 12:37 (es) | "half the tribe" read as ½ by the model (the convention does not count it) | FALSE_ALARM |
| REV 11:4 (es) | "two" added for the witnesses; judges split earlier and now call it a false alarm | FALSE_ALARM |

The remaining false alarms are model misreads and an added number in context. A further rule change
would only be measured on the same 312 verses. The next step is a fresh held-out run in both languages
(`TODO-20261018-001`).

## Also found

NCA cannot run on Acts. The package mapping `eng_org_map_rules.txt` lacks the `ACT 19:40-41`
continuation that `eng.vrs` declares, so `project_scope` stops with `NCA_MAPPING_BASELINE_MISMATCH`.
The 2026-10-18 gate left Acts out and lists it in each receipt. Resolved 2026-10-19 (`TODO-20261018-002`,
`IMP-20261019-001`): `project_scope` takes this one continuation from `eng.vrs` for this package, so the
next gate run includes Acts.

## Limits

The gate measures the selected verses and two WIPs. Judge agreement is not proof: re-judging the same
FAILs in a different batch changed some verdicts between `FALSE_ALARM` and `SPLIT`, which is why a split
counts against precision. Five FAILs is a small sample. SQS confidence checks are not applied.

## Rerun

From `app/` with the managed interpreter (WIP settings, language and script per `--wip`):

```sh
python system/tools/qualify_nca.py --package SAGE_NUMBERS_TYPED_2026-10-09 \
  --wip "ukrNPUv1=<job runtime.yml>:uk-UA:Cyrl" --wip "spaNVIv3=<settings copy>:es-419:Latn" \
  --work <runtime_state_root>/nca-benchmarks/<name> --seed nca-gate-3 \
  --exclude <development selection.json> --exclude <held-out selection.json> \
  --receipt docs/advanced/release/<receipt>.json
```

Each step caches its evidence. To rescore after a comparison change, delete that WIP's `sut.json` and pass
`--replay-route <earlier receipt.json>`: sealed phases are replayed under the recorded route and no
provider is called. A provider failure leaves its verses out and makes the receipt `INCOMPLETE`.
