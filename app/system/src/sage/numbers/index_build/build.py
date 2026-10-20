"""Build typed original-language number records and diff them against the current package."""
from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import re

from sage.vrs import VerseRef, parse_vrs_file

from .compose import Expression, compose
from .lexicon import (CLASSIFIERS, GRK_BOTH, GRK_SCALES, HEB_SCALES, _MYRIAD_GLOSS, exclusion_reason,
                      greek_part, ordinal_part)
from .macula import SOURCES, Word, normalized, read_verses

# Adjacent units are separate numbers in Hebrew; Greek writes compounds adjacently.
_SPLIT_ADJACENT_UNITS = {"HEB": True, "GRK": False}
_REF = re.compile(r"([1-3]?[A-Z]{2,3}) ([0-9]+):([0-9]+)")
_TIME_NOUNS_RAW = {"שָׁנָה", "יוֹם", "חֹדֶשׁ", "ἔτος", "ἡμέρα", "μήν", "ὥρα"}
_MEASURE_NOUNS_RAW = {
    "אַמָּה", "שֶׁקֶל", "כִּכָּר", "אֵיפָה", "הִין", "סְאָה", "עֹמֶר", "כֹּר", "בַּת", "זֶרֶת", "גֵּרָה", "מָנֶה",
    "πῆχυς", "στάδιον", "τάλαντον", "δηνάριον", "μνᾶ", "βάτος", "κόρος", "σάτον", "λίτρα", "μετρητής",
}

_TIME_NOUNS = {normalized(lemma) for lemma in _TIME_NOUNS_RAW}
# An ordinal counts only beside one of these (convention 2.0 rule 3): day, month, year, week,
# watch, sabbath, hour; Hebrew, Biblical Aramaic and Greek.
_DATE_NOUNS = {normalized(lemma) for lemma in (
    "יוֹם", "חֹדֶשׁ", "שָׁנָה", "שָׁבוּעַ", "אַשְׁמֹרֶת", "אַשְׁמוּרָה", "שַׁבָּת", "שְׁנָה", "יְרַח",
    "ἡμέρα", "μήν", "ἔτος", "ὥρα", "φυλακή", "σάββατον",
)}
_INDEFINITE_PLURALS = {Fraction(100), Fraction(1000), Fraction(10000)}
# Strict units (convention 2.0): a fraction counts only as a part of a measure or a time unit;
# these lemmas are themselves a measure ("a tenth-measure", "half an hour").
_MEASURE_FRACTIONS = {normalized(lemma) for lemma in ("עִשָּׂרוֹן", "ἡμιώριον")}
_EXTRA_MEASURES = {normalized(lemma) for lemma in ("קַב", "לֹג", "חֹמֶר", "לֶתֶךְ", "χοῖνιξ", "μόδιος")}
_DURATIONS = {normalized(lemma) for lemma in ("יוֹם", "שָׁנָה", "חֹדֶשׁ", "שָׁבוּעַ", "לַיְלָה", "ἡμέρα", "ἔτος", "μήν",
                                              "ὥρα", "νύξ")}
_TITHE = normalized("מַעֲשֵׂר")
_TIMES = normalized("פַּעַם")
_COMMANDER = normalized("שַׂר")  # שַׂר הָאֶלֶף "commander of the thousand": a unit title
_ARAMAIC_ONE = normalized("חַד")  # חַד־שִׁבְעָה "one-seven": seven times
# Greek χιλιάς/μυριάς are nouns ("thousands", "myriads"); χίλιοι/μύριοι are plural adjectives
# meaning "a thousand"/"ten thousand" and always count.
_GRK_SCALE_NOUNS = {normalized("χιλιάς"), normalized("μυριάς")}
_MEASURE_NOUNS = {normalized(lemma) for lemma in _MEASURE_NOUNS_RAW}


@dataclass(frozen=True)
class TypedValue:
    """One counted original-language value with its words and context."""

    ol_ref: str
    family: str
    expression_no: int
    value: Fraction
    kind: str
    role: str
    word_ids: tuple[str, ...]
    surface: str
    lemmas: tuple[str, ...]
    unit_lemma: str
    unit_gloss: str
    referent: str = ""  # English gloss of what the number counts ("bowls of gold", "darics")


def _parse_ref(label: str) -> VerseRef:
    """Parse one canonical 'BOOK C:V' label."""
    match = _REF.fullmatch(label)
    if match is None:
        raise ValueError(f"Invalid reference label: {label!r}")
    return VerseRef(match[1], int(match[2]), int(match[3]))


def _unit_after(words: list[Word], expression: Expression) -> Word | None:
    """The counted noun next to an expression: after it within two words, else just before it."""
    positions = [words.index(word) for word in expression.words]
    for word in words[max(positions) + 1:max(positions) + 3]:
        if word.pos == "noun" and word.subtype != "proper":
            return word
    for word in reversed(words[max(0, min(positions) - 2):min(positions)]):
        if word.pos == "noun" and word.subtype != "proper":
            return word
    return None


_CONTENT = {"noun", "adjective"}


def _gloss(word: Word) -> str:
    """Readable English gloss of one MACULA word ("of.priests" -> "of priests")."""
    return (word.english or word.gloss or "").replace(".", " ").strip("[] ")


def counted_phrase(words: list[Word], expression: Expression, family: str) -> list[Word]:
    """The words naming what a number counts, head noun last, in reading order.

    Hebrew: a construct numeral governs the noun after it (שְׁנֵי בָנִים "two sons"); an absolute
    numeral after a free (absolute) noun is a list entry for that noun (כְּפוֹרֵי זָהָב שְׁלֹשִׁים
    "gold bowls: 30"); otherwise the noun after it (שְׁלֹשִׁים וּמְאַת שָׁנָה "130 years",
    בֶּן־עֶשְׂרִים שָׁנָה "twenty years old"). Greek: the nearest noun agreeing in case.
    """
    positions = [words.index(word) for word in expression.words]
    first, last = min(positions), max(positions)
    def skip(item: Word) -> bool:
        """Articles carry no meaning for what is counted."""
        return item.subtype == "definite article" or item.pos in ("det",)
    if family == "GRK":
        numeral = expression.words[-1]
        nearby = [item for item in words[max(0, first - 3):last + 4] if item.pos == "noun"
                  and item.subtype != "proper" and item not in expression.words]
        agreeing = [item for item in nearby if item.case and item.case == numeral.case] or nearby
        if not agreeing:
            return []
        head = min(agreeing, key=lambda item: abs(words.index(item) - last))
        position = words.index(head)
        genitive = [item for item in words[position + 1:position + 3]
                    if item.pos == "noun" and item.case == "genitive" and item.case != head.case]
        return [head, *genitive[:1]]
    own_nouns = [word for word in expression.words if word.pos == "noun"
                 and word.lemma not in HEB_SCALES and word.lemma not in GRK_SCALES
                 and not _MYRIAD_GLOSS.search(word.gloss or "") and not _MYRIAD_GLOSS.search(word.english or "")]
    if own_nouns:
        return own_nouns[:1]  # אַמָּתַיִם "two cubits", אַמָּה וָחֵצִי "a cubit and a half"
    def numeral(item: Word) -> bool:
        """A word tagged as a number (never part of a counted phrase)."""
        return item.subtype in ("cardinal number", "ordinal number") or item.pos == "num"
    def bound(position: int) -> bool:
        """A word with its own article or a prefixed preposition starts a new phrase."""
        word = words[position]
        previous = words[position - 1] if position else None
        return previous is not None and previous.position == word.position and (
            previous.subtype == "definite article" or previous.pos == "preposition")
    nearest = next((index for index in range(first - 1, -1, -1) if not skip(words[index])), None)
    head = words[nearest] if nearest is not None else None
    attributive = expression.kind == "ORDINAL" or (first and words[first - 1].subtype == "definite article")
    if head is not None and head.subtype == "proper" and nearest and words[nearest - 1].pos == "noun" \
            and words[nearest - 1].state == "construct":
        return [words[nearest - 1], head]  # בְּנֵי עֵילָם אֶלֶף... "descendants of Elam: 1,254"
    if expression.words[-1].state != "construct" and head is not None and head.pos in _CONTENT \
            and not numeral(head) and head.subtype != "proper" and (head.state != "construct" or attributive):
        chain, index = [], nearest
        while index >= 0 and len(chain) < 3:
            item = words[index]
            if skip(item):
                index -= 1
                continue
            if item.pos not in _CONTENT or numeral(item) or item.subtype == "proper":
                break
            if chain and bound(index):
                break  # לָאוֹצָר "to the treasury", הָעָם "the people" are not part of the list item
            chain.append(item)
            if item.pos == "noun" and item.state == "construct":
                break
            index -= 1
        return list(reversed(chain))
    after = [item for item in words[last + 1:last + 6] if not skip(item)]
    chain = []
    for item in after:
        if item.pos not in _CONTENT or item.subtype == "proper" or numeral(item):
            break
        chain.append(item)
        if item.state != "construct" or len(chain) == 3:
            break
    if chain and chain[-1].state == "construct":
        # A construct noun closed by a suffix or a name and then its own absolute numeral is the
        # next list entry, not this number's item: in פְּאַת־יָמָּה 4500 שַׁעֲרֵיהֶם שְׁלֹשָׁה
        # שַׁעַר גָּד אֶחָד "their gates" counts 3 and "gate of Gad" 1.
        rest = words[words.index(chain[-1]) + 1:]
        following = next((item for item in rest if item.pos != "suffix" and item.subtype != "proper"), None)
        if following is not None and numeral(following) and following.state == "absolute":
            # This number then closes the phrase before it: the noun before any suffix, or the
            # construct noun before a name (מֶלֶךְ שִׁמְרוֹן מְראוֹן אֶחָד "king of Shimron-meron: 1").
            back = next((index for index in range(first - 1, -1, -1)
                         if not skip(words[index]) and words[index].pos != "suffix"), None)
            if back is None:
                return []
            item = words[back]
            if item.subtype == "proper" and back and words[back - 1].pos == "noun" \
                    and words[back - 1].state == "construct":
                return [words[back - 1], item]
            return [item] if item.pos == "noun" and item.subtype != "proper" else []
    return chain


def referent_gloss(chain: list[Word]) -> str:
    """English gloss of a counted phrase in its own word order."""
    return " ".join(part for part in (_gloss(word) for word in chain) if part)


def _role(expression: Expression, unit: Word | None) -> str:
    """Heuristic context role: DATE, AGE, MEASURE, TIME or COUNT."""
    if unit is None:
        return "COUNT"
    if unit.lemma in _TIME_NOUNS:
        return "DATE" if expression.kind == "ORDINAL" else "TIME"
    if unit.lemma in _MEASURE_NOUNS:
        return "MEASURE"
    return "COUNT"


def _near_date(words: list[Word], expression: Expression) -> bool:
    """Whether a day/month/year/hour noun stands within three words of the expression."""
    positions = [words.index(word) for word in expression.words]
    window = words[max(0, min(positions) - 3):max(positions) + 4]
    return any(word.lemma in _DATE_NOUNS for word in window if word not in expression.words)


def _numbers_a_thing(words: list[Word], word: Word, family: str) -> bool:
    """Whether a lone "one" numbers a noun ("one man") rather than standing alone ("one of you")."""
    position = words.index(word)
    if family == "HEB":
        if word.state == "construct":
            return False  # אַחַד + noun: "one of the ..."
        previous = next((item for item in reversed(words[:position]) if item.subtype != "definite article"), None)
        if previous is None:
            return False
        # "one man", "Ephraim: one [portion]", "one sinner" (a participle used as a noun)
        return previous.pos in {"noun", "adjective"} or previous.pos == "verb" and "participle" in previous.subtype
    neighbours = [item for item in words[max(0, position - 3):position + 4] if item is not word]
    return any(item.pos == "noun" and item.case == word.case and item.gender == word.gender for item in neighbours)


def _times_follow(words: list[Word], expression: Expression) -> bool:
    """Whether "times" (פַּעַם) follows through "or"/"and" and further numbers: "five or six times"."""
    position = max(words.index(word) for word in expression.words) + 1
    for word in words[position:position + 5]:
        if word.lemma == _TIMES:
            return True
        if word.pos not in ("conjunction", "adjective") and word.subtype not in ("cardinal number", "definite article"):
            return False
    return False


def scope_reason(words: list[Word], expression: Expression, family: str) -> str | None:
    """Why a composed number is outside NCA's scope (quantities and dates), else None."""
    lemmas = {word.lemma for word in expression.words}
    if GRK_BOTH in lemmas:
        return "BOTH"
    if _TITHE in lemmas:
        return "IMPLICIT_NUMBER"  # "tithe": no numeral written
    if expression.kind == "MULTIPLIER":
        frequency = any(lemma.endswith("κις") or lemma == _TIMES for lemma in lemmas)
        return "FREQUENCY" if frequency else "IMPLICIT_NUMBER"  # ἑπτάκις, פַּעֲמַיִם; שִׁבְעָתַיִם, כִּפְלַיִם
    unit = _unit_after(words, expression)
    if unit is not None and unit.lemma == _TIMES or _times_follow(words, expression):
        return "FREQUENCY"  # שֶׁבַע פְּעָמִים "seven times", חָמֵשׁ אוֹ שֵׁשׁ פְּעָמִים "five or six times"
    if expression.kind == "FRACTION" and not lemmas & _MEASURE_FRACTIONS and (
            unit is None or unit.lemma not in _MEASURE_NOUNS | _EXTRA_MEASURES | _DURATIONS):
        return "FRACTION_NO_MEASURE"  # "a third of the city", "half the tribe"
    if expression.kind == "ORDINAL" and not _near_date(words, expression):
        return "RANK_ORDINAL"  # "the first one", "a fifth son", "the former things"
    if family == "GRK" and all(word.lemma in _GRK_SCALE_NOUNS for word in expression.words):
        return "INDEFINITE_PLURAL"  # μυριάδες μυριάδων καὶ χιλιάδες χιλιάδων
    if len(expression.words) != 1:
        return None
    word = expression.words[0]
    position = words.index(word)
    following = words[position + 1] if position + 1 < len(words) else None
    if family == "HEB" and expression.value in _INDEFINITE_PLURALS:
        previous = next((item for item in reversed(words[:position]) if item.subtype != "definite article"), None)
        if previous is not None and previous.lemma == _COMMANDER:
            return "UNIT_TITLE"
    if family == "HEB" and word.lemma == _ARAMAIC_ONE and following is not None and following.subtype == "cardinal number":
        return "FREQUENCY"  # חַד־שִׁבְעָה "seven times (hotter)"
    previous = words[position - 1] if position else None
    if family == "HEB" and previous is not None and previous.lemma == _ARAMAIC_ONE:
        return "FREQUENCY"
    if expression.kind == "CARDINAL" and expression.value == 1 and not _near_date(words, expression) \
            and not _numbers_a_thing(words, word, family):
        return "PRONOUN_ONE"
    if family == "HEB" and expression.value == 2 and following is not None and following.pos == "suffix" \
            and following.position == word.position:
        return "BOTH"  # שְׁנֵיהֶם "the two of them"
    if expression.value in _INDEFINITE_PLURALS and word.number == "plural" \
            and (family == "HEB" or word.lemma in _GRK_SCALE_NOUNS):
        return "INDEFINITE_PLURAL"  # "thousands", "tens of thousands", "commanders of hundreds"
    return None


def _scoped(words: list[Word], family: str) -> tuple[list[Expression], list[tuple[Expression, str]]]:
    """Composed expressions of one verse, split into counted and out of scope (with the reason)."""
    expressions = compose(words, CLASSIFIERS[family], split_adjacent_units=_SPLIT_ADJACENT_UNITS[family])
    _ordinal_parts(words, expressions, greek_part if family == "GRK" else ordinal_part)
    kept, dropped = [], []
    for expression in expressions:
        why = scope_reason(words, expression, family)
        if why is None:
            kept.append(expression)
        else:
            dropped.append((expression, why))
    return kept, dropped


def typed_values(path: Path, family: str) -> list[TypedValue]:
    """Compose every verse of one pinned MACULA table into typed values."""
    records: list[TypedValue] = []
    for ref, words in read_verses(path, family).items():
        expressions, _dropped = _scoped(words, family)
        for number, expression in enumerate(expressions, 1):
            chain = counted_phrase(words, expression, family)
            nouns = [word for word in chain if word.pos == "noun"]
            unit = (nouns[0] if family == "HEB" and nouns else nouns[0] if nouns else None) or _unit_after(words, expression)
            records.append(TypedValue(
                ol_ref=ref, family=family, expression_no=number, value=expression.value,
                kind=expression.kind, role=_role(expression, unit),
                word_ids=tuple(word.word_id for word in expression.words),
                surface=" ".join(word.text for word in expression.words),
                lemmas=tuple(word.lemma for word in expression.words),
                unit_lemma=unit.lemma if unit else "", unit_gloss=unit.gloss if unit else "",
                referent=referent_gloss(chain),
            ))
    return records


def _ordinal_parts(words: list[Word], expressions: list[Expression], part_of) -> None:
    """Turn an ordinal that names a part into its fraction ("a tenth of an ephah", "a third of the earth")."""
    for expression in expressions:
        if expression.kind != "ORDINAL" or len(expression.words) != 1:
            continue
        position = words.index(expression.words[0])
        following = next((word for word in words[position + 1:position + 3]
                          if word.subtype != "definite article" and word.pos != "det"), None)
        part = part_of(expression.words[0], following)
        if part is not None:
            expression.value, expression.kind = part, "FRACTION"


def scoped_out(path: Path, family: str) -> dict[str, list[tuple[Fraction, str]]]:
    """Per verse, the composed values the scope removed and why (to explain package differences)."""
    found: dict[str, list[tuple[Fraction, str]]] = {}
    for ref, words in read_verses(path, family).items():
        for expression, why in _scoped(words, family)[1]:
            found.setdefault(ref, []).append((expression.value, why))
    return found


def explain(extra: Counter, removed: list[tuple[Fraction, str]]) -> str:
    """The scope reasons that account for every package-only value, or "" when some stay unexplained."""
    left, reasons = Counter(extra), []
    for value, why in removed:
        if left[value] > 0:
            left[value] -= 1
            reasons.append(why)
    return "" if +left else ";".join(sorted(set(reasons)))


@dataclass(frozen=True)
class ExcludedWord:
    """A number-like original-language word the convention does not count, with the reason."""

    ol_ref: str
    family: str
    word_id: str
    surface: str
    lemma: str
    gloss: str
    reason: str


def excluded_words(path: Path, family: str) -> list[ExcludedWord]:
    """Every tagged numeral or known homograph that composition did not count."""
    found = []
    for ref, words in read_verses(path, family).items():
        kept, dropped = _scoped(words, family)
        counted = {word.word_id for expression in kept for word in expression.words}
        scoped = {word.word_id: why for expression, why in dropped for word in expression.words}
        for word in words:
            if word.word_id in counted:
                continue
            if word.word_id in scoped:
                found.append(ExcludedWord(ref, family, word.word_id, word.text, word.lemma,
                                          word.english or word.gloss, f"SCOPE_{scoped[word.word_id]}"))
                continue
            reason = exclusion_reason(word)
            if reason is not None:
                found.append(ExcludedWord(ref, family, word.word_id, word.text, word.lemma,
                                          word.english or word.gloss, reason))
    return found


def western_mapper(mapping_path: Path):
    """Map an original-language (ORG) coordinate to its Western (ENG) coordinate."""
    schema = parse_vrs_file(mapping_path, schema_id="nca-western", canonical_id="org")

    def western(ol_ref: str) -> str:
        """The first Western coordinate an OL coordinate maps to (itself when unmapped)."""
        local = sorted(schema.canonical_to_local(_parse_ref(ol_ref)), key=lambda ref: (ref.chapter, ref.verse))
        return local[0].label() if local else ol_ref

    return western


def _values(raw: str) -> Counter:
    """Parse one package value list into a multiset."""
    return Counter(Fraction(item) for item in raw.split(";") if item.strip())


def current_index(reference_root: Path) -> dict[str, dict[str, str]]:
    """Current package rows keyed by OL reference (rows without an OL coordinate skipped)."""
    with (reference_root / "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv").open(encoding="utf-8", newline="") as handle:
        return {row["OL_REF"]: row for row in csv.DictReader(handle, delimiter="\t") if row["OL_REF"]}


def overrides_by_ref(reference_root: Path) -> dict[str, list[str]]:
    """Normalization override layers recorded per OL reference in the current package."""
    found: dict[str, list[str]] = {}
    with (reference_root / "normalization_overrides.tsv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["OL_REF"]:
                found.setdefault(row["OL_REF"], []).append(f"{row['LAYER']}:{row['RULE_CLASS']}")
    return found


def regression(records: list[TypedValue], reference_root: Path) -> list[dict[str, str]]:
    """Diff rebuilt verse rollups against the current package: AGREE/CHANGED/NEW/DROPPED."""
    index = current_index(reference_root)
    overrides = overrides_by_ref(reference_root)
    built: dict[str, list[TypedValue]] = {}
    for record in records:
        built.setdefault(record.ol_ref, []).append(record)
    families = {record.family for record in records}
    language = {"HEB": "HEB", "GRK": "GRK"}
    refs = set(built) | {ref for ref, row in index.items() if row["LANG"] in {language[f] for f in families}}
    rows = []
    for ref in sorted(refs, key=lambda label: (label.split()[0], *map(int, label.split()[1].split(":")))):
        mine = Counter(record.value for record in built.get(ref, ()))
        row = index.get(ref)
        theirs = _values(row["OL_VALUES"]) if row else Counter()
        if mine == theirs:
            status = "AGREE"
        elif not theirs:
            status = "NEW"
        elif not mine:
            status = "DROPPED"
        else:
            status = "CHANGED"
        rows.append({
            "OL_REF": ref,
            "STATUS": status,
            "REBUILT_VALUES": ";".join(str(record.value) for record in built.get(ref, ())),
            "INDEX_VALUES": row["OL_VALUES"] if row else "",
            "REBUILT_KINDS": ";".join(record.kind for record in built.get(ref, ())),
            "REBUILT_SURFACE": " | ".join(record.surface for record in built.get(ref, ())),
            "INDEX_MATCH_STATUS": row["MATCH_STATUS"] if row else "",
            "INDEX_OVERRIDES": ",".join(sorted(set(overrides.get(ref, ())))),
            "NIV_VALUES": row["NIV_VALUES"] if row else "",
        })
    return rows


def source_manifest() -> dict[str, dict[str, str]]:
    """Pinned source identities recorded with every build."""
    return {family: {key: value for key, value in source.items()} for family, source in SOURCES.items()}
