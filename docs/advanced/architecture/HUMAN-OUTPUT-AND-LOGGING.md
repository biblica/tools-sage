# Human output, reports, and logging

SAGE stores canonical machine records once. One global Operator language is the primary language for human-facing output, and each Job may add one secondary reporting language.

## Interface localization

Terminal interface localization is separate from report-language authority. The workstation selection is stored under `interface.language` in `ecosystem.yml`; menu text is loaded from `system/config/localization/menu-localization.json`. v0.01beta ships complete localization entries for `en-US`, `en-GB`, `id`, `fr`, `ru`, and `pt-BR`. The source is formatted UTF-8 JSON so Operators can inspect and edit it without changing Python source. Functional choices remain numeric and footer navigation uses invariant `A`/`B`/`C`/`D` semantic controls.

Changing interface language does not change report language, Job bindings, Scripture language, grammar profiles, commands, identifiers, paths, status codes, or machine records.

## Current reporting configuration

```yaml
human_output:
  operator_language: en
  operator_language_policy:
    approved: [en]
    candidates: [id, fr, es, pt-BR, pt-PT, ru]
    operational_priorities: [id, fr]
    pilot_only: [hi-Deva, th, fil, tl, sw, ha-Latn]
  logs_and_reports:
    primary_language: OPERATOR_LANGUAGE
    secondary_language: null
    bilingual: false
    verbosity: normal
  translation_challenges:
    primary_language: OPERATOR_LANGUAGE
    secondary_language: null
    bilingual: false
    minimum_individual_urgency: 2
    aggregate_lower_levels: true
    consolidate_repeated_cause: true
    render_only_material_fields: true
  machine_records:
    language: canonical
    localise_codes: false
```

`operator_language` is global and defaults to `en`. It controls the primary language for operational log messages, non-JSON command summaries, INIT reports, validation summaries, status summaries, errors, guided-remediation messages, and translation-challenge reports. Recognized headings and labels are rendered in the effective language order; canonical values are not changed.

The legacy reporting policy still classifies report-language tags as `approved`, `candidates`, or `pilot_only`. That policy is distinct from the six interface-localization columns above. An advanced Operator may still edit the legacy reporting candidate lists in `ecosystem.yml` for controlled reporting evaluation, but that does not change which interface locales are shipped. In this localization patch the former global Operator-language menu is no longer part of the normal Configure surface; the approved target is to replace that legacy primary with required Job-owned reporting language. Until that migration is complete, changing interface language must never be treated as changing report language.

The legacy reporting operational-priority candidates remain Indonesian `id` and French `fr`, in that order. `operational_priorities` controls reporting implementation/evaluation attention only; it does not govern menu-localization availability.

Each Job may store one optional secondary reporting language:

```yaml
reporting:
  secondary_language: id
```

The setting is stored at `jobs/<tool>/<job-id>/job.yml` and can be changed from the active Job settings menu.

Effective report configuration is:

```text
global Operator language -> Job optional secondary language
```

When a Job secondary language is present and differs from the global primary, both ordinary reports and translation-challenge reports are bilingual. Without it, the Job reports only in the global Operator language. Projects do not own report-language configuration.

Every bilingual human report must carry a language-authority notice. The primary Operator-language rendering governs interpretation of the human report, but that status is not a guarantee that every finding is correct. The secondary rendering is an assistive translation with lower, unverified translation confidence and may contain ambiguity; the Operator must verify it against the primary rendering before acting. Producing a secondary rendering adds model usage and report compilation time and requires more human review than a single-language report. Canonical machine records, reason codes, evidence IDs, and Scripture coordinates remain authoritative in every language.

The menu localization source governs terminal menu labels and prompts only. Report rendering remains on the separate reporting contract above until the Job-owned reporting migration is implemented. IDs, paths, status codes, and machine records are never localized.

Language aliases may be used where supported: `OPERATOR_LANGUAGE`, `SOURCE_LANGUAGE`, `TARGET_LANGUAGE`, and `REFERENCE_LANGUAGE`. Project IDs, commands, paths, Scripture coordinates, candidate forms, hashes, status codes, and event codes are never localized.

## Final report storage and batching

Operator-facing SAW reports are chapter-scoped and published only under:

```text
SAGEdata/reports/<job-id>/<BOOK>/
```

Each chapter uses exactly two Operator files:

```text
<BOOK>_<CCC>_ACTION-REPORT.md
<BOOK>_<CCC>_OPERATOR-NOTE.txt
```

`<CCC>` is always a three-digit chapter number, including `001` for single-chapter books. The Markdown Action Report is canonical. The TXT Operator Note is a deterministic Python plain-text rendering of that exact finalized Markdown and never invokes AI independently. Machine JSON/JSONL, secondary-language rendering receipts, validation artifacts, and work-unit evidence remain under governed Job/Run storage.

Findings are ordered by canonical Scripture reference as far as possible: book/chapter/starting verse/ending verse, then stable finding identity. Work-unit completion order does not govern the Operator report order.

A finding groups all configured language renderings together. Human headings use resolved language names rather than ambiguous raw codes. Report headers use configured Project display names. Finding prose stays compact and resolves bare `WIP`/`REFERENCE`/`source` wording to the actual WIP or Reference Project ID, or to the routed `GRK OL`/`HEB OL` authority. The current per-finding projection is:

```markdown
### F-006 — ZEC 3:2-9

- Category: `MEANING`
- Action level: `CHANGE`
- Confidence: `HIGH`
- Evidence: `EV-14, EV-15`; Grammar rules: `GR-03`

**Issue — English**

<issue using configured Project display names>

**Proposed action — English**

<proposed action>

**Issue — Iranian Persian**

<assistive rendering>

**Proposed action — Iranian Persian**

<assistive rendering>

---
```

Use standard Markdown selectively: bold key Project names/action phrases and blockquote exact snippets when they materially help the Operator.

## Translation-challenge materiality

The canonical ledger retains validated challenge evidence. The human report lists a challenge individually only when it is material:

- urgency is at or above `minimum_individual_urgency`;
- an OL check changed the selected candidate;
- OL evidence increased the risk;
- SELF-CHECK materially revises or carries the issue forward.

Lower-level and automatically resolved matters are aggregated. Repeated causes over a contiguous range are consolidated. The default concise entry contains coordinate, category, urgency, selected form, one principal alternative, risk, evidence, and next action. Full candidate vectors, hashes, and diagnostic evidence remain in the canonical JSON ledger.

## Operational logs

SAGE writes:

- canonical JSONL events to `SAGEdata/.system/logs/operational.jsonl`;
- readable localized lines to `SAGEdata/.system/logs/operational.log`;
- the same readable lines to the terminal according to verbosity;
- localized headings and labels for recognized non-JSON command summaries.

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

SAGE uses approved catalog text. When a configured rendering is unavailable, it displays the canonical wording and records the fallback. Missing localization never blocks execution and must not be filled with uncertain specialist terminology.
## Bilingual finding grouping

When a SAW Action Report has a secondary rendering, keep each language's actionable prose together. Render the governing primary language first, then the secondary assistive rendering:

```text
**Issue — English**

<primary issue>
**Proposed action — English**

<primary action>

**Issue — Iranian Persian**

<secondary issue>
**Proposed action — Iranian Persian**

<secondary action>
```

Do not render all Issue blocks first and all Required-action blocks afterward. Evidence IDs, grammar-rule IDs, and OL evidence remain shared canonical fields after the language-grouped prose.
## Beta path normalization

Generated report paths must not repeat an identical adjacent scope segment. A whole-book report uses `SAGEdata/reports/<job-id>/<BOOK>/`; chapter or narrower scope directories may appear beneath `<BOOK>` only when they add coordinate information. Canonical `report_data/` follows the same rule.
