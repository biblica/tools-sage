import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sage_sqs.db import Database
from sage_sqs.publisher import main, verify_bundle_signature
from sage_sqs.repository import Repository


def test_publish_cli_writes_exact_replicas_and_signature(tmp_path, monkeypatch):
    db_path = tmp_path / "sqs.db"
    Repository(Database.open(db_path))
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "signing.pem"
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    first = tmp_path / "a" / "bundle.json"
    second = tmp_path / "b" / "bundle.json"
    monkeypatch.setenv("SQS_DB_PATH", str(db_path))
    monkeypatch.setenv("SQS_AUTHORITY_ID", "biblica-sqs-production")
    monkeypatch.setenv("SQS_PUBLICATION_EPOCH", "1")
    monkeypatch.setenv("SQS_BUNDLE_PATHS", f"{first},{second}")
    monkeypatch.setenv("SQS_SIGNING_PRIVATE_KEY", str(key_path))
    monkeypatch.setenv("SQS_SIGNING_KEY_ID", "prod-1")

    assert main([]) == 0
    assert first.read_bytes() == second.read_bytes()
    bundle = json.loads(first.read_text(encoding="utf-8"))
    public_raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    assert verify_bundle_signature(bundle, {"prod-1": base64.b64encode(public_raw).decode("ascii")})
