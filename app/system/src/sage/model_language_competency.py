"""Model-release-specific estimated language competency registry for SAGE."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from .errors import ConfigurationError
from .iso_languages import iso_language
from .language_codes import canonical_regional_language_tag
from .storage import storage_layout

TIERS = ("EXCELLENT", "GOOD", "FAIR", "UNASSESSED")
TRUSTED_EVIDENCE_SOURCES = frozenset(
    {"SAGE_RELEASE_SEED", "VERSIONED_REGISTRY", "MEASURED_EVALUATION"}
)


def competency_policy_path(root: Path) -> Path:
    """Return the governed SYSTEM competency policy path."""
    return root / "system" / "config" / "model-language-competency.yml"


def competency_registry_path(root: Path) -> Path:
    """Return the local persistent competency registry path."""
    return storage_layout(root).config_root / "model-language-competency.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load one UTF-8 YAML mapping and normalize missing files to an empty mapping."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read model language competency YAML: {path}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError(f"Model language competency YAML must contain a mapping: {path}")
    return raw


def load_competency_policy(root: Path) -> dict[str, Any]:
    """Load and validate the governed model-language competency policy."""
    path = competency_policy_path(root)
    raw = _load_yaml(path)
    if str(raw.get("schema_version") or "") != "1.0":
        raise ConfigurationError("SAGE model language competency policy must be schema_version 1.0")
    policy = dict(raw.get("policy") or {})
    tiers = tuple(str(value).upper() for value in policy.get("tiers", ()))
    if tiers != TIERS:
        raise ConfigurationError(f"Model language competency tiers must be {list(TIERS)}")
    return raw


def _seed_registry(root: Path) -> dict[str, Any]:
    """Materialize the release seed table as an in-memory registry."""
    policy = load_competency_policy(root)
    models: dict[str, Any] = {}
    for row in policy.get("seed_models", []):
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "").strip().lower()
        model = str(row.get("model") or "").strip()
        if not provider or not model:
            continue
        key = model_release_key(provider, model)
        languages: dict[str, Any] = {}
        for tag, item in dict(row.get("languages") or {}).items():
            value = dict(item or {})
            tier = str(value.get("tier") or "UNASSESSED").upper()
            if tier not in TIERS:
                raise ConfigurationError(f"Invalid seed competency tier {tier!r} for {tag}")
            languages[str(tag)] = {
                "canonical_tag": str(tag),
                "language": str(value.get("language") or tag),
                "region": None,
                "script": None,
                "tier": tier,
                "confidence": "SEED",
                "basis": [],
                "limitations": [],
                "operator_message": "",
                "assessment_source": str(row.get("assessment_source") or "SAGE_RELEASE_SEED"),
                "assessed_at": None,
            }
        models[key] = {
            "provider": provider,
            "model": model,
            "model_version": str(row.get("model_version") or model),
            "provider_runtime_version": None,
            "assessment_source": str(row.get("assessment_source") or "SAGE_RELEASE_SEED"),
            "assessed_at": None,
            "languages": languages,
        }
    return {"schema_version": "1.0", "models": models}


def load_competency_registry(root: Path) -> dict[str, Any]:
    """Load local competency history and merge only missing release seeds."""
    path = competency_registry_path(root)
    raw = _load_yaml(path)
    if not raw:
        return _seed_registry(root)
    if str(raw.get("schema_version") or "") != "1.0" or not isinstance(raw.get("models"), dict):
        raise ConfigurationError("Local model language competency registry is invalid")
    # Merge missing release seeds without overwriting operator-supplied measured evidence.
    seed = _seed_registry(root)
    models = dict(raw.get("models") or {})
    for key, value in dict(seed.get("models") or {}).items():
        existing = models.get(key)
        source = (
            str(existing.get("assessment_source") or "").strip().upper()
            if isinstance(existing, dict)
            else ""
        )
        if source not in TRUSTED_EVIDENCE_SOURCES:
            models[key] = value
    return {"schema_version": "1.0", "models": models}


def model_release_key(provider: str, model: str) -> str:
    """Return the stable registry key for one provider/model release pair."""
    return f"{provider.strip().lower()}::{model.strip()}"


def model_record(root: Path, provider: str, model: str) -> dict[str, Any] | None:
    """Return one model-release record only when its evidence source is trusted."""
    registry = load_competency_registry(root)
    value = registry["models"].get(model_release_key(provider, model))
    if not isinstance(value, dict):
        return None
    source = str(value.get("assessment_source") or "").strip().upper()
    return dict(value) if source in TRUSTED_EVIDENCE_SOURCES else None


def lookup_language(record: dict[str, Any] | None, canonical_tag: str) -> dict[str, Any] | None:
    """Resolve an exact regional assessment, with optional base-language fallback for legacy seeds."""
    if not record:
        return None
    languages = dict(record.get("languages") or {})
    exact = languages.get(canonical_tag)
    if (
        isinstance(exact, dict)
        and str(exact.get("assessment_source") or record.get("assessment_source") or "").upper()
        in TRUSTED_EVIDENCE_SOURCES
    ):
        return dict(exact)
    base = canonical_tag.split("-", 1)[0].casefold()
    inherited = languages.get(base)
    if (
        isinstance(inherited, dict)
        and str(inherited.get("assessment_source") or record.get("assessment_source") or "").upper()
        in TRUSTED_EVIDENCE_SOURCES
    ):
        return dict(inherited)
    return None


def exact_language_assessed(record: dict[str, Any] | None, canonical_tag: str) -> bool:
    """Return whether this exact regional/scripted language has a stored row."""
    return bool(record and isinstance(dict(record.get("languages") or {}).get(canonical_tag), dict))


def known_language_rows(root: Path, extra: Iterable[dict[str, Any]] = ()) -> list[dict[str, str]]:
    """Return de-duplicated canonical languages known to SAGE for registry lookup."""
    policy = load_competency_policy(root)
    rows: dict[str, dict[str, str]] = {}
    # Seed list is deliberately base-language context; runtime/project languages add regional identities.
    for seed in policy.get("seed_models", []):
        for tag, item in dict((seed or {}).get("languages") or {}).items():
            rows.setdefault(str(tag), {"canonical_tag": str(tag), "language": str((item or {}).get("language") or tag), "region": "", "script": ""})
    grammar_root = root / "system" / "config" / "profiles" / "grammar"
    if grammar_root.is_dir():
        for directory in sorted(path for path in grammar_root.iterdir() if path.is_dir() and "-" in path.name):
            tag = directory.name
            base = tag.split("-", 1)[0]
            language = str((iso_language(base) or {}).get("name") or base)
            rows[tag] = {"canonical_tag": tag, "language": language, "region": tag.split("-")[-1], "script": ""}
    for item in extra:
        tag = str(item.get("canonical_tag") or "").strip()
        if tag:
            rows[tag] = {
                "canonical_tag": tag,
                "language": str(item.get("language") or tag),
                "region": str(item.get("region") or ""),
                "script": str(item.get("script") or ""),
            }
    return [rows[key] for key in sorted(rows)]


def operator_rows(record: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """Return the low-detail rows used by the operator-facing competency table."""
    if not record:
        return []
    rows: list[tuple[str, str, str]] = []
    for tag, item in sorted(dict(record.get("languages") or {}).items()):
        value = dict(item or {})
        rows.append((tag, str(value.get("language") or tag), str(value.get("tier") or "UNASSESSED")))
    return rows
