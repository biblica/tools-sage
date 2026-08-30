# SAW Review Portions and OL Referral Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give SAW a stable review-range/portion/check progress hierarchy and admit selective OL referrals only through the approved structured, fail-closed fundamental-conflict contract.

**Architecture:** Add one focused referral-contract module for constants, field normalization, and deterministic conflict keys. Version new RTC composite plans, conditionally extend their provider schema/prompt and validator, carry admitted referral provenance into isolated OL tasks and aggregates, and annotate stage plans with controller-derived parent review-portion metadata for the Operator UI. Sealed pre-contract tasks remain legacy-readable.

**Tech Stack:** Python 3.12, PyYAML configuration, JSON task manifests/results, pytest, SAGE text UI.

**Spec:** `app/docs/advanced/release/SAW-REVIEW-PORTIONS-AND-OL-REFERRAL-DESIGN.md`

**Status:** Completed, regression-verified, and pushed on `alpha/0.02alpha1`. Verification recorded 882 passed, 2 established skips, a clean 620-file source audit, and 3,042/3,042 documented Python procedures.

## Global Constraints

- New RTC plans declare `ol_referral_contract: SAW_OL_REFERRAL_ADMISSION_V1`.
- Existing sealed tasks without that field retain their original output contract.
- Allowed classes are exactly `NEGATION_OR_POLARITY_CONFLICT`, `PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT`, `CORE_EVENT_OR_STATE_CONFLICT`, and `CORE_PROPOSITION_OMISSION_OR_ADDITION`.
- The strict gate adds no second referral-triage model call and no numeric referral cap.
- One admitted referral still creates one isolated selective OL task.
- `parse_scope()` remains the contiguous Run-range parser; `parse_scope_set()` remains citation-only.
- Existing machine identifiers such as `work_unit_id`, `ol_review_requests`, and `SELECTIVE_OL_ADJUDICATION` remain stable.
- Python performs deterministic validation and routing; the qualified RTC provider performs the multilingual semantic classification.
- No change is merged into `main`; implementation remains on `alpha/0.02alpha1`.

---

### Task 1: Referral admission primitives

**Files:**
- Create: `app/system/src/sage/ol_referrals.py`
- Create: `app/system/tests/test_ol_referrals.py`

**Interfaces:**
- Produces: `OL_REFERRAL_CONTRACT_V1: str`
- Produces: `OL_REFERRAL_CONFLICT_CLASSES: frozenset[str]`
- Produces: `normalize_referral_admission(request: Mapping[str, Any], *, index: int) -> dict[str, str]`
- Produces: `referral_conflict_key(*, target_reference: str, conflict_class: str, wip_proposition: str, reference_proposition: str) -> str`

- [x] **Step 1: Write failing primitive tests**

```python
def test_normalize_referral_admission_accepts_closed_contract() -> None:
    result = normalize_referral_admission({
        "conflict_class": "NEGATION_OR_POLARITY_CONFLICT",
        "wip_proposition": "The subject did not leave.",
        "reference_proposition": "The subject left.",
        "fundamental_impact": "The event polarity is reversed.",
        "source_dependency": "UNRESOLVED_REQUIRES_ORIGINAL_LANGUAGE",
    }, index=1)
    assert result["conflict_class"] == "NEGATION_OR_POLARITY_CONFLICT"


def test_referral_conflict_key_normalizes_case_and_whitespace() -> None:
    first = referral_conflict_key(
        target_reference="JHN 1:1",
        conflict_class="NEGATION_OR_POLARITY_CONFLICT",
        wip_proposition="  He DID not leave. ",
        reference_proposition="He left.",
    )
    second = referral_conflict_key(
        target_reference="JHN 1:1",
        conflict_class="NEGATION_OR_POLARITY_CONFLICT",
        wip_proposition="he did not leave.",
        reference_proposition="he left.",
    )
    assert first == second
```

- [x] **Step 2: Run the primitive tests and confirm RED**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_ol_referrals.py`

Expected: collection fails because `sage.ol_referrals` does not exist.

- [x] **Step 3: Implement the focused contract module**

```python
OL_REFERRAL_CONTRACT_V1 = "SAW_OL_REFERRAL_ADMISSION_V1"
OL_REFERRAL_CONFLICT_CLASSES = frozenset({
    "NEGATION_OR_POLARITY_CONFLICT",
    "PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT",
    "CORE_EVENT_OR_STATE_CONFLICT",
    "CORE_PROPOSITION_OMISSION_OR_ADDITION",
})


def referral_conflict_key(*, target_reference: str, conflict_class: str,
                          wip_proposition: str, reference_proposition: str) -> str:
    payload = {
        "target_reference": target_reference.strip().upper(),
        "conflict_class": conflict_class.strip().upper(),
        "wip_proposition": " ".join(wip_proposition.casefold().split()),
        "reference_proposition": " ".join(reference_proposition.casefold().split()),
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
```

`normalize_referral_admission()` raises the exact `SAW_OL_REFERRAL_FIELDS_MISSING`, `SAW_OL_REFERRAL_CLASS_INVALID`, or `SAW_OL_REFERRAL_ADMISSION_INVALID` `ValidationError` code and returns the five normalized fields.

- [x] **Step 4: Run primitive tests and confirm GREEN**

Run the Step 2 command.

Expected: all `test_ol_referrals.py` tests pass.

- [x] **Step 5: Commit the primitive boundary**

```bash
git add app/system/src/sage/ol_referrals.py app/system/tests/test_ol_referrals.py
git commit -m "feat: define strict SAW OL referral contract"
```

### Task 2: Provider schema, prompt, and fail-closed validation

**Files:**
- Modify: `app/system/src/sage/llm_tasks.py`
- Modify: `app/system/src/sage/act_tasks.py`
- Modify: `app/system/src/sage/act_outputs.py`
- Modify: `app/system/tests/test_llm_harness.py`
- Modify: `app/system/tests/test_storage_rtc_boundaries.py`

**Interfaces:**
- Consumes: `OL_REFERRAL_CONTRACT_V1`, `OL_REFERRAL_CONFLICT_CLASSES`, `normalize_referral_admission()`, `referral_conflict_key()`
- Changes: `validate_saw_findings(..., ol_referral_contract: str | None = None) -> dict[str, Any]`
- Produces: normalized request fields plus controller-derived `conflict_key`

- [x] **Step 1: Write failing strict-schema and validation tests**

Add tests that assert a V1 meaning-task schema requires the five admission fields, a legacy manifest does not, each allowed conflict class passes, and missing/unsupported/equal-proposition/duplicate requests fail with their specific reason codes.

```python
with pytest.raises(ValidationError) as caught:
    validate_saw_findings(
        output_path,
        task_id=manifest["task_id"],
        operation="rtc",
        rtc_stage="REFERENCE_TEXT_COMPARISON",
        scope_value=manifest["scope"],
        expected_references=manifest["expected_references"],
        allowed_evidence_ids=manifest["allowed_evidence_ids"],
        ol_referral_contract="SAW_OL_REFERRAL_ADMISSION_V1",
    )
assert caught.value.code == "SAW_OL_REFERRAL_FIELDS_MISSING"
```

- [x] **Step 2: Run the focused tests and confirm RED**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_llm_harness.py tests/test_storage_rtc_boundaries.py`

Expected: new assertions fail because the manifest schema and validator do not know the V1 contract.

- [x] **Step 3: Extend the conditional provider schema**

In `_saw_findings_file_schema(manifest)`, require and describe these properties only when `manifest["ol_referral_contract"] == OL_REFERRAL_CONTRACT_V1`:

```python
"conflict_class": {"type": "string", "enum": sorted(OL_REFERRAL_CONFLICT_CLASSES)},
"wip_proposition": _narrative_field_schema(narrative_tag, "State the WIP proposition."),
"reference_proposition": _narrative_field_schema(narrative_tag, "State the REFERENCE proposition."),
"fundamental_impact": _narrative_field_schema(narrative_tag, "Explain the core semantic change."),
"source_dependency": {"type": "string", "enum": ["UNRESOLVED_REQUIRES_ORIGINAL_LANGUAGE"]},
```

- [x] **Step 4: Replace broad referral prompt language with the closed admission contract**

For V1 tasks, state that a request may be emitted if and only if all seven admission rules pass, list the four closed classes, and explicitly prohibit intensity/nuance, equivalent paraphrase, grammar, style, readability, spelling, punctuation, USFM, and resolvable RTC issues. Legacy ACT files remain unchanged because they are sealed artifacts.

- [x] **Step 5: Enforce admission in `validate_saw_findings()`**

Pass `ol_referral_contract` from `submit_act_task()`. For V1 meaning-stage requests, normalize the five new fields, derive `conflict_key`, reject duplicate keys with `SAW_OL_REFERRAL_DUPLICATE`, retain existing scope/evidence/identity/overlap checks, and preserve every normalized field in `ol_review_requests`.

- [x] **Step 6: Run focused tests and confirm GREEN**

Run the Step 2 command.

Expected: strict and legacy schema/validation tests pass.

- [x] **Step 7: Commit the strict runtime gate**

```bash
git add app/system/src/sage/llm_tasks.py app/system/src/sage/act_tasks.py app/system/src/sage/act_outputs.py app/system/tests/test_llm_harness.py app/system/tests/test_storage_rtc_boundaries.py
git commit -m "feat: enforce SAW OL referral admission"
```

### Task 3: Contract versioning, inheritance, and sealed legacy behavior

**Files:**
- Modify: `app/system/src/sage/act_tasks.py`
- Modify: `app/system/src/sage/plan_continuation.py`
- Modify: `app/system/src/sage/findings.py`
- Modify: `app/system/tests/test_storage_rtc_boundaries.py`

**Interfaces:**
- Produces: `ol_referral_contract` on new RTC composite plans and their meaning/selective task manifests
- Preserves: absent field as the immutable legacy contract
- Preserves: `conflict_key` and admission fields through ID globalization and aggregate ledgers

- [x] **Step 1: Write failing versioning and inheritance tests**

Test that a newly created composite plan declares V1, every generated meaning task inherits V1, selective requests retain all admission fields and `conflict_key`, and a copied legacy task without the field still validates its legacy response.

- [x] **Step 2: Run the RTC boundary tests and confirm RED**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_storage_rtc_boundaries.py`

- [x] **Step 3: Seal V1 at new composite creation**

Set `ol_referral_contract` on `_create_saw_rtc_composite()` plans and pass it explicitly through `create_act_task()`, `_create_approved_saw_rtc_stage()`, `_partition_act_request()`, `_partition_selective_ol_cases()`, and continuation-created stages. Include the field in task identity/fingerprints.

- [x] **Step 4: Preserve admission provenance across aggregation**

Ensure `globalize_ol_review_request_ids()` copies all new fields unchanged while rewriting only request/deferred IDs. Preserve V1 and the normalized request ledger in partition aggregates and the final composite document.

- [x] **Step 5: Keep legacy tasks readable**

Only activate strict schema/prompt/validation when the sealed manifest declares V1. An absent contract field follows the existing validator path; no existing manifest, ACT, fingerprint, or output schema is rewritten.

- [x] **Step 6: Run RTC boundary tests and confirm GREEN**

Run the Step 2 command.

- [x] **Step 7: Commit contract propagation**

```bash
git add app/system/src/sage/act_tasks.py app/system/src/sage/plan_continuation.py app/system/src/sage/findings.py app/system/tests/test_storage_rtc_boundaries.py
git commit -m "feat: propagate SAW OL referral provenance"
```

### Task 4: Stable review-portion and stage-check progress

**Files:**
- Modify: `app/system/src/sage/act_tasks.py`
- Modify: `app/system/src/sage/plan_continuation.py`
- Modify: `app/system/src/sage/menu.py`
- Modify: `app/system/tests/test_operator_ux.py`
- Modify: `app/system/tests/test_storage_rtc_boundaries.py`

**Interfaces:**
- Produces on approved units: `review_portion_id`, `review_portion_index`, `review_portion_total`
- Produces on stage cases: `parent_review_portion_id`, `stage_case_index`, `stage_case_total`
- Produces: `SAW_STAGE_CASE_PORTION_MISMATCH` when a case crosses approved portions
- Removes default Operator wording: `Working on SAW work unit n/m`

- [x] **Step 1: Write failing planner and UI tests**

Create a 19-portion fixture with several stage cases and assert the Operator output contains a stable review portion denominator and local source-check denominator:

```python
assert "Review range:     JHN 1:1-21:25" in rendered
assert "Review portion:   4/19" in rendered
assert "Source check:     2/5" in rendered
assert "work unit 20/97" not in rendered.casefold()
```

Also test that a stage case spanning two approved portion inventories raises `SAW_STAGE_CASE_PORTION_MISMATCH` before execution.

- [x] **Step 2: Run progress tests and confirm RED**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_operator_ux.py tests/test_storage_rtc_boundaries.py`

- [x] **Step 3: Annotate immutable review portions**

When `_approved_saw_rtc_work_plan()` validates its ordered units, return controller-owned `review_portion_id`, `review_portion_index`, and `review_portion_total`. Use atomic coverage to map every structural or source case to exactly one portion.

- [x] **Step 4: Annotate local stage cases**

Carry parent metadata into partition plan entries. Group cases by `parent_review_portion_id` and assign one-based `stage_case_index`/`stage_case_total` within that parent. Propagate these fields through `_continue_partitioned_plan()` and `_composite_stage_result()`.

- [x] **Step 5: Render nested progress**

The SAW header prints `Review range`. Meaning-stage progress prints `Review portion`. Structural/selective progress prints the parent portion followed by `Structural check` or `Source check`; the internal `work_unit_id` remains diagnostics-only.

- [x] **Step 6: Run progress tests and confirm GREEN**

Run the Step 2 command.

- [x] **Step 7: Commit stable progress semantics**

```bash
git add app/system/src/sage/act_tasks.py app/system/src/sage/plan_continuation.py app/system/src/sage/menu.py app/system/tests/test_operator_ux.py app/system/tests/test_storage_rtc_boundaries.py
git commit -m "feat: separate SAW portions from source checks"
```

### Task 5: Qualification fixtures and operator documentation

**Files:**
- Modify: `app/system/evaluations/model-routing-alpha1/saw-rtc/false-ol-referral/*`
- Create: `app/system/evaluations/model-routing-alpha1/saw-rtc/fundamental-polarity/*`
- Create: `app/system/evaluations/model-routing-alpha1/saw-rtc/participant-identity/*`
- Modify: `app/system/config/workflows/saw/README.md`
- Modify: `app/system/config/workflows/saw/profile.yml`
- Modify: `app/docs/SAW-CHEAT-SHEET.md`
- Modify: `app/docs/advanced/workflows/SAW-CHECK-POLICY.md`
- Modify: `app/docs/advanced/workflows/SAW-OPERATOR-MODES.md`
- Modify: `app/docs/advanced/workflows/FULL-PROCESS-FLOW.md`
- Modify: `app/docs/advanced/release/RELEASE-NOTES.md`
- Modify: `app/docs/advanced/release/VANILLA-INSTALL-MANIFEST.md`
- Test: `app/system/tests/test_model_evaluation.py`
- Test: `app/system/tests/test_documentation_contracts.py`

**Interfaces:**
- Produces qualification cases for valid fundamental polarity, different participant identity without reversal, lexical intensity false referral, active/passive equivalence, and ordinary grammar/style differences
- Produces Operator documentation matching the V1 runtime contract and progress vocabulary

- [x] **Step 1: Write failing qualification/package assertions**

Assert the `saw-rtc` case inventory includes the new case IDs, each manifest keeps `maximum_review_items_per_request: 1`, and the vanilla package manifest matches the clean tree.

- [x] **Step 2: Run qualification/documentation tests and confirm RED**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_model_evaluation.py tests/test_documentation_contracts.py`

- [x] **Step 3: Add and rehash qualification fixtures**

Create exact single-item ACT/input/expected/manifest sets. Recompute `input_sha256` and `expected_sha256` from the final files using the repository's existing qualification fixture tooling or `shasum -a 256` verification; do not hand-copy stale hashes.

- [x] **Step 4: Update current documentation and profile rules**

Replace “every material variance” with the seven-rule admission contract, four closed classes, non-referral list, V1 contract name, stable review-range/portion/check vocabulary, and one-case selective execution.

- [x] **Step 5: Run qualification/documentation tests and confirm GREEN**

Run the Step 2 command.

- [x] **Step 6: Commit fixtures and documentation**

```bash
git add app/system/evaluations/model-routing-alpha1/saw-rtc app/system/config/workflows/saw app/docs app/system/tests/test_model_evaluation.py app/system/tests/test_documentation_contracts.py
git commit -m "test: harden SAW OL referral qualification"
```

### Task 6: Full verification, release checkpoint, and Alpha push

**Files:**
- Modify: `app/docs/advanced/release/IMPLEMENTATION-REPORT.md`
- Modify: `app/docs/advanced/release/HANDOVER.md`
- Modify: `app/docs/advanced/release/SAW-REVIEW-PORTIONS-AND-OL-REFERRAL-DESIGN.md`
- Modify: `app/docs/advanced/release/SAW-REVIEW-PORTIONS-AND-OL-REFERRAL-IMPLEMENTATION-PLAN.md`

**Interfaces:**
- Produces: a verified local Alpha commit series and pushed `origin/alpha/0.02alpha1`

- [x] **Step 1: Run the combined focused suite**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_ol_referrals.py tests/test_llm_harness.py tests/test_storage_rtc_boundaries.py tests/test_operator_ux.py tests/test_model_evaluation.py tests/test_documentation_contracts.py`

Expected: all focused tests pass.

- [x] **Step 2: Run the complete suite**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider`

Expected: all tests pass, with only established skips.

- [x] **Step 3: Update implementation status documents**

Record the implemented contract, exact test totals, legacy compatibility, and Operator-visible terminology. Mark completed plan checkboxes only after their evidence exists.

- [x] **Step 4: Verify the release diff**

Run: `git diff --check && git status --short --branch && git log --oneline --decorate origin/alpha/0.02alpha1..HEAD`

Expected: no whitespace errors, only intended Alpha commits, and no untracked runtime/test artifacts.

- [x] **Step 5: Commit the verified release checkpoint**

```bash
git add app/docs/advanced/release
git commit -m "docs: record SAW referral hardening verification"
```

- [x] **Step 6: Push only the Alpha branch**

Run: `git push origin alpha/0.02alpha1`

Expected: `origin/alpha/0.02alpha1` advances to the verified local HEAD; `main` is untouched.
