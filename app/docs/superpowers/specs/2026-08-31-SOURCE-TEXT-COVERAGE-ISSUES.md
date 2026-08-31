# Source Text Coverage Issues Design

## Requirements

1. The bundled GRK resource owns authoritative custom versification corrections for coordinates genuinely absent from its SFM text.
2. A valid WIP coordinate with no corresponding text in an otherwise ready RTC REFERENCE or STC primary original-language resource must not abort planning, task creation, submission, aggregation, or report publication.
3. The run reports the difference as a source-text issue and never silently removes the WIP coordinate from planned or reviewed coverage.
4. WIP coverage remains exact. Missing or malformed WIP data remains blocking.
5. Missing source files/books, malformed source USFM, invalid bridge boundaries, unavailable governed resources, and result/plan coverage drift remain blocking.

## Data contract

Runtime differences are separate from Project versification diagnostics and use `source_text_issues`:

```json
{
  "status": "REPORT_ONLY",
  "code": "SOURCE_PRIMARY_COVERAGE_MISMATCH",
  "workflow": "STC",
  "source_stream": "GRK:PRIMARY",
  "source_project_id": "GRK",
  "scope": "JHN 5:1-6",
  "reference": "JHN 5:4",
  "message": "GRK:PRIMARY has no source text at JHN 5:4; the run continued without inventing comparison evidence."
}
```

The collection is carried by planning packages, sealed task manifests, normalized results, aggregate results, and human-readable RTC/STC reports. Source comparison status is `COMPLETE_WITH_SOURCE_TEXT_ISSUES` when the collection is nonempty.

## Runtime behavior

- The shared SFM slicer requires exact primary coverage from WIP. RTC REFERENCE and STC `GRK:PRIMARY`/`HEB:PRIMARY` streams contribute all text actually present.
- A source packet may be header-only when a valid bounded scope contains no source verse. It records zero source coordinates and does not synthesize wording.
- Source-text issues are controller-derived structural facts, not model-generated Scripture findings. Provider instructions prohibit inventing absent source wording.
- WIP analytical completion still reconciles every planned WIP coordinate; comparison status independently reports unavailable source coordinates.

## Validation boundary

Only coordinate-level comparison-source absence is report-only after the resource has compiled into a ready state. Parser errors, missing governed resources, unsafe bridge cuts, immutable plan/result drift, and incomplete WIP coverage remain blocking.
