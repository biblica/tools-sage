# NCA Number Style Profile — setup questionnaire

Date: 2026-09-09. Purpose: concrete setup contract derived from the archived `SAGE_NUMBER_STYLE_PROFILE.txt`, its unpacked working revision, and the user's required-profile decision. This is a design artifact, not an installed runtime profile.

Complete this once for a reusable profile. Each NCA Job selects one compatible configured profile, following RTC's profile selection pattern. A new Job may reuse the profile; it does not require writing a new style guide.

## Profile identity

| Field | Required entry |
|---|---|
| Profile name and stable ID | A recognizable name and unique identifier |
| Version | Explicit profile version |
| Recorded by and date | Operator identity and configuration date |
| Language and script | Project-compatible language identity and script |
| Applicability | Named Project or reusable language/style convention |
| Style authority | Named guide/document/version, or explicitly recorded operator-defined rules |
| Status | DRAFT while incomplete; CONFIGURED only after validation |

## Digit systems

Select the preferred digit system and any explicitly allowed alternatives. Digit system and language are separate choices.

| Choice | Digits |
|---|---|
| ASCII / European digits | `0123456789` |
| Arabic-Indic digits | `٠١٢٣٤٥٦٧٨٩` |
| Extended Arabic-Indic digits | `۰۱۲۳۴۵۶۷۸۹` |
| Devanagari digits | `०१२३४५६७८९` |
| Another decimal digit system | Supply the exact ordered ten characters for validation |

## Number presentation

Choose **words**, **digits**, **words followed by digits in parentheses**, or **not specified** for each band:

- 0–9
- 10–99
- 100 and above

Choose an explicit presentation rule or **not specified** for ordinals, fractions and ranges. Supply the exact expected notation where a guide distinguishes forms such as `1/2` and `½`, or a hyphen and en dash in ranges.

When words and parenthesized digits express the same quantity, they count as one semantic expression. A disagreement between the two representations is a numeric issue; it must not be hidden by collapsing them.

## Grouping and decimals

Select grouping: Western groups of three; Indic grouping; no grouping; or not specified. Record the exact grouping character, such as comma, period, ordinary space, nonbreaking space, narrow nonbreaking space, or Arabic thousands separator. Record the minimum number size at which grouping applies, or explicitly leave that rule unspecified.

Record the decimal separator independently. Grouping and decimal characters must not be ambiguous. Include an example that illustrates the chosen convention. The unpacked working form's truncated “space grouping (any” option does not authorize accepting every kind of space automatically.

## Context exceptions

For each context, choose **inherit the general rule**, **use an explicit override**, or **not specified**:

- Ages
- Dates and years
- Time
- Money
- Measurements
- Population and military counts
- Genealogies

An override states its words/digits, grouping and unit rules. A checked context without an actual rule is incomplete. When the context cannot be established with adequate evidence, report the limitation instead of applying a guessed exception.

## Units and locations

For **main text**, **headings** and **footnotes**, choose full unit names, abbreviations, or not specified. Where abbreviations are required, supply the permitted forms or a referenced approved list. State any spacing rules between quantity and unit.

Unit presentation does not authorize a unit conversion. Conversion acceptance comes from the authoritative registered unit policy. Heading and note numbers remain separate from main-text accuracy, except for canonical superscriptions covered by the reference contract.

## Meaning and uncertainty

Approximation and comparison meanings such as “about,” “at least” and “less than” must be preserved. The style guide can specify their presentation; it cannot remove their numeric meaning.

Textual-variant footnote requirements come from the authoritative registry and selected reading. This profile can govern numeric presentation inside a note, but cannot waive required disclosure or create a new alternate reading.

## Completion rules

Every rule area must contain a rule or an explicit **not specified / not applicable** choice. These choices remain visible as unassessed or inapplicable areas. They are not inferred from blank fields.

Validate compatibility, nonoverlapping number bands, unambiguous separators, complete overrides and stable rule IDs before selecting a profile. Save its exact version and content hash with every Run. Profile changes apply to new Runs.

The profile is required even if presentation consistency is OFF. Pre-Run toggles remain:

1. Number accuracy — ON/OFF.
2. Presentation consistency — ON/OFF.
3. Footnote review and recommendations — ON/OFF.

Default all three ON and reject all-OFF. Every Run report includes the required LLM capability limitation. Shared SQS confidence checks are future functionality and do not block profile setup or current execution.

## Source distinction

The archived questionnaire retains operator/date, approval, examples and additional-location fields. The unpacked working revision adds digit-system choices and words-with-parenthesized-digits options, and differs from its archived checksum. This questionnaire incorporates those useful design choices explicitly; the reference tables themselves remain byte-identical to the archive. No handover source was changed during finalization.
