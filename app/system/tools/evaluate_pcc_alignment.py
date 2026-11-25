#!/usr/bin/env python3
"""Measure PCC word alignment (P5b-0) against the gold BSB alignment, or report coverage for any reference.

    evaluate_pcc_alignment.py --reference <BSB folder or Project> [BOOK ...]
    evaluate_pcc_alignment.py --reference <NIV Project> --coverage-only [BOOK ...]

With a BSB reference, the through-BSB path reproduces the BSB tables' alignment (``gold`` verses); the
direct path (Model 1 both ways) is then scored against it per testament on content words (noun, verb,
adjective): **word coverage** (content words at least one of whose BSB tokens the direct path links to them),
token **coverage** (gold content tokens linked at all) and **precision** (linked tokens that point at the same
MACULA word). With ``--coverage-only`` (any reference, e.g. NIV) the tool reports how many tokens each
method links and, where the through-BSB and direct paths both link a token, how often they agree.
Output is counts only; no Scripture text is printed. Nothing is written.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.canon import NT_27, OT_39  # noqa: E402
from sage.ol_analysis import load_ol_analysis  # noqa: E402
from sage.pcc.align import (DEFAULT_LAMBDA, DEFAULT_THRESHOLD, align_direct, align_via_bsb, bsb_index,  # noqa: E402
                            ol_tokens_for_units, train_direct)
from sage.pcc.ol_resources import load_pcc_ol  # noqa: E402
from sage.pcc.segment import tokenize  # noqa: E402
from sage.pcc.source_text import source_units  # noqa: E402
from sage.references import parse_scope  # noqa: E402
from sage.vrs import parse_vrs_file  # noqa: E402

CONTENT_POS = {"noun", "verb", "adjective", "adj"}


def evaluate(reference: Path, books: list[str], *, coverage_only: bool, lam: float, threshold: float) -> dict:
    """Run both paths over ``books`` and count."""
    analysis = load_ol_analysis(ROOT)
    resources = load_pcc_ol(ROOT)
    schema = parse_vrs_file(ROOT / "system/resources/scripture/eng.vrs", schema_id="eng", canonical_id="org")
    units = [u for book in books for u in source_units(reference, parse_scope(book))]
    tokens = {u.unit_id: tokenize(u.text) for u in units}
    ol = ol_tokens_for_units(units, analysis, schema)
    via = align_via_bsb(units, tokens, bsb_index(resources.bsb_alignment))
    direct = align_direct(tokens, ol, train_direct(tokens, ol), lam=lam, threshold=threshold)
    testament = {u.unit_id: "NT" if u.canonical_ref.split(" ")[0] in NT_27 else "OT" for u in units}
    out: dict[str, Counter] = {"NT": Counter(), "OT": Counter()}
    if coverage_only:
        for unit in units:
            c = out[testament[unit.unit_id]]
            mine_via = {l.token: l.ol_ref for l in via.get(unit.unit_id, ())}
            mine_direct = {l.token: l.ol_ref for l in direct.get(unit.unit_id, ())}
            c["tokens"] += len(tokens[unit.unit_id])
            c["via_bsb"] += len(mine_via)
            c["direct"] += len(mine_direct)
            c["either"] += len(set(mine_via) | set(mine_direct))
            both = set(mine_via) & set(mine_direct)
            c["both"] += len(both)
            c["both_agree"] += sum(1 for i in both if mine_via[i] == mine_direct[i])
        return {k: dict(v) for k, v in out.items() if v}
    content = {}
    for family in ("GRK", "HEB"):
        for words in analysis.verses(family).values():
            for word in words:
                content[word.word_id] = any((s.get("pos") or "") in CONTENT_POS for s in word.segments)
    for unit in units:
        c = out[testament[unit.unit_id]]
        gold = [l for l in via.get(unit.unit_id, ()) if l.method == "gold"]
        c["units"] += 1
        c["gold_units"] += bool(gold)
        predicted = {l.token: l.ol_ref for l in direct.get(unit.unit_id, ())}
        words: dict[str, bool] = {}
        for link in gold:
            if not content.get(link.ol_ref):
                continue
            c["gold_content_tokens"] += 1
            words.setdefault(link.ol_ref, False)
            if link.token in predicted:
                c["linked"] += 1
                c["correct"] += predicted[link.token] == link.ol_ref
                words[link.ol_ref] |= predicted[link.token] == link.ol_ref
        c["content_words"] += len(words)
        c["content_words_found"] += sum(words.values())
    result = {}
    for name, c in out.items():
        if c["units"]:
            result[name] = {**dict(c),
                            "coverage_pct": round(100 * c["linked"] / max(c["gold_content_tokens"], 1), 1),
                            "word_coverage_pct": round(100 * c["content_words_found"] / max(c["content_words"], 1), 1),
                            "precision_pct": round(100 * c["correct"] / max(c["linked"], 1), 1)}
    return result


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and print the counts."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("books", nargs="*", help="USFM book codes (default: every book of both testaments)")
    parser.add_argument("--reference", type=Path, required=True, help="eBible USFM folder or Paratext Project")
    parser.add_argument("--coverage-only", action="store_true", help="no gold: report coverage and agreement")
    parser.add_argument("--lam", type=float, default=DEFAULT_LAMBDA)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)
    books = args.books or list(OT_39) + list(NT_27)
    print(json.dumps(evaluate(args.reference, books, coverage_only=args.coverage_only, lam=args.lam,
                              threshold=args.threshold), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
