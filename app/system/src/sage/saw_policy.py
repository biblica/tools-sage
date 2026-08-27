"""Beta SAW RTC check selection and USFM-context policy."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from .atomic import atomic_write_json
from .errors import ValidationError

POLICY_MODES = {"NORMAL", "MATERIAL_ONLY", "STRUCTURE_ONLY"}
DEFAULT_CHECKS = {
    "structure_completeness": True,
    "translation_meaning": True,
    "language_readability": True,
    "consistency": True,
}
DEFAULT_CONTEXTS = {
    "add": "MATERIAL_ONLY",
    "nd": "MATERIAL_ONLY",
    "f": "STRUCTURE_ONLY",
    "x": "NORMAL",
}
OL_DRIFT_STATES = {"PROHIBITED", "ENABLED"}
DEFAULT_ORIGINAL_LANGUAGE = {"source_text_drift_adjudication": "PROHIBITED"}


def default_rtc_policy(profile_path: Path | None = None) -> dict[str, Any]:
    """Load governed RTC defaults, falling back to compiled Beta defaults."""
    checks = dict(DEFAULT_CHECKS)
    contexts = dict(DEFAULT_CONTEXTS)
    version = "1.0"
    original_language = dict(DEFAULT_ORIGINAL_LANGUAGE)
    if profile_path and profile_path.is_file():
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8-sig")) or {}
        section = dict(raw.get("check_policy") or {}).get("rtc") or {}
        version = str(dict(raw.get("check_policy") or {}).get("version") or version)
        checks.update({str(k): bool(v) for k, v in dict(section.get("checks") or {}).items() if k in checks})
        for key, value in dict(section.get("usfm_contexts") or {}).items():
            mode = str(dict(value).get("mode") if isinstance(value, dict) else value).upper()
            if mode in POLICY_MODES and str(key).lstrip("\\") in contexts:
                contexts[str(key).lstrip("\\")] = mode
        ol_section = dict(section.get("original_language") or {})
        drift = str(ol_section.get("source_text_drift_adjudication") or original_language["source_text_drift_adjudication"]).upper()
        if drift in OL_DRIFT_STATES:
            original_language["source_text_drift_adjudication"] = drift
    return {
        "policy_version": version,
        "checks": checks,
        "usfm_contexts": contexts,
        "original_language": original_language,
    }


def validate_rtc_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one effective RTC policy and reject ambiguous modes."""
    checks = dict(DEFAULT_CHECKS)
    checks.update({str(k): bool(v) for k, v in dict(policy.get("checks") or {}).items() if k in checks})
    contexts = dict(DEFAULT_CONTEXTS)
    for key, value in dict(policy.get("usfm_contexts") or {}).items():
        normalized_key = str(key).lstrip("\\")
        if normalized_key not in contexts:
            continue
        mode = str(value).upper()
        if mode not in POLICY_MODES:
            raise ValidationError(f"Unsupported SAW text policy mode: {value}", code="SAW_POLICY_MODE_INVALID")
        contexts[normalized_key] = mode
    original_language = dict(DEFAULT_ORIGINAL_LANGUAGE)
    ol_value = dict(policy.get("original_language") or {}).get("source_text_drift_adjudication")
    if ol_value is not None:
        drift = str(ol_value).upper()
        if drift not in OL_DRIFT_STATES:
            raise ValidationError(
                f"Unsupported SAW original-language policy state: {ol_value}",
                code="SAW_OL_POLICY_INVALID",
            )
        original_language["source_text_drift_adjudication"] = drift
    return {
        "policy_version": str(policy.get("policy_version") or "1.0"),
        "checks": checks,
        "usfm_contexts": contexts,
        "original_language": original_language,
    }


def should_elevate(*, mode: str, category: str, material: bool, structural: bool) -> bool:
    """Return whether a detected issue becomes a finding; never alter its severity."""
    mode = str(mode).upper()
    if mode == "NORMAL":
        return True
    if mode == "MATERIAL_ONLY":
        return structural or material
    if mode == "STRUCTURE_ONLY":
        return structural
    raise ValidationError(f"Unsupported SAW text policy mode: {mode}", code="SAW_POLICY_MODE_INVALID")


def load_run_policy_snapshot(run_root: Path, *, profile_path: Path | None = None) -> dict[str, Any]:
    """Load one immutable Run policy snapshot, or the governed defaults when absent."""
    path = run_root / "check-policy.json"
    if not path.is_file():
        return default_rtc_policy(profile_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("Run check-policy snapshot is invalid", code="SAW_POLICY_INVALID") from exc
    if not isinstance(raw, dict):
        raise ValidationError("Run check-policy snapshot must contain an object", code="SAW_POLICY_INVALID")
    return validate_rtc_policy(raw)


def write_run_policy_snapshot(run_root: Path, policy: Mapping[str, Any]) -> Path:
    """Persist an immutable effective policy snapshot inside one Run."""
    normalized = validate_rtc_policy(policy)
    path = run_root / "check-policy.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != normalized:
            raise ValidationError("Run check-policy snapshot is immutable", code="SAW_POLICY_IMMUTABLE")
        return path
    atomic_write_json(path, normalized)
    return path
