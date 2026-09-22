"""Local SQS qualification-submission SSH keypair generation and rotation."""
from __future__ import annotations

import stat

import pytest

from sage.sqs_submission_key import (
    generate_submission_keypair,
    private_key_path,
    public_key_path,
    submission_key_status,
)


def test_status_reports_absent_before_any_key_is_generated(tmp_path):
    """A fresh state directory reports no submission key until one is generated."""
    status = submission_key_status(tmp_path)
    assert status.exists is False
    assert status.public_key is None
    assert status.fingerprint is None


def test_generate_writes_a_private_key_readable_only_by_the_owner(tmp_path):
    """The generated private key file is written with owner-only 0600 permissions."""
    generate_submission_keypair(tmp_path)
    mode = stat.S_IMODE(private_key_path(tmp_path).stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_generate_writes_an_openssh_public_key_with_the_submission_comment(tmp_path):
    """The generated public key is a standard OpenSSH line tagged with the submission comment."""
    status = generate_submission_keypair(tmp_path)
    assert status.exists is True
    assert status.public_key.startswith("ssh-ed25519 ")
    assert status.public_key.endswith("sage-sqs-submission")
    assert public_key_path(tmp_path).read_text(encoding="utf-8").strip() == status.public_key


def test_status_after_generation_matches_what_generate_returned(tmp_path):
    """Re-reading status after generation returns the same key generate_submission_keypair reported."""
    generated = generate_submission_keypair(tmp_path)
    status = submission_key_status(tmp_path)
    assert status == generated


def test_generate_refuses_to_silently_overwrite_an_existing_key(tmp_path):
    """Generating a second time without force raises rather than silently replacing the live key."""
    generate_submission_keypair(tmp_path)
    with pytest.raises(FileExistsError):
        generate_submission_keypair(tmp_path)


def test_rotate_with_force_replaces_the_key_and_changes_the_fingerprint(tmp_path):
    """Rotating with force=True replaces the keypair and its reported fingerprint changes."""
    first = generate_submission_keypair(tmp_path)
    second = generate_submission_keypair(tmp_path, force=True)
    assert second.fingerprint != first.fingerprint
    assert submission_key_status(tmp_path).fingerprint == second.fingerprint


def test_fingerprint_is_the_ssh_keygen_style_sha256_form(tmp_path):
    """The reported fingerprint matches ssh-keygen's SHA256:<base64-no-padding> convention."""
    status = generate_submission_keypair(tmp_path)
    assert status.fingerprint.startswith("SHA256:")
    assert "=" not in status.fingerprint
