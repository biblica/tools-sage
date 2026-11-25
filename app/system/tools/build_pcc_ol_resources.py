#!/usr/bin/env python3
"""Build the pinned PCC original-language resource package (gold BSB alignment, word senses, phrase groups).

Subcommands:

- ``fetch``  download the pinned inputs into the SAGE cache (``localdata/.system/cache``) and verify them:
  the BSB tables (bereanbible.com), the MACULA Greek and Hebrew word tables (shared with the OL analysis
  package), Clear's Greek word senses and the MACULA lowfat syntax trees (SBLGNT and WLC). Files already
  present and matching their pins are kept;
- ``build --date YYYY-MM-DD``  write ``system/resources/pcc-ol/<date>/`` (three TSV tables, MANIFEST.json,
  CHECKSUMS.sha256) and print the pin for ``system/config/pcc-ol-reference.json``;
- ``verify --date YYYY-MM-DD``  rebuild into a temporary folder and require byte-identical files.

Sources: https://github.com/Clear-Bible/macula-greek/ and https://github.com/Clear-Bible/macula-hebrew/
(CC BY 4.0, Biblica, Inc.), https://bereanbible.com/bsb_tables.xlsx (public domain). The UBS-licensed fields
are never read (see ``sage.pcc.ol_build``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.numbers.index_build.macula import SOURCES as MACULA_SOURCES  # noqa: E402
from sage.pcc.ol_build import SOURCES, build_package, git_blob_sha, listing_digest, verify_inputs  # noqa: E402
from sage.storage import storage_layout  # noqa: E402

PACKAGES = ROOT / "system/resources/pcc-ol"
USER_AGENT = "SAGE-PCC-resource-builder"


def default_cache() -> Path:
    """Inputs live in the SAGE cache, never in the repository."""
    return storage_layout(ROOT).cache_root


def _get(url: str) -> bytes:
    """Download one URL."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (pinned https URLs)
        return response.read()


def _fetch_file(path: Path, url: str, sha256: str) -> str:
    """Download ``url`` to ``path`` unless a matching copy exists; verify the SHA-256."""
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
        return "kept"
    data = _get(url)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise SystemExit(f"{url} does not match its pinned SHA-256; nothing written.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return "fetched"


def _fetch_tree(folder: Path, source: dict[str, str]) -> str:
    """Download every ``*.xml`` of a pinned git tree, verifying each file's git blob SHA."""
    if folder.is_dir() and listing_digest(folder) == source["listing_sha256"]:
        return "kept"
    tree = json.loads(_get(f"https://api.github.com/repos/{source['repo']}/git/trees/{source['tree']}"))
    folder.mkdir(parents=True, exist_ok=True)
    for entry in tree["tree"]:
        if not entry["path"].endswith(".xml"):
            continue
        target = folder / entry["path"]
        if target.is_file() and git_blob_sha(target.read_bytes()) == entry["sha"]:
            continue
        data = _get(source["url"] + entry["path"])
        if git_blob_sha(data) != entry["sha"]:
            raise SystemExit(f"{entry['path']} does not match its git blob SHA; stopped.")
        target.write_bytes(data)
    if listing_digest(folder) != source["listing_sha256"]:
        raise SystemExit(f"{folder} does not match the pinned listing after the download.")
    return "fetched"


def fetch(cache: Path) -> dict[str, str]:
    """Fetch and verify every pinned input."""
    done = {}
    for family, source in MACULA_SOURCES.items():
        done[f"macula_{family}"] = _fetch_file(cache / "macula" / source["file"], source["url"], source["sha256"])
    for name, source in SOURCES.items():
        if "file" in source:
            done[name] = _fetch_file(cache / source["file"], source["url"], source["sha256"])
        else:
            done[name] = _fetch_tree(cache / source["dir"], source)
    verify_inputs(cache)
    return done


def _pin(target: Path, date: str) -> dict[str, str]:
    """The Core pin for one built package."""
    return {"schema_version": "1.0", "package_id": f"SAGE_PCC_OL_{date}",
            "path": f"system/resources/pcc-ol/{date}",
            "sha256": hashlib.sha256((target / "CHECKSUMS.sha256").read_bytes()).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run one subcommand."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("fetch", "build", "verify"))
    parser.add_argument("--date", help="package date, YYYY-MM-DD (build, verify)")
    parser.add_argument("--cache", type=Path, default=None, help="SAGE cache folder holding the pinned inputs")
    args = parser.parse_args(argv)
    cache = args.cache or default_cache()
    if args.command == "fetch":
        print(json.dumps(fetch(cache), indent=2))
        return 0
    if not args.date:
        parser.error("--date is required for build and verify")
    target = PACKAGES / args.date
    if args.command == "build":
        if target.exists() and any(target.iterdir()):
            raise SystemExit(f"{target} is not empty; released packages are never overwritten.")
        manifest = build_package(target, args.date, cache=cache, macula_sources=MACULA_SOURCES)
        print(json.dumps({"package": str(target), "files": manifest["files"], "pin": _pin(target, args.date)},
                         indent=2, ensure_ascii=False))
        return 0
    with tempfile.TemporaryDirectory() as scratch:
        build_package(Path(scratch), args.date, cache=cache, macula_sources=MACULA_SOURCES)
        names = sorted(path.name for path in Path(scratch).iterdir())
        same = names == sorted(path.name for path in target.iterdir()) and all(
            (target / name).read_bytes() == (Path(scratch) / name).read_bytes() for name in names)
    print("IDENTICAL" if same else "DIFFERENT")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
