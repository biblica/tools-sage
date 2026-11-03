"""PCC phase P3: phrase-index packages build deterministically and verify; the tool round-trips."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.pcc.discovery import Seed, SourceUnit
from sage.pcc.index import CHECKSUMS, EXPRESSIONS, build_index, curated_seeds, verify_index
from sage.pcc.traits import measure_traits

SHA = "c" * 64
TEXTS = ["Stand firm in the faith.", "Stand firm, brave one.", "The lamp is bright; the lamp is near."]
CORPUS = {"corpus_id": "SYN", "edition": "Synthetic", "language_tag": "en", "content_sha256": SHA,
          "versification_id": "eng", "license_id": "SYNTHETIC-PUBLIC-DOMAIN"}
SENSE = {"sense_id": "SENSE-L", "label": "illumination", "discriminator": "light from a lamp", "review_state": "CURATED"}


def _units():
    return [SourceUnit(f"u{i}", f"GEN 1:{i + 1}", (f"GEN 1:{i + 1}",), t) for i, t in enumerate(TEXTS)]


def _build(path: Path):
    return build_index(path, _units(), index_version="t-1", corpus=CORPUS,
                       curated=[Seed("lamp", ("lamp",), "AUTHORIZED_REFERENCE", "TERM", (SENSE,))])


def test_build_is_deterministic_and_verifies(tmp_path):
    _build(tmp_path / "a")
    _build(tmp_path / "b")
    for name in ("expressions.jsonl", "occurrences.jsonl", "MANIFEST.json", CHECKSUMS):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert verify_index(tmp_path / "a")["index_version"] == "t-1"


def test_never_overwrites_a_released_index(tmp_path):
    _build(tmp_path / "a")
    with pytest.raises(ValidationError) as info:
        _build(tmp_path / "a")
    assert info.value.code == "PCC_INDEX_EXISTS"


def test_tampering_is_detected(tmp_path):
    _build(tmp_path / "a")
    path = tmp_path / "a" / EXPRESSIONS
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValidationError) as info:
        verify_index(tmp_path / "a")
    assert info.value.code == "PCC_INDEX_INVALID"


def test_curated_seeds_match_or_downgrade(tmp_path):
    _build(tmp_path / "a")
    traits = measure_traits(TEXTS)
    seeds, exact = curated_seeds(tmp_path / "a", traits, SHA)
    assert exact and [s.surface for s in seeds] == ["lamp"] and seeds[0].senses[0]["review_state"] == "CURATED"
    other, exact = curated_seeds(tmp_path / "a", traits, "d" * 64)
    assert not exact and other[0].senses[0]["review_state"] == "PROVISIONAL"


def test_discovered_entries_are_not_runtime_seeds(tmp_path):
    _build(tmp_path / "a")
    rows = [json.loads(line) for line in (tmp_path / "a" / EXPRESSIONS).read_text(encoding="utf-8").splitlines()]
    assert {r["origin"] for r in rows} == {"AUTHORIZED_REFERENCE", "SOURCE_DISCOVERY"}
    seeds, _ = curated_seeds(tmp_path / "a", measure_traits(TEXTS), SHA)
    assert len(seeds) == 1
