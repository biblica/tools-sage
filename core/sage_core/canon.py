"""Declared project scope, canon registries, roles, and expected-book resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .errors import ConfigurationError

BOOKS_66 = (
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA",
    "1KI", "2KI", "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO",
    "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS", "JOL", "AMO",
    "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL", "MAT",
    "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP",
    "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE",
    "2PE", "1JN", "2JN", "3JN", "JUD", "REV",
)
BOOK_ORDER = {code: index for index, code in enumerate(BOOKS_66, start=1)}
OT_39 = BOOKS_66[:39]
NT_27 = BOOKS_66[39:]
PROTESTANT_66 = OT_39 + NT_27
# USFM/Paratext stores publication matter beside Scripture using these book IDs.
# They belong to the Project resource hash but never to its declared biblical canon.
PERIPHERAL_BOOKS = frozenset(
    {"FRT", "INT", "BAK", "CNC", "GLO", "TDX", "NDX", "OTH"}
    | {f"XX{suffix}" for suffix in "ABCDEFG"}
)

CANON_BOOKS: dict[str, tuple[str, ...]] = {
    "PROTESTANT_66": PROTESTANT_66,
    "GREEK_NT_27": NT_27,
    "HEBREW_BIBLE_39": OT_39,
}

TESTAMENT_VALUES = {"FB", "OT", "NT", "PORTIONS"}
CANON_VALUES = set(CANON_BOOKS) | {"CUSTOM"}
PROJECT_ROLE_VALUES = {
    "CONTENT_SOURCE",
    "LEXICAL_DONOR",
    "REFERENCE",
    "AUXILIARY_SCRIPTURE",
    "ORIGINAL_LANGUAGE_GREEK",
    "ORIGINAL_LANGUAGE_HEBREW",
    "GENERATED_TARGET",
    "WIP",
}


@dataclass(frozen=True)
class ProjectScopeSpec:
    """Declared publication or analysis scope for one Scripture project."""

    testament: str
    canon: str
    expected_books: str | tuple[str, ...]
    roles: tuple[str, ...]


def normalize_book_list(values: Iterable[str], label: str) -> tuple[str, ...]:
    """Normalise and validate an explicit canonical book-ID list."""
    books = tuple(str(value).strip().upper() for value in values)
    if not books:
        raise ConfigurationError(f"{label} must contain at least one book ID")
    if any(not book for book in books):
        raise ConfigurationError(f"{label} must not contain empty book IDs")
    duplicates = sorted({book for book in books if books.count(book) > 1})
    if duplicates:
        raise ConfigurationError(f"{label} contains duplicate book IDs: {', '.join(duplicates)}")
    unknown = sorted(set(books) - set(BOOK_ORDER))
    if unknown:
        raise ConfigurationError(f"{label} contains unsupported book IDs: {', '.join(unknown)}")
    return tuple(sorted(books, key=BOOK_ORDER.__getitem__))


def normalize_roles(values: Iterable[str], label: str) -> tuple[str, ...]:
    """Normalise and validate an explicit project-role list."""
    roles = tuple(str(value).strip().upper() for value in values)
    # SAGE Project Inventory entries are role-neutral; workflow roles are injected by Job bindings.
    # Static fixture declarations may carry roles; operator SAGE Projects remain role-neutral.
    if not roles:
        return ()
    if any(not role for role in roles):
        raise ConfigurationError(f"{label} must not contain empty roles")
    duplicates = sorted({role for role in roles if roles.count(role) > 1})
    if duplicates:
        raise ConfigurationError(f"{label} contains duplicate roles: {', '.join(duplicates)}")
    unknown = sorted(set(roles) - PROJECT_ROLE_VALUES)
    if unknown:
        raise ConfigurationError(f"{label} contains unsupported roles: {', '.join(unknown)}")
    return tuple(sorted(roles))


def resolve_expected_books(scope: ProjectScopeSpec) -> tuple[str, ...]:
    """Resolve ``expected_books: auto`` from declared canon and testament."""
    if scope.expected_books != "auto":
        return tuple(scope.expected_books)
    if scope.testament == "PORTIONS":
        raise ConfigurationError(
            "scope.expected_books cannot be auto when scope.testament is PORTIONS"
        )
    if scope.canon == "CUSTOM":
        raise ConfigurationError("scope.expected_books cannot be auto when scope.canon is CUSTOM")
    try:
        canon_books = CANON_BOOKS[scope.canon]
    except KeyError as exc:
        raise ConfigurationError(f"Unsupported canon: {scope.canon}") from exc

    if scope.testament == "FB":
        selected = canon_books
    elif scope.testament == "OT":
        selected = tuple(book for book in canon_books if book in OT_39)
    elif scope.testament == "NT":
        selected = tuple(book for book in canon_books if book in NT_27)
    else:
        raise ConfigurationError(f"Unsupported testament: {scope.testament}")
    if not selected:
        raise ConfigurationError(
            f"Canon {scope.canon} does not provide books for testament {scope.testament}"
        )
    return selected


def validate_scope_compatibility(scope: ProjectScopeSpec) -> None:
    """Reject incompatible canon/testament and explicit-book combinations."""
    resolved = resolve_expected_books(scope)
    if scope.canon != "CUSTOM":
        outside = sorted(set(resolved) - set(CANON_BOOKS[scope.canon]), key=BOOK_ORDER.__getitem__)
        if outside:
            raise ConfigurationError(
                f"scope.expected_books fall outside canon {scope.canon}: {', '.join(outside)}"
            )
    if scope.testament == "OT":
        outside = sorted(set(resolved) - set(OT_39), key=BOOK_ORDER.__getitem__)
    elif scope.testament == "NT":
        outside = sorted(set(resolved) - set(NT_27), key=BOOK_ORDER.__getitem__)
    elif scope.testament in {"FB", "PORTIONS"}:
        outside = []
    else:
        outside = []
    if outside:
        raise ConfigurationError(
            f"scope.expected_books fall outside testament {scope.testament}: {', '.join(outside)}"
        )
