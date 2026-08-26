"""Canonical language-tag validation for SAGE project and profile identity."""

from __future__ import annotations

import re

from .errors import ConfigurationError

# SAGE uses canonical BCP 47-style tags. The aliases below are common ISO 639-2/3
# forms that have a shorter preferred language subtag for the current resources.
PREFERRED_PRIMARY_SUBTAGS = {
    "eng": "en",
    "ind": "id",
    "ukr": "uk",
    "fas": "fa",
    "per": "fa",
    "hin": "hi",
    "fra": "fr",
    "fre": "fr",
    "amh": "am",
    "tir": "ti",
    "hau": "ha",
    "spa": "es",
    "por": "pt",
    "deu": "de",
    "ger": "de",
    "ara": "ar",
}

_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}$")
_SCRIPT_RE = re.compile(r"^[A-Za-z]{4}$")
_REGION_RE = re.compile(r"^(?:[A-Za-z]{2}|[0-9]{3})$")
_VARIANT_RE = re.compile(r"^(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3})$")


def canonical_language_tag(value: str, label: str, *, require_preferred: bool = True) -> str:
    """Return a case-normalized canonical language tag or raise `ConfigurationError`.

    SAGE intentionally supports the language/script/region/variant subset needed by
    project and profile routing. Extensions and private-use subtags are rejected so
    profile identity remains deterministic and auditable.
    """
    raw = value.strip()
    if not raw:
        raise ConfigurationError(f"{label} must be a non-empty language tag")
    if "_" in raw:
        raise ConfigurationError(f"{label} must use '-' rather than '_' in language tags")
    parts = raw.split("-")
    if any(not part for part in parts) or not _LANGUAGE_RE.fullmatch(parts[0]):
        raise ConfigurationError(f"{label} is not a supported BCP 47 language tag: {value!r}")

    primary = parts[0].lower()
    preferred = PREFERRED_PRIMARY_SUBTAGS.get(primary, primary)
    if require_preferred and preferred != primary:
        raise ConfigurationError(
            f"{label} uses non-preferred language subtag {primary!r}; use {preferred!r}"
        )
    normalized: list[str] = [preferred]
    index = 1

    if index < len(parts) and _SCRIPT_RE.fullmatch(parts[index]):
        normalized.append(parts[index].title())
        index += 1
    if index < len(parts) and _REGION_RE.fullmatch(parts[index]):
        normalized.append(parts[index].upper())
        index += 1
    while index < len(parts):
        part = parts[index]
        if not _VARIANT_RE.fullmatch(part):
            raise ConfigurationError(
                f"{label} contains unsupported extension or invalid variant subtag: {part!r}"
            )
        normalized.append(part.lower())
        index += 1
    return "-".join(normalized)


def canonical_script_code(value: str, label: str) -> str:
    """Return one ISO 15924-style script code in canonical title case."""
    raw = value.strip()
    if not _SCRIPT_RE.fullmatch(raw):
        raise ConfigurationError(f"{label} must be a four-letter script code")
    return raw.title()


def canonical_regional_language_tag(value: str, label: str) -> str:
    """Return a canonical language tag that includes an explicit region subtag."""
    tag = canonical_language_tag(value, label, require_preferred=False)
    parts = tag.split("-")
    index = 1
    if index < len(parts) and _SCRIPT_RE.fullmatch(parts[index]):
        index += 1
    if index >= len(parts) or not _REGION_RE.fullmatch(parts[index]):
        raise ConfigurationError(f"{label} must include an explicit region/country subtag")
    return tag
