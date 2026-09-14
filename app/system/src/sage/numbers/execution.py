"""Own fresh qualification and immutable inputs for one governed NCA attempt."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

from sage.errors import ValidationError
from sage.hashing import sha256_bytes
from sage.jobs import Job, Run
from sage.references import parse_scope
from sage.registry import EcosystemConfig
from sage.versification_service import VersificationService
from sage.vrs import VerseRef

from .models import ProjectedUnit, ReferenceBundle, TargetUnit, freeze
from .policy import _inventory, load_nca_run_snapshot
from .reference import REFERENCE_PARSER_VERSION
from .resources import reference_package_path, resolve_reference_package
from .scope import project_scope
from .style import load_style_profile, validate_style_profile
from .target import extract_heading_units, target_units
from .transport import StreamInput


@dataclass(frozen=True)
class ExecutionInputs:
    """Internal attempt-owned evidence; paths and mutable profile bytes are not authority."""

    bundle: ReferenceBundle
    style_profile: Mapping[str, object]
    policy: Mapping[str, object]
    projected_units: tuple[ProjectedUnit, ...]
    style_units: tuple[TargetUnit, ...]
    expected_unit_ids: tuple[str, ...]
    expected_references: tuple[VerseRef, ...]
    source_documents: Mapping[str, Mapping[str, object]]
    requested_scope: str = ""
    policy_bytes: bytes = b""
    contract_components: Mapping[str, bytes] = field(default_factory=dict)
    evidence_policy: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Require concrete immutable model coverage and copy nested source evidence."""
        if not isinstance(self.bundle, ReferenceBundle):
            raise ValidationError("NCA context bundle is invalid", code="NCA_ENGINE_INPUT_INVALID")
        self.bundle.require_qualified()
        for values, model in ((self.projected_units, ProjectedUnit), (self.style_units, TargetUnit),
                              (self.expected_unit_ids, str), (self.expected_references, VerseRef)):
            if not isinstance(values, tuple) or any(not isinstance(value, model) for value in values):
                raise ValidationError("NCA context values must be typed tuples", code="NCA_ENGINE_INPUT_INVALID")
        for name in ("style_profile", "policy", "source_documents", "contract_components", "evidence_policy"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ValidationError("NCA context mapping is invalid", code="NCA_ENGINE_INPUT_INVALID")
            object.__setattr__(self, name, freeze(value))
        actual = tuple(unit.target.unit_id for unit in self.projected_units) + tuple(
            unit.unit_id for unit in self.style_units
        )
        if (len(actual) != len(set(actual)) or len(self.expected_unit_ids) != len(set(self.expected_unit_ids))
                or set(actual) != set(self.expected_unit_ids)
                or len(self.expected_references) != len(set(self.expected_references))):
            raise ValidationError("NCA context coverage differs", code="NCA_RESULT_COVERAGE_INVALID")
        if any(not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
               or not isinstance(value, Mapping) for key, value in self.source_documents.items()):
            raise ValidationError("NCA context sources are invalid", code="NCA_ENGINE_INPUT_INVALID")
        # Projection uses a zero SHA only for explicit absence when no body source
        # exists. Preserve that coverage ledger without inventing source evidence.
        absent_ids = {
            unit.target.unit_id for unit in self.projected_units
            if unit.status in {"UNMAPPED", "REGISTERED_ABSENCE"}
            and len(unit.western_references) == 1
            and unit.target.unit_id == f"missing:{unit.western_references[0].label()}"
            and unit.target.source_sha256 == "0" * 64
            and not (unit.target.target_references or unit.target.main_text
                     or unit.target.notes or unit.target.source_locator)
        }
        targets = tuple(unit.target for unit in self.projected_units) + self.style_units
        if any(unit.source_sha256 not in self.source_documents and unit.unit_id not in absent_ids
               for unit in targets):
            raise ValidationError("NCA context source is missing", code="NCA_ENGINE_INPUT_INVALID")


def package_root(config: EcosystemConfig, package_id: str) -> Path:
    """Locate the same Core/imported package used during Job qualification."""
    return reference_package_path(config, package_id)


def validate_reference_snapshot(config: EcosystemConfig, policy: Mapping[str, object], *, job: Job) -> ReferenceBundle:
    """Requalify the sealed package once, including its immutable Job binding and inventory."""
    raw = policy.get("reference_package")
    if not isinstance(raw, Mapping):
        raise ValidationError("NCA Run reference identity is missing", code="NCA_RUN_SNAPSHOT_INVALID")
    binding = job.resources.get("numbers_package")
    if not isinstance(binding, Mapping) or any(binding.get(key) != raw.get(key) for key in ("package_id", "sha256")):
        raise ValidationError("NCA Run package differs from Job binding", code="NCA_REFERENCE_PACKAGE_STALE")
    bundle = resolve_reference_package(config, str(raw.get("package_id") or ""))
    if (bundle.package_id != raw.get("package_id") or bundle.sha256 != raw.get("sha256")
            or raw.get("parser_version") != REFERENCE_PARSER_VERSION
            or raw.get("qualification_status") != bundle.qualification_status
            or freeze(raw.get("diagnostics")) != bundle.diagnostics):
        raise ValidationError("NCA reference package changed after Run creation", code="NCA_REFERENCE_PACKAGE_STALE")
    files, inventory = _inventory(package_root(config, bundle.package_id))
    if files != raw.get("files") or inventory != raw.get("inventory_sha256"):
        raise ValidationError("NCA reference package inventory changed after Run creation", code="NCA_REFERENCE_PACKAGE_STALE")
    return bundle


def prepare_execution_inputs(
    config: EcosystemConfig, job: Job, run: Run, policy: Mapping[str, object],
) -> ExecutionInputs:
    """Validate sealed Run resources and project exact source bytes once per attempt."""
    sealed = load_nca_run_snapshot(run.root)
    if not isinstance(policy, Mapping) or freeze(policy) != freeze(sealed):
        raise ValidationError("NCA execution policy differs from Run snapshot", code="NCA_RUN_SNAPSHOT_INVALID")
    if job.tool != "nca" or run.job_id != job.job_id or run.operation != "numbers" or set(job.bindings) != {"wip"}:
        raise ValidationError("NCA execution Run binding is invalid", code="NCA_JOB_BINDING_INVALID")
    bundle = validate_reference_snapshot(config, sealed, job=job)
    wip = sealed["wip"]
    project = config.project(job.bindings["wip"])
    namespace = config.language_profile(project.language_profile)
    if (project.project_id != wip["project_id"] or project.language_code != wip["language"]
            or namespace.script != wip["script"] or project.content_state != "UNDER_REVIEW"):
        raise ValidationError("NCA sealed Project identity changed", code="NCA_WIP_SNAPSHOT_STALE")
    identity = sealed["number_style"]
    if identity['selector'] is None:
        style_document = validate_style_profile(None)
    else:
        style = load_style_profile(run.root / "profiles/number-style.yml", language=wip["language"],
                                   script=wip["script"], project=wip["project_id"])
        if (identity.get("sha256") != style.sha256 or identity.get("selector") != style.selector
                or any(identity.get(key) != style.document["profile"][field]
                       for key, field in (("profile_id", "id"), ("version", "version"),
                                          ("language", "language"), ("script", "script")))):
            raise ValidationError("NCA sealed style identity changed", code="NCA_STYLE_PROFILE_STALE")
        style_document = style.document

    # Read the already verified inventory and hash the bytes actually retained, so
    # later inventory extraction never needs mutable paths or reconstructed SFM.
    scope = parse_scope(run.scope)
    body: list[TargetUnit] = []
    headings: list[TargetUnit] = []
    documents: dict[str, Mapping[str, object]] = {}
    for relative, digest in sorted(wip["files"].items()):
        try:
            data = (run.root / "snapshot" / relative).read_bytes()
            raw = json.loads(data)
        except (OSError, ValueError) as exc:
            raise ValidationError("NCA sealed USJ is invalid", code="NCA_WIP_SNAPSHOT_STALE") from exc
        if sha256_bytes(data) != digest or not isinstance(raw, Mapping):
            raise ValidationError("NCA sealed USJ changed", code="NCA_WIP_SNAPSHOT_STALE")
        documents[digest] = raw
        body.extend(target_units(raw, source_sha256=digest))
        headings.extend(unit for unit in extract_heading_units(raw, source_sha256=digest)
                        if any(scope.contains(ref) for ref in unit.target_references))
    service = VersificationService(config)
    projected, expected_refs = project_scope(
        tuple(body), scope=scope, target_schema=service.project_schema(wip["project_id"]),
        western_schema=service.base_schema("eng.vrs"), bundle=bundle,
        mapping_path=package_root(config, bundle.package_id) / "reference/eng_org_map_rules.txt",
    )
    projected = tuple(projected)
    expected_ids = tuple(unit.target.unit_id for unit in projected) + tuple(unit.unit_id for unit in headings)
    contracts = {}
    if sealed['schema_version'] == '2.0':
        for relative, digest in sealed['phase_contracts']['files'].items():
            data = (config.root / relative).read_bytes()
            if sha256_bytes(data) != digest:
                raise ValidationError('NCA installed phase contract changed', code='NCA_MODEL_ROUTE_CHANGED')
            contracts[relative] = data
    import yaml
    limits = yaml.safe_load((config.root / 'system/config/workflows/nca/profile.yml').read_text())['evidence_policies']['default']
    return ExecutionInputs(bundle, style_document, sealed, projected, tuple(headings),
                           expected_ids, tuple(expected_refs), documents, run.scope,
                           (run.root / 'check-policy.json').read_bytes(), contracts, limits)


def reference_restrictions(policy: Mapping[str, object]) -> tuple[str, ...]:
    """Retain nonblocking package diagnostics as explicit Run coverage limits."""
    return tuple(str(item.get("code")) for item in policy["reference_package"].get("diagnostics", ())
                 if isinstance(item, Mapping) and str(item.get("code") or ""))


@dataclass(frozen=True)
class ScopeInventory:
    """Full coordinate ledger and protected groups, independent of numeric detection."""
    expected_references: tuple[VerseRef, ...]
    projected_units: tuple[ProjectedUnit, ...]
    expected_groups: frozenset[str]
    stream_inputs: tuple[StreamInput, ...]
    requested_scope: str


def build_inventory(inputs: ExecutionInputs) -> ScopeInventory:
    """Reuse the attempt's project_scope result without loading or qualifying again."""
    from .extraction import _parsing_conventions
    from .transport import streams_for_target

    conventions = _parsing_conventions(inputs.style_profile)
    language = str(inputs.policy['wip']['language'])
    streams = []
    for projected in inputs.projected_units:
        target = projected.target
        # Missing placeholders remain coverage, even when a nearby physical note
        # is also associated with that absence by the projection authority.
        if target.target_references:
            streams.extend(streams_for_target(target, inputs.source_documents[target.source_sha256],
                language=language, conventions=conventions))
    for target in inputs.style_units:
        streams.extend(streams_for_target(target, inputs.source_documents[target.source_sha256],
            language=language, conventions=conventions, heading=True))
    return ScopeInventory(inputs.expected_references, inputs.projected_units,
        frozenset(unit.target.unit_id for unit in inputs.projected_units
                  if any(inputs.bundle.lookup(ref) is not None for ref in unit.western_references)),
        tuple(value for purpose in ('BODY', 'NOTE_STYLE', 'HEADING_STYLE')
              for value in streams if value.purpose == purpose), inputs.requested_scope)


def plan_extraction(inputs: ExecutionInputs, inventory: ScopeInventory | None = None):
    """Share actual enabled-stream selection and routed-SFM planning with preflight."""
    from sage.evidence import EvidencePolicy
    from .batching import plan_batches
    from .policy import validate_optimization_policy

    inventory = inventory if inventory is not None else build_inventory(inputs)
    optimization = validate_optimization_policy(inputs.policy['optimization'])
    streams = tuple(value for value in inventory.stream_inputs
                    if value.purpose == 'BODY' or inputs.policy['checks']['presentation_consistency'])
    return streams, plan_batches(streams, policy=EvidencePolicy.from_mapping(inputs.evidence_policy),
                                max_units=optimization['extraction_batch_max_units'])
