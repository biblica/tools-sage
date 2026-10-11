"""Assemble the typed NCA reference package from the rebuilt OL and NIV layers.

The package keeps the established layout (``reference/`` tables, ``CHECKSUMS.sha256`` whose
SHA-256 is the package identity, the Western/OL mapping rules) so scope projection, the Core
pin and imports work unchanged; ``MANIFEST.json`` declares the typed format.

- ``reference/values.tsv``  one row per counted value and layer (OL, NIV): value, kind, role,
  what it counts (REFERENT, an English gloss), the words it came from, and its review status;
- ``reference/verses.tsv``  one row per Western verse: the OL text, the quoted English text and
  its footnotes from the public-domain Berean Standard Bible (``BSB_TEXT``, ``BSB_NOTES``), the
  typed OL/NIV MATCH_STATUS, and the verse review status. No NIV Scripture text is shipped (NIV
  fair use allows at most 500 verses): the NIV is cited by its numbers and number words ("also see");
- curated text-critical registries (textual variants, footnote guidance, unit conversions,
  provenance sources) carried from the 2026-09-09 package unchanged.

Review decisions are applied per layer: ``REBUILT`` keeps the rebuilt values, ``INDEX`` restores
the 2026-09-09 values, ``OTHER`` uses ``FINAL_VALUES``. A difference nobody has decided yet keeps
the rebuilt values with status ``PROVISIONAL`` (a mismatch there is never a FAIL); a difference
the counting convention settles on its own is ``CONVENTION``; a verse that agrees with the
2026-09-09 package is ``AGREES``.
"""
from __future__ import annotations

from collections import OrderedDict
import csv
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import shutil

from .build import typed_values
from .macula import SOURCES, read_verses
from .niv import fingerprint, read_project
from .apparatus import ATTRIBUTION, evidence_entry
from .niv_layer import match_status, ref_key, typed_niv

FORMAT = "sage-numbers-typed-1.1"
VALUE_FIELDS = ("WESTERN_REF", "LAYER", "OL_REF", "LANG", "EXPR_NO", "VALUE", "KIND", "ROLE", "REFERENT",
                "UNIT", "SURFACE", "SOURCE_IDS", "REVIEW_STATUS")
VERSE_FIELDS = ("WESTERN_REF", "OL_REFS", "LANG", "OL_TEXT", "BSB_TEXT", "BSB_NOTES", "MATCH_STATUS",
                "OL_REVIEW_STATUS", "NIV_REVIEW_STATUS", "TC_STATUS", "TC_EVIDENCE")
CARRIED = ("textual_variant_registry.tsv", "footnote_guidance.tsv", "unit_conversion_registry.tsv",
           "provenance_sources.tsv", "eng_org_map_rules.txt")
_STATUS_ORDER = ("AGREES", "CONVENTION", "REVIEWED", "PROVISIONAL")


def _tsv(rows, fields) -> bytes:
    """Deterministic UTF-8 TSV bytes."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _read(path: Path) -> list[dict[str, str]]:
    """Read one UTF-8 TSV into rows."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _decisions(path: Path, key: str) -> dict[str, dict[str, str]]:
    """Review rows keyed by reference."""
    return {row[key]: row for row in _read(path)} if path.is_file() else {}


def _status(decision: dict[str, str] | None) -> str:
    """Review status of one layer at one reference."""
    if decision is None:
        return "AGREES"
    if decision.get("DECISION"):
        return "REVIEWED"
    return "CONVENTION" if decision.get("SUGGESTED_DECISION") else "PROVISIONAL"


def _replacement(decision: dict[str, str] | None) -> list[Fraction] | None:
    """Values a reviewer chose instead of the rebuilt ones, or None to keep them."""
    if not decision:
        return None
    if decision.get("DECISION") == "INDEX":
        raw = decision["INDEX_VALUES"]
    elif decision.get("DECISION") == "OTHER":
        raw = decision["FINAL_VALUES"]
    else:
        return None
    return [Fraction(item) for item in raw.split(";") if item.strip()]


def _ol_text(words) -> str:
    """One verse of MACULA words as running text."""
    return "".join(word.text + word.after for word in words).strip()


def build_package(*, cache: Path, niv_project: Path, review_root: Path, old_package: Path, out: Path,
                  package_id: str, counting_convention: Path, apparatus_cache: Path) -> dict[str, object]:
    """Write one typed package directory deterministically and return its manifest."""
    from .versify import Linker
    from .witnesses import WITNESSES, quoted_verses
    bsb = quoted_verses(apparatus_cache, old_package.parent.parent / "scripture", "BSB")
    links = Linker(old_package.parent.parent / "scripture", niv_project / "Custom.vrs")
    western = links.ol_to_western
    order = {}
    ol_decisions = _decisions(review_root / "REVIEW-DECISIONS.tsv", "OL_REF")
    niv_decisions = _decisions(review_root / "NIV-REVIEW-DECISIONS.tsv", "WESTERN_REF")

    # OL layer: rebuilt MACULA values per Western verse, with any reviewer replacement applied.
    values: dict[str, list[dict[str, str]]] = {}
    ol_refs: dict[str, list[str]] = {}
    language: dict[str, str] = {}
    ol_texts: dict[str, list[str]] = {}
    for family, source in SOURCES.items():
        verses = read_verses(cache / source["file"], family)
        records: dict[str, list] = OrderedDict()
        for record in typed_values(cache / source["file"], family):
            records.setdefault(record.ol_ref, []).append(record)
        for ol_ref, words in verses.items():
            ref = western(ol_ref)
            decision = ol_decisions.get(ol_ref)
            mine = records.get(ol_ref, [])
            if not mine and decision is None:
                continue
            ol_refs.setdefault(ref, []).append(ol_ref)
            language[ref] = family
            ol_texts.setdefault(ref, []).append(_ol_text(words))
            status = _status(decision)
            replacement = _replacement(decision)
            rows = values.setdefault(ref, [])
            if replacement is not None:
                rows.extend({"WESTERN_REF": ref, "LAYER": "OL", "OL_REF": ol_ref, "LANG": family, "EXPR_NO": index,
                             "VALUE": str(value), "SOURCE_IDS": "REVIEW_DECISION", "REVIEW_STATUS": status}
                            for index, value in enumerate(replacement, 1))
                continue
            rows.extend({
                "WESTERN_REF": ref, "LAYER": "OL", "OL_REF": ol_ref, "LANG": family, "EXPR_NO": item.expression_no,
                "VALUE": str(item.value), "KIND": item.kind, "ROLE": item.role, "REFERENT": item.referent,
                "UNIT": item.unit_gloss, "SURFACE": item.surface, "SOURCE_IDS": " ".join(item.word_ids),
                "REVIEW_STATUS": status,
            } for item in mine)

    # NIV layer: counted from the local usNIVv2 project, reviewer replacements applied the same way.
    niv_verses = read_project(niv_project, links)
    order.update({book: number for number, book in enumerate(dict.fromkeys(ref.split()[0] for ref in niv_verses))})
    niv_records: dict[str, list] = OrderedDict()
    for record in typed_niv(niv_verses):
        niv_records.setdefault(record.ref, []).append(record)
    niv_status: dict[str, str] = {}
    for ref in set(niv_records) | set(niv_decisions):
        decision = niv_decisions.get(ref)
        niv_status[ref] = _status(decision)
        replacement = _replacement(decision)
        rows = values.setdefault(ref, [])
        if replacement is not None:
            rows.extend({"WESTERN_REF": ref, "LAYER": "NIV", "EXPR_NO": index, "VALUE": str(value),
                         "SOURCE_IDS": "REVIEW_DECISION", "REVIEW_STATUS": niv_status[ref]}
                        for index, value in enumerate(replacement, 1))
            continue
        rows.extend({
            "WESTERN_REF": ref, "LAYER": "NIV", "EXPR_NO": item.expression_no, "VALUE": str(item.value),
            "KIND": item.kind, "ROLE": item.role, "REFERENT": item.referent, "UNIT": item.unit,
            "SURFACE": item.surface, "SOURCE_IDS": f"{item.start}-{item.end}", "REVIEW_STATUS": niv_status[ref],
        } for item in niv_records.get(ref, []))

    # Verses with registered text-critical guidance stay listed even without numbers (NEH 7:68).
    registered: dict[str, list[dict[str, object]]] = {}
    for row in _read(old_package / "reference" / "textual_variant_registry.tsv"):
        registered.setdefault(f"{row['BK']} {row['CH']}:{row['VS']}", []).append({
            "source": "REGISTRY",
            "summary": " ".join(part for part in (row["MANUSCRIPT_EVIDENCE"], row["CRITICAL_TEXT_POSITION"],
                                                  row["MAJORITY_SCHOLARSHIP_POSITION"]) if part),
            "status": row["SCHOLARSHIP_STATUS"], "url": ""})
    for row in _read(old_package / "reference" / "footnote_guidance.tsv"):
        entries = registered.setdefault(f"{row['BK']} {row['CH']}:{row['VS']}", [])
        if not entries:
            entries.append({"source": "REGISTRY", "summary": " ".join(
                part for part in (row["MANUSCRIPT_EVIDENCE"], row["SCHOLARSHIP_POSITION"]) if part),
                "status": row["SCHOLARSHIP_STATUS"], "url": row["SOURCE_URLS"].split(";")[0].strip()})
    old_rows = {f"{row['BK']} {row['CH']}:{row['VS']}": row
                for row in _read(old_package / "reference/SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv")}

    # Apparatus evidence (tools/build_numbers_index.py apparatus): a recorded number variant makes a
    # verse a text-critical decision; an OL/NIV difference without one is a rendering difference.
    apparatus: dict[str, list[dict[str, str]]] = {}
    if (review_root / "APPARATUS-EVIDENCE.tsv").is_file():
        for row in _read(review_root / "APPARATUS-EVIDENCE.tsv"):
            apparatus.setdefault(row["WESTERN_REF"], []).append(row)

    def sort_key(label: str) -> tuple:
        """Canonical order of a Western reference."""
        book, chapter, verse = ref_key(label)
        return order.get(book, 999), chapter, verse

    verse_rows, value_rows = [], []
    for ref in sorted(set(values) | set(registered), key=sort_key):
        rows = values.get(ref, [])
        ol = [Fraction(row["VALUE"]) for row in rows if row["LAYER"] == "OL"]
        niv = [Fraction(row["VALUE"]) for row in rows if row["LAYER"] == "NIV"]
        if not ol and not niv and ref not in registered:
            continue
        ol_state = max((row["REVIEW_STATUS"] for row in rows if row["LAYER"] == "OL"), key=_STATUS_ORDER.index,
                       default="AGREES")
        quoted = bsb.get(ref)
        old = old_rows.get(ref, {})
        verse_rows.append({
            "WESTERN_REF": ref, "OL_REFS": " ".join(ol_refs.get(ref, [])) or old.get("OL_REF", ""),
            "LANG": language.get(ref) or old.get("LANG", ""),
            "OL_TEXT": " ".join(ol_texts.get(ref, [])) or old.get("OL_TEXT", ""),
            "BSB_TEXT": quoted.text if quoted else "", "BSB_NOTES": " || ".join(quoted.notes) if quoted else "",
            "MATCH_STATUS": match_status(ol, niv), "OL_REVIEW_STATUS": ol_state,
            "NIV_REVIEW_STATUS": niv_status.get(ref, "AGREES"),
            "TC_STATUS": ("VARIANT_ATTESTED" if ref in apparatus or ref in registered else
                          "NO_VARIANT" if not match_status(ol, niv).startswith("PASS") else "NONE"),
            "TC_EVIDENCE": json.dumps([evidence_entry(item["SOURCE"], item["SUMMARY"], item["URL"], item.get("BASIS", ""),
                                                      item.get("SEE_ALSO", ""))
                                       for item in apparatus.get(ref, ())] + registered.get(ref, []),
                                      ensure_ascii=False, sort_keys=True) if ref in apparatus or ref in registered
            else "",
        })
        value_rows.extend(rows)

    # Write tables, carried registries and the manifest; CHECKSUMS.sha256 is the package identity.
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference"
    reference.mkdir(exist_ok=True)
    files = {
        "reference/values.tsv": _tsv(value_rows, VALUE_FIELDS),
        "reference/verses.tsv": _tsv(verse_rows, VERSE_FIELDS),
    }
    for name in CARRIED:
        files[f"reference/{name}"] = (old_package / "reference" / name).read_bytes()
    statuses = {status: sum(1 for row in verse_rows if status in (row["OL_REVIEW_STATUS"], row["NIV_REVIEW_STATUS"]))
                for status in _STATUS_ORDER}
    niv_source = fingerprint(niv_project)
    manifest = {
        "format": FORMAT,
        "package_id": package_id,
        "counting_convention_sha256": hashlib.sha256(counting_convention.read_bytes()).hexdigest(),
        "sources": {
            **{family: {key: source[key] for key in ("edition", "commit", "sha256", "attribution", "url")}
               for family, source in SOURCES.items()},
            "NIV": {"edition": niv_source["edition"], "rights": niv_source["rights"], "sha256": niv_source["sha256"],
                    "shipped": "numbers, number words and offsets only; no NIV Scripture text (fair use: at most 500 verses)"},
            "BSB": {"edition": WITNESSES["BSB"]["label"], "url": WITNESSES["BSB"]["url"],
                    "attribution": ATTRIBUTION["BSB"], "shipped": "quoted verse text and footnotes (BSB_TEXT, BSB_NOTES)"},
            "registries": "SAGE_NUMBERS_REFERENCE_2026-09-09 (textual variants, footnote guidance, unit conversions)",
        },
        "apparatus": {
            "evidence_sha256": hashlib.sha256((review_root / "APPARATUS-EVIDENCE.tsv").read_bytes()).hexdigest()
            if (review_root / "APPARATUS-EVIDENCE.tsv").is_file() else None,
            "sources": "NET Bible tc notes (netbible.org, cited); SBLGNT apparatus (Faithlife/SBLGNT, CC BY 4.0); "
                       "OSHB ketiv/qere (openscriptures/morphhb, CC BY 4.0); BSB footnotes and LXX/Vulgate/KJV/BSB "
                       "readings (public domain)",
            "attribution": dict(ATTRIBUTION),
        },
        "review": {
            "ol_decisions_sha256": hashlib.sha256((review_root / "REVIEW-DECISIONS.tsv").read_bytes()).hexdigest(),
            "niv_decisions_sha256": hashlib.sha256((review_root / "NIV-REVIEW-DECISIONS.tsv").read_bytes()).hexdigest(),
            "verses_by_status": statuses,
        },
        "counts": {"verses": len(verse_rows), "values": len(value_rows),
                   "ol_values": sum(1 for row in value_rows if row["LAYER"] == "OL"),
                   "niv_values": sum(1 for row in value_rows if row["LAYER"] == "NIV")},
    }
    files["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    for name, data in files.items():
        (out / name).write_bytes(data)
    checksums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items()))
    (out / "CHECKSUMS.sha256").write_text(checksums, encoding="utf-8")
    manifest["package_sha256"] = hashlib.sha256(checksums.encode()).hexdigest()
    return manifest


def copy_tree(source: Path, destination: Path) -> None:
    """Replace one package directory with a freshly built one."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
