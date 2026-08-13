"""SIL Semantic Domains normalisation and RapidWords specific-first partitions."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from ..errors import ValidationError

_SEMDOM = re.compile(r"^(?P<code>\d+(?:\.\d+)*)\s*(?P<label>.*)$")


def split_semdom(value: object) -> tuple[str, str]:
    """Split a Semantic Domain value into its stable numeric code and display label."""
    text = str(value or "").strip()
    match = _SEMDOM.fullmatch(text)
    if not match:
        raise ValidationError(f"Invalid SIL Semantic Domain value: {text!r}")
    return match.group("code"), match.group("label").strip()


def normalise_authority_json(path: Path) -> list[dict[str, Any]]:
    """Validate the current SIL semdom.org JSON shape without making it project authority."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid SIL Semantic Domains JSON {path}: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValidationError("SIL Semantic Domains JSON must contain a non-empty list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Semantic Domains row {index} must be an object")
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        guid = str(item.get("guid", "")).strip()
        if not _SEMDOM.fullmatch(code) or not name or not guid:
            raise ValidationError(f"Semantic Domains row {index} lacks valid code/name/guid")
        if code in seen:
            raise ValidationError(f"Duplicate SIL Semantic Domain code: {code}")
        seen.add(code)
        questions_raw = item.get("questions", []) or []
        questions: list[dict[str, str]] = []
        if not isinstance(questions_raw, list):
            raise ValidationError(f"Semantic Domains row {code} questions must be a list")
        for question in questions_raw:
            if not isinstance(question, dict):
                continue
            questions.append(
                {
                    "question": str(question.get("question", "")).strip(),
                    "example_words": str(question.get("exampleWords", "")).strip(),
                    "example_sentences": str(question.get("exampleSentences", "")).strip(),
                }
            )
        result.append(
            {
                "code": code,
                "name": name,
                "guid": guid,
                "description": str(item.get("description", "")).strip(),
                "parent_code": str(item.get("parentCode") or "").strip() or None,
                "child_codes": [str(v).strip() for v in item.get("childCodes", []) or [] if str(v).strip()],
                "related_guids": [str(v).strip() for v in item.get("relatedGuids", []) or [] if str(v).strip()],
                "louw_nida_codes": str(item.get("louwNidaCodes", "")).strip(),
                "ocm_codes": str(item.get("ocmCodes", "")).strip(),
                "questions": questions,
            }
        )
    return result


def _docx_paragraph_texts(path: Path) -> Iterable[str]:
    """Yield paragraph text from a DOCX using only the standard library."""
    try:
        with zipfile.ZipFile(path) as archive:
            payload = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ValidationError(f"Invalid RapidWords DOCX {path}: {exc}") from exc
    root = ET.fromstring(payload)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in root.findall(".//w:p", namespace):
        parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        yield "".join(parts).strip()


def normalise_specific_first_docx(path: Path) -> list[dict[str, Any]]:
    """Parse the RapidWords dotted-line folder divisions into processing metadata."""
    folders: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for text in _docx_paragraph_texts(path):
        if not text:
            continue
        if len(text) >= 10 and set(text) == {"-"}:
            if current:
                folders.append({"folder": len(folders) + 1, "domains": current})
                current = []
            continue
        match = _SEMDOM.fullmatch(text.replace("\t", " ").strip())
        if match:
            current.append(
                {
                    "code": match.group("code"),
                    "label": match.group("label").strip(),
                    "specificity_order": len(current) + 1,
                }
            )
    if current:
        folders.append({"folder": len(folders) + 1, "domains": current})
    if len(folders) < 100:
        raise ValidationError(
            f"RapidWords specific-first file produced only {len(folders)} folders; expected a complete folder map"
        )
    codes = [item["code"] for folder in folders for item in folder["domains"]]
    if len(codes) != len(set(codes)):
        raise ValidationError("RapidWords specific-first folder map contains duplicate Semantic Domain codes")
    return folders
