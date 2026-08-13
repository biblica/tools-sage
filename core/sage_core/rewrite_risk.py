"""Validate REWRITE lexical burden, controller-derived OL referrals, and concise risk reporting."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import ValidationError
from .hashing import sha256_file
from .human_output import (
    HumanOutputSpec,
    TranslationChallengeChannel,
    catalogue_text,
    message_for_languages,
    paired_catalogue_text,
    parse_human_output,
    resolved_languages,
)
from .references import ScriptureScope, parse_scope
from .vrs import VerseRef

_ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
_ALLOWED_CATEGORIES = {
    "VERB_CHOICE",
    "LEXICAL_SENSE",
    "SEMANTIC_FORCE",
    "TENSE_ASPECT_MOOD",
    "VOICE_AGENCY",
    "PARTICIPANT_RELATION",
    "DISCOURSE_FUNCTION",
    "REGISTER",
    "OTHER",
}
_ALLOWED_TRIGGER_CODES = {
    "COMPETING_NON_EQUIVALENT_SENSES",
    "POSSIBLE_FORCE_CHANGE",
    "POSSIBLE_AGENCY_CHANGE",
    "POSSIBLE_PARTICIPANT_CHANGE",
    "POSSIBLE_ASPECT_OR_MODALITY_CHANGE",
    "SOURCE_REFERENCE_TENSION",
    "DISCOURSE_DEPENDENCY",
    "SIGNIFICANT_PROJECT_CONCEPT",
}
_ALLOWED_LONGMAN_BANDS = {"S1", "S2", "S3", "W1", "W2", "W3", "L3000", "L6000", "L9000", "UNLISTED", "UNKNOWN"}
_ALLOWED_EVIDENCE_SOURCES = {"LONGMAN", "PROJECT_CORPUS", "AUDIENCE_TEST", "LEXICOGRAPHIC", "PROJECT_ESTIMATE", "UNKNOWN"}
_ALLOWED_REJECTION_CODES = {
    "MEANING_LOSS",
    "FORCE_WEAKENED",
    "FORCE_INTENSIFIED",
    "WRONG_SENSE",
    "AGENCY_CHANGED",
    "PARTICIPANT_RELATION_CHANGED",
    "TAM_CHANGED",
    "REGISTER_MISMATCH",
    "AMBIGUITY_INTRODUCED",
    "TERMINOLOGY_CONFLICT",
    "LESS_ACCESSIBLE_WITH_NO_SEMANTIC_GAIN",
    "OL_EVIDENCE_DISFAVOURS",
    "OTHER_MATERIAL_LOSS",
}

_LONGMAN_SCORE = {
    "S1": 0,
    "S2": 1,
    "S3": 2,
    "W1": 0,
    "W2": 1,
    "W3": 2,
    "L3000": 2,
    "L6000": 3,
    "L9000": 4,
    "UNLISTED": 4,
}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    """Require one JSON object and preserve its submitted fields for deterministic checks."""
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return dict(value)


def _text(value: Any, label: str, *, maximum: int = 4000) -> str:
    """Require one non-empty bounded text field."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a nonempty string")
    result = value.strip()
    if len(result) > maximum:
        raise ValidationError(f"{label} exceeds {maximum} characters")
    return result


def _score(value: Any, label: str) -> int:
    """Require an integer score on the governed zero-to-four scale."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 4:
        raise ValidationError(f"{label} must be an integer from 0 to 4")
    return value


def _string_list(value: Any, label: str, *, allowed: set[str] | None = None) -> list[str]:
    """Validate a unique list of non-empty strings and optionally restrict its values."""
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"{label} must be a list of nonempty strings")
    result = [item.strip().upper() for item in value]
    if len(result) != len(set(result)):
        raise ValidationError(f"{label} contains duplicate values")
    if allowed is not None and set(result) - allowed:
        raise ValidationError(f"{label} contains unsupported values: {', '.join(sorted(set(result) - allowed))}")
    return result


def _scope_contains(parent: ScriptureScope, value: str) -> bool:
    """Return whether one challenge reference remains inside the immutable task scope."""
    child = parse_scope(value)
    if child.book != parent.book:
        return False
    if child.start_chapter is None:
        return parent.start_chapter is None
    start_verse = child.start_verse or 1
    end_chapter = child.end_chapter or child.start_chapter
    end_verse = child.end_verse or (9999 if child.start_verse is None else child.start_verse)
    return parent.contains(VerseRef(child.book, child.start_chapter, start_verse)) and parent.contains(
        VerseRef(child.book, end_chapter, end_verse)
    )



def longman_familiarity_score(bands: Sequence[str]) -> int | None:
    """Return the governed spoken-first familiarity score for licensed Longman bands."""
    normalised = {str(item).strip().upper() for item in bands}
    spoken = [band for band in ("S1", "S2", "S3") if band in normalised]
    if spoken:
        return min(_LONGMAN_SCORE[band] for band in spoken)
    written = [band for band in ("W1", "W2", "W3") if band in normalised]
    if written:
        return min(_LONGMAN_SCORE[band] for band in written)
    ranked = [band for band in ("L3000", "L6000", "L9000", "UNLISTED") if band in normalised]
    if ranked:
        return min(_LONGMAN_SCORE[band] for band in ranked)
    return None

def lexical_burden_total(components: Mapping[str, int]) -> int:
    """Return the rounded governed burden score from the five component ratings."""
    weighted = (
        0.40 * components["familiarity"]
        + 0.15 * components["register_markedness"]
        + 0.15 * components["sense_ambiguity"]
        + 0.15 * components["construction_burden"]
        + 0.15 * components["specialist_load"]
    )
    return min(4, max(0, int(math.floor(weighted + 0.5))))


def _validate_candidate(raw: Any, label: str) -> dict[str, Any]:
    """Validate one proposed verb or construction while deriving arithmetic locally."""
    row = _mapping(raw, label)
    candidate_id = _text(row.get("candidate_id"), f"{label}.candidate_id", maximum=80)
    form = _text(row.get("form"), f"{label}.form", maximum=160)
    components_raw = _mapping(row.get("lexical_burden"), f"{label}.lexical_burden")
    components = {
        key: _score(components_raw.get(key), f"{label}.lexical_burden.{key}")
        for key in (
            "familiarity",
            "register_markedness",
            "sense_ambiguity",
            "construction_burden",
            "specialist_load",
        )
    }
    expected_total = lexical_burden_total(components)
    if "overall" in components_raw:
        supplied_total = _score(components_raw.get("overall"), f"{label}.lexical_burden.overall")
        if supplied_total != expected_total:
            raise ValidationError(
                f"{label}.lexical_burden.overall must equal the locally derived weighted score {expected_total}"
            )
    frequency = _mapping(row.get("frequency_evidence"), f"{label}.frequency_evidence")
    source = str(frequency.get("source", "")).strip().upper()
    if source not in _ALLOWED_EVIDENCE_SOURCES:
        raise ValidationError(f"{label}.frequency_evidence.source is unsupported: {source}")
    bands = _string_list(
        frequency.get("bands", []),
        f"{label}.frequency_evidence.bands",
        allowed=_ALLOWED_LONGMAN_BANDS,
    )
    longman_score = longman_familiarity_score(bands)
    if source == "LONGMAN":
        if longman_score is None:
            raise ValidationError(
                f"{label}.frequency_evidence requires a licensed Longman band or UNLISTED"
            )
        if components["familiarity"] != longman_score:
            raise ValidationError(
                f"{label}.lexical_burden.familiarity must equal Longman score {longman_score}"
            )
    elif longman_score is not None:
        raise ValidationError(
            f"{label}.frequency_evidence Longman bands require source LONGMAN"
        )
    rejection_code_raw = str(row.get("rejection_code", "")).strip().upper()
    rejection_reason_raw = str(row.get("rejection_reason", "")).strip()
    if rejection_code_raw and rejection_code_raw not in _ALLOWED_REJECTION_CODES:
        raise ValidationError(f"{label}.rejection_code is unsupported: {rejection_code_raw}")
    if rejection_code_raw and not rejection_reason_raw:
        raise ValidationError(f"{label}.rejection_reason is required when rejection_code is supplied")
    return {
        "candidate_id": candidate_id,
        "form": form,
        "meaning_features": _string_list(row.get("meaning_features", []), f"{label}.meaning_features"),
        "tone_and_force": _text(row.get("tone_and_force"), f"{label}.tone_and_force"),
        "register": _text(row.get("register"), f"{label}.register"),
        "lexical_burden": {**components, "overall": expected_total},
        "frequency_evidence": {
            "source": source,
            "bands": bands,
            "note": _text(frequency.get("note"), f"{label}.frequency_evidence.note"),
        },
        "main_risk": _text(row.get("main_risk"), f"{label}.main_risk"),
        "rejection_code": rejection_code_raw or None,
        "rejection_reason": rejection_reason_raw or None,
    }


def _default_human_output() -> HumanOutputSpec:
    """Return an English-only policy for direct validator callers without configuration."""
    return parse_human_output(
        {
            "operator_language": "en",
            "logs_and_reports": {
                "primary_language": "en",
                "secondary_language": None,
                "bilingual": False,
            },
            "translation_challenges": {
                "primary_language": "en",
                "secondary_language": None,
                "bilingual": False,
                "minimum_individual_urgency": 2,
                "aggregate_lower_levels": True,
                "consolidate_repeated_cause": True,
                "render_only_material_fields": True,
            },
            "machine_records": {"language": "canonical", "localise_codes": False},
        }
    )


def _challenge_messages(
    row: Mapping[str, Any],
    *,
    label: str,
    languages: tuple[str, ...],
    canonical_summary: str,
    canonical_risk: str,
    canonical_evidence: str,
    canonical_action: str,
) -> dict[str, dict[str, str]]:
    """Validate localised challenge wording without inventing missing specialist text."""
    raw = row.get("messages")
    if raw in (None, {}) and languages == ("en",):
        return {
            "en": {
                "summary": canonical_summary,
                "risk": canonical_risk,
                "evidence": canonical_evidence,
                "action": canonical_action,
            }
        }
    messages = _mapping(raw, f"{label}.messages")
    result: dict[str, dict[str, str]] = {}
    for language in languages:
        language_row = _mapping(messages.get(language), f"{label}.messages.{language}")
        result[language] = {
            field: _text(
                language_row.get(field),
                f"{label}.messages.{language}.{field}",
                maximum=1800,
            )
            for field in ("summary", "risk", "evidence", "action")
        }
    return result


def _normalise_consolidation_key(
    row: Mapping[str, Any],
    *,
    category: str,
    selected_candidate_id: str,
    candidates: Sequence[Mapping[str, Any]],
    summary: str,
) -> str:
    """Return a stable grouping key for repeated challenges with the same cause."""
    explicit = str(row.get("consolidation_key", "")).strip().upper()
    if explicit:
        if len(explicit) > 160:
            raise ValidationError("challenge consolidation_key exceeds 160 characters")
        return explicit
    candidate_ids = ",".join(sorted(str(item["candidate_id"]) for item in candidates))
    compact_summary = " ".join(summary.casefold().split())[:180]
    return f"{category}|{selected_candidate_id}|{candidate_ids}|{compact_summary}"


def _minor_summary(value: Any) -> dict[str, Any]:
    """Validate the aggregate record for minor matters that do not merit entries."""
    if value in (None, {}):
        return {"total": 0, "by_category": {}, "notes": []}
    row = _mapping(value, "minor_summary")
    total = row.get("total", 0)
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValidationError("minor_summary.total must be a nonnegative integer")
    by_category_raw = _mapping(row.get("by_category", {}), "minor_summary.by_category")
    by_category: dict[str, int] = {}
    for key, count in by_category_raw.items():
        category = str(key).strip().upper()
        if category not in _ALLOWED_CATEGORIES:
            raise ValidationError(f"minor_summary.by_category contains unsupported category: {category}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValidationError(f"minor_summary.by_category.{category} must be a nonnegative integer")
        by_category[category] = count
    notes_raw = row.get("notes", [])
    if not isinstance(notes_raw, list) or any(not isinstance(item, str) or not item.strip() for item in notes_raw):
        raise ValidationError("minor_summary.notes must be a list of nonempty strings")
    return {"total": total, "by_category": by_category, "notes": [item.strip() for item in notes_raw]}


def validate_rewrite_challenges(
    path: Path,
    *,
    task_id: str,
    operation: str,
    scope_value: str,
    output_path: Path,
    inherited_challenge_ids: Sequence[str] = (),
    human_output: HumanOutputSpec | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    ol_evidence_available: bool = True,
) -> dict[str, Any]:
    """Validate REWRITE linguistic judgments while deriving workflow state locally."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid BIC translation-challenges JSON {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValidationError("BIC translation-challenges output must be a JSON object")
    schema_version = str(document.get("schema_version", "")).strip()
    if schema_version != "1.2":
        raise ValidationError("BIC translation-challenges schema_version must be '1.2'")
    policy = human_output or _default_human_output()
    languages = resolved_languages(
        policy.translation_challenges,
        operator_language=policy.operator_language,
        source_language=source_language,
        target_language=target_language,
    )
    expected = {
        "task_id": task_id,
        "operation": operation,
        "scope": scope_value,
        "output_sha256": sha256_file(output_path),
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise ValidationError(f"BIC translation-challenges {key} does not match the task")
    declared_languages = document.get("reporting_languages")
    if declared_languages is not None and declared_languages != list(languages):
        raise ValidationError("BIC translation-challenges reporting_languages do not match effective configuration")
    parent_scope = parse_scope(scope_value)
    raw_challenges = document.get("challenges")
    if not isinstance(raw_challenges, list):
        raise ValidationError("BIC translation-challenges challenges must be a list")
    inherited = set(inherited_challenge_ids)
    seen: set[str] = set()
    normalised: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_challenges, start=1):
        label = f"challenges[{index}]"
        row = _mapping(raw, label)
        # REWRITE has no Operator-choice state. Obsolete choice fields are rejected when truthy.
        for field in ("operator_decision_required", "operator_prompt_available"):
            if bool(row.get(field, False)):
                raise ValidationError(f"{label}.{field} is prohibited; REWRITE has no Operator decision path")
        challenge_id = _text(row.get("challenge_id"), f"{label}.challenge_id", maximum=100).upper()
        if challenge_id in seen:
            raise ValidationError(f"Duplicate BIC translation challenge_id: {challenge_id}")
        seen.add(challenge_id)
        reference = _text(row.get("scripture_reference"), f"{label}.scripture_reference", maximum=160)
        if not _scope_contains(parent_scope, reference):
            raise ValidationError(f"{label}.scripture_reference is outside the bounded task scope")
        category = str(row.get("category", "")).strip().upper()
        if category not in _ALLOWED_CATEGORIES:
            raise ValidationError(f"{label}.category is unsupported: {category}")
        candidates_raw = row.get("candidates")
        if not isinstance(candidates_raw, list) or not candidates_raw:
            raise ValidationError(f"{label}.candidates must contain at least one candidate")
        candidates = [
            _validate_candidate(item, f"{label}.candidates[{candidate_index}]")
            for candidate_index, item in enumerate(candidates_raw, start=1)
        ]
        candidate_ids = [item["candidate_id"] for item in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValidationError(f"{label}.candidates contains duplicate candidate_id values")
        if category == "VERB_CHOICE":
            for candidate_index, candidate in enumerate(candidates, start=1):
                if not candidate["meaning_features"]:
                    raise ValidationError(
                        f"{label}.candidates[{candidate_index}].meaning_features must not be empty for VERB_CHOICE"
                    )
        recommended_candidate_id = _text(
            row.get("recommended_candidate_id"), f"{label}.recommended_candidate_id", maximum=80
        )
        if recommended_candidate_id not in candidate_ids:
            raise ValidationError(f"{label}.recommended_candidate_id must identify a listed candidate")
        supplied_selected = str(row.get("selected_candidate_id", recommended_candidate_id)).strip()
        if supplied_selected and supplied_selected != recommended_candidate_id:
            raise ValidationError(
                f"{label}.selected_candidate_id cannot differ from the recommended candidate; REWRITE has no Operator override"
            )
        risk = _mapping(row.get("risk"), f"{label}.risk")
        before_ol = _score(risk.get("before_ol"), f"{label}.risk.before_ol")
        after_ol = _score(risk.get("after_ol", before_ol), f"{label}.risk.after_ol")
        if "urgency" in risk and _score(risk.get("urgency"), f"{label}.risk.urgency") != after_ol:
            raise ValidationError(f"{label}.risk.urgency must equal the locally derived final risk")
        triggers = _string_list(
            risk.get("material_triggers", []),
            f"{label}.risk.material_triggers",
            allowed=_ALLOWED_TRIGGER_CODES,
        )
        ol_required = bool(before_ol >= 2 and triggers)
        ol = _mapping(row.get("ol_referral", {}), f"{label}.ol_referral")
        performed = ol.get("performed", False)
        if not isinstance(performed, bool):
            raise ValidationError(f"{label}.ol_referral.performed must be boolean")
        if bool(ol.get("operator_requested", False)):
            raise ValidationError(f"{label}.ol_referral.operator_requested is prohibited")
        if performed != ol_required:
            if ol_required:
                raise ValidationError(
                    f"{label} requires one bounded OL check because risk is 2+ and a material trigger exists"
                )
            raise ValidationError(
                f"{label} performs an OL check without both the risk threshold and a material semantic trigger"
            )
        if performed and not ol_evidence_available:
            raise ValidationError(
                f"{label}.ol_referral requires OL evidence that was not conditionally routed to the task"
            )
        if performed:
            question = _text(ol.get("question"), f"{label}.ol_referral.question")
            evidence_scope = _text(
                ol.get("evidence_scope"), f"{label}.ol_referral.evidence_scope", maximum=160
            )
            if not _scope_contains(parent_scope, evidence_scope):
                raise ValidationError(f"{label}.ol_referral.evidence_scope is outside the bounded task scope")
            evidence_summary = _text(
                ol.get("evidence_summary"), f"{label}.ol_referral.evidence_summary"
            )
            before_candidate_id = _text(
                ol.get("before_candidate_id"), f"{label}.ol_referral.before_candidate_id", maximum=80
            )
            if before_candidate_id not in candidate_ids:
                raise ValidationError(f"{label}.ol_referral.before_candidate_id must identify a listed candidate")
        else:
            if after_ol != before_ol:
                raise ValidationError(f"{label}.risk.after_ol must equal before_ol when no OL check is performed")
            forbidden_detail_fields = (
                "question",
                "evidence_scope",
                "evidence_summary",
                "before_candidate_id",
                "after_candidate_id",
                "candidate_changed",
                "resolved",
                "automatic",
            )
            populated = [field for field in forbidden_detail_fields if ol.get(field) not in (None, "", False, [])]
            if populated:
                raise ValidationError(
                    f"{label}.ol_referral contains OL-derived fields although performed is false: {', '.join(populated)}"
                )
            question = ""
            evidence_scope = ""
            evidence_summary = ""
            before_candidate_id = ""
        candidate_changed = bool(performed and before_candidate_id != recommended_candidate_id)
        resolved = bool(performed and after_ol <= 2)
        if performed and "candidate_changed" in ol and bool(ol.get("candidate_changed")) != candidate_changed:
            raise ValidationError(f"{label}.ol_referral.candidate_changed conflicts with the locally derived value")
        if performed and "resolved" in ol and bool(ol.get("resolved")) != resolved:
            raise ValidationError(f"{label}.ol_referral.resolved conflicts with the locally derived value")
        if performed and str(ol.get("after_candidate_id", recommended_candidate_id)).strip() not in {"", recommended_candidate_id}:
            raise ValidationError(f"{label}.ol_referral.after_candidate_id must equal the recommended candidate")
        if after_ol >= 3:
            rejected = [candidate for candidate in candidates if candidate["candidate_id"] != recommended_candidate_id]
            for candidate in rejected:
                if not candidate.get("rejection_code") or not candidate.get("rejection_reason"):
                    raise ValidationError(
                        f"{label} high-risk rejected alternatives require rejection_code and concise rejection_reason"
                    )
        inherited_ids = _string_list(
            row.get("inherited_challenge_ids", []),
            f"{label}.inherited_challenge_ids",
        )
        unknown_inherited = set(inherited_ids) - inherited
        if unknown_inherited:
            raise ValidationError(
                f"{label} cites unknown inherited challenge IDs: {', '.join(sorted(unknown_inherited))}"
            )
        confidence = str(row.get("confidence", "")).strip().upper()
        if confidence not in _ALLOWED_CONFIDENCE:
            raise ValidationError(f"{label}.confidence is unsupported: {confidence}")
        summary = _text(row.get("summary"), f"{label}.summary")
        recommended_action = _text(row.get("recommended_action"), f"{label}.recommended_action")
        selected = next(item for item in candidates if item["candidate_id"] == recommended_candidate_id)
        canonical_risk = selected["main_risk"]
        canonical_evidence = evidence_summary or summary
        messages = _challenge_messages(
            row,
            label=label,
            languages=languages,
            canonical_summary=summary,
            canonical_risk=canonical_risk,
            canonical_evidence=canonical_evidence,
            canonical_action=recommended_action,
        )
        urgency = after_ol
        material = bool(urgency >= policy.translation_challenges.minimum_individual_urgency)
        automatic_resolution = bool(
            performed
            and after_ol < before_ol
            and urgency < policy.translation_challenges.minimum_individual_urgency
        )
        normalised.append(
            {
                "challenge_id": challenge_id,
                "scripture_reference": reference,
                "category": category,
                "summary": summary,
                "messages": messages,
                "confidence": confidence,
                "candidates": candidates,
                "selected_candidate_id": recommended_candidate_id,
                "recommended_candidate_id": recommended_candidate_id,
                "risk": {
                    "before_ol": before_ol,
                    "after_ol": after_ol,
                    "urgency": urgency,
                    "material_triggers": triggers,
                },
                "ol_referral": {
                    "performed": performed,
                    "automatic": ol_required,
                    "question": question,
                    "evidence_scope": evidence_scope,
                    "evidence_summary": evidence_summary,
                    "resolved": resolved,
                    "candidate_changed": candidate_changed,
                    "before_candidate_id": before_candidate_id,
                    "after_candidate_id": recommended_candidate_id if performed else "",
                },
                "inherited_challenge_ids": inherited_ids,
                "recommended_action": recommended_action,
                "consolidation_key": _normalise_consolidation_key(
                    row,
                    category=category,
                    selected_candidate_id=recommended_candidate_id,
                    candidates=candidates,
                    summary=summary,
                ),
                "human_reporting": {
                    "material": material,
                    "automatic_resolution": automatic_resolution,
                    "individual_entry": material,
                },
            }
        )
    supplied_minor = _minor_summary(document.get("minor_summary"))
    derived_minor = [item for item in normalised if not item["human_reporting"]["material"]]
    minor_by_category = dict(supplied_minor["by_category"])
    for item in derived_minor:
        category = item["category"]
        minor_by_category[category] = minor_by_category.get(category, 0) + 1
    minor_total = supplied_minor["total"] + len(derived_minor)
    material_ids = [
        item["challenge_id"] for item in normalised if item["human_reporting"]["material"]
    ]
    automatic_resolution_ids = [
        item["challenge_id"]
        for item in normalised
        if item["human_reporting"]["automatic_resolution"]
    ]
    highest_urgency = max((item["risk"]["urgency"] for item in normalised), default=0)
    return {
        **expected,
        "schema_version": "1.2",
        "reporting_languages": list(languages),
        "status": "COMPLETED_WITH_CHALLENGES" if normalised or minor_total else "COMPLETED",
        "highest_urgency": highest_urgency,
        "decision_required": False,
        "decision_required_ids": [],
        "attention": {
            "level": highest_urgency,
            "classification": (
                "CRITICAL" if highest_urgency == 4 else
                "URGENT" if highest_urgency == 3 else
                "REVIEW_RECOMMENDED" if highest_urgency == 2 else
                "ADVISORY" if normalised or minor_total else "NONE"
            ),
            "next_stage_allowed": True,
            "prompt_required": False,
            "default_action": "CONTINUE_TO_SELF_CHECK",
        },
        "reporting": {
            "minimum_individual_urgency": policy.translation_challenges.minimum_individual_urgency,
            "aggregate_lower_levels": policy.translation_challenges.aggregate_lower_levels,
            "consolidate_repeated_cause": policy.translation_challenges.consolidate_repeated_cause,
            "material_challenge_ids": material_ids,
            "automatic_resolution_ids": automatic_resolution_ids,
            "minor_summary": {
                "total": minor_total,
                "by_category": dict(sorted(minor_by_category.items())),
                "notes": supplied_minor["notes"],
            },
        },
        "challenges": normalised,
    }


def _candidate_form(challenge: Mapping[str, Any], candidate_id: str) -> str:
    """Return one candidate form from a normalised challenge record."""
    for candidate in challenge.get("candidates", []):
        if candidate.get("candidate_id") == candidate_id:
            return str(candidate.get("form", candidate_id))
    return candidate_id


def _group_material_challenges(
    document: Mapping[str, Any],
    channel: TranslationChallengeChannel,
) -> list[list[Mapping[str, Any]]]:
    """Group material challenges by shared cause while preserving first occurrence order."""
    material_ids = set(document.get("reporting", {}).get("material_challenge_ids", []))
    material = [item for item in document.get("challenges", []) if item.get("challenge_id") in material_ids]
    if not channel.consolidate_repeated_cause:
        return [[item] for item in material]
    groups: list[list[Mapping[str, Any]]] = []
    indexes: dict[str, int] = {}
    for item in material:
        key = str(item.get("consolidation_key", item.get("challenge_id")))
        if key not in indexes:
            indexes[key] = len(groups)
            groups.append([])
        groups[indexes[key]].append(item)
    return groups


def render_rewrite_challenge_report(
    document: Mapping[str, Any],
    *,
    human_output: HumanOutputSpec | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
) -> str:
    """Render only material challenges using the configured challenge-language channel."""
    policy = human_output or _default_human_output()
    channel = policy.translation_challenges
    languages = resolved_languages(
        channel,
        operator_language=policy.operator_language,
        source_language=source_language,
        target_language=target_language,
    )

    def label(key: str) -> str:
        """Render one approved challenge-report label for the active language pair."""
        return paired_catalogue_text(
            channel,
            key,
            operator_language=policy.operator_language,
            source_language=source_language,
            target_language=target_language,
        )

    # Keep report rendering here so machine-ledger validation and concise human projection stay visibly paired.
    reporting = document.get("reporting", {})
    material_ids = list(reporting.get("material_challenge_ids", []))
    minor = reporting.get("minor_summary", {})
    lines = [
        f"# {label('label.translation_challenges')}",
        "",
        f"- {label('label.task')}: `{document['task_id']}`",
        f"- {label('label.operation')}: `{document['operation']}`",
        f"- {label('label.scope')}: `{document['scope']}`",
        f"- {label('label.status')}: `{document['status']}`",
        f"- {label('label.highest_urgency')}: `{document['highest_urgency']}`",
        f"- {label('label.material_challenges')}: `{len(material_ids)}`",
        f"- {label('label.minor_aggregated')}: `{minor.get('total', 0)}`",
        f"- {label('label.report_languages')}: `{', '.join(languages)}`",
        "",
    ]
    if not material_ids:
        lines.append(label("label.no_material_challenges"))
    for group in _group_material_challenges(document, channel):
        first = group[0]
        references = ", ".join(str(item["scripture_reference"]) for item in group)
        urgency = max(int(item["risk"]["urgency"]) for item in group)
        urgency_label = label(f"urgency.{urgency}")
        selected = _candidate_form(first, str(first["selected_candidate_id"]))
        alternative_candidates = [
            item
            for item in first.get("candidates", [])
            if item.get("candidate_id") != first.get("selected_candidate_id")
        ]
        alternative_limit = 4 if urgency >= 4 else 3 if urgency == 3 else 2
        alternative_candidates = alternative_candidates[:alternative_limit]
        messages = first.get("messages", {})
        risk_text = message_for_languages(
            messages,
            "risk",
            languages,
            fallback=str(first.get("summary", "")),
        )
        evidence_text = message_for_languages(
            messages,
            "evidence",
            languages,
            fallback=str(first.get("ol_referral", {}).get("evidence_summary", "")),
        )
        action_text = message_for_languages(
            messages,
            "action",
            languages,
            fallback=str(first.get("recommended_action", "")),
        )
        lines.extend(
            [
                f"## {references} · `{first['category']}` · {urgency_label}",
                "",
                f"- {label('label.selected')}: **{selected}**",
                *[
                    (
                        f"- {label('label.alternative')}: **{candidate['form']}** — "
                        f"{candidate.get('rejection_reason') or candidate.get('main_risk') or 'not preferred'}"
                    )
                    for candidate in alternative_candidates
                ],
                f"- {label('label.risk')}: {risk_text}",
                f"- {label('label.evidence')}: {evidence_text}",
                f"- {label('label.action')}: {action_text}",
                "",
            ]
        )
    automatic_ids = set(reporting.get("automatic_resolution_ids", [])) - set(material_ids)
    if automatic_ids:
        lines.extend([f"## {label('label.automatic_resolutions')}", ""])
        by_id = {item["challenge_id"]: item for item in document.get("challenges", [])}
        for challenge_id in sorted(automatic_ids):
            item = by_id[challenge_id]
            before = _candidate_form(item, str(item["ol_referral"].get("before_candidate_id", "")))
            after = _candidate_form(item, str(item["selected_candidate_id"]))
            lines.append(
                f"- `{item['scripture_reference']}`: **{before} → {after}** "
                f"(`{item['risk']['before_ol']}→{item['risk']['after_ol']}`)"
            )
        lines.append("")
    if int(minor.get("total", 0)) and channel.aggregate_lower_levels:
        category_text = ", ".join(
            f"{key}={value}" for key, value in sorted(minor.get("by_category", {}).items())
        ) or "none"
        lines.extend(
            [
                f"## {label('label.summary')}",
                "",
                f"- {label('label.minor_aggregated')}: `{minor.get('total', 0)}` ({category_text})",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"

