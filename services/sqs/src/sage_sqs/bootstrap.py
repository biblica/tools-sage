"""First-run SQS catalog bootstrap from frozen seed inputs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .profile_builder import load_seed_profiles
from .providers.openai_provider import load_openai_catalog, sync_provider_catalog
from .repository import Repository


@dataclass(frozen=True)
class BootstrapResult:
    profiles_created: int
    models_created: int


def bootstrap_catalog(repo: Repository, *, language_dir: Path, provider_catalog: Path) -> BootstrapResult:
    profiles_created = 0
    for draft in load_seed_profiles(language_dir):
        if repo.latest_profile(draft.profile_id) is not None:
            continue
        repo.save_profile(draft.profile)
        profiles_created += 1
        repo.upsert_attention(
            attention_key=f"PROFILE_REVIEW:{draft.profile_id}:{draft.revision}",
            category="PROFILE_REVIEW",
            severity="INFO" if not draft.issues else "MEDIUM",
            summary="Language evaluation profile requires ADMIN review",
            payload={
                "profile_id": draft.profile_id,
                "revision": draft.revision,
                "issues": [{"code": issue.code, "message": issue.message} for issue in draft.issues],
            },
        )

    catalog = load_openai_catalog(provider_catalog)
    missing_before = sum(1 for model in catalog if repo.latest_model(model.provider_family, model.model_id) is None)
    sync_provider_catalog(repo, catalog)
    return BootstrapResult(profiles_created=profiles_created, models_created=missing_before)


def bootstrap_from_config(repo: Repository, config_root: Path) -> BootstrapResult:
    """Bootstrap from the deployed config layout when the catalog files exist."""
    language_dir = Path(config_root) / "languages"
    provider_catalog = Path(config_root) / "openai-provider.yml"
    if not language_dir.is_dir() or not provider_catalog.is_file():
        return BootstrapResult(profiles_created=0, models_created=0)
    return bootstrap_catalog(repo, language_dir=language_dir, provider_catalog=provider_catalog)
