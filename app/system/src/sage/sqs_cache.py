"""Local validation and crash-safe caching of SQS-published bundles.

Implements the SQS integration plan's Task 3 hardening on the bundle-consumer
side: digest validation, Ed25519 signature verification, monotonic
authority/epoch/revision rollback rejection, current+previous known-good
generation rotation, and durable negative-evidence tombstones that survive
normal cache staleness. Independent of current SAGE host routing -- this
module only reads/writes its own cache files; it does not decide how SAGE
routes a task.

Design choice, not in the original plan: bundle and its acceptance metadata
are written as a single atomically-replaced file, not two separate files.
This makes "reject a torn bundle/meta pair" true by construction -- a
half-written file is caught by JSON-decode/schema failure on read, not by a
separate pairing check -- rather than needing bespoke pairing validation for
two independently-written files.

Ordering that makes the crash-safety guarantee hold: negative tombstones are
always committed (atomic replace) before the new generation is rotated in.
If a crash happens between those two writes, the tombstone file already
reflects the newer, more conservative negative evidence while the current
generation is still the old one -- always safe, never the reverse.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .atomic import atomic_write_json
from .errors import ValidationError

_CURRENT_FILENAME = "sqs-cache-current.json"
_PREVIOUS_FILENAME = "sqs-cache-previous.json"
_TOMBSTONES_FILENAME = "sqs-negative-tombstones.json"


class SqsBundleRejected(ValidationError):
    """Raised when a candidate SQS bundle fails validation or would roll back trust."""

    default_code = "SQS_BUNDLE_REJECTED"


def canonical_bundle_bytes(bundle: Mapping[str, Any]) -> bytes:
    """Exact mirror of services/sqs's Publisher.canonical_bundle_bytes.

    Must stay byte-identical to the publisher's canonicalization or every
    digest/signature check here will spuriously fail.
    """
    value = dict(bundle)
    value.pop("bundle_sha256", None)
    value.pop("signature_ed25519", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_bundle_sha256(bundle: Mapping[str, Any]) -> str:
    """Return the sha256 hex digest of the bundle's canonical byte form."""
    return hashlib.sha256(canonical_bundle_bytes(bundle)).hexdigest()


def verify_bundle_digest(bundle: Mapping[str, Any]) -> bool:
    """Return whether the bundle's claimed bundle_sha256 matches its content."""
    claimed = str(bundle.get("bundle_sha256") or "")
    return bool(claimed) and claimed == canonical_bundle_sha256(bundle)


def verify_bundle_signature(bundle: Mapping[str, Any], trusted_keys: Mapping[str, str]) -> bool:
    """Verify an Ed25519 publication against a key-id -> base64 raw public key mapping."""
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


def _tombstone_key(qualification: Mapping[str, Any]) -> str:
    """Return the stable tombstone-ledger key for one qualification row."""
    return "|".join(str(qualification[field]) for field in ("provider_family", "model_id", "profile_id", "capability"))


@dataclass(frozen=True)
class GenerationIdentity:
    """A bundle's rollback-relevant identity: which authority, epoch, and revision."""

    authority_id: str
    publication_epoch: int
    bundle_revision: int

    def is_newer_than(self, other: "GenerationIdentity") -> bool:
        """Return whether this identity is a legitimate forward advance over other."""
        if self.authority_id != other.authority_id:
            return False  # authority rotation is a separate, not-yet-designed trust decision
        if self.publication_epoch != other.publication_epoch:
            return self.publication_epoch > other.publication_epoch
        return self.bundle_revision > other.bundle_revision


def _identity_of(bundle: Mapping[str, Any]) -> GenerationIdentity:
    """Extract a bundle's GenerationIdentity from its top-level fields."""
    return GenerationIdentity(
        authority_id=str(bundle["authority_id"]),
        publication_epoch=int(bundle["publication_epoch"]),
        bundle_revision=int(bundle["bundle_revision"]),
    )


class SqsCache:
    """Crash-safe local cache of the most recent validated SQS bundle plus a
    durable negative-qualification tombstone ledger.

    All state lives under `state_dir`; this class has no knowledge of SAGE's
    routing/policy engine and makes no routing decisions itself.
    """

    def __init__(
        self,
        state_dir: Path,
        *,
        trusted_authority_id: str,
        trusted_signing_keys: Mapping[str, str] | None = None,
        require_signature: bool = False,
    ) -> None:
        """Bind this cache to state_dir and the operator's trusted SQS identity."""
        self.state_dir = Path(state_dir)
        self.trusted_authority_id = trusted_authority_id
        self.trusted_signing_keys = dict(trusted_signing_keys or {})
        self.require_signature = require_signature

    # -- paths -----------------------------------------------------------
    @property
    def _current_path(self) -> Path:
        """Return the on-disk path of the current known-good generation."""
        return self.state_dir / _CURRENT_FILENAME

    @property
    def _previous_path(self) -> Path:
        """Return the on-disk path of the previous known-good generation."""
        return self.state_dir / _PREVIOUS_FILENAME

    @property
    def _tombstones_path(self) -> Path:
        """Return the on-disk path of the durable negative-tombstone ledger."""
        return self.state_dir / _TOMBSTONES_FILENAME

    # -- reads -------------------------------------------------------------
    def _read_generation(self, path: Path) -> dict[str, Any] | None:
        """Read and parse one JSON state file, or None if absent/corrupt."""
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt/partial file must never be treated as a valid rollback
            # floor lower than an intact sibling generation, nor as usable
            # current state -- treat it exactly as absent.
            return None

    def load_current(self) -> dict[str, Any] | None:
        """Return the currently cached, previously validated bundle, or None."""
        return self._read_generation(self._current_path)

    def load_tombstones(self) -> dict[str, dict[str, Any]]:
        """Return the durable negative-qualification tombstone ledger."""
        payload = self._read_generation(self._tombstones_path)
        return dict(payload) if payload else {}

    def rollback_floor(self) -> GenerationIdentity | None:
        """Highest generation identity known from either current or previous.

        A missing (or corrupt) current generation must not lower this floor
        to "accept anything" -- it falls back to previous instead.
        """
        candidates = [
            _identity_of(bundle)
            for bundle in (self._read_generation(self._current_path), self._read_generation(self._previous_path))
            if bundle is not None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda identity: (identity.publication_epoch, identity.bundle_revision))

    # -- acceptance ----------------------------------------------------------
    def accept_bundle(self, candidate: Mapping[str, Any]) -> None:
        """Validate and durably accept a candidate bundle, or raise SqsBundleRejected.

        Order matters and is deliberate:
        1. digest/signature/authority/rollback validation (no writes yet);
        2. tombstones merged and committed durably;
        3. only then is the new generation rotated in as current.
        """
        if not verify_bundle_digest(candidate):
            raise SqsBundleRejected("SQS bundle digest does not match its content", code="SQS_BUNDLE_DIGEST_MISMATCH")

        has_signature = bool(candidate.get("signature_algorithm"))
        if self.require_signature and not has_signature:
            raise SqsBundleRejected("SQS bundle is unsigned but signature verification is required", code="SQS_BUNDLE_SIGNATURE_REQUIRED")
        if has_signature and not verify_bundle_signature(candidate, self.trusted_signing_keys):
            raise SqsBundleRejected("SQS bundle Ed25519 signature is invalid or untrusted", code="SQS_BUNDLE_SIGNATURE_INVALID")

        candidate_identity = _identity_of(candidate)
        if candidate_identity.authority_id != self.trusted_authority_id:
            raise SqsBundleRejected(
                f"SQS bundle authority_id '{candidate_identity.authority_id}' is not the trusted authority",
                code="SQS_BUNDLE_UNTRUSTED_AUTHORITY",
            )

        floor = self.rollback_floor()
        if floor is not None and not candidate_identity.is_newer_than(floor):
            raise SqsBundleRejected(
                f"SQS bundle epoch/revision {candidate_identity.publication_epoch}/{candidate_identity.bundle_revision} "
                f"does not advance past the known floor {floor.publication_epoch}/{floor.bundle_revision}",
                code="SQS_BUNDLE_ROLLBACK_REJECTED",
            )

        self._commit_tombstones(candidate)
        self._rotate_in(candidate)

    def _commit_tombstones(self, candidate: Mapping[str, Any]) -> None:
        """Durably merge candidate's negative evidence into the tombstone ledger.

        Must be called, and complete, before _rotate_in -- see the module
        docstring for why that ordering is what makes the crash-safety
        guarantee hold.
        """
        tombstones = self.load_tombstones()
        candidate_identity = _identity_of(candidate)
        for qualification in candidate.get("qualifications", []):
            key = _tombstone_key(qualification)
            if qualification.get("status") == "NOT_QUALIFIED":
                existing = tombstones.get(key)
                if existing is None or candidate_identity.is_newer_than(GenerationIdentity(
                    authority_id=str(existing["authority_id"]),
                    publication_epoch=int(existing["publication_epoch"]),
                    bundle_revision=int(existing["bundle_revision"]),
                )):
                    tombstones[key] = {
                        "authority_id": candidate_identity.authority_id,
                        "publication_epoch": candidate_identity.publication_epoch,
                        "bundle_revision": candidate_identity.bundle_revision,
                        "qualification": dict(qualification),
                    }
            elif qualification.get("status") == "QUALIFIED" and key in tombstones:
                existing = tombstones[key]
                if candidate_identity.is_newer_than(GenerationIdentity(
                    authority_id=str(existing["authority_id"]),
                    publication_epoch=int(existing["publication_epoch"]),
                    bundle_revision=int(existing["bundle_revision"]),
                )):
                    # An explicit, newer positive re-qualification for the exact
                    # same key supersedes a prior negative tombstone. Absence of
                    # a row (the qualification simply not being republished)
                    # must never do this -- only an explicit newer verdict can.
                    del tombstones[key]
        atomic_write_json(self._tombstones_path, tombstones)

    def _rotate_in(self, candidate: Mapping[str, Any]) -> None:
        """Rotate the current generation to previous, then commit candidate as current."""
        current = self._read_generation(self._current_path)
        if current is not None:
            atomic_write_json(self._previous_path, current)
        atomic_write_json(self._current_path, dict(candidate))

    def is_denied(self, *, provider_family: str, model_id: str, profile_id: str, capability: str) -> bool:
        """True if a durable negative tombstone exists for this exact route.

        Independent of whether the current cached bundle is stale or absent --
        that is the entire point of a tombstone ledger separate from normal
        cache age.
        """
        key = "|".join((provider_family, model_id, profile_id, capability))
        return key in self.load_tombstones()
