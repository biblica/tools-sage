# PCC Flow: Reference Lists and WIP Lists

How the Phrase Consistency Checker's two functions (master reference lists, and PCC Jobs with their WIP lists) fit together, what each step reads and writes, and which
decisions carry from one step to the next. Operator steps: [PCC Cheat Sheet](../../PCC-CHEAT-SHEET.md).
Design and phase history: [PCC implementation plan](../../superpowers/plans/2026-11-02-PCC-IMPLEMENTATION-PLAN.md).

## 1. Two functions and their objects

```
 FUNCTION 1: MASTER REFERENCE LISTS (shared)          FUNCTION 2: PCC JOBS (one per WIP)
 ───────────────────────────────────────────          ──────────────────────────────────────────────────
 complete REFERENCE text ──build──▶ master v1         Job ── pins ──▶ its own WIP list (clone of a master)
 (usNIV, NVI, idKKH ...)            │                 │                 │ ▲
                                    ▼ curate          │     changes ────┘ │ update from a newer master
 another master ──build from──▶ master v1 ... vN ◀────┼──── merge (Operator: all / chosen / workbook)
                                    │                 ├─ terms Run: locate the WIP list's concepts in the SOURCE
                                    └─ cloned by ────▶├─ glossary: the WIP's TARGET renderings (journal)
                                       any number     ├─ check Run: WIP vs approved renderings
                                       of Jobs        └─ decisions on findings → scoped rules
```

| Object | Belongs to | Holds | Changes by |
|---|---|---|---|
| **Master list** (`rl_id`) | one reference text | key concepts (original-language key), their senses and SOURCE wordings, statuses KEEP/PROPOSED/DROP, notes, lineage | a new **version** only (build, curation, merge); versions are immutable and checksummed |
| **WIP list** (`rl_id`, build mode `LOCAL`) | one Job (one WIP) | a full copy of a master version (`build.parent`) plus this WIP's changes against it (`build.local`) | a new version for every change made in the Job, and for every update from the master |
| **PCC Job** | one WIP | bindings (SOURCE, optional secondary SOURCE, WIP), TARGET language, the **pin** of its WIP list, Runs, the glossary journal | Runs, glossary imports, decisions, re-pin |
| **Glossary journal** | one Job | TARGET rendering rules (ACCEPT/REJECT, scope, state PROPOSED/APPROVED/STALE/REVOKED) and finding decisions | append-only review events |

**Rules (PO 2026-11-26, plan D21 and D22).** Master lists live outside Jobs and are reused by every Job on their
text. A Job clones the master it pins; everything changed for that WIP goes to the Job's WIP list, never to the
master and never into the Job's own files. The master changes from a Job only when the Operator merges chosen
changes into it. When the master later drops a concept, the master wins unless the WIP list explicitly kept it.

## 2. Function 1: reference-list flows

### 2.1 Build from a text (mode `SCRATCH`)

```
REFERENCE text ─▶ read (canonical order) ─▶ align with MACULA Greek/Hebrew ─▶ inventory ─▶ realize ─▶ senses ─▶ select ─▶ store v1
                        cached under localdata/.system/cache/pcc-alignment     │
                                                                               └─ Paratext Biblical Terms (optional, read only)
```

- **Inventory**: Paratext Biblical Terms when given (later: the shipped Key Concepts package, plan P5b-5a).
- **Realize**: each original-language occurrence takes the reference tokens aligned to it.
- **Senses**: split by the reference's own head word and case (D19).
- **Select**: kept when anchored, recurring (≥ 3 verses, list setting) and rendered by a real wording (D17).
  Everything else is counted under `left_out` by reason.

### 2.2 Build from another list (mode `INHERIT`, plan P5b-5)

```
base list A (rl_id_A, vK) ──▶ carry concepts by concept_key ──▶ realize in text B (B's own alignment) ──▶ new list
                                 KEEP/PROPOSED ─▶ PROPOSED         wordings come from B, never from A
                                 DROPPED ─────▶ left out (DROPPED_IN_BASE)
                                 WORDING (no OL key): same language only, else listed as not carried
```

| Text of the new list | Result |
|---|---|
| another text (usNIV → NVI, usNIV → idKKH) | a **new `rl_id`**, v1; every carried concept is `PROPOSED` until reviewed; lineage `derived_from = A@vK` |
| the same text as A (rebuild) | the **next version of A**; statuses kept |

The base list is never written. Measured 2026-11-26 on John: usNIV list (141 concepts) → idKKH: 108 carried and
located, 31 below the recurrence bar in idKKH, 1 multi-word Biblical Terms phrase not locatable (it needs its
verse list, which inheritance does not carry yet), 1 not rendered.

### 2.3 Curate and extend (mode `MERGE`)

All three write the next version of the same list and a change report under
`localdata/reports/pcc-reference-lists/`:

| Action | Input | Effect on the next version |
|---|---|---|
| Workbook import | `RL-<id>-v<n>.xlsx` with Status KEEP / DROP / NEW / blank | statuses, category, notes; `NEW` rows anchored and realized in the list's text |
| Add Operator wordings | CSV / TXT / XLSX, first column = SOURCE wording | each wording anchored (original-language key when the alignment allows, else a `WORDING` anchor) and realized; not found → kept without senses, reported |
| Add Biblical Terms | `BiblicalTerms.xml` | terms realized with the list's own settings; only concepts not yet on the list are added; dropped stay dropped |

Locating needs the list's reference text in this SAGE instance; without it, wordings are kept without senses and
the report says so.

### 2.4 WIP lists: clone, update, merge (plan D22)

```
master M vK ──clone──▶ WIP list W v1 (= M vK, no changes)
                         │  workbook / own wordings / Biblical Terms / moved phrases.txt
                         ▼
                       W v2 ... vN    build.local = changes of W against M vK
                         │
     M vK+1 (newer) ─────┤ update: re-apply W's changes on M vK+1 ──▶ W vN+1 (parent M vK+1)
                         │
                         └ merge: chosen changes ──▶ M newest + changes ──▶ M vK+2 ──▶ update W
```

A change is computed, never typed: on every save of a WIP list, PCC compares it with its master version.

| Change | Recorded when | Update from a newer master | Merge into the master |
|---|---|---|---|
| `ADD` (full entry) | the WIP list has a concept its master version does not | kept; retired when the master now has it; not applied when the master dropped that concept | added to the master |
| `SET status DROPPED` | the WIP list left out a master concept | kept; retired when the master no longer has the concept | the master drops it |
| `SET status ACTIVE` over a master drop | the WIP list explicitly kept a concept the master dropped | the explicit keep wins, and is reported | the master keeps it again |
| `SET status/category/notes` | the WIP list confirmed a PROPOSED concept or edited category or notes | applied; retired when equal to the master | applied to the master |

Merging always starts from the **newest** master version, so changes merged from other WIP lists meanwhile are
kept. The Operator merges all changes, chosen changes (by number), or the rows marked `Merge = YES` in the changes
workbook `RL-CHANGES-<list>-v<n>.xlsx`, where Category and Notes may be edited before they reach the master. After
a merge, PCC offers to update the WIP list from the new master version; merged changes then drop out of its change
list. Reports: `RL-MERGE-<master>-v<n>.md`, `RL-UPDATE-<list>-v<n>.md`.

## 3. Function 2: WIP-list flow (one Job)

```
create Job ─▶ clone master ─▶ terms Run ─▶ TERMS-LIST.xlsx ─▶ import renderings ─▶ review proposals
   │                                 ▲                                                    │
   │                                 │ new WIP-list version (re-pin)                      ▼
   │                                 │                                            check Run (needs WIP text)
   │                                 │                                                    │
   │                    SOURCE wordings missing from the terms list ◀── glossary imports  ▼
   │                    (added to the Job's WIP list, never to the Job)           PCC-CHECK.md, PCC-FINDINGS.xlsx
   │                                                                                      │
   └─ attach WIP once (if created without)                       decisions (APPROVE_VARIANT, REJECT_FORM, ...)
                                                                                          │
                                                                                          ▼
                                                                              rules in the journal ─▶ next check
```

1. **Create**: SOURCE, optional secondary SOURCE, WIP or TARGET language; then a master list (stored, built now,
   or none), which is cloned into the Job's WIP list. The Job ID does not change when a WIP is attached later.
2. **terms Run** (scope on the SOURCE): the WIP list's concepts are located in the SOURCE scope with fixed
   senses. Same text as the list → `CURATED`; another text → `PROVISIONAL`. Older Jobs' `phrases.txt` lines are
   still located until they are moved to the list.
3. **Renderings**: the fill-in sheet, Paratext TermRenderings, glossary bundles and the Operator's own list all
   create rules. The fill-in sheet records approved rules; the other three create proposals for review.
4. **check Run** (scope on the WIP): forward check per occurrence (`PC00`–`PC02`, `PC10`, `PC11`, `PC13`, `PC21`,
   `PC23`) and reverse scan (`PC12`); findings are clustered into issues. Best effort: below-bar findings are
   shown with their confidence, never withheld.
5. **Decisions**: `PCC-FINDINGS.xlsx` rows become rules (`GROUP`, `PASSAGE:<range>` or `OCCURRENCE` scope) or
   finding statuses. Among approved rules the most specific scope wins (occurrence > passage > group), so a
   narrower `REJECT` beats a broader `ACCEPT`; an `ACCEPT` and a `REJECT` of the same form at the same scope
   are a conflict: `PC23` for that group only.
6. **Re-pin**: rules carry over by concept and sense; rules whose group is gone become `STALE` (kept, never
   applied). Report `PCC-REPIN-<list>-v<n>.md`.

Integrity guards are the only stops: a Run seals the pin's package hash, and a changed package (`PCC_RL_CHANGED`)
or stale input stops it. Content problems become report lines.

## 4. Lifecycle example: one master, several WIPs

```
usNIV master v3 (curated)
   │ build from list (another text)
   ▼
idKKH master v1 (108 PROPOSED) ─ workbook review ─▶ v2 (KEEP/DROP decided)
   │
   ├─clone─▶ WIP list "idKKH - Karon Dori" v1 ── +12 wordings, 5 left out ──▶ v3   (Job PCC Karon Dori)
   │                                                                          │
   │         Operator merges 8 of the additions ──────────────────────────────┘
   ▼
idKKH master v3 ──▶ Karon Dori WIP list updated to master v3 (8 changes retired, 9 remain local)
   │
   └─clone─▶ WIP list "idKKH - Bonerate" v1 = master v3                              (Job PCC Bonerate)
             (has the 8 merged additions, none of Karon Dori's local choices; no rebuild)
```

TARGET renderings move between Jobs only on purpose, through a glossary bundle, and only into a WIP of the same
target language.

## 5. Where things are stored

| Data | Path |
|---|---|
| Master and WIP-list versions | `localdata/inputs/resources/reference-lists/<rl_id>/<version>/` (`MANIFEST.json`, `entries.jsonl`, `CHECKSUMS.sha256`); a WIP list's parent and changes are in its manifest |
| Alignment cache | `localdata/.system/cache/pcc-alignment/` |
| Job | `localdata/work/jobs/pcc/<job>/` (pin in the Job defaults, glossary journal and records, Runs) |
| List reports | `localdata/reports/pcc-reference-lists/` (`RL-DIFF`, `RL-COMPARE`, `RL-MERGE`, `RL-UPDATE`) |
| Job reports | `localdata/reports/<job>/` |
| Workbooks (list, changes) and bundles | `localdata/exports/pcc/` |

## 6. Not yet built

- Export/import of a list as one checksummed package for another SAGE instance (plan P5b-6).
- The shipped Key Concepts package as an inventory without Biblical Terms (plan P5b-5a).
- Carrying a multi-word Biblical Terms phrase's verse list into a list built from another list.
- Operator guide sections in the full [SAGE Help](../../OPERATOR-GUIDE.md) (plan P9).
