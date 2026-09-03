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


@dataclass(frozen=True)
class ScriptureScopeSet:
    """One ordered, non-overlapping set of scopes within a single Scripture book."""

    portions: tuple[ScriptureScope, ...]

    @property
    def book(self) -> str:
        """Return the one canonical book shared by every selected portion."""
        return self.portions[0].book

    def label(self) -> str:
        """Return the canonical operator-facing selection label."""
        return "; ".join(portion.label() for portion in self.portions)

    def contains(self, ref: VerseRef) -> bool:
        """Return whether any selected portion contains the supplied reference."""
        return any(portion.contains(ref) for portion in self.portions)


AnalysisScope = ScriptureScope | ScriptureScopeSet


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



def parse_scope_set(value: str) -> tuple[ScriptureScope, ...]:
    """Parse one or more semicolon-separated Scripture portions.

    Each portion is a normal SAGE Scripture scope. The canonical book may be
    repeated for every portion (preferred) or omitted after the first portion
    when the continuation begins with a chapter number. Finding citations use
    this directly; RTC/STC Run input adds same-book/non-overlap validation through
    :func:`parse_analysis_scope`.
    """
    cleaned = str(value).strip()
    if not cleaned:
        raise ValidationError("Scripture reference set must not be empty")
    raw_parts = [part.strip() for part in cleaned.split(";")]
    if any(not part for part in raw_parts):
        raise ValidationError(f"Invalid Scripture reference set: {value!r}")
    scopes: list[ScriptureScope] = []
    inherited_book: str | None = None
    for part in raw_parts:
        candidate = part
        if inherited_book is not None and re.fullmatch(
            r"\d+(?:-\d+|:\d+(?:-(?:\d+:)?\d+)?)?",
            candidate,
        ):
            candidate = f"{inherited_book} {candidate}"
        scope = parse_scope(candidate)
        if inherited_book is None:
            inherited_book = scope.book
        scopes.append(scope)
    return tuple(scopes)


def normalize_scope_set(value: str) -> str:
    """Return a canonical display string for a semicolon-separated reference set."""
    return "; ".join(scope.label() for scope in parse_scope_set(value))


def _scope_bounds(scope: ScriptureScope) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return inclusive sortable bounds for overlap validation."""
    if scope.start_chapter is None:
        return (0, 0), (10**9, 10**9)
    start_verse = scope.start_verse if scope.start_verse is not None else 0
    end_chapter = scope.end_chapter or scope.start_chapter
    end_verse = scope.end_verse if scope.start_verse is not None else 10**9
    return (scope.start_chapter, start_verse), (end_chapter, end_verse)


def parse_analysis_scope(value: str) -> AnalysisScope:
    """Parse a contiguous scope or a same-book RTC/STC Run scope selection.

    Semicolons select independent portions for one Run. Numeric portions after
    the first inherit its book, so ``1CH 5-6; 24`` is canonicalized as
    ``1CH 5-6; 1CH 24``. Portions are ordered and may not overlap, preventing a
    coordinate from being reviewed twice under one governed Run.
    """
    portions = parse_scope_set(value)
    books = {portion.book for portion in portions}
    if len(books) != 1:
        raise ValidationError(
            "RTC/STC Run scope portions must remain within one Scripture book"
        )
    ordered = tuple(sorted(portions, key=lambda portion: _scope_bounds(portion)[0]))
    previous_end: tuple[int, int] | None = None
    for portion in ordered:
        start, end = _scope_bounds(portion)
        if previous_end is not None and start <= previous_end:
            raise ValidationError(
                f"RTC/STC Run scope portions overlap: {value!r}"
            )
        previous_end = end
    if len(ordered) == 1:
        return ordered[0]
    return ScriptureScopeSet(ordered)


def analysis_scope_portions(scope: AnalysisScope) -> tuple[ScriptureScope, ...]:
    """Return the independently planned portions of one analysis scope."""
    if isinstance(scope, ScriptureScopeSet):
        return scope.portions
    return (scope,)


def expand_reference_atoms(values: str | Iterable[str]) -> tuple[VerseRef, ...]:
    """Expand verse/range labels into ordered atomic Scripture coordinates.

    Coverage reconciliation deliberately uses this one contract rather than raw
    bridge labels.  Chapter/book scopes and cross-chapter ranges cannot be
    expanded safely without an effective VRS, so governed coverage inventories
    must supply verse-bounded, single-chapter portions.
    """
    raw_values = (values,) if isinstance(values, str) else tuple(values)
    atoms: list[VerseRef] = []
    for value in raw_values:
        label = str(value).strip()
        if not label:
            raise ValidationError("Scripture coverage references must not be empty")
        for scope in parse_scope_set(label):
            if scope.start_chapter is None or scope.start_verse is None:
                raise ValidationError(
                    f"Coverage reference must identify verse coordinates: {label}"
                )
            end_chapter = scope.end_chapter or scope.start_chapter
            end_verse = scope.end_verse or scope.start_verse
            if end_chapter != scope.start_chapter:
                raise ValidationError(
                    f"Coverage reference portions may not cross chapters: {label}"
                )
            atoms.extend(
                VerseRef(scope.book, scope.start_chapter, verse)
                for verse in range(scope.start_verse, end_verse + 1)
            )
    return tuple(atoms)


def atomic_reference_labels(values: str | Iterable[str]) -> tuple[str, ...]:
    """Return ordered atomic labels for a governed coverage inventory."""
    return tuple(ref.label() for ref in expand_reference_atoms(values))

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
