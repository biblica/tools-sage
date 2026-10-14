# RTC Check Policy — Beta

Reference Text Comparison (RTC) can split work into four check groups: structure/completeness, translation/meaning, language/readability, and consistency. All are enabled by default. They are set once per Job under **RTC defaults setting** and apply to every later **Run RTC on <WIP> with defaults**; they cannot change while a Run is open. Findings of a disabled group are filtered out in code even if the model reports them.

Actual multi-coordinate verse records remain indivisible source spans throughout planning. Every
internal RTC boundary is closed against both WIP and REFERENCE source-record bridges, while
canonical verse atoms remain the sole primary-coverage ownership keys. VRS mapping ranges do not
join review portions or block RTC; their coordinate differences remain report-only advisories and
structural candidates. During the later translation/meaning stage,
**structure/completeness** checks bridge coordinate mapping and **translation/meaning** checks the
complete bridged text against all corresponding WIP and Reference content. This applies when only
one Project uses a bridge and when both Projects use bridges.

Text-context policy is marker-class based:

| Mode | Detection/elevation rule |
|---|---|
| `NORMAL` | Content checked normally; marker context does not suppress an otherwise valid finding. |
| `MATERIAL_ONLY` | Detect normally, but omit non-material wording/style findings. Material semantic, consistency, or structural findings retain their normal severity. |
| `STRUCTURE_ONLY` | Evaluate marker/USFM structure only; enclosed content is not elevated as translation findings. |

Default contexts: `\\add` and `\\nd` = `MATERIAL_ONLY`; `\\f` = `STRUCTURE_ONLY`. Cross-references are always checked (`\\x` = `NORMAL`); SAGE compares their target numbers and footnote origins in code. Quotation structure is part of the structure/completeness group. Each finding states its USFM context and whether it is material, and SAGE applies the mode to it in code.

**Suppression never means LOW priority.** The policy answers whether a detection becomes a finding; it must not downgrade the finding's severity. The effective policy is written immutably to `check-policy.json` inside the Run.
## Finding references

RTC finding citations, original-language review requests, and their resolutions use the normal 12,000-character output-text limit. Long semicolon-separated citations are preserved in both action reports and plain-text notes. Every citation portion must still parse as a Scripture reference and satisfy the existing task-scope and stage-evidence checks; a longer citation does not expand the authorized scope.

## RTC defaults screen

The Job menu's **RTC defaults setting** opens this screen. It saves the Job's defaults; there is no per-Run toggle screen.

```text
╔══════════════════════════════════════════════════════════════════════╗
║ REFERENCE TEXT COMPARISON (RTC): JOB defaults                        ║
╚══════════════════════════════════════════════════════════════════════╝

  1. Save RTC defaults
  2. Restore defaults

> Checks [Choose number to toggle ON/OFF]
────────────────────────────────────────────────────────────────────────

  3. Check structure and completeness        ON
  4. Check translation and meaning           ON
  5. Check language and readability          ON
  6. Check consistency                       ON

> Text policy [Choose number to cycle]
────────────────────────────────────────────────────────────────────────

  7. Check added text        \add...\add*     MATERIAL ONLY
  8. Check Name of Deity     \nd...\nd*       MATERIAL ONLY
  9. Check footnotes         \f...\f*         STRUCTURE ONLY
> Original-language evidence [Choose number to toggle]
────────────────────────────────────────────────────────────────────────

 10. Adjudicate WIP-Reference variance        PROHIBITED

┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘
```

`NORMAL` means the marker remains available to the parser but does not modify content-checking or finding-elevation behavior. `MATERIAL_ONLY` omits non-material findings; it never converts them to LOW severity.



## WIP–Reference source adjudication

Reference Text Comparison (RTC) stores `source_text_drift_adjudication` as `PROHIBITED` or `ENABLED` for schema compatibility. New enabled RTC tasks seal `RTC_OL_REFERRAL_ADMISSION_V1`. A request is admitted if and only if:

1. The difference changes the core proposition rather than nuance, intensity, style, register, or preference.
2. WIP and REFERENCE communicate incompatible meanings.
3. It declares exactly one of `NEGATION_OR_POLARITY_CONFLICT`, `PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT`, `CORE_EVENT_OR_STATE_CONFLICT`, or `CORE_PROPOSITION_OMISSION_OR_ADDITION`.
4. Correctness genuinely requires the applicable original-language text.
5. Routed WIP, REFERENCE, grammar, and other non-OL evidence cannot settle it.
6. It asks one question at the smallest necessary Scripture scope.
7. The same normalized conflict is not requested twice.

Different subject, object, recipient, speaker, possessor, or other core participant identity may qualify without a reversal. Equivalent active/passive roles do not. Lexical nuance/intensity, equivalent paraphrase, grammar, readability, spelling, punctuation, USFM structure, style, ordinary consistency, and any issue resolvable from non-OL evidence never qualify. `dislike` versus `hate` remains RTC; `love` versus `hate` may qualify when every rule passes. Each admitted request produces one isolated selective task. SAGE routes OT requests to `HEB` and NT requests to `GRK`; this is advanced RTC option `#10`, not a Job binding or a standalone menu flow.

Targeted Check and standalone Original-Language Review code is parked for future work and is not exposed in the RTC or STC menus.
