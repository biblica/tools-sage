"""Project scope, canon, and transparent auto-resolution tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage_core.canon import resolve_expected_books
from sage_core.errors import ConfigurationError
from sage_core.registry import load_ecosystem
from sage_core.standard import load_standard
from sage_core.validation import validate_static_ecosystem


def _run_initialize(package_root: Path, workspace: Path) -> subprocess.CompletedProcess[str]:
    """Run workspace initialisation in a disposable test process."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "core")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage_core.cli",
            "--settings",
            str(workspace / "ecosystem.yml"),
            "--json",
            "workspace",
            "initialize",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )


def test_declared_canon_resolves_expected_books(make_workspace) -> None:
    """Verify declared canon/testament metadata resolves expected books without distro fixtures."""
    root = make_workspace()
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["projects"]["idKKHv0"]["scope"] = {
        "testament": "NT", "canon": "PROTESTANT_66", "expected_books": "auto", "roles": []
    }
    data["projects"]["usNIVv2"]["scope"] = {
        "testament": "FB", "canon": "PROTESTANT_66", "expected_books": "auto", "roles": []
    }
    data["projects"]["HEB"]["scope"] = {
        "testament": "OT", "canon": "PROTESTANT_66", "expected_books": "auto", "roles": []
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(path)
    assert len(resolve_expected_books(config.project("idKKHv0").scope)) == 27
    assert len(resolve_expected_books(config.project("usNIVv2").scope)) == 66
    assert len(resolve_expected_books(config.project("HEB").scope)) == 39


def test_scope_is_required(make_workspace) -> None:
    """Verify that scope is required."""
    root = make_workspace()
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["projects"]["idKKHv0"]["scope"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=r"projects\.idKKHv0\.scope"):
        load_ecosystem(path)


def test_incompatible_auto_scope_is_rejected(make_workspace) -> None:
    """Verify that incompatible auto scope is rejected."""
    root = make_workspace()
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["projects"]["idKKHv0"]["scope"] = {
        "testament": "OT",
        "canon": "GREEK_NT_27",
        "expected_books": "auto",
        "roles": ["CONTENT_SOURCE"],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="does not provide books"):
        load_ecosystem(path)


def test_scope_validation_rejects_unexpected_book(make_workspace) -> None:
    """Verify that scope validation rejects unexpected book."""
    root = make_workspace()
    (root / "projects" / "idKKHv0" / "42MRK.SFM").write_text(
        "\\id MRK Fixture\n\\c 1\n\\p\n\\v 1 Verse 1.\n",
        encoding="utf-8",
    )
    config = load_ecosystem(root / "ecosystem.yml")
    result = validate_static_ecosystem(config, load_standard(root))
    assert result["status"] == "BLOCKED"
    assert any("outside declared scope" in item for item in result["errors"])


def test_scope_validation_and_initialization_ignore_usfm_peripheral_books(
    package_root: Path,
    make_workspace,
) -> None:
    """USFM publication matter remains hashed but is not treated as biblical canon."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project = root / "projects" / "usWIP"
    for code in ("FRT", "INT", "BAK", "OTH"):
        (project / f"A-{code}.SFM").write_text(
            f"\\id {code}\r\n\\p Peripheral publication material.\r\n",
            encoding="utf-8",
        )

    config = load_ecosystem(root / "ecosystem.yml")
    static = validate_static_ecosystem(config, load_standard(root))
    scope = static["project_scopes"]["usWIP"]
    assert scope["unexpected_books"] == []
    assert scope["peripheral_books"] == ["BAK", "FRT", "INT", "OTH"]

    result = _run_initialize(package_root, root)
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["projects"]["usWIP"]["summary"]["peripheral_books"] == [
        "BAK", "FRT", "INT", "OTH"
    ]


def test_initialize_reports_auto_without_rewriting_yaml(package_root: Path, make_workspace) -> None:
    """Verify that initialisation reports automatic values without rewriting YAML."""
    root = make_workspace(configured=True)
    settings = root / "ecosystem.yml"
    before = settings.read_bytes()
    result = _run_initialize(package_root, root)
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["auto_resolutions"]
    assert settings.read_bytes() == before
    report_root = root / "workspace-data" / "sage" / "output"
    report = (report_root / "auto-resolution-report.md").read_text(encoding="utf-8")
    assert "scope.expected_books" not in report  # Fixture scopes are explicit.
    assert "versification.custom_file" in report
    rows = json.loads((report_root / "auto-resolution-report.json").read_text(encoding="utf-8"))
    assert all(row["declared"] == "auto" for row in rows)
