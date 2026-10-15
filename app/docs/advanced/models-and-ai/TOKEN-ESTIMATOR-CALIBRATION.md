# Token Estimator Calibration

SAGE sizes every model review item from the routed Scripture SFM only (see
[Model Handoff Optimization](MODEL-HANDOFF-OPTIMIZATION.md)). The size unit is the estimated token. This page
records how the estimator is calibrated and how far it is from real token counts.

## Current estimator: `SAGE_MULTILINGUAL_HEURISTIC_2`

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

Re-fit when the governed provider's tokenizer changes, or when a new script enters use and its estimates look
wrong. Count real tokens for a few whole books per script, then repeat the two-stage fit above. Keep held-out
books for checking. Change `TOKEN_ESTIMATOR` whenever the weights change, so approved plans that recorded the
old estimator are rebuilt rather than reused.
