"""Deterministic Paratext language/country evidence collection for Beta."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from .errors import ValidationError
from .iso_languages import iso_language, preferred_operational_primary, regional_profile_candidates
from .language_codes import canonical_regional_language_tag

_PREFIX_RE = re.compile(r"^([a-z]+)")
_COUNTRY_DATA = Path(__file__).with_name("data") / "iso-3166-1.json"


@lru_cache(maxsize=1)
def _countries() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Return ISO-3166 rows indexed by standard identifiers and normalized names."""
    raw = json.loads(_COUNTRY_DATA.read_text(encoding="utf-8"))
    by_code: dict[str, dict[str, str]] = {}
    by_name: dict[str, dict[str, str]] = {}
    for row in raw.get("3166-1", []):
        if not isinstance(row, dict):
            continue
        code = str(row.get("alpha_2") or "").upper()
        alpha3 = str(row.get("alpha_3") or "").upper()
        numeric = str(row.get("numeric") or "").strip()
        name = str(row.get("name") or "").strip()
        identity = {"code": code, "name": name}
        if code:
            by_code[code] = identity
        if alpha3:
            by_code[alpha3] = identity
        if numeric:
            by_code[numeric] = identity
        if name:
            by_name[name.casefold()] = identity
        common = str(row.get("common_name") or "").strip()
        if common:
            by_name[common.casefold()] = {"code": code, "name": common}
        official = str(row.get("official_name") or "").strip()
        if official:
            by_name[official.casefold()] = identity
    return by_code, by_name


def resolve_country(value: str | None) -> dict[str, str] | None:
    """Resolve one ISO country identifier or country name to alpha-2 identity."""
    text = str(value or "").strip()
    if not text:
        return None
    by_code, by_name = _countries()
    if text.upper() in by_code:
        return dict(by_code[text.upper()])
    return dict(by_name[text.casefold()]) if text.casefold() in by_name else None


def resolve_country_input(value: str | None) -> dict[str, str] | None:
    """Resolve direct country input, including a regional language tag such as en-US."""
    country = resolve_country(value)
    if country is not None:
        return country
    parts = str(value or "").strip().replace("_", "-").split("-")
    if len(parts) not in {2, 3} or iso_language(parts[0]) is None:
        return None
    region = parts[-1]
    if len(region) == 2 or (len(region) == 3 and region.isdigit()):
        return resolve_country(region)
    return None


def _local(tag: str) -> str:
    """Return one XML local tag name in lowercase."""
    return str(tag).rsplit("}", 1)[-1].casefold()


def parse_ldml_identity(path: Path) -> dict[str, Any]:
    """Read only the LDML identity block from one file."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValidationError(f"Invalid LDML file: {path}: {exc}", code="PARATEXT_LDML_INVALID") from exc
    identity = next((item for item in root.iter() if _local(item.tag) == "identity"), None)
    if identity is None:
        return {"file": path.name, "language": None, "script": None, "territory": None}
    values: dict[str, Any] = {"file": path.name, "language": None, "script": None, "territory": None}
    for item in identity.iter():
        key = _local(item.tag)
        if key in {"language", "script", "territory"}:
            value = str(item.attrib.get("type") or item.text or "").strip()
            if value:
                values[key] = value
    return values


def project_prefix_candidates(project_code: str) -> tuple[str, ...]:
    """Return plausible two/three-letter ISO candidates from initial lowercase letters."""
    match = _PREFIX_RE.match(str(project_code or ""))
    if not match:
        return ()
    prefix = match.group(1)
    values: list[str] = []
    for length in (2, 3):
        if len(prefix) >= length:
            candidate = prefix[:length]
            if iso_language(candidate) is not None and candidate not in values:
                values.append(candidate)
    return tuple(values)


def _iso_identity(code: str | None) -> dict[str, str] | None:
    """Return normalized alpha-2/alpha-3 identity for one ISO language code."""
    row = iso_language(code)
    if row is None:
        return None
    alpha3 = str(row.get("alpha_3") or "").casefold()
    alpha2 = str(row.get("alpha_2") or "").casefold()
    return {
        "alpha_3": alpha3,
        "alpha_2": alpha2,
        "preferred": alpha2 or alpha3,
        "name": str(row.get("name") or ""),
    }


def estimate_language_identity(
    *,
    project_code: str,
    settings_code: str | None,
    language_name: str | None,
    ldml_rows: Iterable[dict[str, Any]],
    settings_countries: Iterable[str] = (),
) -> dict[str, Any]:
    """Rank language evidence without treating any single Paratext field as infallible."""
    scores: dict[str, int] = {}
    reasons: dict[str, list[str]] = {}

    def add(code: str | None, weight: int, reason: str) -> None:
        """Add weighted evidence for one canonical ISO language identity."""
        identity = _iso_identity(code)
        if identity is None:
            return
        key = identity["alpha_3"]
        scores[key] = scores.get(key, 0) + weight
        reasons.setdefault(key, []).append(reason)

    add(settings_code, 5, f"Settings.xml={settings_code}")
    seen_ldml: set[str] = set()
    countries: dict[str, dict[str, str]] = {}
    scripts: list[str] = []
    ldml_evidence: list[dict[str, Any]] = []
    for raw in ldml_rows:
        row = dict(raw)
        ldml_evidence.append(row)
        language = str(row.get("language") or "").casefold()
        identity = _iso_identity(language)
        if identity is not None and identity["alpha_3"] not in seen_ldml:
            seen_ldml.add(identity["alpha_3"])
            add(language, 4, f"LDML {row.get('file')}={language}")
        script = str(row.get("script") or "").strip()
        if script and script not in scripts:
            scripts.append(script)
        territory = resolve_country(str(row.get("territory") or ""))
        if territory:
            countries[territory["code"]] = territory
    for value in settings_countries:
        country = resolve_country(value)
        if country:
            countries[country["code"]] = country
    for candidate in project_prefix_candidates(project_code):
        add(candidate, 2, f"project prefix={candidate}")
    wanted = str(language_name or "").strip().casefold()
    if wanted:
        for code in tuple(scores):
            row = iso_language(code) or {}
            names = {str(row.get("name") or "").casefold(), str(row.get("inverted_name") or "").casefold()}
            if wanted in names:
                scores[code] += 3
                reasons[code].append(f"language name={language_name}")

    ranked = sorted(scores, key=lambda code: (-scores[code], code))
    candidates: list[dict[str, Any]] = []
    for code in ranked:
        identity = _iso_identity(code)
        assert identity is not None
        candidates.append({**identity, "score": scores[code], "evidence": reasons.get(code, [])})
    selected = candidates[0] if candidates else None
    confidence = "LOW"
    if selected:
        margin = selected["score"] - (candidates[1]["score"] if len(candidates) > 1 else 0)
        confidence = "HIGH" if selected["score"] >= 8 and margin >= 3 else "MEDIUM" if selected["score"] >= 5 else "LOW"

    primary = selected["preferred"] if selected else None
    configured_region_candidates = regional_profile_candidates(
        language_code=primary,
        language_name=selected["name"] if selected else language_name,
        configured_profiles=None,
    ) if primary else ()
    country_rows = sorted(countries.values(), key=lambda row: row["code"])
    primary_country = country_rows[0] if len(country_rows) == 1 else None
    if primary_country is None and len(country_rows) == 0 and len(configured_region_candidates) == 1:
        region = configured_region_candidates[0].split("-")[-1]
        primary_country = resolve_country(region)
    bcp47 = None
    if primary and primary_country:
        bcp47 = canonical_regional_language_tag(f"{primary}-{primary_country['code']}", "Language Profile candidate")
    return {
        "status": "RESOLVED" if selected else "UNRESOLVED",
        "confidence": confidence,
        "selected": selected,
        "candidates": candidates,
        "ldml": ldml_evidence,
        "country_evidence": country_rows,
        "primary_country": primary_country,
        "scripts": scripts,
        "bcp47_candidate": bcp47,
        "regional_candidates": list(configured_region_candidates),
    }
