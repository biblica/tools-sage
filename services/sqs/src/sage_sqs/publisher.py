"""Explicit SQS publication, Ed25519 signing, and static replica writer."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import argparse
import os

from cryptography.hazmat.primitives import serialization
from typing import Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .repository import Repository


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_bundle_bytes(bundle: Mapping[str, object]) -> bytes:
    value = dict(bundle)
    value.pop("bundle_sha256", None)
    value.pop("signature_ed25519", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_bundle_sha256(bundle: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_bundle_bytes(bundle)).hexdigest()


def verify_bundle_signature(bundle: Mapping[str, object], trusted_keys: Mapping[str, str]) -> bool:
    """Verify one Ed25519 publication against a key-id -> base64 raw public key mapping."""
    if bundle.get("signature_algorithm") != "Ed25519":
        return False
    key_id = str(bundle.get("signing_key_id") or "")
    encoded_key = trusted_keys.get(key_id)
    signature = str(bundle.get("signature_ed25519") or "")
    if not encoded_key or not signature:
        return False
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded_key, validate=True))
        public.verify(base64.b64decode(signature, validate=True), canonical_bundle_bytes(bundle))
    except (ValueError, InvalidSignature):
        return False
    return True


class Publisher:
    def __init__(
        self,
        repo: Repository,
        *,
        authority_id: str,
        publication_epoch: int,
        output_paths: Iterable[Path],
        signing_private_key: Ed25519PrivateKey | None = None,
        signing_key_id: str | None = None,
    ):
        if not authority_id.strip():
            raise ValueError("authority_id is required")
        if publication_epoch < 1:
            raise ValueError("publication_epoch must be positive")
        if (signing_private_key is None) != (signing_key_id is None):
            raise ValueError("signing key and signing_key_id must be supplied together")
        self.repo = repo
        self.authority_id = authority_id
        self.publication_epoch = publication_epoch
        self.output_paths = tuple(output_paths)
        self.signing_private_key = signing_private_key
        self.signing_key_id = signing_key_id

    def publish(self, *, actor: str) -> dict:
        profiles = self.repo.active_profiles()
        models = self.repo.approved_models()
        qualifications = self.repo.publishable_qualifications()
        bundle = {
            "schema_version": "1.1",
            "service_version": "0.02a1",
            "authority_id": self.authority_id,
            "publication_epoch": self.publication_epoch,
            "bundle_revision": self.repo.next_bundle_revision(),
            "generated_at": _utc_now(),
            "profiles": [profile.public_dict() for profile in profiles],
            "models": [model.public_dict() for model in models],
            "qualifications": [qualification.public_dict() for qualification in qualifications],
            "bundle_sha256": "",
        }
        if self.signing_private_key is not None:
            bundle["signature_algorithm"] = "Ed25519"
            bundle["signing_key_id"] = str(self.signing_key_id)
        bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)
        if self.signing_private_key is not None:
            signature = self.signing_private_key.sign(canonical_bundle_bytes(bundle))
            bundle["signature_ed25519"] = base64.b64encode(signature).decode("ascii")
        self.repo.store_bundle(bundle)
        self.repo.audit(actor, "PUBLISH_BUNDLE", {
            "bundle_revision": bundle["bundle_revision"],
            "bundle_sha256": bundle["bundle_sha256"],
            "authority_id": self.authority_id,
            "publication_epoch": self.publication_epoch,
            "signing_key_id": self.signing_key_id,
        })
        payload = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for path in self.output_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
        return bundle


def _load_signing_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("SQS signing key must be Ed25519")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the current SQS evidence snapshot")
    parser.add_argument("--actor", default="ADMIN")
    args = parser.parse_args(argv)

    from .db import Database

    repo = Repository(Database.open(Path(os.environ.get("SQS_DB_PATH", "/var/lib/sage-sqs/sqs.db"))))
    raw_paths = os.environ.get("SQS_BUNDLE_PATHS") or os.environ.get("SQS_BUNDLE_PATH", "/var/lib/sage-sqs/public/bundle.json")
    output_paths = tuple(Path(value.strip()) for value in raw_paths.split(",") if value.strip())
    key_path = os.environ.get("SQS_SIGNING_PRIVATE_KEY")
    key_id = os.environ.get("SQS_SIGNING_KEY_ID")
    signing_key = None
    if key_path:
        if not key_id:
            raise ValueError("SQS_SIGNING_KEY_ID is required with SQS_SIGNING_PRIVATE_KEY")
        signing_key = _load_signing_key(Path(key_path))
    elif key_id:
        raise ValueError("SQS_SIGNING_PRIVATE_KEY is required with SQS_SIGNING_KEY_ID")

    publisher = Publisher(
        repo,
        authority_id=os.environ.get("SQS_AUTHORITY_ID", "biblica-sqs-production"),
        publication_epoch=int(os.environ.get("SQS_PUBLICATION_EPOCH", "1")),
        output_paths=output_paths,
        signing_private_key=signing_key,
        signing_key_id=key_id,
    )
    publisher.publish(actor=args.actor)
    return 0
