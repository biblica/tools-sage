#!/usr/bin/env python3
"""Build the pinned original-language analysis package from MACULA Hebrew and Greek word data.

Subcommands:

- ``build --date YYYY-MM-DD``  write ``system/resources/ol-analysis/<date>/``: one plain UTF-8 TSV per family
  (every word or Hebrew word segment with lemma, Strong's, morphology fields, and a gloss; ``ref`` identifies
  the word), MANIFEST.json (source pins, attribution, columns, value vocabularies, counts) and CHECKSUMS.sha256.
  Plain text, not an archive: the source package may not contain nested archives;
- ``verify --date YYYY-MM-DD`` rebuild into a temporary folder and require byte-identical files.

The sources are the MACULA tables pinned in ``sage.numbers.index_build.macula.SOURCES`` (fetch them with
``tools/build_numbers_index.py fetch``). The UBS SDBH and MARBLE domain fields are never read.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.numbers.index_build.macula import SOURCES, normalized, verify_source  # noqa: E402
from sage.storage import storage_layout  # noqa: E402

COLUMNS = ("ref", "text", "lemma", "strong", "pos", "type", "tense", "voice", "mood",
           "stem", "person", "number", "gender", "case", "state", "gloss")
VOCABULARY_FIELDS = ("pos", "type", "tense", "voice", "mood", "stem", "person", "number", "gender", "case", "state")
FILES = {"GRK": "greek.tsv", "HEB": "hebrew.tsv"}
ATTRIBUTION = {
    "GRK": "MACULA Greek Linguistic Datasets, available at https://github.com/Clear-Bible/macula-greek/",
    "HEB": "MACULA Hebrew Linguistic Datasets, available at https://github.com/Clear-Bible/macula-hebrew/",
}
GLOSS_SOURCE = {
    "GRK": "Berean Interlinear gloss (MACULA `gloss`), public domain",
    "HEB": "Cherith Glosses for the Hebrew Old Testament by Andi Wu (MACULA `english`), CC BY 4.0",
}


def default_cache() -> Path:
    """MACULA sources live in the SAGE cache, never in the repository."""
    return storage_layout(ROOT).cache_root / "macula"


def _project(row: dict[str, str], family: str) -> list[str]:
    """Map one MACULA row onto the package columns."""
    if family == "GRK":
        values = {"pos": row.get("class", ""), "strong": row.get("strong", ""), "stem": "", "state": "",
                  "gloss": row.get("gloss", "")}
    else:
        values = {"pos": row.get("pos", ""), "strong": row.get("strongnumberx", ""), "tense": "", "voice": "",
                  "mood": "", "case": "", "gloss": row.get("english", "")}
    projected = {column: row.get(column, "") for column in COLUMNS}
    projected.update(values)
    projected["text"] = normalized(row.get("text"))
    projected["lemma"] = normalized(row.get("lemma"))
    return [str(projected[column] or "").replace("\t", " ").replace("\n", " ") for column in COLUMNS]


def _family_table(source: Path, family: str) -> tuple[bytes, int, dict[str, list[str]]]:
    """Return deterministic TSV bytes, the row count, and each vocabulary field's values."""
    verify_source(source, family)
    csv.field_size_limit(1 << 30)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(COLUMNS)
    count = 0
    vocabulary: dict[str, set[str]] = {field: set() for field in VOCABULARY_FIELDS}
    with source.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            values = _project(row, family)
            writer.writerow(values)
            count += 1
            for field in VOCABULARY_FIELDS:
                value = values[COLUMNS.index(field)]
                if value and not value.startswith("unknown"):
                    vocabulary[field].add(value)
    return buffer.getvalue().encode("utf-8"), count, {field: sorted(values) for field, values in vocabulary.items() if values}


def build(destination: Path, date: str, cache: Path) -> dict[str, str]:
    """Write the package into ``destination`` and return the checksum of each file."""
    destination.mkdir(parents=True, exist_ok=True)
    checksums: dict[str, str] = {}
    families: dict[str, object] = {}
    for family, file_name in FILES.items():
        source = SOURCES[family]
        data, count, vocabulary = _family_table(cache / source["file"], family)
        (destination / file_name).write_bytes(data)
        checksums[file_name] = hashlib.sha256(data).hexdigest()
        families[family] = {
            "file": file_name,
            "rows": count,
            "edition": source["edition"],
            "source_commit": source["commit"],
            "source_url": source["url"],
            "source_sha256": source["sha256"],
            "attribution": ATTRIBUTION[family],
            "gloss_source": GLOSS_SOURCE[family],
            "vocabulary": vocabulary,
        }
    manifest = {
        "schema_version": "1.0",
        "package_id": f"SAGE_OL_ANALYSIS_{date}",
        "license": "CC BY 4.0 (MACULA, (c) 2022-2024 Biblica, Inc.); see docs/advanced/projects-and-resources/THIRD-PARTY-NOTICES.md",
        "changes": "Column selection (no MACULA ids or morphology codes; ref identifies the word), NFC normalization of text and lemma; no values altered. UBS SDBH and MARBLE domain fields are not included.",
        "versification": "MACULA original-language numbering (Hebrew BHS / Greek SBLGNT); map to Western numbering through eng.vrs.",
        "columns": list(COLUMNS),
        "families": families,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (destination / "MANIFEST.json").write_bytes(manifest_bytes)
    checksums["MANIFEST.json"] = hashlib.sha256(manifest_bytes).hexdigest()
    lines = "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items()))
    (destination / "CHECKSUMS.sha256").write_text(lines, encoding="utf-8")
    return checksums


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run one subcommand."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--date", required=True, help="package date, YYYY-MM-DD")
    parser.add_argument("--cache", type=Path, default=None, help="folder holding the pinned MACULA tables")
    args = parser.parse_args(argv)
    cache = args.cache or default_cache()
    target = ROOT / "system/resources/ol-analysis" / args.date
    if args.command == "build":
        checksums = build(target, args.date, cache)
        print(json.dumps({"package": str(target), "files": checksums}, indent=2))
        return 0
    with tempfile.TemporaryDirectory() as scratch:
        build(Path(scratch), args.date, cache)
        names = sorted(path.name for path in Path(scratch).iterdir())
        same = all((target / name).read_bytes() == (Path(scratch) / name).read_bytes() for name in names)
    print("IDENTICAL" if same else "DIFFERENT")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
