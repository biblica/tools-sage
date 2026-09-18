"""Execution-channel descriptor catalog: how a governed host reaches a provider_family.

Distinct from the provider_family model catalog (providers/openai_provider.py):
a provider_family is a model vendor (e.g. "openai"); an execution channel is the
access route to it (e.g. "codex_workspace"). Qualification stays keyed on the
model, never on the channel, so this catalog exists purely for onboarding and
consistency checks, not for qualification identity.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

from .domain import ExecutionChannelDescriptor

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "execution-channel-descriptor.schema.json"


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def load_execution_channel_descriptor(path: str | Path) -> ExecutionChannelDescriptor:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validated = {
        "execution_channel": payload["execution_channel"],
        "provider_family": payload["provider_family"],
        "display_name": payload["display_name"],
        "provisioning_model": payload["provisioning_model"],
        "capability_classes": list(payload.get("capability_classes") or []),
        "reasoning_tier_taxonomy": payload["reasoning_tier_taxonomy"],
    }
    if "availability_check" in payload:
        validated["availability_check"] = payload["availability_check"]
    jsonschema.validate(validated, _schema())
    return ExecutionChannelDescriptor(
        execution_channel=validated["execution_channel"],
        provider_family=validated["provider_family"],
        display_name=validated["display_name"],
        provisioning_model=validated["provisioning_model"],
        capability_classes=tuple(validated["capability_classes"]),
        reasoning_tier_taxonomy=validated["reasoning_tier_taxonomy"],
    )


def load_execution_channel_catalog(directory: str | Path) -> dict[str, ExecutionChannelDescriptor]:
    """Load every *.yml descriptor in directory, keyed by execution_channel.

    Raises ValueError on a duplicate execution_channel across files -- onboarding
    must be unambiguous, never silently last-write-wins.
    """
    catalog: dict[str, ExecutionChannelDescriptor] = {}
    for path in sorted(Path(directory).glob("*.yml")):
        descriptor = load_execution_channel_descriptor(path)
        if descriptor.execution_channel in catalog:
            raise ValueError(
                f"Duplicate execution_channel '{descriptor.execution_channel}' in {path}; "
                f"already defined by another descriptor in {directory}"
            )
        catalog[descriptor.execution_channel] = descriptor
    return catalog


def known_execution_channels(directory: str | Path) -> frozenset[str]:
    return frozenset(load_execution_channel_catalog(directory).keys())
