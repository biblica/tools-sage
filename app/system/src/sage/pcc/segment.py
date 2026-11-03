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
from collections.abc import Iterable
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
