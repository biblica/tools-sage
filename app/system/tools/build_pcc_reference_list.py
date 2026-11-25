#!/usr/bin/env python3
"""Build a PCC reference list top-down from original-language concepts (P5b-2) for one reference text.

    build_pcc_reference_list.py --reference <Project or USFM folder> --title "NIV" --language en \\
        [--biblical-terms BiblicalTerms.xml] [--phrases phrases.txt] [--base <rl_id>[@version]] \\
        [--categories PN,BE,...] [--min-verses 3] [--dry-run] [--rebuild-check] [--show LEMMA ...] [BOOK ...]

Aligns the reference to the original language (cached under ``localdata/.system/cache/pcc-alignment``),
builds the entries and writes a new version into the Operator's store (``localdata/inputs/resources``), unless
``--dry-run``. ``--rebuild-check`` builds twice and compares the package bytes. ``--show`` prints the senses
of concepts whose label contains one of the given strings: reference wording, so local console only. The
summary is counts only. A list built from licensed text or Biblical Terms is marked ``local_only``.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.canon import NT_27, OT_39  # noqa: E402
from sage.ol_analysis import load_ol_analysis  # noqa: E402
from sage.pcc.align import AlignmentCache, cached_alignment, reference_sha256  # noqa: E402
from sage.pcc.glossary import read_biblical_term_entries  # noqa: E402
from sage.pcc.ol_resources import load_pcc_ol  # noqa: E402
from sage.pcc.phrases import read_phrases  # noqa: E402
from sage.pcc.reflist import (CHECKSUMS, ENTRIES, ReferenceListStore, new_rl_id,  # noqa: E402
                              write_reference_list)
from sage.pcc.rlbuild import (DEFAULT_MIN_VERSES, build_reference_list, concepts_from_biblical_terms,  # noqa: E402
                              concepts_from_entries, merge_inventory)
from sage.pcc.source_text import source_units  # noqa: E402
from sage.pcc.traits import measure_traits  # noqa: E402
from sage.references import parse_scope  # noqa: E402
from sage.vrs import parse_vrs_file  # noqa: E402

LOCALDATA = ROOT.parent / "localdata"


def _progress(stage: str, detail: str) -> None:
    """Progress on stderr."""
    print(f"  [{stage}] {detail}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, build, write and report."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("books", nargs="*", help="USFM book codes (default: every book of both testaments)")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--language", default="und", help="language tag of the reference")
    parser.add_argument("--edition", default="", help="edition name (default: the folder name)")
    parser.add_argument("--biblical-terms", type=Path)
    parser.add_argument("--phrases", type=Path)
    parser.add_argument("--base", help="base reference list <rl_id>[@version] in the store")
    parser.add_argument("--categories", help="Biblical Terms categories to use (default: all)")
    parser.add_argument("--min-verses", type=int, default=DEFAULT_MIN_VERSES)
    parser.add_argument("--vrs", type=Path, default=ROOT / "system/resources/scripture/eng.vrs")
    parser.add_argument("--store", type=Path, default=LOCALDATA / "inputs/resources")
    parser.add_argument("--cache", type=Path, default=LOCALDATA / ".system/cache/pcc-alignment")
    parser.add_argument("--license", default="LOCAL-REFERENCE", help="license id of the reference text")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild-check", action="store_true")
    parser.add_argument("--show", nargs="*", default=[])
    args = parser.parse_args(argv)

    started = time.monotonic()
    books = args.books or list(OT_39) + list(NT_27)
    analysis = load_ol_analysis(ROOT)
    resources = load_pcc_ol(ROOT)
    schema = parse_vrs_file(args.vrs, schema_id=args.vrs.stem, canonical_id="org")
    _progress("read", f"{len(books)} books")
    units = [u for book in books for u in source_units(args.reference, parse_scope(book))]
    traits = measure_traits(u.text for u in units)
    package_ids = [analysis.package_id, resources.package_id if resources else "-"]
    _progress("align", f"{len(units)} verses")
    alignment, cached = cached_alignment(units, analysis, schema, bsb_alignment=resources.bsb_alignment if resources else None,
                                         package_ids=package_ids, cache=AlignmentCache(args.cache), cased=traits.cased,
                                         letter_marks=traits.letter_marks)
    aligned_at = time.monotonic()

    store = ReferenceListStore(args.store)
    groups, dropped, skipped, sources = [], set(), {}, []
    if args.biblical_terms:
        terms = read_biblical_term_entries(args.biblical_terms)
        concepts, skipped = concepts_from_biblical_terms(
            terms, categories=args.categories.split(",") if args.categories else None)
        groups.append(concepts)
        sources.append("Paratext Biblical Terms (Operator-supplied, local only)")
    base = None
    if args.base:
        rl_id, _, version = args.base.partition("@")
        manifest, entries = store.load(rl_id, int(version) if version else None)
        base = {"rl_id": rl_id, "version": manifest["version"]}
        kept, dropped = concepts_from_entries(entries, f"INHERITED:{rl_id}@{manifest['version']}")
        groups.insert(0, kept)
    declared = []
    if args.phrases:
        phrases, problems = read_phrases(args.phrases, traits)
        declared = [(p.surface, p.tokens, p.line) for p in phrases]
        for problem in problems:
            print(f"phrases line {problem.line}: {problem.reason}", file=sys.stderr)
    inventory = merge_inventory(*groups)

    def build():
        """One build."""
        return build_reference_list(units, alignment, analysis, schema, traits=traits, language_tag=args.language,
                                    inventory=inventory, declared=declared, dropped=dropped,
                                    clear_senses=resources.senses if resources else None,
                                    groups=resources.groups_by_ref if resources else None,
                                    min_verses=args.min_verses, skipped=skipped, progress=_progress)

    result = build()
    built_at = time.monotonic()
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reference = {"project_id": args.reference.name, "edition": args.edition or args.reference.name,
                 "language_tag": args.language, "content_sha256": reference_sha256(units),
                 "versification_id": args.vrs.stem}
    license_ = {"license_id": args.license, "local_only": True,
                "note": "; ".join(["Reference wording from a licensed text"] + sources)}
    build_record = {"mode": "INHERIT" if base else "SCRATCH", "derived_from": base,
                    "settings": {"books": books, "min_verses": args.min_verses,
                                 "categories": args.categories.split(",") if args.categories else "ALL",
                                 "aligner": package_ids, "cased": traits.cased},
                    "summary": result.summary()}
    report = {"verses": len(units), "alignment": alignment.stats, "alignment_cached": cached,
              "seconds": {"align": round(aligned_at - started, 1), "build": round(built_at - aligned_at, 1)},
              "inventory": len(inventory), **result.summary()}
    if args.rebuild_check:
        with tempfile.TemporaryDirectory() as tmp:
            for name, res in (("a", result), ("b", build())):
                write_reference_list(Path(tmp) / name, rl_id="check-00000000", version=1, title=args.title,
                                     reference=reference, license=license_, build=build_record | {"summary": res.summary()},
                                     entries=res.entries, created_utc=created)
            report["rebuild_identical"] = all((Path(tmp) / "a" / n).read_bytes() == (Path(tmp) / "b" / n).read_bytes()
                                              for n in (ENTRIES, CHECKSUMS))
    if not args.dry_run:
        rl_id = args.base.partition("@")[0] if args.base else new_rl_id(args.title, str(LOCALDATA), created)
        manifest = store.save(rl_id=rl_id, title=args.title, reference=reference, license=license_,
                              build=build_record, entries=result.entries, created_utc=created)
        report["written"] = {"rl_id": manifest["rl_id"], "version": manifest["version"], "counts": manifest["counts"]}
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    for needle in args.show:
        for entry in result.entries:
            if needle in entry["label"]:
                print(f"\n{entry['label']} [{entry['category']}, {entry['status']}] verses={entry['verses']} "
                      f"realization={entry['realization']}")
                for sense in entry["senses"]:
                    words = ", ".join(f"{w['wording']} ({w['verses']})" for w in sense["wordings"][:8])
                    print(f"  {sense['kind']:5} {sense['label']!r:28} {sense['verses']:4}  {words}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
