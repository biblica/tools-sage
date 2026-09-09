"""Validate NCA Job prerequisites and seal immutable Run policy evidence."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from sage.atomic import atomic_write_bytes, atomic_write_json, atomic_write_text
from sage.errors import ValidationError
from sage.job_snapshots import verify_wip_snapshot
from sage.jobs import Job
from sage.registry import EcosystemConfig
from sage.storage import storage_layout

from .models import ReferenceBundle
from .reference import REFERENCE_PARSER_VERSION
from .resources import resolve_reference_package
from .style import StyleProfile, resolve_style_profile

CHECK_NAMES = ("number_accuracy", "presentation_consistency", "footnote_review")
DEFAULT_CHECKS = {name: True for name in CHECK_NAMES}
POLICY_SCHEMA_VERSION = "1.0"
CAPABILITY_LIMITATION_CODE = "NCA_LLM_CAPABILITY_LIMITATION"


@dataclass(frozen=True)
class NCAJobBindings:
    """Resolved immutable NCA resources and Project applicability at Job scope."""

    bundle: ReferenceBundle
    style: StyleProfile
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
    """Resolve and revalidate the WIP, package, and mandatory style binding for one NCA Job."""
    if job.tool != "nca" or set(job.bindings) != {"wip"}:
        raise ValidationError("NCA Job requires one WIP binding", code="NCA_JOB_BINDING_INVALID")
    if set(job.resources) != {"numbers_package"} or set(job.profiles) != {"number_style"}:
        raise ValidationError(
            "NCA Job requires one numbers package and one Number Style Profile",
            code="NCA_JOB_BINDING_INVALID",
        )
    project = config.project(job.bindings["wip"])
    if project.content_state != "UNDER_REVIEW":
        raise ValidationError("NCA WIP must be UNDER_REVIEW", code="NCA_JOB_BINDING_INVALID")
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
        job.profiles["number_style"],
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
    package_root = storage_layout(config.root).resources_root / "numbers" / resolved.bundle.package_id
    files, inventory_sha256 = _inventory(package_root)
    skill = config.root / "system/skills/nca-numbers/SKILL.md"
    schema = config.root / "system/config/schemas/nca-extraction.schema.yml"
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
            "selector": resolved.style.selector,
            "sha256": resolved.style.sha256,
            "profile_id": resolved.style.document["profile"]["id"],
            "version": resolved.style.document["profile"]["version"],
            "language": resolved.style.document["profile"]["language"],
            "script": resolved.style.document["profile"]["script"],
        },
        "model_contract": {
            "skill_id": "nca-numbers",
            "skill_sha256": _sha256(skill),
            "prompt_task_contract_version": "nca-model-phases-1.0",
            "structured_response_schema_sha256": _sha256(schema),
        },
        "model_route": dict(route),
        "sqs_checks_applied": False,
        "capability_limitation_code": CAPABILITY_LIMITATION_CODE,
    }
    return snapshot


def write_nca_run_snapshot(
    run_root: Path,
    snapshot: Mapping[str, object],
    *,
    style_bytes: bytes,
) -> Path:
    """Write policy and exact style bytes before a new Run becomes discoverable."""
    root = run_root.resolve()
    style = snapshot.get("number_style")
    if not isinstance(style, Mapping) or hashlib.sha256(style_bytes).hexdigest() != style.get("sha256"):
        raise ValidationError("NCA style snapshot bytes differ from policy", code="NCA_STYLE_PROFILE_STALE")
    style_path = root / "profiles/number-style.yml"
    atomic_write_bytes(style_path, style_bytes)
    policy_path = root / "check-policy.json"
    atomic_write_json(policy_path, _plain(snapshot))
    atomic_write_text(root / "check-policy.sha256", _sha256(policy_path) + "\n")
    load_nca_run_snapshot(root)
    return policy_path


def load_nca_run_snapshot(run_root: Path) -> Mapping[str, object]:
    """Load and verify mandatory Run-owned policy, style, and WIP evidence."""
    root = run_root.resolve()
    try:
        value = json.loads((root / "check-policy.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("NCA Run policy snapshot is missing or invalid", code="NCA_RUN_SNAPSHOT_INVALID") from exc
    if not isinstance(value, dict) or value.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise ValidationError("NCA Run policy schema is invalid", code="NCA_RUN_SNAPSHOT_INVALID")
    validate_checks(value.get("checks") if isinstance(value.get("checks"), Mapping) else None)
    try:
        recorded_policy_sha = (root / "check-policy.sha256").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValidationError("NCA Run policy hash is missing", code="NCA_RUN_SNAPSHOT_INVALID") from exc
    if recorded_policy_sha != _sha256(root / "check-policy.json"):
        raise ValidationError("NCA Run policy changed after creation", code="NCA_RUN_SNAPSHOT_INVALID")
    style = value.get("number_style")
    if not isinstance(style, Mapping) or _sha256(root / "profiles/number-style.yml") != style.get("sha256"):
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
