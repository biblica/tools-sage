"""Read-only SQS qualification lookup: QUALIFIED/NOT_QUALIFIED/UNASSESSED over a validated cache."""
from __future__ import annotations

from pathlib import Path

from sage.sqs_cache import SqsCache, canonical_bundle_sha256
from sage.sqs_qualification import lookup_qualification

_ROUTE = dict(provider_family="openai", model_id="gpt-x", profile_id="sw-KE", capability="GRAMMAR_ANALYSIS")


def _bundle(*, qualifications: list[dict]) -> dict:
    """Build a minimal, digest-correct bundle carrying the given qualification rows."""
    bundle = {
        "schema_version": "1.1",
        "service_version": "0.02a1",
        "authority_id": "biblica-sqs-production",
        "publication_epoch": 1,
        "bundle_revision": 1,
        "generated_at": "2026-09-18T00:00:00Z",
        "profiles": [],
        "models": [],
        "qualifications": qualifications,
        "bundle_sha256": "",
    }
    bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)
    return bundle


def _qualification(*, status: str, execution_channel: str = "codex_workspace", minimum_reasoning: str | None = "medium") -> dict:
    """Build one qualification row for _ROUTE with the given status."""
    return {**_ROUTE, "execution_channel": execution_channel, "status": status, "minimum_reasoning": minimum_reasoning, "evaluated_at": "2026-09-18T00:00:00Z"}


def _cache(tmp_path: Path) -> SqsCache:
    """Build an SqsCache rooted at tmp_path, trusting the standard test authority."""
    return SqsCache(tmp_path, trusted_authority_id="biblica-sqs-production")


def test_unassessed_when_no_bundle_has_ever_been_cached(tmp_path: Path):
    """With no cached bundle at all, the route is UNASSESSED, not an error."""
    result = lookup_qualification(_cache(tmp_path), **_ROUTE)
    assert result.status == "UNASSESSED"


def test_unassessed_when_bundle_exists_but_route_is_not_in_it(tmp_path: Path):
    """A cached bundle that simply doesn't mention this route reports UNASSESSED."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(qualifications=[]))
    result = lookup_qualification(cache, **_ROUTE)
    assert result.status == "UNASSESSED"


def test_qualified_route_reports_minimum_reasoning_and_channel(tmp_path: Path):
    """A QUALIFIED row surfaces its minimum_reasoning and the execution_channel that produced it."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(qualifications=[_qualification(status="QUALIFIED")]))
    result = lookup_qualification(cache, **_ROUTE)
    assert result.status == "QUALIFIED"
    assert result.minimum_reasoning == "medium"
    assert result.execution_channel == "codex_workspace"


def test_not_qualified_route_blocks_via_tombstone_even_if_bundle_row_is_absent(tmp_path: Path):
    """A durable negative tombstone reports NOT_QUALIFIED even without re-reading the bundle row."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(qualifications=[_qualification(status="NOT_QUALIFIED", minimum_reasoning=None)]))
    result = lookup_qualification(cache, **_ROUTE)
    assert result.status == "NOT_QUALIFIED"
    assert result.minimum_reasoning is None


def test_explicit_positive_requalification_is_visible_after_a_prior_denial(tmp_path: Path):
    """After an explicit newer QUALIFIED row clears a tombstone, lookup reports QUALIFIED again."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(qualifications=[_qualification(status="NOT_QUALIFIED", minimum_reasoning=None)]))
    assert lookup_qualification(cache, **_ROUTE).status == "NOT_QUALIFIED"

    requalified = dict(_bundle(qualifications=[_qualification(status="QUALIFIED")]))
    requalified["bundle_revision"] = 2
    requalified["bundle_sha256"] = ""
    requalified["bundle_sha256"] = canonical_bundle_sha256(requalified)
    cache.accept_bundle(requalified)
    assert lookup_qualification(cache, **_ROUTE).status == "QUALIFIED"


def test_lookup_does_not_match_a_different_execution_channel_as_a_different_route(tmp_path: Path):
    """execution_channel is provenance, not part of route identity -- lookup ignores it entirely."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(qualifications=[_qualification(status="QUALIFIED", execution_channel="some_future_channel")]))
    result = lookup_qualification(cache, **_ROUTE)
    assert result.status == "QUALIFIED"
    assert result.execution_channel == "some_future_channel"
