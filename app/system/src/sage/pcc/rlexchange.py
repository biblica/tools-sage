"""Move reference lists between SAGE instances as one checksummed ``.sagerl.zip`` (plan P5b-6).

A package holds one list version (a master list, or a Job's WIP list together with the master version it was
cloned from, so updating and merging work on the receiving SAGE) and an index ``SAGERL.json``::

    SAGERL.json                                   format, main list, packages, license flags, index SHA-256
    packages/<rl_id>/<version>/MANIFEST.json      each list version exactly as stored (reflist package)
    packages/<rl_id>/<version>/entries.jsonl
    packages/<rl_id>/<version>/CHECKSUMS.sha256

Writing is deterministic (fixed zip timestamps, sorted members), so the same list gives the same bytes. Reading
refuses anything unexpected before a byte reaches the store: unknown or unsafe member names, a changed index, a
package that fails its own checksums, or a size beyond the limit. Import goes through ``ReferenceListStore.
import_package``: an identical version is kept, a different one under the same id and version is stored as a fork,
and nothing in the store is ever overwritten. A list marked ``local_only`` (built from licensed text or Paratext
Biblical Terms) carries that flag in the index so the menu can warn before it leaves the organization.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from .ids import canonical_json, full_digest
from .reflist import CHECKSUMS, ENTRIES, MANIFEST, ReferenceListStore, verify_reference_list

FORMAT = "SAGE-PCC-REFERENCE-LIST"
FORMAT_VERSION = 1
SUFFIX = ".sagerl.zip"
INDEX = "SAGERL.json"
MAX_BYTES = 512 * 1024 * 1024
_MEMBER = re.compile(r"^packages/([a-z0-9][a-z0-9-]*-[a-f0-9]{8})/([1-9][0-9]{0,5})/(MANIFEST\.json|entries\.jsonl|"
                     r"CHECKSUMS\.sha256)$")
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _sha(data: bytes) -> str:
    """SHA-256 of bytes."""
    return hashlib.sha256(data).hexdigest()


def package_name(rl_id: str, version: int) -> str:
    """``<rl_id>-v<n>.sagerl.zip``."""
    return f"{rl_id}-v{version}{SUFFIX}"


def export_list(store: ReferenceListStore, rl_id: str, version: int | None, folder: Path) -> tuple[Path, dict[str, Any]]:
    """Write one list version (plus its master version for a WIP list); return (path, index)."""
    manifest, _ = store.load(rl_id, version)
    parts = []
    parent = manifest["build"].get("parent")
    if parent:
        store.load(parent["rl_id"], parent["version"])
        parts.append((parent["rl_id"], parent["version"]))
    parts.append((rl_id, manifest["version"]))
    packages, licenses = [], []
    for part_id, part_version in parts:
        source = store.path(part_id, part_version)
        part = verify_reference_list(source)
        packages.append({"rl_id": part_id, "version": part_version, "title": part["title"],
                         "reference": part["reference"]["project_id"],
                         "checksums_sha256": _sha((source / CHECKSUMS).read_bytes())})
        licenses.append(part["license"])
    index = {"format": FORMAT, "format_version": FORMAT_VERSION,
             "main": {"rl_id": rl_id, "version": manifest["version"]},
             "kind": "WIP_LIST" if parent else "MASTER", "packages": packages,
             "local_only": any(lic.get("local_only") for lic in licenses),
             "license_ids": sorted({lic["license_id"] for lic in licenses})}
    index["index_sha256"] = full_digest(index)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / package_name(rl_id, manifest["version"])
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write(archive, INDEX, (canonical_json(index) + "\n").encode("utf-8"))
        for part_id, part_version in parts:
            for name in (CHECKSUMS, ENTRIES, MANIFEST):
                _write(archive, f"packages/{part_id}/{part_version}/{name}",
                       (store.path(part_id, part_version) / name).read_bytes())
    return path, index


def _write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    """One member with a fixed timestamp, so the archive bytes are reproducible."""
    info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def _refuse(path: Path, reason: str) -> ValidationError:
    """The one error a bad package gives."""
    return ValidationError(f"{path.name} is not a reference-list package SAGE can import: {reason}",
                           code="PCC_RL_PACKAGE_INVALID",
                           next_action="Ask for the package to be exported again from the other SAGE.")


def read_package(path: Path, into: Path) -> tuple[dict[str, Any], list[Path]]:
    """Check a package and extract it into ``into``; return (index, package folders in import order)."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise _refuse(path, "not a zip file") from exc
    with archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise _refuse(path, "duplicate members")
        if sum(i.file_size for i in infos) > MAX_BYTES:
            raise _refuse(path, "larger than the limit")
        if INDEX not in names:
            raise _refuse(path, f"no {INDEX}")
        members: dict[tuple[str, int], set[str]] = {}
        for name in names:
            if name == INDEX:
                continue
            match = _MEMBER.match(name)
            if match is None:
                raise _refuse(path, f"unexpected member {name!r}")
            members.setdefault((match.group(1), int(match.group(2))), set()).add(match.group(3))
        try:
            index = json.loads(archive.read(INDEX).decode("utf-8"))
            claimed = index.pop("index_sha256")
        except (ValueError, KeyError, AttributeError, UnicodeDecodeError) as exc:
            raise _refuse(path, f"unreadable {INDEX}") from exc
        if index.get("format") != FORMAT or index.get("format_version") != FORMAT_VERSION:
            raise _refuse(path, "another format or format version")
        if full_digest(index) != claimed:
            raise _refuse(path, f"{INDEX} was changed")
        listed = [(p["rl_id"], int(p["version"])) for p in index.get("packages", [])]
        if sorted(listed) != sorted(members) or any(files != {MANIFEST, ENTRIES, CHECKSUMS} for files in members.values()):
            raise _refuse(path, "the packages differ from the index")
        main = (index["main"]["rl_id"], int(index["main"]["version"]))
        if main not in listed:
            raise _refuse(path, "the main list is not in the package")
        folders = []
        for package in index["packages"]:
            folder = into / package["rl_id"] / str(package["version"])
            folder.mkdir(parents=True, exist_ok=True)
            for name in (MANIFEST, ENTRIES, CHECKSUMS):
                (folder / name).write_bytes(archive.read(f"packages/{package['rl_id']}/{package['version']}/{name}"))
            if _sha((folder / CHECKSUMS).read_bytes()) != package["checksums_sha256"]:
                raise _refuse(path, f"{package['rl_id']} v{package['version']} differs from the index")
            try:
                verify_reference_list(folder)
            except ValidationError as exc:
                raise _refuse(path, f"{package['rl_id']} v{package['version']} failed its checksums") from exc
            folders.append(folder)
    return {**index, "index_sha256": claimed}, folders


@dataclass
class ExchangeResult:
    """What an import stored."""

    index: dict[str, Any]
    main: dict[str, Any] | None = None
    stored: list[tuple[str, int, str]] = field(default_factory=list)   # (rl_id, version, kept|imported|forked)
    notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        """Operator summary."""
        words = {"kept": "already here (identical)", "imported": "imported",
                 "forked": "differs from the version with the same number here; stored under a new id"}
        out = [f"{rl_id} v{version}: {words[outcome]}" for rl_id, version, outcome in self.stored]
        return out + [f"- {note}" for note in self.notes]


def import_list(store: ReferenceListStore, path: Path) -> ExchangeResult:
    """Import a ``.sagerl.zip``: masters first, then the WIP list; never overwrites the store."""
    with tempfile.TemporaryDirectory(prefix="sagerl-") as scratch:
        index, folders = read_package(path, Path(scratch))
        result = ExchangeResult(index)
        renamed: dict[str, str] = {}
        main = (index["main"]["rl_id"], int(index["main"]["version"]))
        for folder in folders:
            manifest, outcome = store.import_package(folder)
            original = (folder.parent.name, int(folder.name))
            result.stored.append((manifest["rl_id"], manifest["version"], outcome))
            if outcome == "forked":
                renamed[original[0]] = manifest["rl_id"]
            if original == main:
                result.main = manifest
    if result.main is not None and result.main["build"].get("parent"):
        parent = result.main["build"]["parent"]
        if parent["rl_id"] in renamed:
            result.notes.append(f"This WIP list names master {parent['rl_id']} v{parent['version']}, but this SAGE has a "
                                f"different list with that id and version; the package's master was stored as "
                                f"{renamed[parent['rl_id']]}. Update and merge use this SAGE's {parent['rl_id']}.")
    if index.get("local_only"):
        result.notes.append("This list is marked local only (built from licensed text or Paratext Biblical Terms): "
                            "use it only within your organization's license.")
    return result
