"""Reference lists: versioned, immutable concept-list packages for one REFERENCE edition (plan §5b, D12-D19).

A reference list (RL) belongs to a reference text, not to a Job: every Job on that edition pins one version.
An Operator builds RLs on their own SAGE instance and may export and import them; sharing happens outside
SAGE. A package folder ``<resources>/reference-lists/<rl_id>/<version>/`` holds:

* ``MANIFEST.json``: the ``reference_list_manifest`` contract (reference identity, license, build lineage,
  counts, the entries' SHA-256);
* ``entries.jsonl``: one ``reference_list_entry`` per concept, sorted by ``concept_key``;
* ``CHECKSUMS.sha256``.

Versions are never edited: every change is a new version. Writing is deterministic (the caller supplies the
creation time), so the same inputs give byte-identical packages, which ``verify_reference_list`` re-checks.
Occurrences are not stored; a Run locates them again in the reference text.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from . import ENGINE_VERSION
from .contracts import RL_STATUSES, SCHEMA_VERSION, validate_record
from .jsonl import read_json, read_jsonl, write_json, write_jsonl

MANIFEST = "MANIFEST.json"
ENTRIES = "entries.jsonl"
CHECKSUMS = "CHECKSUMS.sha256"
STORE_FOLDER = "reference-lists"


def _sha(path: Path) -> str:
    """SHA-256 of one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_rl_id(title: str, instance_id: str, created_utc: str) -> str:
    """A new RL id: a slug of the title plus 8 hex of (instance, creation time), unique across instances."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:40].strip("-") or "list"
    return f"{slug}-{hashlib.sha256(f'{instance_id}|{created_utc}'.encode('utf-8')).hexdigest()[:8]}"


def write_reference_list(target: Path, *, rl_id: str, version: int, title: str, reference: Mapping[str, str],
                         license: Mapping[str, Any], build: Mapping[str, Any], entries: Iterable[Mapping[str, Any]],
                         created_utc: str) -> dict[str, Any]:
    """Write one package into the empty folder ``target`` and return its manifest."""
    if target.exists() and any(target.iterdir()):
        raise ValidationError(f"Reference list folder is not empty: {target}", code="PCC_RL_EXISTS",
                              next_action="Write a new version; a reference-list version is never changed.")
    rows = [validate_record("reference_list_entry", entry, where=str(entry.get("concept_key"))) for entry in entries]
    keys = [row["concept_key"] for row in rows]
    if len(set(keys)) != len(keys):
        duplicate = next(key for key, n in Counter(keys).items() if n > 1)
        raise ValidationError(f"Concept {duplicate} appears twice in the reference list", code="PCC_RL_DUPLICATE")
    target.mkdir(parents=True, exist_ok=True)
    write_jsonl(target / ENTRIES, rows, kind="reference_list_entry", sort_key="concept_key")
    statuses = Counter(row["status"] for row in rows)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "rl_id": rl_id,
        "version": version,
        "title": title,
        "reference": dict(reference),
        "license": dict(license),
        "build": {"engine_version": ENGINE_VERSION, "base_version": None, "derived_from": None,
                  "imported_from": None, "settings": {}, "summary": {}, **dict(build)},
        "counts": {"entries": len(rows), **{status.lower(): statuses.get(status, 0) for status in RL_STATUSES}},
        "entries_sha256": _sha(target / ENTRIES),
        "created_utc": created_utc,
    }
    write_json(target / MANIFEST, manifest, kind="reference_list_manifest")
    (target / CHECKSUMS).write_text("".join(f"{_sha(target / n)}  {n}\n" for n in (ENTRIES, MANIFEST)), encoding="utf-8")
    return manifest


def verify_reference_list(folder: Path) -> dict[str, Any]:
    """Re-check checksums, contracts, ordering and counts; return the manifest. Raises on any mismatch."""
    def bad(reason: str) -> ValidationError:
        """An integrity error for this package."""
        return ValidationError(f"Reference list {folder} failed verification: {reason}", code="PCC_RL_INTEGRITY")

    if not (folder / CHECKSUMS).is_file():
        raise bad("no CHECKSUMS.sha256")
    listed = dict(reversed(line.split("  ", 1)) for line in (folder / CHECKSUMS).read_text(encoding="utf-8").splitlines() if line)
    if sorted(listed) != sorted((ENTRIES, MANIFEST)):
        raise bad("unexpected checksum list")
    for name, digest in listed.items():
        if not (folder / name).is_file() or _sha(folder / name) != digest:
            raise bad(f"{name} differs from its checksum")
    manifest = read_json(folder / MANIFEST, kind="reference_list_manifest")
    if manifest["entries_sha256"] != _sha(folder / ENTRIES):
        raise bad("entries differ from the manifest")
    entries = read_jsonl(folder / ENTRIES, kind="reference_list_entry")
    keys = [entry["concept_key"] for entry in entries]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise bad("entries are not unique and sorted by concept_key")
    statuses = Counter(entry["status"] for entry in entries)
    expected = {"entries": len(entries), **{s.lower(): statuses.get(s, 0) for s in RL_STATUSES}}
    if manifest["counts"] != expected:
        raise bad("counts differ from the entries")
    return manifest


def load_entries(folder: Path) -> list[dict[str, Any]]:
    """Entries of a verified package."""
    verify_reference_list(folder)
    return read_jsonl(folder / ENTRIES, kind="reference_list_entry")


class ReferenceListStore:
    """The Operator's reference lists under ``<resources root>/reference-lists``."""

    def __init__(self, resources_root: Path):
        """Use ``resources_root`` (``localdata/inputs/resources``)."""
        self.root = Path(resources_root) / STORE_FOLDER

    def path(self, rl_id: str, version: int) -> Path:
        """Folder of one version."""
        return self.root / rl_id / str(version)

    def versions(self, rl_id: str) -> list[int]:
        """Existing versions of one RL, ascending."""
        folder = self.root / rl_id
        return sorted(int(p.name) for p in folder.iterdir() if p.is_dir() and p.name.isdigit()) if folder.is_dir() else []

    def lists(self) -> list[dict[str, Any]]:
        """The newest manifest of every RL, by title; unreadable versions are skipped, never fatal."""
        found = []
        for folder in sorted(self.root.iterdir()) if self.root.is_dir() else ():
            versions = self.versions(folder.name)
            if versions:
                try:
                    found.append(verify_reference_list(self.path(folder.name, versions[-1])))
                except ValidationError:
                    continue
        return sorted(found, key=lambda m: (m["title"].casefold(), m["rl_id"]))

    def save(self, *, rl_id: str, title: str, reference: Mapping[str, str], license: Mapping[str, Any],
             build: Mapping[str, Any], entries: Iterable[Mapping[str, Any]], created_utc: str) -> dict[str, Any]:
        """Write the next version of ``rl_id`` (1 for a new list)."""
        versions = self.versions(rl_id)
        version = versions[-1] + 1 if versions else 1
        build = {"base_version": versions[-1] if versions else None, **dict(build)}
        return write_reference_list(self.path(rl_id, version), rl_id=rl_id, version=version, title=title,
                                    reference=reference, license=license, build=build, entries=entries,
                                    created_utc=created_utc)

    def load(self, rl_id: str, version: int | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Manifest and entries of one version (the newest when ``version`` is None)."""
        versions = self.versions(rl_id)
        if not versions or (version is not None and version not in versions):
            raise ValidationError(f"No reference list {rl_id} version {version or 'any'}", code="PCC_RL_MISSING")
        folder = self.path(rl_id, version or versions[-1])
        return verify_reference_list(folder), load_entries(folder)

    def import_package(self, folder: Path) -> tuple[dict[str, Any], str]:
        """Import a verified package folder; return (manifest as stored, "kept" | "imported" | "forked").

        An identical version already present is kept. A different package under the same id and version is
        stored as a fork with a new id, so nothing in the store is ever overwritten.
        """
        manifest = verify_reference_list(folder)
        existing = self.path(manifest["rl_id"], manifest["version"])
        if existing.is_dir():
            if (existing / CHECKSUMS).read_bytes() == (folder / CHECKSUMS).read_bytes():
                return verify_reference_list(existing), "kept"
            entries = read_jsonl(folder / ENTRIES, kind="reference_list_entry")
            fork_id = new_rl_id(manifest["title"], manifest["rl_id"], _sha(folder / CHECKSUMS))
            build = {**manifest["build"], "mode": "IMPORT",
                     "imported_from": {"rl_id": manifest["rl_id"], "version": manifest["version"]}}
            stored = write_reference_list(self.path(fork_id, 1), rl_id=fork_id, version=1, title=manifest["title"],
                                          reference=manifest["reference"], license=manifest["license"], build=build,
                                          entries=entries, created_utc=manifest["created_utc"])
            return stored, "forked"
        existing.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, existing)
        return verify_reference_list(existing), "imported"
