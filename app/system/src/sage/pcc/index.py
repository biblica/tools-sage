"""Phrase-index packages: build, verify and load (handover doc 13, plan D5).

A package is an immutable folder: ``MANIFEST.json`` (the ``index_manifest`` contract), ``expressions.jsonl``,
``occurrences.jsonl`` and ``CHECKSUMS.sha256``. Building is deterministic: the same SOURCE units, builder
version and curated entries give byte-identical files, which ``verify_index`` re-checks. At run time an
index is only a candidate accelerator: curated entries are re-located in the actual SOURCE, and an index
built on another edition (different content hash) marks their senses PROVISIONAL.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from . import ENGINE_VERSION
from .contracts import SCHEMA_VERSION, validate_record
from .discovery import Discovery, Seed, SourceUnit, discover
from .ids import canonical_json
from .jsonl import read_json, read_jsonl, write_json, write_jsonl
from .segment import tokenize
from .traits import WipTraits, measure_traits

MANIFEST = "MANIFEST.json"
EXPRESSIONS = "expressions.jsonl"
OCCURRENCES = "occurrences.jsonl"
CHECKSUMS = "CHECKSUMS.sha256"
PAYLOAD_FILES = (EXPRESSIONS, OCCURRENCES, MANIFEST)


def _sha(path: Path) -> str:
    """Implement sha."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_index(
    target: Path,
    units: Iterable[SourceUnit],
    *,
    index_version: str,
    corpus: Mapping[str, str],
    curated: Iterable[Seed] = (),
    notes: str = "",
) -> Discovery:
    """Write one package into the empty folder ``target`` and return the discovery behind it.

    ``corpus`` needs ``corpus_id``, ``edition``, ``language_tag``, ``content_sha256``, ``versification_id``
    and ``license_id``. Curated entries are never pruned; everything else is automatic discovery.
    """
    if target.exists() and any(target.iterdir()):
        raise ValidationError(f"Phrase index folder is not empty: {target}", code="PCC_INDEX_EXISTS",
                              next_action="Build into a new versioned folder; released indexes are never overwritten.")
    unit_list = list(units)
    traits = measure_traits(u.text for u in unit_list)
    found = discover(unit_list, source_corpus_id=corpus["corpus_id"], source_sha256=corpus["content_sha256"],
                     traits=traits, seeds=list(curated))
    write_jsonl(target / EXPRESSIONS, found.expressions, kind="expression", sort_key="expression_id")
    write_jsonl(target / OCCURRENCES, found.occurrences, kind="occurrence", sort_key="occurrence_id")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "index_version": index_version,
        "index_kind": "AUTHORIZED_REFERENCE",
        "corpora": [{**dict(corpus), "role": "PRIMARY_SOURCE"}],
        "expression_file": EXPRESSIONS,
        "occurrence_file": OCCURRENCES,
        "index_notes": f"{notes} builder={ENGINE_VERSION}".strip(),
        "expression_sha256": _sha(target / EXPRESSIONS),
        "occurrence_sha256": _sha(target / OCCURRENCES),
    }
    write_json(target / MANIFEST, manifest, kind="index_manifest")
    lines = "".join(f"{_sha(target / name)}  {name}\n" for name in PAYLOAD_FILES)
    (target / CHECKSUMS).write_text(lines, encoding="utf-8")
    return found


def verify_index(folder: Path) -> dict[str, Any]:
    """Re-check checksums, contracts and references; return the manifest. Raises on any mismatch."""
    def bad(reason: str) -> ValidationError:
        """Implement bad."""
        return ValidationError(f"Phrase index {folder.name} failed verification: {reason}",
                               code="PCC_INDEX_INVALID", details={"folder": str(folder)})
    try:
        listed = dict(line.split("  ", 1)[::-1] for line in (folder / CHECKSUMS).read_text(encoding="utf-8").splitlines())
    except (OSError, ValueError) as exc:
        raise bad(f"{CHECKSUMS} unreadable ({exc})") from exc
    for name in PAYLOAD_FILES:
        if listed.get(name) != _sha(folder / name):
            raise bad(f"checksum mismatch for {name}")
    manifest = read_json(folder / MANIFEST, kind="index_manifest")
    if manifest["expression_sha256"] != listed[EXPRESSIONS] or manifest["occurrence_sha256"] != listed[OCCURRENCES]:
        raise bad("manifest hashes disagree with the files")
    expressions = read_jsonl(folder / manifest["expression_file"], kind="expression")
    occurrences = read_jsonl(folder / manifest["occurrence_file"], kind="occurrence")
    ids = {e["expression_id"] for e in expressions}
    if len(ids) != len(expressions):
        raise bad("duplicate expression_id")
    spans = set()
    for occ in occurrences:
        if occ["expression_id"] not in ids:
            raise bad(f"occurrence {occ['occurrence_id']} references a missing expression")
        key = (occ["expression_id"], occ["source_unit_id"], occ["body_start"], occ["body_end"])
        if key in spans:
            raise bad(f"duplicate occurrence span {key}")
        spans.add(key)
    return manifest


def curated_seeds(folder: Path, traits: WipTraits, source_sha256: str,
                  rejected: frozenset[str] = frozenset()) -> tuple[list[Seed], bool]:
    """Curated entries of a verified package as seeds, and whether the index matches this SOURCE exactly.

    Discovered entries of the package are not seeds (the Run recomputes discovery from the actual
    SOURCE). Without an exact content match, curated senses are downgraded to PROVISIONAL. ``rejected`` holds
    normalized forms the Operator rejected in the core-list overlay.
    """
    manifest = verify_index(folder)
    matches = any(c["content_sha256"] == source_sha256 for c in manifest["corpora"])
    seeds: list[Seed] = []
    for expr in read_jsonl(folder / manifest["expression_file"], kind="expression"):
        if expr["origin"] != "AUTHORIZED_REFERENCE" or expr["normalized_source_form"] in rejected:
            continue
        tokens = tuple(t.norm for t in tokenize(
            expr["source_surface"], cased=traits.cased, letter_marks=traits.letter_marks, unspaced=traits.unspaced))
        if not tokens:
            continue
        senses = tuple(
            {**s, "review_state": s["review_state"] if matches else "PROVISIONAL"} for s in expr["senses"])
        seeds.append(Seed(expr["source_surface"], tokens, "AUTHORIZED_REFERENCE", expr["category"], senses))
    return seeds, matches
