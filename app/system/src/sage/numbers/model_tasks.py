"""Execute the NCA extraction phase through one pinned SAGE model route.

Simplified per the 2026-09-28 rewrite: EXTRACTION is the only model phase.
Comparison against the indexed expected values is local/deterministic
(numbers/compare.py); there is no CORRESPONDENCE or GROUP_CORRESPONDENCE
model phase anymore. FOOTNOTE is replaced by a local, non-blocking
noteworthy-info lookup against already-loaded reference-package guidance
(numbers/footnotes.py) -- no model call needed for it either.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from time import perf_counter_ns
from uuid import uuid4
from types import MappingProxyType
from typing import Any, Callable, Generic, Mapping, TypeVar

from sage.errors import ValidationError
from sage.executors import Executor, ProviderRequest
from sage.llm_settings import load_llm_settings
from sage.llm_tasks import _resolve_task_route, _validate_provider_response_route
from sage.model_policy import cache_provider_catalog
from sage.registry import EcosystemConfig
from sage.routing_override import resolve_routing_mode

from .batching import ExtractionBatch, _batch, split_batch
from .telemetry import CallMeasurement
from .extraction import (
    BatchValidation,
    build_batch_extraction_payload,
    validate_batch_extraction_response,
)
from .models import (
    EXTRACTION_STATUSES,
    Extraction,
    freeze,
)


SKILL_ID = "nca-numbers"
_TASK_VERSIONS = {
    "EXTRACTION": "nca-extraction-1.0",
}
_PHASE_INSTRUCTIONS = {
    "EXTRACTION": (
        "Interpret only the supplied independent target streams. Identify every numeric "
        "expression, preserving multiplicity, in the order it appears in the text. Return "
        "each as a reduced canonical rational string. Do not classify kind, role, or unit -- "
        "only the ordered list of values and honest completeness."
    ),
}


_SCHEMAS: dict[str, dict[str, object]] = {
    "EXTRACTION": {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "phase", "batch_id", "work_units"],
        "properties": {
            "schema_version": {"type": "string", "const": "1.0"},
            "phase": {"type": "string", "const": "EXTRACTION"},
            "batch_id": {"type": "string", "minLength": 1},
            "work_units": {
                "type": "array",
                "minItems": 0,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["input_id", "status", "limitations", "values"],
                    "properties": {
                        "input_id": {"type": "string", "minLength": 1},
                        "status": {"type": "string", "enum": sorted(EXTRACTION_STATUSES)},
                        "limitations": {"type": "array", "items": {"type": "string", "minLength": 1}},
                        "values": {
                            "type": "array",
                            "items": {"type": "string", "pattern": r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$"},
                        },
                    },
                },
            },
        },
    },
}
T = TypeVar("T")


def _sha256(value: bytes) -> str:
    """Return one lowercase SHA-256 digest."""
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Mapping[str, object]) -> str:
    """Serialize one payload deterministically without altering Unicode text."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _model_error(message: str, code: str) -> ValidationError:
    """Build one stable routed NCA validation error."""
    return ValidationError(message, code=code)


def _json_value(value: object, label: str) -> object:
    """Copy bounded JSON data while normalizing exact Fractions to strings."""
    from fractions import Fraction

    if isinstance(value, Fraction):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item, label) for item in value]
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {str(key): _json_value(item, label) for key, item in value.items()}
    raise _model_error(f"{label} contains unsupported data", "NCA_MODEL_PAYLOAD_INVALID")


@dataclass(frozen=True)
class ModelPhaseReceipt:
    """Immutable route and content identity for one NCA model request."""

    phase: str
    task_version: str
    provider: str
    model: str
    reasoning_effort: str
    route_id: str
    routing_mode: str
    qualification_status: str
    prompt_sha256: str
    input_sha256: str
    response_sha256: str
    provider_metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        """Freeze provider metadata so transport receipts cannot mutate later."""
        admitted = {(phase, version) for phase, version in _TASK_VERSIONS.items()}
        if (self.phase, self.task_version) not in admitted:
            raise _model_error("Unknown NCA phase receipt", "NCA_MODEL_RECEIPT_INVALID")
        fields = (
            self.task_version,
            self.provider,
            self.model,
            self.reasoning_effort,
            self.route_id,
            self.routing_mode,
            self.qualification_status,
            self.prompt_sha256,
            self.input_sha256,
            self.response_sha256,
        )
        if any(not isinstance(value, str) or not value for value in fields):
            raise _model_error("Incomplete NCA phase receipt", "NCA_MODEL_RECEIPT_INVALID")
        object.__setattr__(
            self,
            "provider_metadata",
            MappingProxyType(
                {str(key): freeze(value) for key, value in self.provider_metadata.items()}
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Render a JSON-serializable receipt for immutable Run task evidence."""
        return {
            "phase": self.phase,
            "task_version": self.task_version,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "route_id": self.route_id,
            "routing_mode": self.routing_mode,
            "qualification_status": self.qualification_status,
            "prompt_sha256": self.prompt_sha256,
            "input_sha256": self.input_sha256,
            "response_sha256": self.response_sha256,
            "provider_metadata": _json_value(self.provider_metadata, "provider metadata"),
        }


@dataclass(frozen=True)
class ModelPhaseResult(Generic[T]):
    """Pair one validated typed phase value with its immutable execution receipt."""

    value: T
    receipt: ModelPhaseReceipt
    raw_response: str | None = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        """Require a real phase receipt, and physical evidence for every batch result."""
        if not isinstance(self.receipt, ModelPhaseReceipt):
            raise _model_error("NCA phase result lacks a receipt", "NCA_MODEL_RECEIPT_INVALID")
        if self.raw_response is None or not isinstance(self.request_id, str) or not self.request_id:
            raise _model_error("NCA result lacks physical request evidence", "NCA_MODEL_RECEIPT_INVALID")
        if (
            not isinstance(self.raw_response, str)
            or _sha256(self.raw_response.encode("utf-8")) != self.receipt.response_sha256
        ):
            raise _model_error("NCA raw response differs from its receipt", "NCA_MODEL_RECEIPT_INVALID")


class NcaModelTasks:
    """Run the NCA extraction phase through one route resolved and pinned at construction."""

    # Keep phase methods on one instance so every request reuses the readiness snapshot and route.

    def __init__(
        self,
        config: EcosystemConfig,
        *,
        settings: Mapping[str, object] | None = None,
        transport: Executor | None = None,
        expected_route_id: str | None = None,
        timeout_seconds: int = 600,
    ) -> None:
        """Resolve one normal configured Skill route and optionally verify persisted identity."""
        self._config = config
        self._settings = dict(settings) if settings is not None else load_llm_settings(config.root)
        self._timeout_seconds = timeout_seconds
        if transport is None:
            executor, status, route = _resolve_task_route(config, self._settings, SKILL_ID)
        else:
            provider = str(self._settings.get("selected_provider") or "").strip().lower()
            provider_settings = self._settings.get("providers")
            selected = provider_settings.get(provider) if isinstance(provider_settings, Mapping) else None
            if not isinstance(selected, Mapping) or not bool(selected.get("enabled", False)):
                raise _model_error("Configured NCA provider is not enabled", "LLM_PROVIDER_NOT_READY")
            executor = transport
            status = executor.status()
            if status.provider != provider:
                raise _model_error(
                    "NCA transport status differs from configured provider",
                    "PROVIDER_ROUTE_UNAVAILABLE",
                )
            if provider == "codex":
                cache_provider_catalog(config.root, status)
            route = resolve_routing_mode(config.root, SKILL_ID, [status])
            if route.identity.provider != provider:
                raise _model_error(
                    "NCA route differs from configured provider", "PROVIDER_ROUTE_UNAVAILABLE"
                )
        if expected_route_id is not None and route.identity.route_id != expected_route_id:
            raise _model_error(
                "Persisted NCA route identity differs from the currently resolved route",
                "NCA_MODEL_ROUTE_CHANGED",
            )
        self._executor = executor
        self._provider_status = status
        self._route = route
        self._attempts: list[ModelAttempt] = []

    @property
    def route_identity(self) -> Mapping[str, object]:
        """Return the pinned route identity for Run persistence and resume checks."""
        return MappingProxyType(self._route.to_dict())

    @property
    def route_snapshot(self) -> Mapping[str, object]:
        """Return normalized pinned route fields for Job/Run persistence without probing."""
        identity = self._route.identity
        return MappingProxyType(
            {
                "route_id": identity.route_id,
                "provider": identity.provider,
                "model": identity.model_id,
                "reasoning_effort": identity.reasoning_id,
                "capability_fingerprint": identity.capability_fingerprint,
                "qualification_status": self._route.qualification,
                "qualification_evidence_sha256": self._route.evidence_sha256,
                "routing_policy_version": identity.policy_version,
            }
        )

    @property
    def attempts(self) -> tuple[ModelAttempt, ...]:
        """Expose all actual calls, including failed unadmitted raw provider evidence."""
        return tuple(self._attempts)

    def _prompt(self, phase: str, payload: Mapping[str, object], *, task_version: str | None = None) -> str:
        """Assemble a version-aware capsule from the registered simplified skill contract."""
        version = task_version or _TASK_VERSIONS[phase]
        relative = "system/skills/nca-numbers/references/TARGET-EXTRACTION-CONTRACT.md"
        try:
            skill_contract = (self._config.root / relative).read_text(encoding="utf-8")
        except OSError as exc:
            raise _model_error("Registered NCA Skill contract is unavailable", "NCA_MODEL_SKILL_INVALID") from exc
        return _canonical_json({
            "task_version": version, "skill_id": SKILL_ID, "phase": phase,
            "instructions": _PHASE_INSTRUCTIONS[phase],
            "skill_contract": skill_contract, "input": payload,
        })

    def configure_phase_execution(self, executor: object) -> None:
        """Bind one controller-owned checkpoint hook without changing public phase methods."""
        self._phase_executor = executor

    def _execute(
        self, phase: str, payload: Mapping[str, object],
        validator: Callable[[Mapping[str, object]], T], *,
        task_version: str | None = None, schema: Mapping[str, object] | None = None,
    ) -> ModelPhaseResult[T]:
        """Use the optional attempt-local hook around the exact physical phase boundary."""
        hook = getattr(self, '_phase_executor', None)
        if hook is not None:
            return hook(phase, payload, validator, task_version=task_version or _TASK_VERSIONS[phase],
                schema=schema or _SCHEMAS[phase], physical=self._execute_physical)
        return self._execute_physical(phase, payload, validator, task_version=task_version, schema=schema)

    def _execute_physical(
        self, phase: str, payload: Mapping[str, object],
        validator: Callable[[Mapping[str, object]], T], *,
        task_version: str | None = None, schema: Mapping[str, object] | None = None,
    ) -> ModelPhaseResult[T]:
        """Measure each physical call and admit a receipt only after exact validation."""
        version = task_version or _TASK_VERSIONS[phase]
        prompt = self._prompt(phase, payload, task_version=version)
        identity = self._route.identity
        reasoning = None if identity.reasoning_id == "provider-default" else identity.reasoning_id
        request = ProviderRequest(prompt=prompt, schema=dict(schema or _SCHEMAS[phase]),
            model=identity.model_id, reasoning_effort=reasoning, timeout_seconds=self._timeout_seconds)
        wire = {"prompt": request.prompt, "schema": request.schema, "model": request.model,
                "reasoning_effort": request.reasoning_effort, "timeout_seconds": request.timeout_seconds}
        wire_text = _canonical_json(wire)
        unit_ids = tuple(str(item.get("input_id", item.get("unit_id"))) for item in payload["work_units"])
        request_id = uuid4().hex
        response = None
        status = "NCA_MODEL_PROVIDER_FAILED"
        execute_prevalidated = getattr(self._executor, "execute_prevalidated", None)
        started_ns = perf_counter_ns()
        try:
            try:
                response = (execute_prevalidated(request, self._provider_status)
                            if callable(execute_prevalidated) else self._executor.execute(request))
            except Exception as exc:
                if isinstance(exc, ValidationError) and exc.code in {
                    "LLM_RESPONSE_ROUTE_MISMATCH", "NCA_MODEL_ROUTE_CHANGED", "PROVIDER_ROUTE_UNAVAILABLE"
                }:
                    raise
                if str(exc).startswith("invalid_json_schema"):
                    raise _model_error(
                        f"NCA {phase.lower()} request schema was rejected by the provider: {exc}",
                        "NCA_MODEL_SCHEMA_INVALID",
                    ) from exc
                raise _model_error(f"NCA {phase.lower()} provider request failed: {exc}",
                                   "NCA_MODEL_PROVIDER_FAILED") from exc
            finally:
                finished_ns = perf_counter_ns()
            _validate_provider_response_route(response, self._route)
            try:
                raw = json.loads(response.content)
            except (TypeError, json.JSONDecodeError) as exc:
                raise _model_error(f"NCA {phase.lower()} response is not one JSON object",
                                   "NCA_MODEL_RESPONSE_INVALID") from exc
            if not isinstance(raw, Mapping):
                raise _model_error(f"NCA {phase.lower()} response is not one JSON object", "NCA_MODEL_RESPONSE_INVALID")
            value = validator(raw)
            receipt = ModelPhaseReceipt(
                phase=phase, task_version=version, provider=response.provider, model=identity.model_id,
                reasoning_effort=identity.reasoning_id, route_id=identity.route_id,
                routing_mode=self._route.routing_mode, qualification_status=self._route.qualification,
                prompt_sha256=_sha256(prompt.encode("utf-8")),
                input_sha256=_sha256(_canonical_json(payload).encode("utf-8")),
                response_sha256=_sha256(response.content.encode("utf-8")), provider_metadata=response.metadata)
            result = ModelPhaseResult(value, receipt, response.content, request_id)
            status = "VALIDATED"
            return result
        except ValidationError as exc:
            status = str(exc.code)
            raise
        finally:
            content = response.content if response is not None else None
            metadata = response.metadata if response is not None else {}
            usage = metadata.get("usage", {})
            measurement = CallMeasurement(request_id=request_id, phase=phase, unit_ids=unit_ids,
                elapsed_ms=(finished_ns - started_ns) // 1_000_000,
                request_bytes=len(wire_text.encode("utf-8")),
                response_bytes=len(content.encode("utf-8")) if isinstance(content, str) else 0,
                input_tokens=_usage_counter(usage, "input_tokens"),
                output_tokens=_usage_counter(usage, "output_tokens"), status=status, reused=False)
            response_identity = ({"provider": response.provider, "model": response.model,
                                  "reasoning_effort": response.reasoning_effort, "metadata": metadata}
                                 if response is not None else {})
            self._attempts.append(ModelAttempt(measurement, wire, content, response_identity))

    def extract_batch(
        self, batch: ExtractionBatch, *, parsing_conventions: Mapping[str, object],
    ) -> ModelPhaseResult[BatchValidation]:
        """Send precisely one target-only batch request and retain its one parent receipt."""
        payload = build_batch_extraction_payload(batch, parsing_conventions=parsing_conventions)
        return self._execute("EXTRACTION", payload,
            lambda response: validate_batch_extraction_response(batch, response))


def _usage_counter(usage: object, field: str) -> int | None:
    """Retain reported exact nonnegative token counts without estimates or coercion."""
    value = usage.get(field) if isinstance(usage, Mapping) else None
    return value if type(value) is int and value >= 0 else None


@dataclass(frozen=True)
class ModelAttempt:
    """One physical request and its exact raw evidence, independent of receipt admission."""

    measurement: CallMeasurement
    request: Mapping[str, object]
    raw_response: str | None
    response_identity: Mapping[str, object]

    def __post_init__(self) -> None:
        """Own request and provider identity data so later transports cannot mutate evidence."""
        object.__setattr__(self, "request", freeze(self.request))
        object.__setattr__(self, "response_identity", freeze(self.response_identity))


@dataclass(frozen=True)
class BatchExtractionResult:
    """Bounded terminal dispositions and unique parent receipts for checkpoint consumers."""

    accepted: Mapping[str, Extraction]
    pending: Mapping[str, str]
    parents: tuple[ModelPhaseResult[BatchValidation], ...]

    def __post_init__(self) -> None:
        """Own aggregate dispositions without copying parent usage into members."""
        object.__setattr__(self, "accepted", freeze(self.accepted))
        object.__setattr__(self, "pending", freeze(self.pending))


def extract_batch_with_retries(
    tasks: NcaModelTasks, batch: ExtractionBatch, *, parsing_conventions: Mapping[str, object],
    transient_retries: int = 1,
    on_accept: Callable[[ModelPhaseResult[BatchValidation]], None] | None = None,
) -> BatchExtractionResult:
    """Retry at most once per node, checkpoint successes immediately, and bisect unresolved inputs."""
    if type(transient_retries) is not int or transient_retries not in {0, 1}:
        raise _model_error("Batch retry count must be zero or one", "NCA_BATCH_POLICY_INVALID")
    # Validate once before building a failure tree; no preflight failure is a provider call.
    build_batch_extraction_payload(batch, parsing_conventions=parsing_conventions)
    accepted, pending, parents = {}, {}, []
    retryable = {"NCA_MODEL_PROVIDER_FAILED", "NCA_MODEL_RESPONSE_INVALID", "NCA_BATCH_COVERAGE_INVALID",
                 "NCA_EXTRACTION_SCHEMA_INVALID", "NCA_EXTRACTION_EVIDENCE_INVALID"}

    def visit(current: ExtractionBatch) -> None:
        """Spend one bounded node budget, then recurse only into strictly smaller membership."""
        reasons = {}
        for _attempt in range(1 + transient_retries):
            try:
                result = tasks.extract_batch(current, parsing_conventions=parsing_conventions)
            except ValidationError as exc:
                if exc.code not in retryable:
                    raise
                reasons = {value.input_id: str(exc.code) for value in current.inputs}
                continue
            reasons = dict(result.value.pending)
            if result.value.accepted:
                # This callback deliberately sits outside the provider retry exception boundary.
                if on_accept is not None:
                    on_accept(result)
                parents.append(result)
                accepted.update(result.value.accepted)
                remaining = tuple(value for value in current.inputs if value.input_id in reasons)
                if remaining:
                    visit(_batch(remaining, ''.join(value.routed_sfm for value in remaining), current.contract_version))
                return
        children = split_batch(current)
        if children:
            for child in children:
                visit(child)
        else:
            key = current.inputs[0].input_id
            pending[key] = "NCA_BATCH_SINGLETON_FAILED: " + reasons[key]

    visit(batch)
    return BatchExtractionResult(accepted, pending, tuple(parents))
