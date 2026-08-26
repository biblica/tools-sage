"""Assemble bounded local semantic evidence before any AI call."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..registry import EcosystemConfig
from .freshness import require_current_index, require_reviewable_index, semantic_index_state
from .store import index_root, load_review_states


def evidence_for_lemma(config: EcosystemConfig, *, language: str, lemma: str) -> dict[str, Any]:
    """Return local lemma/sense evidence; absence is explicit and never filled by model invention."""
    freshness = semantic_index_state(config, language)
    if freshness.get("state") == "MISSING":
        return {"language": language, "lemma": lemma, "status": "NO_INDEX", "evidence": []}
    require_current_index(config, language, purpose="semantic lemma evidence retrieval")
    root = index_root(config, language)
    lemma_path = root / "lemma.json"
    sense_path = root / "sense-semdom.json"
    lemma_doc = json.loads(lemma_path.read_text(encoding="utf-8"))
    sense_doc = json.loads(sense_path.read_text(encoding="utf-8"))
    node = lemma_doc.get("lemmas", {}).get(lemma.casefold())
    if not isinstance(node, dict):
        return {"language": language, "lemma": lemma, "status": "NO_MATCH", "evidence": []}
    senses = [sense_doc.get("senses", {}).get(sense_id) for sense_id in node.get("sense_ids", [])]
    return {
        "language": language,
        "lemma": lemma,
        "status": "MATCH",
        "lemma_record": node,
        "evidence": [item for item in senses if isinstance(item, dict)],
        "evidence_class": "PROJECT_INDEX_EVIDENCE",
        "translation_authority": False,
        "scripture_authority": False,
        "authority_rule": "Local project-index retrieval supplies evidence only according to provenance; it is not independent Scripture or translation authority.",
    }


def _tokens(text: str) -> list[str]:
    """Return deterministic Unicode word tokens for local exact-form index lookup."""
    import re

    return re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", text, flags=re.UNICODE)


def _senses_by_record_id(senses: dict[str, Any]) -> dict[str, tuple[tuple[int, dict[str, Any]], ...]]:
    """Index sense rows by record ID once while retaining their canonical document order."""
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for position, value in enumerate(senses.values()):
        if not isinstance(value, dict):
            continue
        record_id = str(value.get("record_id", ""))
        if not record_id:
            continue
        grouped.setdefault(record_id, []).append((position, value))
    return {key: tuple(rows) for key, rows in grouped.items()}


def scope_evidence_for_project(
    config: EcosystemConfig,
    *,
    project_id: str,
    text: str,
    maximum_records: int = 250,
) -> dict[str, Any]:
    """Assemble exact local semantic matches for one bounded Scripture packet before AI execution."""
    from .store import semantic_language_for_project

    language = semantic_language_for_project(config, project_id)
    if not language:
        return {
            "project_id": project_id,
            "status": "NO_SEMANTIC_BINDING",
            "matches": [],
            "local_first": True,
        }
    require_current_index(config, language, purpose=f"semantic evidence retrieval for {project_id}")
    root = index_root(config, language)
    form_path = root / "surface-form.json"
    sense_path = root / "sense-semdom.json"
    catalog_path = root / "semdom-catalog.json"
    form_doc = json.loads(form_path.read_text(encoding="utf-8"))
    sense_doc = json.loads(sense_path.read_text(encoding="utf-8"))
    forms = form_doc.get("forms", {}) if isinstance(form_doc, dict) else {}
    senses = sense_doc.get("senses", {}) if isinstance(sense_doc, dict) else {}
    senses_by_record = _senses_by_record_id(senses) if isinstance(senses, dict) else {}
    catalog: dict[str, Any] = {}
    if catalog_path.is_file():
        try:
            catalog_doc = json.loads(catalog_path.read_text(encoding="utf-8"))
            if isinstance(catalog_doc, dict) and isinstance(catalog_doc.get("domains"), dict):
                catalog = catalog_doc["domains"]
        except (OSError, UnicodeError, json.JSONDecodeError):
            catalog = {}
    token_counts: dict[str, int] = {}
    for token in _tokens(text):
        key = token.casefold()
        token_counts[key] = token_counts.get(key, 0) + 1
    matched_record_ids: set[str] = set()
    matches: list[dict[str, Any]] = []
    for form_key in sorted(token_counts):
        record_ids = forms.get(form_key, []) if isinstance(forms, dict) else []
        if not isinstance(record_ids, list) or not record_ids:
            continue
        new_ids = [str(value) for value in record_ids if str(value) not in matched_record_ids]
        if not new_ids:
            continue
        matched_record_ids.update(new_ids)
        ordered_senses = [
            row
            for record_id in new_ids
            for row in senses_by_record.get(record_id, ())
        ]
        ordered_senses.sort(key=lambda item: item[0])
        raw_senses = [value for _position, value in ordered_senses]
        matched_senses: list[dict[str, Any]] = []
        seen_identities: set[str] = set()
        for value in raw_senses:
            identity = str(value.get("evidence_identity") or value.get("sense_id") or "")
            if identity and not bool(value.get("identity_conflict")):
                if identity in seen_identities:
                    continue
                seen_identities.add(identity)
            matched_senses.append(value)
        matches.append(
            {
                "surface_form": form_key,
                "occurrences_in_scope": token_counts[form_key],
                "record_ids": new_ids,
                "senses": matched_senses,
            }
        )
        if len(matched_record_ids) >= maximum_records:
            break
    matched_codes = sorted(
        {
            str(domain.get("code", "")).strip()
            for match in matches
            for sense in (match.get("senses", []) or [])
            if isinstance(sense, dict)
            for domain in (sense.get("semdom", []) or [])
            if isinstance(domain, dict) and str(domain.get("code", "")).strip()
        }
    )
    domain_context = [catalog[code] for code in matched_codes if code in catalog]
    return {
        "project_id": project_id,
        "semantic_language": language,
        "status": "MATCHED" if matches else "NO_MATCHES",
        "matches": matches,
        "matched_record_count": len(matched_record_ids),
        "domain_context": domain_context,
        "local_first": True,
        "evidence_class": "PROJECT_INDEX_EVIDENCE",
        "translation_authority": False,
        "scripture_authority": False,
        "authority_rule": "This packet is governed project-index evidence only. SEMDOM does not authorize Scripture content or a translation choice.",
    }


def evidence_for_form(config: EcosystemConfig, *, language: str, form: str) -> dict[str, Any]:
    """Return exact local form evidence while allowing batched review-only pending changes."""
    reviewability = require_reviewable_index(config, language)
    root = index_root(config, language)
    form_doc = json.loads((root / "surface-form.json").read_text(encoding="utf-8"))
    sense_doc = json.loads((root / "sense-semdom.json").read_text(encoding="utf-8"))
    key = str(form).strip().casefold()
    record_ids = [str(value) for value in (form_doc.get("forms", {}).get(key, []) or [])]
    sense_rows = sense_doc.get("senses", {}) if isinstance(sense_doc, dict) else {}
    by_record = _senses_by_record_id(sense_rows) if isinstance(sense_rows, dict) else {}
    ordered_senses = [
        row
        for record_id in record_ids
        for row in by_record.get(record_id, ())
    ]
    ordered_senses.sort(key=lambda item: item[0])
    senses = [value for _position, value in ordered_senses]
    review_states = load_review_states(config, language)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_sense in senses:
        sense = dict(source_sense)
        sense_id = str(sense.get("sense_id") or "")
        reviewed = review_states.get(sense_id)
        if isinstance(reviewed, dict):
            sense["status"] = str(reviewed.get("status") or sense.get("status") or "OBSERVED")
            sense["review"] = reviewed
        identity = str(sense.get("evidence_identity") or sense.get("sense_id") or "")
        if identity and not bool(sense.get("identity_conflict")):
            if identity in seen:
                continue
            seen.add(identity)
        deduped.append(sense)
    return {
        "language": language,
        "surface_form": str(form).strip(),
        "status": "MATCH" if record_ids else "NO_MATCH",
        "record_ids": sorted(set(record_ids)),
        "senses": deduped,
        "sense_count": len(deduped),
        "review_index_state": reviewability["state"],
        "review_changes_pending": reviewability["review_changes_pending"],
        "evidence_class": "PROJECT_INDEX_EVIDENCE",
        "translation_authority": False,
        "scripture_authority": False,
        "authority_rule": "Lookup is governed project-index evidence only; reviewed state and translation authority remain separate.",
    }
