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
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.pcc.reflist import CHECKSUMS, ENTRIES, ReferenceListStore, write_reference_list  # noqa: E402
from sage.pcc.rlbuild import DEFAULT_MIN_VERSES  # noqa: E402
from sage.pcc.rlservice import build_reference_list_for  # noqa: E402
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
    parser.add_argument("--cache", type=Path, default=LOCALDATA / ".system/cache/pcc-alignment",
                        help="alignment cache folder (must be named pcc-alignment)")
    parser.add_argument("--license", default="LOCAL-REFERENCE", help="license id of the reference text")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild-check", action="store_true")
    parser.add_argument("--show", nargs="*", default=[])
    args = parser.parse_args(argv)

    started = time.monotonic()
    base = None
    if args.base:
        rl_id, _, version = args.base.partition("@")
        base = (rl_id, int(version) if version else None)
    store = ReferenceListStore(args.store)

    def build(dry_run: bool):
        """One build."""
        return build_reference_list_for(
            app_root=ROOT, store=store, cache_root=args.cache.parent, reference_path=args.reference,
            project_id=args.edition or args.reference.name, title=args.title, language_tag=args.language,
            schema=parse_vrs_file(args.vrs, schema_id=args.vrs.stem, canonical_id="org"),
            versification_id=args.vrs.stem, books=args.books or None, biblical_terms=args.biblical_terms,
            phrases=args.phrases, base=base, categories=args.categories.split(",") if args.categories else None,
            min_verses=args.min_verses, license_id=args.license, instance_id=str(LOCALDATA), dry_run=dry_run,
            progress=_progress)

    outcome = build(args.dry_run)
    result, report = outcome.result, dict(outcome.report)
    report["seconds"] = round(time.monotonic() - started, 1)
    if args.rebuild_check:
        again = build(True)
        with tempfile.TemporaryDirectory() as tmp:
            for name, res in (("a", result), ("b", again.result)):
                write_reference_list(Path(tmp) / name, rl_id="check-00000000", version=1, title=args.title,
                                     reference=report["reference"], license=report["license"],
                                     build=report["build"] | {"summary": res.summary()}, entries=res.entries,
                                     created_utc=report["created"])
            report["rebuild_identical"] = all((Path(tmp) / "a" / n).read_bytes() == (Path(tmp) / "b" / n).read_bytes()
                                              for n in (ENTRIES, CHECKSUMS))
    for key in ("reference", "build", "created", "license"):
        report.pop(key, None)
    if outcome.manifest:
        report["written"] = {"rl_id": outcome.manifest["rl_id"], "version": outcome.manifest["version"],
                             "counts": outcome.manifest["counts"]}
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
