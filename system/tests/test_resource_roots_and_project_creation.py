"""Cross-platform path normalization, reusable project roots, and in-context resource registration."""

from __future__ import annotations

import io
import json
from pathlib import Path

from sage.storage import storage_layout
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.registry import load_ecosystem
from sage.project_inventory import register_project
from sage.resource_mounts import (
    discover_project_folders,
    load_resource_mount_state,
    interpret_operator_project_location,
    normalize_operator_path,
    set_project_root,
    set_resource_mount,
)


def test_operator_path_normalisation_accepts_shell_paste_forms() -> None:
    """Verify that quoted and escaped Unix path pastes normalize without shell evaluation."""
    expected = "/Volumes/Win11Arm64/Paratext Projects/faTMNv4"
    assert normalize_operator_path(expected) == expected
    assert normalize_operator_path(f"'{expected}'") == expected
    assert normalize_operator_path(f'"{expected}"') == expected
    assert normalize_operator_path("/Volumes/Win11Arm64/Paratext\\ Projects/faTMNv4") == expected



def test_project_location_accepts_quoted_parent_projects_root(tmp_path: Path) -> None:
    """Verify a selected project can be resolved from a quoted parent Projects root paste."""
    parent = tmp_path / "Paratext Projects"
    child = parent / "ukrNPU"
    child.mkdir(parents=True)
    project_path, inferred_root, inferred_folder = interpret_operator_project_location(
        "ukrNPU", f"'{parent}'"
    )
    assert project_path == child.resolve()
    assert inferred_root == parent.resolve()
    assert inferred_folder == "ukrNPU"


def test_project_location_accepts_quoted_direct_project_folder(tmp_path: Path) -> None:
    """Verify a quoted direct project-folder paste remains a direct explicit mapping."""
    child = tmp_path / "Some Other Name"
    child.mkdir()
    project_path, inferred_root, inferred_folder = interpret_operator_project_location(
        "ukrNPU", f'"{child}"'
    )
    assert project_path == child.resolve()
    assert inferred_root is None
    assert inferred_folder is None

def test_root_relative_mount_persists_root_and_subfolder(make_workspace, tmp_path: Path) -> None:
    """Verify that one projects root can back a resource mapping without repeating its absolute path."""
    root = make_workspace()
    paratext_root = tmp_path / "Paratext Projects"
    project = paratext_root / "faTMNv4"
    project.mkdir(parents=True)
    (project / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 Test.\n", encoding="utf-8")
    (project / "settings.xml").write_text("<Settings><Language>Farsi</Language><FullName>Test Project</FullName><LanguageIsoCode>fa:::</LanguageIsoCode></Settings>\n", encoding="utf-8")
    set_project_root(root, project_root=paratext_root)
    set_resource_mount(
        root,
        project_id="usWIP",
        project_folder="faTMNv4",
    )
    state = load_resource_mount_state(root)
    mount = state["mounts"]["usWIP"]
    assert state["projects_root"] == str(paratext_root.resolve())
    assert mount["project_folder"] == "faTMNv4"
    assert Path(mount["path"]) == project.resolve()
    persisted = json.loads(
        (storage_layout(root).state_root / "resource-mounts.json").read_text(
            encoding="utf-8"
        )
    )
    assert "path" not in persisted["mounts"]["usWIP"]
    assert persisted["mounts"]["usWIP"]["project_folder"] == "faTMNv4"
    assert discover_project_folders(paratext_root) == ("faTMNv4",)


def test_saw_job_creation_can_add_new_detected_wip(make_workspace, tmp_path: Path) -> None:
    """Verify that Create SAW Job can add a role-neutral WIP Project to SAGE without leaving the wizard."""
    root = make_workspace()
    paratext_root = tmp_path / "Paratext Projects"
    project = paratext_root / "newWIP"
    project.mkdir(parents=True)
    (project / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 Test.\n", encoding="utf-8")
    (project / "settings.xml").write_text(
        "<Settings><Language>English</Language><FullName>New WIP</FullName><LanguageIsoCode>en:::</LanguageIsoCode></Settings>\n",
        encoding="utf-8",
    )
    set_project_root(root, project_root=paratext_root)
    register_project(
        root,
        project_id="usNIVv2",
        project_path=storage_layout(root).projects_root / "usNIVv2",
        language_code="en",
        base_vrs_file="eng.vrs",
        display_name="Reference",
    )

    responses = [
        "2",  # WIP: numeric action to enter Add Projects to SAGE
        "1",  # discovered newWIP
        "3",  # language identification: set primary audience country
        "not-a-country", # invalid direct input returns actionable country-entry guidance
        "en-US", # direct regional language tag resolves the ISO-3166 primary audience country
        "1",  # accept governed language identification
        "1",  # create the governed en-US Language Profile namespace
        "",   # Add this Project to SAGE? [Y]
        "1",  # back in WIP selector: choose newWIP
        "2",  # REFERENCE: choose usNIVv2
        "1",  # first create attempt; missing WIP grammar profile routes to maintenance
        "1",  # choose from existing grammar-profile list
        "1",  # select packaged en-US/wip
        "",   # register this grammar profile? [Y]
        "1",  # retry Create Job after profile registration
        "",   # pause after creation
    ]
    output = io.StringIO()
    centre = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput(responses), output=output),
        skip_setup=True,
    )
    centre.create_job_wizard("saw")

    config = load_ecosystem(root / "ecosystem.yml")
    sage_project = config.project("newWIP")
    assert sage_project.scope.roles == ()
    assert sage_project.external_readonly
    assert sage_project.path == project.resolve()
    inventory = json.loads(
        (storage_layout(root).state_root / "project-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    assert inventory["projects"]["newWIP"]["scope"]["roles"] == []
    created = centre.store.load_job("SAW_newWIP-usNIVv2", tool="saw")
    assert created.bindings["wip"] == "newWIP"
    assert created.bindings["reference"] == "usNIVv2"
    rendered = output.getvalue()
    assert "Accepted examples: US, USA, 840, United States, en-US." in rendered
    assert "Enter a listed number or a country as US, USA, 840, United States, or en-US." in rendered
    transcript = output.getvalue()
    assert "Job name            SAW_newWIP-usNIVv2" in transcript
    assert "Created and selected Job: SAW_newWIP-usNIVv2" in transcript


def test_release_package_starts_with_empty_scripture_inventory(package_root: Path) -> None:
    """Verify the shipped alpha configuration contains no pre-registered Scripture Project data."""
    import yaml
    from sage.resource_validation import validate_scripture_resources

    raw = yaml.safe_load((package_root / "ecosystem.yml").read_text(encoding="utf-8"))
    assert raw["projects"] == {}
    assert not (
        storage_layout(package_root).state_root / "project-inventory.json"
    ).exists()
    result = validate_scripture_resources(package_root, package_root / "ecosystem.yml")
    assert result["status"] == "READY_EMPTY"
    assert result["registered_projects"] == 0
    assert result["mapped_projects"] == 0
    assert result["base_vrs"]
    assert all(row["status"] == "READY" for row in result["base_vrs"])


def test_original_language_resources_are_not_ordinary_project_registration_roles(make_workspace, tmp_path: Path) -> None:
    """Verify governed @GRK/@HEB configuration remains separate from ordinary Project registration."""
    from sage.resource_registration import compatible_language_options

    root = make_workspace()
    assert compatible_language_options(root / "ecosystem.yml", "ORIGINAL_LANGUAGE_GREEK") == ()
    assert compatible_language_options(root / "ecosystem.yml", "ORIGINAL_LANGUAGE_HEBREW") == ()
