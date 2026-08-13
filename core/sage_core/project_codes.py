"""Deterministic Paratext/PTLite short-name parsing for SAGE RC7."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

# Paratext project short names are historically limited to 8 characters. The governed
# SAGE convention uses case and position to separate the fields:
#   <lowercase language code><UPPERCASE project abbreviation><lowercase type><iteration digit>
# Common 8-character layouts are xxxYYYz0 and xxYYYYz0. Shorter conforming codes such as
# idKKHv0 and usNIVv2 are valid as long as the total length remains <= 8 characters.
_PROJECT_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,7}$")
_STRUCTURED_RE = re.compile(
    r"^(?P<language>[a-z]{2,3})(?P<abbreviation>[A-Z]{1,4})(?P<type>[a-z])(?P<iteration>[0-9])$"
)

DEFAULT_TYPE_CODES = {
    "v": "TRANSLATION",
    "x": "BACKTRANSLATION",
}


@dataclass(frozen=True)
class ProjectCodeParts:
    """Structural metadata parsed from one Paratext/PTLite project short name."""

    project_code: str
    paratext_language_code: str | None
    abbreviation: str | None
    type_code: str | None
    type_name: str | None
    iteration: int | None
    parse_status: str
    review_required: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return stable serialisable structural metadata for Project Inventory persistence."""
        return {
            "project_code": self.project_code,
            "paratext_language_code": self.paratext_language_code,
            "abbreviation": self.abbreviation,
            "type_code": self.type_code,
            "type_name": self.type_name,
            "iteration": self.iteration,
            "parse_status": self.parse_status,
            "review_required": self.review_required,
            "notes": list(self.notes),
        }


def parse_project_code(
    project_code: str,
    *,
    type_codes: Mapping[str, str] | None = None,
) -> ProjectCodeParts:
    """Parse the governed Paratext short-name convention without role inference.

    The field boundary is derived only from the lowercase/uppercase/lowercase/digit pattern;
    no language registry is required to split the code. The leading lowercase component is
    the Paratext language code (usually ISO-639-3, while established two-character
    language codes remain accepted). Unknown type codes remain registrable but require
    operator review. Scripture scope and workflow role are never inferred from this name.
    """
    code = str(project_code).strip()
    if not _PROJECT_CODE_RE.fullmatch(code):
        return ProjectCodeParts(
            project_code=code,
            paratext_language_code=None,
            abbreviation=None,
            type_code=None,
            type_name=None,
            iteration=None,
            parse_status="INVALID",
            review_required=True,
            notes=("Project code must be 1-8 cross-platform-safe Paratext short-name characters.",),
        )

    match = _STRUCTURED_RE.fullmatch(code)
    if not match:
        return ProjectCodeParts(
            project_code=code,
            paratext_language_code=None,
            abbreviation=None,
            type_code=None,
            type_name=None,
            iteration=None,
            parse_status="UNPARSED",
            review_required=True,
            notes=(
                "Code does not match <lowercase-language><UPPERCASE-abbreviation><lowercase-type><digit>; "
                "project remains registrable without structural inference.",
            ),
        )

    language = match.group("language")
    abbreviation = match.group("abbreviation")
    type_code = match.group("type")
    iteration = int(match.group("iteration"))
    type_map = {
        str(key).casefold(): str(value).strip().upper()
        for key, value in (type_codes or DEFAULT_TYPE_CODES).items()
    }
    type_name = type_map.get(type_code.casefold())

    notes: list[str] = []
    review_required = False
    if type_name is None:
        notes.append(f"Type code {type_code!r} is undefined.")
        review_required = True

    return ProjectCodeParts(
        project_code=code,
        paratext_language_code=language,
        abbreviation=abbreviation,
        type_code=type_code,
        type_name=type_name,
        iteration=iteration,
        parse_status="PARSED" if not review_required else "PARTIAL",
        review_required=review_required,
        notes=tuple(notes),
    )
