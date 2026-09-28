"""Offline CLDR-sourced locale facts: numbers, punctuation, and date/time conventions."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FIELD_GROUPS = ("numbers", "punctuation", "datetime")

_DATA = Path(__file__).with_name("data") / "cldr-locale-facts.json"


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    """Load the bundled CLDR locale-facts snapshot once."""
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    return dict(raw.get("locales") or {})


UNIVERSAL_FALLBACK = "en"


def _fallback_chain(tag: str) -> tuple[str, ...]:
    """Return the tag, its base language, then the universal fallback, without duplicates.

    Mirrors `build_locale_data.py`'s fallback chain: CLDR's `root` locale is not published as
    its own entry in the source packages, so `en` is the bundle's ultimate fallback tier.
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
    return tuple(seen)


def _locale_facts_with_tag(tag: str) -> tuple[str | None, dict[str, Any]]:
    """Return the resolved bundle tag alongside its entry, for provenance display."""
    registry = _registry()
    for candidate in _fallback_chain(tag):
        entry = registry.get(candidate)
        if entry:
            return candidate, entry
    return None, {}


def locale_facts(tag: str) -> dict[str, Any] | None:
    """Return the bundled CLDR entry for a tag, falling back to base language then root."""
    _, entry = _locale_facts_with_tag(tag)
    return entry or None


def resolve_locale_facts(
    *,
    tag: str,
    namespace_override: dict[str, dict[str, str]] | None = None,
    ldml_conventions: dict[str, dict[str, str] | None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge project LDML, namespace override, and bundled CLDR default, per field-group."""
    resolved_tag, bundled = _locale_facts_with_tag(tag)
    namespace_override = namespace_override or {}
    ldml_conventions = ldml_conventions or {}
    result: dict[str, dict[str, Any]] = {}
    for group in FIELD_GROUPS:
        ldml_value = ldml_conventions.get(group)
        override_value = namespace_override.get(group)
        if ldml_value:
            result[group] = {**dict(ldml_value), "source": "project_ldml"}
        elif override_value:
            result[group] = {**dict(override_value), "source": "namespace_override"}
        elif bundled.get(group):
            result[group] = {**dict(bundled[group]), "source": f"cldr:{resolved_tag}"}
        else:
            result[group] = {}
    return result
