#!/usr/bin/env python3
"""Measure the STC name check on a real WIP by planting known name errors (no hand labelling).

Usage::

    evaluate_name_alignment.py <paratext-project-folder> --books GEN,1CH,JHN,ACT [--per-book 60] [--seed 7]

For each book the tool takes verses where the WIP renders a name in the usual way (``OK``) and plants one
error per name, cycling through three kinds:

- ``MISSPELL``: one letter inside the name's stem substituted, deleted, or doubled;
- ``SWAP``: the name replaced by the usual rendering of another well-established name;
- ``REMOVE``: the name deleted.

It relearns the renderings on the changed text and reports, per kind, how many planted errors come back as a
candidate (``VARIANT``, ``SUBSTITUTION``, or ``ABSENT``), plus the candidates the unchanged text already
produces. STC receives only ``VARIANT`` and ``SUBSTITUTION``, so ``REMOVE`` measures the model, not
what STC sees. Only verses where the name appears once are used, so a planted error is never hidden by a second
occurrence. Misspellings after the stem look like inflection and are out of scope by design.

The project's base versification comes from its ``Settings.xml``; a ``custom.vrs`` is ignored.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import re
import sys
import unicodedata

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage import name_alignment as na  # noqa: E402
from sage.canon import NT_27, OT_39  # noqa: E402
from sage.ol_analysis import load_ol_analysis  # noqa: E402
from sage.usj import compile_usfm_text  # noqa: E402
from sage.vrs import parse_vrs_file  # noqa: E402

VERSIFICATIONS = {"1": "org", "2": "lxx", "3": "vul", "4": "eng", "5": "rsc", "6": "rso"}
KINDS = ("MISSPELL", "SWAP", "REMOVE")


def load_wip(folder: Path) -> tuple[dict[str, str], str]:
    """Every canonical verse of a Paratext project as ``{reference: text}``, and its base versification."""
    settings = next((folder / name for name in ("Settings.xml", "settings.xml") if (folder / name).is_file()), None)
    match = re.search(r"<Versification>(\d)</Versification>", settings.read_text(encoding="utf-8", errors="replace")) if settings else None
    versification = VERSIFICATIONS.get(match.group(1) if match else "4", "eng")
    verses: dict[str, str] = {}
    for path in sorted(folder.iterdir()):
        if path.suffix.upper() not in {".SFM", ".USFM"}:
            continue
        usj = compile_usfm_text(path.read_text(encoding="utf-8-sig", errors="replace"), path.name)
        book = usj["sage"]["book_code"]
        if book not in NT_27 and book not in OT_39:
            continue
        for row in usj["sage"]["verse_records"]:
            start, end = int(row["verse_start"]), int(row["verse_end"])
            reference = f"{book} {row['chapter']}:{start}" + (f"-{end}" if end != start else "")
            verses[reference] = str(row.get("body_text_exact", row.get("body_text", "")))
    return verses, versification


def name_occurrences(verses: dict[str, str], versification: str) -> tuple[dict[str, set[str]], dict[str, na.OlName]]:
    """MACULA names per WIP verse."""
    analysis = load_ol_analysis(ROOT)
    if analysis is None:
        raise SystemExit("SAGE has no original-language analysis package")
    schema = parse_vrs_file(
        ROOT / "system/resources/scripture" / f"{versification}.vrs", schema_id=versification, canonical_id="org"
    )
    by_verse: dict[tuple[str, int, int], str] = {}
    for reference in verses:
        book, _, rest = reference.partition(" ")
        chapter, _, span = rest.partition(":")
        first, _, last = span.partition("-")
        for verse in range(int(first), int(last or first) + 1):
            by_verse[(book, int(chapter), verse)] = reference

    def locate(ref):
        """MACULA verse to the WIP verses holding it."""
        local = schema.canonical_to_local(ref) or {ref}
        return [by_verse[key] for item in local if (key := (item.book, item.chapter, item.verse)) in by_verse]

    books = {reference.partition(" ")[0] for reference in verses}
    occurrences: dict[str, set[str]] = {}
    names: dict[str, na.OlName] = {}
    for family in ("HEB", "GRK"):
        found, family_names = na.wip_name_occurrences(analysis, family, books, locate)
        for reference, keys in found.items():
            occurrences.setdefault(reference, set()).update(keys)
        names.update(family_names)
    return occurrences, names


def _surface_words(text: str) -> list[tuple[int, int]]:
    """Spans of letter runs with their combining marks."""
    spans, start = [], None
    for index, char in enumerate(text + " "):
        inside = char.isalpha() or (start is not None and unicodedata.category(char).startswith("M"))
        if inside and start is None:
            start = index
        elif not inside and start is not None:
            spans.append((start, index))
            start = None
    return spans


def plant(verses: dict[str, str], model: na.NameModel, book: str, count: int, seed: int) -> tuple[dict[str, str], list[dict]]:
    """Plant up to ``count`` errors in one book, one per name."""
    rng = random.Random(f"{seed}:{book}")
    family = "HEB" if book in OT_39 else "GRK"
    strong = sorted(key for key, rendering in model.renderings.items() if rendering.strong and key.startswith(family))
    references = sorted(ref for ref in model.occurrences if ref.partition(" ")[0] == book)
    rng.shuffle(references)
    letters = sorted({char for text in list(verses.values())[:500] for char in na.fold(text) if char.isalpha()})
    changed, planted, used = dict(verses), [], set()
    for reference in references:
        if len(planted) >= count:
            break
        ok = sorted(key for key, status in model.status(reference).items() if status == "OK" and key not in used)
        if not ok:
            continue
        key, kind = rng.choice(ok), KINDS[len(planted) % len(KINDS)]
        rendering, text = model.renderings[key], verses[reference]
        hits = []
        for start, end in _surface_words(text):
            folded = na.fold(text[start:end])
            stem = next((s for s, at in zip(rendering.stems, rendering.offsets) if na.carries(folded, s, unspaced=model.unspaced, offsets=at)), None)
            if stem is not None:
                hits.append((start, end, folded, folded.find(stem), len(stem)))
        if len(hits) != 1:
            continue
        start, end, folded, offset, length = hits[0]
        if kind == "MISSPELL":
            if length < 4:
                continue
            chars = list(folded)
            index = offset + rng.randrange(1, length - 1)
            if not chars[index].isalpha():
                continue
            operation = rng.choice(("substitute", "delete", "double"))
            if operation == "substitute":
                chars[index] = rng.choice([char for char in letters if char != chars[index]])
            elif operation == "delete":
                del chars[index]
            else:
                chars.insert(index, chars[index])
            replacement = unicodedata.normalize("NFC", "".join(chars))
        elif kind == "SWAP":
            others = [other for other in strong if other not in model.occurrences[reference]]
            if not others:
                continue
            replacement = model.renderings[rng.choice(others)].forms[0][0]
        else:
            replacement = ""
        used.add(key)
        changed[reference] = text[:start] + replacement + text[end:]
        planted.append({"reference": reference, "name": key, "kind": kind, "original": text[start:end], "planted": replacement})
    return changed, planted


def evaluate(folder: Path, books: list[str], per_book: int, seed: int) -> dict:
    """Recall per error kind and book, and the unchanged text's candidate counts."""
    verses, versification = load_wip(folder)
    occurrences, names = name_occurrences(verses, versification)
    model = na.NameModel(verses, occurrences, names)
    report: dict = {"project": folder.name, "versification": versification, "unspaced": model.unspaced, "books": {}}
    for book in books:
        baseline = Counter(
            candidate.kind for candidate in model.candidates(sorted(ref for ref in model.occurrences if ref.partition(" ")[0] == book))
        )
        changed, planted = plant(verses, model, book, per_book, seed)
        relearned = na.NameModel(changed, occurrences, names)
        flagged = {
            (candidate.reference, candidate.name.key)
            for candidate in relearned.candidates(sorted({row["reference"] for row in planted}))
        }
        recall = {
            kind: {
                "planted": sum(1 for row in planted if row["kind"] == kind),
                "caught": sum(1 for row in planted if row["kind"] == kind and (row["reference"], row["name"]) in flagged),
            }
            for kind in KINDS
        }
        report["books"][book] = {"baseline_candidates": dict(baseline), "recall": recall}
    return report


def main() -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path, help="Paratext project folder")
    parser.add_argument("--books", required=True, help="comma-separated book codes")
    parser.add_argument("--per-book", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args()
    report = evaluate(args.project, [book.strip().upper() for book in args.books.split(",") if book.strip()], args.per_book, args.seed)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"{report['project']} ({report['versification']}{', unspaced script' if report['unspaced'] else ''})")
    for book, row in report["books"].items():
        recall = ", ".join(f"{kind} {value['caught']}/{value['planted']}" for kind, value in row["recall"].items())
        print(f"  {book}: recall {recall}; candidates in unchanged text {row['baseline_candidates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
