"""PCC segmenter: NFC-aware tokens with Unicode code-point offsets (handover doc 03, plan P2).

Offsets index the text exactly as given (``text[start:end] == token.text``), so a span always
reconstructs byte-exact from the raw visible body text. Comparison happens on ``Token.norm`` (NFC, and
casefolded only when the caller says the text is cased). Diacritics are never stripped here.

Nothing is chosen by language code. What varies is passed in as measured or team-declared traits:
``cased``, ``letter_marks`` (apostrophe-like code points that are letters in this text) and whether
the script is unspaced. Unspaced scripts get one token per character cluster and the caller must report
segmentation ``PARTIAL`` (a whitespace/char tokenizer is not a word segmenter).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# Scripts written without spaces between words (same set as name_alignment).
UNSPACED_SCRIPTS = ("CJK", "HIRAGANA", "KATAKANA", "THAI", "LAO", "KHMER", "MYANMAR", "TIBETAN")
# Code points that may be a letter (glottal stop, saltillo) or a quote/apostrophe.
APOSTROPHE_LIKE = ("'", "’", "ʼ", "ꞌ", "ʻ", "‘")


def nfc(text: str) -> str:
    """Canonical composition, the only normalization applied unconditionally."""
    return unicodedata.normalize("NFC", str(text))


def is_unspaced_char(char: str) -> bool:
    """True for a letter of a script written without spaces."""
    return char.isalpha() and unicodedata.name(char, "").startswith(UNSPACED_SCRIPTS)


@dataclass(frozen=True)
class Token:
    """One token: the raw slice, its comparison form and its code-point span."""

    text: str
    norm: str
    start: int
    end: int


def normalize_token(text: str, *, cased: bool) -> str:
    """Comparison form of one token: NFC, plus casefold and NFC again when the text is cased."""
    out = nfc(text)
    return nfc(out.casefold()) if cased else out


def _is_mark(char: str) -> bool:
    """Implement is mark."""
    return unicodedata.category(char).startswith("M")


def tokenize(
    text: str,
    *,
    cased: bool = True,
    letter_marks: Iterable[str] = (),
    unspaced: bool = False,
) -> list[Token]:
    """Split ``text`` into tokens with offsets into ``text`` itself.

    A token is a run of letters with their combining marks, digits-free. Code points in
    ``letter_marks`` count as letters when a letter sits on both sides (or, for a mark in the set,
    directly before a letter at word start, as in a leading glottal stop). With ``unspaced`` true each
    letter of an unspaced script is its own token (with its marks).
    """
    marks = frozenset(letter_marks)
    tokens: list[Token] = []
    n = len(text)
    i = 0
    while i < n:
        char = text[i]
        if not char.isalpha():
            i += 1
            continue
        start = i
        i += 1
        if unspaced and is_unspaced_char(char):
            while i < n and _is_mark(text[i]):
                i += 1
        else:
            while i < n:
                c = text[i]
                if c.isalpha() and not (unspaced and is_unspaced_char(c)) or _is_mark(c):
                    i += 1
                elif c in marks and i + 1 < n and text[i + 1].isalpha():
                    i += 1
                else:
                    break
        raw = text[start:i]
        tokens.append(Token(raw, normalize_token(raw, cased=cased), start, i))
    return tokens


def span_text(text: str, first: Token, last: Token) -> str:
    """The exact raw slice covering ``first`` through ``last``."""
    return text[first.start:last.end]


# --- elided prefixes (plan §5b.3 finding 4) -------------------------------------------------------
# A token such as French "l'écriture" holds an elided prefix when the apostrophe is measured as a letter.
# The prefix is split off when the text itself shows it: short, followed by many different remainders that
# are frequent words on their own. Measured per text, never chosen by language code.
ELISION_MAX_LETTERS = 3
ELISION_MIN_REMAINDER = 3     # a remainder counts when it occurs at least this often as a word on its own
ELISION_MIN_VARIETY = 10      # distinct counted remainders a prefix needs
ELISION_MIN_SHARE = 0.5       # share of the prefix's uses whose remainder counts


def _elision_cut(token: Token, marks: frozenset[str]) -> int | None:
    """Index in ``token.text`` just after a short leading prefix ending in a letter mark, if any."""
    for k, char in enumerate(token.text[:ELISION_MAX_LETTERS + 1]):
        if char in marks:
            return k + 1 if 0 < k and k + 1 < len(token.text) else None
    return None


def measure_elisions(token_lists: Iterable[Iterable[Token]], letter_marks: Iterable[str]) -> frozenset[str]:
    """Elided prefixes (comparison form, e.g. ``l'``) that this text shows, or none."""
    marks = frozenset(letter_marks)
    if not marks:
        return frozenset()
    standalone: dict[str, int] = {}
    pairs: list[tuple[str, str]] = []
    for tokens in token_lists:
        for token in tokens:
            standalone[token.norm] = standalone.get(token.norm, 0) + 1
            cut = _elision_cut(token, marks)
            if cut is not None:
                pairs.append((nfc(token.text[:cut].casefold()), nfc(token.text[cut:].casefold())))
    uses: dict[str, int] = {}
    variety: dict[str, set[str]] = {}
    counted: dict[str, int] = {}
    for prefix, rest in pairs:
        uses[prefix] = uses.get(prefix, 0) + 1
        if standalone.get(rest, 0) >= ELISION_MIN_REMAINDER or standalone.get(rest.capitalize(), 0) >= ELISION_MIN_REMAINDER:
            counted[prefix] = counted.get(prefix, 0) + 1
            variety.setdefault(prefix, set()).add(rest)
    return frozenset(p for p in uses if len(variety.get(p, ())) >= ELISION_MIN_VARIETY
                     and counted.get(p, 0) / uses[p] >= ELISION_MIN_SHARE)


def split_elisions(tokens: Iterable[Token], prefixes: frozenset[str], letter_marks: Iterable[str]) -> list[Token]:
    """Split each measured elided prefix off its word; offsets still index the original text."""
    marks = frozenset(letter_marks)
    out: list[Token] = []
    for token in tokens:
        cut = _elision_cut(token, marks) if prefixes else None
        if cut is not None and nfc(token.text[:cut].casefold()) in prefixes:
            cased = token.norm != nfc(token.text)
            head, tail = token.text[:cut], token.text[cut:]
            out.append(Token(head, normalize_token(head, cased=cased), token.start, token.start + cut))
            out.append(Token(tail, normalize_token(tail, cased=cased), token.start + cut, token.end))
        else:
            out.append(token)
    return out


SENTENCE_END = frozenset(".!?;:։؟।॥。！？")


def at_sentence_start(text: str, tokens: Sequence[Token], index: int) -> bool:
    """True when ``tokens[index]`` opens the text or follows sentence-ending or opening-quote punctuation."""
    if index == 0:
        return True
    gap = text[tokens[index - 1].end:tokens[index].start]
    return any(c in SENTENCE_END or unicodedata.category(c) in ("Pi", "Ps") for c in gap)


def case_feature(token: Token) -> str:
    """``UPPER`` when the token starts with a capital, ``LOWER`` when with a small letter, else ``""``."""
    first = token.text[:1]
    return "UPPER" if first.isupper() else "LOWER" if first.islower() else ""
