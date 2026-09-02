"""System-interface localization for the SAGE terminal menu.

Interface language is workstation/setup state. It is deliberately independent from
Job reporting languages and Scripture language profiles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_text
from .errors import ConfigurationError, ValidationError
from .operator_overrides import load_effective_settings, write_local_settings

DEFAULT_INTERFACE_LANGUAGE = "en-US"
SUPPORTED_INTERFACE_LANGUAGES = ("en-US", "en-GB", "id", "fr", "ru", "pt-BR")
LANGUAGE_DISPLAY_NAMES = {
    "en-US": "English (United States)",
    "en-GB": "English (United Kingdom)",
    "id": "Bahasa Indonesia",
    "fr": "Français",
    "ru": "Русский",
    "pt-BR": "Português (Brasil)",
}
DEFAULT_MENU_SOURCE = Path("system/config/localization/menu-localization.json")


def _canonical_interface_language(value: object) -> str:
    """Resolve accepted interface-language aliases to one governed locale tag."""
    text = str(value or "").strip()
    aliases = {
        "en": "en-US",
        "en-us": "en-US",
        "en-gb": "en-GB",
        "id-id": "id",
        "fr-fr": "fr",
        "ru-ru": "ru",
        "pt-br": "pt-BR",
    }
    result = aliases.get(text.casefold(), text)
    if result not in SUPPORTED_INTERFACE_LANGUAGES:
        raise ValidationError(
            f"Unsupported SAGE interface language: {text or '<blank>'}",
            code="INTERFACE_LANGUAGE_NOT_SUPPORTED",
            next_action="Choose one of: " + ", ".join(SUPPORTED_INTERFACE_LANGUAGES),
        )
    return result


def load_interface_settings(settings_path: Path) -> tuple[str, str]:
    """Return configured interface language and canonical localization-source path."""
    try:
        raw, _override_path, _resolutions = load_effective_settings(settings_path)
    except Exception as exc:
        if isinstance(exc, ConfigurationError):
            raise
        raise ConfigurationError(f"Cannot load interface settings from {settings_path}: {exc}") from exc
    interface = raw.get("interface") or {}
    if not isinstance(interface, dict):
        raise ConfigurationError("interface must be a mapping")
    language = _canonical_interface_language(interface.get("language", DEFAULT_INTERFACE_LANGUAGE))
    source = str(interface.get("menu_localization_source") or DEFAULT_MENU_SOURCE.as_posix()).strip()
    return language, source


def save_interface_language(settings_path: Path, language: str) -> str:
    """Persist one setup-owned interface language without touching reporting policy."""
    selected = _canonical_interface_language(language)
    raw, _override_path, _resolutions = load_effective_settings(settings_path)
    interface = dict(raw.get("interface") or {})
    interface["language"] = selected
    interface.setdefault("menu_localization_source", DEFAULT_MENU_SOURCE.as_posix())
    write_local_settings(settings_path, {"interface": interface})
    return selected


@dataclass
class InterfaceLocalizer:
    """Localize menu strings from the canonical human-editable UTF-8 JSON source."""

    root: Path
    settings_path: Path
    language: str
    source_path: Path
    entries: dict[str, dict[str, str]]
    source_index: dict[str, dict[str, str]]

    @classmethod
    def load(cls, root: Path, settings_path: Path) -> "InterfaceLocalizer":
        """Load the active interface locale and its reduced canonical JSON source."""
        language, source_value = load_interface_settings(settings_path)
        raw_path = Path(source_value)
        source_path = raw_path if raw_path.is_absolute() else (root / raw_path)
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise ConfigurationError(f"Menu localization source not found: {source_path}")
        try:
            raw = json.loads(source_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Cannot load menu localization JSON from {source_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigurationError("Menu localization JSON root must be an object")
        meta = raw.get("_meta") or {}
        strings = raw.get("strings") or {}
        if not isinstance(meta, dict) or not isinstance(strings, dict) or not strings:
            raise ConfigurationError("Menu localization JSON requires _meta and non-empty strings objects")
        locales = meta.get("locales")
        if locales != list(SUPPORTED_INTERFACE_LANGUAGES):
            raise ConfigurationError(
                "Menu localization JSON locales must be exactly: " + ", ".join(SUPPORTED_INTERFACE_LANGUAGES)
            )

        entries: dict[str, dict[str, str]] = {}
        source_index: dict[str, dict[str, str]] = {}
        for key, value in strings.items():
            semantic_key = str(key or "").strip()
            if not semantic_key or not isinstance(value, dict):
                raise ConfigurationError(f"Invalid menu localization entry: {key!r}")
            values = {lang: str(value.get(lang) or "").strip() for lang in SUPPORTED_INTERFACE_LANGUAGES}
            blank = [lang for lang, text in values.items() if not text]
            if blank:
                raise ConfigurationError(
                    f"Menu localization entry {semantic_key} has blank languages: {', '.join(blank)}"
                )
            canonical_source = values["en-US"]
            lookup = canonical_source.casefold()
            if lookup in source_index:
                raise ConfigurationError(
                    f"Duplicate canonical en-US menu phrase in localization JSON: {canonical_source}"
                )
            values["key"] = semantic_key
            entries[semantic_key] = values
            source_index[lookup] = values

        return cls(
            root=root.resolve(),
            settings_path=settings_path.resolve(),
            language=language,
            source_path=source_path,
            entries=entries,
            source_index=source_index,
        )

    @property
    def table_path(self) -> Path:
        """Compatibility alias for callers that still display the old attribute name."""
        return self.source_path

    @property
    def rows(self) -> dict[str, dict[str, str]]:
        """Compatibility alias exposing the canonical source index."""
        return self.source_index

    def set_language(self, language: str) -> None:
        """Persist and activate a new interface language immediately."""
        self.language = save_interface_language(self.settings_path, language)

    def text_key(self, key: str) -> str:
        """Localize one stable semantic key."""
        row = self.entries.get(key)
        if row is None:
            return key
        return row.get(self.language) or row["en-US"]

    def text(self, source: str) -> str:
        """Localize one canonical en-US phrase while preserving edge whitespace and display case."""
        normalized = source.strip()
        if not normalized:
            return source
        row = self.source_index.get(normalized.casefold())
        if row is None:
            return source
        localized = row.get(self.language) or row["en-US"]
        leading = source[: len(source) - len(source.lstrip())]
        trailing = source[len(source.rstrip()) :]
        return leading + localized + trailing

    def language_name(self, language: str | None = None) -> str:
        """Return the self-name shown for one supported interface-language tag."""
        selected = language or self.language
        return LANGUAGE_DISPLAY_NAMES.get(selected, selected)

    def coverage(self) -> dict[str, Any]:
        """Return simple localization-source diagnostics for setup and tests."""
        return {
            "language": self.language,
            "source": str(self.source_path),
            "entries": len(self.entries),
            "languages": list(SUPPORTED_INTERFACE_LANGUAGES),
        }
