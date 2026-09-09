# BIC/RTC/STC Versification Alignment and Project Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route BIC, RTC, and STC Scripture evidence through each Project's effective versification and produce human reports that name the actual configured Projects instead of exposing component-role placeholders.

**Architecture:** First complete the Paratext VRS grammar and import the pinned standard SIL schemas with exact provenance. Then introduce an internal versification facade, immutable Project identity, and canonical verse-index services; teach the existing SFM slicer and workflow adapters to correlate exact Project-local records through canonical coordinates. Preserve Primary Project local coverage and exact SFM, retain versioned legacy local-number routing, and feed sealed Project display names to workflow-specific report renderers through one shared report context.

**Tech Stack:** Python 3.12, dataclasses, existing USJ/SFM and VRS models, JSON/YAML contracts, pytest, atomic file transactions, Markdown documentation.

**Spec:** `docs/superpowers/specs/2026-09-03-BIC-RTC-STC-VERSIFICATION-REPORTING-DESIGN.md`

## Global Constraints

- `org.vrs` remains the canonical cross-Project mapping target.
- Standard VRS assets are pinned, checksummed, licensed, and never downloaded at runtime.
- `vrs.py` remains the pure low-level parser/model; workflows converge on one internal
  versification facade instead of acquiring new direct parsing or projection logic.
- Work-unit ownership and completion coverage remain in the Primary Project's local coordinates.
- Routed Scripture text remains exact Project-local SFM; canonical coordinates are correlation metadata only.
- RTC/STC versification and valid source-coverage differences remain report-only and never become VRS-driven bridge boundaries.
- Only actual multi-coordinate source records may constrain work-unit boundaries.
- BIC must stop before a TARGET write when SOURCE-to-TARGET projection is ambiguous.
- Machine roles and Project IDs remain canonical in governed JSON; human reports use sealed Project display names.
- STC human reports omit REFERENCE entirely.
- Existing sealed plans/tasks retain their stored planner semantics and are never rewritten.
- TUI workflow actions remain paused.
- Every production change follows a witnessed red-green pytest cycle.
- No automated test invokes a live provider.
- Preserve unrelated user changes in the working tree.

## Stage gates

| Stage | Deliverable | Gate before proceeding |
| --- | --- | --- |
| 0 | Paratext grammar compatibility and pinned standard VRS catalog | All six bundled standards parse; provenance and package gates pass |
| 0.5 | Internal VRS API facade | Catalog, invalidation, projection, and migrated loading tests pass |
| 1 | Shared Project identity and canonical verse index | Pure unit tests pass; no workflow behavior changes |
| 2 | VRS-aware shared SFM routing | Existing exact-local slicer tests and new cross-VRS tests pass |
| 3 | RTC and STC migration | Cross-VRS routing, source-gap, bridge, legacy-plan, and hard-limit tests pass |
| 4 | BIC migration | Read-only alignment and fail-before-write/precise-write tests pass |
| 5 | Project-specific reporting | BIC/RTC/STC golden reports contain names and no forbidden placeholders |
| 6 | Packet modularization and complete validation | Full pytest, schemas, package validation, and documentation contracts pass |

---

## Stage 0 — Standard VRS compatibility and catalog

### Task 0: Import and govern the standard SIL versification schemas

**Files:**
- Modify: `system/src/sage/vrs.py`
- Modify: `system/tests/test_vrs.py`
- Create: `system/tests/test_standard_vrs_resources.py`
- Create: `system/resources/scripture/lxx.vrs`
- Create: `system/resources/scripture/vul.vrs`
- Create: `system/resources/scripture/rsc.vrs`
- Create: `system/resources/scripture/rso.vrs`
- Create: `system/resources/scripture/standard-vrs-provenance.json`
- Create: `system/resources/scripture/standard-vrs.LICENSE.txt`
- Modify: `system/resources/scripture/README.md`
- Modify: `ecosystem.yml`
- Modify: `system/src/sage/validation.py`
- Modify: `system/tools/build_release.py`
- Modify: `docs/advanced/projects-and-resources/VERSIFICATION.md`
- Modify: `docs/advanced/release/VANILLA-INSTALL-MANIFEST.md`

**Interfaces:**
- Changes: `VersificationSchema` retains verse-segment and custom chapter-truncation metadata
- Changes: `parse_vrs_file()` accepts plain and `#!` exclusions/segments and validates `&`
- Preserves: existing `eng.vrs` and `org.vrs` bytes
- Adds: six registered standard schemes with pinned, machine-readable provenance

- [x] **Step 1: Write failing grammar tests**

Cover plain and `#!` exclusions, plain and `#!` segment declarations, invalid
many-to-many `&` mappings, and `END` truncation after base/custom composition.
Expect failures against the current parser for each missing behavior.

- [x] **Step 2: Write a failing standard-catalog integration test**

Load `org`, `eng`, `lxx`, `vul`, `rsc`, and `rso` from the package resources. Assert
literal pinned file hashes, representative chapter maxima, LXX exclusion/segment
metadata, and successful parser completion. Verify that every configured base file
is present directly under the shared VRS root.

- [x] **Step 3: Run the tests and witness the compatibility failures**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_vrs.py tests/test_standard_vrs_resources.py`

Expected: FAIL because plain exclusions are misclassified, segment directives and
`END` are unsupported, `&` does not enforce the Paratext rule, and four resources
are absent.

- [x] **Step 4: Implement the minimum parser/model compatibility**

Preserve `-` as the unmarked initial segment in immutable tuple metadata. Merge
custom segment declarations by reference. Record an `END` boundary during parsing
and remove inherited chapters above that boundary during composition. Do not split
USFM verse records based on segment metadata.

- [x] **Step 5: Import the pinned resources and provenance**

Copy the four missing `.vrs` files byte-for-byte from `sillsdev/libpalaso` commit
`bb9d36de70ed7fd6c3e62f0c86c1001f0009eb50`. Record upstream/shipped SHA-256 values,
source paths, source URL, commit, and MIT license for all six schemas. Keep the
existing `eng.vrs` and `org.vrs` bytes unchanged.

- [x] **Step 6: Register and package all six schemas**

Add all filenames to `versification.base_files`, package validation, release
allowlists, Scripture resource documentation, and the exact vanilla source-tree
manifest.

- [x] **Step 7: Run Stage 0 verification**

Run the focused tests from Step 3, then schema validation, package validation,
`git diff --check`, and the complete pytest suite. Proceed to Stage 1 only if every
gate is green.

---

## Stage 0.5 — Internal versification API facade

### Task 0.5: Establish the single workflow-facing VRS loading and projection API

**Files:**
- Create: `system/src/sage/versification_service.py`
- Create: `system/tests/test_versification_service.py`
- Modify: `system/src/sage/scripture.py`
- Modify: `system/src/sage/validation.py`
- Modify: `system/src/sage/act_tasks.py`
- Modify: `docs/advanced/projects-and-resources/VERSIFICATION.md`
- Modify: `docs/advanced/release/VANILLA-INSTALL-MANIFEST.md`

**Interfaces:**
- Produces: `VersificationCatalogEntry`
- Produces: `ReferenceProjection`
- Produces: `VersificationService.catalog()`
- Produces: `VersificationService.base_schema(filename)`
- Produces: `VersificationService.project_schema(project_or_id)`
- Produces: `VersificationService.effective_fingerprint(project_or_id)`
- Produces: `VersificationService.to_canonical(project_or_id, refs)`
- Produces: `VersificationService.from_canonical(project_or_id, refs)`
- Preserves: `vrs.py` as the low-level parser/model and all existing function APIs

- [x] **Step 1: Write failing service contract tests**

Use real temporary Projects and VRS files. Prove catalog role/provenance output,
Project loading, deterministic projection, returned-schema isolation, and same-
process invalidation when a custom VRS file changes. Do not mock parser calls or
assert private cache mechanics.

- [x] **Step 2: Run the service tests and witness the missing API**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_versification_service.py`

Expected: collection fails because `sage.versification_service` does not exist.

- [x] **Step 3: Implement the facade and content-addressed cache**

Read optional standard provenance without making it mandatory in synthetic or
external VRS roots. Resolve Project files through the existing governed resolver.
Key cached schemas by resolved paths and SHA-256 values, discard obsolete entries
for the same Project, and return independent copies. Do not add a global singleton.

- [x] **Step 4: Implement deterministic reference projection**

Return sorted immutable reference tuples. Classify any one-to-many, many-to-one, or
otherwise ambiguous mapping as `EQUIVALENCE_GROUP`; retain `COORDINATE` only when
every input projects to one reversible coordinate.

- [x] **Step 5: Migrate existing schema-loading consumers**

Use the facade in Project compilation, default-VRS advisory checks, static ecosystem
validation, VRS evidence creation, and structural-candidate generation. Keep direct
`VerseRef`/`VersificationSchema` imports where they are type/model dependencies.

- [x] **Step 6: Run the Stage 0.5 gate**

Run the service, VRS, Scripture, static-validation, ACT-task, package, and schema
tests; then run the complete pytest suite. Confirm existing effective VRS hashes and
human/machine artifacts do not drift for schemas without segment metadata.

---

## Stage 1 — Shared identity and alignment foundations

### Task 1: Add immutable Project identity resolution

**Files:**
- Create: `system/src/sage/project_context.py`
- Create: `system/tests/test_project_context.py`
- Modify: `system/src/sage/act_tasks.py:3460-3500`
- Modify: `system/src/sage/act_tasks.py:4865-4935`
- Test: `system/tests/test_stc_task.py`
- Test: `system/tests/test_primary_analysis_jobs.py`
- Modify: `docs/advanced/release/VANILLA-INSTALL-MANIFEST.md`

**Interfaces:**
- Produces: `ProjectIdentity`
- Produces: `resolve_project_identity(root: Path, role: str, project: ProjectSpec, compiled: Mapping[str, Any]) -> ProjectIdentity`
- Produces: `resolve_project_identities(root: Path, bindings: Mapping[str, str], projects: Mapping[str, ProjectSpec], compiled: Mapping[str, Mapping[str, Any]]) -> dict[str, ProjectIdentity]`
- Produces: `identity_bindings(identities: Mapping[str, ProjectIdentity]) -> dict[str, str]`
- Produces: `identity_display_names(identities: Mapping[str, ProjectIdentity]) -> dict[str, str]`

- [x] **Step 1: Write failing Project-identity tests**

```python
def test_project_identity_resolves_inventory_name_and_import_date(make_workspace) -> None:
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")
    register_project(
        root,
        project_id=project.project_id,
        project_path=project.path,
        language_code=project.language_code,
        base_vrs_file=project.versification.base,
        display_name="Persian Contemporary Bible",
        declared_books=("MAT",),
        imported_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    compiled = compile_project(config, project)

    identity = resolve_project_identity(root, "WIP", project, compiled)

    assert identity.role == "WIP"
    assert identity.project_id == "usWIP"
    assert identity.display_name != "WIP"
    assert identity.imported_date == "20260901"
    assert len(identity.content_fingerprint) == 64
    assert len(identity.effective_vrs_sha256) == 64


def test_missing_display_name_falls_back_to_project_id(make_workspace) -> None:
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    project = config.project("usWIP")
    identity = resolve_project_identity(
        root, "WIP", project, compile_project(config, project)
    )
    assert identity.display_name == identity.project_id
```

- [x] **Step 2: Run the tests and verify the module is missing**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_project_context.py`

Expected: FAIL during import because `sage.project_context` does not exist.

- [x] **Step 3: Implement the immutable identity model and resolver**

```python
@dataclass(frozen=True)
class ProjectIdentity:
    role: str
    project_id: str
    display_name: str
    imported_date: str | None
    content_fingerprint: str | None
    vrs_schema_id: str | None
    effective_vrs_sha256: str | None


def resolve_project_identity(
    root: Path,
    role: str,
    project: ProjectSpec,
    compiled: Mapping[str, Any],
) -> ProjectIdentity:
    records = registered_project_records(root)
    inventory = records.get(project.project_id, {})
    effective_vrs = dict(compiled.get("effective_vrs") or {})
    return ProjectIdentity(
        role=role.strip().upper(),
        project_id=project.project_id,
        display_name=str(inventory.get("display_name") or project.project_id),
        imported_date=project_import_date(inventory),
        content_fingerprint=project_validation_fingerprint(dict(compiled)),
        vrs_schema_id=str(effective_vrs.get("schema_id") or ""),
        effective_vrs_sha256=str(effective_vrs.get("effective_sha256") or ""),
    )
```

Validate uppercase non-empty roles and every present SHA-256 value. A dormant Job
binding that was not compiled for the current task retains sealed Project/name
identity with `None` compilation provenance; do not compile or read unused content
solely to populate identity. An allowed-empty `NOT_GENERATED` BIC TARGET follows
the same destination-only rule. Return fresh dictionaries from projection helpers.

- [x] **Step 4: Replace both ACT task identity builders with the resolver**

The standalone STC path must stop assigning `resource_display_names = resource_bindings`. Both generic and STC task builders must serialize:

```python
"resource_bindings": identity_bindings(project_identities),
"resource_display_names": identity_display_names(project_identities),
```

- [x] **Step 5: Run focused identity and task tests**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_project_context.py tests/test_stc_task.py tests/test_primary_analysis_jobs.py`

Expected: PASS; standalone STC manifests contain inventory display names for WIP and GRK/HEB.

- [x] **Step 6: Commit Stage 1 identity work**

```bash
git add app/system/src/sage/project_context.py app/system/src/sage/act_tasks.py app/system/tests/test_project_context.py app/system/tests/test_stc_task.py app/system/tests/test_primary_analysis_jobs.py
git commit -m "refactor: centralize project task identity"
```

### Task 2: Build the canonical Project verse index

**Files:**
- Create: `system/src/sage/verse_alignment.py`
- Create: `system/tests/test_verse_alignment.py`
- Modify: `system/src/sage/findings.py:212-226`
- Test: `system/tests/test_findings_and_coverage.py`
- Test: `system/tests/test_vrs.py`
- Modify: `docs/advanced/release/VANILLA-INSTALL-MANIFEST.md`

**Interfaces:**
- Produces: `AlignedEvidenceRecord`
- Produces: `AlignmentSelection`
- Produces: `CoordinateProjection`
- Produces: `ProjectVerseIndex.build(project_id: str, records: Iterable[EvidenceRecord], schema: VersificationSchema) -> ProjectVerseIndex`
- Produces: `ProjectVerseIndex.canonical_refs_for_records(records: Iterable[EvidenceRecord]) -> frozenset[VerseRef]`
- Produces: `ProjectVerseIndex.records_for_canonical(refs: Iterable[VerseRef]) -> tuple[EvidenceRecord, ...]`
- Produces: `ProjectVerseIndex.local_refs_for_canonical(refs: Iterable[VerseRef], *, existing_only: bool = False) -> frozenset[VerseRef]`
- Produces: `align_records(primary_records: Iterable[EvidenceRecord], primary_index: ProjectVerseIndex, authority_index: ProjectVerseIndex) -> AlignmentSelection`
- Produces: `project_coordinates(primary_refs: Iterable[VerseRef], primary_index: ProjectVerseIndex, target_index: ProjectVerseIndex) -> CoordinateProjection`

- [x] **Step 1: Write failing one-to-one and many-to-one index tests**

```python
def test_index_selects_reference_local_record_through_canonical_coordinate(tmp_path) -> None:
    wip_schema = schema(tmp_path, "wip.vrs", "2CO 13:14\n2CO 13:14 = 2CO 13:13\n")
    ref_schema = schema(tmp_path, "ref.vrs", "2CO 13:13\n")
    wip = (_record("2CO", 13, 14, "wip"),)
    reference = (_record("2CO", 13, 13, "reference"),)

    selection = align_records(
        wip,
        ProjectVerseIndex.build("WIP", wip, wip_schema),
        ProjectVerseIndex.build("REF", reference, ref_schema),
    )

    assert [row.reference for row in selection.authority_records] == ["2CO 13:13"]
    assert [ref.label() for ref in selection.canonical_refs] == ["2CO 13:13"]
    assert selection.missing_canonical_refs == frozenset()


def test_many_to_one_mapping_routes_all_local_primary_records(tmp_path) -> None:
    wip_schema = schema(
        tmp_path,
        "wip.vrs",
        "MAT 1:3\n#! &MAT 1:2-3 = MAT 1:2\n",
    )
    ref_schema = schema(tmp_path, "ref.vrs", "MAT 1:2\n")
    wip = (
        _record("MAT", 1, 2, "first"),
        _record("MAT", 1, 3, "continuation"),
    )
    reference = (_record("MAT", 1, 2, "authority"),)
    selection = align_records(
        wip,
        ProjectVerseIndex.build("WIP", wip, wip_schema),
        ProjectVerseIndex.build("REF", reference, ref_schema),
    )
    assert [row.reference for row in selection.authority_records] == ["MAT 1:2"]
    assert selection.mapping_precision == "EQUIVALENCE_GROUP"
```

- [x] **Step 2: Write failing exclusion and projection tests**

```python
def test_excluded_coordinate_is_not_an_authorized_finding_reference(tmp_path) -> None:
    target_schema = schema(
        tmp_path,
        "target.vrs",
        "MAT 1:3\n#! - MAT 1:2\n",
    )
    with pytest.raises(ValidationError, match="empty under VRS"):
        validate_finding_references(
            {"target_reference": "MAT 1:2"},
            target_schema=target_schema,
            resource_schemas={},
            primary_target_refs=frozenset({VerseRef("MAT", 1, 2)}),
        )


def test_ambiguous_target_projection_is_explicit(tmp_path) -> None:
    source_schema = schema(
        tmp_path,
        "source.vrs",
        "MAT 1:3\nMAT 1:2 = MAT 1:2-3\n",
    )
    target_schema = schema(tmp_path, "target.vrs", "MAT 1:3\n")
    source = (_record("MAT", 1, 2, "source"),)
    target = (
        _record("MAT", 1, 2, "target two"),
        _record("MAT", 1, 3, "target three"),
    )
    projection = project_coordinates(
        (VerseRef("MAT", 1, 2),),
        ProjectVerseIndex.build("SOURCE", source, source_schema),
        ProjectVerseIndex.build("TARGET", target, target_schema),
    )
    assert projection.precision == "EQUIVALENCE_GROUP"
    assert projection.is_deterministic is False
```

- [x] **Step 3: Run the new tests and witness exact-local failure**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_verse_alignment.py tests/test_findings_and_coverage.py`

Expected: FAIL because no verse index exists and `_local_refs()` currently includes VRS exclusions.

- [x] **Step 4: Implement immutable aligned records and indexes**

```python
@dataclass(frozen=True)
class AlignedEvidenceRecord:
    record: EvidenceRecord
    local_refs: frozenset[VerseRef]
    canonical_refs: frozenset[VerseRef]
    mapping_precision: str


@dataclass(frozen=True)
class AlignmentSelection:
    primary_local_refs: frozenset[VerseRef]
    canonical_refs: frozenset[VerseRef]
    authority_records: tuple[EvidenceRecord, ...]
    covered_canonical_refs: frozenset[VerseRef]
    missing_canonical_refs: frozenset[VerseRef]
    mapping_precision: str
```

Build reverse indexes once, deduplicate bridged records by stable record key, and
return records in Project-local canonical Book/chapter/verse order. Evidence
selection returns only actual records. Schema coordinate projection uses
`VersificationSchema.canonical_to_local()` even when the target has no record, and
removes excluded local coordinates. Do not mutate `EvidenceRecord` or relabel its
SFM.

- [x] **Step 5: Exclude VRS-excluded coordinates from finding expansion**

Change `_local_refs()` so it skips `ref in schema.exclusions`. Preserve the existing error when the resulting citation is empty.

- [x] **Step 6: Run Stage 1 alignment tests**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_verse_alignment.py tests/test_findings_and_coverage.py tests/test_vrs.py`

Expected: PASS for one-to-one, continuation, equivalence-group, exclusion, and deterministic-order fixtures.

- [x] **Step 7: Commit the alignment foundation**

```bash
git add app/system/src/sage/verse_alignment.py app/system/src/sage/findings.py app/system/tests/test_verse_alignment.py app/system/tests/test_findings_and_coverage.py app/system/tests/test_vrs.py
git commit -m "feat: index project verses by canonical coordinates"
```

---

## Stage 2 — VRS-aware shared SFM routing

### Task 3: Teach the SFM slicer to use Project verse indexes

**Files:**
- Modify: `system/src/sage/sfm_slicer.py`
- Modify: `system/tests/test_hardening_and_segmentation.py`
- Create: `system/tests/test_sfm_alignment.py`

**Interfaces:**
- Changes: `SfmStream` adds `verse_index: ProjectVerseIndex | None = None`
- Changes: `SfmAnalysisRoute` adds `primary_stream_id: str | None = None` and `primary_index: ProjectVerseIndex | None = None`
- Preserves: routes with no indexes use current exact-local selection

- [x] **Step 1: Write a failing cross-VRS route-sizing test**

```python
def test_sfm_route_measures_authority_record_selected_by_canonical_mapping(tmp_path) -> None:
    route = SfmAnalysisRoute(
        route_id="RTC",
        primary_stream_id="WIP",
        primary_index=wip_index,
        streams=(
            SfmStream("WIP", wip, verse_index=wip_index),
            SfmStream("REFERENCE", reference, verse_index=reference_index),
        ),
    )
    units = plan_sfm_work_units(wip, policy(), unit_prefix="RTC-2CO", route=route)
    assert units[0].measurement.estimated_tokens == (
        measure_sfm_slice(wip).estimated_tokens
        + measure_sfm_slice(reference).estimated_tokens
    )
```

- [x] **Step 2: Write a failing projected source-bridge test**

Create a REFERENCE bridge whose local coordinates map onto two WIP local atoms. Assert that the planner never separates those WIP atoms. Also assert that an equivalent range present only in VRS metadata does not protect a boundary.

- [x] **Step 3: Run the slicer tests and verify exact-local routing fails**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_sfm_alignment.py tests/test_hardening_and_segmentation.py`

Expected: the cross-VRS Authority text is not selected and the projected bridge assertion fails.

- [x] **Step 4: Implement indexed stream selection**

For the declared primary stream, retain exact Primary local record selection. For every indexed Authority stream:

```python
primary_canonical = route.primary_index.canonical_refs_for_records(primary)
selected_primary = stream.verse_index.records_for_canonical(primary_canonical)
```

Coverage checks compare canonical atoms. Context selection follows the same mapping. Legacy routes with missing `primary_index` or stream indexes execute the existing local intersection code.

- [x] **Step 5: Project actual Authority bridges to Primary local coordinates**

Update `SfmAnalysisRoute.protected_spans()` to project only `record.refs` from actual multi-coordinate records through both indexes. Do not add `VersificationSchema.mappings` directly to `required_spans`.

- [x] **Step 6: Run all slicer/work-unit tests**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_sfm_alignment.py tests/test_hardening_and_segmentation.py tests/test_sections_and_work_units.py tests/test_rtc_planner.py tests/test_stc.py`

Expected: PASS; unchanged exact-local tests prove the compatibility path remains intact.

- [x] **Step 7: Commit VRS-aware routing**

```bash
git add app/system/src/sage/sfm_slicer.py app/system/tests/test_sfm_alignment.py app/system/tests/test_hardening_and_segmentation.py
git commit -m "feat: route SFM through canonical verse indexes"
```

---

## Stage 3 — RTC and STC workflow migration

### Task 4: Migrate new RTC plans to canonical correlation

**Files:**
- Modify: `system/src/sage/rtc_planner.py`
- Modify: `system/src/sage/cli.py:3405-3660`
- Modify: `system/src/sage/act_tasks.py:1979-2090`
- Modify: `system/src/sage/act_tasks.py:2808-2871`
- Modify: `system/tests/test_rtc_planner.py`
- Modify: `system/tests/test_cli_dev3.py`
- Modify: `system/tests/test_storage_rtc_boundaries.py`

**Interfaces:**
- Changes: `RTC_PLANNER_VERSION = "SAGE_RTC_SFM_ROUTE_PLANNER_V5"`
- Adds: `LEGACY_RTC_PLANNER_VERSION = "SAGE_RTC_SFM_ROUTE_PLANNER_V4"`
- Changes: `plan_rtc_work_units(wip_records: Iterable[EvidenceRecord], base_policy: EvidencePolicy, sizing: RTCSizingPolicy, *, unit_prefix: str, shared: dict[str, Any], wip_context_pool: Iterable[EvidenceRecord], reference_records: Iterable[EvidenceRecord], wip_index: ProjectVerseIndex, reference_index: ProjectVerseIndex, workflow: str = "rtc", planner_version: str = RTC_PLANNER_VERSION) -> tuple[tuple[WorkUnit, ...], tuple[dict[str, Any], ...], EvidencePolicy]`
- Produces: each `rtc_package` contains `alignment.primary_local_atoms`, `alignment.canonical_atoms`, `alignment.reference_local_spans`, and `alignment.missing_canonical_atoms`

- [ ] **Step 1: Write a failing RTC Project-to-Project VRS test**

Use WIP `2CO 13:14 = 2CO 13:13` and REFERENCE local `2CO 13:13`. Assert the package routes REFERENCE `13:13`, has no source-text issue, and keeps WIP completion atom `13:14`.

- [ ] **Step 2: Write a failing RTC canonical source-gap test**

Give the REFERENCE no record corresponding to canonical `13:13`. Assert one report-only issue is attached to WIP local `2CO 13:14`, with canonical coordinate metadata `2CO 13:13`.

- [ ] **Step 3: Write an RTC V4 compatibility test**

Load a frozen V4 planning fixture and assert resumption uses exact-local correlation and does not alter the fixture bytes. This test must pass before and after the implementation.

- [ ] **Step 4: Run RTC tests and witness the V5 failures**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_rtc_planner.py tests/test_cli_dev3.py tests/test_storage_rtc_boundaries.py`

Expected: new V5 correlation assertions fail; the frozen V4 compatibility test passes.

- [ ] **Step 5: Build both Project indexes in CLI and task planning**

Load each Project schema with `load_project_vrs()`, build indexes from compiled records, pass them to the V5 route, and include the V5 version plus both effective VRS hashes in the plan fingerprint. Never infer a Project's schema from another Project.

- [ ] **Step 6: Replace RTC source coverage with canonical alignment coverage**

Keep issue `reference` in WIP-local coordinates. Add `canonical_references` and actual REFERENCE local spans to machine metadata. Continue using `COMPLETE_WITH_STRUCTURE_PROBLEMS`; do not raise for missing valid REFERENCE coordinates.

- [ ] **Step 7: Preserve V4 resumption explicitly**

Dispatch stored V4 plans to the exact-local route. Reject an unknown future planner version with a typed validation error rather than silently choosing either algorithm.

- [ ] **Step 8: Run RTC workflow and boundary tests**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_rtc_planner.py tests/test_cli_dev3.py tests/test_storage_rtc_boundaries.py tests/test_provider_and_boundary_policy.py`

Expected: PASS with V5 correlation, preserved actual-bridge boundaries, and unchanged V4 behavior.

- [ ] **Step 9: Commit RTC V5**

```bash
git add app/system/src/sage/rtc_planner.py app/system/src/sage/cli.py app/system/src/sage/act_tasks.py app/system/tests/test_rtc_planner.py app/system/tests/test_cli_dev3.py app/system/tests/test_storage_rtc_boundaries.py
git commit -m "feat: correlate RTC projects through canonical VRS"
```

### Task 5: Migrate new STC plans to canonical correlation

**Files:**
- Modify: `system/src/sage/stc.py`
- Modify: `system/src/sage/cli.py:3459-3659`
- Modify: `system/src/sage/act_tasks.py:3274-3535`
- Modify: `system/tests/test_stc.py`
- Modify: `system/tests/test_stc_task.py`
- Modify: `system/tests/test_cli_dev3.py`

**Interfaces:**
- Produces: `STC_PLANNER_VERSION = "SAGE_STC_SFM_ROUTE_PLANNER_V2"`
- Changes: `plan_stc_work_units(wip_records: Iterable[EvidenceRecord], ol_records: Iterable[EvidenceRecord], policy: EvidencePolicy, *, unit_prefix: str, wip_index: ProjectVerseIndex, ol_index: ProjectVerseIndex, context_pool: Iterable[EvidenceRecord] | None = None, planner_version: str = STC_PLANNER_VERSION) -> tuple[WorkUnit, ...]`
- Changes: `stc_package_measurements(units: Iterable[WorkUnit], ol_records: Iterable[EvidenceRecord], *, wip_index: ProjectVerseIndex, ol_index: ProjectVerseIndex) -> tuple[dict[str, Any], ...]`
- Produces: STC alignment audit metadata equivalent to RTC, using the exact `ORIGINAL_LANGUAGE_GREEK` or `ORIGINAL_LANGUAGE_HEBREW` role

- [ ] **Step 1: Write failing STC VRS-alignment tests**

Use a WIP local coordinate that maps to a different canonical GRK/HEB coordinate. Assert STC routes the OL record through canonical correspondence, preserves WIP-local primary coverage, and does not report a false source gap.

- [ ] **Step 2: Write a missing-version compatibility test**

Create a frozen STC plan without `stc_planner_version`. Assert resumption uses the current sealed exact-local behavior and does not mutate the plan.

- [ ] **Step 3: Run the STC tests and witness cross-VRS failure**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_stc.py tests/test_stc_task.py tests/test_cli_dev3.py`

Expected: new canonical-correlation assertions fail; legacy compatibility remains green.

- [ ] **Step 4: Build WIP and canon-selected OL indexes**

Build only the testament-appropriate GRK or HEB index. Route WIP as Primary, route OL through canonical selection, and seal `stc_planner_version` plus both VRS hashes into every new plan fingerprint.

- [ ] **Step 5: Use canonical coverage for STC structural issues**

Report missing canonical authority coverage at the corresponding WIP-local coordinate. Keep the issue report-only and preserve the existing completion-state contract.

- [ ] **Step 6: Run STC and shared routing tests**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_stc.py tests/test_stc_task.py tests/test_cli_dev3.py tests/test_sfm_alignment.py tests/test_structural_issues.py`

Expected: PASS with exact GRK/HEB routing and unchanged hard-limit enforcement.

- [ ] **Step 7: Commit STC V2**

```bash
git add app/system/src/sage/stc.py app/system/src/sage/cli.py app/system/src/sage/act_tasks.py app/system/tests/test_stc.py app/system/tests/test_stc_task.py app/system/tests/test_cli_dev3.py
git commit -m "feat: correlate STC authority through canonical VRS"
```

---

## Stage 4 — BIC read and write safety

### Task 6: Align BIC evidence and project deterministic TARGET coordinates

**Files:**
- Modify: `system/src/sage/act_tasks.py:3900-4175`
- Modify: `system/src/sage/act_tasks.py:4700-4745`
- Modify: `system/src/sage/act_tasks.py:6322-6465`
- Modify: `system/src/sage/act_outputs.py:382-470`
- Modify: `system/src/sage/bounded_target.py:193-285`
- Create: `system/tests/test_bic_verse_alignment.py`
- Test: `system/tests/test_hardening_and_segmentation.py`
- Test: `system/tests/test_rc_block_and_job_cleanup.py`

**Interfaces:**
- Consumes: `project_coordinates(primary_refs: Iterable[VerseRef], primary_index: ProjectVerseIndex, target_index: ProjectVerseIndex) -> CoordinateProjection`
- Produces in new BIC manifests: `source_primary_references`, `expected_output_references`, and `target_scope`
- Changes: `validate_bic_usfm_output()` validates TARGET-local `expected_output_references`
- Changes: `merge_bounded_usfm()` receives the sealed `target_scope`, never the SOURCE-local scope
- Preserves: schema-2.4 BIC tasks without the new fields validate and merge with their sealed `expected_references`/`scope` behavior

- [x] **Step 1: Write a failing BIC one-to-one projection test**

Create a SOURCE local `2CO 13:14` mapped to canonical `13:13` and a TARGET whose local coordinate is `13:13`. Assert the task keeps SOURCE coverage `13:14`, expects TARGET output `13:13`, and routes any existing TARGET `13:13` text.

- [x] **Step 2: Write a failing ambiguous-projection safety test**

Use a SOURCE-to-TARGET equivalence group. Assert INSPECT can be created with a report-only alignment advisory, but REWRITE/SELF-CHECK fails with `BIC_TARGET_VRS_ALIGNMENT_REQUIRED` before task output or TARGET files are written.

- [x] **Step 3: Run BIC alignment tests and witness current same-scope behavior**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_bic_verse_alignment.py tests/test_hardening_and_segmentation.py tests/test_rc_block_and_job_cleanup.py`

Expected: SOURCE references are currently reused as TARGET references and the ambiguity guard is absent.

- [x] **Step 4: Seal separate SOURCE and TARGET coverage**

Build SOURCE and TARGET indexes during BIC task creation. Persist the SOURCE-local work coverage separately from the projected TARGET-local expected output. Include both Project VRS hashes and the projection metadata in the task fingerprint.

- [x] **Step 5: Validate and merge only TARGET-local coordinates**

Pass `expected_output_references` to `validate_bic_usfm_output()` and `target_scope` to `merge_bounded_usfm()`. Keep SOURCE-local scope for memory, findings, and content-provenance records. Reject non-contiguous or equivalence-group TARGET projections before creating a writable task.

- [x] **Step 6: Verify the transaction remains fail-before-write**

In the ambiguity test, snapshot the TARGET bytes and transaction directory before the call. Assert both are unchanged afterward. Retain `FileTransaction` as the only TARGET commit mechanism.

- [x] **Step 7: Run the BIC suite**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_bic_verse_alignment.py tests/test_hardening_and_segmentation.py tests/test_rc_block_and_job_cleanup.py tests/test_rewrite_risk.py tests/test_core_hardening.py`

Expected: PASS; coordinate-precise projections commit only inside TARGET-local scope and ambiguous mappings leave all governed data untouched.

- [x] **Step 8: Commit BIC alignment**

```bash
git add app/system/src/sage/act_tasks.py app/system/src/sage/act_outputs.py app/system/src/sage/bounded_target.py app/system/tests/test_bic_verse_alignment.py app/system/tests/test_hardening_and_segmentation.py app/system/tests/test_rc_block_and_job_cleanup.py
git commit -m "feat: enforce BIC target versification alignment"
```

---

## Stage 5 — Project-specific human reports

### Task 7: Add a shared sealed report context

**Files:**
- Create: `system/src/sage/report_context.py`
- Create: `system/tests/test_report_context.py`
- Modify: `system/src/sage/report_authority.py`
- Modify: `system/tests/test_report_authority.py`

**Interfaces:**
- Produces: `ReportProject`
- Produces: `ProjectReportContext.from_document(document: Mapping[str, Any]) -> ProjectReportContext`
- Produces: `ProjectReportContext.name(role: str) -> str`
- Produces: `ProjectReportContext.project(role: str) -> ReportProject`
- Produces: `ProjectReportContext.resolve_project_terms(text: str) -> str`
- Produces: `ProjectReportContext.require_resolved(text: str) -> None`
- Changes: `authority_header(job: Job, run: Run, *, report_context: ProjectReportContext, family: str | None = None, fingerprints: Mapping[str, Any] | None = None) -> tuple[str, ...]` uses names first and IDs as metadata
- Changes: `write_job_summary(reports_root: Path, job: Job, *, report_context: ProjectReportContext, report_paths: Sequence[Path] = ()) -> Path` names the actual Primary Project

- [ ] **Step 1: Write failing role-resolution tests**

```python
def test_report_context_uses_names_not_component_roles() -> None:
    context = ProjectReportContext.from_document({
        "workflow": "rtc",
        "resource_bindings": {"WIP": "faPCBv3", "REFERENCE": "faTMNv4"},
        "resource_display_names": {
            "WIP": "Persian Contemporary Bible",
            "REFERENCE": "Persian Translation Model",
        },
    })
    assert context.resolve_project_terms("Compare WIP with REFERENCE.") == (
        "Compare Persian Contemporary Bible with Persian Translation Model."
    )
    assert context.resolve_project_terms("Project usWIP differs from usNIVv2.") == (
        "Project Persian Contemporary Bible differs from Persian Translation Model."
    )
```

Also assert that missing names fall back to IDs, STC rejects a REFERENCE presentation field, and unresolved `<WIP_PROJECT_NAME>` tokens fail validation.

- [ ] **Step 2: Run and witness missing report-context failure**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_report_context.py tests/test_report_authority.py`

Expected: FAIL because `sage.report_context` is absent and authority headers expose role labels/IDs.

- [ ] **Step 3: Implement the context without reading live inventory**

Construct it only from sealed `resource_bindings` and `resource_display_names`.
This ensures regenerated historical reports retain the Project names recorded by
their task/run. Replace both whole-word role tokens and exact bound Project IDs in
human prose; do not alter substrings inside ordinary words or audit metadata.

- [ ] **Step 4: Make authority metadata Project-specific**

RTC fields become `Project under review` and `Comparison Project`. STC fields become
`Project under review` and `Original-language authority`; omit REFERENCE rather
than printing `NOT USED`. Update `write_job_summary()` through the same context.
Preserve snapshot date and fingerprints.

- [ ] **Step 5: Run context and authority tests**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_report_context.py tests/test_report_authority.py`

Expected: PASS; no human authority line uses WIP/REFERENCE as a Project name.

- [ ] **Step 6: Commit report context**

```bash
git add app/system/src/sage/report_context.py app/system/src/sage/report_authority.py app/system/tests/test_report_context.py app/system/tests/test_report_authority.py
git commit -m "refactor: centralize project report context"
```

### Task 8: Convert RTC and STC reports to Project-name templates

**Files:**
- Modify: `system/src/sage/act_outputs.py:1051-1142`
- Modify: `system/src/sage/act_outputs.py:1205-1369`
- Modify: `system/src/sage/stc_reporting.py:70-214`
- Modify: `system/src/sage/stc.py:242-359`
- Modify: `system/src/sage/plan_continuation.py:728-805`
- Create: `system/src/sage/stc_report_renderer.py`
- Modify: `system/tests/test_human_output.py`
- Modify: `system/tests/test_stc.py`
- Modify: `system/tests/test_stc_task.py`
- Modify: `system/tests/test_project_grammar_convergence.py`

**Interfaces:**
- Changes: `render_action_report()` constructs `ProjectReportContext` and uses display names in the RTC title, findings, evidence labels, advisories, and structural issues
- Produces: `render_stc_report(document: Mapping[str, Any]) -> str`
- Changes: both standalone and chapter STC publication call the same renderer

- [ ] **Step 1: Replace ID-oriented RTC expectations with failing name-oriented golden tests**

Assert the RTC report starts with:

```markdown
# Persian Contemporary Bible compared with Persian Translation Model
```

Assert findings and evidence labels contain both display names, while `WIP` and `REFERENCE` do not appear as standalone human role terms. IDs may occur in the metadata block.

- [ ] **Step 2: Add failing STC report tests**

Assert the report starts with:

```markdown
# Persian Contemporary Bible correspondence with Greek New Testament
```

Assert `REFERENCE`, `NOT USED`, `WIP evidence`, and raw `GRK evidence` headings are absent. Expect the configured WIP and OL Project names instead.

- [ ] **Step 3: Run report tests and witness the current templates fail**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_human_output.py tests/test_stc.py tests/test_stc_task.py tests/test_project_grammar_convergence.py`

Expected: failures show component-based titles, ID-based finding prose, and STC `REFERENCE Project: NOT USED`.

- [ ] **Step 4: Update RTC rendering through `AnalysisReportContext`**

Remove `_operator_project_ids()` as the human-label source. Render display names everywhere except the compact audit metadata that intentionally shows `(<PROJECT_ID>)`. Resolve structural issue Projects by their bound role before falling back to stored IDs.

- [ ] **Step 5: Consolidate both STC Markdown paths**

Move the one STC human renderer into `stc_report_renderer.py`. Call it from chapter publication and standalone finalization. Keep machine `STC_RUN.json` and `STC_FINDINGS.json` unchanged. Do not maintain a second generic `# STC Report` formatter.

- [ ] **Step 6: Validate final Markdown has no unresolved placeholders**

Call `report_context.require_resolved(markdown)` before every human report write. This rejects source-template tokens such as `<WIP_PROJECT_NAME>` but permits normal Markdown angle-bracket syntax only where explicitly allowlisted.

- [ ] **Step 7: Run RTC/STC reporting suites**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_report_context.py tests/test_report_authority.py tests/test_human_output.py tests/test_stc.py tests/test_stc_task.py tests/test_project_grammar_convergence.py tests/test_report_translation.py`

Expected: PASS; primary and assistive-language renderings retain the same sealed Project identities.

- [ ] **Step 8: Commit RTC/STC report convergence**

```bash
git add app/system/src/sage/act_outputs.py app/system/src/sage/stc_reporting.py app/system/src/sage/stc.py app/system/src/sage/stc_report_renderer.py app/system/src/sage/plan_continuation.py app/system/tests/test_human_output.py app/system/tests/test_stc.py app/system/tests/test_stc_task.py app/system/tests/test_project_grammar_convergence.py
git commit -m "feat: name projects in RTC and STC reports"
```

### Task 9: Add Project identity to BIC translation-challenge reports

**Files:**
- Modify: `system/src/sage/rewrite_risk.py:661-794`
- Modify: `system/src/sage/act_tasks.py:6367-6405`
- Modify: `system/tests/test_rewrite_risk.py`
- Modify: `system/tests/test_human_output.py`

**Interfaces:**
- Changes: normalized BIC challenge documents carry `resource_bindings` and `resource_display_names`
- Changes: `render_rewrite_challenge_report()` consumes `ProjectReportContext`

- [ ] **Step 1: Write a failing BIC report golden test**

Assert the title is `<TARGET_PROJECT_NAME> — Translation Challenge Report` and the metadata names Content, Lexical, and Generated Projects by display name with IDs in parentheses.

- [ ] **Step 2: Run the BIC report tests and witness missing identity**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_rewrite_risk.py tests/test_human_output.py`

Expected: current output contains only task/operation/scope metadata.

- [ ] **Step 3: Seal BIC Project identity before writing normalized challenge data**

Copy the task's canonical `SOURCE`, `DONOR`, and `TARGET` bindings and display names into the normalized challenge document before hashing/writing the validation artifacts.

- [ ] **Step 4: Render BIC through the common report context**

Use TARGET display name in the title. Use SOURCE, DONOR, and TARGET display names in metadata and resolve those role words in any human narrative. Keep challenge IDs, coordinates, and machine role fields unchanged.

- [ ] **Step 5: Run BIC report and submission tests**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_rewrite_risk.py tests/test_human_output.py tests/test_core_hardening.py`

Expected: PASS; no BIC report uses SOURCE/DONOR/TARGET as a substitute for an available Project display name.

- [ ] **Step 6: Commit BIC report identity**

```bash
git add app/system/src/sage/rewrite_risk.py app/system/src/sage/act_tasks.py app/system/tests/test_rewrite_risk.py app/system/tests/test_human_output.py
git commit -m "feat: name projects in BIC challenge reports"
```

---

## Stage 6 — Reusable packet extraction and final convergence

### Task 10: Extract bounded Scripture packet creation from `act_tasks.py`

**Files:**
- Create: `system/src/sage/scripture_packets.py`
- Create: `system/tests/test_scripture_packets.py`
- Modify: `system/src/sage/act_tasks.py:1006-1245`
- Modify: `system/src/sage/act_tasks.py:3160-3227`
- Test: `system/tests/test_stc_task.py`
- Test: `system/tests/test_storage_rtc_boundaries.py`
- Test: `system/tests/test_hardening_and_segmentation.py`

**Interfaces:**
- Produces: `write_scope_usj_packet(source: Path, scope: ScriptureScope, destination: Path, *, allow_empty: bool = False) -> tuple[dict[str, Any], str]`
- Produces: `write_reference_inventory_usj_packet(source: Path, reference_values: Sequence[str], destination: Path, *, parent_scope: ScriptureScope, allow_empty: bool = False) -> tuple[dict[str, Any], str]`
- Produces: `write_bounded_sfm_packet(source: Path, primary_scope: ScriptureScope, destination: Path, *, context_references: Sequence[str] = (), allow_empty: bool = False) -> dict[str, Any]`
- Produces: `scope_units(path: Path, scope: ScriptureScope, *, allow_empty: bool = False) -> tuple[list[dict[str, Any]], set[VerseRef], str]`
- Removes private duplicate packet implementations from `act_tasks.py`

- [ ] **Step 1: Add characterization tests for all packet modes**

Cover one verse, a verse bridge, chapter crossing, context-only records, `allow_empty`, exact marker sequence, serialized-byte count, and estimated-token count. Snapshot both the returned metadata and written bytes.

- [ ] **Step 2: Run characterization tests against current helpers**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_scripture_packets.py`

Expected: PASS when tests initially import the current private helpers; these passing fixtures freeze behavior before movement.

- [ ] **Step 3: Move packet code without changing serialization**

Move the implementation to `scripture_packets.py`, rename only the public entry points listed above, and make `act_tasks.py` import them. Do not duplicate old wrappers unless an external test or module imports a private name.

- [ ] **Step 4: Point characterization tests at the new module**

Change only imports. Rerun the exact Step 2 command and require byte-for-byte identical fixtures.

- [ ] **Step 5: Run all packet consumers**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_scripture_packets.py tests/test_stc_task.py tests/test_storage_rtc_boundaries.py tests/test_hardening_and_segmentation.py`

Expected: PASS with no task fingerprint or packet-byte drift beyond changes explicitly introduced and versioned in Stages 3–4.

- [ ] **Step 6: Commit packet modularization**

```bash
git add app/system/src/sage/scripture_packets.py app/system/src/sage/act_tasks.py app/system/tests/test_scripture_packets.py
git commit -m "refactor: extract bounded scripture packets"
```

### Task 11: Update governance documentation and contract tests

**Files:**
- Modify: `docs/advanced/projects-and-resources/VERSIFICATION.md`
- Modify: `docs/advanced/architecture/SAGE-SYSTEM-GRAMMAR.md`
- Modify: `docs/advanced/architecture/HUMAN-OUTPUT-AND-LOGGING.md`
- Modify: `docs/advanced/workflows/BIC-RTC-STC-AUTHORITY-BOUNDARIES.md`
- Modify: `system/config/schemas/work-unit-manifest.schema.yml`
- Modify: `system/config/schemas/act-task.schema.yml`
- Modify: `system/tests/test_documentation_contracts.py`
- Modify: `system/tests/test_schema_validation.py`

**Interfaces:**
- Documents: Primary local-coordinate ownership and canonical correlation
- Documents: V5 RTC and V2 STC legacy selection rules
- Documents: the three Project-name report templates
- Documents: BIC deterministic TARGET projection and ambiguity error

- [ ] **Step 1: Write failing documentation-contract assertions**

Assert the current docs contain `Project-local coordinate`, `Canonical coordinate`, `SAGE_RTC_SFM_ROUTE_PLANNER_V5`, `SAGE_STC_SFM_ROUTE_PLANNER_V2`, and all three final report title templates. Assert the current human-output contract explicitly forbids `REFERENCE Project: NOT USED` in STC output.

- [ ] **Step 2: Run the documentation tests and witness missing contracts**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_documentation_contracts.py tests/test_schema_validation.py`

Expected: the new architecture terms and planner versions are absent from current normative docs/schemas.

- [ ] **Step 3: Update normative documentation and schema controls**

Describe canonical correlation without claiming that canonical labels replace local report references. Update schema control prose for additive alignment audit metadata and planner-version compatibility. Keep task schema `2.4` unless implementation introduced a new required field; if it did, add an explicit `2.5` reader/writer compatibility test before changing the schema identifier.

- [ ] **Step 4: Run docs and schema validation**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_documentation_contracts.py tests/test_schema_validation.py`

Run: `cd app && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/validate_schemas.py .`

Expected: both commands exit zero.

- [ ] **Step 5: Commit governance documentation**

```bash
git add app/docs/advanced/projects-and-resources/VERSIFICATION.md app/docs/advanced/architecture/SAGE-SYSTEM-GRAMMAR.md app/docs/advanced/architecture/HUMAN-OUTPUT-AND-LOGGING.md app/docs/advanced/workflows/BIC-RTC-STC-AUTHORITY-BOUNDARIES.md app/system/config/schemas/work-unit-manifest.schema.yml app/system/config/schemas/act-task.schema.yml app/system/tests/test_documentation_contracts.py app/system/tests/test_schema_validation.py
git commit -m "docs: govern project-aware verse alignment and reports"
```

### Task 12: Run complete regression and package gates

**Files:**
- Modify only if a failing gate identifies a defect directly caused by Tasks 1–11

**Interfaces:**
- Verifies all interfaces and compatibility promises in this plan

- [ ] **Step 1: Run the focused architectural suite**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider tests/test_project_context.py tests/test_verse_alignment.py tests/test_sfm_alignment.py tests/test_rtc_planner.py tests/test_stc.py tests/test_stc_task.py tests/test_bic_verse_alignment.py tests/test_report_context.py tests/test_report_authority.py tests/test_human_output.py tests/test_rewrite_risk.py tests/test_scripture_packets.py`

Expected: all selected tests pass with zero skips caused by missing implementation.

- [ ] **Step 2: Run schema and package validation**

Run: `cd app && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/validate_schemas.py .`

Run: `cd app && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../localdata/.test-runtime/bin/python system/tools/validate_package.py .`

Expected: both commands exit zero with no warnings attributable to the change.

- [ ] **Step 3: Run the complete automated suite**

Run: `cd app/system && PYTHONDONTWRITEBYTECODE=1 env -u SAGE_DATA_HOME ../../localdata/.test-runtime/bin/python -m pytest -q -p no:cacheprovider`

Expected: every discovered test passes. Provider qualification remains outside pytest.

- [ ] **Step 4: Check diff quality and stale role templates**

Run: `git diff --check`

Run:

```bash
rg -n 'REFERENCE Project.*NOT USED|\*\*WIP evidence\*\*|# STC Report|# Source Text Correspondence \(STC\) Report' app/system/src/sage app/docs/advanced
```

Expected: no current human-report template matches. Historical specifications, plans, or frozen fixtures are outside this current-surface scan.

- [ ] **Step 5: Verify the implementation against the design acceptance criteria**

Read `docs/superpowers/specs/2026-09-03-BIC-RTC-STC-VERSIFICATION-REPORTING-DESIGN.md` and record each of its eleven acceptance criteria as PASS with the proving test or validation command in the implementation handover.

- [ ] **Step 6: Commit any direct gate corrections, then record the final implementation state**

First run `git status --short` and identify only files changed to correct a failing
Task 12 gate. Stage those exact reported paths individually and commit them with
`git commit -m "fix: close verse alignment validation gaps"`. Skip this correction
commit when no files required correction. Do not amend earlier stage commits after
their review gates.

## Execution order and review checkpoints

Execute tasks in numeric order. Pause for review after Tasks 2, 5, 6, 9, and 12:

1. **After Task 2:** confirm the pure index semantics before any workflow adopts them.
2. **After Task 5:** review RTC/STC nonblocking behavior and legacy-plan dispatch.
3. **After Task 6:** review BIC mutation safety and TARGET-local output semantics.
4. **After Task 9:** review all three human report examples with real fixture display names.
5. **After Task 12:** review complete verification evidence before merge or release qualification.

Do not begin a later stage when its preceding gate is red. Fix the failing stage in
its own scope, rerun that stage's full gate, and only then proceed.
