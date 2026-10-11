"""Count the numbers in one English (NIV) verse by the shared counting convention (2.0).

Deterministic word rules, no model: the same convention as the original-language builder
(skills/nca-numbers/references/COUNTING-CONVENTION.md), so a difference between the two
layers is a rendering question, not a counting one. NCA checks numbers that state a quantity
or a date; every number-like word that does not is kept as an exclusion with its reason.

Counted:
- every numeral (digits with group separators, "30", "1,000", "42,360"): the NIV writes its
  verified numbers this way, so no scope rule may exclude one;
- cardinals and numerals, composed into one value ("a hundred and thirty" is 130, "1,000" is
  1000, "forty-two thousand three hundred sixty" is 42360);
- "one" only with the thing it numbers ("one man", "one log of oil", "in one day");
- ordinals inside a date or time ("the seventeenth day of the second month", "the six
  hundredth year", "the ninth hour");
- fractions of a measure or a time unit ("a third of a hin", "half an hour"), with "and a half" folded into its number ("two and a
  half cubits", "a cubit and a half" is 3/2) and "three-tenths of an ephah" counted as 3
  measures, matching the original-language "three tenths" (עֶשְׂרֹנִים);
- "about/some/nearly N" (APPROX); a stated product stays one quantity ("ten thousand times ten
  thousand").

Excluded, with a reason: IMPLICIT_NUMBER ("tithe", "twice", "double", "sevenfold"), FREQUENCY
("seven times", "three times a year"), FRACTION_NO_MEASURE ("a third of the city", "half the
tribe"), PRONOUN_ONE ("should one walk", "one of you", "no one", "the one
who", "the Holy One"), RANK_ORDINAL ("the first one", "a fifth son", "a third time"), BOTH,
INDEFINITE_PLURAL ("thousands", "tens of thousands", "commanders of fifties"), PAIR ("a pair
of sandals"), PART_NOUN ("the halves") and NAME ("Three Taverns").
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re

F = Fraction

UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    # Archaic English (KJV, Douay-Rheims, Brenton): "threescore and ten", "fourscore and six".
    "score": 20, "twoscore": 40, "threescore": 60, "fourscore": 80, "fivescore": 100, "sixscore": 120,
}
_TENS_LIKE = {20, 30, 40, 50, 60, 70, 80, 90, 100, 120}
SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000}
PLURAL_SCALES = {"hundreds": 100, "thousands": 1000, "millions": 1000000}
PLURAL_GROUPS = {"tens": 10, "fifties": 50}  # "commanders of fifties and of tens"
ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50, "sixtieth": 60, "seventieth": 70,
    "eightieth": 80, "ninetieth": 90, "hundredth": 100, "thousandth": 1000,
}
PLURAL_FRACTIONS = {"halves": 2, "thirds": 3, "fourths": 4, "fifths": 5, "sixths": 6,
                    "sevenths": 7, "eighths": 8, "ninths": 9, "tenths": 10}
MULTIPLIERS = {"twice": 2, "thrice": 3, "double": 2}
APPROX_WORDS = {"about", "some", "nearly", "almost", "around", "approximately"}
# A following word that makes "a third" a part ("a third of the city", "add a fifth to it").
_PART_FOLLOWERS = {"of", "part", "to", "more", "in", "and", "or", "from", "for", "at", "on", "by", "with", "is",
                   "was", "will", "shall", "must", "are", "were", "be", "remains", ""}
# Words before "one" that make it a pronoun, not a quantity.
_PRONOUN_ONE_BEFORE = {
    "no", "any", "every", "each", "some", "which", "loved", "holy", "little", "living", "other", "last",
    "evil", "righteous", "wicked", "chosen", "anointed", "mighty", "beloved", "young", "dear", "favored",
    "such", "great", "faithful", "blessed", "lowly", "dead", "weak", "unclean", "poor", "nobody",
}
# Auxiliaries before "one" make it the generic pronoun ("should one walk", "how can one keep warm").
_AUXILIARIES = {"should", "would", "can", "could", "may", "might", "must", "shall", "will", "does", "did", "do",
                "has", "had", "is", "was", "are", "were", "if"}
# Words after "one" that show it stands alone rather than numbering a thing.
_ONE_STANDS_ALONE = {
    "of", "another", "anothers", "who", "whom", "whose", "that", "which", "by", "is", "was", "are", "were", "be",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must", "does", "did", "do", "has",
    "had", "and", "or", "but", "nor", "to", "in", "on", "at", "for", "from", "with", "after", "before", "as",
    "than", "else", "more", "there", "here", "again", "too", "also", "alone", "always", "himself", "herself",
    "he", "she", "it", "they", "i", "you", "we", "his", "her", "its", "their", "my", "your", "our", "the",
    "a", "an", "not", "never", "now", "then", "so", "like", "standing", "sitting", "came", "went", "said",
}
# Numbers that belong to a proper name.
_NAMES = {("three", "taverns")}
TIME_NOUNS = {"day", "days", "year", "years", "month", "months", "hour", "hours", "week", "weeks",
              "night", "nights", "generation", "generations", "watch", "time", "times", "sabbath", "sabbaths"}
# An ordinal is a date or time only next to one of these ("the third day", "the fourth watch").
DATE_NOUNS = {"day", "month", "year", "hour", "watch", "week", "sabbath"}
# Time units a fraction may be a part of ("half an hour", "a quarter of the day").
DURATION_NOUNS = {"day", "days", "hour", "hours", "year", "years", "month", "months", "night", "nights",
                  "week", "weeks"}
MEASURE_NOUNS = {
    "cubit", "cubits", "shekel", "shekels", "ephah", "ephahs", "talent", "talents", "hin", "hins", "homer",
    "homers", "cor", "cors", "bath", "baths", "omer", "omers", "seah", "seahs", "mina", "minas", "drachma",
    "drachmas", "denarius", "denarii", "stadia", "feet", "foot", "pound", "pounds", "mile", "miles",
    "span", "spans", "handbreadth", "handbreadths", "gerah", "gerahs", "beka", "measure", "measures",
    "liter", "liters", "litre", "litres", "kilogram", "kilograms", "gram", "grams", "meter", "meters",
    "inch", "inches", "yard", "yards", "acre", "acres", "log", "logs", "darics", "drachmas", "cab", "cabs",
    "lethek",
}

_TOKEN = re.compile(r"\d{1,3}(?:,\d{3})+|\d+|[A-Za-z]+(?:[-‑][A-Za-z]+)*|[.,!?;:“”\"—(]")
_SENTENCE = {".", "!", "?", "“", "\"", "(", ";", ":", "—"}


@dataclass(frozen=True)
class EnglishValue:
    """One counted English value with its exact place in the verse text."""

    value: Fraction
    kind: str
    role: str
    surface: str
    start: int
    end: int
    unit: str
    reason: str = ""
    referent: str = ""  # what the number counts: "gold bowls", "darics of gold", "descendants of Parosh"


@dataclass
class _Token:
    """One word, numeral or punctuation mark with its span in the verse."""

    text: str
    low: str
    start: int
    end: int


def _tokens(text: str) -> list[_Token]:
    """Split a verse into word, numeral and punctuation tokens."""
    return [_Token(m[0], m[0].lower(), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _cardinal(word: str) -> int | None:
    """Value of one cardinal word or hyphenated cardinal compound ("forty-two")."""
    parts = re.split(r"[-‑]", word)
    if all(part in UNITS for part in parts) and len(parts) <= 2:
        return sum(UNITS[part] for part in parts)
    return None


def _ordinal(word: str) -> int | None:
    """Value of an ordinal word or compound ("twenty-first")."""
    parts = re.split(r"[-‑]", word)
    if parts[-1] in ORDINALS and all(part in UNITS for part in parts[:-1]) and len(parts) <= 2:
        return sum(UNITS[part] for part in parts[:-1]) + ORDINALS[parts[-1]]
    return None


def _numeral(text: str) -> int | None:
    """Value of a digit numeral ("1,000" is 1000)."""
    return int(text.replace(",", "")) if text[0].isdigit() else None


def _is_pronoun_one(tokens: list[_Token], i: int, archaic: bool = False) -> bool:
    """'one' that does not number a thing: a pronoun, title or idiom (convention rule 2)."""
    token = tokens[i]
    previous = tokens[i - 1].low if i else ""
    following = tokens[i + 1] if i + 1 < len(tokens) else None
    sentence_start = i == 0 or tokens[i - 1].text in _SENTENCE
    if token.text == "One" and not sentence_start:
        return True  # the divine title: "the Holy One", "the One enthroned"
    if following is None or following.text in _SENTENCE or following.text == ",":
        return True  # "one is no more", "only one."
    after = tokens[i + 2].low if i + 2 < len(tokens) else ""
    if archaic and following.low == "and" and ((_cardinal(after) or 0) in _TENS_LIKE or (_ordinal(after) or 0) in _TENS_LIKE):
        return False  # archaic "one and twenty", "the one and twentieth day"
    if sentence_start and following.low == "day":
        return True  # "One day the angels came": narrative idiom, not a count
    if (previous, following.low) == ("at", "time") or following.low in {"case", "hand"} and previous == "the":
        return True  # "at one time" (formerly), "in the one case", "on the one hand"
    if previous in _AUXILIARIES or previous in _PRONOUN_ONE_BEFORE or _ordinal(previous) is not None:
        return True  # "should one walk", "no one", "the first one"
    if following.text[:1].isupper() or _cardinal(following.low) is not None:
        return True  # "one Peleg", "one two"
    return following.low in _ONE_STANDS_ALONE  # "one of you", "one who", "one another", "one by one"


def _date_context(tokens: list[_Token], first: int, last: int) -> bool:
    """Whether an ordinal names a date or time: "the third day", "the fourteenth of the month"."""
    after = [t.low for t in tokens[last + 1:last + 5] if t.text not in _SENTENCE and t.text != ","]
    if after[:1] and after[0] in DATE_NOUNS | {noun + "s" for noun in DATE_NOUNS}:
        return True
    return after[:3] in (["of", "the", "month"], ["of", "the", "year"]) or \
        bool(after[:1]) and after[0] in {"and", "or"} and _date_context(tokens, last + 1, last + 2)


def _role(kind: str, unit: str, after: list[str]) -> str:
    """Context role from the counted word: MEASURE, AGE, DATE, TIME or COUNT."""
    if unit in MEASURE_NOUNS:
        return "MEASURE"
    if unit in {"years", "year"} and after[:1] == ["old"]:
        return "AGE"
    if unit in TIME_NOUNS:
        return "DATE" if kind == "ORDINAL" and unit in DATE_NOUNS else "TIME"
    return "COUNT"


def count(text: str, *, archaic: bool = False) -> list[EnglishValue]:
    """Every counted value in one verse, in reading order (``archaic`` for KJV-era English)."""
    return scan(text, archaic=archaic)[0]


def scan(text: str, *, archaic: bool = False) -> tuple[list[EnglishValue], list[EnglishValue]]:
    """Counted values and excluded number-like words (each with its reason) of one verse.

    ``archaic`` joins tens and units across "and" ("five and twenty" = 25, "threescore and ten"
    = 70) as in KJV-era English; modern English keeps "five and twenty" as two numbers (a range).
    """
    tokens = _tokens(text)
    found: list[list] = []  # [value, kind, start_index, end_index]
    excluded: list[list] = []  # [value, kind, start_index, end_index, reason]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        low = token.low
        if (low, tokens[i + 1].low if i + 1 < len(tokens) else "") in _NAMES:
            excluded.append([F(UNITS[low]), "CARDINAL", i, i + 1, "NAME"])
            i += 2
            continue
        if low == "tens" and [t.low for t in tokens[i + 1:i + 3]] == ["of", "thousands"]:
            excluded.append([F(10000), "CARDINAL", i, i + 2, "INDEFINITE_PLURAL"])
            i += 3
            continue
        if low == "one" and _is_pronoun_one(tokens, i, archaic):
            excluded.append([F(1), "CARDINAL", i, i, "PRONOUN_ONE"])
            i += 1
            continue
        start = i
        value = None
        if low in {"a", "an"} and i + 1 < len(tokens) and tokens[i + 1].low in SCALES:
            total, current = F(0), F(1)  # the loop below applies the scale
            value = 1
        elif _numeral(token.text) is not None:
            total, current = F(0), F(_numeral(token.text))
            value = 1
        elif _cardinal(low) is not None and not (
                low == "one" and i + 1 < len(tokens) and (_ordinal(tokens[i + 1].low) or 0) > 2):
            total, current = F(0), F(_cardinal(low))
            value = 1
        elif low in SCALES and i and tokens[i - 1].low not in {"a", "an"}:
            total, current = F(0), F(1)
            value = 1
            i -= 1  # the scale itself is handled by the loop below
        if value is not None:
            ordinal = None
            j = i + 1
            while j < len(tokens):
                word = tokens[j].low
                if word in SCALES:
                    scale = SCALES[word]
                    if scale >= 1000:
                        total, current = total + (current or 1) * scale, F(0)
                    else:
                        current = (current or 1) * scale
                    j += 1
                    continue
                if word in {"hundredth", "thousandth"}:
                    ordinal = (total + (current or 1)) * ORDINALS[word] - (total + current)  # "six hundredth"
                    j += 1
                    break
                if word in PLURAL_SCALES and (tokens[j - 1].low in SCALES or j == i + 1):
                    total, current = (total + current) * PLURAL_SCALES[word], F(0)  # "a thousand thousands"
                    j += 1
                    continue
                if archaic and word == "and" and j + 1 < len(tokens) and not total and current < 100:
                    # Archaic tens and units: "threescore and ten" (70), "one and twenty" (21),
                    # "one and twentieth" (21st); two plain units ("two and three") stay separate.
                    nxt = tokens[j + 1].low
                    following = _cardinal(nxt)
                    ordinal_next = _ordinal(nxt)
                    if following is not None and (
                            (current in _TENS_LIKE and (following < 10 or following == 10 and current % 20 == 0))
                            or (current < 10 and following in _TENS_LIKE)):
                        current += following
                        j += 2
                        continue
                    if ordinal_next is not None and current < 10 and ordinal_next in _TENS_LIKE:
                        ordinal = ordinal_next  # added to the unit below: "one and twentieth" is 21
                        j += 2
                        break
                if word == "and" and j + 1 < len(tokens) and (total or current >= 100):
                    nxt = tokens[j + 1].low
                    if _cardinal(nxt) is not None and _cardinal(nxt) < 100:
                        current += _cardinal(nxt)
                        j += 2
                        continue
                    if _ordinal(nxt) is not None:
                        ordinal = _ordinal(nxt)
                        j += 2
                        break
                if (total or current >= 100) and _cardinal(word) is not None and _cardinal(word) < 100 \
                        and tokens[j - 1].low in SCALES:
                    current += _cardinal(word)
                    j += 1
                    continue
                if (total or current >= 100) and _ordinal(word) is not None and tokens[j - 1].low in SCALES:
                    ordinal = _ordinal(word)
                    j += 1
                    break
                break
            amount = total + current
            if not total and current < 100 and j + 2 < len(tokens) and tokens[j].low in {"or", "to"} \
                    and _cardinal(tokens[j + 1].low) and tokens[j + 2].low in SCALES:
                amount *= SCALES[tokens[j + 2].low]  # "two or three thousand" is 2000, 3000
            if ordinal is not None:
                found.append([amount + ordinal, "ORDINAL", start, j - 1])
                i = j
                continue
            kind = "CARDINAL"
            nxt = tokens[j].low if j < len(tokens) else ""
            if nxt in PLURAL_FRACTIONS:
                kind = "MEASURE_COUNT"  # "three tenths of an ephah"; checked against its unit below
                j += 1
            elif nxt == "times" and j + 1 < len(tokens) and (_cardinal(tokens[j + 1].low) or tokens[j + 1].low in
                                                             {"a", "an"} and j + 2 < len(tokens)
                                                             and tokens[j + 2].low in SCALES):
                multiplier = scan(text[tokens[j + 1].start:], archaic=archaic)[0]
                if multiplier and multiplier[0].start == 0:
                    amount *= multiplier[0].value  # "ten thousand times ten thousand"
                    j = next(k for k in range(j + 1, len(tokens)) if tokens[k].start >= tokens[j + 1].start
                             + multiplier[0].end) if any(tokens[k].start >= tokens[j + 1].start + multiplier[0].end
                                                         for k in range(j + 1, len(tokens))) else len(tokens)
                    found.append([amount, "CARDINAL", start, j - 1])
                    i = j
                    continue
            elif nxt == "times":
                kind = "MULTIPLIER"
                j += 1
            if start and tokens[start - 1].low in APPROX_WORDS and kind == "CARDINAL":
                kind = "APPROX"
            found.append([amount, kind, start, j - 1])
            i = j
            continue
        # single-word forms
        hyphen = re.split(r"[-‑]", low)
        if len(hyphen) >= 4 and hyphen[-3:] == ["and", "a", "half"] and _cardinal("-".join(hyphen[:-3])):
            found.append([F(_cardinal("-".join(hyphen[:-3]))) + F(1, 2), "CARDINAL", i, i])  # "nine-and-a-half"
            i += 1
            continue
        lead = 2 if len(hyphen) > 2 and _cardinal("-".join(hyphen[:2])) else 1
        if len(hyphen) > lead and _cardinal("-".join(hyphen[:lead])) and hyphen[lead] not in ORDINALS \
                and hyphen[lead] not in PLURAL_FRACTIONS:
            found.append([F(_cardinal("-".join(hyphen[:lead]))), "CARDINAL", i, i])  # "a three-day journey"
        elif len(hyphen) == 2 and hyphen[0] in UNITS and hyphen[1] in PLURAL_FRACTIONS:
            found.append([F(UNITS[hyphen[0]]), "MEASURE_COUNT", i, i])  # "three-tenths" of a measure
        elif len(hyphen) == 2 and hyphen[0] == "one" and hyphen[1] in ORDINALS and ORDINALS[hyphen[1]] > 2:
            found.append([F(1, ORDINALS[hyphen[1]]), "FRACTION", i, i])  # "one-tenth"
        elif hyphen[0] == "half":
            found.append([F(1, 2), "FRACTION", i, i])  # "half", "half-tribe"
        elif low in {"quarter"} and i and tokens[i - 1].low in {"a", "one"}:
            found.append([F(1, 4), "FRACTION", i - 1, i])
        elif low in {"tithe", "tithes"}:
            excluded.append([F(1, 10), "FRACTION", i, i, "IMPLICIT_NUMBER"])  # no numeral written
        elif low == "both":
            excluded.append([F(2), "CARDINAL", i, i, "BOTH"])  # "both of them", "both X and Y"
        elif low in MULTIPLIERS and i + 1 < len(tokens) and _cardinal(tokens[i + 1].low) is not None:
            following = scan(text[tokens[i + 1].start:], archaic=archaic)[0]
            if following and following[0].start == 0:
                end = tokens[i + 1].start + following[0].end
                last = max(k for k in range(i + 1, len(tokens)) if tokens[k].end <= end)
                found.append([MULTIPLIERS[low] * following[0].value, "CARDINAL", i, last])  # "twice ten thousand"
                i = last + 1
                continue
            excluded.append([F(MULTIPLIERS[low]), "MULTIPLIER", i, i, "IMPLICIT_NUMBER"])
        elif low in MULTIPLIERS:
            excluded.append([F(MULTIPLIERS[low]), "MULTIPLIER", i, i, "IMPLICIT_NUMBER"])  # "twice", "double"
        elif low.endswith("fold") and (_cardinal(low[:-4]) or low[:-4] in SCALES):
            base = _cardinal(low[:-4]) or SCALES[low[:-4]]
            excluded.append([F(base), "MULTIPLIER", i, i, "IMPLICIT_NUMBER"])  # "sevenfold"
        elif _ordinal(low) is not None:
            number = _ordinal(low)
            previous = tokens[i - 1].low if i else ""
            following = tokens[i + 1].low if i + 1 < len(tokens) else ""
            if number > 2 and (previous in {"a", "one"} and following in _PART_FOLLOWERS | _SENTENCE or previous == "the"
                               and following in _PART_FOLLOWERS - {"of", "and", "or", ""}):
                found.append([F(1, number), "FRACTION", i - 1, i])
            else:
                found.append([F(number), "ORDINAL", i, i])
        elif low in {"pair", "pairs"}:
            excluded.append([F(2), "CARDINAL", i, i, "PAIR"])  # "a pair of sandals", "in pairs"
        elif low == "halves":
            excluded.append([F(1, 2), "FRACTION", i, i, "PART_NOUN"])  # "the halves of a pomegranate"
        elif low in PLURAL_GROUPS:
            excluded.append([F(PLURAL_GROUPS[low]), "CARDINAL", i, i, "INDEFINITE_PLURAL"])
        elif low in PLURAL_SCALES and not (i and (_cardinal(tokens[i - 1].low) or tokens[i - 1].low in SCALES)):
            excluded.append([F(PLURAL_SCALES[low]), "CARDINAL", i, i, "INDEFINITE_PLURAL"])
        i += 1
    _halves(tokens, found)
    for item in list(found):
        unit = _unit(tokens, item[3])
        if item[1] == "ORDINAL" and not _date_context(tokens, item[2], item[3]):
            found.remove(item)
            excluded.append([*item, "RANK_ORDINAL"])  # "the first one", "a fifth son", "a third time"
        elif item[1] == "MULTIPLIER":
            found.remove(item)
            excluded.append([*item, "FREQUENCY"])  # "seven times", "three times a year"
        elif item[1] in ("FRACTION", "MEASURE_COUNT") and unit not in MEASURE_NOUNS | DURATION_NOUNS:
            found.remove(item)
            excluded.append([*item, "FRACTION_NO_MEASURE"])  # "a third of the city", "half the tribe"
        elif item[1] == "MEASURE_COUNT":
            item[1] = "CARDINAL"
    for item in list(excluded):
        if any(tokens[k].text[0].isdigit() for k in range(item[2], item[3] + 1)):
            excluded.remove(item)  # NIV writes verified numbers as numerals: a numeral always counts
            found.append([item[0], "CARDINAL" if item[1] in ("MULTIPLIER", "MEASURE_COUNT") else item[1],
                          item[2], item[3]])
    found.sort(key=lambda item: item[2])
    excluded.sort(key=lambda item: item[2])
    return _values(text, tokens, [[*item, ""] for item in found]), _values(text, tokens, excluded)


_DETERMINERS = {"of", "the", "a", "an", "his", "her", "their", "its", "your", "my", "our", "this", "that"}


def _unit(tokens: list[_Token], last: int) -> str:
    """The counted word after a number, past "of" and determiners ("a third of a hin" -> hin)."""
    for token in tokens[last + 1:last + 5]:
        if token.text in _SENTENCE or token.text == ",":
            return ""
        if token.low not in _DETERMINERS:
            return token.low
    return ""


_PHRASE_STOP = {
    "in", "on", "at", "to", "from", "by", "with", "for", "into", "onto", "over", "under", "before", "after",
    "and", "or", "but", "nor", "so", "than", "as", "is", "was", "were", "are", "be", "been", "being", "have",
    "has", "had", "will", "shall", "would", "could", "should", "may", "might", "must", "do", "does", "did",
    "he", "she", "they", "it", "we", "you", "i", "who", "whom", "whose", "which", "that", "this", "these",
    "those", "there", "here", "when", "while", "until", "if", "not", "no", "more", "times", "each", "all",
    "every", "old", "long", "wide", "high", "deep", "in", "against", "among", "through", "about", "away",
}
_LEADING = {"the", "a", "an", "his", "her", "their", "its", "your", "my", "our"}


def _is_number_token(token: _Token) -> bool:
    """A numeral or number word ("410", "thirty", "hundred")."""
    return token.text[0].isdigit() or _cardinal(token.low) is not None or token.low in SCALES


def _phrase(tokens: list[_Token], indices) -> list[int]:
    """Collect content words (and one "of" link) from an ordered index walk."""
    picked, linked = [], False
    for index in indices:
        token = tokens[index]
        if token.text in _SENTENCE or token.text == "," or _is_number_token(token):
            break
        if token.low == "of" and picked and not linked:
            linked = True
            picked.append(index)
            continue
        if token.low in _PHRASE_STOP or (token.low in _LEADING and picked):
            break
        if token.low in _LEADING:
            continue
        picked.append(index)
        if len([i for i in picked if tokens[i].low != "of"]) == 4:
            break
    while picked and tokens[picked[-1]].low == "of":
        picked.pop()
    return picked


def _own_measure(tokens: list[_Token], first: int, last: int) -> str:
    """A measure word inside the number itself: "a cubit and a half" counts cubits."""
    return next((tokens[index].text for index in range(first, last + 1) if tokens[index].low in MEASURE_NOUNS), "")


def _referent(tokens: list[_Token], first: int, last: int) -> str:
    """What a number counts: the phrase after it, or before it in a list ("gold bowls 30")."""
    after = _phrase(tokens, range(last + 1, len(tokens)))
    before = sorted(_phrase(tokens, range(first - 1, -1, -1)))
    following = after[-1] + 1 if after else last + 1
    if before and (not after or following < len(tokens) and _is_number_token(tokens[following])):
        chosen = before
    else:
        chosen = after
    return " ".join(tokens[index].text for index in sorted(chosen))


def _values(text: str, tokens: list[_Token], items: list[list]) -> list[EnglishValue]:
    """Typed values with their role, counted word and exact span in the verse."""
    values = []
    for value, kind, first, last, why in items:
        after = [t.low for t in tokens[last + 1:last + 5] if t.text not in _SENTENCE and t.text != ","]
        unit = _unit(tokens, last)
        values.append(EnglishValue(value, kind, _role(kind, unit, after[1:]),
                                   text[tokens[first].start:tokens[last].end], tokens[first].start,
                                   tokens[last].end, unit, why, _own_measure(tokens, first, last)
                                   or _referent(tokens, first, last)))
    return values


def _halves(tokens: list[_Token], found: list[list]) -> None:
    """Fold "and a half" into the number or measure before it."""
    for item in list(found):
        value, kind, first, last = item
        if value != F(1, 2) or first != last or tokens[first].low != "half":
            continue
        if first < 2 or [t.low for t in tokens[first - 2:first]] not in (["and", "a"], ["and", "one"]):
            continue
        previous = [entry for entry in found if entry[3] < first - 2 and entry is not item]
        anchor = previous[-1] if previous else None
        if anchor and anchor[1] in {"CARDINAL", "APPROX"} and first - 2 - anchor[3] <= 2:
            anchor[0] += F(1, 2)
            anchor[3] = first
            found.remove(item)
        elif first >= 4 and tokens[first - 4].low in {"a", "one"} and tokens[first - 3].low in MEASURE_NOUNS:
            item[0], item[1], item[2] = F(3, 2), "CARDINAL", first - 4
