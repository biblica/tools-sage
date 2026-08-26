"""Offline ISO evidence for Paratext metadata review and explicit profile routing."""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


_DATA = Path(__file__).with_name("data") / "iso-639-3.json"
_WORD_RE = re.compile(r"[a-z]+")

@lru_cache(maxsize=1)
def _registry() -> tuple[dict[str, dict[str, Any]], tuple[dict[str, Any], ...]]:
    """Load bundled ISO rows once and index alpha-2/alpha-3/bibliographic codes."""
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    rows = tuple(dict(row) for row in raw.get("languages", []) if isinstance(row, dict))
    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in ("alpha_3", "alpha_2", "bibliographic"):
            value = str(row.get(key) or "").strip().casefold()
            if value:
                by_code[value] = row
    return by_code, rows

def iso_language(code: str | None) -> dict[str, Any] | None:
    """Return one ISO registry row for a two/three-letter code or alias."""
    value = str(code or "").strip().casefold()
    if not value:
        return None
    return _registry()[0].get(value)

def _name_words(value: str | None) -> set[str]:
    """Normalize an ISO language name to lowercase word evidence for prefix comparison."""
    return set(_WORD_RE.findall(str(value or "").casefold()))

def resolve_paratext_language(*, settings_code: str | None, language_name: str | None, project_prefix: str | None) -> dict[str, Any]:
    """Assess settings.xml ISO metadata and use Project prefix/name only as secondary evidence."""
    raw = str(settings_code or "").strip().casefold() or None
    direct = iso_language(raw)
    prefix = str(project_prefix or "").strip().casefold() or None
    prefix_row = iso_language(prefix)
    status = "VALID" if direct is not None else ("MISSING" if raw is None else "INVALID")
    suggestions: list[str] = []
    # Project language name is the strongest fallback evidence when settings code is absent/invalid.
    wanted = str(language_name or "").strip().casefold()
    if status != "VALID" and wanted:
        for row in _registry()[1]:
            names = {str(row.get("name") or "").casefold(), str(row.get("inverted_name") or "").casefold()}
            if wanted in names:
                suggestions.append(str(row.get("alpha_3")))
    if status != "VALID" and prefix_row is not None:
        candidate = str(prefix_row.get("alpha_3"))
        if candidate and candidate not in suggestions:
            suggestions.append(candidate)
    consistent: bool | None = None
    if direct is not None and prefix_row is not None:
        if direct.get("alpha_3") == prefix_row.get("alpha_3"):
            consistent = True
        else:
            # A macrolanguage prefix may corroborate a specific language (fa + Iranian Persian,
            # zh + Mandarin Chinese) without being a reason to replace the declared 639-3 code.
            direct_words = _name_words(direct.get("name"))
            prefix_words = _name_words(prefix_row.get("name"))
            consistent = bool(direct_words & prefix_words)
    prefix_evidence = None
    if prefix_row is not None:
        prefix_evidence = f"{prefix} -> {prefix_row.get('name')}" + (" [consistent]" if consistent is True else "" if consistent is None else " [review]")
    return {
        "status": status,
        "declared_code": raw,
        "canonical_alpha_3": str(direct.get("alpha_3")) if direct else None,
        "language_name": str(direct.get("name")) if direct else None,
        "prefix": prefix,
        "prefix_evidence": prefix_evidence,
        "prefix_consistent": consistent,
        "suggestions": suggestions,
    }


# SAGE operational starter profiles require a regional identity. These candidates
# are deliberately explicit and are presented to the Operator; they are not a
# license to infer a Project region silently when more than one candidate exists.
DEFAULT_REGIONAL_PROFILE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "en": ("en-US", "en-GB"),
    "id": ("id-ID",),
    "uk": ("uk-UA",),
    "fa": ("fa-IR",),
    "pes": ("pes-IR",),
    "prs": ("prs-AF",),
    "hi": ("hi-IN",),
    "fr": ("fr-FR", "fr-011"),
    "am": ("am-ET",),
    "ti": ("ti-ER", "ti-ET"),
    "ha": ("ha-NG", "ha-NE"),
    "es": ("es-419", "es-BR"),
    "pt": ("pt-BR", "pt-419"),
    "de": ("de-DE",),
    "ar": ("ar-SA", "ar-145"),
}


def preferred_operational_primary(code: str | None, language_name: str | None = None) -> str | None:
    """Return SAGE's preferred primary language subtag without treating Paratext shorthand as authoritative."""
    raw = str(code or "").strip().casefold()
    name = str(language_name or "").strip().casefold()
    if raw == "pa" and ("persian" in name or "farsi" in name):
        return "fa"
    row = iso_language(raw)
    if row is None:
        return None
    alpha3 = str(row.get("alpha_3") or "").casefold()
    alpha2 = str(row.get("alpha_2") or "").casefold()
    return alpha2 or alpha3 or None


def regional_profile_candidates(
    *,
    language_code: str | None,
    language_name: str | None,
    configured_profiles: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return configured regional profile candidates for imported language metadata."""
    primary = preferred_operational_primary(language_code, language_name)
    if not primary:
        return ()
    candidates = DEFAULT_REGIONAL_PROFILE_CANDIDATES.get(primary, ())
    if configured_profiles is None:
        return candidates
    return tuple(tag for tag in candidates if tag in configured_profiles)
