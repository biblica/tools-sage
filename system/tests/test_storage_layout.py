"""Storage-boundary tests for Core versus persistent SAGEdata."""

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
    storage_layout,
)


def _core(tmp_path: Path) -> Path:
    """Create one disposable Git-controlled Core root for a storage test."""
    root = tmp_path / "SAGE"
    root.mkdir()
    return root


def test_default_data_home_is_sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use sibling SAGEdata as the zero-configuration default."""
    root = _core(tmp_path)
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    clear_persisted_data_home(root)
    layout = storage_layout(root, create=True)
    assert layout.data_root == tmp_path / "SAGEdata"
    assert layout.projects_root.is_dir()
    assert layout.venv_root.parent == layout.runtime_root
    marker = json.loads(layout.marker_path.read_text(encoding="utf-8"))
    assert marker["product"] == "SAGE"


def test_environment_can_place_data_home_anywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow an environment override to select an external Unicode data path."""
    root = _core(tmp_path)
    target = tmp_path / "External Data" / "SAGEdata-Δ"
    monkeypatch.setenv(DATA_HOME_ENV, str(target))
    layout = storage_layout(root, create=True)
    assert layout.data_root == target.resolve()
    assert layout.system_root.is_dir()


def test_data_home_inside_core_is_rejected(tmp_path: Path) -> None:
    """Reject SAGEdata locations inside the Git-controlled Core tree."""
    root = _core(tmp_path)
    with pytest.raises(StorageError):
        storage_layout(root, explicit=root / "local", create=True)


def test_unrecognized_nonempty_directory_is_not_adopted(tmp_path: Path) -> None:
    """Refuse to modify a non-empty directory that is not recognized SAGEdata."""
    root = _core(tmp_path)
    target = tmp_path / "OtherData"
    target.mkdir()
    (target / "unrelated.txt").write_text("do not touch", encoding="utf-8")
    with pytest.raises(StorageError):
        storage_layout(root, explicit=target, create=True)
    assert (target / "unrelated.txt").read_text(encoding="utf-8") == "do not touch"
    assert not (target / ".system").exists()


def test_custom_pointer_survives_core_replacement_at_same_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a persisted custom data-home pointer across Core replacement at the same path."""
    root = _core(tmp_path)
    target = tmp_path / "persistent" / "SAGEdata"
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


def test_default_helper_does_not_create_paths(tmp_path: Path) -> None:
    """Keep the default-location helper side-effect free."""
    root = _core(tmp_path)
    expected = tmp_path / "SAGEdata"
    assert default_data_home(root) == expected
    assert not expected.exists()
