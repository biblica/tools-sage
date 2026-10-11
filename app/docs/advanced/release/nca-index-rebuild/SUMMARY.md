# NCA original-language number index rebuild

Typed per-value records rebuilt from MACULA Hebrew (WLC) and MACULA Greek (SBLGNT) word data
with `system/tools/build_numbers_index.py`, compared verse by verse with the 2026-09-09
reference package. The runtime package is unchanged until every difference below is reviewed.

## Agreement with the current package

| Language | Verses | Agree | Changed | New | Dropped | Agreement |
|---|---:|---:|---:|---:|---:|---:|
| HEB | 4675 | 3746 | 305 | 18 | 606 | 80.1% |
| GRK | 1568 | 1156 | 87 | 1 | 324 | 73.7% |

Typed values: 5347 (CARDINAL 4917, FRACTION 55, ORDINAL 375).

## Review

`REVIEW-DECISIONS.tsv` has one row per verse that differs. For each, set `DECISION` to
`REBUILT` (the rebuilt values are right), `INDEX` (keep the current package values) or
`OTHER` (give `FINAL_VALUES`), with `REVIEWER` and a `NOTE`. A row whose package-only values
are all outside NCA's scope (counting convention 2.0: quantities and dates only) carries
`REASON` `SCOPE: ...` and `SUGGESTED_DECISION` `REBUILT` (1179 rows); the words are listed in `EXCLUDED-WORDS.tsv`. Known difference classes:

- the current index contradicts itself (e.g. twelve as 2;10 in NUM 7:3 but 12 in JOS 4:4;
  "a thousand thousands" as 1,000,000 in 1CH 21:5 but 1000;1000 in 2CH 14:8);
- numbers the current index missed (fractions such as LEV 22:14 "a fifth", 1SA 9:8
  "a fourth of a shekel");
- the 103 undocumented FINAL_OL_VERSE_OVERRIDE verses, now traceable to MACULA word IDs;
- policy classes the index never counts, listed with reasons in `EXCLUDED-WORDS.tsv`: מִשְׁנֶה
  ("second/double/matching", the EZR 1:10 case) and Greek ἅπαξ ("once").

## Sources

- Westminster Leningrad Codex (MACULA Hebrew, OSHB morphology): commit `df1ea5d85c8cb194278a874d6c670cd1d8abd97f`, sha256 `965cb0599beed2fe31283b615bcc369178141c0e718a66d97518d94309cfc124`. MACULA Hebrew Linguistic Datasets, available at https://github.com/Clear-Bible/macula-hebrew/ (CC BY 4.0).
- SBL Greek New Testament (MACULA Greek): commit `076282a3926625a5e670823b0738ce5f1e619528`, sha256 `7f71504fdee8659bdd9f85342e4103d645864c2851b8205915bb298f0c004cc5`. MACULA Greek Linguistic Datasets, available at https://github.com/Clear-Bible/macula-greek/ (CC BY 4.0).
