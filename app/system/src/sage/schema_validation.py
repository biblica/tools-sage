"""Validate SAGE schema/contract definitions and their source-owned instances."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


SCHEMA_OWNERS: dict[str, str] = {
    "act-control.schema.yml": "system/src/sage/act_tasks.py",
    "act-task.schema.yml": "system/src/sage/act_tasks.py",
    "active-jobs.schema.yml": "system/src/sage/jobs.py",
    "bic-grammar-assessment.schema.yml": "system/src/sage/grammar_governance.py",
    "bic-human-review-receipt.schema.yml": "system/src/sage/bic_memory.py",
    "bic-inspect-submission.schema.yml": "system/src/sage/bic_memory.py",
    "bic-translation-challenges.schema.yml": "system/src/sage/rewrite_risk.py",
    "ecosystem.schema.yml": "system/src/sage/registry.py",
    "execution-event.schema.yml": "system/src/sage/execution_events.py",
    "evaluation-set.schema.yml": "system/src/sage/registry.py",
    "generated-target-manifest.schema.yml": "system/src/sage/generations.py",
    "grammar-profile.schema.yml": "system/src/sage/grammar.py",
    "job.schema.yml": "system/src/sage/jobs.py",
    "language-profile-registry.schema.yml": "system/src/sage/registry.py",
    "llm-execution-receipt.schema.yml": "system/src/sage/llm_tasks.py",
    "model-language-competency.schema.yml": "system/src/sage/model_language_competency.py",
    "model-policy.schema.yml": "system/src/sage/model_policy.py",
    "ol-authority-profile.schema.yml": "system/src/sage/original_language_resources.py",
    "original-language-resources.schema.yml": "system/src/sage/original_language_resources.py",
    "paratext-project-catalog.schema.yml": "system/src/sage/paratext_catalog.py",
    "project-code.schema.yml": "system/src/sage/project_codes.py",
    "project-inventory.schema.yml": "system/src/sage/project_inventory.py",
    "project-manifest.schema.yml": "system/src/sage/generations.py",
    "resource-discovery.schema.yml": "system/src/sage/resource_discovery.py",
    "project-scope.schema.yml": "system/src/sage/registry.py",
    "resource-rights.schema.yml": "system/src/sage/resource_rights.py",
    "run.schema.yml": "system/src/sage/jobs.py",
    "saw-findings.schema.yml": "system/src/sage/findings.py",
    "semantic-export-manifest.schema.yml": "system/src/sage/semantic/lift.py",
    "semantic-import-manifest.schema.yml": "system/src/sage/semantic/importers.py",
    "semantic-index-contract.schema.yml": "system/src/sage/semantic/indexes.py",
    "skill-registry.schema.yml": "system/src/sage/act_tasks.py",
    "structure-planning.schema.yml": "system/src/sage/structure_policy.py",
    "transaction-journal.schema.yml": "system/src/sage/transactions.py",
    "work-unit-manifest.schema.yml": "system/src/sage/work_units.py",
    "workflow-profile.schema.yml": "system/src/sage/profiles.py",
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    """Construct one YAML mapping while rejecting duplicate keys."""
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping with duplicate-key protection."""
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    if not isinstance(value, dict):
        raise ValueError("root must be a mapping")
    return dict(value)


def _load_data(path: Path) -> dict[str, Any]:
    """Load one JSON or YAML mapping from a governed source file."""
    if path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
    else:
        value = _load_yaml(path)
    if not isinstance(value, dict):
        raise ValueError("root must be a mapping")
    return dict(value)


def _missing(mapping: Any, required: list[str]) -> list[str]:
    """Return required field names absent from one mapping."""
    if not isinstance(mapping, dict):
        return list(required)
    return [field for field in required if field not in mapping]


def _validate_required_shape(schema: dict[str, Any], instance: dict[str, Any], label: str) -> list[str]:
    """Validate the common SAGE required-field contract form."""
    errors: list[str] = []
    required = schema.get("required")
    if isinstance(required, list):
        missing = _missing(instance, [str(item) for item in required])
        if missing:
            errors.append(f"{label} missing required fields: {', '.join(missing)}")
    elif isinstance(required, dict):
        for key, requirement in required.items():
            if key not in instance:
                errors.append(f"{label} missing required section: {key}")
                continue
            if isinstance(requirement, list):
                missing = _missing(instance.get(key), [str(item) for item in requirement])
                if missing:
                    errors.append(f"{label}.{key} missing required fields: {', '.join(missing)}")
            elif requirement == "mapping" and not isinstance(instance.get(key), dict):
                errors.append(f"{label}.{key} must be a mapping")
            elif requirement == "list" and not isinstance(instance.get(key), list):
                errors.append(f"{label}.{key} must be a list")
    return errors


def _validate_structure_instance(schema: dict[str, Any], instance: Any, label: str) -> list[str]:
    """Validate the JSON-Schema-like subset used by structure planning."""
    errors: list[str] = []
    if schema.get("type") == "object":
        if not isinstance(instance, dict):
            return [f"{label} must be an object"]
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{label} missing required field: {key}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in instance and isinstance(child_schema, dict):
                    errors.extend(_validate_structure_instance(child_schema, instance[key], f"{label}.{key}"))
    elif schema.get("type") == "array" and not isinstance(instance, list):
        errors.append(f"{label} must be an array")
    return errors


def _source_instance_checks(root: Path, schemas: dict[str, dict[str, Any]]) -> list[str]:
    """Validate shipped configuration instances against their owning contracts."""
    errors: list[str] = []

    ecosystem = _load_data(root / "ecosystem.yml")
    errors.extend(_validate_required_shape(schemas["ecosystem.schema.yml"], ecosystem, "ecosystem.yml"))

    model_policy = _load_data(root / "system/config/model-policy.yml")
    errors.extend(_validate_required_shape(schemas["model-policy.schema.yml"], model_policy, "model-policy.yml"))

    model_language = _load_data(root / "system/config/model-language-competency.yml")
    errors.extend(_validate_required_shape(schemas["model-language-competency.schema.yml"], model_language, "model-language-competency.yml"))

    structure = _load_data(root / "system/config/structure-planning.yml")
    structure_schema = schemas["structure-planning.schema.yml"]
    errors.extend(_validate_structure_instance(structure_schema, structure, "structure-planning.yml"))

    workflow_schema = schemas["workflow-profile.schema.yml"]
    for workflow in ("bic", "saw"):
        path = root / f"system/config/workflows/{workflow}/profile.yml"
        errors.extend(_validate_required_shape(workflow_schema, _load_data(path), str(path.relative_to(root))))

    grammar_schema = schemas["grammar-profile.schema.yml"]
    for path in sorted((root / "system/config/profiles/grammar").glob("*/*.yml")):
        errors.extend(_validate_required_shape(grammar_schema, _load_data(path), str(path.relative_to(root))))

    skills = _load_data(root / "system/config/skills.json")
    skill_schema = schemas["skill-registry.schema.yml"]
    errors.extend(_validate_required_shape(skill_schema, skills, "skills.json"))
    required_skill = [str(item) for item in skill_schema.get("skill_required", [])]
    records = skills.get("skills")
    if not isinstance(records, dict):
        errors.append("skills.json.skills must be a mapping")
    else:
        for skill_id, record in records.items():
            missing = _missing(record, required_skill)
            if missing:
                errors.append(f"skills.json.skills.{skill_id} missing: {', '.join(missing)}")

    language_schema = schemas["language-profile-registry.schema.yml"]
    for language, record in (ecosystem.get("language_profiles") or {}).items():
        is_alias = isinstance(record, dict) and record.get("profile_alias") not in (None, "")
        requirement_key = "required_per_alias_namespace" if is_alias else "required_per_concrete_namespace"
        required = [str(item) for item in language_schema.get(requirement_key, [])]
        missing = _missing(record, required)
        if missing:
            errors.append(f"ecosystem.yml.language_profiles.{language} missing: {', '.join(missing)}")
        variants = record.get("variants") if isinstance(record, dict) else None
        if isinstance(variants, dict):
            variant_required = [str(item) for item in language_schema.get("variant_required_fields", [])]
            for variant_id, variant in variants.items():
                missing = _missing(variant, variant_required)
                if missing:
                    errors.append(
                        f"ecosystem.yml.language_profiles.{language}.variants.{variant_id} missing: {', '.join(missing)}"
                    )

    evaluation_schema = schemas["evaluation-set.schema.yml"]
    for set_id, record in (ecosystem.get("evaluation_sets") or {}).items():
        errors.extend(_validate_required_shape(evaluation_schema, record, f"ecosystem.yml.evaluation_sets.{set_id}"))
        entries = record.get("entries") if isinstance(record, dict) else None
        if isinstance(entries, list):
            required_entry = [str(item) for item in evaluation_schema.get("entry_required", [])]
            for index, entry in enumerate(entries):
                missing = _missing(entry, required_entry)
                if missing:
                    errors.append(
                        f"ecosystem.yml.evaluation_sets.{set_id}.entries[{index}] missing: {', '.join(missing)}"
                    )

    ol_authority_schema = schemas["ol-authority-profile.schema.yml"]
    for family in ("grk", "heb"):
        path = root / f"system/resources/scripture/original-language/{family}/authority-profile.yml"
        errors.extend(
            _validate_required_shape(
                ol_authority_schema,
                _load_data(path),
                str(path.relative_to(root)),
            )
        )

    return errors


def validate_schema_contracts(root: Path) -> dict[str, Any]:
    """Validate every shipped SAGE schema definition and applicable source-owned instance."""
    root = root.expanduser().resolve()
    schema_root = root / "system/config/schemas"
    errors: list[str] = []
    warnings: list[str] = []
    schemas: dict[str, dict[str, Any]] = {}
    ids: dict[str, str] = {}

    paths = sorted(schema_root.glob("*.schema.yml"))
    if not paths:
        return {"status": "BLOCKED", "schema_count": 0, "errors": ["No schema files found"], "warnings": []}

    for path in paths:
        name = path.name
        try:
            schema = _load_yaml(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: invalid YAML/schema mapping: {exc}")
            continue
        schemas[name] = schema
        schema_id = str(schema.get("schema_id") or "").strip()
        if not schema_id:
            errors.append(f"{name}: schema_id is required")
        elif schema_id in ids:
            errors.append(f"{name}: duplicate schema_id {schema_id!r} also used by {ids[schema_id]}")
        else:
            ids[schema_id] = name
        owner = SCHEMA_OWNERS.get(name)
        if owner is None:
            errors.append(f"{name}: no runtime/source owner is registered")
        elif not (root / owner).is_file():
            errors.append(f"{name}: registered owner is missing: {owner}")
        if "required" in schema and not isinstance(schema["required"], (list, dict)):
            errors.append(f"{name}: required must be a list or mapping")

    missing_registered = sorted(set(SCHEMA_OWNERS) - set(schemas))
    unexpected = sorted(set(schemas) - set(SCHEMA_OWNERS))
    for name in missing_registered:
        errors.append(f"Registered schema is missing: {name}")
    for name in unexpected:
        errors.append(f"Unregistered schema file: {name}")

    if not errors:
        try:
            errors.extend(_source_instance_checks(root, schemas))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Source-instance schema validation failed: {exc}")

    return {
        "status": "PASS" if not errors else "BLOCKED",
        "schema_count": len(paths),
        "schema_ids": len(ids),
        "owner_count": len(SCHEMA_OWNERS),
        "source_instance_groups": 8,
        "errors": errors,
        "warnings": warnings,
    }
