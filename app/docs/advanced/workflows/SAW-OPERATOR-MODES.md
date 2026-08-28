# SAW Operator modes

This document defines the Operator-facing distinction between the four SAW check modes for Alpha. It governs menu wording, help text, Operator documentation, and examples. Machine operation names remain compatible with the current runtime unless an Alpha migration explicitly changes them.

## Operator decision rule

Use the smallest SAW mode that matches the Operator's intent:

| Operator intent | Use | OL Scripture | Typical scope |
|---|---|---|---|
| Review a passage systematically for translation/meaning quality against REFERENCE | **Reference Text Comparison (RTC)** | Not supplied to ordinary stages; when option 11 is enabled, SAGE may route only a bounded unresolved source-rendering conflict to selective OL adjudication | Chapter, section, book, or other planned RTC scope |
| Review WIP systematically for direct correspondence with the primary source text | **Source Text Correspondence (STC)** | **Yes**, PRIMARY GRK for NT or PRIMARY HEB for OT; REFERENCE is not evidence | Chapter, section, book, or other planned STC scope |
| Answer one specific question about the WIP using the WIP and authorized REFERENCE | **Targeted Check** | **No** | One issue, passage, feature, or tightly bounded question |
| Answer one specific question that requires direct Greek/Hebrew evidence | **Original-Language Review** | **Yes**, exactly the applicable configured OL resource | Verse or short verse range with one explicit OL question |

In shorthand:

```text
Reference Text Comparison (RTC) = broad systematic WIP+REFERENCE comparison
Source Text Correspondence (STC)   = systematic WIP+PRIMARY-OL correspondence
Targeted Check                    = one bounded question, no OL Scripture
Original-Language Review          = one bounded question requiring OL Scripture
```

## 1. Reference Text Comparison (RTC)

Choose **Reference Text Comparison (RTC)** when the Operator wants SAGE to perform the normal, systematic SAW Reference Text Comparison workflow across the selected scope rather than investigate one preselected issue.

Example Operator intents:

- "Run Reference Text Comparison (RTC) on Amos 1."
- "Review Philippians for translation and meaning issues."
- "Check this chapter systematically against the REFERENCE."

Reference Text Comparison (RTC) is a composite governed operation. Its structural and translation/meaning stages do not receive OL Scripture. If option 11, **Adjudicate WIP–Reference variance**, is `ENABLED`, the meaning stage defers every material content-bearing variance whose correctness depends on the source. SAGE automatically routes OT requests to Job-bound Hebrew and NT requests to Job-bound Greek. Grammar, readability, punctuation, spelling, USFM/structure, style, and ordinary consistency remain direct findings. This internal adjudication is not the separate detailed Original-Language Review, which requires one explicit bounded question.

Use Reference Text Comparison (RTC) when the Operator does not already know the specific issue that needs investigation.

## 2. Source Text Correspondence (STC)

Choose **Source Text Correspondence (STC)** when the Operator wants a systematic, independent review of how the bounded WIP corresponds to the testament-appropriate primary original-language authority. NT routes WIP + PRIMARY GRK; OT routes WIP + PRIMARY HEB. STC does not consume REFERENCE Scripture or RTC findings.

STC findings are limited to `OMISSION`, `ADDITION`, `VARIATION`, and `CONSISTENCY`. Surface variation is only a candidate; every primary coordinate must be analytically completed even when no finding is emitted.

## 3. Targeted Check

Choose **Targeted Check** when the Operator already has one specific concern or question and the question can be answered from the governed WIP, REFERENCE, and other explicitly routed non-OL local evidence.

Examples:

- "In John 1:3, is the participant reference clear in the WIP?"
- "Check whether the key term is used consistently in Romans 3:21-26."
- "Does the WIP preserve the contrast expressed by the REFERENCE in this paragraph?"
- "Check only the quotation-boundary issue in Matthew 5:17-20."

A Targeted Check must remain bounded to the declared question. It must not broaden into Reference Text Comparison (RTC).

**Targeted Check never receives Greek or Hebrew Scripture.** If answering the question requires direct original-language adjudication, use Original-Language Review instead.

The beta Operator term is **Targeted Check**. The current machine operation remains `focused` for compatibility until a deliberate schema/CLI migration changes it.

## 4. Original-Language Review

Choose **Original-Language Review** when the Operator has one bounded question whose answer requires direct examination of the applicable configured Greek or Hebrew resource.

Examples:

- "In John 1:3, does the Greek support the grammatical relationship represented by the WIP?"
- "In Romans 5:1, what grammatical relationship in the Greek is relevant to this specific WIP/REFERENCE difference?"
- "In Psalm 2:7, does the Hebrew evidence support the relationship represented in the WIP?"

Original-Language Review is not a general commentary or unrestricted word study. It must have:

- one explicit focus;
- a verse or short verse-range scope;
- the selected WIP and REFERENCE;
- exactly the applicable configured Greek or Hebrew resource for the task.

If no direct OL evidence is required, use Targeted Check instead.

## Operator examples: choosing between modes

### Example A — broad quality review

Operator concern:

> "I want SAGE to check all translation/meaning issues in Romans 1."

Use: **Reference Text Comparison (RTC)**.

Reason: the Operator is asking SAGE to discover and assess issues systematically. A specific issue has not been selected in advance.

### Example B — known issue, no OL required

Operator concern:

> "In Romans 1:16, check whether the WIP makes the participant reference ambiguous compared with the REFERENCE."

Use: **Targeted Check**.

Reason: one bounded issue is already identified and can be checked against WIP/REFERENCE evidence without direct Greek/Hebrew analysis.

### Example C — known issue requiring OL evidence

Operator concern:

> "In Romans 1:16, does the Greek grammatical structure support the relationship represented by the WIP?"

Use: **Original-Language Review**.

Reason: the question explicitly requires direct Greek evidence.

### Example D — Operator asks for a "focused" look

Operator concern:

> "Focus on the pronoun in John 1:3."

Do not infer OL merely from the word "focus". Determine the evidence requirement:

- if the question is whether the WIP is clear/consistent against the REFERENCE, use **Targeted Check**;
- if the question is what the Greek/Hebrew directly supports, use **Original-Language Review**.

## Menu wording

The selected SAW Job menu should expose the four modes directly:

```text
╔══════════════════════════════════════════════════════════════════════╗
║ SAW CHECKS                                                          ║
╚══════════════════════════════════════════════════════════════════════╝

WIP                          <project>
REFERENCE                    <project>

Active Run
  Check                      <Reference Text Comparison (RTC) / Source Text Correspondence (STC) / Targeted Check / Original-Language Review>
  Task                       <current task / NONE>
  Scope                      <scope>
  Progress                   <status>

  1. Continue active Run
  2. Reference Text Comparison (RTC)
  3. Source Text Correspondence (STC)
  4. Targeted Check
  5. Original-Language Review

┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main Menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘
```

When an active Run exists, **Continue active Run** must show enough context above the menu for the Operator to know exactly which Job, check mode, task, scope, and progress will resume.

`A. Back` returns to the SAW Job setup menu. History, reports/exports, recovery, and Job configuration do not belong on this execution menu; they remain available from their appropriate management/reporting surfaces.

## Terminology mapping

| beta Operator wording | Current machine/runtime wording | Rule |
|---|---|---|
| **Reference Text Comparison (RTC)** | `rtc` | Canonical public name and machine operation. |
| **Source Text Correspondence (STC)** | `stc` | Canonical independent WIP-to-primary-OL correspondence operation. |
| **Targeted Check** | `focused`; historically "Focused Check" | Change Operator-facing prose to Targeted Check. Preserve `focused` machine identifier until deliberate migration. |
| **Original-Language Review** | `ol` | Keep machine identifier `ol`; use full Operator term on first reference. |

Do not use **Basic RTC**: it implies reduced rigor. Use **Reference Text Comparison (RTC)** as the canonical beta Operator term. Do not use **Focused Check** as the canonical beta Operator term because "focused" describes scope but can be misread as implying original-language investigation.
## Compact execution feedback

The default Operator terminal must not print provider receipts, ACT paths, selection modes, repeated submission states, or aggregate JSON paths while a normal SAW Run is progressing. Stable Run parameters are printed once, followed by one replaceable work-unit progress line:

```text
SAW_paPCVv1-usNIVv2
========================================================================

paPCVv1 checked against usNIVv2
Checking Reference Text Comparison (RTC) for PHM
Using gpt-5.6-terra High

------------------------------------------------------------------------
Working on SAW work unit 1/3: PHM 1:1-7      |
```

The spinner rotates in place through `| / - \`. Technical execution data remains in governed machine receipts and diagnostic surfaces.
