"""Cross-catalog provider onboarding consistency: SAGE's governed-provider
allowlist vs. SQS's execution-channel descriptor catalog.

This is the provider-side counterpart to language_coverage.py's language
onboarding check (SQS integration plan Task 6, symmetric to Task 1b).
Provider identifiers differ by design between the two systems (SAGE's
governed provider is "codex"; SQS's matching execution_channel is
"codex_workspace" -- see the architecture spec's two-field provider
identity decision), so this is an explicit mapping, not a set-equality
check: adding a governed provider requires adding an entry here AND a
matching SQS execution-channel descriptor, one coordinated action.

NOTE on the sibling-repo split (architecture spec decision 4): like
language_coverage.py, this reads SQS's execution-channel YAML files
directly via a relative filesystem path, assuming services/sqs stays
colocated in this repository. It does not import sage_sqs's Python
package -- these are, and are meant to remain, separate services with
no code-level dependency between them.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .build_policy import ENABLED_AUTOMATED_PROVIDER_IDS

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SQS_EXECUTION_CHANNELS_DIR = _REPO_ROOT / "services" / "sqs" / "seed" / "execution-channels"

SAGE_PROVIDER_TO_EXECUTION_CHANNEL: dict[str, str] = {
    "codex": "codex_workspace",
}


def sage_governed_provider_ids() -> frozenset[str]:
    """Return SAGE's currently governed (automated, non-assistive) provider IDs."""
    return frozenset(ENABLED_AUTOMATED_PROVIDER_IDS)


def sqs_execution_channel_ids(execution_channels_dir: str | Path | None = None) -> frozenset[str]:
    """Return every execution_channel id seeded in SQS's descriptor catalog."""
    directory = Path(execution_channels_dir) if execution_channels_dir is not None else _SQS_EXECUTION_CHANNELS_DIR
    if not directory.is_dir():
        raise FileNotFoundError(
            f"SQS execution-channel descriptor directory not found at {directory}. "
            "If services/sqs has been split into its own repository, this check "
            "needs a different mechanism than a relative filesystem path -- see "
            "the module docstring."
        )
    ids: set[str] = set()
    for path in sorted(directory.glob("*.yml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        ids.add(str(payload["execution_channel"]))
    return frozenset(ids)


def check_provider_onboarding_consistency(execution_channels_dir: str | Path | None = None) -> list[str]:
    """Return a list of provider-onboarding-coordination violations (empty means consistent)."""
    sqs_channels = sqs_execution_channel_ids(execution_channels_dir)
    violations: list[str] = []

    for provider_id in sorted(sage_governed_provider_ids()):
        channel = SAGE_PROVIDER_TO_EXECUTION_CHANNEL.get(provider_id)
        if channel is None:
            violations.append(
                f"{provider_id}: governed in SAGE but has no execution_channel mapping registered "
                "in SAGE_PROVIDER_TO_EXECUTION_CHANNEL -- onboarding a provider requires recording this"
            )
            continue
        if channel not in sqs_channels:
            violations.append(
                f"{provider_id}: mapped to execution_channel '{channel}', but SQS's descriptor "
                "catalog has no such channel -- the SQS-side descriptor may be missing or renamed"
            )

    mapped_channels = set(SAGE_PROVIDER_TO_EXECUTION_CHANNEL.values())
    for channel in sorted(sqs_channels):
        if channel not in mapped_channels:
            violations.append(
                f"{channel}: seeded in SQS's execution-channel catalog but no SAGE provider maps "
                "to it in SAGE_PROVIDER_TO_EXECUTION_CHANNEL -- either onboard it on the SAGE side "
                "or record why it is intentionally not yet governed here"
            )

    return violations
