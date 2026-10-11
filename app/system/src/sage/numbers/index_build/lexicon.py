"""Classify one MACULA word as a numeral: its value, convention kind, and composition role.

Roles drive composition (numbers/index_build/compose.py):

- ``UNIT``   a value that adds (one..nine, tens, teens, "twenty");
- ``TEEN``   the Hebrew teen "ten" (עָשָׂר) that joins a preceding unit (14 = 4 + teen);
- ``SCALE``  hundred/thousand/myriad that multiplies what precedes it; ``plural`` marks a
             plural scale word ("hundreds", "thousands");
- ``WHOLE``  a self-contained value that never composes (ordinals, fractions, multipliers,
             dual scales such as מָאתַיִם "two hundred" are UNIT with value 200).

Kinds follow the shared counting convention: CARDINAL, ORDINAL, FRACTION, MULTIPLIER,
PERCENT, APPROX.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re

from .macula import Word, normalized

F = Fraction


@dataclass(frozen=True)
class Numeral:
    """One classified numeral word."""

    value: Fraction
    kind: str
    role: str
    plural: bool = False


def _table(raw: dict[str, object]) -> dict[str, object]:
    """Key a lexicon table by NFC lemma so it matches MACULA's mark ordering."""
    return {normalized(key): value for key, value in raw.items()}


# ---------- Hebrew and Biblical Aramaic (MACULA Hebrew, OSHB morphology) ----------

HEB_UNITS = _table({
    "אֶחָד": 1, "שְׁנַיִם": 2, "שָׁלֹשׁ": 3, "אַרְבַּע": 4, "חָמֵשׁ": 5, "שֵׁשׁ": 6, "שֶׁבַע": 7,
    "שְׁמֹנֶה": 8, "תֵּשַׁע": 9, "עֶשֶׂר": 10, "עֲשָׂרָה": 10, "שִׁבְעָנָה": 7,
    "חַד": 1, "תְּרֵין": 2, "תְּלָת": 3, "שֵׁת": 6, "שְׁבַע": 7,
})
HEB_TEENS = _table({"עָשָׂר": 10, "עֶשְׂרֵה": 10, "עֲשַׂר": 10})  # עֲשַׂר: Aramaic, תְּרֵי עֲשַׂר = 12
# עַשְׁתֵּי appears only in עַשְׁתֵּי עָשָׂר / עַשְׁתֵּי עֶשְׂרֵה ("eleven").
HEB_ELEVEN = normalized("עַשְׁתֵּי")
HEB_TENS = _table({"עֶשְׂרִים": 20, "עֶשְׂרִין": 20, "שִׁתִּין": 60, "תְּלָתִין": 30})
HEB_SCALES = _table({"מֵאָה": 100, "מְאָה": 100, "אֶלֶף": 1000, "אֲלַף": 1000, "רִבֹּוא": 10000, "רִבּוֹ": 10000})
HEB_ORDINALS = _table({
    "רִאשׁוֹן": 1, "שֵׁנִי": 2, "שְׁלִישִׁי": 3, "רְבִיעִי": 4, "חֲמִישִׁי": 5, "שִׁשִּׁי": 6, "שְׁבִיעִי": 7,
    "שְׁמִינִי": 8, "תְּשִׁיעִי": 9, "עֲשִׂירִי": 10, "תִּנְיָן": 2, "תִּנְיָנוּת": 2, "תְּלִיתַי": 3,
    "תְּלַת": 3, "קַדְמַי": 1, "רְבִיעַי": 4,
})
HEB_FRACTIONS = _table({
    "חֲצִי": F(1, 2), "מַחֲצִית": F(1, 2), "מֶחֱצָה": F(1, 2), "שְׁלִישִׁית": F(1, 3), "רֶבַע": F(1, 4),
    "רֹבַע": F(1, 4), "חֲמִישִׁית": F(1, 5), "עִשָּׂרוֹן": F(1, 10), "מַעֲשֵׂר": F(1, 10),
})
# Words MACULA tags as numerals (or number-like words) the index never counts, with why.
HEB_EXCLUDED_REASONS = {normalized(lemma): reason for lemma, reason in (
    ("בַּתשֶׁבַע", "PROPER_NAME: Bathsheba"),
    ("קִרְיַת אַרְבַּע", "PROPER_NAME: Kiriath Arba"),
    ("שִׁבְעָה", "PROPER_NAME: Shibah"),
    ("שָׁלִישׁ", "TITLE: officer/captain, not 'third' or 'three'"),
    ("עִדָּן", "COUNTED_NOUN: 'times' (periods); the number beside it is counted"),
    ("מִשְׁנֶה", "QUALIFIER: second/matching/double sense, not counted by the index (e.g. EZR 1:10)"),
)}
HEB_EXCLUDED = set(HEB_EXCLUDED_REASONS)
HEB_DUAL_TIME = {normalized("שָׁנָה")}  # שְׁנָתַיִם "two years", tagged cardinal by MACULA
HEB_TIMES = normalized("פַּעַם")
# Counted units whose dual form means "two of them" (not natural pairs such as hands or loins).
HEB_COUNTED_DUALS = {normalized(x) for x in (
    "שָׁבוּעַ", "יוֹם", "חֹדֶשׁ", "כִּכָּר", "אַמָּה", "סְאָה", "חֲמֹרָה", "שָׁנָה",
)}
# עָשׂוֹר "ten (days)", "the tenth (day)", tagged as a noun: "on the tenth of this month" (EXO 12:3),
# "ten days or so" (GEN 24:55), "a ten-stringed lyre".
HEB_TENTH_DAY = normalized("עָשׂוֹר")
_FRACTION_MEASURES = {normalized(x) for x in ("אֵיפָה", "הִין", "שֶׁקֶל", "כֹּר", "בַּת", "סְאָה", "עֹמֶר")}
_NUMBER_GLOSS = re.compile(
    r"(one|two|three|four|five|six|seven|eight|nine|ten|teen|eleven|twelve|twent|thirt|fort|fift|sixt|"
    r"sevent|eight|ninet|hundred|thousand|myriad|first|second|third|fourth|fifth|sixth|seventh|eighth|"
    r"ninth|tenth|half|twice|fold|times|both|pair|single|once|plus|\[)", re.I)
# Strong's numbers of homographs MACULA tags as numerals: 8336 שֵׁשׁ "fine linen".
HEB_EXCLUDED_STRONG = {"8336"}
# Multiplier words by Strong's number: 7659 שִׁבְעָתַיִם "sevenfold", 706 אַרְבַּעְתַּיִם "fourfold".
HEB_MULTIPLIER_STRONG = {"7659": 7, "706": 4, "0706": 4}
# Fraction and multiplier nouns by Strong's number: 2569 חֹמֶשׁ "a fifth" (2570 is "belly"),
# 3718 כֶּפֶל "double" (dual כִּפְלַיִם).
HEB_FRACTION_STRONG = {"2569": F(1, 5)}
HEB_DOUBLE_STRONG = "3718"
_DUAL_FORM = re.compile(r"[ַָ]?י[֑-ִֽ֯]*ם[֑-֯]*$")
_MYRIAD_GLOSS = re.compile(r"tens?\W*(?:of\W*)?thousand|myriad", re.I)


def classify_hebrew(word: Word) -> Numeral | None:
    """Classify one MACULA Hebrew/Aramaic word, or None when it is not a counted numeral."""
    lemma, subtype, number, gloss = word.lemma, word.subtype, word.number, word.gloss
    numeral_tag = subtype in ("cardinal number", "ordinal number")
    if (lemma in HEB_EXCLUDED or gloss[:1].isupper() or subtype == "proper"
            or word.english[:1].isupper() and not _NUMBER_GLOSS.search(word.english)
            or word.strong.rstrip("abcdefgh") in HEB_EXCLUDED_STRONG):
        return None
    if word.strong.rstrip("abcdefgh") in HEB_FRACTION_STRONG:
        return Numeral(HEB_FRACTION_STRONG[word.strong.rstrip("abcdefgh")], "FRACTION", "WHOLE")
    if word.strong.rstrip("abcdefgh") == HEB_DOUBLE_STRONG and number == "dual":
        return Numeral(F(2), "MULTIPLIER", "WHOLE")
    if word.strong.rstrip("abcdefgh") in HEB_MULTIPLIER_STRONG:
        return Numeral(F(HEB_MULTIPLIER_STRONG[word.strong.rstrip("abcdefgh")]), "MULTIPLIER", "WHOLE")
    if subtype == "cardinal number" and not (_NUMBER_GLOSS.search(gloss) or _NUMBER_GLOSS.search(word.english)):
        return None  # a MACULA numeral tag on a homograph, e.g. שְׁנֵי "years of"
    if number == "plural" and "two" in gloss and _DUAL_FORM.search(word.text):
        number = "dual"  # dual forms MACULA records as plural, e.g. אַלְפַּיִם "two thousand"
    if word.pos in ("adjective", "noun") and lemma in HEB_ORDINALS and not numeral_tag:
        return Numeral(F(HEB_ORDINALS[lemma]), "ORDINAL", "WHOLE")  # "the first [month]", "former" alike
    if word.pos == "noun" and (_MYRIAD_GLOSS.search(gloss) or _MYRIAD_GLOSS.search(word.english)):
        return Numeral(F(10000), "CARDINAL", "SCALE", plural=number == "plural")
    if subtype == "ordinal number":
        if lemma in HEB_ORDINALS:
            return Numeral(F(HEB_ORDINALS[lemma]), "ORDINAL", "WHOLE")
        if lemma == HEB_ELEVEN:
            return Numeral(F(1), "CARDINAL", "UNIT")
        if lemma in HEB_UNITS:
            return Numeral(F(HEB_UNITS[lemma]), "CARDINAL", "UNIT")
        if lemma in HEB_FRACTIONS:
            return Numeral(HEB_FRACTIONS[lemma], "FRACTION", "WHOLE")
        return None
    if subtype == "cardinal number":
        if lemma in HEB_DUAL_TIME:
            # שְׁנָתַיִם "two years" counts; שְׁנֵי "the years of" (also tagged cardinal) does not.
            return Numeral(F(2), "CARDINAL", "UNIT") if "two" in gloss else None
        if lemma in HEB_SCALES:
            base = HEB_SCALES[lemma]
            if number == "dual":
                return Numeral(F(2 * base), "CARDINAL", "UNIT")
            return Numeral(F(base), "CARDINAL", "SCALE", plural=number == "plural")
        if lemma in HEB_TEENS:
            return Numeral(F(10), "CARDINAL", "TEEN")
        if lemma == HEB_ELEVEN:
            return Numeral(F(1), "CARDINAL", "UNIT")
        if lemma in HEB_TENS:
            return Numeral(F(HEB_TENS[lemma]), "CARDINAL", "UNIT")
        if lemma in HEB_UNITS:
            base = HEB_UNITS[lemma]
            if number == "plural" and base == 1:
                return None  # אֲחָדִים "a few (days)"
            if number == "plural" and 3 <= base <= 9:
                return Numeral(F(base * 10), "CARDINAL", "UNIT")  # שְׁלֹשִׁים "thirty"
            if number == "dual" and base in (4, 7):
                return Numeral(F(base), "MULTIPLIER", "WHOLE")  # שִׁבְעָתַיִם "sevenfold"
            return Numeral(F(base), "CARDINAL", "UNIT")
        return None
    if word.pos == "noun":
        if lemma == HEB_TENTH_DAY:
            return Numeral(F(10), "CARDINAL", "WHOLE")
        if lemma in HEB_FRACTIONS:
            return Numeral(HEB_FRACTIONS[lemma], "FRACTION", "WHOLE")
        if lemma == HEB_TIMES and number == "dual":
            return Numeral(F(2), "MULTIPLIER", "WHOLE")  # פַּעֲמַיִם "twice"
        if number == "dual" and lemma in HEB_COUNTED_DUALS:
            return Numeral(F(2), "CARDINAL", "WHOLE")  # שְׁבֻעַיִם "two weeks", חֲמֹרָתַיִם "two heaps"
    return None


def ordinal_part(word: Word, following: Word | None) -> Fraction | None:
    """A feminine ordinal before a measure names a part: עֲשִׂירִית הָאֵיפָה "a tenth of an ephah"."""
    if following is None or following.lemma not in _FRACTION_MEASURES or word.lemma not in HEB_ORDINALS:
        return None
    if not (word.state == "construct" or word.text.endswith(normalized("ת"))):
        return None
    return F(1, HEB_ORDINALS[word.lemma])


# ---------- Greek (MACULA Greek, SBLGNT) ----------

GRK_UNITS = _table({
    "εἷς": 1, "δύο": 2, "τρεῖς": 3, "τέσσαρες": 4, "πέντε": 5, "ἕξ": 6, "ἑπτά": 7, "ὀκτώ": 8,
    "ἐννέα": 9, "δέκα": 10, "ἕνδεκα": 11, "δώδεκα": 12, "δεκατέσσαρες": 14, "δεκαπέντε": 15,
    "δεκαοκτώ": 18, "εἴκοσι(ν)": 20, "εἴκοσι": 20, "τριάκοντα": 30, "τεσσεράκοντα": 40,
    "πεντήκοντα": 50, "ἑξήκοντα": 60, "ἑβδομήκοντα": 70, "ὀγδοήκοντα": 80, "ἐνενήκοντα": 90,
    "ἑκατόν": 100, "διακόσιοι": 200, "τριακόσιοι": 300, "τετρακόσιοι": 400, "πεντακόσιοι": 500,
    "ἑξακόσιοι": 600, "χίλιοι": 1000, "δισχίλιοι": 2000, "τρισχίλιοι": 3000,
    "τετρακισχίλιοι": 4000, "πεντακισχίλιοι": 5000, "ἑπτακισχίλιοι": 7000, "μύριοι": 10000,
    # Number-bearing compounds the convention counts (ages, durations, tribes).
    "τεσσερακονταετής": 40, "ἑκατονταετής": 100, "διετής": 2, "διετία": 2, "τριετία": 3,
    "τετράμηνος": 4, "τρίμηνον": 3, "τεταρταῖος": 4, "δευτεραῖος": 2, "ὀκταήμερος": 8,
    "δωδεκάφυλον": 12,
})
GRK_SCALES = _table({"χιλιάς": 1000, "μυριάς": 10000, "δισμυριάς": 20000})
GRK_ORDINALS = _table({
    "πρῶτος": 1, "δεύτερος": 2, "τρίτος": 3, "τέταρτος": 4, "πέμπτος": 5, "ἕκτος": 6,
    "ἕβδομος": 7, "ὄγδοος": 8, "ἔνατος": 9, "δέκατος": 10, "ἑνδέκατος": 11, "δωδέκατος": 12,
    "τεσσαρεσκαιδέκατος": 14, "πεντεκαιδέκατος": 15, "πρῶτον": 1, "πρώτως": 1, "τρίτον": 3,
})
GRK_FRACTIONS = _table({"ἥμισυς": F(1, 2), "δεκάτη": F(1, 10), "ἡμιώριον": F(1, 2)})
GRK_MULTIPLIERS = _table({
    "δίς": 2, "τρίς": 3, "πεντάκις": 5, "ἑπτάκις": 7,
    "ἑβδομηκοντάκις": 70, "ἑκατονταπλασίων": 100, "τετραπλοῦς": 4, "διπλοῦς": 2, "διπλόω": 2,
})
GRK_BOTH = normalized("ἀμφότεροι")  # "both" is counted as 2 by the index
# πρῶτος counts only in its sequence sense ("first"), not "leading men", "foremost", "former".
_GRK_FIRST = {normalized(x) for x in ("πρῶτος", "πρῶτον", "πρώτως")}
# Ordinals used as "a third/fourth of" (substantive neuter): fractions, e.g. REV 8:7 τὸ τρίτον.
_GRK_PART_ORDINALS = {normalized("τρίτος"): F(1, 3), normalized("τέταρτος"): F(1, 4),
                      normalized("δέκατος"): F(1, 10)}


def classify_greek(word: Word) -> Numeral | None:
    """Classify one MACULA Greek word, or None when it is not a counted numeral."""
    lemma = word.lemma
    if not lemma or lemma[:1].isupper() or word.subtype == "proper":
        return None  # names such as Τρεῖς (Ταβέρναι), "Three Taverns"
    if lemma in GRK_MULTIPLIERS:
        return Numeral(F(GRK_MULTIPLIERS[lemma]), "MULTIPLIER", "WHOLE")
    if lemma in GRK_FRACTIONS:
        return Numeral(GRK_FRACTIONS[lemma], "FRACTION", "WHOLE")
    if lemma in GRK_ORDINALS:
        if lemma in _GRK_FIRST and "first" not in word.english.lower():
            return None
        return Numeral(F(GRK_ORDINALS[lemma]), "ORDINAL", "WHOLE")
    if lemma == GRK_BOTH:
        return Numeral(F(2), "CARDINAL", "WHOLE")
    if lemma in GRK_SCALES:
        return Numeral(F(GRK_SCALES[lemma]), "CARDINAL", "SCALE", plural=word.number == "plural")
    if lemma in GRK_UNITS:
        return Numeral(F(GRK_UNITS[lemma]), "CARDINAL", "UNIT")
    return None


def greek_part(word: Word, following: Word | None) -> Fraction | None:
    """A neuter ordinal followed by a genitive names a part: τὸ τρίτον τῆς γῆς "a third of the earth"."""
    if (word.lemma not in _GRK_PART_ORDINALS or word.gender != "neuter" or word.number != "singular"
            or word.case == "genitive" or following is None or following.case != "genitive"):
        return None
    return _GRK_PART_ORDINALS[word.lemma]


CLASSIFIERS = {"HEB": classify_hebrew, "GRK": classify_greek}


def exclusion_reason(word: Word) -> str | None:
    """Why a number-like word (tagged numeral, or a known homograph) is not counted, else None."""
    numeral_tag = word.subtype in ("cardinal number", "ordinal number") or word.pos == "num"
    if word.lemma in HEB_EXCLUDED:
        return HEB_EXCLUDED_REASONS[word.lemma]
    if word.strong.rstrip("abcdefgh") in HEB_EXCLUDED_STRONG:
        return "HOMOGRAPH_STRONG: not a numeral sense (e.g. 8336 fine linen)"
    if not numeral_tag:
        return None
    if word.gloss[:1].isupper() or word.english[:1].isupper() and not _NUMBER_GLOSS.search(word.english) \
            or word.subtype == "proper" \
            or word.lemma[:1].isupper():
        return "PROPER_NAME: number inside a name"
    if word.subtype == "cardinal number" and not (_NUMBER_GLOSS.search(word.gloss) or _NUMBER_GLOSS.search(word.english)):
        return "HOMOGRAPH_GLOSS: numeral tag on a non-numeral sense"
    return "CONVENTION: not counted by the counting convention"
