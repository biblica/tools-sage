#!/usr/bin/env python3
"""Build or verify a PCC phrase-index package from a local Scripture Project folder.

- ``build``   write ``--out`` (a new, empty folder): expressions.jsonl, occurrences.jsonl, MANIFEST.json,
  CHECKSUMS.sha256. Optional ``--curated`` is a JSONL file of ``{"surface", "category", "senses"}`` entries
  that are never pruned.
- ``verify``  check a package's checksums and contracts; with ``--project-path`` also rebuild it from that
  Project and require byte-identical files.

Publicly shipped packages may contain only public-domain SOURCE text (BSB). Any other edition (NIV, ...) is
built locally under ``localdata/inputs/resources/phrase-index/<id>`` and never committed.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.hashing import sha256_paths  # noqa: E402
from sage.pcc.discovery import Seed, SourceUnit  # noqa: E402
from sage.pcc.index import EXPRESSIONS, MANIFEST, OCCURRENCES, build_index, curated_seeds, verify_index  # noqa: E402
from sage.pcc.jsonl import read_jsonl  # noqa: E402
from sage.pcc.segment import tokenize  # noqa: E402
from sage.pcc.traits import measure_traits  # noqa: E402
from sage.pcc.source_text import _book_files, source_units_for_project  # noqa: E402


def _units(path: Path) -> tuple[list[SourceUnit], str]:
    """Implement units."""
    files = _book_files(path)
    if not files:
        raise SystemExit(f"No Scripture files in {path}")
    return source_units_for_project(path), sha256_paths(files, relative_to=path)


def _curated(path: Path | None, units: list[SourceUnit]) -> list[Seed]:
    """Implement curated."""
    if path is None:
        return []
    traits = measure_traits(u.text for u in units)
    seeds = []
    for entry in read_jsonl(path):
        tokens = tuple(t.norm for t in tokenize(entry["surface"], cased=traits.cased,
                                                letter_marks=traits.letter_marks, unspaced=traits.unspaced))
        seeds.append(Seed(entry["surface"], tokens, "AUTHORIZED_REFERENCE", entry.get("category", "FIXED_PHRASE"),
                          tuple(entry.get("senses", ()))))
    return seeds


def cmd_build(args: argparse.Namespace) -> int:
    """Implement cmd build."""
    units, sha = _units(args.project_path)
    corpus = {"corpus_id": args.corpus_id, "edition": args.edition, "language_tag": args.language,
              "content_sha256": sha, "versification_id": args.versification, "license_id": args.license}
    found = build_index(args.out, units, index_version=args.index_version, corpus=corpus,
                        curated=_curated(args.curated, units), notes=args.notes)
    print(f"Built {args.out}: {len(found.expressions)} expressions, {len(found.occurrences)} occurrences")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Implement cmd verify."""
    manifest = verify_index(args.folder)
    print(f"{args.folder.name}: checksums and contracts OK ({manifest['index_version']})")
    if args.project_path is None:
        return 0
    units, sha = _units(args.project_path)
    corpus = dict(manifest["corpora"][0])
    corpus.pop("role", None)
    if corpus["content_sha256"] != sha:
        print("SOURCE content hash differs from the package; cannot rebuild identically.")
        return 1
    curated, _ = curated_seeds(args.folder, measure_traits(u.text for u in units), sha)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "rebuild"
        build_index(out, units, index_version=manifest["index_version"], corpus=corpus,
                    curated=curated, notes=re.sub(r"\s*builder=\S+$", "", manifest.get("index_notes", "")))
        for name in (EXPRESSIONS, OCCURRENCES, MANIFEST):
            if (out / name).read_bytes() != (args.folder / name).read_bytes():
                print(f"NOT byte-identical: {name}")
                return 1
    print("Rebuild is byte-identical.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Implement main."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--project-path", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--index-version", required=True)
    build.add_argument("--corpus-id", required=True)
    build.add_argument("--edition", required=True)
    build.add_argument("--language", required=True)
    build.add_argument("--license", required=True)
    build.add_argument("--versification", default="eng")
    build.add_argument("--curated", type=Path)
    build.add_argument("--notes", default="")
    build.set_defaults(func=cmd_build)
    verify = sub.add_parser("verify")
    verify.add_argument("folder", type=Path)
    verify.add_argument("--project-path", type=Path)
    verify.set_defaults(func=cmd_verify)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
