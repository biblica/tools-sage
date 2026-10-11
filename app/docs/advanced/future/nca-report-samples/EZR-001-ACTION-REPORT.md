> SAMPLE (2026-10-08) — not produced by the current runtime. Rows marked † are invented to show a finding type.
# Number Consistency & Accuracy (NCA) — Action report

- Projects: `ukrNPUv1` checked against `HEB` (secondary: `NIV`)
- Scope: `EZR 1–2`
- Coverage: `COMPLETE` (78 numbered verses; 0 not assessed)
- Report languages: `en`

## Authority and analyzed snapshot

```text
Analysis               NCA
Job / Run              NCA-ukrNPUv1_20261008 / NCA-ukrNPUv1_20261008-001
WIP                    ukrNPUv1 (snapshot 2026-10-08)
Number index           SAGE_NUMBERS_TYPED_2026-10 (HEB: MACULA WLC; GRK: MACULA SBLGNT; NIV 2011)
Number Style Profile   none — reconstructed from this Job (see NUMBER-STYLE.md)
```

## Actionable findings

### NUMBERS_0001 — EZR 2:64 · Wrong number

- Category: `VALUE` · Action: `CORRECT`
- Numbers: WIP **42 316** · expected **42 360** (HEB, NIV agree)

**Issue.** The total of the whole assembly reads 42 316; the Hebrew and the NIV both give
42 360. The tens and units differ (шістнадцять "sixteen" for шістдесят "sixty") — likely a typing
or reading slip.

**Note for translator (copy below)**
```
EZR 2:64 — the total should be 42 360 (сорок дві тисячі триста шістдесят); the text has
сорок дві тисячі триста шістнадцять (42 316).
```

- **ukrNPUv1 †:** Усе зібрання налічувало сорок дві тисячі триста **шістнадцять** осіб,
- **HEB:** אַרְבַּע רִבּוֹא אַלְפַּיִם שְׁלֹשׁ־מֵאוֹת שִׁשִּׁים → 42 360
- **BSB:** The whole assembly numbered 42,360,
- **Also see — NIV:** EZR 2:64: 42 360

---

### NUMBERS_0002 — EZR 1:9 · Numbers attached to the wrong items

- Category: `ASSOCIATION` · Action: `CORRECT`
- Numbers: WIP 1000, 30, 29 · expected 30, 1000, 29 — same numbers, different order

| Item | WIP † | HEB / NIV |
|---|---:|---:|
| gold dishes (אֲגַרְטְלֵי זָהָב) | 1 000 | **30** |
| silver dishes (אֲגַרְטְלֵי־כֶסֶף) | 30 | **1 000** |
| silver pans (מַחֲלָפִים) | 29 | 29 |

**Issue.** The order change swaps the counts of gold and silver dishes: the text gives 1 000 gold
dishes and 30 silver dishes; the source has 30 gold and 1 000 silver.

**Note for translator (copy below)**
```
EZR 1:9 — gold dishes 30, silver dishes 1 000 (the two counts are swapped).
```

---

## Notes (no action needed)

### EZR 1:10 · Order differs, items correctly matched

WIP gives the items in a different order than the source; each number is still attached to the
right item (gold bowls 30, matching silver bowls 410, other articles 1 000). Recorded for the
reviewer only.

---

## Text-critical decisions (operator)

The Hebrew and the NIV disagree here. These are editorial decisions, usually footnoted; NCA
records which reading the WIP follows and whether a footnote is present. Not errors.

| Verse | HEB (MT) | NIV | WIP follows | Footnote in WIP | Status | Evidence |
|---|---|---|---|---|---|---|
| 1SA 13:1 | 2 | 30, 42 | NIV (30, 42) | yes (2 notes) | Recorded | NET Bible text-critical note |
| NEH 7:68 | — (verse absent in most MSS) | 736, 245 | HEB (verse omitted) | **no** | **Footnote recommended** | SAGE textual-variant registry |

**1SA 13:1** — apparatus evidence

- **[NET Bible text-critical note](https://netbible.org/bible/1%20Samuel+13)** — 1SA 13:1: “The MT does not have
  “thirty.” A number appears to have dropped out of the Hebrew text here … some Greek mss have “thirty years” …”
- **[NET Bible text-critical note](https://netbible.org/bible/1%20Samuel+13)** — 1SA 13:1: “The MT has “two years”
  here …”

**NEH 7:68** — apparatus evidence

- **SAGE textual-variant registry** — NEH 7:68 (scholarship: DIVIDED): Most Hebrew manuscripts omit the Western
  verse; some Hebrew manuscripts and Ezra 2:66 include the animals.

Suggested footnote basis (the translation has no footnote here): Most Hebrew manuscripts omit the verse; some
Hebrew manuscripts (cf. Ezra 2:66) include it.

**NEH 7:68 — suggested footnote (copy below)**
```
Деякі єврейські рукописи (пор. Езд. 2:66) містять: «Коней у них було 736, мулів 245».
```

---

## Content advisories (run was not stopped)

| Verse | Problem | Effect |
|---|---|---|
| NEH 7:68 | Verse marker missing in WIP | Not assessed; listed under text-critical decisions |
| EZR 2:3 | Verse text split across list lines (`\li`) | Joined for checking; no action |
| EZR 1:11 † | Footnote numeral `5,40` cannot be read as a number | Reported in NUMBER-STYLE.md as malformed |

Closing limitation: number checking only; wording, grammar and translation choices are outside
NCA (see STC/RTC).
