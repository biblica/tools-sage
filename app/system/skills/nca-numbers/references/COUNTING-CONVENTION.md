# NCA numeric counting convention, version 2.0

NCA checks **numbers that state a quantity or a date**: twelve men, 200 years, five liters,
a third of a hin, half an hour, on the fourteenth day of the first month. A number must be
written as a number (a numeral or number word) and express a quantity of something. One convention decides which
words count and what value each gets. SAGE's own number data is built with the same
convention, so a difference SAGE later finds is a translation question and never a
difference in counting rules.

Not counted: a word that only implies a number ("tithe", "twice", "double", "sevenfold"); how
often something happens ("seven times", "three times a year"); a fraction of a group or place
rather than of a measure or time ("a third of the city", "half the tribe"); a pronoun or idiom
("should one walk", "one of you will", "no one"); a rank or sequence ("the first one", "a third
time", "first of all"); "both"; "a pair"; and indefinite plurals ("thousands", "tens of
thousands").

Return every counted number as a value plus one kind:

| Kind | Use for |
|---|---|
| `CARDINAL` | quantities: counts, amounts, ages, measures, durations, and numbers inside dates |
| `ORDINAL` | an ordinal inside a date or time: "the seventh month", "the third day", "the ninth hour" |
| `FRACTION` | a part of a measure or time unit: half a hin, a third of a shekel, half an hour |
| `PERCENT` | a percentage or "out of a hundred" |
| `APPROX` | a quantity marked as approximate: about 3000, some forty |

## Rules

1. Count every quantity or date number written as a word or numeral, in reading order,
   preserving repeats.
2. A cardinal counts when it states how many or how much: "twelve men" is 12, "seven of every
   kind" is 7, "forty days" is 40. "One" counts only with the thing it numbers: "one man",
   "one log of oil", "in one day" are 1; "one of you", "one is no more", "should one walk",
   "the one who", "no one", "one another" are not counted.
3. An ordinal counts only inside a date or time of day: "on the fourteenth day of the first
   month" is 14, 1; "in the second year of Darius" is 2; "the six hundredth year" is 600.
   Rank and sequence ordinals are not counted: "the first one", "a fifth son", "a third time",
   "the third captain", "first of all".
4. Dates count each part separately, in reading order.
5. Frequency and implied numbers are not counted: "seven times", "three times a year", "twice",
   "once", "double", "sevenfold", "a hundredfold", "tithe". A stated product is one quantity:
   "ten thousand times ten thousand" is 100000000.
6. Fractions count only as a part of a measure or time unit, as exact rationals: "half a hin" is
   1/2, "a third of a shekel" is 1/3, "half an hour" is 1/2 (`FRACTION`). "A third of the city",
   "half the tribe", "a tenth of all" are not counted. A number of fraction measures counts the
   measures: "three-tenths of an ephah" is 3.
7. A compound that names one quantity is one value: "a cubit and a half" is 3/2, "two and a
   half" is 5/2, "forty-two thousand three hundred sixty" is 42360.
8. Separate quantities stay separate: "two or three" is 2, 3; "two or three thousand" is 2000,
   3000.
9. "A thousand", "a hundred" are 1000, 100; the indefinite article alone ("a man") is not a
   number.
10. Approximate quantities count at their stated value: "about three thousand" is 3000
    (`APPROX`).
11. Do not count indefinite plurals without a number ("thousands", "hundreds", "tens of
    thousands", "commanders of fifties"), "both", "a pair", numbers that are part of a proper
    name (Kiriath Arba, Three Taverns), verse or chapter numbers, note callers, or
    cross-references.
12. Numerals in any script count at their value; digit grouping and decimal marks follow the
    supplied parsing conventions.

## Examples

| Text | Values | Kinds |
|---|---|---|
| On the first day of the seventh month | 1, 7 | ORDINAL, ORDINAL |
| He sent twelve men | 12 | CARDINAL |
| He did it twice | — | — |
| seven times a year | — | — |
| a third of the city | — | — |
| half a hin of wine | 1/2 | FRACTION |
| a cubit and a half long | 3/2 | CARDINAL |
| about three thousand men | 3000 | APPROX |
| one of my brothers came | — | — |
| the first one married | — | — |
| bore Jacob a fifth son | — | — |
| both of them went | — | — |
| a tenth of an ephah | 1/10 | FRACTION |
| Saul has slain his thousands | — | — |
| двічі | — | — |
| другого місяця | 2 | ORDINAL |
| півтора ліктя | 3/2 | CARDINAL |
| близько трьох тисяч | 3000 | APPROX |
| un pour cent | 1 | PERCENT |
| in Kiriath Arba lived nine | 9 | CARDINAL |
