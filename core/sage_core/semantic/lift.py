"""Generate conservative LIFT interchange views for FLEx and The Combine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..atomic import atomic_write_json, atomic_write_text
from ..errors import ValidationError
from ..hashing import sha256_bytes, sha256_file
from ..registry import EcosystemConfig
from .freshness import require_current_index
from .policy import export_statuses
from .store import export_root, index_root, safe_id


def _text_form(parent: ET.Element, tag: str, language: str, value: str) -> None:
    """Append one language-tagged LIFT text form."""
    container = ET.SubElement(parent, tag)
    form = ET.SubElement(container, "form", {"lang": language})
    ET.SubElement(form, "text").text = value


def _load_indexes(config: EcosystemConfig, language: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load lexical-head and sense indexes required for LIFT exchange."""
    root = index_root(config, language)
    head_path = root / "lexical-head.json"
    sense_path = root / "sense-semdom.json"
    if not head_path.is_file() or not sense_path.is_file():
        raise ValidationError(f"Build semantic indexes for {language} before export")
    return (
        json.loads(head_path.read_text(encoding="utf-8")),
        json.loads(sense_path.read_text(encoding="utf-8")),
    )


def _validate_generated_lift(path: Path, *, expected_entries: int, expected_senses: int) -> dict[str, Any]:
    """Parse one generated LIFT file locally and verify expected entry/sense counts."""
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        raise ValidationError(f"Generated LIFT failed local validation: {path}: {exc}") from exc
    root = tree.getroot()
    entries = [node for node in list(root) if node.tag.rsplit("}", 1)[-1] == "entry"]
    senses = [
        child
        for entry in entries
        for child in list(entry)
        if child.tag.rsplit("}", 1)[-1] == "sense"
    ]
    if len(entries) != expected_entries or len(senses) != expected_senses:
        raise ValidationError(
            f"Generated LIFT count mismatch: expected {expected_entries}/{expected_senses}, "
            f"received {len(entries)}/{len(senses)} entries/senses"
        )
    return {"status": "PASS", "entry_count": len(entries), "sense_count": len(senses)}


def export_lift(
    config: EcosystemConfig,
    *,
    language: str,
    profile: str,
    view: str,
    output: Path | None = None,
) -> dict[str, Any]:
    """Export one generated LIFT view without mutating any imported FLEx/Combine file."""
    normalized_profile = str(profile).strip().lower()
    if normalized_profile not in {"flex", "combine"}:
        raise ValidationError("LIFT export profile must be flex or combine")
    normalized_view = str(view).strip().casefold()
    included_statuses = set(export_statuses(normalized_view))
    require_current_index(config, language, purpose=f"{normalized_profile} LIFT export")
    head_doc, sense_doc = _load_indexes(config, language)
    senses = dict(sense_doc.get("senses", {}))
    status_counts: dict[str, int] = {}
    for source in senses.values():
        if isinstance(source, dict):
            status = str(source.get("status", "OBSERVED")).strip().upper() or "OBSERVED"
            status_counts[status] = status_counts.get(status, 0) + 1
    root = ET.Element("lift", {"version": "0.13", "producer": f"SAGE {normalized_profile} export"})
    exported_entries = 0
    exported_senses = 0
    exported_status_counts: dict[str, int] = {}
    for key, lexical_head in sorted(head_doc.get("heads", {}).items()):
        form = str(lexical_head.get("headword", "")).strip()
        if not form:
            continue
        sense_ids = [str(v) for v in lexical_head.get("sense_ids", [])]
        eligible: list[tuple[str, dict[str, Any]]] = []
        for sense_id in sense_ids:
            source = senses.get(sense_id)
            if not isinstance(source, dict):
                continue
            status = str(source.get("status", "OBSERVED")).strip().upper() or "OBSERVED"
            if status not in included_statuses:
                continue
            eligible.append((sense_id, source))
        if not eligible:
            continue
        entry_id = sha256_bytes(f"{language}\x1f{key}".encode("utf-8"))[:32]
        entry = ET.SubElement(root, "entry", {"id": entry_id})
        _text_form(entry, "lexical-unit", language, form)
        for sense_id, source in eligible:
            sense = ET.SubElement(entry, "sense", {"id": sense_id})
            for analysis_language, gloss in sorted((source.get("glosses") or {}).items()):
                if str(gloss).strip():
                    _text_form(sense, "gloss", str(analysis_language), str(gloss))
            if normalized_profile == "flex":
                for analysis_language, definition in sorted((source.get("definitions") or {}).items()):
                    if str(definition).strip():
                        _text_form(sense, "definition", str(analysis_language), str(definition))
                pos = str(source.get("part_of_speech") or "").strip()
                if pos:
                    ET.SubElement(sense, "grammatical-info", {"value": pos})
            for domain in source.get("semdom", []) or []:
                if not isinstance(domain, dict):
                    continue
                code = str(domain.get("code", "")).strip()
                label = str(domain.get("label", "")).strip()
                if not code:
                    continue
                value = f"{code} {label}".strip()
                ET.SubElement(sense, "trait", {"name": "semantic-domain-ddp4", "value": value})
            status = str(source.get("status", "OBSERVED")).strip().upper() or "OBSERVED"
            if normalized_profile == "flex":
                note = ET.SubElement(sense, "note", {"type": "SAGE-status"})
                form_node = ET.SubElement(note, "form", {"lang": "en"})
                ET.SubElement(form_node, "text").text = status
            exported_status_counts[status] = exported_status_counts.get(status, 0) + 1
            exported_senses += 1
        exported_entries += 1
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode", xml_declaration=False)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n"
    if output is None:
        destination_root = export_root(config, language) / normalized_profile
        destination_root.mkdir(parents=True, exist_ok=True)
        output = destination_root / f"{safe_id(language, 'language')}-{normalized_view}.lift"
    else:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, xml)
    validation = _validate_generated_lift(
        output, expected_entries=exported_entries, expected_senses=exported_senses
    )
    manifest = {
        "schema_version": "1.0",
        "language": language,
        "profile": "FLEx" if normalized_profile == "flex" else "Combine",
        "view": normalized_view,
        "included_statuses": sorted(included_statuses),
        "output": str(output),
        "sha256": sha256_file(output),
        "entry_count": exported_entries,
        "sense_count": exported_senses,
        "source_status_counts": dict(sorted(status_counts.items())),
        "exported_status_counts": dict(sorted(exported_status_counts.items())),
        "validation": validation,
        "source_index_root": str(index_root(config, language)),
        "rules": [
            "Generated export only; imported LIFT snapshots are never modified in place.",
            "SEMDOM is classification metadata, not translation authority.",
            (
                "FLEx profile retains the supported richer lexical fields defined by the SAGE exchange profile."
                if normalized_profile == "flex"
                else "Combine profile intentionally omits richer FLEx-only fields."
            ),
            "Export scope is explicit; no production export silently includes every evidence state.",
        ],
    }
    atomic_write_json(output.with_suffix(output.suffix + ".manifest.json"), manifest)
    return manifest
