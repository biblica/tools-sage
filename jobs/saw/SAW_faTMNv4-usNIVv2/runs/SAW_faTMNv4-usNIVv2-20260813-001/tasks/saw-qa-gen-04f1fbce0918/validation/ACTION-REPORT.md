# SAW Action Report

- Task: `saw-qa-gen-04f1fbce0918`
- Operation: `qa`
- Stage: `TRANSLATION_AND_MEANING_QA`
- Scope: `GEN 1:1-3:24`
- Coverage: `COMPLETE` (80 coordinates)

## Answer

Completed translation-and-meaning QA for the full bounded scope.

## Actionable findings

### SAW-QA-GEN-3F13C16F37-F001 — GEN 1:14

- Category: `MEANING`
- Action level: `CHANGE`
- Confidence: `HIGH`

**Issue:** The WIP renders the lights as signs for «فصل‌ها، روزها و سال‌ها» (seasons, days, and years), whereas the reference includes sacred times. The sacred/appointed observance component is not conveyed.

**Required action:** Revise the expression for «فصل‌ها» so that the signs also mark the intended sacred or appointed times, while retaining days and years.

**Evidence IDs:** WIP, REFERENCE

### SAW-QA-GEN-3F13C16F37-F002 — GEN 2:14

- Category: `MEANING`
- Action level: `CHANGE`
- Confidence: `MEDIUM`

**Issue:** The WIP says the Tigris «به سوی شرق آشور جاری است» (flows toward the east of Assyria), while the reference locates it along the east side of Ashur. The directional wording can change the geographic relation.

**Required action:** Revise the wording to express that the river runs along or on the east side of Ashur, not toward its east.

**Evidence IDs:** WIP, REFERENCE

### SAW-QA-GEN-3F13C16F37-F003 — GEN 2:23

- Category: `TERMINOLOGY`
- Action level: `CHANGE`
- Confidence: `HIGH`

**Issue:** The WIP has Adam call the woman «نسا», followed by a note claiming it means woman. This is not the ordinary Persian term «زن» and makes the naming statement unclear.

**Required action:** Replace or explain the nonstandard term with an understandable Persian rendering for “woman,” preserving the stated relationship to man.

**Evidence IDs:** WIP, REFERENCE, PROJECT-GRAMMAR

### SAW-QA-GEN-3F13C16F37-F004 — GEN 3:13

- Category: `QUOTATION`
- Action level: `CHANGE`
- Confidence: `HIGH`

**Issue:** The woman's reply ends with «مار مرا فریب داد» (the serpent deceived me), omitting the reference's concluding statement, “and I ate.”

**Required action:** Add the woman's admission that she ate the fruit within the quoted reply.

**Evidence IDs:** WIP, REFERENCE

### SAW-QA-GEN-3F13C16F37-F005 — GEN 3:20

- Category: `GRAMMAR`
- Action level: `CHANGE`
- Confidence: `HIGH`

**Issue:** The parenthetical naming explanation is malformed: «حَوّا (یعنی «زندگی» نامید)». Its punctuation and clause attachment obscure that Adam named his wife Eve and that the name is being explained.

**Required action:** Repair the parenthetical and sentence structure so that the name explanation is grammatical and unambiguous.

**Evidence IDs:** WIP, REFERENCE, PROJECT-GRAMMAR

**Grammar rule IDs:** FA-GR-013, FA-GR-015

### SAW-QA-GEN-3F13C16F37-F006 — GEN 3:23

- Category: `PARTICIPANT_REFERENCE`
- Action level: `CHANGE`
- Confidence: `HIGH`

**Issue:** The reference says that the Lord God banished “him,” the man, but the WIP changes the object to «آنان» (them). This changes the explicitly named participant of the action.

**Required action:** Revise the pronoun and clause so that the banishment explicitly refers to the man, consistent with the reference.

**Evidence IDs:** WIP, REFERENCE, PROJECT-GRAMMAR

**Grammar rule IDs:** FA-GR-008

### SAW-QA-GEN-3F13C16F37-F007 — GEN 3:24

- Category: `PARTICIPANT_REFERENCE`
- Action level: `CHANGE`
- Confidence: `HIGH`

**Issue:** The reference says that God drove out “the man,” but the WIP again uses «آنان» (them). This does not preserve the reference's explicit singular participant reference.

**Required action:** Revise the participant reference to “the man” and retain the singular continuity of the reference.

**Evidence IDs:** WIP, REFERENCE, PROJECT-GRAMMAR

**Grammar rule IDs:** FA-GR-008
