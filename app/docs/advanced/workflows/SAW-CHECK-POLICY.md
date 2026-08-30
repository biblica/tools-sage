# SAW Reference Text Comparison (RTC) Check Policy — Beta

Reference Text Comparison (RTC) can split work into four check groups: structure/completeness, translation/meaning, language/readability, and consistency. All are enabled by default and may be toggled before the Run starts.

Verse bridges remain indivisible source spans throughout planning. Every internal RTC boundary is
closed against both WIP and REFERENCE bridge/equivalence spans, while canonical verse atoms remain
the sole primary-coverage ownership keys. During the later translation/meaning stage,
**structure/completeness** checks bridge coordinate mapping and **translation/meaning** checks the
complete bridged text against all corresponding WIP and Reference content. This applies when only
one Project uses a bridge and when both Projects use bridges.

Text-context policy is marker-class based:

| Mode | Detection/elevation rule |
|---|---|
| `NORMAL` | Content checked normally; marker context does not suppress an otherwise valid finding. |
| `MATERIAL_ONLY` | Detect normally, but omit non-material wording/style findings. Material semantic, consistency, or structural findings retain their normal severity. |
| `STRUCTURE_ONLY` | Evaluate marker/USFM structure only; enclosed content is not elevated as translation findings. |

Default contexts: `\\add` and `\\nd` = `MATERIAL_ONLY`; `\\f` and `\\x` = `STRUCTURE_ONLY`. Quotations are checked normally and are not an Operator policy toggle.

**Suppression never means LOW priority.** The policy answers whether a detection becomes a finding; it must not downgrade the finding's severity. The effective policy is written immutably to `check-policy.json` inside the Run.
## Operator setup screen

The classic UI presents primary actions first, then check toggles and text-policy selectors.

```text
╔══════════════════════════════════════════════════════════════════════╗
║ STANDARD RTC: LUK 1:1-10                                             ║
╚══════════════════════════════════════════════════════════════════════╝

  1. Run Reference Text Comparison (RTC)
  2. Restore defaults

> Checks [Choose number to toggle ON/OFF]
────────────────────────────────────────────────────────────────────────

  3. Structure and completeness        ON
  4. Translation and meaning           ON
  5. Language and readability          ON
  6. Consistency                       ON

> Text policy [Choose number to cycle]
────────────────────────────────────────────────────────────────────────

  7. Added text       \add...\add*     MATERIAL ONLY
  8. Name of Deity    \nd...\nd*       MATERIAL ONLY
  9. Footnotes        \f...\f*         STRUCTURE ONLY
 10. Cross-references \x...\x*        STRUCTURE ONLY

> Original-language evidence [Choose number to toggle]
────────────────────────────────────────────────────────────────────────

 11. Adjudicate WIP-Reference variance        PROHIBITED

┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main Menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘
```

`NORMAL` means the marker remains available to the parser but does not modify content-checking or finding-elevation behavior. `MATERIAL_ONLY` omits non-material findings; it never converts them to LOW severity.



## WIP–Reference source adjudication

Reference Text Comparison (RTC) stores `source_text_drift_adjudication` as `PROHIBITED` or `ENABLED` for schema compatibility. New enabled RTC tasks seal `SAW_OL_REFERRAL_ADMISSION_V1`. A request is admitted if and only if:

1. The difference changes the core proposition rather than nuance, intensity, style, register, or preference.
2. WIP and REFERENCE communicate incompatible meanings.
3. It declares exactly one of `NEGATION_OR_POLARITY_CONFLICT`, `PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT`, `CORE_EVENT_OR_STATE_CONFLICT`, or `CORE_PROPOSITION_OMISSION_OR_ADDITION`.
4. Correctness genuinely requires the applicable original-language text.
5. Routed WIP, REFERENCE, grammar, and other non-OL evidence cannot settle it.
6. It asks one question at the smallest necessary Scripture scope.
7. The same normalized conflict is not requested twice.

Different subject, object, recipient, speaker, possessor, or other core participant identity may qualify without a reversal. Equivalent active/passive roles do not. Lexical nuance/intensity, equivalent paraphrase, grammar, readability, spelling, punctuation, USFM structure, style, ordinary consistency, and any issue resolvable from non-OL evidence never qualify. `dislike` versus `hate` remains RTC; `love` versus `hate` may qualify when every rule passes. Each admitted request produces one isolated selective task. SAGE routes OT requests to Job-bound Hebrew and NT requests to Job-bound Greek. This internal adjudication is distinct from the separate detailed Original-Language Review.
