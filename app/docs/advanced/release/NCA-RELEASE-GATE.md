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
| FAIL verdict | Each FAIL is judged in its own call, so its verdict cannot change with the other FAILs of a rescore. Both judges see the WIP verse, the original-language verse, the BSB, the kind of FAIL, the expected values and the values read with what each counts. Each names one cause, judged against the product policy that only a changed quantity is a FAIL: `VALUE_CHANGED` (genuine), `CHECKER_MISREAD`, `NOT_A_QUANTITY`, `RESTRUCTURED`, `REVIEW_CLASS` (omission, addition, conversion) or `EXPECTED_WRONG`. A FAIL is genuine only when both judges give `VALUE_CHANGED`. A split verdict counts against precision. |
| FAIL reading | Code marks each FAIL `READ_CORRECTLY` when the extracted values equal the gold values (the comparison, convention or index made the call) and `MISREAD` when they differ. This says where a false alarm must be fixed without asking a judge. |
| False-FAIL rate | FAILs not judged genuine, per assessed verse. Unlike precision, it does not depend on how many real errors the WIPs happen to contain, and it is what a reviewer pays for. Since schema 1.2 (PO decision 2026-10-20) this is the gate check; FAIL precision is still reported beside it. |
| Planted errors | Each verse that passes is compared again against its index row with one expected value changed by one. Provisional and apparatus rows are skipped. The comparison must return FAIL. This tests the comparison only. |
| Text plants | End to end, on real WIP text: up to 50 verses per WIP that pass, read exactly as the judges read them, with whole-number values on rows that can FAIL. Opus rewrites each with one counted number raised by one (fewest words, grammar kept). A plant is kept only when both judges count exactly the planned values in the rewrite, and when the edit, made inside that verse of the book's USFM, recompiles to that verse alone changed as planned. The production route then runs on the planted books; each planted verse must FAIL. |
| Thresholds | False-FAIL rate at most 0.5% (1 in 200 verses), extraction recall at least 95%, planted-error and text-plant detection at least 95%, at least two WIP languages. Every ratio carries a Wilson 95% interval. A check fails when the whole interval is on the wrong side of its bar, and passes when the measured value is on the right side on enough cases: 300 verses (false-FAIL rate), 100 (recall, planted errors), 60 (text plants). Anything between is `INSUFFICIENT_EVIDENCE`, which never releases. |

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

## Measurement review, 2026-10-20

The precision measurement was reviewed after held-out 3 (seed `nca-gate-4`, 159 verses per WIP;
receipts in the git-ignored `project-management/private/`). The changes above (gate schema 1.1) came
from five findings:

1. **The verdict question contradicted the product policy.** Judges were told an added or dropped
   number, or one source number replaced by another explicit one, is `GENUINE`. Product decisions since
   2026-10-18 make omissions, additions and unit conversions review. The judges now answer against the
   current policy and name a cause.
2. **Verdicts depended on batch neighbours.** Up to 20 FAILs shared one prompt, so a rescore that added
   or dropped one FAIL re-asked every verdict, and some flipped (see Limits). Each FAIL is now judged
   alone.
3. **"Model misread" was assumed, not measured.** All three held-out 3 false alarms are
   `READ_CORRECTLY`: the model read the WIP exactly as both judges did. Two are `RESTRUCTURED`
   (EZK 45:23 a repeated seven stated once; 2KI 25:17 "the two columns" for "one pillar ... the second")
   and one is `NOT_A_QUANTITY` (NUM 33:3 Ukrainian "другого дня", "the next day"). The fix belongs in the
   comparison and the counting convention, not in the extraction prompt.
4. **Four FAILs cannot show 90%.** 1/4 has a 95% interval of 4.6-69.9%. That is still a clear FAIL,
   but a point estimate on so few FAILs is not evidence in either direction; checks now say so.
5. **Precision depends on the WIPs' own error rate.** Held-out 3 found 1 genuine FAIL in 317 assessed
   verses (0.3%) and 3 false ones (0.9%). With genuine errors that rare, 90% precision needs fewer than
   one false FAIL per about 2,900 verses, and showing it needs about 20 FAILs, so about 6,000 verses per
   run. A run of about 160 verses per WIP can only end `FAIL` or `INSUFFICIENT_EVIDENCE` on precision,
   however good the check is. PO decision 2026-10-20 (schema 1.2): the gate checks the false-FAIL rate
   per verse instead, and text plants test detection end to end on real WIP text, where the index
   plants test the comparison only.

| Held-out 3 | FAILs | Genuine | False alarms by cause | Reading | FAIL precision | False-FAIL rate |
|---|---:|---:|---|---|---:|---:|
| Rejudged, schema 1.1 | 4 | 1 (2KI 25:27, day 27 as 25) | 2 `RESTRUCTURED`, 1 `NOT_A_QUANTITY` | all `READ_CORRECTLY` | 1/4 (25%; 4.6-69.9%) | 3/317 (0.9%; 0.3-2.7%) |

Held-out 3 under schema 1.2 (same verses and sealed extractions; private receipt
`NCA-RELEASE-GATE-2026-10-20-HELDOUT3-SCHEMA12.json`): **`INCOMPLETE`**. The codex workspace ran out of
credits during the Spanish text plants, so 13 of them never ran.

| Check | Measured | 95% interval | Result |
|---|---:|---:|---|
| False-FAIL rate (at most 0.5%) | 3/317 (0.9%) | 0.3-2.7% | `INSUFFICIENT_EVIDENCE` |
| Extraction recall (at least 95%) | 293/314 (93.3%) | 90.0-95.6% | `INSUFFICIENT_EVIDENCE` |
| Planted errors, index (at least 95%) | 151/151 | 97.5-100% | PASS |
| Text plants (at least 95%) | 82/82 | 95.5-100% | PASS |
| FAIL precision (reported only) | 1/4 (25%) | 4.6-69.9% | — |

Text plants: 49 of 50 plants per WIP were confirmed by both judges, and 47 (Ukrainian) and 48 (Spanish)
were applied to the USFM; the rest touched markup or a repeated phrase. Every measured plant was read
exactly as planned. The first run found a comparison bug in both languages: 2CH 2:10 with one 20,000
raised to 20,001 came back as `UNIT_CONVERSION` review, because the conversion rule took the unit of
the first source item with that value (cors) while the WIP had changed the baths of oil. The rule now
checks the units of every source item with that value. Replaying the sealed phases with the fix (no
provider calls) detects 82/82 plants and changes no outcome on the 318 held-out verses.


## Also found

NCA cannot run on Acts. The package mapping `eng_org_map_rules.txt` lacks the `ACT 19:40-41`
continuation that `eng.vrs` declares, so `project_scope` stops with `NCA_MAPPING_BASELINE_MISMATCH`.
The 2026-10-18 gate left Acts out and lists it in each receipt. Resolved 2026-10-19 (`TODO-20261018-002`,
`IMP-20261019-001`): `project_scope` takes this one continuation from `eng.vrs` for this package, so the
next gate run includes Acts.

## Limits

The gate measures the selected verses and two WIPs. Judge agreement is not proof: re-judging the same
FAILs in a different batch changed some verdicts between `FALSE_ALARM` and `SPLIT`, which is why a split
counts against precision. Since schema 1.1 each FAIL is judged in its own call, so a rescore no longer
re-asks the verdicts of unchanged FAILs. Five FAILs is a small sample. SQS confidence checks are not applied.

## Rerun

From `app/` with the managed interpreter (WIP settings, language and script per `--wip`):

```sh
python system/tools/qualify_nca.py --package SAGE_NUMBERS_TYPED_2026-10-09 \
  --wip "ukrNPUv1=<job runtime.yml>:uk-UA:Cyrl" --wip "spaNVIv3=<settings copy>:es-419:Latn" \
  --work <runtime_state_root>/nca-benchmarks/<name> --seed nca-gate-3 \
  --exclude <development selection.json> --exclude <held-out selection.json> \
  --receipt docs/advanced/release/<receipt>.json
```

Each step caches its evidence. `--plants N` sets text plants per WIP (default 50; 0 skips them, which leaves
that check `INSUFFICIENT_EVIDENCE`). To rescore after a comparison change, delete that WIP's `sut.json` (and
`plants-sut.json`) and pass
`--replay-route <earlier receipt.json>`: sealed phases are replayed under the recorded route and no
provider is called. A provider failure leaves its verses out and makes the receipt `INCOMPLETE`.
Before any step that will call the route under test, the tool sends it one tiny request. If the provider
refuses (for example a workspace out of credits, which a signed-in check does not show), it stops with
exit code 2 and the provider's message before changing anything.
