# RTC/STC Cheat Sheet — beta

RTC and STC are independent canonical workflows. Each Job binds one immutable `WIP`; RTC also binds one immutable `REFERENCE`, while STC selects the testament-appropriate primary original-language authority by Book canon. Scripture Projects remain read-only.

**Authority:** RTC compares WIP with the Job-bound REFERENCE. STC uses configured PRIMARY GRK for NT or PRIMARY HEB for OT and never uses a REFERENCE Project. WIP remains the subject under assessment.

## Menus

The Main Menu exposes separate **Reference Text Comparison (RTC)** and **Source Text Correspondence (STC)** Job setup menus. The management list marks the active row once as `[ACTIVE]`; **Choose active Job** changes that marker. `A. Back` returns to the calling workflow list.

Each Job menu exposes its one canonical Run action plus Run history, Manage Job, reports, and recovery. **Continue active Run** appears while a Run exists and shows the Job, task/stage, scope, and status.

The Job view also shows `AI Routing` and a compact `SKILL | PROVIDER | MODEL | REASONING | STATUS`
table. Idle rows are current recommendations. An active attempt uses its immutable execution receipt.
Normal Setup chooses a provider only. The audited advanced override is the single manual route
control. Automatic routing uses exact qualification data when present; in a true no-data state it
uses the Operator's pinned no-data default when one is set, otherwise Codex native `medium`, and
displays `PROVISIONAL_UNQUALIFIED`, regardless of release state. Failed, unreliable, stale, or
unavailable evidence does not trigger fallback. The advanced override cannot bypass per-Skill
qualification.

## Reference Text Comparison (RTC)

Broad systematic RTC over a selected scope. The Operator can enable/disable four standard check groups: structure/completeness, translation/meaning, language/readability, and consistency. Ordinary stages do not receive OL Scripture; a justified bounded issue may be routed internally to selective OL adjudication.

### Text policy

Marker context controls **finding elevation**, never finding severity:

- `NORMAL` — content is checked normally; marker context does not suppress findings.
- `MATERIAL_ONLY` — non-material wording/style detections are omitted; material semantic/consistency/structural issues are reported at their normal severity.
- `STRUCTURE_ONLY` — only marker/USFM structure is evaluated as a finding source.

Defaults: `\add` and `\nd` = `MATERIAL_ONLY`; `\f` = `STRUCTURE_ONLY`; `\x` = `NORMAL`. Cross-references are therefore checked for structure, presence, payload, and ordering by default; SAGE compares their Scripture target numbers and footnote origins in code. Quotation structure belongs to the structure/completeness group, so turning that group off also turns off quotation checks. The effective policy is snapshotted into the Run.

The Job menu offers **Run RTC on <WIP> with defaults** and **RTC defaults setting**. The defaults screen (titled `JOB defaults`) holds the check groups and text policy every later Run uses; there is no separate per-Run toggle screen, and defaults cannot change while a Run is open.

### Selective source referral

An RTC issue becomes a source referral only when it changes the core proposition, creates incompatible meanings, fits one closed class, genuinely requires original-language evidence, remains unresolved by routed non-OL evidence, contains one smallest-scope issue, and is unique. Closed classes: polarity/negation, participant identity or role, core event or state, and essential proposition omission/addition. Nuance or intensity (`dislike` versus `hate`), equivalent paraphrase/voice, grammar, style, readability, spelling, punctuation, USFM, and ordinary consistency stay in RTC. Each admitted request is evaluated alone.

## Source Text Correspondence (STC)

Independent systematic WIP-to-primary-OL correspondence review. NT routes bounded WIP + PRIMARY GRK; OT routes bounded WIP + PRIMARY HEB. STC does not read, require, fingerprint, or use REFERENCE Scripture or RTC findings as analytical evidence. Findings are limited to `OMISSION`, `ADDITION`, `VARIATION`, and `CONSISTENCY`; zero-finding work units still require analytical-completion proof.

## Natural-language entry

Natural-language entry may request Reference Text Comparison (RTC) or Source Text Correspondence (STC). Recoverable missing or ambiguous Operator input returns `INPUT_REQUIRED`; reserve `BLOCKED` for a confirmed in-scope technical or integrity failure.

## Run state

A successful RTC/STC Run progresses through governed tasks and ends `COMPLETE` after required findings, coverage, and report outputs pass their contracts (`COMPLETE_WITH_STRUCTURE_PROBLEMS` or `COMPLETE_WITH_EXCEPTIONS` when structure differences or `NOT_ASSESSED` work units are reported). Plans and work units are `FINALIZED` internally; a Run is not. RTC/STC never edit Scripture Projects. Aggregation, coverage reconciliation, report composition, report naming, and publication are deterministic Python work. Optional secondary-language rendering calls the model for the rendered text; it is assistive and cannot change the canonical result.

A work unit that keeps failing is reported `NOT_ASSESSED` after three attempts and the Run continues; its coordinates are listed under "Exceptions — not assessed". Defective items inside a usable result are dropped or corrected and recorded in the Run's exception report.

An RTC chapter report consolidates every Run of the Job that reviewed that chapter: a coordinate reviewed in any Run counts as reviewed, repeated findings are merged, and conflicting conclusions are marked for human review.

Progress uses `Review range` for the Run, `Review portion` for the immutable approved partition, and local `Structural check` / `Source check` counters inside that portion. A source case never increases or renumbers the approved portion denominator.
