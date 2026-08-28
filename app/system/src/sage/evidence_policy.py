"""Canonical closed-evidence and linguistic-competence policy for governed SAGE tasks."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError

EVIDENCE_POLICY_VERSION = "1.0"

AUTHORIZED_CONTENT_EVIDENCE = "AUTHORIZED_CONTENT_EVIDENCE"
AUTHORIZED_LEXICAL_EVIDENCE = "AUTHORIZED_LEXICAL_EVIDENCE"
PROJECT_INDEX_EVIDENCE = "PROJECT_INDEX_EVIDENCE"
DERIVED_EVIDENCE = "DERIVED_EVIDENCE"
STRUCTURAL_EVIDENCE = "STRUCTURAL_EVIDENCE"
SUBJECT_TEXT = "SUBJECT_TEXT"
LINGUISTIC_COMPETENCE_RULES = "LINGUISTIC_COMPETENCE_RULES"
AUTHORITY_INTERPRETATION_RULES = "AUTHORITY_INTERPRETATION_RULES"
PROCESS_CONTROL = "PROCESS_CONTROL"

READ_CLASSES = {
    AUTHORIZED_CONTENT_EVIDENCE,
    AUTHORIZED_LEXICAL_EVIDENCE,
    PROJECT_INDEX_EVIDENCE,
    DERIVED_EVIDENCE,
    STRUCTURAL_EVIDENCE,
    SUBJECT_TEXT,
    LINGUISTIC_COMPETENCE_RULES,
    AUTHORITY_INTERPRETATION_RULES,
    PROCESS_CONTROL,
}

READ_CLASS_RULES = {
    AUTHORIZED_CONTENT_EVIDENCE: (
        "May support content judgments only within the exact role and scope established by the Job."
    ),
    AUTHORIZED_LEXICAL_EVIDENCE: (
        "May support lexical choice only; it may not supply verse wording, syntax, propositions, sequence, participants, or discourse."
    ),
    PROJECT_INDEX_EVIDENCE: (
        "May support local retrieval/classification/triage according to provenance; it is not independent Scripture or translation authority."
    ),
    DERIVED_EVIDENCE: (
        "May support only the claims inherited from its verified authorized local provenance; it is never a new authority class."
    ),
    STRUCTURAL_EVIDENCE: (
        "May support bounded structural, versification, coverage, or routing judgments; it may not introduce independent content."
    ),
    SUBJECT_TEXT: (
        "May be analyzed as the Job subject/candidate/WIP, but it is not independent authority for what the content should be."
    ),
    LINGUISTIC_COMPETENCE_RULES: (
        "May constrain orthography, morphology, grammar, and syntax; it may not introduce Scripture content, lexical meaning, or interpretation."
    ),
    AUTHORITY_INTERPRETATION_RULES: (
        "May establish the routed OL authority historical language, register, representation, and source constraints; it may not supply Scripture content, lexical meanings, translation equivalents, variant readings, or interpretations absent from routed evidence."
    ),
    PROCESS_CONTROL: (
        "May govern execution, validation, schema, or Skill behavior only; it is not content evidence."
    ),
}

GENERAL_LINGUISTIC_COMPETENCE = ("ORTHOGRAPHY", "MORPHOLOGY", "GRAMMAR", "SYNTAX")
FORBIDDEN_EXTERNAL_CONTENT = (
    "MODEL_RECALL",
    "PRETRAINED_SCRIPTURE_KNOWLEDGE",
    "UNROUTED_TRANSLATIONS",
    "UNROUTED_LEXICONS_OR_CORPORA",
    "COMMENTARY_OR_THEOLOGY",
    "HISTORICAL_OR_CULTURAL_RECALL",
    "WEB_SEARCH_OR_EXTERNAL_APIS",
    "UNSTATED_FACTS",
)


def validate_read_class(value: object) -> str:
    """Return one canonical read class or fail closed on an unclassified task read."""
    normalized = str(value or "").strip().upper()
    if normalized not in READ_CLASSES:
        raise ValidationError(
            f"Task read has no canonical evidence classification: {value!r}",
            code="TASK_READ_EVIDENCE_CLASS_INVALID",
            next_action="Recreate the governed task so every read has an explicit evidence class.",
        )
    return normalized


def task_evidence_policy(workflow: str) -> dict[str, Any]:
    """Return the immutable evidence/competence contract embedded in each governed task."""
    normalized = workflow.strip().lower()
    if normalized not in {"bic", "saw"}:
        raise ValidationError(f"Unsupported evidence-policy workflow: {workflow}")
    authority = (
        {
            "SOURCE": "sole BIC content/translation authority",
            "DONOR": "lexical evidence only",
            "TARGET": "subject/output destination only; existing TARGET is not content evidence",
            "ORIGINAL_LANGUAGE": "bounded content evidence only when explicitly routed",
        }
        if normalized == "bic"
        else {
            "REFERENCE": "authorized LWC comparison/content authority",
            "WIP": "subject under analysis, not independent content authority",
            "ORIGINAL_LANGUAGE": "bounded content evidence only when explicitly routed",
        }
    )
    return {
        "schema_version": EVIDENCE_POLICY_VERSION,
        "mode": "CLOSED_LOCAL_EVIDENCE",
        "local_evidence_boundary": "SAGE_LOCAL_GOVERNED_TASK",
        "invariant": (
            "Content comes from authorized local evidence. The LLM contributes general linguistic competence, not external content knowledge."
        ),
        "authority": authority,
        "project_index_rule": (
            "Explicitly imported/merged SAGE-local project indexes may provide retrieval, classification, lexical, or triage evidence according to provenance; they never become independent Scripture authority."
        ),
        "derived_pack_rule": (
            "A derived pack inherits the authority and restrictions of its verified local provenance and never becomes an independent source."
        ),
        "general_linguistic_competence": list(GENERAL_LINGUISTIC_COMPETENCE),
        "linguistic_competence_limit": (
            "General linguistic competence may parse, validate, transform, or express supported content. It may not introduce new propositions, lexical meanings, translation equivalents, Scripture content, interpretations, historical/cultural claims, or other content-bearing evidence."
        ),
        "language_specificity": {
            "canonical_profiles_required": True,
            "infer_language_from_text": False,
            "profiles_are_sliced": False,
            "sfm_budget_contribution": "NONE",
            "missing_or_ambiguous_profile": "FAIL_CLOSED",
        },
        "forbidden_external_content": list(FORBIDDEN_EXTERNAL_CONTENT),
        "read_class_rules": dict(READ_CLASS_RULES),
        "fail_closed": True,
    }
