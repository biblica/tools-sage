"""Fetch and vendor a bounded slice of Unicode CLDR locale facts for SAGE Language Profiles.

Produces `src/sage/data/cldr-locale-facts.json`: per-locale number-system, punctuation, and
date/time facts resolved once at build time from `unicode-org/cldr-json`. Consumed offline at
runtime by `sage.locale_data`; this tool is the only part of SAGE that talks to the network.
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import certifi

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "system" / "src" / "sage" / "data" / "cldr-locale-facts.json"
RAW_BASE = "https://raw.githubusercontent.com/unicode-org/cldr-json/{ref}/cldr-json"

FIELD_GROUPS = ("numbers", "punctuation", "datetime")

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _fetch_json(url: str, *, timeout: float = 20.0) -> dict[str, Any] | None:
    """Fetch one CLDR JSON file, returning None for a locale/package that does not exist."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to fetch {url}: {exc}") from exc


UNIVERSAL_FALLBACK = "en"


def _fallback_chain(tag: str) -> list[str]:
    """Return the tag, its base language, then the universal fallback, without duplicates.

    CLDR's `root` locale is not published as its own entry in the `-full` npm packages this
    tool fetches (root has no directory under `cldr-numbers-full/main/`, etc.) so `en` — the
    most complete real CLDR locale — is used as the ultimate practical default instead of a
    fabricated root entry.
    """
    base = tag.split("-", 1)[0]
    chain = [tag] if tag != base else []
    chain.append(base)
    if base != UNIVERSAL_FALLBACK:
        chain.append(UNIVERSAL_FALLBACK)
    seen: list[str] = []
    for item in chain:
        if item not in seen:
            seen.append(item)
    return seen


def _date_field_order(pattern: str) -> str | None:
    """Derive the short-date field order (YMD/DMY/MDY) from a CLDR skeleton pattern.

    Case matters here: CLDR uses 'y'/'Y' for year, capital 'M' for month (lowercase 'm' is
    minutes elsewhere), and 'd' for day — so this deliberately does not lowercase the pattern.
    """
    order = []
    for tokens, field in ((("y", "Y"), "Y"), (("M",), "M"), (("d",), "D")):
        index = min((pattern.find(token) for token in tokens if token in pattern), default=-1)
        if index != -1:
            order.append((index, field))
    if len(order) != 3:
        return None
    order.sort()
    return "".join(field for _, field in order)


def _hour_cycle(pattern: str) -> str | None:
    """Classify a CLDR short-time pattern as 12-hour or 24-hour."""
    if any(ch in pattern for ch in ("h", "K")):
        return "h12"
    if any(ch in pattern for ch in ("H", "k")):
        return "h24"
    return None


def _grouping_style(pattern: str) -> str:
    """Classify a CLDR decimal pattern as Western (THREE) or Indic (THREE_TWO) grouping."""
    whole = pattern.split(".", 1)[0]
    return "THREE_TWO" if whole.count(",") >= 2 else "THREE"


class CldrSource:
    """Fetch and cache the handful of CLDR packages this tool needs."""

    def __init__(self, ref: str) -> None:
        """Bind one pinned unicode-org/cldr-json ref for every fetch this source performs."""
        self.ref = ref
        self._numbers: dict[str, dict[str, Any] | None] = {}
        self._delimiters: dict[str, dict[str, Any] | None] = {}
        self._dates: dict[str, dict[str, Any] | None] = {}
        self._numbering_systems: dict[str, Any] | None = None
        self._calendar_preference: dict[str, Any] | None = None

    def _package_url(self, package: str, path: str) -> str:
        """Build one raw.githubusercontent.com URL for a file inside a CLDR package."""
        return f"{RAW_BASE.format(ref=self.ref)}/{package}/{path}"

    def numbers(self, locale: str) -> dict[str, Any] | None:
        """Fetch and cache one locale's `numbers.json` body, or None if it does not exist."""
        if locale not in self._numbers:
            data = _fetch_json(self._package_url("cldr-numbers-full", f"main/{locale}/numbers.json"))
            self._numbers[locale] = data["main"][locale]["numbers"] if data else None
        return self._numbers[locale]

    def delimiters(self, locale: str) -> dict[str, Any] | None:
        """Fetch and cache one locale's `delimiters.json` body, or None if it does not exist."""
        if locale not in self._delimiters:
            data = _fetch_json(self._package_url("cldr-misc-full", f"main/{locale}/delimiters.json"))
            self._delimiters[locale] = data["main"][locale]["delimiters"] if data else None
        return self._delimiters[locale]

    def dates(self, locale: str) -> dict[str, Any] | None:
        """Fetch and cache one locale's Gregorian calendar dates, or None if it does not exist."""
        if locale not in self._dates:
            data = _fetch_json(self._package_url("cldr-dates-full", f"main/{locale}/ca-gregorian.json"))
            self._dates[locale] = (
                data["main"][locale]["dates"]["calendars"]["gregorian"] if data else None
            )
        return self._dates[locale]

    def numbering_systems(self) -> dict[str, Any]:
        """Fetch and cache the shared numbering-systems supplemental data once."""
        if self._numbering_systems is None:
            data = _fetch_json(self._package_url("cldr-core", "supplemental/numberingSystems.json"))
            self._numbering_systems = (data or {}).get("supplemental", {}).get("numberingSystems", {})
        return self._numbering_systems

    def calendar_preference(self) -> dict[str, Any]:
        """Fetch and cache the shared per-region calendar-preference supplemental data once."""
        if self._calendar_preference is None:
            data = _fetch_json(self._package_url("cldr-core", "supplemental/calendarPreferenceData.json"))
            self._calendar_preference = (data or {}).get("supplemental", {}).get("calendarPreferenceData", {})
        return self._calendar_preference


def _numbers_facts(source: CldrSource, locale: str) -> dict[str, str] | None:
    """Derive one locale's number-system facts from its raw CLDR numbers.json, or None."""
    numbers = source.numbers(locale)
    if not numbers:
        return None
    system = numbers.get("defaultNumberingSystem")
    symbols = numbers.get(f"symbols-numberSystem-{system}") or {}
    decimal_formats = numbers.get(f"decimalFormats-numberSystem-{system}") or {}
    pattern = decimal_formats.get("standard")
    decimal = symbols.get("decimal")
    group = symbols.get("group")
    if not (system and decimal and group and pattern):
        return None
    digits = source.numbering_systems().get(system, {}).get("_digits")
    facts = {
        "numbering_system": system,
        "decimal_separator": decimal,
        "group_separator": group,
        "grouping_style": _grouping_style(pattern),
    }
    if digits:
        facts["digits"] = digits
    return facts


def _punctuation_facts(source: CldrSource, locale: str) -> dict[str, str] | None:
    """Derive one locale's quotation-mark facts from its raw CLDR delimiters.json, or None."""
    delimiters = source.delimiters(locale)
    if not delimiters:
        return None
    required = ("quotationStart", "quotationEnd")
    if not all(delimiters.get(key) for key in required):
        return None
    facts = {
        "quote_start": delimiters["quotationStart"],
        "quote_end": delimiters["quotationEnd"],
    }
    if delimiters.get("alternateQuotationStart") and delimiters.get("alternateQuotationEnd"):
        facts["alt_quote_start"] = delimiters["alternateQuotationStart"]
        facts["alt_quote_end"] = delimiters["alternateQuotationEnd"]
    return facts


def _datetime_facts(source: CldrSource, locale: str, *, region: str | None) -> dict[str, str] | None:
    """Derive one locale's date/time facts from its raw CLDR ca-gregorian.json, or None."""
    dates = source.dates(locale)
    if not dates:
        return None
    short_date = (dates.get("dateFormats") or {}).get("short")
    short_time = (dates.get("timeFormats") or {}).get("short")
    if not (short_date and short_time):
        return None
    field_order = _date_field_order(short_date)
    hour_cycle = _hour_cycle(short_time)
    if not (field_order and hour_cycle):
        return None
    preference = source.calendar_preference()
    calendar_list = preference.get(region or "001") or preference.get("001") or ["gregorian"]
    return {
        "date_field_order": field_order,
        "calendar": calendar_list[0],
        "hour_cycle": hour_cycle,
    }


def _build_locale_entry(source: CldrSource, tag: str) -> dict[str, Any] | None:
    """Resolve one requested tag by walking its fallback chain per field-group."""
    region = tag.split("-", 1)[1] if "-" in tag else None
    entry: dict[str, Any] = {}
    for group, builder in (
        ("numbers", lambda locale: _numbers_facts(source, locale)),
        ("punctuation", lambda locale: _punctuation_facts(source, locale)),
        ("datetime", lambda locale: _datetime_facts(source, locale, region=region)),
    ):
        for candidate in _fallback_chain(tag):
            facts = builder(candidate)
            if facts:
                entry[group] = facts
                break
    return entry or None


def default_locales() -> list[str]:
    """Derive the default locale list from ecosystem.yml's registered language profiles."""
    import yaml

    ecosystem = yaml.safe_load((ROOT / "ecosystem.yml").read_text(encoding="utf-8"))
    tags = sorted(tag for tag in (ecosystem.get("language_profiles") or {}) if tag != "en")
    return tags


def build(*, locales: list[str], ref: str) -> dict[str, Any]:
    """Resolve every requested tag (plus its fallback chain) into one flattened locales map."""
    source = CldrSource(ref)
    locales_out: dict[str, Any] = {}
    needed: list[str] = []
    for tag in locales:
        for candidate in _fallback_chain(tag):
            if candidate not in needed:
                needed.append(candidate)
    for tag in needed:
        entry = _build_locale_entry(source, tag)
        if entry:
            locales_out[tag] = entry
    if UNIVERSAL_FALLBACK not in locales_out:
        raise RuntimeError(
            f"CLDR universal fallback locale {UNIVERSAL_FALLBACK!r} must resolve; check network access"
        )
    return locales_out


def _check(output: Path) -> int:
    """Offline dry-run: verify the vendored bundle covers every registered language, no network."""
    if not output.is_file():
        print(f"missing vendored bundle: {output}", file=sys.stderr)
        return 1
    bundle = json.loads(output.read_text(encoding="utf-8"))
    locales = bundle.get("locales") or {}
    missing = [tag for tag in default_locales() if not any(
        candidate in locales for candidate in _fallback_chain(tag)
    )]
    if missing:
        print(f"bundle missing locale-fact coverage for: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", "locales_registered": len(default_locales()), "bundle_entries": len(locales)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and either check or (re)write the vendored locale-facts bundle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locales", help="comma-separated BCP-47 tags (default: every registered Language Profile)")
    parser.add_argument("--ref", default="main", help="unicode-org/cldr-json git ref (tag/commit) to fetch")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="offline: verify the existing bundle, no network access")
    args = parser.parse_args(argv)

    if args.check:
        return _check(args.output)

    locales = args.locales.split(",") if args.locales else default_locales()
    locales_out = build(locales=locales, ref=args.ref)
    bundle = {
        "source": "Unicode CLDR JSON (unicode-org/cldr-json), packages cldr-numbers-full, "
                   "cldr-misc-full, cldr-dates-full, cldr-core",
        "schema_version": "1.0",
        "cldr_ref": args.ref,
        "locales": locales_out,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "WROTE", "output": str(args.output), "locales": len(locales_out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
