"""One effective-scope decision: chapters with compile defects are left out instead of blocking a Run.

RTC and STC decide once, at plan time, which chapters of the requested scope can be analyzed. A chapter
with a defect located in it is excluded and later reported NOT_ASSESSED; the rest of the scope becomes the
Run's scope, so every later readiness check (task creation, approved-plan revalidation, Run preview)
compiles a scope that is already clean. A defect that cannot be tied to a chapter still blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .references import AnalysisScope, ScriptureScope, analysis_scope_portions, parse_analysis_scope, parse_scope
from .registry import EcosystemConfig, ProjectSpec
from .scripture import compile_project_scope, issue_chapters
from .work_units import EvidenceRecord

SCOPE_CHAPTER_COMPILE_DEFECT = "SCOPE_CHAPTER_COMPILE_DEFECT"
# Excluding chapters can only remove issues; a few rounds cover issues that appear only once a range narrows.
_MAX_ROUNDS = 3


@dataclass(frozen=True)
class ScopeDecision:
    """What the requested scope becomes once chapters with located compile defects are left out."""

    requested: AnalysisScope
    effective: AnalysisScope | None
    excluded: tuple[dict[str, Any], ...] = ()
    unlocalized: tuple[dict[str, Any], ...] = ()

    @property
    def blocked(self) -> bool:
        """Return whether the scope must still be refused as a whole."""
        return self.effective is None or bool(self.unlocalized)

    @property
    def narrowed(self) -> bool:
        """Return whether chapters were left out and the rest can still run."""
        return not self.blocked and bool(self.excluded)


def _chapter_bounds(compiled: dict[str, Any], book: str) -> tuple[dict[int, int], int]:
    """Return per-chapter last verses from the effective VRS and the book's last chapter."""
    chapter_max = {
        int(chapter): int(maximum)
        for chapter, maximum in dict(dict(compiled.get("effective_vrs") or {}).get("chapter_max") or {})
        .get(book, {})
        .items()
    }
    present = {
        int(chapter)
        for entry in compiled.get("files") or []
        if str(entry.get("book") or "") == book
        for chapter in entry.get("chapters_present") or []
    }
    return chapter_max, max(set(chapter_max) | present, default=0)


def _carve(
    portion: ScriptureScope,
    excluded: set[int],
    chapter_max: dict[int, int],
    last_chapter: int,
) -> list[ScriptureScope] | None:
    """Split one portion around excluded chapters; None when a needed chapter end is unknown."""
    book = portion.book
    if portion.start_chapter is None:
        start_chapter, end_chapter = 1, last_chapter
    else:
        start_chapter = portion.start_chapter
        end_chapter = portion.end_chapter or portion.start_chapter
    if not excluded.intersection(range(start_chapter, end_chapter + 1)):
        return [portion]
    verse_bounded = portion.start_verse is not None
    runs: list[tuple[int, int]] = []
    for chapter in range(start_chapter, end_chapter + 1):
        if chapter in excluded:
            continue
        if runs and runs[-1][1] == chapter - 1:
            runs[-1] = (runs[-1][0], chapter)
        else:
            runs.append((chapter, chapter))
    pieces: list[ScriptureScope] = []
    for first, last in runs:
        if not verse_bounded or (first != start_chapter and last != end_chapter):
            pieces.append(ScriptureScope(book=book, start_chapter=first, end_chapter=last))
            continue
        first_verse = portion.start_verse if first == start_chapter else 1
        last_verse = (portion.end_verse or portion.start_verse) if last == end_chapter else chapter_max.get(last)
        if first_verse is None or last_verse is None:
            return None
        pieces.append(
            ScriptureScope(
                book=book,
                start_chapter=first,
                start_verse=first_verse,
                end_chapter=last,
                end_verse=last_verse,
            )
        )
    return pieces


def _without_chapters(
    scope: AnalysisScope,
    excluded: set[int],
    chapter_max: dict[int, int],
    last_chapter: int,
) -> AnalysisScope | None:
    """Return the requested scope minus the excluded chapters, or None when nothing (safe) remains."""
    pieces: list[ScriptureScope] = []
    for portion in analysis_scope_portions(scope):
        carved = _carve(portion, excluded, chapter_max, last_chapter)
        if carved is None:
            return None
        pieces.extend(carved)
    if not pieces:
        return None
    return parse_analysis_scope("; ".join(piece.label() for piece in pieces))


def decide_effective_scope(
    config: EcosystemConfig,
    projects: Sequence[tuple[str, ProjectSpec]],
    scope: AnalysisScope,
) -> ScopeDecision:
    """Leave out every chapter a bound project has a located compile defect in.

    ``projects`` lists ``(role, project)`` pairs; the first is the WIP, whose effective VRS gives chapter
    ends. Only blocking ``issues`` count: warnings and VRS advisories never exclude a chapter. Statuses other
    than BLOCKED (for example NOT_GENERATED) are left to the existing readiness checks.
    """
    book = scope.book
    excluded: dict[int, list[dict[str, Any]]] = {}
    current: AnalysisScope = scope
    bounds: tuple[dict[int, int], int] | None = None
    for _ in range(_MAX_ROUNDS):
        unlocalized: list[dict[str, Any]] = []
        found: dict[int, list[dict[str, Any]]] = {}
        for index, (role, project) in enumerate(projects):
            compiled = compile_project_scope(config, project, current)
            if index == 0 and bounds is None:
                bounds = _chapter_bounds(compiled, book)
            if compiled.get("status") != "BLOCKED":
                continue
            for issue in compiled.get("issues") or []:
                row = {
                    "role": role,
                    "project_id": project.project_id,
                    "code": str(issue.get("code") or "UNKNOWN"),
                    "reference": str(issue.get("reference") or ""),
                    "message": str(issue.get("message") or ""),
                }
                chapters = issue_chapters(issue, book)
                if not chapters:
                    unlocalized.append(row)
                    continue
                for chapter in chapters:
                    found.setdefault(chapter, []).append(row)
        if unlocalized:
            return ScopeDecision(scope, None, _excluded_rows(book, excluded), tuple(unlocalized))
        if not found:
            return ScopeDecision(scope, current, _excluded_rows(book, excluded))
        for chapter, rows in found.items():
            excluded.setdefault(chapter, []).extend(rows)
        assert bounds is not None
        narrowed = _without_chapters(scope, set(excluded), *bounds)
        if narrowed is None:
            return ScopeDecision(scope, None, _excluded_rows(book, excluded))
        current = narrowed
    return ScopeDecision(
        scope,
        None,
        _excluded_rows(book, excluded),
        ({"code": "SCOPE_DECISION_UNSTABLE", "reference": scope.label(),
          "message": "Compile defects kept appearing after chapters were left out."},),
    )


def _excluded_rows(book: str, excluded: dict[int, list[dict[str, Any]]]) -> tuple[dict[str, Any], ...]:
    """Render the excluded chapters as plan rows, one per chapter."""
    return tuple(
        {
            "scope": f"{book} {chapter}",
            "code": SCOPE_CHAPTER_COMPILE_DEFECT,
            "issues": rows,
            "message": (
                f"{book} {chapter} was left out because {rows[0]['role']} {rows[0]['project_id']} has a "
                f"compile defect there ({rows[0]['code']}: {rows[0]['message']}); it was not assessed."
            ),
        }
        for chapter, rows in sorted(excluded.items())
    )


def without_excluded_chapters(
    records: Iterable[EvidenceRecord],
    excluded: Iterable[Mapping[str, Any]],
) -> tuple[EvidenceRecord, ...]:
    """Drop records of left-out chapters, so a defective chapter is never routed as boundary context."""
    chapters = {
        chapter
        for row in excluded
        if (chapter := parse_scope(str(row.get("scope") or "")).start_chapter) is not None
    }
    return tuple(record for record in records if record.chapter not in chapters)
