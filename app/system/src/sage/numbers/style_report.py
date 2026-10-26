"""Number formatting consistency: how the WIP writes its numbers, against a guide or itself.

Local and deterministic. Every number NCA read is classified by how it is written:
- form: ``DIGITS`` ("42 360"), ``WORDS`` ("сорок дві тисячі"), ``MIXED`` ("5 тисяч");
- digit script (Latin, Arabic-Indic, Devanagari ...), grouping separator (numerals of 1 000
  and more), decimal mark;
- measure system (ancient or modern) of the unit a number counts, from the extraction's English
  gloss and closed word lists (``measures.py``); the translation should keep to one;
- location: ``BODY`` (verse text, from extraction) or ``NOTE`` (footnote numerals, read here).

With a configured Number Style Profile every occurrence is checked against its rules and each
variance is reported. Without one, SAGE reconstructs the guide from the WIP itself (the dominant
use per area and location) and reports the minority uses as inconsistencies; the reconstructed
guide is offered as a profile the operator can import. Findings are grouped patterns with counts
and example verses, never one finding per verse.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from fractions import Fraction
import unicodedata
from typing import Iterable, Mapping

from .measures import has_lexicon, measure_system
from .numerals import find_numerals

_BANDS = ((0, 9), (10, 99), (100, 999), (1000, None))
_DOMINANT_SHARE = 0.6
_MIN_EVIDENCE = 3
_EXAMPLES = 8


def _form(surface: str) -> str:
    """DIGITS, WORDS or MIXED for one written number."""
    digits = any(char.isdecimal() for char in surface)
    letters = any(char.isalpha() for char in surface)
    return "MIXED" if digits and letters else "DIGITS" if digits else "WORDS"


def _script(surface: str) -> str:
    """Name of the digit script ("LATIN", "ARABIC-INDIC", ...), or "" without digits."""
    digit = next((char for char in surface if char.isdecimal()), "")
    if not digit:
        return ""
    name = unicodedata.name(digit, "")
    return "LATIN" if name.startswith("DIGIT ") else name.rsplit(" DIGIT ", 1)[0]


def _separators(surface: str, value: Fraction) -> tuple[str, str]:
    """(grouping separator or "NONE" for whole numbers >= 1000, decimal mark) of a digit numeral."""
    numeral = next(iter(find_numerals(surface)), None)
    if numeral is None:
        return "", ""
    if value not in numeral.readings:
        return "", ""  # "12 тисяч" (12 000): the numeral is only part of the number
    marks = [char for char in numeral.text if not char.isdecimal()]
    if value.denominator != 1:
        return ("" if len(marks) < 2 else marks[0]), (marks[-1] if marks else "")
    if value >= 1000:
        return (marks[0] if marks else "NONE"), ""
    return "", ""


def _alphabet(script: str) -> str:
    """The ten digits of a digit script named as by ``_script`` ("LATIN", "ARABIC-INDIC" ...)."""
    if script == "LATIN":
        return "0123456789"
    try:
        zero = ord(unicodedata.lookup(f"{script} DIGIT ZERO"))
    except KeyError:
        return "0123456789"
    return "".join(chr(zero + offset) for offset in range(10))


def _name(char: str) -> str:
    """Readable separator name."""
    return {"NONE": "none", " ": "space", " ": "no-break space", " ": "narrow no-break space",
            ",": "comma", ".": "period", "'": "apostrophe", "’": "apostrophe"}.get(char, repr(char))


def occurrences(groups: Iterable[object], language: str = "") -> list[dict[str, object]]:
    """Every written number of a Run: body numbers from extraction, footnote numerals read locally."""
    found = []
    for group in groups:
        unit = group.projected
        refs = [ref.label() for ref in unit.target.target_references] or [ref.label() for ref in unit.western_references]
        ref = refs[0] if refs else ""
        extraction = group.extraction
        for index, value in enumerate(extraction.values):
            surface = extraction.surfaces[index] if index < len(extraction.surfaces) else ""
            if not surface:
                continue
            counts = extraction.counts[index] if index < len(extraction.counts) else ""
            found.append({**_occurrence(ref, "BODY", surface, value), "measure": measure_system(counts, language)})
        for note in unit.target.notes:
            for numeral in find_numerals(note.text):
                if numeral.readings:
                    found.append(_occurrence(ref, "NOTE", numeral.text, numeral.readings[0]))
    return found


def _occurrence(ref: str, location: str, surface: str, value: Fraction) -> dict[str, object]:
    """One classified written number."""
    form = _form(surface)
    grouping, decimal = _separators(surface, value) if form != "WORDS" else ("", "")
    return {"reference": ref, "location": location, "surface": surface, "value": str(value), "form": form,
            "script": _script(surface), "grouping": grouping, "decimal": decimal, "measure": ""}


def _band(value: Fraction) -> tuple[int, int | None] | None:
    """Magnitude band of a whole number."""
    if value.denominator != 1 or value < 0:
        return None
    for low, high in _BANDS:
        if value >= low and (high is None or value <= high):
            return low, high
    return None


def _band_label(band: tuple[int, int | None]) -> str:
    """Readable band label."""
    low, high = band
    return f"{low}–{high}" if high is not None else f"{low}+"


def _pattern(area: str, location: str, expected: str, found: str, items: list[dict[str, object]]) -> dict[str, object]:
    """One grouped inconsistency with its count and examples."""
    refs = list(dict.fromkeys(str(item["reference"]) for item in items))
    return {"area": area, "location": location, "expected": expected, "found": found, "count": len(items),
            "examples": [f"{item['reference']} «{item['surface']}»" for item in items[:_EXAMPLES]],
            "references": refs}


def _dominant(counter: Counter) -> tuple[str, float] | None:
    """The dominant choice and its share, when there is enough evidence for one."""
    total = sum(counter.values())
    if total < _MIN_EVIDENCE:
        return None
    choice, count = counter.most_common(1)[0]
    share = count / total
    return (choice, share) if share >= _DOMINANT_SHARE else None


def _measure_consistency(found: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """One measure system per translation: the dominant system and the uses of the other, or both when even."""
    items = [item for item in found if item["location"] == "BODY" and item.get("measure")]
    by_system = {system: [item for item in items if item["measure"] == system] for system in ("ANCIENT", "MODERN")}
    names = {"ANCIENT": "ancient measures", "MODERN": "modern measures"}
    dominant = _dominant(Counter(item["measure"] for item in items))
    if dominant is not None:
        choice, share = dominant
        other = "MODERN" if choice == "ANCIENT" else "ANCIENT"
        rules = [{"area": "measures", "location": "BODY", "rule": names[choice], "share_percent": round(100 * share),
                  "count": len(items), "value": choice}]
        patterns = [_pattern("measures", "BODY", names[choice], names[other], by_system[other])] if by_system[other] else []
        return rules, patterns
    if by_system["ANCIENT"] and by_system["MODERN"]:
        return [], [_pattern("measures", "BODY", "one measure system (none dominant)", names[system], by_system[system])
                    for system in ("ANCIENT", "MODERN")]
    return [], []


def reconstruct(found: list[dict[str, object]]) -> dict[str, object]:
    """Infer the dominant number style of the WIP and list the minority uses."""
    rules, patterns = [], []
    for location in ("BODY", "NOTE"):
        here = [item for item in found if item["location"] == location]
        by_band = defaultdict(list)
        for item in here:
            band = _band(Fraction(str(item["value"])))
            if band is not None:
                by_band[band].append(item)
        for band, items in sorted(by_band.items()):
            dominant = _dominant(Counter(item["form"] for item in items))
            if dominant is None:
                continue
            form, share = dominant
            rules.append({"area": "bands", "location": location, "band": _band_label(band), "rule": form,
                          "share_percent": round(100 * share), "count": len(items)})
            minority = [item for item in items if item["form"] != form]
            for other in sorted({item["form"] for item in minority}):
                patterns.append(_pattern("form", location, f"{form.lower()} for {_band_label(band)}",
                                         other.lower(), [item for item in minority if item["form"] == other]))
        for area, key in (("grouping", "grouping"), ("decimal", "decimal"), ("digits", "script")):
            items = [item for item in here if item[key]]
            dominant = _dominant(Counter(item[key] for item in items))
            if dominant is None:
                continue
            choice, share = dominant
            label = choice if area == "digits" else _name(choice)
            rules.append({"area": area, "location": location, "rule": label, "share_percent": round(100 * share),
                          "count": len(items), "value": choice})
            for other in sorted({item[key] for item in items} - {choice}):
                patterns.append(_pattern(area, location, label, other if area == "digits" else _name(other),
                                         [item for item in items if item[key] == other]))
    measure_rules, measure_patterns = _measure_consistency(found)
    return {"basis": "RECONSTRUCTED", "rules": rules + measure_rules, "patterns": patterns + measure_patterns}


def variance(found: list[dict[str, object]], profile: Mapping[str, object]) -> dict[str, object]:
    """Check every written number against a configured Number Style Profile."""
    rules = profile.get("rules", {})
    patterns: dict[tuple[str, str, str, str], list] = defaultdict(list)
    bands = rules.get("bands", {})
    grouping = rules.get("grouping", {})
    decimal = rules.get("decimal", {})
    digits = rules.get("digits", {})
    for item in found:
        if item["location"] != "BODY":
            continue
        value = Fraction(str(item["value"]))
        if bands.get("status") == "CONFIGURED" and value.denominator == 1:
            for band in bands.get("bands", ()):
                low, high = Fraction(band["min"]), (None if band.get("max") is None else Fraction(band["max"]))
                if value >= low and (high is None or value <= high):
                    expected = str(band["form"])
                    if expected != "WORDS_AND_DIGITS" and item["form"] != expected and not (
                            expected == "WORDS" and item["form"] == "MIXED"):
                        label = f"{expected.lower()} for {band['min']}–{band.get('max') or '+'}"
                        patterns[("form", "BODY", label, item["form"].lower())].append(item)
                    break
        if grouping.get("status") == "CONFIGURED" and item["grouping"] and value >= Fraction(grouping["minimum"]):
            expected = "NONE" if grouping["style"] == "NONE" else grouping["separator"]
            if item["grouping"] != expected:
                patterns[("grouping", "BODY", _name(expected), _name(item["grouping"]))].append(item)
        if decimal.get("status") == "CONFIGURED" and item["decimal"] and item["decimal"] != decimal["separator"]:
            patterns[("decimal", "BODY", _name(decimal["separator"]), _name(item["decimal"]))].append(item)
        if digits.get("status") == "CONFIGURED" and item["script"]:
            allowed = {_script(alphabet) for alphabet in digits.get("allowed", ())}
            if item["script"] not in allowed:
                patterns[("digits", "BODY", ", ".join(sorted(allowed)), item["script"])].append(item)
    measure_patterns = _measure_consistency(found)[1]
    return {"basis": "PROFILE", "profile": str((profile.get("profile") or {}).get("id") or ""),
            "rules": [], "patterns": [_pattern(area, location, expected, other, items)
                                      for (area, location, expected, other), items in sorted(patterns.items())]
            + measure_patterns}


def analyze(groups: Iterable[object], style_profile: Mapping[str, object], language: str = "") -> dict[str, object]:
    """The Run's number-style report: variance against the profile, or a reconstructed guide."""
    found = occurrences(groups, language)
    configured = (style_profile.get("profile") or {}).get("status") == "CONFIGURED"
    result = variance(found, style_profile) if configured else reconstruct(found)
    result["numbers"] = len(found)
    if not has_lexicon(language):
        result["not_checked"] = [f"Measure-system consistency: no measure word list for language {language or 'unknown'}"]
    return result


def reconstructed_profile(style: Mapping[str, object], *, project: str, language: str, script: str,
                          recorded_date: str, run_id: str) -> dict[str, object] | None:
    """A Number Style Profile document from a reconstructed style (importable once approved)."""
    if style.get("basis") != "RECONSTRUCTED":
        return None
    body = [rule for rule in style.get("rules", ()) if rule["location"] == "BODY"]

    def area(name: str, **configured) -> dict[str, object]:
        """One rule area: configured when evidence exists, NOT_SPECIFIED otherwise."""
        rule_id = f"RECON_{name.upper()}"
        return {"id": rule_id, "status": "CONFIGURED", **configured} if configured else {
            "id": rule_id, "status": "NOT_SPECIFIED"}

    band_rules = [rule for rule in body if rule["area"] == "bands"]
    bands = []
    for low, high in _BANDS:
        label = _band_label((low, high))
        rule = next((item for item in band_rules if item["band"] == label), None)
        if rule is not None and rule["rule"] in {"WORDS", "DIGITS"}:
            bands.append({"min": str(low), "max": None if high is None else str(high), "form": rule["rule"]})
    grouping = next((rule for rule in body if rule["area"] == "grouping"), None)
    decimal = next((rule for rule in body if rule["area"] == "decimal"), None)
    if grouping and decimal and grouping["value"] == decimal["value"]:
        grouping = decimal = None  # one mark for both cannot be a rule; leave both unspecified
    digits = next((rule for rule in body if rule["area"] == "digits"), None)
    alphabet = _alphabet(digits["value"]) if digits else "0123456789"
    rules = {
        "digits": area("digits", preferred=alphabet, allowed=[alphabet]),
        "bands": area("bands", bands=bands) if bands else area("bands"),
        "grouping": (area("grouping", style="NONE", separator="", minimum="1000")
                     if grouping and grouping["value"] == "NONE" else
                     area("grouping", style="WESTERN", separator=grouping["value"], minimum="1000")
                     if grouping else area("grouping")),
        "decimal": area("decimal", separator=decimal["value"]) if decimal else area("decimal"),
    }
    for name in ("ordinals", "fractions", "ranges", "qualifiers", "contexts", "units"):
        rules[name] = area(name)
    return {
        "schema_version": "1.0",
        "profile": {
            "id": f"{project}-reconstructed", "version": recorded_date, "language": language, "script": script,
            "projects": [project], "source_guide": f"Reconstructed by SAGE NCA from {run_id}",
            "recorded_by": "SAGE NCA (reconstructed; review before import)", "recorded_date": recorded_date,
            "status": "CONFIGURED",
        },
        "rules": rules,
    }


def render(style: Mapping[str, object], *, project: str, profile_path: str | None = None) -> str:
    """NUMBER-STYLE.md: the rules (given or reconstructed) and the grouped inconsistencies."""
    lines = []
    if style.get("basis") == "PROFILE":
        lines += [f"# Number style — {project}", "",
                  f"Checked against the Number Style Profile `{style.get('profile')}`. Each row is one way the "
                  "translation departs from it.", ""]
    else:
        lines += [f"# Number style — {project} (reconstructed)", "",
                  "No Number Style Profile is selected. SAGE reconstructed the conventions from how this "
                  "translation writes its numbers (the dominant use per area). Approve the guide by importing "
                  "it as a Number Style Profile; later runs then report variance against it.", ""]
        if profile_path:
            lines += [f"Reconstructed profile: `{profile_path}`", ""]
        lines += ["## Reconstructed rules", "", "| Location | Area | Rule (dominant use) | Share | Numbers |",
                  "|---|---|---|---:|---:|"]
        for rule in style.get("rules", ()):
            what = f"{rule['rule'].lower()} for {rule['band']}" if rule["area"] == "bands" else rule["rule"]
            lines.append(f"| {rule['location'].lower()} | {rule['area']} | {what} | {rule['share_percent']} % "
                         f"| {rule['count']} |")
        lines.append("")
    patterns = list(style.get("patterns", ()))
    lines += ["## Inconsistencies", ""]
    if not patterns:
        lines += ["No inconsistencies found.", ""]
    else:
        lines += ["| Location | Area | Expected | Found | Count | Examples |", "|---|---|---|---|---:|---|"]
        for item in sorted(patterns, key=lambda row: -int(row["count"])):
            lines.append(f"| {item['location'].lower()} | {item['area']} | {item['expected']} | {item['found']} | "
                         f"{item['count']} | {' · '.join(item['examples'])} |")
        lines.append("")
        for item in patterns:
            if len(item["references"]) > _EXAMPLES:
                lines += [f"**{item['area']} — {item['found']}** ({item['count']}): "
                          + ", ".join(item["references"]), ""]
    for note in style.get("not_checked", ()):
        lines += [f"Not checked: {note}.", ""]
    lines += [f"Numbers classified: {style.get('numbers', 0)}. Number formatting only; wording and grammar are "
              "outside NCA."]
    return "\n".join(lines).rstrip() + "\n"
