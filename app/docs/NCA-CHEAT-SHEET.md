# Number Consistency & Accuracy (NCA)

**SAGE NUMBERS CHECK** reviews numeric meaning, registered reading disclosures, and configured number presentation in one read-only WIP Project. Open **Main Menu → 5. Number Consistency & Accuracy (NCA)**. SAGE Maintenance is option **6**.

## Set up a Job

1. Import and qualify the supplied reference archive. Its contents remain unchanged; qualification receipts are separate.
2. Choose an onboarded WIP Project. Its language, script, recorded import date, and versification identify the input.
3. Choose one compatible configured **Number Style Profile**. One candidate resolves automatically; multiple candidates require a choice. If none exists, configure a copy of `system/config/profiles/numbers/number-style-template.yml` and import it. The shipped draft is not an active guide.
4. Review reference diagnostics and model routing. The independent Job is named `NCA-<Project>_<YYYYMMDD>`.

The style profile is mandatory even with presentation OFF. Record all questionnaire areas, using `NOT_SPECIFIED` when the guide supplies no rule. Unspecified areas remain unassessed. Profiles use resolved localdata `inputs/styleguides/numbers`; packages use `inputs/resources/numbers`.

## Choose Run checks

Three independent switches are initially ON:

- **Number accuracy** compares supported numeric meaning with immutable OL authority.
- **Presentation consistency** applies the guide to number forms, separators, contexts, and units.
- **Footnote review and recommendations** checks disclosure for the selected registered reading.

At least one check must be ON. OFF means **NOT ASSESSED**, never passed. Save or restore Job defaults before starting. Each Run seals its checks, style bytes/hash, package, target snapshot, mapping, and model/task identities. Resuming uses sealed evidence; revised defaults apply to new Runs.

## Read results

The Hebrew/Greek index is Authority 1. NIV is secondary evidence and never silently replaces OL values. Only whole registered alternatives are eligible. Unit conversions apply to their exact registered verse and preserve unrelated quantities, units, and qualifiers.

Numeric correspondence and disclosure are separate. An OL reading may pass numerically with a recommended-note advisory. Missing or inadequate required disclosure produces review. Unknown note understanding remains insufficient evidence. An adequate existing target note produces no duplicate add-note recommendation. With footnotes OFF, the report cannot claim acceptance **with a footnote**.

Reports preserve target-local navigation, Western lookup, differing stored OL references, exact evidence, provenance IDs, selected readings, and coverage. Registered OL absence at NEH 7:68 is not an ordinary pass. Unsupported interpretation, unindexed coordinates, and missing coverage remain visible; completed execution does not establish all-clear assessment.

`REFERENCE_LINEAGE_INCOMPLETE` records 47 rows and 51 values missing from the supplementary expression audit. The agreeing authoritative indexes remain usable: 4,392 numeric rows and 6,800 values. The original artifact's `PENDING_FINAL_RUN` gate remains unchanged; software qualification uses separate receipts.

**Findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities. SQS confidence checks have not been applied.** This limitation appears in zero-finding and incomplete reports and machine output. SQS is future functionality, not a current setup prerequisite.

## Canonical CLI

Run from the application directory with the managed Python environment. Global `--settings` and `--json` options precede the domain.

```sh
python -m sage.cli resource numbers import --archive /path/to/handover.zip
python -m sage.cli resource numbers inspect --package PACKAGE_ID
python -m sage.cli resource number-style import --path /path/to/configured-profile.yml
python -m sage.cli task create --workflow nca --operation numbers --wip PROJECT_ID --scope "MAT 1:1-17" --numbers-package PACKAGE_ID --number-style PROFILE_ID/VERSION
python -m sage.cli task execute --task /path/to/task-manifest.json
python -m sage.cli task submit --task /path/to/task-manifest.json
```

Use `--job-id` for an existing Job and `--run-id` for a sealed Run. New-Run switches are `--number-accuracy` / `--no-number-accuracy`, `--presentation-consistency` / `--no-presentation-consistency`, and `--footnote-review` / `--no-footnote-review`. Omitted switches use Job defaults. Package/style selectors belong to Job setup and cannot replace sealed Run evidence.

Resource inspection is local. Model-dependent execution requires the configured NCA route and provider readiness. `task execute --dry-run` validates the request without generating findings. NCA never edits Scripture or Paratext Notes XML. The experimental TUI retains its documented execution limitations; use the Control Center or CLI for NCA.

## Planned optimization

The [optimization design](superpowers/specs/2026-09-10-NCA-OPTIMIZATION-DESIGN.md) and [implementation plan](superpowers/plans/2026-09-10-NCA-OPTIMIZATION.md) propose full-scope batched extraction, validated input/checkpoint reuse, attributed bridge comparison, and chapter-organized reports. These are planned changes; the current runtime retains its existing behavior and bridge limitations.
