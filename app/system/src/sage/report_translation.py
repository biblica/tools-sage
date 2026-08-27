"""Assistive secondary-language rendering for validated human-facing SAGE reports.

Canonical findings remain unchanged. This module renders only already-validated
human report prose in the configured secondary reporting language and records a
cache/receipt so report regeneration does not consume another model call.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .act_outputs import operator_finding_text
from .atomic import atomic_write_json
from .errors import SageError, ValidationError
from .executors import ProviderRequest, make_executor
from .hashing import sha256_bytes
from .storage import storage_layout
from .llm_settings import (
    LOCAL_AI_EXTERNAL_RENDERING_REQUIRED,
    load_llm_settings,
    local_ai_enabled,
)

_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)


def _canonical_bytes(value: Any) -> bytes:
    """Serialize one report-rendering payload deterministically for hashing."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _rendering_path(root: Path, report_path: Path) -> Path:
    """Return the governed sidecar path outside the Operator-facing reports tree."""
    resolved_root = root.expanduser().resolve()
    layout = storage_layout(resolved_root)
    resolved_report = report_path.expanduser().resolve()
    try:
        relative = resolved_report.relative_to(layout.reports_root)
        job_id, book = relative.parts[0], relative.parts[1]
        destination = layout.jobs_root / "saw" / job_id / "report_data" / book
    except (ValueError, IndexError):
        destination = layout.diagnostics_root / "report-renderings"
    destination.mkdir(parents=True, exist_ok=True)
    return destination / (resolved_report.stem + "-SECONDARY-RENDERING.json")


def _translation_source(document: Mapping[str, Any]) -> tuple[dict[str, Any], str, str] | None:
    """Project canonical findings into the bounded secondary-rendering input."""
    authority = document.get("language_authority")
    if not isinstance(authority, Mapping):
        return None
    primary = str(authority.get("primary_language") or "").strip()
    secondary = str(authority.get("secondary_language") or "").strip()
    if not primary or not secondary or primary == secondary:
        return None
    rows: list[dict[str, str]] = []
    for raw in document.get("findings", []):
        if not isinstance(raw, Mapping):
            continue
        finding_id = str(raw.get("finding_id") or "").strip()
        issue = operator_finding_text(raw.get("issue"), document, raw).strip()
        required_action = operator_finding_text(raw.get("required_action"), document, raw).strip()
        if finding_id and issue:
            rows.append(
                {
                    "finding_id": finding_id,
                    "issue": issue,
                    "required_action": required_action,
                }
            )
    event_rows: list[dict[str, str]] = []
    for raw in document.get("execution_events", []):
        if not isinstance(raw, Mapping):
            continue
        event_id = str(raw.get("event_id") or "").strip()
        message = str(raw.get("message") or "").strip()
        next_action = str(raw.get("next_action") or "").strip()
        if event_id and message:
            event_rows.append({"event_id": event_id, "message": message, "next_action": next_action})
    if not rows and not event_rows:
        return None
    return ({"primary_language": primary, "secondary_language": secondary, "findings": rows, "events": event_rows}, primary, secondary)


def _parse_translation_response(
    content: str, *, secondary_language: str, expected_ids: list[str], expected_event_ids: list[str]
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Validate one provider secondary-rendering response against exact finding/event inventories."""
    text = content.strip()
    match = _JSON_FENCE.fullmatch(text)
    if match:
        text = match.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Secondary report rendering is not valid JSON: {exc}",
            code="SECONDARY_REPORT_RENDERING_INVALID",
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ValidationError("Secondary report rendering has invalid schema_version", code="SECONDARY_REPORT_RENDERING_INVALID")
    if str(value.get("secondary_language") or "").strip() != secondary_language:
        raise ValidationError("Secondary report rendering language does not match the Job", code="SECONDARY_REPORT_RENDERING_INVALID")
    raw_rows = value.get("findings")
    if not isinstance(raw_rows, list):
        raise ValidationError("Secondary report rendering findings must be a list", code="SECONDARY_REPORT_RENDERING_INVALID")
    rows: dict[str, dict[str, str]] = {}
    for index, raw in enumerate(raw_rows, start=1):
        if not isinstance(raw, Mapping):
            raise ValidationError(f"Secondary rendering findings[{index}] must be an object", code="SECONDARY_REPORT_RENDERING_INVALID")
        finding_id = str(raw.get("finding_id") or "").strip()
        issue = str(raw.get("issue") or "").strip()
        required_action = str(raw.get("required_action") or "").strip()
        if not finding_id or not issue:
            raise ValidationError(f"Secondary rendering findings[{index}] is incomplete", code="SECONDARY_REPORT_RENDERING_INVALID")
        if finding_id in rows:
            raise ValidationError(f"Duplicate secondary rendering finding_id: {finding_id}", code="SECONDARY_REPORT_RENDERING_INVALID")
        rows[finding_id] = {"issue": issue, "required_action": required_action}
    if set(rows) != set(expected_ids):
        raise ValidationError("Secondary report rendering does not reconcile the exact finding inventory", code="SECONDARY_REPORT_RENDERING_INVALID")
    raw_events = value.get("events", [])
    if not isinstance(raw_events, list):
        raise ValidationError("Secondary report rendering events must be a list", code="SECONDARY_REPORT_RENDERING_INVALID")
    events: dict[str, dict[str, str]] = {}
    for index, raw in enumerate(raw_events, start=1):
        if not isinstance(raw, Mapping):
            raise ValidationError(f"Secondary rendering events[{index}] must be an object", code="SECONDARY_REPORT_RENDERING_INVALID")
        event_id = str(raw.get("event_id") or "").strip()
        message = str(raw.get("message") or "").strip()
        next_action = str(raw.get("next_action") or "").strip()
        if not event_id or not message:
            raise ValidationError(f"Secondary rendering events[{index}] is incomplete", code="SECONDARY_REPORT_RENDERING_INVALID")
        if event_id in events:
            raise ValidationError(f"Duplicate secondary rendering event_id: {event_id}", code="SECONDARY_REPORT_RENDERING_INVALID")
        events[event_id] = {"message": message, "next_action": next_action}
    if set(events) != set(expected_event_ids):
        raise ValidationError("Secondary report rendering does not reconcile the exact execution-event inventory", code="SECONDARY_REPORT_RENDERING_INVALID")
    return rows, events


def _translation_schema(
    secondary_language: str,
    *,
    expected_ids: list[str],
    expected_event_ids: list[str],
) -> dict[str, Any]:
    """Build the exact one-item secondary-rendering response schema."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "secondary_language", "findings", "events"],
        "properties": {
            "schema_version": {"type": "string", "const": "1.0"},
            "secondary_language": {"type": "string", "const": secondary_language},
            "findings": {
                "type": "array",
                "minItems": len(expected_ids),
                "maxItems": len(expected_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["finding_id", "issue", "required_action"],
                    "properties": {
                        "finding_id": {"type": "string", "enum": expected_ids},
                        "issue": {"type": "string", "minLength": 1},
                        "required_action": {"type": "string"},
                    },
                },
            },
            "events": {
                "type": "array",
                "minItems": len(expected_event_ids),
                "maxItems": len(expected_event_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["event_id", "message", "next_action"],
                    "properties": {
                        "event_id": {"type": "string", "enum": expected_event_ids},
                        "message": {"type": "string", "minLength": 1},
                        "next_action": {"type": "string"},
                    },
                },
            },
        },
    }


def _translation_prompt(source: Mapping[str, Any]) -> str:
    """Render one provider prompt containing exactly one report item."""
    return "\n".join(
        [
            "SAGE ASSISTIVE SECONDARY REPORT RENDERING — ONE ITEM",
            "",
            "Render only the single supplied human-facing report item in the requested secondary language.",
            "The primary text is already governed and validated. Do not correct, reinterpret, summarize, expand, or add evidence.",
            "Preserve finding_id or event_id exactly. Preserve Scripture references, quoted source-language strings, IDs, codes, and technical tokens when they should remain unchanged.",
            "Preserve explicit Project IDs and GRK OL/HEB OL labels; do not replace them with generic source or reference terms.",
            "For a finding, render issue and required_action faithfully. For an event, render message and next_action faithfully. Preserve an empty action as empty.",
            "Return only JSON matching the supplied schema.",
            "",
            json.dumps(source, ensure_ascii=False, sort_keys=True),
        ]
    )


def ensure_secondary_saw_report_rendering(
    root: Path,
    report_path: Path,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach or generate one assistive secondary rendering without changing canonical findings.

    Failure to create the assistive secondary rendering never invalidates the governed
    primary report. Instead the report receives an explicit DEGRADED rendering status.
    """
    # Keep this orchestration linear: cache validation, provider rendering, then degraded fallback.
    result = deepcopy(dict(document))
    source_info = _translation_source(document)
    if source_info is None:
        result.pop("report_renderings", None)
        return result
    source, primary, secondary = source_info
    expected_ids = [row["finding_id"] for row in source["findings"]]
    expected_event_ids = [row["event_id"] for row in source.get("events", [])]
    expected_request_count = len(expected_ids) + len(expected_event_ids)
    source_sha256 = sha256_bytes(_canonical_bytes(source))
    cache_path = _rendering_path(root, report_path)
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if (
            isinstance(cached, dict)
            and cached.get("schema_version") == "1.0"
            and cached.get("source_sha256") == source_sha256
            and cached.get("primary_language") == primary
            and cached.get("secondary_language") == secondary
            and cached.get("status") == "AVAILABLE"
            and cached.get("rendering_unit") == "ONE_REPORT_ITEM_PER_PROVIDER_REQUEST"
            and cached.get("provider_request_count") == expected_request_count
            and isinstance(cached.get("findings"), dict)
            and set(cached["findings"]) == set(expected_ids)
            and isinstance(cached.get("events"), dict)
            and set(cached["events"]) == set(expected_event_ids)
        ):
            result["report_renderings"] = cached
            return result

    if local_ai_enabled(root):
        rejected = {
            "schema_version": "1.0",
            "status": "DEGRADED",
            "authority": "ASSISTIVE_TRANSLATION_ONLY",
            "primary_language": primary,
            "secondary_language": secondary,
            "source_sha256": source_sha256,
            "provider": None,
            "model": None,
            "reasoning_effort": None,
            "findings": {},
            "events": {},
            "reason_code": LOCAL_AI_EXTERNAL_RENDERING_REQUIRED,
            "diagnostic": (
                "Secondary rendering was rejected for this Job because it requires Hosted AI "
                "while Local AI is enabled; the governing primary report remains available."
            ),
        }
        atomic_write_json(cache_path, rejected)
        result["report_renderings"] = rejected
        return result

    settings = load_llm_settings(root)
    provider = str(settings.get("selected_provider") or "codex").strip().lower()
    item = dict((settings.get("providers") or {}).get(provider) or {})
    model = str(item.get("model") or "").strip() or None
    reasoning = str(item.get("reasoning_effort") or "").strip().lower() or None
    try:
        executor = make_executor(provider, settings)
        secondary_rows: dict[str, dict[str, str]] = {}
        secondary_events: dict[str, dict[str, str]] = {}
        responses = []
        item_sources = [
            {
                "primary_language": primary,
                "secondary_language": secondary,
                "findings": [row],
                "events": [],
            }
            for row in source["findings"]
        ] + [
            {
                "primary_language": primary,
                "secondary_language": secondary,
                "findings": [],
                "events": [row],
            }
            for row in source.get("events", [])
        ]
        for item_source in item_sources:
            item_ids = [row["finding_id"] for row in item_source["findings"]]
            item_event_ids = [row["event_id"] for row in item_source["events"]]
            response = executor.execute(
                ProviderRequest(
                    prompt=_translation_prompt(item_source),
                    schema=_translation_schema(
                        secondary,
                        expected_ids=item_ids,
                        expected_event_ids=item_event_ids,
                    ),
                    model=model,
                    reasoning_effort=reasoning,
                    timeout_seconds=300,
                )
            )
            item_rows, item_events = _parse_translation_response(
                response.content,
                secondary_language=secondary,
                expected_ids=item_ids,
                expected_event_ids=item_event_ids,
            )
            secondary_rows.update(item_rows)
            secondary_events.update(item_events)
            responses.append(response)
        if set(secondary_rows) != set(expected_ids) or set(secondary_events) != set(expected_event_ids):
            raise ValidationError(
                "Individually rendered report items do not reconcile the exact report inventory",
                code="SECONDARY_REPORT_RENDERING_INVALID",
            )
        response = responses[-1]
        receipt = {
            "schema_version": "1.0",
            "status": "AVAILABLE",
            "authority": "ASSISTIVE_TRANSLATION_ONLY",
            "primary_language": primary,
            "secondary_language": secondary,
            "source_sha256": source_sha256,
            "provider": response.provider,
            "model": response.model or model,
            "reasoning_effort": response.reasoning_effort or reasoning,
            "rendering_unit": "ONE_REPORT_ITEM_PER_PROVIDER_REQUEST",
            "provider_request_count": len(responses),
            "findings": secondary_rows,
            "events": secondary_events,
        }
        atomic_write_json(cache_path, receipt)
        result["report_renderings"] = receipt
        return result
    except (SageError, OSError, ValueError) as exc:
        degraded = {
            "schema_version": "1.0",
            "status": "DEGRADED",
            "authority": "ASSISTIVE_TRANSLATION_ONLY",
            "primary_language": primary,
            "secondary_language": secondary,
            "source_sha256": source_sha256,
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning,
            "findings": {},
            "events": {},
            "diagnostic": str(exc),
        }
        atomic_write_json(cache_path, degraded)
        result["report_renderings"] = degraded
        return result
