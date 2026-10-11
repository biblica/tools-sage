"""Find and read digit numerals in WIP text locally, without a model.

Digits are deterministic: SAGE reads them itself so a typed number never depends on model
interpretation, a numeral the model missed is still checked, and a malformed numeral
("10,0000", "1,00") is reported. Any Unicode decimal digit counts (Latin, Arabic-Indic,
Devanagari ...). Separators are a space, no-break or narrow no-break space, comma, period
or apostrophe.

Reading rules:
- with configured parsing conventions (style profile: grouping separator, decimal separator),
  a numeral is read strictly under them;
- without conventions, a grouped integer (each group after a separator has exactly three
  digits; Indian grouping 2-2-3 is accepted) is the reading when it is well formed; otherwise a
  decimal with one or two fraction digits and no trailing zero ("8,4", "2.75"). "1,000" is 1000,
  and "10,0000", "1,00", "5,40" have no reading (likely mistypes).
A numeral with no well-formed reading is MALFORMED.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re
import unicodedata
from typing import Mapping

_SEPARATORS = "   ,.'’"
# A no-break or narrow no-break space is the same group separator as a space ("12 000");
# a typographic apostrophe the same as a straight one.
_SAME = {"\u00a0": " ", "\u202f": " ", "’": "'"}


def _same(text: str) -> str:
    """One spelling per separator: no-break spaces as a space, typographic as straight apostrophe."""
    return "".join(_SAME.get(char, char) for char in text)
_NUMERAL = re.compile(r"\d+(?:[   ,.'’]\d+)*")


@dataclass(frozen=True)
class Numeral:
    """One digit numeral found in a text, with its possible readings."""

    text: str
    start: int
    end: int
    readings: tuple[Fraction, ...]
    suffixed: bool = False

    @property
    def malformed(self) -> bool:
        """No well-formed reading exists."""
        return not self.readings

    # ``suffixed``: a letter suffix follows ("2nd", "3-й", "5º"): an ordinal, which the counting
    # convention counts only inside a date, so SAGE never adds it as a cardinal by itself.


def _digits(text: str) -> str:
    """Latin digits for any Unicode decimal digits."""
    return "".join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in text)


def _grouped(parts: list[str], separators: list[str]) -> Fraction | None:
    """An integer written with one repeated group separator (Western 3-3-3 or Indian 2-2-3)."""
    if len(set(separators)) != 1:
        return None
    if all(len(part) == 3 for part in parts[1:]) and 1 <= len(parts[0]) <= 3:
        return Fraction(int("".join(parts)))
    if len(parts) >= 3 and len(parts[-1]) == 3 and all(len(part) == 2 for part in parts[1:-1]) \
            and 1 <= len(parts[0]) <= 2:
        return Fraction(int("".join(parts)))
    return None


def _plain_decimal(fraction: str) -> bool:
    """Without conventions, a decimal part is 1-2 digits without a trailing zero ("8,4", "2.75")."""
    return 1 <= len(fraction) <= 2 and not fraction.endswith("0")


def readings(text: str, conventions: Mapping[str, object] | None = None) -> tuple[Fraction, ...]:
    """Every well-formed value of one numeral under the given (or open) conventions."""
    latin = _same(_digits(text))
    parts = re.split(r"[   ,.'’]", latin)
    separators = re.findall(r"[   ,.'’]", latin)
    if not separators:
        return (Fraction(int(latin)),)
    grouping = ((conventions or {}).get("grouping") or {}).get("separator")
    decimal = ((conventions or {}).get("decimal") or {}).get("separator")
    grouping = _same(grouping) if isinstance(grouping, str) else grouping
    decimal = _same(decimal) if isinstance(decimal, str) else decimal
    found: list[Fraction] = []
    if decimal and separators[-1] == decimal:
        whole_parts, whole_separators = parts[:-1], separators[:-1]
        whole = _grouped(whole_parts, whole_separators) if whole_separators else Fraction(int(whole_parts[0]))
        if whole is not None and (not grouping or all(item == grouping for item in whole_separators)):
            found.append(whole + Fraction(int(parts[-1]), 10 ** len(parts[-1])))
    elif grouping or decimal:
        if not grouping or all(item == grouping for item in separators):
            value = _grouped(parts, separators)
            if value is not None:
                found.append(value)
    else:
        value = _grouped(parts, separators)
        if value is not None:
            found.append(value)
        if separators[-1] in ",." and _plain_decimal(parts[-1]) and not found:
            if len(separators) == 1:
                found.append(Fraction(int(parts[0])) + Fraction(int(parts[1]), 10 ** len(parts[1])))
            elif len(set(separators[:-1])) == 1 and separators[-1] != separators[0]:
                whole = _grouped(parts[:-1], separators[:-1])
                if whole is not None:
                    found.append(whole + Fraction(int(parts[-1]), 10 ** len(parts[-1])))
    return tuple(dict.fromkeys(found))


def find_numerals(text: str, conventions: Mapping[str, object] | None = None) -> tuple[Numeral, ...]:
    """Every digit numeral in a text, in reading order."""
    found = []
    for match in _NUMERAL.finditer(text):
        token = match.group(0).rstrip(_SEPARATORS)
        if not token:
            continue
        for start, part in _space_split(token, match.start()):
            end = start + len(part)
            suffixed = bool(re.match(r"-?[^\W\d_]|[º°ª]", text[end:end + 2]))
            found.append(Numeral(part, start, end, readings(part, conventions), suffixed))
    return tuple(found)


def _space_split(token: str, offset: int) -> list[tuple[int, str]]:
    """Split numerals that only a space joins ("in 30 40 years"); "12 000" stays one numeral.

    A space continues a numeral only before a group of exactly three digits; "1000 000" stays
    one (malformed) numeral rather than reading as 1000 and 0.
    """
    pieces, start = [], 0
    for match in re.finditer("[ \u00a0\u202f]", token):
        after = re.match(r"\d+", token[match.end():])
        if not after or len(after.group(0)) != 3:
            pieces.append((offset + start, token[start:match.start()]))
            start = match.end()
    pieces.append((offset + start, token[start:]))
    return pieces
