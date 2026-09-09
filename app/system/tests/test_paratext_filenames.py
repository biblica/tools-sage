"""Settings.xml controls imported Scripture, including snapshot selection."""

import pytest
from dataclasses import replace

from sage.errors import ValidationError
from sage.job_snapshots import capture_wip_snapshot
from sage.paratext_catalog import inspect_paratext_project
from sage.project_inventory import detect_scripture_books
from sage.registry import load_ecosystem
from sage.scripture import compile_project, discover_usfm_files
from sage.storage import storage_layout


def settings(root, *, prefix="", suffix="faTMNv4.SFM", form="41MAT"):
    """Write an independent Paratext filename-template fixture."""
    (root / "Settings.xml").write_text(
        f"<ScriptureText><Language>Farsi</Language><LanguageIsoCode>fa</LanguageIsoCode>"
        f"<FileNamePrePart>{prefix}</FileNamePrePart>"
        f"<FileNamePostPart>{suffix}</FileNamePostPart>"
        f"<FileNameBookNameForm>{form}</FileNameBookNameForm></ScriptureText>",
        encoding="utf-8",
    )


@pytest.mark.parametrize(("form", "name"), [
    ("41MAT", "pre41MATfaTMNv4.SFM"), ("MAT", "preMATfaTMNv4.SFM"),
    ("41", "pre41faTMNv4.SFM"), ("40", "pre41faTMNv4.SFM"),
])
def test_discovery_uses_complete_settings_template(tmp_path, form, name):
    """Only exact prefix, book-form and suffix matches may supply imported Scripture."""
    settings(tmp_path, prefix="pre", form=form)
    active = tmp_path / name
    active.write_text("\\id MAT\n", encoding="utf-8")
    (tmp_path / ("Working Copy of " + name)).write_bytes(b"\\id MAT\n\xff")
    (tmp_path / "42MRKother.SFM").write_text("\\id MRK\n", encoding="utf-8")
    assert discover_usfm_files(tmp_path) == [active]
    assert detect_scripture_books(tmp_path) == ("MAT",)


def test_backup_cannot_supply_missing_book_to_inventory(tmp_path):
    """A working copy cannot make a missing canonical file appear available."""
    settings(tmp_path)
    (tmp_path / "Working Copy of 41MATfaTMNv4.SFM").write_text("\\id MAT\n")
    assert detect_scripture_books(tmp_path) == ()


@pytest.mark.parametrize("body", ["\\id MRK\n", "\\c 1\n"])
def test_matching_filename_requires_matching_book_id(tmp_path, body):
    """A filename must not misidentify its Scripture content during import."""
    settings(tmp_path)
    (tmp_path / "41MATfaTMNv4.SFM").write_text(body)
    with pytest.raises(ValidationError, match="MAT") as failure:
        detect_scripture_books(tmp_path)
    assert failure.value.code == "PARATEXT_FILENAME_BOOK_ID_MISMATCH"


@pytest.mark.parametrize("xml", [
    "<ScriptureText>",
    "<ScriptureText><FileNamePostPart>x.SFM</FileNamePostPart></ScriptureText>",
    "<ScriptureText><FileNamePrePart/><FileNamePostPart>.SFM</FileNamePostPart>"
    "<FileNameBookNameForm>invalid</FileNameBookNameForm></ScriptureText>",
])
def test_invalid_settings_do_not_fall_back_to_all_sfm(tmp_path, xml):
    """Invalid or partial templates must fail visibly rather than widening discovery."""
    (tmp_path / "Settings.xml").write_text(xml)
    (tmp_path / "41MAT.SFM").write_text("\\id MAT\n")
    with pytest.raises(ValidationError):
        discover_usfm_files(tmp_path)


def test_legacy_project_without_template_keeps_sfm_discovery(tmp_path):
    """Existing Projects without a filename declaration keep legacy discovery."""
    (tmp_path / "settings.xml").write_text("<ScriptureText><Language>English</Language></ScriptureText>")
    source = tmp_path / "41MAT.SFM"
    source.write_text("\\id MAT\n")
    assert discover_usfm_files(tmp_path) == [source]


def test_catalog_reports_excluded_files(tmp_path):
    """Catalog evidence identifies excluded filenames and counts only active books."""
    settings(tmp_path)
    (tmp_path / "41MATfaTMNv4.SFM").write_text("\\id MAT\n")
    excluded = "Working Copy of 42MRKfaTMNv4.SFM"
    (tmp_path / excluded).write_text("\\id MRK\n")
    row = inspect_paratext_project(tmp_path)
    assert row["sfm_books"] == ["MAT"]
    assert row["filename_validation"]["excluded_files"] == [excluded]


def test_snapshot_uses_template_and_preserves_working_copy(make_workspace):
    """Snapshot content comes from the active file while the working copy stays intact."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project = storage_layout(root).projects_root / "usWIP"
    settings(project, suffix=".SFM")
    backup = project / "Working Copy of 41MAT.SFM"
    backup.write_text("\\id MAT\n\\c 1\n\\p\n\\v 1 Old working copy.\n")
    before = backup.read_bytes()
    receipt = capture_wip_snapshot(
        root, settings_path=root / "ecosystem.yml", project_id="usWIP",
        destination=root.parent / "template-snapshot",
    )
    assert receipt["books"] == ["MAT"]
    assert receipt["atomic_coordinates"] == 3
    assert receipt["filename_validation"]["excluded_files"] == [backup.name]
    assert backup.read_bytes() == before


def test_compile_blocks_filename_id_mismatch(make_workspace):
    """Compilation must report the concrete filename identity defect."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project = storage_layout(root).projects_root / "usWIP"
    settings(project, suffix=".SFM")
    (project / "41MAT.SFM").write_text("\\id MRK\n")
    config = load_ecosystem(root / "ecosystem.yml")
    result = compile_project(config, config.project("usWIP"))
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["code"] == "PARATEXT_FILENAME_BOOK_ID_MISMATCH"


def test_compile_reports_exclusions_when_no_matching_scripture_remains(make_workspace):
    """Missing-file errors retain exclusion evidence through snapshot failure."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project = storage_layout(root).projects_root / "usWIP"
    settings(project, suffix=".SFM")
    backup = project / "Working Copy of 41MAT.SFM"
    (project / "41MAT.SFM").rename(backup)
    config = load_ecosystem(root / "ecosystem.yml")
    result = compile_project(config, config.project("usWIP"))
    assert result["status"] == "BLOCKED"
    assert result["filename_validation"]["excluded_files"] == [backup.name]
    with pytest.raises(ValidationError) as failure:
        capture_wip_snapshot(
            root, settings_path=root / "ecosystem.yml", project_id="usWIP",
            destination=root.parent / "rejected-snapshot",
        )
    assert failure.value.details["filename_validation"]["excluded_files"] == [backup.name]


@pytest.mark.parametrize(("book", "filename"), [
    ("GEN", "01GEN.SFM"), ("MAT", "41MAT.SFM"), ("REV", "67REV.SFM"),
    ("FRT", "A0FRT.SFM"), ("BAK", "A1BAK.SFM"), ("OTH", "A2OTH.SFM"),
    ("XXG", "100XXG.SFM"),
])
def test_template_uses_paratext_book_numbers(tmp_path, book, filename):
    """Canonical and peripheral book filenames follow Paratext numbering."""
    settings(tmp_path, suffix=".SFM")
    source = tmp_path / filename
    source.write_text(f"\\id {book}\n")
    assert discover_usfm_files(tmp_path) == [source]


def test_template_honors_declared_extension_and_case(tmp_path):
    """The declared extension and Windows-compatible casing control selection."""
    settings(tmp_path, suffix=".USFM")
    source = tmp_path / "41mat.usfm"
    source.write_text("\\id MAT\n")
    assert discover_usfm_files(tmp_path) == [source]


def test_wrong_number_and_book_combination_is_excluded(tmp_path):
    """A valid book code cannot rescue an incorrect filename number."""
    settings(tmp_path)
    (tmp_path / "40MATfaTMNv4.SFM").write_text("\\id MAT\n")
    assert discover_usfm_files(tmp_path) == []


def test_scoped_compile_does_not_validate_unrelated_book_identity(make_workspace):
    """Bounded work validates only the expected identities inside its scope."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project = storage_layout(root).projects_root / "usWIP"
    settings(project, suffix=".SFM")
    (project / "42MRK.SFM").write_text("\\id MAT\nInvalid working text.\n")
    config = load_ecosystem(root / "ecosystem.yml")
    result = compile_project(config, config.project("usWIP"), books={"MAT"})
    assert result["status"] == "READY"
    assert result["summary"]["files"] == 1
    assert discover_usfm_files(project, books={"MAT"}) == [project / "41MAT.SFM"]
    with pytest.raises(ValidationError):
        detect_scripture_books(project)


def test_disabled_project_does_not_validate_template(make_workspace):
    """Inactive Projects retain their NOT_APPLICABLE state despite source defects."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    project = storage_layout(root).projects_root / "usWIP"
    settings(project, form="invalid")
    config = load_ecosystem(root / "ecosystem.yml")
    result = compile_project(config, replace(config.project("usWIP"), enabled=False))
    assert result["status"] == "NOT_APPLICABLE"


def test_template_accepts_utf8_bom_before_book_id(tmp_path):
    """Template validation accepts the same UTF-8 BOM as the Scripture compiler."""
    settings(tmp_path, suffix=".SFM")
    source = tmp_path / "41MAT.SFM"
    source.write_text("\\id MAT\n", encoding="utf-8-sig")
    assert discover_usfm_files(tmp_path) == [source]
    assert detect_scripture_books(tmp_path) == ("MAT",)


@pytest.mark.parametrize(("form", "expected"), [
    ("41MAT", "pre42MRKtarget.USFM"), ("MAT", "preMRKtarget.USFM"),
    ("41", "pre42target.USFM"),
])
def test_bic_generated_filename_is_discoverable(tmp_path, form, expected):
    """BIC creates missing books under the same template used by import discovery."""
    from types import SimpleNamespace
    from sage.act_tasks import _target_book_filename

    settings(tmp_path, prefix="pre", suffix="target.USFM", form=form)
    project = SimpleNamespace(path=tmp_path, project_id="usTGT")
    name = _target_book_filename(project, "MRK")
    assert name == expected
    source = tmp_path / name
    source.write_text("\\id MRK\n")
    assert discover_usfm_files(tmp_path, books={"MRK"}) == [source]


def test_bic_default_filename_uses_paratext_nt_number(tmp_path):
    """The default naming convention skips slot 40 before Matthew."""
    from types import SimpleNamespace
    from sage.act_tasks import _target_book_filename

    project = SimpleNamespace(path=tmp_path, project_id="usTGT")
    assert _target_book_filename(project, "MAT") == "41MATusTGT.SFM"


def test_bundled_hebrew_settings_match_shipped_files(package_root):
    """Bundled authority metadata must select all shipped Hebrew books."""
    root = package_root / "system/resources/scripture/original-language/heb"
    assert len(detect_scripture_books(root)) == 39
