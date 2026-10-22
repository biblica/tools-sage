"""Bridge exposing SAGE's own governed CLI executor as an SQS ProviderAdapter.

Lets an ADMIN-run SAGE host vet workspace-channel qualifications using its own
already-authenticated provider CLI login (Codex with ChatGPT, or Claude Code
with a Claude subscription) -- no separate credential material, no headless
auth (see the SQS Codex-workspace provider plan). Reuses the executor
in-process, with zero duplication of CLI invocation logic.

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

Token usage: CodexCLIExecutor does not capture it (it never runs
`codex exec --json`, deliberately -- see codex_cli.py's module comment on why
rate-limit detection depends on plain-text stdout/stderr), so Codex results
report input_tokens/output_tokens as None, which sage_sqs.evaluation.runner
already treats as zero. ClaudeCLIExecutor reports usage, so Claude results
carry real counts (prompt tokens include cache creation and cache reads).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .executors import cli_executor
from .executors.base import ProviderRequest, ProviderResponse
from .sqs_provider_coverage import SAGE_PROVIDER_TO_EXECUTION_CHANNEL, SAGE_PROVIDER_TO_PROVIDER_FAMILY

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


def _token_counts(response: ProviderResponse) -> tuple[int | None, int | None]:
    """Return (input, output) tokens when the provider reported usage, else (None, None)."""
    usage = response.metadata.get("usage")
    if not isinstance(usage, dict) or usage.get("output_tokens") is None:
        return None, None
    prompt = sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return prompt, int(usage["output_tokens"])


class WorkspaceProviderAdapter:
    """SQS ProviderAdapter implementation backed by SAGE's own governed CLI executor.

    Callers must ensure sage_sqs is importable (via ensure_sage_sqs_importable)
    before constructing sage_sqs.evaluation.runner.run_planned_test calls that
    use this adapter.
    """

    def __init__(self, executor: Any = None, *, provider: str = "codex"):
        """Wrap the given executor, or construct SAGE's default one for `provider`."""
        self.executor = executor or cli_executor(provider)
        self.execution_channel = SAGE_PROVIDER_TO_EXECUTION_CHANNEL[self.executor.provider_id]
        self.provider_family = SAGE_PROVIDER_TO_PROVIDER_FAMILY[self.executor.provider_id]

    def execute(self, *, model_id: str, reasoning: str, prompt: str):
        """Run one workspace-channel prompt and return it as an SQS ProviderResult."""
        from sage_sqs.providers.base import ProviderResult

        request = ProviderRequest(prompt=prompt, schema=_PASSTHROUGH_SCHEMA, model=model_id, reasoning_effort=reasoning)
        response = self.executor.execute(request)
        input_tokens, output_tokens = _token_counts(response)
        return ProviderResult(
            text=response.content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage_raw=dict(response.metadata),
        )
