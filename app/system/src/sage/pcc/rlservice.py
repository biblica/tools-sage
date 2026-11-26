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
    if not units:
        from ..errors import ValidationError
        raise ValidationError(f"No verses were read from {reference_path}" + (f" for {', '.join(books)}" if books else ""),
                              code="PCC_RL_NO_TEXT",
                              next_action="Check the reference text folder and the book codes; nothing was written.")
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
    carried: dict[str, Any] = {}
    same_text = False
    if base:
        manifest, entries = store.load(base[0], base[1])
        base_entries = list(entries)
        derived = {"rl_id": base[0], "version": manifest["version"]}
        same_text = manifest["reference"]["project_id"] == project_id
        entries, carried = inheritable_entries(entries, language_tag=language_tag, same_text=same_text)
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
    if base and same_text:
        # A rebuild of the same text (for example after the text gained books) never loses a decision: the team's
        # DROP stays recorded, and a curated concept the rebuild cannot locate again (a multi-word Biblical Terms
        # phrase without its verse list, or a wording no longer in the text) is kept as it was, and reported.
        have = {e["concept_key"] for e in result.entries}
        kept_dropped, kept_unchanged = 0, []
        for entry in base_entries:
            if entry["concept_key"] in have:
                continue
            result.entries.append(entry)
            if entry["status"] == "DROPPED":
                kept_dropped += 1
            else:
                kept_unchanged.append(entry["label"])
        carried["drops_kept"] = kept_dropped
        carried["kept_unchanged"] = sorted(kept_unchanged)
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
    if carried:
        build["summary"] = {**build["summary"], "inherited": carried}
    report = {"verses": len(units), "alignment": alignment.stats, "alignment_cached": cached,
              "inventory": sum(len(g) for g in groups), "inherited": carried, **result.summary()}
    manifest = None
    if not dry_run:
        # A rebuild of the same text is the next version of its list; another text gets a list of its own.
        rl_id = rl_id or (base[0] if base and same_text else new_rl_id(title, instance_id, created))
        manifest = store.save(rl_id=rl_id, title=title, reference=reference, license=license_, build=build,
                              entries=result.entries, created_utc=created)
    return BuildOutcome(manifest, result, report | {"reference": reference, "build": build, "created": created,
                                                    "license": license_})


def inheritable_entries(entries: Sequence[dict[str, Any]], *, language_tag: str,
                        same_text: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """What a base list hands to a new build (plan P5b-5, D14 revised).

    Concepts carry by ``concept_key``; the new text's own wordings come from its own alignment. Rebuilding the
    same text keeps every status. Building **another** text from the list keeps ``DROPPED`` decisions, but a
    kept concept arrives as ``PROPOSED``: nothing derived is ``ACTIVE`` until the team reviews it in the new
    list's workbook. An Operator wording (``WORDING`` anchor, no original-language key) can only be located
    in a text of the same language; in another language it is not carried and is listed in the summary.
    """
    carried: dict[str, Any] = {"concepts": 0, "dropped": 0, "wordings_same_language": 0,
                               "wordings_other_language": []}
    kept = []
    for entry in entries:
        if entry["status"] == "DROPPED":
            carried["dropped"] += 1
            kept.append(entry)
            continue
        if entry["anchor"]["kind"] == "WORDING":
            language = entry["anchor"]["value"][0].split("|", 1)[0]
            if language.casefold() != language_tag.casefold() and not same_text:
                carried["wordings_other_language"].append(entry["label"])
                continue
            carried["wordings_same_language"] += 1
        carried["concepts"] += 1
        kept.append(entry if same_text else {**entry, "status": "PROPOSED"})
    carried["wordings_other_language"] = sorted(carried["wordings_other_language"])
    return kept, carried


def add_biblical_terms(*, app_root: Path, store: ReferenceListStore, cache_root: Path, rl_id: str,
                       version: int | None, reference_path: Path, schema: VersificationSchema, biblical_terms: Path,
                       report_folder: Path, categories: Sequence[str] | None = None,
                       progress: Callable[[str, str], None] | None = None):
    """Add the concepts of a Paratext Biblical Terms list to a reference list, as its next version.

    The terms are realized in the list's own reference text with the list's settings (books, recurrence), exactly
    as a build would. A concept already on the list is left as it is; one the team dropped stays dropped. Returns
    ``(ImportResult, BuildOutcome)``; no version is written when no new concept qualifies.
    """
    from .reflist_xlsx import ImportResult, store_changes
    manifest, entries = store.load(rl_id, version)
    settings = manifest["build"].get("settings", {})
    books = settings.get("books")
    outcome = build_reference_list_for(
        app_root=app_root, store=store, cache_root=cache_root, reference_path=reference_path,
        project_id=manifest["reference"]["project_id"], title=manifest["title"],
        language_tag=manifest["reference"]["language_tag"], schema=schema,
        versification_id=manifest["reference"]["versification_id"], books=books if isinstance(books, list) else None,
        biblical_terms=biblical_terms, categories=categories,
        min_verses=int(settings.get("min_verses", DEFAULT_MIN_VERSES)), dry_run=True, progress=progress)
    by_key = {e["concept_key"]: dict(e) for e in entries}
    result = ImportResult(None)
    for entry in outcome.result.entries:
        existing = by_key.get(entry["concept_key"])
        if existing is None:
            by_key[entry["concept_key"]] = entry
            result.added.append(entry["label"])
        elif existing["status"] == "DROPPED":
            result.problems.append(f"{entry['label']}: dropped by the team on this list; left dropped")
    from .source_text import books_label, present_books
    present = present_books(reference_path)
    if isinstance(books, list) and set(present) - set(books):
        result.problems.append(f"The list covers {books_label(books)}; the text now has {books_label(present)}. Terms were "
                               "located in the list's books only. Widen the list first: Build a new list from an "
                               "existing list, with the same text.")
    left = outcome.result.left_out
    result.problems.append(f"Left out by the build rules: {left.get('NOT_IN_REFERENCE', 0)} not in the text, "
                           f"{left.get('BELOW_RECURRENCE', 0)} not recurring, "
                           f"{left.get('NO_REALIZATION', 0) + left.get('FUNCTION_ONLY', 0)} not rendered by a wording")
    return store_changes(store, manifest, manifest["version"], by_key, result, report_folder=report_folder,
                         summary_key="biblical_terms", summary={"file": Path(biblical_terms).name}), outcome


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
