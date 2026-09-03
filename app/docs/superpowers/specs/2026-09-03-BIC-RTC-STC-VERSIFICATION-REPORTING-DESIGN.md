# BIC/RTC/STC Versification Alignment and Project Reporting Design

## Status

Approved direction from the architecture review on 2026-09-03.

## Purpose

SAGE already loads, composes, validates, fingerprints, and exposes an effective
versification (VRS) for every Scripture Project. Finding validation also uses
canonical VRS equivalence. The remaining gap is earlier in the pipeline: work-unit
planning and routed-source selection still correlate Project records by identical
local book/chapter/verse numbers. That can omit the correct comparison record, or
report a false source gap, when two Projects express the same canonical Scripture
content under different local coordinates.

Human reports have a related identity gap. Machine roles such as `WIP`,
`REFERENCE`, `SOURCE`, `DONOR`, and `TARGET` are valid internal identifiers, but
several report titles, headings, authority blocks, and finding renderers expose
those roles or Project IDs instead of the configured Project display names.

This design makes canonical VRS alignment a reusable routing service, gives all
three workflows one sealed Project-identity model, and makes every human report
Project-specific without weakening machine auditability.

## Goals

1. Correlate BIC, RTC, and STC Project records through canonical VRS coordinates.
2. Preserve each Project's original local reference labels and exact SFM text.
3. Keep RTC/STC versification and source-coverage differences report-only.
4. Prevent BIC from writing ambiguous target coordinates.
5. Centralize Project identity, verse alignment, bounded Scripture packet creation,
   and common report context in focused reusable modules.
6. Render configured Project display names throughout human reports while retaining
   stable Project IDs in machine data and compact metadata.
7. Preserve all sealed legacy Jobs, Runs, plans, tasks, and reports byte-for-byte.

## Non-goals

- Changing the canonical versification from `org.vrs`.
- Treating a VRS mapping range as an indivisible source-text bridge.
- Hiding malformed USFM/USJ, duplicate or overlapping verse records, missing Book
  files, or other Scripture-integrity failures.
- Rewriting existing governed artifacts to use the new routing semantics.
- Re-enabling the paused Textual TUI workflow actions.
- Replacing the established RTC/STC chapter report paths or Job-owned report model.
- Splitting `menu.py` or `cli.py` merely to reduce line counts.

## Terminology and identity

The following terms are distinct:

- **Project-local coordinate:** the book/chapter/verse label present in one
  Project's USFM and interpreted by that Project's effective VRS.
- **Canonical coordinate:** a coordinate in the configured canonical VRS used only
  to correlate equivalent content across Projects.
- **Primary Project:** the Project whose local coordinates own work-unit boundaries
  and completion coverage.
- **Authority Project:** another Project whose local records are selected by
  canonical correspondence with the Primary Project.
- **Project display name:** the configured human-readable name sealed from the
  Project inventory when a task/report context is created.
- **Project ID:** the stable Paratext/SAGE identifier retained in machine records,
  fingerprints, paths, and secondary human metadata.

Machine roles remain uppercase and canonical. They must not serve as human Project
names.

## Workflow coordinate ownership

Each workflow has one explicit Primary Project:

| Workflow | Primary local coordinates | Canonically correlated Projects |
| --- | --- | --- |
| BIC | `SOURCE` for planning and content coverage | existing `TARGET`; optional OL evidence |
| RTC | `WIP` | `REFERENCE`; selective GRK/HEB evidence |
| STC | `WIP` | canon-selected primary `GRK` or `HEB` |

BIC `DONOR` remains a lexical-vocabulary stream. It is not treated as verse-aligned
content unless a later governed feature routes donor Scripture records as content
evidence.

An Operator scope is interpreted under the Primary Project's effective VRS. Work
units, context ownership, completion receipts, and finding targets continue to use
Primary Project local coordinates. Canonical coordinates are correlation keys, not
replacement labels.

## Canonical verse index

SAGE will introduce a `ProjectVerseIndex` built from one Project's validated
`EvidenceRecord` sequence and effective `VersificationSchema`.

For every source record it retains:

- the exact Project-local atomic coordinates;
- the union of canonical coordinates produced by the effective VRS;
- the original `EvidenceRecord` and exact SFM;
- mapping precision: `COORDINATE` or `EQUIVALENCE_GROUP`;
- deterministic Project-local ordering.

The index supports:

```python
canonical_refs_for_records(records) -> frozenset[VerseRef]
records_for_canonical(canonical_refs) -> tuple[EvidenceRecord, ...]
local_refs_for_canonical(canonical_refs, existing_only=False) -> frozenset[VerseRef]
align_records(primary_records, primary_index, authority_index) -> AlignmentSelection
project_coordinates(primary_refs, primary_index, target_index) -> CoordinateProjection
```

`AlignmentSelection` records the Primary local atoms, canonical atoms, selected
Authority local records, covered canonical atoms, missing canonical atoms, and
mapping precision. It is deterministic and serializable for planning audit.

`records_for_canonical()` is evidence-backed and returns only actual source
records. `local_refs_for_canonical()` is schema-backed by default, so BIC can
project coordinates into a valid empty TARGET Project; `existing_only=True` limits
it to local coordinates that already have records.

Equal-length VRS mappings remain positionally precise. Many-to-one mappings route
all relevant local records. Other unequal mappings route the complete equivalence
group because the VRS does not contain phrase-level attribution.

VRS exclusions are enforced when expanding valid citations and expected schema
coverage. If excluded coordinates nevertheless occur in source text, the existing
Project validation advisory is preserved and the raw record remains auditable; it
must not silently authorize an ordinary finding citation.

## Routed-SFM behavior

`SfmAnalysisRoute` remains the shared sizing and bridge-preservation engine. Its
stream selection becomes VRS-aware when Project verse indexes are supplied:

1. Primary records are selected and partitioned in their own local coordinates.
2. Their canonical equivalence set is calculated.
3. Every Authority stream selects its own local records whose canonical sets
   intersect the Primary canonical set.
4. Exact unmodified local SFM is rendered for every selected stream.
5. Token and byte sizing is performed on that exact routed SFM.
6. Primary completion coverage remains expressed in Primary local coordinates.

An actual multi-coordinate source record remains indivisible. When it occurs in an
Authority stream, its canonical coordinates are projected back to the Primary
Project only for source-bridge boundary protection. A mapping range found only in a
VRS file never becomes a work-unit boundary constraint.

Routes without verse indexes retain the current exact-local behavior for explicit
legacy compatibility. Every new BIC/RTC/STC route supplies indexes.

## Structural differences and blocking policy

RTC and STC never block solely because equivalent Projects use different local
coordinates or because an otherwise valid Authority Project lacks corresponding
text. They:

- keep the complete WIP-local primary coverage;
- route every available canonically corresponding Authority record;
- record missing canonical coverage as a report-only `STRUCTURE_PROBLEM`;
- describe the issue using the actual Project display names;
- finish as `COMPLETE_WITH_STRUCTURE_PROBLEMS` when analysis completes.

Malformed Scripture, missing governed input files, overlapping records, invalid
VRS syntax, or evidence that exceeds a hard route limit remains blocking.

BIC differs because it may write to a TARGET Project. BIC planning uses SOURCE
local coordinates and canonical alignment to select existing TARGET evidence. A
rewrite may project SOURCE coverage to TARGET local coordinates only when the
projection is deterministic and coordinate-precise. An ambiguous equivalence group
must stop before any TARGET write with `BIC_TARGET_VRS_ALIGNMENT_REQUIRED`. Existing
TARGET content and all Job/Run data remain unchanged. INSPECT may continue and
report the ambiguity because it is read-only.

## Project identity model

One immutable `ProjectIdentity` will carry:

```python
@dataclass(frozen=True)
class ProjectIdentity:
    role: str
    project_id: str
    display_name: str
    imported_date: str | None
    content_fingerprint: str
    vrs_schema_id: str
    effective_vrs_sha256: str
```

The identity is resolved once from the owning Job, Project inventory, effective
runtime Project, and compiled Project result. The configured display name is
primary. The Project ID is the fallback only when no display name was recorded.

`resource_bindings` remains the canonical machine role-to-ID map. Every new
BIC/RTC/STC writer seals `resource_display_names` as the human projection in tasks
and aggregate results. Compatibility readers tolerate that field being absent from
an older schema-2.4 artifact and fall back to its stable Project IDs. Report
regeneration uses sealed names when present rather than silently adopting a later
inventory rename.

## Human report contract

Component names identify the kind of report; they do not replace Project names.
Human-facing titles, Project fields, evidence headings, structural messages,
advisories, and finding prose use configured display names. Stable Project IDs may
appear once in parentheses or an audit metadata block.

Canonical templates are:

### BIC

```markdown
# <TARGET_PROJECT_NAME> — Translation Challenge Report

- Content Project: `<SOURCE_PROJECT_NAME>` (`<SOURCE_PROJECT_ID>`)
- Lexical Project: `<DONOR_PROJECT_NAME>` (`<DONOR_PROJECT_ID>`)
- Generated Project: `<TARGET_PROJECT_NAME>` (`<TARGET_PROJECT_ID>`)
```

### RTC

```markdown
# <WIP_PROJECT_NAME> compared with <REFERENCE_PROJECT_NAME>

- Project under review: `<WIP_PROJECT_NAME>` (`<WIP_PROJECT_ID>`)
- Comparison Project: `<REFERENCE_PROJECT_NAME>` (`<REFERENCE_PROJECT_ID>`)
```

### STC

```markdown
# <WIP_PROJECT_NAME> correspondence with <OL_PROJECT_NAME>

- Project under review: `<WIP_PROJECT_NAME>` (`<WIP_PROJECT_ID>`)
- Original-language authority: `<OL_PROJECT_NAME>` (`<OL_PROJECT_ID>`)
```

STC omits REFERENCE completely. It never prints `REFERENCE Project: NOT USED`.

Templates use placeholders only in source documentation/tests. Final generated
reports contain resolved values and no unresolved `<PROJECT_NAME_TOKEN>`. Internal
roles may remain visible in machine JSON, diagnostics intended for maintainers, and
formal evidence identifiers.

## Module boundaries

### `project_context.py`

Owns `ProjectIdentity`, inventory resolution, sealed display-name projections, and
role-aware report lookup. It must not read or render Scripture content.

### `verse_alignment.py`

Owns `AlignedEvidenceRecord`, `ProjectVerseIndex`, `AlignmentSelection`, canonical
coverage comparison, and deterministic target-coordinate projection. It depends on
`vrs.py` and `work_units.py` but not on CLI, menus, Jobs, or report renderers.

### `scripture_packets.py`

Owns bounded USJ/SFM extraction and packet metadata currently embedded in
`act_tasks.py`. It accepts already resolved Project/verse context and does not
choose workflow authority.

### Existing workflow adapters

`rtc_planner.py`, `stc.py`, and the BIC task adapter declare their stream roles,
Primary Project, policy, and failure behavior. They consume shared services rather
than reimplementing selection.

### `report_context.py`

Owns `ProjectReportContext`, Project-name lookup, safe replacement of internal role
words and bound Project IDs in model-authored human prose, and validation that no
unresolved Project placeholder remains. Existing BIC, RTC, and STC renderers remain
workflow-specific but consume this common context.

## Data flow

```text
Job bindings + Project inventory + compiled Project result
                         |
                         v
             sealed ProjectIdentity values
                         |
Validated EvidenceRecords + effective VRS
                         |
                         v
                ProjectVerseIndex
                         |
Primary local work units + canonical correlation
                         |
                         v
Exact local SFM packets + alignment audit metadata
                         |
                         v
Validated findings/results
                         |
                         v
Workflow renderer + sealed report context
                         |
                         v
Project-specific human report
```

## Versioning and legacy compatibility

- New RTC planning uses `SAGE_RTC_SFM_ROUTE_PLANNER_V5`.
- RTC V4 plans retain exact-local selection when resumed.
- New STC planning declares `SAGE_STC_SFM_ROUTE_PLANNER_V2`.
- STC plans without a planner version retain exact-local selection when resumed.
- Existing task schema `2.4` remains readable. The change uses existing
  `resource_bindings`, `resource_display_names`, VRS evidence, and additive
  alignment metadata; a schema bump is unnecessary unless implementation reveals
  a new required persisted field.
- Existing report files are not rewritten automatically. Regeneration of an old
  sealed artifact retains its stored identity and compatibility semantics.

## Error handling

- `VERSE_ALIGNMENT_SCHEMA_MISSING`: a new route lacks an effective Project VRS.
- `VERSE_ALIGNMENT_PROJECT_MISMATCH`: records and index belong to different
  Projects.
- `BIC_TARGET_VRS_ALIGNMENT_REQUIRED`: a BIC write cannot project SOURCE coverage
  to one deterministic TARGET-local span.
- Existing RTC/STC source gaps remain report-only structural issues.
- No error handler may replace a Project name with a component name when a sealed
  `ProjectIdentity` is available.

## Testing strategy

Tests use synthetic VRS pairs with visibly different coordinates, including
`2CO 13:14 = 2CO 13:13`, many-to-one continuations, one-to-many equivalence groups,
exclusions, and actual source bridges.

Required layers:

1. Unit tests for indexes, selection, coverage, exclusions, and deterministic
   target projection.
2. SFM-slicer tests proving exact routed text and projected bridge boundaries.
3. RTC/STC planning and task tests proving cross-VRS evidence selection without
   blocking.
4. BIC tests proving coordinate-precise writes and fail-before-write ambiguity.
5. Report golden tests proving display names are used and unused roles are absent.
6. Compatibility tests for RTC V4, unversioned STC plans, and existing task 2.4
   artifacts.
7. Full schema, package, documentation-contract, and pytest validation.

No pytest test invokes a live provider.

## Acceptance criteria

1. A WIP local coordinate mapped to another canonical coordinate routes the correct
   REFERENCE or OL local record.
2. RTC/STC report-only structure issues are based on canonical coverage, not equal
   local numbers.
3. Actual Authority verse bridges still protect Primary boundaries; VRS-only ranges
   do not.
4. Finding citations reject excluded coordinates and continue to authorize valid
   cross-VRS citations.
5. BIC never writes an ambiguously projected TARGET span.
6. New BIC/RTC/STC tasks seal real Project display names for every bound Project.
7. BIC, RTC, and STC reports use the specified Project-name templates throughout.
8. STC reports contain no REFERENCE field or `NOT USED` substitute.
9. Machine artifacts retain canonical role identifiers and stable Project IDs.
10. Legacy sealed artifacts remain readable without mutation.
11. Schema validation, package validation, documentation contracts, and the full
    automated test suite pass.
