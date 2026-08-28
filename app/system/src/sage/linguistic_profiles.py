"""Canonical resolution of complete governed natural-language profile contracts."""

from __future__ import annotations

from typing import Any

from .errors import ConfigurationError, ValidationError
from .grammar import GrammarProfile, load_grammar_profile
from .grammar_governance import active_grammar_review, grammar_profile_is_approved
from .registry import EcosystemConfig


def complete_language_profile_contract(
    config: EcosystemConfig,
    language_tag: str,
) -> tuple[GrammarProfile, dict[str, Any]]:
    """Resolve one unambiguous complete LANGUAGE_PROFILE contract for a language stream."""
    try:
        namespace = config.language_profile(language_tag)
    except ConfigurationError as exc:
        raise ValidationError(
            f"Language stream {language_tag} has no canonical LANGUAGE_PROFILE namespace",
            code="LINGUISTIC_PROFILE_MISSING",
        ) from exc
    variants = tuple(namespace.variants.values())
    if not variants:
        raise ValidationError(
            f"Language stream {language_tag} has no canonical LANGUAGE_PROFILE variant",
            code="LINGUISTIC_PROFILE_MISSING",
        )
    if len(variants) != 1:
        raise ValidationError(
            f"Language stream {language_tag} has multiple canonical LANGUAGE_PROFILE variants",
            code="LINGUISTIC_PROFILE_AMBIGUOUS",
            details={
                "language": language_tag,
                "variants": sorted(item.variant_id for item in variants),
            },
        )
    spec = variants[0]
    profile = load_grammar_profile(
        spec.path,
        expected_profile_id=spec.variant_id,
        expected_language=namespace.profile_language,
        expected_role=spec.role,
    )
    if profile.status == "INACTIVE":
        raise ValidationError(
            f"LANGUAGE_PROFILE {profile.language}/{profile.profile_id} is INACTIVE",
            code="GRAMMAR_PROFILE_INACTIVE",
        )
    contract = profile.contract()
    contract["governance_review"] = active_grammar_review(config, profile)
    contract["effective_status"] = (
        "ACTIVE" if grammar_profile_is_approved(config, profile) else profile.status
    )
    return profile, contract
