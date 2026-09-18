from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from sage_sqs.db import Database
from sage_sqs.publisher import Publisher, verify_bundle_signature
from sage_sqs.repository import Repository
from test_publication_boundary import _seed


def test_publisher_can_sign_bundle_with_ed25519(tmp_path: Path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    _seed(repo)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    publisher = Publisher(
        repo,
        authority_id="biblica-sqs-production",
        publication_epoch=1,
        output_paths=(),
        signing_private_key=private,
        signing_key_id="prod-2026-01",
    )
    bundle = publisher.publish(actor="ADMIN")
    assert bundle["signature_algorithm"] == "Ed25519"
    assert bundle["signing_key_id"] == "prod-2026-01"
    assert bundle["signature_ed25519"]
    assert verify_bundle_signature(bundle, {"prod-2026-01": base64.b64encode(public).decode("ascii")}) is True


def test_signature_verification_detects_tampering(tmp_path: Path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    _seed(repo)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    bundle = Publisher(
        repo,
        authority_id="biblica-sqs-production",
        publication_epoch=1,
        output_paths=(),
        signing_private_key=private,
        signing_key_id="prod-2026-01",
    ).publish(actor="ADMIN")
    bundle["bundle_revision"] += 1
    assert verify_bundle_signature(bundle, {"prod-2026-01": base64.b64encode(public).decode("ascii")}) is False
