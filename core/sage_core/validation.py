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
from .standard import SageStandard
from .structure_policy import load_structure_policy
from .transactions import incomplete_transactions
from .vrs import load_project_vrs, resolve_project_vrs_paths


REQUIRED_PACKAGE_PATHS = {
    "VERSION",
    "HELP.md",
    "README.md",
    "docs/INDEX.md",
    "docs/macos-linux/CHEAT-SHEET.md",
    "docs/windows/CHEAT-SHEET.md",
    "docs/macos-linux/RECOVERY.md",
    "docs/windows/RECOVERY.md",
    "docs/macos-linux/ERRORS.md",
    "docs/windows/ERRORS.md",
    "docs/ARCHITECTURE.md",
    "docs/SAW-CHEAT-SHEET.md",
    "docs/PROJECT-TREE.md",
    "docs/PROJECT-CATALOGUE-AND-MAINTENANCE.md",
    "docs/PROJECT-OPERATOR-CHEAT-SHEET.md",
    "docs/ORIGINAL-LANGUAGE-RESOURCES.md",
    "docs/PROJECT-DOCUMENT-GRAMMAR.md",
    "docs/GOOD-PRACTICE.md",
    "docs/BIC-CHEAT-SHEET.md",
    "docs/AUTO-RESOLUTION.md",
    "docs/FULL-PROCESS-FLOW.md",
    "docs/PROJECT-SCOPE-AND-CANON.md",
    "docs/LANGUAGE-PROFILES.md",
    "docs/MODEL-SELECTION-AND-REASONING.md",
    "docs/LOCAL-FIRST-DESIGN-RULE.md",
    "docs/RWC-SEMDOM-INDEXES.md",
    "docs/FLEX-COMBINE-INTERCHANGE.md",
    "docs/CARDINALITY-AND-BINDING-GRAMMAR.md",
    "docs/HARDENING-AND-CONTEXT-REFINEMENT.md",
    "docs/BIC-SAW-AUTHORITY-BOUNDARIES.md",
    "docs/future/WDA-WORD-DATA-ANALYSIS.md",
    "docs/future/BASE-TARGET-REVISION-WORKFLOW.md",
    "docs/RELEASE-NOTES.md",
    "docs/STRUCTURE-PLANNING.md",
    "docs/TARGET-GENERATIONS.md",
    "docs/TEST-AND-VALIDATION-REPORT.md",
    "ecosystem.yml",
    "sage",
    "sage.cmd",
    "scripts/bootstrap_runtime.py",
    "meta/sage.yml",
    "meta/model-policy.yml",
    "meta/bic-protected-rewrite-contract.yml",
    "meta/bic-protected-verb-selection-contract.yml",
    "meta/contracts/BIC-VERB-SELECTION-POLICY.yml",
    "meta/skills.yml",
    "meta/schemas/llm-execution-receipt.schema.yml",
    "meta/schemas/model-policy.schema.yml",
    "meta/schemas/bic-translation-challenges.schema.yml",
    "core/sage_core/semantic/__init__.py",
    "core/sage_core/semantic/store.py",
    "core/sage_core/semantic/policy.py",
    "core/sage_core/semantic/freshness.py",
    "core/sage_core/semantic/semdom.py",
    "core/sage_core/semantic/importers.py",
    "core/sage_core/semantic/indexes.py",
    "core/sage_core/semantic/evidence.py",
    "core/sage_core/semantic/diagnostics.py",
    "core/sage_core/semantic/lift.py",
    "core/sage_core/semantic_cli.py",
    "meta/schemas/semantic-import-manifest.schema.yml",
    "meta/schemas/semantic-index-contract.schema.yml",
    "meta/schemas/semantic-export-manifest.schema.yml",
    "resources/rwc/README.md",
    "resources/rwc/authority/SOURCES.yml",
    "skills/bic-inspect/SKILL.md",
    "skills/bic-rewrite/SKILL.md",
    "skills/bic-self-check/SKILL.md",
    "skills/saw-qa/SKILL.md",
    "skills/saw-focused-check/SKILL.md",
    "skills/saw-ol-review/SKILL.md",
    "meta/structure-planning.yml",
    "meta/terminology.yml",
    "workflows/bic/profile.yml",
    "workflows/saw/profile.yml",
    "profiles/languages/README.md",
    "profiles/languages/id/source.yml",
    "profiles/languages/en/bol-target.yml",
    "profiles/languages/uk/wip.yml",
    "profiles/languages/fa/wip.yml",
    "meta/schemas/ecosystem.schema.yml",
    "meta/schemas/project-manifest.schema.yml",
    "meta/schemas/project-scope.schema.yml",
    "meta/schemas/grammar-profile.schema.yml",
    "meta/schemas/language-profile-registry.schema.yml",
    "meta/schemas/workflow-profile.schema.yml",
    "meta/schemas/structure-planning.schema.yml",
    "meta/schemas/work-unit-manifest.schema.yml",
    "meta/schemas/transaction-journal.schema.yml",
    "meta/schemas/act-task.schema.yml",
    "meta/schemas/act-control.schema.yml",
    "meta/schemas/bic-human-review-receipt.schema.yml",
    "meta/schemas/bic-inspect-submission.schema.yml",
    "meta/schemas/bic-grammar-assessment.schema.yml",
    "meta/schemas/saw-findings.schema.yml",
    "meta/schemas/skill-registry.schema.yml",
    "meta/schemas/generated-target-manifest.schema.yml",
    "meta/schemas/project-inventory.schema.yml",
    "meta/schemas/paratext-project-catalog.schema.yml",
    "meta/schemas/original-language-resources.schema.yml",
    "meta/schemas/project-code.schema.yml",
    "meta/schemas/job.schema.yml",
    "meta/schemas/run.schema.yml",
    "meta/schemas/active-jobs.schema.yml",
    "resources/scripture/eng.vrs",
    "resources/scripture/org.vrs",
    "resources/scripture/original-language/README.md",
    "resources/scripture/original-language/grk/README.md",
    "resources/scripture/original-language/heb/README.md",
    "resources/rwc/README.md",
    "resources/rwc/authority/SOURCES.yml",
    "jobs/README.md",
    "jobs/bic/README.md",
    "jobs/saw/README.md",
    "workspace-data/scripture-projects/README.md",
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
    "core/sage_core/cline_bridge.py",
}
LEGACY_REWRITE_PATHS = {
    "meta/schemas/bic-operator-decisions.schema.yml",
}

EPHEMERAL_PARTS = {
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
    """Check the source tree for missing files and common build artefacts."""
    errors: list[str] = []
    warnings: list[str] = []
    for relative in sorted(REQUIRED_PACKAGE_PATHS):
        if not (root / relative).exists():
            errors.append(f"Required package path is missing: {relative}")
    legacy_paths = [relative for relative in sorted(LEGACY_PROVIDER_PATHS) if (root / relative).exists()]
    if legacy_paths:
        errors.append("Legacy provider-specific runtime paths are not permitted: " + ", ".join(legacy_paths))
    legacy_rewrite_paths = [relative for relative in sorted(LEGACY_REWRITE_PATHS) if (root / relative).exists()]
    if legacy_rewrite_paths:
        errors.append("Legacy BIC candidate-decision paths are not permitted: " + ", ".join(legacy_rewrite_paths))
    scripture_files: list[str] = []
    artifacts: list[str] = []
    nested_archives: list[str] = []
    symlinks: list[str] = []
    stale_rc_artifacts: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            symlinks.append(str(relative).replace("\\", "/"))
            continue
        if any(part in EPHEMERAL_PARTS for part in relative.parts):
            continue
        rel_text = str(relative).replace("\\", "/")
        if path.name in FORBIDDEN_NAMES:
            artifacts.append(rel_text)
        for token in re.findall(r"(?i)rc\d+(?:[a-z]|\.\d+)?", rel_text):
            current_version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").exists() else ""
            current_match = re.search(r"(?i)rc\d+(?:[a-z]|\.\d+)?", current_version)
            current_token = current_match.group(0).casefold() if current_match else ""
            if token.casefold() != current_token:
                stale_rc_artifacts.append(rel_text)
                break
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        if path.is_file() and path.suffix.lower() in {
            ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"
        }:
            nested_archives.append(str(relative).replace("\\", "/"))
        if path.is_file() and path.suffix.lower() in {".sfm", ".usfm"}:
            scripture_files.append(str(relative).replace("\\", "/"))
    if artifacts:
        errors.append("Runtime or platform artefacts: " + ", ".join(artifacts))
    if nested_archives:
        errors.append("Nested archives are not permitted in the source package: " + ", ".join(nested_archives))
    if scripture_files:
        errors.append("Scripture payloads are not permitted in the source package: " + ", ".join(scripture_files))
    if symlinks:
        errors.append("Symbolic links are not permitted in the source package: " + ", ".join(symlinks))
    if stale_rc_artifacts:
        errors.append("Previous RC-specific artifacts are not permitted in the source package: " + ", ".join(sorted(set(stale_rc_artifacts))))
    version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").exists() else ""
    if not re.fullmatch(r"0\.01-(?:dev(?:\.\d+)?|rc\d+(?:[a-z]|\.\d+)?)", version):
        warnings.append(f"Unexpected SAGE version format: {version!r}")
    return {
        "status": "BLOCKED" if errors else ("READY_WITH_WARNINGS" if warnings else "READY"),
        "errors": errors,
        "warnings": warnings,
        "scripture_payloads": scripture_files,
        "artifacts": artifacts,
        "nested_archives": nested_archives,
        "symlinks": symlinks,
        "stale_rc_artifacts": sorted(set(stale_rc_artifacts)),
        "legacy_provider_paths": legacy_paths,
        "legacy_rewrite_paths": legacy_rewrite_paths,
    }
