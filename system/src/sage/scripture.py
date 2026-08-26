"""Project discovery, strict USFM validation, USJ caching, and VRS checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .canon import PERIPHERAL_BOOKS, resolve_expected_books
from .errors import ValidationError
from .hashing import sha256_bytes, sha256_file, sha256_paths
from .registry import EcosystemConfig, ProjectSpec
from .sections import section_index_from_usj
from .structure_policy import load_structure_policy
from .usj import USJ_COMPILER, compile_usfm_file, parse_usj_units
from .vrs import VerseRef, VersificationSchema, load_project_vrs, parse_vrs_file
from .references import BOOK_ORDER, ScriptureScope

USFM_SUFFIXES = {".sfm"}
BOOK_ID_BYTES_RE = re.compile(rb"(?m)^\\id[ \t]+([A-Za-z0-9]{3})(?:[ \t\r]|$)")


def _peek_book_code(path: Path) -> str | None:
    """Read an ASCII ``\\id`` code without decoding unrelated Scripture text."""
    try:
        with path.open("rb") as source:
            prefix = source.read(65536)
    except OSError as exc:
        raise ValidationError(f"Unable to inspect USFM book ID in {path}: {exc}") from exc
    match = BOOK_ID_BYTES_RE.search(prefix)
    return match.group(1).decode("ascii").upper() if match else None


def discover_usfm_files(
    project_root: Path,
    *,
    books: set[str] | frozenset[str] | None = None,
) -> list[Path]:
    """Return top-level Paratext Scripture files, optionally for selected books.

    Scope-limited discovery reads only each file's ASCII ``\\id`` prefix. The
    selected book is still decoded and validated strictly when compiled.
    """
    if not project_root.exists() or not project_root.is_dir():
        return []
    files = sorted(
        path
        for path in project_root.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.casefold() in USFM_SUFFIXES
        and not path.name.startswith(".")
    )
    if books is None:
        return files
    selected = {book.upper() for book in books}
    return [path for path in files if _peek_book_code(path) in selected]


def discover_book_ids(project_root: Path) -> dict[str, Path]:
    """Return discovered top-level USFM book IDs and their source files."""
    result: dict[str, Path] = {}
    for path in discover_usfm_files(project_root):
        book = _peek_book_code(path)
        if book is not None and book not in result:
            result[book] = path
    return result




VERSIFICATION_ADVISORY_CODES = frozenset({
    "EXCLUDED_COORDINATE_PRESENT",
    "COORDINATE_OUTSIDE_VRS",
    "EXPECTED_CHAPTER_MISSING",
    "EXPECTED_COORDINATE_MISSING",
})


def is_default_vrs_compatible_issue(
    config: EcosystemConfig,
    project: ProjectSpec,
    issue: dict[str, str],
) -> bool:
    """Return whether a VRS defect is explained by SAGE's default ENG/KJV scheme.

    SAGE's canonical VRS (org.vrs) is the mapping target, not the default numbering
    assumed for an undeclared translation Project.  A coordinate discrepancy is
    advisory for SAW only when the same coordinate state is valid under the
    configured default VRS.  Genuine missing Scripture under the default remains
    blocking.
    """
    code = str(issue.get("code") or "").upper()
    if code not in VERSIFICATION_ADVISORY_CODES:
        return False
    default_name = config.default_versification
    default_path = config.base_vrs_files.get(default_name.casefold())
    if default_path is None or not default_path.is_file():
        return False
    default_schema = parse_vrs_file(
        default_path,
        schema_id=default_name,
        canonical_id=config.canonical_versification,
        source_label=f"base:{default_path.name}",
    )
    reference = str(issue.get("reference") or "").strip().upper()
    match = re.fullmatch(r"([1-4]?[A-Z0-9]{2,3})\s+(\d+)(?::(\d+))?", reference)
    if not match:
        return False
    book = match.group(1)
    chapter = int(match.group(2))
    verse_text = match.group(3)
    maximum = default_schema.chapter_limit(book, chapter)
    if verse_text is None:
        return code == "EXPECTED_CHAPTER_MISSING" and maximum is None
    verse = int(verse_text)
    ref = VerseRef(book, chapter, verse)
    expected_by_default = maximum is not None and 1 <= verse <= maximum and ref not in default_schema.exclusions
    if code in {"EXPECTED_COORDINATE_MISSING", "EXPECTED_CHAPTER_MISSING"}:
        return not expected_by_default
    if code in {"COORDINATE_OUTSIDE_VRS", "EXCLUDED_COORDINATE_PRESENT"}:
        return expected_by_default
    return False

def _critical_parser_error(value: str) -> bool:
    """Return the first parser condition that makes bounded Scripture use unsafe."""
    return value.startswith(("UNCLOSED_", "UNEXPECTED_", "INVALID_", "MISSING_BOOK_ID")) or any(
        token in value for token in (":UNCLOSED_", ":UNEXPECTED_", ":INVALID_")
    )


def validate_usj_document(
    usj: dict[str, Any],
    schema: VersificationSchema,
    *,
    coverage_policy: str,
) -> dict[str, Any]:
    """Validate one compiled book against marker order and effective VRS."""
    # Check structural order before VRS reconciliation so malformed content cannot mimic missing coordinates.
    units = parse_usj_units(usj)
    book = str(usj.get("sage", {}).get("book_code", "UNK"))
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    parser_errors = list(usj.get("sage", {}).get("errors", []))
    for parser_error in parser_errors:
        target = issues if _critical_parser_error(parser_error) else warnings
        target.append(
            {
                "code": "USFM_PARSER_ERROR" if target is issues else "USFM_PARSER_WARNING",
                "reference": book,
                "message": parser_error,
            }
        )

    seen_ranges: set[tuple[int, int, int]] = set()
    actual_refs: set[VerseRef] = set()
    last_by_chapter: dict[int, tuple[int, int]] = {}
    empty_units = 0
    note_only_units = 0
    for unit in units:
        chapter = int(unit["chapter"])
        start = int(unit["verse_start"])
        end = int(unit["verse_end"])
        key = (chapter, start, end)
        label = f"{book} {chapter}:{start}" + (f"-{end}" if end != start else "")
        if key in seen_ranges:
            issues.append(
                {
                    "code": "DUPLICATE_VERSE_RANGE",
                    "reference": label,
                    "message": "Duplicate verse marker or bridge.",
                }
            )
        seen_ranges.add(key)
        prior = last_by_chapter.get(chapter)
        if prior and start <= prior[1]:
            issues.append(
                {
                    "code": "OVERLAPPING_OR_OUT_OF_ORDER_RANGE",
                    "reference": label,
                    "message": f"Verse range follows or overlaps {book} {chapter}:{prior[0]}-{prior[1]}.",
                }
            )
        last_by_chapter[chapter] = (start, end)
        body = str(unit.get("body_text_exact", unit.get("body_text", ""))).strip()
        raw = str(unit.get("raw_usfm", ""))
        if not body:
            empty_units += 1
            note_only = any(marker in raw for marker in ("\\f ", "\\f+", "\\x ", "\\x+"))
            if note_only:
                note_only_units += 1
                warnings.append(
                    {
                        "code": "PRESENT_NOTE_ONLY",
                        "reference": label,
                        "message": "Verse coordinate contains note material but no visible body text.",
                    }
                )
            else:
                warnings.append(
                    {
                        "code": "EMPTY_VISIBLE_BODY",
                        "reference": label,
                        "message": "Verse coordinate has no visible body text.",
                    }
                )
        for verse in range(start, end + 1):
            ref = VerseRef(book, chapter, verse)
            actual_refs.add(ref)
            if ref in schema.exclusions:
                warnings.append(
                    {
                        "code": "EXCLUDED_COORDINATE_PRESENT",
                        "reference": ref.label(),
                        "message": "Coordinate is excluded by the effective project VRS but is present in USFM.",
                    }
                )
            maximum = schema.chapter_limit(book, chapter)
            if maximum is not None and verse > maximum and verse != 0:
                warnings.append(
                    {
                        "code": "COORDINATE_OUTSIDE_VRS",
                        "reference": ref.label(),
                        "message": f"Coordinate exceeds configured chapter maximum {maximum}.",
                    }
                )

    chapters_present = sorted({ref.chapter for ref in actual_refs})
    schema_chapters = sorted(schema.chapter_max.get(book, {}))
    if coverage_policy == "CONFIGURED_BOOKS_COMPLETE" and schema_chapters:
        for chapter in sorted(set(schema_chapters) - set(chapters_present)):
            warnings.append(
                {
                    "code": "EXPECTED_CHAPTER_MISSING",
                    "reference": f"{book} {chapter}",
                    "message": "Chapter is defined by the effective VRS but absent from the project book file.",
                }
            )
    selected_chapters = schema_chapters if coverage_policy == "CONFIGURED_BOOKS_COMPLETE" else chapters_present
    for chapter in selected_chapters:
        maximum = schema.chapter_limit(book, chapter)
        if maximum is None:
            continue
        expected = {
            VerseRef(book, chapter, verse)
            for verse in range(1, maximum + 1)
            if VerseRef(book, chapter, verse) not in schema.exclusions
        }
        for missing in sorted(expected - actual_refs):
            warnings.append(
                {
                    "code": "EXPECTED_COORDINATE_MISSING",
                    "reference": missing.label(),
                    "message": "Coordinate is expected by the effective VRS and is not covered by a verse marker or bridge.",
                }
            )
    if book in {"", "UNK"}:
        issues.append(
            {
                "code": "BOOK_ID_MISSING",
                "reference": "",
                "message": "Valid USFM \\id marker not found.",
            }
        )
    if not units:
        issues.append(
            {
                "code": "NO_VERSE_UNITS",
                "reference": book,
                "message": "No verse units were compiled.",
            }
        )
    return {
        "book": book,
        "verse_units": len(units),
        "atomic_coordinates": len(actual_refs),
        "chapters_present": chapters_present,
        "empty_visible_body_units": empty_units,
        "note_only_units": note_only_units,
        "issues": issues,
        "warnings": warnings,
        "status": "BLOCKED" if issues else ("READY_WITH_WARNINGS" if warnings else "READY"),
    }


def _cache_key(source_hash: str, structure_policy_sha256: str) -> str:
    """Build a content-addressed cache key from source, compiler, and effective VRS identity."""
    payload = f"{USJ_COMPILER}\0{structure_policy_sha256}\0{source_hash}"
    return sha256_bytes(payload.encode("utf-8"))[:24]


def _cache_path(
    config: EcosystemConfig,
    project: ProjectSpec,
    source: Path,
    source_hash: str,
    structure_policy_sha256: str,
) -> Path:
    """Return the governed USJ cache path for one content-addressed compilation."""
    key = _cache_key(source_hash, structure_policy_sha256)
    return config.cache_root / "usj" / project.project_id / f"{source.stem}-{key}.usj.json"


def _section_cache_path(
    config: EcosystemConfig,
    project: ProjectSpec,
    source: Path,
    source_hash: str,
    structure_policy_sha256: str,
) -> Path:
    """Return the governed section-index cache path for one compiled book."""
    key = _cache_key(source_hash, structure_policy_sha256)
    return (
        config.cache_root
        / "section-indexes"
        / project.project_id
        / f"{source.stem}-{key}.sections.json"
    )


def compile_project(
    config: EcosystemConfig,
    project: ProjectSpec,
    *,
    books: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Compile and validate one project or a selected book set without editing it."""
    # Validate and cache books independently so one failed book cannot contaminate another result.
    requested_books = frozenset(book.upper() for book in (books or ()))
    all_files = discover_usfm_files(project.path)
    files = (
        discover_usfm_files(project.path, books=requested_books)
        if books is not None
        else [path for path in all_files if _peek_book_code(path) not in PERIPHERAL_BOOKS]
    )
    peripheral_books = sorted(
        {
            book
            for path in all_files
            if (book := _peek_book_code(path)) in PERIPHERAL_BOOKS
        }
    )
    if project.enabled and not project.path.exists():
        if project.allow_empty:
            return {
                "project_id": project.project_id,
                "path": str(project.path),
                "status": "NOT_GENERATED",
                "generation_state": "NOT_RUN",
                "issues": [],
                "warnings": [],
                "summary": {"files": 0, "books": [], "verse_units": 0, "atomic_coordinates": 0},
                "files": [],
            }
        return {
            "project_id": project.project_id,
            "path": str(project.path),
            "status": "BLOCKED",
            "issues": [
                {
                    "code": "PROJECT_ROOT_MISSING",
                    "reference": "",
                    "message": f"Project root does not exist: {project.path}",
                }
            ],
            "warnings": [],
            "files": [],
        }
    if project.enabled and books is not None and not files:
        return {
            "project_id": project.project_id,
            "path": str(project.path),
            "status": "BLOCKED",
            "issues": [
                {
                    "code": "REQUESTED_BOOKS_MISSING",
                    "reference": ", ".join(sorted(requested_books)),
                    "message": "No top-level USFM files matched the requested book IDs.",
                }
            ],
            "warnings": [],
            "summary": {
                "files": 0,
                "books": [],
                "verse_units": 0,
                "atomic_coordinates": 0,
                "scope_limited": True,
                "requested_books": sorted(requested_books),
            },
            "files": [],
        }
    if project.enabled and not files:
        if project.allow_empty:
            return {
                "project_id": project.project_id,
                "path": str(project.path),
                "status": "NOT_GENERATED",
                "generation_state": "NOT_RUN",
                "issues": [],
                "warnings": [],
                "summary": {"files": 0, "books": [], "verse_units": 0, "atomic_coordinates": 0},
                "files": [],
            }
        return {
            "project_id": project.project_id,
            "path": str(project.path),
            "status": "BLOCKED",
            "issues": [
                {
                    "code": "USFM_FILES_MISSING",
                    "reference": "",
                    "message": "No top-level .SFM files were found.",
                }
            ],
            "warnings": [],
            "files": [],
        }
    if not project.enabled:
        return {
            "project_id": project.project_id,
            "path": str(project.path),
            "status": "NOT_APPLICABLE",
            "issues": [],
            "warnings": [],
            "files": [],
        }

    schema = load_project_vrs(config, project)
    structure_policy = load_structure_policy(config.root)
    file_results: list[dict[str, Any]] = []
    project_issues: list[dict[str, str]] = []
    project_warnings: list[dict[str, str]] = []
    seen_books: dict[str, Path] = {}
    total_verse_units = 0
    total_atomic = 0
    total_sections = 0
    total_poetry_blocks = 0
    total_paragraphs = 0
    for source in files:
        source_hash = sha256_file(source)
        cache_path = _cache_path(
            config,
            project,
            source,
            source_hash,
            structure_policy.effective_sha256,
        )
        try:
            if cache_path.exists():
                usj = json.loads(cache_path.read_text(encoding="utf-8"))
                sage_meta = usj.get("sage", {})
                if (
                    sage_meta.get("source_sha256") != source_hash
                    or sage_meta.get("compiler") != USJ_COMPILER
                    or sage_meta.get("structure_policy_sha256")
                    != structure_policy.effective_sha256
                ):
                    usj = compile_usfm_file(
                        source,
                        structure_policy=structure_policy,
                    )
                    atomic_write_json(cache_path, usj)
            else:
                usj = compile_usfm_file(
                    source,
                    structure_policy=structure_policy,
                )
                atomic_write_json(cache_path, usj)
        except UnicodeError as exc:
            raise ValidationError(f"Invalid UTF-8 or replacement character in {source}: {exc}") from exc
        except json.JSONDecodeError:
            usj = compile_usfm_file(
                source,
                structure_policy=structure_policy,
            )
            atomic_write_json(cache_path, usj)
        result = validate_usj_document(
            usj,
            schema,
            coverage_policy=project.coverage_policy,
        )
        section_cache = _section_cache_path(
            config,
            project,
            source,
            source_hash,
            structure_policy.effective_sha256,
        )
        regenerate_section_cache = True
        if section_cache.exists():
            try:
                cached_section = json.loads(section_cache.read_text(encoding="utf-8"))
                regenerate_section_cache = (
                    cached_section.get("structure_policy", {}).get("sha256")
                    != structure_policy.effective_sha256
                )
            except json.JSONDecodeError:
                regenerate_section_cache = True
        if regenerate_section_cache:
            atomic_write_json(section_cache, section_index_from_usj(usj))
        book = result["book"]
        if book in seen_books:
            result["issues"].append(
                {
                    "code": "DUPLICATE_BOOK_ID",
                    "reference": book,
                    "message": f"Book ID is also supplied by {seen_books[book].name}.",
                }
            )
            result["status"] = "BLOCKED"
        else:
            seen_books[book] = source
        entry = {
            "source": str(source),
            "source_sha256": source_hash,
            "cache": str(cache_path),
            "section_index": str(section_cache),
            **result,
        }
        file_results.append(entry)
        project_issues.extend({**issue, "file": str(source)} for issue in result["issues"])
        project_warnings.extend({**warning, "file": str(source)} for warning in result["warnings"])
        total_verse_units += int(result["verse_units"])
        total_atomic += int(result["atomic_coordinates"])
        section_summary = json.loads(section_cache.read_text(encoding="utf-8")).get("summary", {})
        total_sections += int(section_summary.get("sections", 0))
        total_poetry_blocks += int(section_summary.get("poetry_blocks", 0))
        total_paragraphs += int(section_summary.get("paragraphs", 0))

    resource_hash = sha256_paths(all_files, relative_to=project.path)
    compiled_files_hash = sha256_paths(files, relative_to=project.path)
    status = "BLOCKED" if project_issues else ("READY_WITH_WARNINGS" if project_warnings else "READY")
    return {
        "project_id": project.project_id,
        "path": str(project.path),
        "language_code": project.language_code,
        "language_profile": project.language_profile,
        "profile_variant": project.profile_variant,
        "kind": project.kind,
        "content_state": project.content_state,
        "roles": list(project.scope.roles),
        "producer": project.producer,
        "coverage_policy": project.coverage_policy,
        "declared_scope": {
            "testament": project.scope.testament,
            "canon": project.scope.canon,
            "expected_books": (
                project.scope.expected_books
                if isinstance(project.scope.expected_books, str)
                else list(project.scope.expected_books)
            ),
            "resolved_expected_books": list(resolve_expected_books(project.scope)),
            "roles": list(project.scope.roles),
            "content_state": project.content_state,
        },
        "status": status,
        "resource_sha256": resource_hash,
        "compiled_files_sha256": compiled_files_hash,
        "effective_vrs": schema.to_dict(),
        "structure_policy": structure_policy.to_dict(),
        "summary": {
            "files": len(file_results),
            "books": sorted(seen_books),
            "verse_units": total_verse_units,
            "atomic_coordinates": total_atomic,
            "sections": total_sections,
            "poetry_blocks": total_poetry_blocks,
            "paragraphs": total_paragraphs,
            "issues": len(project_issues),
            "warnings": len(project_warnings),
            "peripheral_books": peripheral_books,
            "scope_limited": books is not None,
            "requested_books": sorted(requested_books),
        },
        "issues": project_issues,
        "warnings": project_warnings,
        "files": file_results,
    }


_SCOPE_REFERENCE_RE = re.compile(
    r"(?<![A-Z0-9])(?P<book>[1-4]?[A-Z0-9]{2,3})(?:\s+(?P<chapter>\d+)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?)?(?![A-Z0-9])"
)


def _issue_intersects_scope(issue: dict[str, str], scope: "ScriptureScope") -> bool:
    """Return whether one validation issue can affect the requested scope.

    Prefer the most specific canonical Scripture coordinate present anywhere in the
    issue. Parser diagnostics often use a book-only ``reference`` while embedding the
    exact chapter/verse in ``message``; a broad book label must not override that more
    precise coordinate. Issues with no canonical Scripture coordinate remain
    conservatively blocking.
    """
    matches: list[tuple[int, str, int | None, int | None, int | None]] = []
    for value in (str(issue.get("reference", "")), str(issue.get("message", ""))):
        for match in _SCOPE_REFERENCE_RE.finditer(value.upper()):
            book = match.group("book")
            if book not in BOOK_ORDER:
                continue
            chapter_text = match.group("chapter")
            start_text = match.group("start")
            if chapter_text is None:
                matches.append((1, book, None, None, None))
                continue
            chapter = int(chapter_text)
            if start_text is None:
                matches.append((2, book, chapter, None, None))
                continue
            start = int(start_text)
            end = int(match.group("end") or start)
            matches.append((3, book, chapter, start, end))

    if not matches:
        return True

    specificity = max(item[0] for item in matches)
    for _, book, chapter, start, end in (item for item in matches if item[0] == specificity):
        if book != scope.book:
            continue
        if chapter is None:
            return True
        if start is None:
            if scope.start_chapter is None:
                return True
            end_chapter = scope.end_chapter or scope.start_chapter
            if scope.start_chapter <= chapter <= end_chapter:
                return True
            continue
        assert end is not None
        if any(scope.contains(VerseRef(scope.book, chapter, verse)) for verse in range(start, end + 1)):
            return True
    return False


def compile_project_scope(
    config: EcosystemConfig,
    project: ProjectSpec,
    scope: "ScriptureScope",
) -> dict[str, Any]:
    """Compile one requested book and calculate readiness for the exact scope.

    Project-wide defects outside the requested scope remain reported in the last
    initialization state, but do not prevent a bounded task from starting.
    """
    result = compile_project(config, project, books={scope.book})
    if result.get("status") in {"NOT_GENERATED", "NOT_APPLICABLE"}:
        return {**result, "scope": scope.label(), "scope_limited": True}
    issues = list(result.get("issues", []))
    warnings = list(result.get("warnings", []))
    in_scope_issues = [item for item in issues if _issue_intersects_scope(item, scope)]
    out_scope_issues = [item for item in issues if item not in in_scope_issues]
    in_scope_warnings = [item for item in warnings if _issue_intersects_scope(item, scope)]
    out_scope_warnings = [item for item in warnings if item not in in_scope_warnings]
    status = "BLOCKED" if in_scope_issues else ("READY_WITH_WARNINGS" if in_scope_warnings else "READY")
    summary = dict(result.get("summary", {}))
    summary.update({
        "scope_limited": True,
        "requested_scope": scope.label(),
        "out_of_scope_issue_count": len(out_scope_issues),
        "out_of_scope_warning_count": len(out_scope_warnings),
    })
    return {
        **result,
        "project_status": result.get("status"),
        "status": status,
        "scope": scope.label(),
        "scope_limited": True,
        "issues": in_scope_issues,
        "warnings": in_scope_warnings,
        "out_of_scope_issues": out_scope_issues,
        "out_of_scope_warnings": out_scope_warnings,
        "summary": summary,
    }
