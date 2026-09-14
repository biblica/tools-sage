# NCA Efficiency and Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce NCA processing and model-call overhead while preserving full-scope numeric detection and improving supported bridged-verse accuracy.

**Architecture:** Build an expected-reference inventory and independently extract every eligible WIP stream in bounded batches. Reuse validated execution inputs and task-local phase checkpoints, then apply typed single-row/group comparison and deterministic reporting. Keep semantic adjudications independent and preserve old result contracts.

**Tech Stack:** Existing Python 3.10+ runtime, standard library, pytest, SAGE provider routing, SFM slicer, USJ/VRS projections, immutable Job/Run controls, exact Fraction-based numeric models, schemas, and localization. No new runtime dependency.

**Spec:** [NCA optimization design](../specs/2026-09-10-NCA-OPTIMIZATION-DESIGN.md). Also read the [initial NCA design](../specs/2026-09-09-NCA-DESIGN.md), [reference audit](../specs/2026-09-09-NCA-FINAL-REFERENCE-AUDIT.md), [qualification record](../../advanced/release/NCA-QUALIFICATION.md), and [model-handoff policy](../../advanced/models-and-ai/MODEL-HANDOFF-OPTIMIZATION.md).

**Status:** Tasks 1–8 are implemented and independently reviewed. Task 9 deterministic release gates pass for implementation `6001294dc2360ede1cdab445e5df8aedb64771da`; final independent review is PENDING. Live-model qualification remains `LIVE_MODEL_BENCHMARK_NOT_RUN`; SQS: NOT_APPLIED. See the [optimization qualification](../../advanced/release/NCA-OPTIMIZATION-QUALIFICATION.md).

## Global constraints

- Preserve Python 3.10 compatibility and the existing Linux/macOS/Windows CI matrix.
- Add no runtime dependency and no new general Job, provider, or confidence framework.
- Keep workflow `nca`, operation `numbers`, check `NUMBERS`, Main Menu NCA=5 and Maintenance=6.
- OL HEB/GRK remains Authority 1; NIV remains secondary; only registered whole readings and coordinate-specific unit pairs may be accepted.
- Keep a configured Number Style Profile mandatory even when presentation is OFF; retain the three independent check toggles and all-OFF rejection.
- Never write Scripture, Paratext Notes XML, reference packages, or historical sealed Run evidence.
- Keep WIP-local, Western, canonical, and stored nullable OL references distinct.
- Extract target numbers without supplying expected OL/NIV values, variant values, or expected-number flags to the extraction model.
- Do not treat an absent reference row as an authoritative zero-number row.
- Do not turn PARTIAL, UNSUPPORTED, invalid, missing, or oversized evidence into a pass.
- Preserve exact surfaces, offsets, rational values, kinds, qualifiers, units, referents, multiplicity, and provenance at every input/replay boundary.
- Use the existing routed-SFM sizing authority; never run the Scripture token estimator on prompts, JSON, profiles, schemas, IDs, hashes, or USJ projections.
- Keep independent semantic adjudications and note assessments separate; only target inventory extraction may share one bounded multi-unit review item.
- Keep the existing capability limitation and `SQS: NOT_APPLIED` in every report/export. Do not add a confidence cutoff or imply SQS qualification.
- Keep ordinary CI synthetic and provider-free. An actual model benchmark is a separately initiated run using existing authorized provider routing.

## Delivery order and file ownership

```text
1 baseline/measurement -> 2 execution-input reuse -> 3 scope/batch planning
3 -> 4 batch extraction -> 5 checkpoint storage -> 6 governed hybrid execution
6 -> 7 bridge accuracy -> 8 reports/preflight -> 9 qualification
```

Each task includes tests, review, and a bounded commit. Do not modify a shared file concurrently; model/schema/result changes are sequential. During execution use an isolated checkout/worktree when needed, preserve user changes, and keep generated resources/receipts outside Core. Paths below are relative to `app/`; commands run from `app/` with the qualification interpreter. In task file lists, `numbers/` abbreviates `system/src/sage/numbers/`, bare source module names abbreviate `system/src/sage/`, and NCA test filenames abbreviate `system/tests/numbers/`. Shared tests use explicit `system/tests/` paths. Schema ownership lives in `system/src/sage/schema_validation.py`; Skill registration/evaluation inventories live in `system/config/skills.json`, `system/config/skill-evaluation-contracts.json`, and `system/evaluations/model-routing-alpha1/nca-numbers/`.

| File | Responsibility |
|---|---|
| `system/src/sage/numbers/telemetry.py` | Count attempts, usage, timings, reuse and local qualification separately from semantic decisions. |
| `system/src/sage/numbers/execution.py` | Construct immutable validated execution inputs and a prepared scope inventory. |
| `system/src/sage/numbers/transport.py` | Bind exact routed SFM to existing body/note/heading projections. |
| `system/src/sage/numbers/batching.py` | Deterministic protected-unit batching, identities, and bounded splitting. |
| `system/src/sage/numbers/replay.py` | Task-local attempt artifacts, validated checkpoints and publication manifests. |
| `system/src/sage/numbers/groups.py` | Multi-row correspondence contracts, assignment validation and row-specific decisions. |
| `system/src/sage/numbers/models_v2.py` | Immutable parent-group, row-component and optimized Run result types. |
| `system/src/sage/numbers/results_v2.py` | Strict version-2.0 materialization/validation; shared dispatcher preserves version 1.0. |
| `system/src/sage/numbers/model_tasks.py`, `extraction.py`, `engine.py` | Existing routed phases, exact evidence validation, and orchestration. |
| `system/src/sage/nca.py`, `numbers/policy.py` | Existing task locks, immutable Run policy, execution, submit/finalize, and compatibility. |
| `system/src/sage/nca_reporting.py`, `nca_menu.py`, `nca_cli.py`, `human_output.py` | Existing operator/report surfaces and localization. |
| `system/tools/benchmark_nca.py` | Reproducible synthetic and explicitly initiated live comparisons. |

The names and signatures below are proposed interfaces to implement, not claims that they already exist. Keep existing public single-unit APIs available until their callers migrate in Task 6.

## Task 1: Reproducible baseline and measurement

**Files:** Create `numbers/telemetry.py`, `system/tools/benchmark_nca.py`, `system/tests/numbers/test_benchmark.py`, and `system/tests/numbers/fixtures/optimization-cases.json`. Extend `system/tests/numbers/conftest.py`. Update the vanilla manifest for new shipped paths.

**Interfaces:** `CallMeasurement` is a frozen dataclass with `request_id: str`, `phase: str`, `unit_ids: tuple[str, ...]`, `elapsed_ms: int`, `request_bytes: int`, `response_bytes: int`, `input_tokens: int | None`, `output_tokens: int | None`, `status: str`, and `reused: bool`. `summarize_calls(calls: tuple[CallMeasurement, ...]) -> dict[str, object]` deduplicates request IDs, rejects inconsistent duplicate measurements, and excludes reused receipts from newly executed call/usage totals. Integers use nonnegative exact counts; unavailable usage is null.

- [x] Add fixtures for ordinary numeric and number-free verses, indexed omission, unindexed numeric content, registered absence, mixed word/digit forms, Unicode digits, repeated values, ratios/fractions/ordinals, and three bridge shapes. Keep source fixtures synthetic or limited authorized acceptance values. Record case IDs, language, exact input streams, expected expressions/outcomes/uncertainty, and whether the expected bridge result is new behavior.
- [x] Add a reusable `make_units(count)` test fixture using real MAT 5:1–32 coordinates:

```python
def make_units(count: int) -> tuple[TargetUnit, ...]:
    """Build small target units for deterministic batch tests."""
    assert 1 <= count <= 32
    return tuple(
        TargetUnit(f"MAT 5:{v}", (VerseRef("MAT", 5, v),),
                   "Three men.", (), "0" * 64,
                   {"line_start": v, "line_end": v})
        for v in range(1, count + 1)
    )
```

- [x] Write the first measurement test, then run it to witness failure:

```python
def test_reused_batch_receipt_is_not_another_provider_call():
    """Member count and reuse must not inflate usage."""
    call = CallMeasurement("r1", "EXTRACTION", ("a", "b"), 10,
                           100, 50, None, None, "VALIDATED", False)
    result = summarize_calls((call, replace(call, reused=True)))
    assert result["provider_calls"] == 1
    assert result["input_tokens"] is None
```

- [x] Implement aggregation keyed by request ID; preserve attempt failures and reuse events separately. Benchmark wrappers observe the existing execution APIs without weakening version-1.0 receipt validation. Measure actual reference-load/profile-validation counts rather than assuming them from call sites.
- [x] Implement `benchmark_nca.py --mode synthetic --strategy baseline --cases PATH --receipt PATH`. Default to synthetic mode and reject unknown strategies. The later optimized strategy is added in Task 6; live mode is added only in Task 9. Include input/fixture/code hashes, environment, phase counts, transport/usage fields, local-load timing, and semantic outcome diffs in the receipt.
- [x] Run `python -m pytest -q system/tests/numbers/test_benchmark.py`, run the synthetic baseline command, inspect the receipt, review, and commit `test(nca): establish optimization baseline`.

## Task 2: One validated execution context

**Files:** Create `numbers/execution.py` and `system/tests/numbers/test_execution_context.py`. Modify `nca.py`, `numbers/engine.py`, and `system/tests/numbers/test_nca_tasks.py`.

**Interfaces:** `ExecutionInputs` is an internal frozen dataclass containing `bundle: ReferenceBundle`, `style_profile: Mapping[str, object]`, `policy: Mapping[str, object]`, `projected_units: tuple[ProjectedUnit, ...]`, `style_units: tuple[TargetUnit, ...]`, `expected_unit_ids: tuple[str, ...]`, and `expected_references: tuple[VerseRef, ...]`. `prepare_execution_inputs(config, job, run, policy) -> ExecutionInputs` owns validation and freezing. The internal prepared evaluator consumes this type; the existing public `evaluate_unit` continues validating arbitrary inputs.

- [x] Add a test wrapping the actual bundle loader and style validator during canonical task execution. Assert one qualification/load and one style validation for many units, then mutate a package/profile before a fresh attempt and assert rejection before provider execution. Also test that changed Job defaults do not replace sealed Run inputs.
- [x] Run `python -m pytest -q system/tests/numbers/test_execution_context.py` and witness the repeated-call assertion fail.
- [x] Refactor `_validate_task`, `_sealed_units`, and `_execute_nca_task_locked` to pass one validated bundle/context through the locked attempt. Remove duplicate loading only after all existing trust checks have a single explicit owner:

```python
inputs = prepare_execution_inputs(runtime_config, job, run, policy)
result = evaluate_prepared_run(inputs, model_tasks=recording, run_id=run.run_id)
```

  Define `evaluate_prepared_run(inputs: ExecutionInputs, *, model_tasks: object, run_id: str) -> RunResult` as the internal prepared path. No public validation bypass, cross-attempt package trust cache, or mutable profile shortcut is permitted.
- [x] Run context tests, `test_nca_tasks.py`, `test_nca_jobs.py`, `test_policy.py`, and `test_engine.py`; verify identical baseline outcomes and lower local invocation counts. Review and commit `perf(nca): reuse validated execution inputs`.

## Task 3: Explicit scope inventory and deterministic extraction batches

**Files:** Extend `numbers/execution.py`; create `numbers/transport.py`, `numbers/batching.py`, `test_batching.py`, `test_transport.py`; extend `test_scope.py`. Modify the NCA profile/policy in preparation for new Runs and clarify NCA extraction geometry in `docs/advanced/models-and-ai/MODEL-HANDOFF-OPTIMIZATION.md`.

**Interfaces:**

```python
@dataclass(frozen=True)
class StreamInput:
    input_id: str
    owner_unit_id: str
    stream_id: str
    purpose: str                 # BODY, NOTE_STYLE, or HEADING_STYLE
    target_references: tuple[VerseRef, ...]
    records: tuple[EvidenceRecord, ...]
    text: str
    routed_sfm: str
    source_sha256: str
    projection_sha256: str
    language: str
    conventions_sha256: str

@dataclass(frozen=True)
class ExtractionBatch:
    batch_id: str
    inputs: tuple[StreamInput, ...]
    routed_sfm: str
    contract_version: str

@dataclass(frozen=True)
class BatchPlan:
    batches: tuple[ExtractionBatch, ...]
    blocked: Mapping[str, str]   # input_id -> explicit planning limitation

def plan_batches(inputs: tuple[StreamInput, ...], *,
                 policy: EvidencePolicy, max_units: int = 8
                 ) -> BatchPlan:
    """Pack protected inputs with the existing routed-SFM planner."""

def split_batch(batch: ExtractionBatch) -> tuple[ExtractionBatch, ...]:
    """Bisect a failed multi-unit batch without splitting any input."""
```

`ScopeInventory` contains the full expected-coordinate ledger, protected projected groups, `expected_groups: frozenset[str]` (indexed and registered cases), and all eligible `StreamInput` records. `build_inventory(inputs: ExecutionInputs) -> ScopeInventory` reuses `project_scope`; it does not derive expected coverage from detected numbers.

- [x] Write tests proving all selected coordinates survive inventory construction, missing WIP remains explicit, index-only omissions are impossible, bridges/boundary groups are not split, and body/note/heading offsets remain in their own streams. Use `make_units(32)` from Task 1 and exact fixture SFM to construct 32 validated `StreamInput` values.
- [x] Add deterministic planner assertions:

```python
def test_eight_unit_batches_cover_the_scope_once(stream_inputs, evidence_policy):
    """Batching cannot lose or duplicate target streams."""
    plan = plan_batches(stream_inputs, policy=evidence_policy, max_units=8)
    batches = plan.batches
    assert len(batches) == 4
    assert not plan.blocked
    assert [x.input_id for b in batches for x in b.inputs] == [x.input_id for x in stream_inputs]
    assert plan == plan_batches(stream_inputs, policy=evidence_policy, max_units=8)
```

  Here `stream_inputs` is the 32-input MAT fixture and `evidence_policy` is the existing loaded NCA EvidencePolicy with enough hard capacity for eight small units. Add tests where that hard capacity is exceeded and a protected singleton cannot be split.
- [x] Run the new tests to witness failure. Implement the adapter using `SfmAnalysisRoute`, `SfmStream`, `EvidenceRecord`, and `plan_sfm_work_units`; retain the exact SFM sent in `ExtractionBatch.routed_sfm`. Bind body/note/heading projections to the same source slices. Never feed serialized JSON into the estimator. Return an unsplittable oversized input in `BatchPlan.blocked`; the union of planned and blocked input IDs must equal the inventory exactly once.
- [x] Add versioned optimization policy fields: `contract_version: nca-optimization-2.0`, `extraction_batch_max_units: 8`, `request_concurrency: 1`, `transient_retries: 1`, `reuse_scope: TASK`. Validate positive exact integers and preserve existing hard limits; derive the binary-split bound from batch membership. Seal the policy only for new optimized Runs in Task 6.
- [x] Run batching/transport/scope tests plus `system/tests/test_sfm_slicer.py` and `system/tests/test_verse_alignment.py`. Verify that projection/profile/schema bytes do not influence Scripture sizing. Review and commit `feat(nca): plan protected extraction batches`.

## Task 4: Target-only batch extraction and strict receipts

**Files:** Modify `numbers/extraction.py`, `numbers/model_tasks.py`, and `system/skills/nca-numbers/SKILL.md`; create `system/config/schemas/nca-extraction-v2.schema.yml`, `system/skills/nca-numbers/references/TARGET-EXTRACTION-CONTRACT.md`, `test_batch_extraction.py`; extend `test_model_tasks.py`, `test_extraction.py`, schema ownership, and sealed evaluation fixtures/hashes.

**Interfaces:** `BatchValidation` contains `accepted: Mapping[str, Extraction]`, `pending: Mapping[str, str]`, and `batch_id: str`. `validate_batch_extraction_response(batch: ExtractionBatch, response: Mapping[str, object]) -> BatchValidation` validates each known input independently. `NcaModelTasks.extract_batch(batch: ExtractionBatch, *, parsing_conventions: Mapping[str, object]) -> ModelPhaseResult[BatchValidation]` sends one target-only request and one receipt. It retains the existing single-unit API for legacy execution.

- [x] Add valid two-unit responses, out-of-order results, missing/duplicate/unknown IDs, invented surfaces, wrong stream/offset, overlapping expressions, contradictory/one-sided dual forms, duplicate note-local evidence, partial interpretation, and truncation tests. Ensure expected values and registry presence never enter the extraction payload or extraction capsule.
- [x] Witness failure with `python -m pytest -q system/tests/numbers/test_batch_extraction.py`. Implement a version-2.0 envelope with `batch_id`, `work_units`, and per-item `input_id`, `status`, `limitations`, and `expressions`. Keep the existing exact expression validator as the semantic boundary, parameterized by admitted stream text/identity.
- [x] Implement coverage reconciliation after parsing the top-level envelope:

```python
expected = {item.input_id for item in batch.inputs}
received = [item["input_id"] for item in response["work_units"]]
if len(received) != len(set(received)) or set(received) - expected:
    raise ValidationError("Invalid batch identities", code="NCA_BATCH_COVERAGE_INVALID")
# Validate known items independently; absent IDs remain pending, never empty COMPLETE.
```

- [x] Materialize controller identities and accepted-item hashes locally. Preserve one parent request/response receipt and bind each accepted input ID to it; do not clone its usage into each unit. Preserve PARTIAL/UNSUPPORTED status without automatic semantic retries.
- [x] Exercise the configured transient retry and `split_batch` path with recorded responses. Assert at most `2 * (2 * n - 1)` attempts, no route substitution, no resubmission of committed valid items, and explicit singleton failure.
- [x] Run batch/extraction/model/schema/routing tests and regenerate only affected NCA Skill/evaluation hashes with existing tools. Review and commit `feat(nca): validate batched target extraction`.

## Task 5: Verified same-task phase checkpoints

**Files:** Create `numbers/replay.py`, `test_replay.py`, and `system/config/schemas/nca-phase-ledger.schema.yml`; register schema ownership. Prepare controller-owned write declarations in `nca.py` without enabling optimized execution yet.

**Interfaces:** `PhaseKey` is a frozen canonical identity with `phase: str`, `task_fingerprint: str`, `input_ids: tuple[str, ...]`, `input_sha256: str`, `policy_sha256: str`, `route_sha256: str`, `contract_sha256: str`, and `validator_version: str`. Its input hash includes all applicable source/package/mapping/profile bytes and ordered stream identities; its contract hash includes schema, Skill/capsule and phase versions. `PhaseStore(task_root: Path, *, task_fingerprint: str)` exposes `lookup(key: PhaseKey, *, validate: Callable) -> object | None`, `commit(key: PhaseKey, artifact: Mapping[str, object], *, validate: Callable) -> str`, and `record_failure(key: PhaseKey, diagnostic: Mapping[str, object]) -> None`. `commit` returns the checkpoint ID only after validation and atomic ledger publication.

- [x] Write tests for interrupted execution after an accepted extraction, corrupted content, wrong route/profile/source hash, unsupported evidence, orphan attempt files, symlink/path escape, concurrent writers, and changed Job defaults with unchanged sealed inputs. Keep fixtures inside `tmp_path` and use the existing WorkspaceLock/atomic-write helpers.
- [x] Add the crucial identity test before implementation:

```python
def test_changed_phase_identity_cannot_reuse_evidence(phase_store, phase_key, artifact, validator):
    """A valid earlier response is not authority for different source inputs."""
    phase_store.commit(phase_key, artifact, validate=validator)
    assert phase_store.lookup(phase_key, validate=validator) is not None
    changed = replace(phase_key, input_sha256="f" * 64)
    assert phase_store.lookup(changed, validate=validator) is None
```

  Define `phase_key`, `artifact`, and `validator` fixtures in `test_replay.py` from the Task 4 two-unit batch response and its actual phase hashes; the validator must call `validate_batch_extraction_response`, not return an unvalidated dictionary.
- [x] Implement `validation/nca-phases/attempts/<attempt-id>.json` plus `validation/nca-phases/ledger.json` under the governed task root. Write attempt, validate, then atomically publish ledger membership. Validate exact keys, hashes, task ownership, and version before reuse. No cache outside the task; no modification of accepted artifacts.
- [x] Add a final-publication manifest binding the canonical output and execution receipt. Test recovery from one staged final file using valid checkpoints; never accept an arbitrary partial output. Document the crash window before a phase checkpoint and retain old-task behavior.
- [x] Run `test_replay.py`, `test_nca_tasks.py`, `system/tests/test_authority_boundaries.py`, and `system/tests/test_storage_layout.py`. Review and commit `feat(nca): checkpoint validated model phases`.

## Task 6: Governed hybrid execution and version-2.0 results

**Files:** Modify `numbers/engine.py`, `numbers/results.py`, `numbers/policy.py`, `nca.py`; create `numbers/models_v2.py`, `numbers/results_v2.py`, `system/config/schemas/numbers-result-v2.schema.yml`, `system/config/schemas/nca-check-policy-v2.schema.yml`, `test_hybrid_execution.py`, `test_results_v2.py`; extend canonical acceptance, policy, Job, and task tests.

**Interfaces:** `candidate_group_ids(inventory: ScopeInventory, extractions: Mapping[str, Extraction]) -> frozenset[str]` returns expected groups plus detected/unresolved owners. Add `evaluate_optimized_run(inputs: ExecutionInputs, *, model_tasks: object, phase_store: PhaseStore, run_id: str) -> OptimizedRunResult`; retain the Task 2 legacy `evaluate_prepared_run` return type. `numbers_result_document_v2(result: OptimizedRunResult, *, provenance: Mapping[str, object], check_policy: Mapping[str, object], model_receipts: Mapping[str, object]) -> dict[str, object]` and `validate_numbers_result_v2(document: Mapping[str, object], *, expected_unit_ids: tuple[str, ...], allowed_evidence_ids: tuple[str, ...]) -> dict[str, object]` own the new contract; the existing dispatcher chooses the strict version-specific validator.

Define frozen v2 types with these fields: `ComponentResult` holds `western_reference: VerseRef`, `ol_reference: str | None`, `owned_target_expression_ids: tuple[str, ...]`, `source_expressions: tuple[NumericExpression, ...]`, `reading: ReadingDecision`, `footnote: FootnoteDecision`, `final_outcome: str`, and `limitations: tuple[str, ...]`; `GroupResult` holds `projected: ProjectedUnit`, the single parent `extraction: Extraction`, `reference_rows: tuple[Mapping[str, object], ...]`, `components: tuple[ComponentResult, ...]`, `alignment_status: str`, `expression_ownership: Mapping[str, str]`, `unmatched_target_ids: tuple[str, ...]`, `unresolved_target_ids: tuple[str, ...]`, `style_findings: tuple[Mapping[str, object], ...]`, and `limitations: tuple[str, ...]`; `OptimizedRunResult` holds `groups: tuple[GroupResult, ...]`, `findings: tuple[Mapping[str, object], ...]`, `coverage: Mapping[str, object]`, `summary: Mapping[str, object]`, and `metrics: Mapping[str, object]`. Freeze nested mappings, validate enums and references, and keep parent extraction separate from per-row ownership to prevent double counting.

- [x] Test the union explicitly, with an existing empty target at an indexed row, numeric content outside the index, complete number-free unindexed text, registered OL absence, missing WIP, and unsupported extraction. Candidate detection uses BODY streams only; add negatives where a number appears solely in a note or editorial heading and cannot satisfy or create a body-number finding:

```python
def test_expected_and_unexpected_numeric_groups_both_reach_evaluation(inventory, extractions):
    """Only-target and only-index selection must not shrink coverage."""
    assert candidate_group_ids(inventory, extractions) == frozenset({"expected", "unexpected", "uncertain"})
```

  Define this test's inventory with four owners: indexed `expected`, unindexed `unexpected`, unindexed `uncertain`, and unindexed `empty`. Their extractions are respectively COMPLETE/empty, COMPLETE/one expression, UNSUPPORTED/empty with a limitation, and COMPLETE/empty. Keep all four owners in the final coverage ledger.
- [x] Witness failure, then connect context, inventory, batching, strict extraction, checkpoints, and the existing typed comparison. Pass already validated extractions into the internal prepared evaluator; do not invoke extraction again for accuracy or style. Preserve ordinary single-row correspondence calls and policy-specific note calls. Check-disabled paths publish NOT_ASSESSED and make no unnecessary calls.
- [x] Define version-2.0 output with externally bounded expected coverage, parent WIP groups, `reference_rows`, `components`, `alignment_status`, `expression_ownership`, phase receipt/checkpoint references, scope-expansion details, and derived metrics. Use one singleton component for ordinary resolved rows; unresolved bridges retain empty components and explicit alignment limitations until Task 7. For all versions, preserve exact source/target evidence and the capability statement.
- [x] Seal the version-2.0 policy and a phase-contract manifest binding all applicable schema/capsule/validator versions and hashes, plus the actual model route, in new Runs. Use schema IDs `sage-nca-extraction-2.0` and `sage-numbers-result-2.0`; preserve the old schema files and validators. New-Run EXTRACTION, CORRESPONDENCE and FOOTNOTE contracts use version 2.0. Admit GROUP_CORRESPONDENCE with task version `nca-group-correspondence-2.0` for Task 7. Extend `_RecordingModelTasks` and execution-receipt phase aggregation explicitly so group receipts cannot disappear from counts or hashes. Extend controller-only writes for checkpoints and final publication. Test completed version-1.0 report read/replay, rejection of stale in-flight legacy execution, and no rewriting or automatic conversion of old Runs.
- [x] Add `--strategy optimized` to the synthetic benchmark. Compare non-bridge golden outcomes and call/local-load counts against baseline. Run hybrid, v2 replay, canonical acceptance, policy/Job/task/authority tests. Review and commit `feat(nca): execute complete scope through hybrid analysis`.

## Task 7: Typed bridge comparison with row-specific authority

**Files:** Create `numbers/groups.py`, `test_groups.py`; modify `numbers/model_tasks.py`, `numbers/engine.py`, `numbers/models_v2.py`, `numbers/results_v2.py`, v2 schemas, and bridge/variant/unit/footnote tests and evaluation fixtures.

**Interfaces:** `ReferenceGroup` contains the protected `ProjectedUnit`, ordered resolved/absent/unindexed row ledger, and exact source streams. `GroupCorrespondence` contains per-row validated `CorrespondenceEvidence`, target-role evidence, `assignments: Mapping[str, tuple[str, ...]]` keyed by Western row label, explicit unmatched target IDs, unresolved IDs, and limitations. `correspond_group(unit, extraction, reference_group) -> ModelPhaseResult[GroupCorrespondence]` is one group adjudication. `evaluate_group(reference_group, extraction, correspondence, *, bundle, checks) -> tuple[ComponentResult, ...]` produces attributed row decisions for the Task 6 v2 parent group; it does not duplicate the target extraction.

- [x] Test an ordinary two-row bridge with clear referents, one missing quantity, extra target numbers, repeated identical quantities, swapped roles, ranges/ratios, and one ambiguous allocation. Use the existing `reference_bundle`/typed expression helpers where applicable; add exact source spans for every row rather than deriving types from flat OL_VALUES.
- [x] Add mutation tests proving a target expression cannot be consumed twice:

```python
def test_two_reference_rows_cannot_consume_one_target_expression(group, extraction, response):
    """A bridge must retain multiplicity and one owner per target expression."""
    response["assignments"] = {"MAT 5:1": ["t1"], "MAT 5:2": ["t1"]}
    with pytest.raises(ValidationError, match="ownership"):
        validate_group_correspondence(group, extraction, response)
```

  Define `validate_group_correspondence(group: ReferenceGroup, extraction: Extraction, response: Mapping[str, object]) -> GroupCorrespondence` in `groups.py`. This fixture has two exact OL expressions with value 3 and only one target expression `t1`; all non-ownership evidence is otherwise valid.
- [x] Run the new tests and witness failure. Implement row-keyed source validation, exact target role/assignment evidence, complete/unmatched/unresolved accounting, and per-row calls to existing semantic/variant/unit policies. Do not concatenate rows into one fake ReferenceRow or accept pooled value equality.
- [x] Add bridge cases containing a registered alternate, a coordinate-specific conversion with unrelated residual quantities, and NEH 7:68. Test that neighboring policies cannot authorize an assignment, an unindexed row cannot become zero-valued, and ambiguous note attribution cannot fulfill disclosure. Retain PSA 60:0, 1SA 20:42 and 1CH 12:4 mapping/source attribution tests.
- [x] Enforce the same group constraints in typed models and v2 serialized/replayed results: nullable sources, exact source sequences, partial subsequences, complete dual forms, per-note uniqueness, one expression owner, and per-row provenance. An unresolved component prevents overall all-clear when its assessment is required by an enabled check. Presentation-only execution sets alignment NOT_ASSESSED, permits an empty numeric-ownership map, and makes no correspondence call. Validate alignment states NOT_ASSESSED, COMPLETE, PARTIAL and UNAVAILABLE explicitly; counters distinguish parent groups from reference coordinates.
- [x] Run group, v2 result, engine, projection/scope, variants/units/footnotes, and canonical acceptance tests. Review and commit `feat(nca): compare bridged verses with attributed reference rows`.

## Task 8: Chapter-organized reports and transparent preflight

**Files:** Modify `nca_reporting.py`, `nca_menu.py`, `nca_cli.py`, `human_output.py`, `test_reporting.py`, `test_nca_menu.py`, `test_nca_cli.py`, `test_acceptance.py`, `docs/NCA-CHEAT-SHEET.md`.

**Interfaces:** Keep existing report entry points. Add `chapter_sections(document) -> tuple[Mapping[str, object], ...]` to reporting; it returns ordered WIP book/chapter sections with canonical group/finding IDs and cross-references. Input/output identity remains controller-derived.

- [x] Test one Run covering multiple chapters, a protected group crossing a chapter boundary, an unaligned bridge finding, mixed indexed/unindexed coverage, and secondary-language output. Assert each canonical finding is counted once and linked to its WIP range.
- [x] Add the report acceptance assertion:

```python
def test_chapter_sections_do_not_duplicate_cross_boundary_findings(document):
    """Navigation copies cannot create additional canonical findings."""
    sections = chapter_sections(document)
    primary_ids = [item for section in sections for item in section["finding_ids"]]
    assert len(primary_ids) == len(set(primary_ids))
    assert set(primary_ids) == {item["finding_id"] for item in document["findings"]}
```

- [x] Witness failure, then render book/chapter sections, exact bridge ranges, supported per-row evidence and explicit uncertainty. Preserve the full handover counters and add planned/executed/reused call metrics, extraction coverage, and scope expansion. Localize new human labels through all existing report locales; keep codes/identities canonical.
- [x] Show reference expectations, protected groups, estimated extraction batches, mandatory profile, enabled checks, and capability/coverage limitations in preflight. Estimates are planning information, not measured time/cost or model qualification. Keep one report per Run and current menu/CLI grammar.
- [x] Run report/menu/CLI/localization/acceptance/documentation tests, review, and commit `feat(nca): explain optimized coverage by chapter`.

## Task 9: Differential accuracy and efficiency qualification

**Files:** Extend `benchmark_nca.py`, optimization fixtures and `test_benchmark.py`; add `docs/advanced/release/NCA-OPTIMIZATION-QUALIFICATION.md` and a synthetic benchmark receipt. Update the vanilla manifest, affected schema/Skill inventories, and completed plan status only after gates pass. Preserve the original NCA qualification record.

- [x] Run the controlled MAT 5:1–32 workload with identical source/profile/check fixtures and provider/model/reasoning selection. Record baseline and optimized contract/route fingerprints separately; each must pass its own governance checks. Record call counts, total transport bytes, local-load counts, failures/retries, normalized semantic diffs and scope completeness. Require four extraction requests when all eight-unit batches fit, at least 50% fewer extraction calls for this workload, lower aggregate request bytes, one bundle/style validation per attempt, and zero repeat calls for valid checkpoints.
- [x] Add failure/cold-start/resume workloads. Assert the attempt bound and that fault recovery does not worsen coverage or manufacture pass states. Do not use noisy wall-clock thresholds in CI; record measured timings and compare model-call/byte counts deterministically.
- [x] Run all original numeric acceptance examples, all 21 registered-reading rows/42 choices, all 12 unit pairs, and new bridge positives/negatives. Require unchanged non-bridge golden behavior, correct new labelled bridge resolutions, zero new false all-clear, and no reference/source mutations. Compare typed extraction and findings against labels, not just baseline outputs.
- [x] Add an explicit `--mode live` benchmark requiring a selected existing WIP Project/scope, compatible style profile, current route, operator-reviewed labels, and output receipt path under authorized runtime storage. Use existing provider readiness/authentication; never introduce API-key routing or run live mode from CI. Keep source payloads local and record hashes in shareable receipts. A live run is separately initiated, not implied by executing this implementation plan.
- [x] For a separately initiated live comparison, keep route/model/reasoning and inputs fixed, use at least three paired repetitions, and report per-case extraction recall/precision, exact values/types/roles, finding correctness, unresolved rate, timings and available usage. No accuracy regression is acceptable on critical omission, extra-number, referent, and bridge cases. If evidence is unavailable, state `LIVE_MODEL_BENCHMARK_NOT_RUN` and make no model/language speed or accuracy qualification claim.
- [x] Run the clean-source release commands:

```sh
python -m pytest -p no:cacheprovider system/tests/numbers
python system/tools/validate_schemas.py
python system/tools/validate_package.py
python -m pytest -p no:cacheprovider system/tests
python system/tools/deep_audit.py . --mode source
python system/tools/validate_numbers_reference.py --package "$NCA_REFERENCE_DIR" --release --receipt "$NCA_RECEIPT_PATH"
```

  `NCA_REFERENCE_DIR` is the unchanged authorized package directory supplied for qualification; `NCA_RECEIPT_PATH` is outside that package and Core. Missing real evidence must fail the reference release gate, not silently substitute synthetic qualification. Verify the CI matrix and exact final source inventory. Preserve existing ignored workspace artifacts by using a clean staged source copy.
- [ ] Record exact commit/input hashes, environment, fixture outcomes, calls/bytes/load counts, timings, review verdict, capability limits and live-benchmark status. Review the final diff and version-1.0 compatibility evidence, commit `test(nca): qualify optimized execution`, and keep external integration separate from local implementation.

## Plan self-review and completion criteria

| Requirement | Delivery |
|---|---|
| Expected plus unexpected numeric coverage, including complete omissions | Tasks 3, 6, 9 |
| Exact target-only batched extraction, shared sizing and protected groups | Tasks 3, 4 |
| One qualified reference/profile per execution attempt | Tasks 1, 2, 9 |
| Bounded failure recovery and same-task replay without forged receipts | Tasks 4–6 |
| Typed bridge accuracy and row-specific reading/unit/disclosure policy | Tasks 7, 9 |
| Versioned typed/serialized evidence, immutable historical Runs | Tasks 4–7 |
| Book/chapter navigation without duplicated findings/counters | Task 8 |
| Measured efficiency, labelled accuracy, and explicit live/SQS limits | Tasks 1, 9 |
| Current menus, toggles, style requirements and other workflows | Tasks 6, 8, 9 |

Implementation is complete only when all nine deliveries and deterministic release gates pass and review finds no unresolved blockers. Live-model/language qualification is a separate reported state. Do not describe planned batching speedups or bridge outcomes as already delivered while this checklist remains open.
