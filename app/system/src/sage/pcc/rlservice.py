"""Build and store a reference list for one reference text (P5b-2/P5b-3 service, used by the tool and the menu).

The reference is read in canonical book order (``source_text.reference_units``) and aligned through the shared
cache, so a terms Run on the same text reuses the alignment. The list records what a Run needs to match its
senses again: the learned suffixes, whether the text is cased, and the reference's content hash.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..ol_analysis import load_ol_analysis
from ..vrs import VersificationSchema
from .align import AlignmentCache, cached_alignment
from .glossary import read_biblical_term_entries
from .ol_resources import load_pcc_ol
from .phrases import read_phrases
from .reflist import ReferenceListStore, new_rl_id
from .rlbuild import (DEFAULT_MIN_VERSES, BuildResult, build_reference_list, concepts_from_biblical_terms,
                      concepts_from_entries, merge_inventory)
from .source_text import reference_units, source_content_sha256
from .traits import measure_traits

CACHE_FOLDER = "pcc-alignment"


@dataclass
class BuildOutcome:
    """The stored manifest (None on a dry run), the build result and timing/alignment facts."""

    manifest: dict[str, Any] | None
    result: BuildResult
    report: dict[str, Any]


def alignment_cache(cache_root: Path) -> AlignmentCache:
    """The shared PCC alignment cache under SAGE's cache root."""
    return AlignmentCache(Path(cache_root) / CACHE_FOLDER)


def build_reference_list_for(
    *,
    app_root: Path,
    store: ReferenceListStore,
    cache_root: Path,
    reference_path: Path,
    project_id: str,
    title: str,
    language_tag: str,
    schema: VersificationSchema,
    versification_id: str,
    books: Sequence[str] | None = None,
    biblical_terms: Path | None = None,
    phrases: Path | None = None,
    base: tuple[str, int | None] | None = None,
    categories: Sequence[str] | None = None,
    min_verses: int = DEFAULT_MIN_VERSES,
    license_id: str = "LOCAL-REFERENCE",
    rl_id: str | None = None,
    instance_id: str = "",
    dry_run: bool = False,
    progress: Callable[[str, str], None] | None = None,
) -> BuildOutcome:
    """Align, build and (unless ``dry_run``) store a new version; ``base`` = (rl_id, version or newest)."""
    note = progress or (lambda stage, detail: None)
    analysis = load_ol_analysis(app_root)
    resources = load_pcc_ol(app_root)
    note("read", str(reference_path))
    units = reference_units(reference_path, list(books) if books else None)
    traits = measure_traits(u.text for u in units)
    package_ids = [analysis.package_id, resources.package_id if resources else "-"]
    note("align", f"{len(units)} verses")
    alignment, cached = cached_alignment(
        units, analysis, schema, bsb_alignment=resources.bsb_alignment if resources else None,
        package_ids=package_ids, cache=alignment_cache(cache_root), cased=traits.cased,
        letter_marks=traits.letter_marks)
    groups, dropped, skipped, sources = [], set(), {}, []
    if biblical_terms:
        concepts, skipped = concepts_from_biblical_terms(read_biblical_term_entries(biblical_terms),
                                                         categories=categories)
        groups.append(concepts)
        sources.append("Paratext Biblical Terms (Operator-supplied, local only)")
    derived = None
    if base:
        manifest, entries = store.load(base[0], base[1])
        derived = {"rl_id": base[0], "version": manifest["version"]}
        kept, dropped = concepts_from_entries(entries, f"INHERITED:{base[0]}@{manifest['version']}")
        groups.insert(0, kept)
    declared, phrase_problems = [], []
    if phrases:
        lines, problems = read_phrases(phrases, traits)
        declared = [(p.surface, p.tokens, p.line) for p in lines]
        phrase_problems = [f"line {p.line}: {p.reason}" for p in problems]
    result = build_reference_list(
        units, alignment, analysis, schema, traits=traits, language_tag=language_tag,
        inventory=merge_inventory(*groups), declared=declared, dropped=dropped,
        clear_senses=resources.senses if resources else None, groups=resources.groups_by_ref if resources else None,
        min_verses=min_verses, skipped=skipped, progress=progress)
    result.declared_problems = phrase_problems + result.declared_problems
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reference = {"project_id": project_id, "edition": project_id, "language_tag": language_tag,
                 "content_sha256": source_content_sha256(reference_path), "versification_id": versification_id}
    license_ = {"license_id": license_id, "local_only": True,
                "note": "; ".join(["Reference wording from the Operator's own text"] + sources)}
    build = {"mode": "INHERIT" if derived else "SCRATCH", "derived_from": derived,
             "settings": {"books": list(dict.fromkeys(u.canonical_ref.split(" ")[0] for u in units)),
                          "min_verses": min_verses, "categories": list(categories) if categories else "ALL",
                          "aligner": package_ids, "cased": traits.cased,
                          "suffixes": [a.form for a in traits.suffixes]},
             "summary": result.summary()}
    report = {"verses": len(units), "alignment": alignment.stats, "alignment_cached": cached,
              "inventory": sum(len(g) for g in groups), **result.summary()}
    manifest = None
    if not dry_run:
        rl_id = rl_id or (base[0] if base else new_rl_id(title, instance_id, created))
        manifest = store.save(rl_id=rl_id, title=title, reference=reference, license=license_, build=build,
                              entries=result.entries, created_utc=created)
    return BuildOutcome(manifest, result, report | {"reference": reference, "build": build, "created": created,
                                                    "license": license_})


def reference_context(*, app_root: Path, cache_root: Path, reference_path: Path, schema: VersificationSchema,
                      settings: dict[str, Any] | None = None):
    """The ``BuildContext`` of a reference text (aligned through the shared cache), e.g. to locate NEW rows."""
    from .rlbuild import build_context
    analysis = load_ol_analysis(app_root)
    resources = load_pcc_ol(app_root)
    units = reference_units(reference_path)
    traits = measure_traits(u.text for u in units)
    alignment, _ = cached_alignment(
        units, analysis, schema, bsb_alignment=resources.bsb_alignment if resources else None,
        package_ids=[analysis.package_id, resources.package_id if resources else "-"],
        cache=alignment_cache(cache_root), cased=traits.cased, letter_marks=traits.letter_marks)
    settings = settings or {}
    return build_context(units, alignment, analysis, schema,
                         suffixes=settings.get("suffixes", [a.form for a in traits.suffixes]),
                         cased=settings.get("cased", traits.cased),
                         groups=resources.groups_by_ref if resources else None)
