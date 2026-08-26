"""Deterministic removal of regenerable SAGE system/test state."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .registry import EcosystemConfig

TEST_ARTIFACT_NAMES = {
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage",
    "coverage.xml", "htmlcov",
}


def _remove(path: Path, removed: list[str], label_root: Path) -> None:
    """Remove one generated path without following directory symlinks."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        label = path.resolve().relative_to(label_root.resolve()).as_posix()
    except ValueError:
        label = str(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    removed.append(label)


def reset_project_state(config: EcosystemConfig, *, include_test_artifacts: bool = True) -> dict[str, Any]:
    """Clear regenerable SAGE-owned state while preserving operator Projects, Jobs, reports and settings."""
    removed: list[str] = []
    # Local settings and the managed runtime are durable installation state. Everything
    # else in these known .system subtrees is safe to regenerate.
    for path in (
        config.system_root / "state",
        config.system_root / "indexes",
        config.system_root / "cache",
        config.system_root / "locks",
        config.system_root / "transactions",
        config.system_root / "logs",
        config.system_root / "diagnostics",
        config.system_root / "temp",
        config.system_root / "workflows",
        config.system_root / "jobs",
    ):
        _remove(path, removed, config.data_root)
        path.mkdir(parents=True, exist_ok=True)
    if include_test_artifacts:
        for path in sorted(config.root.rglob("*"), reverse=True):
            if path.name in TEST_ARTIFACT_NAMES or path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
                _remove(path, removed, config.root)
    return {
        "status": "RESET",
        "root": str(config.root),
        "data_root": str(config.data_root),
        "removed": sorted(set(removed)),
        "preserved": [
            "SAGE Core",
            "SAGEdata/projects",
            "SAGEdata/jobs",
            "SAGEdata/resources",
            "SAGEdata/plugins",
            "SAGEdata/reports",
            "SAGEdata/exports",
            "SAGEdata/.system/config",
            "SAGEdata/.system/runtime/venv",
        ],
    }
