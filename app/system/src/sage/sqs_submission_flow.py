"""Run one planned SQS qualification locally and prepare/upload its submission.

Ties together the pieces built separately for the SQS Codex-workspace
provider plan: the work-queue list (sqs_client.fetch_planned_evaluations),
the validated local bundle cache (sqs_cache.SqsCache) for model/profile
lookup, sage_sqs's own portable evaluation runner and qualification
synthesis (made importable via sqs_provider_bridge.ensure_sage_sqs_importable),
and the Codex-workspace provider bridge
(sqs_provider_bridge.CodexWorkspaceProviderAdapter).

This module never writes to the SQS server's database -- it only produces a
qualification-submission-1.0 file and SCPs it into the server's incoming/
directory, where sage_sqs.ingest stages it as a QUALIFICATION_SUBMISSION
attention item pending explicit ADMIN review.
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .atomic import atomic_write_json
from .errors import ValidationError
from .sqs_provider_bridge import CodexWorkspaceProviderAdapter, ensure_sage_sqs_importable

_SUBMISSION_SCHEMA = "sage-sqs-qualification-submission-1.0"


class PlannedEvaluationNotRunnable(ValidationError):
    """Raised when a planned evaluation cannot be matched to a known model/profile/pack."""

    default_code = "SQS_PLANNED_EVALUATION_NOT_RUNNABLE"


class SqsSubmissionUploadError(ValidationError):
    """Raised when the SCP upload of a prepared submission file fails."""

    default_code = "SQS_SUBMISSION_UPLOAD_FAILED"


@dataclass(frozen=True)
class _BundleProfile:
    """The two LanguageProfile fields synthesize_qualification actually reads."""

    profile_id: str
    evaluation_identity_sha256: str


@dataclass(frozen=True)
class _BundleModel:
    """The ModelRecord fields run_planned_test/synthesize_qualification actually read."""

    provider_family: str
    model_id: str
    capability_fingerprint: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float


def _find(rows: list[dict[str, Any]], **match: Any) -> dict[str, Any] | None:
    """Return the first row matching all given field values, or None."""
    return next((row for row in rows if all(row.get(key) == value for key, value in match.items())), None)


def _utc_now_z() -> str:
    """Return the current UTC time as an integer-second, Z-suffixed ISO 8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def prepare_submission(
    *,
    planned_evaluation: dict[str, Any],
    bundle: dict[str, Any],
    pack_dir: Path,
    sage_root: Path,
    submitted_by: str,
    provider: Any = None,
) -> dict[str, Any]:
    """Run one planned evaluation locally and build its qualification-submission payload.

    Does not write or upload anything -- callers pass the result to
    write_submission_file and then upload_submission_file. `provider` is
    injectable for tests; production callers leave it as None to use
    CodexWorkspaceProviderAdapter.
    """
    if not ensure_sage_sqs_importable(sage_root):
        raise PlannedEvaluationNotRunnable(
            "sage_sqs is not importable; services/sqs must be a sibling checkout of this SAGE root",
            code="SQS_LIBRARY_NOT_AVAILABLE",
        )
    from sage_sqs.domain import EvidenceBasis
    from sage_sqs.evaluation.packs import load_pack_catalog
    from sage_sqs.evaluation.runner import run_planned_test
    from sage_sqs.qualification import synthesize_qualification

    provider_family = str(planned_evaluation.get("provider_family", "openai"))
    profile_id = str(planned_evaluation["profile_id"])
    model_id = str(planned_evaluation["model_id"])
    capability = str(planned_evaluation["capability"])
    reasoning = str(planned_evaluation.get("reasoning", "medium"))
    scope = str(planned_evaluation.get("scope", "FULL"))

    profile_row = _find(bundle.get("profiles") or [], profile_id=profile_id)
    if profile_row is None:
        raise PlannedEvaluationNotRunnable(f"Unknown profile in local bundle: {profile_id}")
    model_row = _find(bundle.get("models") or [], provider_family=provider_family, model_id=model_id)
    if model_row is None:
        raise PlannedEvaluationNotRunnable(f"Unknown model in local bundle: {provider_family}/{model_id}")

    pack = load_pack_catalog(pack_dir).get((profile_id, capability))
    if pack is None:
        raise PlannedEvaluationNotRunnable(f"No evaluation pack for {profile_id}/{capability}")
    if pack.review_state != "READY":
        raise PlannedEvaluationNotRunnable(f"Evaluation pack for {profile_id}/{capability} is not READY")

    profile = _BundleProfile(profile_id=str(profile_row["profile_id"]), evaluation_identity_sha256=str(profile_row["evaluation_identity_sha256"]))
    model = _BundleModel(
        provider_family=str(model_row["provider_family"]),
        model_id=str(model_row["model_id"]),
        capability_fingerprint=str(model_row["capability_fingerprint"]),
        input_usd_per_mtok=float(model_row["input_usd_per_mtok"]),
        output_usd_per_mtok=float(model_row["output_usd_per_mtok"]),
    )
    adapter = provider if provider is not None else CodexWorkspaceProviderAdapter()

    result = run_planned_test(pack=pack, provider=adapter, model=model, starting_reasoning=reasoning, scope=scope)
    qualification = synthesize_qualification(
        model=model, profile=profile, capability=capability, run=result,
        evidence_basis=EvidenceBasis.CONFIRMED if scope == "CONFIRMATION" else EvidenceBasis.MEASURED,
        route_value="HIGH", execution_channel="codex_workspace",
    )
    return {
        "schema": _SUBMISSION_SCHEMA,
        "run_id": str(planned_evaluation["id"]),
        "submitted_by": submitted_by,
        "submitted_at": _utc_now_z(),
        "qualification": asdict(qualification),
        "attempt": {
            "minimum_reasoning": result.minimum_reasoning,
            "quality_score": result.quality_score,
            "reliability_score": result.reliability_score,
            "total_input_tokens": result.total_input_tokens,
            "total_output_tokens": result.total_output_tokens,
            "estimated_unit_cost_usd": result.estimated_unit_cost_usd,
            "reasoning_runs": [run.reasoning for run in result.reasoning_runs],
        },
    }


def write_submission_file(submission: dict[str, Any], destination_dir: Path) -> Path:
    """Write one qualification-submission payload as a canonical JSON file, atomically."""
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    path = destination_dir / f"{submission['run_id']}.json"
    atomic_write_json(path, submission)
    return path


def upload_submission_file(
    local_path: Path,
    *,
    ssh_host: str,
    ssh_port: int,
    ssh_user: str,
    remote_incoming_dir: str,
    private_key_path: Path,
    timeout: int = 60,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """SCP one submission file into the SQS server's incoming/ directory.

    Uses the system scp binary (matching CodexCLIExecutor's own external-tool
    invocation style) with the dedicated submission private key. BatchMode=yes
    makes an auth or host-key failure fail fast and closed rather than hang
    waiting for an interactive prompt that has no terminal to reach -- normal
    OpenSSH host-key verification still applies; this deliberately does not
    disable StrictHostKeyChecking.
    """
    if not str(ssh_host or "").strip():
        raise SqsSubmissionUploadError(
            "SQS submission target is not configured (empty ssh_host in sqs.yml's submission section)",
            code="SQS_SUBMISSION_NOT_CONFIGURED",
        )
    destination = f"{ssh_user}@{ssh_host}:{str(remote_incoming_dir).rstrip('/')}/{Path(local_path).name}"
    args = [
        "scp", "-P", str(ssh_port), "-i", str(private_key_path),
        "-o", "BatchMode=yes", str(local_path), destination,
    ]
    try:
        completed = runner(args, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise SqsSubmissionUploadError("scp is not available on this host", code="SQS_SCP_NOT_FOUND") from exc
    except subprocess.TimeoutExpired as exc:
        raise SqsSubmissionUploadError(f"SCP upload to {ssh_host} timed out", code="SQS_SUBMISSION_UPLOAD_TIMEOUT") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SqsSubmissionUploadError(
            f"SCP upload to {ssh_host} failed: {detail}",
            code="SQS_SUBMISSION_UPLOAD_FAILED",
        )
