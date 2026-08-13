"""Deterministic removal of generated SAGE runtime and test state."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .registry import EcosystemConfig


TEST_ARTIFACT_NAMES = {
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage",
    "coverage.xml", "htmlcov",
}


def _remove(path: Path, removed: list[str], root: Path) -> None:
    """Remove one generated path safely and record the relative path in the reset report."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        label = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        label = str(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    removed.append(label)


def reset_project_state(config: EcosystemConfig, *, include_test_artifacts: bool = True) -> dict[str, Any]:
    """Remove generated state while preserving governed source seeds and configuration."""
    removed: list[str] = []
    preserved_override: tuple[Path, bytes] | None = None
    if config.operator_overrides_path and config.operator_overrides_path.is_file():
        preserved_override = (
            config.operator_overrides_path,
            config.operator_overrides_path.read_bytes(),
        )
    # The internal Scripture README is a shipped empty-directory seed, not operator data.
    # Hardening/reset must remove generated Scripture payloads without invalidating the
    # clean source-package structure that release validation requires.
    scripture_seed = config.workspace_data_root / "scripture-projects" / "README.md"
    preserved_scripture_seed: tuple[Path, bytes] | None = None
    if scripture_seed.is_file():
        preserved_scripture_seed = (scripture_seed, scripture_seed.read_bytes())
    for governed in (config.cache_root, config.workspace_data_root):
        _remove(governed, removed, config.root)
        governed.mkdir(parents=True, exist_ok=True)
    if preserved_scripture_seed is not None:
        seed_path, seed_bytes = preserved_scripture_seed
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_bytes(seed_bytes)
    if preserved_override is not None:
        override_path, override_bytes = preserved_override
        override_path.parent.mkdir(parents=True, exist_ok=True)
        override_path.write_bytes(override_bytes)
    if include_test_artifacts:
        for path in sorted(config.root.rglob("*"), reverse=True):
            if path.name in TEST_ARTIFACT_NAMES or path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}:
                _remove(path, removed, config.root)
    return {
        "status": "RESET",
        "root": str(config.root),
        "removed": sorted(set(removed)),
        "preserved": [
            "projects",
            "ecosystem.yml",
            "profiles",
            "workflows",
            "meta",
            "workspace-data/sage/init/operator-overrides.yml (when present)",
        ],
    }
