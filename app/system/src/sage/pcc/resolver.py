"""PCC rule scopes and the rule resolver (plan P7-1..P7-3, handover doc 04; AT13, AT14, AT23, AT24).

A glossary rule (``variant_rule``) has one scope:

* ``OCCURRENCE``: one occurrence, identified as ``<verse ref>|<nth occurrence of the group in it>|<verse hash>``;
* ``PASSAGE``: a reference range, ``<range>#<passage hash>`` (a range without ``#`` is not text-bound);
* ``SECG``: the whole group (concept + sense);
* ``LANGUAGE_PROFILE``: a WIP-language rule, group ``LANGUAGE``; an approved ``a=b`` form declares a spelling
  equivalence (see ``language_equivalences``).

The verse hash covers the SOURCE verse and the paired WIP verse(s); the passage hash covers the WIP verses of the
range. When the text under a bound rule changes, the rule no longer applies: it is reported **stale** and listed
for review, never deleted, never accepting (AT13).

``resolve`` is pure: among the **approved** rules that apply at a site and match the form, the most specific scope
wins (occurrence > passage > group > language), so a more specific ``REJECT`` beats a broader ``ACCEPT`` (AT24).
``PROPOSED``, ``REVOKED`` and ``STALE`` rules never accept (AT23). Approved ``ACCEPT`` (or ``CONTEXT_ONLY``) and
``REJECT`` of the same form at the same, highest specificity is a conflict: ``PC23`` for that group only (AT14).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from ..references import parse_scope
from ..vrs import VerseRef

SPECIFICITY = {"OCCURRENCE": 4, "PASSAGE": 3, "SECG": 2, "LANGUAGE_PROFILE": 1, "NORMALIZATION": 0}
LANGUAGE_GROUP = "LANGUAGE"
ACCEPTING = ("ACCEPT", "CONTEXT_ONLY")


def text_hash(*texts: str) -> str:
    """16 hex of SHA-256 over the texts (unit separator between them)."""
    return hashlib.sha256("\x1f".join(texts).encode("utf-8")).hexdigest()[:16]


def _ref(label: str) -> VerseRef:
    """``BOOK C:V`` -> VerseRef."""
    book, _, cv = label.partition(" ")
    chapter, _, verse = cv.partition(":")
    return VerseRef(book, int(chapter), int(verse))


def occurrence_identifier(ref: str, nth: int, verse_hash: str) -> str:
    """Scope identifier of one occurrence."""
    return f"{ref}|{nth}|{verse_hash}"


def passage_hash(verse_hashes: Mapping[str, str], passage: str) -> str:
    """Hash of the WIP verses inside ``passage`` (``verse_hashes``: canonical ref -> verse text hash)."""
    scope = parse_scope(passage)
    inside = sorted((ref, h) for ref, h in verse_hashes.items() if scope.contains(_ref(ref)))
    return text_hash(*(f"{ref}={h}" for ref, h in inside))


def passage_identifier(passage: str, verse_hashes: Mapping[str, str]) -> str:
    """Scope identifier of a text-bound passage."""
    return f"{passage}#{passage_hash(verse_hashes, passage)}"


@dataclass(frozen=True)
class Site:
    """Where a form was found: group, SOURCE reference, nth occurrence of the group in the verse, verse hash."""

    group_id: str
    ref: str
    nth: int
    verse_hash: str


def applies(rule: Mapping[str, object], site: Site, verse_hashes: Mapping[str, str]) -> str:
    """``YES``, ``NO`` or ``STALE`` (the rule's scope covers the site but its text changed)."""
    scope = rule["scope"]
    level, ident = scope["level"], scope["identifier"]
    if level == "LANGUAGE_PROFILE":
        return "YES"
    if rule["group_id"] != site.group_id:
        return "NO"
    if level == "SECG":
        return "YES"
    if level == "OCCURRENCE":
        ref, _, rest = ident.partition("|")
        nth, _, bound = rest.partition("|")
        if ref != site.ref or nth != str(site.nth):
            return "NO"
        return "YES" if not bound or bound == site.verse_hash else "STALE"
    if level == "PASSAGE":
        passage, _, bound = ident.partition("#")
        try:
            if not parse_scope(passage).contains(_ref(site.ref)):
                return "NO"
        except Exception:  # noqa: BLE001 - an unreadable passage never applies
            return "NO"
        return "YES" if not bound or bound == passage_hash(verse_hashes, passage) else "STALE"
    return "NO"


@dataclass(frozen=True)
class Resolution:
    """The decision at one site for one form."""

    effect: str | None            # ACCEPT | CONTEXT_ONLY | REJECT | CONFLICT | None (no approved rule)
    rule_ids: tuple[str, ...] = ()
    level: str = ""
    stale: tuple[str, ...] = ()


def resolve(rules: Iterable[Mapping[str, object]], site: Site, form_key: str, key_of: Callable[[str], str],
            verse_hashes: Mapping[str, str] | None = None) -> Resolution:
    """Most specific approved rule for ``form_key`` at ``site`` (see module doc)."""
    hashes = verse_hashes or {}
    live: list[Mapping[str, object]] = []
    stale: list[str] = []
    for rule in rules:
        form = str(rule["normalized_target_form"])
        if "=" in form and rule["scope"]["level"] == "LANGUAGE_PROFILE":
            continue  # a spelling equivalence, not a rendering
        if key_of(form) != form_key:
            continue
        where = applies(rule, site, hashes)
        if where == "NO":
            continue
        if rule["state"] != "APPROVED":
            continue
        if where == "STALE":
            stale.append(str(rule["rule_id"]))
            continue
        live.append(rule)
    if not live:
        return Resolution(None, stale=tuple(sorted(stale)))
    top = max(SPECIFICITY[str(r["scope"]["level"])] for r in live)
    winners = [r for r in live if SPECIFICITY[str(r["scope"]["level"])] == top]
    effects = {str(r["effect"]) for r in winners}
    level = str(winners[0]["scope"]["level"])
    ids = tuple(sorted(str(r["rule_id"]) for r in winners))
    if "REJECT" in effects and effects & set(ACCEPTING):
        return Resolution("CONFLICT", ids, level, tuple(sorted(stale)))
    effect = "REJECT" if "REJECT" in effects else "ACCEPT" if "ACCEPT" in effects else "CONTEXT_ONLY"
    return Resolution(effect, tuple(sorted(str(r["rule_id"]) for r in winners if r["effect"] == effect)), level,
                      tuple(sorted(stale)))


def language_equivalences(rules: Iterable[Mapping[str, object]]) -> dict[str, str]:
    """Approved LANGUAGE_PROFILE ``a=b`` rules as spelling equivalences (variant -> preferred)."""
    found = {}
    for rule in rules:
        form = str(rule["normalized_target_form"])
        if rule["scope"]["level"] == "LANGUAGE_PROFILE" and rule["state"] == "APPROVED" and "=" in form:
            a, _, b = form.partition("=")
            if a.strip() and b.strip():
                found[" ".join(a.casefold().split())] = " ".join(b.casefold().split())
    return found
