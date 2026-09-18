"""Bundle-consumer-side hardening for SQS cache acceptance (integration plan Task 3)."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sage.sqs_cache import (
    SqsBundleRejected,
    SqsCache,
    canonical_bundle_sha256,
    verify_bundle_signature,
)


def _bundle(*, epoch: int = 1, revision: int = 1, authority_id: str = "biblica-sqs-production",
            qualifications: list[dict] | None = None) -> dict:
    """Build a minimal, digest-correct unsigned bundle for cache-acceptance tests."""
    bundle = {
        "schema_version": "1.1",
        "service_version": "0.02a1",
        "authority_id": authority_id,
        "publication_epoch": epoch,
        "bundle_revision": revision,
        "generated_at": "2026-09-18T00:00:00Z",
        "profiles": [],
        "models": [],
        "qualifications": qualifications or [],
        "bundle_sha256": "",
    }
    bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)
    return bundle


def _qualification(*, status: str, provider_family="openai", model_id="gpt-x", profile_id="sw-KE", capability="GRAMMAR_ANALYSIS") -> dict:
    """Build one qualification row for embedding in a test bundle."""
    return {
        "provider_family": provider_family,
        "execution_channel": "codex_workspace",
        "model_id": model_id,
        "profile_id": profile_id,
        "capability": capability,
        "status": status,
    }


def _cache(tmp_path: Path, **kwargs) -> SqsCache:
    """Build an SqsCache rooted at tmp_path, trusting the standard test authority."""
    return SqsCache(tmp_path, trusted_authority_id="biblica-sqs-production", **kwargs)


def test_accepts_a_valid_first_bundle(tmp_path: Path):
    """A digest-correct, trusted-authority bundle is accepted as current."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle())
    assert cache.load_current()["bundle_revision"] == 1


def test_rejects_a_bundle_with_a_tampered_digest(tmp_path: Path):
    """A bundle whose claimed digest does not match its content is rejected and never cached."""
    cache = _cache(tmp_path)
    bundle = _bundle()
    bundle["bundle_sha256"] = "0" * 64
    with pytest.raises(SqsBundleRejected) as excinfo:
        cache.accept_bundle(bundle)
    assert excinfo.value.code == "SQS_BUNDLE_DIGEST_MISMATCH"
    assert cache.load_current() is None


def test_rejects_untrusted_authority(tmp_path: Path):
    """A structurally valid bundle from an authority_id we do not trust is rejected."""
    cache = _cache(tmp_path)
    bundle = _bundle(authority_id="some-other-authority")
    with pytest.raises(SqsBundleRejected) as excinfo:
        cache.accept_bundle(bundle)
    assert excinfo.value.code == "SQS_BUNDLE_UNTRUSTED_AUTHORITY"


def test_rejects_rollback_to_an_older_revision(tmp_path: Path):
    """A bundle with a lower revision than the cached one is rejected as a rollback."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(revision=5))
    with pytest.raises(SqsBundleRejected) as excinfo:
        cache.accept_bundle(_bundle(revision=3))
    assert excinfo.value.code == "SQS_BUNDLE_ROLLBACK_REJECTED"
    assert cache.load_current()["bundle_revision"] == 5


def test_rejects_rollback_to_an_older_epoch_even_with_higher_revision(tmp_path: Path):
    """Epoch takes priority over revision: a lower epoch is a rollback regardless of revision."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(epoch=2, revision=1))
    with pytest.raises(SqsBundleRejected):
        cache.accept_bundle(_bundle(epoch=1, revision=999))
    assert cache.load_current()["publication_epoch"] == 2


def test_current_and_previous_generation_rotate(tmp_path: Path):
    """Accepting a second bundle rotates the first into the previous-generation slot."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(revision=1))
    cache.accept_bundle(_bundle(revision=2))
    assert cache.load_current()["bundle_revision"] == 2
    assert cache._read_generation(cache._previous_path)["bundle_revision"] == 1


def test_rollback_floor_survives_a_missing_current_generation(tmp_path: Path):
    """A missing/corrupt current generation must not lower the rollback floor
    to "accept anything" -- it must fall back to the previous generation.
    Losing `current` legitimately lowers the floor to whatever `previous`
    still holds (there is no way to recover a fact recorded nowhere at all);
    the guarantee is that it never drops further, to "no floor recorded"."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(revision=1))
    cache.accept_bundle(_bundle(revision=5))
    cache._current_path.unlink()  # simulate a lost/corrupt current file

    with pytest.raises(SqsBundleRejected) as excinfo:
        cache.accept_bundle(_bundle(revision=1))  # no better than the surviving previous generation
    assert excinfo.value.code == "SQS_BUNDLE_ROLLBACK_REJECTED"

    cache.accept_bundle(_bundle(revision=3))  # genuinely newer than the surviving previous=1 -- correctly accepted
    assert cache.load_current()["bundle_revision"] == 3


def test_corrupt_current_file_is_treated_as_absent_not_as_a_crash(tmp_path: Path):
    """A corrupt current-generation file degrades to 'no cache', never an exception."""
    cache = _cache(tmp_path)
    cache._current_path.parent.mkdir(parents=True, exist_ok=True)
    cache._current_path.write_text("{not valid json", encoding="utf-8")
    assert cache.load_current() is None
    assert cache.rollback_floor() is None
    cache.accept_bundle(_bundle())  # must not raise despite the corrupt sibling file
    assert cache.load_current()["bundle_revision"] == 1


def test_negative_tombstone_persists_across_a_later_stale_or_missing_positive_cache(tmp_path: Path):
    """A later bundle that simply omits a NOT_QUALIFIED row must not clear its tombstone."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(revision=1, qualifications=[_qualification(status="NOT_QUALIFIED")]))
    assert cache.is_denied(provider_family="openai", model_id="gpt-x", profile_id="sw-KE", capability="GRAMMAR_ANALYSIS")

    # A later bundle that simply omits this qualification (e.g. cache went
    # stale/unavailable) must NOT clear the tombstone.
    cache.accept_bundle(_bundle(revision=2, qualifications=[]))
    assert cache.is_denied(provider_family="openai", model_id="gpt-x", profile_id="sw-KE", capability="GRAMMAR_ANALYSIS")


def test_negative_tombstone_survives_current_generation_deletion(tmp_path: Path):
    """Tombstones are durable independent of the normal cache -- deleting the
    current bundle file must not resurrect provisional eligibility."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(qualifications=[_qualification(status="NOT_QUALIFIED")]))
    cache._current_path.unlink()
    cache._previous_path.unlink(missing_ok=True)
    assert cache.load_current() is None
    assert cache.is_denied(provider_family="openai", model_id="gpt-x", profile_id="sw-KE", capability="GRAMMAR_ANALYSIS")


def test_explicit_newer_positive_requalification_clears_a_tombstone(tmp_path: Path):
    """An explicit newer QUALIFIED row for the same route clears its prior tombstone."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(revision=1, qualifications=[_qualification(status="NOT_QUALIFIED")]))
    assert cache.is_denied(provider_family="openai", model_id="gpt-x", profile_id="sw-KE", capability="GRAMMAR_ANALYSIS")
    cache.accept_bundle(_bundle(revision=2, qualifications=[_qualification(status="QUALIFIED")]))
    assert not cache.is_denied(provider_family="openai", model_id="gpt-x", profile_id="sw-KE", capability="GRAMMAR_ANALYSIS")


def test_crash_between_tombstone_commit_and_generation_commit_fails_closed(tmp_path: Path, monkeypatch):
    """Simulate a crash after the tombstone file is durably written but before
    the new generation is rotated in. On 'recovery' (just re-reading state),
    the tombstone must already be in effect even though current is still old."""
    cache = _cache(tmp_path)
    cache.accept_bundle(_bundle(revision=1))  # establish an initial generation

    def _crash_before_rotate(candidate):
        """Stand in for _rotate_in to simulate a crash right before it would run."""
        raise RuntimeError("simulated crash between tombstone commit and generation commit")

    monkeypatch.setattr(cache, "_rotate_in", _crash_before_rotate)
    with pytest.raises(RuntimeError):
        cache.accept_bundle(_bundle(revision=2, qualifications=[_qualification(status="NOT_QUALIFIED")]))

    # "Recovery": a fresh SqsCache instance over the same state_dir.
    recovered = _cache(tmp_path)
    assert recovered.load_current()["bundle_revision"] == 1  # generation commit never happened
    assert recovered.is_denied(provider_family="openai", model_id="gpt-x", profile_id="sw-KE", capability="GRAMMAR_ANALYSIS")  # but tombstone did


def test_signature_required_rejects_unsigned_bundle(tmp_path: Path):
    """When signature enforcement is on, an unsigned bundle is rejected outright."""
    cache = _cache(tmp_path, require_signature=True)
    with pytest.raises(SqsBundleRejected) as excinfo:
        cache.accept_bundle(_bundle())
    assert excinfo.value.code == "SQS_BUNDLE_SIGNATURE_REQUIRED"


def _signed_bundle(private_key: Ed25519PrivateKey, *, key_id: str = "key-1", **bundle_kwargs) -> dict:
    """Build a bundle the way the real Publisher does: signature metadata is
    part of the content that gets hashed into bundle_sha256, and the
    signature itself is computed over that same canonical content afterward."""
    from sage.sqs_cache import canonical_bundle_bytes

    bundle = {
        "schema_version": "1.1",
        "service_version": "0.02a1",
        "authority_id": "biblica-sqs-production",
        "publication_epoch": 1,
        "bundle_revision": 1,
        "generated_at": "2026-09-18T00:00:00Z",
        "profiles": [],
        "models": [],
        "qualifications": [],
        "bundle_sha256": "",
        "signature_algorithm": "Ed25519",
        "signing_key_id": key_id,
    }
    bundle.update(bundle_kwargs)
    bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)
    bundle["signature_ed25519"] = base64.b64encode(private_key.sign(canonical_bundle_bytes(bundle))).decode("ascii")
    return bundle


def test_valid_signature_is_accepted_and_tampering_is_rejected(tmp_path: Path):
    """A correctly signed bundle is accepted; the same content re-signed after tampering is not."""
    from cryptography.hazmat.primitives import serialization

    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    encoded_public = base64.b64encode(public_bytes).decode("ascii")
    bundle = _signed_bundle(private_key)
    trusted_keys = {"key-1": encoded_public}
    assert verify_bundle_signature(bundle, trusted_keys)

    cache = _cache(tmp_path, trusted_signing_keys=trusted_keys, require_signature=True)
    cache.accept_bundle(bundle)  # does not raise

    tampered = dict(bundle)
    tampered["bundle_revision"] = 999
    tampered["bundle_sha256"] = canonical_bundle_sha256(tampered)  # digest recomputed to match tamper
    # signature is now stale relative to the tampered content
    with pytest.raises(SqsBundleRejected) as excinfo:
        SqsCache(tmp_path / "other", trusted_authority_id="biblica-sqs-production", trusted_signing_keys=trusted_keys, require_signature=True).accept_bundle(tampered)
    assert excinfo.value.code == "SQS_BUNDLE_SIGNATURE_INVALID"
