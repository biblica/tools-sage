"""Non-blocking provider CLI update checks; a failed check never stops or delays SAGE work."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .atomic import atomic_write_json
from .errors import SageError
from .storage import storage_layout

CODEX_LATEST_RELEASE_URL = "https://api.github.com/repos/openai/codex/releases/latest"
CHECK_TTL_SECONDS = 12 * 3600
FETCH_TIMEOUT_SECONDS = 4
DISABLE_ENVIRONMENT_VARIABLE = "SAGE_DISABLE_UPDATE_CHECK"
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")

Fetcher = Callable[[], str]


@dataclass(frozen=True)
class CliUpdateStatus:
    """Installed-versus-latest comparison for one provider CLI."""

    installed: str | None
    latest: str | None
    update_available: bool
    source: str  # LIVE, CACHE, or UNAVAILABLE

    def summary(self) -> str:
        """Return one operator-facing line for status screens."""
        if self.latest is None:
            return "Update check unavailable"
        if self.update_available:
            return f"UPDATE AVAILABLE - {self.latest}"
        return "UP TO DATE"


def update_check_disabled() -> bool:
    """Return whether the operator or a test harness turned the network check off."""
    return os.environ.get(DISABLE_ENVIRONMENT_VARIABLE, "").strip().casefold() in {"1", "true", "yes"}


def parse_cli_version(text: str | None) -> tuple[int, int, int] | None:
    """Extract the first MAJOR.MINOR.PATCH triple from CLI output or a release tag."""
    match = _VERSION.search(str(text or ""))
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def _cache_path(root: Path) -> Path:
    """Return the per-installation cache of the latest known Codex release."""
    return storage_layout(root).state_root / "provider-update-check.json"


def _fetch_latest_tag() -> str:
    """Read the latest published Codex release tag; sends no local data."""
    # Imported here so the CA-bundle policy stays the one used for every SAGE HTTPS download.
    from .ollama_admin import OllamaAdminService

    request = urllib.request.Request(
        CODEX_LATEST_RELEASE_URL,
        headers={"User-Agent": f"SAGE/{__version__}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(
        request, timeout=FETCH_TIMEOUT_SECONDS, context=OllamaAdminService._https_context()  # noqa: SLF001
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload.get("tag_name") or "")


def _read_cache(root: Path) -> dict[str, Any]:
    """Return the cached check or an empty mapping when it is missing or unreadable."""
    try:
        value = json.loads(_cache_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def latest_codex_release(
    root: Path,
    *,
    force: bool = False,
    fetch: Fetcher | None = None,
    clock: Callable[[], float] = time.time,
) -> tuple[str | None, str]:
    """Return ``(latest_version, source)``; never raises and never blocks beyond one short request."""
    cache = _read_cache(root)
    cached = parse_cli_version(cache.get("latest"))
    checked_at = cache.get("checked_at")
    fresh = isinstance(checked_at, (int, float)) and 0 <= clock() - checked_at < CHECK_TTL_SECONDS
    if cached and fresh and not force:
        return ".".join(map(str, cached)), "CACHE"
    if fetch is None and update_check_disabled():
        return (".".join(map(str, cached)), "CACHE") if cached else (None, "UNAVAILABLE")
    try:
        latest = parse_cli_version((fetch or _fetch_latest_tag)())
    except (OSError, ValueError, SageError):
        latest = None
    if latest:
        text = ".".join(map(str, latest))
        try:
            atomic_write_json(_cache_path(root), {"latest": text, "checked_at": clock()})
        except OSError:
            pass
        return text, "LIVE"
    return (".".join(map(str, cached)), "CACHE") if cached else (None, "UNAVAILABLE")


def compare_codex_version(installed_text: str | None, latest: str | None, source: str) -> CliUpdateStatus:
    """Compare the installed CLI version text with the latest release version."""
    installed = parse_cli_version(installed_text)
    newest = parse_cli_version(latest)
    return CliUpdateStatus(
        installed=".".join(map(str, installed)) if installed else None,
        latest=latest if newest else None,
        update_available=bool(installed and newest and newest > installed),
        source=source,
    )
