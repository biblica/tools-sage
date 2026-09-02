"""Project scope, canon, and transparent auto-resolution tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.canon import (
    BOOKS_66,
    NT_27,
    format_project_book_scope,
    parse_project_book_scope,
    resolve_expected_books,
)
from sage.errors import ConfigurationError
from sage.registry import load_ecosystem
from sage.standard import load_standard
from sage.validation import validate_static_ecosystem


def _run_initialize(package_root: Path, workspace: Path) -> subprocess.CompletedProcess[str]:
    """Run workspace initialization in a disposable test process."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
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


def test_project_book_scope_accepts_presets_unions_and_usfm_ranges() -> None:
    """Onboarding scope accepts presets alongside individual IDs and ranges."""
    assert parse_project_book_scope("FB") == BOOKS_66
    assert parse_project_book_scope("NT, PSA") == ("PSA", *NT_27)
    assert parse_project_book_scope("LUK-ACT") == ("LUK", "JHN", "ACT")
    combined = parse_project_book_scope("GEN-DEU, MAT MRK")
    assert combined == ("GEN", "EXO", "LEV", "NUM", "DEU", "MAT", "MRK")
    assert parse_project_book_scope(format_project_book_scope(combined)) == combined


@pytest.mark.parametrize("value", ["ACT-LUK", "MAT-XYZ", "XYZ", "-"])
def test_project_book_scope_rejects_invalid_or_reversed_ranges(value: str) -> None:
    """Invalid USFM IDs and reverse canonical ranges receive an input error."""
    with pytest.raises(ConfigurationError):
        parse_project_book_scope(value)


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


def test_scope_validation_and_initialization_ignore_out_of_scope_book(
    package_root: Path,
    make_workspace,
) -> None:
    """Out-of-scope early WIP is reported but neither read nor made blocking."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    (storage_layout(root).projects_root / "idKKHv0" / "19PSA.SFM").write_bytes(
        b"\\id PSA Early WIP\n\\c 1\n\\v 1 unread outside scope: \xff\n"
    )
    config = load_ecosystem(root / "ecosystem.yml")
    static = validate_static_ecosystem(config, load_standard(root))
    scope = static["project_scopes"]["idKKHv0"]
    assert static["status"] != "BLOCKED"
    assert scope["unexpected_books"] == ["PSA"]
    assert not any("outside declared scope" in item for item in static["errors"])

    result = _run_initialize(package_root, root)
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    project = payload["projects"]["idKKHv0"]
    assert project["status"] == "READY"
    assert project["summary"]["books"] == ["MAT"]
    assert project["summary"]["ignored_out_of_scope_books"] == ["PSA"]


def test_scope_validation_and_initialization_ignore_usfm_peripheral_books(
    package_root: Path,
    make_workspace,
) -> None:
    """USFM publication matter remains hashed but is not treated as biblical canon."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project = storage_layout(root).projects_root / "usWIP"
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
    """Verify that initialization reports automatic values without rewriting YAML."""
    root = make_workspace(configured=True)
    settings = root / "ecosystem.yml"
    before = settings.read_bytes()
    result = _run_initialize(package_root, root)
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["auto_resolutions"]
    assert settings.read_bytes() == before
    report_root = storage_layout(root).reports_root / "initialization"
    report = (report_root / "auto-resolution-report.md").read_text(encoding="utf-8")
    assert "scope.expected_books" not in report  # Fixture scopes are explicit.
    assert "versification.custom_file" in report
    rows = json.loads((report_root / "auto-resolution-report.json").read_text(encoding="utf-8"))
    assert all(row["declared"] == "auto" for row in rows)


def test_explicit_other_book_validation_issue_does_not_intersect_requested_scope() -> None:
    """An issue that explicitly names another book must not block this bounded scope."""
    from sage.references import parse_scope
    from sage.scripture import _issue_intersects_scope

    issue = {
        "code": "EXPECTED_COORDINATE_MISSING",
        "reference": "MAT 1:4",
        "message": "Coordinate is expected by the effective VRS and is not covered.",
    }
    assert _issue_intersects_scope(issue, parse_scope("RUT 1:1-8")) is False
    assert _issue_intersects_scope(issue, parse_scope("MAT 1:1-3")) is False
    assert _issue_intersects_scope(issue, parse_scope("MAT 1:4-8")) is True



def test_parser_issue_uses_precise_message_coordinate_over_book_only_reference() -> None:
    """A parser issue's precise message coordinate controls bounded-scope intersection."""
    from sage.references import parse_scope
    from sage.scripture import _issue_intersects_scope

    issue = {
        "code": "USFM_PARSER_ERROR",
        "reference": "RUT",
        "message": "RUT 1:17:UNEXPECTED_NOTE_CLOSING_MARKER:fr",
    }
    assert _issue_intersects_scope(issue, parse_scope("RUT 1:1-8")) is False
    assert _issue_intersects_scope(issue, parse_scope("RUT 1:14-17")) is True


def test_parser_issue_does_not_treat_marker_names_as_scripture_books() -> None:
    """Marker fragments such as fr/ft must not become false Scripture references."""
    from sage.references import parse_scope
    from sage.scripture import _issue_intersects_scope

    issue = {
        "code": "USFM_PARSER_ERROR",
        "reference": "RUT",
        "message": "RUT 2:12:UNEXPECTED_NOTE_CLOSING_MARKER:fr",
    }
    assert _issue_intersects_scope(issue, parse_scope("RUT 1:1-8")) is False
    assert _issue_intersects_scope(issue, parse_scope("RUT 2:12-15")) is True


def test_daniel_org_coordinate_differences_are_advisory_when_eng_default_explains_them(make_workspace) -> None:
    """English/KJV Daniel numbering must explain ORG-vs-ENG coordinate differences without hiding true omissions."""
    import yaml
    from sage.registry import load_ecosystem
    from sage.scripture import is_default_vrs_compatible_issue

    root = make_workspace(configured=True)
    base_vrs_root = root / "system" / "resources" / "scripture"
    (base_vrs_root / "eng.vrs").write_text(
        "MAT 1:4\nDAN 1:21 2:49 3:30 4:37 5:31 6:28 7:28 8:27 9:27 10:21 11:45 12:13\n"
        "DAN 4:1-3 = DAN 3:31-33\nDAN 4:4-37 = DAN 4:1-34\nDAN 5:31 = DAN 6:1\nDAN 6:1-28 = DAN 6:2-29\n",
        encoding="utf-8",
    )
    (base_vrs_root / "org.vrs").write_text(
        "MAT 1:4\nDAN 1:21 2:49 3:33 4:34 5:30 6:29 7:28 8:27 9:27 10:21 11:45 12:13\n",
        encoding="utf-8",
    )
    settings = root / "ecosystem.yml"
    raw = yaml.safe_load(settings.read_text(encoding="utf-8"))
    raw["versification"]["default_file"] = "eng.vrs"
    raw["projects"]["usNIVv2"]["versification"]["base_file"] = "org.vrs"
    settings.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(settings)
    project = config.project("usNIVv2")

    advisory_rows = [
        {"code": "EXPECTED_COORDINATE_MISSING", "reference": "DAN 3:31", "message": "missing"},
        {"code": "EXPECTED_COORDINATE_MISSING", "reference": "DAN 3:33", "message": "missing"},
        {"code": "COORDINATE_OUTSIDE_VRS", "reference": "DAN 4:35", "message": "outside"},
        {"code": "COORDINATE_OUTSIDE_VRS", "reference": "DAN 4:37", "message": "outside"},
        {"code": "COORDINATE_OUTSIDE_VRS", "reference": "DAN 5:31", "message": "outside"},
        {"code": "EXPECTED_COORDINATE_MISSING", "reference": "DAN 6:29", "message": "missing"},
    ]
    assert all(is_default_vrs_compatible_issue(config, project, row) for row in advisory_rows)

    # A real omission required by ENG/KJV is not downgraded.
    assert not is_default_vrs_compatible_issue(
        config,
        project,
        {"code": "EXPECTED_COORDINATE_MISSING", "reference": "MAT 1:4", "message": "missing"},
    )
