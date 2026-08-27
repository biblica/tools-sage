"""Enforce canonical target-text action vocabulary on generated SAGE surfaces."""

from __future__ import annotations

import re
from typing import Iterable

from .errors import ValidationError

CANONICAL_TARGET_TEXT_OPERATION = "rewrite"
PROHIBITED_TARGET_TEXT_VERBS = (
    "translate",
    "translated",
    "translates",
    "translating",
)
_PROHIBITED_TARGET_TEXT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(item) for item in PROHIBITED_TARGET_TEXT_VERBS) + r")\b",
    re.IGNORECASE,
)


def prohibited_target_text_verbs(text: str) -> tuple[str, ...]:
    """Return unique prohibited target-text verb forms found in one emitted surface."""
    return tuple(dict.fromkeys(match.group(0) for match in _PROHIBITED_TARGET_TEXT_RE.finditer(text)))


def require_canonical_target_text_vocabulary(text: str, *, surface: str) -> None:
    """Reject generated text that uses a prohibited target-text action verb."""
    matches = prohibited_target_text_verbs(text)
    if matches:
        rendered = ", ".join(repr(item) for item in matches)
        raise ValidationError(
            f"{surface} uses prohibited target-text action vocabulary: {rendered}; "
            f"use {CANONICAL_TARGET_TEXT_OPERATION!r}",
            code="PROHIBITED_TARGET_TEXT_VOCABULARY",
        )


def require_canonical_operation_set(operations: Iterable[str]) -> None:
    """Require REWRITE to be the sole canonical BIC target-text production operation."""
    values = {str(item).strip().lower() for item in operations}
    if CANONICAL_TARGET_TEXT_OPERATION not in values:
        raise ValidationError(
            "BIC operation set omits the canonical REWRITE operation",
            code="BIC_REWRITE_OPERATION_MISSING",
        )
    prohibited = values.intersection(PROHIBITED_TARGET_TEXT_VERBS)
    if prohibited:
        raise ValidationError(
            "BIC operation set exposes prohibited target-text operation aliases: "
            + ", ".join(sorted(prohibited)),
            code="PROHIBITED_TARGET_TEXT_OPERATION",
        )
