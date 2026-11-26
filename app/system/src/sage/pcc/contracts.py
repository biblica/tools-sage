"""PCC record contracts and their validator.

The PCC handover ships JSON Schema 2020-12 contracts. SAGE keeps ``jsonschema`` as a development
dependency only (plan D8), so the contracts are restated here in the same schema vocabulary and
checked by a small validator that covers exactly the keywords they use. Tests cross-check these
specs against the handover schemas with the real ``jsonschema`` package.

SAGE adaptations (plan §3/§4, recorded in the plan's deviations):

* ``brief_id`` becomes ``job_id``: SAGE has no Translation Brief; the PCC Job binds SOURCE authority.
* ``review_event`` gains ``target_language`` and ``policy_version``, which handover doc 04 requires
  but its schema omitted, and ``previous_event_id``, which chains the append-only journal.
* ``run_manifest`` and ``summary`` gain ``operation`` and allow no TARGET (a ``terms`` Run has none).
* The handover ``config`` is replaced by the sealed ``run_snapshot``; Job defaults hold the settings.
* ``corpus_manifest`` is the phrase-index manifest (``index_manifest``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..errors import ValidationError

SCHEMA_VERSION = 1

_SHA256 = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_TEXT = {"type": "string", "minLength": 1}
_TEXT_OR_NULL = {"type": ["string", "null"]}
_TEXT_LIST = {"type": "array", "items": _TEXT}
_UNIT = {"oneOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]}
_COUNT = {"type": "integer", "minimum": 0}
_VERSION = {"const": SCHEMA_VERSION}

FINDING_CODES = (
    "PC00", "PC01", "PC02",
    "PC10", "PC11", "PC12", "PC13",
    "PC20", "PC21", "PC22",
    "PC23", "PC24", "PC25",
)
BLOCKING_CODES = frozenset({"PC23", "PC24", "PC25"})
SCOPE_LEVELS = ("OCCURRENCE", "PASSAGE", "SECG", "LANGUAGE_PROFILE", "NORMALIZATION")
# STALE (plan D16, P7-3): the rule's concept or sense is gone from the pinned reference list; listed for
# re-review, never deleted, never accepting.
RULE_STATES = ("PROPOSED", "APPROVED", "REVOKED", "STALE")
EFFECTS = ("ACCEPT", "REJECT", "CONTEXT_ONLY")
REVIEW_OPERATIONS = (
    "PROPOSE", "APPROVE", "REJECT", "CONTEXT_ONLY", "REVOKE", "RECLASSIFY_SENSE", "CORRECT_ALIGNMENT",
    "MARK_STALE", "CONFIRM_ISSUE", "DISMISS", "DEFER",
)
REVIEW_SUBJECTS = ("VARIANT_RULE", "EXCEPTION", "OCCURRENCE", "ALIGNMENT", "FINDING")
RUN_OPERATIONS = ("terms", "check")

_SCOPE = {
    "type": "object",
    "properties": {"level": {"type": "string", "enum": list(SCOPE_LEVELS)}, "identifier": _TEXT},
    "required": ["level", "identifier"],
    "additionalProperties": False,
}


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Return a closed object spec; every property is required unless ``required`` is given."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


CONTRACTS: dict[str, dict[str, Any]] = {
    "expression": _object({
        "schema_version": _VERSION,
        "expression_id": _TEXT,
        "source_corpus_id": _TEXT,
        "source_surface": _TEXT,
        "normalized_source_form": _TEXT,
        "origin": {"type": "string", "enum": ["AUTHORIZED_REFERENCE", "SOURCE_DISCOVERY", "LOCAL_INPUT"]},
        "category": {
            "type": "string",
            "enum": ["TERM", "FIXED_PHRASE", "IDIOM", "FORMULA", "COLLOCATION", "OTHER"],
        },
        "senses": {
            "type": "array",
            "minItems": 1,
            "items": _object({
                "sense_id": _TEXT,
                "label": _TEXT,
                "discriminator": _TEXT,
                "review_state": {"type": "string", "enum": ["CURATED", "REVIEWED", "PROVISIONAL"]},
            }),
        },
    }),
    "occurrence": _object(
        {
            "schema_version": _VERSION,
            "occurrence_id": _TEXT,
            "expression_id": _TEXT,
            "source_corpus_id": _TEXT,
            "source_corpus_sha256": _SHA256,
            "source_unit_id": _TEXT,
            "canonical_ref": _TEXT,
            "native_refs": {"type": "array", "items": _TEXT, "minItems": 1},
            "body_start": {"type": "integer", "minimum": 0},
            "body_end": {"type": "integer", "minimum": 1},
            "offset_units": {"const": "UNICODE_CODE_POINT"},
            "source_text_span": _TEXT,
            "sense_id": _TEXT_OR_NULL,
            "sense_state": {"type": "string", "enum": ["CONFIRMED", "PROVISIONAL", "UNRESOLVED"]},
            "sense_evidence": {"type": "array", "items": {"type": "string"}},
        },
        required=[
            "schema_version", "occurrence_id", "expression_id", "source_corpus_id", "source_corpus_sha256",
            "source_unit_id", "canonical_ref", "native_refs", "body_start", "body_end", "offset_units",
            "source_text_span", "sense_id", "sense_state",
        ],
    ),
    "alignment": _object(
        {
            "schema_version": _VERSION,
            "alignment_id": _TEXT,
            "source_occurrence_id": _TEXT,
            "target_corpus_id": _TEXT,
            "status": {"type": "string", "enum": ["CONFIRMED", "PROVISIONAL", "UNRESOLVED"]},
            "target_spans": {
                "type": "array",
                "items": _object({
                    "target_unit_id": _TEXT,
                    "canonical_ref": _TEXT,
                    "body_start": {"type": "integer", "minimum": 0},
                    "body_end": {"type": "integer", "minimum": 1},
                    "text_span": _TEXT,
                }),
            },
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        required=["schema_version", "alignment_id", "source_occurrence_id", "target_corpus_id", "status",
                  "target_spans"],
    ),
    "variant_rule": _object(
        {
            "schema_version": _VERSION,
            "rule_id": _TEXT,
            "group_id": _TEXT,
            "target_language": _TEXT,
            "target_form": _TEXT,
            "normalized_target_form": _TEXT,
            "type": {
                "type": "string",
                "enum": ["EXACT", "MORPHOLOGICAL", "SYNTACTIC", "SEMANTIC_VARIANT", "CULTURAL_EQUIVALENT",
                         "DISCOURSE_ADAPTATION"],
            },
            "effect": {"type": "string", "enum": list(EFFECTS)},
            "state": {"type": "string", "enum": list(RULE_STATES)},
            "scope": _SCOPE,
            "protected_features": {"type": "array", "items": _TEXT, "uniqueItems": True},
            "rationale": _TEXT,
            "evidence_refs": _TEXT_LIST,
            "approved_by": _TEXT_OR_NULL,
            "approved_at_utc": _TEXT_OR_NULL,
        },
        required=["schema_version", "rule_id", "group_id", "target_language", "target_form",
                  "normalized_target_form", "type", "effect", "state", "scope", "protected_features",
                  "rationale", "evidence_refs"],
    ),
    "exception": _object(
        {
            "schema_version": _VERSION,
            "exception_id": _TEXT,
            "kind": {
                "type": "string",
                "enum": ["MORPHOLOGICAL", "SYNTACTIC", "SEMANTIC_VARIANT", "CULTURAL_EQUIVALENT",
                         "DISCOURSE_ADAPTATION", "ALIGNMENT_CORRECTION", "SENSE_RECLASSIFICATION",
                         "FALSE_POSITIVE"],
            },
            "effect": {"type": "string", "enum": list(EFFECTS)},
            "state": {"type": "string", "enum": list(RULE_STATES)},
            "scope": _SCOPE,
            "reason": _TEXT,
            "subject_ids": {"type": "array", "items": _TEXT, "minItems": 1},
            "dependencies": _object({
                "source_corpus_sha256": _SHA256,
                "target_corpus_sha256": _SHA256,
                "profile_version": _TEXT,
                "policy_version": _TEXT,
            }),
            "reviewer_id": _TEXT_OR_NULL,
            "reviewed_at_utc": _TEXT_OR_NULL,
        },
        required=["schema_version", "exception_id", "kind", "effect", "state", "scope", "reason",
                  "subject_ids", "dependencies"],
    ),
    "finding": _object({
        "schema_version": _VERSION,
        "finding_id": _TEXT,
        "run_id": _TEXT,
        "code": {"type": "string", "enum": list(FINDING_CODES)},
        "review_status": {
            "type": "string",
            "enum": ["RESOLVED", "OPEN", "IN_REVIEW", "APPROVED_VARIANT", "CONFIRMED_ISSUE", "DISMISSED",
                     "DEFERRED", "STALE"],
        },
        "severity": {"type": "string", "enum": ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]},
        "is_blocking": {"type": "boolean"},
        "detection_confidence": _UNIT,
        "semantic_confidence": _UNIT,
        "group_id": _TEXT_OR_NULL,
        "issue_cluster_id": _TEXT,
        "source_occurrence_ids": _TEXT_LIST,
        "source_refs": _TEXT_LIST,
        "target_refs": _TEXT_LIST,
        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "applied_rule_ids": _TEXT_LIST,
        "reason": _TEXT,
    }),
    "occurrence_audit": _object({
        "schema_version": _VERSION,
        "run_id": {"type": "string"},
        "occurrence_id": {"type": "string"},
        "group_id": {"type": "string"},
        "disposition": {"enum": ["EVALUATED", "REVIEW", "INFORMATIONAL", "BLOCKED"]},
        "result_code": {"enum": list(FINDING_CODES)},
        "reason": {"type": "string"},
    }),
    "review_event": _object({
        "schema_version": _VERSION,
        "event_id": _TEXT,
        "time_utc": _TEXT,
        "actor_id": _TEXT,
        "operation": {"type": "string", "enum": list(REVIEW_OPERATIONS)},
        "subject_type": {"type": "string", "enum": list(REVIEW_SUBJECTS)},
        "subject_id": _TEXT,
        "rationale": _TEXT,
        "before_hash": _TEXT_OR_NULL,
        "after_hash": _TEXT_OR_NULL,
        "evidence_refs": _TEXT_LIST,
        "job_id": _TEXT,
        "source_corpus_sha256": _SHA256,
        "target_language": _TEXT,
        "policy_version": _TEXT,
        "scope": _SCOPE,
        "previous_event_id": _TEXT_OR_NULL,
    }),
    "run_manifest": _object({
        "schema_version": _VERSION,
        "run_id": _TEXT,
        "created_utc": _TEXT,
        "job_id": _TEXT,
        "operation": {"type": "string", "enum": list(RUN_OPERATIONS)},
        "source_corpus_id": _TEXT,
        "target_corpus_id": _TEXT_OR_NULL,
        "source_corpus_sha256": _SHA256,
        "target_corpus_sha256": {"oneOf": [_SHA256, {"type": "null"}]},
        "reference_index_version": _TEXT_OR_NULL,
        "profile_version": _TEXT,
        "config_sha256": _SHA256,
        "decision_snapshot_sha256": _SHA256,
        "engine_version": _TEXT,
        "semantic_review_mode": {"type": "string", "enum": ["OFF", "ADVISORY"]},
    }),
    "summary": _object({
        "schema_version": _VERSION,
        "run_id": _TEXT,
        "operation": {"type": "string", "enum": list(RUN_OPERATIONS)},
        "source_corpus_id": _TEXT,
        "target_corpus_id": _TEXT_OR_NULL,
        "eligible_groups": _COUNT,
        "evaluated_groups": _COUNT,
        "fully_resolved_groups": _COUNT,
        "eligible_occurrences": _COUNT,
        "evaluated_occurrences": _COUNT,
        "review_groups": _COUNT,
        "blocked_groups": _COUNT,
        "findings_by_code": {
            "type": "object",
            "propertyNames": {"pattern": "^PC[0-9]{2}$"},
            "additionalProperties": _COUNT,
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
        # check Runs only (P8): distinct issues (linked findings count once) and reverse-scan dispositions
        "issue_clusters": _COUNT,
        "reverse_scan": {"type": "object", "propertyNames": {"pattern": "^[A-Z_]+$"}, "additionalProperties": _COUNT},
    }, required=["schema_version", "run_id", "operation", "source_corpus_id", "target_corpus_id", "eligible_groups",
                 "evaluated_groups", "fully_resolved_groups", "eligible_occurrences", "evaluated_occurrences",
                 "review_groups", "blocked_groups", "findings_by_code", "limitations"]),
    "language_profile": _object({
        "schema_version": _VERSION,
        "profile_id": _TEXT,
        "profile_version": _TEXT,
        "language_tag": _TEXT,
        "normalization": _object({
            "unicode_form": {"const": "NFC"},
            "case_mode": {"type": "string", "enum": ["PRESERVE", "LANGUAGE_AWARE"]},
            "strip_diacritics": {"type": "boolean"},
            "fold_whitespace": {"type": "boolean"},
        }),
        "segmentation": _object(
            {
                "method": {
                    "type": "string",
                    "enum": ["WHITESPACE_TEST_ONLY", "SAGE_EXISTING_TOKENIZER", "LANGUAGE_SPECIFIC"],
                },
                "tokenizer_id": _TEXT,
            },
            required=["method"],
        ),
        "protected_features": {
            "type": "array",
            "uniqueItems": True,
            "items": {
                "type": "string",
                "enum": ["NEGATION", "POLARITY", "AGENCY", "NUMBER", "MODALITY", "PARTICIPANT_ROLES",
                         "REFERENCE", "POSSESSION", "ASPECT"],
            },
        },
        "capabilities": _object({
            "morphology": {"type": "string", "enum": ["NONE", "RULES", "ANALYZER"]},
            "syntax": {"type": "string", "enum": ["NONE", "RULES", "PARSER"]},
            "semantic_review": {"type": "string", "enum": ["NONE", "EXISTING_SAGE_ADAPTER"]},
        }),
    }),
    "index_manifest": _object(
        {
            "schema_version": _VERSION,
            "index_version": _TEXT,
            "index_kind": {"type": "string", "enum": ["AUTHORIZED_REFERENCE", "PROJECT_SYNTHETIC"]},
            "corpora": {
                "type": "array",
                "minItems": 1,
                "items": _object(
                    {
                        "corpus_id": _TEXT,
                        "edition": _TEXT,
                        "language_tag": _TEXT,
                        "role": {"type": "string", "enum": ["PRIMARY_SOURCE", "SECONDARY_SOURCE", "TARGET"]},
                        "content_sha256": _SHA256,
                        "versification_id": _TEXT,
                        "license_id": _TEXT,
                        "native_reference_style": _TEXT,
                    },
                    required=["corpus_id", "edition", "language_tag", "role", "content_sha256",
                              "versification_id", "license_id"],
                ),
            },
            "expression_file": _TEXT,
            "occurrence_file": _TEXT,
            "index_notes": {"type": "string"},
            "expression_sha256": _SHA256,
            "occurrence_sha256": _SHA256,
        },
        required=["schema_version", "index_version", "index_kind", "corpora", "expression_file",
                  "occurrence_file", "expression_sha256", "occurrence_sha256"],
    ),
}

_DISCOVERY = _object({
    "min_confirmed_same_sense_occurrences": {"type": "integer", "minimum": 2},
    "min_ngram_tokens": {"type": "integer", "minimum": 1},
    "max_ngram_tokens": {"type": "integer", "minimum": 1},
})
_ANALYSIS = _object({
    "semantic_assistance": {"type": "string", "enum": ["OFF"]},
    "reverse_detection": {"type": "string", "enum": ["OFF", "REVIEW_PROBABLE_ADDITIONS"]},
    "audit_level": {"type": "string", "enum": ["SUMMARY", "FULL"]},
})
_PROJECT_IDENTITY = _object({
    "project_id": _TEXT,
    "language_tag": _TEXT,
    "content_sha256": _SHA256,
    "versification_sha256": _SHA256,
})

# A Job's pin of one reference-list version (plan D16): the package is re-checked against ``sha256`` (the
# SHA-256 of its CHECKSUMS.sha256) whenever a Run seals or executes.
RL_PIN = _object({
    "rl_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*-[a-f0-9]{8}$"},
    "version": {"type": "integer", "minimum": 1},
    "sha256": _SHA256,
})

# The Job's editable defaults (Job manifest ``defaults``). ``semantic_assistance`` accepts only
# ``OFF`` until the optional advisory step (plan P10) exists.
CONTRACTS["job_defaults"] = _object({
    "target_language": _TEXT,
    "discovery": _DISCOVERY,
    "analysis": _ANALYSIS,
    "reference_list": {"oneOf": [RL_PIN, {"type": "null"}]},
})

# The sealed per-Run policy snapshot; it replaces the handover's ``config.json``.
CONTRACTS["run_snapshot"] = _object({
    "schema_version": _VERSION,
    "run_id": _TEXT,
    "job_id": _TEXT,
    "operation": {"type": "string", "enum": list(RUN_OPERATIONS)},
    "scope": _TEXT,
    "source": _PROJECT_IDENTITY,
    "secondary_source": {"oneOf": [_PROJECT_IDENTITY, {"type": "null"}]},
    "target": {"oneOf": [_PROJECT_IDENTITY, {"type": "null"}]},
    "target_language": _TEXT,
    "source_authority": {"type": "string", "enum": ["SINGLE_SOURCE", "PRIMARY_CONTROLS"]},
    "discovery": _DISCOVERY,
    "analysis": _ANALYSIS,
    "decision_snapshot_sha256": _SHA256,
    "reference_list": {"oneOf": [_object({**RL_PIN["properties"], "reference_content_sha256": _SHA256}),
                                 {"type": "null"}]},
    "engine_version": _TEXT,
    "created_utc": _TEXT,
})

# Reference lists (plan §5b, D12-D19): one versioned package per REFERENCE edition, built outside any Job.
RL_STATUSES = ("ACTIVE", "PROPOSED", "DROPPED")
RL_BUILD_MODES = ("SCRATCH", "INHERIT", "MERGE", "IMPORT")
# SENSE: a reference sense (D19) that recurs; OTHER: renderings too rare to be a sense, kept as evidence only.
RL_SENSE_KINDS = ("SENSE", "OTHER")
# Per concept: original-language occurrences in the reference, how many were realized by a wording, rendered
# only by function words (pronoun, article), or left without any aligned token; links by alignment method.
RL_REALIZATION_COUNTS = ("occurrences", "realized", "function_only", "no_realization",
                         "gold", "transitive", "direct", "located")
_RL_REF = _object({"rl_id": _TEXT, "version": {"type": "integer", "minimum": 1}})
CONTRACTS["reference_list_manifest"] = _object({
    "schema_version": _VERSION,
    "rl_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*-[a-f0-9]{8}$"},
    "version": {"type": "integer", "minimum": 1},
    "title": _TEXT,
    "reference": _object({
        "project_id": _TEXT,
        "edition": _TEXT,
        "language_tag": _TEXT,
        "content_sha256": _SHA256,
        "versification_id": _TEXT,
    }),
    "license": _object({"license_id": _TEXT, "local_only": {"type": "boolean"}, "note": {"type": "string"}}),
    "build": _object({
        "mode": {"type": "string", "enum": list(RL_BUILD_MODES)},
        "base_version": {"oneOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]},
        "derived_from": {"oneOf": [_RL_REF, {"type": "null"}]},
        "imported_from": {"oneOf": [_RL_REF, {"type": "null"}]},
        "engine_version": _TEXT,
        "settings": {"type": "object"},
        "summary": {"type": "object"},
    }),
    "counts": _object({status.lower(): _COUNT for status in RL_STATUSES} | {"entries": _COUNT}),
    "entries_sha256": _SHA256,
    "created_utc": _TEXT,
})
_RL_WORDING = _object({"wording": _TEXT, "verses": _COUNT})
CONTRACTS["reference_list_entry"] = _object({
    "concept_key": {"type": "string", "pattern": "^CPT-[a-f0-9]{16}$"},
    "anchor": _object({"kind": {"type": "string", "enum": ["OL", "BT", "WORDING"]},
                       "value": {"type": "array", "items": _TEXT, "minItems": 1}}),
    "label": _TEXT,
    "category": _TEXT,
    "status": {"type": "string", "enum": list(RL_STATUSES)},
    "origin": _TEXT,
    "sources": _TEXT_LIST,
    "senses": {"type": "array", "items": _object({
        "sense_key": {"type": "string", "pattern": "^CSN-[a-f0-9]{16}$"},
        "kind": {"type": "string", "enum": list(RL_SENSE_KINDS)},
        "label": _TEXT,
        "wordings": {"type": "array", "items": _RL_WORDING},
        "verses": _COUNT,
        "examples": {"type": "array", "items": _TEXT},
        "ol_senses": _TEXT_LIST,
        "state": {"type": "string", "enum": ["PROPOSED", "CONFIRMED"]},
    })},
    "realization": _object({name: _COUNT for name in RL_REALIZATION_COUNTS}),
    "verses": _COUNT,
    "examples": {"type": "array", "items": _TEXT},
    "notes": {"type": "string"},
})

RECORD_KINDS = tuple(sorted(CONTRACTS))

_TYPE_CHECKS = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "object": lambda value: isinstance(value, Mapping),
    "array": lambda value: isinstance(value, list),
    "null": lambda value: value is None,
}


def _errors(spec: Mapping[str, Any], value: Any, path: str) -> list[str]:
    """Return every contract violation of ``value`` at ``path`` (empty when valid)."""
    if "oneOf" in spec:
        matches = sum(1 for option in spec["oneOf"] if not _errors(option, value, path))
        return [] if matches == 1 else [f"{path}: must match exactly one allowed form"]
    if "const" in spec and (value != spec["const"] or type(value) is not type(spec["const"])):
        return [f"{path}: must be {spec['const']!r}"]
    if "enum" in spec and value not in spec["enum"]:
        return [f"{path}: {value!r} is not one of {', '.join(map(str, spec['enum']))}"]
    expected = spec.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_TYPE_CHECKS[name](value) for name in names):
            return [f"{path}: must be {' or '.join(names)}"]
    found: list[str] = []
    if isinstance(value, str):
        if len(value) < spec.get("minLength", 0):
            found.append(f"{path}: must not be empty")
        if "pattern" in spec and not re.search(spec["pattern"], value):
            found.append(f"{path}: does not match {spec['pattern']}")
    if _TYPE_CHECKS["number"](value):
        if "minimum" in spec and value < spec["minimum"]:
            found.append(f"{path}: must be at least {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            found.append(f"{path}: must be at most {spec['maximum']}")
    if isinstance(value, list):
        if len(value) < spec.get("minItems", 0):
            found.append(f"{path}: needs at least {spec['minItems']} item(s)")
        if spec.get("uniqueItems") and len({repr(item) for item in value}) != len(value):
            found.append(f"{path}: items must be unique")
        if "items" in spec:
            for index, item in enumerate(value):
                found.extend(_errors(spec["items"], item, f"{path}[{index}]"))
    if isinstance(value, Mapping):
        properties = spec.get("properties", {})
        for name in spec.get("required", []):
            if name not in value:
                found.append(f"{path}.{name}: is required")
        for name, item in value.items():
            key = str(name)
            if "propertyNames" in spec:
                found.extend(_errors(spec["propertyNames"], key, f"{path}.{key} (name)"))
            if key in properties:
                found.extend(_errors(properties[key], item, f"{path}.{key}"))
            elif spec.get("additionalProperties") is False:
                found.append(f"{path}.{key}: is not allowed")
            elif isinstance(spec.get("additionalProperties"), Mapping):
                found.extend(_errors(spec["additionalProperties"], item, f"{path}.{key}"))
    return found


def contract_errors(kind: str, record: Any) -> list[str]:
    """Return the violations of one record against the named PCC contract."""
    try:
        spec = CONTRACTS[kind]
    except KeyError as exc:
        raise ValidationError(f"Unknown PCC record kind: {kind}", code="PCC_CONTRACT_UNKNOWN") from exc
    return _errors(spec, record, kind)


def validate_record(kind: str, record: Any, *, where: str | None = None) -> dict[str, Any]:
    """Return ``record`` when it satisfies its contract, else raise with every violation listed."""
    errors = contract_errors(kind, record)
    if errors:
        location = f" ({where})" if where else ""
        raise ValidationError(
            f"PCC {kind} record is invalid{location}: {errors[0]}"
            + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""),
            code="PCC_CONTRACT_INVALID",
            details={"kind": kind, "where": where, "errors": errors},
        )
    return dict(record)
