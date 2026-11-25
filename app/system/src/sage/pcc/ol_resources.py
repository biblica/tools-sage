"""Load the pinned PCC original-language resource package (``SAGE_PCC_OL_<date>``).

The package (``system/resources/pcc-ol/<date>/``, pinned by ``system/config/pcc-ol-reference.json``) holds
the gold BSB word alignment, Clear word senses and syntax-tree phrase groups, all keyed by the MACULA word
``ref`` of the OL analysis package. It is checked against its checksums on load, like the OL analysis package.
Build it with ``tools/build_pcc_ol_resources.py`` (see ``sage.pcc.ol_build``).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from .ol_build import BSB_ALIGNMENT, OL_GROUPS, OL_SENSES, REFS_SEPARATOR

PIN_PATH = Path("system/config/pcc-ol-reference.json")
_CACHE: dict[Path, "PccOlResources"] = {}


@dataclass(frozen=True)
class BsbLink:
    """Where one original-language word is rendered in the BSB."""

    bsb_ref: str
    order: int
    english: str
    punct: str
    match: str      # "strong" (Strong's sequence) or "position" (short equal gap between anchors)


@dataclass(frozen=True)
class OlGroup:
    """One syntax-tree phrase group (noun, adjective or prepositional phrase)."""

    cls: str
    rule: str
    role: str
    refs: tuple[str, ...]


def _rows(data: bytes) -> list[dict[str, str]]:
    """Parse one package TSV."""
    return list(csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter="\t"))


class PccOlResources:
    """The verified package; each table is parsed on first use."""

    def __init__(self, package_id: str, manifest: dict[str, Any], blobs: dict[str, bytes]):
        """Keep the verified files."""
        self.package_id = package_id
        self.manifest = manifest
        self._blobs = blobs

    @cached_property
    def bsb_alignment(self) -> dict[str, BsbLink]:
        """MACULA word ref -> its BSB rendering (only words the BSB tables pair with MACULA)."""
        return {r["ol_ref"]: BsbLink(r["bsb_ref"], int(r["bsb_order"]), r["english"], r["punct"], r["match"] or "strong")
                for r in _rows(self._blobs[BSB_ALIGNMENT])}

    @cached_property
    def senses(self) -> dict[tuple[str, int], str]:
        """(MACULA word ref, segment index) -> Clear word-sense number."""
        return {(r["ol_ref"], int(r["seg"])): r["sense"] for r in _rows(self._blobs[OL_SENSES])}

    @cached_property
    def groups(self) -> list[OlGroup]:
        """All phrase groups, in original-language order."""
        return [OlGroup(r["class"], r["rule"], r["role"], tuple(r["refs"].split(REFS_SEPARATOR)))
                for r in _rows(self._blobs[OL_GROUPS])]

    @cached_property
    def groups_by_ref(self) -> dict[str, list[OlGroup]]:
        """MACULA word ref -> the phrase groups it belongs to."""
        index: dict[str, list[OlGroup]] = defaultdict(list)
        for group in self.groups:
            for ref in group.refs:
                index[ref].append(group)
        return dict(index)


def load_pcc_ol(root: Path) -> PccOlResources | None:
    """Load and integrity-check the pinned package once per process; None when SAGE has no pin."""
    pin_path = Path(root) / PIN_PATH
    if not pin_path.is_file():
        return None
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    package = (Path(root) / str(pin["path"])).resolve()
    if package in _CACHE:
        return _CACHE[package]
    checksums_bytes = (package / "CHECKSUMS.sha256").read_bytes()
    if hashlib.sha256(checksums_bytes).hexdigest() != pin["sha256"]:
        raise ValidationError("PCC original-language package checksums differ from the Core pin",
                              code="PCC_OL_RESOURCES_INTEGRITY")
    expected = dict(reversed(line.split("  ", 1)) for line in checksums_bytes.decode("utf-8").splitlines() if line)
    blobs: dict[str, bytes] = {}
    for name, digest in expected.items():
        data = (package / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValidationError(f"PCC original-language package file {name} differs from its checksum",
                                  code="PCC_OL_RESOURCES_INTEGRITY")
        blobs[name] = data
    manifest = json.loads(blobs["MANIFEST.json"].decode("utf-8"))
    if manifest.get("package_id") != pin.get("package_id"):
        raise ValidationError("PCC original-language package is not the pinned one", code="PCC_OL_RESOURCES_INTEGRITY")
    resources = PccOlResources(str(pin["package_id"]), manifest, blobs)
    _CACHE[package] = resources
    return resources
