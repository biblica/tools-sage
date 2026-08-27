"""Paratext catalog, Project metadata, reporting, and governed OL resource tests."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sage.storage import storage_layout
from sage.canon import NT_27
from sage.jobs import JobStore
from sage.menu import SageControlCenter
from sage.original_language_resources import (
    active_ol_project_id,
    configure_ol_resource,
    paratext_ol_candidates,
    resolved_ol_entry,
    validate_original_language_resources,
)
from sage.paratext_catalog import (
    filtered_projects,
    language_filter_counts,
    load_paratext_catalog,
    rescan_catalog_project,
    scan_paratext_projects,
)
from sage.project_inventory import register_project
from sage.registry import load_ecosystem
from sage.resource_mounts import set_project_root, set_resource_mount


def _settings(path: Path, *, language: str, full_name: str, iso: str) -> None:
    """Write the minimal Paratext settings.xml metadata used by catalog tests."""
    path.write_text(
        f"<Settings><Language>{language}</Language><FullName>{full_name}</FullName>"
        f"<LanguageIsoCode>{iso}:::</LanguageIsoCode></Settings>\n",
        encoding="utf-8",
    )


def _sfm(path: Path, book: str) -> None:
    """Write one minimal readable USFM/SFM book fixture."""
    path.write_text(f"\\id {book}\n\\c 1\n\\v 1 Test.\n", encoding="utf-8")


def test_catalogue_requires_valid_settings_and_preparses_paratext_metadata(tmp_path: Path) -> None:
    """Verify settings.xml is the discovery gate and canons/custom.vrs fill cached Project data."""
    sage = tmp_path / "SAGE" / "app"
    sage.mkdir(parents=True)
    projects = tmp_path / "Paratext Projects"
    projects.mkdir()

    valid = projects / "usNIVv2"
    valid.mkdir()
    _settings(valid / "settings.xml", language="english", full_name="New International Version", iso="en")
    (valid / "canons.xml").write_text(
        "<Canons><Books>" + " ".join(NT_27) + "</Books></Canons>\n",
        encoding="utf-8",
    )
    _sfm(valid / "41MAT.SFM", "MAT")
    (valid / "custom.vrs").write_text(
        '#\n# Versification "NIV English"\n# custom.vrs by Project Team\n# custom modifications to eng.vrs (Based on RSV versification)\nMAT 1:25\n',
        encoding="utf-8",
    )

    ignored = projects / "random-backup"
    ignored.mkdir()
    _sfm(ignored / "41MAT.SFM", "MAT")

    invalid = projects / "badXML"
    invalid.mkdir()
    (invalid / "settings.xml").write_text("<Settings>", encoding="utf-8")

    result = scan_paratext_projects(sage, projects, full=True)
    assert set(result["projects"]) == {"usNIVv2"}
    assert "random-backup" not in result["projects"]
    assert result["invalid_folders"]["badXML"]["code"] == "PARATEXT_SETTINGS_INVALID"

    row = result["projects"]["usNIVv2"]
    assert row["full_name"] == "New International Version"
    assert row["language_name"] == "english"
    assert row["language_iso"] == "en"
    assert row["scope"] == "NT"
    assert row["filter_scope"] == "NT"
    assert row["book_count"] == 27
    assert row["versification"]["name"] == "NIV English"
    assert row["versification"]["base_file"] == "eng.vrs"
    assert row["versification"]["base_description"] == "Based on RSV versification"
    assert (storage_layout(sage).state_root / "paratext-project-catalog.json").is_file()


def test_catalogue_filters_are_only_scope_and_language() -> None:
    """Verify the operator filter grammar is FB/NT/Portions plus dynamic language."""
    catalogue = {
        "projects": {
            "a": {"project_code": "a", "filter_scope": "FB", "language_iso": "en", "language_name": "English"},
            "b": {"project_code": "b", "filter_scope": "NT", "language_iso": "en", "language_name": "English"},
            "c": {"project_code": "c", "filter_scope": "PORTIONS", "language_iso": "uk", "language_name": "Ukrainian"},
        }
    }
    assert [row["project_code"] for row in filtered_projects(catalogue, scope="NT")] == ["b"]
    assert [row["project_code"] for row in filtered_projects(catalogue, language_iso="en")] == ["a", "b"]
    assert [row["project_code"] for row in filtered_projects(catalogue, scope="PORTIONS", language_iso="uk")] == ["c"]
    languages = language_filter_counts(catalogue)
    assert {(row["language_iso"], row["count"]) for row in languages} == {("en", 2), ("uk", 1)}


def test_setting_projects_root_immediately_builds_persistent_catalogue(make_workspace, tmp_path: Path) -> None:
    """Selecting the Paratext root performs only the permanent tree-discovery scan."""
    root = make_workspace()
    projects = tmp_path / "Paratext Projects"
    project = projects / "faTMNv4"
    project.mkdir(parents=True)
    _settings(project / "settings.xml", language="Farsi", full_name="Farsi Test", iso="fa")
    _sfm(project / "41MAT.SFM", "MAT")

    set_project_root(root, project_root=projects)
    catalogue = load_paratext_catalog(root)
    assert catalogue["projects_root"] == str(projects.resolve())
    row = catalogue["projects"]["faTMNv4"]
    assert row["detail_status"] == "PENDING"
    assert row["language_iso"] is None
    validated = rescan_catalog_project(root, "faTMNv4")
    assert validated["detail_status"] == "VALIDATED"
    assert validated["language_iso"] == "fa"


def test_quick_scan_never_opens_project_content(tmp_path: Path, monkeypatch) -> None:
    """Quick Scan is a strict marker/tree pass and cannot invoke detailed Project readers."""
    sage = tmp_path / "SAGE" / "app"
    sage.mkdir(parents=True)
    projects = tmp_path / "Paratext Projects"
    project = projects / "enABCv1"
    project.mkdir(parents=True)
    _settings(project / "settings.xml", language="English", full_name="Fixture", iso="en")
    _sfm(project / "41MAT.SFM", "MAT")

    def forbidden(*_args, **_kwargs):
        """Fail if Quick Scan invokes a detailed Project reader."""
        raise AssertionError("quick scan opened Project content")

    monkeypatch.setattr("sage.paratext_catalog.inspect_paratext_project", forbidden)
    monkeypatch.setattr("sage.paratext_catalog._source_signature", forbidden)
    result = scan_paratext_projects(sage, projects, full=False)
    assert result["projects"]["enABCv1"]["detail_status"] == "PENDING"
    assert result["projects"]["enABCv1"]["source_signature"] is None


def test_quick_scan_handles_large_root_without_detail_reads(tmp_path: Path, monkeypatch) -> None:
    """Quick discovery stays marker-only when the Paratext root exceeds 100 subfolders."""
    sage = tmp_path / "SAGE" / "app"
    sage.mkdir(parents=True)
    projects = tmp_path / "Paratext Projects"
    expected: set[str] = set()
    for index in range(120):
        folder = projects / f"fixture-{index:03d}"
        folder.mkdir(parents=True)
        if index % 2 == 0:
            _settings(folder / "settings.xml", language="English", full_name=f"Fixture {index}", iso="en")
            expected.add(folder.name)

    def forbidden(*_args, **_kwargs):
        """Fail if a large-root Quick Scan invokes detailed Project inspection."""
        raise AssertionError("large-root quick scan opened Project content")

    monkeypatch.setattr("sage.paratext_catalog.inspect_paratext_project", forbidden)
    monkeypatch.setattr("sage.paratext_catalog._source_signature", forbidden)
    result = scan_paratext_projects(sage, projects, full=False)

    assert set(result["projects"]) == expected
    assert len(result["projects"]) == 60
    assert all(row["detail_status"] == "PENDING" for row in result["projects"].values())


def test_quick_scan_detects_added_and_removed_project_folders(tmp_path: Path) -> None:
    """Tree-only rescans refresh additions/removals without requiring detailed validation."""
    sage = tmp_path / "SAGE" / "app"
    sage.mkdir(parents=True)
    projects = tmp_path / "Paratext Projects"
    first = projects / "enONEv1"
    first.mkdir(parents=True)
    _settings(first / "settings.xml", language="English", full_name="One", iso="en")
    initial = scan_paratext_projects(sage, projects, full=False)
    assert set(initial["projects"]) == {"enONEv1"}

    second = projects / "enTWOv1"
    second.mkdir()
    _settings(second / "settings.xml", language="English", full_name="Two", iso="en")
    for child in first.iterdir():
        child.unlink()
    first.rmdir()
    refreshed = scan_paratext_projects(sage, projects, full=False)
    assert set(refreshed["projects"]) == {"enTWOv1"}


def test_paratext_ol_candidates_are_recognised_but_not_automatically_selected() -> None:
    """Verify only grcSRCv#/hboSRCv# are convenience candidates and highest iteration lists first."""
    catalogue = {
        "projects": {
            "grcSRCv1": {"project_code": "grcSRCv1", "language_iso": "grc", "code_metadata": {"iteration": 1}},
            "grcSRCv3": {"project_code": "grcSRCv3", "language_iso": "grc", "code_metadata": {"iteration": 3}},
            "grcOTHv9": {"project_code": "grcOTHv9", "language_iso": "grc", "code_metadata": {"iteration": 9}},
            "hboSRCv2": {"project_code": "hboSRCv2", "language_iso": "hbo", "code_metadata": {"iteration": 2}},
        }
    }
    assert [row["project_code"] for row in paratext_ol_candidates(catalogue, "GRK")] == ["grcSRCv3", "grcSRCv1"]
    assert [row["project_code"] for row in paratext_ol_candidates(catalogue, "HEB")] == ["hboSRCv2"]


def test_explicit_ol_override_injects_stable_grk_alias_without_project_registration(make_workspace, tmp_path: Path) -> None:
    """Verify an explicit local OL resource becomes machine ID GRK while remaining outside Project inventory."""
    root = make_workspace()
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["projects"].pop("GRK", None)
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    greek = tmp_path / "greek"
    greek.mkdir()
    _sfm(greek / "41MAT.SFM", "MAT")
    configure_ol_resource(root, resource_id="GRK", source="LOCAL", path=greek)

    resolved = resolved_ol_entry(root, "GRK")
    assert resolved["alias"] == "@GRK"
    assert resolved["status"] == "READY"
    assert active_ol_project_id(root, "GRK") == "GRK"
    assert not (storage_layout(root).state_root / "project-inventory.json").exists()
    config = load_ecosystem(settings_path)
    assert config.project("GRK").path == greek.resolve()
    assert config.project("GRK").external_readonly


def test_missing_bundled_ol_corpus_is_nonfatal_and_reported(package_root: Path) -> None:
    """Verify source builds without bundled corpus report OL capability rather than fabricating Scripture."""
    result = validate_original_language_resources(package_root)
    assert result["status"] in {"PARTIAL", "UNAVAILABLE", "READY"}
    for row in result["resources"]:
        assert row["source"] == "BUNDLED"
        assert row["alias"] in {"@GRK", "@HEB"}


def test_job_secondary_reporting_language_flows_to_bic_runtime(make_workspace) -> None:
    """Verify a Job adds a secondary report language to the global primary language."""
    root = make_workspace()
    target_path = storage_layout(root).projects_root / "usBOLx1"
    register_project(
        root,
        project_id="usBOLx1",
        project_path=target_path,
        language_code="en",
        language_profile="en",
        profile_variant="bol-target",
        base_vrs_file="eng.vrs",
        display_name="Book of Life",
        kind="GENERATED_SCRIPTURE",
        content_state="UNDER_REVIEW",
        allow_empty=True,
        coverage_policy="PRESENT_CHAPTERS_ONLY",
    )
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="bic",
        job_id="BIC_idKKHv0-usNIVv2-usBOLx1",
        display_name="Reporting test",
        bindings={"content_source": "idKKHv0", "lexical_donor": "usNIVv2", "generated_target": "usBOLx1"},
        profiles={"source_grammar": "id/source", "target_grammar": "en/bol-target"},
        defaults={"publication_enabled": True},
        secondary_report_language="uk",
    )
    runtime = yaml.safe_load(job.runtime_settings_path.read_text(encoding="utf-8"))
    assert runtime["human_output"]["operator_language"] == "en"
    assert runtime["human_output"]["logs_and_reports"]["primary_language"] == "en"
    assert runtime["human_output"]["logs_and_reports"]["secondary_language"] == "uk"
    assert runtime["human_output"]["logs_and_reports"]["bilingual"] is True
    assert runtime["human_output"]["translation_challenges"]["primary_language"] == "en"
    assert runtime["human_output"]["translation_challenges"]["secondary_language"] == "uk"
    assert yaml.safe_load(job.manifest_path.read_text(encoding="utf-8"))["reporting"] == {
        "secondary_language": "uk"
    }



def test_project_vrs_summary_uses_only_comment_reported_base_for_custom_vrs(make_workspace) -> None:
    """Verify custom.vrs summaries never present the configured SAGE base as comment-derived metadata."""
    root = make_workspace()
    center = SageControlCenter(sage_root=root, settings_path=root / "ecosystem.yml", skip_setup=True, dry_run_provider=True)
    unknown = center._project_vrs_summary(
        {
            "custom_file": "custom.vrs",
            "base_file": "eng.vrs",
            "reported_base_file": None,
            "metadata_status": "BASE_UNKNOWN",
            "name": "Local custom",
        }
    )
    assert unknown == "custom.vrs (base unknown) - Local custom"
    known = center._project_vrs_summary(
        {
            "custom_file": "custom.vrs",
            "base_file": "org.vrs",
            "reported_base_file": "eng.vrs",
            "base_description": "Based on RSV versification",
        }
    )
    assert known == "custom.vrs based on eng.vrs (Based on RSV versification)"


def test_registered_other_location_project_refreshes_without_primary_catalogue(make_workspace, tmp_path: Path) -> None:
    """Verify <Other location> Projects refresh from their mapped folder rather than projects_root/project_id."""
    root = make_workspace()
    external = tmp_path / "external" / "usALTv0"
    external.mkdir(parents=True)
    _settings(external / "settings.xml", language="English", full_name="External Project", iso="en")
    _sfm(external / "41MAT.SFM", "MAT")
    (external / "custom.vrs").write_text('#\n# Versification "External"\n# based on eng.vrs\n', encoding="utf-8")
    register_project(
        root,
        project_id="usALTv0",
        project_path=external,
        language_code="en",
        language_profile="en",
        base_vrs_file="eng.vrs",
        display_name="Old name",
    )
    set_resource_mount(root, project_id="usALTv0", external_path=external)
    center = SageControlCenter(sage_root=root, settings_path=root / "ecosystem.yml", skip_setup=True, dry_run_provider=True)
    refreshed = center._refresh_registered_from_catalog("usALTv0")
    assert refreshed["display_name"] == "External Project"
    assert refreshed["scope_summary"] == "MAT"
    assert refreshed["versification"]["reported_base_file"] == "eng.vrs"



def test_job_runtime_records_explicit_grk_override_provenance(make_workspace, tmp_path: Path) -> None:
    """Verify a READY governed @GRK override binds by stable ID and is recorded in Job runtime provenance."""
    root = make_workspace()
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["projects"].pop("GRK", None)
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    greek = tmp_path / "grcSRCv2"
    greek.mkdir()
    _sfm(greek / "41MAT.SFM", "MAT")
    configure_ol_resource(root, resource_id="GRK", source="LOCAL", path=greek)
    store = JobStore(root, settings_path)
    job = store.create_job(
        tool="bic",
        job_id="BIC_idKKHv0-usNIVv2-usBOLx1",
        display_name="OL provenance test",
        bindings={
            "content_source": "idKKHv0",
            "lexical_donor": "usNIVv2",
            "generated_target": "usBOLx1",
            "original_language_greek": "GRK",
        },
        profiles={"source_grammar": "id/source", "target_grammar": "en/bol-target"},
        defaults={"publication_enabled": True},
    )
    runtime = yaml.safe_load(job.runtime_settings_path.read_text(encoding="utf-8"))
    ol = runtime["runtime_context"]["original_language_resources"]["GRK"]
    assert ol["alias"] == "@GRK"
    assert ol["source"] == "LOCAL"
    assert ol["status"] == "READY"
    assert Path(ol["path"]) == greek.resolve()
    config = load_ecosystem(job.runtime_settings_path)
    assert job.bindings["original_language_greek"] == "GRK"
    assert config.project("GRK").path == greek.resolve()
