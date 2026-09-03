"""Single workflow-facing API for SAGE versification schemas and projection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import load_json, require_mapping
from .errors import ConfigurationError
from .hashing import sha256_file
from .registry import EcosystemConfig, ProjectSpec
from .vrs import (
    VerseRef,
    VersificationSchema,
    load_project_vrs,
    parse_vrs_file,
    resolve_project_vrs_paths,
)

_PROVENANCE_FILENAME = "standard-vrs-provenance.json"


@dataclass(frozen=True)
class VersificationCatalogEntry:
    """One configured base VRS and its optional governed upstream provenance."""

    filename: str
    path: Path
    sha256: str
    canonical: bool
    default: bool
    source_repository: str | None
    source_commit: str | None
    source_license: str | None
    upstream_path: str | None
    upstream_sha256: str | None


@dataclass(frozen=True)
class ReferenceProjection:
    """Deterministic reference projection through one Project's effective VRS."""

    project_id: str
    schema_id: str
    direction: str
    input_refs: tuple[VerseRef, ...]
    projected_refs: tuple[VerseRef, ...]
    precision: str


class VersificationService:
    """Load, fingerprint, and project configured versification schemas.

    Cache identities include current VRS bytes. Returned schemas are deep copies
    because ``VersificationSchema`` still contains mutable collections.
    """

    def __init__(self, config: EcosystemConfig) -> None:
        """Create an isolated service whose caches follow one ecosystem config."""
        self.config = config
        # Keep caches instance-local so tests and independently loaded ecosystems do not leak state.
        self._base_cache: dict[str, tuple[tuple[str, ...], VersificationSchema]] = {}
        self._project_cache: dict[str, tuple[tuple[str, ...], VersificationSchema]] = {}

    def _provenance(self) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        """Load optional governed provenance for the bundled standard VRS files."""
        path = self.config.base_vrs_root / _PROVENANCE_FILENAME
        if not path.is_file():
            return {}, {}
        document = load_json(path)
        source = {
            str(key): str(value)
            for key, value in require_mapping(
                document.get("source"), "standard VRS provenance source"
            ).items()
            if value is not None
        }
        resources = document.get("resources")
        if not isinstance(resources, list):
            raise ConfigurationError("standard VRS provenance resources must be a list")
        rows: dict[str, dict[str, str]] = {}
        for index, value in enumerate(resources):
            row = require_mapping(value, f"standard VRS provenance resources[{index}]")
            filename = str(row.get("filename") or "").strip()
            if not filename:
                raise ConfigurationError(
                    f"standard VRS provenance resources[{index}].filename must not be empty"
                )
            key = filename.casefold()
            if key in rows:
                raise ConfigurationError(
                    f"Duplicate standard VRS provenance filename: {filename}"
                )
            rows[key] = {
                str(item_key): str(item_value)
                for item_key, item_value in row.items()
                if item_value is not None
            }
        return source, rows

    def catalog(self) -> tuple[VersificationCatalogEntry, ...]:
        """Return all configured base schemas with roles, hashes, and provenance."""
        source, provenance = self._provenance()
        entries: list[VersificationCatalogEntry] = []
        for key, path in sorted(self.config.base_vrs_files.items()):
            digest = sha256_file(path)
            row = provenance.get(key, {})
            shipped = row.get("shipped_sha256")
            if shipped is not None and shipped != digest:
                raise ConfigurationError(
                    f"Standard VRS provenance hash mismatch for {path.name}: "
                    f"expected {shipped}, found {digest}"
                )
            entries.append(
                VersificationCatalogEntry(
                    filename=path.name,
                    path=path,
                    sha256=digest,
                    canonical=key == self.config.canonical_versification.casefold(),
                    default=key == self.config.default_versification.casefold(),
                    source_repository=source.get("repository") if row else None,
                    source_commit=source.get("commit") if row else None,
                    source_license=source.get("license") if row else None,
                    upstream_path=row.get("upstream_path"),
                    upstream_sha256=row.get("upstream_sha256"),
                )
            )
        return tuple(entries)

    def base_schema(self, filename: str) -> VersificationSchema:
        """Load one configured base VRS by filename with content-aware caching."""
        key = filename.strip().casefold()
        try:
            path = self.config.base_vrs_files[key]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown base VRS filename: {filename}") from exc
        digest = sha256_file(path)
        identity = (str(path.resolve()), digest, self.config.canonical_versification)
        cached = self._base_cache.get(key)
        if cached is None or cached[0] != identity:
            schema = parse_vrs_file(
                path,
                schema_id=path.name,
                canonical_id=self.config.canonical_versification,
                source_label=f"base:{path.name}",
            )
            self._base_cache[key] = (identity, schema)
        return deepcopy(self._base_cache[key][1])

    def _project(self, project_or_id: ProjectSpec | str) -> ProjectSpec:
        """Resolve a Project identifier while accepting an already resolved specification."""
        return (
            self.config.project(project_or_id)
            if isinstance(project_or_id, str)
            else project_or_id
        )

    def project_schema(
        self, project_or_id: ProjectSpec | str
    ) -> VersificationSchema:
        """Load one Project's effective base/custom schema without stale cache reuse."""
        project = self._project(project_or_id)
        base_path, custom_path = resolve_project_vrs_paths(self.config, project)
        if not base_path.is_file() or (
            custom_path is not None and not custom_path.is_file()
        ):
            return load_project_vrs(self.config, project)
        identity = (
            str(base_path.resolve()),
            sha256_file(base_path),
            str(custom_path.resolve()) if custom_path is not None else "",
            sha256_file(custom_path) if custom_path is not None else "",
            project.versification.base,
            project.versification.custom,
            self.config.canonical_versification,
        )
        cached = self._project_cache.get(project.project_id)
        if cached is None or cached[0] != identity:
            self._project_cache[project.project_id] = (
                identity,
                load_project_vrs(self.config, project),
            )
        return deepcopy(self._project_cache[project.project_id][1])

    def effective_fingerprint(self, project_or_id: ProjectSpec | str) -> str:
        """Return the effective schema hash for one configured Project."""
        return str(self.project_schema(project_or_id).to_dict()["effective_sha256"])

    def to_canonical(
        self,
        project_or_id: ProjectSpec | str,
        refs: Iterable[VerseRef],
    ) -> ReferenceProjection:
        """Project Project-local references into canonical VRS coordinates."""
        project = self._project(project_or_id)
        schema = self.project_schema(project)
        input_refs = tuple(sorted(set(refs)))
        projected_refs = tuple(sorted(schema.canonical_set(input_refs)))
        precision = schema.mapping_precision(input_refs)
        if precision == "COORDINATE":
            for ref in input_refs:
                canonical_refs = schema.local_to_canonical(ref)
                canonical_ref = next(iter(canonical_refs))
                if schema.canonical_to_local(canonical_ref) != frozenset({ref}):
                    precision = "EQUIVALENCE_GROUP"
                    break
        return ReferenceProjection(
            project_id=project.project_id,
            schema_id=schema.schema_id,
            direction="LOCAL_TO_CANONICAL",
            input_refs=input_refs,
            projected_refs=projected_refs,
            precision=precision,
        )

    def from_canonical(
        self,
        project_or_id: ProjectSpec | str,
        refs: Iterable[VerseRef],
    ) -> ReferenceProjection:
        """Project canonical references into one Project's local coordinates."""
        project = self._project(project_or_id)
        schema = self.project_schema(project)
        input_refs = tuple(sorted(set(refs)))
        projected: set[VerseRef] = set()
        precise = True
        for ref in input_refs:
            local_refs = schema.canonical_to_local(ref)
            projected.update(local_refs)
            if len(local_refs) != 1:
                precise = False
                continue
            local_ref = next(iter(local_refs))
            if schema.local_to_canonical(local_ref) != frozenset({ref}):
                precise = False
        return ReferenceProjection(
            project_id=project.project_id,
            schema_id=schema.schema_id,
            direction="CANONICAL_TO_LOCAL",
            input_refs=input_refs,
            projected_refs=tuple(sorted(projected)),
            precision="COORDINATE" if precise else "EQUIVALENCE_GROUP",
        )
