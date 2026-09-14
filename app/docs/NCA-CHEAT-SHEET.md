# Number Consistency & Accuracy (NCA)

**SAGE NUMBERS CHECK** reviews numeric meaning, registered reading disclosures, and configured number presentation in one read-only WIP Project. Open **Main Menu → 5. Number Consistency & Accuracy (NCA)**. SAGE Maintenance is option **6**.

## Set up a Job

1. SAGE includes the qualified NCA reference tables. A standard installation selects the bundled package automatically; no archive import is required. Review any reference diagnostics shown.
2. Choose an onboarded WIP Project. Its language, script, recorded import date, and versification identify the input.
3. Choose one compatible configured **Number Style Profile**. One candidate resolves automatically; multiple candidates require a choice. If none exists, configure a copy of `system/config/profiles/numbers/number-style-template.yml` and import it. The shipped draft is not an active guide.
4. Review reference diagnostics and model routing. The independent Job is named `NCA-<Project>_<YYYYMMDD>`.

The style profile is mandatory even with presentation OFF. Record all questionnaire areas, using `NOT_SPECIFIED` when the guide supplies no rule. Unspecified areas remain unassessed. Profiles use resolved localdata `inputs/styleguides/numbers`; additional imported packages use `inputs/resources/numbers`. The bundled reference remains read-only under Core `system/resources/numbers`.

## Choose Run checks

Three independent switches are initially ON:

- **Number accuracy** compares supported numeric meaning with immutable OL authority.
- **Presentation consistency** applies the guide to number forms, separators, contexts, and units.
- **Footnote review and recommendations** checks disclosure for the selected registered reading.

At least one check must be ON. OFF means **NOT ASSESSED**, never passed. Save or restore Job defaults before starting. Each Run seals its checks, style bytes/hash, package, target snapshot, mapping, and model/task identities. Resuming uses sealed evidence; revised defaults apply to new Runs.

After choosing checks and scope, the menu seals the Run and displays its scoped preflight. This shows Western reference expectations, indexed and unindexed coordinates, protected groups, the mandatory profile, enabled checks, initial extraction batch estimates, blocked inputs, missing WIP coverage, and any scope expansion. A protected bridge may include verses outside the requested range; those exact additions remain visible. Resuming uses the same sealed inputs.

Batch estimates use the same routed-SFM limits and enabled body/note/heading streams as execution. They are planning information, not measured time, cost, or model qualification. Independent correspondence and footnote calls, retries, and checkpoint reuse depend on the evidence.

## Read results

The Hebrew/Greek index is Authority 1. NIV is secondary evidence and never silently replaces OL values. Only whole registered alternatives are eligible. Unit conversions apply to their exact registered verse and preserve unrelated quantities, units, and qualifiers.

Numeric correspondence and disclosure are separate. An OL reading may pass numerically with a recommended-note advisory. Missing or inadequate required disclosure produces review. Unknown note understanding remains insufficient evidence. An adequate existing target note produces no duplicate add-note recommendation. With footnotes OFF, the report cannot claim acceptance **with a footnote**.

One report covers each Run, organized by WIP book and chapter. A group crossing chapters appears once with links from other chapters; each canonical finding is counted once and links to its protected WIP range. If row ownership is unresolved, the report keeps the parent range and explicit uncertainty. Missing WIP groups without proven target coordinates appear under **Unlocated WIP coverage**; their Western ledger describes coverage, not a WIP location.

Each group retains exact per-row OL evidence, readings, note assessments, provenance, and available limitations. Repeated source expression IDs remain local to their Western row. Reports preserve target-local navigation, Western lookup, differing stored OL references, exact evidence, provenance IDs, selected readings, and coverage. Registered OL absence at NEH 7:68 is not an ordinary pass. Unsupported interpretation, unindexed coordinates, and missing coverage remain visible; completed execution does not establish all-clear assessment.

Reports retain the full handover counters, indexed/unindexed coverage, and complete/partial/unsupported extraction totals. Initial planned extraction calls are separate from observed physical calls, failures, and reused checkpoints. Historical evidence without a retained plan count displays **NOT RECORDED**. Partial, unsupported, unindexed, or missing evidence cannot establish a pass.

`REFERENCE_LINEAGE_INCOMPLETE` records 47 rows and 51 values missing from the supplementary expression audit. The agreeing authoritative indexes remain usable: 4,392 numeric rows and 6,800 values. The original artifact's `PENDING_FINAL_RUN` gate remains unchanged; software qualification uses separate receipts.

**Findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities. SQS confidence checks have not been applied.** This limitation appears in zero-finding and incomplete reports and machine output. SQS is future functionality, not a current setup prerequisite.

## Canonical CLI

Run from the application directory with the managed Python environment. Global `--settings` and `--json` options precede the domain.

```sh
python -m sage.cli resource numbers inspect
python -m sage.cli resource number-style import --path /path/to/configured-profile.yml
python -m sage.cli task create --workflow nca --operation numbers --wip PROJECT_ID --scope "MAT 1:1-17" --number-style PROFILE_ID/VERSION
python -m sage.cli task execute --task /path/to/task-manifest.json --dry-run
python -m sage.cli task execute --task /path/to/task-manifest.json
python -m sage.cli task submit --task /path/to/task-manifest.json
```

Use `--job-id` for an existing Job and `--run-id` for a sealed Run. New-Run switches are `--number-accuracy` / `--no-number-accuracy`, `--presentation-consistency` / `--no-presentation-consistency`, and `--footnote-review` / `--no-footnote-review`. Omitted switches use Job defaults. Package/style selectors belong to Job setup and cannot replace sealed Run evidence.

Resource inspection is local. Model-dependent execution requires the configured NCA route and provider readiness. `task execute --dry-run` validates the request and returns scoped `preflight` metadata without contacting a completion provider or generating findings. NCA never edits Scripture or Paratext Notes XML. The experimental TUI retains its documented execution limitations; use the Control Center or CLI for NCA.

## Optimization and qualification

Full-scope bounded extraction, validated checkpoint reuse, attributed bridge comparison, and chapter reports are implemented. The [optimization design](superpowers/specs/2026-09-10-NCA-OPTIMIZATION-DESIGN.md) and [implementation plan](superpowers/plans/2026-09-10-NCA-OPTIMIZATION.md) record the contracts and remaining qualification work. Provider-free tests establish software behavior; they do not establish actual-model language accuracy, cost, or performance.

The `--numbers-package` selector is optional for a new Job; omission selects the bundled Core reference. `resource numbers inspect` also defaults to the bundled reference. Use `resource numbers import --archive ...` only to add another qualified package.

Final bundled-table validation, ambiguous-reading notes and known NIV continuation limits: [validation report](advanced/release/NCA-BUNDLED-REFERENCE-VALIDATION.md).
