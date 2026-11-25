#!/usr/bin/env python3
"""Measure the PCC forward check (P6-8) on real texts: planted-error recall per kind and review workload.

    evaluate_pcc_check.py --source <SOURCE Project> --wip <WIP Project> [--biblical-terms BT.xml] \\
        [--samples 300] [--seed 0] BOOK ...

Builds the SOURCE reference list in memory (shared alignment cache), locates it in the scope (P5b-3), pairs
SOURCE and WIP verses, trains the SOURCE <-> WIP model on every pair and runs the check with no glossary
(every group is learned-only). Planted errors are the Run's own self-qualification with ``--samples`` cases
per kind. Output is counts only: no SOURCE or WIP text is printed. Nothing is written except the caches.
Both texts use ``eng.vrs`` unless ``--vrs`` / ``--wip-vrs`` say otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.ol_analysis import load_ol_analysis  # noqa: E402
from sage.pcc import check as pcc_check  # noqa: E402
from sage.pcc.align import cached_alignment  # noqa: E402
from sage.pcc.check_run import testament_of  # noqa: E402
from sage.pcc.check import (CheckInput, Morphology, pair_verses, run_check, side_tokens, stop_forms,  # noqa: E402
                            train_pair_model)
from sage.pcc.ol_resources import load_pcc_ol  # noqa: E402
from sage.pcc.reflist import ReferenceListStore  # noqa: E402
from sage.pcc.rlbuild import build_context  # noqa: E402
from sage.pcc.rlservice import alignment_cache, build_reference_list_for  # noqa: E402
from sage.pcc.rlterms import terms_from_reference_list  # noqa: E402
from sage.pcc.source_text import reference_units, source_content_sha256  # noqa: E402
from sage.pcc.traits import measure_traits  # noqa: E402
from sage.vrs import parse_vrs_file  # noqa: E402

LOCALDATA = ROOT.parent / "localdata"


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run and print counts."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("books", nargs="+")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--wip", type=Path, required=True)
    parser.add_argument("--biblical-terms", type=Path)
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--vrs", type=Path, default=ROOT / "system/resources/scripture/eng.vrs")
    parser.add_argument("--wip-vrs", type=Path)
    parser.add_argument("--cache", type=Path, default=LOCALDATA / ".system/cache")
    args = parser.parse_args(argv)
    started = time.monotonic()
    schema = parse_vrs_file(args.vrs, schema_id=args.vrs.stem, canonical_id="org")
    wip_schema = parse_vrs_file(args.wip_vrs, schema_id=args.wip_vrs.stem, canonical_id="org") if args.wip_vrs else schema
    with __import__("tempfile").TemporaryDirectory() as tmp:
        outcome = build_reference_list_for(
            app_root=ROOT, store=ReferenceListStore(Path(tmp)), cache_root=args.cache, reference_path=args.source,
            project_id=args.source.name, title="eval", language_tag="und", schema=schema, versification_id=args.vrs.stem,
            biblical_terms=args.biblical_terms, dry_run=True)
    analysis, resources = load_ol_analysis(ROOT), load_pcc_ol(ROOT)
    source_units = reference_units(args.source)
    straits = measure_traits(u.text for u in source_units)
    alignment, _ = cached_alignment(source_units, analysis, schema, bsb_alignment=resources.bsb_alignment,
                                    package_ids=[analysis.package_id, resources.package_id],
                                    cache=alignment_cache(args.cache), cased=straits.cased, letter_marks=straits.letter_marks)
    settings = outcome.report["build"]["settings"]
    ctx = build_context(source_units, alignment, analysis, schema, suffixes=settings["suffixes"], cased=settings["cased"],
                        groups=resources.groups_by_ref)
    scope = [u.unit_id for u in source_units if u.canonical_ref.split(" ")[0] in args.books]
    manifest = {"rl_id": "eval-00000000", "version": 1, "reference": outcome.report["reference"]}
    terms = terms_from_reference_list(ctx, scope_units=scope, manifest=manifest, entries=outcome.result.entries,
                                      source_corpus_id=args.source.name, source_sha256=source_content_sha256(args.source))
    wip_units = reference_units(args.wip)
    wtraits = measure_traits(u.text for u in wip_units)
    pairs, unit_pair = pair_verses(source_units, wip_units, schema, wip_schema)
    s_map, t_map = {u.unit_id: u for u in source_units}, {u.unit_id: u for u in wip_units}
    s_side = side_tokens(pairs, s_map, "source", cased=straits.cased, letter_marks=straits.letter_marks)
    t_side = side_tokens(pairs, t_map, "target", cased=wtraits.cased, letter_marks=wtraits.letter_marks,
                         unspaced=wtraits.unspaced)
    trained = time.monotonic()
    testaments = {testament_of(f"{b} 1:1") for b in args.books}
    model = train_pair_model([p for p in pairs if testament_of(s_map[p.source[0]].canonical_ref) in testaments],
                             s_side, t_side)
    trained = round(time.monotonic() - trained, 1)
    pcc_check.QUALIFY_SAMPLES = args.samples
    inp = CheckInput("EVAL", "e" * 64, s_map, t_map, pairs, unit_pair, s_side, t_side, model,
                     Morphology.from_traits(wtraits), terms.expressions, terms.occurrences, terms.groups, {},
                     stop_forms(t_side), stop_forms(s_side))
    result = run_check(inp, seed=args.seed)
    verses = len(scope)
    statuses = Counter(e.status for evs in result.evidence.values() for e in evs)
    report = {
        "wip": args.wip.name, "books": args.books, "verses_in_scope": verses, "pairs": len(pairs),
        "pair_kinds": dict(Counter(p.kind for p in pairs)), "wip_unspaced": wtraits.unspaced,
        "groups_compared": len(result.outcomes), "outcomes": dict(sorted(Counter(result.outcomes.values()).items())),
        "occurrence_status": dict(sorted(statuses.items())),
        "findings_per_1000_verses": {c: round(1000 * n / max(verses, 1), 1)
                                     for c, n in sorted(Counter(f["code"] for f in result.findings).items())},
        "qualification": result.qualification, "model_seconds": trained,
        "seconds": round(time.monotonic() - started, 1),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
