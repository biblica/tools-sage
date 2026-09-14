"""Validate NCA Job prerequisites and seal immutable Run policy evidence."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from sage.atomic import atomic_write_bytes, atomic_write_json, atomic_write_text
from sage.errors import ValidationError
from sage.job_snapshots import verify_wip_snapshot
from sage.jobs import Job
from sage.registry import EcosystemConfig

from .models import ReferenceBundle
from .reference import REFERENCE_PARSER_VERSION
from .resources import reference_package_path, resolve_reference_package
from .style import StyleProfile, resolve_style_profile

CHECK_NAMES = ("number_accuracy", "presentation_consistency", "footnote_review")
DEFAULT_CHECKS = {name: True for name in CHECK_NAMES}
POLICY_SCHEMA_VERSION = "2.0"
CAPABILITY_LIMITATION_CODE = "NCA_LLM_CAPABILITY_LIMITATION"


@dataclass(frozen=True)
class NCAJobBindings:
    """Resolved immutable NCA resources and Project applicability at Job scope."""

    bundle: ReferenceBundle
    style: StyleProfile | None
    project_id: str
    language: str
    script: str
    wip_snapshot: Mapping[str, object]


def _plain(value: object) -> object:
    """Copy frozen evidence into JSON-owned containers without changing values."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    """Hash one required immutable input file."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValidationError(
            f"Required NCA contract file is unavailable: {path}",
            code="NCA_RUN_CONTRACT_INVALID",
        ) from exc


def _inventory(root: Path) -> tuple[dict[str, str], str]:
    """Build the exact regular-file inventory for one qualified package root."""
    resolved = root.resolve()
    files: dict[str, str] = {}
    for path in sorted(resolved.rglob("*")):
        if path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir()):
            raise ValidationError("NCA package contains an unsafe entry", code="NCA_REFERENCE_PACKAGE_STALE")
        if path.is_file():
            files[path.relative_to(resolved).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return files, hashlib.sha256(payload).hexdigest()


def validate_checks(raw: Mapping[str, object] | None) -> dict[str, bool]:
    """Require all three exact NCA booleans and at least one enabled assessment."""
    if not isinstance(raw, Mapping) or set(raw) != set(CHECK_NAMES):
        raise ValidationError(
            "NCA check policy requires exactly three assessment booleans",
            code="NCA_CHECK_POLICY_INVALID",
        )
    checks = {name: raw[name] for name in CHECK_NAMES}
    if any(type(value) is not bool for value in checks.values()):
        raise ValidationError("NCA check settings must be booleans", code="NCA_CHECK_POLICY_INVALID")
    if not any(checks.values()):
        raise ValidationError(
            "At least one NCA assessment must be enabled",
            code="NCA_CHECK_POLICY_ALL_OFF",
            next_action="Enable number accuracy, presentation consistency, or footnote review.",
        )
    return checks


def validate_nca_job_prerequisites(config: EcosystemConfig, job: Job) -> NCAJobBindings:
    """Resolve and revalidate the WIP, package, and optional style binding for one NCA Job."""
    if job.tool != "nca" or set(job.bindings) != {"wip"}:
        raise ValidationError("NCA Job requires one WIP binding", code="NCA_JOB_BINDING_INVALID")
    if set(job.resources) != {"numbers_package"} or set(job.profiles) - {"number_style"}:
        raise ValidationError(
            "NCA Job requires one numbers package and an optional Number Style Profile",
            code="NCA_JOB_BINDING_INVALID",
        )
    project = config.project(job.bindings["wip"])
    # Prerequisites may use the role-neutral inventory configuration. The WIP
    # binding establishes review authority; execution validates Job-local state.
    package = job.resources["numbers_package"]
    package_id = str(package.get("package_id") or "")
    bundle = resolve_reference_package(config, package_id)
    if package.get("sha256") != bundle.sha256:
        raise ValidationError(
            "NCA reference package differs from the Job binding",
            code="NCA_REFERENCE_PACKAGE_STALE",
        )
    namespace = config.language_profile(project.language_profile)
    style = resolve_style_profile(
        config,
        job.profiles.get("number_style"),
        language=project.language_code,
        script=namespace.script,
        project=project.project_id,
    )
    snapshot = verify_wip_snapshot(job.root / "snapshot", require_file_inventory=True)
    if snapshot.get("project_id") != project.project_id:
        raise ValidationError("NCA WIP snapshot belongs to another Project", code="NCA_WIP_SNAPSHOT_STALE")
    return NCAJobBindings(
        bundle=bundle,
        style=style,
        project_id=project.project_id,
        language=project.language_code,
        script=namespace.script,
        wip_snapshot=snapshot,
    )


def build_nca_run_snapshot(
    config: EcosystemConfig,
    job: Job,
    *,
    checks: Mapping[str, object],
    route: Mapping[str, object],
) -> Mapping[str, object]:
    """Build one complete immutable policy snapshot from revalidated Job inputs."""
    resolved = validate_nca_job_prerequisites(config, job)
    exact_checks = validate_checks(checks)
    route_required = {
        "route_id",
        "provider",
        "model",
        "reasoning_effort",
        "capability_fingerprint",
        "qualification_status",
        "qualification_evidence_sha256",
        "routing_policy_version",
    }
    nullable = {"qualification_evidence_sha256"}
    if set(route) != route_required or any(
        not isinstance(route[key], str) or not route[key]
        for key in route_required - nullable
    ) or route["qualification_evidence_sha256"] is not None and (
        not isinstance(route["qualification_evidence_sha256"], str)
        or not route["qualification_evidence_sha256"]
    ):
        raise ValidationError("NCA model route identity is incomplete", code="NCA_MODEL_ROUTE_INVALID")
    package_root = reference_package_path(config, resolved.bundle.package_id)
    files, inventory_sha256 = _inventory(package_root)
    skill = config.root / "system/skills/nca-numbers/SKILL.md"
    schema = config.root / "system/config/schemas/nca-extraction-v2.schema.yml"
    snapshot = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "checks": exact_checks,
        "wip": {
            "project_id": resolved.project_id,
            "language": resolved.language,
            "script": resolved.script,
            "content_fingerprint": resolved.wip_snapshot["content_fingerprint"],
            "inventory_sha256": resolved.wip_snapshot["inventory_sha256"],
            "files": dict(resolved.wip_snapshot["files"]),
        },
        "reference_package": {
            "package_id": resolved.bundle.package_id,
            "sha256": resolved.bundle.sha256,
            "parser_version": REFERENCE_PARSER_VERSION,
            "qualification_status": resolved.bundle.qualification_status,
            "diagnostics": _plain(resolved.bundle.diagnostics),
            "files": files,
            "inventory_sha256": inventory_sha256,
        },
        "number_style": {
            "selector": resolved.style.selector if resolved.style else None,
            "sha256": resolved.style.sha256 if resolved.style else None,
            "profile_id": resolved.style.document["profile"]["id"] if resolved.style else None,
            "version": resolved.style.document["profile"]["version"] if resolved.style else None,
            "language": resolved.style.document["profile"]["language"] if resolved.style else resolved.language,
            "script": resolved.style.document["profile"]["script"] if resolved.style else resolved.script,
        },
        "model_contract": {
            "skill_id": "nca-numbers",
            "skill_sha256": _sha256(skill),
            "prompt_task_contract_version": "nca-model-phases-2.0",
            "structured_response_schema_sha256": _sha256(schema),
        },
        "model_route": dict(route),
        "optimization": validate_optimization_policy(yaml.safe_load(
            (config.root / "system/config/workflows/nca/profile.yml").read_text(encoding="utf-8")).get("optimization_policy")),
        "phase_contracts": phase_contract_manifest(config.root, route),
        "sqs_checks_applied": False,
        "capability_limitation_code": CAPABILITY_LIMITATION_CODE,
    }
    return snapshot


def write_nca_run_snapshot(
    run_root: Path,
    snapshot: Mapping[str, object],
    *,
    style_bytes: bytes | None,
) -> Path:
    """Write policy and any selected style bytes before a new Run becomes discoverable."""
    root = run_root.resolve()
    style = snapshot.get("number_style")
    if not isinstance(style, Mapping):
        raise ValidationError("NCA style snapshot bytes differ from policy", code="NCA_STYLE_PROFILE_STALE")
    style_path = root / "profiles/number-style.yml"
    if style.get('selector') is None:
        if style_bytes is not None or style_path.exists() or any(style.get(key) is not None for key in ('sha256', 'profile_id', 'version')):
            raise ValidationError("NCA absent style snapshot has unexpected content", code="NCA_STYLE_PROFILE_STALE")
    else:
        if style_bytes is None or hashlib.sha256(style_bytes).hexdigest() != style.get("sha256"):
            raise ValidationError("NCA style snapshot bytes differ from policy", code="NCA_STYLE_PROFILE_STALE")
        atomic_write_bytes(style_path, style_bytes)
    policy_path = root / "check-policy.json"
    atomic_write_json(policy_path, _plain(snapshot))
    atomic_write_text(root / "check-policy.sha256", _sha256(policy_path) + "\n")
    load_nca_run_snapshot(root)
    return policy_path


def load_nca_run_snapshot(run_root: Path) -> Mapping[str, object]:
    """Load and verify Run-owned policy, optional style, and WIP evidence."""
    root = run_root.resolve()
    try:
        value = json.loads((root / "check-policy.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("NCA Run policy snapshot is missing or invalid", code="NCA_RUN_SNAPSHOT_INVALID") from exc
    if not isinstance(value, dict) or value.get("schema_version") not in {"1.0", "2.0"}:
        raise ValidationError("NCA Run policy schema is invalid", code="NCA_RUN_SNAPSHOT_INVALID")
    if value["schema_version"] == "2.0":
        validate_optimization_policy(value.get("optimization"))
        if not isinstance(value.get("phase_contracts"), Mapping) or value["phase_contracts"].get("model_route") != value.get("model_route"):
            raise ValidationError("NCA phase contract manifest is invalid", code="NCA_RUN_SNAPSHOT_INVALID")
    validate_checks(value.get("checks") if isinstance(value.get("checks"), Mapping) else None)
    try:
        recorded_policy_sha = (root / "check-policy.sha256").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValidationError("NCA Run policy hash is missing", code="NCA_RUN_SNAPSHOT_INVALID") from exc
    if recorded_policy_sha != _sha256(root / "check-policy.json"):
        raise ValidationError("NCA Run policy changed after creation", code="NCA_RUN_SNAPSHOT_INVALID")
    style = value.get("number_style")
    if not isinstance(style, Mapping) or set(style) != {'selector', 'sha256', 'profile_id', 'version', 'language', 'script'}:
        raise ValidationError("NCA sealed style bytes have changed", code="NCA_STYLE_PROFILE_STALE")
    style_path = root / "profiles/number-style.yml"
    if style['selector'] is None:
        if (any(style[key] is not None for key in ('sha256', 'profile_id', 'version'))
                or style_path.exists() or style_path.is_symlink()
                or any(style[key] != value.get('wip', {}).get(key) for key in ('language', 'script'))):
            raise ValidationError("NCA sealed style absence has changed", code="NCA_STYLE_PROFILE_STALE")
    elif _sha256(style_path) != style.get('sha256'):
        raise ValidationError("NCA sealed style bytes have changed", code="NCA_STYLE_PROFILE_STALE")
    wip = value.get("wip")
    receipt = verify_wip_snapshot(root / "snapshot", require_file_inventory=True)
    if not isinstance(wip, Mapping) or any(
        wip.get(field) != receipt.get(field)
        for field in ("project_id", "content_fingerprint", "inventory_sha256", "files")
    ):
        raise ValidationError("NCA sealed WIP snapshot has changed", code="NCA_WIP_SNAPSHOT_STALE")
    if value.get("sqs_checks_applied") is not False or value.get("capability_limitation_code") != CAPABILITY_LIMITATION_CODE:
        raise ValidationError("NCA capability limitation contract is invalid", code="NCA_RUN_SNAPSHOT_INVALID")
    return value


def validate_optimization_policy(raw: Mapping[str, object]) -> dict[str, object]:
    """Validate versioned settings for future optimized Runs without resealing history."""
    integers = ('extraction_batch_max_units', 'request_concurrency', 'transient_retries')
    if (not isinstance(raw, Mapping)
            or set(raw) != {'contract_version', 'reuse_scope', *integers}
            or raw.get('contract_version') != 'nca-optimization-2.0' or raw.get('reuse_scope') != 'TASK'
            or any(type(raw.get(name)) is not int for name in integers)
            or raw['extraction_batch_max_units'] <= 0
            or raw['request_concurrency'] != 1 or raw['transient_retries'] not in {0, 1}):
        raise ValidationError('NCA optimization policy is invalid', code='NCA_OPTIMIZATION_POLICY_INVALID')
    return dict(raw)


def phase_contract_manifest(root: Path, route: Mapping[str, object]) -> dict[str, object]:
    """Seal applicable schema, capsule, validator, routing limits, and actual route identities."""
    paths = [
        'system/config/schemas/nca-extraction-v2.schema.yml',
        'system/config/schemas/nca-extraction.schema.yml',
        'system/config/schemas/numbers-result-v2.schema.yml',
        'system/config/schemas/nca-check-policy-v2.schema.yml',
        'system/config/schemas/nca-phase-ledger.schema.yml',
        'system/config/workflows/nca/profile.yml',
        'system/skills/nca-numbers/SKILL.md',
        'system/skills/nca-numbers/references/TARGET-EXTRACTION-CONTRACT.md',
        'system/src/sage/nca.py', 'system/src/sage/nca_reporting.py',
    ]
    paths.extend(path.relative_to(root).as_posix() for path in sorted((root / 'system/src/sage/numbers').glob('*.py')))
    return {'version': 'nca-phase-contracts-2.0', 'schema_ids': ['sage-nca-extraction-2.0', 'sage-numbers-result-2.0'],
        'phases': {name: 'nca-' + name.lower().replace('_', '-') + '-2.0'
                   for name in ('EXTRACTION', 'CORRESPONDENCE', 'FOOTNOTE', 'GROUP_CORRESPONDENCE')},
        'files': {name: _sha256(root / name) for name in paths}, 'model_route': dict(route)}
