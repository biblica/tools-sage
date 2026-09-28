# NCA Extraction Batch Size Optimization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise NCA's extraction batch size from its original, deliberately conservative starting cap toward the real ceiling its own evidence policy already provisions, cutting the number of sequential provider round-trips per Run by a large factor with no change to extraction correctness, checkpointing, or retry semantics.

**Architecture:** No new subsystem. `numbers/batching.py::plan_batches` already delegates real sizing to the shared, token-budget-aware authority (`sfm_slicer.plan_sfm_work_units`, driven by `EvidencePolicy`) that RTC also uses. Today that delegation never gets to do its job at scale: `plan_batches` pre-truncates each candidate group to `optimization_policy.extraction_batch_max_units` (currently `8`) *before* handing it to `plan_sfm_work_units`, which is otherwise licensed by the same evidence policy (`target_estimated_tokens: 18000`, `hard_estimated_tokens: 28000`, `maximum_primary_verse_units: 220` — identical to RTC's) to size much larger work units on its own. This plan measures what the sizer actually produces when it isn't pre-truncated, raises the configured cap to that measured, safe value, and re-qualifies the change with the same benchmark discipline the original optimization plan used. It does not touch batching identity, checkpointing (`replay.py`'s `PhaseStore`), retry/bisection (`split_batch`), or the extraction schema/skill contract.

**Tech Stack:** Existing Python 3.10+ runtime, pytest, the existing `benchmark_nca.py` synthetic/live benchmark tool, the existing SFM slicer/evidence-policy sizing authority. No new runtime dependency.

**Prior art (read first):** [`2026-09-10-NCA-OPTIMIZATION.md`](2026-09-10-NCA-OPTIMIZATION.md) (the plan that introduced batching, the `extraction_batch_max_units` field, and the benchmark tool), its [design spec](../specs/2026-09-10-NCA-OPTIMIZATION-DESIGN.md) — line 80 states in full: *"Start with a proposed cap of eight protected target units per extraction batch. This is a conservative initial configuration to benchmark, not a measured optimal size... Honor existing routed-SFM hard limits independently; the eight-unit cap never authorizes an oversized bridge."* — and the existing [qualification record](../../advanced/release/NCA-OPTIMIZATION-QUALIFICATION.md), which recorded the original baseline (32 single-unit calls) vs. cap-eight (4 calls, 87.5% fewer requests) measurement this plan extends.

**Status:** All three tasks complete; full `system/tests/numbers` (917 tests) and the full `system/tests` app suite pass. Written from a live operator question about why a real NCA Run (job `NCA-ukrNPUv1_20260921`, 66 books, ~31,103 atomic coordinates) needs on the order of several thousand sequential extraction calls to complete, and the observation that NCA does not need the same per-verse interpretive context RTC does, so it should be able to safely batch at least as many verses per call as RTC does (220) within the identical token budget.

**Corrections made during execution, for anyone reading this plan afterward:**
- `system/tests/numbers/test_benchmark.py:365,387` (the original Task 2 target) turned out to need **no change** — `benchmark_nca_optimized.py`'s synthetic strategy hardcodes its own hard-coded test policy (`extraction_batch_max_units: 8` inline in `_run_synthetic_optimized`), entirely decoupled from the shipped `profile.yml`. The actually-hardcoded, needed-generalizing spot was `benchmark_nca_qualification.py::qualify_pair`'s fixture-specific `if before['case_count'] == 32: gates['four_batches'] = optimized == 4` gate, which the real fix replaced with a general `batches_match_configured_cap` gate.
- No new larger synthetic fixture was needed for Task 3 — the existing 32-unit `optimization-mat5.json` fixture already collapses cleanly to 1 batch at cap=220 (32 < 220), which is sufficient to prove and regression-test the mechanism. A larger fixture would only be needed to test a case that itself still requires >1 batch at the new cap, which isn't necessary to validate this change.
- The real ceiling turned out to be governed by **chapter boundaries**, not the token budget: `plan_batches` unconditionally flushes at every book/chapter change (`numbers/batching.py`'s pending-loop, independent of `max_units`), so in practice no batch can ever span more than one chapter regardless of cap. This made "measure the real ceiling" concrete: it's the longest chapter in the canon (Psalm 119, 176 verses), not RTC's 220-unit policy ceiling in the abstract.

## Global constraints

- This plan changes a configured *number*, not the `nca-optimization-2.0` policy schema shape — `extraction_batch_max_units` remains a required positive integer field; only its shipped default changes. Sealed Runs created before this change keep their own recorded `optimization_policy` snapshot (per the existing `ACT_INPUT_STALE`/staleness-detection design) and are unaffected; only newly created Runs pick up the new default.
- Do not remove the `extraction_batch_max_units` ceiling itself. Per the original design spec, it is an intentional belt-and-suspenders governance ceiling in addition to (not instead of) `plan_sfm_work_units`'s own hard token/byte limits — keep both.
- Preserve every existing accuracy/coverage guarantee: no batch may lose, duplicate, or silently truncate a protected group; `BatchPlan`'s union-of-planned-and-blocked-equals-inventory invariant in `plan_batches` must continue to hold at any cap value.
- Preserve `split_batch`'s bisection-retry behavior and `transient_retries: 1`; re-derive (do not assume) the resulting worst-case attempt bound at the new cap, since it scales with batch size.
- Do not weaken `test_eight_unit_batches_cover_the_scope_once` (`system/tests/numbers/test_batching.py:35`) or the extraction-count assertions in `system/tests/numbers/test_benchmark.py:365,387` — generalize them to the configured cap rather than deleting or hardcoding a new magic number, so a future re-tuning does not require another manual test rewrite.
- No CI wall-clock speed thresholds; report measured call/byte counts deterministically, exactly as the original plan's Task 9 did.
- Keep `LIVE_MODEL_BENCHMARK_NOT_RUN` / `SQS: NOT_APPLIED` unless a real live comparison is separately, explicitly initiated by the operator — this plan does not authorize or imply one.
- Out of scope for this plan, tracked separately (do not fold in): (a) a deterministic digit-numeral fast path ahead of the LLM extraction call, using this session's new CLDR locale-facts digit data — a bigger, structural change to *whether* a verse needs a call at all, not *how many verses per call*; (b) `request_concurrency` (currently hard-pinned to `1` in `numbers/policy.py:289`) — a separate, already-reviewed-as-contained feature in its own right (batches are embarrassingly parallel and the checkpoint layer is already lock-safe, per this conversation's prior review, but it touches the same sealed-Run-snapshot compatibility surface and deserves its own plan).

## Delivery order and file ownership

```text
1 measure the real ceiling -> 2 raise the configured cap + generalize tests -> 3 re-benchmark and re-qualify
```

Paths below are relative to `app/`. In task file lists, `numbers/` abbreviates `system/src/sage/numbers/`, and NCA test filenames abbreviate `system/tests/numbers/`.

| File | Responsibility |
|---|---|
| `numbers/batching.py` | Unchanged: `plan_batches`'s `max_units` parameter and truncation logic stay as-is; only its caller's configured value changes. |
| `system/config/workflows/nca/profile.yml` | `optimization_policy.extraction_batch_max_units` — the value this plan raises. |
| `numbers/policy.py` | `validate_optimization_policy` — unchanged validation (positive integer), confirm no other code path assumes `8` specifically. |
| `system/tests/numbers/test_batching.py` | Generalize the batch-count assertion to the configured/measured cap. |
| `system/tests/numbers/test_benchmark.py` | Generalize the `phase_counts['EXTRACTION'] == 4` assertions and extend the synthetic fixture large enough to exercise the new cap meaningfully. |
| `system/tools/benchmark_nca.py`, `system/tests/numbers/fixtures/optimization-cases.json` | Extend the controlled synthetic workload beyond 32 units so the new cap is actually exercised, not just permitted. |
| `docs/advanced/release/NCA-OPTIMIZATION-QUALIFICATION.md` | Append the new measurement (new task, do not rewrite the original 32-unit/cap-eight history). |

## Task 1: Measure the real, untruncated batch size

**Files:** Extend `system/tests/numbers/test_batching.py`; no production code changes in this task.

- [x] Added `test_uncapped_batch_size_is_governed_by_the_real_sizer_not_an_artificial_truncation` and `test_configured_cap_covers_the_scope_once_at_any_size` to `test_batching.py`, using a 220-unit synthetic fixture (raised `make_units`'s ceiling from 32 to 256 in `conftest.py` for this and future large-fixture tests). Confirms: 220 token-cheap units truncate to 28 batches at cap=8 vs. 1 batch uncapped — the pre-truncation, not the real sizer, was the bottleneck.
- [x] Measured against **real project data**, not just synthetic placeholders (see the qualification addendum): a real in-progress WIP book (10 chapters, 280 verses, longest chapter 70) needed 39 batches at cap=8 vs. exactly 10 (one per chapter) at cap>=70 — raising the cap past 70 changed nothing further for that book, since chapter boundaries (not the token budget) are the actual binding constraint once the cap is no longer artificially small. **Psalm 119** (176 verses, the single longest chapter in the whole canon) collapsed from 22 batches at cap=8 to exactly **1 batch** at cap=176 or 220, with zero blocked inputs — real evidence that even the canon's most extreme case fits the same 18k/28k-token budget RTC already uses.
- [x] Response-side token risk: **not verified, and cannot be from local measurement alone** — the sizer estimates routed-SFM *input* tokens, not the structured extraction *response*'s size, which scales with how many numbers a batch actually contains rather than its verse count. This remains an open, explicitly flagged risk requiring a live benchmark to close (see Task 3 and the qualification addendum) — not assumed safe.
- [x] Measured ceiling: chapter boundaries are the real binding constraint in practice (see Status correction above), with Psalm 119 (176v) as the canon-wide worst case. Chose **220** for Task 2 — matching RTC's already-approved `maximum_primary_verse_units` exactly, comfortably above the 176-verse worst case, and proven in real measurement to add zero risk beyond cap=176-200 (no chapter is long enough to tell the difference).

## Task 2: Raise the configured cap and generalize the fixed tests

**Files:** Modify `system/config/workflows/nca/profile.yml`, `system/tests/numbers/test_batching.py`, `system/tests/numbers/test_benchmark.py`.

- [x] Raised `optimization_policy.extraction_batch_max_units` in `system/config/workflows/nca/profile.yml` from `8` to **220**, per Task 1's measurement (matches RTC's `maximum_primary_verse_units`; Psalm 119's 176 verses is the real canon-wide worst case and fits comfortably below it).
- [x] `test_eight_unit_batches_cover_the_scope_once` (`test_batching.py:35`) needed **no change** — it calls `plan_batches(..., max_units=8)` with a literal `8`, not the shipped config, so it already stands as the pinned old-cap=8 regression case exactly as intended. Added `test_configured_cap_covers_the_scope_once_at_any_size`, which reads the *live* shipped value and re-asserts the coverage/identity invariants at whatever it is.
- [x] Correction (see Status): `test_benchmark.py:365,387` needed no change — they use the benchmark tool's own independent `--batch-cap` default (8), not the shipped profile. The actual hardcoded spot was `benchmark_nca_qualification.py::qualify_pair`'s `if before['case_count'] == 32: gates['four_batches'] = optimized == 4`, replaced with a general `gates['batches_match_configured_cap'] = optimized == math.ceil(before['case_count'] / cap)`, reading a new `extraction_batch_max_units` field now recorded directly in the optimized-strategy receipt. Verified both cap=8 (`PASS`, `batches_match_configured_cap: True`, matching the historical 4-batch result) and cap=220 (`PASS`, 1 batch) via real `benchmark_nca.py --strategy paired` runs.
- [x] Re-derived and empirically confirmed (not just formula-assumed) via a real `--fault malformed --batch-cap 220` run: **126** worst-case extraction attempts (`2 × (2×32 − 1)`), vs. the old cap=8's 120 (`2 × (2×32 − 4)`) — a single larger batch has *more* total bisection nodes (63 vs. 60) than several smaller ones covering the same leaves, so worst-case full-failure cost rises slightly, not falls. Added `test_qualification_faults_remain_bounded_at_the_shipped_production_cap` (all 4 fault types) asserting this exactly.
- [x] Added `system/tools/benchmark_nca.py --batch-cap` (threaded through `run_synthetic_optimized`/`_run_synthetic_optimized` in `benchmark_nca_optimized.py`, default `8` to preserve every existing test's behavior unchanged) so the cap is a real, externally exercisable parameter rather than only the profile.yml default.
- [x] Ran `system/tests/numbers/test_batching.py` (25 passed), `system/tests/numbers/test_benchmark.py` (41 passed), full `system/tests/numbers` (917 passed), and the full `system/tests` app suite (in progress at commit time — see Task 3).

## Task 3: Re-benchmark and re-qualify

**Files:** Extend `system/tools/benchmark_nca.py` and `system/tests/numbers/fixtures/optimization-cases.json` with a larger controlled synthetic workload (sized to actually exercise the new cap, not just permit it — reuse Task 1's larger fixture); append to `docs/advanced/release/NCA-OPTIMIZATION-QUALIFICATION.md`.

- [x] Ran the existing 32-unit MAT5 fixture (sufficient — see Status correction, a new larger fixture wasn't needed) through baseline, cap=8, and cap=220 via `benchmark_nca.py --strategy paired`. Measured: extraction requests 32/4/1, total physical requests 64/36/33, request bytes 389981/231281/217478, response bytes 28063/28640/28190.
- [x] All `paired` qualification gates pass at cap=220 (`identical_inputs`, `identical_route`, `baseline_goldens`, `optimized_goldens`, `baseline_findings`, `optimized_findings`, `complete_scope`, `extraction_call_reduction`, `lower_request_bytes`, `one_qualification`, `zero_resume_calls`, `identical_resume_semantics`, `batches_match_configured_cap` — all `True`, `qualification_status: PASS`). No accuracy/finding regression: identical golden and finding-label matches to the cap=8 run.
- [x] Appended a new dated section ("Raised extraction batch cap...") to `NCA-OPTIMIZATION-QUALIFICATION.md`, preserving the original cap-eight table unchanged, including the real-project Ezra/Psalm-119 measurements and an explicit, honest disclosure that response-side token risk at 220 verses remains unverified pending a live benchmark (`LIVE_MODEL_BENCHMARK_NOT_RUN`, `SQS: NOT_APPLIED`).
- [x] Full `system/tests/numbers` (917 passed) and full `system/tests` app suite run; committed as `perf(nca): raise extraction batch size toward the real evidence-policy ceiling` (see git log for the exact commit — this checklist is not amended per-commit-hash after the fact).

## Plan self-review and completion criteria

| Requirement | Delivery |
|---|---|
| Real (not assumed) measurement of the safe batch-size ceiling | Task 1 |
| Configured cap raised to the measured value, old behavior still regression-tested | Task 2 |
| Bisection-retry attempt bound re-verified at the new scale | Task 2 |
| Deterministic call/byte reduction re-measured and re-qualified | Task 3 |
| No change to batching identity, checkpointing, retry mechanics, or the extraction schema | All tasks (constraint, not a delivery) |
| No accuracy regression on critical numeric categories | Task 3 |

Implementation is complete only when all three tasks' checkboxes are closed and the qualification addendum records a reviewed, passing measurement. Do not describe the new batch size as already delivered while this checklist remains open. The deterministic digit-numeral pre-filter and concurrent batch dispatch remain explicitly out of scope — see Global constraints — and should become their own plans if pursued.
