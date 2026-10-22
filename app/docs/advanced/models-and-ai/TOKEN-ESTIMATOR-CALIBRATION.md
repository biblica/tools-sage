# Token Estimator Calibration

SAGE sizes every model review item from the routed Scripture SFM only (see
[Model Handoff Optimization](MODEL-HANDOFF-OPTIMIZATION.md)). The size unit is the estimated token. This page
records how the estimator is calibrated, how far it is from real token counts, and the two adjustments the
Operator and SAGE make on top of the workflow budgets.

## Provider-aware tables (2026-10-22)

`sage.evidence.estimate_tokens` sums a cost per character by Unicode script block. Since 2026-10-22 there is one
weight table per governed tokenizer, and SAGE uses the table of the selected provider:

| Table | Used for | Calibrated |
|---|---|---|
| `o200k-2026-10-15` | Codex | 2026-10-15 (below); re-checked 2026-10-22 on fresh chapters: 0.94-1.28x of real o200k tokens |
| `claude-2026-10-22` | Claude (Opus 5.5 and Sonnet 5.5 measured identical) | 2026-10-22; held-out chapters 0.88-1.37x of real tokens |

The same Scripture costs Claude a median **1.6x** the o200k tokens: Russian/Ukrainian/Hebrew about 1.2-1.4x,
Latin-script languages 1.4-1.9x, Indic scripts 2-3.9x (Punjabi 3.9x, Malayalam 2.8x), while Lao and Tigrinya
cost slightly less. A single table cannot serve both providers: taking the higher weight per script would make
Codex estimates 1.5-4x too high and shrink Codex work units by the same factor.

Budgets therefore mean real tokens of the provider in use. At work-unit size M a Claude request carries about
60% of the Scripture a Codex request carries; size L restores roughly the Codex amount.

Every sizing contract and context budget records its `token_table`. An approved RTC plan stays valid while the
table and work-unit size are unchanged (plans approved before tables existed count as `o200k-2026-10-15` at M);
switching provider makes it stale, and SAGE asks for the plan to be rebuilt and approved.

### Work-unit size (S/M/L)

Configure AI > Work-unit size (or `sage model work-unit-size --size S|M|L`) scales every token and byte budget
and the verse cap of RTC, STC, and BIC by 0.5 / 1 / 2. S means more, smaller requests with closer attention to
each passage; L means fewer requests and less per-request overhead. NCA does not use the estimator. Changing
the size makes approved RTC plans stale. Execution receipts record the size and token table under `sizing`.

### Learned token correction

Every governed call whose provider reports usage (Claude today) appends the estimate and the real prompt tokens
(input + cache creation + cache reads) to `localdata/.system/state/token-observations.jsonl`; prompts under
2,000 estimated tokens are skipped. Once a model has 20 observations, the provider's correction is the highest
per-model median of real/estimated over its last 200 calls, bounded to 1.0-1.5x. The correction only shrinks
planning targets; hard limits follow the work-unit size alone, so a unit planned under an older correction is
never rejected later. An approved RTC plan keeps the correction it was built with.

### Codex models: pending

`gpt-6.1-sol` and `gpt-5.6-sol` were not measured: the Codex workspace was out of credits on 2026-10-22. The
calibration tool can count Codex models through `codex exec --json` once credits are refilled; Codex governed
calls do not report usage yet, so the learned correction applies to Claude only until they do.

### Method and evidence

`system/tools/calibrate_token_estimator.py` takes one chapter (3,500 characters of John; Psalms for Hebrew)
from 24 local translations in 16 scripts plus `@GRK`/`@HEB`, and holds out 2,500 characters of Romans (Isaiah
for Hebrew). o200k is counted locally with `tiktoken`; Claude is counted through SAGE's sealed Claude executor
as the usage of a prompt carrying the sample minus the usage of the same prompt without it. The ASCII space
weight stays at 0.4702 (per character, letters and spaces are almost collinear), punctuation is fitted by least
squares, and the letter weight is raised to cover the worst Latin sample; every other script takes the highest
per-sample value. Counts (keyed by sample hash, no Scripture text) and the fit report are in
[`token-calibration-2026-10-22/`](token-calibration-2026-10-22/). The Claude counts used about 260,000 tokens
of subscription quota across the two models.

## The o200k table: `SAGE_MULTILINGUAL_HEURISTIC_2` (2026-10-15)

`sage.evidence.estimate_tokens` sums a fixed cost per character. The cost depends on the character's Unicode
script block:

| Class | Tokens per character |
|---|---|
| ASCII letters and digits | 0.1608 |
| ASCII punctuation, including USFM markers such as `\v` and `\q1` | 2.1525 |
| ASCII spaces and line breaks | 0.4702 |
| Accented Latin letters; non-ASCII punctuation such as curly quotes and dashes | 0.5 (floor) |
| Hebrew letters and vowel points | 0.9708 |
| Hebrew cantillation accents (U+0591–U+05AF) | 2.1091 |
| Greek | 0.7345 |
| Cyrillic | 0.2927 |
| Arabic letters / Arabic vowel marks | 0.3277 / 1.0901 |
| Devanagari / Bengali / Gurmukhi / Oriya / Malayalam / Sinhala | 0.3388 / 0.3095 / 0.4756 / 1.1086 / 0.3267 / 0.4986 |
| Thai / Lao | 0.2422 / 1.6574 |
| Ethiopic | 2.1597 |
| Han (CJK) | 1.0026 |
| Any other script | 1.0 |

The weights were fitted on 2026-10-15 against `o200k_base`, the tokenizer of the governed Codex provider. The
fit used two books (John and Psalms) from each of 30 local Paratext translations in 13 scripts, plus the
bundled `@GRK` and `@HEB`. The method had two stages:

1. Fit the ASCII and Latin weights on the Latin-script translations.
2. Fit each other script's weight on that script's translations, taking the highest value so the estimate
   errs on the high side.

Scripts with no calibration text cost 1.0 per character, which overestimates most of them. The two
floor values protect languages that use many precomposed accented letters, such as Vietnamese.

## Accuracy on held-out books (Romans; Isaiah for Hebrew)

| Text | Script | Old estimator ÷ real | New estimator ÷ real |
|---|---|---|---|
| English | Latin | 0.99 | 1.21 |
| French | Latin | 0.89 | 1.21 |
| Indonesian | Latin | 0.93 | 1.13 |
| Swahili | Latin | 0.67 | 0.99 |
| Shona | Latin | 0.73 | 0.81 |
| Ukrainian | Cyrillic | 1.07 | 1.13 |
| Russian | Cyrillic | 1.10 | 1.15 |
| Arabic | Arabic | 0.84 | 1.06 |
| Persian | Arabic | 1.20 | 1.14 |
| Urdu | Arabic | 0.97 | 1.02 |
| Hindi | Devanagari | 1.36 | 1.28 |
| Bengali | Bengali | 1.32 | 1.11 |
| Malayalam | Malayalam | 1.14 | 1.01 |
| Thai | Thai | 0.80 | 1.13 |
| Lao | Lao | 0.27 | 1.01 |
| Chinese (Simplified) | Han | 0.52 | 1.14 |
| Tigrinya | Ethiopic | 0.26 | 1.01 |
| Sinhala | Sinhala | 0.85 | 1.02 |
| Punjabi | Gurmukhi | 0.91 | 1.05 |
| Greek (`@GRK`) | Greek | 0.65 | 1.05 |
| Hebrew (`@HEB`) | Hebrew | 0.53 | 1.02 |
| Hebrew without cantillation | Hebrew | 0.64 | 1.02 |

The old estimator, `SAGE_MULTILINGUAL_HEURISTIC_1`, computed the larger of ASCII/4 + non-ASCII/2 and
words × 1.35. It undercounted Greek and Hebrew by about half, and Ethiopic and Lao by about three quarters.
It also split pointed Hebrew words at every vowel mark when counting words, which partly hid the Hebrew
undercount. Some work units therefore carried two to four times the tokens their budget assumed.

## Budgets

Token budgets in the workflow profiles were scaled when the estimator changed. The aim was that typical work
units keep about the same amount of Scripture. Each factor is the median ratio of new to old estimates for
that workflow's routed mix:

| Workflow | Routed mix | Factor |
|---|---|---|
| RTC (and the legacy combined-analysis profile) | WIP + Reference | ×1.25 (measured 1.24) |
| BIC | SOURCE, DONOR, TARGET translations | ×1.25 |
| STC (and the legacy combined-analysis profile) | WIP + Greek or accent-free Hebrew | ×1.45 (measured NT 1.44, OT 1.49) |
| Legacy combined-analysis Targeted Check / Original-Language Review | translations / translations + original language | ×1.25 / ×1.35 |

Byte limits did not change; they remain an independent hard guard. NCA does not use the estimator.
Changing the estimator makes an RTC plan approved under `SAGE_MULTILINGUAL_HEURISTIC_1` stale, because the
sizing contract records the estimator. SAGE asks for the plan to be rebuilt and approved again.

## Hebrew cantillation

Hebrew sent to STC and to RTC original-language adjudication has its cantillation accents (U+0591–U+05AF)
removed. Consonants, vowel points, meteg, maqaf, sof pasuq, and the ketiv/qere marks are kept. The STC planner
measures the same accent-free text. This saves 18–25% of the real tokens in a Hebrew packet (Isaiah 18%,
Genesis 22%, Psalms 25%). The Hebrew authority profile tells the model that missing accents are never a
textual difference. STC's verbatim-quote check already matches quotes with or without accents. BIC's
conditional original-language reads are unchanged.

## Recalibrating

Re-run `calibrate_token_estimator.py` when a provider's tokenizer changes, when a new model line appears, or
when the learned correction for a model sits at its 1.5x bound. Counts are cached, so only new tokenizers or
samples spend quota. Add a new dated table rather than editing an existing one, so approved plans that recorded
the old table are rebuilt rather than reused.
