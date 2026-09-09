"""Bounded import and external qualification receipts for NCA resources."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from sage.atomic import atomic_write_json
from sage.errors import ValidationError

from .reference import REFERENCE_PARSER_VERSION, load_reference, validate_package_id
from .models import ReferenceBundle

if TYPE_CHECKING:
    from sage.registry import EcosystemConfig


MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 1024 * 1024 * 1024


def _reference_library(config: EcosystemConfig) -> Path:
    """Resolve the numbers library without following symlinked publication parents."""
    configured_root = Path(config.data_root).expanduser()
    resolved_root = configured_root.resolve()
    components = (
        configured_root / "inputs",
        configured_root / "inputs" / "resources",
        configured_root / "inputs" / "resources" / "numbers",
    )
    if any(path.is_symlink() for path in components):
        raise ValidationError(
            "NCA resource library cannot use symbolic links.",
            code="NCA_REFERENCE_PUBLICATION_CONFLICT",
        )
    library = components[-1].resolve()
    try:
        library.relative_to(resolved_root)
    except ValueError as exc:
        raise ValidationError(
            "NCA resource library escapes configured data storage.",
            code="NCA_REFERENCE_PUBLICATION_CONFLICT",
            details={"data_root": str(resolved_root), "resource_root": str(library)},
        ) from exc
    return library


def resolve_reference_package(config: EcosystemConfig, package_id: str) -> ReferenceBundle:
    """Requalify one imported package and require its stored identity to match."""
    library = _reference_library(config)
    validate_package_id(package_id)
    path = library / package_id
    if library.is_symlink() or path.is_symlink():
        raise ValidationError('NCA reference selectors cannot use symlinks.', code='NCA_REFERENCE_PUBLICATION_CONFLICT')
    destination = _publication_destination(library, package_id)
    if not destination.is_dir():
        raise ValidationError('NCA reference package is not imported.', code='NCA_REFERENCE_NOT_IMPORTED', next_action='Import and qualify the NCA operator archive.')
    bundle = load_reference(destination, qualification='STRICT')
    if bundle.package_id != package_id:
        raise ValidationError('NCA package directory and manifest identities disagree.', code='NCA_REFERENCE_PUBLICATION_CONFLICT')
    bundle.require_qualified()
    return bundle


def reference_package_candidates(config: EcosystemConfig) -> tuple[tuple[Path, ReferenceBundle], ...]:
    """List qualified packages, exposing corrupt published packages as errors."""
    library = _reference_library(config)
    if library.is_symlink():
        raise ValidationError('NCA resource library cannot be a symlink.', code='NCA_REFERENCE_PUBLICATION_CONFLICT')
    if not library.exists():
        return ()
    return tuple((path, resolve_reference_package(config, path.name)) for path in sorted(library.iterdir())
                 if not path.name.startswith('.'))


def _archive_error(message: str, **details: object) -> ValidationError:
    """Build one stable bounded-import error."""
    return ValidationError(
        message,
        code="NCA_REFERENCE_ARCHIVE_INVALID",
        details=dict(details),
    )


def _plain(value: object) -> object:
    """Convert recursively frozen reference evidence to JSON-owned containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    return value


def _validated_members(archive: zipfile.ZipFile) -> tuple[str, tuple[zipfile.ZipInfo, ...]]:
    """Validate archive paths, entry types, root shape, and expansion bounds."""
    members = archive.infolist()
    if not members or len(members) > MAX_ARCHIVE_ENTRIES:
        raise _archive_error(
            "NCA reference archive has an invalid entry count",
            entries=len(members),
            maximum=MAX_ARCHIVE_ENTRIES,
        )
    roots: set[str] = set()
    paths: set[str] = set()
    total = 0
    files: list[zipfile.ZipInfo] = []
    for member in members:
        raw = member.filename
        path = PurePosixPath(raw)
        if (
            not raw
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in raw
            or re.match(r"^[A-Za-z]:", raw)
        ):
            raise _archive_error(f"Unsafe NCA archive member path: {raw!r}", path=raw)
        normalized = path.as_posix().rstrip("/")
        if not normalized or normalized in paths:
            raise _archive_error(f"Duplicate or empty NCA archive member path: {raw!r}", path=raw)
        paths.add(normalized)
        roots.add(path.parts[0])
        mode = member.external_attr >> 16
        entry_type = stat.S_IFMT(mode)
        if stat.S_ISLNK(mode) or (entry_type and entry_type not in {stat.S_IFREG, stat.S_IFDIR}):
            raise _archive_error(f"Unsupported NCA archive member type: {raw}", path=raw)
        if member.flag_bits & 0x1:
            raise _archive_error(f"Encrypted NCA archive members are not supported: {raw}", path=raw)
        if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise _archive_error(
                f"NCA archive member exceeds the import bound: {raw}",
                path=raw,
                bytes=member.file_size,
            )
        total += member.file_size
        if total > MAX_ARCHIVE_TOTAL_BYTES:
            raise _archive_error(
                "NCA archive exceeds the total import bound",
                bytes=total,
                maximum=MAX_ARCHIVE_TOTAL_BYTES,
            )
        if not member.is_dir():
            if len(path.parts) < 2:
                raise _archive_error("NCA archive files must share one package root", path=raw)
            files.append(member)
    if len(roots) != 1 or not files:
        raise _archive_error(
            "NCA archive must contain exactly one nonempty package root",
            roots=sorted(roots),
        )
    root = next(iter(roots))
    return root, tuple(files)


def _publication_destination(parent: Path, package_id: str) -> Path:
    """Resolve a validated package identity to exactly one child of the resource root."""
    safe_id = validate_package_id(package_id)
    resolved_parent = parent.resolve()
    destination = (resolved_parent / safe_id).resolve()
    if destination.parent != resolved_parent:
        raise ValidationError(
            f"NCA package publication escapes its resource root: {safe_id}",
            code="NCA_REFERENCE_PUBLICATION_CONFLICT",
            details={"package_id": safe_id, "resource_root": str(resolved_parent)},
        )
    return destination


def _write_receipt(
    config: EcosystemConfig,
    *,
    package_root: Path,
    archive: Path,
    archive_sha256: str,
    package_sha256: str,
    qualification_status: str,
    diagnostics: tuple[object, ...],
) -> Path:
    """Write the software qualification receipt outside the immutable package."""
    receipt = (
        config.data_root
        / ".system"
        / "state"
        / "numbers"
        / "qualification"
        / f"{package_root.name}.json"
    )
    atomic_write_json(
        receipt,
        {
            "schema_version": "1.0",
            "package_id": package_root.name,
            "package_root": str(package_root),
            "package_sha256": package_sha256,
            "archive_path": str(archive),
            "archive_sha256": archive_sha256,
            "parser_version": REFERENCE_PARSER_VERSION,
            "qualification_status": qualification_status,
            "diagnostics": _plain(diagnostics),
            "immutable_source_package": True,
            "source_package_gate_unchanged": True,
        },
    )
    return receipt


def import_reference(config: EcosystemConfig, archive: Path) -> Path:
    """Validate and atomically publish one unchanged NCA archive into resolved localdata."""
    source = Path(archive).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise _archive_error(f"NCA reference archive is unavailable or unsafe: {source}", path=str(source))
    publication_parent = _reference_library(config)
    archive_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(source) as package:
            root_name, members = _validated_members(package)
            corrupt = package.testzip()
            if corrupt is not None:
                raise _archive_error(f"NCA archive CRC failure: {corrupt}", path=corrupt)

            publication_parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".numbers-reference-", dir=publication_parent))
            try:
                newly_published = False
                extracted = staging / root_name
                for member in members:
                    relative = PurePosixPath(member.filename).relative_to(root_name)
                    destination = extracted.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    payload = package.read(member)
                    with destination.open("wb") as target:
                        target.write(payload)
                bundle = load_reference(extracted, qualification="STRICT")
                destination = _publication_destination(publication_parent, bundle.package_id)
                if destination.exists() or destination.is_symlink():
                    if destination.is_symlink() or not destination.is_dir():
                        raise ValidationError(
                            f"NCA reference publication target is unsafe: {destination}",
                            code="NCA_REFERENCE_PUBLICATION_CONFLICT",
                            details={"path": str(destination)},
                        )
                    existing = load_reference(destination, qualification="STRICT")
                    if existing.sha256 != bundle.sha256:
                        raise ValidationError(
                            f"NCA package ID is already bound to different bytes: {bundle.package_id}",
                            code="NCA_REFERENCE_PUBLICATION_CONFLICT",
                            details={"package_id": bundle.package_id},
                        )
                else:
                    os.replace(extracted, destination)
                    newly_published = True
                try:
                    _write_receipt(
                        config,
                        package_root=destination,
                        archive=source,
                        archive_sha256=archive_sha256,
                        package_sha256=bundle.sha256,
                        qualification_status=bundle.qualification_status,
                        diagnostics=bundle.diagnostics,
                    )
                except Exception:
                    if newly_published:
                        os.replace(destination, extracted)
                    raise
                return destination
            finally:
                shutil.rmtree(staging, ignore_errors=True)
    except zipfile.BadZipFile as exc:
        raise _archive_error(f"Invalid NCA ZIP archive: {source}", path=str(source)) from exc
