"""Tree-only resource discovery and drift detection tests."""

from __future__ import annotations

from pathlib import Path

from sage.resource_discovery import quick_resource_discovery
from sage.resource_mounts import set_project_root


def _marker(project: Path) -> None:
    """Create only the Paratext marker needed for tree discovery."""
    project.mkdir(parents=True, exist_ok=True)
    (project / "settings.xml").write_text("<Settings/>", encoding="utf-8")


def test_resource_discovery_baselines_then_detects_project_tree_drift(make_workspace, tmp_path: Path) -> None:
    """The first pass establishes a baseline; later passes report added/removed tree entries."""
    root = make_workspace()
    projects = tmp_path / "Paratext Projects"
    first = projects / "enONEv1"
    _marker(first)
    set_project_root(root, project_root=projects)

    baseline = quick_resource_discovery(root)
    assert baseline["status"] == "BASELINE"
    assert baseline["change_count"] == 0
    assert baseline["groups"]["paratext_projects"]["entries"] == ["enONEv1"]

    for item in first.iterdir():
        item.unlink()
    first.rmdir()
    _marker(projects / "enTWOv1")

    changed = quick_resource_discovery(root)
    assert changed["status"] == "CHANGED"
    assert changed["changes"]["paratext_projects"]["added"] == ["enTWOv1"]
    assert changed["changes"]["paratext_projects"]["removed"] == ["enONEv1"]


def test_resource_discovery_uses_names_not_resource_content(make_workspace, tmp_path: Path, monkeypatch) -> None:
    """Tree drift detection must not invoke Scripture inventory/content validation."""
    root = make_workspace()
    projects = tmp_path / "Paratext Projects"
    _marker(projects / "enONEv1")
    set_project_root(root, project_root=projects)

    def forbidden(*_args, **_kwargs):
        """Fail if tree drift detection invokes Scripture content inspection."""
        raise AssertionError("resource discovery opened resource content")

    monkeypatch.setattr("sage.original_language_resources.detect_scripture_books", forbidden)
    result = quick_resource_discovery(root)
    assert result["status"] == "BASELINE"
