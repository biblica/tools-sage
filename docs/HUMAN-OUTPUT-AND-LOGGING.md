# Human output, reports, and logging

SAGE stores canonical machine records once and renders human-facing output through two independent language channels.

## Configuration

```yaml
human_output:
  operator_language: en
  logs_and_reports:
    primary_language: en
    secondary_language: id
    bilingual: true
    verbosity: normal
  translation_challenges:
    primary_language: id
    secondary_language: en
    bilingual: true
    minimum_individual_urgency: 2
    aggregate_lower_levels: true
    consolidate_repeated_cause: true
    render_only_material_fields: true
  machine_records:
    language: canonical
    localise_codes: false
```

`logs_and_reports` controls operational log messages, non-JSON command summaries, INIT reports, validation summaries, status summaries, errors, and guided-remediation messages. Recognised report headings and labels are rendered in the configured language order; canonical values are not changed. `translation_challenges` separately controls the linguistic challenge report consumed by the Team and SELF-CHECK.

For RC7 the **terminal UI/operator language is fixed to English**. Human reports are bilingual. A SAGE translation Project may store a `reporting` override with primary language, secondary language, and bilingual enabled. Effective report configuration is:

```text
Project override -> global human_output defaults
```

BIC uses the TARGET Project override; SAW uses the WIP Project override. Translation-challenge language ordering is derived from the effective Project pair so the translation language can be presented first while English remains available as the secondary report language. Project reporting changes do not localise commands, IDs, paths, status codes, or menu text.

The Project override selects rendering languages only. It does not make the Project an owner or storage location for report files.

Language aliases may be used where supported: `OPERATOR_LANGUAGE`, `SOURCE_LANGUAGE`, `TARGET_LANGUAGE`, and `REFERENCE_LANGUAGE`. Project IDs, commands, paths, Scripture coordinates, candidate forms, hashes, status codes, and event codes are never localised.

## Final report storage and batching

Run-local outputs provide evidence, validation, recovery, and audit history. After deterministic finalisation, SAGE batches the accepted findings into the owning Job's main human-report catalogue:

```text
jobs/<tool>/<job-id>/reports/<BOOK>/
```

The `<job-id>` path segment identifies the owning Job, not a Project. The filename contract is `<SCOPE>_<YYYY-MM-DD>_<SERIAL>_<REPORT-TYPE>`. For example, `GEN 1` becomes `GEN/GEN-001_2026-08-13_001_ACTION-REPORT.md`. The matching plain-text file uses the same basename and serial with `_OPERATOR-NOTE.txt`. Serial allocation is Job/book/date scoped, so reports from later Runs do not overwrite earlier reports.

This batching does not change Project identity or Scripture. The Job catalogue is SAGE-owned and must not be confused with the external Paratext Project folder. SAGE does not automatically publish report files into Paratext.

## Translation-challenge materiality

The canonical ledger retains validated challenge evidence. The human report lists a challenge individually only when it is material:

- urgency is at or above `minimum_individual_urgency`;
- an OL check changed the selected candidate;
- OL evidence increased the risk;
- SELF-CHECK materially revises or carries the issue forward.

Lower-level and automatically resolved matters are aggregated. Repeated causes over a contiguous range are consolidated. The default concise entry contains coordinate, category, urgency, selected form, one principal alternative, risk, evidence, and next action. Full candidate vectors, hashes, and diagnostic evidence remain in the canonical JSON ledger.

## Operational logs

SAGE writes:

- canonical JSONL events to `workspace-data/sage/logs/operational.jsonl`;
- readable localised lines to `workspace-data/sage/logs/operational.log`;
- the same readable lines to the terminal according to verbosity;
- localised headings and labels for recognised non-JSON command summaries.

Each line has one timestamp, severity, message, and short key-value context. Normal output does not include raw JSON or stack traces.

### Verbosity

| Mode | Human output |
|---|---|
| `--quiet` | completions, warnings, critical issues, and errors |
| default | normal stage transitions and material issues |
| `--verbose` | automatic resolutions and evidence-routing events |
| `--debug` | full diagnostic event stream; machine evidence remains in JSONL |

Command-line `--quiet`, `--verbose`, or `--debug` overrides the configured default for that invocation. `--json` suppresses human log lines on stdout and returns canonical structured output.

## Fallback

SAGE uses approved catalogue text. When a configured rendering is unavailable, it displays the canonical wording and records the fallback. Missing localisation never blocks execution and must not be filled with uncertain specialist terminology.
