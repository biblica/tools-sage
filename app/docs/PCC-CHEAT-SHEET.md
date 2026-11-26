# Phrase Consistency Checker (PCC)

PCC helps a translation team render key biblical terms and phrases consistently. Open **Main Menu → 6. Phrase
Consistency Checker (PCC)**. PCC works locally and by fixed rules: it makes no model calls and never writes to
Paratext.

PCC has **two separate functions**:

| | Function | What it is | Where it lives |
|---|---|---|---|
| 1 | **Master reference lists** | A SOURCE list of key concepts built from one **complete reference text** (for example usNIV, idKKH). | Shared, outside every Job: `localdata/inputs/resources/reference-lists/` |
| 2 | **PCC Jobs** | One **WIP**, its own **WIP list** (a clone of a master list), and the WIP's **TARGET renderings** (its glossary). Kept up to date while the WIP is drafted. | Job: `localdata/work/jobs/pcc/<job>/`; its WIP list sits beside the masters |

A Job **clones** the master list when it pins it. Everything the team changes for that WIP (added wordings,
concepts left out, notes) goes to the Job's WIP list. The master changes only when the Operator **merges** chosen
additions and omissions into it, by menu action or by editing a changes workbook. A master list is built **once**
and reused: Karon Dori and Bonerate each clone the same idKKH master. How it fits together:
[PCC flow](advanced/workflows/PCC-FLOW.md).

## Menu map

```
6. Phrase Consistency Checker (PCC)
   1. Reference lists (SOURCE lists from reference texts)
   2. Open active PCC JOB
   3. Set active PCC JOB
   4. Add new PCC JOB (a WIP and its reference list)

Reference lists
   1. Show lists and versions                      masters, their versions, their WIP lists, the Jobs
   2. Build a new list from a reference text
   3. Build a new list from an existing list (another text, or a rebuild)
   4. Export a list for curation (workbook: KEEP / DROP / NEW)
   5. Import a curated workbook (new version)
   6. Add my own SOURCE wordings (CSV, TXT or XLSX; new version)
   7. Add Paratext Biblical Terms (new version)
   8. Compare two versions of a list
   9. Update a WIP list from its master
  10. Merge WIP-list changes into the master
   -- inside a Job only --
  11. Pin a master list to this JOB (cloned into this JOB's WIP list)
  12. Move this JOB's own wordings into its list   (older Jobs with a phrases.txt)

PCC JOB <id>
   1. Build SOURCE terms list (from the pinned reference list)    or: Continue PCC Run <id>
   2. Check WIP against the glossary
   3. Glossary (TARGET renderings and decisions)
   4. Reference list (this JOB's WIP list, pin, merge into the master)   the menu above, for this Job
   5. Manage PCC JOB: delete, recovery and diagnostics, attach a WIP (once)

Merge <WIP list> into its master
   1. Merge all changes into the master
   2. Choose changes to merge                      by number: 1,3,5-7
   3. Export the changes for manual edit (workbook)
   4. Import an edited changes workbook

Glossary
   1. Export the terms list to fill in renderings (Markdown and XLSX)
   2. Import the filled terms list
   3. Import Paratext TermRenderings (read-only proposals)
   4. Review proposed renderings
   5. Export a glossary bundle (renderings, for another WIP of this language)
   6. Import a glossary bundle from another WIP
   7. Import my own renderings list (wording, rendering(s)[, note])
   8. Import decisions on check findings (PCC-FINDINGS.xlsx)
   9. Review stale rules
  10. Revoke an approved rendering
```

Inside a Job, Reference lists options 4, 6, 7, 9 and 10 act on **this Job's WIP list**; outside a Job you choose
the list. Option numbers in the Job menu move up by one while a Run is open (option 1 is then **Continue PCC
Run**). **A** goes back one menu.

## Function 1: master reference lists

### Build a list from a reference text

**Reference lists → 2.** Choose the reference text, confirm its Paratext **Biblical Terms** list (if the project
has one), and give the list a title. PCC aligns the text with the Greek and Hebrew original. The first alignment
of a text takes a few minutes; later builds and terms Runs reuse it.

A concept is kept on the list only when it is a key term, occurs in **at least 3 verses** and is rendered by a
real wording in the text. The rest is counted under **Left out** (not in the text, not recurring, not rendered
by a wording). Each concept is split into **senses** by the reference's own wording: NIV *Jews* and
*Jewish leaders* are two senses of one Greek word.

### Build a list from another list

**Reference lists → 3.** Choose the base master list and version, then the text the new list is for.

- **Another text** (usNIV list → Spanish NVI, usNIV list → idKKH): a **new master list** is made. The concepts
  are carried over by their original-language key and located in the new text, so the wordings come from the new
  text, not the base. Every carried concept arrives as **PROPOSED** ("to review"): review them in the new list's
  workbook. Concepts the team **dropped** on the base list stay out. Wordings the team added by hand to the base
  list can only be carried into a text of the same language; others are named so you can add them in the new
  language.
- **The same text** (a rebuild, for example after the text was revised): the result is the **next version** of
  the same list, and every decision is kept.

The base list is never changed.

### Curate a list (workbook)

**Reference lists → 4** writes `RL-<id>-v<n>.xlsx` to `localdata/exports/pcc/`. In sheet **Entries**:

| Status | Meaning |
|---|---|
| `KEEP` | the concept stays on the list (also confirms a PROPOSED one) |
| `DROP` | the concept is left out (it is remembered: later builds from this list leave it out) |
| `NEW` | a new row: put the SOURCE wording in **Wordings**, leave **Concept key** empty |
| blank | no decision; a PROPOSED concept stays PROPOSED |

**Category** and **Notes** may be edited. **Reference lists → 5** imports the file as a **new version** of the list
it came from (a master or a WIP list) and writes `RL-DIFF-<id>-v<n>.md` to
`localdata/reports/pcc-reference-lists/`. A bad row is reported with its row number; the other rows still apply.

### Add your own wordings or Biblical Terms

- **6. Add my own SOURCE wordings**: a CSV, TXT or XLSX whose first column is a SOURCE wording (one per line; a
  header row `wording` is skipped). Each wording is located in the list's reference text. A wording that does not
  occur there is kept without senses and reported.
- **7. Add Paratext Biblical Terms**: the terms are located in the list's text with the list's own settings.
  Concepts already on the list are left as they are; dropped ones stay dropped.

Both write a new version and a report. The reference text must be in this SAGE instance to locate wordings.

### Versions

Every change writes a **new version**; an old version is never edited. A Job stays on the version it pinned until
it is re-pinned. **1. Show lists and versions** shows each master, its versions (how each was made), its WIP lists
(with their changes) and the Jobs. **8. Compare two versions** writes `RL-COMPARE-<id>-v<a>-v<b>.md`.

## Function 2: PCC Jobs and their WIP lists

### Create a Job

**PCC → 4. Add new PCC JOB.** Choose:

1. the **SOURCE** (the reference text the WIP is based on), and optionally a secondary SOURCE;
2. the **WIP**, or none yet (you can attach a WIP **once**, later, under Manage PCC JOB). Without a WIP you give
   the TARGET language tag;
3. the **master list**: pin a stored one, build one from the SOURCE now, build one from an existing list, or none
   for now. The master is **cloned** into this Job's own WIP list (`<master title> - <WIP>`), and the Job pins
   the clone.

A WIP with no text yet (for example Karon Dori before drafting) works: you can build its terms list and fill in
renderings before there is text to check.

### Change the Job's WIP list

**Job → 4 Reference list**, then 4–7 (workbook, own wordings, Biblical Terms). Every change writes a new version of
**this Job's WIP list** and offers the re-pin. The master and other Jobs are not affected.

An older Job pinned to a master directly is offered a clone the first time you change its list.

### Merge into the master

**Job → 4 → 10** (or **Reference lists → 10** outside a Job). The WIP list's changes against its master are:

| Change | Meaning |
|---|---|
| added | a concept or wording this WIP added |
| left out | a master concept this WIP dropped |
| kept although the master dropped it | an explicit keep |
| status / edited | a confirmed PROPOSED concept, or changed category or notes |

Choose how to merge:

- **1 Merge all changes** or **2 Choose changes** (by number, for example `1,3,5-7`);
- **3 Export the changes** to `RL-CHANGES-<list>-v<n>.xlsx`, set **Merge** to `YES` on the rows the master
  should get, edit **Category** or **Notes** if needed, then **4 Import** it.

The chosen changes are applied to the **newest** master version, so other changes made to the master meanwhile
are kept. A new master version and `RL-MERGE-<master>-v<n>.md` are written. PCC then offers to update the WIP list
from that master; merged changes drop out of its change list because the master now has them.

### Update from the master

**Job → 4 → 9** (or **Reference lists → 9**). When the master has a newer version, the WIP list's changes are
applied again on top of it, as the WIP list's next version, and the Job is offered the re-pin
(`RL-UPDATE-<list>-v<n>.md`):

- a change the master now has is retired (no longer needed);
- when the master **drops** a concept, the master wins, unless this WIP explicitly **kept** it (KEEP in its
  workbook); either way it is reported;
- a concept the master no longer has takes its changes with it.

### Build the terms list (terms Run)

**Job → 1.** Choose a scope. PCC finds where the WIP list's concepts occur in the SOURCE in that scope. A concept
in the same text the list was built on is **CURATED**; on another text it is **PROVISIONAL**.

### Fill in the TARGET renderings (Glossary)

1. **Glossary → 1** writes `TERMS-LIST.md` and `TERMS-LIST.xlsx` to `localdata/reports/<job>/`.
2. The team fills in the chosen rendering(s). Several renderings are separated by `;`; a rendering starting with
   `!` is a **rejected** rendering. **Scope** blank means the whole concept sense; `PASSAGE:<reference>` limits it.
3. **Glossary → 2** imports the sheet. Each rendering is recorded in the Job's journal.

Other ways to propose renderings, all of which arrive as **proposals** for **Glossary → 4 Review**:

- **3** Paratext `TermRenderings.xml` (read only);
- **6** a glossary bundle exported (**5**) from another WIP of the same language;
- **7** your own list: `wording, rendering(s)[, note]`.

If an import names SOURCE wordings that are not on the terms list, PCC offers to add them to **this Job's WIP
list** (a new version, then the re-pin). Build the terms list again and import the file again to propose their
renderings.

### Check the WIP (check Run)

**Job → 2.** Needs a WIP. Choose a scope. PCC compares every occurrence with the approved renderings (forward
check) and looks for approved TARGET forms with no matching SOURCE term (reverse scan). Reports:
`localdata/reports/<job>/PCC-CHECK.md` and `PCC-FINDINGS.xlsx`.

| Code | Meaning |
|---|---|
| `PC00` | consistent: every occurrence uses the approved rendering |
| `PC01` | consistent with an approved variant or inflection |
| `PC02` | uniform but not yet approved (or senses only provisional) |
| `PC10` | rendering variation: differing unapproved forms, or a rejected form |
| `PC11` | likely omission: no rendering where the SOURCE term occurs |
| `PC12` | possible insertion: a TARGET form where the SOURCE has no matching term (lower confidence) |
| `PC13` | negation/polarity difference (only when negation markers are declared) |
| `PC21` | not decidable: no WIP verse, or the alignment is too uncertain |
| `PC23` | conflicting rules of equal scope; that group is not assessed |

The check is **best effort**: findings below the confidence bar are still shown, with their confidence; nothing
is withheld. A content problem never stops a Run; only an integrity guard (for example a changed list package)
does.

### Decide on findings

Fill **Decision** in `PCC-FINDINGS.xlsx` and import it with **Glossary → 8**:

| Decision | Effect |
|---|---|
| `APPROVE_VARIANT` | the finding's forms become approved renderings |
| `REJECT_FORM` | the finding's forms become rejected renderings |
| `CONFIRMED_ISSUE` / `DISMISS` / `DEFER` | the finding keeps that status in later Runs until its text changes |

**Scope** (for the first two): blank or `GROUP`, `PASSAGE:<range>`, or `OCCURRENCE`. Run the check again to see
the effect.

### Keep the Job current

- **Re-pin** happens whenever the WIP list gets a new version (PCC asks). Renderings carry over wherever their
  concept and sense still exist; the others become **STALE** (kept, never applied). Report:
  `PCC-REPIN-<list>-v<n>.md`.
- **Glossary → 9 Review stale rules**: rules tied to WIP text that has since changed; mark them STALE or revoke.
- **Glossary → 10 Revoke**: a revoked rendering stays in the journal and is never applied again.
- **Job → 4 → 11** pins a different master. It replaces the Job's WIP list with a new clone; merge the old WIP
  list's changes first if the master should keep them.

### Older Jobs

A Job created before 2026-11-26 may have its own `input/phrases.txt`. **Job → 4 → 12** moves those wordings into
the Job's WIP list (cloning the master first if needed), re-pins the Job, and keeps the file as
`phrases.moved-<date>.txt`. Key terms imported into an older Job keep working for that Job.

## Example: Karon Dori and Bonerate (both from idKKH)

1. **Reference lists → 3**: build the `idKKH reference list` master from the curated usNIV list. Review the
   PROPOSED concepts in its workbook (**4**, edit, **5**) → master `v2`.
2. **Add new PCC JOB**: SOURCE idKKH, WIP Karon Dori, pin the idKKH master `v2` → the Job gets its WIP list
   `idKKH reference list - Karon Dori`.
3. While working on Karon Dori the team adds 12 wordings and leaves out 5 concepts → the Karon Dori WIP list
   `v2`, `v3`, ... The idKKH master is unchanged.
4. The team decides 8 of the additions are useful for every WIP: **Job → 4 → 10 → 2** (or the changes workbook)
   merges them → idKKH master `v3`, and Karon Dori's WIP list is updated to it.
5. **Add new PCC JOB**: SOURCE idKKH, WIP Bonerate, pin the idKKH master `v3` → Bonerate's own WIP list starts
   with the 8 merged additions, without Karon Dori's local choices. Karon Dori's renderings are not copied (they
   are another language).

## Files

| What | Where |
|---|---|
| Master lists and WIP lists (versions) | `localdata/inputs/resources/reference-lists/<list>/<version>/` |
| List workbooks | `localdata/exports/pcc/RL-<list>-v<n>.xlsx` |
| Changes workbook (manual merge) | `localdata/exports/pcc/RL-CHANGES-<wip list>-v<n>.xlsx` |
| List reports | `localdata/reports/pcc-reference-lists/` (`RL-DIFF`, `RL-COMPARE`, `RL-MERGE`, `RL-UPDATE`) |
| Terms list to fill in | `localdata/reports/<job>/TERMS-LIST.md`, `TERMS-LIST.xlsx` |
| Check reports | `localdata/reports/<job>/PCC-CHECK.md`, `PCC-FINDINGS.xlsx` |
| Re-pin reports | `localdata/reports/<job>/PCC-REPIN-<list>-v<n>.md` |
| Glossary bundle | `localdata/exports/pcc/<job>-glossary-bundle.json` |

A list built from licensed text or from Paratext Biblical Terms is marked **local only**: do not share it outside
your organization's license.
