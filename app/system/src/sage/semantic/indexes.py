"""Build local-first semantic indexes from immutable imports."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_json
from ..errors import ValidationError
from ..hashing import sha256_paths
from ..registry import EcosystemConfig
from .authority_registry import authority_source_for_type
from .freshness import INDEX_MANIFEST_SCHEMA, current_input_fingerprint, semantic_index_state
from .store import (
    authority_root,
    index_root,
    import_root,
    language_root,
    load_authority_selection,
    load_import_selection,
    load_review_states,
)


def _load_imports(config: EcosystemConfig, language: str) -> tuple[list[dict[str, Any]], list[Path]]:
    """Load immutable normalized imports for one semantic language namespace."""
    root = language_root(config, language) / "imports"
    if not root.is_dir():
        return [], []
    records: list[dict[str, Any]] = []
    sources: list[Path] = []
    active_imports = load_import_selection(config, language)
    for source_id in active_imports:
        path = import_root(config, language, source_id) / "records.json"
        if not path.is_file():
            raise ValidationError(f"Active semantic import is missing records: {source_id}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Invalid semantic import {path}: {exc}") from exc
        if not isinstance(payload, list):
            raise ValidationError(f"Semantic import must contain a list: {path}")
        records.extend(item for item in payload if isinstance(item, dict))
        sources.append(path)
    return records, sources


def _active_domain_catalog(config: EcosystemConfig) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Load explicitly selected SIL and RapidWords metadata into one local classification catalog."""
    active = load_authority_selection(config)
    catalog: dict[str, dict[str, Any]] = {}
    semdom_spec = authority_source_for_type(config, "semdom")
    folder_spec = authority_source_for_type(config, "folders")
    semdom_source = active.get(semdom_spec.selection_key)
    if semdom_source:
        path = authority_root(config) / semdom_spec.storage_directory / semdom_source / semdom_spec.content_file
        if not path.is_file():
            raise ValidationError(f"Selected SIL Semantic Domains source is missing: {semdom_source}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValidationError(f"Selected SIL Semantic Domains source is invalid: {path}")
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code", "")).strip()
            if code:
                catalog[code] = {
                    "code": code,
                    "label": str(row.get("name", "")).strip(),
                    "description": str(row.get("description", "")).strip(),
                    "parent_code": row.get("parent_code"),
                    "child_codes": list(row.get("child_codes", []) or []),
                    "questions": list(row.get("questions", []) or []),
                    "louw_nida_codes": str(row.get("louw_nida_codes", "")).strip(),
                    "authority_source": semdom_source,
                }
    folder_source = active.get(folder_spec.selection_key)
    if folder_source:
        path = authority_root(config) / folder_spec.storage_directory / folder_source / folder_spec.content_file
        if not path.is_file():
            raise ValidationError(f"Selected RapidWords folder source is missing: {folder_source}")
        folders = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(folders, list):
            raise ValidationError(f"Selected RapidWords folder source is invalid: {path}")
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            folder_number = folder.get("folder")
            for domain in folder.get("domains", []) or []:
                if not isinstance(domain, dict):
                    continue
                code = str(domain.get("code", "")).strip()
                if not code:
                    continue
                node = catalog.setdefault(
                    code,
                    {
                        "code": code,
                        "label": str(domain.get("label", "")).strip(),
                        "description": "",
                        "parent_code": None,
                        "child_codes": [],
                        "questions": [],
                        "louw_nida_codes": "",
                        "authority_source": None,
                    },
                )
                if not node.get("label"):
                    node["label"] = str(domain.get("label", "")).strip()
                node["rapidwords"] = {
                    "folder": folder_number,
                    "specificity_order": domain.get("specificity_order"),
                    "source": folder_source,
                }
    return catalog, active


def build_semantic_indexes(config: EcosystemConfig, *, language: str) -> dict[str, Any]:
    """Build lemma, sense/SEMDOM, correspondence-ready, decision, and coverage indexes locally."""
    records, source_paths = _load_imports(config, language)
    if not records:
        raise ValidationError(f"No semantic imports are available for {language}")
    domain_catalog, authority_selection = _active_domain_catalog(config)
    review_states = load_review_states(config, language)
    seen_sense_ids: set[str] = set()
    lemmas: dict[str, dict[str, Any]] = {}
    lexical_heads: dict[str, dict[str, Any]] = {}
    senses: dict[str, dict[str, Any]] = {}
    semdom: dict[str, dict[str, Any]] = defaultdict(lambda: {"senses": [], "lemmas": [], "records": []})
    key_terms: list[dict[str, Any]] = []
    surface_forms: dict[str, list[str]] = defaultdict(list)
    for record in records:
        record_id = str(record.get("record_id", "")).strip()
        lemma = record.get("lemma")
        lemma_status = str(record.get("lemma_status", "UNKNOWN"))
        headword = str(record.get("headword", "")).strip()
        if headword:
            surface_forms[headword.casefold()].append(record_id)
        if headword:
            head_key = headword.casefold()
            head_node = lexical_heads.setdefault(
                head_key,
                {
                    "headword": headword,
                    "lemma": lemma,
                    "lemma_statuses": [],
                    "record_ids": [],
                    "surface_forms": [],
                    "sense_ids": [],
                },
            )
            head_node["record_ids"].append(record_id)
            head_node["lemma_statuses"].append(lemma_status)
            head_node["surface_forms"].extend(str(v) for v in record.get("surface_forms", []) if str(v).strip())
        canonical_lemma = bool(lemma) and lemma_status not in {"SEED_HEADWORD", "SURFACE_FORM_ONLY", "UNKNOWN"}
        if canonical_lemma:
            key = str(lemma).casefold()
            node = lemmas.setdefault(
                key,
                {
                    "lemma": str(lemma),
                    "lemma_statuses": [],
                    "record_ids": [],
                    "surface_forms": [],
                    "sense_ids": [],
                },
            )
            node["record_ids"].append(record_id)
            node["lemma_statuses"].append(lemma_status)
            node["surface_forms"].extend(str(v) for v in record.get("surface_forms", []) if str(v).strip())
        for sense in record.get("senses", []) or []:
            sense_id = str(sense.get("sense_id", "")).strip()
            if not sense_id:
                continue
            seen_sense_ids.add(sense_id)
            semdom_entries = [item for item in sense.get("semdom", []) or [] if isinstance(item, dict)]
            imported_status = str(sense.get("status", "OBSERVED")).strip().upper() or "OBSERVED"
            reviewed = review_states.get(sense_id)
            effective_status = str(reviewed.get("status")) if isinstance(reviewed, dict) else imported_status
            senses[sense_id] = {
                "sense_id": sense_id,
                "source_sense_id": sense.get("source_sense_id"),
                "record_id": record_id,
                "lemma": lemma,
                "lemma_status": lemma_status,
                "headword": headword,
                "glosses": dict(sense.get("glosses", {}) or {}),
                "definitions": dict(sense.get("definitions", {}) or {}),
                "part_of_speech": sense.get("part_of_speech"),
                "semdom": semdom_entries,
                "references": list(sense.get("references", []) or []),
                "status": effective_status,
                "imported_status": imported_status,
                "review": reviewed,
                "provenance": record.get("provenance", {}),
            }
            if headword:
                lexical_heads[headword.casefold()]["sense_ids"].append(sense_id)
            if canonical_lemma:
                lemmas[str(lemma).casefold()]["sense_ids"].append(sense_id)
            for domain in semdom_entries:
                code = str(domain.get("code", "")).strip()
                if not code:
                    continue
                bucket = semdom[code]
                bucket["code"] = code
                bucket["label"] = str(domain.get("label", "")).strip()
                bucket["senses"].append(sense_id)
                bucket["records"].append(record_id)
                if lemma:
                    bucket["lemmas"].append(str(lemma))
        if bool(record.get("key_term")):
            key_terms.append({"record_id": record_id, "headword": headword, "lemma": lemma})
    identity_groups: dict[str, list[str]] = defaultdict(list)
    for sense_id, node in senses.items():
        provenance = node.get("provenance", {}) if isinstance(node.get("provenance"), dict) else {}
        source_type = str(provenance.get("source_type", "")).strip().upper()
        source_sense_id = str(node.get("source_sense_id") or "").strip()
        if source_sense_id and source_type in {"FLEX_LIFT", "COMBINE_LIFT"}:
            identity = f"{source_type}:{source_sense_id}"
        else:
            identity = f"SAGE:{sense_id}"
        node["evidence_identity"] = identity
        identity_groups[identity].append(sense_id)

    reconciliation_groups: list[dict[str, Any]] = []
    for identity, sense_ids in sorted(identity_groups.items()):
        if len(sense_ids) < 2 or identity.startswith("SAGE:"):
            continue
        signatures: set[str] = set()
        for sense_id in sense_ids:
            node = senses[sense_id]
            signature = json.dumps(
                {
                    "lemma": str(node.get("lemma") or "").casefold(),
                    "headword": str(node.get("headword") or "").casefold(),
                    "glosses": node.get("glosses", {}),
                    "definitions": node.get("definitions", {}),
                    "part_of_speech": node.get("part_of_speech"),
                    "semdom": sorted(
                        str(item.get("code", "")).strip()
                        for item in (node.get("semdom", []) or [])
                        if isinstance(item, dict) and str(item.get("code", "")).strip()
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            signatures.add(signature)
        conflict = len(signatures) > 1
        for sense_id in sense_ids:
            senses[sense_id]["identity_conflict"] = conflict
        reconciliation_groups.append(
            {
                "evidence_identity": identity,
                "sense_ids": sorted(sense_ids),
                "status": "CONFLICT" if conflict else "CONSISTENT_DUPLICATE",
                "rule": "Only stable external LIFT sense IDs are reconciled automatically; string similarity is never merged.",
            }
        )

    orphaned_reviews = sorted(set(review_states) - seen_sense_ids)
    if orphaned_reviews:
        raise ValidationError(
            "Semantic review state references senses outside the active import set: "
            + ", ".join(orphaned_reviews[:10])
            + (" ..." if len(orphaned_reviews) > 10 else "")
        )

    for collection in (lemmas, lexical_heads):
        for node in collection.values():
            for key in ("record_ids", "surface_forms", "sense_ids", "lemma_statuses"):
                node[key] = sorted(set(node[key]))
    semdom_final: dict[str, dict[str, Any]] = {}
    for code, bucket in semdom.items():
        semdom_final[code] = {
            **bucket,
            "senses": sorted(set(bucket["senses"])),
            "records": sorted(set(bucket["records"])),
            "lemmas": sorted(set(bucket["lemmas"]), key=str.casefold),
        }
    for code, observed in semdom_final.items():
        node = domain_catalog.setdefault(
            code,
            {
                "code": code,
                "label": observed.get("label", ""),
                "description": "",
                "parent_code": None,
                "child_codes": [],
                "questions": [],
                "louw_nida_codes": "",
                "authority_source": None,
            },
        )
        if not node.get("label"):
            node["label"] = observed.get("label", "")
        node["attested_in_index"] = True
        node["attested_sense_count"] = len(observed.get("senses", []))

    root = index_root(config, language)
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(root / "lemma.json", {"schema_version": "1.0", "language": language, "lemmas": lemmas})
    atomic_write_json(
        root / "lexical-head.json",
        {
            "schema_version": "1.0",
            "language": language,
            "heads": lexical_heads,
            "rule": "Seed headwords remain lexical-head evidence until an explicit lemma/lexeme authority establishes canonical lemma identity.",
        },
    )
    atomic_write_json(root / "sense-semdom.json", {"schema_version": "1.0", "language": language, "senses": senses, "domains": semdom_final})
    atomic_write_json(root / "surface-form.json", {"schema_version": "1.0", "language": language, "forms": {k: sorted(set(v)) for k, v in surface_forms.items()}})
    atomic_write_json(root / "key-terms.json", {"schema_version": "1.0", "language": language, "records": key_terms})
    atomic_write_json(
        root / "reconciliation.json",
        {
            "schema_version": "1.0",
            "language": language,
            "groups": reconciliation_groups,
            "conflicts": sum(1 for item in reconciliation_groups if item["status"] == "CONFLICT"),
            "consistent_duplicates": sum(1 for item in reconciliation_groups if item["status"] == "CONSISTENT_DUPLICATE"),
        },
    )
    atomic_write_json(
        root / "semdom-catalog.json",
        {
            "schema_version": "1.0",
            "language": language,
            "translation_authority": False,
            "active_authority": authority_selection,
            "domains": dict(sorted(domain_catalog.items())),
        },
    )
    # Reserved local-first indexes exist from the start even when no project-governed rows have been established yet.
    for filename, key in (
        ("correspondence.json", "correspondences"),
        ("construction.json", "constructions"),
        ("decisions.json", "decisions"),
    ):
        path = root / filename
        if not path.exists():
            atomic_write_json(path, {"schema_version": "1.0", "language": language, key: []})
    input_fingerprint, input_descriptor = current_input_fingerprint(config, language)
    coverage = {
        "schema_version": "1.0",
        "language": language,
        "records": len(records),
        "lemmas": len(lemmas),
        "lexical_heads": len(lexical_heads),
        "senses": len(senses),
        "semantic_domains": len(semdom_final),
        "key_terms": len(key_terms),
        "surface_forms": len(surface_forms),
        "semdom_catalog_domains": len(domain_catalog),
        "active_authority": authority_selection,
        "source_fingerprint": sha256_paths(source_paths) if source_paths else None,
        "input_fingerprint": input_fingerprint,
        "reviewed_senses": len(review_states),
        "reconciliation_conflicts": sum(1 for item in reconciliation_groups if item["status"] == "CONFLICT"),
        "reconciled_duplicate_groups": sum(1 for item in reconciliation_groups if item["status"] == "CONSISTENT_DUPLICATE"),
        "notes": [
            "SEMDOM organizes meaning but is not translation authority.",
            "SEED and OBSERVED records do not become APPROVED by import or frequency.",
            "SURFACE_FORM_ONLY project-index records are excluded from lemma authority.",
        ],
    }
    atomic_write_json(root / "coverage.json", coverage)
    atomic_write_json(
        root / "index-manifest.json",
        {
            "schema_version": INDEX_MANIFEST_SCHEMA,
            "language": language,
            "input_fingerprint": input_fingerprint,
            "input_descriptor": input_descriptor,
            "rules": [
                "Generated semantic indexes are valid only for the exact active import/authority/review fingerprint.",
                "Stale indexes must not feed BIC, RTC, STC, legacy analysis, or LIFT export.",
            ],
        },
    )
    return {**coverage, "index_state": "CURRENT", "index_root": str(root)}


def semantic_status(config: EcosystemConfig, *, language: str) -> dict[str, Any]:
    """Return a local snapshot without triggering AI or provider calls."""
    root = language_root(config, language)
    imports = sorted(path.parent.name for path in (root / "imports").glob("*/manifest.json")) if (root / "imports").is_dir() else []
    active_imports = load_import_selection(config, language)
    index = root / "indexes" / "coverage.json"
    coverage = None
    if index.is_file():
        try:
            coverage = json.loads(index.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            coverage = {"status": "INVALID"}
    authority = load_authority_selection(config)
    semdom_spec = authority_source_for_type(config, "semdom")
    folder_spec = authority_source_for_type(config, "folders")
    semdom_root = authority_root(config) / semdom_spec.storage_directory
    folder_root = authority_root(config) / folder_spec.storage_directory
    semdom_sources = sorted(
        path.parent.name for path in semdom_root.glob("*/manifest.json")
    ) if semdom_root.is_dir() else []
    folder_sources = sorted(
        path.parent.name for path in folder_root.glob("*/manifest.json")
    ) if folder_root.is_dir() else []
    freshness = semantic_index_state(config, language)
    return {
        "language": language,
        "imports": imports,
        "import_count": len(imports),
        "active_imports": active_imports,
        "active_import_count": len(active_imports),
        "index_state": freshness.get("state"),
        "indexes_ready": freshness.get("state") == "CURRENT",
        "index_detail": freshness,
        "coverage": coverage,
        "active_authority": authority,
        "available_authority": {semdom_spec.selection_key: semdom_sources, folder_spec.selection_key: folder_sources},
        "root": str(root),
    }
