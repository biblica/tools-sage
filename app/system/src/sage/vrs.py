"""SIL-style VRS parsing and project-local custom-versification composition."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .errors import ConfigurationError, VersificationError
from .external_access import validate_external_file
from .hashing import sha256_bytes, sha256_file
from .registry import EcosystemConfig, ProjectSpec


@dataclass(frozen=True, order=True)
class VerseRef:
    """One book, chapter, and verse coordinate."""

    book: str
    chapter: int
    verse: int

    def label(self) -> str:
        """Return the stable USFM-style reference label."""
        return f"{self.book} {self.chapter}:{self.verse}"


@dataclass(frozen=True)
class RefSpan:
    """A verse range restricted to one book and chapter."""

    start: VerseRef
    end: VerseRef

    def refs(self) -> list[VerseRef]:
        """Expand the span into ordered atomic coordinates."""
        if self.start.book != self.end.book or self.start.chapter != self.end.chapter:
            raise VersificationError(
                f"VRS range may not cross books or chapters: {self.start.label()}-{self.end.label()}"
            )
        if self.end.verse < self.start.verse:
            raise VersificationError(
                f"VRS range end precedes start: {self.start.label()}-{self.end.label()}"
            )
        return [
            VerseRef(self.start.book, self.start.chapter, verse)
            for verse in range(self.start.verse, self.end.verse + 1)
        ]

    def label(self) -> str:
        """Return a stable reference or reference-range label."""
        if self.start == self.end:
            return self.start.label()
        return f"{self.start.book} {self.start.chapter}:{self.start.verse}-{self.end.verse}"


@dataclass(frozen=True)
class VerseMapping:
    """A local-to-canonical VRS mapping from one source line."""

    local: RefSpan
    canonical: RefSpan
    source: str
    line_number: int
    continuation: bool = False

    def local_key(self) -> tuple[str, int, int, int]:
        """Return the local range key used for custom override replacement."""
        return (
            self.local.start.book,
            self.local.start.chapter,
            self.local.start.verse,
            self.local.end.verse,
        )


@dataclass
class VersificationSchema:
    """A composed base plus custom versification schema."""

    schema_id: str
    canonical_id: str
    chapter_max: dict[str, dict[int, int]]
    exclusions: set[VerseRef]
    mappings: list[VerseMapping]
    source_files: list[dict[str, str]]

    def chapter_limit(self, book: str, chapter: int) -> int | None:
        """Return the local maximum verse number for a chapter when defined."""
        return self.chapter_max.get(book, {}).get(chapter)

    def local_to_canonical(self, ref: VerseRef) -> frozenset[VerseRef]:
        """Map one local coordinate to its canonical equivalence set.

        Equal-length ranges are paired positionally. A many-to-one continuation
        maps every local coordinate to the single canonical coordinate. Other
        unequal spans are treated as a complete equivalence group because VRS
        data does not encode phrase-level boundaries.
        """
        matches = [mapping for mapping in self.mappings if ref in mapping.local.refs()]
        if not matches:
            return frozenset({ref})
        canonical: set[VerseRef] = set()
        for mapping in matches:
            local_refs = mapping.local.refs()
            canonical_refs = mapping.canonical.refs()
            if len(local_refs) == len(canonical_refs):
                canonical.add(canonical_refs[local_refs.index(ref)])
            elif len(canonical_refs) == 1:
                canonical.add(canonical_refs[0])
            else:
                canonical.update(canonical_refs)
        return frozenset(canonical)

    def canonical_to_local(self, ref: VerseRef) -> frozenset[VerseRef]:
        """Return all local coordinates whose equivalence sets include a canonical ref."""
        local: set[VerseRef] = set()
        for mapping in self.mappings:
            local_refs = mapping.local.refs()
            canonical_refs = mapping.canonical.refs()
            if len(local_refs) == len(canonical_refs):
                if ref in canonical_refs:
                    local.add(local_refs[canonical_refs.index(ref)])
            elif len(canonical_refs) == 1:
                if ref == canonical_refs[0]:
                    local.update(local_refs)
            elif ref in canonical_refs:
                local.update(local_refs)
        if not local:
            local.add(ref)
        return frozenset(local)

    def canonical_set(self, refs: Iterable[VerseRef]) -> frozenset[VerseRef]:
        """Map a local coordinate collection to one canonical equivalence set."""
        canonical: set[VerseRef] = set()
        for ref in refs:
            canonical.update(self.local_to_canonical(ref))
        return frozenset(canonical)

    def mapping_precision(self, refs: Iterable[VerseRef]) -> str:
        """Classify whether mappings preserve coordinate-level attribution."""
        for ref in refs:
            mapped = self.local_to_canonical(ref)
            if len(mapped) != 1:
                return "EQUIVALENCE_GROUP"
            for mapping in self.mappings:
                if ref in mapping.local.refs() and len(mapping.local.refs()) != len(mapping.canonical.refs()):
                    return "EQUIVALENCE_GROUP"
        return "COORDINATE"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the effective schema together with its deterministic provenance hash."""
        content = {
            "schema_id": self.schema_id,
            "canonical_id": self.canonical_id,
            "source_files": self.source_files,
            "chapter_max": {
                book: {str(chapter): maximum for chapter, maximum in sorted(chapters.items())}
                for book, chapters in sorted(self.chapter_max.items())
            },
            "exclusions": [item.label() for item in sorted(self.exclusions)],
            "mappings": [
                {
                    "local": item.local.label(),
                    "canonical": item.canonical.label(),
                    "source": item.source,
                    "line_number": item.line_number,
                    "continuation": item.continuation,
                    "approximate": len(item.local.refs()) != len(item.canonical.refs()),
                }
                for item in self.mappings
            ],
        }
        payload = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {**content, "effective_sha256": sha256_bytes(payload)}


_REF_RE = re.compile(r"^([1-4]?[A-Z0-9]{2,3})\s+(\d+):(\d+)(?:[A-Z])?(?:-(\d+)(?:[A-Z])?)?$")
_CHAPTER_TOKEN_RE = re.compile(r"^(\d+):(\d+)$")
_EXCLUSION_RE = re.compile(r"^#!\s*-\s*([1-4]?[A-Z0-9]{2,3})\s+(\d+):(\d+)(?:-(\d+))?\s*$")


def _strict_text(path: Path) -> str:
    """Read a VRS file as strict UTF-8 and raise a typed error for invalid bytes."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise VersificationError(f"VRS file is not valid UTF-8: {path}: {exc}") from exc


def _parse_span(value: str) -> RefSpan:
    """Parse one VRS chapter or verse span into canonical integer boundaries."""
    match = _REF_RE.fullmatch(value.strip().upper())
    if not match:
        raise VersificationError(f"Invalid VRS coordinate or range: {value!r}")
    book, chapter, start, end = match.groups()
    start_ref = VerseRef(book, int(chapter), int(start))
    end_ref = VerseRef(book, int(chapter), int(end or start))
    return RefSpan(start_ref, end_ref)


def _strip_inline_comment(line: str) -> str:
    """Remove an inline VRS comment without altering the governed value before it."""
    marker = re.search(r"\s+#", line)
    return line[: marker.start()].rstrip() if marker else line.rstrip()


def parse_vrs_file(
    path: Path,
    *,
    schema_id: str,
    canonical_id: str,
    source_label: str | None = None,
) -> VersificationSchema:
    """Parse supported chapter definitions, exclusions, and mappings.

    ``source_label`` is a stable logical identifier used in provenance. Absolute
    filesystem paths are deliberately excluded so effective VRS hashes remain
    identical when the same Paratext projects are moved between computers.
    """
    if not path.exists():
        raise VersificationError(f"VRS file not found: {path}")
    logical_source = source_label or path.name
    chapter_max: dict[str, dict[int, int]] = {}
    exclusions: set[VerseRef] = set()
    mappings: list[VerseMapping] = []
    errors: list[str] = []
    for line_number, raw_line in enumerate(_strict_text(path).splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        exclusion = _EXCLUSION_RE.fullmatch(line)
        if exclusion:
            book, chapter, start, end = exclusion.groups()
            for verse in range(int(start), int(end or start) + 1):
                exclusions.add(VerseRef(book, int(chapter), verse))
            continue
        if line.startswith("#!"):
            line = line[2:].lstrip()
        elif line.startswith("#"):
            continue
        line = _strip_inline_comment(line)
        if not line:
            continue
        if "=" in line:
            continuation = line.startswith("&")
            if continuation:
                line = line[1:].lstrip()
            left, right = (part.strip() for part in line.split("=", 1))
            try:
                mappings.append(
                    VerseMapping(
                        local=_parse_span(left),
                        canonical=_parse_span(right),
                        source=logical_source,
                        line_number=line_number,
                        continuation=continuation,
                    )
                )
            except VersificationError as exc:
                errors.append(f"line {line_number}: {exc}")
            continue
        parts = line.split()
        book = parts[0].upper() if parts else ""
        tokens = parts[1:]
        if not book or not tokens:
            errors.append(f"line {line_number}: invalid chapter definition: {raw_line}")
            continue
        for token in tokens:
            match = _CHAPTER_TOKEN_RE.fullmatch(token)
            if not match:
                errors.append(f"line {line_number}: invalid chapter token {token!r}")
                continue
            chapter, maximum = int(match.group(1)), int(match.group(2))
            chapter_max.setdefault(book, {})[chapter] = maximum
    if errors:
        raise VersificationError(f"{path}: " + "; ".join(errors[:20]))
    return VersificationSchema(
        schema_id=schema_id,
        canonical_id=canonical_id,
        chapter_max=chapter_max,
        exclusions=exclusions,
        mappings=mappings,
        source_files=[{"path": logical_source, "sha256": sha256_file(path)}],
    )


def compose_vrs(
    base: VersificationSchema,
    custom: VersificationSchema | None,
    *,
    schema_id: str,
) -> VersificationSchema:
    """Apply project-local custom definitions over a shared base schema."""
    chapter_max = {book: dict(chapters) for book, chapters in base.chapter_max.items()}
    exclusions = set(base.exclusions)
    mappings = list(base.mappings)
    sources = list(base.source_files)
    if custom is not None:
        for book, chapters in custom.chapter_max.items():
            chapter_max.setdefault(book, {}).update(chapters)
        exclusions.update(custom.exclusions)
        custom_keys = {item.local_key() for item in custom.mappings}
        mappings = [item for item in mappings if item.local_key() not in custom_keys]
        mappings.extend(custom.mappings)
        sources.extend(custom.source_files)
    return VersificationSchema(
        schema_id=schema_id,
        canonical_id=base.canonical_id,
        chapter_max=chapter_max,
        exclusions=exclusions,
        mappings=mappings,
        source_files=sources,
    )



def _casefold_file(root: Path, filename: str) -> Path | None:
    """Return one top-level file by case-insensitive name without following symlinks."""
    if not root.is_dir():
        return None
    wanted = filename.casefold()
    matches = [
        item for item in root.iterdir()
        if item.is_file() and not item.is_symlink() and item.name.casefold() == wanted
    ]
    if len(matches) > 1:
        raise VersificationError(
            f"Ambiguous VRS filename differing only by case in {root}: {filename}"
        )
    return matches[0] if matches else None

def resolve_project_vrs_paths(
    config: EcosystemConfig, project: ProjectSpec
) -> tuple[Path, Path | None]:
    """Resolve project-local VRS files first, then the configurable base-VRS root."""
    base_name = project.versification.base
    project_base = _casefold_file(project.path, base_name)
    if project_base is not None:
        base = project_base
    else:
        configured = config.base_vrs_files.get(base_name.casefold())
        if configured is None:
            raise ConfigurationError(
                f"Project {project.project_id} references undefined base VRS {base_name!r}"
            )
        base = configured if configured.is_file() else (_casefold_file(config.base_vrs_root, configured.name) or configured)

    custom_value = project.versification.custom.strip()
    custom: Path | None
    if custom_value.lower() in {"", "none", "false"}:
        custom = None
    elif custom_value.lower() == "auto":
        custom = _casefold_file(project.path, config.custom_vrs_filename)
    else:
        raw = Path(custom_value)
        if raw.is_absolute() or len(raw.parts) != 1:
            raise ConfigurationError(
                f"Project {project.project_id} custom VRS must be one project-local filename: {custom_value}"
            )
        custom = _casefold_file(project.path, raw.name)
        if custom is None:
            custom = (project.path / raw).resolve()

    if project.external:
        if project_base is not None:
            base = validate_external_file(base, roots=(project.path,), write=False)
        else:
            base = validate_external_file(base, roots=(config.base_vrs_root,), write=False)
        if custom is not None:
            custom = validate_external_file(custom, roots=(project.path,), write=False)
    return base, custom


def load_project_vrs(config: EcosystemConfig, project: ProjectSpec) -> VersificationSchema:
    """Load and compose one project's effective VRS schema."""
    base_path, custom_path = resolve_project_vrs_paths(config, project)
    base = parse_vrs_file(
        base_path,
        schema_id=project.versification.base,
        canonical_id=config.canonical_versification,
        source_label=f"base:{base_path.name}",
    )
    custom = None
    if custom_path is not None:
        if not custom_path.exists():
            raise VersificationError(
                f"Configured custom VRS not found for {project.project_id}: {custom_path}"
            )
        custom = parse_vrs_file(
            custom_path,
            schema_id=f"{project.project_id}-custom",
            canonical_id=config.canonical_versification,
            source_label=f"project:{project.project_id}/{custom_path.name}",
        )
    suffix = f"+{custom_path.name}" if custom else ""
    return compose_vrs(
        base,
        custom,
        schema_id=f"{project.project_id}:{project.versification.base}{suffix}",
    )
