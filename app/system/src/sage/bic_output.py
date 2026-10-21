"""SAGE-created BIC TARGET folders under ``localdata/exports/bic``.

A BIC Job can write its generated TARGET into SAGE localdata instead of an existing
Paratext project. SAGE then registers its own TARGET Project named ``<language-tag>_<SOURCE>``
(for example ``en-US_idKKHv0``). Its language identity and grammar come from the DONOR, its
versification from the SOURCE (default) or the DONOR, and its book files use plain
``{NN}{BOOK}.SFM`` names ready for a later Paratext import.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, atomic_write_text
from .errors import ValidationError
from .execution_events import utc_now
from .project_inventory import (
    GENERATED_PROJECT_ID_RE,
    register_project,
    registered_project_records,
)
from .registry import ProjectSpec, load_ecosystem
from .storage import storage_layout

TARGET_OUTPUT_LOCALDATA = "LOCALDATA"
TARGET_OUTPUT_PARATEXT = "PARATEXT"
TARGET_OUTPUTS = (TARGET_OUTPUT_LOCALDATA, TARGET_OUTPUT_PARATEXT)
VERSIFICATION_FROM = ("SOURCE", "DONOR")
MANIFEST_NAME = "sage-output.json"
README_NAME = "README.md"
SCHEMA_VERSION = "1.0"


def generated_target_id(language_tag: str, source_id: str) -> str:
    """Return the ``<language-tag>_<SOURCE>`` code of one SAGE-created TARGET."""
    project_id = f"{language_tag.strip()}_{source_id.strip()}"
    if not GENERATED_PROJECT_ID_RE.fullmatch(project_id):
        raise ValidationError(
            f"BIC localdata TARGET name is not cross-platform safe: {project_id}",
            code="BIC_GENERATED_TARGET_ID_INVALID",
        )
    return project_id


def generated_target_root(root: Path, project_id: str) -> Path:
    """Return the localdata folder of one SAGE-created TARGET."""
    return storage_layout(root).bic_outputs_root / project_id


def is_generated_target_folder(path: Path) -> bool:
    """Return whether a TARGET folder is a SAGE-created localdata output."""
    return (path / MANIFEST_NAME).is_file()


def generated_target_record(root: Path, project_id: str) -> dict[str, Any] | None:
    """Return the ``sage_generated`` metadata of one Project, or None for Paratext Projects."""
    record = registered_project_records(root).get(project_id)
    if not record or not isinstance(record.get("sage_generated"), dict):
        return None
    return dict(record["sage_generated"])


def language_region(language_tag: str) -> str | None:
    """Return the region subtag of a BCP-47 tag (``US`` in ``en-US``), if any."""
    for part in language_tag.split("-")[1:]:
        if (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            return part.upper()
    return None


def target_output_mode(root: Path, target_id: str) -> str:
    """Return LOCALDATA for a SAGE-created TARGET and PARATEXT for every other TARGET."""
    return TARGET_OUTPUT_LOCALDATA if generated_target_record(root, target_id) is not None else TARGET_OUTPUT_PARATEXT


def _expected_books(root: Path, source: ProjectSpec) -> tuple[str, ...]:
    """Return the SOURCE's declared books; the TARGET may receive any of them."""
    if isinstance(source.scope.expected_books, tuple) and source.scope.expected_books:
        return source.scope.expected_books
    record = registered_project_records(root).get(source.project_id) or {}
    books = record.get("detected_books") or record.get("sfm_books") or []
    return tuple(str(book) for book in books)


def _write_versification(folder: Path, versification_project: ProjectSpec) -> str | None:
    """Copy the chosen Project's custom.vrs into the TARGET folder; return its name when present."""
    candidate = versification_project.path / "custom.vrs"
    if not candidate.is_file():
        return None
    shutil.copyfile(candidate, folder / "custom.vrs")
    return "custom.vrs"


def _readme(metadata: dict[str, Any]) -> str:
    """Render the Operator-facing README for one localdata TARGET folder."""
    return (
        f"# {metadata['project_id']}\n\n"
        "BIC output written by SAGE. It is not a Paratext project: check it, then import the\n"
        "book files into Paratext.\n\n"
        f"- SOURCE: {metadata['source']}\n"
        f"- DONOR (language data): {metadata['donor']}\n"
        f"- Language: {metadata['language_tag']}"
        + (f" (ISO 639-3 {metadata['iso_639_3']})" if metadata.get("iso_639_3") else "")
        + "\n"
        f"- Versification: {metadata['versification_from']} ({metadata['versification_base']}"
        + (", custom.vrs" if metadata.get("custom_vrs") else "")
        + ")\n"
        f"- Owning Job: {metadata['owning_job']}\n\n"
        "## Import into Paratext\n\n"
        "1. Open the receiving Paratext project and confirm its versification matches the one above.\n"
        "2. File > Import books, and choose the `.SFM` files in this folder. Paratext reads the book\n"
        "   from each file's `\\id` line.\n\n"
        "Files only change through BIC SELF-CHECK commits. Each commit is recorded in the Job's\n"
        "`target-history/` and can be reverted per scope from the BIC Job menu.\n"
    )


def write_output_files(root: Path, project_id: str, metadata: dict[str, Any]) -> Path:
    """Write the folder manifest and README; return the folder."""
    folder = generated_target_root(root, project_id)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": SCHEMA_VERSION, **metadata}
    atomic_write_json(folder / MANIFEST_NAME, manifest)
    atomic_write_text(folder / README_NAME, _readme(metadata))
    return folder


def _project_folder(root: Path, project_id: str) -> Path:
    """Return a registered Project's folder from its mount, or its internal SAGE folder."""
    from .resource_mounts import load_resource_mounts

    mount = load_resource_mounts(root).get(project_id)
    if mount and mount.get("path"):
        return Path(str(mount["path"]))
    return storage_layout(root).projects_root / project_id


def ensure_generated_target_folder(root: Path, project_id: str) -> Path | None:
    """Recreate a SAGE-created TARGET folder that was deleted by hand; None for Paratext TARGETs."""
    metadata = generated_target_record(root, project_id)
    if metadata is None:
        return None
    folder = generated_target_root(root, project_id)
    if not (folder / MANIFEST_NAME).is_file():
        write_output_files(root, project_id, metadata)
    if metadata.get("custom_vrs") and not (folder / "custom.vrs").is_file():
        # The versification the folder was created with must come back with it.
        candidate = _project_folder(root, str(metadata.get("versification_project") or "")) / "custom.vrs"
        if candidate.is_file():
            shutil.copyfile(candidate, folder / "custom.vrs")
    return folder


def ensure_generated_target(
    settings_path: Path,
    *,
    source_id: str,
    donor_id: str,
    job_id: str,
    versification_from: str = "SOURCE",
) -> str:
    """Create or reuse the SAGE localdata TARGET for one SOURCE and DONOR language; return its code.

    One folder belongs to one BIC Job. A second Job whose DONOR shares the language would
    write into the same folder, so it is refused rather than allowed to interleave commits.
    """
    vrs_from = versification_from.strip().upper()
    if vrs_from not in VERSIFICATION_FROM:
        raise ValidationError(
            f"BIC localdata versification must come from SOURCE or DONOR, not {versification_from}",
            code="BIC_GENERATED_TARGET_VERSIFICATION_INVALID",
        )
    config = load_ecosystem(settings_path)
    root = config.root
    source = config.project(source_id)
    donor = config.project(donor_id)
    project_id = generated_target_id(donor.language_code, source.project_id)
    existing = generated_target_record(root, project_id)
    if existing is not None:
        if existing.get("owning_job") != job_id:
            raise ValidationError(
                f"BIC localdata TARGET {project_id} already belongs to Job {existing.get('owning_job')}",
                code="BIC_GENERATED_TARGET_OWNED",
                next_action=(
                    f"Open Job {existing.get('owning_job')} to continue that output, or remove that Job "
                    "and its output folder first."
                ),
                details={"project_id": project_id, "owning_job": existing.get("owning_job"), "requested_job": job_id},
            )
        if str(existing.get("versification_from", "SOURCE")) != vrs_from:
            raise ValidationError(
                f"BIC localdata TARGET {project_id} already uses {existing.get('versification_from')} versification",
                code="BIC_GENERATED_TARGET_VERSIFICATION_FIXED",
                details={"project_id": project_id, "versification_from": existing.get("versification_from")},
            )
        ensure_generated_target_folder(root, project_id)
        return project_id
    if project_id in config.projects:
        raise ValidationError(
            f"A SAGE Project named {project_id} already exists and is not a BIC localdata TARGET",
            code="BIC_GENERATED_TARGET_ID_TAKEN",
            details={"project_id": project_id},
        )

    versification_project = source if vrs_from == "SOURCE" else donor
    folder = generated_target_root(root, project_id)
    folder.mkdir(parents=True, exist_ok=True)
    custom_vrs = _write_versification(folder, versification_project)
    donor_record = registered_project_records(root).get(donor.project_id) or {}
    donor_paratext = dict(donor_record.get("paratext_metadata") or {})
    metadata: dict[str, Any] = {
        "project_id": project_id,
        "tool": "bic",
        "owning_job": job_id,
        "source": source.project_id,
        "donor": donor.project_id,
        "language_tag": donor.language_code,
        "language_region": language_region(donor.language_code),
        "iso_639_3": donor_paratext.get("canonical_iso_639_3"),
        "versification_from": vrs_from,
        "versification_project": versification_project.project_id,
        "versification_base": versification_project.versification.base_file,
        "custom_vrs": custom_vrs,
        "created_utc": utc_now(),
    }
    write_output_files(root, project_id, metadata)
    register_project(
        root,
        project_id=project_id,
        project_path=folder,
        language_code=donor.language_code,
        language_profile=donor.language_profile,
        base_vrs_file=versification_project.versification.base_file,
        display_name=f"BIC output {source.project_id} in {donor.language_code}",
        kind="SCRIPTURE",
        content_state="LOCKED",
        allow_empty=True,
        coverage_policy="PRESENT_CHAPTERS_ONLY",
        declared_books=_expected_books(root, source) or None,
        paratext_metadata={"language_profile_tag": donor.language_code},
        versification_metadata={"custom_file": custom_vrs or "none", "base_selection": f"FROM_{vrs_from}"},
        sage_generated=metadata,
    )
    return project_id


def release_generated_target(root: Path, project_id: str, *, delete_folder: bool) -> None:
    """Detach a SAGE-created TARGET from its removed Job; optionally delete its folder."""
    from .project_inventory import unregister_project

    if generated_target_record(root, project_id) is None:
        return
    unregister_project(root, project_id=project_id)
    folder = generated_target_root(root, project_id)
    if delete_folder and folder.is_dir():
        shutil.rmtree(folder)


def release_all_generated_targets(root: Path) -> list[str]:
    """Unregister every SAGE-created TARGET; used when all Job data is wiped. Returns their codes."""
    from .project_inventory import unregister_project

    released = sorted(
        project_id
        for project_id, record in registered_project_records(root).items()
        if isinstance(record.get("sage_generated"), dict)
    )
    for project_id in released:
        unregister_project(root, project_id=project_id)
    return released


def output_summary(root: Path, project_id: str) -> dict[str, Any] | None:
    """Return display facts for one SAGE-created TARGET folder, or None for Paratext TARGETs."""
    metadata = generated_target_record(root, project_id)
    if metadata is None:
        return None
    folder = generated_target_root(root, project_id)
    books = sorted(path.name for path in folder.glob("*.SFM")) if folder.is_dir() else []
    return {**metadata, "folder": str(folder), "book_files": books}
