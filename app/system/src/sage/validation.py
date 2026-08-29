"""Static ecosystem, permission, and source-package validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .act_tasks import load_skill_registry
from .canon import PERIPHERAL_BOOKS, resolve_expected_books
from .errors import ConfigurationError, SageError
from .grammar import load_grammar_profile
from .profiles import load_workflow_profile, validate_workflow_isolation
from .registry import EcosystemConfig
from .scripture import discover_book_ids
from .schema_validation import validate_schema_contracts
from .standard import SageStandard
from .structure_policy import load_structure_policy
from .transactions import incomplete_transactions
from .vrs import load_project_vrs, resolve_project_vrs_paths


REQUIRED_PACKAGE_PATHS = {
    "VERSION",
    "docs/OPERATOR-GUIDE.md",
    "docs/advanced/README.md",
    "README.md",
    "docs/INDEX.md",
    "docs/macos-linux/CHEAT-SHEET.md",
    "docs/windows/CHEAT-SHEET.md",
    "docs/macos-linux/RECOVERY.md",
    "docs/windows/RECOVERY.md",
    "docs/macos-linux/ERRORS.md",
    "docs/windows/ERRORS.md",
    "docs/advanced/architecture/ARCHITECTURE.md",
    "docs/advanced/future/RESOURCE-HUB.md",
    "docs/advanced/architecture/STORAGE-AND-CORE-BOUNDARY.md",
    "docs/SAW-CHEAT-SHEET.md",
    "docs/advanced/architecture/PROJECT-TREE.md",
    "docs/advanced/architecture/FILE-NAMING-AND-SERIALIZATION.md",
    "docs/advanced/projects-and-resources/PROJECT-CATALOG-AND-MAINTENANCE.md",
    "docs/PROJECT-OPERATOR-CHEAT-SHEET.md",
    "docs/advanced/projects-and-resources/ORIGINAL-LANGUAGE-RESOURCES.md",
    "docs/advanced/architecture/SAGE-SYSTEM-GRAMMAR.md",
    "docs/advanced/maintenance/PURPOSE-FUNCTION-DRIFT-REPORT.md",
    "docs/GOOD-PRACTICE.md",
    "docs/BIC-CHEAT-SHEET.md",
    "docs/advanced/workflows/AUTO-RESOLUTION.md",
    "docs/advanced/workflows/FULL-PROCESS-FLOW.md",
    "docs/advanced/projects-and-resources/PROJECT-SCOPE-AND-CANON.md",
    "docs/advanced/projects-and-resources/GRAMMAR-PROFILES.md",
    "docs/advanced/models-and-ai/MODEL-SELECTION-AND-REASONING.md",
    "docs/advanced/models-and-ai/LOCAL-FIRST-DESIGN-RULE.md",
    "docs/advanced/models-and-ai/LOCAL-AI-ASSISTIVE-MODE.md",
    "docs/advanced/projects-and-resources/RWC-SEMDOM-INDEXES.md",
    "docs/advanced/projects-and-resources/FLEX-COMBINE-INTERCHANGE.md",
    "docs/advanced/architecture/CARDINALITY-AND-BINDING-GRAMMAR.md",
    "docs/advanced/maintenance/HARDENING-AND-CONTEXT-REFINEMENT.md",
    "docs/advanced/workflows/BIC-SAW-AUTHORITY-BOUNDARIES.md",
    "docs/advanced/future/WDA-WORD-DATA-ANALYSIS.md",
    "docs/advanced/future/BASE-TARGET-REVISION-WORKFLOW.md",
    "docs/advanced/release/RELEASE-NOTES.md",
    "docs/advanced/workflows/STRUCTURE-PLANNING.md",
    "docs/advanced/workflows/TARGET-GENERATIONS.md",
    "docs/advanced/release/TEST-AND-VALIDATION-REPORT.md",
    "ecosystem.yml",
    "system/pyproject.toml",
    "system/requirements.txt",
    "system/requirements-dev.txt",
    "system/bin/sage",
    "system/bin/sage.cmd",
    "system/bin/bic",
    "system/bin/bic.cmd",
    "system/bin/saw",
    "system/bin/saw.cmd",
    "system/tools/bootstrap_runtime.py",
    "system/config/sage-standard.json",
    "system/config/model-policy.yml",
    "system/config/execution-ownership.yml",
    "system/config/model-qualification-seeds.json",
    "system/config/skill-evaluation-contracts.json",
    "system/config/bic-protected-rewrite-pin.json",
    "system/config/bic-protected-verb-selection-pin.json",
    "system/config/contracts/bic-verb-selection-policy.yml",
    "system/config/skills.json",
    "system/config/qualification-baselines.json",
    "system/config/schemas/llm-execution-receipt.schema.yml",
    "system/config/schemas/model-policy.schema.yml",
    "system/config/schemas/execution-ownership.schema.yml",
    "system/config/schemas/model-routing-override.schema.yml",
    "system/config/schemas/model-routing-override-receipt.schema.yml",
    "system/config/schemas/model-qualification-receipt.schema.yml",
    "system/config/schemas/model-qualification-seeds.schema.yml",
    "system/config/schemas/skill-evaluation-contracts.schema.yml",
    "system/config/schemas/bic-translation-challenges.schema.yml",
    "system/src/sage/semantic/__init__.py",
    "system/src/sage/semantic/authority_registry.py",
    "system/src/sage/semantic/store.py",
    "system/src/sage/semantic/policy.py",
    "system/src/sage/semantic/freshness.py",
    "system/src/sage/semantic/semdom.py",
    "system/src/sage/semantic/importers.py",
    "system/src/sage/semantic/indexes.py",
    "system/src/sage/semantic/evidence.py",
    "system/src/sage/semantic/diagnostics.py",
    "system/src/sage/semantic/lift.py",
    "system/src/sage/semantic_cli.py",
    "system/config/schemas/semantic-import-manifest.schema.yml",
    "system/config/schemas/semantic-index-contract.schema.yml",
    "system/config/schemas/semantic-export-manifest.schema.yml",
    "system/resources/rwc/README.md",
    "system/resources/rwc/authority/sources.json",
    "system/skills/bic-inspect/SKILL.md",
    "system/skills/bic-rewrite/SKILL.md",
    "system/skills/bic-self-check/SKILL.md",
    "system/skills/saw-rtc/SKILL.md",
    "system/skills/saw-stc/SKILL.md",
    "system/skills/saw-focused-check/SKILL.md",
    "system/skills/saw-ol-review/SKILL.md",
    "system/src/sage/consolidation.py",
    "system/src/sage/local_assistive.py",
    "system/src/sage/skill_routing.py",
    "system/src/sage/routing_override.py",
    "system/src/sage/model_evaluation.py",
    "system/tools/build_model_evaluation_cases.py",
    "system/config/structure-planning.yml",
    "system/config/sage-standard.json",
    "system/config/workflows/bic/profile.yml",
    "system/config/workflows/saw/profile.yml",
    "system/config/profiles/grammar/README.md",
    "system/config/profiles/grammar/fa-IR/wip.yml",
    "system/config/schemas/ecosystem.schema.yml",
    "system/config/schemas/project-manifest.schema.yml",
    "system/config/schemas/project-scope.schema.yml",
    "system/config/schemas/grammar-profile.schema.yml",
    "system/config/schemas/language-profile-registry.schema.yml",
    "system/config/schemas/workflow-profile.schema.yml",
    "system/config/schemas/structure-planning.schema.yml",
    "system/config/schemas/work-unit-manifest.schema.yml",
    "system/config/schemas/transaction-journal.schema.yml",
    "system/config/schemas/act-task.schema.yml",
    "system/config/schemas/act-control.schema.yml",
    "system/config/schemas/bic-human-review-receipt.schema.yml",
    "system/config/schemas/bic-inspect-submission.schema.yml",
    "system/config/schemas/bic-grammar-assessment.schema.yml",
    "system/config/schemas/saw-findings.schema.yml",
    "system/config/schemas/skill-registry.schema.yml",
    "system/config/schemas/generated-target-manifest.schema.yml",
    "system/config/schemas/project-inventory.schema.yml",
    "system/config/schemas/paratext-project-catalog.schema.yml",
    "system/config/schemas/original-language-resources.schema.yml",
    "system/config/schemas/project-code.schema.yml",
    "system/config/schemas/job.schema.yml",
    "system/config/schemas/run.schema.yml",
    "system/config/schemas/active-jobs.schema.yml",
    "system/config/schemas/evaluation-set.schema.yml",
    "system/config/schemas/resource-rights.schema.yml",
    "system/tests/test_local_ai_assistive.py",
    "system/tools/validate_schemas.py",
    "system/src/sage/schema_validation.py",
    "system/src/sage/storage.py",
    "system/resources/scripture/eng.vrs",
    "system/resources/scripture/org.vrs",
    "system/resources/scripture/original-language/README.md",
    "system/resources/scripture/original-language/grk/README.md",
    "system/resources/scripture/original-language/heb/README.md",
    "system/resources/rwc/README.md",
    "system/resources/rwc/authority/sources.json",
}
FORBIDDEN_CORE_TOP_LEVEL = {
    ".venv",
    "cache",
    "state",
    "workspace_data",
    "jobs",
    "reports",
    "localdata",
}

FORBIDDEN_NAMES = {
    ".coverage",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}
LEGACY_PROVIDER_PATHS = {
    ".cline",
    ".clinerules",
    ".clineignore",
    "system/src/sage/cline_bridge.py",
}
LEGACY_REWRITE_PATHS = {
    "system/config/schemas/bic-operator-decisions.schema.yml",
}

EPHEMERAL_PARTS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
}


def _is_inside(child: Path, parent: Path) -> bool:
    """Return whether the candidate path remains inside the governed root."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_static_ecosystem(
    config: EcosystemConfig,
    standard: SageStandard,
) -> dict[str, Any]:
    """Validate paths, VRS ownership, profiles, and write boundaries."""
    # Accumulate independent configuration defects so the Operator receives one complete remediation list.
    errors: list[str] = []
    warnings: list[str] = []
    if not config.projects_root.exists():
        errors.append(f"Internal Scripture projects root does not exist: {config.projects_root}")
    for vrs_id, path in config.base_vrs_files.items():
        if not path.exists():
            errors.append(f"Base VRS {vrs_id} is missing from configured base VRS root: {path}")
        elif path.parent.resolve() != config.base_vrs_root.resolve():
            errors.append(f"Base VRS {vrs_id} must reside directly in configured base VRS root: {path}")
    if config.canonical_versification not in config.base_vrs_files:
        errors.append(
            f"Canonical VRS {config.canonical_versification!r} is not declared in versification.base_files"
        )
    if _is_inside(config.cache_root, config.projects_root):
        errors.append("SAGE cache must not be stored inside the internal Scripture projects root")
    if _is_inside(config.projects_root, config.cache_root):
        errors.append("Internal Scripture projects root must not be nested inside SAGE cache")
    errors.extend(validate_workflow_isolation(config))

    language_profiles: dict[str, Any] = {}
    for language_code, namespace in config.language_profiles.items():
        variants: dict[str, Any] = {}
        for variant_id, spec in namespace.variants.items():
            try:
                profile = load_grammar_profile(
                    spec.path,
                    expected_profile_id=variant_id,
                    expected_language=namespace.profile_language,
                    expected_role=spec.role,
                )
                variants[variant_id] = {
                    "path": str(profile.path),
                    "role": profile.role,
                    "status": profile.status,
                    "sha256": profile.sha256,
                    "rules": len(profile.checks),
                }
            except SageError as exc:
                errors.append(f"Language profile {language_code}/{variant_id}: {exc}")
        language_profiles[language_code] = {
            "script": namespace.script,
            "profile_alias": namespace.profile_alias,
            "variants": variants,
        }

    structure_policy: dict[str, Any] = {}
    try:
        policy = load_structure_policy(config.root)
        structure_policy = policy.to_dict()
    except SageError as exc:
        errors.append(f"Structure-planning policy: {exc}")

    skills: dict[str, Any] = {}
    try:
        registry = load_skill_registry(config.root)
        skills = {
            f"{workflow}/{operation}": {
                "id": skill.skill_id,
                "path": str(skill.path),
                "source_system": skill.source_system,
                "source_version": skill.source_version,
            }
            for (workflow, operation), skill in sorted(registry.items())
        }
    except SageError as exc:
        errors.append(f"Skill registry: {exc}")

    profiles: dict[str, Any] = {}
    for workflow_id, workflow in config.workflows.items():
        try:
            profile = load_workflow_profile(config, workflow)
        except ConfigurationError as exc:
            errors.append(str(exc))
            continue
        profiles[workflow_id] = {
            "name": profile.name,
            "qualification_status": profile.qualification_status,
            "bindings": profile.bindings,
            "language_profile_bindings": profile.language_profile_bindings,
            "evidence_policies": {
                name: policy.to_dict()
                for name, policy in sorted(profile.evidence_policies.items())
            },
            "may_write_projects": list(profile.may_write_projects),
            "publication_root": str(profile.publication_root) if profile.publication_root else None,
        }
        if config.configured:
            disabled_bindings = sorted(
                project_id
                for project_id in profile.bindings.values()
                if not config.projects[project_id].enabled
            )
            if disabled_bindings:
                errors.append(
                    f"{workflow_id.upper()} required bindings are disabled: "
                    + ", ".join(disabled_bindings)
                )
        if workflow_id == "saw" and profile.may_write_projects:
            errors.append("SAW must not have permission to write any Scripture project")
        if workflow.publication_root is not None:
            if _is_inside(workflow.publication_root, config.projects_root):
                errors.append(
                    f"{workflow_id.upper()} publication root must not be inside internal Scripture projects root: "
                    f"{workflow.publication_root}"
                )
            if _is_inside(config.projects_root, workflow.publication_root):
                errors.append(
                    f"Internal Scripture projects root must not be nested inside {workflow_id.upper()} publication root: "
                    f"{workflow.publication_root}"
                )
        pending_transactions = incomplete_transactions(workflow.transaction_root)
        if pending_transactions:
            warnings.append(
                f"{workflow_id.upper()} has {len(pending_transactions)} incomplete transaction(s) "
                "requiring recovery"
            )
        if workflow_id == "bic":
            writable = set(profile.may_write_projects)
            generated = {
                project_id
                for project_id, project in config.projects.items()
                if project.producer == "bic" and project.kind == "GENERATED_SCRIPTURE"
            }
            if writable - generated:
                errors.append(
                    "BIC write permission includes projects that are not BIC-produced generated Scripture: "
                    + ", ".join(sorted(writable - generated))
                )

    project_vrs: dict[str, Any] = {}
    project_scopes: dict[str, Any] = {}
    for project_id, project in config.projects.items():
        expected_books = resolve_expected_books(project.scope)
        discovered_books = discover_book_ids(project.path) if project.enabled else {}
        peripheral_books = sorted(set(discovered_books) & PERIPHERAL_BOOKS)
        observed_books = {
            book: path
            for book, path in discovered_books.items()
            if book not in PERIPHERAL_BOOKS
        }
        missing_books = sorted(set(expected_books) - set(observed_books))
        unexpected_books = sorted(set(observed_books) - set(expected_books))
        project_scopes[project_id] = {
            "language_code": project.language_code,
            "language_profile": project.language_profile,
            "profile_variant": project.profile_variant,
            "content_state": project.content_state,
            "roles": list(project.scope.roles),
            "testament": project.scope.testament,
            "canon": project.scope.canon,
            "declared_expected_books": (
                project.scope.expected_books
                if isinstance(project.scope.expected_books, str)
                else list(project.scope.expected_books)
            ),
            "resolved_expected_books": list(expected_books),
            "observed_books": sorted(observed_books),
            "missing_books": missing_books,
            "unexpected_books": unexpected_books,
            "peripheral_books": peripheral_books,
        }
        if project.enabled and unexpected_books:
            errors.append(
                f"Project {project_id} contains books outside declared scope: "
                + ", ".join(unexpected_books)
            )
        if (
            project.enabled
            and project.coverage_policy == "CONFIGURED_BOOKS_COMPLETE"
            and not project.allow_empty
            and observed_books
            and missing_books
        ):
            errors.append(
                f"Project {project_id} is missing books required by declared scope: "
                + ", ".join(missing_books)
            )
        if not project.enabled:
            continue
        if not project.external and project.path.parent.resolve() != config.projects_root.resolve():
            errors.append(f"Project {project_id} is not a direct child of projects root: {project.path}")
        if project.external and not project.path.is_dir():
            errors.append(f"External project {project_id} folder is unavailable: {project.path}")
        try:
            base_path, custom_path = resolve_project_vrs_paths(config, project)
            schema = load_project_vrs(config, project)
            project_vrs[project_id] = {
                "base": str(base_path),
                "custom": str(custom_path) if custom_path else None,
                "schema_id": schema.schema_id,
                "source_files": schema.source_files,
            }
        except SageError as exc:
            errors.append(f"Project {project_id} VRS: {exc}")
    return {
        "status": "BLOCKED" if errors else ("READY_WITH_WARNINGS" if warnings else "READY"),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "profiles": profiles,
        "skills": skills,
        "evaluation_sets": {
            set_id: {
                "execution_mode": spec.execution_mode,
                "entries": [
                    {
                        "output_project": entry.output_project,
                        "contemporary_source": entry.contemporary_source,
                    }
                    for entry in spec.entries
                ],
            }
            for set_id, spec in sorted(config.evaluation_sets.items())
        },
        "language_profiles": language_profiles,
        "structure_policy": structure_policy,
        "project_vrs": project_vrs,
        "project_scopes": project_scopes,
        "capability_states": sorted(standard.capability_states),
    }


def validate_package(root: Path) -> dict[str, Any]:
    """Check the source tree for missing files and common build artifacts."""
    errors: list[str] = []
    warnings: list[str] = []
    for relative in sorted(REQUIRED_PACKAGE_PATHS):
        if not (root / relative).exists():
            errors.append(f"Required package path is missing: {relative}")
    forbidden_core = [name for name in sorted(FORBIDDEN_CORE_TOP_LEVEL) if (root / name).exists()]
    if forbidden_core:
        errors.append("Core source tree contains local/runtime data roots: " + ", ".join(forbidden_core))
    legacy_paths = [relative for relative in sorted(LEGACY_PROVIDER_PATHS) if (root / relative).exists()]
    if legacy_paths:
        errors.append("Legacy provider-specific runtime paths are not permitted: " + ", ".join(legacy_paths))
    legacy_rewrite_paths = [relative for relative in sorted(LEGACY_REWRITE_PATHS) if (root / relative).exists()]
    if legacy_rewrite_paths:
        errors.append("Legacy BIC candidate-decision paths are not permitted: " + ", ".join(legacy_rewrite_paths))
    scripture_files: list[str] = []
    bundled_ol_scripture: list[str] = []
    artifacts: list[str] = []
    nested_archives: list[str] = []
    symlinks: list[str] = []
    stale_pre_release_artifacts: list[str] = []
    current_version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").exists() else ""
    current_rc_match = re.search(r"(?i)rc\d+(?:\.\d+)?", current_version)
    current_release_tokens = {current_version.casefold()}
    if current_rc_match:
        current_release_tokens.add(current_rc_match.group(0).casefold())
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in EPHEMERAL_PARTS for part in relative.parts):
            continue
        if path.is_symlink():
            symlinks.append(str(relative).replace("\\", "/"))
            continue
        rel_text = str(relative).replace("\\", "/")
        if path.name in FORBIDDEN_NAMES:
            artifacts.append(rel_text)
        for token in re.findall(
            r"(?i)(?:\d+\.\d+-(?:alpha|beta|dev|rc\d+)(?:\.\d+)?|rc\d+(?:\.\d+)?)",
            rel_text,
        ):
            if token.casefold() not in current_release_tokens:
                stale_pre_release_artifacts.append(rel_text)
                break
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        if path.is_file() and path.suffix.lower() in {
            ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"
        }:
            nested_archives.append(str(relative).replace("\\", "/"))
        if path.is_file() and path.suffix.lower() in {".sfm", ".usfm"}:
            scripture_relative = str(relative).replace("\\", "/")
            if (
                path.suffix.lower() == ".sfm"
                and str(relative.parent).replace("\\", "/")
                in {
                    "system/resources/scripture/original-language/grk",
                    "system/resources/scripture/original-language/heb",
                }
            ):
                bundled_ol_scripture.append(scripture_relative)
            else:
                scripture_files.append(scripture_relative)
    if artifacts:
        errors.append("Runtime or platform artifacts: " + ", ".join(artifacts))
    if nested_archives:
        errors.append("Nested archives are not permitted in the source package: " + ", ".join(nested_archives))
    if scripture_files:
        errors.append(
            "Scripture payloads outside governed bundled OL resources are not permitted in the source package: "
            + ", ".join(scripture_files)
        )
    if symlinks:
        errors.append("Symbolic links are not permitted in the source package: " + ", ".join(symlinks))
    if stale_pre_release_artifacts:
        errors.append("Previous pre-release-specific artifacts are not permitted in the source package: " + ", ".join(sorted(set(stale_pre_release_artifacts))))
    schema_validation = validate_schema_contracts(root)
    if schema_validation["status"] != "PASS":
        errors.extend(f"Schema validation: {item}" for item in schema_validation["errors"])
    warnings.extend(f"Schema validation: {item}" for item in schema_validation["warnings"])
    if not re.fullmatch(
        r"(?:\d+\.\d+(?:alpha|beta)(?:\d+)?|\d+\.\d+-(?:alpha|beta|dev|rc\d+[a-z]?)(?:\.\d+)?|\d+\.\d+(?:a|b|rc)\d+[a-z]?(?:-rc\d+)?)",
        current_version,
        flags=re.IGNORECASE,
    ):
        warnings.append(f"Unexpected SAGE version format: {current_version!r}")
    return {
        "status": "BLOCKED" if errors else ("READY_WITH_WARNINGS" if warnings else "READY"),
        "errors": errors,
        "warnings": warnings,
        "scripture_payloads": scripture_files,
        "bundled_ol_scripture": bundled_ol_scripture,
        "artifacts": artifacts,
        "nested_archives": nested_archives,
        "symlinks": symlinks,
        "stale_pre_release_artifacts": sorted(set(stale_pre_release_artifacts)),
        "legacy_provider_paths": legacy_paths,
        "legacy_rewrite_paths": legacy_rewrite_paths,
    }
