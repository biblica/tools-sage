"""BIC TARGET written to a SAGE-created localdata folder instead of a Paratext project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import submit_with_receipt
from .test_storage_rtc_boundaries import _initialize, _submit_inspect, _write_bic_assessment
from sage.act_tasks import create_act_task
from sage.bic_output import (
    MANIFEST_NAME,
    ensure_generated_target,
    generated_target_id,
    generated_target_root,
    language_region,
    target_output_mode,
)
from sage.bounded_target import list_target_history, revert_target_scope
from sage.errors import ValidationError
from sage.jobs import JobStore, default_job_name
from sage.registry import load_ecosystem


def _commit_scope(config, target_id: str, scope: str, candidate: str) -> dict:
    """Run INSPECT, REWRITE and SELF-CHECK for one scope with a hand-written candidate."""
    common = {
        "workflow": "bic",
        "output_project_id": target_id,
        "contemporary_source_id": "idKKHv0",
        "lexical_donor_id": "usNIVv2",
        "scope_value": scope,
    }
    inspect = create_act_task(config, operation="inspect", **common)
    _submit_inspect(config, inspect)
    rewrite = create_act_task(config, operation="rewrite", **common)
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output" / "rewrite.usfm"
    rewrite_output.write_text(candidate, encoding="utf-8")
    _write_bic_assessment(rewrite, rewrite_output)
    submit_with_receipt(config, rewrite_manifest)
    check = create_act_task(config, operation="self_check", predecessor_task=str(rewrite_manifest), **common)
    check_manifest = Path(check["manifest_path"])
    check_output = check_manifest.parent / "output" / "self-check.usfm"
    check_output.write_text(candidate, encoding="utf-8")
    _write_bic_assessment(check, check_output)
    return {"job_id": check["job_id"], **submit_with_receipt(config, check_manifest)}


def test_generated_target_id_keeps_the_region() -> None:
    """US and UK English produce different localdata TARGETs."""
    assert generated_target_id("en-US", "idKKHv0") == "en-US_idKKHv0"
    assert generated_target_id("en-GB", "idKKHv0") != generated_target_id("en-US", "idKKHv0")
    assert language_region("en-US") == "US"
    assert language_region("zh-Hant-TW") == "TW"
    assert language_region("id") is None
    with pytest.raises(ValidationError):
        generated_target_id("en US", "idKKHv0")


def test_bic_commits_into_localdata_folder_and_builds_the_book_by_scope(package_root: Path, make_workspace) -> None:
    """A localdata TARGET starts empty, takes DONOR language data, and grows one scope at a time."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    settings = root / "ecosystem.yml"
    job_id = default_job_name("bic", "en_idKKHv0", "idKKHv0", "usNIVv2")
    target_id = ensure_generated_target(settings, source_id="idKKHv0", donor_id="usNIVv2", job_id=job_id)
    assert target_id == "en_idKKHv0"

    config = load_ecosystem(settings)
    folder = generated_target_root(config.root, target_id)
    manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["donor"] == "usNIVv2"
    assert manifest["versification_from"] == "SOURCE"
    assert (folder / "README.md").is_file()
    assert target_output_mode(config.root, target_id) == "LOCALDATA"
    assert target_output_mode(config.root, "usBOLx1") == "PARATEXT"
    assert config.project(target_id).language_code == config.project("usNIVv2").language_code

    first = _commit_scope(config, target_id, "MAT 1:1", "\\id MAT Candidate\n\\c 1\n\\p\n\\v 1 NEW ONE\n")
    book = folder / "41MAT.SFM"
    assert Path(first["commit"]["target_file"]) == book.resolve()
    assert first["job_id"] == job_id

    _commit_scope(config, target_id, "MAT 1:2-3", "\\id MAT Candidate\n\\c 1\n\\p\n\\v 2 NEW TWO\n\\v 3 NEW THREE\n")
    text = book.read_text(encoding="utf-8")
    assert text.index("\\v 1 NEW ONE") < text.index("\\v 2 NEW TWO") < text.index("\\v 3 NEW THREE")
    assert sorted(path.name for path in folder.glob("*.SFM")) == ["41MAT.SFM"]

    store = JobStore(config.root, config.settings_path)
    job = store.load_job(job_id, tool="bic")
    assert job.profiles["target_grammar"] == "en/bol-target"
    assert len(list_target_history(job.root)) == 2
    revert_target_scope(
        job_root=job.root,
        target_file=book,
        scope_value="MAT 1:2-3",
        transaction_root=config.workflow("bic").transaction_root,
        allowed_roots=(folder,),
    )
    assert "NEW TWO" not in book.read_text(encoding="utf-8")
    assert "\\v 1 NEW ONE" in book.read_text(encoding="utf-8")


def test_generated_target_belongs_to_one_job(package_root: Path, make_workspace) -> None:
    """A second Job may not interleave commits into another Job's localdata folder."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    settings = root / "ecosystem.yml"
    ensure_generated_target(settings, source_id="idKKHv0", donor_id="usNIVv2", job_id="BIC_idKKHv0-usNIVv2-en_idKKHv0")
    assert ensure_generated_target(
        settings, source_id="idKKHv0", donor_id="usNIVv2", job_id="BIC_idKKHv0-usNIVv2-en_idKKHv0"
    ) == "en_idKKHv0"
    with pytest.raises(ValidationError) as owned:
        ensure_generated_target(settings, source_id="idKKHv0", donor_id="usNIVv2", job_id="BIC_idKKHv0-other-en_idKKHv0")
    assert owned.value.code == "BIC_GENERATED_TARGET_OWNED"
    with pytest.raises(ValidationError) as fixed:
        ensure_generated_target(
            settings, source_id="idKKHv0", donor_id="usNIVv2",
            job_id="BIC_idKKHv0-usNIVv2-en_idKKHv0", versification_from="DONOR",
        )
    assert fixed.value.code == "BIC_GENERATED_TARGET_VERSIFICATION_FIXED"


def test_donor_versification_copies_donor_custom_vrs(package_root: Path, make_workspace) -> None:
    """Choosing DONOR versification writes the DONOR's custom.vrs into the output folder."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    settings = root / "ecosystem.yml"
    config = load_ecosystem(settings)
    (config.project("usNIVv2").path / "custom.vrs").write_text("MAT 1:3\n", encoding="utf-8")
    target_id = ensure_generated_target(
        settings, source_id="idKKHv0", donor_id="usNIVv2", job_id="BIC_idKKHv0-usNIVv2-en_idKKHv0",
        versification_from="DONOR",
    )
    folder = generated_target_root(config.root, target_id)
    assert (folder / "custom.vrs").read_text(encoding="utf-8") == "MAT 1:3\n"
    manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["versification_project"] == "usNIVv2"


def test_cli_without_target_resolves_the_localdata_target(package_root: Path, make_workspace) -> None:
    """BIC task creation without --target writes into localdata; other workflows still need --wip."""
    import argparse

    from sage.cli import _resolve_task_output_project

    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    def args(**values) -> argparse.Namespace:
        """Build task-create arguments for BIC from SOURCE idKKHv0 via DONOR usNIVv2."""
        base = {
            "workflow_id": "bic", "output_project": None, "contemporary_source": "idKKHv0",
            "lexical_donor": "usNIVv2", "target_output": None, "target_versification": "source", "job_id": None,
        }
        return argparse.Namespace(**{**base, **values})

    assert _resolve_task_output_project(args(output_project="usBOLx1"), config) == "usBOLx1"
    assert _resolve_task_output_project(args(), config) == "en_idKKHv0"
    assert target_output_mode(config.root, "en_idKKHv0") == "LOCALDATA"
    with pytest.raises(ValidationError):
        _resolve_task_output_project(args(target_output="paratext"), config)
    with pytest.raises(ValidationError):
        _resolve_task_output_project(args(workflow_id="stc"), config)


def test_removing_the_job_releases_the_target_and_keeps_its_files(package_root: Path, make_workspace) -> None:
    """Job removal frees the localdata name for another Job without deleting committed books."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    settings = root / "ecosystem.yml"
    job_id = default_job_name("bic", "en_idKKHv0", "idKKHv0", "usNIVv2")
    target_id = ensure_generated_target(settings, source_id="idKKHv0", donor_id="usNIVv2", job_id=job_id)
    config = load_ecosystem(settings)
    _commit_scope(config, target_id, "MAT 1:1", "\\id MAT Candidate\n\\c 1\n\\p\n\\v 1 NEW ONE\n")
    folder = generated_target_root(config.root, target_id)

    store = JobStore(config.root, config.settings_path)
    store.remove_job(store.load_job(job_id, tool="bic"))
    assert (folder / "41MAT.SFM").is_file()
    assert target_output_mode(config.root, target_id) == "PARATEXT"
    assert ensure_generated_target(settings, source_id="idKKHv0", donor_id="usNIVv2", job_id="BIC_idKKHv0-other-en_idKKHv0") == target_id


def test_job_data_wipe_releases_localdata_targets(package_root: Path, make_workspace) -> None:
    """Wiping all Job data removes the output folders and frees their TARGET names."""
    from sage.job_data_reset import wipe_all_job_data

    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    settings = root / "ecosystem.yml"
    target_id = ensure_generated_target(settings, source_id="idKKHv0", donor_id="usNIVv2", job_id="BIC_idKKHv0-usNIVv2-en_idKKHv0")
    receipt = wipe_all_job_data(root)
    assert receipt["released_bic_localdata_targets"] == [target_id]
    assert target_output_mode(root, target_id) == "PARATEXT"
    assert not generated_target_root(root, target_id).exists()


def test_deleted_folder_is_recreated_with_its_versification(package_root: Path, make_workspace) -> None:
    """Reopening a Job whose folder was deleted by hand restores manifest and custom.vrs."""
    import shutil

    from sage.bic_output import ensure_generated_target_folder

    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    settings = root / "ecosystem.yml"
    config = load_ecosystem(settings)
    (config.project("idKKHv0").path / "custom.vrs").write_text("MAT 1:3\n", encoding="utf-8")
    target_id = ensure_generated_target(settings, source_id="idKKHv0", donor_id="usNIVv2", job_id="BIC_idKKHv0-usNIVv2-en_idKKHv0")
    folder = generated_target_root(root, target_id)
    shutil.rmtree(folder)
    ensure_generated_target_folder(root, target_id)
    assert (folder / MANIFEST_NAME).is_file()
    assert (folder / "custom.vrs").read_text(encoding="utf-8") == "MAT 1:3\n"


def test_another_job_cannot_bind_a_localdata_target_it_does_not_own(package_root: Path, make_workspace) -> None:
    """Picking a localdata TARGET as an ordinary TARGET still respects its owning Job."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    settings = root / "ecosystem.yml"
    target_id = ensure_generated_target(settings, source_id="idKKHv0", donor_id="usNIVv2", job_id="BIC_someone-else")
    store = JobStore(root, settings)
    with pytest.raises(ValidationError) as caught:
        store.create_job(
            tool="bic",
            job_id=default_job_name("bic", target_id, "idKKHv0", "usNIVv2"),
            display_name="intruder",
            bindings={"content_source": "idKKHv0", "lexical_donor": "usNIVv2", "generated_target": target_id},
            profiles={},
            defaults={},
        )
    assert caught.value.code == "BIC_GENERATED_TARGET_OWNED"
