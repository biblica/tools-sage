"""Assistive-only Local AI transforms over validated administrative/report facts.

This module intentionally exposes capability-specific methods rather than a free-form
prompt API.  It cannot authorize actions, execute governed workflow tasks, or receive
raw Scripture/original-language evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .atomic import atomic_write_json
from .errors import ValidationError
from .hashing import sha256_bytes, sha256_file
from .llm_settings import LOCAL_AI_AUTHORITY, local_ai_policy_status
from .storage import storage_layout

ASSISTIVE_LABEL = "NON_AUTHORITATIVE_ASSISTIVE"
ASSISTIVE_CAPABILITIES = (
    "status_explanation",
    "diagnostic_explanation",
    "approved_action_explanation",
    "report_executive_summary",
)
_STATUS_FACT_KEYS = frozenset(
    {
        "state",
        "status",
        "active_task",
        "stage",
        "current_job",
        "current_run",
        "resource_status",
        "ai_connection",
        "ai_prerequisite",
        "workflow",
        "reporting_mode",
        "secondary_language_allowed",
        "reason_code",
        "condition",
        "approved_action_count",
    }
)
_CAPABILITY_FACT_KEYS: dict[str, frozenset[str]] = {
    "status_explanation": _STATUS_FACT_KEYS,
    "diagnostic_explanation": _STATUS_FACT_KEYS | frozenset({"component", "severity"}),
    "approved_action_explanation": _STATUS_FACT_KEYS | frozenset({"action_context"}),
    "report_executive_summary": frozenset(
        {
            "schema_version",
            "workflow",
            "operation",
            "scope",
            "status",
            "item_kind",
            "item_count",
            "item_ids",
            "critical_unresolved_ids",
            "items",
            "canonical_report_sha256",
        }
    ),
}
_REPORT_ITEM_KEYS = frozenset(
    {
        "id",
        "kind",
        "reference",
        "category",
        "risk",
        "urgency",
        "confidence",
        "status",
        "recommended_action",
        "selected_candidate_id",
        "candidate_ids",
    }
)
_FORBIDDEN_KEY_PARTS = (
    "scripture",
    "usfm",
    "usj",
    "greek",
    "hebrew",
    "original_language",
    "act_body",
    "skill_body",
    "credential",
    "secret",
    "password",
    "api_key",
    "authorization",
    "filesystem",
    "file_path",
    "source_path",
    "project_path",
)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class AssistiveResult:
    """One validated assistive transform result plus immutable provenance metadata."""

    status: str
    capability: str
    label: str
    text: str | None
    provider: str | None
    model: str | None
    source_sha256: str
    output_sha256: str | None
    fallback_used: bool
    action_tokens: tuple[str, ...]
    referenced_ids: tuple[str, ...]
    receipt_path: str
    diagnostic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation of the assistive result."""
        return asdict(self)


def _canonical_bytes(value: Any) -> bytes:
    """Serialize an assistive payload deterministically for hashing and prompting."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _looks_like_absolute_path(value: str) -> bool:
    """Return whether a string resembles a host filesystem absolute path."""
    text = value.strip()
    return text.startswith(("/", "~/", "\\\\")) or bool(_WINDOWS_ABSOLUTE_RE.match(text))


def _validate_safe_value(value: Any, *, breadcrumb: str = "input") -> None:
    """Reject model inputs outside the bounded administrative/report data contract."""
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if _looks_like_absolute_path(value):
            raise ValidationError(
                f"Local AI input contains a filesystem path at {breadcrumb}",
                code="LOCAL_AI_INPUT_POLICY_VIOLATION",
            )
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_safe_value(item, breadcrumb=f"{breadcrumb}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).strip().casefold()
            if any(part in name for part in _FORBIDDEN_KEY_PARTS):
                raise ValidationError(
                    f"Local AI input field is prohibited: {breadcrumb}.{key}",
                    code="LOCAL_AI_INPUT_POLICY_VIOLATION",
                )
            _validate_safe_value(item, breadcrumb=f"{breadcrumb}.{key}")
        return
    raise ValidationError(
        f"Local AI input contains unsupported data at {breadcrumb}",
        code="LOCAL_AI_INPUT_POLICY_VIOLATION",
    )


def _validate_capability_facts(capability: str, facts: Mapping[str, Any]) -> None:
    """Reject fields outside the typed contract for one assistive capability."""
    allowed = _CAPABILITY_FACT_KEYS.get(capability)
    if allowed is None:
        raise ValidationError(
            f"Unsupported Local AI capability: {capability}",
            code="LOCAL_AI_CAPABILITY_NOT_ALLOWED",
        )
    unexpected = sorted(str(key) for key in facts if str(key) not in allowed)
    if unexpected:
        raise ValidationError(
            f"Local AI {capability} input contains unwhitelisted fields: {', '.join(unexpected)}",
            code="LOCAL_AI_INPUT_POLICY_VIOLATION",
        )
    if capability == "report_executive_summary":
        items = facts.get("items", [])
        if not isinstance(items, list):
            raise ValidationError(
                "Local AI report summary items must be a list",
                code="LOCAL_AI_INPUT_POLICY_VIOLATION",
            )
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise ValidationError(
                    f"Local AI report summary item {index} must be an object",
                    code="LOCAL_AI_INPUT_POLICY_VIOLATION",
                )
            extra = sorted(str(key) for key in item if str(key) not in _REPORT_ITEM_KEYS)
            if extra:
                raise ValidationError(
                    f"Local AI report summary item {index} contains unwhitelisted fields: {', '.join(extra)}",
                    code="LOCAL_AI_INPUT_POLICY_VIOLATION",
                )
    _validate_safe_value(facts)


def compact_report_view(
    document: Mapping[str, Any],
    *,
    canonical_report_sha256: str | None = None,
) -> dict[str, Any]:
    """Project a canonical report into a Scripture-free assistive summary view."""
    rows = document.get("findings")
    item_kind = "finding"
    if not isinstance(rows, list):
        rows = document.get("challenges")
        item_kind = "challenge"
    rows = rows if isinstance(rows, list) else []
    safe_rows: list[dict[str, Any]] = []
    item_ids: list[str] = []
    critical_unresolved_ids: list[str] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        item_id = str(
            raw.get("finding_id")
            or raw.get("challenge_id")
            or raw.get("request_id")
            or ""
        ).strip()
        if not item_id:
            continue
        item_ids.append(item_id)
        risk = raw.get("risk")
        risk_value: Any = raw.get("risk_level")
        urgency: Any = raw.get("urgency")
        if isinstance(risk, Mapping):
            risk_value = risk.get("level", risk.get("risk", risk_value))
            urgency = risk.get("urgency", urgency)
        reference = str(
            raw.get("scripture_reference")
            or raw.get("target_reference")
            or raw.get("reference")
            or raw.get("coordinate")
            or ""
        ).strip()
        candidate_ids = [
            str(candidate.get("candidate_id"))
            for candidate in raw.get("candidates", [])
            if isinstance(candidate, Mapping) and candidate.get("candidate_id")
        ] if isinstance(raw.get("candidates"), list) else []
        safe = {
            "id": item_id,
            "kind": item_kind,
            "reference": reference or None,
            "category": raw.get("category") or raw.get("type"),
            "risk": risk_value,
            "urgency": urgency,
            "confidence": raw.get("confidence"),
            "status": raw.get("status"),
            "recommended_action": raw.get("recommended_action") if isinstance(raw.get("recommended_action"), str) and not _looks_like_absolute_path(str(raw.get("recommended_action"))) else None,
            "selected_candidate_id": raw.get("selected_candidate_id"),
            "candidate_ids": candidate_ids,
        }
        safe_rows.append({key: value for key, value in safe.items() if value not in (None, "", [])})
        risk_text = str(risk_value or "").strip().upper()
        urgency_text = str(urgency or "").strip().upper()
        status_text = str(raw.get("status") or "").strip().upper()
        critical = risk_text in {"4", "CRITICAL", "HIGH"} or urgency_text in {"4", "CRITICAL", "HIGH"}
        unresolved = status_text not in {"RESOLVED", "CLOSED", "COMPLETE", "ACCEPTED"}
        if critical and unresolved:
            critical_unresolved_ids.append(item_id)
    view = {
        "schema_version": "1.0",
        "workflow": document.get("workflow"),
        "operation": document.get("operation"),
        "scope": document.get("scope"),
        "status": document.get("status") or document.get("result"),
        "item_kind": item_kind,
        "item_count": len(safe_rows),
        "item_ids": item_ids,
        "critical_unresolved_ids": critical_unresolved_ids,
        "items": safe_rows,
    }
    if canonical_report_sha256:
        view["canonical_report_sha256"] = canonical_report_sha256
    _validate_safe_value(view)
    return view


class LocalTransformService:
    """Render whitelisted assistive transforms deterministically."""

    # Keep receipt identity and rendering in one class so every UI surface hashes the
    # same normalized facts and cannot quietly introduce a provider-specific path.

    def __init__(self, root: Path) -> None:
        """Bind one deterministic assistive renderer to a SAGE root."""
        self.root = root.expanduser().resolve()
        self.receipt_root = storage_layout(self.root).state_root / "local-ai-receipts"

    def _receipt_path(self, capability: str, source_sha256: str) -> Path:
        """Return the deterministic administrative receipt path for one source view."""
        return self.receipt_root / f"{capability}-{source_sha256}.json"

    def _write_receipt(self, result: dict[str, Any]) -> Path:
        """Persist provenance without writing any Job, Run, Project, or Scripture state."""
        path = self._receipt_path(str(result["capability"]), str(result["source_sha256"]))
        atomic_write_json(path, result)
        return path

    @staticmethod
    def _deterministic_explanation(
        capability: str,
        facts: Mapping[str, Any],
        action_tokens: Sequence[str],
    ) -> str:
        """Render a complete explanation without model judgment or new actions."""
        parts = [f"{key}={facts[key]}" for key in sorted(facts) if facts[key] not in (None, "", [], {})]
        text = "; ".join(parts) if parts else "No additional diagnostic facts are available."
        if action_tokens:
            text += "; approved actions=" + ", ".join(action_tokens)
        return text

    @staticmethod
    def _deterministic_report_summary(facts: Mapping[str, Any]) -> str:
        """Render a concise report summary from controller-owned counts and identifiers."""
        workflow = str(facts.get("workflow") or "SAGE").upper()
        operation_id = str(facts.get("operation") or "report").strip().lower()
        operation = (
            "Reference Text Comparison (RTC)"
            if operation_id == "rtc"
            else operation_id.replace("_", " ")
        )
        scope = str(facts.get("scope") or "the requested scope")
        item_kind = str(facts.get("item_kind") or "item")
        item_count = int(facts.get("item_count") or 0)
        plural = item_kind if item_count == 1 else f"{item_kind}s"
        text = f"{workflow} {operation} report for {scope}: {item_count} {plural}."
        critical = [str(value) for value in facts.get("critical_unresolved_ids", [])]
        if critical:
            text += f" Critical unresolved: {', '.join(critical)}."
        else:
            text += " No critical unresolved items are recorded."
        return text

    def _transform(
        self,
        capability: str,
        facts: Mapping[str, Any],
        *,
        action_tokens: Sequence[str] = (),
        referenced_ids: Sequence[str] = (),
    ) -> AssistiveResult:
        """Render one whitelisted transform deterministically from validated facts."""
        if capability not in ASSISTIVE_CAPABILITIES:
            raise ValidationError(
                f"Unsupported Local AI capability: {capability}",
                code="LOCAL_AI_CAPABILITY_NOT_ALLOWED",
            )
        _validate_capability_facts(capability, facts)
        actions = tuple(str(value) for value in action_tokens)
        references = tuple(str(value) for value in referenced_ids)
        request_view = {
            "capability": capability,
            "facts": dict(facts),
            "action_tokens": list(actions),
            "referenced_ids": list(references),
        }
        source_sha256 = sha256_bytes(_canonical_bytes(request_view))
        text = (
            self._deterministic_report_summary(facts)
            if capability == "report_executive_summary"
            else self._deterministic_explanation(capability, facts, actions)
        )
        provider = None
        model = None
        diagnostic = "Rendered deterministically by the SAGE controller; no AI call was made."
        fallback_used = False
        status = "READY"
        output_sha256 = sha256_bytes(text.encode("utf-8")) if text is not None else None
        receipt_payload = {
            "schema_version": "1.0",
            "status": status,
            "capability": capability,
            "label": ASSISTIVE_LABEL,
            "authority": LOCAL_AI_AUTHORITY,
            "provider": provider,
            "model": model,
            "source_sha256": source_sha256,
            "output_sha256": output_sha256,
            "fallback_used": fallback_used,
            "action_tokens": list(actions),
            "referenced_ids": list(references),
            "diagnostic": diagnostic,
        }
        receipt = self._write_receipt(receipt_payload)
        return AssistiveResult(
            status=status,
            capability=capability,
            label=ASSISTIVE_LABEL,
            text=text,
            provider=provider,
            model=model,
            source_sha256=source_sha256,
            output_sha256=output_sha256,
            fallback_used=fallback_used,
            action_tokens=actions,
            referenced_ids=references,
            receipt_path=str(receipt),
            diagnostic=diagnostic,
        )

    def explain_status(
        self,
        facts: Mapping[str, Any],
        *,
        approved_actions: Sequence[str] = (),
    ) -> AssistiveResult:
        """Phrase validated controller status facts without changing their action set."""
        return self._transform(
            "status_explanation",
            facts,
            action_tokens=approved_actions,
        )

    def explain_diagnostic(
        self,
        facts: Mapping[str, Any],
        *,
        approved_actions: Sequence[str] = (),
    ) -> AssistiveResult:
        """Phrase a validated diagnostic while preserving approved remediation actions."""
        return self._transform(
            "diagnostic_explanation",
            facts,
            action_tokens=approved_actions,
        )

    def explain_approved_actions(
        self,
        facts: Mapping[str, Any],
        *,
        approved_actions: Sequence[str],
    ) -> AssistiveResult:
        """Explain controller-approved actions without inventing or authorizing alternatives."""
        return self._transform(
            "approved_action_explanation",
            facts,
            action_tokens=approved_actions,
        )

    def summarize_report(self, report_view: Mapping[str, Any]) -> AssistiveResult:
        """Summarize a compact canonical report view without receiving Scripture text."""
        ids = report_view.get("item_ids", [])
        if not isinstance(ids, list):
            raise ValidationError(
                "Report assistive view item_ids must be a list",
                code="LOCAL_AI_INPUT_POLICY_VIOLATION",
            )
        return self._transform(
            "report_executive_summary",
            report_view,
            referenced_ids=[str(value) for value in ids],
        )

    def write_report_executive_summary(
        self,
        canonical_report_path: Path,
        canonical_document: Mapping[str, Any],
        *,
        output_path: Path | None = None,
    ) -> Path | None:
        """Write a separate deterministic summary artifact when assistive mode is enabled."""
        source = canonical_report_path.expanduser().resolve()
        if not source.is_file():
            raise ValidationError(
                f"Canonical report source does not exist: {source}",
                code="LOCAL_AI_REPORT_SOURCE_MISSING",
            )
        policy = local_ai_policy_status(self.root)
        if not policy["enabled"]:
            return None
        view = compact_report_view(
            canonical_document,
            canonical_report_sha256=sha256_file(source),
        )
        result = self.summarize_report(view)
        if not result.text:
            return None
        destination = output_path
        if destination is None:
            destination = source.with_name(source.stem + "_ASSISTIVE-SUMMARY.json")
        payload = {
            "schema_version": "1.0",
            "label": ASSISTIVE_LABEL,
            "authority": LOCAL_AI_AUTHORITY,
            "canonical_report_sha256": sha256_file(source),
            "critical_unresolved_ids": list(view.get("critical_unresolved_ids", [])),
            "item_ids": list(view.get("item_ids", [])),
            "summary": result.text,
            "assistive_receipt": result.to_dict(),
        }
        atomic_write_json(destination, payload)
        return destination


def maybe_write_report_executive_summary(
    root: Path,
    canonical_report_path: Path,
    canonical_document: Mapping[str, Any],
) -> Path | None:
    """Best-effort separate assistive summary that can never block canonical publication."""
    if not local_ai_policy_status(root)["enabled"]:
        return None
    try:
        return LocalTransformService(root).write_report_executive_summary(
            canonical_report_path,
            canonical_document,
        )
    except Exception:
        # This boundary is intentionally fail-open for the already-published canonical report.
        return None
