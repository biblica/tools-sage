"""SQS qualification-submission SSH keypair.

Generated locally on the ADMIN's own SAGE host and used only to authenticate
SCP/SFTP uploads of measured qualification results into the SQS server's
`incoming/` directory (see the SQS Codex-workspace provider plan). The
private key never leaves this host and is never transmitted anywhere -- the
admin hands only the printed public key to whoever operates the SQS server,
to append to a dedicated, restricted system account's `authorized_keys`.
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_PRIVATE_KEY_FILENAME = "sqs-submission-key"
_PUBLIC_KEY_FILENAME = "sqs-submission-key.pub"
_COMMENT = "sage-sqs-submission"


@dataclass(frozen=True)
class SubmissionKeyStatus:
    """Whether a submission keypair exists locally, and its public half if so."""

    exists: bool
    public_key: str | None
    fingerprint: str | None
    private_key_path: Path


def private_key_path(state_dir: Path) -> Path:
    """Return the on-disk path of the local submission private key."""
    return Path(state_dir) / _PRIVATE_KEY_FILENAME


def public_key_path(state_dir: Path) -> Path:
    """Return the on-disk path of the local submission public key."""
    return Path(state_dir) / _PUBLIC_KEY_FILENAME


def _fingerprint(openssh_public_key: str) -> str:
    """Return the ssh-keygen-style SHA256 fingerprint of an OpenSSH public key line."""
    raw = base64.b64decode(openssh_public_key.split()[1])
    digest = hashlib.sha256(raw).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def submission_key_status(state_dir: Path) -> SubmissionKeyStatus:
    """Report whether a submission keypair exists, without generating one."""
    private_path = private_key_path(state_dir)
    public_path = public_key_path(state_dir)
    if not private_path.is_file() or not public_path.is_file():
        return SubmissionKeyStatus(exists=False, public_key=None, fingerprint=None, private_key_path=private_path)
    public_key = public_path.read_text(encoding="utf-8").strip()
    return SubmissionKeyStatus(exists=True, public_key=public_key, fingerprint=_fingerprint(public_key), private_key_path=private_path)


def generate_submission_keypair(state_dir: Path, *, force: bool = False) -> SubmissionKeyStatus:
    """Generate (or, with force=True, rotate) the dedicated Ed25519 submission keypair.

    Raises FileExistsError if a key already exists and force is not set --
    rotating a live credential must be a deliberate, explicit choice.
    """
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    private_path = private_key_path(state_dir)
    public_path = public_key_path(state_dir)
    if private_path.exists() and not force:
        raise FileExistsError("SQS submission key already exists; rotate explicitly to replace it")

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    # Open with the restrictive mode set at creation time, not write-then-chmod --
    # there must be no window where the private key exists world/group-readable.
    fd = os.open(private_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, private_bytes)
    finally:
        os.close(fd)
    public_path.write_text(f"{public_bytes.decode('ascii')} {_COMMENT}\n", encoding="utf-8")
    return submission_key_status(state_dir)
