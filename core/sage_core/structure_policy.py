"""Load and validate the normative USFM structure-planning policy."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import load_yaml, require_mapping, require_string
from .errors import ConfigurationError
from .hashing import sha256_bytes, sha256_file


@dataclass(frozen=True)
class StructurePolicy:
    """Governed marker classes and boundary scores used by the work-unit planner."""

    policy_id: str
    schema_version: str
    status: str
    purpose: str
    section_scores: dict[str, int]
    poetry_scores: dict[str, int]
    ignored_split_headers: frozenset[str]
    continuation_markers: frozenset[str]
    header_patterns: tuple[str, ...]
    body_paragraph_patterns: tuple[str, ...]
    poetry_line_patterns: tuple[str, ...]
    paragraph_score: int
    chapter_score: int
    chapter_continuation_score: int
    verse_score: int
    book_overrides: dict[str, dict[str, dict[str, int]]]
    source_path: Path | None
    source_sha256: str
    effective_sha256: str

    def section_score(self, marker: str, book_code: str | None = None) -> int | None:
        """Return the section-boundary score, applying a book override when present."""
        cleaned = _clean_marker(marker)
        if book_code:
            override = self.book_overrides.get(book_code.upper(), {}).get("section", {})
            if cleaned in override:
                return override[cleaned]
        return self.section_scores.get(cleaned)

    def poetry_score(self, marker: str, book_code: str | None = None) -> int | None:
        """Return the poetry-boundary score, applying a book override when present."""
        cleaned = _clean_marker(marker)
        if book_code:
            override = self.book_overrides.get(book_code.upper(), {}).get("poetry", {})
            if cleaned in override:
                return override[cleaned]
        return self.poetry_scores.get(cleaned)

    def chapter_score_for(self, book_code: str | None = None) -> int:
        """Return the chapter score, applying a book-specific override when configured."""
        if book_code:
            chapter = self.book_overrides.get(book_code.upper(), {}).get("scores", {}).get("chapter")
            if chapter is not None:
                return int(chapter)
        return self.chapter_score

    def is_ignored_split_header(self, marker: str) -> bool:
        """Return whether a marker is a structural header but not a split candidate."""
        return _clean_marker(marker) in self.ignored_split_headers

    def is_continuation(self, marker: str) -> bool:
        """Return whether a marker continues the immediately preceding body block."""
        return _clean_marker(marker) in self.continuation_markers

    def is_header(self, marker: str) -> bool:
        """Return whether a marker breaks backward paragraph attachment."""
        return _matches_any(_clean_marker(marker), self.header_patterns)

    def is_body_paragraph(self, marker: str) -> bool:
        """Return whether a marker begins an ordinary body paragraph."""
        return _matches_any(_clean_marker(marker), self.body_paragraph_patterns)

    def is_poetry_line(self, marker: str) -> bool:
        """Return whether a marker is an internal poetry line, not a stanza split."""
        return _matches_any(_clean_marker(marker), self.poetry_line_patterns)

    def to_dict(self) -> dict[str, Any]:
        """Return the normalised policy used for hashing, audit, and documentation."""
        return {
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "purpose": self.purpose,
            "section_scores": dict(sorted(self.section_scores.items())),
            "poetry_scores": dict(sorted(self.poetry_scores.items())),
            "ignored_split_headers": sorted(self.ignored_split_headers),
            "continuation_markers": sorted(self.continuation_markers),
            "header_patterns": list(self.header_patterns),
            "body_paragraph_patterns": list(self.body_paragraph_patterns),
            "poetry_line_patterns": list(self.poetry_line_patterns),
            "book_overrides": self.book_overrides,
            "scores": {
                "paragraph": self.paragraph_score,
                "chapter": self.chapter_score,
                "chapter_continuation": self.chapter_continuation_score,
                "verse": self.verse_score,
            },
            "source": str(self.source_path) if self.source_path else None,
            "source_sha256": self.source_sha256,
            "effective_sha256": self.effective_sha256,
        }


def _clean_marker(value: str) -> str:
    """Return the canonical marker token used by structure-policy matching."""
    marker = value.lstrip("+").casefold().strip()
    # USFM permits the unnumbered aliases \s and \ms for level 1.
    return {"s": "s1", "ms": "ms1"}.get(marker, marker)


def _matches_any(marker: str, patterns: Iterable[str]) -> bool:
    """Return whether the marker matches any compiled pattern in the supplied group."""
    return any(re.fullmatch(pattern, marker) is not None for pattern in patterns)


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    """Require a list of non-empty strings for one policy field."""
    if not isinstance(value, list) or not value:
        raise ConfigurationError(f"{label} must be a nonempty string list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(f"{label} must contain only nonempty strings")
        result.append(item.strip())
    return tuple(result)


def _score_map(value: Any, label: str) -> dict[str, int]:
    """Parse marker-to-score mappings and reject invalid marker or score values."""
    mapping = require_mapping(value, label)
    if not mapping:
        raise ConfigurationError(f"{label} must not be empty")
    result: dict[str, int] = {}
    for marker, raw_score in mapping.items():
        normalized = _clean_marker(str(marker))
        if not normalized:
            raise ConfigurationError(f"{label} contains an empty marker")
        if isinstance(raw_score, bool) or not isinstance(raw_score, int):
            raise ConfigurationError(f"{label}.{marker} must be an integer")
        result[normalized] = raw_score
    return result


def _integer(value: Any, label: str) -> int:
    """Require an integer policy value within the supplied inclusive bounds."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{label} must be an integer")
    return value


def _compile_patterns(patterns: Iterable[str], label: str) -> tuple[str, ...]:
    """Compile configured marker patterns once for deterministic matching."""
    compiled: list[str] = []
    for pattern in patterns:
        try:
            re.compile(rf"^(?:{pattern})$")
        except re.error as exc:
            raise ConfigurationError(f"Invalid regex in {label}: {pattern!r}: {exc}") from exc
        compiled.append(pattern)
    return tuple(compiled)


def _from_mapping(
    data: dict[str, Any],
    *,
    source_path: Path | None,
    source_sha256: str,
) -> StructurePolicy:
    """Construct and validate a complete structure policy from one YAML mapping."""
    # Validate every policy branch before constructing the immutable policy object.
    profile = require_mapping(data.get("profile"), "structure_planning.profile")
    split = require_mapping(data.get("split_markers"), "structure_planning.split_markers")
    patterns = require_mapping(data.get("marker_patterns"), "structure_planning.marker_patterns")
    scores = require_mapping(data.get("scores"), "structure_planning.scores")
    raw_overrides = data.get("book_overrides", {})
    overrides_map = require_mapping(raw_overrides, "structure_planning.book_overrides") if raw_overrides else {}

    section_scores = _score_map(split.get("section"), "structure_planning.split_markers.section")
    poetry_scores = _score_map(split.get("poetry"), "structure_planning.split_markers.poetry")
    ignored = frozenset(
        _clean_marker(item)
        for item in _string_list(
            data.get("ignored_split_headers"),
            "structure_planning.ignored_split_headers",
        )
    )
    continuation = frozenset(
        _clean_marker(item)
        for item in _string_list(
            data.get("continuation_markers"),
            "structure_planning.continuation_markers",
        )
    )
    header_patterns = _compile_patterns(
        _string_list(patterns.get("headers"), "structure_planning.marker_patterns.headers"),
        "structure_planning.marker_patterns.headers",
    )
    body_patterns = _compile_patterns(
        _string_list(
            patterns.get("body_paragraphs"),
            "structure_planning.marker_patterns.body_paragraphs",
        ),
        "structure_planning.marker_patterns.body_paragraphs",
    )
    poetry_line_patterns = _compile_patterns(
        _string_list(
            patterns.get("poetry_lines"),
            "structure_planning.marker_patterns.poetry_lines",
        ),
        "structure_planning.marker_patterns.poetry_lines",
    )

    overlap = set(section_scores) & set(poetry_scores)
    if overlap:
        raise ConfigurationError(
            "Structure markers may not be both section and poetry split markers: "
            + ", ".join(sorted(overlap))
        )
    if continuation & (set(section_scores) | set(poetry_scores) | ignored):
        raise ConfigurationError(
            "Continuation markers may not also be split markers or ignored headers"
        )
    for marker in set(section_scores) | set(poetry_scores) | ignored:
        if not _matches_any(marker, header_patterns) and marker != "b":
            raise ConfigurationError(
                f"Structural marker {marker!r} must be classified as a header or explicit break"
            )

    book_overrides: dict[str, dict[str, dict[str, int]]] = {}
    for raw_book, raw_override in overrides_map.items():
        book = str(raw_book).upper().strip()
        if not book:
            raise ConfigurationError("structure_planning.book_overrides contains an empty book code")
        override = require_mapping(raw_override, f"structure_planning.book_overrides.{book}")
        section = _score_map(override.get("section"), f"structure_planning.book_overrides.{book}.section") if override.get("section") else {}
        poetry = _score_map(override.get("poetry"), f"structure_planning.book_overrides.{book}.poetry") if override.get("poetry") else {}
        score_values = require_mapping(override.get("scores"), f"structure_planning.book_overrides.{book}.scores") if override.get("scores") else {}
        normalized_scores = {key: _integer(value, f"structure_planning.book_overrides.{book}.scores.{key}") for key, value in score_values.items()}
        unknown = set(normalized_scores) - {"chapter"}
        if unknown:
            raise ConfigurationError(f"Unsupported book override scores for {book}: {', '.join(sorted(unknown))}")
        book_overrides[book] = {"section": section, "poetry": poetry, "scores": normalized_scores}

    normalized = {
        "profile": {
            "schema_version": require_string(
                profile.get("schema_version"),
                "structure_planning.profile.schema_version",
            ),
            "id": require_string(profile.get("id"), "structure_planning.profile.id"),
            "status": require_string(
                profile.get("status"),
                "structure_planning.profile.status",
            ).upper(),
            "purpose": require_string(
                profile.get("purpose"),
                "structure_planning.profile.purpose",
            ),
        },
        "split_markers": {
            "section": dict(sorted(section_scores.items())),
            "poetry": dict(sorted(poetry_scores.items())),
        },
        "ignored_split_headers": sorted(ignored),
        "continuation_markers": sorted(continuation),
        "marker_patterns": {
            "headers": list(header_patterns),
            "body_paragraphs": list(body_patterns),
            "poetry_lines": list(poetry_line_patterns),
        },
        "book_overrides": book_overrides,
        "scores": {
            "paragraph": _integer(scores.get("paragraph"), "structure_planning.scores.paragraph"),
            "chapter": _integer(scores.get("chapter"), "structure_planning.scores.chapter"),
            "chapter_continuation": _integer(
                scores.get("chapter_continuation"),
                "structure_planning.scores.chapter_continuation",
            ),
            "verse": _integer(scores.get("verse"), "structure_planning.scores.verse"),
        },
    }
    effective_sha256 = sha256_bytes(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return StructurePolicy(
        policy_id=normalized["profile"]["id"],
        schema_version=normalized["profile"]["schema_version"],
        status=normalized["profile"]["status"],
        purpose=normalized["profile"]["purpose"],
        section_scores=section_scores,
        poetry_scores=poetry_scores,
        ignored_split_headers=ignored,
        continuation_markers=continuation,
        header_patterns=header_patterns,
        body_paragraph_patterns=body_patterns,
        poetry_line_patterns=poetry_line_patterns,
        paragraph_score=normalized["scores"]["paragraph"],
        chapter_score=normalized["scores"]["chapter"],
        chapter_continuation_score=normalized["scores"]["chapter_continuation"],
        verse_score=normalized["scores"]["verse"],
        book_overrides=book_overrides,
        source_path=source_path,
        source_sha256=source_sha256,
        effective_sha256=effective_sha256,
    )


def load_structure_policy(root: Path) -> StructurePolicy:
    """Load the package's normative structure-planning policy."""
    path = (root / "meta" / "structure-planning.yml").resolve()
    data = load_yaml(path)
    return _from_mapping(data, source_path=path, source_sha256=sha256_file(path))


def default_structure_policy() -> StructurePolicy:
    """Return the built-in policy used by direct compiler calls and fixtures."""
    data = {
        "profile": {
            "schema_version": "1.0",
            "id": "usfm-structure-planning",
            "status": "ACTIVE",
            "purpose": "Built-in SAGE structure policy",
        },
        "split_markers": {
            "section": {"ms1": 100, "ms2": 90, "s1": 80, "s2": 60},
            "poetry": {"qa": 95, "b": 70},
        },
        "ignored_split_headers": ["s3"],
        "continuation_markers": ["m"],
        "marker_patterns": {
            "headers": [
                r"ms\d*", r"mr", r"s\d*", r"sr", r"r", r"d", r"sp",
                r"sd\d*", r"mt\d*", r"mte\d*", r"imt\d*", r"imte\d*",
                r"is\d*", r"ip", r"ipi", r"im", r"imi", r"ipq", r"imq",
                r"ipr", r"iq\d*", r"iot", r"io\d*", r"iex", r"cl", r"cd",
                r"qa",
            ],
            "body_paragraphs": [
                r"p", r"po", r"pr", r"cls", r"pmo", r"pm", r"pmc", r"pmr",
                r"pi\d*", r"mi\d*", r"nb", r"pc", r"ph\d*", r"lh", r"li\d*",
                r"lf", r"lim\d*", r"tr", r"tc\d*", r"th\d*", r"tcr\d*",
                r"thr\d*", r"lit",
            ],
            "poetry_lines": [r"q\d*", r"qm\d*", r"qr", r"qc", r"qd"],
        },
        "book_overrides": {
            "PSA": {
                "section": {"cl": 110},
                "poetry": {"qa": 90, "b": 1},
                "scores": {"chapter": 110},
            }
        },
        "scores": {
            "paragraph": 30,
            "chapter": 10,
            "chapter_continuation": -20,
            "verse": 0,
        },
    }
    return _from_mapping(data, source_path=None, source_sha256="")
