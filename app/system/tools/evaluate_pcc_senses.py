#!/usr/bin/env python3
"""Measure PCC sense evidence against the Berean Standard Bible interlinear tables (tagged data).

``bsb_tables.xlsx`` (https://bereanbible.com/bsb_tables.xlsx, public domain) gives, for every Hebrew or Greek
word, the BSB English it is rendered by. For each BSB expression occurrence the table says which Strong's
numbers it renders; the tool compares them with the lemma PCC confirmed (``SENSE-OL-LEMMA``). No hand
labelling: the truth comes from the table. Nothing is written to the repository; the table and the BSB
USFM folder stay in the local cache. Output is counts only.

    evaluate_pcc_senses.py --tables bsb_tables.xlsx --bsb <folder of engbsb *.usfm> JHN ROM GEN
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.ol_analysis import load_ol_analysis  # noqa: E402
from sage.pcc.discovery import discover  # noqa: E402
from sage.pcc.ol_evidence import ol_items_for_units  # noqa: E402
from sage.pcc.segment import tokenize  # noqa: E402
from sage.pcc.sense import DEFAULT_WINDOW, assign_senses  # noqa: E402
from sage.pcc.source_text import source_units  # noqa: E402
from sage.pcc.traits import measure_traits  # noqa: E402
from sage.references import parse_scope, resolve_book  # noqa: E402
from sage.vrs import parse_vrs_file  # noqa: E402


def _digits(value: object) -> str | None:
    """Implement digits."""
    match = re.match(r"\D*(\d+)", str(value)) if value not in (None, "") else None
    return match.group(1) if match else None


def read_tables(path: Path, books: set[str]) -> dict[tuple[str, int, int], list[tuple[str | None, str]]]:
    """(book, chapter, verse) -> [(Strong's number, BSB English chunk)] in table order."""
    import openpyxl
    sheet = openpyxl.load_workbook(path, read_only=True)["biblosinterlinear96"]
    rows: dict[tuple[str, int, int], list[tuple[str | None, str]]] = defaultdict(list)
    book = chapter = verse = None
    for index, row in enumerate(sheet.iter_rows(values_only=True)):
        if index == 0:
            continue
        language, heb, grk, verse_id, english = row[4], row[10], row[11], row[12], row[18]
        if verse_id:
            match = re.match(r"(.+?) (\d+):(\d+)$", str(verse_id).strip())
            if match:
                try:
                    book = resolve_book(match[1])
                except Exception:
                    book = None
                chapter, verse = int(match[2]), int(match[3])
        if book in books and chapter is not None:
            rows[(book, chapter, verse)].append((_digits(grk if language == "Greek" else heb), str(english or "")))
    return rows


def evaluate(tables: Path, bsb: Path, books: list[str], window: float | None) -> Counter:
    """Implement evaluate."""
    rows = read_tables(tables, set(books))
    analysis = load_ol_analysis(ROOT)
    schema = parse_vrs_file(ROOT / "system/resources/scripture/eng.vrs", schema_id="eng", canonical_id="org")
    total: Counter = Counter()
    for book in books:
        units = source_units(bsb, parse_scope(book))
        traits = measure_traits(u.text for u in units)
        found = discover(units, source_corpus_id="BSB", source_sha256="0" * 64, traits=traits)
        result = assign_senses(found.expressions, found.occurrences, ol_items_for_units(units, analysis, schema), window=window,
                               unit_lengths={u.unit_id: len(u.text) for u in units})
        wanted = {e["expression_id"]: e["normalized_source_form"].split(" ") for e in result.expressions}
        stream = {key: [(t.norm, strong) for strong, english in chunks
                        for t in tokenize(english, cased=traits.cased, letter_marks=traits.letter_marks)]
                  for key, chunks in rows.items() if key[0] == book}
        seen: Counter = Counter()
        for occ in sorted(result.occurrences, key=lambda o: (o["source_unit_id"], o["body_start"])):
            if len(occ["native_refs"]) != 1:
                continue
            name, cv = occ["canonical_ref"].split(" ")
            chapter, verse = cv.split(":")
            key = (name, int(chapter), int(verse))
            n = len(wanted[occ["expression_id"]])
            nth = seen[(occ["expression_id"], key)]
            seen[(occ["expression_id"], key)] += 1
            tokens = stream.get(key, [])
            hits = [i for i in range(len(tokens) - n + 1)
                    if [t[0] for t in tokens[i:i + n]] == wanted[occ["expression_id"]]]
            total["occurrences"] += 1
            if nth >= len(hits):
                total["untraceable"] += 1
                continue
            truth = {t[1] for t in tokens[hits[nth]:hits[nth] + n] if t[1]}
            total["traceable"] += 1
            if occ["sense_state"] != "CONFIRMED":
                total["unresolved"] += 1
                continue
            total["confirmed"] += 1
            assigned = _digits(occ["sense_evidence"][0].split("|")[-1])
            total["correct" if assigned in truth else ("no_truth" if not truth else "wrong")] += 1
    return total


def main(argv: list[str] | None = None) -> int:
    """Implement main."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("books", nargs="+")
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--bsb", type=Path, required=True)
    parser.add_argument("--window", default=str(DEFAULT_WINDOW), help="relative position window, or 'none'")
    args = parser.parse_args(argv)
    window = None if args.window == "none" else float(args.window)
    total = evaluate(args.tables, args.bsb, args.books, window)
    judged = total["confirmed"] - total["no_truth"]
    print(json.dumps(dict(total), sort_keys=True))
    print(f"precision of CONFIRMED senses: {100 * total['correct'] / max(judged, 1):.1f}% ({total['correct']}/{judged})")
    print(f"confirmed share of traceable occurrences: {100 * total['confirmed'] / max(total['traceable'], 1):.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
