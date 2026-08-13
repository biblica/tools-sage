"""Shared fixtures for SAGE integration-foundation tests."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PACKAGE_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    """Write stable UTF-8 YAML for one fixture file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def simple_usfm(book: str = "MAT", verses: int = 3) -> str:
    """Return a compact structurally valid USFM fixture."""
    lines = [f"\\id {book} Fixture", "\\c 1", "\\p"]
    for verse in range(1, verses + 1):
        lines.append(f"\\v {verse} Verse {verse}.")
    return "\n".join(lines) + "\n"


def grammar_profile(profile_id: str, language: str, role: str) -> dict[str, Any]:
    """Return a governed grammar profile suitable for integration fixtures."""
    target_role = role.upper() in {"TARGET", "WIP"}
    check_count = 8 if target_role else 3
    value: dict[str, Any] = {
        "profile": {
            "schema_version": "2.0",
            "id": profile_id,
            "language": language,
            "script": "Latn",
            "role": role,
            "status": "ACTIVE",
            "purpose": "fixture_support",
            "owner_role": "PROJECT_LEAD",
            "last_reviewed": "2026-08-03",
        },
        "checks": [
            {
                "id": f"{profile_id.upper()}-{index:03d}",
                "dimension": dimension,
                "review": f"Review {dimension.replace('_', ' ')} in the bounded fixture evidence.",
                "caution": "Do not approve automatically; report evidence and uncertainty.",
            }
            for index, dimension in enumerate(
                (
                    "meaning",
                    "participant_reference",
                    "word_order",
                    "clause_structure",
                    "verb_form",
                    "terminology",
                    "punctuation",
                    "naturalness",
                )[:check_count],
                start=1,
            )
        ],
        "normalization": {"unicode": "NFC", "preserve_script": True},
        "project_decisions": [],
        "approved_exceptions": [],
    }
    if target_role:
        value.update(
            {
                "governance": {
                    "authority": "fixture_project_team",
                    "human_approval_required": True,
                },
                "evidence_priority": [
                    "bounded_project_text",
                    "approved_project_decisions",
                    "declared_contemporary_source",
                    "relevant_original_language_source",
                ],
                "usage": {
                    "apply_to": ["rewrite", "self_check", "qa", "focused", "ol"],
                    "report_rule_ids": True,
                },
                "finding_requirements": [
                    "Cite each applicable rule ID.",
                    "Separate grammar findings from general meaning findings.",
                ],
                "restrictions": [
                    "Do not invent project rules.",
                    "Do not promote AI-generated guidance to approved project grammar.",
                ],
            }
        )
    return value


DEFAULT_POLICY = {
    "target_estimated_tokens": 18000,
    "hard_estimated_tokens": 28000,
    "hard_serialized_bytes": 196000,
    "minimum_target_tokens": 6000,
    "maximum_primary_verse_units": 220,
    "context_before_verses": 1,
    "context_after_verses": 1,
    "allow_cross_chapter_units": True,
}


@pytest.fixture
def package_root() -> Path:
    """Return the checked-out SAGE source root."""
    return PACKAGE_ROOT


@pytest.fixture
def make_workspace(tmp_path: Path):
    """Create one configured disposable SAGE workspace."""

    def factory(
        *,
        configured: bool = True,
        qualification_status: str = "IN_PROGRESS",
        verse_max: int = 3,
    ) -> Path:
        """Create an isolated test workspace from the requested fixture options."""
        # Build each fixture in an isolated directory so tests cannot share generated state.
        root = tmp_path / "SAGE"
        root.mkdir()
        (root / "VERSION").write_text((PACKAGE_ROOT / "VERSION").read_text(encoding="utf-8"), encoding="utf-8")
        shutil.copytree(PACKAGE_ROOT / "meta", root / "meta")
        shutil.copytree(PACKAGE_ROOT / "skills", root / "skills")
        projects_root = root / "projects"
        projects_root.mkdir()
        (projects_root / "eng.vrs").write_text(f"MAT 1:{verse_max}\n", encoding="utf-8")
        (projects_root / "org.vrs").write_text(f"MAT 1:{verse_max}\n", encoding="utf-8")

        projects = {
            "idKKHv0": {
                "enabled": True,
                "path": "idKKHv0",
                "language": "id",
                "format": "USFM",
                "kind": "SCRIPTURE",
                "content_state": "LOCKED",
                "scope": {"testament": "PORTIONS", "canon": "PROTESTANT_66", "expected_books": ["MAT"], "roles": []},
                "coverage_policy": "CONFIGURED_BOOKS_COMPLETE",
                "versification": {"base_file": "eng.vrs", "custom_file": "auto"},
            },
            "usNIRVv2": {
                "enabled": True,
                "path": "usNIRVv2",
                "language": "en",
                "format": "USFM",
                "kind": "SCRIPTURE",
                "content_state": "LOCKED",
                "scope": {"testament": "PORTIONS", "canon": "PROTESTANT_66", "expected_books": ["MAT"], "roles": []},
                "coverage_policy": "CONFIGURED_BOOKS_COMPLETE",
                "versification": {"base_file": "eng.vrs", "custom_file": "auto"},
            },
            "usBOLx1": {
                "enabled": True,
                "path": "usBOLx1",
                "language": "en",
                "format": "USFM",
                "kind": "GENERATED_SCRIPTURE",
                "content_state": "UNDER_REVIEW",
                "producer": "bic",
                "scope": {"testament": "PORTIONS", "canon": "PROTESTANT_66", "expected_books": ["MAT"], "roles": []},
                "coverage_policy": "CONFIGURED_BOOKS_COMPLETE",
                "versification": {"base_file": "eng.vrs", "custom_file": "auto"},
            },
            "usWIP": {
                "enabled": True,
                "path": "usWIP",
                "language": "en",
                "format": "USFM",
                "kind": "SCRIPTURE",
                "content_state": "UNDER_REVIEW",
                "scope": {"testament": "PORTIONS", "canon": "PROTESTANT_66", "expected_books": ["MAT"], "roles": []},
                "coverage_policy": "CONFIGURED_BOOKS_COMPLETE",
                "versification": {"base_file": "eng.vrs", "custom_file": "auto"},
            },
            "usNIVv2": {
                "enabled": True,
                "path": "usNIVv2",
                "language": "en",
                "format": "USFM",
                "kind": "SCRIPTURE",
                "content_state": "LOCKED",
                "scope": {"testament": "PORTIONS", "canon": "PROTESTANT_66", "expected_books": ["MAT"], "roles": []},
                "coverage_policy": "CONFIGURED_BOOKS_COMPLETE",
                "versification": {"base_file": "eng.vrs", "custom_file": "auto"},
            },
            "GRK": {
                "enabled": True,
                "path": "GRK",
                "language": "grc",
                "format": "USFM",
                "kind": "SCRIPTURE",
                "content_state": "LOCKED",
                "scope": {"testament": "PORTIONS", "canon": "PROTESTANT_66", "expected_books": ["MAT"], "roles": []},
                "coverage_policy": "CONFIGURED_BOOKS_COMPLETE",
                "versification": {"base_file": "org.vrs", "custom_file": "auto"},
            },
            "HEB": {
                "enabled": True,
                "path": "HEB",
                "language": "hbo",
                "format": "USFM",
                "kind": "SCRIPTURE",
                "content_state": "LOCKED",
                "scope": {"testament": "PORTIONS", "canon": "PROTESTANT_66", "expected_books": ["MAT"], "roles": []},
                "coverage_policy": "CONFIGURED_BOOKS_COMPLETE",
                "versification": {"base_file": "org.vrs", "custom_file": "auto"},
            },
        }
        project_roles = {
            "idKKHv0": ["CONTENT_SOURCE"],
            "usNIRVv2": ["AUXILIARY_SCRIPTURE"],
            "usBOLx1": ["GENERATED_TARGET"],
            "usWIP": ["WIP"],
            "usNIVv2": ["REFERENCE", "LEXICAL_DONOR"],
            "GRK": ["ORIGINAL_LANGUAGE_GREEK"],
            "HEB": ["ORIGINAL_LANGUAGE_HEBREW"],
        }
        for project_id, item in projects.items():
            item["scope"]["roles"] = project_roles[project_id]

        project_variants = {"idKKHv0": "source", "usBOLx1": "bol-target", "usWIP": "bol-target"}
        for project_id, item in projects.items():
            code = item["language"]
            item["language"] = {"code": code, "profile": code}
            if project_id in project_variants:
                item["language"]["variant"] = project_variants[project_id]
            folder = projects_root / item["path"]
            folder.mkdir()
            (folder / "41MAT.SFM").write_text(
                simple_usfm(verses=verse_max),
                encoding="utf-8",
            )

        write_yaml(
            root / "profiles" / "languages" / "id" / "source.yml",
            grammar_profile("source", "id", "CONTENT_SOURCE"),
        )
        write_yaml(
            root / "profiles" / "languages" / "en" / "bol-target.yml",
            grammar_profile("bol-target", "en", "TARGET"),
        )

        bic_profile = {
            "workflow": {
                "id": "bic",
                "name": "Biblical Interpretation and Composition",
                "purpose": "Controlled fixture BIC workflow.",
                "qualification_status": qualification_status,
                "baseline_version": "4.00",
                "execution_model": "SAGE_GOVERNED_TASK_V1",
            },
            "bindings": {
                "CONTENT_SOURCE": "idKKHv0",
                "LEXICAL_DONOR": "usNIVv2",
                "GENERATED_TARGET": "usBOLx1",
                "ORIGINAL_LANGUAGE_GREEK": "GRK",
                "ORIGINAL_LANGUAGE_HEBREW": "HEB",
            },
            "evidence_policies": {"default": DEFAULT_POLICY},
            "permissions": {"may_write_projects": ["usBOLx1"]},
            "process": {
                "stages": ["INSPECT", "REWRITE", "SELF_CHECK", "TRANSACTIONAL_COMMIT"],
                "rules": ["Fixture BIC authority contract."],
            },
            "qualification_gates": ["fixture_gate"],
        }
        saw_profile = {
            "workflow": {
                "id": "saw",
                "name": "Scripture Analysis Workbench",
                "purpose": "Read-only fixture SAW workflow.",
                "qualification_status": qualification_status,
                "baseline_version": "A0002-current",
                "execution_model": "SAGE_GOVERNED_TASK_V1",
            },
            "bindings": {
                "WIP": "usWIP",
                "REFERENCE": "usNIVv2",
                "ORIGINAL_LANGUAGE_GREEK": "GRK",
                "ORIGINAL_LANGUAGE_HEBREW": "HEB",
            },
            "evidence_policies": {"default": DEFAULT_POLICY, "focused": DEFAULT_POLICY},
            "permissions": {"may_write_projects": []},
            "process": {
                "stages": [
                    "DETERMINISTIC_PREFLIGHT",
                    "STRUCTURAL_ADJUDICATION",
                    "TRANSLATION_AND_MEANING_QA",
                    "SELECTIVE_OL_ADJUDICATION",
                    "COVERAGE_RECONCILIATION",
                    "DETERMINISTIC_FINALISATION",
                ],
                "rules": ["Fixture SAW composite QA contract."],
            },
            "qualification_gates": ["fixture_gate"],
        }
        write_yaml(root / "workflows" / "bic" / "profile.yml", bic_profile)
        write_yaml(root / "workflows" / "saw" / "profile.yml", saw_profile)

        settings = {
            "ecosystem": {
                "schema_version": "0.04",
                "id": "sage",
                "name": "Fixture SAGE",
                "configured": configured,
            },
            "paths": {
                "projects_root": "projects",
                "base_vrs_root": "projects",
                "cache_root": "cache",
                "workspace_data_root": "workspace-data",
            },
            "versification": {
                "canonical_file": "org.vrs",
                "base_files": ["eng.vrs", "org.vrs"],
                "custom_file_default": "custom.vrs",
            },
            "language_profiles": {
                "id": {
                    "script": "Latn",
                    "variants": {
                        "source": {
                            "file": "profiles/languages/id/source.yml",
                            "role": "CONTENT_SOURCE",
                        }
                    },
                },
                "en": {
                    "script": "Latn",
                    "variants": {
                        "bol-target": {
                            "file": "profiles/languages/en/bol-target.yml",
                            "role": "TARGET",
                        }
                    },
                },
                "grc": {"script": "Grek", "variants": {}},
                "hbo": {"script": "Hebr", "variants": {}},
            },
            "projects": projects,
            "workflows": {
                "bic": {
                    "profile": "workflows/bic/profile.yml",
                    "state_root": "workspace-data/bic/state",
                    "lock_root": "workspace-data/bic/locks",
                    "transaction_root": "workspace-data/bic/transactions",
                    "output_root": "workspace-data/bic/output",
                    "publication_root": "workspace-data/bic/output/published-targets",
                },
                "saw": {
                    "profile": "workflows/saw/profile.yml",
                    "state_root": "workspace-data/saw/state",
                    "lock_root": "workspace-data/saw/locks",
                    "transaction_root": "workspace-data/saw/transactions",
                    "output_root": "workspace-data/saw/output",
                },
            },
        }
        write_yaml(root / "ecosystem.yml", settings)
        return root

    return factory
