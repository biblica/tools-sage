"""Storage-boundary tests for Core versus persistent localdata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage.storage import (
    DATA_HOME_ENV,
    StorageError,
    clear_persisted_data_home,
    default_data_home,
    persist_data_home,
    resolve_declared_path,
    resolve_persisted_path,
    storage_layout,
)


def _core(tmp_path: Path) -> Path:
    """Create one disposable immutable app root for a storage test."""
    root = tmp_path / "SAGE" / "app"
    root.mkdir(parents=True)
    return root


def test_default_data_home_is_sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use sibling localdata as the zero-configuration default."""
    root = _core(tmp_path)
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    clear_persisted_data_home(root)
    layout = storage_layout(root, create=True)
    assert layout.data_root == tmp_path / "SAGE" / "localdata"
    assert layout.inputs_root == layout.data_root / "inputs"
    assert layout.work_root == layout.data_root / "work"
    assert layout.projects_root == layout.work_root / "projects"
    assert layout.jobs_root == layout.work_root / "jobs"
    assert layout.resources_root == layout.inputs_root / "resources"
    assert layout.styleguides_root.is_dir()
    assert layout.semantic_domains_root.is_dir()
    assert layout.reports_root == layout.data_root / "reports"
    assert layout.projects_root.is_dir()
    assert layout.venv_root.parent == layout.runtime_root
    marker = json.loads(layout.marker_path.read_text(encoding="utf-8"))
    assert marker["product"] == "SAGE"
    assert marker["schema_version"] == 2
    assert marker["layout"] == "INPUTS_WORK_REPORTS"


def test_flat_beta_layout_is_migrated_without_data_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Move only recognized flat roots into inputs/work and preserve their contents."""
    root = _core(tmp_path)
    data = tmp_path / "SAGE" / "localdata"
    (data / ".system").mkdir(parents=True)
    (data / ".system" / "data-root.json").write_text(
        '{"schema_version":1,"product":"SAGE","data_root":"."}\n', encoding="utf-8"
    )
    (data / "projects" / "demo").mkdir(parents=True)
    (data / "projects" / "demo" / "keep.txt").write_text("preserved", encoding="utf-8")
    (data / "jobs" / "saw").mkdir(parents=True)
    (data / "resources" / "custom").mkdir(parents=True)
    monkeypatch.setenv(DATA_HOME_ENV, str(data))

    layout = storage_layout(root, create=True)

    assert (layout.projects_root / "demo" / "keep.txt").read_text(encoding="utf-8") == "preserved"
    assert not (data / "projects").exists()
    assert not (data / "jobs").exists()
    assert not (data / "resources").exists()
    marker = json.loads(layout.marker_path.read_text(encoding="utf-8"))
    assert marker["schema_version"] == 2


def test_environment_can_place_data_home_anywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow an environment override to select an external Unicode data path."""
    root = _core(tmp_path)
    target = tmp_path / "External Data" / "localdata-Δ"
    monkeypatch.setenv(DATA_HOME_ENV, str(target))
    layout = storage_layout(root, create=True)
    assert layout.data_root == target.resolve()
    assert layout.system_root.is_dir()


def test_data_home_inside_core_is_rejected(tmp_path: Path) -> None:
    """Reject localdata locations inside the Git-controlled Core tree."""
    root = _core(tmp_path)
    with pytest.raises(StorageError):
        storage_layout(root, explicit=root / "local", create=True)


def test_unrecognized_nonempty_directory_is_not_adopted(tmp_path: Path) -> None:
    """Refuse to modify a non-empty directory that is not recognized localdata."""
    root = _core(tmp_path)
    target = tmp_path / "OtherData"
    target.mkdir()
    (target / "unrelated.txt").write_text("do not touch", encoding="utf-8")
    with pytest.raises(StorageError):
        storage_layout(root, explicit=target, create=True)
    assert (target / "unrelated.txt").read_text(encoding="utf-8") == "do not touch"
    assert not (target / ".system").exists()


def test_tracked_readme_seed_is_a_recognized_empty_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allow a fresh distribution's tracked README while rejecting arbitrary files."""
    root = _core(tmp_path)
    target = tmp_path / "seeded-localdata"
    target.mkdir()
    (target / "README.md").write_text("tracked explanation\n", encoding="utf-8")
    monkeypatch.setenv(DATA_HOME_ENV, str(target))

    layout = storage_layout(root, create=True)

    assert layout.marker_path.is_file()
    assert (target / "README.md").read_text(encoding="utf-8") == "tracked explanation\n"


def test_custom_pointer_survives_core_replacement_at_same_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a persisted custom data-home pointer across Core replacement at the same path."""
    root = _core(tmp_path)
    target = tmp_path / "persistent" / "localdata"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    storage_layout(root, explicit=target, create=True)
    persist_data_home(root, target)
    root.rmdir()
    root.mkdir()
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    assert storage_layout(root).data_root == target.resolve()


def test_declared_tokens_cannot_escape_owned_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve governed tokens while preventing relative path escape."""
    root = _core(tmp_path)
    monkeypatch.setenv(DATA_HOME_ENV, str(tmp_path / "data"))
    layout = storage_layout(root, create=True)
    assert resolve_declared_path(root, "@projects/demo", "project") == layout.projects_root / "demo"
    assert resolve_declared_path(root, "@system/cache/a", "cache") == layout.cache_root / "a"
    with pytest.raises(StorageError):
        resolve_declared_path(root, "@projects/../escape", "project")


def test_legacy_absolute_flat_paths_rebase_to_categorized_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep old absolute Job records usable after both bundle and layout moves."""
    root = _core(tmp_path)
    monkeypatch.setenv(DATA_HOME_ENV, str(tmp_path / "SAGE" / "localdata"))
    layout = storage_layout(root, create=True)
    legacy = tmp_path.parent / "old-host" / "SAGEdata" / "jobs" / "saw" / "SAW_demo" / "run.json"
    assert resolve_persisted_path(root, str(legacy), "legacy run") == (
        layout.jobs_root / "saw" / "SAW_demo" / "run.json"
    )


def test_default_helper_does_not_create_paths(tmp_path: Path) -> None:
    """Keep the default-location helper side-effect free."""
    root = _core(tmp_path)
    expected = tmp_path / "SAGE" / "localdata"
    assert default_data_home(root) == expected
    assert not expected.exists()
