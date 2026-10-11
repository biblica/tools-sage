#!/usr/bin/env python3
"""Rebuild the NCA original-language number index from pinned MACULA sources.

Subcommands:

- ``fetch``  download the pinned MACULA Hebrew/Greek word tables into the SAGE cache and
             verify their SHA-256 (sources are not vendored; they are 100 MB of upstream data);
- ``build``  compose typed per-value records, map OL coordinates to Western ones, and write
             the review artifacts: TYPED-NUMBERS.tsv, EXCLUDED-WORDS.tsv (number-like words not counted,
             with the reason), REGRESSION-DIFF.tsv (every verse that
             differs from the current package), REVIEW-DECISIONS.tsv (one row per difference,
             for a reviewer to decide), SUMMARY.md and BUILD-MANIFEST.json;
- ``verify`` rebuild into a temporary folder and require byte-identical artifacts;
- ``niv-build --niv PROJECT``  count the NIV (secondary authority) from a local Paratext
             project and write NIV-TYPED-NUMBERS.tsv, NIV-EVIDENCE.tsv (text SHA-256 and count of
             number-bearing footnotes for every verse either layer counts in; no NIV text),
             OL-NIV-COMPARISON.tsv (typed MATCH_STATUS per Western verse), NIV-REGRESSION-DIFF.tsv,
             NIV-REVIEW-DECISIONS.tsv, NIV-SUMMARY.md and NIV-BUILD-MANIFEST.json. The NIV text is
             Biblica, Inc. copyright and is never copied into the repository (fair use allows at most
             500 verses); verse text is quoted from the public-domain BSB;
- ``niv-verify --niv PROJECT`` rebuild the NIV layer and require byte-identical artifacts;
- ``apparatus`` classify every indexed verse against cached online apparatus (NET tc notes,
             SBLGNT apparatus, OSHB ketiv/qere; see numbers/index_build/apparatus.py) and write
             APPARATUS-EVIDENCE.tsv and APPARATUS-SUMMARY.md (cache: ``--apparatus-cache``);
- ``package --niv PROJECT --date YYYY-MM-DD`` assemble the typed runtime package
             ``system/resources/numbers/<date>/`` from both layers and the review decisions.

The runtime reference package is not switched by this tool: the current package stays
authoritative until every difference carries a reviewed decision.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from fractions import Fraction
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Mapping
import sys
import tempfile
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system/src"))

from sage.numbers.index_build.build import (  # noqa: E402
    excluded_words, explain, regression, scoped_out, typed_values)
from sage.numbers.index_build.macula import SOURCES, verify_source  # noqa: E402
from sage.numbers.index_build.niv import CANON, fingerprint, read_project  # noqa: E402
from sage.numbers.index_build import niv_layer  # noqa: E402
from sage.storage import storage_layout  # noqa: E402

PACKAGE = ROOT / "system/resources/numbers/2026-09-09"
DEFAULT_OUT = ROOT / "docs/advanced/release/nca-index-rebuild"
TYPED_FIELDS = ("OL_REF", "WESTERN_REF", "LANG", "EXPR_NO", "VALUE", "KIND", "ROLE", "UNIT_LEMMA",
                "UNIT_GLOSS", "REFERENT", "SURFACE", "LEMMAS", "WORD_IDS")
DIFF_FIELDS = ("OL_REF", "WESTERN_REF", "LANG", "STATUS", "REBUILT_VALUES", "INDEX_VALUES", "REBUILT_KINDS",
               "REBUILT_SURFACE", "INDEX_MATCH_STATUS", "INDEX_OVERRIDES", "NIV_VALUES", "REASON",
               "SUGGESTED_DECISION")
EXCLUDED_FIELDS = ("OL_REF", "WESTERN_REF", "LANG", "WORD_ID", "SURFACE", "LEMMA", "GLOSS", "REASON")
DECISION_FIELDS = ("OL_REF", "WESTERN_REF", "LANG", "STATUS", "REBUILT_VALUES", "INDEX_VALUES", "REASON",
                   "SUGGESTED_DECISION", "DECISION", "FINAL_VALUES", "REVIEWER", "NOTE")


def default_cache() -> Path:
    """MACULA sources live in the SAGE cache, never in the repository."""
    return storage_layout(ROOT).cache_root / "macula"


def fetch(cache: Path) -> dict[str, str]:
    """Download each pinned source once and verify it."""
    cache.mkdir(parents=True, exist_ok=True)
    paths = {}
    for family, source in SOURCES.items():
        path = cache / source["file"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            temporary = path.with_suffix(".part")
            with urllib.request.urlopen(source["url"], timeout=600) as response, temporary.open("wb") as handle:
                while chunk := response.read(1 << 20):
                    handle.write(chunk)
            temporary.replace(path)
        verify_source(path, family)
        paths[family] = str(path)
    return paths


def _tsv(rows: list[dict[str, object]], fields: tuple[str, ...]) -> bytes:
    """Deterministic UTF-8 TSV bytes with a fixed header and LF line endings."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


REVIEWER_FIELDS = ("DECISION", "FINAL_VALUES", "REVIEWER", "NOTE")


def _keep_decisions(rows: list[dict[str, object]], previous: Path, key: str) -> list[dict[str, object]]:
    """Carry a reviewer's DECISION, FINAL_VALUES, REVIEWER and NOTE into a rebuilt review file.

    A decision is kept only while the row's rebuilt and package values are unchanged; when they
    change, the earlier decision moves into NOTE so the reviewer rechecks it.
    """
    if not previous.is_file():
        return rows
    earlier = {row[key]: row for row in _read_tsv(previous)}
    for row in rows:
        old = earlier.get(str(row[key]))
        if old is None or not any(old.get(field) for field in REVIEWER_FIELDS):
            continue
        if (old["REBUILT_VALUES"], old["INDEX_VALUES"]) == (row["REBUILT_VALUES"], row["INDEX_VALUES"]):
            row.update({field: old.get(field, "") for field in REVIEWER_FIELDS})
        else:
            row["NOTE"] = (f"RECHECK: values changed since {old.get('REVIEWER') or 'review'} decided "
                           f"{old.get('DECISION')} on {old['REBUILT_VALUES']} vs {old['INDEX_VALUES']}")
    return rows


def _summary(totals: list[dict[str, str]], typed: list[dict[str, object]], diff: list[dict[str, str]]) -> bytes:
    """Human summary of what the rebuild found and what review must decide."""
    by_family = {family: Counter(row["STATUS"] for row in totals if row["LANG"] == family) for family in SOURCES}
    lines = [
        "# NCA original-language number index rebuild",
        "",
        "Typed per-value records rebuilt from MACULA Hebrew (WLC) and MACULA Greek (SBLGNT) word data",
        "with `system/tools/build_numbers_index.py`, compared verse by verse with the 2026-09-09",
        "reference package. The runtime package is unchanged until every difference below is reviewed.",
        "",
        "## Agreement with the current package",
        "",
        "| Language | Verses | Agree | Changed | New | Dropped | Agreement |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family, counts in by_family.items():
        total = sum(counts.values())
        lines.append(f"| {family} | {total} | {counts['AGREE']} | {counts['CHANGED']} | {counts['NEW']} | "
                     f"{counts['DROPPED']} | {100 * counts['AGREE'] / total:.1f}% |")
    kinds = Counter(str(row["KIND"]) for row in typed)
    lines += [
        "",
        f"Typed values: {len(typed)} ({', '.join(f'{kind} {count}' for kind, count in sorted(kinds.items()))}).",
        "",
        "## Review",
        "",
        "`REVIEW-DECISIONS.tsv` has one row per verse that differs. For each, set `DECISION` to",
        "`REBUILT` (the rebuilt values are right), `INDEX` (keep the current package values) or",
        "`OTHER` (give `FINAL_VALUES`), with `REVIEWER` and a `NOTE`. A row whose package-only values",
        "are all outside NCA's scope (counting convention 2.0: quantities and dates only) carries",
        f"`REASON` `SCOPE: ...` and `SUGGESTED_DECISION` `REBUILT` ({sum(1 for row in diff if row.get('REASON'))}"
        " rows); the words are listed in `EXCLUDED-WORDS.tsv`. Known difference classes:",
        "",
        "- the current index contradicts itself (e.g. twelve as 2;10 in NUM 7:3 but 12 in JOS 4:4;",
        "  \"a thousand thousands\" as 1,000,000 in 1CH 21:5 but 1000;1000 in 2CH 14:8);",
        "- numbers the current index missed (fractions such as LEV 22:14 \"a fifth\", 1SA 9:8",
        "  \"a fourth of a shekel\");",
        "- the 103 undocumented FINAL_OL_VERSE_OVERRIDE verses, now traceable to MACULA word IDs;",
        "- policy classes the index never counts, listed with reasons in `EXCLUDED-WORDS.tsv`: מִשְׁנֶה",
        "  (\"second/double/matching\", the EZR 1:10 case) and Greek ἅπαξ (\"once\").",
        "",
        "## Sources",
        "",
    ]
    for source in SOURCES.values():
        lines.append(f"- {source['edition']}: commit `{source['commit']}`, sha256 `{source['sha256']}`. "
                     f"{source['attribution']} (CC BY 4.0).")
    return ("\n".join(lines) + "\n").encode("utf-8")


SCRIPTURE = ROOT / "system/resources/scripture"


def linker(niv_project: Path | None = None):
    """The shared .vrs linker (eng.vrs Western baseline; the NIV project's Custom.vrs when given)."""
    from sage.numbers.index_build.versify import Linker
    return Linker(SCRIPTURE, niv_project / "Custom.vrs" if niv_project is not None else None)


def build(cache: Path, out: Path, committed: Path = DEFAULT_OUT) -> dict[str, object]:
    """Build every artifact deterministically into ``out``."""
    western = linker().ol_to_western
    records = []
    for family, source in SOURCES.items():
        records.extend(typed_values(cache / source["file"], family))
    typed = [{
        "OL_REF": record.ol_ref, "WESTERN_REF": western(record.ol_ref), "LANG": record.family,
        "EXPR_NO": record.expression_no, "VALUE": str(record.value), "KIND": record.kind, "ROLE": record.role,
        "UNIT_LEMMA": record.unit_lemma, "UNIT_GLOSS": record.unit_gloss, "REFERENT": record.referent,
        "SURFACE": record.surface,
        "LEMMAS": " ".join(record.lemmas), "WORD_IDS": " ".join(record.word_ids),
    } for record in records]
    family_of = {record.ol_ref: record.family for record in records}
    removed: dict[str, list] = {}
    for family, source in SOURCES.items():
        removed.update(scoped_out(cache / source["file"], family))
    diff = []
    for row in regression(records, PACKAGE / "reference"):
        if row["STATUS"] == "AGREE":
            continue
        mine = Counter(Fraction(value) for value in row["REBUILT_VALUES"].split(";") if value)
        theirs = Counter(Fraction(value) for value in row["INDEX_VALUES"].split(";") if value)
        why = explain(theirs - mine, removed.get(row["OL_REF"], [])) if not mine - theirs else ""
        diff.append({**row, "WESTERN_REF": western(row["OL_REF"]),
                     "LANG": family_of.get(row["OL_REF"]) or _index_language(row["OL_REF"]),
                     "REASON": f"SCOPE: {why}" if why else "", "SUGGESTED_DECISION": "REBUILT" if why else ""})
    totals = []
    for row in regression(records, PACKAGE / "reference"):
        totals.append({"STATUS": row["STATUS"], "LANG": family_of.get(row["OL_REF"]) or _index_language(row["OL_REF"])})
    decisions = _keep_decisions([{key: row.get(key, "") for key in DECISION_FIELDS} for row in diff],
                                committed / "REVIEW-DECISIONS.tsv", "OL_REF")
    excluded = [{
        "OL_REF": item.ol_ref, "WESTERN_REF": western(item.ol_ref), "LANG": item.family, "WORD_ID": item.word_id,
        "SURFACE": item.surface, "LEMMA": item.lemma, "GLOSS": item.gloss, "REASON": item.reason,
    } for family, source in SOURCES.items() for item in excluded_words(cache / source["file"], family)]
    artifacts = {
        "TYPED-NUMBERS.tsv": _tsv(typed, TYPED_FIELDS),
        "REGRESSION-DIFF.tsv": _tsv(diff, DIFF_FIELDS),
        "REVIEW-DECISIONS.tsv": _tsv(decisions, DECISION_FIELDS),
        "EXCLUDED-WORDS.tsv": _tsv(excluded, EXCLUDED_FIELDS),
        "SUMMARY.md": _summary(totals, typed, diff),
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        (out / name).write_bytes(data)
    manifest = {
        "builder": "system/tools/build_numbers_index.py",
        "builder_modules": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted((ROOT / "system/src/sage/numbers/index_build").glob("*.py"))},
        "counting_convention_sha256": hashlib.sha256(
            (ROOT / "system/skills/nca-numbers/references/COUNTING-CONVENTION.md").read_bytes()).hexdigest(),
        "compared_package": PACKAGE.name,
        "sources": {family: {key: source[key] for key in ("commit", "sha256", "edition", "attribution", "url")}
                    for family, source in SOURCES.items()},
        "artifacts": {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()},
        "counts": {"typed_values": len(typed), "differences": len(diff), "excluded_words": len(excluded)},
    }
    (out / "BUILD-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8")
    return manifest


NIV_TYPED_FIELDS = ("WESTERN_REF", "EXPR_NO", "VALUE", "KIND", "ROLE", "UNIT", "REFERENT", "SURFACE", "START", "END")
NIV_EVIDENCE_FIELDS = ("WESTERN_REF", "NUMBER_NOTES", "TEXT_SHA256")
COMPARISON_FIELDS = ("WESTERN_REF", "OL_REFS", "LANG", "OL_VALUES", "OL_KINDS", "NIV_VALUES", "NIV_KINDS",
                     "MATCH_STATUS", "OL_ONLY", "NIV_ONLY", "OL_SURFACE", "NIV_SURFACE")
NIV_DIFF_FIELDS = ("WESTERN_REF", "STATUS", "REBUILT_VALUES", "INDEX_VALUES", "REBUILT_SURFACE", "REASON",
                   "SUGGESTED_DECISION")
NIV_DECISION_FIELDS = ("WESTERN_REF", "STATUS", "REBUILT_VALUES", "INDEX_VALUES", "REASON", "SUGGESTED_DECISION",
                       "DECISION", "FINAL_VALUES", "REVIEWER", "NOTE")
NIV_ARTIFACTS = ("NIV-TYPED-NUMBERS.tsv", "NIV-EVIDENCE.tsv", "OL-NIV-COMPARISON.tsv", "NIV-REGRESSION-DIFF.tsv",
                 "NIV-REVIEW-DECISIONS.tsv", "NIV-SUMMARY.md")


def _read_tsv(path: Path) -> list[dict[str, str]]:
    """Read one UTF-8 TSV into rows."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _niv_summary(niv, comparison, diff, evidence, source) -> bytes:
    """Human summary of the NIV layer, its agreement with the OL layer, and what review must decide."""
    statuses = Counter(row["MATCH_STATUS"] for row in comparison)
    kinds = Counter(record.kind for record in niv)
    reasons = Counter(row["REASON"] for row in diff)
    lines = [
        "# NCA NIV (secondary authority) number layer",
        "",
        "Typed NIV values counted with `system/tools/build_numbers_index.py niv-build` from the local",
        "`usNIVv2` Paratext project by the shared counting convention, and compared verse by verse with",
        "the rebuilt original-language layer (`TYPED-NUMBERS.tsv`). Original language stays the only",
        "BLOCKING authority; NIV is secondary evidence (see `docs/advanced/future/AUTHORITY-POLICY.md`).",
        "",
        f"Typed NIV values: {len(niv)} in {len({record.ref for record in niv})} verses "
        f"({', '.join(f'{kind} {number}' for kind, number in sorted(kinds.items()))}).",
        f"Evidence rows (NIV text SHA-256 + count of number-bearing footnotes; no NIV text is shipped): {len(evidence)}.",
        "",
        "## OL / NIV agreement (typed, per Western verse)",
        "",
        "| MATCH_STATUS | Verses |",
        "|---|---:|",
    ]
    lines += [f"| {status} | {number} |" for status, number in sorted(statuses.items())]
    lines += [
        "",
        "## Differences from the 2026-09-09 package NIV_VALUES",
        "",
        f"{len(diff)} verses differ. `NIV-REVIEW-DECISIONS.tsv` has one row each with a reason class; a",
        "`SUGGESTED_DECISION` of `REBUILT` marks classes the counting convention decides on its own.",
        "",
        "| Reason | Verses |",
        "|---|---:|",
    ]
    lines += [f"| {why} | {number} |" for why, number in sorted(reasons.items(), key=lambda item: -item[1])]
    lines += [
        "",
        "## Source",
        "",
        f"- {source['edition']}; {source['rights']}",
        f"- Local Paratext project read at build time; combined sha256 `{source['sha256']}` (per-book",
        "  digests in `NIV-BUILD-MANIFEST.json`). No NIV Scripture text is shipped (NIV fair use allows at most",
        "  500 verses): verse text is quoted from the public-domain Berean Standard Bible and the NIV is cited",
        "  by reference and its numbers (\"also see\").",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_niv(project: Path, out: Path, committed: Path = DEFAULT_OUT) -> dict[str, object]:
    """Build the NIV layer artifacts deterministically into ``out``."""
    source = fingerprint(project)
    verses = read_project(project, linker(project))
    niv = niv_layer.typed_niv(verses)
    order = {book: number for number, book in enumerate(CANON)}
    ol_rows = _read_tsv(DEFAULT_OUT / "TYPED-NUMBERS.tsv")
    package_rows = _read_tsv(PACKAGE / "reference/SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv")
    comparison = niv_layer.comparison(ol_rows, niv, order)
    diff = niv_layer.regression(niv, package_rows, verses)
    needed = {row["WESTERN_REF"] for row in comparison} | {row["WESTERN_REF"] for row in diff}
    needed |= {f"{row['BK']} {row['CH']}:{row['VS']}" for row in package_rows}
    evidence = niv_layer.evidence(verses, needed)
    typed = [{
        "WESTERN_REF": record.ref, "EXPR_NO": record.expression_no, "VALUE": str(record.value), "KIND": record.kind,
        "ROLE": record.role, "UNIT": record.unit, "REFERENT": record.referent, "SURFACE": record.surface,
        "START": record.start, "END": record.end,
    } for record in niv]
    decisions = _keep_decisions([{key: row.get(key, "") for key in NIV_DECISION_FIELDS} for row in diff],
                                committed / "NIV-REVIEW-DECISIONS.tsv", "WESTERN_REF")
    artifacts = {
        "NIV-TYPED-NUMBERS.tsv": _tsv(typed, NIV_TYPED_FIELDS),
        "NIV-EVIDENCE.tsv": _tsv(evidence, NIV_EVIDENCE_FIELDS),
        "OL-NIV-COMPARISON.tsv": _tsv(comparison, COMPARISON_FIELDS),
        "NIV-REGRESSION-DIFF.tsv": _tsv(diff, NIV_DIFF_FIELDS),
        "NIV-REVIEW-DECISIONS.tsv": _tsv(decisions, NIV_DECISION_FIELDS),
        "NIV-SUMMARY.md": _niv_summary(niv, comparison, diff, evidence, source),
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        (out / name).write_bytes(data)
    manifest = {
        "builder": "system/tools/build_numbers_index.py niv-build",
        "builder_modules": {name: hashlib.sha256((ROOT / "system/src/sage/numbers/index_build" / name).read_bytes())
                            .hexdigest() for name in ("english.py", "niv.py", "niv_layer.py")},
        "counting_convention_sha256": hashlib.sha256(
            (ROOT / "system/skills/nca-numbers/references/COUNTING-CONVENTION.md").read_bytes()).hexdigest(),
        "ol_layer_sha256": hashlib.sha256((DEFAULT_OUT / "TYPED-NUMBERS.tsv").read_bytes()).hexdigest(),
        "compared_package": PACKAGE.name,
        "source": source,
        "artifacts": {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()},
        "counts": {"niv_values": len(niv), "evidence_rows": len(evidence), "comparison_rows": len(comparison),
                   "differences": len(diff)},
    }
    (out / "NIV-BUILD-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                                                 + "\n", encoding="utf-8")
    return manifest


APPARATUS_FIELDS = ("WESTERN_REF", "SOURCE", "SUMMARY", "URL", "BASIS", "SEE_ALSO")
_NON_NUMERAL_STRONGS = {"884", "1339", "7652", "7656", "8141", "8336"}  # Beersheba, Bathsheba, Sheba, Shibah, year, linen


def build_apparatus(cache: Path, apparatus_cache: Path, out: Path) -> dict[str, object]:
    """Evidence table and verse classification from the cached online apparatus."""
    from sage.numbers.index_build.apparatus import ATTRIBUTION, collect
    from sage.numbers.index_build.macula import SOURCES as MACULA
    strongs = set()
    with (cache / MACULA["HEB"]["file"]).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["type"] in ("cardinal number", "ordinal number") and row.get("strongnumberx"):
                strongs.add(str(int(re.sub(r"[^0-9]", "", row["strongnumberx"]) or 0)))
    strongs -= _NON_NUMERAL_STRONGS
    package_root = ROOT / json.loads((ROOT / "system/config/numbers-reference.json").read_text())["path"]
    verses = _read_tsv(package_root / "reference/verses.tsv")
    evidence = collect(apparatus_cache, [row["WESTERN_REF"] for row in verses], strongs, linker())
    # BSB footnotes that report a number in another text ("LXX and Syriac; Hebrew seventh").
    from sage.numbers.index_build.apparatus import Evidence
    from sage.numbers.index_build.witnesses import WITNESSES, textual_notes
    indexed = {row["WESTERN_REF"] for row in verses}
    for ref, notes in textual_notes(apparatus_cache, SCRIPTURE, "BSB").items():
        if ref in indexed:
            evidence.setdefault(ref, []).extend(Evidence(ref, "BSB_NOTE", note, WITNESSES["BSB"]["url"]) for note in notes)
    rows = [{"WESTERN_REF": item.reference, "SOURCE": item.source, "SUMMARY": item.summary, "URL": item.url,
             "BASIS": item.basis} for row in verses for item in evidence.get(row["WESTERN_REF"], ())]
    # Public-domain witnesses (LXX, Vulgate, KJV; BSB as a rendering reference with "see also")
    # at every verse with recorded evidence: independent support for the NET references, citable in full.
    corroboration, witness_rows = _witness_evidence(apparatus_cache, package_root, verses, evidence)
    rows += witness_rows
    order = {row["WESTERN_REF"]: index for index, row in enumerate(verses)}
    rows.sort(key=lambda row: order.get(row["WESTERN_REF"], 0))
    differ = [row for row in verses if not row["MATCH_STATUS"].startswith("PASS")]
    attested = [row for row in differ if row["WESTERN_REF"] in evidence]
    hidden = [row for row in verses if row["MATCH_STATUS"].startswith("PASS") and row["WESTERN_REF"] in evidence]
    registry = {f"{row['BK']} {row['CH']}:{row['VS']}" for row in _read_tsv(package_root / "reference/footnote_guidance.tsv")}
    unconfirmed = sorted(registry - set(evidence))
    sources = Counter(item["SOURCE"] for item in rows)
    lines = [
        "# NCA apparatus check of the number index", "",
        "Every indexed verse checked against cached online apparatus: NET Bible text-critical notes",
        "(netbible.org, cited by URL), the SBLGNT apparatus (Faithlife/SBLGNT, CC BY 4.0), OSHB",
        "ketiv/qere (openscriptures/morphhb, CC BY 4.0) and Berean Standard Bible footnotes that report a",
        "number in another text (BSB, public domain). An entry counts when it records a number.", "",
        "NET excerpts (at most 240 characters per note, each with its link): "
        + ATTRIBUTION["NET_TC"], "",
        "| Measure | Verses |", "|---|---:|",
        f"| Indexed verses | {len(verses)} |",
        f"| Original language and NIV differ | {len(differ)} |",
        f"| … with a recorded number variant (text-critical decision) | {len(attested)} |",
        f"| … without one (rendering difference, not text-critical) | {len(differ) - len(attested)} |",
        f"| Agreeing verses that still have a recorded number variant | {len(hidden)} |",
        f"| Registered footnote guidance not confirmed by these sources | {len(unconfirmed)} |", "",
        "Evidence entries by source: " + ", ".join(f"{name} {count}" for name, count in sorted(sources.items())) + ".", "",
    ]
    if unconfirmed:
        lines += ["Registered guidance without apparatus evidence here (kept; review): " + ", ".join(unconfirmed), ""]
    support = _rule_support(out, evidence)
    verdicts_net = Counter(row["VERDICT"].split(":")[0] for row in corroboration)
    lines += [
        "## NET references checked against public-domain witnesses", "",
        "Each verse with a NET text-critical reference is read in four public-domain witnesses linked "
        "through their own versification: the Septuagint (Brenton 1851, `lxx.vrs`), the Vulgate "
        "(Douay-Rheims, `vul.vrs`), the KJV (Masoretic / Received text, `eng.vrs`) and the BSB "
        "(Berean Standard Bible, `eng.vrs`). The BSB is a modern rendering, cited with where to look next "
        "(\"also see\": MT or Greek NT, NIV, LXX, Vulgate, KJV); it never corroborates a variant. Details in "
        "`NET-CORROBORATION.tsv`.", "",
        "| Verdict | Verses |", "|---|---:|",
        *[f"| {name} | {count} |" for name, count in sorted(verdicts_net.items())], "",
        "- `CORROBORATED`: the Septuagint or Vulgate lacks the verse (while having its chapter), agrees with the "
        "NIV against the original language, or reads a number the original language does not have; in the NT "
        "the KJV (Received text) can corroborate the same way.",
        "- A cited parallel passage (`parallel <ref>`) corroborates when it lies in a synoptic book pair "
        "(Samuel-Kings/Chronicles, Kings/Jeremiah 52 or Isaiah 36-39, Ezra 2/Nehemiah 7, the Gospels ...), shares "
        "a number with this verse, and our own index of it has an original-language number this verse lacks "
        "(1CH 19:18 seven thousand / 2SA 10:18 seven hundred).",
        "- `MT_ONLY`: the versions and cited parallels agree with the original language; the variant rests on the "
        "NET note alone. Its basis is recorded, not quoted (column `NET_BASIS`, with the NET link):", "",
        "| Verse | Basis cited by the NET Bible tc note |", "|---|---|",
        *[f"| {row['WESTERN_REF']} | {row['NET_BASIS']} |" for row in corroboration
          if row["VERDICT"].startswith("MT_ONLY")], "",
    ]
    verdicts = Counter(row["APPARATUS_ASSESSMENT"].split(":")[0] for row in support)
    lines += [
        "## Rule decisions checked against the apparatus", "",
        "Every review row decided by the NIV number rule (REVIEWER `RULE-2026-10-08`) is checked here; "
        "details in `RULE-DECISIONS-APPARATUS.tsv`.", "",
        "| Assessment | Rows |", "|---|---:|",
        *[f"| {name} | {count} |" for name, count in sorted(verdicts.items())], "",
        "- `SUPPORTED`: no number variant is recorded at the verse, so the difference from the 2026-09-09 index "
        "is a counting matter, not a textual one; the rule decision stands.",
        "- `TEXTUAL`: a number variant is recorded; the verse is a text-critical decision for the operator "
        "(the index keeps the original-language reading).",
        "- `CONFLICT`: a removed value is named by a recorded variant; check the decision.", "",
    ]
    out.mkdir(parents=True, exist_ok=True)
    (out / "RULE-DECISIONS-APPARATUS.tsv").write_bytes(_tsv(support, RULE_SUPPORT_FIELDS))
    (out / "NET-CORROBORATION.tsv").write_bytes(_tsv(corroboration, CORROBORATION_FIELDS))
    (out / "APPARATUS-EVIDENCE.tsv").write_bytes(_tsv(rows, APPARATUS_FIELDS))
    (out / "APPARATUS-SUMMARY.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"verses": len(verses), "differ": len(differ), "attested": len(attested), "hidden_variants": len(hidden),
            "evidence_rows": len(rows), "registry_unconfirmed": len(unconfirmed), "rule_rows": dict(verdicts)}


from sage.canon import OT_39 as OL_BOOKS_OT  # noqa: E402

_SYNOPTIC = [
    {"1SA", "2SA", "1KI", "2KI", "1CH", "2CH"}, {"2KI", "JER"}, {"2KI", "ISA"}, {"EZR", "NEH"},
    {"2SA", "PSA"}, {"MAT", "MRK", "LUK", "JHN"}, {"EXO", "LEV", "NUM", "DEU"}, {"GEN", "1CH"},
]


def _synoptic(ref: str, other: str) -> bool:
    """Whether two verses sit in books that tell the same events (Samuel-Kings/Chronicles, Ezra/Nehemiah ...).

    A neighbouring verse of the same chapter is a cross-reference, not a parallel passage.
    """
    book, other_book = ref.split()[0], other.split()[0]
    if ref.rsplit(":", 1)[0] == other.rsplit(":", 1)[0]:
        return False
    return book != other_book and any({book, other_book} <= group for group in _SYNOPTIC)


CORROBORATION_FIELDS = ("WESTERN_REF", "OL_VALUES", "NIV_VALUES", "LXX_BRENTON", "VULGATE_DRA", "KJV", "BSB", "PARALLELS",
                        "VERDICT", "NET_BASIS", "NET_URL")


def _witness_evidence(apparatus_cache: Path, package_root: Path, verses: list, evidence: Mapping[str, list]):
    """Witness readings at evidenced verses, and the NET corroboration verdict per NET verse."""
    from sage.numbers.index_build.witnesses import WITNESSES, attests_variant, load, readings, see_also
    values: dict[str, tuple[list, list]] = {}
    for row in _read_tsv(package_root / "reference/values.tsv"):
        values.setdefault(row["WESTERN_REF"], ([], []))[0 if row["LAYER"] == "OL" else 1].append(Fraction(row["VALUE"]))
    registry = {f"{row['BK']} {row['CH']}:{row['VS']}" for row in _read_tsv(package_root / "reference/footnote_guidance.tsv")}
    targets = [row for row in verses if row["WESTERN_REF"] in evidence or row["WESTERN_REF"] in registry]
    found = readings(apparatus_cache, SCRIPTURE, targets, values)
    by_ref: dict[str, dict[str, object]] = {}
    rows = []
    for item in found:
        by_ref.setdefault(item.reference, {})[item.witness] = item
    for item in found:
        numbers = ", ".join(str(value) for value in item.values) or "no numbers"
        excerpt = item.text if len(item.text) <= 220 else item.text[:217].rsplit(" ", 1)[0] + " ..."
        summary = (f"{item.relation}: verse absent in this witness" if item.relation == "ABSENT"
                   else f"{item.relation}: {numbers} — “{excerpt}”")
        # The BSB is cited as a rendering reference with where to look next (MT, NIV, the versions).
        others = {name: reading for name, reading in by_ref[item.reference].items() if name != item.witness}
        rows.append({"WESTERN_REF": item.reference, "SOURCE": item.witness, "SUMMARY": summary,
                     "URL": WITNESSES[item.witness]["url"],
                     "SEE_ALSO": see_also(item.reference, *values.get(item.reference, ([], [])), others)
                     if item.witness == "BSB" else ""})
    # Parallel passages a NET note cites (1CH 19:18 -> 2SA 10:18): our own index of the parallel
    # verse (original language and NIV) is citable evidence that needs no license.
    from sage.numbers.index_build.apparatus import net_tc_parallels
    links = linker()
    bsb_texts = load(apparatus_cache, SCRIPTURE, "BSB")  # quoted text: public domain (no NIV text is shipped)
    parallels: dict[str, list[str]] = {}
    for row in targets:
        ref = row["WESTERN_REF"]
        book, _, cv = ref.partition(" ")
        chapter, _, verse = cv.partition(":")
        cited = net_tc_parallels(apparatus_cache, book, int(chapter)).get(int(verse), [])
        parallels[ref] = [other for other in (links.english_to_western(item) for item in cited)
                          if _synoptic(ref, other) and set(values.get(other, ([], []))[0])
                          & set(values.get(ref, ([], []))[0] or values.get(ref, ([], []))[1])]
        for other in parallels[ref]:
            ol, niv = values.get(other, ([], []))
            if not ol and not niv:
                continue
            bsb_text = bsb_texts.get(other, "")
            excerpt = bsb_text if len(bsb_text) <= 200 else bsb_text[:197].rsplit(" ", 1)[0] + " ..."
            rows.append({"WESTERN_REF": ref, "SOURCE": "PARALLEL",
                         "SUMMARY": f"{other}: original language {', '.join(str(v) for v in ol) or '—'}; "
                                    f"NIV {', '.join(str(v) for v in niv) or '—'} — BSB “{excerpt}”",
                         "URL": ""})
    corroboration = []
    for row in targets:
        ref = row["WESTERN_REF"]
        if not any(entry.source == "NET_TC" for entry in evidence.get(ref, ())):
            continue
        witnesses = by_ref.get(ref, {})
        ol, niv = values.get(ref, ([], []))
        versional = [name for name in ("LXX_BRENTON", "VULGATE_DRA")
                     if name in witnesses and attests_variant(witnesses[name], ol)]
        nt_received = ref.split()[0] not in OL_BOOKS_OT and "KJV" in witnesses and \
            attests_variant(witnesses["KJV"], ol)
        parallel = [other for other in parallels.get(ref, [])
                    if set(values.get(other, ([], []))[0]) - set(ol) or
                    (values.get(other, ([], []))[0] and set(values.get(other, ([], []))[0]) & (set(niv) - set(ol)))]
        support = versional + (["KJV (Received text)"] if nt_received else []) + [f"parallel {item}" for item in parallel]
        verdict = (f"CORROBORATED: {', '.join(support)}" if support
                   else "MT_ONLY: versions and cited parallels agree with the original language")
        cell = {name: (f"{witnesses[name].relation} {', '.join(str(v) for v in witnesses[name].values)}".strip()
                       if name in witnesses else "—") for name in WITNESSES}
        cited = "; ".join(f"{other} OL {';'.join(str(v) for v in values.get(other, ([], []))[0]) or '—'}"
                          for other in parallels.get(ref, []))
        net = [entry for entry in evidence.get(ref, ()) if entry.source == "NET_TC"]
        basis = list(dict.fromkeys(item for entry in net for item in entry.basis.split("; ") if item))
        corroboration.append({"WESTERN_REF": ref, "OL_VALUES": ";".join(str(v) for v in ol),
                              "NIV_VALUES": ";".join(str(v) for v in niv), **cell, "PARALLELS": cited,
                              "VERDICT": verdict, "NET_BASIS": "; ".join(basis),
                              "NET_URL": net[0].url if net else ""})
    return corroboration, rows


RULE_SUPPORT_FIELDS = ("LAYER", "REFERENCE", "WESTERN_REF", "DECISION", "REBUILT_VALUES", "INDEX_VALUES",
                       "FINAL_VALUES", "APPARATUS_ASSESSMENT", "APPARATUS_SOURCES", "APPARATUS_EVIDENCE")
_NUMBER_WORDS = {
    "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "10": "ten", "12": "twelve", "20": "twenty", "30": "thirty", "40": "forty", "50": "fifty", "60": "sixty",
    "70": "seventy", "80": "eighty", "90": "ninety", "100": "hundred", "1000": "thousand",
}


def _rule_support(out: Path, evidence: Mapping[str, list]) -> list[dict[str, str]]:
    """Check every rule-decided review row against the apparatus evidence at its verse."""
    found = []
    for name, layer, key in (("REVIEW-DECISIONS.tsv", "OL", "OL_REF"), ("NIV-REVIEW-DECISIONS.tsv", "NIV", "WESTERN_REF")):
        path = out / name
        if not path.is_file():
            continue
        for row in _read_tsv(path):
            if row.get("REVIEWER") != "RULE-2026-10-08":
                continue
            western = row["WESTERN_REF"]
            items = evidence.get(western, [])
            removed = re.findall(r"(\d[\d/]*) «", row.get("NOTE") or "")
            text = " ".join(item.summary for item in items).lower()
            named = [value for value in removed
                     if value in text or (_NUMBER_WORDS.get(value) and _NUMBER_WORDS[value] in text)]
            if not items:
                verdict = "SUPPORTED: no number variant recorded (NET tc, SBLGNT, OSHB, BSB notes)"
            elif named:
                verdict = "CONFLICT: removed value(s) " + ", ".join(named) + " named by a recorded variant"
            else:
                verdict = "TEXTUAL: number variant recorded; operator decision with evidence"
            found.append({
                "LAYER": layer, "REFERENCE": row[key], "WESTERN_REF": western, "DECISION": row["DECISION"],
                "REBUILT_VALUES": row["REBUILT_VALUES"], "INDEX_VALUES": row["INDEX_VALUES"],
                "FINAL_VALUES": row["FINAL_VALUES"], "APPARATUS_ASSESSMENT": verdict,
                "APPARATUS_SOURCES": ", ".join(sorted({item.source for item in items})),
                "APPARATUS_EVIDENCE": " || ".join(f"{item.source}: {item.summary} <{item.url}>" for item in items),
            })
    return found


_LANGUAGES: dict[str, str] = {}


def _index_language(ol_ref: str) -> str:
    """Language of a current-package row that the rebuild produced nothing for."""
    if not _LANGUAGES:
        with (PACKAGE / "reference/SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv").open(encoding="utf-8") as handle:
            _LANGUAGES.update({row["OL_REF"]: row["LANG"] for row in csv.DictReader(handle, delimiter="\t")})
    return _LANGUAGES.get(ol_ref, "")


def main(argv: list[str] | None = None) -> int:
    """Run fetch, build or verify."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("fetch", "build", "verify", "niv-build", "niv-verify", "apparatus", "package"))
    parser.add_argument("--niv", type=Path, default=None, help="local NIV Paratext project (usNIVv2)")
    parser.add_argument("--date", default=None, help="package date for the package command (YYYY-MM-DD)")
    parser.add_argument("--apparatus-cache", type=Path, default=None,
                        help="apparatus cache (default: SAGE cache /apparatus)")
    parser.add_argument("--cache", type=Path, default=None, help="MACULA source cache (default: SAGE cache)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="artifact folder")
    args = parser.parse_args(argv)
    cache = args.cache or default_cache()
    if args.command == "apparatus":
        apparatus_cache = args.apparatus_cache or storage_layout(ROOT).cache_root / "apparatus"
        print(json.dumps(build_apparatus(cache, apparatus_cache, args.out), indent=2))
        return 0
    if args.command == "package":
        if args.niv is None or not args.date:
            parser.error("--niv PROJECT and --date YYYY-MM-DD are required for package")
        from sage.numbers.index_build.package import build_package
        manifest = build_package(
            cache=cache, niv_project=args.niv, review_root=args.out, old_package=PACKAGE,
            apparatus_cache=args.apparatus_cache or storage_layout(ROOT).cache_root / "apparatus",
            out=ROOT / "system/resources/numbers" / args.date, package_id=f"SAGE_NUMBERS_TYPED_{args.date}",
            counting_convention=ROOT / "system/skills/nca-numbers/references/COUNTING-CONVENTION.md")
        print(json.dumps({key: manifest[key] for key in ("package_id", "counts", "review", "package_sha256")},
                         indent=2))
        return 0
    if args.command.startswith("niv-"):
        if args.niv is None:
            parser.error("--niv PROJECT is required for the NIV layer")
        if args.command == "niv-build":
            print(json.dumps(build_niv(args.niv, args.out, args.out)["counts"], indent=2))
            return 0
        with tempfile.TemporaryDirectory(prefix="sage-niv-index-") as directory:
            rebuilt = build_niv(args.niv, Path(directory), args.out)
        committed = json.loads((args.out / "NIV-BUILD-MANIFEST.json").read_text(encoding="utf-8"))
        if rebuilt["source"]["sha256"] != committed["source"]["sha256"]:
            print("FAIL: the NIV project differs from the one the committed layer was built from")
            return 2
        same = rebuilt["artifacts"] == committed["artifacts"]
        print("PASS" if same else "FAIL: rebuilt NIV artifacts differ from the committed artifacts")
        return 0 if same else 2
    if args.command == "fetch":
        print(json.dumps(fetch(cache), indent=2))
        return 0
    if args.command == "build":
        print(json.dumps(build(cache, args.out, args.out)["counts"], indent=2))
        return 0
    with tempfile.TemporaryDirectory(prefix="sage-numbers-index-") as directory:
        rebuilt = build(cache, Path(directory), args.out)
    committed = json.loads((args.out / "BUILD-MANIFEST.json").read_text(encoding="utf-8"))
    same = rebuilt["artifacts"] == committed["artifacts"] and all(
        hashlib.sha256((args.out / name).read_bytes()).hexdigest() == digest
        for name, digest in committed["artifacts"].items())
    print("PASS" if same else "FAIL: rebuilt artifacts differ from the committed review artifacts")
    return 0 if same else 2


if __name__ == "__main__":
    raise SystemExit(main())
