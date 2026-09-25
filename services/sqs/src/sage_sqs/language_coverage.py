"""Cross-catalog language onboarding consistency: SAGE's grammar-profile
registry vs. SQS's seeded qualification languages, reconciled against an
explicit, checked-in coverage manifest.

This is the language-side counterpart to execution_channels.py's provider
consistency check (SQS integration plan Task 1b, symmetric to Task 1). It
does not author any language content -- evaluation packs and grammar
profiles require linguistic subject-matter review, not fabrication. It only
enforces that every profile known to either side has an explicitly recorded
status, so drift is caught, not silent.

NOTE on the sibling-repo split (architecture spec decision 4): this reads
SAGE's grammar-profile directory via a relative path assuming services/sqs
is still colocated in the same repository as app/. Once SQS moves to its
own repository, this check needs a different mechanism (e.g. SAGE exporting
a checked-in profile-id list, or a live registry query) -- it is not meant
to survive that split unchanged.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SAGE_GRAMMAR_PROFILES_DIR = _REPO_ROOT / "app" / "system" / "config" / "profiles" / "grammar"


def load_coverage_manifest(path: str | Path) -> dict[str, dict]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return dict(payload.get("profiles") or {})


def sqs_seeded_language_ids(seed_languages_dir: str | Path) -> set[str]:
    return {path.stem for path in Path(seed_languages_dir).glob("*.yml")}


def sage_grammar_profile_ids(sage_grammar_profiles_dir: str | Path | None = None) -> set[str]:
    directory = Path(sage_grammar_profiles_dir) if sage_grammar_profiles_dir is not None else _SAGE_GRAMMAR_PROFILES_DIR
    if not directory.is_dir():
        raise FileNotFoundError(
            f"SAGE grammar-profile directory not found at {directory}. "
            "If services/sqs has been split into its own repository, this check "
            "needs a different mechanism than a relative filesystem path -- see "
            "the module docstring."
        )
    return {entry.name for entry in directory.iterdir() if entry.is_dir()}


def check_language_onboarding_consistency(
    *,
    manifest_path: str | Path,
    seed_languages_dir: str | Path,
    sage_grammar_profiles_dir: str | Path | None = None,
) -> list[str]:
    """Return a list of onboarding-coordination violations (empty means consistent)."""
    manifest = load_coverage_manifest(manifest_path)
    sqs_ids = sqs_seeded_language_ids(seed_languages_dir)
    sage_ids = sage_grammar_profile_ids(sage_grammar_profiles_dir)
    violations: list[str] = []

    for profile_id in sorted(sqs_ids):
        entry = manifest.get(profile_id)
        if entry is None:
            violations.append(
                f"{profile_id}: seeded in SQS but has no entry in the coverage manifest "
                "-- onboarding a language into SQS requires recording its status"
            )
            continue
        status = entry.get("status")
        if status == "ONBOARDED" and profile_id not in sage_ids:
            violations.append(
                f"{profile_id}: manifest says ONBOARDED but no matching SAGE grammar profile exists "
                "-- the SAGE profile may have been removed without updating the manifest"
            )
        elif status not in {"ONBOARDED", "SQS_ONLY_PENDING_SAGE_PROFILE"}:
            violations.append(f"{profile_id}: seeded in SQS but manifest status '{status}' is not valid for an SQS-seeded language")

    for profile_id in sorted(sage_ids):
        entry = manifest.get(profile_id)
        if entry is None:
            violations.append(
                f"{profile_id}: exists as a SAGE grammar profile but has no entry in the coverage manifest "
                "-- adding a language profile requires recording its SQS coverage status (Task 1b)"
            )
            continue
        status = entry.get("status")
        if status == "ONBOARDED" and profile_id not in sqs_ids:
            violations.append(
                f"{profile_id}: manifest says ONBOARDED but no matching SQS seed language exists "
                "-- the SQS seed may have been removed without updating the manifest"
            )
        elif status not in {"ONBOARDED", "SAGE_ONLY_UNASSESSED"}:
            violations.append(f"{profile_id}: exists as a SAGE grammar profile but manifest status '{status}' is not valid for a SAGE profile")

    for profile_id in sorted(manifest):
        if profile_id not in sqs_ids and profile_id not in sage_ids:
            violations.append(f"{profile_id}: recorded in the coverage manifest but exists in neither catalog -- stale entry, should be removed")

    return violations
