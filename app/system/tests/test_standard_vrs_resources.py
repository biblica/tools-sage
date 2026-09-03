"""Bundled standard-versification compatibility and provenance tests."""

from __future__ import annotations

import json
from pathlib import Path

from sage.hashing import sha256_file
from sage.registry import load_ecosystem
from sage.vrs import VerseRef, parse_vrs_file


SHIPPED_SHA256 = {
    "eng.vrs": "003981c7f43c69b73b60d40a3f35f72e7ee017a686a6fb206f19a1b721157541",
    "org.vrs": "9ae11065dda573a9ac9a16c331867ea6c39e94b89a4bcffb5dce280d45364391",
    "lxx.vrs": "f7c7bd6e0e5a536b6ec924bfb5f19596bc21af5bee268f97dd51d0845328cc1f",
    "vul.vrs": "f3312f4f0ffcbf48a43a20f88212a64b070b100b2764d912481c5e481a015c51",
    "rsc.vrs": "10beba712a98f9175268b770c24193897a1e6cdc0e5f2bb413423a839781471a",
    "rso.vrs": "36dd088244fc5b41fa8f3d0dcce58412e3b944c9bdc8bbce818abdfb03df3072",
}


def test_all_registered_standard_vrs_resources_parse(package_root: Path) -> None:
    """A registered standard must exist, retain its bytes, and parse completely."""
    config = load_ecosystem(package_root / "ecosystem.yml")
    resource_root = package_root / "system" / "resources" / "scripture"

    assert set(config.base_vrs_files) == set(SHIPPED_SHA256)
    schemas = {}
    for filename, expected_hash in SHIPPED_SHA256.items():
        path = resource_root / filename
        assert sha256_file(path) == expected_hash
        schemas[filename] = parse_vrs_file(
            path,
            schema_id=filename,
            canonical_id="org.vrs",
            source_label=f"base:{filename}",
        )
        assert len(schemas[filename].to_dict()["effective_sha256"]) == 64

    lxx = schemas["lxx.vrs"]
    assert lxx.chapter_limit("PSA", 151) == 7
    assert len(lxx.exclusions) == 304
    assert len(lxx.verse_segments) == 74
    assert lxx.verse_segments[VerseRef("EXO", 28, 29)] == ("", "a")
    assert schemas["vul.vrs"].chapter_limit("1CH", 11) == 46
    assert schemas["vul.vrs"].local_to_canonical(VerseRef("DAG", 3, 52)) >= {
        VerseRef("S3Y", 1, 30)
    }
    assert schemas["rsc.vrs"].chapter_limit("1CH", 6) == 81
    assert schemas["rso.vrs"].chapter_limit("1CH", 6) == 81


def test_standard_vrs_provenance_matches_shipped_resources(package_root: Path) -> None:
    """The machine provenance manifest must account for every shipped standard."""
    resource_root = package_root / "system" / "resources" / "scripture"
    manifest = json.loads(
        (resource_root / "standard-vrs-provenance.json").read_text(encoding="utf-8")
    )

    assert manifest["source"]["commit"] == "bb9d36de70ed7fd6c3e62f0c86c1001f0009eb50"
    assert manifest["source"]["license"] == "MIT"
    entries = {row["filename"]: row for row in manifest["resources"]}
    assert set(entries) == set(SHIPPED_SHA256)
    for filename, expected_hash in SHIPPED_SHA256.items():
        assert entries[filename]["shipped_sha256"] == expected_hash
        assert sha256_file(resource_root / filename) == entries[filename]["shipped_sha256"]
