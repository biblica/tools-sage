"""Scripture book aliases, scope parsing, and coordinate selection helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .errors import ValidationError
from .vrs import VerseRef, VersificationSchema


_BOOK_NAMES = {
    "GEN": ("genesis", "gen"),
    "EXO": ("exodus", "exo", "exod"),
    "LEV": ("leviticus", "lev"),
    "NUM": ("numbers", "num"),
    "DEU": ("deuteronomy", "deu", "deut"),
    "JOS": ("joshua", "jos", "josh"),
    "JDG": ("judges", "jdg", "judg"),
    "RUT": ("ruth", "rut"),
    "1SA": ("1samuel", "1sam", "isamuel"),
    "2SA": ("2samuel", "2sam", "iisamuel"),
    "1KI": ("1kings", "1kgs", "ikings"),
    "2KI": ("2kings", "2kgs", "iikings"),
    "1CH": ("1chronicles", "1chr", "ichronicles"),
    "2CH": ("2chronicles", "2chr", "iichronicles"),
    "EZR": ("ezra", "ezr"),
    "NEH": ("nehemiah", "neh"),
    "EST": ("esther", "est"),
    "JOB": ("job",),
    "PSA": ("psalms", "psalm", "psa", "ps"),
    "PRO": ("proverbs", "pro", "prov"),
    "ECC": ("ecclesiastes", "ecc", "eccl"),
    "SNG": ("songofsolomon", "songofsongs", "songs", "sng", "canticles"),
    "ISA": ("isaiah", "isa"),
    "JER": ("jeremiah", "jer"),
    "LAM": ("lamentations", "lam"),
    "EZK": ("ezekiel", "ezk", "eze"),
    "DAN": ("daniel", "dan"),
    "HOS": ("hosea", "hos"),
    "JOL": ("joel", "jol"),
    "AMO": ("amos", "amo"),
    "OBA": ("obadiah", "oba", "obad"),
    "JON": ("jonah", "jon"),
    "MIC": ("micah", "mic"),
    "NAM": ("nahum", "nam", "nah"),
    "HAB": ("habakkuk", "hab"),
    "ZEP": ("zephaniah", "zep", "zeph"),
    "HAG": ("haggai", "hag"),
    "ZEC": ("zechariah", "zec", "zech"),
    "MAL": ("malachi", "mal"),
    "MAT": ("matthew", "mat", "matt"),
    "MRK": ("mark", "mrk"),
    "LUK": ("luke", "luk"),
    "JHN": ("john", "jhn", "joh"),
    "ACT": ("acts", "act"),
    "ROM": ("romans", "rom"),
    "1CO": ("1corinthians", "1cor", "icorinthians"),
    "2CO": ("2corinthians", "2cor", "iicorinthians"),
    "GAL": ("galatians", "gal"),
    "EPH": ("ephesians", "eph"),
    "PHP": ("philippians", "php", "phil"),
    "COL": ("colossians", "col"),
    "1TH": ("1thessalonians", "1thess", "ithessalonians"),
    "2TH": ("2thessalonians", "2thess", "iithessalonians"),
    "1TI": ("1timothy", "1tim", "itimothy"),
    "2TI": ("2timothy", "2tim", "iitimothy"),
    "TIT": ("titus", "tit"),
    "PHM": ("philemon", "phm", "philem"),
    "HEB": ("hebrews", "heb"),
    "JAS": ("james", "jas", "jam"),
    "1PE": ("1peter", "1pet", "ipeter"),
    "2PE": ("2peter", "2pet", "iipeter"),
    "1JN": ("1john", "1jn", "ijohn"),
    "2JN": ("2john", "2jn", "iijohn"),
    "3JN": ("3john", "3jn", "iiijohn"),
    "JUD": ("jude", "jud"),
    "REV": ("revelation", "rev", "apocalypse"),
}


def _normalize_book(value: str) -> str:
    """Resolve a book alias to its canonical USFM code or raise a scope error."""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


BOOK_ORDER = {code: index for index, code in enumerate(_BOOK_NAMES, start=1)}
def _book_label(value: str) -> str:
    """Return the standard human-readable label for one canonical book code."""
    spaced = re.sub(r"^([1-3])(?=[a-z])", r"\1 ", value)
    return spaced.replace("of", " of ").title()


BOOK_LABELS = {code: _book_label(names[0]) for code, names in _BOOK_NAMES.items()}

BOOK_ALIASES: dict[str, str] = {}
for _code, _names in _BOOK_NAMES.items():
    BOOK_ALIASES[_normalize_book(_code)] = _code
    for _name in _names:
        BOOK_ALIASES[_normalize_book(_name)] = _code


@dataclass(frozen=True)
class ScriptureScope:
    """One book, chapter, verse, or cross-chapter scope."""

    book: str
    start_chapter: int | None = None
    start_verse: int | None = None
    end_chapter: int | None = None
    end_verse: int | None = None

    def label(self) -> str:
        """Return the operator-facing label for this Scripture scope."""
        if self.start_chapter is None:
            return self.book
        if self.start_verse is None:
            if self.end_chapter and self.end_chapter != self.start_chapter:
                return f"{self.book} {self.start_chapter}-{self.end_chapter}"
            return f"{self.book} {self.start_chapter}"
        end_chapter = self.end_chapter or self.start_chapter
        end_verse = self.end_verse or self.start_verse
        if end_chapter == self.start_chapter and end_verse == self.start_verse:
            return f"{self.book} {self.start_chapter}:{self.start_verse}"
        if end_chapter == self.start_chapter:
            return f"{self.book} {self.start_chapter}:{self.start_verse}-{end_verse}"
        return (
            f"{self.book} {self.start_chapter}:{self.start_verse}-"
            f"{end_chapter}:{end_verse}"
        )

    def contains(self, ref: VerseRef) -> bool:
        """Return whether this scope contains the supplied Scripture reference."""
        if ref.book != self.book:
            return False
        if self.start_chapter is None:
            return True
        if self.start_verse is None:
            end_chapter = self.end_chapter or self.start_chapter
            return self.start_chapter <= ref.chapter <= end_chapter
        start = (self.start_chapter, self.start_verse)
        end = (self.end_chapter or self.start_chapter, self.end_verse or self.start_verse)
        return start <= (ref.chapter, ref.verse) <= end


_SCOPE_RE = re.compile(
    r"^(?P<book>.+?)"
    r"(?:\s+(?P<chapter>\d+)"
    r"(?:-(?P<end_chapter_only>\d+)|"
    r"\:(?P<verse>\d+)"
    r"(?:-(?:(?P<end_chapter>\d+)\:)?(?P<end_verse>\d+))?"
    r")?"
    r")?$"
)


def resolve_book(value: str) -> str:
    """Resolve a USFM code or common English book name to a USFM code."""
    key = _normalize_book(value)
    try:
        return BOOK_ALIASES[key]
    except KeyError as exc:
        raise ValidationError(f"Unknown Scripture book: {value!r}") from exc


def parse_scope(value: str) -> ScriptureScope:
    """Parse a book, chapter, verse, or cross-chapter operator scope."""
    cleaned = value.strip()
    match = _SCOPE_RE.fullmatch(cleaned)
    if not match:
        raise ValidationError(f"Invalid Scripture scope: {value!r}")
    book = resolve_book(match.group("book"))
    chapter_text = match.group("chapter")
    verse_text = match.group("verse")
    if chapter_text is None:
        return ScriptureScope(book=book)
    chapter = int(chapter_text)
    if chapter <= 0:
        raise ValidationError(f"Chapter must be positive: {value!r}")
    if verse_text is None:
        end_chapter_only = int(match.group("end_chapter_only") or chapter)
        if end_chapter_only < chapter:
            raise ValidationError(f"Chapter-range end precedes start: {value!r}")
        return ScriptureScope(
            book=book,
            start_chapter=chapter,
            end_chapter=end_chapter_only,
        )
    verse = int(verse_text)
    if verse < 0:
        raise ValidationError(f"Verse must not be negative: {value!r}")
    end_chapter = int(match.group("end_chapter") or chapter)
    end_verse = int(match.group("end_verse") or verse)
    if (end_chapter, end_verse) < (chapter, verse):
        raise ValidationError(f"Scope end precedes start: {value!r}")
    return ScriptureScope(
        book=book,
        start_chapter=chapter,
        start_verse=verse,
        end_chapter=end_chapter,
        end_verse=end_verse,
    )


def expand_scope(
    scope: ScriptureScope,
    available: Iterable[VerseRef],
) -> tuple[VerseRef, ...]:
    """Select ordered available coordinates intersecting a scope."""
    selected = tuple(sorted(ref for ref in set(available) if scope.contains(ref)))
    if not selected:
        raise ValidationError(f"Scope does not intersect available coordinates: {scope.label()}")
    return selected


def expand_scope_with_schema(scope: ScriptureScope, schema: VersificationSchema) -> tuple[VerseRef, ...]:
    """Expand a scope using chapter maxima from one effective VRS schema."""
    if scope.book not in schema.chapter_max:
        raise ValidationError(
            f"Book {scope.book} is not defined by VRS schema {schema.schema_id}"
        )
    refs: list[VerseRef] = []
    for chapter, maximum in sorted(schema.chapter_max[scope.book].items()):
        for verse in range(1, maximum + 1):
            ref = VerseRef(scope.book, chapter, verse)
            if ref in schema.exclusions:
                continue
            if scope.contains(ref):
                refs.append(ref)
    if not refs:
        raise ValidationError(f"Scope is empty under VRS schema {schema.schema_id}: {scope.label()}")
    return tuple(refs)


def split_scope_book(value: str) -> tuple[str, str]:
    """Split an operator scope into its book token and untouched numeric suffix."""
    cleaned = value.strip()
    match = re.match(r"^(?P<book>.*?)(?P<suffix>\s+\d.*)?$", cleaned)
    if not match:
        return cleaned, ""
    return match.group("book").strip(), match.group("suffix") or ""


def replace_scope_book(value: str, book: str) -> str:
    """Replace only the book portion of a Scripture scope."""
    _, suffix = split_scope_book(value)
    return f"{book}{suffix}".strip()


def parse_reference_set(value: str, schema: VersificationSchema) -> frozenset[VerseRef]:
    """Parse a local reference and expand it under a resource VRS schema."""
    return frozenset(expand_scope_with_schema(parse_scope(value), schema))
