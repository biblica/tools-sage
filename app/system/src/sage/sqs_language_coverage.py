"""SAGE-side echo of the language onboarding consistency check (integration
plan Task 6, symmetric to Task 1b's SQS-side check in
services/sqs/src/sage_sqs/language_coverage.py).

Both sides read the same two real sources of truth (SAGE's own grammar
profile registry, and the shared coverage manifest) rather than depending
on each other's Python package -- a SAGE-only contributor who never runs
the SQS test suite still catches onboarding drift here, and vice versa.

NOTE on the sibling-repo split (architecture spec decision 4): this reads
the shared manifest via a relative path into services/sqs, assuming
colocation in this repository, same caveat as sqs_provider_coverage.py.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
_COVERAGE_MANIFEST_PATH = _REPO_ROOT / "services" / "sqs" / "config" / "language-coverage-status.yml"
_SAGE_GRAMMAR_PROFILES_DIR = _REPO_ROOT / "app" / "system" / "config" / "profiles" / "grammar"

_VALID_SAGE_STATUSES = {"ONBOARDED", "SAGE_ONLY_UNASSESSED"}


def load_coverage_manifest(path: str | Path | None = None) -> dict[str, dict]:
    """Load the shared language-coverage manifest (see language_coverage.py's format)."""
    manifest_path = Path(path) if path is not None else _COVERAGE_MANIFEST_PATH
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Shared language-coverage manifest not found at {manifest_path}. "
            "If services/sqs has been split into its own repository, this check "
            "needs a different mechanism than a relative filesystem path -- see "
            "the module docstring."
        )
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return dict(payload.get("profiles") or {})


def sage_grammar_profile_ids(directory: str | Path | None = None) -> frozenset[str]:
    """Return every language profile id in SAGE's own grammar-profile registry."""
    grammar_dir = Path(directory) if directory is not None else _SAGE_GRAMMAR_PROFILES_DIR
    return frozenset(entry.name for entry in grammar_dir.iterdir() if entry.is_dir())


def check_language_onboarding_consistency(
    *, manifest_path: str | Path | None = None, grammar_profiles_dir: str | Path | None = None,
) -> list[str]:
    """Return SAGE-side language onboarding violations: every profile must have a recorded status."""
    manifest = load_coverage_manifest(manifest_path)
    violations: list[str] = []
    for profile_id in sorted(sage_grammar_profile_ids(grammar_profiles_dir)):
        entry = manifest.get(profile_id)
        if entry is None:
            violations.append(
                f"{profile_id}: exists as a SAGE grammar profile but has no entry in the shared "
                "language-coverage manifest -- adding a profile requires recording its SQS status (Task 1b)"
            )
            continue
        status = entry.get("status")
        if status not in _VALID_SAGE_STATUSES:
            violations.append(f"{profile_id}: manifest status '{status}' is not valid for a SAGE profile")
    return violations
