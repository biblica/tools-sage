"""SAGE MAINTENANCE > SQS submission key menu (Codex-workspace provider plan client side)."""
from __future__ import annotations

import io

from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.sqs_submission_key import generate_submission_keypair, submission_key_status
from sage.storage import storage_layout


def _center(root, inputs):
    """Build a SageControlCenter fed a scripted sequence of menu-prompt responses."""
    return SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(inputs), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )


def test_maintenance_menu_lists_the_sqs_submission_key_item(make_workspace):
    """SAGE MAINTENANCE exposes the new SQS submission key entry as item 7."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = _center(root, ["a"])
    center.system_configuration_menu()
    rendered = center.io.output.getvalue()
    assert "7. SQS submission key" in rendered


def test_generating_a_key_for_the_first_time_shows_its_public_key_and_fingerprint(make_workspace):
    """Confirming generation on a fresh host prints the new key's public fingerprint."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = _center(root, ["y", "n"])
    center._sqs_submission_key_menu()
    rendered = center.io.output.getvalue()
    assert "Submission keypair generated." in rendered
    assert "SHA256:" in rendered
    assert "ssh-ed25519" in rendered
    state_dir = storage_layout(root).state_root / "sqs"
    assert submission_key_status(state_dir).exists is True


def test_declining_first_generation_does_not_create_a_key(make_workspace):
    """Declining the initial generate prompt leaves no submission key on disk."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = _center(root, ["n"])
    center._sqs_submission_key_menu()
    state_dir = storage_layout(root).state_root / "sqs"
    assert submission_key_status(state_dir).exists is False


def test_existing_key_is_shown_without_regenerating_when_rotation_is_declined(make_workspace):
    """An existing key's status is displayed, and declining rotation leaves it unchanged."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    state_dir = storage_layout(root).state_root / "sqs"
    original = generate_submission_keypair(state_dir)

    center = _center(root, ["n"])
    center._sqs_submission_key_menu()

    assert submission_key_status(state_dir).fingerprint == original.fingerprint


def test_rotating_with_the_exact_confirmation_replaces_the_key(make_workspace):
    """Typing ROTATE after confirming rotation replaces the key and its fingerprint changes."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    state_dir = storage_layout(root).state_root / "sqs"
    original = generate_submission_keypair(state_dir)

    center = _center(root, ["y", "ROTATE"])
    center._sqs_submission_key_menu()

    rendered = center.io.output.getvalue()
    assert "Submission keypair rotated." in rendered
    assert submission_key_status(state_dir).fingerprint != original.fingerprint


def test_rotation_requires_the_exact_confirmation_phrase(make_workspace):
    """A mismatched confirmation phrase cancels rotation and leaves the key untouched."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    state_dir = storage_layout(root).state_root / "sqs"
    original = generate_submission_keypair(state_dir)

    center = _center(root, ["y", "not rotate"])
    center._sqs_submission_key_menu()

    rendered = center.io.output.getvalue()
    assert "Rotation cancelled" in rendered
    assert submission_key_status(state_dir).fingerprint == original.fingerprint
