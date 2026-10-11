# NCA apparatus check of the number index

Every indexed verse checked against cached online apparatus: NET Bible text-critical notes
(netbible.org, cited by URL), the SBLGNT apparatus (Faithlife/SBLGNT, CC BY 4.0), OSHB
ketiv/qere (openscriptures/morphhb, CC BY 4.0) and Berean Standard Bible footnotes that report a
number in another text (BSB, public domain). An entry counts when it records a number.

NET excerpts (at most 240 characters per note, each with its link): NET Bible® notes copyright © 1996, 2019 by Biblical Studies Press, L.L.C., https://netbible.com. All rights reserved. Short excerpts of text-critical notes are quoted for commentary on number variants (fair use).

| Measure | Verses |
|---|---:|
| Indexed verses | 3814 |
| Original language and NIV differ | 1134 |
| … with a recorded number variant (text-critical decision) | 39 |
| … without one (rendering difference, not text-critical) | 1095 |
| Agreeing verses that still have a recorded number variant | 49 |
| Registered footnote guidance not confirmed by these sources | 2 |

Evidence entries by source: BSB 90, BSB_NOTE 58, KJV 90, LXX_BRENTON 68, NET_TC 47, PARALLEL 11, SBLGNT_APPARATUS 13, VULGATE_DRA 90.

Registered guidance without apparatus evidence here (kept; review): EZK 26:1, NEH 7:68

## NET references checked against public-domain witnesses

Each verse with a NET text-critical reference is read in four public-domain witnesses linked through their own versification: the Septuagint (Brenton 1851, `lxx.vrs`), the Vulgate (Douay-Rheims, `vul.vrs`), the KJV (Masoretic / Received text, `eng.vrs`) and the BSB (Berean Standard Bible, `eng.vrs`). The BSB is a modern rendering, cited with where to look next ("also see": MT or Greek NT, NIV, LXX, Vulgate, KJV); it never corroborates a variant. Details in `NET-CORROBORATION.tsv`.

| Verdict | Verses |
|---|---:|
| CORROBORATED | 34 |
| MT_ONLY | 12 |

- `CORROBORATED`: the Septuagint or Vulgate lacks the verse (while having its chapter), agrees with the NIV against the original language, or reads a number the original language does not have; in the NT the KJV (Received text) can corroborate the same way.
- A cited parallel passage (`parallel <ref>`) corroborates when it lies in a synoptic book pair (Samuel-Kings/Chronicles, Kings/Jeremiah 52 or Isaiah 36-39, Ezra 2/Nehemiah 7, the Gospels ...), shares a number with this verse, and our own index of it has an original-language number this verse lacks (1CH 19:18 seven thousand / 2SA 10:18 seven hundred).
- `MT_ONLY`: the versions and cited parallels agree with the original language; the variant rests on the NET note alone. Its basis is recorded, not quoted (column `NET_BASIS`, with the NET link):

| Verse | Basis cited by the NET Bible tc note |
|---|---|
| NUM 1:18 | Septuagint |
| 1SA 6:19 | Hebrew manuscripts |
| 2SA 15:7 | Septuagint (specific manuscripts or recension); Syriac Peshitta; Vulgate; Scribal-error explanation |
| 2SA 23:13 | Qere/Kethib; Hebrew manuscripts; Scribal-error explanation |
| 2SA 23:18 | Septuagint; Syriac Peshitta; Vulgate; Qere/Kethib; Hebrew manuscripts |
| 1CH 11:20 | Syriac Peshitta |
| 2CH 3:4 | Septuagint (specific manuscripts or recension); Syriac Peshitta; Conjecture or emendation |
| NEH 5:11 | Conjecture or emendation |
| JER 38:10 | Hebrew manuscripts; Conjecture or emendation |
| JER 52:20 | Septuagint; Parallel passage; Scribal-error explanation |
| MRK 10:34 | Syriac Peshitta; Greek NT manuscripts (A W Θ ƒ1,13 𝔐 sy) |
| ACT 27:37 | Greek NT manuscripts; Early versions (Coptic, Old Latin) (B sa) |

## Rule decisions checked against the apparatus

Every review row decided by the NIV number rule (REVIEWER `RULE-2026-10-08`) is checked here; details in `RULE-DECISIONS-APPARATUS.tsv`.

| Assessment | Rows |
|---|---:|
| SUPPORTED | 231 |
| TEXTUAL | 7 |

- `SUPPORTED`: no number variant is recorded at the verse, so the difference from the 2026-09-09 index is a counting matter, not a textual one; the rule decision stands.
- `TEXTUAL`: a number variant is recorded; the verse is a text-critical decision for the operator (the index keeps the original-language reading).
- `CONFLICT`: a removed value is named by a recorded variant; check the decision.
