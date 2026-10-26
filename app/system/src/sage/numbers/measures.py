"""Which measure system a counted unit belongs to: ancient or modern, by word lists per language.

Deterministic and local, with no model call of its own. The extraction call a Run already makes returns,
for each number, what it counts in the translation's own language ("кубітів", "codos", "kilómetros");
this module only looks those words up in the list for the WIP language. A counted-item text with no
listed measure word, or with words from both lists, has no system. Nothing is converted and no value
is compared: NCA reports whether the translation keeps to one measure system, nothing more.

A language with no list here is reported as not checked, never guessed. To add one, add an entry to
``LEXICONS`` keyed by the primary language subtag. ``prefixes`` match the start of a word (they cover
inflected forms: Ukrainian "лікт" matches "ліктів"); ``words`` match a whole word (short or ambiguous
forms). Ambiguous words (pound, coin, mile in a Roman sense) are left out so a mixed report is never
caused by a guess.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"\w+", re.UNICODE)

LEXICONS: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {
    "en": {
        "ancient": {
            "prefixes": ("cubit", "handbreadth", "fathom", "stadi", "ephah", "omer", "shekel", "talent", "denari",
                         "drachma", "gerah", "bekah", "metretes", "lethek", "homer"),
            "words": ("span", "reed", "log", "kab", "seah", "seahs", "bath", "baths", "hin", "cor", "cors", "mina",
                      "minas", "pim", "stadion", "furlong", "furlongs"),
        },
        "modern": {
            "prefixes": ("metre", "meter", "kilometre", "kilometer", "centimetre", "centimeter", "millimetre",
                         "millimeter", "inch", "litre", "liter", "gallon", "quart", "kilogram", "gram", "ounce",
                         "tonne", "hectare", "acre", "dollar", "euro"),
            "words": ("foot", "feet", "yard", "yards", "pint", "pints", "kilo", "kilos", "ton", "tons", "cent", "cents",
                      "mile", "miles"),
        },
    },
    "es": {
        "ancient": {
            "prefixes": ("codo", "palmo", "braza", "estadio", "efa", "gomor", "siclo", "talento", "denario",
                         "dracma", "gera", "guera", "cuadrante", "leptón", "metreta"),
            "words": ("caña", "cañas", "cab", "log", "sea", "seas", "seá", "seahs", "bato", "batos", "hin", "coro", "coros", "seah",
                      "mina", "minas", "pim"),
        },
        "modern": {
            "prefixes": ("metro", "kilómetro", "kilometro", "centímetro", "centimetro", "milímetro", "milimetro",
                         "pulgada", "yarda", "litro", "galón", "galon", "kilogramo", "gramo", "onza", "tonelada",
                         "hectárea", "hectarea", "acre", "dólar", "dolar", "euro", "centavo", "peso"),
            "words": ("pie", "pies", "kilo", "kilos", "milla", "millas"),
        },
    },
    "uk": {
        "ancient": {
            "prefixes": ("лікт", "лікоть", "долон", "сяжн", "тростин", "стаді", "ефи", "ефа", "ефі", "гомор",
                         "гомер", "ґер", "шекел", "сікл", "талант", "динар", "драхм", "кодрант", "лепт", "метрет"),
            "words": ("п'ядь", "п’ядь", "п'яді", "п’яді", "кав", "сат", "сата", "сати", "бат", "бата", "бати", "батів", "батами", "гін", "гіна",
                      "кор", "кора", "кори", "міна", "міни", "мін", "гера", "пім"),
        },
        "modern": {
            "prefixes": ("метр", "кілометр", "сантиметр", "міліметр", "дюйм", "ярд", "літр", "галон", "кілограм",
                         "грам", "унці", "тонн", "гектар", "акр", "долар", "євро", "гривн"),
            "words": ("фут", "футів", "фути", "кіло", "цент", "центів", "миля", "милі", "миль", "милю", "милею"),
        },
    },
}


def language_key(language: str) -> str:
    """The primary subtag of a language code: ``es-419`` -> ``es``."""
    return str(language or "").strip().lower().replace("_", "-").split("-")[0]


def has_lexicon(language: str) -> bool:
    """Whether measure words are listed for this language."""
    return language_key(language) in LEXICONS


def _hit(words: list[str], entry: dict[str, tuple[str, ...]]) -> bool:
    """Whether any word is listed, whole or as the start of an inflected form."""
    return any(word in entry["words"] or any(word.startswith(prefix) for prefix in entry["prefixes"])
               for word in words)


def measure_system(counted: str, language: str) -> str:
    """``ANCIENT``, ``MODERN`` or ``""`` for the text of what a number counts, in the WIP language."""
    lexicon = LEXICONS.get(language_key(language))
    if lexicon is None:
        return ""
    words = [word.lower().replace("’", "'") for word in _WORD.findall(str(counted).replace("’", "'"))]
    ancient, modern = _hit(words, lexicon["ancient"]), _hit(words, lexicon["modern"])
    return "ANCIENT" if ancient and not modern else "MODERN" if modern and not ancient else ""
