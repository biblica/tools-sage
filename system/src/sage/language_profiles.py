"""First-class Language Profile namespace maintenance for Beta."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_text
from .errors import ValidationError
from .language_codes import canonical_regional_language_tag, canonical_script_code
from .registry import load_ecosystem
from .operator_overrides import load_effective_settings, write_local_settings


def ensure_language_profile_namespace(settings_path: Path, *, tag: str, script: str) -> bool:
    """Create one empty regional Language Profile namespace if it does not already exist."""
    tag = canonical_regional_language_tag(tag, "Language Profile")
    script = canonical_script_code(script, "Language Profile script")
    raw, _override_path, _resolutions = load_effective_settings(settings_path)
    profiles = dict(raw.get("language_profiles") or {})
    if tag in profiles:
        return False
    profiles[tag] = {"script": script, "variants": {}}
    write_local_settings(settings_path, {"language_profiles": profiles})
    load_ecosystem(settings_path)
    return True


def language_profile_status(settings_path: Path, tag: str) -> dict[str, Any]:
    """Return operator-facing namespace and grammar-variant status."""
    config = load_ecosystem(settings_path)
    namespace = config.language_profiles.get(tag)
    if namespace is None:
        return {"tag": tag, "status": "NOT_CONFIGURED", "script": None, "variants": []}
    variants = sorted(f"{item.role}:{item.variant_id}" for item in namespace.variants.values())
    return {
        "tag": tag,
        "status": "READY" if variants else "INCOMPLETE",
        "script": namespace.script,
        "variants": variants,
        "profile_alias": namespace.profile_alias,
    }
