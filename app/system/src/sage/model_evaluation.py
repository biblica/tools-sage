"""Sealed per-Skill model evaluation with deterministic qualification receipts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from .atomic import atomic_write_json
from .errors import ConfigurationError, ValidationError
from .executors import ProviderRequest, ProviderResponse, ProviderStatus, make_executor
from .llm_settings import load_llm_settings
from .model_policy import load_model_policy
from .skill_routing import capability_fingerprint
from .storage import storage_layout


class EvaluationTransport(Protocol):
    """Minimal live or fake transport used only by the sealed evaluation harness."""

    def status(self) -> ProviderStatus:
        """Return one complete current provider capability snapshot."""
        ...

    def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
        """Execute one fresh sealed case without provider conversation reuse."""
        ...


class ProviderEvaluationTransport:
    """Adapt a normal SAGE executor to one-request-per-case evaluation calls."""

    def __init__(
        self,
        root: Path,
        *,
        provider: str,
        model_id: str,
        reasoning_id: str,
    ) -> None:
        """Bind provider settings while leaving all qualification decisions to Python."""
        self.root = root
        self.provider = provider
        self.model_id = model_id
        self.reasoning_id = reasoning_id
        self.executor = make_executor(provider, load_llm_settings(root))

    def status(self) -> ProviderStatus:
        """Probe the provider without sending a sealed case or Job evidence."""
        return self.executor.status()

    def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
        """Send exactly one case in one stateless provider request."""
        prompt = "\n".join(
            [
                str(case["act_text"]),
                "SYNTHETIC SEALED INPUT",
                str(case["input_text"]),
                f"INDEPENDENT REPETITION: {repetition}",
                "Return only the required JSON object.",
            ]
        )
        schema = {
            "type": "object",
            "required": [
                "schema_version",
                "task_id",
                "skill_id",
                "case_id",
                "scope",
                "decision",
                "finding_ids",
                "reviewed_item_ids",
                "evidence_ids",
                "prohibited_actions",
            ],
        }
        return self.executor.execute(
            ProviderRequest(
                prompt=prompt,
                schema=schema,
                model=self.model_id,
                reasoning_effort=(
                    None if self.reasoning_id == "provider-default" else self.reasoning_id
                ),
            )
        )


def _load_object(path: Path, label: str) -> dict[str, Any]:
    """Load one required JSON object with an evaluation-specific error boundary."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be one JSON object: {path}")
    return value


def load_evaluation_contracts(root: Path) -> dict[str, Any]:
    """Load the Core-owned exact Skill evaluation contract registry."""
    contracts = _load_object(
        root.resolve() / "system/config/skill-evaluation-contracts.json",
        "Skill evaluation contracts",
    )
    if contracts.get("schema_version") != "1.0" or not isinstance(contracts.get("skills"), dict):
        raise ConfigurationError("Skill evaluation contracts must use schema_version 1.0")
    return contracts


def _sha256(value: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(value).hexdigest()


def _bundle_sha256(files: Mapping[str, bytes]) -> str:
    """Hash one complete case-relative artifact inventory."""
    manifest = "\n".join(f"{name}\t{_sha256(files[name])}" for name in sorted(files)) + "\n"
    return _sha256(manifest.encode("utf-8"))


def _load_case(root: Path, row: Mapping[str, Any]) -> dict[str, object]:
    """Load and verify one sealed case bundle before any provider call."""
    case_root = (root / str(row.get("path") or "")).resolve()
    try:
        case_root.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigurationError("Evaluation case path escapes the SAGE app root") from exc
    names = ("ACT.md", "expected.json", "input.fixture.txt", "task-manifest.json")
    files = {name: (case_root / name).read_bytes() for name in names}
    if _bundle_sha256(files) != str(row.get("bundle_sha256") or ""):
        raise ValidationError(
            f"Sealed evaluation case hash mismatch: {row.get('case_id')}",
            code="MODEL_EVALUATION_CASE_STALE",
        )
    manifest = json.loads(files["task-manifest.json"].decode("utf-8"))
    expected = json.loads(files["expected.json"].decode("utf-8"))
    if not isinstance(manifest, dict) or not isinstance(expected, dict):
        raise ConfigurationError("Evaluation case manifest and expected result must be objects")
    return {
        **manifest,
        "act_text": files["ACT.md"].decode("utf-8"),
        "input_text": files["input.fixture.txt"].decode("utf-8"),
        "expected": expected,
        "bundle_sha256": str(row.get("bundle_sha256") or ""),
    }


def _provider_capability(
    status: ProviderStatus,
    *,
    provider: str,
    model_id: str,
    reasoning_id: str,
):
    """Return the exact advertised candidate or reject evaluation before case evidence."""
    if status.provider != provider or not status.available or not status.ready:
        raise ValidationError(
            f"Evaluation provider {provider} is not ready",
            code="PROVIDER_ROUTE_UNAVAILABLE",
        )
    capability = next(
        (item for item in status.model_capabilities if item.model == model_id or item.id == model_id),
        None,
    )
    if capability is None:
        raise ValidationError(f"Evaluation model is unavailable: {model_id}", code="MODEL_NOT_AVAILABLE")
    allowed = capability.reasoning_efforts or ("provider-default",)
    if reasoning_id not in allowed:
        raise ValidationError(
            f"Provider does not advertise reasoning setting {reasoning_id} for {model_id}",
            code="MODEL_REASONING_NOT_AVAILABLE",
        )
    return capability


def _parse_response(response: ProviderResponse) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse one provider response while classifying malformed output as a hard failure."""
    try:
        value = json.loads(response.content)
    except json.JSONDecodeError as exc:
        return None, [f"Response is not valid JSON: {exc}"]
    if not isinstance(value, dict):
        return None, ["Response must contain one JSON object"]
    return value, []


def _validate_attempt(
    case: Mapping[str, object],
    response: ProviderResponse,
) -> tuple[list[str], list[str]]:
    """Apply hard identity/authority checks before independent semantic assertions."""
    value, hard_errors = _parse_response(response)
    if value is None:
        return hard_errors, []
    expected = case["expected"]
    assert isinstance(expected, dict)
    exact_fields = {
        "schema_version": "1.0",
        "task_id": case["task_id"],
        "skill_id": case["skill_id"],
        "case_id": case["case_id"],
        "scope": case["scope"],
    }
    for field, wanted in exact_fields.items():
        if value.get(field) != wanted:
            hard_errors.append(f"{field} differs from the sealed case identity")
    reviewed = value.get("reviewed_item_ids")
    expected_reviewed = expected.get("expected_reviewed_item_ids")
    if reviewed != expected_reviewed:
        if str(case["skill_id"]) == "saw-original-language-review":
            hard_errors.append("Original-language evaluation requires exactly one reviewed item")
        else:
            hard_errors.append("Reviewed item identity differs from the sealed case")
    if value.get("evidence_ids") != expected.get("expected_evidence_ids"):
        hard_errors.append("Evidence identity differs from the sealed case")
    prohibited = value.get("prohibited_actions")
    if not isinstance(prohibited, list):
        hard_errors.append("prohibited_actions must be a list")
    elif prohibited:
        hard_errors.append("Response reports prohibited behavior: " + ", ".join(map(str, prohibited)))

    semantic_errors: list[str] = []
    if value.get("decision") != expected.get("expected_decision"):
        semantic_errors.append("Semantic decision differs from the sealed expectation")
    if value.get("finding_ids") != expected.get("expected_finding_ids"):
        semantic_errors.append("Finding identity differs from the sealed expectation")
    return hard_errors, semantic_errors


def _skill_sha256(root: Path, skill_id: str) -> str:
    """Return the exact adapted Skill hash from the registered Skill inventory."""
    registry = _load_object(root / "system/config/skills.json", "Skill registry")
    skill = (registry.get("skills") or {}).get(skill_id)
    if not isinstance(skill, dict) or not skill.get("adapted_sha256"):
        raise ConfigurationError(f"Unknown registered Skill: {skill_id}")
    return str(skill["adapted_sha256"])


def _receipt_path(
    root: Path,
    *,
    skill_id: str,
    provider: str,
    model_id: str,
    reasoning_id: str,
    created: datetime,
) -> Path:
    """Return a collision-resistant machine-local qualification receipt path."""
    safe = lambda value: "".join(character if character.isalnum() or character in "-." else "-" for character in value)
    directory = (
        storage_layout(root).state_root
        / "model-qualification"
        / safe(skill_id)
        / safe(provider)
        / safe(model_id)
        / safe(reasoning_id)
    )
    stamp = created.strftime("%Y%m%dT%H%M%S%fZ")
    return directory / f"qualification-{stamp}.json"


def _receipt_evidence_sha256(receipt: Mapping[str, Any]) -> str:
    """Hash every governed receipt field except its self-referential evidence digest."""
    payload = {
        key: value
        for key, value in receipt.items()
        if key not in {"evidence_sha256", "receipt_path"}
    }
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def evaluate_candidate(
    root: Path,
    *,
    skill_id: str,
    provider: str,
    model_id: str,
    reasoning_id: str,
    transport: EvaluationTransport | None = None,
) -> dict[str, Any]:
    """Run every sealed case three times and persist a deterministic route verdict."""
    root = root.expanduser().resolve()
    contracts = load_evaluation_contracts(root)
    contract = contracts["skills"].get(skill_id)
    if not isinstance(contract, dict):
        raise ConfigurationError(f"No model evaluation contract exists for {skill_id}")
    effective_transport = transport or ProviderEvaluationTransport(
        root,
        provider=provider,
        model_id=model_id,
        reasoning_id=reasoning_id,
    )
    status = effective_transport.status()
    capability = _provider_capability(
        status,
        provider=provider,
        model_id=model_id,
        reasoning_id=reasoning_id,
    )
    attempts: list[dict[str, Any]] = []
    repetitions = int(contract.get("repetitions_per_case") or 0)
    if repetitions != 3:
        raise ConfigurationError(f"Evaluation contract for {skill_id} must require three repetitions")

    # Each execution receives a newly loaded immutable case object and a fresh
    # provider call; no conversation state or another case is carried forward.
    for case_row in contract.get("cases", []):
        if not isinstance(case_row, dict):
            raise ConfigurationError(f"Evaluation cases for {skill_id} must be objects")
        for repetition in range(1, repetitions + 1):
            case = _load_case(root, case_row)
            response = effective_transport.execute(case, repetition)
            hard_errors, semantic_errors = _validate_attempt(case, response)
            attempts.append(
                {
                    "case_id": case["case_id"],
                    "case_kind": case["case_kind"],
                    "repetition": repetition,
                    "hard_errors": hard_errors,
                    "semantic_errors": semantic_errors,
                    "response_sha256": _sha256(response.content.encode("utf-8")),
                }
            )
    hard_failures = sum(1 for row in attempts if row["hard_errors"])
    semantic_failures = sum(1 for row in attempts if row["semantic_errors"])
    qualification = "FAILED" if hard_failures else ("UNRELIABLE" if semantic_failures else "QUALIFIED")
    created = datetime.now(timezone.utc)
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "provider": provider,
        "model_id": capability.model,
        "capability_fingerprint": capability_fingerprint(capability),
        "reasoning_id": reasoning_id,
        "skill_id": skill_id,
        "skill_sha256": _skill_sha256(root, skill_id),
        "suite_id": str(contract.get("suite_id") or ""),
        "suite_sha256": str(contract.get("suite_sha256") or ""),
        "policy_version": str(contracts.get("qualification_policy_version") or ""),
        "qualification_status": qualification,
        "provider_runtime_version": status.version,
        "model_identity_strength": capability.identity_strength,
        "cost_class": capability.cost_class,
        "case_count": len(contract.get("cases", [])),
        "repetitions_per_case": repetitions,
        "attempt_count": len(attempts),
        "hard_failure_count": hard_failures,
        "semantic_failure_count": semantic_failures,
        "semantic_score": (len(attempts) - semantic_failures) / len(attempts),
        "semantic_score_material": False,
        "attempts": attempts,
        "created_utc": created.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    }
    receipt["evidence_sha256"] = _receipt_evidence_sha256(receipt)
    path = _receipt_path(
        root,
        skill_id=skill_id,
        provider=provider,
        model_id=capability.model,
        reasoning_id=reasoning_id,
        created=created,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, receipt)
    return {**receipt, "receipt_path": str(path)}


def reconcile_qualification_receipt(root: Path, path: Path) -> dict[str, Any]:
    """Reconcile one local receipt with its hash-bound current Skill, suite, and policy."""
    root = root.expanduser().resolve()
    receipt = _load_object(path.expanduser().resolve(), "model qualification receipt")
    recorded_hash = str(receipt.get("evidence_sha256") or "")
    if recorded_hash != _receipt_evidence_sha256(receipt):
        return {
            "status": "STALE",
            "reason_code": "QUALIFICATION_EVIDENCE_HASH_MISMATCH",
            "receipt_path": str(path),
        }
    skill_id = str(receipt.get("skill_id") or "")
    contracts = load_evaluation_contracts(root)
    contract = contracts["skills"].get(skill_id)
    policy = load_model_policy(root)
    route_policy = policy["skill_routes"].get(skill_id)
    current = {
        "skill_sha256": _skill_sha256(root, skill_id),
        "suite_id": str(contract.get("suite_id") or "") if isinstance(contract, dict) else "",
        "suite_sha256": str(contract.get("suite_sha256") or "") if isinstance(contract, dict) else "",
        "policy_version": str(policy.get("qualification_policy_version") or ""),
    }
    if not isinstance(route_policy, dict):
        return {
            "status": "STALE",
            "reason_code": "QUALIFICATION_SKILL_ROUTE_REMOVED",
            "receipt_path": str(path),
        }
    mismatches = [
        field for field, expected in current.items() if str(receipt.get(field) or "") != expected
    ]
    if (
        str(route_policy.get("suite_id") or "") != current["suite_id"]
        or str(route_policy.get("suite_sha256") or "") != current["suite_sha256"]
    ):
        mismatches.append("model_policy_suite_identity")
    return {
        "status": "CURRENT" if not mismatches else "STALE",
        "reason_code": None if not mismatches else "QUALIFICATION_BOUND_IDENTITY_CHANGED",
        "mismatches": sorted(set(mismatches)),
        "receipt_path": str(path),
        "receipt": receipt,
    }


def promote_receipts(
    root: Path,
    *,
    receipt_paths: list[Path],
    destination: Path,
) -> dict[str, Any]:
    """Write a reviewable seed candidate from current fully qualified receipts only."""
    if not receipt_paths:
        raise ConfigurationError("Seed promotion requires at least one qualification receipt")
    if destination.exists():
        raise ConfigurationError(f"Seed candidate destination already exists: {destination}")
    route_fields = (
        "provider",
        "model_id",
        "capability_fingerprint",
        "reasoning_id",
        "skill_id",
        "skill_sha256",
        "suite_id",
        "suite_sha256",
        "policy_version",
        "qualification_status",
        "evidence_sha256",
        "cost_class",
        "semantic_score",
        "semantic_score_material",
    )
    routes: list[dict[str, Any]] = []
    for path in receipt_paths:
        reconciled = reconcile_qualification_receipt(root, path)
        receipt = reconciled.get("receipt")
        if reconciled.get("status") != "CURRENT" or not isinstance(receipt, dict):
            raise ValidationError(
                f"Qualification receipt is stale and cannot be promoted: {path}",
                code="SKILL_ROUTE_EVIDENCE_STALE",
            )
        if receipt.get("qualification_status") != "QUALIFIED":
            raise ValidationError(
                f"Only QUALIFIED receipts can be promoted: {path}",
                code="MODEL_QUALIFICATION_NOT_PASSED",
            )
        routes.append({field: receipt.get(field) for field in route_fields})
    routes.sort(
        key=lambda row: (
            str(row["skill_id"]),
            str(row["provider"]),
            str(row["model_id"]),
            str(row["reasoning_id"]),
        )
    )
    payload = {"schema_version": "1.0", "routes": routes}
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, payload)
    return {
        "status": "PROMOTED_CANDIDATE",
        "route_count": len(routes),
        "destination": str(destination),
    }
