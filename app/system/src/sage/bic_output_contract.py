"""BIC provider output contract: model-facing JSON schemas and controller-owned materialization.

The model returns only semantic judgments. SAGE sets every identity, scope, fingerprint, hash,
language-list, and derived field after parsing, exactly as RTC and STC do for analysis findings.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .bic_memory import CHALLENGE_TYPES, RECORD_TYPES
from .errors import ValidationError
from .hashing import sha256_bytes
from .human_output import resolved_languages
from .registry import EcosystemConfig
from .rewrite_risk import (
    _ALLOWED_CATEGORIES,
    _ALLOWED_CONFIDENCE,
    _ALLOWED_REJECTION_CODES,
    _ALLOWED_TRIGGER_CODES,
)

INSPECT_FILE = "output/inspect-submission.json"
CHALLENGES_FILE = "output/translation-challenges.json"
GRAMMAR_FILE = "output/grammar-assessment.json"
CANDIDATE_FILES = {"rewrite": "output/rewrite.usfm", "self_check": "output/self-check.usfm"}
BIC_MODEL_FILES = frozenset({INSPECT_FILE, CHALLENGES_FILE, GRAMMAR_FILE})
_SCORE = {"type": "integer", "enum": [0, 1, 2, 3, 4]}
_STRING = {"type": "string"}


def _object(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Build one strict provider object: every property required, nothing additional."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": dict(properties),
    }


def _array(items: Mapping[str, Any]) -> dict[str, Any]:
    """Build one provider array schema."""
    return {"type": "array", "items": dict(items)}


def _enum(values: Any) -> dict[str, Any]:
    """Build one typed provider enum with a stable order."""
    return {"type": "string", "enum": sorted(values)}


def _prose(purpose: str, narrative_note: str) -> dict[str, str]:
    """Describe one generated-narrative field in the bound report language."""
    return {"type": "string", "description": f"{purpose} {narrative_note}"}


def reporting_languages(config: EcosystemConfig, manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Resolve the translation-challenge languages the validator will require for this task."""
    policy = config.human_output
    source = config.project(str(manifest.get("contemporary_source") or ""))
    target = config.project(str(manifest.get("output_project") or ""))
    return resolved_languages(
        policy.translation_challenges,
        operator_language=policy.operator_language,
        source_language=source.language_code,
        target_language=target.language_code,
    )


def _inspect_schema(narrative_note: str) -> dict[str, Any]:
    """Model contract for INSPECT: proposals and challenges, never identity."""
    return _object(
        {
            "proposals": _array(
                _object(
                    {
                        "record_type": _enum(RECORD_TYPES),
                        "payload_json": {
                            "type": "string",
                            "description": "One JSON object, serialized as text, holding the proposed record fields.",
                        },
                        "evidence_refs": _array(_STRING),
                    }
                )
            ),
            "challenges": _array(
                _object(
                    {
                        "scripture_reference": {
                            "type": "string",
                            "description": "One bounded Scripture reference inside the task scope.",
                        },
                        "challenge_type": _enum(CHALLENGE_TYPES),
                        "summary": _prose("State the translation challenge.", narrative_note),
                        "recommended_action": _prose("State the recommended action.", narrative_note),
                    }
                )
            ),
        }
    )


def _candidate_schema(narrative_note: str) -> dict[str, Any]:
    """One candidate rendering; familiarity is a tie-break rule, not a recorded score."""
    return _object(
        {
            "candidate_id": _STRING,
            "form": {"type": "string", "description": "The candidate rendering in the target language."},
            "meaning_features": _array(_STRING),
            "tone_and_force": _prose("Describe tone and force.", narrative_note),
            "register": _prose("Describe register.", narrative_note),
            "main_risk": _prose("State the main risk of this candidate.", narrative_note),
            "rejection_code": {
                "type": "string",
                "enum": ["", *sorted(_ALLOWED_REJECTION_CODES)],
                "description": "Empty unless this candidate is a rejected alternative.",
            },
            "rejection_reason": _prose(
                "Concise reason; empty unless this candidate is a rejected alternative.", narrative_note
            ),
        }
    )


def _challenges_schema(languages: tuple[str, ...], narrative_note: str) -> dict[str, Any]:
    """Model contract for REWRITE challenges; risk, OL referral, and totals are controller-owned."""
    challenge: dict[str, Any] = {
        "challenge_id": _STRING,
        "scripture_reference": {
            "type": "string",
            "description": "One bounded Scripture reference inside the task scope.",
        },
        "category": _enum(_ALLOWED_CATEGORIES),
        "summary": _prose("Summarize the challenge.", narrative_note),
        "confidence": _enum(_ALLOWED_CONFIDENCE),
        "candidates": _array(_candidate_schema(narrative_note)),
        "recommended_candidate_id": _STRING,
        "risk": _object(
            {
                "before_ol": _SCORE,
                "material_triggers": _array(_enum(_ALLOWED_TRIGGER_CODES)),
            }
        ),
        "inherited_challenge_ids": _array(_STRING),
        "recommended_action": _prose("State the recommended action.", narrative_note),
    }
    if languages != ("en",):
        message = _object(
            {
                "summary": _STRING,
                "risk": _STRING,
                "evidence": _STRING,
                "action": _STRING,
            }
        )
        challenge["messages"] = _object({language: message for language in languages})
    return _object(
        {
            "challenges": _array(_object(challenge)),
            "minor_summary": _object(
                {
                    "by_category": _object(
                        {category: {"type": "integer"} for category in sorted(_ALLOWED_CATEGORIES)}
                    ),
                    "notes": _array(_STRING),
                }
            ),
        }
    )


def _grammar_schema(rule_ids: list[str], narrative_note: str) -> dict[str, Any]:
    """Model contract for the grammar assessment: one verdict per profile rule."""
    rule_id = {"type": "string", "enum": rule_ids} if rule_ids else dict(_STRING)
    return _object(
        {
            "rules": _array(
                _object(
                    {
                        "rule_id": rule_id,
                        "status": {"type": "string", "enum": ["PASS", "NOT_APPLICABLE", "ISSUE"]},
                        "evidence": _prose("Evidence; required when status is ISSUE.", narrative_note),
                    }
                )
            ),
            "unresolved": _array(_STRING),
        }
    )


def file_schemas(
    config: EcosystemConfig, manifest: Mapping[str, Any], narrative_note: str
) -> dict[str, dict[str, Any]]:
    """Return the JSON schema for each BIC semantic file this task is allowed to write."""
    if str(manifest.get("workflow") or "").lower() != "bic":
        return {}
    allowed = {str(item) for item in manifest.get("allowed_writes", [])}
    schemas: dict[str, dict[str, Any]] = {}
    if INSPECT_FILE in allowed:
        schemas[INSPECT_FILE] = _inspect_schema(narrative_note)
    if CHALLENGES_FILE in allowed:
        schemas[CHALLENGES_FILE] = _challenges_schema(reporting_languages(config, manifest), narrative_note)
    if GRAMMAR_FILE in allowed:
        rule_ids = [str(item) for item in dict(manifest.get("project_grammar") or {}).get("rule_ids", [])]
        schemas[GRAMMAR_FILE] = _grammar_schema(rule_ids, narrative_note)
    return schemas


def assignment(config: EcosystemConfig, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the BIC-only controller assignment keys sent to the model."""
    allowed = {str(item) for item in manifest.get("allowed_writes", [])}
    result: dict[str, Any] = {
        "source_primary_references": manifest.get(
            "source_primary_references", manifest.get("expected_references", [])
        ),
        "target_scope": manifest.get("target_scope", manifest.get("scope")),
        "expected_output_references": manifest.get(
            "expected_output_references", manifest.get("expected_references", [])
        ),
        "marker_policy": manifest.get("marker_policy"),
    }
    rule_ids = list(dict(manifest.get("project_grammar") or {}).get("rule_ids", []))
    if GRAMMAR_FILE in allowed and rule_ids:
        result["grammar_rule_ids"] = rule_ids
    if CHALLENGES_FILE in allowed:
        result["reporting_languages"] = list(reporting_languages(config, manifest))
    return result


def _load_object(files: Mapping[str, str], path: str) -> dict[str, Any]:
    """Parse one provider JSON file into an object or fail as an invalid provider response."""
    try:
        value = json.loads(files[path])
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"BIC provider result {path} is not valid JSON: {exc}",
            code="LLM_PROVIDER_RESPONSE_INVALID",
        ) from exc
    if not isinstance(value, dict):
        raise ValidationError(
            f"BIC provider result {path} must be a JSON object",
            code="LLM_PROVIDER_RESPONSE_INVALID",
        )
    return value


def _dump(document: Mapping[str, Any]) -> str:
    """Serialize one governed JSON file."""
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _materialize_inspect(manifest: Mapping[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """Set INSPECT identity and bookkeeping; decode each proposal payload, dropping and reporting defective items."""
    proposals: list[dict[str, Any]] = []
    dropped_items: list[dict[str, Any]] = []
    for index, raw in enumerate(document.get("proposals") or [], start=1):
        if not isinstance(raw, dict):
            dropped_items.append(
                {
                    "collection": "proposals",
                    "index": index,
                    "submitted_id": f"P{index:04d}",
                    "code": "INSPECT_ITEM_INVALID",
                    "message": f"BIC INSPECT proposals[{index}] must be an object",
                }
            )
            continue
        row = {key: value for key, value in raw.items() if key != "payload_json"}
        if "payload_json" in raw:
            try:
                payload = json.loads(str(raw["payload_json"]))
            except json.JSONDecodeError as exc:
                dropped_items.append(
                    {
                        "collection": "proposals",
                        "index": index,
                        "submitted_id": f"P{index:04d}",
                        "code": "INSPECT_ITEM_INVALID",
                        "message": f"BIC INSPECT proposals[{index}].payload_json is not valid JSON: {exc}",
                    }
                )
                continue
            row["payload"] = payload
        proposals.append({"submitted_id": f"P{index:04d}", **row})
    challenges: list[dict[str, Any]] = []
    for index, raw in enumerate(document.get("challenges") or [], start=1):
        if isinstance(raw, dict):
            challenges.append({"submitted_id": f"C{index:04d}", **dict(raw)})
        else:
            dropped_items.append(
                {
                    "collection": "challenges",
                    "index": index,
                    "submitted_id": f"C{index:04d}",
                    "code": "INSPECT_ITEM_INVALID",
                    "message": f"BIC INSPECT challenges[{index}] must be an object",
                }
            )
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "operation_id": manifest.get("task_id"),
        "scope": manifest.get("scope"),
        "resource_fingerprints": dict(manifest.get("resource_fingerprints") or {}),
        "proposals": proposals,
        "challenges": challenges,
    }
    if dropped_items:
        result["dropped_items"] = dropped_items
    return result


def _materialize_grammar(
    manifest: Mapping[str, Any], document: dict[str, Any], output_sha256: str
) -> dict[str, Any]:
    """Bind the grammar assessment to the task, profile, and final candidate hash."""
    grammar = dict(manifest.get("project_grammar") or {})
    return {
        **{
            key: value
            for key, value in document.items()
            if key
            not in {"schema_version", "task_id", "scope", "profile_id", "profile_sha256", "output_sha256"}
        },
        "schema_version": "1.0",
        "task_id": manifest.get("task_id"),
        "scope": manifest.get("scope"),
        "profile_id": grammar.get("profile_id", ""),
        "profile_sha256": grammar.get("profile_sha256", ""),
        "output_sha256": output_sha256,
    }


def _materialize_challenges(
    config: EcosystemConfig,
    manifest: Mapping[str, Any],
    document: dict[str, Any],
    output_sha256: str,
) -> dict[str, Any]:
    """Set challenge-ledger identity and every locally derived field.

    Idempotent over an OL micro merge: a merged ``after_ol`` and a performed (or recorded-unavailable)
    ``ol_referral`` are kept.
    """
    challenges: list[dict[str, Any]] = []
    for raw in document.get("challenges") or []:
        if not isinstance(raw, dict):
            raise ValidationError(
                "BIC challenge rows must be objects", code="LLM_PROVIDER_RESPONSE_INVALID"
            )
        row = dict(raw)
        risk = dict(row.get("risk") or {})
        before = risk.get("before_ol")
        risk["after_ol"] = risk.get("after_ol", before)
        risk["urgency"] = risk["after_ol"]
        row["risk"] = risk
        row["selected_candidate_id"] = row.get("recommended_candidate_id")
        referral = row.get("ol_referral")
        kept = isinstance(referral, dict) and (
            referral.get("performed") is True
            or (referral.get("performed") is False and referral.get("unavailable") is True)
        )
        row["ol_referral"] = referral if kept else {"performed": False}
        challenges.append(row)
    minor = dict(document.get("minor_summary") or {})
    by_category = {
        str(key): int(value)
        for key, value in dict(minor.get("by_category") or {}).items()
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    minor = {
        "total": sum(by_category.values()),
        "by_category": by_category,
        "notes": list(minor.get("notes") or []),
    }
    return {
        "schema_version": "1.3",
        "task_id": manifest.get("task_id"),
        "operation": manifest.get("operation"),
        "scope": manifest.get("scope"),
        "output_sha256": output_sha256,
        "reporting_languages": list(reporting_languages(config, manifest)),
        "minor_summary": minor,
        "challenges": challenges,
    }


def materialize_files(
    config: EcosystemConfig, manifest: Mapping[str, Any], files: Mapping[str, str]
) -> dict[str, str]:
    """Return provider files with every controller-owned BIC field set from the sealed task."""
    result = dict(files)
    if str(manifest.get("workflow") or "").lower() != "bic":
        return result
    if INSPECT_FILE in result:
        result[INSPECT_FILE] = _dump(_materialize_inspect(manifest, _load_object(result, INSPECT_FILE)))
    candidate_path = CANDIDATE_FILES.get(str(manifest.get("operation") or "").lower())
    if GRAMMAR_FILE in result or CHALLENGES_FILE in result:
        if candidate_path is None or candidate_path not in result:
            raise ValidationError(
                "BIC grammar and challenge files need the final USFM candidate to bind their hash",
                code="LLM_PROVIDER_RESPONSE_INVALID",
            )
        candidate_hash = sha256_bytes(result[candidate_path].encode("utf-8"))
        if GRAMMAR_FILE in result:
            result[GRAMMAR_FILE] = _dump(
                _materialize_grammar(manifest, _load_object(result, GRAMMAR_FILE), candidate_hash)
            )
        if CHALLENGES_FILE in result:
            result[CHALLENGES_FILE] = _dump(
                _materialize_challenges(
                    config, manifest, _load_object(result, CHALLENGES_FILE), candidate_hash
                )
            )
    return result
