"""Bridge exposing SAGE's own CodexCLIExecutor as an SQS ProviderAdapter.

Lets an ADMIN-run SAGE host vet Codex-workspace-channel qualifications using
its own already-authenticated Codex CLI login -- no separate credential
material, no headless auth (see the SQS Codex-workspace provider plan).
Reuses CodexCLIExecutor in-process, including its bounded token-rate-limit
auto-retry (Task 3a), with zero duplication of Codex CLI invocation logic.

sage_sqs is not a pip dependency of SAGE: it is not published anywhere, and
its full package pulls in fastapi/pydantic/uvicorn that SAGE's deterministic,
exactly-pinned runtime does not need. Only its narrow, dependency-light
evaluation/qualification/provider-adapter modules are imported here (needing
only stdlib and the already-pinned PyYAML, confirmed by direct import
against an environment with no fastapi/pydantic/uvicorn installed), made
importable by adding the sibling services/sqs/src checkout path to
sys.path. This assumes services/sqs ships alongside app/ on hosts that run
SQS vetting; it is not verified against a fully portable, code-signed SAGE
Core bundle that might omit services/sqs -- left as an open packaging
question in the plan, not resolved here.

Known gap, not fabricated: CodexCLIExecutor does not currently capture
token usage (it never runs `codex exec --json`, deliberately -- see
codex_cli.py's module comment on why rate-limit detection depends on
plain-text stdout/stderr, which --json would replace). Until that is
addressed, this bridge reports input_tokens/output_tokens as None, which
sage_sqs.evaluation.runner already treats as zero rather than raising.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .executors.base import ProviderRequest
from .executors.codex_cli import CodexCLIExecutor

_PASSTHROUGH_SCHEMA = {"type": "object"}


def ensure_sage_sqs_importable(sage_root: Path) -> bool:
    """Make sage_sqs importable by adding its sibling checkout path to sys.path if needed.

    Returns whether sage_sqs is importable after this call. Never installs
    anything or touches pip -- purely an in-process sys.path addition, the
    in-process analogue of the existing system/src sibling-path precedent.
    """
    try:
        import sage_sqs  # noqa: F401
        return True
    except ModuleNotFoundError:
        pass
    candidate = Path(sage_root).resolve().parent / "services" / "sqs" / "src"
    if candidate.is_dir():
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        try:
            import sage_sqs  # noqa: F401
            return True
        except ModuleNotFoundError:
            return False
    return False


class CodexWorkspaceProviderAdapter:
    """SQS ProviderAdapter implementation backed by SAGE's own CodexCLIExecutor.

    Callers must ensure sage_sqs is importable (via ensure_sage_sqs_importable)
    before constructing sage_sqs.evaluation.runner.run_planned_test calls that
    use this adapter.
    """

    def __init__(self, executor: CodexCLIExecutor | None = None):
        """Wrap the given CodexCLIExecutor, or construct SAGE's default one."""
        self.executor = executor or CodexCLIExecutor()

    def execute(self, *, model_id: str, reasoning: str, prompt: str):
        """Run one Codex-workspace prompt and return it as an SQS ProviderResult."""
        from sage_sqs.providers.base import ProviderResult

        request = ProviderRequest(prompt=prompt, schema=_PASSTHROUGH_SCHEMA, model=model_id, reasoning_effort=reasoning)
        response = self.executor.execute(request)
        return ProviderResult(
            text=response.content,
            input_tokens=None,
            output_tokens=None,
            usage_raw=dict(response.metadata),
        )
