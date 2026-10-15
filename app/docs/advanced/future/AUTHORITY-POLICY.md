# Future Policy — SAGE Authority Roles per Function

**Status: APPROVED 2026-10-07; not yet implemented.** The "Current" column
records what the workflow profiles enforce today; the "Proposed" column is the direction under
review. Nothing here changes a Job, Run, schema, or model handover until it is approved and
implemented.

## Context

SAGE is built by Biblica and is used primarily to check Biblica's NIV vernacular translations.
Biblica owns the NIV rights. MACULA was built by Clear Bible (acquired by Biblica) and released
under CC BY 4.0.

## Authority roles

Each governed resource has exactly one role. A role says what a resource may decide, not only
what it may be shown.

| Role | Resource | May decide | Never |
|---|---|---|---|
| `PRIMARY_OL` | `@HEB`, `@GRK`: bundled Hebrew and Greek SFM | What the original-language text says; the only basis for a BLOCKING original-language finding | Be replaced silently by another corpus |
| `OL_ANALYSIS` | MACULA Hebrew (WLC) + MACULA Greek (SBLGNT), aligned word by word to `@HEB`/`@GRK` | Lemma, morphology, syntax and number typing *for the bound OL text* | Override the `PRIMARY_OL` wording; text differences between MACULA and the bundled SFM are diagnostics, not corrections |
| `MODEL_TRANSLATION` | `@NIV`: NIV 2011 (2016 update), bundled snapshot of `usNIVv2` | How the NIV renders a verse; the expected model for an NIV vernacular | Outrank `PRIMARY_OL`; produce BLOCKING on its own |
| `REFERENCE` | The Job-bound reference Project (RTC, Targeted Check) | Differences between WIP and that reference | Stand in for the original-language text |
| `RENDERING_REFERENCE` | BSB: Berean Standard Bible (public domain since 2023-04-30), read from ebible.org `engbsb` (NCA apparatus only) | How a second modern translation renders a verse, cited with "Also see: MT/Greek NT, NIV, LXX, Vulgate, KJV"; its footnotes that report a number in another text are apparatus evidence | Decide a value, corroborate a variant on its own, or stand in for NIV or the original language |
| `CONTENT_SOURCE` / `LEXICAL_DONOR` | BIC bindings | BIC content (SOURCE) and vocabulary evidence only (DONOR) | Unchanged from BIC policy |

Precedence when roles disagree: `PRIMARY_OL` (read through `OL_ANALYSIS`) > `MODEL_TRANSLATION` >
`REFERENCE`. A function may use a lower role only for findings it labels with that role.

## Policy per function

| Function | Current | Proposed |
|---|---|---|
| **NCA** | HEB/GRK operator values are Authority 1; NIV values are secondary evidence; both come from the external 2026-09-09 package | Number index built in-repo: OL layer from `OL_ANALYSIS` (MACULA), NIV layer from bundled `@NIV`. BLOCKING only when `PRIMARY_OL` backs it. WIP that follows NIV against OL → see decision D1 |
| **STC** | WIP compared directly with the testament-correct HEB/GRK; the Reference Project is not an input | Unchanged decisive authority. Add `OL_ANALYSIS` lemma/morphology to the OL packet. NIV stays out, so STC remains an independent check against the source text |
| **RTC** | WIP vs one Job-bound Reference; structural and meaning stages get no OL; OL only for admitted closed-class source referrals | `@NIV` becomes the default Reference for NIV vernacular Jobs (operator can still bind another). Source referrals additionally get `OL_ANALYSIS` |
| **Targeted Check** | WIP + Reference only; no OL | Unchanged; `@NIV` may be the default Reference as for RTC |
| **Original-Language Review** | WIP + Reference + applicable configured HEB/GRK | Add `OL_ANALYSIS` |
| **BIC** | SOURCE is sole content authority; DONOR is vocabulary evidence only; bounded OL micro-check at material risk ≥ 2 | Unchanged authority. Add `OL_ANALYSIS` to the OL micro-check packet. NIV is used only if bound explicitly as SOURCE or DONOR |

## Resource notes

- **`@NIV` source:** the `usNIVv2` Paratext maintenance project, read locally at build time ("NIV 2011, updated 2016",
  66 books, NIV English custom versification). Because it is a live maintenance project, each
  build records per-book sha256 digests, and `niv-verify` fails if the project has changed.
  The parser must handle book introductions (`\imt`, `\im`) and list markers (`\litl`).
- **BSB (added 2026-10-09):** public domain, so unlike the NIV it may be cached and quoted in full; the
  witness cache is `localdata/.system/cache/apparatus/witnesses/engbsb` (from `engbsb_usfm.zip`).
- **Rights records** (`RESOURCE-RIGHTS-AND-PROVENANCE.md`): NIV — status CONFIRMED, copyright
  holder Biblica, Inc.; MACULA — © 2022–2024 Biblica, Inc., CC BY 4.0, with the attribution text from the rebuild
  [summary](../release/nca-index-rebuild/SUMMARY.md). Licenses, attribution lines, and changes for every shipped
  source: [Third-Party Data Notices](../projects-and-resources/THIRD-PARTY-NOTICES.md). MACULA's UBS domain fields (SDBH, MARBLE)
  are outside that grant and stay unused until UBS terms are confirmed.

- **NIV text (decided 2026-10-09, supersedes the 2026-10-07 hosting note below):** no NIV Scripture text is
  committed or quoted. NIV fair use allows at most 500 verses and less than 25% of the work. Verse
  text is quoted from the public-domain BSB; the NIV is cited as "other reference; also see" by its
  reference, values and number words. `NIV-EVIDENCE.tsv` keeps only a text SHA-256 per verse.
- **NIV hosting (decided 2026-10-07):** the full NIV is not committed (the SAGE repository is
  public). The number layer is built from the operator's local `usNIVv2` with
  `tools/build_numbers_index.py niv-build --niv <project>`, and SAGE ships only the evidence the
  index needs: typed values with surface words and offsets (the verse text and footnotes once shipped
  here were removed on 2026-10-09, see above; details in
  [NIV-SUMMARY.md](../release/nca-index-rebuild/NIV-SUMMARY.md)).

## Decisions (approved 2026-10-07)

- **D1 — NIV followed against OL:** NEEDS_REVIEW, labelled "follows NIV, differs from OL"
  (example: EZR 1:10, where the Hebrew has "second" and NIV omits it). Never PASS, never
  BLOCKING on NIV alone.
- **D2 — Distribution scope** of the bundled NIV snapshot: Biblica internal and partner
  translation teams.
- **D3 — Snapshot source:** the current `usNIVv2` text, i.e. the published NIV 2011.
- **D4 — STC independence:** confirmed; STC excludes NIV.
