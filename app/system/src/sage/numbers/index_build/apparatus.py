"""Text-critical evidence for indexed numbers from online apparatus (cached, never vendored).

Sources (pinned or cached under the SAGE cache, cited per entry):
- NET Bible text-critical ("tc") notes, netbible.org (copyright Biblical Studies Press; quoted
  under fair use with attribution: a short excerpt of at most 240 characters and the URL per
  number-relevant note, never copied in bulk);
- SBLGNT apparatus (Faithlife/SBLGNT, CC BY 4.0): variant units against WH, Treg, NA28, RP, NIV;
- OSHB / morphhb (Open Scriptures Hebrew Bible, CC BY 4.0): ketiv/qere readings.

An entry is number-relevant when it names a number: a numeral or number word in the NET note,
a Greek numeral in an SBLGNT variant unit, a Hebrew numeral lemma in a qere reading. Verses whose
original-language and NIV numbers differ are then classified as ``VARIANT_ATTESTED`` (some
apparatus records a number variant: a text-critical decision for the operator) or ``NO_VARIANT``
(a rendering difference, not a text-critical decision).
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import ssl
import time
import unicodedata
import urllib.parse
import urllib.request

from sage.canon import NT_27

NET_NAMES = {
    "GEN": "Genesis", "EXO": "Exodus", "LEV": "Leviticus", "NUM": "Numbers", "DEU": "Deuteronomy",
    "JOS": "Joshua", "JDG": "Judges", "RUT": "Ruth", "1SA": "1 Samuel", "2SA": "2 Samuel", "1KI": "1 Kings",
    "2KI": "2 Kings", "1CH": "1 Chronicles", "2CH": "2 Chronicles", "EZR": "Ezra", "NEH": "Nehemiah",
    "EST": "Esther", "JOB": "Job", "PSA": "Psalms", "PRO": "Proverbs", "ECC": "Ecclesiastes",
    "SNG": "Song of Solomon", "ISA": "Isaiah", "JER": "Jeremiah", "LAM": "Lamentations", "EZK": "Ezekiel",
    "DAN": "Daniel", "HOS": "Hosea", "JOL": "Joel", "AMO": "Amos", "OBA": "Obadiah", "JON": "Jonah",
    "MIC": "Micah", "NAM": "Nahum", "HAB": "Habakkuk", "ZEP": "Zephaniah", "HAG": "Haggai", "ZEC": "Zechariah",
    "MAL": "Malachi", "MAT": "Matthew", "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts",
    "ROM": "Romans", "1CO": "1 Corinthians", "2CO": "2 Corinthians", "GAL": "Galatians", "EPH": "Ephesians",
    "PHP": "Philippians", "COL": "Colossians", "1TH": "1 Thessalonians", "2TH": "2 Thessalonians",
    "1TI": "1 Timothy", "2TI": "2 Timothy", "TIT": "Titus", "PHM": "Philemon", "HEB": "Hebrews",
    "JAS": "James", "1PE": "1 Peter", "2PE": "2 Peter", "1JN": "1 John", "2JN": "2 John", "3JN": "3 John",
    "JUD": "Jude", "REV": "Revelation",
}
SBLGNT_FILES = {
    "MAT": "Matt", "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts", "ROM": "Rom", "1CO": "1Cor",
    "2CO": "2Cor", "GAL": "Gal", "EPH": "Eph", "PHP": "Phil", "COL": "Col", "1TH": "1Thess", "2TH": "2Thess",
    "1TI": "1Tim", "2TI": "2Tim", "TIT": "Titus", "PHM": "Phlm", "HEB": "Heb", "JAS": "Jas", "1PE": "1Pet",
    "2PE": "2Pet", "1JN": "1John", "2JN": "2John", "3JN": "3John", "JUD": "Jude", "REV": "Rev",
}
OSHB_FILES = {
    "GEN": "Gen", "EXO": "Exod", "LEV": "Lev", "NUM": "Num", "DEU": "Deut", "JOS": "Josh", "JDG": "Judg",
    "RUT": "Ruth", "1SA": "1Sam", "2SA": "2Sam", "1KI": "1Kgs", "2KI": "2Kgs", "1CH": "1Chr", "2CH": "2Chr",
    "EZR": "Ezra", "NEH": "Neh", "EST": "Esth", "JOB": "Job", "PSA": "Ps", "PRO": "Prov", "ECC": "Eccl",
    "SNG": "Song", "ISA": "Isa", "JER": "Jer", "LAM": "Lam", "EZK": "Ezek", "DAN": "Dan", "HOS": "Hos",
    "JOL": "Joel", "AMO": "Amos", "OBA": "Obad", "JON": "Jonah", "MIC": "Mic", "NAM": "Nah", "HAB": "Hab",
    "ZEP": "Zeph", "HAG": "Hag", "ZEC": "Zech", "MAL": "Mal",
}
# Attribution printed wherever an entry of the source is quoted (reports, package manifest).
ATTRIBUTION = {
    "NET_TC": "NET Bible® notes copyright © 1996, 2019 by Biblical Studies Press, L.L.C., https://netbible.com. "
              "All rights reserved. Short excerpts of text-critical notes are quoted for commentary on number "
              "variants (fair use).",
    "SBLGNT_APPARATUS": "SBLGNT apparatus, Society of Biblical Literature and Logos Bible Software "
                        "(Faithlife/SBLGNT), CC BY 4.0.",
    "OSHB_KETIV_QERE": "Open Scriptures Hebrew Bible (openscriptures/morphhb), CC BY 4.0.",
    "LXX_BRENTON": "Brenton, The Septuagint Version of the Old Testament (1851), public domain (ebible.org).",
    "VULGATE_DRA": "Douay-Rheims Bible (Challoner revision), public domain (ebible.org).",
    "KJV": "King James Version (1769 text, eng-kjv2006), public domain (ebible.org).",
    "BSB": "Berean Standard Bible, public domain (berean.bible; ebible.org engbsb).",
    "BSB_NOTE": "Berean Standard Bible footnotes, public domain (berean.bible; ebible.org engbsb).",
}

NET_URL = "https://netbible.org/resource/getPassage/{passage}?jsoncallback=x"
_USER_AGENT = "Mozilla/5.0 (SAGE NCA text-critical research; Biblica)"
_ENGLISH_NUMBER = re.compile(
    r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|half|number|numbers|numeral)\b", re.I)
_GREEK_NUMERAL = re.compile(
    r"\b(δυο|δυσι|τρει|τρια|τριων|τρισι|τεσσαρ|τεσσερ|πεντ|εξ|επτα|οκτω|εννεα|δεκα|δωδεκα|εικοσι|τριακοντα|"
    r"τεσσερακοντα|τεσσαρακοντα|πεντηκοντα|εξηκοντα|εβδομηκοντα|ογδοηκοντα|ενενηκοντα|εκατον|διακοσι|τριακοσι|"
    r"τετρακοσι|πεντακοσι|εξακοσι|χιλι|μυρι|δευτερ|τριτ|τεταρτ|πεμπτ|εκτ|εβδομ|ογδο|ενατ|δεκατ|ημισ)\w*")


_QUOTED = re.compile(r"[“\"]([^”\"]{1,80})[”\"]")


_WITNESS_VERB = re.compile(r"\b(reads?|read|has|have|had|lacks?|omits?|adds?|does not have|do not have|instead of|"
                           r"rather than|attests?|supports?)\b[^“\"]{0,40}[“\"]([^”\"]{1,80})[”\"]", re.I)


_NUMBER_TOKEN = re.compile(
    r"\d[\d,]*|\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|half)\w*", re.I)
_OMISSION = re.compile(r"\b(lacks?|omits?|adds?|does not have|do not have|without)\b", re.I)


def net_names_a_number(note: str) -> bool:
    """A NET tc note records a number variant: a witness lacks, adds or omits a quoted number
    ("The MT does not have “thirty”"), different numbers are quoted as readings ("“three” instead
    of “seven”"), or a witness reads a number once ("The LXX reads “190 days”"). A number merely
    mentioned ("the number “two” suggests ..."), the same number in competing readings ("“two
    eyes” / “two sins”"), or a bare "one" does not count."""
    readings = [(verb, quote) for verb, quote in _WITNESS_VERB.findall(note)]
    quoted = _QUOTED.findall(note)
    tokens = [token.group(0).lower() for quote in quoted for token in _NUMBER_TOKEN.finditer(quote)]
    if any(_OMISSION.search(verb) and _NUMBER_TOKEN.search(quote) for verb, quote in readings):
        return True
    if len(set(tokens)) >= 2:
        return True
    if len(set(tokens)) == 1 and len(tokens) == 1:
        return any(_NUMBER_TOKEN.search(quote) for _verb, quote in readings)
    return False


_BASIS = (
    ("Septuagint (specific manuscripts or recension)",
     r"Lucianic|recension|(?:[Ss]ome|[Aa] few|[Oo]ne|[Ss]everal|[Aa]n ancient) (?:LXX|Greek) (?:mss|ms|witness(?:es)?)|Codex|"
     r"Vaticanus|Alexandrinus|LXX\s*(?:mss|ms)\b|LXX\^?[A-Z]\b"),
    ("Septuagint", r"\bLXX\b|Septuagint|Greek version|\bOG\b"),
    ("Syriac Peshitta", r"Syriac|Peshitta|\bsy\b"),
    ("Vulgate", r"Vulgate|\b[Vv]g\b"),
    ("Targum", r"\bTg\.?\b|Targum"),
    ("Samaritan Pentateuch", r"\bSmr\b|Samaritan"),
    ("Qumran (Dead Sea Scrolls)", r"\b[1-9]Q[A-Za-z0-9]*|Qumran|Dead Sea|\bDSS\b"),
    ("Qere/Kethib", r"\bQere\b|\bKethib\b|\bKetiv\b"),
    ("Hebrew manuscripts", r"Heb(?:rew)?\.? mss?\b|medieval Hebrew|Kennicott"),
    ("Greek NT manuscripts", r"\((?=[^)]*(?:\b[ABCDLWΘ]\b|\bP ?\d+\b|ƒ|א|𝔐))[^)]*\)|early ms|Most mss"),
    ("Early versions (Coptic, Old Latin)",
     r"Coptic|Old Latin|Sahidic|Bohairic|early version|\([^)]*\b(?:sa|bo|it|lat|co)\b[^)]*\)"),
    ("Parallel passage", r"\bparallel\b|reflects the description in"),
    ("Scribal-error explanation", r"dittography|haplography|homoioarcton|homoioteleuton|scribal error|accidentally omitted"),
    ("Conjecture or emendation", r"emend|conjectur|proposal|suggest(?:s|ed)? emending|no textual or versional evidence"),
)


_NT_ONLY = {"Greek NT manuscripts", "Early versions (Coptic, Old Latin)"}
_OT_ONLY = {"Septuagint (specific manuscripts or recension)", "Septuagint", "Targum", "Samaritan Pentateuch",
            "Qere/Kethib", "Hebrew manuscripts"}


def net_basis(note: str, book: str = "") -> list[str]:
    """The kinds of witness a NET tc note rests on, in a fixed vocabulary (cited, not quoted).

    "Lucianic Greek recension ... Syriac Peshitta ... Vulgate" yields specific Septuagint
    manuscripts, Syriac and Vulgate; a note naming no witness and proposing a reading is a
    conjecture or emendation.
    """
    found = []
    testament = "NT" if book in NT_27 else "OT" if book else ""
    for label, pattern in _BASIS:
        if (testament == "OT" and label in _NT_ONLY) or (testament == "NT" and label in _OT_ONLY):
            continue  # NT sigla in an OT note are English words ("A", "it"), and vice versa
        if re.search(pattern, note) and label not in found:
            if label == "Septuagint" and "Septuagint (specific manuscripts or recension)" in found:
                continue
            found.append(label)
    if not found:
        found.append("Conjecture or emendation")
    return found


def _nt_variant_sigla(note: str) -> str:
    """The witness sigla of the first reading an NT note cites ("A W Θ ƒ1,13 𝔐 sy"), or ''.

    Every sigla list in the first sentence that has one names the variant's witnesses ("One
    early ms (B) and an early version (sa)"); later sentences usually name the witnesses that
    resisted it, so they are not cited.
    """
    for sentence in re.split(r"(?<=[.”])\s+(?=[A-Z])", note):
        found = []
        for group in re.findall(r"\(([^)]*)\)", sentence):
            tokens = [token for token in re.sub(r"\[\s*\*\s*\]", "", group).split() if token]
            if tokens and all(re.fullmatch(r"[A-ZΘΔΨא𝔐]|ƒ|\d[\d,]*|P\d+|sy|sa|bo|co|it|lat|vg|pc", t)
                              for t in tokens):
                found.append(re.sub(r"ƒ (\d)", r"ƒ\1", " ".join("𝔐" if t == "M" else t for t in tokens)))
        if found:
            return " ".join(found)
    return ""


def net_basis_label(note: str, book: str) -> str:
    """The recorded basis of a NET tc note: witness kinds, plus the variant's sigla in the NT."""
    if book in NT_27:
        sigla = _nt_variant_sigla(note)
        if sigla:
            # classify only the variant's own witnesses, not those cited for the printed text
            labels = net_basis(f"({sigla})", book)
            return "; ".join(labels) + f" ({sigla})"
    return "; ".join(net_basis(note, book))


_GREEK_VALUES = (
    ("δεκαδυο", 12), ("δωδεκ", 12), ("δεκατεσσαρ", 14), ("δεκαπεντ", 15), ("δεκαοκτω", 18),
    ("δυο", 2), ("δυσι", 2), ("τρει", 3), ("τρια", 3), ("τρισ", 3), ("τεσσαρακοντ", 40), ("τεσσερακοντ", 40),
    ("τεσσαρ", 4), ("τεσσερ", 4), ("πεντηκοντ", 50), ("πεντακοσι", 500), ("πεντακισχιλι", 5000), ("πεντε", 5),
    ("εξηκοντ", 60), ("εξακοσι", 600), ("επτα", 7), ("εβδομηκοντ", 70), ("οκτω", 8), ("ογδοηκοντ", 80),
    ("εννεα", 9), ("ενενηκοντ", 90), ("δεκα", 10), ("εικοσι", 20), ("τριακοντ", 30), ("τριακοσι", 300),
    ("εκατον", 100), ("διακοσι", 200), ("τετρακοσι", 400), ("χιλι", 1000), ("μυρι", 10000),
    ("πρωτ", 1001), ("δευτερ", 1002), ("τριτ", 1003), ("τεταρτ", 1004), ("πεμπτ", 1005), ("εκτ", 1006),
    ("εβδομ", 1007), ("ογδο", 1008), ("ενατ", 1009), ("δεκατ", 1010), ("ημισ", 1500),
)  # ἕξ "six" is left out: without breathings it is the preposition ἐξ
_SIGLA = re.compile(r"\b(WH|Treg|NA28|RP|NIV)\b")


def _greek_numbers(reading: str) -> list[int]:
    """Number words in one Greek reading, as comparable keys (ordinals offset by 1000)."""
    found = []
    for word in re.findall(r"[^\W\d_]+", _plain_greek(reading)):
        for stem, value in _GREEK_VALUES:
            if word.startswith(stem):
                found.append(value)
                break
    return sorted(found)


def sblgnt_changes_a_number(unit: str) -> bool:
    """Whether the readings of one SBLGNT unit differ in their numbers (not only order or spelling)."""
    lemma, _, alternatives = unit.partition("]")
    lemma = _SIGLA.sub("", lemma)
    base = _greek_numbers(lemma)
    for alternative in alternatives.split(";"):
        reading = _SIGLA.sub("", alternative).strip()
        if reading.startswith("–"):
            other = []
        elif reading.startswith("+"):
            other = sorted(base + _greek_numbers(reading[1:]))
        else:
            other = _greek_numbers(reading)
        if other != base:
            return True
    return False


_HEBREW_MARKS = re.compile(r"[\u0591-\u05C7/]")


def _consonants(text: str) -> str:
    """Hebrew consonant stem without vowel letters, marks, doubled letters or a gender/plural ending,
    so spelling and gender forms of one numeral compare equal (אחד/אחת, רבון/רבבן)."""
    plain = re.sub(r"[יוהא\s]", "", _HEBREW_MARKS.sub("", text))
    plain = re.sub(r"(.)\1+", r"\1", plain)
    return re.sub(r"[םןתד]+$", "", plain)


def _plain_greek(text: str) -> str:
    """Lowercase Greek without accents or breathings."""
    return "".join(char for char in unicodedata.normalize("NFD", text.lower())
                   if not unicodedata.combining(char))


@dataclass(frozen=True)
class Evidence:
    """One number-relevant apparatus entry at one verse."""

    reference: str
    source: str
    summary: str
    url: str
    basis: str = ""


def _tls() -> ssl.SSLContext:
    """Verified TLS using certifi's CA bundle when the interpreter has no usable system store."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SIGLA = {"WH": "Westcott–Hort", "Treg": "Tregelles", "NA28": "Nestle–Aland 28", "RP": "Robinson–Pierpont",
         "NIV": "Greek text behind the NIV (Holmes)"}


def sblgnt_readings(unit: str) -> list[dict[str, object]]:
    """The readings of one SBLGNT unit with their witnesses; the first is the SBLGNT text."""
    lemma, _, alternatives = unit.partition("]")
    readings = []
    for index, part in enumerate([lemma, *alternatives.split(";")]):
        witnesses = _SIGLA.findall(part)
        text = re.sub(r"[⸀⸁⸂⸃]", "", _SIGLA.sub("", part)).replace("\u00a0", " ").strip()
        if index and text.startswith("+"):
            text = "adds " + text[1:].strip()
        elif index and text.startswith("–"):
            text = "omits"
        readings.append({"text": text, "witnesses": witnesses, "sblgnt": index == 0})
    return readings


def evidence_entry(source: str, summary: str, url: str, basis: str = "", see_also: str = "") -> dict[str, object]:
    """One structured evidence entry for the typed package (rendered in operator reports)."""
    entry: dict[str, object] = {"source": source, "summary": summary, "url": url}
    if basis:
        entry["basis"] = [item.strip() for item in basis.split(";") if item.strip()]
    if see_also:
        entry["see_also"] = [item.strip() for item in see_also.split(";") if item.strip()]
    if source == "SBLGNT_APPARATUS":
        entry["readings"] = sblgnt_readings(summary)
    elif source == "OSHB_KETIV_QERE":
        ketiv, _, qere = summary.partition(" / ")
        entry["readings"] = [{"text": ketiv.replace("ketiv ", "").strip(), "witnesses": ["Ketiv (written)"]},
                             {"text": qere.replace("qere ", "").strip(), "witnesses": ["Qere (read)"]}]
    return entry


def fetch_net(cache: Path, chapters, *, pause: float = 1.0, log=print) -> int:
    """Download every NET chapter not yet cached (book code, chapter); returns how many were fetched."""
    context = _tls()
    root = cache / "net"
    root.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for book, chapter in chapters:
        path = root / f"{book}-{int(chapter):03d}.json"
        if path.is_file() and path.stat().st_size > 0:
            continue
        passage = urllib.parse.quote(f"{NET_NAMES[book]} {int(chapter)}")
        request = urllib.request.Request(NET_URL.format(passage=passage), headers={"User-Agent": _USER_AGENT})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60, context=context) as response:
                    raw = response.read().decode("utf-8")
                break
            except OSError as exc:  # transient network failure: back off, then give up on this chapter
                log(f"NET {book} {chapter}: {exc}")
                time.sleep(5 * (attempt + 1))
        else:
            continue
        payload = raw[raw.index("(") + 1:raw.rindex(")")]
        json.loads(payload)
        path.write_text(payload, encoding="utf-8")
        fetched += 1
        time.sleep(pause)
    return fetched


LOGOS_BOOKS = {
    "Ge": "GEN", "Ex": "EXO", "Le": "LEV", "Nu": "NUM", "De": "DEU", "Jos": "JOS", "Jdg": "JDG", "Ru": "RUT",
    "1Sa": "1SA", "2Sa": "2SA", "1Ki": "1KI", "2Ki": "2KI", "1Ch": "1CH", "2Ch": "2CH", "Ezr": "EZR", "Ne": "NEH",
    "Es": "EST", "Est": "EST", "Job": "JOB", "Ps": "PSA", "Pr": "PRO", "Ec": "ECC", "Ecc": "ECC", "So": "SNG",
    "Song": "SNG", "Is": "ISA", "Je": "JER", "La": "LAM", "Eze": "EZK", "Da": "DAN", "Ho": "HOS", "Joe": "JOL",
    "Am": "AMO", "Ob": "OBA", "Jon": "JON", "Mic": "MIC", "Na": "NAM", "Hab": "HAB", "Zep": "ZEP", "Hag": "HAG",
    "Zec": "ZEC", "Mal": "MAL", "Mt": "MAT", "Mat": "MAT", "Mk": "MRK", "Lu": "LUK", "Jn": "JHN", "Ac": "ACT",
    "Ro": "ROM", "1Co": "1CO", "2Co": "2CO", "Ga": "GAL", "Gal": "GAL", "Eph": "EPH", "Php": "PHP", "Col": "COL",
    "1Th": "1TH", "2Th": "2TH", "1Ti": "1TI", "2Ti": "2TI", "Tit": "TIT", "Phm": "PHM", "Heb": "HEB",
    "Jam": "JAS", "1Pe": "1PE", "2Pe": "2PE", "1Jn": "1JN", "2Jn": "2JN", "3Jn": "3JN", "Jud": "JUD",
    "Jude": "JUD", "Re": "REV",
}


def net_tc_parallels(cache: Path, book: str, chapter: int) -> dict[int, list[str]]:
    """Verses a number-relevant NET tc note cites (its tagged references), keyed by the note's verse.

    "The parallel text of 2 Sam 10:18 has “seven hundred”" yields 2SA 10:18 for 1CH 19:18.
    References inside the same verse, or to books outside the 66, are skipped.
    """
    path = cache / "net" / f"{book}-{int(chapter):03d}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    verse_of = {int(match["note"]): int(match["verse"]) for match in re.finditer(
        r'data-verse="(?P<verse>\d+)"[^>]*id="noteSuper_(?P<note>\d+)_', data.get("content", ""))}
    found: dict[int, list[str]] = {}
    for match in re.finditer(r'id="note_(\d+)">.*?</sup><span class="notetype">(\w+)</span>(.*?)(?=<div class="note">|$)',
                             data.get("notes", ""), re.S):
        number, kind, body = int(match[1]), match[2], match[3]
        if kind != "tc" or number not in verse_of:
            continue
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        if not net_names_a_number(text):
            continue
        verse = verse_of[number]
        for ref in re.findall(r'<data ref="Bible:([1-3]?[A-Za-z]+) (\d+):(\d+)', body):
            code = LOGOS_BOOKS.get(ref[0])
            label = f"{code} {int(ref[1])}:{int(ref[2])}" if code else None
            if label and label != f"{book} {int(chapter)}:{verse}" and label not in found.get(verse, []):
                found.setdefault(verse, []).append(label)
    return found


def net_tc_notes(cache: Path, book: str, chapter: int) -> dict[int, list[str]]:
    """Text-critical NET notes of one cached chapter, keyed by verse."""
    path = cache / "net" / f"{book}-{int(chapter):03d}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    # pos restarts in every verse; the chapter-wide note number is in id="noteSuper_<n>_...".
    verse_of = {int(match["note"]): int(match["verse"]) for match in re.finditer(
        r'data-verse="(?P<verse>\d+)"[^>]*id="noteSuper_(?P<note>\d+)_', data.get("content", ""))}
    found: dict[int, list[str]] = {}
    for match in re.finditer(r'id="note_(\d+)">.*?</sup><span class="notetype">(\w+)</span>(.*?)(?=<div class="note">|$)',
                             data.get("notes", ""), re.S):
        number, kind, body = int(match[1]), match[2], match[3]
        if kind != "tc" or number not in verse_of:
            continue
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        found.setdefault(verse_of[number], []).append(text)
    return found


def sblgnt_units(cache: Path) -> dict[str, list[str]]:
    """Every SBLGNT apparatus unit, keyed 'BOOK C:V'."""
    found: dict[str, list[str]] = {}
    for book, name in SBLGNT_FILES.items():
        path = cache / "sblgntapp" / f"{name}.txt"
        if not path.is_file():
            continue
        reference = None
        for line in path.read_text(encoding="utf-8").splitlines():
            header = re.match(rf"^{re.escape(name)} (\d+):(\d+)$", line.strip())
            if header:
                reference = f"{book} {int(header[1])}:{int(header[2])}"
                continue
            if reference and "]" in line:
                unit = re.sub(r"^(?:\d+:)?\d+\s+|^•\s*", "", line.strip())
                found.setdefault(reference, []).append(unit)
    return found


def oshb_numeral_qere(cache: Path, numeral_strongs: set[str]) -> dict[str, list[str]]:
    """Ketiv/qere notes whose qere is a numeral (by Strong's number), keyed 'BOOK C:V'."""
    found: dict[str, list[str]] = {}
    reverse = {name: book for book, name in OSHB_FILES.items()}
    for path in sorted((cache / "morphhb").glob("*.xml")):
        text = path.read_text(encoding="utf-8")
        for verse in re.finditer(r'<verse osisID="([^"]+)">(.*?)</verse>', text, re.S):
            name, chapter, number = verse[1].split(".")
            for note in re.finditer(r'<note type="variant"><catchWord>(.*?)</catchWord><rdg type="x-qere">(.*?)</rdg>',
                                    verse[2], re.S):
                lemmas = set(re.findall(r'lemma="(?:[a-z]/)*(\d+)', note[2]))
                qere = re.sub(r"<[^>]+>", "", note[2]).strip()
                if lemmas & numeral_strongs and _consonants(note[1]) != _consonants(qere):
                    found.setdefault(f"{reverse.get(name, name)} {chapter}:{number}", []).append(
                        f"ketiv {note[1]} / qere {qere}")
    return found


def collect(cache: Path, references, numeral_strongs: set[str], linker=None) -> dict[str, list[Evidence]]:
    """Number-relevant apparatus evidence for every given Western reference.

    SBLGNT and OSHB entries are numbered like the Hebrew/Greek editions (org); with a ``linker``
    (index_build/versify.py) they are linked to Western coordinates through eng.vrs. NET notes
    are English-numbered and keep their label where eng.vrs has the verse.
    """
    units = sblgnt_units(cache)
    qere = oshb_numeral_qere(cache, numeral_strongs)
    if linker is not None:
        relinked: dict[str, list[str]] = {}
        for label, items in units.items():
            relinked.setdefault(linker.ol_to_western(label), []).extend(items)
        units = relinked
        relinked = {}
        for label, items in qere.items():
            relinked.setdefault(linker.ol_to_western(label), []).extend(items)
        qere = relinked
    chapters: dict[tuple[str, int], dict[int, list[str]]] = {}
    found: dict[str, list[Evidence]] = {}
    for reference in references:
        book, _, cv = reference.partition(" ")
        chapter, _, verse = cv.partition(":")
        key = (book, int(chapter))
        if key not in chapters:
            chapters[key] = net_tc_notes(cache, book, int(chapter))
        url = f"https://netbible.org/bible/{urllib.parse.quote(NET_NAMES.get(book, book))}+{int(chapter)}"
        for note in chapters[key].get(int(verse), ()):
            if net_names_a_number(note):
                summary = note if len(note) <= 240 else note[:237].rsplit(" ", 1)[0] + " ..."
                found.setdefault(reference, []).append(
                    Evidence(reference, "NET_TC", summary, url, net_basis_label(note, reference.split()[0])))
        for unit in units.get(reference, ()):
            if _GREEK_NUMERAL.search(_plain_greek(unit)) and sblgnt_changes_a_number(unit):
                found.setdefault(reference, []).append(Evidence(
                    reference, "SBLGNT_APPARATUS", unit, "https://github.com/Faithlife/SBLGNT"))
        for item in qere.get(reference, ()):
            found.setdefault(reference, []).append(Evidence(
                reference, "OSHB_KETIV_QERE", item, "https://github.com/openscriptures/morphhb"))
    return found
