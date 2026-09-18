"""SQS-backed QualificationEvidenceRepository: extension seam, not wired into live routing."""
from __future__ import annotations

from pathlib import Path

import pytest

from sage.sqs_cache import SqsCache, canonical_bundle_sha256
from sage.sqs_evidence_repository import SqsQualificationEvidenceRepository


def _cache(tmp_path: Path) -> SqsCache:
    """Build an SqsCache rooted at tmp_path, trusting the standard test authority."""
    return SqsCache(tmp_path, trusted_authority_id="biblica-sqs-production")


def _bundle_with_a_qualified_route() -> dict:
    """Build a bundle carrying one real QUALIFIED row, to prove that data is deliberately ignored."""
    bundle = {
        "schema_version": "1.1",
        "service_version": "0.02a1",
        "authority_id": "biblica-sqs-production",
        "publication_epoch": 1,
        "bundle_revision": 1,
        "generated_at": "2026-09-18T00:00:00Z",
        "profiles": [],
        "models": [],
        "qualifications": [{
            "provider_family": "openai",
            "execution_channel": "codex_workspace",
            "model_id": "gpt-x",
            "profile_id": "sw-KE",
            "capability": "GRAMMAR_ANALYSIS",
            "status": "QUALIFIED",
            "minimum_reasoning": "medium",
            "evaluated_at": "2026-09-18T00:00:00Z",
        }],
        "bundle_sha256": "",
    }
    bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)
    return bundle


def test_plugs_into_the_real_skill_routing_evidence_repository_seam(tmp_path: Path, make_workspace):
    """qualified_skill_routes accepts this class through its real evidence_repository= seam.

    Against a real registered Skill and no live provider statuses, it behaves
    exactly like an empty built-in repository would -- a clean
    NO_QUALIFIED_SKILL_ROUTE, never a shape/compatibility error.
    """
    from sage.errors import ValidationError
    from sage.skill_routing import qualified_skill_routes

    root = make_workspace()
    repository = SqsQualificationEvidenceRepository(cache=_cache(tmp_path))
    with pytest.raises(ValidationError) as excinfo:
        qualified_skill_routes(root, "bic-inspect", [], evidence_repository=repository)
    assert excinfo.value.code == "NO_QUALIFIED_SKILL_ROUTE"


def test_always_returns_no_records_even_with_real_qualified_evidence_cached(tmp_path: Path):
    """A real QUALIFIED SQS route in the cache still yields no records -- not a temporary gap, see module docstring."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle_with_a_qualified_route())
    repository = SqsQualificationEvidenceRepository(cache=cache)
    assert repository.records_for_skill("bic-inspect") == []
    assert repository.records_for_skill("nca-numbers") == []


def test_returns_no_records_for_an_unknown_skill_id(tmp_path: Path):
    """An unregistered or nonexistent skill_id behaves identically -- always empty."""
    repository = SqsQualificationEvidenceRepository(cache=_cache(tmp_path))
    assert repository.records_for_skill("not-a-real-skill") == []
